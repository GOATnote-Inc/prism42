"""
DOM discovery — dumps the relevant Runway UI regions so we can write proper
selectors for runway_automation.py.

Run after --login. Output: dom-dump.json with accessibility-tree snapshots and
per-region element inventories.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, Page

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = Path.home() / ".runway-automation-profile"
OUTPUT = ROOT / "dom-dump.json"
RUNWAY_BASE = "https://app.runwayml.com"


async def inventory_region(page: Page, region_label: str, locator_str: str) -> list[dict]:
    """Walk a region and return descriptive metadata for every interactive element."""
    elements = page.locator(f"{locator_str} button, {locator_str} a, {locator_str} input, {locator_str} textarea, {locator_str} [contenteditable], {locator_str} [role='button'], {locator_str} [role='link'], {locator_str} [role='textbox'], {locator_str} [role='combobox']")
    count = await elements.count()
    out = []
    for i in range(min(count, 60)):
        el = elements.nth(i)
        try:
            visible = await el.is_visible(timeout=500)
        except Exception:
            visible = False
        if not visible:
            continue
        try:
            tag = await el.evaluate("e => e.tagName.toLowerCase()")
            text = (await el.inner_text(timeout=500))[:80] if await el.evaluate("e => e.innerText !== undefined") else ""
            attrs = await el.evaluate("""e => {
                const a = {};
                for (const at of e.attributes) a[at.name] = at.value;
                return a;
            }""")
            box = await el.bounding_box()
            out.append({
                "i": i,
                "tag": tag,
                "text": text.strip(),
                "role": attrs.get("role", ""),
                "aria_label": attrs.get("aria-label", ""),
                "placeholder": attrs.get("placeholder", ""),
                "data_testid": attrs.get("data-testid", ""),
                "class": attrs.get("class", "")[:120],
                "x": int(box["x"]) if box else None,
                "y": int(box["y"]) if box else None,
            })
        except Exception as e:
            out.append({"i": i, "error": str(e)[:80]})
    return out


async def main() -> None:
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1600, "height": 1000},
    )
    page = context.pages[0] if context.pages else await context.new_page()
    dump: dict = {}
    try:
        await page.goto(RUNWAY_BASE)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

        print("page url:", page.url)
        dump["url"] = page.url

        print("inventorying left sidebar...")
        dump["left_sidebar"] = await inventory_region(page, "left_sidebar", "nav, aside, [class*='sidebar' i], [class*='nav' i]")

        print("inventorying full page (interactive top 60)...")
        dump["page_top60"] = await inventory_region(page, "page", "body")

        # Click Scene Builder if present
        try:
            await page.locator("text=Scene Builder").first.click(timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            print("on Scene Builder page:", page.url)
            dump["scene_builder_url"] = page.url
            dump["scene_builder_top60"] = await inventory_region(page, "scene_builder", "body")
        except Exception as e:
            print("could not open Scene Builder:", e)
            dump["scene_builder_error"] = str(e)[:200]

        # Back to Apps and try Multi-Shot Video
        try:
            await page.locator('button[aria-label="Apps"]').first.click(timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            await page.locator("text=Multi-Shot Video").first.click(timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            print("on Multi-Shot Video page:", page.url)
            dump["multi_shot_url"] = page.url
            dump["multi_shot_top60"] = await inventory_region(page, "multi_shot", "body")
        except Exception as e:
            print("could not open Multi-Shot Video:", e)
            dump["multi_shot_error"] = str(e)[:200]

        # Image-to-Video — under Apps → Video tab → Image to Video
        try:
            await page.locator('button[aria-label="Apps"]').first.click(timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            await page.locator("text=/^Video$/").first.click(timeout=5000)
            await asyncio.sleep(2)
            await page.locator("text=Image to Video").first.click(timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            print("on Image-to-Video page:", page.url)
            dump["i2v_url"] = page.url
            dump["i2v_top60"] = await inventory_region(page, "i2v", "body")
        except Exception as e:
            print("could not open Image-to-Video:", e)
            dump["i2v_error"] = str(e)[:200]

    finally:
        OUTPUT.write_text(json.dumps(dump, indent=2, default=str))
        print(f"wrote {OUTPUT}")
        await context.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
