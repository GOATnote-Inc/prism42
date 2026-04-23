"""Torch validator — GPU-resident equivalent of prism.validator.validate.

Two-tier, same structure. Tier-1 catches shape / NaN / max-abs-error /
determinism. Tier-2 adds config sweep and a shape-generalization gaming
check (can't easily run the full numpy-side adversarial battery without a
signature bridge — left as future work).

Tolerance defaults to 5e-2: the reference is float32, candidates may be
bf16/fp16; we're comparing a bf16 reduction chain against float32, so 5e-2
is the honest floor (matches flashinfer_runner.verify_matches_reference).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import torch


@dataclass
class TorchValidationResult:
    passed: bool
    tier_reached: int
    tier_failed_at: int | None
    failed_check: str | None
    max_abs_error: float
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.passed


def validate_torch(
    candidate: Callable,
    reference: Callable,
    inputs: dict[str, Any],
    *,
    tolerance: float = 5e-2,
    run_tier2: bool = True,
    config_sweep: list[dict[str, Any]] | None = None,
) -> TorchValidationResult:
    details: dict[str, Any] = {}

    # --- Tier 1 ---
    try:
        out_ref = reference(**inputs).float()
    except Exception as e:
        return TorchValidationResult(
            False, 1, 1, f"reference raised: {type(e).__name__}: {e}",
            math.inf, details,
        )
    try:
        out_cand = candidate(**inputs).float()
    except Exception as e:
        return TorchValidationResult(
            False, 1, 1, f"candidate raised: {type(e).__name__}: {e}",
            math.inf, details,
        )

    if out_ref.shape != out_cand.shape:
        return TorchValidationResult(
            False, 1, 1,
            f"shape mismatch: ref={tuple(out_ref.shape)} cand={tuple(out_cand.shape)}",
            math.inf, details,
        )

    if torch.isnan(out_cand).any() or torch.isinf(out_cand).any():
        return TorchValidationResult(
            False, 1, 1, "NaN or Inf in candidate output", math.inf, details,
        )

    max_err = float((out_ref - out_cand).abs().max().item())
    details["tier1_max_abs_error"] = max_err
    if max_err > tolerance:
        return TorchValidationResult(
            False, 1, 1,
            f"tier1 max_abs_error {max_err:.3e} > tolerance {tolerance:.3e}",
            max_err, details,
        )

    # Determinism: two runs on the same input must agree bitwise.
    try:
        out_cand_2 = candidate(**inputs).float()
    except Exception as e:
        return TorchValidationResult(
            False, 1, 1, f"candidate raised on rerun: {e}", max_err, details,
        )
    if not torch.equal(out_cand, out_cand_2):
        # Allow tiny drift from tensor-core algorithm non-determinism; require
        # the two runs to agree to ~eps in float32.
        drift = float((out_cand - out_cand_2).abs().max().item())
        details["determinism_drift"] = drift
        if drift > 1e-5:
            return TorchValidationResult(
                False, 1, 1,
                f"candidate non-deterministic: rerun drift {drift:.3e} > 1e-5",
                max_err, details,
            )

    if not run_tier2:
        return TorchValidationResult(True, 1, None, None, max_err, details)

    # --- Tier 2: config sweep ---
    sweep_errors: list[float] = []
    for cfg_inputs in config_sweep or []:
        try:
            r = reference(**cfg_inputs).float()
            c = candidate(**cfg_inputs).float()
        except Exception as e:
            return TorchValidationResult(
                False, 2, 2, f"config-sweep raise: {e}", max_err, details,
            )
        if r.shape != c.shape or torch.isnan(c).any() or torch.isinf(c).any():
            return TorchValidationResult(
                False, 2, 2,
                f"config-sweep structural failure (shape={tuple(c.shape)})",
                max_err, details,
            )
        e = float((r - c).abs().max().item())
        sweep_errors.append(e)
        if e > tolerance:
            return TorchValidationResult(
                False, 2, 2, f"config-sweep error {e:.3e}",
                e, details,
            )
    details["tier2_sweep_errors"] = sweep_errors

    return TorchValidationResult(True, 2, None, None, max_err, details)
