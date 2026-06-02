"""Tests for the two-tier validator.

Every test proves the validator *catches* a specific failure class described in
mental-models/munger-inversion.md or red-team-adversarial.md. If a test starts
passing a kernel that it should reject, the whole premise of the loop breaks.
"""
from __future__ import annotations

import numpy as np
import pytest

from prism import (
    DEFAULT_INVARIANTS,
    NO_EXTREME_VALUES,
    OUTPUT_ROW_NORMS_BOUNDED,
    TOPK_AGREEMENT,
    build_adversarial_battery,
    validate,
)


# ---- reference kernel: plain numpy multi-head attention ----

def reference_attention(Q, K, V):
    """Numerically-stable multi-head attention. Shape: (B, H, S, D)."""
    scale = 1.0 / np.sqrt(Q.shape[-1])
    logits = np.einsum("bhid,bhjd->bhij", Q, K) * scale
    logits -= logits.max(axis=-1, keepdims=True)
    w = np.exp(logits)
    w /= w.sum(axis=-1, keepdims=True)
    return np.einsum("bhij,bhjd->bhid", w, V)


def _rand_inputs(seqlen=32, dhead=16, batch=1, heads=4, seed=0):
    rng = np.random.default_rng(seed)
    return {
        "Q": rng.standard_normal((batch, heads, seqlen, dhead)).astype(np.float32),
        "K": rng.standard_normal((batch, heads, seqlen, dhead)).astype(np.float32),
        "V": rng.standard_normal((batch, heads, seqlen, dhead)).astype(np.float32),
    }


# ---- golden path ----

def test_identical_kernels_pass_tier2():
    inputs = _rand_inputs()
    result = validate(reference_attention, reference_attention, inputs, run_tier2=True)
    assert result.passed
    assert result.tier_reached == 2
    assert result.max_abs_error == pytest.approx(0.0, abs=1e-6)


# ---- Tier 1 rejection tests ----

def test_rejects_shape_mismatch():
    def bad(Q, K, V):
        return reference_attention(Q, K, V)[..., :-1]  # last dim shorter
    result = validate(bad, reference_attention, _rand_inputs())
    assert not result.passed
    assert result.tier_failed_at == 1
    assert "shape mismatch" in result.failed_check


def test_rejects_nan_output():
    def bad(Q, K, V):
        out = reference_attention(Q, K, V)
        out[0, 0, 0, 0] = np.nan
        return out
    result = validate(bad, reference_attention, _rand_inputs())
    assert not result.passed
    assert "NaN" in result.failed_check or "Inf" in result.failed_check


def test_rejects_inf_output():
    def bad(Q, K, V):
        out = reference_attention(Q, K, V)
        out[0, 0, 0, 0] = np.inf
        return out
    result = validate(bad, reference_attention, _rand_inputs())
    assert not result.passed
    assert "NaN" in result.failed_check or "Inf" in result.failed_check


def test_rejects_large_numerical_error():
    def bad(Q, K, V):
        return reference_attention(Q, K, V) + 1.0  # constant offset 1.0
    result = validate(bad, reference_attention, _rand_inputs(), tolerance=1e-3)
    assert not result.passed
    assert result.tier_failed_at == 1
    assert "tier1 max_abs_error" in result.failed_check


def test_rejects_nondeterministic_kernel():
    rng = np.random.default_rng(42)
    def nondet(Q, K, V):
        out = reference_attention(Q, K, V)
        out += rng.standard_normal(out.shape).astype(np.float32) * 1e-6  # tiny noise, below tolerance
        return out
    result = validate(nondet, reference_attention, _rand_inputs(), tolerance=1e-2)
    assert not result.passed
    assert result.tier_failed_at == 1
    assert "non-deterministic" in result.failed_check


def test_rejects_kernel_that_raises():
    def raises(Q, K, V):
        raise RuntimeError("CUDA out of memory")
    result = validate(raises, reference_attention, _rand_inputs())
    assert not result.passed
    assert result.tier_failed_at == 1
    assert "CUDA out of memory" in result.failed_check


# ---- Tier 1 success but should be rejected at Tier 2 ----

def test_tier2_rejects_extreme_output():
    # Candidate produces an output 1e6 larger than ref — but only inside tolerance
    # relative... no, here we rig it so tier 1 tolerance is huge but NO_EXTREME_VALUES fires.
    def inflated(Q, K, V):
        return reference_attention(Q, K, V) * 1e5
    result = validate(
        inflated,
        reference_attention,
        _rand_inputs(),
        tolerance=1e10,  # pass Tier 1 trivially
        invariants=[NO_EXTREME_VALUES],
    )
    assert not result.passed
    assert result.tier_failed_at == 2
    assert "no_extreme_values" in result.failed_check


def test_tier2_rejects_unbounded_output_norm():
    # Output norms exceed V norms -> fails row-norm invariant
    def bad(Q, K, V):
        return V * 1000  # completely ignores attention math
    result = validate(
        bad,
        reference_attention,
        _rand_inputs(),
        tolerance=1e10,  # pass Tier 1
        invariants=[OUTPUT_ROW_NORMS_BOUNDED],
    )
    assert not result.passed
    assert "output_row_norms_bounded" in result.failed_check


def test_tier2_config_sweep_catches_config_overfit():
    # Candidate matches ref only when seqlen==32; fails at seqlen==64.
    def overfit(Q, K, V):
        if Q.shape[-2] == 32:
            return reference_attention(Q, K, V)
        return np.zeros_like(reference_attention(Q, K, V))  # garbage at other sizes
    result = validate(
        overfit,
        reference_attention,
        _rand_inputs(seqlen=32),
        config_sweep=[_rand_inputs(seqlen=64, seed=1)],
    )
    assert not result.passed
    assert result.tier_failed_at == 2
    assert "config-sweep" in result.failed_check


def test_tier2_adversarial_catches_nan_on_denormal():
    def bad(Q, K, V):
        out = reference_attention(Q, K, V)
        # only misbehave when Q has denormal values
        if np.abs(Q).max() < 1e-30:
            out[...] = np.nan
        return out
    battery = build_adversarial_battery(shape_hint={"seqlen": 32, "dhead": 16, "heads": 4}, include_long=False)
    result = validate(
        bad,
        reference_attention,
        _rand_inputs(),
        adversarial_inputs=battery,
    )
    assert not result.passed
    assert result.tier_failed_at == 2
    assert "adversarial" in result.failed_check


# ---- Tier 2 golden path with full default invariants ----

def test_tier2_passes_with_default_invariants():
    result = validate(
        reference_attention,
        reference_attention,
        _rand_inputs(),
        invariants=DEFAULT_INVARIANTS,
    )
    assert result.passed
    assert result.tier_reached == 2


# ---- ValidationResult protocol ----

def test_validation_result_is_truthy():
    inputs = _rand_inputs()
    result = validate(reference_attention, reference_attention, inputs)
    assert bool(result) is True


def test_validation_result_is_falsy_on_fail():
    def bad(Q, K, V):
        out = reference_attention(Q, K, V)
        out[0, 0, 0, 0] = np.nan
        return out
    result = validate(bad, reference_attention, _rand_inputs())
    assert bool(result) is False


# ---- Topk-agreement smoke ----

def test_topk_invariant_passes_for_matching_outputs():
    rng = np.random.default_rng(7)
    a = rng.standard_normal((2, 4, 8, 64)).astype(np.float32)
    check = TOPK_AGREEMENT.run(a, a, {})
    assert check["passed"]


def test_topk_invariant_rejects_scrambled():
    rng = np.random.default_rng(7)
    a = rng.standard_normal((2, 4, 8, 64)).astype(np.float32)
    b = -a  # argmax inverted
    check = TOPK_AGREEMENT.run(a, b, {})
    assert not check["passed"]
