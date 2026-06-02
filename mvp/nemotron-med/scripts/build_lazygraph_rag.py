"""build_lazygraph_rag — build-time scaffold for the LazyGraphRAG-shaped
retrieval index, NVIDIA-primitive-aligned.

Status: SCAFFOLD. Authored 2026-04-29 alongside the graph-RAG rethink at
`findings/research/2026-04-29-graph-rag-rethink/synthesis.md`. The
heavy-lift steps (NV-Embed-v2 inference, cuGraph Leiden, cuVS index
build) require GPU + the OpenEM corpus on disk; today this script
documents the contract and runs a CPU-only smoke pass on the seed KG so
the v1 ship can pull-up cleanly when GPU time is available.

Pipeline (six stages):

  1. Load merged KG (data/seed_kg/expansions/openem_370.gpickle if
     present; else data/seed_kg/graph.gpickle).
  2. For each node, compose a textual representation: condition card
     synthesis (label + chief complaint + red_flags + decision_rules +
     ICD-10s + first 1-hop neighbors).
  3. Embed each node's text with NV-Embed-v2 (or Omni-Embed-Nemotron-3B
     once Omni is the inference target).
  4. Compute Leiden community partitions on the KG via cuGraph
     (nx-cugraph backend). At ~2K nodes this is tens of milliseconds on
     a GPU; community count is target ~10 medical clusters.
  5. Build a cuVS IVF-PQ index over the node embeddings. Persist to
     data/lazygraph/cuvs_index.bin alongside community labels and a
     companion JSON manifest with provenance hashes.
  6. Pre-compute 1-hop adjacency lists per node for fast in-VRAM
     subgraph slicing at query time.

Output (data/lazygraph/):
  manifest.json          — provenance: KG file + embedding model + seed
                           + Leiden resolution + cuVS index params
  embeddings.npy         — float16 [N, D] node embeddings
  communities.json       — {node_id: community_id} from Leiden
  adjacency.json         — {node_id: [neighbor_node_id, ...]}
  cuvs_index.bin         — cuVS IVF-PQ index (GPU-side artifact;
                           regenerated at startup if missing)

Usage:
    # CPU smoke (validates pipeline structure on seed_kg):
    python scripts/build_lazygraph_rag.py --smoke

    # Full GPU build (requires nx-cugraph, cuvs-cu13, NV-Embed-v2):
    python scripts/build_lazygraph_rag.py \\
        --kg data/seed_kg/expansions/openem_370.gpickle \\
        --embedding-model nvidia/NV-Embed-v2 \\
        --out data/lazygraph/

The script is double-gated for the GPU path: --commit on CLI AND
PRISM42_BUILD_LAZYGRAPH=1 in env. CPU smoke runs without gates.

Per the synthesis brief: graph-augmented dense retrieval is the right
shape for medical multi-hop. This file is the build half; runtime side
lives in mla/retrieval.py (GraphAugmentedRetriever, planned).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SEED_KG = REPO / "data" / "seed_kg" / "graph.gpickle"
EXPANDED_KG = REPO / "data" / "seed_kg" / "expansions" / "openem_370.gpickle"
OUT_DIR = REPO / "data" / "lazygraph"


def _load_graph(path: Path) -> Any:
    try:
        import networkx as _nx  # noqa: F401, PLC0415
    except ImportError as exc:
        raise SystemExit("networkx required: pip install networkx") from exc
    if not path.exists():
        raise SystemExit(f"KG not found at {path}")
    with path.open("rb") as f:
        return pickle.load(f)


def _node_text(g: Any, node_id: str) -> str:
    """Compose the text representation we'll embed for this node."""
    attrs = g.nodes[node_id]
    parts: list[str] = [str(attrs.get("label", node_id))]
    if attrs.get("chief_complaint"):
        parts.append(f"Chief complaint: {attrs['chief_complaint']}")
    if attrs.get("category"):
        parts.append(f"Category: {attrs['category']}")
    if attrs.get("esi"):
        parts.append(f"ESI: {attrs['esi']}")
    if attrs.get("risk_tier"):
        parts.append(f"Risk tier: {attrs['risk_tier']}")
    # 1-hop neighbors that are red-flags / ICD-10s / decision rules.
    rf, icd, rule = [], [], []
    for _, target, edata in g.out_edges(node_id, data=True):
        kind = edata.get("kind", "")
        label = g.nodes[target].get("label", target)
        if kind == "condition_to_red_flag":
            rf.append(label)
        elif kind == "condition_to_icd10":
            icd.append(label)
        elif kind == "condition_to_decision_rule":
            rule.append(label)
    if rf:
        parts.append("Red flags: " + "; ".join(rf[:8]))
    if icd:
        parts.append("ICD-10: " + ", ".join(icd[:8]))
    if rule:
        parts.append("Decision rules: " + "; ".join(rule[:5]))
    return " | ".join(parts)


def _smoke_pipeline(g: Any, out_dir: Path) -> dict[str, Any]:
    """CPU-only smoke: stages 1, 2, 4 (without GPU), 6. Skips embedding
    (stage 3) and cuVS index (stage 5). Validates that the rest of the
    pipeline plumbing is wired."""
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = list(g.nodes())
    print(f"[smoke] node count: {len(nodes)}")
    # Stage 2 — node text composition
    texts = {n: _node_text(g, n) for n in nodes[:25]}  # sample for smoke
    print(f"[smoke] sample node texts (first 3):")
    for n, t in list(texts.items())[:3]:
        print(f"  {n[:40]:40s}  {t[:120]}{'...' if len(t) > 120 else ''}")
    # Stage 4 — Leiden via networkx fallback (community.greedy_modularity)
    try:
        import networkx as nx  # noqa: PLC0415
        from networkx.algorithms.community import greedy_modularity_communities  # noqa: PLC0415
        undirected = g.to_undirected() if g.is_directed() else g
        comms = list(greedy_modularity_communities(undirected))
        community_labels = {n: i for i, c in enumerate(comms) for n in c}
        print(f"[smoke] greedy-modularity communities: {len(comms)} (CPU fallback for Leiden)")
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] community pass skipped: {exc}")
        community_labels = {n: 0 for n in nodes}
    # Stage 6 — adjacency
    adjacency = {n: [t for _, t in g.out_edges(n)] for n in nodes}
    # Persist a smoke manifest so the runtime can detect "smoke-only" state.
    manifest = {
        "smoke": True,
        "node_count": len(nodes),
        "community_count": len(set(community_labels.values())),
        "embeddings_present": False,
        "cuvs_index_present": False,
        "kg_sha256": hashlib.sha256(repr(sorted(g.nodes())).encode()).hexdigest()[:16],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out_dir / "communities.json").write_text(json.dumps(community_labels, indent=2))
    (out_dir / "adjacency.json").write_text(json.dumps(adjacency, indent=2))
    return manifest


def _full_build(g: Any, embedding_model: str, out_dir: Path) -> int:
    """Full GPU build — stub. Implementation lands when GPU time is
    available and dependencies (nx-cugraph, cuvs-cu13, sentence-transformers
    with NV-Embed-v2 weights) are installed on the target pod.
    """
    print("[full-build] not yet implemented; would do:")
    print(f"  - load embedding model: {embedding_model}")
    print(f"  - embed {g.number_of_nodes()} nodes (batch of 64, fp16)")
    print(f"  - compute Leiden communities via cugraph (nx-cugraph backend)")
    print(f"  - build cuVS IVF-PQ index over embeddings, persist to {out_dir}/cuvs_index.bin")
    print(f"  - persist manifest.json with provenance + cuVS params + Leiden resolution")
    print()
    print("To implement: see findings/research/2026-04-29-graph-rag-rethink/synthesis.md")
    print("for the architecture; cite the cuVS optimization blog and nx-cugraph docs")
    print("listed there for primitive APIs.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg", help="path to .gpickle KG (default: expansion if present, else seed)")
    parser.add_argument("--smoke", action="store_true", help="CPU-only pipeline smoke")
    parser.add_argument("--embedding-model", default="nvidia/NV-Embed-v2")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--commit", action="store_true", help="full GPU build (with PRISM42_BUILD_LAZYGRAPH=1)")
    args = parser.parse_args()

    kg_path = Path(args.kg) if args.kg else (EXPANDED_KG if EXPANDED_KG.exists() else SEED_KG)
    g = _load_graph(kg_path)
    out_dir = Path(args.out).resolve()
    print(f"loaded KG: {kg_path} ({g.number_of_nodes()} nodes, {g.number_of_edges()} edges)")

    if args.smoke:
        manifest = _smoke_pipeline(g, out_dir)
        print(f"[smoke] wrote {out_dir}/manifest.json (smoke=True)")
        return 0

    if not args.commit or os.environ.get("PRISM42_BUILD_LAZYGRAPH") != "1":
        print("DRY RUN — full GPU build is double-gated.")
        print("  --commit on CLI AND PRISM42_BUILD_LAZYGRAPH=1 in env.")
        print("Use --smoke for the CPU pipeline check.")
        return 0

    return _full_build(g, args.embedding_model, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
