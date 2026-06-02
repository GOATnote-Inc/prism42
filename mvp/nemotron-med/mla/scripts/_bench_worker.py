"""One-shot bench worker — fresh process per invocation.

Runs a single (subject, config, replicate) measurement and emits one JSON
object to stdout. Designed to be spawned by scripts/isolated_bench.py. Never
imports across runs — each invocation gets a cold CUDA context, cold
torchinductor dynamo/triton caches (unless the filesystem cache is kept),
and pristine allocator state.

Subject grammar:
    flashinfer                      FlashInfer MLA decode, backend=auto
    baseline_eager                  baseline_bf16 without torch.compile
    baseline_compiled[=mode]        baseline_bf16 wrapped in torch.compile(mode)
                                    mode defaults to max-autotune-no-cudagraphs
    claude:INDEX                    record[INDEX] from candidates-json, compiled
                                    with the same default torch.compile mode

Output: one JSON object per run, one line. Always valid JSON even on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

# Path bootstrap so we can import prism-mla modules from any CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def emit(obj: dict) -> None:
    print(json.dumps(obj, default=str))


def _env_snapshot() -> dict:
    info = {
        "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "unset"),
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", "unset"),
        "TORCHINDUCTOR_CACHE_DIR": os.environ.get("TORCHINDUCTOR_CACHE_DIR", "unset"),
    }
    try:
        import torch
        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            info["device_name"] = torch.cuda.get_device_name(0)
            info["cc"] = str(torch.cuda.get_device_capability(0))
            info["cuda_runtime"] = torch.version.cuda
    except Exception as e:
        info["torch_err"] = f"{type(e).__name__}: {e}"
    try:
        import flashinfer
        info["flashinfer"] = getattr(flashinfer, "__version__", "unknown")
    except Exception:
        info["flashinfer"] = None
    return info


def _stats(samples_ns: list[int]) -> dict:
    s = sorted(samples_ns)
    n = len(s)
    def pct(p: float) -> float:
        if n == 0:
            return 0.0
        return float(s[min(int(p * n), n - 1)])
    return {
        "n": n,
        "p10_ns": pct(0.10),
        "p50_ns": pct(0.50),
        "p90_ns": pct(0.90),
        "p99_ns": pct(0.99),
        "max_ns": float(s[-1]) if n else 0.0,
        "mean_ns": float(statistics.fmean(samples_ns)) if n else 0.0,
        "stdev_ns": float(statistics.stdev(samples_ns)) if n > 1 else 0.0,
    }


def _nvidia_smi_clocks() -> dict:
    """Best-effort capture of current GPU clock and power. No sudo needed."""
    import subprocess
    out: dict = {}
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=clocks.sm,clocks.max.sm,power.draw,uuid",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [x.strip() for x in r.stdout.strip().split("\n")[0].split(",")]
            if len(parts) >= 4:
                out["clock_sm_mhz"] = int(parts[0]) if parts[0].isdigit() else None
                out["clock_max_sm_mhz"] = int(parts[1]) if parts[1].isdigit() else None
                try:
                    out["power_w"] = float(parts[2])
                except ValueError:
                    out["power_w"] = None
                out["gpu_uuid"] = parts[3]
    except Exception as e:
        out["smi_err"] = f"{type(e).__name__}: {e}"
    return out


def _build_flashinfer(config: dict, backend: str = "auto") -> tuple[callable, dict]:
    """Build FlashInfer MLA subject with an explicit backend choice.

    H1 support: `flashinfer` (default "auto"), `flashinfer=cutlass`,
    `flashinfer=fa3`, `flashinfer=fa2`. Subject string parsed in main().
    """
    from runner.flashinfer_runner import FlashInferMLAConfig, FlashInferMLAHarness
    fi_cfg = FlashInferMLAConfig(
        batch_size=config["batch"], kv_len=config["kv_len"], page_size=64,
        num_heads=128, head_dim_ckv=512, head_dim_kpe=64,
        q_dtype=config["dtype"], kv_dtype=config["dtype"], backend=backend,
    )
    h = FlashInferMLAHarness(fi_cfg, seed=config.get("seed", 0))
    v = h.verify_matches_reference()
    return h.run, {
        "max_abs_error": v["max_abs_error"],
        "out_shape": v["out_shape"],
        "flashinfer_backend": backend,
    }


def _build_flashinfer_cudagraph(config: dict) -> tuple[callable, dict]:
    """H6.1 subject: FlashInfer MLA decode wrapped in a CUDA Graph.

    Math doc §7 attributes ~70% of the torch.compile-vs-FlashInfer gap to
    per-launch overhead. A CUDA Graph captures one decode call and replays
    from a single launch, eliminating most of that overhead. Prediction:
    p50 = 13.0 ± 1.5 µs at H100 T=1024 (from 17.6 µs uncaptured).
    """
    from runner.flashinfer_runner import FlashInferMLAConfig, FlashInferMLAHarness
    fi_cfg = FlashInferMLAConfig(
        batch_size=config["batch"], kv_len=config["kv_len"], page_size=64,
        num_heads=128, head_dim_ckv=512, head_dim_kpe=64,
        q_dtype=config["dtype"], kv_dtype=config["dtype"], backend="auto",
        use_cuda_graph=True,
    )
    h = FlashInferMLAHarness(fi_cfg, seed=config.get("seed", 0))
    v = h.verify_matches_reference()
    # Build the graph AFTER verification (verification uses h.run() which
    # does NOT pass out=; the graph path uses h.run_graph()).
    h.prepare_cuda_graph()
    return h.run_graph, {"max_abs_error": v["max_abs_error"], "out_shape": v["out_shape"]}


def _build_torch_subject(subject: str, config: dict, candidates_json: str | None):
    import torch
    from agent.torch_stub_mutations import TORCH_CANDIDATES
    from kernels.base.mla_decode_torch import (
        TorchMLAConfig, make_torch_inputs, mla_decode_torch_reference,
    )
    from prism.validator_torch import validate_torch

    # Identify source function.
    if subject.startswith("baseline"):
        fn = next(c for c in TORCH_CANDIDATES if c.name == "baseline_bf16").fn
    elif subject.startswith("claude:"):
        idx = int(subject.split(":", 1)[1])
        assert candidates_json, "claude subject requires --candidates-json"
        payload = json.loads(Path(candidates_json).read_text())
        rec = next(r for r in payload["records"] if r.get("index") == idx)
        if not rec.get("compile_ok"):
            raise RuntimeError(f"claude record #{idx} failed safety: {rec.get('compile_error')}")
        from agent.safety import compile_candidate_torch
        fn = compile_candidate_torch(rec["source"])
    else:
        raise ValueError(f"unknown torch subject: {subject}")

    # Optional torch.compile.
    compile_s = 0.0
    if subject == "baseline_compiled" or subject.startswith("baseline_compiled="):
        mode = "max-autotune-no-cudagraphs"
        if "=" in subject:
            mode = subject.split("=", 1)[1]
        fn = torch.compile(fn, mode=mode, fullgraph=False, dynamic=False)
    elif subject == "baseline_eager":
        pass
    elif subject.startswith("claude:"):
        fn = torch.compile(fn, mode="max-autotune-no-cudagraphs", fullgraph=False, dynamic=False)

    # Inputs.
    t_cfg = TorchMLAConfig(
        batch=config["batch"], heads=128, kv_len=config["kv_len"],
        d_ckv=512, d_pe=64, dtype=config["dtype"],
    )
    inputs = make_torch_inputs(t_cfg, seed=config.get("seed", 0))

    # First call triggers any JIT / autotune — measure compile_s.
    t0 = time.perf_counter()
    v = validate_torch(fn, mla_decode_torch_reference, inputs,
                       tolerance=5e-2, run_tier2=False)
    compile_s = time.perf_counter() - t0
    if not v.passed:
        raise RuntimeError(f"validator rejected {subject}: {v.failed_check}")

    def _invoke():
        return fn(**inputs)

    return _invoke, {"compile_s": compile_s, "max_abs_error": v.max_abs_error}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True,
                    help="flashinfer | baseline_eager | baseline_compiled[=MODE] | claude:INDEX")
    ap.add_argument("--candidates-json", default=None,
                    help="path to mutations JSON (required for claude:INDEX subjects)")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--kv-len", type=int, default=1024)
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--replicate", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--discard-first", type=int, default=5,
                    help="number of timed samples to discard (post-warmup stabilization)")
    args = ap.parse_args()

    config = {
        "batch": args.batch, "kv_len": args.kv_len, "dtype": args.dtype,
        "seed": args.seed,
    }
    env = _env_snapshot()
    clock_start = _nvidia_smi_clocks()

    result = {
        "subject": args.subject,
        "config": config,
        "replicate": args.replicate,
        "warmup": args.warmup,
        "iters": args.iters,
        "discard_first": args.discard_first,
        "env": env,
        "clock_start": clock_start,
        "ts_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        import torch
        if not torch.cuda.is_available():
            result["status"] = "no_cuda"
            emit(result); return 2

        # Build subject.
        t_build0 = time.perf_counter()
        if args.subject == "flashinfer":
            invoke, build_info = _build_flashinfer(config, backend="auto")
        elif args.subject.startswith("flashinfer="):
            backend = args.subject.split("=", 1)[1]
            if backend not in ("auto", "cutlass", "fa3", "fa2"):
                raise ValueError(
                    f"flashinfer backend {backend!r} not in "
                    f"{{auto, cutlass, fa3, fa2}}"
                )
            invoke, build_info = _build_flashinfer(config, backend=backend)
        elif args.subject == "flashinfer_cudagraph":
            invoke, build_info = _build_flashinfer_cudagraph(config)
        else:
            invoke, build_info = _build_torch_subject(args.subject, config, args.candidates_json)
        result["build_s"] = time.perf_counter() - t_build0
        result.update(build_info)

        # Warmup (untimed).
        for _ in range(args.warmup):
            invoke()
        torch.cuda.synchronize()

        # Cold call — first call in the timed loop, pre-discard.
        starts = [torch.cuda.Event(enable_timing=True) for _ in range(args.iters)]
        ends = [torch.cuda.Event(enable_timing=True) for _ in range(args.iters)]
        for i in range(args.iters):
            starts[i].record()
            invoke()
            ends[i].record()
        torch.cuda.synchronize()

        times_ns = [int(starts[i].elapsed_time(ends[i]) * 1e6) for i in range(args.iters)]
        result["cold_ns"] = times_ns[0] if times_ns else 0
        kept = times_ns[args.discard_first:]
        result["warm"] = _stats(kept)
        result["tokens_per_sec"] = (
            config["batch"] / (result["warm"]["p50_ns"] / 1e9) if result["warm"]["p50_ns"] > 0 else 0.0
        )
        result["clock_end"] = _nvidia_smi_clocks()
        result["ts_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["status"] = "ok"
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
        emit(result); return 3

    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
