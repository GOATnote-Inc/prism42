"""H5.1 — bf16 accumulator fails validator at T=4096 (CPU simulation test).

Prediction from the numerical-stability literature on bf16 accumulators:
  - bf16 ULP at 1.0 ≈ 7.8e-3
  - Direct bf16 accumulation of T terms drifts as O(T * ULP)
  - Validator's 5e-2 bf16 tolerance is exceeded when T >= ~6/ULP ≈ 768,
    with a safety margin crossed well before T=4096
  - Fp32 accumulation holds O(sqrt(T) * ULP); at T=4096 that is ≈ 5e-4,
    comfortably inside tolerance

This test pins that behavior with a matched pair of assertions. If all pass,
H5.1 is SUPPORTED. If any fails, the verdict inverts and the math-§9 drift
model needs revision.

The "bf16" is simulated by truncating fp32 mantissa to 7 bits via bit mask
(`bits & 0xFFFF0000`). This approximates bf16 precision loss without
requiring torch on the test host; numpy-only, runs in ~1 s on CPU.

Runnable on any platform:
    .venv/bin/python -m pytest mla/tests/test_numerical_stability.py -v
"""
from __future__ import annotations

import numpy as np
import pytest

VALIDATOR_BF16_TOLERANCE = 5e-2


def _bf16_round(x_fp32: np.ndarray) -> np.ndarray:
    """Simulate bf16 precision by truncating fp32 mantissa to 7 bits.

    Not exact bf16 RNE — this is round-toward-zero — but the TAIL behavior
    (reduction drift at large T) is dominated by the precision loss, not the
    rounding mode. For H5.1 (drift exceeds tolerance at T=4096), truncation
    is a lower bound on the error; a real bf16 RNE would show similar or
    larger tail drift.
    """
    if x_fp32.dtype != np.float32:
        x_fp32 = x_fp32.astype(np.float32)
    bits = x_fp32.view(np.uint32).copy()
    bits_truncated = bits & np.uint32(0xFFFF0000)
    return bits_truncated.view(np.float32)


def _softmax_fp64_reference(scores: np.ndarray) -> np.ndarray:
    """Stable softmax in fp64 accumulator — the reference path.

    fp64 drift on T <= 16K is O(1e-15), indistinguishable from exact at
    our tolerance.
    """
    s = scores.astype(np.float64)
    s = s - s.max(axis=-1, keepdims=True)
    e = np.exp(s)
    return (e / e.sum(axis=-1, keepdims=True)).astype(np.float32)


def _softmax_bf16_accum(scores: np.ndarray) -> np.ndarray:
    """Softmax with every intermediate rounded to bf16 precision."""
    s = _bf16_round(scores.astype(np.float32))
    m = _bf16_round(s.max(axis=-1, keepdims=True))
    s = _bf16_round(s - m)
    e = _bf16_round(np.exp(s.astype(np.float32)))
    denom = _bf16_round(e.sum(axis=-1, keepdims=True))
    return _bf16_round(e / denom)


def _mla_output(scores: np.ndarray, V: np.ndarray, *, bf16_accum: bool) -> np.ndarray:
    """Weighted sum V @ softmax(scores). If bf16_accum, both softmax and V
    are truncated to bf16; reduction output is also bf16-rounded."""
    if bf16_accum:
        w = _softmax_bf16_accum(scores)
        V_q = _bf16_round(V)
        out = np.einsum("bht,btd->bhd", w, V_q).astype(np.float32)
        return _bf16_round(out)
    w = _softmax_fp64_reference(scores)
    return np.einsum("bht,btd->bhd", w, V.astype(np.float64)).astype(np.float32)


def _random_mla_inputs(T: int, seed: int = 0, B: int = 1, H: int = 128, D: int = 512):
    rng = np.random.default_rng(seed)
    scores = rng.standard_normal((B, H, T)).astype(np.float32) * 0.5
    V = rng.standard_normal((B, T, D)).astype(np.float32) * 0.05
    return scores, V


# ---- H5.1 verdict: FALSIFIED 2026-04-23 ----
# Original prediction: bf16 accumulator drift > 5e-2 tolerance at T >= 4096 per
# math §9's O(T*ULP) model. Observed at T=4096: drift ~3e-5, well within
# tolerance. Mechanism: softmax normalization makes each weight O(1/T), so the
# weighted sum has error that grows as ~O(sqrt(T)*ULP) or less for uniform
# attention distributions — NOT O(T*ULP). The `xfail` tests below preserve
# the original prediction for lineage; the `test_bf16_accum_learned_behavior_*`
# tests pin the actual observed behavior as regression guards.


@pytest.mark.xfail(
    reason=(
        "H5.1 falsified 2026-04-23: math §9 O(T*ULP) model overestimated drift. "
        "Observed drift at T=4096 is ~3e-5 (3 orders below 5e-2 tolerance). "
        "Uniform softmax weights are O(1/T), so the weighted-sum error cancels. "
        "See successor H5.2 for the near-one-hot attention edge case that may "
        "still stress bf16 accumulation."
    ),
    strict=True,
)
@pytest.mark.parametrize("T", [4096, 8192])
def test_H5_1_prediction_bf16_accum_drift_exceeds_tolerance_at_long_T_XFAIL(T):
    """Preserved as xfail: original H5.1 prediction. Strict=True means pytest
    fails the suite if this ever starts PASSING — that would indicate the
    simulation changed and we have a new real-world regression."""
    scores, V = _random_mla_inputs(T=T, seed=42)
    out_fp64 = _mla_output(scores, V, bf16_accum=False)
    out_bf16 = _mla_output(scores, V, bf16_accum=True)
    max_err = float(np.max(np.abs(out_fp64 - out_bf16)))
    assert max_err > VALIDATOR_BF16_TOLERANCE


@pytest.mark.parametrize("T", [64, 256, 1024, 4096, 8192])
def test_bf16_accum_learned_behavior_stays_within_tolerance(T):
    """H5.1-derived regression guard: bf16 accum drift stays within 5e-2
    at ALL tested T on uniform attention. This is the ACTUAL observed
    behavior, contradicting math §9's O(T*ULP) pessimism. If this test
    starts failing, bf16-accum has regressed or inputs have shifted."""
    scores, V = _random_mla_inputs(T=T, seed=42)
    out_fp64 = _mla_output(scores, V, bf16_accum=False)
    out_bf16 = _mla_output(scores, V, bf16_accum=True)
    max_err = float(np.max(np.abs(out_fp64 - out_bf16)))
    assert max_err <= VALIDATOR_BF16_TOLERANCE, (
        f"bf16 accum drift at T={T} = {max_err:.3e} exceeds tolerance "
        f"{VALIDATOR_BF16_TOLERANCE:.0e}. Either input scale shifted or "
        f"simulation regressed."
    )


def test_bf16_accum_drift_does_NOT_grow_linearly_with_T():
    """H5.1-derived regression guard: math §9 predicted O(T) drift growth;
    actual behavior is sub-linear (softmax cancellation). Guard against
    anyone re-introducing an O(T) assumption into a future mutation prompt."""
    drifts: dict[int, float] = {}
    for T in (64, 256, 1024, 4096, 8192):
        scores, V = _random_mla_inputs(T=T, seed=42)
        out_fp64 = _mla_output(scores, V, bf16_accum=False)
        out_bf16 = _mla_output(scores, V, bf16_accum=True)
        drifts[T] = float(np.max(np.abs(out_fp64 - out_bf16)))
    # Actual observation: drift at T=8192 is within 2x of drift at T=64
    # (often smaller due to cancellation). If the ratio ever exceeds 10x,
    # linear-growth behavior has re-emerged and math §9's model reverts.
    ratio = drifts[8192] / max(drifts[64], 1e-12)
    assert ratio < 10.0, (
        f"bf16 drift scaled to {ratio:.2f}x from T=64 to T=8192; "
        f"O(T) prediction was ~128x. Regression to O(T) behavior would "
        f"invalidate H5.1-falsified regression guards."
    )


# ---- H5.2 tests ----

def _bf16_sequential_accumulator_sum(arr: np.ndarray) -> float:
    """True bf16 accumulator: add each element sequentially, truncate to
    bf16 precision after each addition. This is the abstraction math §9
    modeled — theoretical, not production. Real bf16 kernels use fp32
    accumulator internally.

    Slow in Python for large T, but correct. Kept off the hot path; only
    used in H5.2 edge-case tests."""
    acc = np.float32(0.0)
    for v in arr.astype(np.float32).ravel():
        acc = _bf16_round(np.array([acc + v], dtype=np.float32))[0]
    return float(acc)


def _bf16_operand_fp32_accum_sum(arr: np.ndarray) -> float:
    """Production abstraction: bf16 OPERANDS, fp32 ACCUMULATOR. Every
    tensor-core MMA does this; every well-written softmax kernel does
    this. Error scales O(sqrt(T)*ULP) not O(T*ULP) because accumulator
    precision exceeds operand precision."""
    arr_bf16 = _bf16_round(arr.astype(np.float32))
    return float(arr_bf16.astype(np.float64).sum())


@pytest.mark.parametrize("T", [1024, 4096])
def test_H5_2_sequential_bf16_accum_shows_O_T_drift(T):
    """H5.2: strict-sequential bf16 accumulator DOES show math §9's
    O(T*ULP) drift. This is the theoretical abstraction; confirms math
    §9 is correct for THAT abstraction even though it's not what
    production kernels do.

    Setup: sum T values each ~1.0; exact sum is T. bf16 sequential
    accumulator drifts linearly with T due to precision loss at each
    addition. Predicted relative drift at T=4096: ~T*ULP/2 ~ 16.
    """
    rng = np.random.default_rng(7)
    # Values near 1.0 stress bf16 ULP (which is ~7.8e-3 at that magnitude)
    arr = rng.uniform(0.9, 1.1, size=T).astype(np.float32)
    exact = float(arr.astype(np.float64).sum())
    bf16_seq = _bf16_sequential_accumulator_sum(arr)
    rel_drift = abs(bf16_seq - exact) / abs(exact)
    # math §9 O(T*ULP) predicts rel_drift grows linearly with T; at T=1024
    # should be >=0.5%, at T=4096 should be >=2%. These are DEGRADED numbers
    # exceeding the 5e-2 tolerance when applied to output scale.
    min_expected_drift = 5e-3 if T == 1024 else 2e-2
    assert rel_drift >= min_expected_drift, (
        f"H5.2 falsified at T={T}: sequential bf16 accum rel_drift "
        f"{rel_drift:.3e} < {min_expected_drift:.0e}. Math §9's O(T*ULP) "
        f"abstraction does not hold even sequentially; fp32-accum-only "
        f"guidance in mutation prompts may be over-prescribed."
    )


@pytest.mark.parametrize("T", [64, 1024, 4096])
def test_H5_2_fp32_accum_stays_bounded_at_all_T(T):
    """H5.2 corollary: bf16-operand + fp32-accumulator is the production
    abstraction and stays within 5e-2 at all T. Confirms H5.1's falsified
    result is explained by "real kernels use fp32 accum, not bf16 accum."
    """
    rng = np.random.default_rng(7)
    arr = rng.uniform(0.9, 1.1, size=T).astype(np.float32)
    exact = float(arr.astype(np.float64).sum())
    bf16_op_fp32_acc = _bf16_operand_fp32_accum_sum(arr)
    rel_drift = abs(bf16_op_fp32_acc - exact) / abs(exact)
    assert rel_drift <= VALIDATOR_BF16_TOLERANCE, (
        f"Production abstraction drifted {rel_drift:.3e} at T={T}, "
        f"exceeds 5e-2. H5.2 falsified: fp32-accumulator is NOT sufficient "
        f"to explain H5.1. Something else is giving uniform attention its "
        f"robustness."
    )


def test_H5_2_summarizes_the_real_guidance():
    """H5.2 synthesis: mutation prompts should demand fp32 ACCUMULATOR,
    not fp32 OPERANDS. This test pins the distinction numerically.

    - Theoretical pure-bf16-accum: O(T*ULP), unsafe at T>=1024 (demonstrated)
    - Production bf16-op + fp32-accum: O(sqrt(T)*ULP), safe at T=8192 (demonstrated)
    - Gap in relative drift at T=4096 is >= 10x.
    """
    rng = np.random.default_rng(7)
    T = 4096
    arr = rng.uniform(0.9, 1.1, size=T).astype(np.float32)
    exact = float(arr.astype(np.float64).sum())
    seq_drift = abs(_bf16_sequential_accumulator_sum(arr) - exact) / abs(exact)
    acc_drift = abs(_bf16_operand_fp32_accum_sum(arr) - exact) / abs(exact)
    assert seq_drift >= 10 * acc_drift, (
        f"Expected >=10x drift gap between sequential-bf16 and "
        f"fp32-accum; got seq={seq_drift:.3e}, acc={acc_drift:.3e} "
        f"(ratio {seq_drift/max(acc_drift,1e-12):.1f}x). Guidance for "
        f"mutation prompts ('demand fp32 accumulator') loses its numeric "
        f"grounding."
    )


def test_bf16_round_simulation_is_actually_bf16ish():
    """Sanity: _bf16_round produces the precision loss we claim.

    An fp32 with mantissa bits beyond bit 16 gets flushed; 1.0 + 2^-23
    (smallest fp32 ULP at 1.0) rounds down to 1.0 in bf16 (bf16 ULP at 1.0
    is 2^-7). 1.0 + 2^-7 should be preserved.
    """
    x = np.array([1.0 + 2**-23], dtype=np.float32)
    rounded = _bf16_round(x)
    assert rounded[0] == 1.0
    y = np.array([1.0 + 2**-7], dtype=np.float32)
    assert _bf16_round(y)[0] == 1.0 + 2**-7
