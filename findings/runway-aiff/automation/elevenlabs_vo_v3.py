"""elevenlabs_vo_v3.py — Harrison Gale, first-person, structure-agent 12-beat plan.

Voice direction (from voice-craft research):
- Primary: Harrison Gale (fCxG8OHm4STbIsWe4aT9) — American documentary baritone
- Settings: stability 0.62, similarity_boost 0.75, style 0.08
- Model: eleven_multilingual_v2

Drops Charlie field-stringer entirely (research: "back to you, Brian" was the worst line).
Switches register from broadcast-news pastiche to first-person developer-monologue.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
AUDIO_DIR = PROJECT_ROOT / "audio"
LEDGER = ROOT / "spend-log.csv"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

HARRISON_GALE = "fCxG8OHm4STbIsWe4aT9"
NARRATOR = {
    "stability": 0.62,
    "similarity_boost": 0.75,
    "style": 0.08,
    "use_speaker_boost": True,
}
MODEL_ID = "eleven_multilingual_v2"

# 12-beat plan from winning-demo-structure.md, voiced first-person per voice-craft.md.
# Beat 3 (0:20-0:35) is silent — live voice turn plays.
# Beat 7 (1:25-1:50) bookends the Opus self-monologue (already rendered separately).
# Beat 12 (2:55-3:00) is silent — single sustained low brass cue, no VO.
VO_LINES: list[dict] = [
    {"id": "v3-B1-question", "speaker": "harrison",
     "text": "Every 911 call starts with a question. How fast can help arrive."},
    {"id": "v3-B2-physician", "speaker": "harrison",
     "text": "I'm a physician. I spent five days trying to get that question answered in under fifty milliseconds."},
    # B3 — silent (live voice turn)
    {"id": "v3-B4-baseline", "speaker": "harrison",
     "text": "The hosted API baseline. p95: sixteen-fifty-five milliseconds. The local stack. Forty-four."},
    {"id": "v3-B5-codegen", "speaker": "harrison",
     "text": "Native sm one-oh-three codegen. NVFP4 on Blackwell. CUDA thirteen. vLLM, rebuilt from source."},
    {"id": "v3-B6-broke", "speaker": "harrison",
     "text": "Three things broke first. macOS shipped no timeout binary. An env file took down a shell. A perf claim got retracted under review."},
    {"id": "v3-B7a-opus-intro", "speaker": "harrison",
     "text": "Opus 4.7. Adaptive thinking, display omitted — so the dispatcher answers, not narrates. Task budgets, so the model paces itself across a multi-turn call."},
    # B7b — the Opus self-monologue (already rendered as v3-opus-self-harrison.mp3)
    {"id": "v3-B7c-attribution", "speaker": "harrison",
     "text": "Voice: ElevenLabs. Words: Opus 4.7. Unedited."},
    {"id": "v3-B8-managed-agents", "speaker": "harrison",
     "text": "One coordinator. Parallel threads. The dispatcher answers the call. The auditor checks every clinical claim against HealthBench Hard, while the call is still happening."},
    {"id": "v3-B9-e2e", "speaker": "harrison",
     "text": "End-to-end p95 — under one and a half seconds."},
    {"id": "v3-B10-shifts", "speaker": "harrison",
     "text": "Built between hospital shifts. Five days. One developer."},
    {"id": "v3-B11-repo", "speaker": "harrison",
     "text": "Open source. Apache two. github dot com slash GOATnote dash inc slash prism four two."},
    # B12 — silent
]


def append_ledger(line_id: str, action: str, amount: float, note: str = "elevenlabs-pro") -> None:
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "shot_id", "action", "amount_usd", "note"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), line_id, action, f"{amount:.4f}", note])


def render(api_key: str, line: dict, out_path: Path) -> tuple[bool, int]:
    body = {
        "text": line["text"],
        "model_id": MODEL_ID,
        "voice_settings": NARRATOR,
    }
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{HARRISON_GALE}"
    headers = {"xi-api-key": api_key, "Accept": "audio/mpeg", "Content-Type": "application/json"}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=60.0)
        if r.status_code == 200:
            out_path.write_bytes(r.content)
            return True, len(r.content)
        print(f"  {line['id']} HTTP {r.status_code}: {r.text[:200]}")
        return False, 0
    except Exception as e:
        print(f"  {line['id']} failed: {e}")
        return False, 0


def main() -> None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY not in env")

    manifest = []
    rendered = 0
    total_chars = 0
    for line in VO_LINES:
        out_path = AUDIO_DIR / f"{line['id']}-harrison.mp3"
        if out_path.exists() and out_path.stat().st_size > 1024:
            print(f"  {line['id']:24} cached")
            manifest.append({**line, "path": str(out_path), "cached": True})
            rendered += 1
            continue
        chars = len(line["text"])
        total_chars += chars
        # ElevenLabs Pro: bundled in subscription. Track at $0 for ledger purposes.
        ok, size = render(key, line, out_path)
        if ok:
            append_ledger(line["id"], "tts-v3", 0.0, "harrison-gale-pro-bundled")
            print(f"  {line['id']:24} {chars:4}ch -> {out_path.name} ({size//1024}KB)")
            manifest.append({**line, "path": str(out_path), "size_bytes": size,
                             "voice": "Harrison Gale", "voice_id": HARRISON_GALE, "model": MODEL_ID})
            rendered += 1
        else:
            manifest.append({**line, "path": None, "error": True})
        time.sleep(0.4)

    (AUDIO_DIR / "v3-vo-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nrendered {rendered}/{len(VO_LINES)} v3 lines, {total_chars} chars")


if __name__ == "__main__":
    main()
