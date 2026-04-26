"""openai_vo.py — Fallback VO renderer using OpenAI TTS (ElevenLabs quota tapped).

Mirrors elevenlabs_vo.py output paths so assemble.py is voice-source-agnostic.
Voice mapping:
  KEN -> onyx (deep authoritative male, news-anchor coded)
  FIZZLEPUFF -> fable (textured British male, fits the puppet-bureau wackiness)

Cost: tts-1-hd ~$0.030/1k chars. 1501 chars ≈ $0.045.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
AUDIO_DIR = PROJECT_ROOT / "audio"
LEDGER = ROOT / "spend-log.csv"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

VO_LINES: list[dict] = [
    {"id": "S1-KEN-bumper", "speaker": "ken",
     "text": "From the only desk still covering the hackathon nobody can name — this is GOATnote Nightly."},
    {"id": "S1-KEN-tease", "speaker": "ken",
     "text": "Tonight: a kernel that should not exist. And a number so small a senior engineer briefly forgot he was on camera."},
    {"id": "S1-FIZZ-cold", "speaker": "fizzlepuff",
     "text": "Brian — Brian, no cap, the GEMM is crashing — sorry, sorry, am I early — am I — is this live, fr —"},
    {"id": "S1-KEN-unbothered", "speaker": "ken", "text": "We'll get to him."},
    {"id": "S4-KEN-hardware", "speaker": "ken",
     "text": "This week, the developer stood up a self-hosted B300 pod. Caddy auto-TLS. Parakeet on port nine-one-hundred. Fish Speech on nine-two-hundred."},
    {"id": "S4-KEN-broke", "speaker": "ken",
     "text": "Not everything held. macOS ships no timeout binary, which silently broke a session-start hook for two days. An env file with unquoted multi-line JSON took down a shell. And a perf claim — that a CUDA twelve-eight nvcc against a thirteen-oh driver had negligible cost — was retracted under pressure. It was, in fact, broken at runtime."},
    {"id": "S5-KEN-breaking", "speaker": "ken",
     "text": "This is breaking. The voice agent migrated off a hosted API onto local Nemotron Nano 3 on vLLM zero-point-twenty. First boot: the NVFP4 GEMM crashed. They installed CUDA thirteen nvcc. They installed flashinfer-cubin. They rebuilt vLLM with native sm one-oh-three. The five-gate strict performance gate —"},
    {"id": "S5-KEN-passed", "speaker": "ken",
     "text": "— passed. Time-to-first-token, p95: forty-four milliseconds. Down from sixteen-fifty-five. A ninety-one-point-six percent reduction."},
    {"id": "S5-FIZZ-quiet", "speaker": "fizzlepuff",
     "text": "Brian. Brian, deadass — that's the latency of a well-rested human. We are SO back."},
    {"id": "S6-KEN-closer", "speaker": "ken",
     "text": "Five days. One developer. A B300, a felted correspondent, and three things that broke on the way to a number that didn't."},
    {"id": "S6-FIZZ-button", "speaker": "fizzlepuff",
     "text": "Brian. We did the thing. The dev cooked."},
    {"id": "S6-KEN-out", "speaker": "ken", "text": "We did the thing. Goodnight."},
]

VOICE = {"ken": "onyx", "fizzlepuff": "fable"}
MODEL = "tts-1-hd"


def append_ledger(line_id: str, action: str, amount: float, note: str = "openai-tts") -> None:
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "shot_id", "action", "amount_usd", "note"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), line_id, action, f"{amount:.4f}", note])


def main() -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY not in env")
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai SDK not installed. Run: pip install openai")
    client = OpenAI(api_key=key)

    manifest = []
    total_chars = 0
    rendered = 0
    for line in VO_LINES:
        out_path = AUDIO_DIR / f"{line['id']}-{line['speaker']}.mp3"
        if out_path.exists() and out_path.stat().st_size > 1024:
            print(f"  {line['id']:22} cached")
            manifest.append({**line, "path": str(out_path), "cached": True})
            rendered += 1
            continue
        chars = len(line["text"])
        total_chars += chars
        cost_est = chars * 0.030 / 1000
        try:
            resp = client.audio.speech.create(
                model=MODEL,
                voice=VOICE[line["speaker"]],
                input=line["text"],
                response_format="mp3",
            )
            with out_path.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=4096):
                    f.write(chunk)
            size = out_path.stat().st_size
            append_ledger(line["id"], "tts", cost_est)
            print(f"  {line['id']:22} {line['speaker']:11} {chars:4}ch ${cost_est:.4f} -> {out_path.name} ({size//1024}KB)")
            manifest.append({**line, "path": str(out_path), "size_bytes": size,
                             "voice": VOICE[line["speaker"]], "model": MODEL})
            rendered += 1
        except Exception as e:
            print(f"  {line['id']:22} FAIL: {str(e)[:200]}")
            manifest.append({**line, "path": None, "error": str(e)[:200]})
        time.sleep(0.3)

    (AUDIO_DIR / "vo-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nrendered {rendered}/{len(VO_LINES)} lines, {total_chars} chars total (~${total_chars * 0.030 / 1000:.3f})")


if __name__ == "__main__":
    main()
