"""Canned torch-backed MLA candidate functions.

Each candidate is a standalone callable with signature
    (q_nope, q_pe, ckv, kpe, sm_scale) -> torch.Tensor

matching `kernels.base.mla_decode_torch.mla_decode_torch_reference`. Used
by loop/evolve_torch.py as the offline analogue of agent.llm_client.StubClient
before we layer a real Claude mutation round on top.

All candidates assume inputs may be bf16/fp16/float32; they internally
cast to the input dtype or stay in float32 at the caller's discretion.
The reference promotes to float32; these candidates stay in the input dtype
for speed — accepting the bf16 error budget established at 5e-2.

Four "honest" variants + one negative control.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import torch
import torch.nn.functional as F


@dataclass
class TorchCandidate:
    name: str
    fn: Callable
    reasoning: str


def _baseline_bf16(q_nope, q_pe, ckv, kpe, sm_scale):
    """Straight bf16/fp16 path — no float32 promotion. The evolve loop's
    'baseline' candidate; all others are mutations of this."""
    scores_n = torch.einsum("bhd,btd->bht", q_nope, ckv)
    scores_p = torch.einsum("bhd,btd->bht", q_pe, kpe)
    scores = (scores_n + scores_p) * sm_scale
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    return torch.einsum("bht,btd->bhd", w, ckv)


def _fused_concat(q_nope, q_pe, ckv, kpe, sm_scale):
    """Concatenate q_nope || q_pe and ckv || kpe, then one einsum for scores.
    Saves one reduction launch + one add kernel; ckv for output stays separate."""
    q_cat = torch.cat([q_nope, q_pe], dim=-1)
    k_cat = torch.cat([ckv, kpe], dim=-1)
    scores = torch.einsum("bhd,btd->bht", q_cat, k_cat) * sm_scale
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    return torch.einsum("bht,btd->bhd", w, ckv)


def _scale_folded(q_nope, q_pe, ckv, kpe, sm_scale):
    """Fold softmax scale into Q at materialization; saves one broadcast mul."""
    qn = q_nope * sm_scale
    qp = q_pe * sm_scale
    scores = torch.einsum("bhd,btd->bht", qn, ckv) + torch.einsum("bhd,btd->bht", qp, kpe)
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    return torch.einsum("bht,btd->bhd", w, ckv)


def _sdpa_wrap(q_nope, q_pe, ckv, kpe, sm_scale):
    """Wrap torch.nn.functional.scaled_dot_product_attention. SDPA on H100
    uses cuDNN / Flash / memory-efficient backends under the hood, so this
    is likely the fastest non-FlashInfer option."""
    # SDPA expects (B, H, S_q, D) for Q and (B, H, S_kv, D) for K, V.
    # Build concatenated Q/K from absorbed form; V is ckv replicated across heads.
    B, H, D_ckv = q_nope.shape
    D_pe = q_pe.shape[-1]
    T = ckv.shape[1]
    q_cat = torch.cat([q_nope, q_pe], dim=-1).unsqueeze(2)             # (B, H, 1, D_ckv+D_pe)
    k_cat = torch.cat([ckv, kpe], dim=-1).unsqueeze(1).expand(B, H, T, D_ckv + D_pe)
    v     = ckv.unsqueeze(1).expand(B, H, T, D_ckv)
    # SDPA applies its own 1/sqrt(d_k) scale by default; override with ours.
    out = F.scaled_dot_product_attention(
        q_cat, k_cat, v, attn_mask=None, dropout_p=0.0,
        is_causal=False, scale=sm_scale,
    )
    return out.squeeze(2)  # (B, H, D_ckv)


def _chunked_kv(q_nope, q_pe, ckv, kpe, sm_scale):
    """Tile the KV axis and run the softmax via online reduction across
    chunks. Good cache locality for long kv_len; extra overhead for short."""
    B, H, _ = q_nope.shape
    T = ckv.shape[1]
    chunk = 256 if T > 256 else T
    d_ckv = ckv.shape[-1]

    # Running max, running sum, running output.
    m = torch.full((B, H), -float("inf"), dtype=torch.float32, device=q_nope.device)
    l = torch.zeros((B, H), dtype=torch.float32, device=q_nope.device)
    o = torch.zeros((B, H, d_ckv), dtype=torch.float32, device=q_nope.device)

    for start in range(0, T, chunk):
        end = min(start + chunk, T)
        ckv_c = ckv[:, start:end]
        kpe_c = kpe[:, start:end]
        s_n = torch.einsum("bhd,btd->bht", q_nope, ckv_c)
        s_p = torch.einsum("bhd,btd->bht", q_pe, kpe_c)
        s = (s_n + s_p).float() * float(sm_scale)   # (B, H, chunk)
        m_new_chunk = s.amax(dim=-1)                # (B, H)
        m_new = torch.maximum(m, m_new_chunk)
        exp_old = torch.exp(m - m_new)              # (B, H)
        exp_s   = torch.exp(s - m_new.unsqueeze(-1)) # (B, H, chunk)
        l = l * exp_old + exp_s.sum(dim=-1)
        o = o * exp_old.unsqueeze(-1) + torch.einsum("bht,btd->bhd", exp_s, ckv_c.float())
        m = m_new
    return (o / l.unsqueeze(-1)).to(q_nope.dtype)


def _negative_control_drops_rope(q_nope, q_pe, ckv, kpe, sm_scale):
    """INTENTIONAL BUG — drops the rope contribution. Validator must catch."""
    scores = torch.einsum("bhd,btd->bht", q_nope, ckv) * sm_scale
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    return torch.einsum("bht,btd->bhd", w, ckv)


TORCH_CANDIDATES: list[TorchCandidate] = [
    TorchCandidate(
        name="baseline_bf16",
        fn=_baseline_bf16,
        reasoning="Straight path, single dtype — reference shape",
    ),
    TorchCandidate(
        name="fused_concat",
        fn=_fused_concat,
        reasoning="Concatenate Q and K halves; single einsum replaces add of two",
    ),
    TorchCandidate(
        name="scale_folded",
        fn=_scale_folded,
        reasoning="Fold sm_scale into Q materialization; one fewer broadcast",
    ),
    TorchCandidate(
        name="sdpa_wrap",
        fn=_sdpa_wrap,
        reasoning="Delegate to torch SDPA — picks cuDNN/Flash under the hood",
    ),
    TorchCandidate(
        name="chunked_kv",
        fn=_chunked_kv,
        reasoning="Online softmax over KV chunks; cache-friendly for long kv_len",
    ),
    TorchCandidate(
        name="neg_ctl_drops_rope",
        fn=_negative_control_drops_rope,
        reasoning="[BUG] drops rope path — validator must reject",
    ),
]
