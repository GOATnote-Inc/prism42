"""Pod-side: consume /tmp/claude_torch_mutations.json, compile each with
torch.compile, validate vs the torch reference, benchmark, and compare to
baseline_bf16+max-autotune and FlashInfer in the same process.

Writes results to /workspace/prism-mla/results/logs/claude_torch_iter.json.

Runs on the RunPod H100 pod. Invokes its own FlashInfer + torch.compile.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from agent.safety import UnsafeSourceError, compile_candidate_torch
from agent.torch_stub_mutations import TORCH_CANDIDATES
from kernels.base.mla_decode_torch import (
    TorchMLAConfig,
    make_torch_inputs,
    mla_decode_torch_reference,
)
from prism.validator_torch import validate_torch
from runner.flashinfer_runner import FlashInferMLAConfig, run_flashinfer_mla_decode
from runner.torch_runner import benchmark_torch


def _compile_best_mode(fn):
    """Apply torch.compile(mode='max-autotune-no-cudagraphs') — the mode
    that won the compile sweep for baseline_bf16 (68.5 µs vs 52.3 µs FI)."""
    return torch.compile(fn, mode="max-autotune-no-cudagraphs", fullgraph=False, dynamic=False)


def evaluate_one(name: str, source: str, inputs: dict, sweep_inputs: list,
                 *, batch_size: int) -> dict:
    t_start = time.perf_counter()
    # Safety + compile.
    try:
        fn = compile_candidate_torch(source)
    except UnsafeSourceError as e:
        return {"name": name, "status": "rejected_safety", "reason": str(e),
                "wall_s": time.perf_counter() - t_start}
    # Quick sanity call (uncompiled).
    try:
        _ = fn(**inputs)
    except Exception as e:
        return {"name": name, "status": "eager_raise",
                "reason": f"{type(e).__name__}: {e}",
                "wall_s": time.perf_counter() - t_start}
    # Wrap in torch.compile.
    try:
        compiled = _compile_best_mode(fn)
    except Exception as e:
        return {"name": name, "status": "compile_wrap_raise",
                "reason": f"{type(e).__name__}: {e}",
                "wall_s": time.perf_counter() - t_start}
    # Validate (first call triggers actual Inductor compile — timed as compile_s).
    t_comp = time.perf_counter()
    try:
        v = validate_torch(compiled, mla_decode_torch_reference, inputs,
                           tolerance=5e-2, config_sweep=sweep_inputs)
    except Exception as e:
        return {"name": name, "status": "validate_raise",
                "reason": f"{type(e).__name__}: {e}",
                "compile_s": time.perf_counter() - t_comp,
                "wall_s": time.perf_counter() - t_start}
    compile_s = time.perf_counter() - t_comp
    if not v.passed:
        return {"name": name, "status": "validator_rejected",
                "reason": v.failed_check, "max_abs_error": v.max_abs_error,
                "compile_s": compile_s, "wall_s": time.perf_counter() - t_start}
    # Benchmark.
    try:
        b = benchmark_torch(compiled, inputs, warmup=20, iters=50, batch_size=batch_size)
    except Exception as e:
        return {"name": name, "status": "bench_raise",
                "reason": f"{type(e).__name__}: {e}",
                "compile_s": compile_s, "wall_s": time.perf_counter() - t_start}
    return {
        "name": name, "status": "pass",
        "max_abs_error": v.max_abs_error, "compile_s": compile_s,
        "median_ns": b.median_ns, "mean_ns": b.mean_ns, "p90_ns": b.p90_ns,
        "std_ns": b.std_ns, "tokens_per_sec": b.tokens_per_sec,
        "wall_s": time.perf_counter() - t_start,
    }


def main() -> int:
    if not torch.cuda.is_available():
        print("ERROR: torch.cuda not available"); return 2

    payload = json.loads(Path("/tmp/claude_torch_mutations.json").read_text())
    cfg = TorchMLAConfig(batch=1, heads=128, kv_len=1024, d_ckv=512, d_pe=64,
                         dtype="bfloat16")
    print(f"[gpu] {torch.cuda.get_device_name(0)} cc={torch.cuda.get_device_capability(0)}")
    print(f"[cfg] {cfg}")
    inputs = make_torch_inputs(cfg, seed=0)
    sweep_inputs = [
        make_torch_inputs(TorchMLAConfig(**{**asdict(cfg), "kv_len": cfg.kv_len // 4}), seed=101),
        make_torch_inputs(TorchMLAConfig(**{**asdict(cfg), "kv_len": cfg.kv_len * 4}), seed=404),
    ]

    # Baseline: baseline_bf16 + max-autotune (the previous winner).
    print("\n--- baseline_bf16::max-autotune-no-cg (reigning winner) ---")
    baseline_fn = next(c for c in TORCH_CANDIDATES if c.name == "baseline_bf16").fn
    b_compiled = _compile_best_mode(baseline_fn)
    _ = b_compiled(**inputs)  # warm compile
    baseline_v = validate_torch(b_compiled, mla_decode_torch_reference, inputs,
                                tolerance=5e-2, config_sweep=sweep_inputs)
    baseline_b = benchmark_torch(b_compiled, inputs, warmup=20, iters=50, batch_size=cfg.batch)
    print(f"  median={baseline_b.median_ns/1000:.1f}us  tok/s={baseline_b.tokens_per_sec:.0f}  "
          f"max_err={baseline_v.max_abs_error:.2e}")

    # FlashInfer ceiling.
    print("\n--- flashinfer ceiling ---")
    fi_cfg = FlashInferMLAConfig(
        batch_size=cfg.batch, kv_len=cfg.kv_len, page_size=64,
        num_heads=cfg.heads, head_dim_ckv=cfg.d_ckv, head_dim_kpe=cfg.d_pe,
        q_dtype=cfg.dtype, kv_dtype=cfg.dtype, backend="auto",
    )
    fi = run_flashinfer_mla_decode(fi_cfg)
    print(f"  median={fi['bench']['median_ns']/1000:.1f}us  tok/s={fi['bench']['tokens_per_sec']:.0f}")

    # Claude candidates.
    print("\n--- claude candidates ---")
    cand_results = []
    for rec in payload["records"]:
        if not rec.get("compile_ok"):
            print(f"[skip] #{rec['index']} safety/compile: {rec.get('compile_error','?')[:120]}")
            cand_results.append({
                "index": rec["index"], "status": "skip_compile",
                "reason": rec.get("compile_error"),
                "objective": rec["objective"],
            })
            continue
        name = f"claude_{rec['index']}"
        print(f"\n[{rec['index']}] objective: {rec['objective'][:70]}...")
        r = evaluate_one(name, rec["source"], inputs, sweep_inputs, batch_size=cfg.batch)
        r["objective"] = rec["objective"]
        r["reasoning"] = rec.get("reasoning", "")
        cand_results.append(r)
        if r.get("status") == "pass":
            print(f"  [PASS] median={r['median_ns']/1000:.1f}us  "
                  f"tok/s={r['tokens_per_sec']:.0f}  max_err={r['max_abs_error']:.2e}  "
                  f"compile={r['compile_s']:.1f}s")
        else:
            reason = str(r.get('reason') or '')[:200]
            print(f"  [FAIL:{r['status']}] {reason}")

    # Ranking.
    passing = [r for r in cand_results if r.get("status") == "pass"]
    passing.sort(key=lambda r: r["median_ns"])
    print("\n=== final ranking ===")
    fi_med = fi["bench"]["median_ns"]
    base_med = baseline_b.median_ns
    print(f"  flashinfer                  : median={fi_med/1000:7.2f}us  1.00x (ceiling)")
    print(f"  baseline_bf16+max-autotune  : median={base_med/1000:7.2f}us  "
          f"{base_med/fi_med:.2f}x (parent)")
    for r in passing:
        ratio_fi = r["median_ns"] / fi_med
        ratio_base = r["median_ns"] / base_med
        print(f"  {r['name']:<27s} : median={r['median_ns']/1000:7.2f}us  "
              f"{ratio_fi:.2f}x FI   {ratio_base:.2f}x parent   "
              f"{'***BEATS PARENT***' if ratio_base < 1.0 else ''}"
              f"{'  ***BEATS FI***' if ratio_fi < 1.0 else ''}")
    summary = {
        "config": asdict(cfg),
        "flashinfer": fi,
        "baseline": {
            "name": "baseline_bf16::max-autotune-no-cg",
            "median_ns": baseline_b.median_ns,
            "tokens_per_sec": baseline_b.tokens_per_sec,
            "max_abs_error": baseline_v.max_abs_error,
        },
        "claude_candidates": cand_results,
        "ranking_by_median": [r["name"] for r in passing],
        "beats_parent": [r["name"] for r in passing if r["median_ns"] < base_med],
        "beats_flashinfer": [r["name"] for r in passing if r["median_ns"] < fi_med],
    }
    out = Path("/workspace/prism-mla/results/logs/claude_torch_iter.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[log] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
