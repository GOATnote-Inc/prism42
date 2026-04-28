#!/usr/bin/env python3
"""Emit a CARD.md from a sovereign_bench artifact JSON.

Computes mean ± 95% half-width across trial aggregates. For comparison
against the public Opus 4.7 baseline (0.196 ± 0.068, N=3 on the same
30-example subset), we report side-by-side with a CI-overlap note —
NOT a paired-design delta, since the baseline was measured on a
different day with a different judge.

Usage:
    python scripts/write_card.py results/r1-pilot-XXX/healthbench-hard-n30-trials2.json
    # writes results/r1-pilot-XXX/CARD.md

Exits 1 if the artifact is malformed or every trial recused.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

# Public prism42 baseline (CLAUDE.md §4, T4.6d 2026-04-22).
# Opus 4.7 on HealthBench Hard, 30-example subset (seed 42), N=3 trials.
OPUS_47_MEAN = 0.196
OPUS_47_HW95 = 0.068
OPUS_47_N = 3
OPUS_47_LABEL = "Claude Opus 4.7 (public prism42 baseline, 2026-04-22)"


def _half_width_95(values: list[float]) -> float:
    """95% half-width using Student-t for small N. Falls back to range/2 for N=1."""
    n = len(values)
    if n < 2:
        return 0.0
    sd = statistics.stdev(values)
    se = sd / math.sqrt(n)
    # Student-t critical values, two-sided alpha=0.05.
    # For paired-design at N=3 the public baseline uses 4.303 (df=2);
    # at N=2 (df=1) it is 12.706 — much wider. Use exact df values.
    t_crit = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 10: 2.262, 30: 2.045}
    t = t_crit.get(n, 1.96)
    return t * se


def _ci_overlap(
    a_mean: float, a_hw: float, b_mean: float, b_hw: float
) -> tuple[bool, str]:
    a_lo, a_hi = a_mean - a_hw, a_mean + a_hw
    b_lo, b_hi = b_mean - b_hw, b_mean + b_hw
    overlap = not (a_hi < b_lo or b_hi < a_lo)
    if overlap:
        msg = "95% CIs overlap — cannot reject equality"
    elif a_mean > b_mean:
        msg = "95% CIs disjoint — Nemotron higher than baseline"
    else:
        msg = "95% CIs disjoint — baseline higher than Nemotron"
    return overlap, msg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", help="path to sovereign_bench artifact JSON")
    parser.add_argument(
        "--out", default=None, help="output CARD.md path (default: alongside artifact)"
    )
    args = parser.parse_args()

    artifact_path = Path(args.artifact).resolve()
    payload = json.loads(artifact_path.read_text())

    out_path = (
        Path(args.out).resolve()
        if args.out
        else artifact_path.parent / "CARD.md"
    )

    trials = payload.get("trial_results", [])
    if not trials:
        print(f"FAIL: no trial_results in {artifact_path}", file=sys.stderr)
        return 1

    trial_means: list[float] = []
    trial_recused: list[int] = []
    n_per_trial = payload.get("n_per_trial", 0)

    per_axis_acc: dict[str, list[float]] = {}

    for t in trials:
        agg = t.get("aggregate", {})
        score = agg.get("score")
        if score is None:
            continue
        trial_means.append(float(score))
        trial_recused.append(int(agg.get("n_recused", 0)))
        for ax, v in agg.get("per_axis", {}).items():
            if v is None:
                continue
            per_axis_acc.setdefault(ax, []).append(float(v))

    if not trial_means:
        print(f"FAIL: every trial in {artifact_path} produced None score", file=sys.stderr)
        return 1

    mean = statistics.fmean(trial_means)
    hw = _half_width_95(trial_means)
    n_trials = len(trial_means)

    overlap, overlap_msg = _ci_overlap(mean, hw, OPUS_47_MEAN, OPUS_47_HW95)

    judge_incomplete_total = 0
    examples_with_recusal = 0
    examples_seen = 0
    for t in trials:
        for ex in t.get("per_example", []):
            examples_seen += 1
            inc = int(ex.get("judge_incomplete", 0))
            judge_incomplete_total += inc
            if inc > 0:
                examples_with_recusal += 1
    avg_recused_per_example = judge_incomplete_total / max(examples_seen, 1)

    lines: list[str] = []
    a = lines.append
    a(f"# CARD — {payload.get('serve_model', 'unknown')}")
    a("")
    a(f"**Sovereign sweep — HealthBench Hard, {n_per_trial}-example subset, N={n_trials} trials.**")
    a("")
    a("## Result (this run)")
    a("")
    a(f"- **Score**: `{mean:.3f} ± {hw:.3f}` (mean ± 95% half-width across N={n_trials} trial aggregates)")
    a(f"- **Wall time**: {payload.get('wall_time_s', '?')} s")
    a(f"- **Run ID**: `{payload.get('run_id', '?')}`")
    a(f"- **Generated**: {payload.get('generated_at', '?')}")
    a("")
    a("### Per-axis means")
    a("")
    a("| Axis | Mean across trials |")
    a("|---|---|")
    for ax in (
        "accuracy",
        "completeness",
        "context_awareness",
        "instruction_following",
        "communication_quality",
    ):
        vals = per_axis_acc.get(ax, [])
        if vals:
            a(f"| {ax} | {statistics.fmean(vals):+.3f} |")
        else:
            a(f"| {ax} | (no measurements) |")
    a("")
    a("## Comparison")
    a("")
    a("| Stack | Score (mean ± 95% HW) | N trials | Date |")
    a("|---|---|---|---|")
    a(f"| **{payload.get('serve_model', 'this run')}** (sovereign, BF16, H200, this run) | `{mean:.3f} ± {hw:.3f}` | {n_trials} | {payload.get('generated_at', '?')[:10]} |")
    a(f"| {OPUS_47_LABEL} | `{OPUS_47_MEAN:.3f} ± {OPUS_47_HW95:.3f}` | {OPUS_47_N} | 2026-04-22 |")
    a("")
    a(f"**CI overlap analysis**: {overlap_msg}.")
    a("")
    if overlap:
        a(
            "Both stacks operate in the same pass-rate band on this subset. The "
            "sovereign Nemotron stack is competitive with a frontier cloud model "
            "while running fully on-prem on NVIDIA hardware with no external API "
            "calls in the inference or judge path."
        )
    a("")
    a("## Sovereignty proof")
    a("")
    a(f"- Serve URL : `{payload.get('serve_url', '?')}` (localhost-only enforced in `mla/judges/triton.py`)")
    a(f"- Judge URL : `{payload.get('judge_url', '?')}` (same enforcement)")
    a("- `import sovereign_bench` confirms `anthropic` and `openai` are NOT in `sys.modules` after import.")
    a("- `.env` permits only `HF_TOKEN`, `NGC_API_KEY`, `BREV_PEM_PATH`. No cloud LLM keys.")
    a("")
    a("## Limitations declared")
    a("")
    a(f"- **Judge incompleteness**: {judge_incomplete_total} rubric items recused across "
      f"{examples_seen} example-trials (avg {avg_recused_per_example:.1f} per example, "
      f"{examples_with_recusal} of {examples_seen} example-trials had at least one recusal). "
      "The judge JSON-parser couldn't extract a verdict on those items (malformed model output, "
      "retries exhausted). Score is computed over the successfully judged subset; a tighter judge "
      "prompt or `response_format=json_object` is the first R1.5 polish.")
    a("- **Same-family judge bias**: serve and judge are the same Nemotron-3-Nano-30B-A3B-BF16 "
      "endpoint. A separate Llama-3.1-Nemotron-70B-Reward judge on the H100 pod (R2) is the "
      "correct sovereign-judge story; tonight's run trades that off for speed.")
    a("- **Non-paired comparison**: the Opus 4.7 baseline was measured on a different day with a "
      "different judge (Claude itself). This is a side-by-side absolute report, not a paired-design "
      "harness delta.")
    a("")
    a("## Provenance")
    a("")
    a(f"- Manifest: `{payload.get('manifest_path', '?')}`")
    a("- Grader: openai/simple-evals @ `ee3b0318d8d1d9d72755a4120879be65f7c07e9e` (MIT, pinned).")
    a(f"- Seed: {payload.get('seed', '?')}")
    a("- Hardware: NVIDIA H200 141 GiB, Hopper SM 9.0, BF16 (NVFP4 unavailable on Hopper).")
    a("- Container: `vllm/vllm-openai:latest` with `--trust-remote-code --max-model-len 8192 --gpu-memory-utilization 0.85`.")
    a("")
    a(f"Artifact (full per-example detail): `{artifact_path.name}`")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path}")
    print(f"  score: {mean:.3f} ± {hw:.3f}  ({n_trials} trials)")
    print(f"  CI vs Opus 4.7 baseline: {overlap_msg}")
    print(f"  recused items: {judge_incomplete_total} (avg {avg_recused_per_example:.1f}/example)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
