"""opus_self_monologue.py — the prize-bet beat.

Sends Opus 4.7 a tight prompt asking it, in first person, to explain one
engineering decision from the prism42 build (NVFP4 + tensor-core utilization).
Captures the model's own text. Renders the words through ElevenLabs Harrison
Gale at introspective-developer settings. Saves both the audio and a verbatim
text file so the demo can caption "Voice: ElevenLabs. Words: Opus 4.7, unedited."

Cost: ~$0.05 (Anthropic) + ~$0.02 (ElevenLabs).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
AUDIO_DIR = PROJECT_ROOT / "audio"
TEXT_DIR = PROJECT_ROOT / "audio" / "opus-self"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
TEXT_DIR.mkdir(parents=True, exist_ok=True)

# Harrison Gale (American documentary baritone) — fresh, not in the saturated default catalog
HARRISON_GALE = "fCxG8OHm4STbIsWe4aT9"

# Introspective developer monologue settings (per voice-craft research)
INTROSPECTIVE = {
    "stability": 0.52,
    "similarity_boost": 0.70,
    "style": 0.12,
    "use_speaker_boost": True,
}

OPUS_PROMPT = """You are Claude Opus 4.7. A solo developer just used you across 5 days during the Anthropic "Built with Opus 4.7" hackathon to build prism42 — a self-hosted 911 voice-dispatch agent. The journey: Nemotron Nano 3 MoE on vLLM 0.20 on a Blackwell B300 pod, NVFP4 quantization on the GEMM path, native sm_103 codegen via flashinfer-cubin and a CUDA 13 nvcc rebuild. The result: time-to-first-token p95 dropped from 1655 ms (hosted API) to 44 ms (local). 91.6% reduction.

In exactly 28-35 words, first-person, dry register, address a fellow engineer: explain ONE specific engineering choice you helped reason about during this build (the format choice OR the kernel-arch choice OR the why-rebuild-vLLM-from-source choice). Cite a concrete number. No marketing language. No "we." No "I'm excited to." Sentence structure: short declarative + one mid-length clause.

Output ONLY the monologue text, nothing else. No quotation marks. No preamble."""


def call_opus(api_key: str) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-opus-4-7",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": OPUS_PROMPT}],
    }
    r = httpx.post(url, headers=headers, json=body, timeout=60.0)
    if r.status_code != 200:
        raise RuntimeError(f"Anthropic API HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return text.strip()


def render_elevenlabs(api_key: str, text: str, out_path: Path) -> int:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{HARRISON_GALE}"
    headers = {"xi-api-key": api_key, "Accept": "audio/mpeg", "Content-Type": "application/json"}
    body = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": INTROSPECTIVE,
    }
    r = httpx.post(url, headers=headers, json=body, timeout=60.0)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}")
    out_path.write_bytes(r.content)
    return len(r.content)


def main() -> None:
    anth = os.environ.get("ANTHROPIC_API_KEY")
    el = os.environ.get("ELEVENLABS_API_KEY")
    if not anth:
        sys.exit("ANTHROPIC_API_KEY not in env")
    if not el:
        sys.exit("ELEVENLABS_API_KEY not in env")

    print("[1/2] asking Opus 4.7 for first-person engineering monologue...")
    t0 = time.time()
    monologue = call_opus(anth)
    elapsed = time.time() - t0
    print(f"  got {len(monologue.split())} words in {elapsed:.1f}s:\n")
    print("  " + "\n  ".join(monologue.split("\n")))
    print()

    text_path = TEXT_DIR / "monologue.txt"
    text_path.write_text(monologue + "\n")
    print(f"  saved verbatim -> {text_path}")

    print("\n[2/2] rendering via ElevenLabs Harrison Gale (introspective settings)...")
    t1 = time.time()
    audio_path = AUDIO_DIR / "v3-opus-self-harrison.mp3"
    size = render_elevenlabs(el, monologue, audio_path)
    elapsed = time.time() - t1
    print(f"  {size//1024} KB in {elapsed:.1f}s -> {audio_path}")

    print("\nDone. Caption for the demo: 'Voice: ElevenLabs · Harrison Gale. Words: Opus 4.7, unedited.'")


if __name__ == "__main__":
    main()
