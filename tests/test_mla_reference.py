"""Tests for the MLA decode reference (Phase M / M2).

Verifies:
    1. Both decode forms (non-absorbed, absorbed) agree within FP32 tolerance.
    2. Committed golden vectors reproduce exactly from the documented seeds.
    3. Golden JSON files have the expected schema.
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
REF_DIR = REPO_ROOT / "corpus" / "mla" / "reference"
GOLDEN_DIR = REF_DIR / "golden_vectors"


@pytest.fixture(scope="module")
def ref():
    """Load the reference module by path without requiring a package layout."""
    module_name = "mla_decode_numpy"
    spec = importlib.util.spec_from_file_location(module_name, REF_DIR / "mla_decode_numpy.py")
    mod = importlib.util.module_from_spec(spec)
    # dataclasses on Python 3.14 resolve annotations via sys.modules[__module__];
    # register before exec so @dataclass-decorated classes can find their own module.
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize("config_name", ["small", "v2_lite"])
def test_both_forms_agree(ref, config_name):
    cfg = getattr(ref.MLAConfig, config_name)()
    weights = ref.init_weights(cfg, seed=42)
    cache = ref.init_cache(cfg, seqlen=16, seed=43)
    x_q = ref.init_query(cfg, batch=1, seed=44)

    out_nonabs = ref.mla_decode_nonabsorbed(x_q, cache["c_kv"], cache["k_r"], weights, cfg)
    out_abs = ref.mla_decode_absorbed(x_q, cache["c_kv"], cache["k_r"], weights, cfg)

    max_abs = float(np.abs(out_nonabs - out_abs).max())
    out_scale = float(np.abs(out_nonabs).max()) + 1e-9
    max_rel = max_abs / out_scale

    assert max_rel < 1e-4, f"{config_name}: forms disagree rel={max_rel:.3e}"


@pytest.mark.parametrize("config_name", ["small", "v2_lite"])
def test_golden_reproduces_exactly(ref, config_name):
    """The committed golden must be bit-exactly reproducible from its seeds."""
    path = GOLDEN_DIR / f"{config_name}_decode_s16_w42.json"
    assert path.exists(), f"missing golden: {path}"
    golden = json.loads(path.read_text())

    cfg = getattr(ref.MLAConfig, config_name)()
    seeds = golden["seeds"]
    weights = ref.init_weights(cfg, seed=seeds["weights_seed"])
    cache = ref.init_cache(cfg, seqlen=golden["seqlen"], seed=seeds["cache_seed"])
    x_q = ref.init_query(cfg, batch=1, seed=seeds["query_seed"])

    out = ref.mla_decode_nonabsorbed(x_q, cache["c_kv"], cache["k_r"], weights, cfg)

    # Primary integrity: sha256 of regenerated output must exactly match stored sha256.
    # This is the canonical drift check — if the reference computation changes by any bit,
    # this fails.
    assert ref.output_sha256(out) == golden["output_sha256"], \
        f"{config_name}: golden sha256 mismatch (reference drift?)"

    # Secondary sanity: stored inline values match regenerated within JSON round-trip tolerance.
    # JSON serializes fp32 via fp64 repr, which can introduce up to ~1 fp32 ULP (~1.2e-7
    # relative) on re-parse + cast-to-fp32. sha256 above is the strict check.
    stored = np.asarray(golden["output"], dtype=np.float32)
    assert stored.shape == out.shape
    max_diff = float(np.abs(stored - out).max())
    assert max_diff < 1e-6, \
        f"{config_name}: stored output diverges from regeneration by {max_diff:.3e} (>1e-6)"


@pytest.mark.parametrize("config_name", ["small", "v2_lite"])
def test_golden_schema(config_name):
    path = GOLDEN_DIR / f"{config_name}_decode_s16_w42.json"
    golden = json.loads(path.read_text())

    # Required top-level keys
    for key in ("config_name", "config", "seeds", "seqlen", "shapes", "output_sha256", "output"):
        assert key in golden, f"golden missing key: {key}"

    # Config name matches filename
    assert golden["config_name"] == config_name

    # Config has all MLA shape params
    for key in ("d_model", "n_heads", "d_nope", "d_rope", "d_v", "d_c"):
        assert key in golden["config"], f"golden config missing: {key}"

    # Seeds block
    for key in ("weights_seed", "cache_seed", "query_seed"):
        assert key in golden["seeds"], f"golden seeds missing: {key}"

    # Output shape matches declared shape
    out = np.asarray(golden["output"], dtype=np.float32)
    assert list(out.shape) == golden["shapes"]["out"]

    # sha256 length
    assert len(golden["output_sha256"]) == 64
