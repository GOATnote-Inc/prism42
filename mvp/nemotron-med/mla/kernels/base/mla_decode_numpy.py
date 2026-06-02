"""Pure-numpy MLA decode reference.

Math: DeepSeek-V2 (arXiv 2405.04434) §2.1. A compressed latent c_KV of size
d_c carries the per-token KV state; per-head up-projections W_UK and W_UV
reconstruct full K and V at read time. A separate rope subspace (k_R, q_rope)
of size d_r is carried uncompressed because rotary embeddings don't commute
with low-rank compression.

Two reference forms live here:
    mla_decode_naive      — reconstruct K and V, then standard attention.
                            Slow per-token but unambiguous. Golden reference.
    mla_decode_absorbed   — W_UK folded into Q, W_UV folded into output.
                            Stays in compressed space. Fewer FLOPs / fewer
                            memory reads per KV token. Numerically equivalent
                            modulo float associativity.

The absorbed form is the first mutation target for the evolutionary loop.
All inputs are float32 arrays. Shapes follow DeepSeek convention:
    B = batch                    H = heads
    T = kv_len (cache length)    d_c = latent dim
    d_r = rope dim               qk_n = qk_nope_head_dim
    v_h = v_head_dim

Cross-refs:
    mla/mla-fp4-literature.md §1 (DeepSeek V2 math)
    cross-pollination/tcu-gpu-tpu-trainium-playbook.md §4.1-4.2 (absorption
        is the reason MLA moves less HBM than MHA decode)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MLAConfig:
    batch: int
    heads: int
    kv_len: int
    d_c: int          # latent compressed dim
    d_r: int          # rope dim
    qk_nope: int      # nope head dim (qk_nope_head_dim)
    v_head: int       # value head dim
    softmax_scale: float = 0.0  # 0.0 => 1/sqrt(qk_nope + d_r)

    @property
    def qk_head(self) -> int:
        return self.qk_nope + self.d_r

    @property
    def effective_scale(self) -> float:
        if self.softmax_scale != 0.0:
            return self.softmax_scale
        return 1.0 / np.sqrt(self.qk_head)


def make_inputs(cfg: MLAConfig, *, seed: int = 0, dtype=np.float32) -> dict[str, np.ndarray]:
    """Random inputs of the correct shape for a given config."""
    rng = np.random.default_rng(seed)

    def f(shape):
        return rng.standard_normal(shape).astype(dtype)

    # Per-head Q split into nope/rope halves.
    q_nope = f((cfg.batch, cfg.heads, cfg.qk_nope))
    q_rope = f((cfg.batch, cfg.heads, cfg.d_r))
    # Cache: c_KV is shared across heads; k_R is per-token, shared across heads.
    c_KV = f((cfg.batch, cfg.kv_len, cfg.d_c))
    k_R = f((cfg.batch, cfg.kv_len, cfg.d_r))
    # Per-head up-projections.
    W_UK = f((cfg.heads, cfg.qk_nope, cfg.d_c))
    W_UV = f((cfg.heads, cfg.d_c, cfg.v_head))
    return {
        "q_nope": q_nope, "q_rope": q_rope,
        "c_KV": c_KV, "k_R": k_R,
        "W_UK": W_UK, "W_UV": W_UV,
        "softmax_scale": cfg.effective_scale,
    }


def mla_decode_naive(
    q_nope: np.ndarray,
    q_rope: np.ndarray,
    c_KV: np.ndarray,
    k_R: np.ndarray,
    W_UK: np.ndarray,
    W_UV: np.ndarray,
    softmax_scale: float,
) -> np.ndarray:
    """Reconstruct full K and V, then run standard attention. Golden ref.

    Shapes:
        q_nope (B, H, qk_n); q_rope (B, H, d_r)
        c_KV   (B, T, d_c); k_R   (B, T, d_r)
        W_UK   (H, qk_n, d_c); W_UV (H, d_c, v_h)
        returns (B, H, v_h)
    """
    # K_nope[b, h, t, n] = sum_d c_KV[b, t, d] * W_UK[h, n, d]
    K_nope = np.einsum("btd,hnd->bhtn", c_KV, W_UK)
    B, T, d_r = k_R.shape
    H = q_nope.shape[1]
    # k_R is shared across heads — broadcast explicitly.
    K_rope = np.broadcast_to(k_R[:, None, :, :], (B, H, T, d_r))
    K_full = np.concatenate([K_nope, K_rope], axis=-1)           # (B, H, T, qk_head)
    Q_full = np.concatenate([q_nope, q_rope], axis=-1)           # (B, H, qk_head)

    scores = np.einsum("bhd,bhtd->bht", Q_full, K_full) * softmax_scale
    scores -= scores.max(axis=-1, keepdims=True)
    exp = np.exp(scores)
    w = exp / exp.sum(axis=-1, keepdims=True)                    # (B, H, T)

    # V[b, h, t, v] = sum_d c_KV[b, t, d] * W_UV[h, d, v]
    V = np.einsum("btd,hdv->bhtv", c_KV, W_UV)
    out = np.einsum("bht,bhtv->bhv", w, V)                       # (B, H, v_h)
    return out


def mla_decode_absorbed(
    q_nope: np.ndarray,
    q_rope: np.ndarray,
    c_KV: np.ndarray,
    k_R: np.ndarray,
    W_UK: np.ndarray,
    W_UV: np.ndarray,
    softmax_scale: float,
) -> np.ndarray:
    """Absorbed MLA decode. W_UK folds into Q, W_UV folds into output.

    Attention stays in compressed latent space: scores come from Q_merged ·
    c_KV instead of Q · K_full, and the weighted sum is computed in d_c
    before a single W_UV multiply per (B, H) instead of per (B, H, T).

    Numerically equivalent to mla_decode_naive modulo float associativity.
    """
    # q_merged[b, h, d] = sum_n q_nope[b, h, n] * W_UK[h, n, d]
    q_merged = np.einsum("bhn,hnd->bhd", q_nope, W_UK)          # (B, H, d_c)

    scores_nope = np.einsum("bhd,btd->bht", q_merged, c_KV)    # (B, H, T)
    # k_R shared across heads — einsum with broadcast over H.
    scores_rope = np.einsum("bhd,btd->bht", q_rope, k_R)       # (B, H, T)
    scores = (scores_nope + scores_rope) * softmax_scale

    scores -= scores.max(axis=-1, keepdims=True)
    exp = np.exp(scores)
    w = exp / exp.sum(axis=-1, keepdims=True)                   # (B, H, T)

    # ctx in compressed space — one reduction instead of per-t in v_h space.
    ctx = np.einsum("bht,btd->bhd", w, c_KV)                    # (B, H, d_c)
    out = np.einsum("bhd,hdv->bhv", ctx, W_UV)                  # (B, H, v_h)
    return out


# ---- FLOP / byte accounting for roofline analysis ----

def flops(cfg: MLAConfig, kernel: str = "absorbed") -> int:
    """Approximate FLOPs per decode step. Used for Carnot-efficiency scoring
    (see mental-models/einstein-first-principles.md §6)."""
    B, H, T, d_c, d_r, qn, vh = (
        cfg.batch, cfg.heads, cfg.kv_len, cfg.d_c, cfg.d_r, cfg.qk_nope, cfg.v_head
    )
    if kernel == "naive":
        # K_nope: B*H*T*qn*d_c MACs ; V: B*H*T*d_c*vh MACs
        # scores QK: B*H*T*(qn+d_r) MACs
        # ctx: B*H*T*vh MACs
        return 2 * (
            B * H * T * qn * d_c     # K_nope
            + B * H * T * d_c * vh   # V
            + B * H * T * (qn + d_r)  # scores
            + B * H * T * vh         # ctx
        )
    # absorbed
    return 2 * (
        B * H * qn * d_c            # q_merged
        + B * H * T * d_c            # scores_nope
        + B * H * T * d_r            # scores_rope
        + B * H * T * d_c            # ctx reduction
        + B * H * d_c * vh           # final W_UV
    )


def bytes_moved_from_cache(cfg: MLAConfig, kernel: str = "absorbed", *, dtype_bytes: int = 4) -> int:
    """HBM bytes read from KV cache per decode step. The key driver of MLA's
    decode-throughput advantage over MHA: absorbed MLA only reads c_KV and
    k_R, never the reconstructed full K/V."""
    B, T, d_c, d_r = cfg.batch, cfg.kv_len, cfg.d_c, cfg.d_r
    # Both forms read the same cache; the "naive" form above runs its
    # reconstruction from the same cache, so the HBM traffic is equal in
    # this numpy model. On hardware the gap opens when the naive form
    # materializes K/V to HBM; not modeled here.
    return B * T * (d_c + d_r) * dtype_bytes
