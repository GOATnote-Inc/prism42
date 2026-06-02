"""Torch-backed MLA decode reference at DeepSeek dims.

Mirrors kernels/base/mla_decode_numpy.py but operates on torch GPU tensors
in the absorbed form that FlashInfer consumes:

    q_nope: (B, H, d_ckv)   -- W_UK already merged into Q
    q_pe:   (B, H, d_pe)    -- rope queries
    ckv:    (B, T, d_ckv)   -- dense compressed-KV cache
    kpe:    (B, T, d_pe)    -- dense rope-K cache
    out:    (B, H, d_ckv)   -- attention output in compressed space

DeepSeek-V2/V3 dims are the defaults:
    H=128, d_ckv=512, d_pe=64, total qk_head=576

This module is the canonical *reference* the torch-evolve candidates are
validated against. It is mathematically equivalent to flashinfer's output
modulo float-precision reduction order; the validator uses a 5e-2 bf16
tolerance as flashinfer does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch


@dataclass(frozen=True)
class TorchMLAConfig:
    batch: int = 1
    heads: int = 128
    kv_len: int = 1024
    d_ckv: int = 512
    d_pe: int = 64
    dtype: str = "bfloat16"   # "bfloat16" | "float16" | "float32"
    device: str = "cuda"
    sm_scale: float = 0.0     # 0 => 1/sqrt(d_ckv + d_pe)

    @property
    def effective_sm_scale(self) -> float:
        if self.sm_scale != 0.0:
            return float(self.sm_scale)
        import math
        return 1.0 / math.sqrt(self.d_ckv + self.d_pe)


def _torch_dtype(name: str):
    d = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}
    return d[name]


def make_torch_inputs(cfg: TorchMLAConfig, *, seed: int = 0) -> dict[str, Any]:
    device = torch.device(cfg.device)
    gen = torch.Generator(device=device).manual_seed(seed)
    dt = _torch_dtype(cfg.dtype)
    q_nope = torch.randn(cfg.batch, cfg.heads, cfg.d_ckv, dtype=torch.float32, generator=gen, device=device).to(dt)
    q_pe   = torch.randn(cfg.batch, cfg.heads, cfg.d_pe,  dtype=torch.float32, generator=gen, device=device).to(dt)
    ckv    = torch.randn(cfg.batch, cfg.kv_len, cfg.d_ckv, dtype=torch.float32, generator=gen, device=device).to(dt)
    kpe    = torch.randn(cfg.batch, cfg.kv_len, cfg.d_pe,  dtype=torch.float32, generator=gen, device=device).to(dt)
    return {"q_nope": q_nope, "q_pe": q_pe, "ckv": ckv, "kpe": kpe,
            "sm_scale": cfg.effective_sm_scale}


def mla_decode_torch_reference(q_nope, q_pe, ckv, kpe, sm_scale):
    """Stable reference. Float32 on GPU. Matches the torch ref in
    runner/flashinfer_runner.torch_mla_decode_absorbed.

    Promotes inputs to float32 before the reduction so the comparison
    against bf16 candidates is honest (bf16 ref would inherit bf16 noise
    and mask candidate errors of that magnitude)."""
    q_nope_f = q_nope.float()
    q_pe_f   = q_pe.float()
    ckv_f    = ckv.float()
    kpe_f    = kpe.float()
    scores = (
        torch.einsum("bhd,btd->bht", q_nope_f, ckv_f)
        + torch.einsum("bhd,btd->bht", q_pe_f, kpe_f)
    ) * float(sm_scale)
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    out = torch.einsum("bht,btd->bhd", w, ckv_f)
    return out  # (B, H, d_ckv), float32
