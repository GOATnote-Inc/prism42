#!/usr/bin/env python3
"""Aggregate N healthbench_runner result JSONs into mean ± 95% CI half-width.

Pure compute: loads N >= 2 `scripts/healthbench_runner.py` output JSONs
and reports the mean aggregate score, sample standard deviation, and
two-sided 95% CI half-width across the runs.

Replaces the retired `compare_runs.py --tolerance 0.02` two-run absolute
gate (see `docs/seed-stability-2026-04-22.md` for the variance analysis
that motivated the switch).

Usage:

    scripts/aggregate_runs.py results/baseline-42.json \\
                              results/baseline-43.json \\
                              results/baseline-44.json

Exits 0 with a single-line report; exits 1 on malformed input or when the
runs disagree on the set of example IDs (structural mismatch).

No network. No SDK imports. Pure read + arithmetic.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# Student's t critical values (two-sided, alpha=0.05).
# Looked up, not computed here to keep the script stdlib-only.
_T_CRIT_95 = {
    2: 12.706,
    3: 4.303,
    4: 3.182,
    5: 2.776,
    6: 2.571,
    7: 2.447,
    8: 2.365,
    9: 2.306,
    10: 2.262,
}


def _load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _aggregate_score(run: dict) -> float:
    agg = run.get("aggregate") or {}
    score = agg.get("score")
    if score is None:
        raise ValueError(f"run missing aggregate.score: {run.get('run_id', '<no run_id>')}")
    return float(score)


def _id_set(run: dict) -> set[str]:
    return {str(row.get("id")) for row in (run.get("per_example") or []) if row.get("id") is not None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="Two or more results JSON paths.")
    args = ap.parse_args()

    if len(args.runs) < 2:
        print("error: need at least 2 runs for a CI", file=sys.stderr)
        return 1

    scores: list[float] = []
    id_sets: list[set[str]] = []
    for r in args.runs:
        p = Path(r).resolve()
        if not p.exists():
            print(f"error: file not found: {p}", file=sys.stderr)
            return 1
        run = _load(p)
        scores.append(_aggregate_score(run))
        id_sets.append(_id_set(run))

    for i in range(1, len(id_sets)):
        if id_sets[i] != id_sets[0]:
            only_first = sorted(id_sets[0] - id_sets[i])[:5]
            only_other = sorted(id_sets[i] - id_sets[0])[:5]
            print(f"error: id-set mismatch between run[0] and run[{i}]", file=sys.stderr)
            if only_first:
                print(f"  only in run[0]: {only_first}", file=sys.stderr)
            if only_other:
                print(f"  only in run[{i}]: {only_other}", file=sys.stderr)
            return 1

    n = len(scores)
    mean = sum(scores) / n
    # Sample variance (n-1 denominator) — small-sample estimate.
    var = sum((s - mean) ** 2 for s in scores) / (n - 1)
    sd = math.sqrt(var)
    sem = sd / math.sqrt(n)
    t = _T_CRIT_95.get(n)
    if t is None:
        print(f"error: no t-critical table entry for n={n}; extend _T_CRIT_95 if needed", file=sys.stderr)
        return 1
    ci_half = t * sem

    print(f"n={n}  mean={mean:.4f}  sd={sd:.4f}  sem={sem:.4f}  95% CI half-width={ci_half:.4f}")
    print(f"per-run aggregates: {[round(s, 4) for s in scores]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
