"""PyTorch CUDA port of the MLA decode reference.

Phase M / M6a (Hopper integration run). See docs/mla-oracle-roadmap.md.

Mirrors corpus/mla/reference/mla_decode_numpy.py bit-for-bit at FP32 and
additionally exposes bf16 / fp16 paths for native H100 (SM90) execution.
The oracle grades the reduced-precision output against the FP32
committed golden via the matching tolerance preset.

Weights are seeded identically to the numpy reference (np.random.default_rng
with the same seeds), so the same committed golden applies. Non-absorbed
form only — the absorbed/non-absorbed equivalence was cross-checked in M2.

Run (on H100 pod):
    python3 mla_decode_pytorch.py --dtype bf16 --config v2_lite --seqlen 16

Output (on stdout): one JSON object with
    {"bug_id": "GPU-HOPPER-RAIL-PROOF", "status": "triggered",
     "hardware": {"device_name": "NVIDIA H100 ...", "cuda_cc": [9, 0], ...},
     "dtype": "bf16", "output": [[float, ...]]}
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
    def v2_lite(cls):
        return cls()

    @classmethod
    def small(cls):
        return cls(d_model=256, n_heads=2, d_nope=64, d_rope=16, d_v=64, d_c=64)


def _init_weights_np(cfg, seed=42):
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


def _init_cache_np(cfg, seqlen, seed=43):
    rng = np.random.default_rng(seed)
    return {
        "c_kv": rng.normal(0, 1.0, (seqlen, cfg.d_c)).astype(np.float32),
        "k_r":  rng.normal(0, 1.0, (seqlen, cfg.d_rope)).astype(np.float32),
    }


def _init_query_np(cfg, batch=1, seed=44):
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1.0, (batch, cfg.d_model)).astype(np.float32)


def mla_decode_pytorch(x_q, c_kv, k_r, weights, cfg):
    """Torch non-absorbed MLA decode. All tensors must be on the same device + dtype."""
    import torch

    B = x_q.shape[0]
    S = c_kv.shape[0]

    q_nope = (x_q @ weights["W_Q_nope"]).reshape(B, cfg.n_heads, cfg.d_nope)
    q_rope = (x_q @ weights["W_Q_rope"]).reshape(B, cfg.n_heads, cfg.d_rope)

    k_nope = (c_kv @ weights["W_UK"]).reshape(S, cfg.n_heads, cfg.d_nope)

    scores_nope = torch.einsum("bhd,shd->bhs", q_nope, k_nope)
    scores_rope = torch.einsum("bhd,sd->bhs", q_rope, k_r)
    scale = 1.0 / (cfg.d_nope + cfg.d_rope) ** 0.5
    scores = (scores_nope + scores_rope) * scale
    attn = torch.softmax(scores, dim=-1)

    v = (c_kv @ weights["W_UV"]).reshape(S, cfg.n_heads, cfg.d_v)
    ctx = torch.einsum("bhs,shd->bhd", attn, v).reshape(B, cfg.n_heads * cfg.d_v)
    return ctx @ weights["W_O"]


def _emit(obj):
    json.dump(obj, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dtype", choices=["fp32", "bf16", "fp16"], default="bf16")
    p.add_argument("--config", choices=["small", "v2_lite"], default="v2_lite")
    p.add_argument("--seqlen", type=int, default=16)
    args = p.parse_args()

    try:
        import torch
    except ImportError as e:
        _emit({"bug_id": "GPU-HOPPER-RAIL-PROOF", "status": "error",
               "reason": f"torch not importable: {e}"})
        return 1

    if not torch.cuda.is_available():
        _emit({"bug_id": "GPU-HOPPER-RAIL-PROOF", "status": "deferred",
               "reason": "no CUDA device available"})
        return 0

    cc = torch.cuda.get_device_capability(0)
    device_name = torch.cuda.get_device_name(0)
    dtype_map = {"fp32": torch.float32, "bf16": torch.bfloat16, "fp16": torch.float16}
    torch_dtype = dtype_map[args.dtype]

    cfg = getattr(MLAConfig, args.config)()

    # FP32 numpy init (identical seeds to numpy + jax references).
    weights_np = _init_weights_np(cfg, seed=42)
    cache_np = _init_cache_np(cfg, seqlen=args.seqlen, seed=43)
    x_q_np = _init_query_np(cfg, batch=1, seed=44)

    device = torch.device("cuda:0")
    weights = {k: torch.from_numpy(v).to(device=device, dtype=torch_dtype) for k, v in weights_np.items()}
    c_kv = torch.from_numpy(cache_np["c_kv"]).to(device=device, dtype=torch_dtype)
    k_r = torch.from_numpy(cache_np["k_r"]).to(device=device, dtype=torch_dtype)
    x_q = torch.from_numpy(x_q_np).to(device=device, dtype=torch_dtype)

    with torch.no_grad():
        out = mla_decode_pytorch(x_q, c_kv, k_r, weights, cfg)

    # Upcast to FP32 then move to CPU for stdout emission.
    out_fp32 = out.to(dtype=torch.float32).cpu().numpy()

    _emit({
        "bug_id": "GPU-HOPPER-RAIL-PROOF",
        "status": "triggered",
        "hardware": {
            "device_name": device_name,
            "cuda_cc": list(cc),
            "cuda_version": torch.version.cuda,
            "torch_version": torch.__version__,
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
