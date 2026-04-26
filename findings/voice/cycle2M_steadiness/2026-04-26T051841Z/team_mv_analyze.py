#!/usr/bin/env python3
"""Team M-V acoustic validator: prosodic features for 6 LibriTTS WAVs.

READ-ONLY. Uses stdlib `wave` + numpy + scipy.io.wavfile only.
Lightweight autocorrelation pitch tracker w/ octave correction (no librosa).

Per L1 GO criterion (cycle2L_forensic/team_l1_phrase_audit.md):
    f0_std <= 30 Hz strict (39 Hz looser)
    f0_range <= 130 Hz
Anchor: cycle-2j wav2/p4 OUTPUT had f0_std=17, f0_range=100, f0_mean=131.
"""
from __future__ import annotations
import json
import os
import sys
import wave
from pathlib import Path
import numpy as np
from scipy.io import wavfile

LIBRITTS_DIR = Path("/Users/kiteboard/Downloads/libritts-english/2026/22756")

CANDIDATES = [
    "2026_22756_000001_000000.wav",
    "2026_22756_000001_000001.wav",
    "2026_22756_000003_000000.wav",
    "2026_22756_000006_000001.wav",
    "2026_22756_000010_000000.wav",
    "2026_22756_000013_000000.wav",
]

# Pitch-tracker config — designed to match L1 audit conventions
WINDOW_MS = 30.0   # match L1 (30 ms window)
HOP_MS = 10.0
F0_MIN_HZ = 70.0
F0_MAX_HZ = 400.0  # adult female ceiling — narrower to suppress octave doublings
ENERGY_RATIO_THRESH = 0.01  # 1% of peak frame RMS → unvoiced (matches L1 spec)
SILENCE_THRESH_RATIO = 0.05
AC_PEAK_THRESH = 0.30  # match L1-style permissive voicing


def load_wav(path: Path):
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sr = wf.getframerate()
    sr2, data = wavfile.read(str(path))
    assert sr2 == sr
    if data.ndim == 2:
        data = data.mean(axis=1)
    if data.dtype == np.int16:
        peak_int = int(np.max(np.abs(data)))
        x = data.astype(np.float64) / 32768.0
        bit_depth = 16
    elif data.dtype == np.int32:
        peak_int = int(np.max(np.abs(data)))
        x = data.astype(np.float64) / 2147483648.0
        bit_depth = 32
    elif data.dtype == np.uint8:
        peak_int = int(np.max(np.abs(data.astype(np.int32) - 128)))
        x = (data.astype(np.float64) - 128.0) / 128.0
        bit_depth = 8
    else:
        x = data.astype(np.float64)
        peak_int = int(np.max(np.abs(data)))
        bit_depth = sample_width * 8
    return x, sr, n_channels, sample_width, bit_depth, peak_int


def autocorr_f0_with_octave_correction(frame: np.ndarray, sr: int) -> float:
    """Autocorrelation pitch w/ subharmonic-preference octave correction."""
    n = len(frame)
    if n < 32:
        return 0.0
    frame = frame - frame.mean()
    # Pre-emphasis + Hann
    pre = np.empty_like(frame)
    pre[0] = frame[0]
    pre[1:] = frame[1:] - 0.97 * frame[:-1]
    win = np.hanning(n)
    sig = pre * win
    nfft = 1
    while nfft < 2 * n:
        nfft *= 2
    spec = np.fft.rfft(sig, n=nfft)
    ac = np.fft.irfft(spec * np.conj(spec), n=nfft)[:n]
    if ac[0] <= 0:
        return 0.0
    ac = ac / ac[0]

    lag_min = max(int(sr / F0_MAX_HZ), 2)
    lag_max = min(int(sr / F0_MIN_HZ), n - 1)
    if lag_max <= lag_min + 1:
        return 0.0

    seg = ac[lag_min:lag_max + 1].copy()
    # Find local maxima via simple slope test
    peaks = []
    for i in range(1, len(seg) - 1):
        if seg[i] > seg[i - 1] and seg[i] > seg[i + 1] and seg[i] > AC_PEAK_THRESH:
            peaks.append((i, float(seg[i])))
    if not peaks:
        # fallback: global argmax
        idx = int(np.argmax(seg))
        if seg[idx] < AC_PEAK_THRESH:
            return 0.0
        peaks = [(idx, float(seg[idx]))]

    # Octave correction: prefer the LARGEST lag (lowest f0) whose AC value
    # is within 0.85x of the global max — this resolves 2x harmonic doublings
    # by selecting the true period when subharmonics are present.
    global_max = max(p[1] for p in peaks)
    best = None
    for idx, val in peaks:
        if val >= 0.85 * global_max:
            if best is None or idx > best[0]:
                best = (idx, val)
    if best is None:
        return 0.0
    peak_idx, peak_val = best

    # Parabolic interpolation
    lag = lag_min + peak_idx
    if 0 < peak_idx < len(seg) - 1:
        a = float(seg[peak_idx - 1])
        b = float(seg[peak_idx])
        c = float(seg[peak_idx + 1])
        denom = a - 2 * b + c
        if abs(denom) > 1e-12:
            shift = 0.5 * (a - c) / denom
            lag = lag + shift
    if lag <= 0:
        return 0.0
    return float(sr) / float(lag)


def median_smooth_octave_jumps(f0s: np.ndarray) -> np.ndarray:
    """Final-pass octave-jump correction using median continuity."""
    if len(f0s) < 5:
        return f0s
    out = f0s.copy()
    # 5-frame median tracker; if a frame is ~2x or ~0.5x the median, snap it.
    for i in range(2, len(out) - 2):
        med = np.median(out[max(0, i - 5):i + 5 + 1])
        if med > 0:
            ratio = out[i] / med
            if 1.7 < ratio < 2.3:
                out[i] = out[i] / 2.0
            elif 0.43 < ratio < 0.59:
                out[i] = out[i] * 2.0
    return out


def compute_f0_track(x: np.ndarray, sr: int):
    win = int(round(sr * WINDOW_MS / 1000.0))
    hop = int(round(sr * HOP_MS / 1000.0))
    if len(x) < win:
        return np.array([]), 0, 0
    n_frames = 1 + (len(x) - win) // hop
    energies = np.empty(n_frames, dtype=np.float64)
    for i in range(n_frames):
        s = i * hop
        frame = x[s:s + win]
        energies[i] = float(np.sqrt(np.mean(frame * frame)))
    peak_e = float(energies.max()) if energies.size else 0.0
    voiced_thresh = peak_e * ENERGY_RATIO_THRESH
    raw_f0 = np.zeros(n_frames, dtype=np.float64)
    voiced_mask = np.zeros(n_frames, dtype=bool)
    for i in range(n_frames):
        if energies[i] < voiced_thresh:
            continue
        s = i * hop
        frame = x[s:s + win]
        f = autocorr_f0_with_octave_correction(frame, sr)
        if F0_MIN_HZ <= f <= F0_MAX_HZ:
            raw_f0[i] = f
            voiced_mask[i] = True
    # Smooth raw track to fix residual octave jumps
    if voiced_mask.sum() >= 5:
        smoothed = raw_f0.copy()
        smoothed[voiced_mask] = median_smooth_octave_jumps(raw_f0[voiced_mask])
        f0_voiced = smoothed[voiced_mask]
    else:
        f0_voiced = raw_f0[voiced_mask]
    return f0_voiced, int(voiced_mask.sum()), n_frames


def silence_head_tail(x: np.ndarray, sr: int):
    if x.size == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    abs_x = np.abs(x)
    peak = float(abs_x.max())
    if peak <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    thresh = peak * SILENCE_THRESH_RATIO
    above = abs_x > thresh
    if not above.any():
        return 0.0, 0.0, 0.0, 0.0, 100.0
    first = int(np.argmax(above))
    last = len(above) - 1 - int(np.argmax(above[::-1]))
    head_samples = first
    tail_samples = (len(above) - 1) - last
    total_silent = int(np.sum(~above))
    return (
        head_samples / sr * 1000.0,
        tail_samples / sr * 1000.0,
        head_samples / len(x) * 100.0,
        tail_samples / len(x) * 100.0,
        total_silent / len(x) * 100.0,
    )


def find_clipping(x: np.ndarray) -> int:
    abs_x = np.abs(x)
    near_full = float(abs_x.max())
    if near_full <= 0:
        return 0
    return int(np.sum(abs_x >= near_full * 0.999) - 1)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def analyze(wav_path: Path):
    x, sr, n_ch, sw_bytes, bit_depth, peak_int = load_wav(wav_path)
    duration_s = len(x) / sr
    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    peak_amp = float(np.max(np.abs(x))) if x.size else 0.0
    f0_arr, n_voiced, n_frames = compute_f0_track(x, sr)
    if n_voiced >= 5:
        f0_mean = float(np.mean(f0_arr))
        f0_std = float(np.std(f0_arr))
        f0_p5 = float(np.percentile(f0_arr, 5))
        f0_p95 = float(np.percentile(f0_arr, 95))
        f0_min = float(np.min(f0_arr))
        f0_max = float(np.max(f0_arr))
        # Use raw min/max range to match L1 convention (max-min over voiced frames)
        f0_range = f0_max - f0_min
        f0_range_p5p95 = f0_p95 - f0_p5
    else:
        f0_mean = f0_std = f0_p5 = f0_p95 = f0_min = f0_max = f0_range = f0_range_p5p95 = 0.0
    head_ms, tail_ms, head_pct, tail_pct, total_silence_pct = silence_head_tail(x, sr)
    clipping_n = find_clipping(x)
    base = wav_path.with_suffix("")
    orig_text = read_text(base.parent / (base.name + ".original.txt"))
    norm_text = read_text(base.parent / (base.name + ".normalized.txt"))
    return {
        "file": wav_path.name,
        "path": str(wav_path),
        "size_bytes": wav_path.stat().st_size,
        "sample_rate": sr,
        "channels": n_ch,
        "sample_width_bytes": sw_bytes,
        "bit_depth": bit_depth,
        "duration_s": round(duration_s, 3),
        "peak_amplitude": round(peak_amp, 4),
        "rms_energy": round(rms, 4),
        "clipping_samples": clipping_n,
        "f0_voiced_frames": n_voiced,
        "f0_total_frames": n_frames,
        "f0_voiced_pct": round(100.0 * n_voiced / max(n_frames, 1), 1),
        "f0_mean_hz": round(f0_mean, 1),
        "f0_std_hz": round(f0_std, 1),
        "f0_min_hz": round(f0_min, 1),
        "f0_max_hz": round(f0_max, 1),
        "f0_p5_hz": round(f0_p5, 1),
        "f0_p95_hz": round(f0_p95, 1),
        "f0_range_hz": round(f0_range, 1),
        "f0_range_p5p95_hz": round(f0_range_p5p95, 1),
        "silence_head_ms": round(head_ms, 1),
        "silence_tail_ms": round(tail_ms, 1),
        "silence_head_pct": round(head_pct, 2),
        "silence_tail_pct": round(tail_pct, 2),
        "silence_total_pct": round(total_silence_pct, 2),
        "transcript_original": orig_text,
        "transcript_normalized": norm_text,
        "transcript_original_avail": bool(orig_text),
        "transcript_normalized_avail": bool(norm_text),
    }


def main():
    results = []
    for cand in CANDIDATES:
        p = LIBRITTS_DIR / cand
        if not p.exists():
            print(f"MISSING: {p}", file=sys.stderr)
            continue
        results.append(analyze(p))
    out = {
        "anchor_cycle2j_wav2_p4": {"f0_std_hz": 17, "f0_range_hz": 100, "f0_mean_hz": 131},
        "l1_go_criterion": {
            "f0_std_strict_hz": 30, "f0_std_loose_hz": 39,
            "f0_range_hz": 130,
            "source": "findings/voice/cycle2L_forensic/2026-04-26T044254Z/team_l1_phrase_audit.md",
        },
        "tracker_config": {
            "window_ms": WINDOW_MS, "hop_ms": HOP_MS,
            "f0_min_hz": F0_MIN_HZ, "f0_max_hz": F0_MAX_HZ,
            "voicing_energy_ratio": ENERGY_RATIO_THRESH,
            "ac_peak_threshold": AC_PEAK_THRESH,
            "silence_threshold_ratio": SILENCE_THRESH_RATIO,
            "octave_correction": "subharmonic-preference + 5-frame median snap",
            "f0_range_method": "max-min over voiced frames (matches L1 audit)",
        },
        "files": results,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
