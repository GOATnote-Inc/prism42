#!/usr/bin/env python3
"""Cycle-2d Fish microbench. Runs 5 direct TTS requests against Fish on the pod.

Measures per request:
  - HTTP TTFB (time to first byte)
  - Full-render time (time to last byte)
  - Audio byte count
  - Audio peak amplitude (decoded as int16 mono)
  - Audio waveform shape signature (RMS over 10 equal-time slices)

Pre-patch baseline (cycle-2a-debug): tts_total_ms_max p50=6275 p95=7455
                                      reply_speech_amp_max range 20598-25639
"""
from __future__ import annotations
import json
import statistics
import struct
import time
import urllib.request

FISH_URL = "http://127.0.0.1:9200"
PROMPT = "Nine one one, what's your emergency?"
N_RUNS = 5
SPACING_S = 10


def run_one(idx: int) -> dict:
    body = json.dumps({
        "text": PROMPT,
        "format": "wav",
        "streaming": True,
        "references": [],
        "chunk_length": 200,
    }).encode()
    # Use msgpack? No — Fish accepts JSON; we mimic the simple path.
    # Actually synthetic_caller uses ormsgpack. To stay protocol-faithful
    # let's use ormsgpack if available, else fall back to JSON.
    try:
        import ormsgpack
        body = ormsgpack.packb(json.loads(body))
        ctype = "application/msgpack"
    except Exception:
        ctype = "application/json"

    req = urllib.request.Request(
        FISH_URL + "/v1/tts",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )

    t0 = time.perf_counter()
    ttfb_ms = None
    chunks: list[bytes] = []
    total_bytes = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(4096)
                if ttfb_ms is None and chunk:
                    ttfb_ms = int((time.perf_counter() - t0) * 1000)
                if not chunk:
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
    except Exception as exc:
        return {"idx": idx, "error": str(exc), "ttfb_ms": ttfb_ms}

    full_ms = int((time.perf_counter() - t0) * 1000)

    pcm = b"".join(chunks)
    # Strip WAV header if present (RIFF/WAVE). Fish streams chunked RIFF
    # where `data` chunk size is 0; PCM follows from offset 44 to EOF.
    audio_bytes = pcm
    if pcm[:4] == b"RIFF" and pcm[8:12] == b"WAVE":
        i = 12
        while i < len(pcm) - 8:
            cid = pcm[i:i+4]
            csz = struct.unpack("<I", pcm[i+4:i+8])[0]
            if cid == b"data":
                if csz == 0:
                    # Streaming: take everything after the data header.
                    audio_bytes = pcm[i+8:]
                else:
                    audio_bytes = pcm[i+8:i+8+csz]
                break
            i += 8 + csz

    n_samples = len(audio_bytes) // 2
    peak = 0
    rms_slices: list[float] = []
    if n_samples > 0:
        # int16 little-endian
        sample_format = "<%dh" % n_samples
        try:
            samples = struct.unpack(sample_format, audio_bytes[:n_samples*2])
        except struct.error:
            samples = ()
        if samples:
            peak = max(abs(s) for s in samples)
            slice_size = max(1, n_samples // 10)
            for i in range(10):
                start = i * slice_size
                end = min(start + slice_size, n_samples)
                if start >= n_samples:
                    rms_slices.append(0.0)
                    continue
                seg = samples[start:end]
                if not seg:
                    rms_slices.append(0.0)
                    continue
                ms = sum(s*s for s in seg) / len(seg)
                rms_slices.append(round(ms ** 0.5, 1))

    return {
        "idx": idx,
        "ttfb_ms": ttfb_ms,
        "full_render_ms": full_ms,
        "total_bytes": total_bytes,
        "audio_data_bytes": len(audio_bytes),
        "n_samples": n_samples,
        "peak_amplitude": peak,
        "rms_slices_10": rms_slices,
        "approx_audio_duration_s": round(n_samples / 44100.0, 3),
    }


def main():
    print(f"=== Cycle-2d Fish microbench: {N_RUNS} runs of '{PROMPT}' ===")
    runs = []
    for i in range(1, N_RUNS + 1):
        if i > 1:
            time.sleep(SPACING_S)
        r = run_one(i)
        runs.append(r)
        print(f"run {i}: {json.dumps(r)}")

    ttfb = [r["ttfb_ms"] for r in runs if r.get("ttfb_ms") is not None]
    full = [r["full_render_ms"] for r in runs if r.get("full_render_ms") is not None]
    peaks = [r["peak_amplitude"] for r in runs if r.get("peak_amplitude") is not None]

    summary = {
        "prompt": PROMPT,
        "n_runs": N_RUNS,
        "successful_runs": len(full),
        "ttfb_ms": {
            "min": min(ttfb) if ttfb else None,
            "p50": int(statistics.median(ttfb)) if ttfb else None,
            "max": max(ttfb) if ttfb else None,
            "mean": round(statistics.mean(ttfb), 1) if ttfb else None,
        },
        "full_render_ms": {
            "min": min(full) if full else None,
            "p50": int(statistics.median(full)) if full else None,
            "max": max(full) if full else None,
            "mean": round(statistics.mean(full), 1) if full else None,
        },
        "peak_amplitude": {
            "min": min(peaks) if peaks else None,
            "max": max(peaks) if peaks else None,
            "mean": round(statistics.mean(peaks), 1) if peaks else None,
        },
        "pre_patch_baseline_cycle_2a_debug": {
            "tts_total_ms_max_p50": 6275,
            "tts_total_ms_max_p95": 7455,
            "reply_speech_amp_min": 20598,
            "reply_speech_amp_max": 25639,
        },
        "runs": runs,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
