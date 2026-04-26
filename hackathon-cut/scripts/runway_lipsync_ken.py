"""runway_lipsync_ken.py — Step 3 + 4 of the Runway DROP-IN pipeline.

Registers Ken canon as a gwm1 avatar, then drives with bio-intro-mix.mp3
to produce a lip-synced Ken speaking the full bio VO. Polls + downloads.

Cost: ~$0.12. Wall: ~2 min.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
PIPELINE = PROJECT / "runway-pipeline"
PIPELINE.mkdir(parents=True, exist_ok=True)

URLS_FILE = PIPELINE / "asset_urls.json"
RESULT_FILE = PIPELINE / "ken_lipsync_result.json"
OUT_VIDEO = PIPELINE / "ken_lipsync.mp4"


def main() -> None:
    key = os.environ.get("RUNWAYML_API_SECRET")
    if not key:
        sys.exit("RUNWAYML_API_SECRET not in env")
    if not URLS_FILE.exists():
        sys.exit(f"missing {URLS_FILE}; run upload step first")
    urls = json.loads(URLS_FILE.read_text())
    ken_url = urls["ken_canon_png"]
    audio_url = urls["bio_intro_mix_mp3"]
    print(f"ken canon: {ken_url}")
    print(f"audio:     {audio_url}")

    from runwayml import RunwayML
    client = RunwayML(api_key=key)

    # Reuse a prior in-flight avatar if previous run left an id on disk
    AVATAR_FILE = PIPELINE / "ken_avatar_id.txt"
    avatar_id = None
    if AVATAR_FILE.exists():
        avatar_id = AVATAR_FILE.read_text().strip() or None
    if avatar_id:
        print(f"\n[3/4] reusing prior avatar.id = {avatar_id}")
    else:
        print("\n[3/4] avatars.create — registering ken-fox-canon...")
        ken_avatar = client.avatars.create(
            name=f"ken-fox-canon-{int(time.time())}",
            personality=(
                "Calm broadcast news anchor with documentary register. Sober delivery, "
                "Brokaw-cadence baritone, occasional dry humor on the down-beat. "
                "Anthropomorphic red fox; intelligent amber eyes; subtle eyebrow does the work."
            ),
            reference_image=ken_url,
            voice={"type": "runway-live-preset", "preset_id": "drew"},
            image_processing="optimize",
        )
        avatar_id = ken_avatar.id
        AVATAR_FILE.write_text(avatar_id + "\n")
        print(f"  avatar.id = {avatar_id}")

    # Wait for avatar status READY (image processing takes ~30-90s)
    print("  polling avatar status...")
    deadline_a = time.time() + 300  # 5 min max
    last_st = None
    while time.time() < deadline_a:
        a = client.avatars.retrieve(avatar_id)
        st = getattr(a, "status", None)
        if st != last_st:
            print(f"    status: {st}")
            last_st = st
        if st in ("READY", "ACTIVE", "active", "ready"):
            break
        if st in ("FAILED", "failed", "ERROR", "error"):
            sys.exit(f"avatar create failed: {st}")
        time.sleep(6)
    else:
        sys.exit("avatar never reached READY in 5 min")

    # Step 4 — drive with the bio-intro-mix audio
    print("\n[4/4] avatar_videos.create — gwm1_avatars audio-driven lip-sync...")
    task = client.avatar_videos.create(
        avatar={"type": "custom", "avatar_id": avatar_id},
        model="gwm1_avatars",
        speech={"type": "audio", "audio": audio_url},
    )
    task_id = getattr(task, "id", None) or getattr(task, "task_id", None)
    print(f"  task.id = {task_id}")

    # Poll
    deadline = time.time() + 600  # 10 min cap
    last_status = None
    while time.time() < deadline:
        t = client.tasks.retrieve(task_id)
        if t.status != last_status:
            print(f"  status: {t.status}")
            last_status = t.status
        if t.status == "SUCCEEDED":
            outs = getattr(t, "output", None) or []
            if outs:
                first = outs[0] if isinstance(outs[0], str) else getattr(outs[0], "url", None) or str(outs[0])
                print(f"  output URL: {first[:100]}...")
                # Download
                with httpx.stream("GET", first, timeout=120.0) as r:
                    r.raise_for_status()
                    with OUT_VIDEO.open("wb") as f:
                        for chunk in r.iter_bytes(64 * 1024):
                            f.write(chunk)
                print(f"  downloaded -> {OUT_VIDEO} ({OUT_VIDEO.stat().st_size//1024} KB)")
                RESULT_FILE.write_text(json.dumps({
                    "avatar_id": avatar_id,
                    "task_id": task_id,
                    "output_url": first,
                    "local_path": str(OUT_VIDEO),
                    "status": "ok",
                }, indent=2))
                return
            print("  succeeded but no output found")
            sys.exit(2)
        if t.status in ("FAILED", "CANCELLED"):
            print(f"  failure: {getattr(t, 'failure', '')}")
            RESULT_FILE.write_text(json.dumps({
                "avatar_id": avatar_id,
                "task_id": task_id,
                "status": t.status,
                "failure": str(getattr(t, "failure", "")),
            }, indent=2))
            sys.exit(2)
        time.sleep(8)
    sys.exit("timeout after 10 min")


if __name__ == "__main__":
    main()
