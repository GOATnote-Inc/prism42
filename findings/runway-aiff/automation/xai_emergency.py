"""xAI Imagine — emergency-services B-roll for v2 master.

Generates 9 documentary-register shots: 911 dispatch, EMT, ambulance, police,
fire, dispatcher, dawn closer. No characters, no in-frame text, simple camera
moves, photoreal documentary lighting.
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
RESULTS_FILE = ROOT / "xai-emergency-results.json"
LEDGER = ROOT / "spend-log.csv"
HARD_HALT_USD = 300.0

CLIPS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Shot:
    id: str
    prompt: str
    duration: int = 6
    resolution: str = "720p"


# Emergency-services documentary B-roll. No faces, no text, no real-agency markings.
# Generic "EMS" / "FIRE" / "POLICE" without city specifics.
SHOTS = [
    Shot("C01",
         "Wide establishing shot of a 911 dispatch operations floor at night, multiple "
         "operator consoles in rows with deep blue and cyan monitor glow, soft overhead "
         "task lighting, faint motion of operators in headsets seen from behind, "
         "documentary cinematic, 35mm anamorphic, deep focus, muted color palette, "
         "real broadcast-news b-roll energy, no on-screen text, no agency markings"),
    Shot("C02",
         "Close-up of a single dispatcher headset resting on a desk console next to a "
         "lit monitor, anonymous hands entering the frame to pick up the headset, shallow "
         "depth of field, warm desk lamp light against cool monitor blue, slow push-in, "
         "documentary cinematic, no readable text on the screens, no faces visible"),
    Shot("C03",
         "Ambulance speeding through a dark wet city street at night seen from a low "
         "tracking angle, generic white-and-orange livery with faint EMS striping, light "
         "bar strobing red and blue reflecting off rain-slicked asphalt, motion blur on "
         "background buildings, photoreal cinematic documentary, 24fps, no readable "
         "agency name, no city signage"),
    Shot("C04",
         "Inside the back of a moving ambulance, an EMT's gloved hands prepping medical "
         "equipment on a tray, fast confident motion, neon-green and white interior "
         "lighting, slight handheld camera bob, no face visible, photoreal documentary, "
         "shallow depth of field, no on-screen text",
         duration=5),
    Shot("C05",
         "Police patrol car parked at a generic urban scene at night, blue and red light "
         "bar strobing across wet asphalt and brick walls, no officers visible, no city "
         "or agency name on the vehicle, slow dolly-in from across the street, "
         "documentary cinematic, photoreal, atmospheric haze, 35mm lens",
         duration=5),
    Shot("C06",
         "Fire engine at a generic emergency scene at night, dramatic backlight from "
         "behind the truck, water spray catching the strobe of the light bar, faint "
         "smoke drifting through the frame, no firefighters visible up close, no agency "
         "markings, documentary cinematic, slow tilt-up, 50mm lens",
         duration=5),
    Shot("C07",
         "Medium shot of a 911 dispatcher seated at a console speaking calmly into a "
         "headset, seen from behind and slightly to the side so the face is not visible, "
         "monitor screens in front of them showing abstract waveforms and timer-style "
         "interfaces, warm task light from above, documentary cinematic, slight handheld "
         "bob, no readable text on the screens",
         duration=8),
    Shot("C08",
         "Wide aerial city skyline at night, faint sirens implied through tiny moving "
         "blue and red points of light far below, low-hanging fog drifting across mid-"
         "rise rooftops, single lit window in foreground, contemplative documentary "
         "cinematic, slow lateral drift, photoreal, no text"),
    Shot("C09",
         "911 dispatch operations floor at dawn, soft warm sunrise light filtering "
         "through high windows, most consoles dark, one operator silhouetted at a "
         "single still-active console, quiet contemplative atmosphere, documentary "
         "cinematic, locked-off, photoreal, 35mm anamorphic, no on-screen text",
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
        for row in csv.DictReader(f):
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

    print(f"prior spend: ~${total_spend():.2f} | hard halt: ${HARD_HALT_USD:.2f}\n")

    results: list[dict] = []
    if RESULTS_FILE.exists():
        results = json.loads(RESULTS_FILE.read_text())
    done_ids = {r["id"] for r in results if r.get("status") == "downloaded"}

    t_total = time.time()
    for s in SHOTS:
        out = CLIPS_DIR / f"{s.id}.mp4"
        if s.id in done_ids and out.exists() and out.stat().st_size > 1024:
            print(f"[{s.id}] cached")
            continue
        if total_spend() + cost(s) > HARD_HALT_USD:
            print(f"[{s.id}] HALT cap")
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
                raise RuntimeError("no url on response")
            elapsed = time.time() - t0
            print(f"[{s.id}] gen={elapsed:.1f}s")
            with httpx.stream("GET", url, timeout=120.0) as r:
                r.raise_for_status()
                with out.open("wb") as f:
                    for chunk in r.iter_bytes(64 * 1024):
                        f.write(chunk)
            size_mb = out.stat().st_size / 1_000_000
            print(f"[{s.id}] -> {out.name} ({size_mb:.1f} MB)")
            append_ledger(s.id, "generate+download", cost(s), f"720p {s.duration}s emergency")
            results.append({"id": s.id, "status": "downloaded", "path": str(out),
                            "url": url, "size_mb": size_mb, "wall_s": elapsed})
        except Exception as e:
            err = str(e)[:300]
            print(f"[{s.id}] FAIL: {err}")
            results.append({"id": s.id, "status": "fail", "error": err})
        RESULTS_FILE.write_text(json.dumps(results, indent=2))

    ok = sum(1 for r in results if r.get("status") == "downloaded")
    print(f"\n=== summary === {ok}/{len(SHOTS)} | wall {time.time()-t_total:.0f}s | spend ${total_spend():.2f}")


if __name__ == "__main__":
    main()
