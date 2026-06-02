"""Physics invariants for attention / MLA kernels.

Each invariant is a cheap check that a correct kernel must satisfy. They catch
numerics bugs that a single max-abs-error threshold misses. Source:
`mental-models/einstein-first-principles.md` §7.

An InvariantCheck has a name and a `run(out_cand, out_ref, inputs) -> dict`
returning `{"passed": bool, "reason": str, "value": Any}`. The validator
short-circuits on the first failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np


@dataclass(frozen=True)
class InvariantCheck:
    name: str
    fn: Callable[[np.ndarray, np.ndarray, Mapping[str, Any]], dict]

    def run(self, out_cand: np.ndarray, out_ref: np.ndarray, inputs: Mapping[str, Any]) -> dict:
        try:
            result = self.fn(out_cand, out_ref, inputs)
        except Exception as e:
            return {"passed": False, "reason": f"invariant raised {type(e).__name__}: {e}", "value": None}
        # Sanity on the result shape.
        return {
            "passed": bool(result.get("passed", False)),
            "reason": str(result.get("reason", "")),
            "value": result.get("value"),
        }


# --- canonical invariants ---

def _softmax_rows_sum_to_one(
    out_cand: np.ndarray,
    out_ref: np.ndarray,
    inputs: Mapping[str, Any],
    *,
    axis: int = -1,
    tol: float = 1e-4,
) -> dict:
    """If the candidate exposes attention weights as `attn_weights`, each row
    along the last axis should sum to 1. Skipped when no weights are exposed."""
    weights = inputs.get("_attn_weights_from_candidate")
    if weights is None:
        return {"passed": True, "reason": "no attention weights exposed; skipped", "value": None}
    w = np.asarray(weights, dtype=np.float64)
    sums = w.sum(axis=axis)
    max_dev = float(np.max(np.abs(sums - 1.0)))
    return {
        "passed": max_dev <= tol,
        "reason": f"max |row_sum - 1| = {max_dev:.3e}, tol={tol:.3e}",
        "value": max_dev,
    }


def _output_row_norms_bounded(
    out_cand: np.ndarray,
    out_ref: np.ndarray,
    inputs: Mapping[str, Any],
    *,
    tol_factor: float = 1.01,
) -> dict:
    """For attention output `O = softmax(QK^T) @ V`, each row of O is a convex
    combination of rows of V. ||O_i|| must be <= max_j ||V_j|| * tol_factor."""
    V = inputs.get("V")
    if V is None:
        return {"passed": True, "reason": "no V in inputs; skipped", "value": None}
    V_arr = np.asarray(V, dtype=np.float64)
    out_arr = out_cand.astype(np.float64)
    # row norms over the last axis of V; flatten across batch/heads for the bound.
    v_flat = V_arr.reshape(-1, V_arr.shape[-1])
    o_flat = out_arr.reshape(-1, out_arr.shape[-1])
    v_max = float(np.max(np.linalg.norm(v_flat, axis=-1)))
    o_max = float(np.max(np.linalg.norm(o_flat, axis=-1)))
    bound = v_max * tol_factor
    return {
        "passed": o_max <= bound,
        "reason": f"max ||O_i|| = {o_max:.3e}, bound = {bound:.3e}",
        "value": {"o_max": o_max, "bound": bound},
    }


def _no_extreme_values(
    out_cand: np.ndarray,
    out_ref: np.ndarray,
    inputs: Mapping[str, Any],
    *,
    max_abs: float = 1e4,
) -> dict:
    """Outputs in a well-scaled attention kernel should not have extreme
    magnitudes. Catches scale-decode bugs on FP4 paths."""
    m = float(np.max(np.abs(out_cand)))
    return {
        "passed": m <= max_abs,
        "reason": f"max |output| = {m:.3e}, cap = {max_abs:.3e}",
        "value": m,
    }


def _topk_agreement(
    out_cand: np.ndarray,
    out_ref: np.ndarray,
    inputs: Mapping[str, Any],
    *,
    k: int = 16,
    min_overlap: float = 0.9,
) -> dict:
    """For attention weights or logits, the top-k indices should agree between
    candidate and reference. Only runs if the last axis is >= k."""
    if out_cand.shape[-1] < k:
        return {"passed": True, "reason": f"last dim {out_cand.shape[-1]} < k={k}; skipped", "value": None}
    # Flatten all leading dims.
    c = out_cand.reshape(-1, out_cand.shape[-1])
    r = out_ref.reshape(-1, out_ref.shape[-1])
    top_c = np.argpartition(c, -k, axis=-1)[:, -k:]
    top_r = np.argpartition(r, -k, axis=-1)[:, -k:]
    # Per-row overlap ratio.
    overlaps = []
    for cr, rr in zip(top_c, top_r):
        overlap = len(np.intersect1d(cr, rr)) / k
        overlaps.append(overlap)
    mean_overlap = float(np.mean(overlaps))
    return {
        "passed": mean_overlap >= min_overlap,
        "reason": f"mean top-{k} overlap = {mean_overlap:.3f}, min = {min_overlap:.3f}",
        "value": mean_overlap,
    }


SOFTMAX_ROWS_SUM_TO_ONE = InvariantCheck("softmax_rows_sum_to_one", _softmax_rows_sum_to_one)
OUTPUT_ROW_NORMS_BOUNDED = InvariantCheck("output_row_norms_bounded", _output_row_norms_bounded)
NO_EXTREME_VALUES = InvariantCheck("no_extreme_values", _no_extreme_values)
TOPK_AGREEMENT = InvariantCheck("topk_agreement", _topk_agreement)


DEFAULT_INVARIANTS = [
    NO_EXTREME_VALUES,
    OUTPUT_ROW_NORMS_BOUNDED,
    TOPK_AGREEMENT,
    SOFTMAX_ROWS_SUM_TO_ONE,
]
