"""Two-tier numerical validator for evolutionary MLA kernel search.

Tier 1 is cheap: shape, dtype, NaN/Inf, single-input max-error, determinism.
Tier 2 is expensive: physics invariants, distribution agreement, config sweep,
adversarial input battery. Only runs when Tier 1 passes.

Cross-refs:
    mental-models/munger-inversion.md §1 (validator wrong)
    mental-models/einstein-first-principles.md §7 (physics invariants)
    mental-models/red-team-adversarial.md §3 (numerics-as-weapon)

The validator is intentionally framework-agnostic: candidate_kernel and
reference_kernel are callables returning numpy ndarrays (or anything with
.shape, .dtype, and __array__). Pass torch tensors through .detach().cpu()
.numpy() before calling if you want a GPU harness; the runner layer owns that.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np

Kernel = Callable[..., np.ndarray]
Inputs = Mapping[str, Any]


@dataclass
class ValidationResult:
    passed: bool
    tier_reached: int
    tier_failed_at: int | None
    failed_check: str | None
    max_abs_error: float
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.passed


def _as_array(x: Any) -> np.ndarray:
    if isinstance(x, np.ndarray):
        return x
    return np.asarray(x)


def _has_nan_or_inf(arr: np.ndarray) -> bool:
    return bool(np.isnan(arr).any() or np.isinf(arr).any())


def _max_abs_error(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64))))


def _bit_equal(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and a.dtype == b.dtype and np.array_equal(a, b)


def validate(
    candidate: Kernel,
    reference: Kernel,
    inputs: Inputs,
    *,
    tolerance: float = 1e-2,
    run_tier2: bool = True,
    config_sweep: list[Inputs] | None = None,
    adversarial_inputs: list[Inputs] | None = None,
    invariants: "list[InvariantCheck] | None" = None,
    anti_gaming: bool = False,
    shape_hint: dict[str, int] | None = None,
) -> ValidationResult:
    """Validate candidate against reference.

    Args:
        candidate: the kernel under test.
        reference: the golden reference kernel.
        inputs: keyword-argument mapping passed to both kernels.
        tolerance: Tier-1 max-abs-error threshold.
        run_tier2: if False, stop after Tier 1.
        config_sweep: optional list of additional input configs for Tier 2.
        adversarial_inputs: optional list of crafted inputs for Tier 2.
        invariants: optional list of physics checks for Tier 2.

    Returns:
        ValidationResult; truthiness is pass/fail.
    """
    details: dict[str, Any] = {}

    # ---- Tier 1 ----
    try:
        out_ref = _as_array(reference(**inputs))
        out_cand = _as_array(candidate(**inputs))
    except Exception as e:
        return ValidationResult(
            passed=False,
            tier_reached=1,
            tier_failed_at=1,
            failed_check=f"kernel raised: {type(e).__name__}: {e}",
            max_abs_error=math.inf,
            details=details,
        )

    if out_ref.shape != out_cand.shape:
        return ValidationResult(
            False, 1, 1,
            f"shape mismatch: ref={out_ref.shape} cand={out_cand.shape}",
            math.inf, details,
        )

    if out_ref.dtype.kind != out_cand.dtype.kind:
        # allow width differences inside the same kind (e.g., float16 vs float32)
        return ValidationResult(
            False, 1, 1,
            f"dtype kind mismatch: ref={out_ref.dtype} cand={out_cand.dtype}",
            math.inf, details,
        )

    if _has_nan_or_inf(out_cand):
        return ValidationResult(
            False, 1, 1, "NaN or Inf in candidate output", math.inf, details,
        )

    max_err = _max_abs_error(out_cand, out_ref)
    details["tier1_max_abs_error"] = max_err
    if max_err > tolerance:
        return ValidationResult(
            False, 1, 1,
            f"tier1 max_abs_error {max_err:.3e} > tolerance {tolerance:.3e}",
            max_err, details,
        )

    # Determinism: two runs of the candidate on the same input must agree bit-for-bit.
    out_cand_2 = _as_array(candidate(**inputs))
    if not _bit_equal(out_cand, out_cand_2):
        return ValidationResult(
            False, 1, 1,
            "candidate non-deterministic: two runs produced different outputs",
            max_err, details,
        )

    if not run_tier2:
        return ValidationResult(True, 1, None, None, max_err, details)

    # ---- Tier 2 ----
    # 2z (before invariants): Robust-KBench gaming-pattern checks.
    if anti_gaming:
        # Late import to avoid circular import; invariants module doesn't need it.
        from prism import gaming_patterns as _gp
        hint = shape_hint or {}
        checks = _gp.run_all_gaming_checks(
            candidate=candidate,
            reference=reference,
            sample_output=out_cand,
            shape_hint=hint,
            tolerance=tolerance,
        )
        details["tier2_gaming_checks"] = [
            {"check": c.check, "passed": c.passed, "reason": c.reason}
            for c in checks
        ]
        for c in checks:
            if not c.passed:
                return ValidationResult(
                    False, 2, 2,
                    f"gaming check {c.check!r} failed: {c.reason}",
                    max_err, details,
                )

    # 2a. Physics invariants on the reference *and* the candidate.
    for check in invariants or []:
        inv_result = check.run(out_cand, out_ref, inputs)
        details.setdefault("tier2_invariants", []).append(inv_result)
        if not inv_result["passed"]:
            return ValidationResult(
                False, 2, 2,
                f"invariant {check.name!r} failed: {inv_result['reason']}",
                max_err, details,
            )

    # 2b. Config sweep: same kernel on different (batch, seqlen, heads, ...).
    sweep_errors: list[float] = []
    for cfg in config_sweep or []:
        try:
            r = _as_array(reference(**cfg))
            c = _as_array(candidate(**cfg))
        except Exception as e:
            return ValidationResult(
                False, 2, 2,
                f"config-sweep raise: {type(e).__name__}: {e}",
                max_err, details,
            )
        if r.shape != c.shape or _has_nan_or_inf(c):
            return ValidationResult(
                False, 2, 2,
                f"config-sweep structural failure at cfg={cfg!r}",
                max_err, details,
            )
        cfg_err = _max_abs_error(c, r)
        sweep_errors.append(cfg_err)
        if cfg_err > tolerance:
            return ValidationResult(
                False, 2, 2,
                f"config-sweep error {cfg_err:.3e} at cfg={cfg!r}",
                cfg_err, details,
            )
    details["tier2_sweep_errors"] = sweep_errors

    # 2c. Adversarial inputs: should not NaN, Inf, or diverge.
    adv_errors: list[float] = []
    for adv in adversarial_inputs or []:
        try:
            r = _as_array(reference(**adv))
            c = _as_array(candidate(**adv))
        except Exception as e:
            return ValidationResult(
                False, 2, 2,
                f"adversarial raise: {type(e).__name__}: {e}",
                max_err, details,
            )
        if _has_nan_or_inf(c):
            return ValidationResult(
                False, 2, 2,
                f"adversarial produced NaN/Inf at input keys={list(adv.keys())}",
                math.inf, details,
            )
        adv_err = _max_abs_error(c, r)
        adv_errors.append(adv_err)
        # Adversarial tolerance is 10x Tier-1 — these inputs are deliberately hostile.
        if adv_err > 10 * tolerance:
            return ValidationResult(
                False, 2, 2,
                f"adversarial error {adv_err:.3e} > 10x tolerance",
                adv_err, details,
            )
    details["tier2_adversarial_errors"] = adv_errors

    return ValidationResult(True, 2, None, None, max_err, details)
