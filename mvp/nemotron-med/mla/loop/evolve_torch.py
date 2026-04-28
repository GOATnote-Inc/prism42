"""Torch-GPU evolve driver.

End-to-end: for each candidate in the torch stub pool (baseline + 4
mutations + 1 negative control), validate against the torch reference,
benchmark via CUDA events, score against a FlashInfer baseline at the
same DeepSeek config. Produces a single JSON summary.

This is the minimum-viable real-GPU version of the stub evolve loop; the
multi-island + LLM-driven layer from loop/evolve.py plugs on top once
mutation prompts can emit torch source (see agent/prompts/mutation.txt —
needs torch binding added to agent/safety.compile_candidate).
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from agent.torch_stub_mutations import TORCH_CANDIDATES
from kernels.base.mla_decode_torch import (
    TorchMLAConfig,
    make_torch_inputs,
    mla_decode_torch_reference,
)
from prism.validator_torch import validate_torch
from runner.torch_runner import benchmark_torch


@dataclass
class TorchScore:
    name: str
    passed: bool
    reason: str
    max_abs_error: float
    median_ns: float
    mean_ns: float
    p90_ns: float
    std_ns: float
    tokens_per_sec: float
    reasoning: str = ""


def _flashinfer_reference_benchmark(cfg: TorchMLAConfig, kv_lens: list[int]) -> list[dict[str, Any]]:
    """Benchmark flashinfer at the same config for each kv_len, returning
    per-length results."""
    from runner.flashinfer_runner import FlashInferMLAConfig, run_flashinfer_mla_decode
    out = []
    for kv_len in kv_lens:
        fi = FlashInferMLAConfig(
            batch_size=cfg.batch, kv_len=kv_len, page_size=64,
            num_heads=cfg.heads, head_dim_ckv=cfg.d_ckv, head_dim_kpe=cfg.d_pe,
            q_dtype=cfg.dtype, kv_dtype=cfg.dtype, backend="auto",
        )
        r = run_flashinfer_mla_decode(fi)
        out.append({"kv_len": kv_len, **r})
    return out


def run(cfg: TorchMLAConfig, *, sweep_kv_lens: tuple[int, ...] = (1024,), seed: int = 0) -> dict:
    inputs = make_torch_inputs(cfg, seed=seed)
    # Sweep configs for the torch validator — same dims, different kv_len.
    sweep_inputs = []
    for kv in sweep_kv_lens:
        if kv == cfg.kv_len:
            continue
        alt = TorchMLAConfig(batch=cfg.batch, heads=cfg.heads, kv_len=kv,
                             d_ckv=cfg.d_ckv, d_pe=cfg.d_pe, dtype=cfg.dtype,
                             device=cfg.device)
        sweep_inputs.append(make_torch_inputs(alt, seed=seed + kv))

    scored: list[TorchScore] = []
    for cand in TORCH_CANDIDATES:
        t0 = time.perf_counter()
        v = validate_torch(
            cand.fn, mla_decode_torch_reference, inputs,
            tolerance=5e-2, config_sweep=sweep_inputs,
        )
        if not v.passed:
            scored.append(TorchScore(
                name=cand.name, passed=False, reason=v.failed_check or "unknown",
                max_abs_error=v.max_abs_error, median_ns=0, mean_ns=0, p90_ns=0,
                std_ns=0, tokens_per_sec=0, reasoning=cand.reasoning,
            ))
            print(f"  [REJECT] {cand.name:<24s} reason={v.failed_check}")
            continue
        b = benchmark_torch(cand.fn, inputs, warmup=10, iters=50, batch_size=cfg.batch)
        scored.append(TorchScore(
            name=cand.name, passed=True, reason="ok",
            max_abs_error=v.max_abs_error,
            median_ns=b.median_ns, mean_ns=b.mean_ns, p90_ns=b.p90_ns,
            std_ns=b.std_ns, tokens_per_sec=b.tokens_per_sec,
            reasoning=cand.reasoning,
        ))
        wall = time.perf_counter() - t0
        print(f"  [PASS]   {cand.name:<24s} "
              f"max_err={v.max_abs_error:.2e}  "
              f"median={b.median_ns/1000:7.1f}us  "
              f"tok/s={b.tokens_per_sec:>8.0f}  "
              f"val+bench wall={wall:.1f}s")

    # Flashinfer baseline at the primary kv_len + sweep lens.
    fi_sweep_lens = sorted(set([cfg.kv_len, *sweep_kv_lens]))
    fi_results = _flashinfer_reference_benchmark(cfg, fi_sweep_lens)

    # Ranking: among passing candidates, sort by median_ns asc.
    passing = [s for s in scored if s.passed]
    passing.sort(key=lambda s: s.median_ns)

    summary = {
        "config": asdict(cfg),
        "scored": [asdict(s) for s in scored],
        "ranking_by_median": [s.name for s in passing],
        "flashinfer": fi_results,
    }
    return summary


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--kv-len", type=int, default=1024)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--heads", type=int, default=128)
    p.add_argument("--d-ckv", type=int, default=512)
    p.add_argument("--d-pe", type=int, default=64)
    p.add_argument("--dtype", default="bfloat16")
    p.add_argument("--sweep", default="256,4096", help="comma-separated extra kv_lens for Tier-2 sweep")
    args = p.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: torch.cuda not available"); return 2

    cfg = TorchMLAConfig(
        batch=args.batch, heads=args.heads, kv_len=args.kv_len,
        d_ckv=args.d_ckv, d_pe=args.d_pe, dtype=args.dtype,
    )
    sweep = tuple(int(x) for x in args.sweep.split(",") if x.strip())
    print(f"[cfg] {cfg}  sweep={sweep}")
    print(f"[gpu] {torch.cuda.get_device_name(0)} cc={torch.cuda.get_device_capability(0)}")
    print("\n[candidates]")
    summary = run(cfg, sweep_kv_lens=sweep)

    print("\n[ranking by median]")
    for i, name in enumerate(summary["ranking_by_median"], 1):
        sc = next(s for s in summary["scored"] if s["name"] == name)
        print(f"  {i}. {name:<24s} median={sc['median_ns']/1000:7.1f}us  tok/s={sc['tokens_per_sec']:>8.0f}")

    print("\n[flashinfer baseline — same dims]")
    for r in summary["flashinfer"]:
        b = r["bench"]; v = r["verify"]
        print(f"  kv_len={r['kv_len']:>5d}  median={b['median_ns']/1000:7.1f}us  "
              f"tok/s={b['tokens_per_sec']:>8.0f}  max_err={v['max_abs_error']:.2e}")

    # Winner vs flashinfer at same primary kv_len.
    if summary["ranking_by_median"]:
        winner = next(s for s in summary["scored"] if s["name"] == summary["ranking_by_median"][0])
        fi_at = next(r for r in summary["flashinfer"] if r["kv_len"] == cfg.kv_len)
        fi_median = fi_at["bench"]["median_ns"]
        ratio = winner["median_ns"] / fi_median if fi_median > 0 else float("inf")
        print(f"\n[gap] winner '{winner['name']}' is {ratio:.2f}x flashinfer "
              f"({winner['median_ns']/1000:.1f}us vs {fi_median/1000:.1f}us)")
        if ratio < 1.0:
            print(f"       >>> winner beats flashinfer by {(1-ratio)*100:.1f}%")

    out = Path(__file__).resolve().parent.parent / "results" / "logs" / "torch_evolve.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[log] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
