# RAPIDS 26.04 Integration Brief

**Date:** 2026-04-27 · **Status:** research-only · **Verdict:** 🟢 cuVS for
healthcraft + openem-corpus; 🟡 cuDF for scribegoat2 (defer)

## 1. What's in RAPIDS 26.04 (April 2026)

NVIDIA's GPU data-science suite, April 2026 release. Key components:

1. **cuDF 26.04** — pandas-compatible GPU DataFrame; cu12 + cu13 wheels.
2. **cuML 26.04** — scikit-learn-compatible classical ML (KNN, clustering,
   regression).
3. **cuVS 26.04** — vector search (DiskANN/IVF/Vamana) with FAISS 1.10+
   integration. Up to 40× index-build speedup over CPU.
4. **RMM 26.04** — unified GPU memory manager.
5. **cuSpatial 26.04** — spatial indexing.

Sources:
- https://rapids.ai/
- https://docs.rapids.ai/install/
- https://docs.rapids.ai/platform-support/
- https://docs.rapids.ai/api/cuml/stable/

## 2. CUDA / Python compatibility

| Component | CUDA 12 wheel | CUDA 13 wheel | Python | B300 (SM 10.3) |
|---|---|---|---|---|
| cuDF | ✓ `cudf-cu12` | ✓ `cudf-cu13` | 3.10–3.13 | ✓ |
| cuML | ✓ | ✓ | 3.10–3.13 | ✓ |
| cuVS | ✓ | ✓ | 3.10–3.13 | ✓ |
| RMM | ✓ | ✓ | 3.10–3.13 | ✓ |

Install on B300 (CUDA 13.2.1 driver, forward-compatible with CUDA 13.0
wheels): `pip install cudf-cu13==26.04` (NOT conda-forge, which lags).

Source: https://github.com/rapidsai/build-planning/issues/208 ·
https://pypi.org/project/cudf-cu12/

## 3. Highest-leverage targets in the workspace, ranked

### #1 — healthcraft (HIGHEST LEVERAGE)

- **What:** 14-type entity graph, 3,987 entities at seed=42
  (`/Users/kiteboard/healthcraft/CLAUDE.md:38`), 24 MCP tools, 195 eval tasks.
- **RAPIDS fit:**
  - **cuVS** for embedding-based condition retrieval (drop-in replacement for
    LanceDB cosine search). 7× lower query latency, 40× faster index build.
  - **cuML** KNN for entity-similarity ranking on audit logs.
- **Integration point:** `src/healthcraft/openem/fhir_adapter.py` (bridge to
  OpenEM corpus) is the natural seam.
- **Estimated delta:** ~300 LOC, 80% net-new (loader, fallback, tests).

### #2 — openem-corpus (HIGH LEVERAGE)

- **What:** 370 OpenEM conditions, LanceDB index at
  `/Users/kiteboard/openem-corpus/data/index/openem.lance/` (rebuilt
  2026-03-13).
- **RAPIDS fit:** cuVS as a sidecar to LanceDB. 370 × 384-dim embeddings is
  small (~0.6 MB raw + ~5–10× index overhead); GPU win is index-build
  amortization across rebuilds.
- **Integration point:** `python/openem/index.py` — wrap `lancedb.connect`
  with optional cuVS backend.
- **Estimated delta:** ~120–180 LOC.

### #3 — scribegoat2 (MEDIUM, defer)

- **What:** 11,547 trajectories, Wilson CI / pass^k aggregations.
- **RAPIDS fit:** cuDF for trajectory dataframes. Current numpy/pandas
  pipeline runs in <30s — no blocking latency. Defer until trajectory count
  hits 100K+ or eval cadence becomes blocked.

### #4 — lostbench (LOW)

- I/O-bound (LLM API calls), not compute-bound. Skip.

## 4. Integration delta for healthcraft (the #1 target)

**Files that would change** (none touched today — research only):

| File | Change | LOC |
|---|---|---|
| `src/healthcraft/openem/fhir_adapter.py` | Add cuVS embedding loader; preload 370 vecs on container init | ~120 |
| `src/healthcraft/world/state.py` | Expose `search_by_embedding()` API with CPU fallback | ~30 |
| `src/healthcraft/mcp/tools/compute_tools.py` (optional) | New `searchConditionsByEmbeddingSimilarity` MCP tool | ~50 |
| `pyproject.toml` | Add optional dep `rapids = ["cudf-cu13>=26.04", "cuvs-cu13>=26.04"]` | ~3 |
| `tests/test_cuvs_embedding_search.py` | Determinism @ seed=42, fallback path | ~100 |

**Total: ~300 LOC, optional dep, CPU fallback preserves existing behavior.**

## 5. Risks / unknowns

1. **Python pin:** RAPIDS 26.04 likely 3.10–3.13. healthcraft / openem-corpus
   pin `>=3.10`; verify no upper-bound conflict before installing.
2. **VRAM budget:** 370 embeddings × 384 dims × fp32 = 0.6 MB + cuVS index
   (3–6 MB). Negligible. If a future workload adds image embeddings (RadSlice
   crossover), re-budget.
3. **Conda vs pip:** Pip wheels are 120 MB/package; conda-forge 2 GB. Use pip
   on the B300 pod.
4. **Cold-start JIT:** First cuVS query triggers ~500 ms CUDA kernel
   compilation. Mitigate with a warm-up dummy query in `__init__`.
5. **B300 SM 10.3 wheel availability:** RAPIDS wheels are arch-agnostic
   (PTX-fallback) but verify the cu13 wheel actually loads with
   `python -c "import cuvs; cuvs.test()"` on the pod before relying on it.

## 6. Recommendation

🟢 **GREEN — healthcraft cuVS** + **openem-corpus cuVS** in Q2 2026
(post-hackathon, end of April / early May).

🟡 **YELLOW — scribegoat2 cuDF.** Defer until trajectory volume forces it.

🔴 **RED — lostbench.** Workload is I/O-bound; no RAPIDS leverage.

**Suggested order:** openem-corpus first (decoupled, lower-risk), then
healthcraft (builds on openem). Budget 3–4 days per repo for integration +
tests + docs.

---

## Sources

- https://rapids.ai/
- https://docs.rapids.ai/install/
- https://docs.rapids.ai/platform-support/
- https://docs.rapids.ai/api/cuml/stable/
- https://www.elastic.co/search-labs/blog/elasticsearch-gpu-accelerated-vector-indexing-nvidia
- https://developer.nvidia.com/blog/optimizing-vector-search-for-indexing-and-real-time-retrieval-with-nvidia-cuvs/
- https://github.com/rapidsai/build-planning/issues/208
- https://pypi.org/project/cudf-cu12/
- https://github.com/rapidsai/cuvs/releases
