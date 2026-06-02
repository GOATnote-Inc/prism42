"""CPU-safe tests for runner/flashinfer_runner.

These run on a Mac laptop (no CUDA). They verify:
    - module imports cleanly without torch / flashinfer
    - helper functions are pure-python-safe
    - require_gpu_environment() raises with a clear message when deps are absent
    - BenchmarkResult is numeric-compatible with runner.numpy_runner's result

The CUDA-dependent tests live in test_flashinfer_runner_cuda.py (marked
pytest.mark.cuda; skipped on non-CUDA hosts).
"""
from __future__ import annotations

import pytest

from runner import flashinfer_runner as fir


def test_module_imports_without_error():
    assert hasattr(fir, "FlashInferMLAConfig")
    assert hasattr(fir, "FlashInferMLAHarness")
    assert hasattr(fir, "run_flashinfer_mla_decode")
    assert hasattr(fir, "benchmark_flashinfer_mla")
    assert hasattr(fir, "environment_report")


def test_constants_match_deepseek_dimensions():
    assert fir.DEEPSEEK_NUM_HEADS == 128
    assert fir.DEEPSEEK_KV_LORA_RANK == 512
    assert fir.DEEPSEEK_QK_ROPE_DIM == 64
    assert fir.DEEPSEEK_HEAD_DIM_TOTAL == 576


def test_config_default_sm_scale_matches_formula():
    import math
    cfg = fir.FlashInferMLAConfig()
    assert cfg.sm_scale is None
    expected = 1.0 / math.sqrt(576)
    assert abs(cfg.effective_sm_scale - expected) < 1e-9


def test_config_explicit_sm_scale_overrides():
    cfg = fir.FlashInferMLAConfig(sm_scale=0.125)
    assert cfg.effective_sm_scale == 0.125


def test_have_flashinfer_returns_bool():
    """Either True or False, but never raises. On Mac, False."""
    v = fir.have_flashinfer()
    assert isinstance(v, bool)


def test_have_cuda_returns_bool():
    v = fir.have_cuda()
    assert isinstance(v, bool)


def test_require_gpu_environment_raises_without_cuda():
    if fir.have_cuda() and fir.have_flashinfer():
        pytest.skip("this host has CUDA+flashinfer; raise path untestable here")
    with pytest.raises(RuntimeError):
        fir.require_gpu_environment()


def test_environment_report_is_serializable():
    import json
    report = fir.environment_report()
    assert "have_torch" in report
    assert "have_flashinfer" in report
    # Must be JSON-serializable so it can be piped into logs.
    json.dumps(report)


def test_benchmark_result_has_matching_fields():
    """BenchmarkResult fields must match numpy_runner.BenchmarkResult so
    downstream code can consume either type identically."""
    from runner.numpy_runner import BenchmarkResult as NpResult
    np_fields = set(NpResult.__dataclass_fields__.keys())
    fi_fields = set(fir.BenchmarkResult.__dataclass_fields__.keys())
    assert np_fields == fi_fields, (
        f"BenchmarkResult fields drifted: "
        f"numpy={np_fields}  flashinfer={fi_fields}"
    )


def test_harness_raises_on_cpu_host():
    if fir.have_cuda() and fir.have_flashinfer():
        pytest.skip("GPU host — use the cuda test file")
    cfg = fir.FlashInferMLAConfig()
    with pytest.raises(RuntimeError):
        fir.FlashInferMLAHarness(cfg)
