#!/usr/bin/env python3
"""Sovereign HealthBench sweep — Triton-served Nemotron, Triton-served judge.

Drop-in replacement for the Opus-4.7 path in `healthbench_runner.py` that
keeps every grading invariant (paired-design CI machinery, RECUSED items,
audit logging) but routes both the model-under-test and the judge through
local OpenAI-compatible endpoints exposed via ssh tunnel from the H200 /
H100 Brev pods.

No `anthropic` import. No `openai` SDK. Only `httpx` to the local
endpoints, plus the existing `_healthbench_grader_bridge` for the
GRADER_TEMPLATE/calculate_score.

Usage:
    python scripts/sovereign_bench.py \\
        --manifest corpus/pins/healthbench-hard-1000.yaml \\
        --serve-url http://127.0.0.1:8000/v1 \\
        --serve-model nvidia/Llama-3.1-Nemotron-70B-Instruct-HF \\
        --judge-url http://127.0.0.1:8001/v1 \\
        --judge-model meta-llama/Llama-3.1-Nemotron-70B-Instruct-AWQ-INT4 \\
        --n 30 --trials 3 --seed 42 \\
        --out results/r1-bare/healthbench-hard-n30.json

Both --serve-url and --judge-url MUST be 127.0.0.1/localhost. External
URLs raise immediately — see CLAUDE.md §2.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from healthbench_runner import (  # noqa: E402
    HEALTHBENCH_AXES,
    _aggregate,
    _load_manifest,
    _now_iso,
    _real_grader,
    _write_out,
)
from mla.judges.triton import make_triton_judge  # noqa: E402


def _require_local(url: str, label: str) -> None:
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        raise ValueError(
            f"{label} must be a 127.0.0.1/localhost URL, got {url!r}. "
            "External URLs defeat the sovereign-stack design — see CLAUDE.md §2."
        )


def _generate(
    *,
    client: httpx.Client,
    model: str,
    messages: list[dict],
    max_tokens: int,
    timeout_s: float,
) -> str:
    """Single chat completion against the local serve endpoint."""
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    # base_url ends with /v1; relative path so httpx joins correctly.
    resp = client.post("chat/completions", json=body, timeout=timeout_s)
    resp.raise_for_status()
    payload = resp.json()
    return payload["choices"][0]["message"]["content"]


def _example_messages(example: dict) -> list[dict]:
    msgs = example.get("messages") or [
        {"role": "user", "content": example.get("prompt", "")}
    ]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="HealthBench Hard YAML manifest")
    parser.add_argument("--serve-url", required=True, help="local serve base URL (e.g. http://127.0.0.1:8000/v1)")
    parser.add_argument("--serve-model", required=True, help="model id to send to /chat/completions")
    parser.add_argument("--judge-url", required=True, help="local judge base URL")
    parser.add_argument("--judge-model", required=True, help="judge model id")
    parser.add_argument("--n", type=int, default=30, help="examples per trial")
    parser.add_argument("--trials", type=int, default=3, help="N trials for paired-design CI")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="single-example smoke run; READ the JSON artifact before scaling up",
    )
    args = parser.parse_args()

    _require_local(args.serve_url, "--serve-url")
    _require_local(args.judge_url, "--judge-url")

    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(manifest_path)
    examples: list[dict] = manifest.get("examples", [])
    if not examples:
        print(f"FAIL: {manifest_path}: no examples in manifest", file=sys.stderr)
        return 1

    n_per_trial = 1 if args.smoke else args.n
    trials = 1 if args.smoke else args.trials
    examples = examples[:n_per_trial]

    run_id = uuid.uuid4().hex[:8]
    started = time.time()

    audit_dir = out_path.parent / "judge-audit"
    audit_dir.mkdir(exist_ok=True)
    judge_fn = make_triton_judge(
        base_url=args.judge_url,
        model_id=args.judge_model,
        audit_log_path=audit_dir / f"judge-{run_id}.jsonl",
        max_retries=3,
    )

    serve_client = httpx.Client(base_url=args.serve_url, timeout=args.timeout_s)

    trial_results: list[dict] = []

    print(
        f"[sovereign_bench] run_id={run_id} examples={n_per_trial} trials={trials} "
        f"serve={args.serve_model} judge={args.judge_model}"
    )

    for trial_idx in range(trials):
        per_example: list[dict] = []
        for ex_idx, example in enumerate(examples):
            t0 = time.time()
            messages = _example_messages(example)
            try:
                response_text = _generate(
                    client=serve_client,
                    model=args.serve_model,
                    messages=messages,
                    max_tokens=args.max_tokens,
                    timeout_s=args.timeout_s,
                )
            except httpx.HTTPError as exc:
                print(
                    f"  trial={trial_idx} ex={ex_idx} SERVE FAIL: {exc}",
                    file=sys.stderr,
                )
                continue

            graded = _real_grader(response_text, example, judge_fn=judge_fn)
            per_example.append(
                {
                    "example_id": example.get("id", f"ex{ex_idx}"),
                    "trial": trial_idx,
                    "response": response_text,
                    "score": graded.get("score"),
                    "per_axis": graded.get("per_axis", {a: None for a in HEALTHBENCH_AXES}),
                    "judge_incomplete": graded.get("judge_incomplete", 0),
                    "duration_ms": int((time.time() - t0) * 1000),
                }
            )
            print(
                f"  trial={trial_idx} ex={ex_idx} "
                f"score={graded.get('score')} "
                f"recused={graded.get('judge_incomplete', 0)}"
            )

        trial_aggregate = _aggregate(per_example)
        trial_results.append(
            {
                "trial": trial_idx,
                "per_example": per_example,
                "aggregate": trial_aggregate,
            }
        )

    payload = {
        "dry_run": False,
        "sovereign": True,
        "run_id": run_id,
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "seed": args.seed,
        "serve_url": args.serve_url,
        "serve_model": args.serve_model,
        "judge_url": args.judge_url,
        "judge_model": args.judge_model,
        "n_per_trial": n_per_trial,
        "trials": trials,
        "trial_results": trial_results,
        "wall_time_s": int(time.time() - started),
    }

    _write_out(out_path, payload)
    print(f"[sovereign_bench] artifact: {out_path}")
    print(
        "[sovereign_bench] READ THE ARTIFACT before claiming success: judge-401 "
        "silently produces reward=0 everywhere. Spot-check at least one trial's "
        "per_example[].score for non-zero values."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
