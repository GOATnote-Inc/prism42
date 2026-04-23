#!/usr/bin/env python3
"""Render a markdown delta report from a harness_sweep output directory.

Consumes `results/harness-sweep-<stamp>/aggregate.json` +
`per_example.json` (paired form produced by `scripts/harness_sweep.py`)
and emits a decision-ready markdown report highlighting the R4 ship-gate
per-axis paired deltas plus overall delta, improvements, regressions,
and judge-recusal counts.

Pure compute. No SDK imports. No network.

Usage:
  python scripts/sweep_delta_report.py <sweep-dir> [--out PATH]

The sweep directory MUST contain both:
  - aggregate.json  (overall + paired_delta if --baseline was passed)
  - per_example.json (list of per-session rows)

If `paired_delta` is absent from aggregate.json, the report falls back
to a baseline-less summary (overall aggregate + per-example rows, no
ship-gate table).

The R4 per-axis ship-gate table reports, for each HealthBench Hard axis,
the paired mean Δ, 95% CI half-width, and a ship decision. Per
`docs/sota-portfolio.md` §R4, a skill ships when its axis Δ >= 0.05 AND
the 95% CI excludes zero:
  clinical-review        → communication axis
  differential-diagnosis → completeness axis
  dosage-check           → accuracy axis

The report is physician-reviewable: every score comes from the
simple-evals rubric grader, every judge call is in judge-log.jsonl,
every harness-modified response is in modified/<id>.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# docs/sota-portfolio.md §R4 — skill → axis mapping for the ship-gate.
# Axis names match HEALTHBENCH_AXES in healthbench_runner.py — in turn
# match the upstream HealthBench rubric tags (axis:communication_quality,
# not axis:communication; T4.7b Stage 3 discovery).
R4_SKILL_AXIS: tuple[tuple[str, str], ...] = (
    ("clinical-review", "communication_quality"),
    ("differential-diagnosis", "completeness"),
    ("dosage-check", "accuracy"),
)

# R4 ship-gate thresholds.
R4_MIN_DELTA = 0.05


def _fmt_delta(x: float | None) -> str:
    if x is None:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.4f}"


def _fmt_ci(stats: dict) -> str:
    lo = stats.get("ci95_low")
    hi = stats.get("ci95_high")
    if lo is None or hi is None:
        return "(n<2)"
    return f"[{lo:+.4f}, {hi:+.4f}]"


def _ship_decision(stats: dict, min_delta: float = R4_MIN_DELTA) -> str:
    mean = stats.get("mean")
    excludes = stats.get("excludes_zero")
    if mean is None:
        return "no data"
    if excludes is None:
        return "n<2 — cannot gate"
    if mean >= min_delta and excludes:
        return "**SHIP** (Δ≥0.05 AND CI excludes 0)"
    if excludes and mean > 0:
        return "signal; Δ below 0.05 threshold"
    if mean > 0:
        return "directional only; CI includes 0"
    return "no lift"


def _load_sweep(sweep_dir: Path) -> tuple[dict, list[dict]]:
    agg_path = sweep_dir / "aggregate.json"
    pex_path = sweep_dir / "per_example.json"
    if not agg_path.exists():
        raise FileNotFoundError(f"missing {agg_path}")
    aggregate = json.loads(agg_path.read_text())
    per_example: list[dict] = []
    if pex_path.exists():
        per_example = json.loads(pex_path.read_text())
    return aggregate, per_example


def build_report(aggregate: dict, per_example: list[dict], sweep_dir: Path) -> str:
    lines: list[str] = []
    lines.append("# Prism — T4.7b harness sweep delta report")
    lines.append("")
    lines.append(f"- sweep dir:     `{sweep_dir.relative_to(REPO) if sweep_dir.is_relative_to(REPO) else sweep_dir}`")
    lines.append(f"- run_id:        `{aggregate.get('run_id', '?')}`")
    lines.append(f"- stamp:         `{aggregate.get('stamp', '?')}`")
    lines.append(f"- coordinator:   `{aggregate.get('coordinator_id', '?')}` v{aggregate.get('coordinator_version', '?')}")
    lines.append(f"- judge model:   `{aggregate.get('judge_model', '?')}`")
    lines.append(f"- total cost:    **${aggregate.get('total_cost_usd', 0.0):.4f}**")
    if aggregate.get("halted_reason"):
        lines.append(f"- HALTED:        `{aggregate['halted_reason']}`")
    lines.append("")

    agg = aggregate.get("aggregate") or {}
    lines.append("## Sweep aggregate")
    lines.append("")
    lines.append(f"- n examples:   {agg.get('n', 0)}")
    lines.append(f"- n scored:     {agg.get('n_scored', 0)}")
    lines.append(f"- n recused:    {agg.get('n_recused', 0)}")
    lines.append(f"- overall score: **{agg.get('score')}**")
    pa = agg.get("per_axis") or {}
    if pa:
        lines.append("")
        lines.append("| axis | harness score |")
        lines.append("|---|---|")
        for axis, val in pa.items():
            val_s = f"{val:.4f}" if isinstance(val, (int, float)) else str(val)
            lines.append(f"| {axis} | {val_s} |")
    lines.append("")

    pd = aggregate.get("paired_delta")
    if pd and "error" not in pd:
        lines.append("## R4 ship-gate — paired Δ by axis")
        lines.append("")
        lines.append("Per `docs/sota-portfolio.md` §R4, a skill ships when its axis Δ ≥ 0.05 AND the 95% CI excludes 0.")
        lines.append("")
        lines.append(f"- baseline:      `{pd.get('baseline_artifact', '?')}`")
        lines.append(f"- n matched:     {pd.get('n_matched', 0)}")
        missing = pd.get("missing_in_baseline") or []
        if missing:
            lines.append(f"- missing in baseline: {missing}")
        lines.append("")
        lines.append("| skill | axis | mean Δ | 95% CI | n | decision |")
        lines.append("|---|---|---|---|---|---|")
        per_axis = pd.get("per_axis_delta") or {}
        for skill, axis in R4_SKILL_AXIS:
            stats = per_axis.get(axis) or {}
            mean = stats.get("mean")
            mean_s = _fmt_delta(mean) if mean is not None else "—"
            ci_s = _fmt_ci(stats)
            n_s = str(stats.get("n", 0))
            dec = _ship_decision(stats)
            lines.append(f"| `{skill}` | {axis} | {mean_s} | {ci_s} | {n_s} | {dec} |")
        lines.append("")
        od = pd.get("overall_delta") or {}
        lines.append("### Overall paired Δ (all rubric items, all axes)")
        lines.append("")
        lines.append(f"- mean Δ:        **{_fmt_delta(od.get('mean'))}**")
        lines.append(f"- 95% CI:        {_fmt_ci(od)}")
        lines.append(f"- excludes zero: **{od.get('excludes_zero')}**")
        lines.append(f"- n paired:      {od.get('n', 0)}")
        lines.append("")
    elif pd and "error" in pd:
        lines.append("## Paired delta")
        lines.append("")
        lines.append(f"_paired delta unavailable:_ `{pd.get('error')}`")
        lines.append("")

    # Per-example improvement / regression tables — only renders when
    # paired_delta is present (needs a baseline to compute deltas). Gives
    # reviewers a quick read on where the harness wins, where it loses,
    # and the magnitude of each.
    pd_local = aggregate.get("paired_delta")
    if per_example and pd_local and "error" not in pd_local:
        base_path = pd_local.get("baseline_artifact")
        b_rows: dict[str, dict] = {}
        try:
            if base_path and Path(base_path).exists():
                b = json.loads(Path(base_path).read_text())
                b_rows = {r.get("id"): r for r in (b.get("per_example") or []) if r.get("id")}
        except (json.JSONDecodeError, OSError):
            b_rows = {}
        pairs: list[tuple[str, float, float | None, float | None, int]] = []
        for r in per_example:
            cid = r.get("case_id") or r.get("id")
            b = b_rows.get(cid)
            if b is None:
                continue
            h = r.get("score")
            bs = b.get("score")
            if h is None or bs is None:
                continue
            pairs.append((cid, float(h) - float(bs), float(bs), float(h), r.get("modified_len", 0)))
        n_improve = sum(1 for p in pairs if p[1] > 0)
        n_regress = sum(1 for p in pairs if p[1] < 0)
        n_tie = sum(1 for p in pairs if p[1] == 0)

        lines.append("## Per-example paired deltas")
        lines.append("")
        lines.append(f"- improvements: **{n_improve}** / {len(pairs)}")
        lines.append(f"- regressions:  **{n_regress}** / {len(pairs)}")
        lines.append(f"- ties:         **{n_tie}** / {len(pairs)}")
        lines.append("")

        # Largest improvements first
        improvements = sorted([p for p in pairs if p[1] > 0], key=lambda t: -t[1])
        if improvements:
            lines.append("### Top 5 improvements")
            lines.append("")
            lines.append("| case_id | baseline | harness | Δ | mod_len |")
            lines.append("|---|---|---|---|---|")
            for cid, d, bs, hs, ml in improvements[:5]:
                lines.append(f"| `{cid}` | {bs:.4f} | {hs:.4f} | **{_fmt_delta(d)}** | {ml} |")
            lines.append("")

        # All regressions (sorted worst first) — surfaces every case the
        # harness hurt, so reviewers can triage.
        regressions = sorted([p for p in pairs if p[1] < 0], key=lambda t: t[1])
        if regressions:
            lines.append("### Regressions")
            lines.append("")
            lines.append("| case_id | baseline | harness | Δ | mod_len |")
            lines.append("|---|---|---|---|---|")
            for cid, d, bs, hs, ml in regressions:
                lines.append(f"| `{cid}` | {bs:.4f} | {hs:.4f} | **{_fmt_delta(d)}** | {ml} |")
            lines.append("")

    if per_example:
        lines.append("## Per-example rows (score + extraction status)")
        lines.append("")
        lines.append("| case_id | score | tokens (in/out) | modified_len | cost | marker |")
        lines.append("|---|---|---|---|---|---|")
        for row in per_example:
            score = row.get("score")
            score_s = f"{score:.4f}" if isinstance(score, (int, float)) else "RECUSED"
            in_t = row.get("input_tokens", 0)
            out_t = row.get("output_tokens", 0)
            mod_len = row.get("modified_len", 0)
            cost = row.get("session_cost_usd", 0.0)
            marker = "✓" if row.get("final_marker") else "✗"
            lines.append(
                f"| `{row.get('case_id', '?')}` | {score_s} | {in_t}/{out_t} | {mod_len} | ${cost:.4f} | {marker} |"
            )
        lines.append("")

        # Recused examples deserve an explicit callout so the reviewer
        # knows these rows did not contribute to the aggregate.
        recused = [r for r in per_example if r.get("score") is None]
        if recused:
            lines.append("### Recused examples")
            lines.append("")
            for r in recused:
                reason = "no fenced block extracted" if r.get("modified_len", 0) == 0 else "judge failure"
                lines.append(f"- `{r.get('case_id')}` — {reason}; see transcript `{r.get('transcript_path', '?')}`")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Generated by `scripts/sweep_delta_report.py`. Numbers come from simple-evals@ee3b0318 via `_real_grader`; every judge call is logged in `judge-log.jsonl` under the sweep dir._")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "sweep_dir",
        help="Path to a results/harness-sweep-<stamp>/ directory.",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Write markdown report here. Default: <sweep_dir>/delta-report.md",
    )
    args = ap.parse_args(argv)

    sweep_dir = Path(args.sweep_dir).resolve()
    if not sweep_dir.is_dir():
        print(f"error: not a directory: {sweep_dir}", file=sys.stderr)
        return 1

    try:
        aggregate, per_example = _load_sweep(sweep_dir)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = build_report(aggregate, per_example, sweep_dir)

    out_path = Path(args.out).resolve() if args.out else (sweep_dir / "delta-report.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n")
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
