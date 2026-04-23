"""Runnable evolve demo with the offline stub client.

End-to-end proof that the loop survives all six failure modes it can hit:
    compile failure, unsafe source, validator rejection, duplicate hash,
    stability regression, nothing-improves-over-baseline.

On a real host with PRISM_USE_ANTHROPIC=1 the same script calls Claude.

Usage:
    .venv/bin/python loop/evolve_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_client import make_default_client  # noqa: E402
from kernels.base.mla_decode_numpy import MLAConfig, mla_decode_absorbed  # noqa: E402
from loop.evolve import EvolveConfig, evolve  # noqa: E402


def main() -> int:
    import os
    cfg = EvolveConfig(
        mla=MLAConfig(batch=2, heads=8, kv_len=256, d_c=64, d_r=16, qk_nope=32, v_head=32),
        iterations=3,
        per_island=3,
        keep_per_island=2,
        migrate_every=2,
        tolerance=1e-3,
        seed=0,
        run_critique=os.environ.get("PRISM_CRITIQUE", "1") != "0",
        pareto_keep=os.environ.get("PRISM_PARETO", "1") != "0",
        critique_linear_topk=2,
    )
    client = make_default_client()
    log = Path(__file__).resolve().parent.parent / "results" / "logs" / "evolve.json"

    print(f"[client]  {type(client).__name__}")
    print(f"[flags]   critique={cfg.run_critique}  pareto={cfg.pareto_keep}")
    print(f"[config]  {cfg.mla}")
    summary = evolve(client, mla_decode_absorbed, cfg, log_path=log)

    print("\n[history]")
    for it in summary["history"]:
        print(f"  iter {it['iteration']}  wall={it['wall_s']:.2f}s")
        for isl in it["islands"]:
            cf = len(isl["compile_failures"])
            vf = len(isl["validator_failures"])
            cr = isl.get("critiques", [])
            pr = isl.get("pareto_retained", [])
            extra = ""
            if cr:
                rejs = sum(1 for c in cr if c["recommendation"] == "reject")
                extra += f"  critique_accept={len(cr) - rejs}  reject={rejs}"
            if pr:
                extra += f"  pareto_kept={len(pr)}"
            print(f"    island={isl['name']:<8s}  top={isl['top_score']:,.1f}  "
                  f"proposed={isl['proposed']:<2d}  compile_fail={cf}  val_fail={vf}{extra}")
        if it["migrations"]:
            for m in it["migrations"]:
                print(f"    migrate {m['from']}->{m['to']}  hash={m['hash']}  score={m['score']:,.1f}")

    best = summary["best"]
    print("\n[best]")
    print(f"  island   = {best['island']}")
    print(f"  hash     = {best['hash']}")
    print(f"  score    = {best['score']:,.2f}")
    print(f"  tokens/s = {best['tokens_per_sec']:,.0f}")
    print(f"  median   = {best['median_ns']:,.0f} ns")
    print(f"  stability= {best['stability']:.3f}")
    if best["reasoning"]:
        print(f"  reasoning:\n    " + "\n    ".join(best["reasoning"].splitlines()[:4]))
    print(f"\n[log] {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
