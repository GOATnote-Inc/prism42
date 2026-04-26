"""xAI Imagine Video batch — 5 B-roll shots for the AIFF teaser.

Sequential `generate()` (each ~20–60s wall-clock at 720p, smoke proved). Saves
to ../clips/B0X.mp4 and tracks spend in spend-log.csv.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CLIPS_DIR = PROJECT_ROOT / "clips"
RESULTS_FILE = ROOT / "xai-batch-results.json"
LEDGER = ROOT / "spend-log.csv"
HARD_HALT_USD = 300.0

CLIPS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Shot:
    id: str
    prompt: str
    duration: int = 6
    resolution: str = "720p"


SHOTS = [
    Shot("B01",
         "Macro push-in on a Blackwell-class GPU silicon die, iridescent micro-circuits "
         "catching teal and amber light, shallow depth of field, slow steady push-in, "
         "photoreal cinematic, broadcast lens, dark studio backdrop, no text, abstract science"),
    Shot("B02",
         "Slow tilt-up across a row of glowing dark server racks in a dim datacenter aisle, "
         "deep blue and amber LED indicators, faint condensation in the cool air, locked rack "
         "doors, photoreal cinematic, 35mm anamorphic, shallow depth, no text on screens"),
    Shot("B03",
         "Locked-off close-up of a whiteboard covered in scientific equations and arrows, "
         "abstract attention-mechanism mathematical notation, faint marker stickers in the "
         "corner, warm tungsten classroom lighting, soft focus on margins, slight camera bob, "
         "documentary-cinematic, no readable letters or numbers"),
    Shot("B04",
         "Locked-off shot of a saturated red gradient backdrop, subtle chromatic noise, "
         "broadcast studio quality, faint volumetric haze in the foreground, slow zoom-in, "
         "absolutely no text, no numbers, no graphics — clean plate ready for compositing",
         duration=5),
    Shot("B05",
         "Locked-off slow zoom over a dark studio backdrop with faint volumetric haze, "
         "subtle warm tungsten edge light from camera-left, broadcast end-card atmosphere, "
         "extremely simple composition, no text, no graphics, no logos",
         duration=5),
]


def cost(s: Shot) -> float:
    return (0.07 if s.resolution == "720p" else 0.05) * s.duration


def append_ledger(shot_id: str, action: str, amount: float, note: str = "") -> None:
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "shot_id", "action", "amount_usd", "note"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), shot_id, action, f"{amount:.4f}", note])


def total_spend() -> float:
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    with LEDGER.open() as f:
        rows = list(csv.DictReader(f))
        for row in rows:
            try:
                total += float(row["amount_usd"])
            except (KeyError, ValueError):
                pass
    return total


def main() -> None:
    key = os.environ.get("X_AI_APIKEY")
    if not key:
        sys.exit("X_AI_APIKEY not in env")

    from xai_sdk import Client
    client = Client(api_key=key)

    print(f"prior spend: ~${total_spend():.2f}")
    print(f"hard halt:   ${HARD_HALT_USD:.2f}\n")

    # Resume support — skip clips already on disk
    results: list[dict] = []
    if RESULTS_FILE.exists():
        results = json.loads(RESULTS_FILE.read_text())
    done_ids = {r["id"] for r in results if r.get("status") == "downloaded"}

    t_total = time.time()
    for s in SHOTS:
        out = CLIPS_DIR / f"{s.id}.mp4"
        if s.id in done_ids and out.exists() and out.stat().st_size > 1024:
            print(f"[{s.id}] cached -> {out.name}")
            continue
        if total_spend() + cost(s) > HARD_HALT_USD:
            print(f"[{s.id}] HALT: would cross ${HARD_HALT_USD} ledger cap")
            results.append({"id": s.id, "status": "halt-cap"})
            continue

        t0 = time.time()
        print(f"[{s.id}] submitting {s.duration}s {s.resolution} ~${cost(s):.2f}...")
        try:
            resp = client.video.generate(
                prompt=s.prompt,
                model="grok-imagine-video",
                aspect_ratio="16:9",
                resolution=s.resolution,
                duration=s.duration,
            )
            url = getattr(resp, "url", None)
            if not url:
                raise RuntimeError(f"no url on response: attrs={[a for a in dir(resp) if not a.startswith('_')]}")
            elapsed = time.time() - t0
            print(f"[{s.id}] gen={elapsed:.1f}s, url={url[:80]}...")

            with httpx.stream("GET", url, timeout=120.0) as r:
                r.raise_for_status()
                with out.open("wb") as f:
                    for chunk in r.iter_bytes(64 * 1024):
                        f.write(chunk)
            size_mb = out.stat().st_size / 1_000_000
            print(f"[{s.id}] downloaded {size_mb:.1f} MB -> {out.name}")
            append_ledger(s.id, "generate+download", cost(s), f"720p {s.duration}s")
            results.append({"id": s.id, "status": "downloaded", "path": str(out),
                            "url": url, "size_mb": size_mb, "wall_s": elapsed})
        except Exception as e:
            err = str(e)[:300]
            print(f"[{s.id}] FAIL: {err}")
            results.append({"id": s.id, "status": "fail", "error": err})

        RESULTS_FILE.write_text(json.dumps(results, indent=2))

    total_elapsed = time.time() - t_total
    ok = sum(1 for r in results if r.get("status") == "downloaded")
    print(f"\n=== summary ===")
    print(f"  downloaded: {ok}/{len(SHOTS)}")
    print(f"  total wall: {total_elapsed:.1f}s")
    print(f"  total spend so far: ~${total_spend():.2f}")
    print(f"  results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
