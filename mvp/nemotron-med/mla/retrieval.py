"""mla.retrieval — sovereign medical-context retrieval.

ARCHITECTURE NOTE (revised 2026-04-28 after Nemotron-3-Nano-Omni release):

The original R2 plan was query -> embedding -> top-k -> 2-hop graph
expansion. Per the engineering brief at
`findings/research/2026-04-28-nemotron-omni/engineering-decisions.md`,
that plan is REVISED for the Omni inference target:

  - At our scale (OpenEM 370 conditions / ~2K KG nodes), graph-walks do
    not outperform dense retrieval (GraphRAG analysis, arXiv:2506.05690).
  - Omni's 256K context window lets us inline ~50K tokens of relevant
    medical content directly. Top-50 condition cards via NV-Embed-v2 +
    FAISS, no graph walk required.
  - Mamba2 long-context degradation is state-saturation (not "lost in
    the middle"); place high-priority chunks at the START AND END of
    the context window. See `_format_for_long_context` in mla/preamble.py
    (R2 todo).

Three implementations exist or are planned:

  - `KeywordRetriever`   zero-dep CPU fallback. Exact-match aliases +
                         ICD-10 + label substring search. Tonight's R1
                         test path; not load-bearing for Omni.

  - `EmbeddingRetriever` NV-Embed-v2 + FAISS over the OpenEM 370 corpus.
                         R2 v1 target: top-10 inlined into 32K context.
                         R2 v2 target: top-50 inlined into ~50K of Omni's
                         256K context. Stub today.

  - `MultimodalRetriever` (R2 v3 deferred) image retrieval via BiomedCLIP
                         or NeMo Embed VL for ECG/chest-X-ray when the
                         prompt mentions them. Requires Omni's vision
                         encoder; not relevant to text-only HealthBench.

The originally-planned 2-hop graph expansion is documented in
`KGNode.differentials` for completeness but the runtime path no longer
calls graph traversal; condition cards include their own differential
list inline via the retrieved-card formatting.

Both retrievers return a list of `KGNode` dicts ordered by relevance
score, with the originating node's neighborhood (red flags, ICD-10
codes, decision rules) for inline prompt formatting in mla/preamble.py.
"""

from __future__ import annotations

import os
import pickle
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

REPO = Path(__file__).resolve().parent.parent
KG_PATH = REPO / "data" / "seed_kg" / "expansions" / "openem_370.gpickle"
SEED_KG_PATH = REPO / "data" / "seed_kg" / "graph.gpickle"


@dataclass
class KGNode:
    """A single retrieval hit with its 2-hop neighborhood."""

    node_id: str
    label: str
    kind: str
    score: float
    red_flags: list[str]
    icd10_codes: list[str]
    decision_rules: list[str]
    differentials: list[str]


class Retriever(Protocol):
    def retrieve(self, query: str, *, k: int = 5) -> list[KGNode]: ...


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------
def load_graph(path: Path | None = None) -> Any:
    """Load the merged KG; falls back to seed if expansion absent."""
    try:
        import networkx as _nx  # noqa: F401, PLC0415
    except ImportError as exc:
        raise SystemExit("networkx required: pip install networkx") from exc

    target = path or (KG_PATH if KG_PATH.exists() else SEED_KG_PATH)
    if not target.exists():
        raise SystemExit(
            f"KG not found at {target}. Run scripts/expand_kg_with_openem.py first."
        )
    with target.open("rb") as f:
        return pickle.load(f)


def neighborhood(g: Any, node_id: str) -> dict[str, list[str]]:
    """Return the 1-hop neighborhood of node_id, grouped by edge kind."""
    bins: dict[str, list[str]] = {
        "red_flags": [],
        "icd10_codes": [],
        "decision_rules": [],
        "differentials": [],
    }
    if node_id not in g:
        return bins
    for _, target, edata in g.out_edges(node_id, data=True):
        kind = edata.get("kind", "")
        label = g.nodes[target].get("label", target)
        if kind == "condition_to_red_flag":
            bins["red_flags"].append(label)
        elif kind == "condition_to_icd10":
            bins["icd10_codes"].append(label)
        elif kind == "condition_to_decision_rule":
            bins["decision_rules"].append(label)
        elif kind == "condition_to_differential":
            bins["differentials"].append(label)
    return bins


def _to_kgnode(g: Any, node_id: str, score: float) -> KGNode:
    attrs = g.nodes[node_id]
    n = neighborhood(g, node_id)
    return KGNode(
        node_id=node_id,
        label=attrs.get("label", node_id),
        kind=attrs.get("kind", "unknown"),
        score=score,
        red_flags=n["red_flags"],
        icd10_codes=n["icd10_codes"],
        decision_rules=n["decision_rules"],
        differentials=n["differentials"],
    )


# ---------------------------------------------------------------------------
# Keyword retriever — zero-dep fallback
# ---------------------------------------------------------------------------
class KeywordRetriever:
    """Exact-match aliases + ICD-10 + label substring search.

    No external models. Suitable for tests and the R2 fallback path when
    the embedding stack is unavailable.
    """

    def __init__(self, graph: Any | None = None) -> None:
        self.g = graph if graph is not None else load_graph()

    def retrieve(self, query: str, *, k: int = 5) -> list[KGNode]:
        q_lower = query.lower()
        scored: list[tuple[float, str]] = []

        try:
            import networkx as nx  # noqa: PLC0415, F401
        except ImportError:
            return []

        for node_id, attrs in self.g.nodes(data=True):
            kind = attrs.get("kind", "")
            if kind not in ("condition", "icd10"):
                continue
            label = str(attrs.get("label", "")).lower()
            score = 0.0
            if label and label in q_lower:
                score += 2.0
            for tok in q_lower.split():
                if tok and tok in label:
                    score += 0.2
            if score > 0:
                scored.append((score, node_id))

        scored.sort(reverse=True)
        return [_to_kgnode(self.g, nid, s) for s, nid in scored[:k]]


# ---------------------------------------------------------------------------
# Embedding retriever — placeholder
# ---------------------------------------------------------------------------
class EmbeddingRetriever:
    """NV-Embed-v2 + FAISS retrieval.

    Requires:
      - `sentence-transformers` (pip install sentence-transformers)
      - `faiss` (pip install faiss-cpu OR faiss-gpu)
      - a built index at data/embeddings/openem_nv_embed_v2.faiss
        produced by `scripts/build_nv_embed_index.py` (R2 todo)

    Tonight's R1 does not exercise this path. The class is here to
    document the contract so future-me can swap implementations cleanly.
    """

    DEFAULT_MODEL = "nvidia/NV-Embed-v2"
    DEFAULT_INDEX = REPO / "data" / "embeddings" / "openem_nv_embed_v2.faiss"

    def __init__(
        self,
        graph: Any | None = None,
        *,
        model_name: str = DEFAULT_MODEL,
        index_path: Path | None = None,
    ) -> None:
        self.g = graph if graph is not None else load_graph()
        self.model_name = model_name
        self.index_path = index_path or self.DEFAULT_INDEX
        self._model: Any | None = None
        self._index: Any | None = None
        self._node_ids: list[str] = []

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            import faiss  # noqa: PLC0415, F401
        except ImportError as exc:
            raise SystemExit(
                "EmbeddingRetriever requires sentence-transformers + faiss. "
                "See scripts/build_nv_embed_index.py for R2 setup."
            ) from exc
        if not self.index_path.exists():
            raise SystemExit(
                f"FAISS index not found at {self.index_path}. "
                "Build it via scripts/build_nv_embed_index.py (R2 todo)."
            )
        # Concrete loading deferred — implemented when R2 lands.
        raise NotImplementedError("EmbeddingRetriever is R2 scaffold")

    def retrieve(self, query: str, *, k: int = 5) -> list[KGNode]:
        self._ensure_loaded()
        return []  # unreachable; raises in _ensure_loaded


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def make_retriever(*, mode: str | None = None) -> Retriever:
    """Factory honoring PRISM42_RETRIEVAL_MODE env var.

    mode in {keyword, embedding}; default = keyword (R1-safe).
    """
    selected = (mode or os.environ.get("PRISM42_RETRIEVAL_MODE", "keyword")).lower()
    if selected == "keyword":
        return KeywordRetriever()
    if selected == "embedding":
        return EmbeddingRetriever()
    raise ValueError(f"unknown retrieval mode: {selected}")


def retrieve_medical_context(
    query: str, *, k: int = 5, retriever: Retriever | None = None
) -> list[KGNode]:
    """One-shot helper used by the bench / harness."""
    r = retriever if retriever is not None else make_retriever()
    return r.retrieve(query, k=k)
