# Karpathy "Autoresearch" — Attribution Correction

**Date:** 2026-04-27 · **Status:** research-only · **Verdict:** ⚠️
ATTRIBUTION CORRECTION — the framing in the user's stack diagram is not
well-founded. Recommended substitute: **DSPy GEPA** with a footnote citing
the autoresearch *pattern*.

## 1. What Karpathy actually shipped

`github.com/karpathy/autoresearch`, released **2026-03-07**:

- ~630-line single-GPU Python tool, self-contained.
- AI agent edits `train.py`, runs ~5-min training jobs, keeps the wins,
  discards the losses.
- **Optimizes `val_bpb`** (validation bits-per-byte on a language-model
  training run). NOT RAG retrieval, NOT ranking, NOT subgraph logic.
- Instructions live in `program.md` of the repo.
- Verified author: `karpathy` = Andrej Karpathy (~176 K followers,
  Stanford bio, owner of nanoGPT/llama2.c).
- Karpathy's own follow-up (2 days, ~700 experiments, ~20 transferable
  wins, 11% speedup on already-tuned code).

**Karpathy has not published a RAG-specific autoresearch repo.** No
`nano-research`, no `nightly-rag`, no `kr-research` exists under his
GitHub.

Sources:
- https://github.com/karpathy/autoresearch
- https://x.com/karpathy/status/2030371219518931079
- https://x.com/karpathy/status/2031135152349524125
- https://www.marktechpost.com/2026/03/08/andrej-karpathy-open-sources-autoresearch-a-630-line-python-tool-letting-ai-agents-run-autonomous-ml-experiments-on-single-gpus/

## 2. The "nightly RAG optimizer" the user is describing

The closest match is **`Auto-RAG-Optimizer` by Yeyu Huang** (Substack
post, March 2026):

- Applies the autoresearch pattern to a fixed QA benchmark.
- Edits only `rag_pipeline.py`, runs ~20 autonomous experiments.
- Reported lift on retrieval-quality metric.
- **Not authored by Karpathy.** Inspired-by, single-author Substack
  derivative, not a maintained library.

Source:
- https://yeyu.substack.com/p/auto-rag-optimizer-applying-autoresearch

## 3. Better-attributed alternatives

If the goal is "agent-driven nightly self-improvement loop on a RAG
pipeline with real maintainership and CI," these are the better answers:

### #1 — DSPy + GEPA (Stanford NLP) ✅ RECOMMENDED

- `gepa-ai/gepa` + `stanfordnlp/dspy`.
- GEPA = "Reflective Prompt Evolution" (Agrawal et al., 2025).
- **Generic RAG Adapter** out of the box: Chroma / Weaviate / Qdrant /
  Pinecone backends; optimizes query reformulation, context synthesis,
  answer generation, reranker prompts.
- Active 2026 releases (gepa[dspy] 0.0.26 adds cached evals).
- Sources:
  - https://dspy.ai/api/optimizers/GEPA/overview/
  - https://github.com/gepa-ai/gepa

### #2 — DSPy MIPROv2

- Joint instruction + few-shot tuning.
- Documented lift: ReAct on HotPotQA 24% → 51%; RAG SemanticF1
  53% → 61%.
- Source: https://dspy.ai/api/optimizers/MIPROv2/

### #3 — `alvinreal/awesome-autoresearch`

- Curated list of autoresearch-pattern loops (survey).
- Source: https://github.com/alvinreal/awesome-autoresearch

## 4. Recommendation for the user's stack diagram

Two clean options:

### Option A — keep the autoresearch framing, fix attribution

> "Autoresearch pattern (Karpathy, 2026-03) — overnight agent-driven
> experiment loop. We apply it to RAG following Huang's adaptation."

This is honest about what Karpathy shipped (the *pattern*) vs. what's
being applied here (RAG-specific derivative).

### Option B — drop Karpathy, cite the canonical RAG-optimizer ✅ PREFERRED

> "**DSPy GEPA** (Stanford NLP, 2026) — nightly RAG optimizer with a
> Generic RAG Adapter for Chroma / Weaviate / Qdrant. Optimizes query
> reformulation, context synthesis, and answer generation."

This is the better-attributed, actively-maintained, RAG-native answer.

**My pick:** Option B. The Karpathy framing as currently written
("Karpathy Autoresearch — Optimizes RAG nightly") is not well-founded
and risks reading as marketing fluff. DSPy GEPA is the precise tool for
the job and has the maintainer track record to back it.

---

## Sources

- https://github.com/karpathy/autoresearch
- https://github.com/karpathy
- https://x.com/karpathy/status/2030371219518931079
- https://x.com/karpathy/status/2031135152349524125
- https://www.marktechpost.com/2026/03/08/andrej-karpathy-open-sources-autoresearch-a-630-line-python-tool-letting-ai-agents-run-autonomous-ml-experiments-on-single-gpus/
- https://yeyu.substack.com/p/auto-rag-optimizer-applying-autoresearch
- https://dspy.ai/api/optimizers/GEPA/overview/
- https://github.com/gepa-ai/gepa
- https://dspy.ai/api/optimizers/MIPROv2/
- https://github.com/alvinreal/awesome-autoresearch
