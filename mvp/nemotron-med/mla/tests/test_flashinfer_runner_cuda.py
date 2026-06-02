"""GPU-only tests for runner/flashinfer_runner.

Gated with pytest.mark.cuda and a runtime skip — they only execute when
both torch-cuda and flashinfer are importable. Runs on every H100 /
B200 pod during verify; silently skipped elsewhere.

Run explicitly:
    pytest tests/test_flashinfer_runner_cuda.py -v

These tests are the load-bearing correctness check for the FlashInfer
runner. If they fail, the evolve loop cannot trust GPU benchmark numbers.
"""
from __future__ import annotations

import pytest

from runner import flashinfer_runner as fir

pytestmark = pytest.mark.cuda


def _skip_without_gpu():
    if not fir.have_cuda():
        pytest.skip("CUDA not available")
    if not fir.have_flashinfer():
        pytest.skip("flashinfer not installed")


def test_environment_has_gpu():
    _skip_without_gpu()
    rep = fir.environment_report()
    assert rep["cuda_available"] is True
    assert rep["cuda_device_count"] >= 1
    assert isinstance(rep["device_name"], str)


@pytest.mark.parametrize("backend", ["auto"])
def test_harness_constructs(backend):
    _skip_without_gpu()
    cfg = fir.FlashInferMLAConfig(
        batch_size=1, kv_len=256, page_size=64, backend=backend,
    )
    h = fir.FlashInferMLAHarness(cfg, seed=0)
    assert h.workspace.is_cuda
    assert h.q_nope.shape == (1, 128, 512)
    assert h.q_pe.shape == (1, 128, 64)


@pytest.mark.parametrize("backend", ["auto"])
def test_single_run_produces_correct_shape(backend):
    _skip_without_gpu()
    cfg = fir.FlashInferMLAConfig(
        batch_size=1, kv_len=256, page_size=64, backend=backend,
    )
    h = fir.FlashInferMLAHarness(cfg, seed=0)
    out = h.run()
    assert out.shape == (1, 128, 512)
    assert out.is_cuda


def test_matches_torch_reference():
    _skip_without_gpu()
    cfg = fir.FlashInferMLAConfig(
        batch_size=1, kv_len=256, page_size=64, backend="auto",
    )
    h = fir.FlashInferMLAHarness(cfg, seed=0)
    v = h.verify_matches_reference()
    assert v["passed"], (
        f"flashinfer vs torch-ref diverge: max_err={v['max_abs_error']:.3e} "
        f"mean_err={v['mean_abs_error']:.3e}"
    )


def test_benchmark_produces_sensible_numbers():
    _skip_without_gpu()
    cfg = fir.FlashInferMLAConfig(
        batch_size=1, kv_len=1024, page_size=64, backend="auto",
    )
    h = fir.FlashInferMLAHarness(cfg, seed=0)
    b = fir.benchmark_flashinfer_mla(h, warmup=5, iters=30)
    # H100: DeepSeek decode should land in the microsecond range.
    assert 1e3 < b.median_ns < 1e7, (
        f"benchmark out of plausible range: median={b.median_ns} ns"
    )
    # Throughput positive and reasonable.
    assert b.tokens_per_sec > 100


def test_run_flashinfer_mla_decode_end_to_end():
    _skip_without_gpu()
    cfg = fir.FlashInferMLAConfig(
        batch_size=1, kv_len=512, page_size=64, backend="auto",
    )
    result = fir.run_flashinfer_mla_decode(cfg, seed=0)
    assert result["verify"]["passed"]
    assert result["bench"]["median_ns"] > 0
