"""Render the bio intro VO — Harrison Gale (Ken) + Charlie (Fizzlepuff yell).

Outputs three mp3 files in ../vo/:
  ken-bio-1.mp3       Ken V.O. segment 1 (~14s)
  fizz-assistant.mp3  Fizzlepuff yell (~1s)
  ken-bio-2.mp3       Ken V.O. segment 2 (~7s)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
VO_DIR = PROJECT / "vo"
VO_DIR.mkdir(parents=True, exist_ok=True)

HARRISON = "fCxG8OHm4STbIsWe4aT9"   # Ken — documentary baritone, fresh
CHARLIE = "IKne3meq5aSn9XLyUdCD"     # Fizzlepuff — existing canon, comedic interrupt

LINES = [
    {
        "id": "ken-bio-1", "voice_id": HARRISON,
        "text": (
            "We are here with Brandon Dent, MD — contestant in Anthropic's Built "
            "with Opus 4.7 hackathon. He has worked emergency departments since "
            "starting as an EMT — through medical school, through residency at "
            "some of the country's largest and most reputable trauma centers. Then —"
        ),
        "settings": {"stability": 0.62, "similarity_boost": 0.75, "style": 0.08, "use_speaker_boost": True},
        "model": "eleven_multilingual_v2",
    },
    {
        "id": "fizz-assistant", "voice_id": CHARLIE,
        "text": "ASSISTANT!",
        "settings": {"stability": 0.30, "similarity_boost": 0.80, "style": 0.70, "use_speaker_boost": True},
        "model": "eleven_turbo_v2_5",
    },
    {
        "id": "ken-bio-2", "voice_id": HARRISON,
        "text": (
            "— assistant professor for six and a half years. "
            "About a year ago, he set out to research AI."
        ),
        "settings": {"stability": 0.62, "similarity_boost": 0.75, "style": 0.08, "use_speaker_boost": True},
        "model": "eleven_multilingual_v2",
    },
]


def render(api_key: str, line: dict, out_path: Path) -> tuple[bool, int]:
    body = {"text": line["text"], "model_id": line["model"], "voice_settings": line["settings"]}
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{line['voice_id']}"
    headers = {"xi-api-key": api_key, "Accept": "audio/mpeg", "Content-Type": "application/json"}
    r = httpx.post(url, json=body, headers=headers, timeout=60.0)
    if r.status_code == 200:
        out_path.write_bytes(r.content)
        return True, len(r.content)
    print(f"  {line['id']} HTTP {r.status_code}: {r.text[:200]}")
    return False, 0


def main() -> None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY not in env")
    print(f"writing to {VO_DIR}")
    for line in LINES:
        out = VO_DIR / f"{line['id']}.mp3"
        if out.exists() and out.stat().st_size > 1024:
            print(f"  {line['id']}: cached")
            continue
        ok, size = render(key, line, out)
        if ok:
            print(f"  {line['id']:18} {len(line['text']):4}ch -> {out.name} ({size//1024}KB)")
        time.sleep(0.4)


if __name__ == "__main__":
    main()
