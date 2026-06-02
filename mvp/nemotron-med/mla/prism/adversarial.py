"""Adversarial input battery for the Tier-2 validator.

Each input exercises a known numerics-bug class. Sources:
    - Published numerical-stability literature on attention kernels
    - Internal bug corpus (LSE overflow, causal index fix, etc.)
    - Red-team adversarial patterns (numerics-as-weapon)

The module exposes `build_adversarial_battery(shape_hint)` that returns a list
of input dicts sized to the user's kernel signature. A caller wires each dict
through validator.validate(..., adversarial_inputs=[...]).
"""
from __future__ import annotations

from typing import Any

import numpy as np


def _large_range_qk(shape_hint: dict[str, int]) -> dict[str, Any]:
    """Q and K with extreme magnitudes on some rows, normal on others. Catches
    softmax overflow / LSE stride bugs."""
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 8)
    seqlen = shape_hint.get("seqlen", 128)
    dhead = shape_hint.get("dhead", 64)
    Q = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    K = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    V = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    # Poison: one row of K has magnitude 1e3 so QK^T dominates softmax.
    K[:, :, 0, :] *= 1e3
    return {"Q": Q, "K": K, "V": V}


def _all_zeros_in_one_head(shape_hint: dict[str, int]) -> dict[str, Any]:
    """A whole head has zero K and V. Should produce uniform softmax."""
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 8)
    seqlen = shape_hint.get("seqlen", 128)
    dhead = shape_hint.get("dhead", 64)
    Q = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    K = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    V = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    K[:, 0, :, :] = 0.0
    V[:, 0, :, :] = 0.0
    return {"Q": Q, "K": K, "V": V}


def _degenerate_seqlen_one(shape_hint: dict[str, int]) -> dict[str, Any]:
    """seqlen=1. Many kernels have off-by-one bugs here (seqlen==0 has been a
    reported crash; seqlen==1 is the next cliff)."""
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 8)
    dhead = shape_hint.get("dhead", 64)
    Q = np.random.randn(batch, heads, 1, dhead).astype(np.float32)
    K = np.random.randn(batch, heads, 1, dhead).astype(np.float32)
    V = np.random.randn(batch, heads, 1, dhead).astype(np.float32)
    return {"Q": Q, "K": K, "V": V}


def _very_long_seqlen(shape_hint: dict[str, int]) -> dict[str, Any]:
    """Long sequence probes accumulator precision drift."""
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 8)
    dhead = shape_hint.get("dhead", 64)
    seqlen = shape_hint.get("long_seqlen", 4096)
    Q = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32) * 0.02
    K = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32) * 0.02
    V = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32) * 0.02
    return {"Q": Q, "K": K, "V": V}


def _denormal_values(shape_hint: dict[str, int]) -> dict[str, Any]:
    """Inputs containing denormal floats. Some tensor-core paths flush to zero
    silently; agreement with reference is the check."""
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 8)
    seqlen = shape_hint.get("seqlen", 128)
    dhead = shape_hint.get("dhead", 64)
    tiny = np.finfo(np.float32).tiny
    Q = np.random.uniform(-tiny, tiny, size=(batch, heads, seqlen, dhead)).astype(np.float32)
    K = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    V = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    return {"Q": Q, "K": K, "V": V}


def _near_identical_q_rows(shape_hint: dict[str, int]) -> dict[str, Any]:
    """Q rows are near-identical except for epsilon noise. Catches precision
    bugs where the kernel treats them as identical (hash collision in tile
    scheduler, for instance)."""
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 8)
    seqlen = shape_hint.get("seqlen", 128)
    dhead = shape_hint.get("dhead", 64)
    base = np.random.randn(1, heads, 1, dhead).astype(np.float32)
    Q = np.broadcast_to(base, (batch, heads, seqlen, dhead)).copy()
    Q += np.random.randn(*Q.shape).astype(np.float32) * 1e-5
    K = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    V = np.random.randn(batch, heads, seqlen, dhead).astype(np.float32)
    return {"Q": Q, "K": K, "V": V}


def build_adversarial_battery(
    shape_hint: dict[str, int] | None = None,
    *,
    include_long: bool = True,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Return a standard battery of adversarial inputs.

    shape_hint keys: batch, heads, seqlen, dhead, long_seqlen (optional).
    """
    np.random.seed(seed)
    hint = {"batch": 1, "heads": 8, "seqlen": 128, "dhead": 64}
    if shape_hint:
        hint.update(shape_hint)
    battery = [
        _large_range_qk(hint),
        _all_zeros_in_one_head(hint),
        _degenerate_seqlen_one(hint),
        _denormal_values(hint),
        _near_identical_q_rows(hint),
    ]
    if include_long:
        battery.append(_very_long_seqlen(hint))
    return battery
