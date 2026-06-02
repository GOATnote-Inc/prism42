"""Generate committed golden vectors for the MLA decode oracle.

Phase M (MLA decode oracle). See docs/mla-oracle-roadmap.md §3 M2.

Produces JSON files under corpus/mla/reference/golden_vectors/ that record
the seeded input + FP32 reference output for each (config, seqlen, seed)
tuple. These files are committed so the oracle (M3) can grade any
candidate kernel output against a stable, diffable reference without
recomputing the reference on the auditor's machine.

Output format (per config):
    {
        "config_name": "v2_lite" | "small",
        "config": {d_model, n_heads, d_nope, d_rope, d_v, d_c},
        "seeds": {weights_seed, cache_seed, query_seed},
        "seqlen": int,
        "shapes": {x_q, c_kv, k_r, out},
        "output_sha256": "...",
        "output": [[float, ...]]           # [B, d_model], FP32 values
    }

The input arrays are regenerable from the seeds + config — not stored
inline to keep files diffable. Weights likewise regenerate from seeds.

Run:
    .venv/bin/python3 corpus/mla/reference/generate_golden_vectors.py

Idempotent: writes overwrite deterministically given the same seeds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

import numpy as np

from mla_decode_numpy import (
    MLAConfig,
    init_cache,
    init_query,
    init_weights,
    mla_decode_nonabsorbed,
    output_sha256,
)


GOLDEN_DIR = Path(__file__).parent / "golden_vectors"


def _compute_golden(cfg: MLAConfig, *, seqlen: int, weights_seed: int, cache_seed: int, query_seed: int) -> Dict[str, Any]:
    weights = init_weights(cfg, seed=weights_seed)
    cache = init_cache(cfg, seqlen=seqlen, seed=cache_seed)
    x_q = init_query(cfg, batch=1, seed=query_seed)
    out = mla_decode_nonabsorbed(x_q, cache["c_kv"], cache["k_r"], weights, cfg)
    return {
        "config": {
            "d_model": cfg.d_model,
            "n_heads": cfg.n_heads,
            "d_nope": cfg.d_nope,
            "d_rope": cfg.d_rope,
            "d_v": cfg.d_v,
            "d_c": cfg.d_c,
        },
        "seeds": {
            "weights_seed": weights_seed,
            "cache_seed": cache_seed,
            "query_seed": query_seed,
        },
        "seqlen": seqlen,
        "shapes": {
            "x_q": list(x_q.shape),
            "c_kv": list(cache["c_kv"].shape),
            "k_r": list(cache["k_r"].shape),
            "out": list(out.shape),
        },
        "output_sha256": output_sha256(out),
        "output": out.astype(np.float32).tolist(),
    }


def main() -> None:
    GOLDEN_DIR.mkdir(exist_ok=True)

    targets = [
        ("small",   MLAConfig.small(),   {"seqlen": 16, "weights_seed": 42, "cache_seed": 43, "query_seed": 44}),
        ("v2_lite", MLAConfig.v2_lite(), {"seqlen": 16, "weights_seed": 42, "cache_seed": 43, "query_seed": 44}),
    ]

    for name, cfg, kwargs in targets:
        golden = {"config_name": name, **_compute_golden(cfg, **kwargs)}
        path = GOLDEN_DIR / f"{name}_decode_s{kwargs['seqlen']}_w{kwargs['weights_seed']}.json"
        with path.open("w") as fh:
            json.dump(golden, fh, indent=2)
        out_arr = np.asarray(golden["output"], dtype=np.float32)
        size_kb = path.stat().st_size / 1024
        print(f"wrote {path.name} ({size_kb:.1f} KB)  sha256={golden['output_sha256'][:16]}...  max|out|={float(np.abs(out_arr).max()):.3e}")


if __name__ == "__main__":
    main()
