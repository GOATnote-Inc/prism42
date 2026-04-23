#!/usr/bin/env python3
"""Run Claude Opus 4.7 against MMLU-Medical-6, grade exact-match, write JSON.

This is the Phase B B4 runner for Prism's clinical rail. MMLU-Medical-6
is the breadth null-result control — the adversarial-dialectic harness
is not expected to move closed-book knowledge recall across six medical
subsets beyond noise. Same |delta| <= 0.01 gate as B2 MedQA.

Role assertion: null-result breadth control — same |delta| <= 0.01
gate as B2.

Subsets (all six handled in one run): anatomy, clinical_knowledge,
college_medicine, medical_genetics, professional_medicine, virology.
Any absent subset is tolerated in dry-run with a warning; commit-mode
proceeds silently over subsets actually present in the manifest.

Default behavior is --dry-run: loads the manifest, prints the planned
API call count per subset, planned seed, planned output path, and
writes a skeletal JSON marked dry_run:true. No network, no anthropic
SDK import.

Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_MMLU_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic SDK is
only imported inside do_commit(); dry-run never touches it.
scripts/check_sdk_containment.py enforces this with AST.

Manifest shape (YAML or JSON; .yaml / .yml / .json accepted):
  {"subsets": {
     "anatomy": [
       {"id": "MMLU-ANAT-001",
        "question": "...",
        "choices": ["A...", "B...", "C...", "D..."],
        "answer_letter": "B"},
       ...
     ],
     "clinical_knowledge": [...],
     "college_medicine": [...],
     "medical_genetics": [...],
     "professional_medicine": [...],
     "virology": [...],
  }}

Output JSON shape:
  {"run_id": "<uuid>",
   "seed": <int>,
   "commit": <bool>,
   "benchmark": "mmlu_medical",
   "subsets": {
     "anatomy": {"n": ..., "correct": ..., "accuracy": ...,
                 "examples": [{"id": ..., "predicted": "A",
                               "expected": "B", "correct": false}, ...]},
     ...
   },
   "aggregate": {
     "micro_accuracy": <float>,
     "n_total": <int>,
     "correct_total": <int>
   }}
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO / "results"

MODEL_ID = "claude-opus-4-7"

VALID_LETTERS = ("A", "B", "C", "D")
EXPECTED_SUBSETS = (
    "anatomy",
    "clinical_knowledge",
    "college_medicine",
    "medical_genetics",
    "professional_medicine",
    "virology",
)


def _load_manifest(path: Path) -> dict:
    """Load manifest from YAML or JSON; validate shape. Raises on malformed."""
    text = path.read_text()
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a mapping at top level")
    if "subsets" not in data or not isinstance(data["subsets"], dict):
        raise ValueError(f"{path}: manifest missing required key 'subsets' (mapping)")
    for subset_name, examples in data["subsets"].items():
        if not isinstance(examples, list):
            raise ValueError(
                f"{path}: subsets['{subset_name}'] must be a list of examples"
            )
        for i, ex in enumerate(examples):
            if not isinstance(ex, dict):
                raise ValueError(
                    f"{path}: subsets['{subset_name}'][{i}] is not a mapping"
                )
            for key in ("id", "question", "choices", "answer_letter"):
                if key not in ex:
                    raise ValueError(
                        f"{path}: subsets['{subset_name}'][{i}] "
                        f"missing required key '{key}'"
                    )
            if not isinstance(ex["choices"], list) or len(ex["choices"]) != 4:
                raise ValueError(
                    f"{path}: subsets['{subset_name}'][{i}].choices "
                    f"must be a list of 4 options"
                )
            if ex["answer_letter"] not in VALID_LETTERS:
                raise ValueError(
                    f"{path}: subsets['{subset_name}'][{i}].answer_letter "
                    f"must be one of {VALID_LETTERS}"
                )
    return data


def _subset_aggregate(per_example: list[dict]) -> dict:
    n = len(per_example)
    correct = sum(1 for e in per_example if e.get("correct"))
    accuracy = (correct / n) if n else 0.0
    return {"n": n, "correct": correct, "accuracy": accuracy}


def _micro_aggregate(subset_results: dict[str, dict]) -> dict:
    n_total = sum(s["n"] for s in subset_results.values())
    correct_total = sum(s["correct"] for s in subset_results.values())
    micro = (correct_total / n_total) if n_total else 0.0
    return {
        "micro_accuracy": micro,
        "n_total": n_total,
        "correct_total": correct_total,
    }


def _write_out(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
        + "Z"
    )


def _extract_letter(text: str) -> str | None:
    """Best-effort extract a single letter A-D from model output."""
    if not text:
        return None
    m = re.search(r"(?:answer|final|choice)\s*[:\-]?\s*\(?([ABCD])\)?", text, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([ABCD])\b", text)
    if m:
        return m.group(1).upper()
    return None


def do_dry_run(args: argparse.Namespace, run_id: str) -> int:
    """Load manifest, print plan, write skeletal dry-run JSON."""
    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out).resolve()

    try:
        manifest = _load_manifest(manifest_path)
        subsets = manifest.get("subsets", {})
        manifest_ok = True
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        # Dry-run tolerates a missing/malformed manifest so the gate-check
        # refusal tests can run against /dev/null. Emit a placeholder.
        print(f"(dry-run) manifest not usable ({exc}); writing placeholder plan")
        subsets = {}
        manifest_ok = False

    subset_counts = {name: len(exs) for name, exs in subsets.items()}
    planned_calls = sum(subset_counts.values())
    # Cost estimate: ~350 input toks + ~30 out toks per MCQ -> ~$0.008/example.
    est_cost = planned_calls * 0.008

    # Warn about absent expected subsets (dry-run only; commit-mode silent).
    missing = [s for s in EXPECTED_SUBSETS if s not in subsets]
    if missing and manifest_ok:
        print(f"(dry-run) warning: manifest missing subsets: {', '.join(missing)}")

    print("(dry-run) mmlu_medical_runner.py plan:")
    print(f"  benchmark        : mmlu_medical")
    print(f"  role             : null-result breadth control "
          f"(same |delta| <= 0.01 gate as B2)")
    print(f"  manifest         : {manifest_path}")
    print(f"  out              : {out_path}")
    print(f"  seed             : {args.seed}")
    print(f"  run_id           : {run_id}")
    print(f"  budget_cap_usd   : {args.budget_cap_usd}")
    print(f"  subsets present  : {list(subsets.keys())}")
    for name in EXPECTED_SUBSETS:
        n = subset_counts.get(name, 0)
        print(f"    {name:<24} n={n}")
    print(f"  planned api calls: {planned_calls}")
    print(f"  est cost usd     : ~{est_cost:.2f}")
    print(f"  model            : {MODEL_ID}")
    print(f"  grader           : exact-match (A/B/C/D, micro-avg across subsets)")
    print(f"  manifest status  : {'ok' if manifest_ok else 'placeholder'}")
    print("(dry-run) no network activity; no anthropic SDK import")

    subset_results_skeleton = {
        name: {"n": 0, "correct": 0, "accuracy": 0.0, "examples": []}
        for name in subsets
    }

    payload = {
        "dry_run": True,
        "commit": False,
        "run_id": run_id,
        "seed": args.seed,
        "benchmark": "mmlu_medical",
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "model": MODEL_ID,
        "budget_cap_usd": args.budget_cap_usd,
        "planned_api_calls": planned_calls,
        "subsets": subset_results_skeleton,
        "aggregate": _micro_aggregate(subset_results_skeleton)
        if subset_results_skeleton
        else {"micro_accuracy": 0.0, "n_total": 0, "correct_total": 0},
    }
    _write_out(out_path, payload)
    print(f"(dry-run) wrote skeletal results to: {out_path}")
    return 0


def do_commit(args: argparse.Namespace, run_id: str) -> int:
    """Live Messages API sweep. Reached only when both gates pass."""
    # The Anthropic client is only constructed in this function. It is
    # never imported or instantiated at module scope and never touched
    # from dry-run. scripts/check_sdk_containment.py enforces this.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out).resolve()
    manifest = _load_manifest(manifest_path)
    subsets: dict[str, list[dict]] = manifest.get("subsets", {})

    client = Anthropic()
    total_examples = sum(len(exs) for exs in subsets.values())
    print(f"(commit) run_id={run_id} model={MODEL_ID} seed={args.seed}")
    print(
        f"(commit) subsets={list(subsets.keys())} "
        f"examples={total_examples} budget_cap=${args.budget_cap_usd}"
    )

    subset_results: dict[str, dict] = {}
    total_cost_usd = 0.0
    halted_reason: str | None = None
    halted = False

    for subset_name, examples in subsets.items():
        if halted:
            break
        per_example: list[dict] = []

        for idx, example in enumerate(examples):
            if total_cost_usd >= args.budget_cap_usd:
                halted_reason = (
                    f"budget cap hit in subset '{subset_name}' at example {idx} "
                    f"(spent=${total_cost_usd:.2f} >= "
                    f"cap=${args.budget_cap_usd:.2f})"
                )
                print(f"(commit) HALT: {halted_reason}")
                halted = True
                break

            choices = example["choices"]
            letters = VALID_LETTERS[: len(choices)]
            choice_block = "\n".join(
                f"{ltr}. {choice}" for ltr, choice in zip(letters, choices)
            )
            prompt = (
                f"{example['question']}\n\n"
                f"{choice_block}\n\n"
                f"Respond with only the letter (A, B, C, or D) of the correct answer."
            )

            # Opus 4.7 does not expose a seed parameter on messages.create
            # (CLAUDE.md §8). task-budgets-2026-03-13 is a managed-agent-
            # thread concern; client-side --budget-cap-usd is authoritative.
            response = client.messages.create(
                model=MODEL_ID,
                max_tokens=16,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = ""
            for block in getattr(response, "content", []) or []:
                if getattr(block, "type", None) == "text":
                    response_text += getattr(block, "text", "")

            predicted = _extract_letter(response_text)
            expected = example["answer_letter"]
            correct = predicted == expected

            usage = getattr(response, "usage", None)
            in_toks = getattr(usage, "input_tokens", 0) if usage else 0
            out_toks = getattr(usage, "output_tokens", 0) if usage else 0
            cost = (in_toks / 1_000_000) * 15.0 + (out_toks / 1_000_000) * 75.0
            total_cost_usd += cost

            per_example.append(
                {
                    "id": example.get("id", f"{subset_name}-ex-{idx}"),
                    "predicted": predicted,
                    "expected": expected,
                    "correct": bool(correct),
                    "input_tokens": in_toks,
                    "output_tokens": out_toks,
                    "est_cost_usd": round(cost, 6),
                }
            )
            print(
                f"(commit) [{subset_name} {idx + 1}/{len(examples)}] "
                f"id={example.get('id', '?')} pred={predicted} exp={expected} "
                f"{'OK' if correct else 'MISS'} cum=${total_cost_usd:.2f}"
            )

        agg = _subset_aggregate(per_example)
        subset_results[subset_name] = {
            "n": agg["n"],
            "correct": agg["correct"],
            "accuracy": agg["accuracy"],
            "examples": per_example,
        }

    payload = {
        "dry_run": False,
        "commit": True,
        "run_id": run_id,
        "seed": args.seed,
        "benchmark": "mmlu_medical",
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "model": MODEL_ID,
        "budget_cap_usd": args.budget_cap_usd,
        "total_cost_usd": round(total_cost_usd, 4),
        "halted_reason": halted_reason,
        "subsets": subset_results,
        "aggregate": _micro_aggregate(subset_results),
    }
    _write_out(out_path, payload)
    print(f"(commit) wrote results to: {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--manifest",
        required=True,
        help="Path to MMLU-Medical-6 manifest (YAML or JSON).",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Path to write results JSON (e.g. results/mmlu-med-opus47-NAME.json).",
    )
    ap.add_argument("--seed", type=int, default=42, help="Seed for Messages API calls.")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run for real. Requires PRISM_MMLU_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--run-id",
        default=None,
        help="Optional UUID for this run; generated if absent.",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=15.0,
        help="Hard-stop if cumulative cost exceeds this (default 15.0, larger aggregate).",
    )
    args = ap.parse_args()

    run_id = args.run_id or str(uuid.uuid4())

    if args.commit and os.environ.get("PRISM_MMLU_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_MMLU_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args, run_id)

    return do_dry_run(args, run_id)


if __name__ == "__main__":
    sys.exit(main())
