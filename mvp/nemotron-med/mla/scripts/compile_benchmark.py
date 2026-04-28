"""torch.compile sweep on the torch MLA candidate pool.

For each torch candidate that passes the validator, try wrapping with
torch.compile at several modes and measure the effect on median latency
against the uncompiled baseline and FlashInfer's ceiling.

Modes tested (default all):
    eager                  - no compile, baseline
    default                - torch.compile(fn)
    reduce-overhead        - torch.compile(fn, mode='reduce-overhead')
    max-autotune-no-cg     - torch.compile(fn, mode='max-autotune-no-cudagraphs')

Skipped (incompatible with per-call CUDA-event timing):
    max-autotune           - uses cudagraphs; benchmark would need graph-aware loop

Compile warmup is bumped to 30 iters so the autotune search has room to settle.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from agent.torch_stub_mutations import TORCH_CANDIDATES
from kernels.base.mla_decode_torch import (
    TorchMLAConfig,
    make_torch_inputs,
    mla_decode_torch_reference,
)
from prism.validator_torch import validate_torch
from runner.flashinfer_runner import FlashInferMLAConfig, run_flashinfer_mla_decode
from runner.torch_runner import benchmark_torch


COMPILE_MODES = {
    "eager": None,
    "default": "default",
    "reduce-overhead": "reduce-overhead",
    "max-autotune-no-cg": "max-autotune-no-cudagraphs",
}


def _compile(fn, mode: str | None):
    if mode is None:
        return fn
    # dynamic=False because our inputs have fixed shapes in this run
    return torch.compile(fn, mode=mode, fullgraph=False, dynamic=False)


def _try_one(name: str, fn, inputs, sweep_inputs, *, warmup: int, iters: int,
             batch_size: int) -> dict:
    """Validate + benchmark one (candidate, compile_mode). Returns a record."""
    t_start = time.perf_counter()
    # First-call compile cost is baked into validate's first call. Time it.
    try:
        t_compile_start = time.perf_counter()
        v = validate_torch(
            fn, mla_decode_torch_reference, inputs,
            tolerance=5e-2, config_sweep=sweep_inputs,
        )
        compile_s = time.perf_counter() - t_compile_start
    except Exception as e:
        return {
            "name": name, "passed": False,
            "reason": f"validate raised: {type(e).__name__}: {e}",
            "max_abs_error": None, "median_ns": None, "tokens_per_sec": None,
            "compile_s": None, "total_s": time.perf_counter() - t_start,
        }
    if not v.passed:
        return {
            "name": name, "passed": False, "reason": v.failed_check,
            "max_abs_error": v.max_abs_error, "median_ns": None,
            "tokens_per_sec": None, "compile_s": compile_s,
            "total_s": time.perf_counter() - t_start,
        }
    try:
        b = benchmark_torch(fn, inputs, warmup=warmup, iters=iters, batch_size=batch_size)
    except Exception as e:
        return {
            "name": name, "passed": False,
            "reason": f"benchmark raised: {type(e).__name__}: {e}",
            "max_abs_error": v.max_abs_error, "median_ns": None,
            "tokens_per_sec": None, "compile_s": compile_s,
            "total_s": time.perf_counter() - t_start,
        }
    return {
        "name": name, "passed": True, "reason": "ok",
        "max_abs_error": v.max_abs_error, "median_ns": b.median_ns,
        "mean_ns": b.mean_ns, "p90_ns": b.p90_ns, "std_ns": b.std_ns,
        "tokens_per_sec": b.tokens_per_sec, "compile_s": compile_s,
        "total_s": time.perf_counter() - t_start,
    }


def run(cfg: TorchMLAConfig) -> dict:
    inputs = make_torch_inputs(cfg, seed=0)
    sweep_kv_lens = [cfg.kv_len // 4, cfg.kv_len * 4]
    sweep_inputs = []
    for kv in sweep_kv_lens:
        alt = TorchMLAConfig(batch=cfg.batch, heads=cfg.heads, kv_len=kv,
                             d_ckv=cfg.d_ckv, d_pe=cfg.d_pe, dtype=cfg.dtype,
                             device=cfg.device)
        sweep_inputs.append(make_torch_inputs(alt, seed=100 + kv))

    results: list[dict] = []
    for cand in TORCH_CANDIDATES:
        if cand.name == "neg_ctl_drops_rope":
            # Skip negative control in compile sweep — already proven rejected.
            continue
        print(f"\n--- {cand.name} ---")
        for mode_label, mode in COMPILE_MODES.items():
            try:
                fn_compiled = _compile(cand.fn, mode)
            except Exception as e:
                print(f"  {mode_label:<20s} compile wrap raised: {e}")
                continue
            warmup = 8 if mode is None else 30  # autotune needs room
            iters = 50
            rec = _try_one(
                name=f"{cand.name}::{mode_label}",
                fn=fn_compiled, inputs=inputs, sweep_inputs=sweep_inputs,
                warmup=warmup, iters=iters, batch_size=cfg.batch,
            )
            rec["candidate"] = cand.name
            rec["mode"] = mode_label
            results.append(rec)
            if rec["passed"]:
                print(f"  {mode_label:<20s} median={rec['median_ns']/1000:7.1f}us  "
                      f"tok/s={rec['tokens_per_sec']:>8.0f}  "
                      f"compile={rec['compile_s']:>5.1f}s  "
                      f"max_err={rec['max_abs_error']:.2e}")
            else:
                print(f"  {mode_label:<20s} FAIL: {rec['reason']}")

    # Flashinfer ceiling at same primary kv_len.
    fi_cfg = FlashInferMLAConfig(
        batch_size=cfg.batch, kv_len=cfg.kv_len, page_size=64,
        num_heads=cfg.heads, head_dim_ckv=cfg.d_ckv, head_dim_kpe=cfg.d_pe,
        q_dtype=cfg.dtype, kv_dtype=cfg.dtype, backend="auto",
    )
    fi = run_flashinfer_mla_decode(fi_cfg)
    return {
        "config": asdict(cfg),
        "results": results,
        "flashinfer": fi,
    }


def main() -> int:
    if not torch.cuda.is_available():
        print("ERROR: torch.cuda not available"); return 2

    cfg = TorchMLAConfig(
        batch=1, heads=128, kv_len=1024, d_ckv=512, d_pe=64, dtype="bfloat16",
    )
    print(f"[cfg] {cfg}")
    print(f"[gpu] {torch.cuda.get_device_name(0)} cc={torch.cuda.get_device_capability(0)}")
    print(f"[torch] {torch.__version__}")
    summary = run(cfg)

    # Summary table: for each candidate, show eager vs each compile mode
    print("\n\n=== summary: median µs by (candidate x mode) ===")
    # Unique candidates (keep order)
    cands_seen = []
    for r in summary["results"]:
        if r["candidate"] not in cands_seen:
            cands_seen.append(r["candidate"])
    modes_order = list(COMPILE_MODES)
    header = f"{'candidate':<20s} " + " ".join(f"{m:>15s}" for m in modes_order)
    print(header)
    print("-" * len(header))
    for c in cands_seen:
        row = f"{c:<20s} "
        for m in modes_order:
            rec = next((r for r in summary["results"] if r["candidate"] == c and r["mode"] == m), None)
            if rec is None or not rec["passed"] or rec["median_ns"] is None:
                row += f"{'--':>15s} "
            else:
                row += f"{rec['median_ns']/1000:>12.1f} us "
        print(row)

    fi_median = summary["flashinfer"]["bench"]["median_ns"]
    print(f"\nflashinfer@{cfg.kv_len}: {fi_median/1000:.1f} us  "
          f"(tok/s={summary['flashinfer']['bench']['tokens_per_sec']:.0f})")

    # Best candidate x mode overall
    passing = [r for r in summary["results"] if r["passed"] and r["median_ns"] is not None]
    if passing:
        best = min(passing, key=lambda r: r["median_ns"])
        ratio = best["median_ns"] / fi_median if fi_median > 0 else float("inf")
        print(f"\n[winner] {best['name']}  median={best['median_ns']/1000:.1f}us  "
              f"is {ratio:.2f}x flashinfer")

    out = Path(__file__).resolve().parent.parent / "results" / "logs" / "compile_sweep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[log] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
