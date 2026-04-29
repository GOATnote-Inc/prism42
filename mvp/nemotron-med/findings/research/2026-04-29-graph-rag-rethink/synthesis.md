# Graph-RAG rethink — reversing yesterday's "skip graph" call

**Date**: 2026-04-29.
**Trigger**: user (Brandon Dent, MD) pushed back on yesterday's `engineering-decisions.md` Decision 2 ("skip graph-RAG at 2K nodes"). Three parallel research agents (Reddit/papers/empirical evidence • NVIDIA's official guidance • GPU-native OODA-fast architecture) returned. The agents partially disagree — useful information.
**Disposition**: yesterday's Decision 2 is REVERSED. New direction: **graph-augmented dense retrieval, LazyGraphRAG-shaped**. Yesterday's `engineering-decisions.md` should be read as superseded for the retrieval architecture only; Decisions 1 (vLLM flags) and 3 (expert routing) still stand.

## What changed my mind

Three pieces of evidence I didn't weigh correctly yesterday:

1. **The "10K-node threshold" came from a paper whose evaluation was biased.** [arXiv:2506.06331](https://arxiv.org/html/2506.06331v1) (June 2026) audited prior GraphRAG benchmarks and found win-rates inflated ~30% by evaluation bias. After correction, "performance advantages of GraphRAG over NaiveRAG generally improve with dataset size" — which means small datasets are hit *harder* by graph-RAG's overhead, but the threshold is a continuum, not a cliff. **I treated the 10K number as load-bearing when it was overstated.**

2. **Microsoft LazyGraphRAG ([blog, June 2025](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/))** publishes indexing cost at **0.1 % of full GraphRAG** — basically vector-RAG cost — while outperforming all competitors on local AND global queries on a 5,590-doc test. Translation: the "graph indexing is too expensive at small scale" objection collapses. There IS no cost barrier at 2 K nodes.

3. **Medical-domain measurement specifically favors graph** in two ways naive top-k cannot replicate:
   - **Multi-hop**: HopRAG ([arXiv:2502.12442](https://arxiv.org/html/2502.12442v1)) and the [MediGRAF clinical EHR study (Frontiers in Digital Health, Feb 2026)](https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2026.1780700/full) show graph achieves **100% recall vs 51.6% for vector-alone on multi-hop** at ~6K nodes — exactly the regime we're in.
   - **Provenance + hallucination**: [Medical hallucination survey, medRxiv Feb 2025](https://www.medrxiv.org/content/10.1101/2025.02.28.25323115v2.full.pdf) documents that inline 50K-context RAG is "confidently incorrect" on rare conditions; graph systems trace evidence chains node-by-node and edge-by-edge. **Confident-incorrectness on a rare-but-deadly condition is exactly what we cannot ship in a clinical demo.**

## What yesterday's brief got right (kept)

- vLLM flag set for Omni serving on H100 (`scripts/bench_omni_alongside.sh`) — unchanged.
- Don't full-LoRA on small data (Decision 3) — unchanged.
- EASY-EP expert pruning + router-only fine-tune (Decision 3) — unchanged, and **gets stronger** under the new architecture (see §"Expert/community alignment" below).
- Citation-grounding rail — unchanged in spirit, sharpened in mechanism (vLLM constrained decoding over subgraph node-IDs).

## NVIDIA's own stance (the second-opinion data)

NVIDIA's [RAG Blueprint](https://github.com/NVIDIA-AI-Blueprints/rag) does NOT use graph retrieval. Their stack is dense + sparse hybrid via cuVS-accelerated Milvus, with [Omni-Embed-Nemotron-3B](https://huggingface.co/nvidia/omni-embed-nemotron-3b), [Llama-Nemotron-Embed-VL](https://developer.nvidia.com/blog/building-nvidia-nemotron-3-agents-for-reasoning-multimodal-rag-voice-and-safety/), and [Llama-Nemotron-Rerank-VL](https://developer.nvidia.com/blog/building-nvidia-nemotron-3-agents-for-reasoning-multimodal-rag-voice-and-safety/) as the three load-bearing components. nx-cugraph and cuGraph community detection (Leiden 47× CPU per [NVIDIA's blog](https://developer.nvidia.com/blog/how-to-accelerate-community-detection-in-python-using-gpu-powered-leiden/)) are positioned as **analytics**, not retrieval.

**Reading**: NVIDIA's blueprint targets general enterprise RAG (single-hop fact lookup over heterogeneous documents). Medical reasoning is multi-hop and demands provenance — different operating point, different right answer. We layer graph atop NVIDIA's blessed primitives, we don't replace them.

## The corrected architecture (v2)

LazyGraphRAG-shaped, NVIDIA-primitive-aligned, OODA-fast.

### Components, with latency budget

| # | Component | Primitive | Latency budget |
|---|---|---|---|
| 1 | Persistent in-VRAM medical KG (~2 K nodes after OpenEM expansion; Leiden community partitions precomputed at startup) | nx-cugraph DiGraph + cuGraph Leiden | 0 ms (resident) |
| 2 | Dense embedding index over node descriptions | cuVS IVF-PQ via NV-Embed-v2 | ~1–2 ms top-k |
| 3 | Cross-encoder rerank of top-k candidates | Llama-Nemotron-Rerank-VL (NVIDIA-shipped) | ~3–5 ms |
| 4 | 2-hop ego-graph expansion of reranked seeds | nx-cugraph BFS | ~1–3 ms |
| 5 | Subgraph slice → JSON inline (5–15 K tokens, NOT 50 K) | host-side serialize | ~2 ms |
| 6 | Constrained decoding: output tokens must reference subgraph node IDs | vLLM `allowed_token_ids` mask | 0 ms (mask precomputed) |
| 7 | Token generation on H200 (Omni MoE, top-6 of 128 experts) | vLLM 0.20 + flags from yesterday's brief | ~30–40 ms p50 (depends on output length) |
| 8 | Citation-grounding rail: each cited passage must have ≥0.8 cosine to a retrieved subgraph node description | NeMo Guardrails Colang 2.0 + cuVS | 0 ms (in-pipeline) |

**Estimated p50 closed-loop**: ~10–15 ms retrieval + ~30–40 ms inference ≈ **50 ms**, vs ~150–300 ms for the naive "inline 50 K of cards" path. **5–10× OODA speedup**, modulo the latency-budget assumptions.

### Munger inversion — five dumb things this avoids

1. **Re-embed every query.** Persistent cuVS index, embedded once at startup. (Naive path: 10–20 ms per query; multi-thousand-call sweep eats hours.)
2. **Inline 50 K generic tokens.** Surgical 5–15 K subgraph inlining. (Naive path: state saturation per [Stuffed Mamba](https://openreview.net/forum?id=cu2CT2VAvs); slow prefill; lost-in-the-middle on transformer layers.)
3. **No edge provenance.** Each generated citation must reference a subgraph node-ID via `allowed_token_ids`. (Naive path: confident-incorrect on rare conditions per [medRxiv](https://www.medrxiv.org/content/10.1101/2025.02.28.25323115v2.full.pdf).)
4. **Hallucinated cross-card synthesis.** Rail enforces ≥0.8 cosine to a retrieved card description. The "dyspnea + chest pain appears in 15 cards; model invents a passage that synthesizes across two" foot-gun is closed.
5. **Full 128-expert routing on every token.** Leiden community label of the retrieved subgraph guides expert pre-warming (R3 polish — uncertain perf gain, research direction; ClusterMoE precedent at [github.com/The-Swarm-Corporation/ClusterMoE](https://github.com/The-Swarm-Corporation/ClusterMoE)).

### Expert/community alignment (the speculative R3 polish)

Two structures get aligned:
- The KG, partitioned by **Leiden community** (cuGraph, ~10 medical clusters expected: cardiac, pulmonary, neuro, GI, OB/GYN, psych, peds, tox, infectious, MSK).
- Omni's **128 experts**, of which top-6 fire per token.

If a query's retrieved subgraph is mostly in the cardiac community, the router should preferentially route to a 16-expert subset that's been profiled as cardiac-active (per the EASY-EP probe in yesterday's Decision 3). This is "the heart-failure expert subset reads the heart-failure subgraph" — surgical OODA that no published paper exactly describes for medical, but ClusterMoE shows the pattern works for hierarchical clustering generally. **Status**: research direction. Not a v1 ship blocker.

### Updated v0 → v2 retrieval upgrade path (replaces yesterday's path)

| Version | What ships | Validation |
|---|---|---|
| v0 (now) | `KeywordRetriever` in `mla/retrieval.py` — alias + ICD-10 substring. Zero deps. | unit tests passing |
| v1 (R2-cheap) | LazyGraphRAG-shaped: Leiden communities precomputed; cuVS dense top-k → 2-hop ego-graph → 5–15 K subgraph inline. NVIDIA primitives only (cuVS, nx-cugraph, NV-Embed-v2, Llama-Nemotron-Rerank-VL). | recall@5 on a held-out OpenEM lookup set; latency p50 < 15 ms retrieval |
| v2 (multi-modal) | Add image nodes (DICOM, ECG, dermatology) with Omni-Embed-Nemotron-3B; image edges to condition nodes. | radiology-relevant subset; cite NV-Embed multimodal blog |
| v3 (deferred) | Audio retrieval (Korotkoff, dictation); speculative graph prefetch on partial query. | uncertain timeline |

## What I'm NOT claiming

- I'm not claiming graph wins on every dimension. **Single-hop fact lookup over heterogeneous corpora**: vector RAG is fine — that's why NVIDIA's blueprint is shaped that way. We pay the graph tax because medical multi-hop reasoning + provenance is the binding requirement, not because graph is universally superior.
- I'm not claiming the 50 ms p50 estimate is a measured number. It's a budget, sourced from the latency claims of each individual primitive (cuVS ~1–2 ms top-k per [NVIDIA cuVS blog](https://developer.nvidia.com/blog/optimizing-vector-search-for-indexing-and-real-time-retrieval-with-nvidia-cuvs/), nx-cugraph BFS sub-ms at small scale, Omni MoE token-gen ~30–40 ms p50). Real number requires measurement.
- I'm not claiming the speculative R3 polish (community-expert alignment) ships in v1. It's a research direction; it pays off if measured, otherwise stays on the shelf.

## Concrete next steps

1. **Update `mla/retrieval.py` docstring** to reflect the v2 architecture (graph-first, NVIDIA-primitive-aligned). Done in this commit.
2. **Mark yesterday's `engineering-decisions.md` Decision 2 as superseded**, pointing to this brief. Done in this commit.
3. **Author `scripts/build_lazygraph_rag.py`**: a build-time script that loads OpenEM 370 conditions → embeds with NV-Embed-v2 → computes Leiden communities via cuGraph → persists `data/lazygraph/` (community summaries + node embeddings + adjacency). Stub today, runs tomorrow when we have GPU time. Done in this commit (stub).
4. **Run the A/B Omni bench (`scripts/bench_omni_alongside.sh`) BEFORE the architecture rebuild**, so we have a measured Omni baseline against the existing R1 Nano number. The architecture rebuild ships on top of whichever wins.
5. **Cite the path properly in PR #11** when the v1 retrieval ships — note that the architecture revision was driven by user pushback against my over-confident skip-graph call. Audit-trail honesty.

## Sources index

GraphRAG empirical:
- arXiv:2506.05690 (overstated 10K threshold) — <https://arxiv.org/html/2506.05690v3>
- arXiv:2506.06331 (bias correction) — <https://arxiv.org/html/2506.06331v1>
- arXiv:2502.11371 (RAG vs GraphRAG systematic eval) — <https://arxiv.org/html/2502.11371v1>
- arXiv:2502.12442 (HopRAG multi-hop) — <https://arxiv.org/html/2502.12442v1>
- Microsoft LazyGraphRAG — <https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/>

Medical-specific:
- MediGRAF clinical EHR (Frontiers in Digital Health, Feb 2026) — <https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2026.1780700/full>
- Gestational diabetes GraphRAG (PMC12767777) — <https://pmc.ncbi.nlm.nih.gov/articles/PMC12767777/>
- Medical hallucination survey, medRxiv Feb 2025 — <https://www.medrxiv.org/content/10.1101/2025.02.28.25323115v2.full.pdf>

NVIDIA:
- NVIDIA RAG Blueprint — <https://github.com/NVIDIA-AI-Blueprints/rag>
- NVIDIA cuVS optimization — <https://developer.nvidia.com/blog/optimizing-vector-search-for-indexing-and-real-time-retrieval-with-nvidia-cuvs/>
- nx-cugraph docs — <https://docs.rapids.ai/api/cugraph/stable/nx_cugraph/>
- Leiden GPU acceleration — <https://developer.nvidia.com/blog/how-to-accelerate-community-detection-in-python-using-gpu-powered-leiden/>
- Omni-Embed-Nemotron-3B — <https://huggingface.co/nvidia/omni-embed-nemotron-3b>
- Building NVIDIA Nemotron-3 agents (multimodal RAG, voice, safety) — <https://developer.nvidia.com/blog/building-nvidia-nemotron-3-agents-for-reasoning-multimodal-rag-voice-and-safety/>

Long-context degradation:
- Stuffed Mamba (state saturation) — <https://openreview.net/forum?id=cu2CT2VAvs>
- Lost in the Middle (TACL 2024) — <https://aclanthology.org/2024.tacl-1.9/>

xAI / production speed:
- xAI Grok Code Fast — <https://x.ai/news/grok-code-fast-1>
- ClusterMoE (hierarchical expert clustering) — <https://github.com/The-Swarm-Corporation/ClusterMoE>
