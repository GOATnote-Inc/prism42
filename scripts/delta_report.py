#!/usr/bin/env python3
"""Emit a Markdown delta report: baseline vs. harness, sorted by magnitude.

Pure compute: loads two result JSONs — typically the T4.6 baseline
(direct Messages API) and the T4.7 harness output (Managed Agents
dialectic) — and produces a Markdown report with:

  - baseline aggregate
  - harness aggregate
  - per-example deltas sorted by absolute magnitude
  - top-5 confirmed improvements
  - regressions flagged with WARN lines

Writes to --out if given, else stdout. No network. No SDK imports.
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
    return float(agg.get("score", 0.0))


def _per_example_map(run: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in run.get("per_example") or []:
        rid = row.get("id")
        if rid is None:
            continue
        out[str(rid)] = row
    return out


def _fmt_delta(d: float) -> str:
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.4f}"


def build_report(baseline: dict, harness: dict) -> str:
    b_agg = _aggregate_score(baseline)
    h_agg = _aggregate_score(harness)
    b_map = _per_example_map(baseline)
    h_map = _per_example_map(harness)

    ids_b, ids_h = set(b_map), set(h_map)
    shared = sorted(ids_b & ids_h)
    only_b = sorted(ids_b - ids_h)
    only_h = sorted(ids_h - ids_b)

    deltas: list[tuple[str, float, float, float]] = []
    for rid in shared:
        bs = float(b_map[rid].get("score", 0.0))
        hs = float(h_map[rid].get("score", 0.0))
        deltas.append((rid, hs - bs, bs, hs))
    deltas.sort(key=lambda t: abs(t[1]), reverse=True)

    improvements = [d for d in deltas if d[1] > 0]
    regressions = [d for d in deltas if d[1] < 0]
    improvements.sort(key=lambda t: t[1], reverse=True)
    regressions.sort(key=lambda t: t[1])

    top5 = improvements[:5]
    agg_delta = h_agg - b_agg

    lines: list[str] = []
    lines.append("# Prism clinical delta report")
    lines.append("")
    lines.append(f"- baseline run_id: `{baseline.get('run_id', '?')}`")
    lines.append(f"- harness  run_id: `{harness.get('run_id', '?')}`")
    lines.append(f"- model:          `{baseline.get('model', '?')}` "
                 f"vs. `{harness.get('model', '?')}`")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- baseline aggregate: **{b_agg:.4f}**")
    lines.append(f"- harness  aggregate: **{h_agg:.4f}**")
    lines.append(f"- aggregate delta:    **{_fmt_delta(agg_delta)}**")
    lines.append(f"- n shared examples:  **{len(shared)}**")
    if only_b:
        lines.append(f"- examples only in baseline: {len(only_b)}")
    if only_h:
        lines.append(f"- examples only in harness:  {len(only_h)}")
    lines.append("")

    lines.append("## Top-5 confirmed improvements")
    lines.append("")
    if top5:
        lines.append("| id | baseline | harness | delta |")
        lines.append("|---|---|---|---|")
        for rid, d, bs, hs in top5:
            lines.append(f"| `{rid}` | {bs:.4f} | {hs:.4f} | {_fmt_delta(d)} |")
    else:
        lines.append("_no improvements observed_")
    lines.append("")

    lines.append("## Regressions")
    lines.append("")
    if regressions:
        lines.append("| id | baseline | harness | delta |")
        lines.append("|---|---|---|---|")
        for rid, d, bs, hs in regressions:
            lines.append(f"| `{rid}` | {bs:.4f} | {hs:.4f} | {_fmt_delta(d)} |")
        lines.append("")
        for rid, d, bs, hs in regressions:
            lines.append(
                f"WARN: regression on `{rid}` "
                f"(baseline={bs:.4f}, harness={hs:.4f}, delta={_fmt_delta(d)})"
            )
    else:
        lines.append("_no regressions observed_")
    lines.append("")

    lines.append("## All per-example deltas (by magnitude)")
    lines.append("")
    lines.append("| id | baseline | harness | delta |")
    lines.append("|---|---|---|---|")
    for rid, d, bs, hs in deltas:
        lines.append(f"| `{rid}` | {bs:.4f} | {hs:.4f} | {_fmt_delta(d)} |")
    lines.append("")

    if only_b or only_h:
        lines.append("## Mismatched examples")
        lines.append("")
        if only_b:
            lines.append(f"- only in baseline ({len(only_b)}): {only_b}")
        if only_h:
            lines.append(f"- only in harness  ({len(only_h)}): {only_h}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("baseline", help="Path to baseline results JSON.")
    ap.add_argument("harness", help="Path to harness results JSON.")
    ap.add_argument("--out", default=None, help="Write Markdown here (default stdout).")
    args = ap.parse_args()

    b_path = Path(args.baseline).resolve()
    h_path = Path(args.harness).resolve()
    for p in (b_path, h_path):
        if not p.exists():
            print(f"error: file not found: {p}", file=sys.stderr)
            return 1

    baseline = _load(b_path)
    harness = _load(h_path)
    report = build_report(baseline, harness)

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            f.write(report + "\n")
        print(f"wrote delta report: {out_path}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
