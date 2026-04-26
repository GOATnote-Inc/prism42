#!/usr/bin/env python3
"""Re-parse cycle-2j metrics.json. Standalone for repro auditing."""
from __future__ import annotations
import json
import statistics
import sys
from pathlib import Path

INPUT = Path(__file__).parent / "metrics.json"


def p_pct(xs: list[int], pct: int) -> int | None:
    if not xs:
        return None
    sxs = sorted(xs)
    idx = max(0, int(len(sxs) * pct / 100) - 1)
    return int(sxs[min(idx, len(sxs) - 1)])


def main() -> int:
    raw = json.loads(INPUT.read_text())
    print("Cycle-2j metrics aggregator")
    print(f"Loaded: {INPUT}")
    print(f"ts_utc: {raw['ts_utc']}")
    print()
    rows = []
    for cond, by_phrase in raw["metrics_per_condition"].items():
        ttfbs = [m["ttfb_ms"] for m in by_phrase.values() if m.get("success")]
        totals = [m["total_ms"] for m in by_phrase.values() if m.get("success")]
        peaks = [m["peak"] for m in by_phrase.values() if m.get("success")]
        durs = [m["duration_s"] for m in by_phrase.values() if m.get("success")]
        succ = sum(1 for m in by_phrase.values() if m.get("success"))
        rows.append((
            cond, succ,
            int(statistics.median(ttfbs)) if ttfbs else None,
            p_pct(ttfbs, 95),
            int(statistics.median(totals)) if totals else None,
            p_pct(totals, 95),
            min(peaks) if peaks else None,
            max(peaks) if peaks else None,
            round(sum(durs), 3) if durs else None,
        ))
    hdr = ("cond", "n_ok", "ttfb_p50", "ttfb_p95", "total_p50", "total_p95",
           "peak_min", "peak_max", "tot_dur_s")
    print("{:<10}{:>6}{:>10}{:>10}{:>11}{:>11}{:>10}{:>10}{:>11}".format(*hdr))
    for r in rows:
        print("{:<10}{:>6}{:>10}{:>10}{:>11}{:>11}{:>10}{:>10}{:>11}".format(
            *[("-" if x is None else x) for x in r]
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
