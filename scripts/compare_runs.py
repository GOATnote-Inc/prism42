#!/usr/bin/env python3
"""Compare two result JSONs for seed-stability reproducibility.

Pure compute: loads two `scripts/healthbench_runner.py` output JSONs and
checks that the aggregate scores and per-example scores agree within a
tolerance. Used by the T4.6 verification gate (spec §5 T4.6):

    make verify-baseline
    # must print: "baseline reproducible (delta=<d> < 0.02), spot-check passed"

No network. No SDK imports. Pure read + arithmetic.

Exits 0 on reproducible runs, 1 on aggregate-delta >= tolerance or on
structural mismatch (different example IDs, different lengths, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _aggregate_score(run: dict) -> float:
    agg = run.get("aggregate") or {}
    score = agg.get("score")
    if score is None:
        raise ValueError("run missing aggregate.score")
    return float(score)


def _per_example_map(run: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in run.get("per_example") or []:
        rid = row.get("id")
        if rid is None:
            continue
        out[str(rid)] = float(row.get("score", 0.0))
    return out


def compare(run1: dict, run2: dict, tolerance: float) -> tuple[bool, float, list[str]]:
    """Return (ok, aggregate_delta, messages)."""
    msgs: list[str] = []

    a1 = _aggregate_score(run1)
    a2 = _aggregate_score(run2)
    delta = abs(a1 - a2)

    m1 = _per_example_map(run1)
    m2 = _per_example_map(run2)
    ids1, ids2 = set(m1), set(m2)
    if ids1 != ids2:
        only1 = sorted(ids1 - ids2)
        only2 = sorted(ids2 - ids1)
        if only1:
            msgs.append(f"examples only in run1: {only1[:5]}{'...' if len(only1) > 5 else ''}")
        if only2:
            msgs.append(f"examples only in run2: {only2[:5]}{'...' if len(only2) > 5 else ''}")

    max_per_ex_delta = 0.0
    worst_id: str | None = None
    for rid in ids1 & ids2:
        d = abs(m1[rid] - m2[rid])
        if d > max_per_ex_delta:
            max_per_ex_delta = d
            worst_id = rid
    if worst_id is not None:
        msgs.append(
            f"largest per-example delta: {max_per_ex_delta:.4f} on id={worst_id}"
        )

    ok = delta < tolerance and ids1 == ids2
    return ok, delta, msgs


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("run1", help="First results JSON (e.g. results/baseline-1.json).")
    ap.add_argument("run2", help="Second results JSON (e.g. results/baseline-2.json).")
    ap.add_argument(
        "--tolerance",
        type=float,
        default=0.02,
        help="Aggregate-score delta threshold (default 0.02).",
    )
    args = ap.parse_args()

    p1 = Path(args.run1).resolve()
    p2 = Path(args.run2).resolve()
    for p in (p1, p2):
        if not p.exists():
            print(f"error: file not found: {p}", file=sys.stderr)
            return 1

    run1 = _load(p1)
    run2 = _load(p2)

    ok, delta, msgs = compare(run1, run2, args.tolerance)
    for m in msgs:
        print(f"  {m}")

    if ok:
        print(f"reproducible: delta={delta:.3f} (< {args.tolerance})")
        return 0
    print(f"NOT reproducible: delta={delta:.3f} (>= {args.tolerance})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
