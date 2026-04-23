# Evaluation rubric for prism-mla performance claims
Last updated: 2026-04-23. Drafted in response to reviewer feedback that earlier
results drifted into marketing-adjacent framing. This rubric is binding: any
performance claim that appears in a commit message, paper, deck, or demo must
cite a session ID that passed this protocol.

## Background — why this exists
Initial runs quoted "1.31x FlashInfer" based on same-process measurements where
FlashInfer's own median had been contaminated by preceding torch.compile
autotune (52.3 µs measured, vs 17.5 µs in a fresh process — a 3x measurement
artifact). Under the rubric below that claim does not survive: the correct
clean-process number is 3.68x, not 1.31x, and the framing changes accordingly.

The goal of this document is to make it structurally hard to make that mistake
again.

## 1. Clean-run protocol (mandatory for any "beats X" framing)

Every reported number must come from `scripts/isolated_bench.py`, which
enforces the following:

### 1.1 Process isolation
- One fresh Python subprocess per `(subject, config, replicate)` measurement.
- No module is imported in the orchestrator that would warm CUDA or torch.compile state shared with the worker.
- `TORCHINDUCTOR_CACHE_DIR` is allowed to be shared across subprocesses (cuts autotune cost on repeated configs) but never across **subjects** — different subjects mean different graphs so the cache is naturally partitioned.
- The subprocess's exit drops the CUDA context, freeing allocator and kernel caches.

### 1.2 GPU clock behavior
- Best-effort `nvidia-smi -lgc <max_sm>,<max_sm>` at session start. If it fails (e.g., unprivileged container), the session records `clock_lock.locked = false` and prints a warning. **Results remain usable** only if observed replicate variance is below the stability threshold in §1.5; otherwise the session is rejected.
- `nvidia-smi -rgc` at session end.
- Each worker captures SM clock and power before and after the timed loop. A drift of >5% SM clock within a worker invalidates that row.

### 1.3 Warmup and sample collection
- Warmup: **30 untimed invocations** of the kernel.
- `torch.cuda.synchronize()` before timing begins.
- Timed loop: **200 CUDA-event–paired samples** (`torch.cuda.Event(enable_timing=True)`).
- Discard the first **5 timed samples** (residual compile/autotune noise).
- Capture full distribution: `p10 / p50 / p90 / p99 / max / mean / stdev / n`.

### 1.4 Replicates (v1.1 — 2026-04-23, raised from n=3 → n=9)
- **9 independent subprocess replicates** per `(subject, config)` — minimum floor for any rel_stdev claim.
- Report `mean ± stdev` across the 9 replicates' p50 values.
- Also report `min..max` range.
- **Rationale:** session 20260423_044102 (n=3) showed FlashInfer rel_stdev 0.33% at (kv=256). Session 20260423_070837 (n=9, different pod) showed FlashInfer rel_stdev 20.23% at the same config. The n=3 number was effectively a single draw from a wide distribution; it carried no statistical weight. Every n<5 rel_stdev label in prior artifacts is now marked untrusted. Incident report: `failures/INCIDENT_2026-04-23_n3-rel-stdev-unreliable.md`.
- **Legacy sessions at n=3 remain in the log for lineage** but cannot ground a claim. Revalidation at n=9 required.

### 1.5 Stability threshold (v1.1 — bands widened to reflect observed n=9 variance)
- **STABLE:** rel_stdev ≤ 5% across n≥9 replicates. Claim-grade.
- **MARGINAL:** 5% < rel_stdev ≤ 10%. Citable with an explicit "marginal stability, n=9" caveat.
- **HIGH_VARIANCE:** rel_stdev > 10%. Provisional only; row cannot ground a "beats X" claim.
- Remediation for HIGH_VARIANCE: provision a second pod and check whether the row becomes STABLE there. If still HIGH_VARIANCE on ≥2 pods, the config is intrinsically noisy and requires a workload change, not a measurement change.
- **Never "pick the best replicate."** Never drop outliers without a documented reason tied to a specific hardware event (thermal throttle, clock drop, nvidia-smi clock mismatch).

### 1.6 Compile-cost reporting
- `build_s` (harness construction) and `compile_s` (first-call JIT+autotune) are reported alongside steady-state. **Never report a steady-state median without its associated compile cost.**
- For candidates that require torch.compile: the `compile_s` of the first replicate is the honest cold-start cost; subsequent replicates hit the cache. Report both.

### 1.7 Cold vs warm
- `cold_ns` (first timed sample, pre-discard) captured separately from `warm.*`.
- Serving workloads are warm-dominated; batch-first-use workloads are cold-sensitive. Both numbers ship.

### 1.8 Reproducibility pin
Each worker emits in its JSON output:
- git SHA of the prism-mla repo
- torch version
- flashinfer version
- CUDA runtime version
- GPU UUID and `nvidia-smi` version
- CUDA_VISIBLE_DEVICES
- `clock.sm` / `clock.max.sm` / `power.draw` at start and end
- RNG seed
- Config dict
- Session ID

## 2. Acceptance criteria for "beats X"

Let `M_candidate` and `M_ref` be the mean-p50 across 3 clean replicates.

### 2.1 Correctness (hard gate)
- `max_abs_error <= 5e-2` on bf16 paths; `<= 1e-3` on fp16 with a 1/sqrt(d_k) scale; `<= 1e-6` on fp32.
- Invariants from `prism/invariants.py` pass (softmax row-sum, output norm bound, no extreme values, top-k agreement on attention weights where applicable).
- One failure on any point of the grid = the entire candidate is **rejected for this release**. No partial credit.

### 2.2 Coverage grid
The candidate must be evaluated on at least:
- `batch ∈ {1, 4, 16}`
- `kv_len ∈ {256, 1024, 4096, 16384}`
- `dtype ∈ {bf16, fp16}`

That is 24 grid points. Smaller slices are acceptable for intermediate reports but must be explicitly marked "slice-only" in any summary language.

### 2.3 Performance threshold
- Candidate must satisfy `M_candidate <= M_ref` on **≥ 20 of 24** grid points (≥ 83%).
- On the remaining ≤ 4 points, `M_candidate <= 1.05 * M_ref` (within 5%).
- Any ratio below 1.0 is "beats"; any ratio above 1.05 on more than 4 points is not.

### 2.4 Amortization rule for compile cost
If `compile_s > 10 * warm_median_s`, the headline must include the break-even call count:
> "Candidate X beats ref on steady state at Y µs median; break-even vs ref's 0 s compile is N calls."
Otherwise the headline reads as if compile cost doesn't exist — it does.

### 2.5 Independent rerun (v1.1 — now required, not optional)
- Claim must reproduce on a **second pod / machine** with different GPU UUID.
- Both pods must show rel_stdev ≤ 10% at n=9 AND p50 means within 5% of each other.
- If the second run violates §1.5 stability or §2.3 threshold, the claim is withdrawn publicly — no exceptions.
- **Precedent:** session 20260423_044102 (pod A) showed baseline_compiled rel_stdev 14.78% at kv=4096; session 20260423_060948 (pod different UUID) showed 21.04% same config. A performance claim using only pod A's n=3 mean would have been non-reproducible under v1.0; v1.1 catches this class structurally.

## 3. End-to-end gate (for system-level claims)

Micro-benchmarks at the decode kernel level do **not** support statements like
"inference faster by X%." Those require:

### 3.1 Integrated harness
- Candidate wired into a real inference engine: vLLM, TRT-LLM, SGLang, or an
  equivalent production loop.
- Sampling, page management, request scheduling all participate.
- Measured against a published trace: ShareGPT, LMSYS-Chat-1M, or in-house workload with the specific distribution documented.

### 3.2 System-level metrics
- Throughput (tokens / second) at representative concurrent request counts
  (e.g., N ∈ {1, 8, 32, 128}).
- Latency: p50 / p99 time-to-first-token, inter-token latency, end-to-end.
- Memory: peak HBM, KV cache footprint, working set.
- Stability: 99th-percentile degradation under load, OOM behavior at the
  concurrency cliff.

### 3.3 Triplicate
- 3 independent end-to-end runs. Report `mean ± stdev` per metric.

### 3.4 Comparison framing
- Only then: "in workload W at concurrency C on hardware H, candidate X
  delivers N% more throughput / N% lower p99 than reference Y."

## 4. Language rules for summaries

| Do not say | Say instead (when supported) |
| --- | --- |
| "beats FlashInfer" | "at config C on grid point P, candidate p50 is N.NNx flashinfer p50 (3 replicates, sessions S1/S2/S3)" |
| "automatic discovery" | "torch.compile found tile X,Y,Z for this graph; the evolve loop proposed the mutation that fed into it" |
| "N% speedup" | "N% reduction in warm p50 at config C; compile_s is M; break-even call count is K" |
| "production-ready" | "passes §2 rubric at N/24 grid points; §3 not yet run" |
| "beats hand-tuned kernel" | "reaches M.MMx of the hand-tuned reference at N grid points; does not beat on the remaining" |

## 5. Artifacts required for each reported result

1. **JSONL row file** — one line per worker subprocess, containing every field from §1.8.
2. **Summary JSON** — aggregated per `(subject, config)` with replicate statistics.
3. **Markdown report** — human-readable, including the rubric version it complies with.
4. **Reproducibility command** — the exact `scripts/isolated_bench.py` invocation, suitable for paste-and-run.
5. **Session ID** (timestamp-based) referenced in every claim that depends on this session.

## 6. When a claim fails

The right move is:
1. **Withdraw** the claim publicly with an explicit correction.
2. **Document** the failure mode (same-process contamination, small grid, etc.) in a `failures/` file in this repo.
3. **Update the rubric** if a new failure mode was found that §1–§4 didn't catch.

## 7. Version pin

- **v1.0 (2026-04-23 AM):** initial rubric after same-process autotune contamination produced a 3× measurement artifact. Drafted post-incident.
- **v1.1 (2026-04-23 PM):** replicate floor raised from n=3 to n=9; stability bands explicitly widened (STABLE/MARGINAL/HIGH_VARIANCE); independent-rerun gate moved from optional to mandatory. Drafted after sessions 20260423_044102 / 060948 / 070837 showed that n=3 rel_stdev labels were effectively single draws from wide distributions (FlashInfer rel_stdev shifted from 0.33% at n=3 to 20.23% at n=9 on the same config, different pod).

Any result predating v1.1 was produced under weaker methodology. Revalidation at n=9 on ≥2 pods required before any performance claim ships.

## Cross-references
- Implementation: `scripts/isolated_bench.py`, `scripts/_bench_worker.py`.
- Example compliant session: see `results/logs/isolated_bench_*.{jsonl,md,summary.json}` triples.
- Mental models: `mental-models/munger-inversion.md` §6 (benchmark-is-not-measuring-what-you-think) — the primary failure class this rubric guards.
- Red-team: `mental-models/red-team-adversarial.md` §2 (benchmark gaming) — adversarial defense reads the same way from the other direction.
