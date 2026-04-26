"""Cycle-2k pod-side bench harness — runs on B300, hits Fish :9200 directly.

Methodology mirrors what fish_speech_tts.py does in production: same
ormsgpack body, same 12 fields, same seed, same chunk_length, same
streaming=True. The ONLY difference per condition is the pace-tag prefix
on the text field — this is a faithful reproduction of what the adapter
emits when PRISM42_FISH_PACE_TAG=<tag>.

Output: 30 audio files (6 conditions x 5 phrases) + per-call metrics.

Conditions:
  baseline = no tag (PRISM42_FISH_PACE_TAG="")
  T1       = "[urgent dispatcher pace]"
  T2       = "[fast clear]"
  T3       = "[news anchor pace]"
  T4       = "[brisk professional]"
  T5       = "[911 dispatcher voice]"

Phrases (verbatim per spec):
  P1 = "Nine one one, where is your emergency?"
  P2 = "What's your location?"
  P3 = "Are they breathing?"
  P4 = "Stay with me."
  P5 = "Help is on the way."

Audio: 44.1 kHz mono PCM16 wrapped in RIFF WAV.
"""
import json
import struct
import sys
import time
import wave
from pathlib import Path

import httpx
import ormsgpack

FISH_URL = "http://127.0.0.1:9200"
SAMPLE_RATE = 44_100
CHANNELS = 1

CONDITIONS = [
    ("baseline", ""),
    ("T1", "[urgent dispatcher pace]"),
    ("T2", "[fast clear]"),
    ("T3", "[news anchor pace]"),
    ("T4", "[brisk professional]"),
    ("T5", "[911 dispatcher voice]"),
]

PHRASES = [
    ("p1", "Nine one one, where is your emergency?"),
    ("p2", "What's your location?"),
    ("p3", "Are they breathing?"),
    ("p4", "Stay with me."),
    ("p5", "Help is on the way."),
]


def strip_wav_header(wav_bytes: bytes) -> bytes:
    """Strip RIFF header from a Fish WAV blob, return raw PCM16."""
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF":
        return wav_bytes
    idx = wav_bytes.find(b"data", 12)
    if idx == -1:
        return wav_bytes
    return wav_bytes[idx + 8:]


def write_wav(path: Path, pcm_bytes: bytes) -> None:
    """Write canonical 16-bit mono RIFF WAV at SAMPLE_RATE."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm_bytes)


def synth_one(client: httpx.Client, tag: str, text: str) -> dict:
    """Run one synth via Fish HTTP. Return metrics + audio bytes."""
    text_with_tag = f"{tag} {text}" if tag else text
    body = {
        "text": text_with_tag,
        "format": "wav",
        "chunk_length": 200,
        "normalize": True,
        "streaming": True,
        "max_new_tokens": 1024,
        "top_p": 0.7,
        "repetition_penalty": 1.1,
        "temperature": 0.1,
        "use_memory_cache": "on",
        "seed": 911,
        "references": [],
    }
    t0 = time.monotonic()
    t_first_byte = None
    buf = bytearray()
    try:
        with client.stream(
            "POST",
            f"{FISH_URL}/v1/tts",
            content=ormsgpack.packb(body),
            headers={"Content-Type": "application/msgpack"},
        ) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes():
                if chunk:
                    if t_first_byte is None:
                        t_first_byte = time.monotonic()
                    buf.extend(chunk)
        t_done = time.monotonic()
        wav_bytes = bytes(buf)
        pcm_bytes = strip_wav_header(wav_bytes)
        # Pad to even byte for whole 16-bit samples
        if len(pcm_bytes) % 2 == 1:
            pcm_bytes = pcm_bytes[:-1]
        sample_count = len(pcm_bytes) // 2
        # Audio peak (energy proxy for silent/broken detection)
        peak = 0
        if sample_count > 0:
            for i in range(0, len(pcm_bytes), 2):
                v = struct.unpack("<h", pcm_bytes[i:i+2])[0]
                if abs(v) > peak:
                    peak = abs(v)
        return {
            "ok": True,
            "ttfb_ms": int((t_first_byte - t0) * 1000) if t_first_byte else None,
            "total_ms": int((t_done - t0) * 1000),
            "wav_bytes": len(wav_bytes),
            "pcm_bytes": len(pcm_bytes),
            "duration_ms": int(sample_count / SAMPLE_RATE * 1000),
            "peak": peak,
            "text_sent": text_with_tag,
            "_audio": pcm_bytes,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:300],
            "text_sent": text_with_tag,
            "_audio": b"",
            "ttfb_ms": None,
            "total_ms": int((time.monotonic() - t0) * 1000),
            "wav_bytes": 0,
            "pcm_bytes": 0,
            "duration_ms": 0,
            "peak": 0,
        }


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"conditions": {}}
    with httpx.Client(timeout=60.0) as client:
        for cond_name, cond_tag in CONDITIONS:
            cond_dir = out_dir / "audio" / cond_name
            cond_dir.mkdir(parents=True, exist_ok=True)
            cond_results = {"tag": cond_tag, "phrases": {}}
            for p_id, p_text in PHRASES:
                print(f"=== {cond_name} / {p_id} === tag={cond_tag!r} text={p_text!r}", flush=True)
                m = synth_one(client, cond_tag, p_text)
                audio = m.pop("_audio")
                m["text_orig"] = p_text
                if m["ok"] and audio:
                    wav_path = cond_dir / f"{p_id}.wav"
                    write_wav(wav_path, audio)
                    m["wav_path"] = str(wav_path)
                else:
                    m["wav_path"] = None
                cond_results["phrases"][p_id] = m
                # Brief sleep to avoid hammering Fish back-to-back
                time.sleep(0.2)
            results["conditions"][cond_name] = cond_results
    results_path = out_dir / "result.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nWrote {results_path}", flush=True)
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/cycle2k_bench")
    sys.exit(main(out))
