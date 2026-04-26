"""ElevenLabs voice render — turns the cut-down script.md into Ken/Fizzlepuff
WAV files for DaVinci timeline.

Reads ELEVENLABS_API_KEY from env. Writes ../audio/ken-{seg}.mp3 and
../audio/fizzlepuff-{seg}.mp3, plus a master ../audio/vo-manifest.json with
timing.

Voice settings per CHARACTER_BIBLE.md:
  KEN: voice 'Brian' (American narrator), stability 55, similarity 75, style 15
  FIZZLEPUFF: voice 'Charlie' pitched +2 semitones equivalent, stability 35,
              similarity 80, style 60
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
AUDIO_DIR = PROJECT_ROOT / "audio"
LEDGER = ROOT / "spend-log.csv"
SCRIPT_PATH = Path("/Users/kiteboard/prism42/script.md")

# v2 — documentary register. BRIAN as narrator + CHARLIE as field stringer (one call-in
# + one button at the end). Maps to script-v2.md.
VO_LINES: list[dict] = [
    # Segment 1 — Cold Open
    {"id": "v2-S1-bumper", "speaker": "brian",
     "text": "Every night, in rooms most people never see, a question gets asked thousands of times. How fast can help arrive."},
    {"id": "v2-S1-tease", "speaker": "brian",
     "text": "This week, one developer cut the time it takes a voice agent to start answering that question — by ninety-one percent."},

    # Segment 2 — Field Stringer Cold
    {"id": "v2-S2-stringer", "speaker": "charlie",
     "text": "Brian — picking up a feed from the dispatch desk now — the prior pipeline was a hosted API, latency p95 sixteen-fifty-five milliseconds — they're running a local stack tonight —"},
    {"id": "v2-S2-stay", "speaker": "brian",
     "text": "Stay with that."},

    # Segment 3 — Hardware
    {"id": "v2-S3-build", "speaker": "brian",
     "text": "The build: a self-hosted Blackwell-class GPU pod. Caddy auto-TLS. Parakeet on port nine-one-hundred for speech recognition. Fish Speech on nine-two-hundred for synthesis. The model: Nemotron Nano three, on vLLM zero-point-twenty."},
    {"id": "v2-S3-broke", "speaker": "brian",
     "text": "Not everything held. Three things broke before anything worked. macOS ships no timeout binary, which silently broke a session-start hook for two days. An environment file with unquoted multi-line JSON took down a shell. And one performance claim — about a CUDA toolchain mismatch — was retracted under pressure. It was, in fact, broken at runtime."},

    # Segment 4 — Engineering Breaking News
    {"id": "v2-S4-firstboot", "speaker": "brian",
     "text": "First boot of the local stack: the NVFP4 GEMM crashed on the GPU. They installed CUDA thirteen nvcc. They installed flashinfer-cubin. They rebuilt vLLM with native sm one-oh-three. The five-gate strict performance gate —"},
    {"id": "v2-S4-passed", "speaker": "brian",
     "text": "— passed. Time-to-first-token, p95 — forty-four milliseconds. Down from sixteen-fifty-five."},
    {"id": "v2-S4-quiet", "speaker": "charlie",
     "text": "Brian — that's the latency of a well-rested human."},

    # Segment 5 — Closer
    {"id": "v2-S5-closer", "speaker": "brian",
     "text": "Five days. One developer. A purpose-built GPU pod, three things that broke on the way to a number that didn't, and a voice agent that now answers in forty-four milliseconds."},
    {"id": "v2-S5-room", "speaker": "brian",
     "text": "The room never sleeps. Now neither does the model."},
    {"id": "v2-S5-button", "speaker": "charlie",
     "text": "Back to you, Brian."},
]

# ElevenLabs voice IDs — `Brian` and `Charlie` are public preset voices
VOICE_IDS = {
    "brian": "nPczCjzI2devNBz1zQrb",      # Brian (American narrator) — public preset
    "charlie": "IKne3meq5aSn9XLyUdCD",    # Charlie — public preset
}

VOICE_SETTINGS = {
    # v2: pull style back on Brian for sober narration
    "brian": {"stability": 0.60, "similarity_boost": 0.75, "style": 0.10, "use_speaker_boost": True},
    # Charlie hurried but not panicked — phone-line treatment in DaVinci
    "charlie": {"stability": 0.45, "similarity_boost": 0.80, "style": 0.50, "use_speaker_boost": True},
}

MODEL_ID = "eleven_turbo_v2_5"  # fast + good quality


def append_ledger(line_id: str, action: str, amount: float) -> None:
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "shot_id", "action", "amount_usd", "note"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), line_id, action, f"{amount:.4f}", "elevenlabs-tts"])


def render_line(api_key: str, line: dict, out_path: Path) -> tuple[bool, int]:
    voice_id = VOICE_IDS[line["speaker"]]
    settings = VOICE_SETTINGS[line["speaker"]]
    body = {
        "text": line["text"],
        "model_id": MODEL_ID,
        "voice_settings": settings,
    }
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Accept": "audio/mpeg", "Content-Type": "application/json"}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=60.0)
        if r.status_code == 200:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(r.content)
            return True, len(r.content)
        else:
            print(f"  {line['id']} HTTP {r.status_code}: {r.text[:200]}")
            return False, 0
    except Exception as e:
        print(f"  {line['id']} failed: {e}")
        return False, 0


def main() -> None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY not in env")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    total_chars = 0
    for line in VO_LINES:
        out_path = AUDIO_DIR / f"{line['id']}-{line['speaker']}.mp3"
        if out_path.exists() and out_path.stat().st_size > 1024:
            print(f"  {line['id']} cached -> {out_path.name}")
            manifest.append({**line, "path": str(out_path), "cached": True})
            continue
        chars = len(line["text"])
        total_chars += chars
        # ElevenLabs Turbo v2.5 = $0.0001/char (~$0.10 per 1k chars on Starter)
        cost_est = chars * 0.0001
        ok, size = render_line(key, line, out_path)
        if ok:
            append_ledger(line["id"], "tts", cost_est)
            print(f"  {line['id']} {line['speaker']:11} {chars}ch ${cost_est:.3f} -> {out_path.name} ({size//1024}KB)")
            manifest.append({**line, "path": str(out_path), "size_bytes": size})
        else:
            manifest.append({**line, "path": None, "error": True})
        time.sleep(0.5)  # gentle to ElevenLabs rate limits

    (AUDIO_DIR / "vo-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nrendered {sum(1 for m in manifest if m.get('path'))}/{len(VO_LINES)} lines")
    print(f"total chars: {total_chars} (~${total_chars * 0.0001:.2f})")
    print(f"manifest: {AUDIO_DIR / 'vo-manifest.json'}")


if __name__ == "__main__":
    main()
