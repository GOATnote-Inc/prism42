"""Single real-Claude call smoke test: one mutate(), one critique(), verify
parsing + safety gate + validator all survive real LLM output.

Small, cheap, deliberate. Budget cap: max_tokens=4096 per call, 2 calls.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.critique import CritiqueRequest
from agent.llm_client import AnthropicClient, MutationRequest
from agent.mutate import Candidate
from agent.safety import UnsafeSourceError, compile_candidate
from kernels.base.mla_decode_numpy import (
    MLAConfig,
    make_inputs,
    mla_decode_absorbed,
    mla_decode_naive,
)
from prism import validate
import inspect


def main() -> int:
    print("[smoke] creating AnthropicClient (claude-opus-4-7)")
    client = AnthropicClient(allow_real_calls=True)

    baseline_src = inspect.getsource(mla_decode_absorbed)
    req = MutationRequest(
        current_best_source=baseline_src,
        population_summary="(empty — first mutation)",
        mutation_objective="reduce redundant arithmetic while preserving exact MLA semantics",
    )

    # --- mutate call ---
    print("[smoke] calling mutate()...")
    t0 = time.perf_counter()
    mresp = client.mutate(req)
    t_mut = time.perf_counter() - t0
    print(f"[smoke] mutate returned in {t_mut:.1f}s; reasoning_len={len(mresp.reasoning)}, source_len={len(mresp.source)}")
    print(f"[smoke] reasoning (first 300 chars):\n  {mresp.reasoning[:300]!r}")
    print(f"[smoke] source (first 200 chars):\n  {mresp.source[:200]!r}")

    # --- compile via safety gate ---
    try:
        fn = compile_candidate(mresp.source)
        print(f"[smoke] compile_candidate OK: {fn}")
    except UnsafeSourceError as e:
        print(f"[smoke] compile_candidate REJECTED: {e}")
        # Save the source for inspection; not a failure of the smoke unless unexpected
        Path("results/logs/real_claude_rejected.txt").parent.mkdir(parents=True, exist_ok=True)
        Path("results/logs/real_claude_rejected.txt").write_text(mresp.source)
        return 2

    # --- run validator against real-claude-generated kernel ---
    cfg = MLAConfig(batch=1, heads=4, kv_len=32, d_c=16, d_r=8, qk_nope=16, v_head=16)
    inputs = make_inputs(cfg, seed=0)
    vresult = validate(fn, mla_decode_naive, inputs, tolerance=1e-3)
    print(f"[smoke] validator: passed={vresult.passed}  tier_reached={vresult.tier_reached}  max_err={vresult.max_abs_error:.3e}")
    if not vresult.passed:
        print(f"[smoke] validator failure: {vresult.failed_check}")

    # --- critique call ---
    print("[smoke] calling critique()...")
    t0 = time.perf_counter()
    cresp = client.critique(CritiqueRequest(
        baseline_source=baseline_src,
        candidate_source=mresp.source,
    ))
    t_crit = time.perf_counter() - t0
    print(f"[smoke] critique returned in {t_crit:.1f}s")
    print(f"[smoke] numerical_risk={cresp.numerical_risk}")
    print(f"[smoke] efficiency_risk={cresp.efficiency_risk}")
    print(f"[smoke] novelty={cresp.novelty}")
    print(f"[smoke] recommendation={cresp.recommendation}")

    # --- persist ---
    log = {
        "model": client.model,
        "mutate": {
            "wall_s": t_mut,
            "reasoning_len": len(mresp.reasoning),
            "source_len": len(mresp.source),
            "reasoning": mresp.reasoning,
            "source": mresp.source,
        },
        "compile": {"passed": True},
        "validator": {
            "passed": vresult.passed, "tier_reached": vresult.tier_reached,
            "max_abs_error": vresult.max_abs_error,
            "failed_check": vresult.failed_check,
        },
        "critique": {
            "wall_s": t_crit,
            "numerical_risk": cresp.numerical_risk,
            "efficiency_risk": cresp.efficiency_risk,
            "novelty": cresp.novelty,
            "recommendation": cresp.recommendation,
            "rationale": cresp.rationale,
        },
    }
    out = Path("results/logs/real_claude_smoke.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(log, indent=2))
    print(f"[smoke] log written: {out}")

    print(json.dumps({
        "smoke": "ok" if vresult.passed else "validator_failed",
        "validator_passed": vresult.passed,
        "max_abs_error": vresult.max_abs_error,
        "critique_recommendation": cresp.recommendation,
        "mutate_wall_s": t_mut,
        "critique_wall_s": t_crit,
    }))
    return 0 if vresult.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
