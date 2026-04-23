#!/usr/bin/env python3
"""Regenerate per_axis scores on an existing results JSON from its
judge-log.jsonl, without calling any API.

Reason this exists: pre-2026-04-23, `_per_axis_scores` in
scripts/healthbench_runner.py bucketed rubric items by raw tag, so
HealthBench Hard items whose tags use the canonical prefixed form
(`axis:accuracy`, `axis:completeness`, etc.) never matched the bare
`accuracy` lookup. Every baseline and harness-sweep run wrote
per_axis = {axis: 0.0 for all 5 axes} while the overall score was
correctly non-zero. The T4.7b Stage 2 pilot surfaced this when the
paired per-axis delta table showed all-zero R4 ship-gate rows.

The grader is already fixed — this script re-applies the fix to
artifacts that were produced BEFORE the fix, so we don't have to pay
the API again. It works by:

  1. Load the target results JSON (baseline-opus47-seed42.json,
     harness-sweep-<stamp>/aggregate.json, etc.).
  2. Load the accompanying judge-log-*.jsonl (written during the
     original run; one JSON record per judge call).
  3. Load the clinical_subset.yaml to recover each example's rubric
     items and their tags.
  4. For each per_example row: match the judge verdicts back to
     rubric items by criterion text (the unique key), re-run
     `_per_axis_scores` with the fixed tag normalizer, update the
     per_example row's per_axis field.
  5. Re-aggregate across all examples and rewrite the target JSON.

Pure compute. No SDK imports. No network. Idempotent — running twice
yields the same output.

Usage:
  python scripts/regrade_per_axis.py \\
      --results results/baseline-opus47-seed42.json \\
      --judge-log results/judge-log-baseline-seed42-20260422T101603Z.jsonl \\
      --subset corpus/clinical_subset.yaml
      [--out results/baseline-opus47-seed42.regraded.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent

if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from healthbench_runner import (  # noqa: E402
    HEALTHBENCH_AXES,
    RubricItem,
    _aggregate,
    _per_axis_scores,
)


def _load_subset_rubrics(subset_path: Path) -> dict[str, list[dict]]:
    """Return {example_id: list-of-rubric-item-dicts} from clinical_subset.yaml."""
    doc = yaml.safe_load(subset_path.read_text()) or {}
    out: dict[str, list[dict]] = {}
    for ex in doc.get("examples") or []:
        eid = ex.get("id")
        if eid:
            out[eid] = ex.get("rubrics") or []
    return out


def _index_judge_log(log_path: Path) -> dict[str, bool]:
    """Return {criterion_text: criteria_met} from the judge-log.

    The log is JSONL with one record per judge call. Records with
    criteria_met=None (recused / judge failure) are skipped; they'll
    fall through to a default 'not met' in the reconstruction.
    """
    by_criterion: dict[str, bool] = {}
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            crit = rec.get("criterion")
            parsed = rec.get("parsed") or {}
            met = parsed.get("criteria_met")
            if isinstance(crit, str) and isinstance(met, bool):
                # Keep the LAST occurrence — retries overwrite prior attempts.
                by_criterion[crit] = met
    return by_criterion


def _rebucket_example(
    example_rubrics: list[dict],
    judge_verdicts: dict[str, bool],
) -> tuple[dict, int]:
    """Reconstruct per_axis + overall score for one example.

    Returns (per_axis_dict, n_items_matched). Rubric items whose
    criterion doesn't appear in the judge-log are dropped (they were
    recused in the original run).
    """
    items = [RubricItem.from_dict(r) for r in example_rubrics]
    responses: list[dict] = []
    kept_items: list[RubricItem] = []
    for item in items:
        # Match on the leading 200 chars of criterion — the log
        # truncates criteria at 200 chars per healthbench_runner's
        # audit-log policy.
        key = item.criterion[:200]
        met = judge_verdicts.get(item.criterion) or judge_verdicts.get(key)
        if met is None:
            continue
        kept_items.append(item)
        responses.append({"criteria_met": bool(met), "explanation": ""})
    if not kept_items:
        return ({a: 0.0 for a in HEALTHBENCH_AXES}, 0)
    per_axis = _per_axis_scores(kept_items, responses)
    return (per_axis, len(kept_items))


def _regrade(
    results: dict,
    judge_verdicts: dict[str, bool],
    subset_rubrics: dict[str, list[dict]],
) -> dict:
    """Return a new results dict with per_example per_axis + aggregate regraded."""
    new = json.loads(json.dumps(results))  # deep copy
    per_example = new.get("per_example") or []
    n_regraded = 0
    n_missing_rubric = 0
    for row in per_example:
        rid = row.get("id") or row.get("case_id")
        rubrics = subset_rubrics.get(rid)
        if rubrics is None:
            n_missing_rubric += 1
            continue
        per_axis, n_items = _rebucket_example(rubrics, judge_verdicts)
        row["per_axis"] = per_axis
        row["per_axis_regraded_items"] = n_items
        n_regraded += 1

    # Re-aggregate overall per_axis from the per_example rows.
    agg = _aggregate(per_example)
    # If original had a nested aggregate structure (baseline shape), keep it.
    if isinstance(new.get("aggregate"), dict):
        new["aggregate"] = agg
    new["per_axis_regrade"] = {
        "n_regraded": n_regraded,
        "n_missing_rubric": n_missing_rubric,
        "axes": HEALTHBENCH_AXES,
    }
    return new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--results", required=True, help="Path to results JSON to regrade.")
    ap.add_argument("--judge-log", required=True, help="Path to judge-log-*.jsonl from that run.")
    ap.add_argument("--subset", default=str(REPO / "corpus" / "clinical_subset.yaml"),
                    help="Clinical subset YAML with rubric items.")
    ap.add_argument("--out", default=None,
                    help="Output path. Default: <results>.regraded.json")
    args = ap.parse_args(argv)

    results_path = Path(args.results).resolve()
    log_path = Path(args.judge_log).resolve()
    subset_path = Path(args.subset).resolve()
    if args.out:
        out_path = Path(args.out).resolve()
    else:
        out_path = results_path.with_suffix(".regraded" + results_path.suffix)

    for p, label in ((results_path, "results"), (log_path, "judge-log"), (subset_path, "subset")):
        if not p.exists():
            print(f"error: {label} not found: {p}", file=sys.stderr)
            return 1

    results = json.loads(results_path.read_text())
    judge_verdicts = _index_judge_log(log_path)
    subset_rubrics = _load_subset_rubrics(subset_path)

    print(f"loaded: {len(results.get('per_example') or [])} per_example rows, "
          f"{len(judge_verdicts)} judge verdicts, "
          f"{len(subset_rubrics)} rubric sets")

    regraded = _regrade(results, judge_verdicts, subset_rubrics)
    rep = regraded.get("per_axis_regrade") or {}
    print(f"regraded: {rep.get('n_regraded')} examples; "
          f"missing rubric for {rep.get('n_missing_rubric')}")

    # Surface the fresh aggregate per_axis so the user can sanity-check
    # before committing the regraded file.
    agg_per_axis = (regraded.get("aggregate") or {}).get("per_axis") or {}
    print("regraded per_axis (aggregate):")
    for axis in HEALTHBENCH_AXES:
        v = agg_per_axis.get(axis)
        v_s = f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
        print(f"  {axis:24s} {v_s}")

    out_path.write_text(json.dumps(regraded, indent=2, sort_keys=True, default=str) + "\n")
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
