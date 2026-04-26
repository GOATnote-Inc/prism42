#!/usr/bin/env python3
"""Cycle-2M steadiness aggregate.

Replicates L1's f0 measurement pipeline (autocorrelation pitch tracker,
30ms / 10ms hop, voiced-only via energy threshold) on cycle-2M output
WAVs and applies the L1 GO criterion:

  PASS_GO_strict if f0_std <= 30 AND f0_range <= 130
  PASS_GO_loose  if f0_std <= 39 AND f0_range <= 128

Reads metrics.json (per-phrase records), emits aggregate counts to
stdout + writes aggregate.json beside metrics.json.

Source for thresholds + algorithm: cycle2L_forensic/2026-04-26T044254Z/
team_l1_phrase_audit.md.
"""
from __future__ import annotations
import json
import statistics
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
FRAME_MS = 30
HOP_MS = 10
F0_MIN = 60.0
F0_MAX = 500.0
# Energy threshold: voiced if frame RMS >= 5% of max RMS over the clip.
# Same heuristic L1 used (≥5% peak in trail/init silence detection).
VOICED_RMS_FRAC = 0.05


def read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    """Read 16-bit mono WAV → float32 in [-1, 1]."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(n)
    assert sw == 2, f"expected 16-bit PCM, got sampwidth={sw} ({path})"
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)
    return samples, sr


def f0_track(samples: np.ndarray, sr: int) -> dict:
    """Autocorrelation pitch tracker, 30ms / 10ms hop, voiced-only.

    Returns dict with f0_mean / f0_std / f0_range / voiced_count / total_frames.
    Computes f0 only on frames passing the energy threshold; unvoiced
    frames contribute nothing (matches L1's algorithm description).
    """
    frame_n = int(FRAME_MS / 1000.0 * sr)
    hop_n = int(HOP_MS / 1000.0 * sr)
    if len(samples) < frame_n:
        return {
            "f0_mean": 0.0,
            "f0_std": 0.0,
            "f0_range": 0.0,
            "f0_min": 0.0,
            "f0_max": 0.0,
            "voiced_count": 0,
            "total_frames": 0,
        }
    # Frame-level RMS for voicing decision.
    frames = []
    rms_per_frame = []
    for start in range(0, len(samples) - frame_n + 1, hop_n):
        f = samples[start : start + frame_n]
        frames.append(f)
        rms_per_frame.append(float(np.sqrt(np.mean(f * f))))
    rms_arr = np.array(rms_per_frame)
    if rms_arr.size == 0:
        return {
            "f0_mean": 0.0,
            "f0_std": 0.0,
            "f0_range": 0.0,
            "f0_min": 0.0,
            "f0_max": 0.0,
            "voiced_count": 0,
            "total_frames": 0,
        }
    rms_threshold = max(VOICED_RMS_FRAC * rms_arr.max(), 1e-6)

    # Autocorrelation pitch per voiced frame.
    lag_min = int(sr / F0_MAX)
    lag_max = int(sr / F0_MIN)
    f0_vals: list[float] = []
    for f, rms in zip(frames, rms_per_frame):
        if rms < rms_threshold:
            continue
        # Subtract DC, hann window for cleaner ACF.
        f_work = f - f.mean()
        win = np.hanning(len(f_work))
        f_work = f_work * win
        # Compute autocorrelation via FFT for speed.
        n = len(f_work)
        nfft = 1 << (n - 1).bit_length() << 1
        spec = np.fft.rfft(f_work, n=nfft)
        acf_full = np.fft.irfft(spec * np.conj(spec), n=nfft).real
        acf = acf_full[: n]
        if acf[0] <= 0:
            continue
        # Restrict to [lag_min, lag_max] and find the peak.
        if lag_max >= len(acf):
            continue
        seg = acf[lag_min : lag_max + 1]
        if seg.size == 0:
            continue
        peak_lag = int(np.argmax(seg)) + lag_min
        peak_val = float(acf[peak_lag])
        # Reject if peak is below 30% of zero-lag autocorrelation
        # (weak periodicity = unvoiced misclass).
        if peak_val < 0.30 * float(acf[0]):
            continue
        f0 = sr / peak_lag
        if F0_MIN <= f0 <= F0_MAX:
            f0_vals.append(f0)

    if not f0_vals:
        return {
            "f0_mean": 0.0,
            "f0_std": 0.0,
            "f0_range": 0.0,
            "f0_min": 0.0,
            "f0_max": 0.0,
            "voiced_count": 0,
            "total_frames": len(frames),
        }
    arr = np.array(f0_vals)
    return {
        "f0_mean": round(float(arr.mean()), 1),
        "f0_std": round(float(arr.std()), 1),
        "f0_range": round(float(arr.max() - arr.min()), 1),
        "f0_min": round(float(arr.min()), 1),
        "f0_max": round(float(arr.max()), 1),
        "voiced_count": int(arr.size),
        "total_frames": int(len(frames)),
    }


def go_eval(f0_std: float, f0_range: float) -> dict:
    return {
        "pass_strict": bool(f0_std <= 30 and f0_range <= 130),
        "pass_loose": bool(f0_std <= 39 and f0_range <= 128),
    }


def analyze_dir(d: Path) -> list[dict]:
    """Walk all *.wav under d, compute per-file metrics."""
    rows = []
    for wav in sorted(d.rglob("*.wav")):
        try:
            samples, sr = read_pcm16(wav)
            f0 = f0_track(samples, sr)
            duration_s = round(len(samples) / sr, 3)
            peak = int(np.abs(samples * 32768).max()) if samples.size else 0
            rms = round(float(np.sqrt(np.mean(samples * samples)) * 32768), 1)
            row = {
                "wav_path": str(wav),
                "condition": wav.parent.name,
                "phrase": wav.stem,
                "duration_s": duration_s,
                "peak": peak,
                "rms": rms,
                **f0,
                **go_eval(f0["f0_std"], f0["f0_range"]),
            }
            rows.append(row)
        except Exception as e:
            rows.append({
                "wav_path": str(wav),
                "condition": wav.parent.name,
                "phrase": wav.stem,
                "error": f"{type(e).__name__}: {e}",
            })
    return rows


def aggregate(rows: list[dict]) -> dict:
    """Group by condition, report counts + medians."""
    by_cond: dict[str, list[dict]] = {}
    for r in rows:
        by_cond.setdefault(r["condition"], []).append(r)
    agg = {}
    for cond, items in sorted(by_cond.items()):
        ok = [r for r in items if "error" not in r]
        f0_stds = [r["f0_std"] for r in ok]
        f0_ranges = [r["f0_range"] for r in ok]
        f0_means = [r["f0_mean"] for r in ok]
        agg[cond] = {
            "n_total": len(items),
            "n_ok": len(ok),
            "f0_std_mean": round(statistics.mean(f0_stds), 1) if f0_stds else None,
            "f0_std_max": max(f0_stds) if f0_stds else None,
            "f0_range_mean": round(statistics.mean(f0_ranges), 1) if f0_ranges else None,
            "f0_range_max": max(f0_ranges) if f0_ranges else None,
            "f0_mean_mean": round(statistics.mean(f0_means), 1) if f0_means else None,
            "pass_strict_count": sum(1 for r in ok if r.get("pass_strict")),
            "pass_loose_count": sum(1 for r in ok if r.get("pass_loose")),
            "per_phrase": {
                r["phrase"]: {
                    "f0_mean": r.get("f0_mean"),
                    "f0_std": r.get("f0_std"),
                    "f0_range": r.get("f0_range"),
                    "pass_strict": r.get("pass_strict"),
                    "pass_loose": r.get("pass_loose"),
                }
                for r in ok
            },
        }
    return agg


def main() -> int:
    here = Path(__file__).parent
    audio_dir = here / "audio"
    if not audio_dir.is_dir():
        sys.exit(f"FATAL: {audio_dir} missing")
    rows = analyze_dir(audio_dir)
    out_metrics = here / "metrics.json"
    out_metrics.write_text(json.dumps(rows, indent=2))
    print(f"wrote {out_metrics} ({len(rows)} rows)")
    agg = aggregate(rows)
    out_agg = here / "aggregate.json"
    out_agg.write_text(json.dumps(agg, indent=2))
    print(f"wrote {out_agg}")
    print()
    print(f"{'cond':<10}{'n_ok':>6}{'f0σ̄':>8}{'f0σmax':>9}{'rangē':>8}{'rangemax':>10}{'PASS_loose':>13}{'PASS_strict':>14}")
    for cond, a in agg.items():
        print(f"{cond:<10}{a['n_ok']:>6}"
              f"{(a['f0_std_mean'] or 0):>8.1f}"
              f"{(a['f0_std_max'] or 0):>9.1f}"
              f"{(a['f0_range_mean'] or 0):>8.1f}"
              f"{(a['f0_range_max'] or 0):>10.1f}"
              f"{a['pass_loose_count']}/{a['n_ok']:<11}"
              f"{a['pass_strict_count']}/{a['n_ok']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
