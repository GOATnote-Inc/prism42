"""xAI Imagine Video smoke test — minimum-cost verification that the API key
grants video access AND the SDK pattern works end-to-end (submit → poll →
download)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SMOKE_OUT = PROJECT_ROOT / "clips" / "xai-smoke.mp4"
SMOKE_OUT.parent.mkdir(parents=True, exist_ok=True)

SMOKE_PROMPT = (
    "Locked-off macro shot of a single GPU silicon die, iridescent micro-circuits "
    "catching teal light, slow push-in, broadcast cinematic, shallow depth of field, "
    "no text, abstract scientific atmosphere"
)


def main() -> None:
    key = os.environ.get("X_AI_APIKEY")
    if not key:
        sys.exit("X_AI_APIKEY not in env (source .env first)")
    print(f"key prefix: {key[:6]}... len={len(key)}")

    from xai_sdk import Client
    client = Client(api_key=key)

    t0 = time.time()
    print(f"[{int(time.time()-t0)}s] submitting smoke gen — 480p, 5s, no audio overhead...")
    # Use generate() which blocks + polls internally
    resp = client.video.generate(
        prompt=SMOKE_PROMPT,
        model="grok-imagine-video",
        aspect_ratio="16:9",
        resolution="480p",
        duration=5,
    )
    print(f"[{int(time.time()-t0)}s] response received: {type(resp).__name__}")
    print(f"  attrs: {[a for a in dir(resp) if not a.startswith('_')][:20]}")

    # Find the video URL
    url = None
    for attr in ("url", "video_url", "download_url"):
        if hasattr(resp, attr):
            url = getattr(resp, attr)
            if url:
                print(f"  found url via .{attr}: {url[:100]}...")
                break
    if not url:
        # Try inspecting the proto
        print(f"  raw: {resp}")
        sys.exit("no video url found on response")

    # Download
    print(f"[{int(time.time()-t0)}s] downloading...")
    with httpx.stream("GET", url, timeout=120.0) as r:
        r.raise_for_status()
        with SMOKE_OUT.open("wb") as f:
            for chunk in r.iter_bytes(64 * 1024):
                f.write(chunk)
    size_mb = SMOKE_OUT.stat().st_size / 1_000_000
    print(f"[{int(time.time()-t0)}s] downloaded {size_mb:.2f} MB -> {SMOKE_OUT}")
    print("SMOKE OK")


if __name__ == "__main__":
    main()
