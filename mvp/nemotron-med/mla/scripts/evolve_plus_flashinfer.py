"""Run the stub evolve loop + a FlashInfer baseline sweep on the same host.

Two deliberately separate runs, one report:

1. Stub evolve loop at toy dims (batch=2, heads=8, kv_len=256, d_c=64, d_r=16,
   qk_nope=32, v_head=32). Pure numpy. Same as loop/evolve_demo.py — but here
   the script *also* runs it on the GPU host so we know the loop mechanics
   work in this environment.

2. FlashInfer MLA decode at DeepSeek dims (heads=128, d_ckv=512, d_pe=64,
   total 576) swept across kv_len ∈ {256, 1024, 4096, 8192}. This is the
   production baseline our future GPU mutations must beat.

Output: `results/logs/evolve_plus_flashinfer.json` plus a human-readable
table on stdout.

Why two runs instead of one integrated loop: the stub mutations produce
numpy kernels with our toy signature; FlashInfer only accepts DeepSeek-dim
paged inputs. Bridging them requires rewriting the mutations in torch — a
separate step (documented in README.md "What's intentionally not here yet").

Usage (on the H100 pod):
    export PATH="/workspace/prism-mla/.venv/bin:/usr/local/cuda/bin:$PATH"
    .venv/bin/python scripts/evolve_plus_flashinfer.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_client import StubClient
from kernels.base.mla_decode_numpy import MLAConfig, mla_decode_absorbed
from loop.evolve import EvolveConfig, evolve


def run_stub_evolve() -> dict:
    print("\n=== 1. stub evolve loop (numpy, toy dims) ===")
    cfg = EvolveConfig(
        mla=MLAConfig(batch=2, heads=8, kv_len=256, d_c=64, d_r=16, qk_nope=32, v_head=32),
        iterations=3,
        per_island=3,
        keep_per_island=2,
        migrate_every=2,
        tolerance=1e-3,
        seed=0,
        run_critique=True,
        pareto_keep=True,
        critique_linear_topk=2,
    )
    t0 = time.perf_counter()
    summary = evolve(StubClient(), mla_decode_absorbed, cfg)
    wall = time.perf_counter() - t0
    print(f"  wall_s = {wall:.2f}")
    for it in summary["history"]:
        for isl in it["islands"]:
            cr = isl.get("critiques", [])
            rejs = sum(1 for c in cr if c["recommendation"] == "reject")
            print(f"  iter={it['iteration']}  island={isl['name']:<8s}  "
                  f"top={isl['top_score']:,.1f}  critique_reject={rejs}")
    print(f"  best.score          = {summary['best']['score']:,.2f}")
    print(f"  best.tokens_per_sec = {summary['best']['tokens_per_sec']:,.0f}")
    print(f"  best.median_ns      = {summary['best']['median_ns']:,.0f}")
    print(f"  best.stability      = {summary['best']['stability']:.3f}")
    print(f"  best.hash           = {summary['best']['hash']}")
    return {"wall_s": wall, "summary": summary}


def run_flashinfer_sweep() -> list[dict]:
    from runner.flashinfer_runner import (
        FlashInferMLAConfig,
        environment_report,
        run_flashinfer_mla_decode,
    )
    print("\n=== 2. flashinfer MLA decode sweep (GPU, DeepSeek dims) ===")
    print(f"  environment: {environment_report().get('device_name', '?')}")
    sweep_lens = [int(x) for x in os.environ.get("PRISM_SWEEP", "256,1024,4096,8192").split(",")]
    results = []
    for kv_len in sweep_lens:
        cfg = FlashInferMLAConfig(
            batch_size=1, kv_len=kv_len, page_size=64,
            q_dtype="bfloat16", kv_dtype="bfloat16", backend="auto",
        )
        t0 = time.perf_counter()
        r = run_flashinfer_mla_decode(cfg)
        wall = time.perf_counter() - t0
        v = r["verify"]; b = r["bench"]
        print(f"  kv_len={kv_len:>5d}  max_err={v['max_abs_error']:.2e}  "
              f"median={b['median_ns']/1000:7.1f} us  p90={b['p90_ns']/1000:7.1f} us  "
              f"tok/s={b['tokens_per_sec']:>8.0f}  setup_s={wall-(b['median_ns']*b['iters']/1e9):.2f}")
        results.append({"kv_len": kv_len, "verify": v, "bench": b, "config": r["config"]})
    return results


def main() -> int:
    evolve_result = run_stub_evolve()
    flashinfer_sweep = run_flashinfer_sweep()

    combined = {
        "stub_evolve": evolve_result,
        "flashinfer_sweep": flashinfer_sweep,
        "context": {
            "stub_evolve_note": "numpy-backed mutations at toy dims; measures loop mechanics",
            "flashinfer_note": "production DeepSeek dims (128 heads, 512 d_ckv, 64 d_pe), bf16; measures real GPU floor",
            "dimension_mismatch": ("stub mutations use a numpy signature "
                                   "(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, scale) "
                                   "that does not match flashinfer's paged "
                                   "layout; bridging requires torch-GPU mutations"),
        },
    }
    out = Path(__file__).resolve().parent.parent / "results" / "logs" / "evolve_plus_flashinfer.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(combined, indent=2))

    print("\n=== summary ===")
    best = evolve_result["summary"]["best"]
    print(f"  stub evolve winner      :: {best['tokens_per_sec']:>10.0f} tok/s  "
          f"median={best['median_ns']/1000:>6.1f} us   (numpy, toy dims)")
    for r in flashinfer_sweep:
        print(f"  flashinfer kv_len={r['kv_len']:>5d} :: "
              f"{r['bench']['tokens_per_sec']:>10.0f} tok/s  "
              f"median={r['bench']['median_ns']/1000:>6.1f} us   "
              f"(GPU, DeepSeek dims, bf16)")
    print(f"\n[log] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
