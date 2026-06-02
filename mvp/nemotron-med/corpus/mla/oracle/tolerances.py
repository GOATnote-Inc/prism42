"""Oracle tolerance presets per candidate dtype.

Phase M (MLA decode oracle). See docs/mla-oracle-roadmap.md §3 M3.

The reference MLA decode (corpus/mla/reference/mla_decode_numpy.py) is
FP32. Candidate kernels run at reduced precision (bf16, fp8, nvfp4, ...).
The oracle compares candidate output against the FP32 reference — the
comparison tolerance must therefore reflect the candidate's precision
floor, not the reference's.

Preset bounds below are conservative upper bounds. A well-designed kernel
typically beats these by 2-10x; a broken kernel clears them by orders of
magnitude. The presets are tuned so:

    - PASS on a correctly-implemented kernel at the stated precision.
    - FAIL on the three live public bugs the paper targets (SGLang #10284,
      vLLM #38439, FlashInfer #3047 — all involve observable divergence
      well beyond the bf16/fp8/fp4 precision floor on specific inputs).

Sources for precision floors:

    - FP16 / BF16: IEEE 754-style but with reduced mantissa. FP16 has
      10-bit mantissa (~1e-3 rel ULP); BF16 has 7-bit mantissa (~8e-3 rel
      ULP). See Kalamkar et al., "A Study of BFLOAT16 for Deep Learning
      Training" (arXiv:1905.12322).

    - FP8 (e4m3 / e5m2): NVIDIA + Intel + Arm joint format spec, Sun et
      al. "FP8 Formats for Deep Learning" (arXiv:2209.05433). e4m3 has
      3-bit mantissa (~1e-1 rel ULP for small values, sat. at ±448).
      e5m2 has 2-bit mantissa (~2e-1 rel ULP, range ±57344).

    - NVFP4 / MXFP4: 4-bit element with shared microscaling factor
      (1 scale per 16 elements for MX, or 32 for NVFP4). Reference:
      NVIDIA "Introducing NVFP4 for Efficient and Accurate Low-Precision
      Inference" (developer.nvidia.com, 2025-05). Effective rel ULP
      ~3e-1 for well-scaled blocks, degrades on outliers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class OracleTolerance:
    """Per-dtype tolerance bounds for the MLA decode oracle.

    A candidate output PASSES if all of:
        - no NaN or Inf values (unless explicitly allowed)
        - max_abs_diff <= max_abs_diff
        - max_rel_diff <= max_rel_diff
        - cosine similarity >= min_cos_sim

    A candidate output FAILS on the first violated bound.
    """

    name: str
    max_abs_diff: float
    max_rel_diff: float
    min_cos_sim: float
    allow_nan: bool = False
    allow_inf: bool = False


# Tolerance presets. Keyed by candidate dtype string (lowercase).
#
# Rationale column (per bound):
#   max_rel_diff: set to ~3x the dtype's nominal relative ULP — allows
#                 accumulated round-off across a full decode without
#                 flagging a correct kernel.
#   min_cos_sim:  much stricter than max_rel_diff; catches cases where
#                 output diverges in direction even if magnitudes are
#                 close. This is what the three target bugs violate.
TOLERANCES: Dict[str, OracleTolerance] = {
    "fp32": OracleTolerance(
        name="fp32",
        max_abs_diff=1e-4,
        max_rel_diff=1e-5,
        min_cos_sim=0.99999,
    ),
    "fp16": OracleTolerance(
        name="fp16",
        max_abs_diff=1e-2,
        max_rel_diff=5e-3,
        min_cos_sim=0.9999,
    ),
    "bf16": OracleTolerance(
        name="bf16",
        max_abs_diff=5e-2,
        max_rel_diff=2e-2,
        min_cos_sim=0.999,
    ),
    "fp8_e4m3": OracleTolerance(
        name="fp8_e4m3",
        max_abs_diff=2e-1,
        max_rel_diff=1e-1,
        min_cos_sim=0.99,
    ),
    "fp8_e5m2": OracleTolerance(
        name="fp8_e5m2",
        max_abs_diff=3e-1,
        max_rel_diff=2e-1,
        min_cos_sim=0.98,
    ),
    "nvfp4": OracleTolerance(
        name="nvfp4",
        max_abs_diff=5e-1,
        max_rel_diff=3e-1,
        min_cos_sim=0.97,
    ),
    "mxfp4": OracleTolerance(
        name="mxfp4",
        max_abs_diff=5e-1,
        max_rel_diff=3e-1,
        min_cos_sim=0.97,
    ),
}


def get_tolerance(dtype: str) -> OracleTolerance:
    """Look up a preset tolerance by dtype name. Raises KeyError if unknown."""
    key = dtype.lower().replace("-", "_")
    if key not in TOLERANCES:
        raise KeyError(
            f"unknown dtype {dtype!r}; known: {sorted(TOLERANCES)}"
        )
    return TOLERANCES[key]
