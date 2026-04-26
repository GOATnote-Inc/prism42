#!/usr/bin/env python3
"""Cycle-2N MW reference bench: 5 PSAP phrases via Fish HTTP /v1/tts.

streaming=True + format=wav. Adapter behavior: returns RAW 16-bit PCM
(no RIFF header) at SAMPLE_RATE=44100 mono.
"""
import json, sys, time, struct
from pathlib import Path

import ormsgpack
import urllib.request, urllib.error
import numpy as np

REF_AUDIO = "/opt/prism42/voice-refs/mw_sample.wav"
REF_TEXT = "Bleeding, choking, or trouble breathing? Help is being sent while I ask these questions. Listen carefully and follow my instructions. Are you safe where you are? Do you see smoke, fear?"

PHRASES = [
    ("p1", "Nine one one, where is your emergency?"),
    ("p2", "What's your location?"),
    ("p3", "Are they breathing?"),
    ("p4", "Stay with me."),
    ("p5", "Help is on the way."),
]

OUT_DIR = Path("/tmp/cycle2N_out")
OUT_DIR.mkdir(exist_ok=True)
AUDIO_DIR = OUT_DIR / "audio_MW"
AUDIO_DIR.mkdir(exist_ok=True)

FISH_URL = "http://127.0.0.1:9200/v1/tts"
SAMPLE_RATE = 44100  # adapter default — Fish returns raw PCM at this rate
CHANNELS = 1


def load_ref():
    with open(REF_AUDIO, "rb") as f:
        return f.read()


def wrap_wav(pcm_bytes: bytes, sr: int = SAMPLE_RATE, ch: int = CHANNELS) -> bytes:
    """Wrap raw PCM in a RIFF WAV header for archival."""
    n_samples = len(pcm_bytes) // 2  # int16
    bps = 16
    byte_rate = sr * ch * bps // 8
    block_align = ch * bps // 8
    data_size = len(pcm_bytes)
    file_size = 36 + data_size
    hdr = b"RIFF" + struct.pack("<I", file_size) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, sr, byte_rate, block_align, bps)
    hdr += b"data" + struct.pack("<I", data_size)
    return hdr + pcm_bytes


def synth(text: str, ref_audio: bytes, ref_text: str, save_path: Path | None = None):
    body = {
        "text": text,
        "format": "wav",
        "chunk_length": 200,
        "max_new_tokens": 1024,
        "top_p": 0.7,
        "repetition_penalty": 1.2,
        "temperature": 0.7,
        "streaming": True,
        "use_memory_cache": "on",
        "seed": 42,
        "references": [{"audio": ref_audio, "text": ref_text}],
    }
    payload = ormsgpack.packb(body)
    req = urllib.request.Request(
        FISH_URL,
        data=payload,
        headers={"Content-Type": "application/msgpack"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            t1 = time.monotonic()
            data = resp.read()
            t2 = time.monotonic()
            ttfb_ms = int((t1 - t0) * 1000)
            total_ms = int((t2 - t0) * 1000)
            status = resp.status
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "err": e.read()[:500].decode("utf-8", errors="replace")}
    if status != 200 or len(data) < 100:
        return {"ok": False, "status": status, "err": data[:200]}
    # streaming=True returns raw PCM. Wrap in WAV.
    pcm = data
    n_samples = len(pcm) // 2
    duration_s = n_samples / SAMPLE_RATE
    x = np.frombuffer(pcm, dtype=np.int16)
    peak = int(np.max(np.abs(x))) if x.size else 0
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0
    if save_path:
        save_path.write_bytes(wrap_wav(pcm))
    return {
        "ok": True, "status": status, "ttfb_ms": ttfb_ms, "total_ms": total_ms,
        "sr": SAMPLE_RATE, "nch": CHANNELS, "bps": 16,
        "duration_s": round(duration_s, 3), "peak": peak, "rms": round(rms, 1),
        "wav_bytes": len(data) + 44,  # PCM + RIFF wrap
        "audio_bytes": len(data),
    }


def main():
    ref_audio = load_ref()
    print(f"REF_AUDIO bytes={len(ref_audio)} text_chars={len(REF_TEXT)}")
    # pre-warm
    print("Warming up...")
    w = synth("Hello world.", ref_audio, REF_TEXT)
    print(f"  warmup: ok={w['ok']} ttfb={w.get('ttfb_ms', '?')} total={w.get('total_ms','?')} dur={w.get('duration_s', '?')}")
    if not w["ok"]:
        print(f"  warmup failed: {w}", file=sys.stderr); sys.exit(3)
    print(f"\n=== MW reference 5-phrase bench ===")
    metrics = {"condition": "MW", "ref_audio_path": REF_AUDIO, "ref_text": REF_TEXT, "phrases": {}}
    for pid, txt in PHRASES:
        save_p = AUDIO_DIR / f"{pid}.wav"
        r = synth(txt, ref_audio, REF_TEXT, save_path=save_p)
        if r["ok"]:
            print(f"  {pid}: ttfb={r['ttfb_ms']:>5}ms total={r['total_ms']:>5}ms dur={r['duration_s']:>5.3f}s peak={r['peak']:>6} rms={r['rms']:>7.1f} sr={r['sr']} bytes={r['wav_bytes']}")
        else:
            print(f"  {pid}: FAIL status={r['status']} err={r.get('err','?')[:200]}")
        metrics["phrases"][pid] = {"text": txt, **r}
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"\nSAVED: {OUT_DIR / 'metrics.json'}")
    successes = sum(1 for r in metrics["phrases"].values() if r.get("ok"))
    print(f"Success: {successes}/5")


if __name__ == "__main__":
    main()
