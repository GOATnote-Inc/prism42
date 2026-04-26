"""
Runway Gen-4.5 Phase 2 batch automation.

Drives app.runwayml.com via Playwright. Inherits an isolated browser profile so
auth state persists across runs. Reads shots from `../shot-list.json`, posts each
prompt, polls for completion, downloads the HD master to `../clips/<shot-id>.mp4`.

Three operating modes:

  python runway_automation.py --login
      One-time human login. Opens a visible browser; you sign in to Runway;
      press Enter in this terminal to save the session.

  python runway_automation.py --probe
      Opens each Runway tool (Scene Builder, Multi-Shot Video, Image-to-Video)
      and writes detected selectors to selectors.json. Run this whenever the
      Runway UI changes or the script reports "selector miss".

  python runway_automation.py --run [--shot S01] [--limit N] [--dry-run]
      Generation loop. Defaults to all non-Act-Two shots. --shot processes one
      ID for testing. --limit caps the run. --dry-run prints actions only.

Out of scope (do these manually or via Chrome's Claude):
  Phase 1 — character upload (needs OS file picker)
  Phase 3 — Act-Two close-ups (needs driving videos + per-shot judgment)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PWTimeout
except ImportError:
    sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SHOT_LIST_PATH = PROJECT_ROOT / "shot-list.json"
CLIPS_DIR = PROJECT_ROOT / "clips"
PROFILE_DIR = Path.home() / ".runway-automation-profile"
SELECTORS_PATH = ROOT / "selectors.json"
LOG_PATH = ROOT / "run.log"

RUNWAY_BASE = "https://app.runwayml.com"

# Tool URL/route hints (relative paths Runway uses). The probe step verifies these.
TOOL_ROUTES = {
    "Scene Builder": {"category": "Film or shorts", "card_text": "Scene Builder"},
    "Multi-Shot Video": {"category": "Film or shorts", "card_text": "Multi-Shot Video"},
    "Image-to-Video": {"category": None, "menu_path": ["Apps", "Video", "Image-to-Video"]},
    # Act-Two intentionally omitted — manual-only.
}

# Default selectors. These are starting heuristics; --probe may overwrite.
DEFAULT_SELECTORS: dict[str, dict[str, str]] = {
    "global": {
        "unlimited_badge": "text=Unlimited",
        "apps_nav": "role=link[name=Apps] >> nth=0",
        "recents_nav": "role=link[name=Recents] >> nth=0",
        "characters_nav": "role=link[name=Characters] >> nth=0",
    },
    "tool_picker": {
        "category_film": "text=Film or shorts",
        "card_scene_builder": "text=Scene Builder",
        "card_multi_shot": "text=Multi-Shot Video",
    },
    "generate_panel": {
        "prompt_textarea": "role=textbox[name=/prompt|describe/i]",
        "duration_5s": "role=button[name=/^5s$/]",
        "duration_10s": "role=button[name=/^10s$/]",
        "aspect_dropdown": "role=combobox[name=/aspect|ratio/i]",
        "aspect_16_9_option": "role=option[name=/16:9|1920/]",
        "model_dropdown": "role=combobox[name=/model/i]",
        "model_gen45": "role=option[name=/Gen-4.5/i]",
        "generate_button": "role=button[name=/^Generate$|generate/i]",
    },
    "task_status": {
        "progress_indicator": "role=progressbar",
        "completed_marker": "text=/completed|finished|done/i",
        "download_hd_button": "role=button[name=/download.*hd|download.*high/i]",
    },
}


@dataclass
class Shot:
    id: str
    segment: str
    tool: str
    duration_gen_s: int
    prompt: str
    notes: str
    raw: dict

    @classmethod
    def from_dict(cls, d: dict) -> "Shot":
        return cls(
            id=d["id"],
            segment=d.get("segment", ""),
            tool=d["tool"],
            duration_gen_s=int(d.get("duration_gen_s", 5)),
            prompt=d["prompt"],
            notes=d.get("notes", ""),
            raw=d,
        )


def setup_logging() -> logging.Logger:
    log = logging.getLogger("runway")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    return log


def load_selectors() -> dict[str, dict[str, str]]:
    if SELECTORS_PATH.exists():
        return json.loads(SELECTORS_PATH.read_text())
    return DEFAULT_SELECTORS


def save_selectors(selectors: dict[str, dict[str, str]]) -> None:
    SELECTORS_PATH.write_text(json.dumps(selectors, indent=2))


def load_shots(shot_id: str | None = None, limit: int | None = None) -> list[Shot]:
    raw = json.loads(SHOT_LIST_PATH.read_text())
    shots = [Shot.from_dict(s) for s in raw if s["tool"] != "Act-Two"]
    if shot_id:
        shots = [s for s in shots if s.id == shot_id]
        if not shots:
            sys.exit(f"shot {shot_id} not found or is Act-Two (manual)")
    if limit:
        shots = shots[:limit]
    return shots


async def open_context() -> tuple[Any, BrowserContext, Page]:
    pw = await async_playwright().start()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        accept_downloads=True,
        viewport={"width": 1600, "height": 1000},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return pw, context, page


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


async def mode_login(log: logging.Logger, max_wait_s: int = 600) -> None:
    """Open Runway and poll until the Unlimited badge appears (login complete)."""
    pw, context, page = await open_context()
    try:
        await page.goto(RUNWAY_BASE)
        log.info("browser open. log in to Runway in the visible window.")
        log.info(f"auto-detecting login via Unlimited badge (max {max_wait_s}s)...")
        deadline = asyncio.get_event_loop().time() + max_wait_s
        confirmed = False
        while asyncio.get_event_loop().time() < deadline:
            try:
                await page.locator("text=Unlimited").first.wait_for(state="visible", timeout=5000)
                confirmed = True
                break
            except PWTimeout:
                remaining = int(deadline - asyncio.get_event_loop().time())
                log.info(f"  ...still waiting ({remaining}s remaining)")
                continue
        if confirmed:
            log.info("Unlimited badge visible — login confirmed. session saved to profile dir.")
        else:
            log.warning("login timed out. session may not be saved; re-run --login.")
    finally:
        await context.close()
        await pw.stop()


async def mode_probe(log: logging.Logger) -> None:
    """Walk the Runway UI and capture selectors for the elements we need.

    Writes selectors.json. Logs anything it can't find so the user can fix
    selectors.json by hand before --run.
    """
    pw, context, page = await open_context()
    selectors = load_selectors()
    misses: list[str] = []

    async def check(category: str, key: str, selector: str, on_url: str | None = None) -> None:
        try:
            if on_url and not page.url.startswith(on_url):
                await page.goto(on_url)
                await page.wait_for_load_state("networkidle")
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=4000)
            log.info(f"  ok  {category}.{key}")
        except PWTimeout:
            log.warning(f"  miss {category}.{key} :: {selector}")
            misses.append(f"{category}.{key}")

    try:
        await page.goto(RUNWAY_BASE + "/")
        await page.wait_for_load_state("networkidle")

        log.info("probing global selectors...")
        for key, sel in selectors["global"].items():
            await check("global", key, sel)

        log.info("probing tool picker (Film or shorts)...")
        for key, sel in selectors["tool_picker"].items():
            await check("tool_picker", key, sel)

        # Open Scene Builder as the canonical generate panel
        log.info("opening Scene Builder to probe generate-panel selectors...")
        try:
            await page.locator(selectors["tool_picker"]["card_scene_builder"]).first.click(timeout=5000)
            await page.wait_for_load_state("networkidle")
            for key, sel in selectors["generate_panel"].items():
                await check("generate_panel", key, sel)
        except PWTimeout:
            log.warning("could not open Scene Builder — generate_panel selectors not probed.")
            misses.append("(scene builder unreachable)")

        save_selectors(selectors)
        if misses:
            log.warning(f"{len(misses)} selector misses. edit selectors.json by hand:")
            for m in misses:
                log.warning(f"   - {m}")
            log.warning("DOM hint: open Runway, right-click element → Inspect → copy ARIA role/name.")
        else:
            log.info("all selectors verified.")
    finally:
        await context.close()
        await pw.stop()


async def mode_run(log: logging.Logger, shots: list[Shot], dry_run: bool, no_generate: bool = False) -> None:
    """Process shots: navigate → paste prompt → set params → [generate → download]."""
    selectors = load_selectors()
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    if dry_run:
        log.info(f"DRY RUN — {len(shots)} shots")
        for s in shots:
            log.info(f"  {s.id} [{s.tool}] {s.duration_gen_s}s 16:9 :: {s.prompt[:80]}...")
        return

    pw, context, page = await open_context()
    results: list[dict] = []
    try:
        await page.goto(RUNWAY_BASE)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)

        for shot in shots:
            log.info(f"=== {shot.id} [{shot.tool}] {shot.duration_gen_s}s ===")
            try:
                await navigate_to_tool(page, shot.tool, selectors, log)
                await fill_prompt_and_params(page, shot, selectors, log)
                if no_generate:
                    log.info("  --no-generate: stopped before clicking Generate")
                    results.append({"id": shot.id, "status": "filled-no-gen"})
                    continue
                await click_generate(page, shot, selectors, log)
                output = CLIPS_DIR / f"{shot.id}.mp4"
                ok, info = await wait_and_download_v2(page, shot, output, log)
                results.append({"id": shot.id, "status": "ok" if ok else "fail",
                                "path": str(output) if ok else None, "info": info})
            except Exception as e:  # noqa: BLE001
                results.append({"id": shot.id, "status": "fail", "error": str(e)[:200]})
                log.error(f"  fail :: {e}")
    finally:
        (ROOT / "results.json").write_text(json.dumps(results, indent=2))
        log.info(f"results -> {ROOT / 'results.json'}")
        await context.close()
        await pw.stop()


# ---------------------------------------------------------------------------
# Per-shot building blocks
# ---------------------------------------------------------------------------


async def navigate_to_tool(page: Page, tool: str, selectors: dict, log: logging.Logger) -> None:
    """Click into the named tool from the Apps starter-kit page."""
    g = selectors["global"]
    tp = selectors["tool_picker"]
    # Land on Apps page
    await page.locator(g["apps_nav"]).first.click(timeout=5000)
    await page.wait_for_load_state("domcontentloaded", timeout=15000)
    await page.wait_for_timeout(800)

    if tool == "Multi-Shot Video":
        await page.locator(tp["card_multi_shot"]).first.click(timeout=5000)
    elif tool == "Scene Builder":
        await page.locator(tp["card_scene_builder"]).first.click(timeout=5000)
    elif tool == "Image-to-Video":
        # Different navigation; punted to manual for now
        raise NotImplementedError("Image-to-Video automation not implemented; do S25 by hand")
    else:
        raise ValueError(f"unknown tool {tool!r}")

    await page.wait_for_load_state("domcontentloaded", timeout=15000)
    await page.wait_for_timeout(1500)
    log.info(f"  navigated to {tool} ({page.url})")


async def select_dropdown_option(page: Page, button_selector: str, option_text: str, log: logging.Logger) -> bool:
    """Click a control button to open its menu, then click the option matching text.

    Tries several common menu patterns since Runway's popovers don't use one
    standard role. Returns True if applied."""
    try:
        await page.locator(button_selector).first.click(timeout=3000)
        await page.wait_for_timeout(500)
    except PWTimeout:
        log.warning(f"  could not click {button_selector}")
        return False

    candidates = [
        f"[role='menuitemradio']:has-text('{option_text}')",
        f"[role='menuitem']:has-text('{option_text}')",
        f"[role='option']:has-text('{option_text}')",
        f"[role='radio']:has-text('{option_text}')",
        f"[role='menu'] button:has-text('{option_text}')",
        f"[role='dialog'] button:has-text('{option_text}')",
        f"[role='listbox'] *:has-text('{option_text}')",
        f"div[class*='popover' i] button:has-text('{option_text}')",
        f"div[class*='menu' i] button:has-text('{option_text}')",
        # Last resort: any visible button/element with the exact text
        f"button:has-text('{option_text}'):visible",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=600):
                await loc.click(timeout=1500)
                log.info(f"  matched option via: {sel}")
                return True
        except (PWTimeout, Exception):
            continue
    # Close menu
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    log.warning(f"  no candidate selector matched option={option_text!r}")
    return False


async def fill_prompt_and_params(page: Page, shot: Shot, selectors: dict, log: logging.Logger) -> None:
    """Tool-specific prompt + parameter fill."""
    if shot.tool == "Multi-Shot Video":
        await _fill_multishot(page, shot, selectors, log)
    elif shot.tool == "Scene Builder":
        await _fill_scene_builder(page, shot, selectors, log)
    else:
        raise NotImplementedError(f"fill not implemented for tool={shot.tool}")


async def _fill_multishot(page: Page, shot: Shot, selectors: dict, log: logging.Logger) -> None:
    ms = selectors["multi_shot"]
    box = page.locator(ms["prompt_textarea"]).first
    await box.wait_for(state="visible", timeout=10000)
    await box.click()
    await page.keyboard.press("Meta+A")
    await page.keyboard.press("Delete")
    # press_sequentially fires real keydown/input events so React sees a "user typed" change
    # and enables Generate. fill() only sets value and doesn't always trigger onChange listeners.
    await box.press_sequentially(shot.prompt, delay=2)
    log.info(f"  prompt typed ({len(shot.prompt)} chars via key events)")

    # Duration
    target_dur = "10s" if shot.duration_gen_s >= 10 else "5s"
    cur_dur = (await page.locator(ms["duration_button"]).first.inner_text(timeout=2000)).strip()
    if target_dur not in cur_dur:
        if await select_dropdown_option(page, ms["duration_button"], target_dur, log):
            log.info(f"  duration set to {target_dur}")
    else:
        log.info(f"  duration already {target_dur}")

    # Aspect 16:9 — verify
    cur_aspect = (await page.locator(ms["aspect_button"]).first.inner_text(timeout=2000)).strip()
    if "16:9" not in cur_aspect:
        if await select_dropdown_option(page, ms["aspect_button"], "16:9", log):
            log.info("  aspect set to 16:9")
    else:
        log.info(f"  aspect already 16:9")


async def _fill_scene_builder(page: Page, shot: Shot, selectors: dict, log: logging.Logger) -> None:
    sb = selectors["scene_builder"]
    # Make sure we're on Step 1: Frame your scene
    try:
        await page.locator(sb["step_frame"]).first.click(timeout=3000)
        await page.wait_for_timeout(500)
    except PWTimeout:
        log.info("  Frame step button not found (might already be there)")

    box = page.locator(sb["prompt_textarea"]).first
    await box.wait_for(state="visible", timeout=10000)
    await box.fill("")
    await box.fill(shot.prompt)
    log.info(f"  prompt pasted ({len(shot.prompt)} chars)")

    # Aspect
    cur_aspect = (await page.locator(sb["aspect_button"]).first.inner_text(timeout=2000)).strip()
    if "16:9" not in cur_aspect:
        await select_dropdown_option(page, sb["aspect_button"], "16:9", log)
    log.info(f"  aspect: {cur_aspect}")
    log.warning("  Scene Builder is 2-step (Frame + Animate). This pass only frames; "
                "animate-step automation needs further DOM probing.")


async def click_generate(page: Page, shot: Shot, selectors: dict, log: logging.Logger) -> None:
    if shot.tool == "Multi-Shot Video":
        sel = selectors["multi_shot"]["generate_button"]
    elif shot.tool == "Scene Builder":
        sel = selectors["scene_builder"]["generate_frame_button"]
    else:
        raise NotImplementedError(f"generate not wired for {shot.tool}")
    btn = page.locator(sel).first
    await btn.wait_for(state="visible", timeout=5000)
    # Wait for enabled — React may still be validating after the prompt event flush
    for attempt in range(10):
        if await btn.is_enabled(timeout=500):
            break
        log.info(f"  Generate disabled, waiting... ({attempt+1}/10)")
        await page.wait_for_timeout(500)
    else:
        raise RuntimeError("Generate button never enabled — form likely incomplete")
    await btn.click()
    log.info("  generate clicked (button was enabled)")


async def wait_and_download(
    page: Page, output: Path, selectors: dict, log: logging.Logger, timeout_s: int = 600
) -> None:
    """Legacy stub kept to avoid import breakage; use wait_and_download_v2."""
    raise NotImplementedError("use wait_and_download_v2")


PLACEHOLDER_SRC_PATTERNS = (
    "/empty-state/",
    "/app/empty-state/",
    "d3phaj0sisr2ct.cloudfront.net/app/empty-state",
    "/example/", "/examples/", "/demo/",
)


def _is_placeholder_src(src: str) -> bool:
    return any(p in src for p in PLACEHOLDER_SRC_PATTERNS)


async def _collect_real_video_srcs(page: Page) -> set[str]:
    out: set[str] = set()
    try:
        videos = page.locator("video[src]")
        n = await videos.count()
        for i in range(n):
            try:
                v = videos.nth(i)
                src = await v.get_attribute("src")
                if src and (src.startswith("blob:") or src.startswith("http")):
                    if not _is_placeholder_src(src):
                        out.add(src)
            except Exception:
                continue
    except Exception:
        pass
    return out


async def wait_and_download_v2(
    page: Page, shot: Shot, output: Path, log: logging.Logger, timeout_s: int = 900
) -> tuple[bool, str]:
    """Wait for a NEW non-placeholder result video, then download.

    Snapshots video srcs immediately after click_generate (the "before set").
    Polls until a new src appears that isn't in the before set. Dumps DOM
    every 90s for diagnosis.
    """
    before = await _collect_real_video_srcs(page)
    log.info(f"  baseline real videos before generate: {len(before)}")

    deadline = asyncio.get_event_loop().time() + timeout_s
    last_dump = 0.0
    dump_dir = ROOT / "dom-dumps"
    dump_dir.mkdir(exist_ok=True)
    start = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() < deadline:
        current = await _collect_real_video_srcs(page)
        new = current - before
        if new:
            new_src = next(iter(new))
            log.info(f"  result video appeared (src={new_src[:80]}...)")
            # Locate the actual element by src
            v = page.locator(f"video[src='{new_src}']").first
            try:
                await v.wait_for(state="visible", timeout=3000)
            except PWTimeout:
                pass
            return await try_download_near_video(page, v, output, log)

        elapsed = asyncio.get_event_loop().time() - start
        if elapsed - last_dump > 90:
            last_dump = elapsed
            html_snapshot = (dump_dir / f"{shot.id}-t{int(elapsed)}s.html")
            try:
                content = await page.content()
                html_snapshot.write_text(content[:200000])
                log.info(f"  ... still generating ({int(elapsed)}s); snapshot -> {html_snapshot.name}")
            except Exception:
                log.info(f"  ... still generating ({int(elapsed)}s)")

        await asyncio.sleep(8)

    return False, f"timeout after {timeout_s}s without new video"


async def try_download_near_video(page: Page, video_locator, output: Path, log: logging.Logger) -> tuple[bool, str]:
    """Once a result video exists, find and click a download button."""
    # Hover the video to expose hover-only controls
    try:
        await video_locator.hover(timeout=2000)
        await page.wait_for_timeout(500)
    except Exception:
        pass

    candidates = [
        "button[aria-label*='Download' i]",
        "button:has-text('Download'):visible",
        "[role='menuitem']:has-text('Download'):visible",
        "a[href*='download' i]:visible",
        # Sometimes a meatball/menu button → click it then look for Download item
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=800):
                async with page.expect_download(timeout=60000) as dl_info:
                    await loc.click()
                download = await dl_info.value
                await download.save_as(str(output))
                log.info(f"  downloaded -> {output}")
                return True, "ok"
        except (PWTimeout, Exception) as e:
            continue

    # Fallback: open the kebab/more menu near the video
    try:
        more_btn = page.locator("button[aria-label*='more' i], button[aria-label*='options' i]").first
        if await more_btn.is_visible(timeout=1000):
            await more_btn.click()
            await page.wait_for_timeout(400)
            dl_item = page.locator("[role='menuitem']:has-text('Download'), button:has-text('Download'):visible").first
            async with page.expect_download(timeout=60000) as dl_info:
                await dl_item.click()
            download = await dl_info.value
            await download.save_as(str(output))
            log.info(f"  downloaded via more-menu -> {output}")
            return True, "ok-via-menu"
    except (PWTimeout, Exception):
        pass

    return False, "video found but no download button matched"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--login", action="store_true", help="One-time interactive login")
    g.add_argument("--probe", action="store_true", help="Verify selectors against live UI")
    g.add_argument("--run", action="store_true", help="Execute shot batch")
    p.add_argument("--shot", help="Single shot id (e.g., S01)")
    p.add_argument("--limit", type=int, help="Max shots in --run")
    p.add_argument("--dry-run", action="store_true", help="--run without browser actions")
    p.add_argument("--no-generate", action="store_true", help="--run navigates + fills prompt + sets params, but does NOT click Generate (safe verify)")
    args = p.parse_args()

    log = setup_logging()

    if args.login:
        asyncio.run(mode_login(log))
    elif args.probe:
        asyncio.run(mode_probe(log))
    elif args.run:
        shots = load_shots(shot_id=args.shot, limit=args.limit)
        log.info(f"loaded {len(shots)} non-Act-Two shots")
        asyncio.run(mode_run(log, shots, args.dry_run, args.no_generate))


if __name__ == "__main__":
    main()
