"""JAX port of the MLA decode reference.

Phase M / M7 (Trillium rail). See docs/mla-oracle-roadmap.md §3 M7.

Mirrors corpus/mla/reference/mla_decode_numpy.py bit-for-bit at FP32,
and additionally exposes a bf16 path for native Trillium (v6e) execution.
The oracle grades the bf16 output against the FP32 committed golden
using the "bf16" tolerance preset.

Run (on TPU VM):
    python3 mla_decode_jax.py --dtype bf16 --config v2_lite

Output: one JSON object on stdout with
    {"bug_id": "TPU-RAIL-PROOF", "status": "triggered",
     "hardware": {"device_kind": "...", "dtype_requested": "bf16"},
     "dtype": "bf16", "output": [[float, ...]]}

Design: same seeded weight init as the numpy reference (so the same
golden applies). Non-absorbed form only — absorbed form's identical
outputs were already cross-checked in M2; running one form on TPU is
enough to validate the algebra's portability.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MLAConfig:
    d_model: int = 2048
    n_heads: int = 16
    d_nope: int = 128
    d_rope: int = 64
    d_v: int = 128
    d_c: int = 512

    @classmethod
    def v2_lite(cls) -> "MLAConfig":
        return cls()

    @classmethod
    def small(cls) -> "MLAConfig":
        return cls(d_model=256, n_heads=2, d_nope=64, d_rope=16, d_v=64, d_c=64)


def _init_weights(cfg: MLAConfig, seed: int = 42):
    """FP32 numpy init (same seed scheme as mla_decode_numpy.py)."""
    rng = np.random.default_rng(seed)
    s_model = 1.0 / np.sqrt(cfg.d_model)
    s_c = 1.0 / np.sqrt(cfg.d_c)
    s_v = 1.0 / np.sqrt(cfg.n_heads * cfg.d_v)
    return {
        "W_Q_nope": rng.normal(0, s_model, (cfg.d_model, cfg.n_heads * cfg.d_nope)).astype(np.float32),
        "W_Q_rope": rng.normal(0, s_model, (cfg.d_model, cfg.n_heads * cfg.d_rope)).astype(np.float32),
        "W_UK":     rng.normal(0, s_c, (cfg.d_c, cfg.n_heads * cfg.d_nope)).astype(np.float32),
        "W_UV":     rng.normal(0, s_c, (cfg.d_c, cfg.n_heads * cfg.d_v)).astype(np.float32),
        "W_O":      rng.normal(0, s_v, (cfg.n_heads * cfg.d_v, cfg.d_model)).astype(np.float32),
    }


def _init_cache(cfg: MLAConfig, seqlen: int, seed: int = 43):
    rng = np.random.default_rng(seed)
    return {
        "c_kv": rng.normal(0, 1.0, (seqlen, cfg.d_c)).astype(np.float32),
        "k_r":  rng.normal(0, 1.0, (seqlen, cfg.d_rope)).astype(np.float32),
    }


def _init_query(cfg: MLAConfig, batch: int = 1, seed: int = 44):
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1.0, (batch, cfg.d_model)).astype(np.float32)


def mla_decode_nonabsorbed_jax(x_q, c_kv, k_r, weights, cfg: MLAConfig):
    """JAX non-absorbed MLA decode. Casting to target dtype is the caller's job."""
    import jax.numpy as jnp  # lazy-imported so module imports cheap

    B, _ = x_q.shape
    S, _ = c_kv.shape

    q_nope = (x_q @ weights["W_Q_nope"]).reshape(B, cfg.n_heads, cfg.d_nope)
    q_rope = (x_q @ weights["W_Q_rope"]).reshape(B, cfg.n_heads, cfg.d_rope)

    k_nope = (c_kv @ weights["W_UK"]).reshape(S, cfg.n_heads, cfg.d_nope)

    scores_nope = jnp.einsum("bhd,shd->bhs", q_nope, k_nope)
    scores_rope = jnp.einsum("bhd,sd->bhs", q_rope, k_r)
    scale = 1.0 / jnp.sqrt(jnp.array(cfg.d_nope + cfg.d_rope, dtype=x_q.dtype))
    scores = (scores_nope + scores_rope) * scale
    scores_max = scores.max(axis=-1, keepdims=True)
    ex = jnp.exp(scores - scores_max)
    attn = ex / ex.sum(axis=-1, keepdims=True)

    v = (c_kv @ weights["W_UV"]).reshape(S, cfg.n_heads, cfg.d_v)
    ctx = jnp.einsum("bhs,shd->bhd", attn, v).reshape(B, cfg.n_heads * cfg.d_v)
    return ctx @ weights["W_O"]


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    p = argparse.ArgumentParser(description="JAX MLA decode reference (TPU / Trillium rail)")
    p.add_argument("--dtype", choices=["fp32", "bf16", "fp16"], default="bf16")
    p.add_argument("--config", choices=["small", "v2_lite"], default="v2_lite")
    p.add_argument("--seqlen", type=int, default=16)
    args = p.parse_args()

    try:
        import jax
        import jax.numpy as jnp
    except ImportError as e:
        _emit({
            "bug_id": "TPU-RAIL-PROOF",
            "status": "error",
            "reason": f"jax not importable: {e}",
        })
        return 1

    cfg = getattr(MLAConfig, args.config)()
    dtype_map = {"fp32": jnp.float32, "bf16": jnp.bfloat16, "fp16": jnp.float16}
    dtype = dtype_map[args.dtype]

    # Seeded FP32 init in numpy, cast to target dtype for TPU run.
    weights_np = _init_weights(cfg, seed=42)
    cache_np = _init_cache(cfg, seqlen=args.seqlen, seed=43)
    x_q_np = _init_query(cfg, batch=1, seed=44)

    weights = {k: jnp.asarray(v, dtype=dtype) for k, v in weights_np.items()}
    c_kv = jnp.asarray(cache_np["c_kv"], dtype=dtype)
    k_r = jnp.asarray(cache_np["k_r"], dtype=dtype)
    x_q = jnp.asarray(x_q_np, dtype=dtype)

    out = mla_decode_nonabsorbed_jax(x_q, c_kv, k_r, weights, cfg)
    out_fp32 = np.asarray(out.astype(jnp.float32))

    devices = jax.devices()
    device_kind = devices[0].device_kind if devices else "cpu"
    _emit({
        "bug_id": "TPU-RAIL-PROOF",
        "status": "triggered",
        "hardware": {
            "device_kind": device_kind,
            "device_count": len(devices),
            "dtype_requested": args.dtype,
            "config": args.config,
            "seqlen": args.seqlen,
        },
        "dtype": args.dtype,
        "output": out_fp32.tolist(),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
