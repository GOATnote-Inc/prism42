"""Gaming-pattern detectors from Robust-KBench (arXiv:2509.14279, Apache-2.0).

The six checks detect kernels that pass a naive allclose(candidate, reference)
but cheat: constant outputs, zero-variance outputs, broadcast collapse,
init-seed hardcoding, shape hardcoding, trivial reference-op delegation.

Each check is a cheap structural probe run *before* expensive benchmarking.
Tolerance floor op_atol = op_rtol = 1e-5 is Robust-KBench's default; 0.01 is
the structural threshold for non-degeneracy.

Sources: notes in ../papers/notes-robust-kbench.md.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np


@dataclass
class GamingCheckResult:
    check: str
    passed: bool
    reason: str
    value: Any = None


Kernel = Callable[..., np.ndarray]


# ---- Check 1: Output Range ----
def check_output_range(
    out: np.ndarray,
    *,
    min_abs_max: float = 0.01,
) -> GamingCheckResult:
    """Reject outputs clamped near zero — a common cheat for passing allclose
    on near-zero references. Numeric tensors should have some dynamic range."""
    abs_max = float(np.max(np.abs(out)))
    return GamingCheckResult(
        "output_range",
        abs_max >= min_abs_max,
        f"max(abs(output)) = {abs_max:.3e}, min required = {min_abs_max:.3e}",
        abs_max,
    )


# ---- Check 2: Standard Deviation ----
def check_output_std(
    out: np.ndarray,
    *,
    min_std: float = 0.01,
) -> GamingCheckResult:
    """Reject constant-tensor outputs that happen to match a reference mean."""
    std = float(np.std(out))
    return GamingCheckResult(
        "output_std",
        std >= min_std,
        f"std(output) = {std:.3e}, min required = {min_std:.3e}",
        std,
    )


# ---- Check 3: Per-Axis Variation ----
def check_per_axis_variation(
    out: np.ndarray,
    *,
    min_std_per_axis: float = 0.01,
) -> GamingCheckResult:
    """Reject outputs that are constant along any axis — broadcast-collapse
    shortcut. Compute std along each axis; every axis must clear the floor."""
    worst_axis = -1
    worst_std = float("inf")
    for axis in range(out.ndim):
        # Size-1 axes carry no variation to measure; skip — not a cheat.
        if out.shape[axis] < 2:
            continue
        std_axis = float(np.mean(np.std(out, axis=axis)))
        if std_axis < worst_std:
            worst_std = std_axis
            worst_axis = axis
    if worst_axis == -1:
        return GamingCheckResult(
            "per_axis_variation",
            True,
            "all axes are size 1; variation not measurable",
            {"worst_axis": None, "worst_std": None},
        )
    return GamingCheckResult(
        "per_axis_variation",
        worst_std >= min_std_per_axis,
        f"worst-axis mean std = {worst_std:.3e} (axis {worst_axis}), min = {min_std_per_axis:.3e}",
        {"worst_axis": worst_axis, "worst_std": worst_std},
    )


# ---- Check 4: Initialization Impact ----
def check_init_robustness(
    candidate: Kernel,
    reference: Kernel,
    shape_hint: Mapping[str, int],
    *,
    seeds: tuple[int, ...] = (0, 17, 42),
    distributions: tuple[str, ...] = ("normal", "uniform"),
    tolerance: float = 1e-2,
) -> GamingCheckResult:
    """Re-run the candidate under multiple seeds and distributions. Outputs
    must continue to match the reference. Catches kernels that hardcode values
    for one specific init."""
    failures: list[str] = []
    batch = shape_hint.get("batch", 1)
    heads = shape_hint.get("heads", 4)
    seqlen = shape_hint.get("seqlen", 32)
    dhead = shape_hint.get("dhead", 16)
    shape = (batch, heads, seqlen, dhead)
    for seed in seeds:
        for dist in distributions:
            rng = np.random.default_rng(seed)
            if dist == "normal":
                Q = rng.standard_normal(shape).astype(np.float32)
                K = rng.standard_normal(shape).astype(np.float32)
                V = rng.standard_normal(shape).astype(np.float32)
            elif dist == "uniform":
                Q = rng.uniform(-1, 1, shape).astype(np.float32)
                K = rng.uniform(-1, 1, shape).astype(np.float32)
                V = rng.uniform(-1, 1, shape).astype(np.float32)
            else:
                continue
            try:
                ref = reference(Q=Q, K=K, V=V)
                cand = candidate(Q=Q, K=K, V=V)
            except Exception as e:
                failures.append(f"seed={seed} dist={dist} raised {type(e).__name__}")
                continue
            err = float(np.max(np.abs(np.asarray(cand) - np.asarray(ref))))
            if err > tolerance:
                failures.append(f"seed={seed} dist={dist} err={err:.3e}")
    return GamingCheckResult(
        "init_robustness",
        not failures,
        f"failures: {failures}" if failures else "all (seed, dist) pairs within tolerance",
        failures,
    )


# ---- Check 5: Input Shape Generalization ----
def check_shape_generalization(
    candidate: Kernel,
    reference: Kernel,
    base_shape_hint: Mapping[str, int],
    *,
    shape_variants: tuple[Mapping[str, int], ...] | None = None,
    tolerance: float = 1e-2,
    seed: int = 99,
) -> GamingCheckResult:
    """Re-run at multiple shapes. Catches kernels that hardcode one (B, S, H, D)."""
    if shape_variants is None:
        base_seq = base_shape_hint.get("seqlen", 32)
        base_dhead = base_shape_hint.get("dhead", 16)
        shape_variants = (
            {"seqlen": base_seq // 2 or 1},
            {"seqlen": base_seq * 2},
            {"dhead": 32 if base_dhead != 32 else 48},
        )
    failures: list[str] = []
    for variant in shape_variants:
        hint = dict(base_shape_hint)
        hint.update(variant)
        batch = hint.get("batch", 1)
        heads = hint.get("heads", 4)
        seqlen = hint.get("seqlen", 32)
        dhead = hint.get("dhead", 16)
        rng = np.random.default_rng(seed)
        shape = (batch, heads, seqlen, dhead)
        Q = rng.standard_normal(shape).astype(np.float32)
        K = rng.standard_normal(shape).astype(np.float32)
        V = rng.standard_normal(shape).astype(np.float32)
        try:
            ref = reference(Q=Q, K=K, V=V)
            cand = candidate(Q=Q, K=K, V=V)
        except Exception as e:
            failures.append(f"variant={variant} raised {type(e).__name__}")
            continue
        err = float(np.max(np.abs(np.asarray(cand) - np.asarray(ref))))
        if err > tolerance:
            failures.append(f"variant={variant} err={err:.3e}")
    return GamingCheckResult(
        "shape_generalization",
        not failures,
        f"failures: {failures}" if failures else f"all {len(shape_variants)} variants ok",
        failures,
    )


# ---- Check 6: Trivial Delegation ----
_BANNED_SOURCE_TOKENS = (
    "torch.nn.functional.scaled_dot_product_attention",
    "F.scaled_dot_product_attention",
    "flashinfer.decode",
    # The candidate shouldn't be a literal wrap of the reference
    "reference_attention",
    "reference(",
)


def check_no_trivial_delegation(
    candidate: Kernel,
    *,
    banned_tokens: tuple[str, ...] = _BANNED_SOURCE_TOKENS,
) -> GamingCheckResult:
    """Static inspection: the candidate's source must not directly call the
    reference op or a library implementation of the same op. This is
    Sakana's 'LLM-judge Inefficiency' check done statically with an
    explicit allowlist-inverse — no LLM call per candidate."""
    try:
        src = inspect.getsource(candidate)
    except (OSError, TypeError):
        return GamingCheckResult(
            "no_trivial_delegation",
            True,
            "source not available; skipped",
            None,
        )
    hits = [tok for tok in banned_tokens if tok in src]
    return GamingCheckResult(
        "no_trivial_delegation",
        not hits,
        f"banned tokens in source: {hits}" if hits else "no delegation to reference op",
        hits,
    )


# ---- Convenience roll-up ----

def run_all_gaming_checks(
    candidate: Kernel,
    reference: Kernel,
    sample_output: np.ndarray,
    shape_hint: Mapping[str, int],
    *,
    tolerance: float = 1e-2,
) -> list[GamingCheckResult]:
    """Run all six Robust-KBench checks. First check to fail short-circuits."""
    return [
        check_output_range(sample_output),
        check_output_std(sample_output),
        check_per_axis_variation(sample_output),
        check_no_trivial_delegation(candidate),
        check_init_robustness(candidate, reference, shape_hint, tolerance=tolerance),
        check_shape_generalization(candidate, reference, shape_hint, tolerance=tolerance),
    ]
