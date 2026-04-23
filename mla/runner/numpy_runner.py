"""Pure-numpy benchmark runner — stand-in for FlashInfer until real GPU.

This runner is deliberately dumb: it times a kernel with perf_counter_ns over
a warmup + measurement sweep and returns statistics. The signature matches the
eventual FlashInfer runner so swapping backends is a one-line change.

Why numpy now: the laptop running this archive has no CUDA. The validator and
the loop shape stabilize here, then the same loop drives a FlashInfer runner
on real H100/B200.

Cross-ref: mental-models/munger-inversion.md §6 (benchmarks are often wrong);
config_sweep in the validator is the measurement-side complement.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping


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


def benchmark(
    kernel: Callable,
    inputs: Mapping,
    *,
    warmup: int = 3,
    iters: int = 20,
    tokens_per_call: int = 1,
) -> BenchmarkResult:
    """Benchmark a kernel on a single input set.

    Args:
        kernel: the callable to time.
        inputs: kwargs passed to kernel each call.
        warmup: untimed calls to settle caches / JIT. Kept low for numpy.
        iters: timed iterations; statistics computed from these.
        tokens_per_call: for tokens/sec headline metric (1 for decode).
    """
    # Warmup
    for _ in range(warmup):
        kernel(**inputs)

    samples: list[int] = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        kernel(**inputs)
        t1 = time.perf_counter_ns()
        samples.append(t1 - t0)

    mean = statistics.fmean(samples)
    median = statistics.median(samples)
    # Manual p90 because statistics.quantiles can split oddly at small n.
    p90 = sorted(samples)[int(len(samples) * 0.9) - 1]
    std = statistics.stdev(samples) if len(samples) > 1 else 0.0
    tps = tokens_per_call / (median / 1e9) if median > 0 else 0.0
    return BenchmarkResult(
        mean_ns=mean,
        median_ns=median,
        p90_ns=float(p90),
        std_ns=std,
        iters=iters,
        tokens_per_sec=tps,
        raw_ns=samples,
    )
