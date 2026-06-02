#!/usr/bin/env python3
# golden-case PoC -- kernel call is mocked; shape and exit semantics are what's under test.
#
# Demonstrates ATK-001 driving INV-002 (precision class) in a mocked
# fp8 online-softmax accumulator. The mock is arithmetically faithful
# to the *failure mode* (subnormal flush of the rescale factor zeroing
# out l_prev) without invoking any real CUDA kernel. Exits nonzero when
# the precision invariant is violated; prints a PRISM_VERDICT line to
# stdout and a human-readable diagnostic to stderr that names the
# invariant id and its class.
"""
PoC for KERNEL-GOLDEN.

Attack:     ATK-001 (subnormal-heavy fp8 K/V tiles)
Invariant:  INV-002 (precision -- fp8 rescale underflow)
            INV-003 (numerical -- zero-denominator downstream)
Rail:       cuda (mocked here; the real reproducer runs on an H100 SXM)

Exit semantics:
    0 -> invariant held (attack failed; golden fixture would be BROKEN)
    1 -> invariant violated (attack succeeded; this is the expected path)
    2 -> tooling / shape error
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

CASE_ID = "KERNEL-GOLDEN"
ATTACK_ID = "ATK-001"
INVARIANT_ID = "INV-002"
INVARIANT_CLASS = "precision"

# E4M3 subnormal boundary: smallest normal is 2^-6 in the 1.M * 2^(E-7) convention
# used by the most common fp8 variant; values below ~2^-9 flush-to-zero under the
# hardware's default rounding in the rescale path we are modelling.
E4M3_SUBNORMAL_THRESHOLD = 2.0 ** -9  # ~1.953e-3


@dataclass
class TileResult:
    m: float  # running row-max
    l: float  # running denominator
    o: float  # running (unnormalized) output (scalar stand-in for a row vector)


def _fp8_rescale_mock(x: float) -> float:
    """Mock fp8 E4M3 rescale: values below the subnormal threshold flush to zero.

    This is the precise failure mode INV-002 describes: exp(m_prev - m_new) is
    computed in a low-precision intermediate and, when small enough, is rounded
    to zero before it multiplies l_prev. The real kernel does this in a fused
    MMA epilogue; we model it with a threshold.
    """
    if abs(x) < E4M3_SUBNORMAL_THRESHOLD:
        return 0.0
    return x


def online_softmax_tile_sweep_MOCKED(
    tile_row_maxes: list[float],
    tile_row_sums: list[float],
    tile_outputs: list[float],
) -> TileResult:
    """Mocked online-softmax over a fixed sequence of tiles.

    Returns the final (m, l, o). We deliberately apply the fp8 rescale mock to
    the cross-tile correction factor only -- which is where the real kernel
    under audit loses precision.
    """
    m = -math.inf
    l = 0.0
    o = 0.0
    for m_tile, sum_tile, o_tile in zip(tile_row_maxes, tile_row_sums, tile_outputs):
        m_new = max(m, m_tile)
        # Correction factor applied to the prior tile's accumulators.
        if m == -math.inf:
            corr = 0.0  # first tile: nothing to correct
        else:
            corr_true = math.exp(m - m_new)
            corr = _fp8_rescale_mock(corr_true)  # <-- the bug site
        l = l * corr + sum_tile * math.exp(m_tile - m_new)
        o = o * corr + o_tile * math.exp(m_tile - m_new)
        m = m_new
    return TileResult(m=m, l=l, o=o)


def reference_softmax(
    tile_row_maxes: list[float],
    tile_row_sums: list[float],
    tile_outputs: list[float],
) -> TileResult:
    """Fp32 reference: same recurrence, no subnormal flush."""
    m = -math.inf
    l = 0.0
    o = 0.0
    for m_tile, sum_tile, o_tile in zip(tile_row_maxes, tile_row_sums, tile_outputs):
        m_new = max(m, m_tile)
        corr = 0.0 if m == -math.inf else math.exp(m - m_new)
        l = l * corr + sum_tile * math.exp(m_tile - m_new)
        o = o * corr + o_tile * math.exp(m_tile - m_new)
        m = m_new
    return TileResult(m=m, l=l, o=o)


def main() -> int:
    # ATK-001 scenario: row-maxes rise by 9.0 between adjacent tiles so
    # exp(-9) ~ 1.23e-4 << E4M3 subnormal threshold (2^-9 ~ 1.95e-3) and
    # the cross-tile correction factor flushes to zero. Early tiles carry
    # substantial probability mass (large row sums); later tiles carry
    # much less. Under the reference the early mass, attenuated by the
    # correction, still contributes a non-trivial 1e-4 share of l. Under
    # the buggy rescale the early mass is discarded outright, so l_final
    # collapses to the last tile's unscaled sum and diverges from the
    # reference by more than 50% whenever the discarded mass dominates.
    tile_row_maxes = [0.0, 9.0, 18.0]
    tile_row_sums = [1.0e4, 1.0e4, 1.0]
    tile_outputs = [0.5, 0.5, 0.5]

    buggy = online_softmax_tile_sweep_MOCKED(tile_row_maxes, tile_row_sums, tile_outputs)
    ref = reference_softmax(tile_row_maxes, tile_row_sums, tile_outputs)

    # INV-002 is violated iff the buggy denominator lost prior-tile mass, i.e.
    # diverged from the fp32 reference by more than a modest tolerance.
    rel_err = abs(buggy.l - ref.l) / max(ref.l, 1e-30)

    print(
        f"PRISM_VERDICT case_id={CASE_ID} attack_id={ATTACK_ID} "
        f"invariant_id={INVARIANT_ID} ref_l={ref.l:.6e} buggy_l={buggy.l:.6e} "
        f"rel_err={rel_err:.3f}"
    )

    if rel_err > 0.5:
        sys.stderr.write(
            f"VIOLATION invariant_id={INVARIANT_ID} class={INVARIANT_CLASS} "
            f"attack_id={ATTACK_ID} case_id={CASE_ID}: "
            f"fp8 rescale underflow dropped prior-tile probability mass "
            f"(ref l={ref.l:.4e}, buggy l={buggy.l:.4e}, rel_err={rel_err:.3f}); "
            f"attack_succeeded\n"
        )
        return 1

    sys.stderr.write(
        f"INVARIANT_HELD invariant_id={INVARIANT_ID} class={INVARIANT_CLASS}: "
        f"rel_err={rel_err:.3f} within tolerance; attack_failed\n"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- tooling/shape failures return 2
        sys.stderr.write(f"POC_TOOLING_ERROR case_id={CASE_ID}: {exc!r}\n")
        sys.exit(2)
