"""Reference numpy MLA decode — the golden that every kernel candidate is graded against.

Phase M (MLA decode oracle). See docs/mla-oracle-roadmap.md §3 M2.

Implements Multi-head Latent Attention decode in two equivalent forms:

    1. non-absorbed: K and V are materialized from the cache (c_KV, k_R) via
       the up-projections W_UK and W_UV. Straightforward, easy to audit.

    2. absorbed: the decode-time algebra folds W_UK into the query
       projection and W_UV into the output projection, so K and V are
       never materialized. This is the canonical production decode form
       (DeepSeek V2 §2.1.3, "absorption"). Faster on real hardware;
       numerically equivalent to non-absorbed up to FP32 round-off.

The self-test at the bottom asserts both forms agree within 1e-4
relative error and prints a sha256 of the canonical output.

RoPE is intentionally omitted from this reference. MLA's decoupled-RoPE
design (d_h^R dim, Rotary applied separately to q_rope and cached k_R)
is orthogonal to the correctness property the oracle audits — namely
that the attention algebra is preserved across precision-reduced kernels.
Any candidate kernel must apply RoPE consistently with this reference
(either both-sides-skipped, or both-sides-applied with identical cos/sin
tables) for a direct comparison. The oracle's ULP bound accounts for
this constraint in its contract.

Shapes follow DeepSeek-V2-Lite (`kv_lora_rank=512`, `qk_nope_head_dim=128`,
`qk_rope_head_dim=64`, `v_head_dim=128`, `num_attention_heads=16`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict

import numpy as np


@dataclass(frozen=True)
class MLAConfig:
    """MLA decode shape parameters. Default matches DeepSeek-V2-Lite."""

    d_model: int = 2048
    n_heads: int = 16
    d_nope: int = 128       # qk_nope_head_dim
    d_rope: int = 64        # qk_rope_head_dim
    d_v: int = 128          # v_head_dim
    d_c: int = 512          # kv_lora_rank
    # (q_lora_rank is omitted — this reference uses full-rank W_Q for simplicity;
    # numerical correctness of the decode algebra is unchanged.)

    @classmethod
    def v2_lite(cls) -> "MLAConfig":
        return cls()

    @classmethod
    def small(cls) -> "MLAConfig":
        """Small config for fast unit tests (~100x smaller than v2_lite)."""
        return cls(d_model=256, n_heads=2, d_nope=64, d_rope=16, d_v=64, d_c=64)


def init_weights(cfg: MLAConfig, seed: int = 42) -> Dict[str, np.ndarray]:
    """Generate seeded MLA weights in FP32.

    Variance scaling follows standard transformer init: 1/sqrt(fan_in).
    """
    rng = np.random.default_rng(seed)
    s_model = 1.0 / np.sqrt(cfg.d_model)
    s_c = 1.0 / np.sqrt(cfg.d_c)
    s_v = 1.0 / np.sqrt(cfg.n_heads * cfg.d_v)

    return {
        # Query projections (full-rank for simplicity; real MLA uses q_lora)
        "W_Q_nope": rng.normal(0, s_model, (cfg.d_model, cfg.n_heads * cfg.d_nope)).astype(np.float32),
        "W_Q_rope": rng.normal(0, s_model, (cfg.d_model, cfg.n_heads * cfg.d_rope)).astype(np.float32),
        # KV down-projection and up-projections
        "W_UK":     rng.normal(0, s_c, (cfg.d_c, cfg.n_heads * cfg.d_nope)).astype(np.float32),
        "W_UV":     rng.normal(0, s_c, (cfg.d_c, cfg.n_heads * cfg.d_v)).astype(np.float32),
        # Output projection
        "W_O":      rng.normal(0, s_v, (cfg.n_heads * cfg.d_v, cfg.d_model)).astype(np.float32),
    }


def init_cache(cfg: MLAConfig, seqlen: int, seed: int = 43) -> Dict[str, np.ndarray]:
    """Generate seeded MLA KV cache.

    Returns:
        c_kv: [S, d_c] compressed latent KV cache.
        k_r:  [S, d_rope] decoupled RoPE K cache (shared across heads).
    """
    rng = np.random.default_rng(seed)
    return {
        "c_kv": rng.normal(0, 1.0, (seqlen, cfg.d_c)).astype(np.float32),
        "k_r":  rng.normal(0, 1.0, (seqlen, cfg.d_rope)).astype(np.float32),
    }


def init_query(cfg: MLAConfig, batch: int = 1, seed: int = 44) -> np.ndarray:
    """Generate a seeded query activation [B, d_model]."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1.0, (batch, cfg.d_model)).astype(np.float32)


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    """Numerically stable softmax."""
    x_max = x.max(axis=axis, keepdims=True)
    ex = np.exp(x - x_max)
    return ex / ex.sum(axis=axis, keepdims=True)


def mla_decode_nonabsorbed(
    x_q: np.ndarray,
    c_kv: np.ndarray,
    k_r: np.ndarray,
    weights: Dict[str, np.ndarray],
    cfg: MLAConfig,
) -> np.ndarray:
    """MLA decode, non-absorbed form. K and V are materialized via up-projections.

    Args:
        x_q:   [B, d_model]   query activation for the decode step.
        c_kv:  [S, d_c]       compressed KV latent cache.
        k_r:   [S, d_rope]    decoupled RoPE K cache (shared across heads).
        weights: from init_weights().
        cfg:     MLAConfig.

    Returns:
        out: [B, d_model] decode output.
    """
    B, _ = x_q.shape
    S, _ = c_kv.shape

    # Query projection
    q_nope = (x_q @ weights["W_Q_nope"]).reshape(B, cfg.n_heads, cfg.d_nope)
    q_rope = (x_q @ weights["W_Q_rope"]).reshape(B, cfg.n_heads, cfg.d_rope)

    # Reconstruct K (non-RoPE part) from compressed cache
    k_nope = (c_kv @ weights["W_UK"]).reshape(S, cfg.n_heads, cfg.d_nope)

    # Attention scores
    scores_nope = np.einsum("bhd,shd->bhs", q_nope, k_nope)
    scores_rope = np.einsum("bhd,sd->bhs", q_rope, k_r)
    scale = 1.0 / np.sqrt(cfg.d_nope + cfg.d_rope)
    scores = (scores_nope + scores_rope) * scale
    attn = _softmax(scores, axis=-1)  # [B, H, S]

    # Reconstruct V from compressed cache
    v = (c_kv @ weights["W_UV"]).reshape(S, cfg.n_heads, cfg.d_v)

    # Context and output projection
    ctx = np.einsum("bhs,shd->bhd", attn, v).reshape(B, cfg.n_heads * cfg.d_v)
    return ctx @ weights["W_O"]


def mla_decode_absorbed(
    x_q: np.ndarray,
    c_kv: np.ndarray,
    k_r: np.ndarray,
    weights: Dict[str, np.ndarray],
    cfg: MLAConfig,
) -> np.ndarray:
    """MLA decode, absorbed form. K and V are never materialized.

    The weight products W_Q_nope @ W_UK^T (per head) and W_O @ W_UV^T (per
    head) are absorbed so the attention operates directly on the compressed
    latent c_kv. This is the canonical decode form used by production
    kernels (DeepSeek FlashMLA, FlashInfer trtllm MLA, CUTLASS CuTeDSL
    blackwell/mla).
    """
    B, _ = x_q.shape
    S, _ = c_kv.shape
    H, D_NOPE, D_V, D_C = cfg.n_heads, cfg.d_nope, cfg.d_v, cfg.d_c

    # Per-head reshape of Q-projection and K up-projection
    W_Q_nope_h = weights["W_Q_nope"].reshape(cfg.d_model, H, D_NOPE).transpose(1, 0, 2)  # [H, D_MODEL, D_NOPE]
    W_UK_h = weights["W_UK"].reshape(D_C, H, D_NOPE).transpose(1, 0, 2)                  # [H, D_C, D_NOPE]

    # Absorb: Q-in-latent-space = W_Q_nope @ W_UK^T, per head. [H, D_MODEL, D_C]
    W_Q_abs = np.einsum("hmd,hcd->hmc", W_Q_nope_h, W_UK_h)

    # Project query directly to latent space (per head)
    q_nope_abs = np.einsum("bm,hmc->bhc", x_q, W_Q_abs)  # [B, H, D_C]

    # Score against c_kv directly — no K reconstruction
    scores_nope = np.einsum("bhc,sc->bhs", q_nope_abs, c_kv)

    # RoPE portion unchanged (decoupled, shared across heads)
    q_rope = (x_q @ weights["W_Q_rope"]).reshape(B, H, cfg.d_rope)
    scores_rope = np.einsum("bhd,sd->bhs", q_rope, k_r)

    scale = 1.0 / np.sqrt(cfg.d_nope + cfg.d_rope)
    scores = (scores_nope + scores_rope) * scale
    attn = _softmax(scores, axis=-1)  # [B, H, S]

    # Context in latent space (attention-weighted c_kv, per head)
    ctx_latent = np.einsum("bhs,sc->bhc", attn, c_kv)  # [B, H, D_C]

    # Absorb W_UV into W_O: per-head output-from-latent = W_UV @ W_O. [H, D_C, D_MODEL]
    W_UV_h = weights["W_UV"].reshape(D_C, H, D_V).transpose(1, 0, 2)   # [H, D_C, D_V]
    W_O_h = weights["W_O"].reshape(H, D_V, cfg.d_model)                # [H, D_V, D_MODEL]
    W_O_abs = np.einsum("hcv,hvm->hcm", W_UV_h, W_O_h)

    # Output: sum over heads of ctx_latent @ W_O_abs
    return np.einsum("bhc,hcm->bm", ctx_latent, W_O_abs)


def output_sha256(x: np.ndarray) -> str:
    """Deterministic hash of an output tensor's bytes."""
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def _self_test() -> None:
    for config_name, cfg in [("small", MLAConfig.small()), ("v2_lite", MLAConfig.v2_lite())]:
        weights = init_weights(cfg, seed=42)
        cache = init_cache(cfg, seqlen=16, seed=43)
        x_q = init_query(cfg, batch=1, seed=44)

        out_nonabs = mla_decode_nonabsorbed(x_q, cache["c_kv"], cache["k_r"], weights, cfg)
        out_abs = mla_decode_absorbed(x_q, cache["c_kv"], cache["k_r"], weights, cfg)

        max_abs = float(np.abs(out_nonabs - out_abs).max())
        out_scale = float(np.abs(out_nonabs).max()) + 1e-9
        max_rel = max_abs / out_scale

        # FP32 ULP is ~1e-7; accumulated einsum error over matmul chains is
        # larger. 1e-4 relative is a conservative bound that both forms hit.
        assert max_rel < 1e-4, f"{config_name}: forms disagree rel={max_rel:.3e}"

        print(f"[{config_name}] d_model={cfg.d_model} n_heads={cfg.n_heads} d_c={cfg.d_c}")
        print(f"  shape:    {out_nonabs.shape}")
        print(f"  max_abs:  {max_abs:.3e}")
        print(f"  max_rel:  {max_rel:.3e}")
        print(f"  sha256:   {output_sha256(out_nonabs)}")


if __name__ == "__main__":
    _self_test()
