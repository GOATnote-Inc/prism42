"""Tests for the Robust-KBench gaming-pattern detectors.

Each test proves a detector catches the specific shortcut class described in
arXiv:2509.14279 §3. If a test passes a known cheating kernel, the validator's
anti-gaming tier is broken.
"""
from __future__ import annotations

import numpy as np
import pytest

from prism import (
    check_init_robustness,
    check_no_trivial_delegation,
    check_output_range,
    check_output_std,
    check_per_axis_variation,
    check_shape_generalization,
    validate,
)


def reference_attention(Q, K, V):
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


# ---- Check 1: Output Range ----

def test_output_range_rejects_near_zero_output():
    near_zero = np.random.randn(2, 4, 8, 16).astype(np.float32) * 1e-4
    r = check_output_range(near_zero)
    assert not r.passed
    assert "max(abs(output))" in r.reason


def test_output_range_passes_normal_output():
    normal = np.random.randn(2, 4, 8, 16).astype(np.float32)
    r = check_output_range(normal)
    assert r.passed


# ---- Check 2: Standard Deviation ----

def test_output_std_rejects_constant():
    const = np.full((2, 4, 8, 16), 3.14, dtype=np.float32)
    r = check_output_std(const)
    assert not r.passed


def test_output_std_passes_normal():
    normal = np.random.randn(2, 4, 8, 16).astype(np.float32)
    r = check_output_std(normal)
    assert r.passed


# ---- Check 3: Per-Axis Variation ----

def test_per_axis_rejects_broadcast_collapse():
    # All heads identical -> std along head axis is zero.
    base = np.random.randn(2, 1, 8, 16).astype(np.float32)
    collapsed = np.broadcast_to(base, (2, 4, 8, 16)).copy()
    r = check_per_axis_variation(collapsed)
    assert not r.passed
    assert r.value["worst_axis"] == 1


def test_per_axis_passes_normal():
    normal = np.random.randn(2, 4, 8, 16).astype(np.float32)
    r = check_per_axis_variation(normal)
    assert r.passed


# ---- Check 4: Init Robustness ----

def test_init_robustness_catches_seed_hardcode():
    # This candidate only returns correct values for seed=0 default Q.
    gold_Q = np.random.default_rng(0).standard_normal((1, 4, 32, 16)).astype(np.float32)
    def seed_cheat(Q, K, V):
        if np.allclose(Q, gold_Q):
            return reference_attention(Q, K, V)
        return np.zeros_like(reference_attention(Q, K, V))
    r = check_init_robustness(
        seed_cheat,
        reference_attention,
        {"batch": 1, "heads": 4, "seqlen": 32, "dhead": 16},
        seeds=(0, 17, 42),
        distributions=("normal", "uniform"),
    )
    assert not r.passed


def test_init_robustness_passes_correct_kernel():
    r = check_init_robustness(
        reference_attention,
        reference_attention,
        {"batch": 1, "heads": 4, "seqlen": 32, "dhead": 16},
    )
    assert r.passed


# ---- Check 5: Shape Generalization ----

def test_shape_generalization_catches_hardcoded_shape():
    def shape_cheat(Q, K, V):
        if Q.shape[-2] == 32:
            return reference_attention(Q, K, V)
        return np.zeros_like(reference_attention(Q, K, V))
    r = check_shape_generalization(
        shape_cheat,
        reference_attention,
        {"batch": 1, "heads": 4, "seqlen": 32, "dhead": 16},
    )
    assert not r.passed


def test_shape_generalization_passes_correct_kernel():
    r = check_shape_generalization(
        reference_attention,
        reference_attention,
        {"batch": 1, "heads": 4, "seqlen": 32, "dhead": 16},
    )
    assert r.passed


# ---- Check 6: No Trivial Delegation ----

def test_delegation_catches_reference_call():
    def delegating(Q, K, V):
        return reference_attention(Q, K, V)
    r = check_no_trivial_delegation(delegating)
    assert not r.passed
    assert "reference_attention" in r.reason or "reference(" in r.reason


def test_delegation_passes_original():
    def original(Q, K, V):
        scale = 1.0 / np.sqrt(Q.shape[-1])
        w = np.einsum("bhid,bhjd->bhij", Q, K) * scale
        w = np.exp(w - w.max(-1, keepdims=True))
        w /= w.sum(-1, keepdims=True)
        return np.einsum("bhij,bhjd->bhid", w, V)
    r = check_no_trivial_delegation(original)
    assert r.passed


# ---- Validator integration: anti_gaming flag ----

def test_validator_anti_gaming_catches_constant_output():
    def constant_zeros(Q, K, V):
        return np.zeros_like(reference_attention(Q, K, V))
    result = validate(
        constant_zeros,
        lambda Q, K, V: np.zeros_like(Q),  # ref also zeros so Tier 1 passes
        _rand_inputs(),
        tolerance=1e-2,
        anti_gaming=True,
        shape_hint={"batch": 1, "heads": 4, "seqlen": 32, "dhead": 16},
    )
    assert not result.passed
    assert result.tier_failed_at == 2
    assert "gaming check" in result.failed_check
    # Should fail on output_range or output_std (first in the list that fires)
    assert "output_range" in result.failed_check or "output_std" in result.failed_check


def test_validator_anti_gaming_passes_correct_kernel():
    # Candidate is mathematically equivalent but implemented differently — so
    # no trivial-delegation hit. Uses batch=2 so per-axis variation is
    # measurable on every axis.
    def correct_but_distinct(Q, K, V):
        scale = 1.0 / np.sqrt(Q.shape[-1])
        s = np.einsum("bhid,bhjd->bhij", Q, K) * scale
        s -= s.max(axis=-1, keepdims=True)
        e = np.exp(s)
        w = e / e.sum(axis=-1, keepdims=True)
        return np.einsum("bhij,bhjd->bhid", w, V)

    result = validate(
        correct_but_distinct,
        reference_attention,
        _rand_inputs(batch=2),
        anti_gaming=True,
        shape_hint={"batch": 2, "heads": 4, "seqlen": 32, "dhead": 16},
    )
    assert result.passed, result
    assert result.tier_reached == 2
    assert "tier2_gaming_checks" in result.details
    assert all(c["passed"] for c in result.details["tier2_gaming_checks"])
