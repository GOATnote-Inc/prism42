"""runway_api_batch.py — Phase 2 batch via Runway Python SDK.

Submits all non-Act-Two shots from ../shot-list.json via the Runway API,
polls for completion, downloads results to ../clips/<shot_id>.mp4.

Auth: reads RUNWAYML_API_SECRET from ~/prism42/.env (or env var).

Character refs (optional): place PNGs at refs/ken.png and refs/fizzlepuff.png
to lock identity on the 8 Scene Builder shots. Without them, those shots fall
back to plain text-to-video (no character lock).

Modes:
  --dry-run                  enumerate planned API calls + cost estimate, no submission
  --shot S01                 process a single shot
  --limit N                  cap shots
  --resume                   skip shots that already have a downloaded clip
  --submit-only              submit, save tasks.json, exit before polling
  --poll-only                skip submit, poll tasks.json + download

Notes:
  - text_to_video (gen4.5) duration must be 4, 6, or 8s. 5s shots round to 6s, 10s to 8s.
  - image_to_video (gen4.5) duration is 5 or 10s; matches shot-list values exactly.
  - Cost (gen4.5): 12 cr/sec at $0.01/cr. 6s = $0.72; 10s = $1.20. text_to_image
    gen4_image: ~$0.05-0.08 each.
  - Skipped: Act-Two (manual), Image-to-Video shots in our list (S25 needs typeset still
    we don't have yet).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

try:
    from runwayml import RunwayML
except ImportError:
    sys.exit("runwayml SDK not installed. Run: pip install runwayml")

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SHOT_LIST = PROJECT_ROOT / "shot-list.json"
CLIPS_DIR = PROJECT_ROOT / "clips"
REFS_DIR = ROOT / "refs"
TASKS_FILE = ROOT / "tasks-api.json"
RESULTS_FILE = ROOT / "results-api.json"
ENV_FILE = Path("~/prism42/.env")

# Models
M_T2V = "gen4.5"
M_T2I = "gen4_image"
M_I2V = "gen4.5"
RATIO_16x9_VIDEO = "1920:1080"
RATIO_16x9_IMAGE = "1920:1080"

# Cost per second (credits) — gen4.5 video
GEN45_CR_PER_SEC = 12
CR_USD = 0.01


def setup_logging() -> logging.Logger:
    log = logging.getLogger("runway-api")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def load_env_secret() -> str | None:
    """Read RUNWAYML_API_SECRET from env or /prism42/.env."""
    if v := os.environ.get("RUNWAYML_API_SECRET"):
        return v
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(errors="ignore").splitlines():
        m = re.match(r"^\s*RUNWAYML_API_SECRET\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def load_ref_data_uri(name: str) -> str | None:
    """Look for refs/{name}.{png,jpg,jpeg,webp} and return a data URI."""
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = REFS_DIR / f"{name}.{ext}"
        if p.exists():
            mime = "image/png" if ext == "png" else f"image/{ext}"
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{b64}"
    return None


def t2v_duration(shot_dur: int) -> int:
    """Map shot duration to gen4.5 text_to_video allowed values (4, 6, 8)."""
    if shot_dur <= 4:
        return 4
    if shot_dur <= 6:
        return 6
    return 8


def i2v_duration(shot_dur: int) -> int:
    """Map shot duration to gen4.5 image_to_video allowed values (5, 10)."""
    return 5 if shot_dur < 8 else 10


@dataclass
class Plan:
    shot_id: str
    pipeline: str  # 't2v' | 't2i+i2v' | 'skip'
    text_prompt: str
    duration_video: int
    refs_needed: list[str]
    refs_present: bool
    cost_estimate_usd: float
    skip_reason: str = ""


def plan_for_shot(shot: dict, refs_uris: dict[str, str]) -> Plan:
    pid = shot["id"]
    tool = shot["tool"]
    prompt = shot.get("prompt", "")
    dur = int(shot.get("duration_gen_s", 5))

    refs_used: list[str] = []
    if "@ken" in prompt:
        refs_used.append("ken")
    if "@fizzlepuff" in prompt:
        refs_used.append("fizzlepuff")
    refs_have = all(r in refs_uris for r in refs_used)

    if tool == "Act-Two":
        return Plan(pid, "skip", prompt, 0, refs_used, refs_have, 0.0, "Act-Two manual")
    if tool == "Image-to-Video":
        return Plan(pid, "skip", prompt, 0, refs_used, refs_have, 0.0, "needs typeset still (S25)")

    if tool == "Multi-Shot Video":
        # text_to_video; no refs
        d = t2v_duration(dur)
        cost = d * GEN45_CR_PER_SEC * CR_USD
        return Plan(pid, "t2v", prompt, d, refs_used, True, cost)

    if tool == "Scene Builder":
        # text_to_image (with refs if available) → image_to_video
        if not refs_used:
            # No character mentions; just use t2v
            d = t2v_duration(dur)
            cost = d * GEN45_CR_PER_SEC * CR_USD
            return Plan(pid, "t2v", prompt, d, refs_used, True, cost, "(no @ refs in prompt)")
        if not refs_have:
            d = t2v_duration(dur)
            cost = d * GEN45_CR_PER_SEC * CR_USD
            missing = [r for r in refs_used if r not in refs_uris]
            return Plan(pid, "t2v", prompt, d, refs_used, False, cost,
                        f"missing refs {missing}; falling back to t2v (no character lock)")
        d = i2v_duration(dur)
        # ~$0.07 t2i + d * 12 cr * $0.01 i2v
        cost = 0.07 + d * GEN45_CR_PER_SEC * CR_USD
        return Plan(pid, "t2i+i2v", prompt, d, refs_used, True, cost)

    return Plan(pid, "skip", prompt, 0, refs_used, refs_have, 0.0, f"unknown tool {tool!r}")


def submit_t2v(client: RunwayML, plan: Plan, log: logging.Logger) -> str:
    resp = client.text_to_video.create(
        model=M_T2V,
        prompt_text=plan.text_prompt,
        ratio=RATIO_16x9_VIDEO,
        duration=plan.duration_video,
        audio=True,
    )
    log.info(f"  {plan.shot_id} t2v submitted task={resp.id} dur={plan.duration_video}s")
    return resp.id


def submit_t2i_then_i2v(client: RunwayML, plan: Plan, refs_uris: dict[str, str], log: logging.Logger) -> str:
    """Generate keyframe via t2i with refs, then i2v on it."""
    refs_payload = [{"uri": refs_uris[r], "tag": r} for r in plan.refs_needed]
    log.info(f"  {plan.shot_id} t2i submitting (refs={[r for r in plan.refs_needed]})")
    t2i = client.text_to_image.create(
        model=M_T2I,
        prompt_text=plan.text_prompt,
        ratio=RATIO_16x9_IMAGE,
        reference_images=refs_payload,
    )
    # Poll t2i to completion to get the image URL
    img_url = poll_for_output_url(client, t2i.id, log, label=f"{plan.shot_id} t2i")
    if not img_url:
        raise RuntimeError(f"{plan.shot_id} t2i did not produce an image URL")
    log.info(f"  {plan.shot_id} keyframe url={img_url[:80]}...")
    i2v = client.image_to_video.create(
        model=M_I2V,
        prompt_image=img_url,
        prompt_text=plan.text_prompt,
        ratio=RATIO_16x9_VIDEO,
        duration=plan.duration_video,
    )
    log.info(f"  {plan.shot_id} i2v submitted task={i2v.id} dur={plan.duration_video}s")
    return i2v.id


def poll_for_output_url(
    client: RunwayML, task_id: str, log: logging.Logger, label: str = "", timeout_s: int = 600
) -> str | None:
    """Poll a task until SUCCEEDED, return the first output URL."""
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        try:
            t = client.tasks.retrieve(task_id)
        except Exception as e:
            log.warning(f"  {label} retrieve failed: {e}")
            time.sleep(8)
            continue
        if t.status != last_status:
            log.info(f"  {label} status={t.status}")
            last_status = t.status
        if t.status == "SUCCEEDED":
            outs = t.output or []
            if outs:
                return outs[0] if isinstance(outs[0], str) else getattr(outs[0], "url", None) or str(outs[0])
            return None
        if t.status in ("FAILED", "CANCELLED"):
            log.error(f"  {label} failed: {getattr(t, 'failure', '')}")
            return None
        time.sleep(8)
    log.warning(f"  {label} timed out after {timeout_s}s")
    return None


def download_url_to(url: str, dest: Path, log: logging.Logger) -> bool:
    try:
        with httpx.stream("GET", url, timeout=120.0) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        size_mb = dest.stat().st_size / 1_000_000
        log.info(f"  downloaded -> {dest.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        log.error(f"  download failed for {dest.name}: {e}")
        return False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--shot", help="single shot id")
    p.add_argument("--limit", type=int, help="cap shots processed")
    p.add_argument("--dry-run", action="store_true", help="enumerate plans, no API calls")
    p.add_argument("--resume", action="store_true", help="skip shots that already have a clip on disk")
    p.add_argument("--submit-only", action="store_true", help="submit + save tasks.json, exit")
    p.add_argument("--poll-only", action="store_true", help="skip submit, poll tasks.json")
    args = p.parse_args()

    log = setup_logging()
    secret = load_env_secret()

    shots_all = json.loads(SHOT_LIST.read_text())
    shots = [s for s in shots_all if s["tool"] != "Act-Two"]
    if args.shot:
        shots = [s for s in shots if s["id"] == args.shot]
    if args.limit:
        shots = shots[: args.limit]

    refs_uris: dict[str, str] = {}
    for name in ("ken", "fizzlepuff"):
        if uri := load_ref_data_uri(name):
            refs_uris[name] = uri
            log.info(f"loaded ref: {name} ({len(uri)//1024} KB base64)")
        else:
            log.warning(f"ref missing: refs/{name}.png — Scene Builder shots referencing @{name} will fall back to t2v")

    plans = [plan_for_shot(s, refs_uris) for s in shots]

    log.info("plan:")
    total_cost = 0.0
    for pl in plans:
        marker = "·" if pl.pipeline != "skip" else "✗"
        note = pl.skip_reason or ""
        log.info(f"  {marker} {pl.shot_id} {pl.pipeline:8} dur={pl.duration_video}s "
                 f"cost~${pl.cost_estimate_usd:.2f} {note}")
        total_cost += pl.cost_estimate_usd
    log.info(f"estimated total cost: ~${total_cost:.2f} (gen4.5 + gen4_image, before retries)")

    if args.dry_run:
        log.info("--dry-run: stopping here.")
        return

    if not secret:
        sys.exit("RUNWAYML_API_SECRET not found in env or ~/prism42/.env. "
                 "Add it and retry.")

    client = RunwayML(api_key=secret)

    # Resume support: load previous tasks
    tasks: dict[str, dict] = {}
    if TASKS_FILE.exists():
        tasks = json.loads(TASKS_FILE.read_text())

    if not args.poll_only:
        for pl in plans:
            if pl.pipeline == "skip":
                continue
            if args.resume:
                clip = CLIPS_DIR / f"{pl.shot_id}.mp4"
                if clip.exists() and clip.stat().st_size > 1024:
                    log.info(f"  {pl.shot_id} already on disk; skipping")
                    continue
                if pl.shot_id in tasks and tasks[pl.shot_id].get("status") == "downloaded":
                    continue
            try:
                if pl.pipeline == "t2v":
                    tid = submit_t2v(client, pl, log)
                elif pl.pipeline == "t2i+i2v":
                    tid = submit_t2i_then_i2v(client, pl, refs_uris, log)
                else:
                    continue
                tasks[pl.shot_id] = {"task_id": tid, "pipeline": pl.pipeline,
                                     "duration_s": pl.duration_video, "status": "submitted"}
                TASKS_FILE.write_text(json.dumps(tasks, indent=2))
            except Exception as e:
                log.error(f"  {pl.shot_id} submit failed: {e}")
                tasks[pl.shot_id] = {"status": "submit-failed", "error": str(e)[:200]}
                TASKS_FILE.write_text(json.dumps(tasks, indent=2))

        if args.submit_only:
            log.info(f"--submit-only: {len(tasks)} tasks saved to {TASKS_FILE.name}. "
                     f"Run with --poll-only to download.")
            return

    # Poll + download
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for shot_id, info in tasks.items():
        tid = info.get("task_id")
        if not tid:
            results.append({"id": shot_id, "status": info.get("status", "unknown")})
            continue
        clip = CLIPS_DIR / f"{shot_id}.mp4"
        if clip.exists() and clip.stat().st_size > 1024 and info.get("status") == "downloaded":
            results.append({"id": shot_id, "status": "ok", "path": str(clip)})
            continue
        url = poll_for_output_url(client, tid, log, label=shot_id, timeout_s=900)
        if url:
            if download_url_to(url, clip, log):
                info["status"] = "downloaded"
                info["url"] = url
                results.append({"id": shot_id, "status": "ok", "path": str(clip)})
            else:
                info["status"] = "download-failed"
                results.append({"id": shot_id, "status": "fail", "error": "download"})
        else:
            info["status"] = "no-output"
            results.append({"id": shot_id, "status": "fail", "error": "no output url"})
        TASKS_FILE.write_text(json.dumps(tasks, indent=2))

    RESULTS_FILE.write_text(json.dumps(results, indent=2))
    ok = sum(1 for r in results if r["status"] == "ok")
    log.info(f"done. {ok}/{len(results)} clips downloaded. results -> {RESULTS_FILE.name}")


if __name__ == "__main__":
    main()
