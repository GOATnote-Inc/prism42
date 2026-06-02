"""Local driver: call Claude N times to generate torch MLA mutations.

Reads parent kernel source from agent/torch_stub_mutations.py (baseline_bf16),
asks Claude to mutate it toward a specific objective, safety-checks each
response via compile_candidate_torch, and writes a JSON payload to
/tmp/claude_torch_mutations.json for the pod-side evaluator.

API key must already be sourced (ANTHROPIC_API_KEY in env). Nothing goes to
the network except the Claude calls. No GPU needed here.

Usage:
    set -a && source /Users/kiteboard/lostbench/.env && set +a && \\
    .venv/bin/python scripts/claude_torch_mutate.py
"""
from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_client import AnthropicClient, MutationRequest
# Do NOT import torch_stub_mutations here — that imports torch, which may
# be absent on the Claude-calling host. We parse baseline_bf16's source via
# AST below. Safety validation (compile_candidate_torch) is deferred to the
# pod-side evaluator where torch is guaranteed present.


# Objectives designed to cover different parts of the mutation surface.
OBJECTIVES = [
    "Dispatch into F.scaled_dot_product_attention correctly so torch picks its H100-optimized backend (cuDNN/Flash). Be precise about shapes, causal=False, and the scale argument.",
    "Replace both einsums with torch.bmm after reshaping Q and K to (B*H, 1, D) layouts; aim to reduce kernel launch count.",
    "Fuse the softmax stabilization (subtract-max + exp + divide) into a single torch.softmax call and minimize temporary allocations; consider in-place where safe.",
    "Restructure to be torch.compile-friendly: all shapes fixed, no Python conditionals on runtime tensor values, prefer contiguous strides.",
    "Use torch.matmul with explicit unsqueeze/squeeze at dim=-2 so the BMM planner can pick a tensor-core-friendly tile; avoid einsum entirely.",
]


def get_parent_source(parent_fn_name: str = "_baseline_bf16") -> str:
    """Return the source of baseline_bf16 by parsing torch_stub_mutations.py
    via AST — avoids importing torch on the Claude-calling host."""
    src_path = Path(__file__).resolve().parent.parent / "agent" / "torch_stub_mutations.py"
    tree = ast.parse(src_path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == parent_fn_name:
            return ast.get_source_segment(src_path.read_text(), node) or ""
    raise RuntimeError(f"could not find {parent_fn_name!r} in {src_path}")


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not in env; source the canonical .env first", file=sys.stderr)
        return 1

    parent_src = get_parent_source()
    print(f"[parent] baseline_bf16, {len(parent_src)} chars")
    print(f"[client] AnthropicClient (claude-opus-4-7)")
    client = AnthropicClient(allow_real_calls=True)

    records: list[dict] = []
    total_t0 = time.perf_counter()
    for i, objective in enumerate(OBJECTIVES, 1):
        print(f"\n[{i}/{len(OBJECTIVES)}] objective: {objective[:80]}...")
        req = MutationRequest(
            current_best_source=parent_src,
            population_summary=(
                "Parent: baseline_bf16 with torch.compile(max-autotune-no-cg) = 68.5 µs median. "
                "FlashInfer ceiling at same dims = 52.3 µs."
            ),
            mutation_objective=objective,
        )
        t0 = time.perf_counter()
        try:
            resp = client.mutate_torch(req)
            wall = time.perf_counter() - t0
        except Exception as e:
            print(f"  LLM call failed: {type(e).__name__}: {e}")
            records.append({
                "index": i, "objective": objective,
                "error": f"{type(e).__name__}: {e}",
                "wall_s": time.perf_counter() - t0,
            })
            continue

        # Safety token check locally (lightweight — no torch required).
        # The pod-side evaluator runs compile_candidate_torch with real torch.
        from agent.safety import scan_tokens, scan_ast, _BANNED_TORCH_TOKENS
        bad_tokens = scan_tokens(resp.source)
        bad_torch = [t for t in _BANNED_TORCH_TOKENS if t in resp.source]
        try:
            bad_ast = scan_ast(resp.source)
        except Exception as e:
            bad_ast = [f"parse_error:{type(e).__name__}:{e}"]
        compile_ok = not (bad_tokens or bad_torch or bad_ast)
        compile_err = None
        if not compile_ok:
            compile_err = f"banned_tokens={bad_tokens} banned_torch={bad_torch} banned_ast={bad_ast}"

        print(f"  wall={wall:.1f}s  src_len={len(resp.source)}  safety_ok={compile_ok}"
              + (f"  err={compile_err}" if compile_err else ""))
        print(f"  reasoning[:200]: {resp.reasoning[:200]!r}")
        records.append({
            "index": i, "objective": objective,
            "wall_s": wall, "reasoning": resp.reasoning,
            "source": resp.source, "raw": resp.raw,
            "compile_ok": compile_ok, "compile_error": compile_err,
        })

    out = Path("/tmp/claude_torch_mutations.json")
    out.write_text(json.dumps({
        "parent_name": "baseline_bf16",
        "parent_source": parent_src,
        "records": records,
        "total_wall_s": time.perf_counter() - total_t0,
    }, indent=2))
    n_ok = sum(1 for r in records if r.get("compile_ok"))
    print(f"\n[done] {n_ok}/{len(records)} compile-clean; total wall {time.perf_counter() - total_t0:.1f}s")
    print(f"[log] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
