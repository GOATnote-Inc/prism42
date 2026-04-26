# Team M — Phase 2: Lever Inventory + ROI Ranking

**Scoring (1–5):** Impact (steady-state user benefit), Effort (1=trivial, 5=hard), Risk (LOW/MED/HIGH = could affect voice). **Reversibility:** in-flag, restart, rebuild.

**Calibration vs current state.** vLLM is at 0.20.1.dev0 with `gpu-memory-utilization=0.20`, `max-model-len=32768`, `max-num-seqs=8`, `kv-cache-dtype=fp8`, `cudagraph_capture_sizes=[1,2,4,8,16]` (already small), prefix caching ON but 0% hit, MoE backend = FLASHINFER_CUTLASS (correct), attention backend = FLASHINFER (correct). **Cold-start = 62 s already, NOT 14 min. The 14-min memory note is stale.**

---

## Levers ranked (highest ROI first)

| # | Lever | Where set | Predicted impact | Risk | Reversible | Cite |
|---|---|---|---|---|---|---|
| **L3** | `--gpu-memory-utilization 0.85` | CLI flag | **+57 GiB KV cache (3x more)**, supports future multi-call concurrency without OOM. Aligns with NVIDIA cookbook (0.85) and vLLM recipes (0.92). Fish-Speech runs in a separate CUDA context — vLLM raising its budget does NOT shrink Fish's allocation. | LOW | restart | NVIDIA cookbook quotes `gpu_memory_utilization=0.85` for NVFP4 |
| **L8b** | `VLLM_USE_FLASHINFER_MOE_FP4=1`, `VLLM_FLASHINFER_MOE_BACKEND=throughput`, `VLLM_ATTENTION_BACKEND=FLASHINFER`, `TORCH_CUDA_ARCH_LIST=10.0;10.3` made **persistent** in a systemd-style env file | drop-in conf | Today these env vars live in the parent shell of the manual `vllm serve`. If the process is ever restarted from a fresh shell (or by someone who doesn't know), TRTLLM auto-select → JS-garbage. Risk is operational, not performance. | LOW | restart | Memory finding #6 |
| **L1b** | `--cuda-graph-sizes 1 2 4 8` (drop the size-16 capture) | CLI flag | **Save ~0.1 GiB CUDA graph pool**, ~0.5 s startup, no steady-state cost (we're batch=1 always). Already at 5 sizes, so marginal. Memory's predicted "14 min → 1-2 min" win was already realized — current cold start is 62 s. | LOW | restart | vLLM source: `cudagraph_capture_sizes` |
| **L7b** | `--async-scheduling` | CLI flag | **Zero-bubble scheduling overlaps prefill + decode + comm.** vLLM blog says paired with speculative decoding gives 1.3-1.7x throughput. Already enabled (log line 21:26:25 "Asynchronous scheduling is enabled") — VERIFY it's persisted in the launch script. | LOW | restart | vLLM blog "Zero-bubble async scheduling" |
| **L2** | `--max-model-len 8192` (down from 32768) | CLI flag | **Cuts KV cache memory commitment** by 75% per slot. With L3, KV slots grow from 33 GiB → ~140 GiB which could serve 17,000+ concurrent 8K turns (vs 70 currently at 32K). For voice-only workloads, 8K is plenty (PSAP turns < 300 tokens). NVIDIA cookbook uses 262144 — but that's for code/agent workloads. **Voice ≠ code.** | LOW (voice never crosses 8K) | restart | Workload analysis |
| **L6** | `--speculative-config '{"method":"ngram","num_speculative_tokens":3,"prompt_lookup_max":4,"prompt_lookup_min":2}'` | CLI flag | **N-gram speculative decoding can give 1.3-1.5x decode speedup** for repetitive PSAP outputs (JSON envelopes, common phrases). Free — no draft model. Compatible with B300 + NVFP4. Needs validation that NemotronH supports it. | MED (could fail to apply on Mamba layers) | restart | vLLM `speculative.py` SpeculativeMethods supports `ngram` |
| **L5** | `--mamba-cache-mode align` | CLI flag | **Switch from "all" (default, 0% hit) to "align" mode.** Caches less aggressively but per vllm-ascend PR #7103, "align" enables prefix cache for Qwen3.5/Next-class hybrid models. Could move hit rate from 0% → 10-30% on PSAP workloads if the orchestrator emits a stable header. Untested for NemotronH specifically. | MED (experimental, could break Mamba state) | restart | `cache.py:120` MambaCacheMode literal |
| **L11** | `enable_mfu_metrics=True` (observability) | env | Set `VLLM_OBSERVABILITY_ENABLE_MFU=1` or `--observability-config 'enable_mfu_metrics=True'`. **Doesn't change perf — just exposes Model FLOPs Utilization metric**, currently shown as 0 in `/metrics`. Lets future cycles measure HBM bandwidth + MFU instead of guessing. | LOW (observability only) | restart | vLLM ObservabilityConfig |
| **L4** | `--block-size 8` (down from default 16) | CLI flag | **Smaller KV blocks = less internal fragmentation** for short PSAP turns. Mamba has its own block size; this affects attention only. Marginal. | LOW | restart | vLLM CacheConfig |
| **L13** | Pre-build / verify FlashInfer cubins for sm_103 | env | Memory note: "FlashInfer 0.5.0 cubin builds for sm_103". Log shows `Tuning fp4_gemm` ran 4 rounds — that's autotune, not JIT compile. Probably already cached. **Verify** `~/.cache/flashinfer/` has cubin files. | LOW | none (cache survives restart) | FlashInfer 0.5 release notes |
| **L12** | Verify `quantization=modelopt_fp4` in engine config | log | **Already verified** in startup log: `quantization=modelopt_fp4`. NVFP4 path active. No action needed. | n/a | n/a | log |
| **L10** | Confirm `--tensor-parallel-size 1` | CLI flag | **Already correct.** Single B300, TP=1 is right; higher TP adds overhead. | n/a | n/a | log |
| **L14** | `VLLM_TUNED_RANDOM_KERNELS=1` | env | Memory's mention. Search of vLLM source did not surface this exact name; allreduce fusion is automatic for sm_103. Likely a stale flag from an earlier vLLM version. Not pursued. | n/a | n/a | n/a |
| **L9** | MIG / MPS for Fish ↔ vLLM co-residency | nvidia-smi | Not pursued. Memory says CUDA 13.0 lacks MLOPart (need 13.1). Status quo (default compute mode) works. Steady-state idle is 0% util — there's no contention to resolve. | n/a | n/a | memory note |
| **L15** | Persistent CUDA graphs across reboot | env | vLLM doesn't offer this (graphs are bound to a CUDA context that dies with the process). The torch.compile inductor cache **IS** persistent (`~/.cache/vllm/torch_compile_cache/`) and saves 10s of those 62s. Already on. | n/a | n/a | startup log |

---

## Top 3 ROI levers (Phase 3 targets)

### Pick 1 — L3: `--gpu-memory-utilization 0.85` 

**Why this is #1.** Single highest-impact change that matches the user's hypothesis ("not leveraging B300"). HBM is at 32% used. NVIDIA cookbook explicitly recommends 0.85 for NVFP4 Nemotron-3-Nano. The 0.20 setting in the current launcher is the binding constraint forcing KV cache to 33 GiB instead of 140+ GiB. Risk is bounded because Fish-Speech's CUDA context allocates separately — raising vLLM's budget can only consume what's currently FREE (185 GiB).

- **Predicted delta:** KV cache slots 70x → 290x at 32K; or with L2, 17,000+ at 8K. **TTFT unchanged at batch=1.** Future-proofs multi-call demo.
- **Verify command:** `curl -s :8001/metrics | grep -E "kv_cache_usage_perc|num_gpu_blocks"` after restart; expect `num_gpu_blocks` ~5-10x higher.
- **Risk class:** LOW. Headroom is real and measured.

### Pick 2 — L8b: Make MoE backend env vars persistent (drop-in conf file)

**Why this is #2.** The CURRENT process inherits the right env. But there is NO systemd unit. If the integrator restarts vLLM from a fresh shell after a tmux death, the env vars vanish → vLLM auto-selects FLASHINFER_TRTLLM → JS-garbage output → memory finding #6 reproduces. **This is a latent prod-down bug masked by current shell state.** Cost: 5 minutes to write a drop-in conf or shell wrapper. Risk: zero (it's already what's running).

- **Predicted delta:** Operational reliability. Eliminates a likely future incident.
- **Verify command:** Restart from a fresh shell; confirm `cat /proc/$pid/environ | tr '\0' '\n' | grep VLLM` still shows all 4 vars.
- **Risk class:** LOW.

### Pick 3 — L6: `--speculative-config ngram (3,2-4)` 

**Why this is #3.** Free decode speedup. PSAP outputs are JSON-envelope-heavy and have repetitive surface forms ("intent": "emergency", "severity": ...). N-gram speculation tables learn these online. NVIDIA's vLLM blog cites 1.3-1.7x throughput from async scheduling + speculative decoding combined — async is already on, so adding spec-decode is the unlocked half. **No draft model needed.**

- **Predicted delta:** Inter-token latency 3.2 ms → ~2.4 ms (33% faster decode), TPS 313 → ~420. For a 50-token reply, total time drops ~40 ms. User-perceptible on tail latency.
- **Verify command:** Look for `vllm:spec_decode_num_accepted_tokens_total` in `/metrics` after restart. Acceptance rate 30-50% is expected.
- **Risk class:** MED. Spec-decode on hybrid Mamba+Transformer is documented as supported for transformer layers; if NemotronH falls through, vLLM should fall back gracefully (validate in pre-flight, see Phase 3 verify command). If it errors at startup, the rollback is one-line.

---

## Why I rejected L5 (mamba-cache-mode align) for top 3

L5 has the highest THEORETICAL impact (0% → 30% prefix hit could cut prefill cost 30%), BUT:
1. The orchestrator emits a per-turn-mutated system prompt; even with `align`, the cacheable shared prefix may be tiny.
2. Mode `align` is experimental for hybrid models; NemotronH may have undefined behavior.
3. Charter forbids touching the orchestrator (where the real fix lives — emit stable header + mutable suffix).
4. Untested with NemotronH at NVFP4 specifically.

**Recommendation:** Hold L5 for cycle-2T. Pair it with an orchestrator pattern change (PR to dispatcher/FSM authors, separate from voice path) to emit stable prefixes — then the lever lands in a context where it can actually deliver.

## Why I rejected L2 (max-model-len 8192) for top 3

L2 is great but **lower marginal gain than L3.** With L3, the KV cache memory grows 5x just from raising the budget; we don't NEED to drop max-len. If we want to push concurrency for multi-call scenarios, L2 + L3 stack additively. For now, keeping max-model-len at 32768 preserves the option of long contexts (e.g. a stuck call with extensive history) without forcing a restart.

## Why I rejected L7b (async-scheduling persistence) for top 3

It's **already enabled** at runtime. Like L8b, it's a "make it persistent" concern, but the asyc-scheduling default is enabled by vLLM 0.20 unless explicitly disabled. Lower operational risk than L8b (which depends on env vars, not flags).
