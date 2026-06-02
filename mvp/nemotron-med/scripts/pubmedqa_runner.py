#!/usr/bin/env python3
"""Run Claude Opus 4.7 against PubMedQA (PQA-L), grade exact-match, write JSON.

This is the Phase B B3 runner for Prism's clinical rail. PubMedQA is
the RAG-validator anchor: baseline (no retrieval) vs. R1-augmented run
(MedlinePlus / PubMed retrieval before answering). Expected lift >=
10pp when R1 is correctly wired. If lift is <5pp the retriever is not
firing or its context is being ignored.

Role assertion: RAG-validator anchor — R1/R2 ship only when lift >=
10pp over no-retrieval baseline.

Default behavior is --dry-run: loads the manifest, prints the planned
API call count, planned seed, planned output path, and writes a
skeletal JSON marked dry_run:true. No network, no anthropic SDK import.

Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_PUBMEDQA_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic SDK is
only imported inside do_commit(); dry-run never touches it.
scripts/check_sdk_containment.py enforces this with AST.

Manifest shape (YAML or JSON; .yaml / .yml / .json accepted):
  {"examples": [
     {"id": "PQ-L-001",
      "question": "...",
      "context": "<abstract>",
      "answer_yn": "yes" | "no" | "maybe"},
     ...
  ]}

Output JSON shape:
  {"run_id": "<uuid>",
   "seed": <int>,
   "commit": <bool>,
   "benchmark": "pubmedqa",
   "examples": [
     {"id": ..., "predicted": "yes", "expected": "no", "correct": false},
     ...
   ],
   "aggregate": {
     "accuracy": <float 0..1>,
     "n": <int>,
     "correct": <int>
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

VALID_ANSWERS = ("yes", "no", "maybe")


def _load_manifest(path: Path) -> dict:
    """Load manifest from YAML or JSON; validate shape. Raises on malformed."""
    text = path.read_text()
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a mapping at top level")
    if "examples" not in data or not isinstance(data["examples"], list):
        raise ValueError(f"{path}: manifest missing required key 'examples' (list)")
    for i, ex in enumerate(data["examples"]):
        if not isinstance(ex, dict):
            raise ValueError(f"{path}: examples[{i}] is not a mapping")
        for key in ("id", "question", "context", "answer_yn"):
            if key not in ex:
                raise ValueError(f"{path}: examples[{i}] missing required key '{key}'")
        if ex["answer_yn"] not in VALID_ANSWERS:
            raise ValueError(
                f"{path}: examples[{i}].answer_yn must be one of {VALID_ANSWERS}"
            )
    return data


def _aggregate(per_example: list[dict]) -> dict:
    n = len(per_example)
    correct = sum(1 for e in per_example if e.get("correct"))
    accuracy = (correct / n) if n else 0.0
    return {"accuracy": accuracy, "n": n, "correct": correct}


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


def _extract_answer(text: str) -> str | None:
    """Best-effort extract yes/no/maybe from model output."""
    if not text:
        return None
    lower = text.lower()
    # Look for "Answer: yes/no/maybe" first.
    m = re.search(r"(?:answer|final)\s*[:\-]?\s*\(?(yes|no|maybe)\)?", lower)
    if m:
        return m.group(1)
    # Fall back to the first standalone yes/no/maybe token.
    m = re.search(r"\b(yes|no|maybe)\b", lower)
    if m:
        return m.group(1)
    return None


def do_dry_run(args: argparse.Namespace, run_id: str) -> int:
    """Load manifest, print plan, write skeletal dry-run JSON."""
    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out).resolve()

    try:
        manifest = _load_manifest(manifest_path)
        examples = manifest.get("examples", [])
        manifest_ok = True
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        # Dry-run tolerates a missing/malformed manifest so the gate-check
        # refusal tests can run against /dev/null. Emit a placeholder.
        print(f"(dry-run) manifest not usable ({exc}); writing placeholder plan")
        examples = []
        manifest_ok = False

    planned_calls = len(examples)
    # Cost estimate: ~800 input toks (abstract is bulky) + ~20 out toks
    # at $15/Mtok in, $75/Mtok out -> ~$0.013/example.
    est_cost = planned_calls * 0.013

    print("(dry-run) pubmedqa_runner.py plan:")
    print(f"  benchmark        : pubmedqa")
    print(f"  role             : RAG-validator anchor "
          f"(R1/R2 ship only when lift >= 10pp over no-retrieval baseline)")
    print(f"  manifest         : {manifest_path}")
    print(f"  out              : {out_path}")
    print(f"  seed             : {args.seed}")
    print(f"  run_id           : {run_id}")
    print(f"  budget_cap_usd   : {args.budget_cap_usd}")
    print(f"  planned api calls: {planned_calls}")
    print(f"  est cost usd     : ~{est_cost:.2f}")
    print(f"  model            : {MODEL_ID}")
    print(f"  grader           : exact-match (yes/no/maybe)")
    print(f"  manifest status  : {'ok' if manifest_ok else 'placeholder'}")
    print("(dry-run) no network activity; no anthropic SDK import")

    payload = {
        "dry_run": True,
        "commit": False,
        "run_id": run_id,
        "seed": args.seed,
        "benchmark": "pubmedqa",
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "model": MODEL_ID,
        "budget_cap_usd": args.budget_cap_usd,
        "planned_api_calls": planned_calls,
        "examples": [],
        "aggregate": _aggregate([]),
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
    examples: list[dict] = manifest.get("examples", [])

    client = Anthropic()
    print(f"(commit) run_id={run_id} model={MODEL_ID} seed={args.seed}")
    print(f"(commit) examples={len(examples)} budget_cap=${args.budget_cap_usd}")

    per_example: list[dict] = []
    total_cost_usd = 0.0
    halted_reason: str | None = None

    for idx, example in enumerate(examples):
        if total_cost_usd >= args.budget_cap_usd:
            halted_reason = (
                f"budget cap hit at example {idx} "
                f"(spent=${total_cost_usd:.2f} >= cap=${args.budget_cap_usd:.2f})"
            )
            print(f"(commit) HALT: {halted_reason}")
            break

        prompt = (
            f"Context:\n{example['context']}\n\n"
            f"Question: {example['question']}\n\n"
            f"Respond with only one word: yes, no, or maybe."
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

        predicted = _extract_answer(response_text)
        expected = example["answer_yn"]
        correct = predicted == expected

        usage = getattr(response, "usage", None)
        in_toks = getattr(usage, "input_tokens", 0) if usage else 0
        out_toks = getattr(usage, "output_tokens", 0) if usage else 0
        cost = (in_toks / 1_000_000) * 15.0 + (out_toks / 1_000_000) * 75.0
        total_cost_usd += cost

        per_example.append(
            {
                "id": example.get("id", f"ex-{idx}"),
                "predicted": predicted,
                "expected": expected,
                "correct": bool(correct),
                "input_tokens": in_toks,
                "output_tokens": out_toks,
                "est_cost_usd": round(cost, 6),
            }
        )
        print(
            f"(commit) [{idx + 1}/{len(examples)}] id={example.get('id', '?')} "
            f"pred={predicted} exp={expected} "
            f"{'OK' if correct else 'MISS'} cum=${total_cost_usd:.2f}"
        )

    payload = {
        "dry_run": False,
        "commit": True,
        "run_id": run_id,
        "seed": args.seed,
        "benchmark": "pubmedqa",
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "model": MODEL_ID,
        "budget_cap_usd": args.budget_cap_usd,
        "total_cost_usd": round(total_cost_usd, 4),
        "halted_reason": halted_reason,
        "examples": per_example,
        "aggregate": _aggregate(per_example),
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
        help="Path to PubMedQA manifest (YAML or JSON).",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Path to write results JSON (e.g. results/pubmedqa-opus47-NAME.json).",
    )
    ap.add_argument("--seed", type=int, default=42, help="Seed for Messages API calls.")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run for real. Requires PRISM_PUBMEDQA_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--run-id",
        default=None,
        help="Optional UUID for this run; generated if absent.",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=10.0,
        help="Hard-stop if cumulative cost exceeds this (default 10.0).",
    )
    args = ap.parse_args()

    run_id = args.run_id or str(uuid.uuid4())

    if args.commit and os.environ.get("PRISM_PUBMEDQA_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_PUBMEDQA_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args, run_id)

    return do_dry_run(args, run_id)


if __name__ == "__main__":
    sys.exit(main())
