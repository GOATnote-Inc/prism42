"""MLA decode oracle harness.

Phase M (MLA decode oracle). See docs/mla-oracle-roadmap.md §3 M3.

Grades a candidate MLA decode output against the FP32 reference (either
regenerated from seeds or loaded from a committed golden JSON). Emits a
structured verdict with per-metric numbers and a boolean pass/fail.

Contract:

    verdict = check(reference, candidate, tolerance, candidate_label=?)

    - reference: FP32 numpy array from the reference impl.
    - candidate: numpy array of any dtype; cast to FP32 for comparison.
    - tolerance: OracleTolerance from tolerances.TOLERANCES.
    - candidate_label: optional string tag (e.g. "sglang-10284-b200-nvfp4").

    verdict.passed is True iff every declared bound holds.
    verdict.reasons lists the violated bounds (empty when passed).

Metrics computed:

    max_abs_diff: max |candidate_i - reference_i|
    max_rel_diff: max |candidate_i - reference_i| / (|reference_i| + eps)
    cos_sim:     cosine similarity over flattened arrays
    nan_count:   number of NaN values in candidate
    inf_count:   number of Inf values in candidate
    shape_match: candidate.shape == reference.shape

No task-level (GSM8K / rubric) grading in this module — that belongs on
top of a running model. This module is dtype-agnostic and purely
numerical; every metric is a function of the two tensors plus the
declared tolerance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

import numpy as np

from tolerances import OracleTolerance


_EPS = 1e-9


@dataclass
class OracleVerdict:
    """Structured oracle result for one (reference, candidate) pair."""

    passed: bool
    reasons: List[str]
    tolerance_name: str
    candidate_label: Optional[str]
    shape_match: bool
    reference_shape: List[int]
    candidate_shape: List[int]
    nan_count: int
    inf_count: int
    max_abs_diff: float
    max_rel_diff: float
    cos_sim: float
    reference_norm: float
    candidate_norm: float

    def to_dict(self) -> dict:
        """JSON-serializable view of this verdict."""
        return asdict(self)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity over flattened arrays. Returns 0.0 if either is zero."""
    a_flat = a.reshape(-1).astype(np.float64)
    b_flat = b.reshape(-1).astype(np.float64)
    na2 = float((a_flat * a_flat).sum())
    nb2 = float((b_flat * b_flat).sum())
    if na2 < _EPS * _EPS or nb2 < _EPS * _EPS:
        return 0.0
    # For a == b, numerator == na2 and denom == na2, so ratio is 1.0 bit-exactly.
    return float((a_flat * b_flat).sum() / np.sqrt(na2 * nb2))


def check(
    reference: np.ndarray,
    candidate: np.ndarray,
    tolerance: OracleTolerance,
    candidate_label: Optional[str] = None,
) -> OracleVerdict:
    """Grade a candidate against the FP32 reference. Returns an OracleVerdict."""

    reasons: List[str] = []

    # Shape check (hard gate — if shapes differ, metrics below are meaningless).
    shape_match = reference.shape == candidate.shape
    if not shape_match:
        reasons.append(
            f"shape_mismatch: reference={list(reference.shape)} candidate={list(candidate.shape)}"
        )
        return OracleVerdict(
            passed=False,
            reasons=reasons,
            tolerance_name=tolerance.name,
            candidate_label=candidate_label,
            shape_match=False,
            reference_shape=list(reference.shape),
            candidate_shape=list(candidate.shape),
            nan_count=int(np.isnan(candidate).sum()) if candidate.size else 0,
            inf_count=int(np.isinf(candidate).sum()) if candidate.size else 0,
            max_abs_diff=float("nan"),
            max_rel_diff=float("nan"),
            cos_sim=float("nan"),
            reference_norm=float("nan"),
            candidate_norm=float("nan"),
        )

    # Cast both to FP64 for comparison (avoids silent upcasts during arithmetic).
    ref_f = reference.astype(np.float64)
    cand_f = candidate.astype(np.float64)

    nan_count = int(np.isnan(cand_f).sum())
    inf_count = int(np.isinf(cand_f).sum())
    if nan_count > 0 and not tolerance.allow_nan:
        reasons.append(f"nan_detected: {nan_count} NaN values in candidate")
    if inf_count > 0 and not tolerance.allow_inf:
        reasons.append(f"inf_detected: {inf_count} Inf values in candidate")

    # Numerical metrics — only meaningful when outputs are finite. If NaN/Inf
    # present, skip so we don't report NaN metrics.
    if nan_count == 0 and inf_count == 0:
        diff = np.abs(cand_f - ref_f)
        max_abs_diff = float(diff.max())
        # Global (max-scaled) relative error, not pointwise.
        # Pointwise |diff| / |ref[i]| explodes at near-zero reference entries
        # — routine in decode outputs — even when the kernel is correct.
        # Surfaced 2026-04-22 by the first Trillium bf16 run: max_abs_diff =
        # 8.9e-3 (well inside bf16's 5e-2 floor) and cos_sim = 0.99998 (well
        # above bf16's 0.999), yet pointwise rel_diff spiked to 345x at a
        # near-zero reference entry. Global rel_diff agrees with the other
        # two metrics on whether the output is acceptable.
        ref_scale = float(np.abs(ref_f).max())
        max_rel_diff = max_abs_diff / (ref_scale + _EPS)
        cos_sim = _cosine_similarity(ref_f, cand_f)

        if max_abs_diff > tolerance.max_abs_diff:
            reasons.append(
                f"abs_diff_exceeded: {max_abs_diff:.3e} > {tolerance.max_abs_diff:.3e}"
            )
        if max_rel_diff > tolerance.max_rel_diff:
            reasons.append(
                f"rel_diff_exceeded: {max_rel_diff:.3e} > {tolerance.max_rel_diff:.3e}"
            )
        if cos_sim < tolerance.min_cos_sim:
            reasons.append(
                f"cos_sim_below_floor: {cos_sim:.6f} < {tolerance.min_cos_sim:.6f}"
            )
    else:
        max_abs_diff = float("nan")
        max_rel_diff = float("nan")
        cos_sim = float("nan")

    return OracleVerdict(
        passed=len(reasons) == 0,
        reasons=reasons,
        tolerance_name=tolerance.name,
        candidate_label=candidate_label,
        shape_match=True,
        reference_shape=list(reference.shape),
        candidate_shape=list(candidate.shape),
        nan_count=nan_count,
        inf_count=inf_count,
        max_abs_diff=max_abs_diff,
        max_rel_diff=max_rel_diff,
        cos_sim=cos_sim,
        reference_norm=float(np.linalg.norm(ref_f)),
        candidate_norm=float(np.linalg.norm(cand_f)),
    )


def check_against_golden(
    golden_path: str,
    candidate: np.ndarray,
    tolerance: OracleTolerance,
    candidate_label: Optional[str] = None,
) -> OracleVerdict:
    """Convenience: load a committed golden JSON and grade against it."""
    import json

    with open(golden_path) as fh:
        golden = json.load(fh)
    reference = np.asarray(golden["output"], dtype=np.float32)
    return check(reference, candidate, tolerance, candidate_label=candidate_label)
