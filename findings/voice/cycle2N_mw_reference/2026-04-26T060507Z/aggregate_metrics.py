#!/usr/bin/env python3
"""Replay aggregator for cycle-2N MW reference bench.

Reads metrics.json + audio/MW/*.wav, recomputes f0 features via M-V tracker,
and prints summary table.
"""
import importlib.util
import json
from pathlib import Path

ART = Path(__file__).resolve().parent
TRACKER_PATH = Path(
    "/Users/kiteboard/prism42/findings/voice/cycle2M_steadiness/2026-04-26T051841Z/team_mv_analyze.py"
)


def main():
    spec = importlib.util.spec_from_file_location("mv_tracker", TRACKER_PATH)
    mv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mv)
    print(f"=== MW reference (35-50s) ===")
    ref = mv.analyze(ART / "audio/reference/mw_sample_trim.wav")
    for k in ("duration_s", "f0_mean_hz", "f0_std_hz", "f0_range_hz", "peak_amplitude", "rms_energy", "clipping_samples"):
        print(f"  {k}: {ref[k]}")
    print(f"\n=== MW outputs ===")
    out_files = sorted((ART / "audio/MW").glob("*.wav"))
    print(f"{'phrase':<8} {'dur s':>6} {'f0_mean':>8} {'f0_std':>7} {'f0_range':>9} {'p5p95':>7} {'voiced%':>8}")
    rows = []
    for f in out_files:
        r = mv.analyze(f)
        rows.append(r)
        print(f"{f.stem:<8} {r['duration_s']:>6.2f} {r['f0_mean_hz']:>8.1f} {r['f0_std_hz']:>7.1f} {r['f0_range_hz']:>9.1f} {r['f0_range_p5p95_hz']:>7.1f} {r['f0_voiced_pct']:>8.1f}")
    n = len(rows)
    if n:
        print(f"\nMean f0_std: {sum(r['f0_std_hz'] for r in rows)/n:.1f}")
        print(f"Mean f0_range: {sum(r['f0_range_hz'] for r in rows)/n:.1f}")
        print(f"PASS_loose (f0_std<=39 AND f0_range<=128): {sum(1 for r in rows if r['f0_std_hz']<=39 and r['f0_range_hz']<=128)}/{n}")
        print(f"PASS_strict (f0_std<=30 AND f0_range<=130): {sum(1 for r in rows if r['f0_std_hz']<=30 and r['f0_range_hz']<=130)}/{n}")


if __name__ == "__main__":
    main()
