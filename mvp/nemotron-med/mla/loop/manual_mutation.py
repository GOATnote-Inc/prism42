"""One manual mutation loop end-to-end — prove the machinery before the agent.

Flow:
    1. Build a config.
    2. Generate inputs.
    3. Baseline: mla_decode_naive.
    4. Mutation: mla_decode_absorbed (the first real MLA optimization — stay in
       compressed latent space instead of reconstructing K/V).
    5. Run the full validator against the baseline reference.
    6. Benchmark both.
    7. Score per mental-models/einstein-first-principles.md §6
       (Carnot-ish efficiency) and per scaffold/prism-mla-scaffold.md §7
       (blended throughput + latency + stability).

No agent involved. This is the measurement infrastructure working against a
known-good mutation so we can trust the loop before wiring an LLM to it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# Allow `python loop/manual_mutation.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernels.base.mla_decode_numpy import (  # noqa: E402
    MLAConfig,
    bytes_moved_from_cache,
    flops,
    make_inputs,
    mla_decode_absorbed,
    mla_decode_naive,
)
from prism import (  # noqa: E402
    DEFAULT_INVARIANTS,
    validate,
)
from runner.numpy_runner import benchmark  # noqa: E402


def score(perf_tps: float, stability: float, *, w_tps: float = 0.7, w_stab: float = 0.3) -> float:
    """Blended score: throughput-heavy with a stability penalty.

    Throughput is tokens/sec on the representative config; stability is the
    coefficient-of-variation across repeated runs (lower std -> higher
    stability score).
    """
    return w_tps * perf_tps + w_stab * stability


def cov_stability(bench_result) -> float:
    """Stability as (1 - coefficient of variation). Saturates at 0 for noisy
    benchmarks, 1 for perfectly deterministic timing."""
    if bench_result.mean_ns <= 0:
        return 0.0
    cv = bench_result.std_ns / bench_result.mean_ns
    return max(0.0, 1.0 - cv)


def main() -> int:
    cfg = MLAConfig(
        batch=2,
        heads=8,
        kv_len=256,
        d_c=64,
        d_r=16,
        qk_nope=32,
        v_head=32,
    )
    print(f"[config] {cfg}")

    inputs = make_inputs(cfg, seed=0)

    # ---- Step 1: validate the mutation against the reference ----
    print("\n[validate] candidate=mla_decode_absorbed  ref=mla_decode_naive")
    # Build extra configs for Tier-2 sweep.
    sweep_configs = [
        make_inputs(MLAConfig(1, 8, 128, 64, 16, 32, 32), seed=1),
        make_inputs(MLAConfig(4, 8, 64,  64, 16, 32, 32), seed=2),
        make_inputs(MLAConfig(2, 16, 256, 64, 16, 32, 32), seed=3),
    ]
    result = validate(
        mla_decode_absorbed,
        mla_decode_naive,
        inputs,
        tolerance=1e-3,
        config_sweep=sweep_configs,
        invariants=DEFAULT_INVARIANTS,
    )
    print(f"  passed={result.passed}  tier_reached={result.tier_reached}  "
          f"max_err={result.max_abs_error:.3e}")
    if not result.passed:
        print(f"  FAIL at tier {result.tier_failed_at}: {result.failed_check}")
        return 1

    # ---- Step 2: benchmark both kernels ----
    print("\n[bench] baseline mla_decode_naive")
    naive = benchmark(mla_decode_naive, inputs, warmup=5, iters=50)
    print(f"  median={naive.median_ns:9.0f} ns  mean={naive.mean_ns:9.0f} ns  "
          f"std={naive.std_ns:8.0f} ns  tokens/sec={naive.tokens_per_sec:,.0f}")

    print("[bench] candidate mla_decode_absorbed")
    absorbed = benchmark(mla_decode_absorbed, inputs, warmup=5, iters=50)
    print(f"  median={absorbed.median_ns:9.0f} ns  mean={absorbed.mean_ns:9.0f} ns  "
          f"std={absorbed.std_ns:8.0f} ns  tokens/sec={absorbed.tokens_per_sec:,.0f}")

    speedup = naive.median_ns / absorbed.median_ns if absorbed.median_ns > 0 else float("inf")
    print(f"\n[speedup] absorbed is {speedup:.2f}x over naive (median)")

    # ---- Step 3: first-principles check ----
    naive_flops = flops(cfg, "naive")
    absorbed_flops = flops(cfg, "absorbed")
    bytes_moved = bytes_moved_from_cache(cfg)
    flop_ratio = naive_flops / max(absorbed_flops, 1)
    print(f"\n[physics] naive flops={naive_flops:,}  absorbed flops={absorbed_flops:,}")
    print(f"          flop ratio naive/absorbed = {flop_ratio:.2f}x")
    print(f"          bytes moved from cache    = {bytes_moved:,}")

    # ---- Step 4: scoring (scaffold Part 7 style) ----
    naive_score = score(naive.tokens_per_sec, cov_stability(naive))
    absorbed_score = score(absorbed.tokens_per_sec, cov_stability(absorbed))
    winner = "absorbed" if absorbed_score > naive_score else "naive"
    print(f"\n[score] naive={naive_score:,.2f}  absorbed={absorbed_score:,.2f}  "
          f"winner={winner}")

    # ---- Step 5: persist ----
    out_path = Path(__file__).resolve().parent.parent / "results" / "logs" / "manual_mutation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "config": cfg.__dict__,
        "validate": {
            "passed": result.passed,
            "tier_reached": result.tier_reached,
            "max_abs_error": result.max_abs_error,
        },
        "bench": {
            "naive": {
                "median_ns": naive.median_ns, "mean_ns": naive.mean_ns,
                "std_ns": naive.std_ns, "p90_ns": naive.p90_ns,
                "tokens_per_sec": naive.tokens_per_sec,
            },
            "absorbed": {
                "median_ns": absorbed.median_ns, "mean_ns": absorbed.mean_ns,
                "std_ns": absorbed.std_ns, "p90_ns": absorbed.p90_ns,
                "tokens_per_sec": absorbed.tokens_per_sec,
            },
            "speedup_median": speedup,
        },
        "physics": {
            "naive_flops": naive_flops, "absorbed_flops": absorbed_flops,
            "flop_ratio": flop_ratio, "bytes_moved_from_cache": bytes_moved,
        },
        "score": {"naive": naive_score, "absorbed": absorbed_score, "winner": winner},
    }
    out_path.write_text(json.dumps(record, indent=2))
    print(f"\n[log] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
