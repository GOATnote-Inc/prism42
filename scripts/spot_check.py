#!/usr/bin/env python3
"""Print N random graded examples from a result JSON, seeded for repeatability.

Pure read: loads a `scripts/healthbench_runner.py` output JSON, selects
N examples using a seeded random choice, and prints question + response
+ score for each. Used by the T4.6 verification gate (spec §5 T4.6):

    make verify-baseline
    # ...
    python scripts/spot_check.py results/baseline-1.json --n 3

No network. No SDK imports. Pure read + print.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _render_example(row: dict) -> str:
    lines: list[str] = []
    rid = row.get("id", "?")
    score = row.get("score", 0.0)
    stubbed = row.get("stub_grader", False)
    lines.append(f"--- example id={rid} score={score:.3f}"
                 f"{' (STUB grader)' if stubbed else ''} ---")
    prompt = row.get("prompt") or row.get("question")
    if prompt:
        lines.append("Q:")
        lines.append(str(prompt))
    else:
        msgs = row.get("messages") or []
        if msgs:
            lines.append("messages:")
            for m in msgs:
                role = m.get("role", "?") if isinstance(m, dict) else "?"
                content = m.get("content", "") if isinstance(m, dict) else str(m)
                lines.append(f"  [{role}] {content}")
    response = row.get("response_text") or row.get("response")
    if response:
        lines.append("A:")
        lines.append(str(response))
    per_axis = row.get("per_axis") or {}
    if per_axis:
        axes_s = ", ".join(f"{k}={v:.3f}" for k, v in sorted(per_axis.items()))
        lines.append(f"per_axis: {axes_s}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("results", help="Path to a results JSON.")
    ap.add_argument("--n", type=int, default=3, help="Number of examples to sample (default 3).")
    ap.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    args = ap.parse_args()

    path = Path(args.results).resolve()
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    data = _load(path)
    rows = data.get("per_example") or []
    if not rows:
        print("(spot-check) no per_example rows in results; nothing to sample")
        return 0

    rng = random.Random(args.seed)
    n = min(args.n, len(rows))
    sample = rng.sample(rows, n)

    print(f"spot-check: sampled {n} of {len(rows)} examples (seed={args.seed})")
    print(f"run_id={data.get('run_id', '?')} model={data.get('model', '?')} "
          f"dry_run={data.get('dry_run', '?')}")
    print()
    for row in sample:
        print(_render_example(row))
        print()
    print("(spot-check) done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
