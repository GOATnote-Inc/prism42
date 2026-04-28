# nx-cugraph 26.04.00 Drop-in Brief

**Date:** 2026-04-27 · **Status:** research-only · **Verdict:** 🔴 RED at
current scale — no NetworkX call sites in any repo, and 3,987 nodes is below
the GPU break-even.

## 1. What nx-cugraph 26.04.00 is

NetworkX backend that routes supported graph algorithms to NVIDIA GPUs via
cuGraph (RAPIDS). Zero-code-change activation via env var. ~60 algorithms
GPU-accelerated (PageRank, betweenness centrality, shortest path, Louvain,
connected components). Released April 9, 2024 baseline; nightly track
extending into 2026.

Sources:
- https://rapids.ai/nx-cugraph/
- https://developer.nvidia.com/blog/networkx-introduces-zero-code-change-acceleration-using-nvidia-cugraph/
- https://github.com/rapidsai/nx-cugraph/releases

## 2. Enable mechanics — exact API

Three activation modes, in order of preference:

```python
# Mode 1 (recommended): zero-code-change
import os
os.environ["NX_CUGRAPH_AUTOCONFIG"] = "True"
import networkx as nx
# ... build graph ...
result = nx.pagerank(G)  # routes to GPU automatically

# Mode 2: per-call
result = nx.pagerank(G, backend="cugraph")

# Mode 3: type-based dispatch
import nx_cugraph as nxcg
gpu_G = nxcg.from_networkx(G)
result = nx.pagerank(gpu_G)
```

Source:
https://developer.nvidia.com/blog/networkx-introduces-zero-code-change-acceleration-using-nvidia-cugraph/

## 3. Healthcraft graph audit

**No NetworkX usage detected anywhere in healthcraft.**

Grep audit across `/Users/kiteboard/healthcraft/`:
- No `import networkx`, `from networkx`, `nx.Graph`, `nx.DiGraph`.
- No graph algorithm calls (`pagerank`, `betweenness_centrality`,
  `shortest_path`, `connected_components`, etc.).
- `pyproject.toml:11` lists no graph libraries.

The "14-type entity graph, 3,987 entities" referenced in
`/Users/kiteboard/healthcraft/CLAUDE.md:38` is a **relational reference
graph** — entities stored as dicts keyed by ID in
`src/healthcraft/world/state.py:55-57`, with foreign keys (`patient_id`,
`encounter_id`, `condition_id`) maintained as fields. There is no NetworkX
`Graph` object, no traversal API, no centrality computation.

**Conclusion:** zero drop-in surface today.

## 4. GPU vs CPU break-even

Per RAPIDS benchmarks
(https://developer.nvidia.com/blog/accelerating-networkx-on-nvidia-gpus-for-high-performance-graph-analytics/):

| Graph size | GPU win? |
|---|---|
| < 50 nodes | CPU faster (init overhead dominates) |
| 50–1K nodes | Marginal or CPU-favored |
| 10K–100K | GPU 2–10× win |
| 1M+ | GPU mandatory (50–500× on betweenness) |

**healthcraft at 3,987 nodes lands squarely in the "GPU overhead > savings"
zone.** GPU init takes ~100–500 ms; CPU naive PageRank on a 4K-node graph
completes in < 10 ms. No performance win at this scale even if NetworkX
*were* used.

## 5. Other repos — NetworkX usage check

- `/Users/kiteboard/lostbench/` — none
- `/Users/kiteboard/openem-corpus/` — none
- `/Users/kiteboard/scribegoat2/` — none
- `/Users/kiteboard/prism42/` — none

## 6. Integration delta

Best case (if any repo had NetworkX): **zero code change** (env var only).

Actual case: **no integration possible without a refactor** — entity
relationships would have to be materialized as a NetworkX `Graph` object and
new graph operations added (centrality, community detection, shortest-path).
That's net-new product work, not a drop-in.

## 7. Risks if forced

1. **Graph-conversion overhead** — materializing 3,987 entities + FK edges
   into a NetworkX `Graph` is O(V+E); acceptable as one-time init, brittle
   if recomputed per task.
2. **Attribute loss** — cuGraph drops rich node/edge attributes; only
   source/target/weight survive. Healthcraft's FHIR R4 attributes (status,
   observation values, timestamps) would have to be re-joined from the
   original entity dicts.
3. **MultiGraph constraints** — encounter chains (same patient, multiple
   admissions) form multi-edges; cuGraph flattens them.
4. **Algorithm mismatch** — supported algorithms are PageRank, centrality,
   community detection. healthcraft's clinical workload is FHIR validation
   and audit logging — none of these.

## 8. Recommendation

🔴 **RED. Do not attempt.**

Reasons:
1. No NetworkX call sites in any of 5 repos to drop-in to.
2. 3,987 nodes is below GPU break-even — would be slower than CPU even if
   the surface existed.
3. Algorithm coverage doesn't match healthcraft's clinical workload.
4. Attribute model conflicts with FHIR R4.

**Revisit when:** a future healthcraft feature wants graph-based clinical
decision support (e.g. comorbidity-similarity retrieval) AND graph size
crosses 10K nodes. Until then, zero ROI.

---

## Sources

- https://rapids.ai/nx-cugraph/
- https://developer.nvidia.com/blog/networkx-introduces-zero-code-change-acceleration-using-nvidia-cugraph/
- https://developer.nvidia.com/blog/accelerating-networkx-on-nvidia-gpus-for-high-performance-graph-analytics/
- https://github.com/rapidsai/nx-cugraph/releases
