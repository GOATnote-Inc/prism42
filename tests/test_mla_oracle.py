"""Tests for the MLA decode oracle (Phase M / M3).

The oracle must:
    - PASS a correct candidate (reference itself, or reference with
      dtype-appropriate noise).
    - FAIL each canonical failure mode: shape mismatch, NaN poison,
      magnitude drift, sign flip, all-zeros.
    - Flag the right reason on failure (not just pass=False).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

numpy = pytest.importorskip("numpy")
import numpy as np  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ORACLE_DIR = REPO_ROOT / "corpus" / "mla" / "oracle"
REF_DIR = REPO_ROOT / "corpus" / "mla" / "reference"
GOLDEN_DIR = REF_DIR / "golden_vectors"


@pytest.fixture(scope="module")
def oracle():
    """Load the oracle module (harness + tolerances) by path."""
    # tolerances.py must load first — harness imports from it by name.
    sys.path.insert(0, str(ORACLE_DIR))
    try:
        tol_spec = importlib.util.spec_from_file_location("tolerances", ORACLE_DIR / "tolerances.py")
        tol_mod = importlib.util.module_from_spec(tol_spec)
        sys.modules["tolerances"] = tol_mod
        tol_spec.loader.exec_module(tol_mod)

        har_spec = importlib.util.spec_from_file_location("harness", ORACLE_DIR / "harness.py")
        har_mod = importlib.util.module_from_spec(har_spec)
        sys.modules["harness"] = har_mod
        har_spec.loader.exec_module(har_mod)

        return {"harness": har_mod, "tolerances": tol_mod}
    finally:
        sys.path.remove(str(ORACLE_DIR))
        # intentionally leave modules in sys.modules across the test module;
        # tearing down here would break cross-test re-use of the fixture.


@pytest.fixture(scope="module")
def reference_output():
    """Load the committed v2_lite golden as our reference tensor."""
    with (GOLDEN_DIR / "v2_lite_decode_s16_w42.json").open() as fh:
        golden = json.load(fh)
    return np.asarray(golden["output"], dtype=np.float32)


# ---- pass cases ---------------------------------------------------------


def test_reference_vs_itself_passes(oracle, reference_output):
    tol = oracle["tolerances"].get_tolerance("fp32")
    v = oracle["harness"].check(reference_output, reference_output, tol)
    assert v.passed, f"reference-vs-itself failed: {v.reasons}"
    assert v.max_abs_diff == 0.0
    assert v.max_rel_diff == 0.0
    assert v.cos_sim == pytest.approx(1.0, abs=1e-12)
    assert v.nan_count == 0
    assert v.inf_count == 0


def test_bf16_precision_noise_passes_bf16_tolerance(oracle, reference_output):
    """Simulate a bf16-quantized output: downcast and upcast — adds bf16 noise."""
    # numpy has no native bf16; simulate by masking low mantissa bits.
    # bf16 = 1 sign + 8 exp + 7 mantissa.  FP32 has 23 mantissa bits.
    # Drop lower 16 mantissa bits to approximate bf16 quantization.
    bits = reference_output.view(np.uint32).copy()
    bits &= np.uint32(0xFFFF0000)
    candidate = bits.view(np.float32).reshape(reference_output.shape)

    tol = oracle["tolerances"].get_tolerance("bf16")
    v = oracle["harness"].check(reference_output, candidate, tol, candidate_label="bf16-sim")
    assert v.passed, f"bf16-sim failed bf16 tolerance: {v.reasons}"
    # bf16 quantization noise should be well under the bf16 floor.
    assert v.max_rel_diff < tol.max_rel_diff
    assert v.cos_sim > tol.min_cos_sim


def test_bf16_precision_noise_fails_fp32_tolerance(oracle, reference_output):
    """Same bf16-quantized output, graded against tighter fp32 tolerance — must fail."""
    bits = reference_output.view(np.uint32).copy()
    bits &= np.uint32(0xFFFF0000)
    candidate = bits.view(np.float32).reshape(reference_output.shape)

    tol = oracle["tolerances"].get_tolerance("fp32")
    v = oracle["harness"].check(reference_output, candidate, tol, candidate_label="bf16-vs-fp32-tol")
    assert not v.passed
    # At least one bound should have been exceeded; since bf16 has ~8e-3 rel ULP,
    # this trips rel_diff_exceeded.
    assert any("rel_diff_exceeded" in r or "abs_diff_exceeded" in r for r in v.reasons), v.reasons


# ---- failure cases ------------------------------------------------------


def test_shape_mismatch_fails(oracle, reference_output):
    tol = oracle["tolerances"].get_tolerance("fp32")
    truncated = reference_output[:, :-1]  # shape (1, d_model-1)
    v = oracle["harness"].check(reference_output, truncated, tol)
    assert not v.passed
    assert not v.shape_match
    assert any("shape_mismatch" in r for r in v.reasons)


def test_nan_poison_fails(oracle, reference_output):
    tol = oracle["tolerances"].get_tolerance("fp32")
    candidate = reference_output.copy()
    candidate[0, 0] = np.nan
    v = oracle["harness"].check(reference_output, candidate, tol)
    assert not v.passed
    assert v.nan_count == 1
    assert any("nan_detected" in r for r in v.reasons)


def test_magnitude_drift_fails(oracle, reference_output):
    tol = oracle["tolerances"].get_tolerance("fp32")
    candidate = reference_output * 10.0  # 10x scale — huge rel diff
    v = oracle["harness"].check(reference_output, candidate, tol)
    assert not v.passed
    assert any("abs_diff_exceeded" in r or "rel_diff_exceeded" in r for r in v.reasons)


def test_sign_flip_fails_cosine(oracle, reference_output):
    """Negated output has perfect magnitude match but cos_sim = -1."""
    tol = oracle["tolerances"].get_tolerance("nvfp4")  # most permissive tolerance
    candidate = -reference_output
    v = oracle["harness"].check(reference_output, candidate, tol)
    assert not v.passed
    # Cosine similarity for negation is -1 — catches this even if magnitudes match.
    assert v.cos_sim == pytest.approx(-1.0, abs=1e-6)
    assert any("cos_sim_below_floor" in r for r in v.reasons)


def test_zeros_fails_cosine(oracle, reference_output):
    """All-zeros output — classic "kernel silently no-ops" failure."""
    tol = oracle["tolerances"].get_tolerance("nvfp4")  # most permissive
    candidate = np.zeros_like(reference_output)
    v = oracle["harness"].check(reference_output, candidate, tol)
    assert not v.passed
    # Cosine similarity with a zero vector is ~0 (eps prevents div-by-zero).
    assert v.cos_sim < 0.01
    assert any("cos_sim_below_floor" in r for r in v.reasons)


# ---- convenience API -----------------------------------------------------


def test_check_against_golden_passes(oracle, reference_output):
    golden_path = GOLDEN_DIR / "v2_lite_decode_s16_w42.json"
    tol = oracle["tolerances"].get_tolerance("fp32")
    v = oracle["harness"].check_against_golden(str(golden_path), reference_output, tol)
    # Golden JSON may drift by ~1 ULP from in-memory reference due to JSON round-trip.
    # fp32 tolerance (1e-5 rel) accommodates that.
    assert v.passed, f"golden check failed: {v.reasons}"


def test_unknown_dtype_raises(oracle):
    with pytest.raises(KeyError):
        oracle["tolerances"].get_tolerance("fp1")


# ---- verdict serialization ----------------------------------------------


def test_verdict_is_json_serializable(oracle, reference_output):
    tol = oracle["tolerances"].get_tolerance("fp32")
    v = oracle["harness"].check(reference_output, reference_output, tol)
    d = v.to_dict()
    # Round-trip through json to confirm serializability.
    s = json.dumps(d)
    d2 = json.loads(s)
    assert d2["passed"] is True
    assert d2["tolerance_name"] == "fp32"
