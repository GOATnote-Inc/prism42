"""Lock the MLA reference implementations: naive and absorbed must agree
within float-associativity tolerance, on small and larger configs.

If this test starts failing, the absorbed mutation is no longer a safe swap
for the naive reference; the manual_mutation loop's speedup claim invalidates.
"""
from __future__ import annotations

import numpy as np
import pytest

from kernels.base.mla_decode_numpy import (
    MLAConfig,
    make_inputs,
    mla_decode_absorbed,
    mla_decode_naive,
)
from prism import DEFAULT_INVARIANTS, validate


SMALL = MLAConfig(batch=1, heads=2, kv_len=16, d_c=8, d_r=4, qk_nope=8, v_head=8)
MID = MLAConfig(batch=2, heads=8, kv_len=128, d_c=64, d_r=16, qk_nope=32, v_head=32)


@pytest.mark.parametrize("cfg", [SMALL, MID])
def test_naive_and_absorbed_agree(cfg):
    inputs = make_inputs(cfg, seed=0)
    out_n = mla_decode_naive(**inputs)
    out_a = mla_decode_absorbed(**inputs)
    assert out_n.shape == out_a.shape == (cfg.batch, cfg.heads, cfg.v_head)
    max_err = float(np.max(np.abs(out_n - out_a)))
    # Float-associativity tolerance; einsum ordering differs between forms.
    assert max_err < 1e-4, f"naive vs absorbed max_err={max_err:.3e} exceeds 1e-4"


def test_absorbed_passes_validator_tier2():
    cfg = MID
    inputs = make_inputs(cfg, seed=0)
    sweep = [
        make_inputs(MLAConfig(1, 8, 64, 64, 16, 32, 32), seed=1),
        make_inputs(MLAConfig(2, 8, 32, 64, 16, 32, 32), seed=2),
    ]
    r = validate(
        mla_decode_absorbed,
        mla_decode_naive,
        inputs,
        tolerance=1e-3,
        config_sweep=sweep,
        invariants=DEFAULT_INVARIANTS,
    )
    assert r.passed, f"absorbed failed validator: {r.failed_check}"
    assert r.tier_reached == 2


def test_output_deterministic():
    cfg = SMALL
    inputs = make_inputs(cfg, seed=0)
    out_1 = mla_decode_absorbed(**inputs)
    out_2 = mla_decode_absorbed(**inputs)
    assert np.array_equal(out_1, out_2), "absorbed kernel is non-deterministic"


def test_output_has_no_nan_inf():
    cfg = MID
    inputs = make_inputs(cfg, seed=99)
    for kernel in (mla_decode_naive, mla_decode_absorbed):
        out = kernel(**inputs)
        assert not np.isnan(out).any(), f"{kernel.__name__} produced NaN"
        assert not np.isinf(out).any(), f"{kernel.__name__} produced Inf"
