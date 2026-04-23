"""CUDA-event benchmark harness for torch MLA candidates.

Contract-compatible BenchmarkResult with runner/numpy_runner.py and
runner/flashinfer_runner.py — the evolve loop can be pointed at any of
the three without changes to its scoring code.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable


try:
    import torch
    _HAVE_TORCH = True
except ImportError:
    torch = None  # type: ignore
    _HAVE_TORCH = False


@dataclass
class BenchmarkResult:
    mean_ns: float
    median_ns: float
    p90_ns: float
    std_ns: float
    iters: int
    tokens_per_sec: float
    raw_ns: list[int] = field(default_factory=list)

    @property
    def mean_s(self) -> float:
        return self.mean_ns / 1e9

    @property
    def median_s(self) -> float:
        return self.median_ns / 1e9


def have_cuda() -> bool:
    return _HAVE_TORCH and torch.cuda.is_available()


def benchmark_torch(
    kernel: Callable,
    inputs: dict[str, Any],
    *,
    warmup: int = 10,
    iters: int = 50,
    batch_size: int = 1,
) -> BenchmarkResult:
    """Benchmark a torch callable using torch.cuda.Event.

    `kernel` is called as `kernel(**inputs)` and must return a GPU tensor.
    `tokens_per_sec` uses batch_size / median so it compares fairly against
    flashinfer's and numpy's results on the same config.
    """
    if not have_cuda():
        raise RuntimeError("benchmark_torch requires torch.cuda")

    for _ in range(warmup):
        kernel(**inputs)
    torch.cuda.synchronize()

    starts = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    ends = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for i in range(iters):
        starts[i].record()
        kernel(**inputs)
        ends[i].record()
    torch.cuda.synchronize()

    times_ns = [int(starts[i].elapsed_time(ends[i]) * 1e6) for i in range(iters)]
    mean = statistics.fmean(times_ns)
    median = statistics.median(times_ns)
    p90 = sorted(times_ns)[int(len(times_ns) * 0.9) - 1]
    std = statistics.stdev(times_ns) if len(times_ns) > 1 else 0.0
    tps = (batch_size / (median / 1e9)) if median > 0 else 0.0
    return BenchmarkResult(
        mean_ns=mean, median_ns=median, p90_ns=float(p90), std_ns=std,
        iters=iters, tokens_per_sec=tps, raw_ns=times_ns,
    )
