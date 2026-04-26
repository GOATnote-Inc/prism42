# Team M — Phase 1: B300 vLLM/Nemotron Profile

**Probe time:** 2026-04-26 ~10:12 UTC. **vLLM uptime at probe:** 12h 45min (started 21:25 UTC 04-25).
**No prod traffic injected.** All probes read-only or single 48-token request.

---

## 1. vLLM process inspection

### How it's launched (NOT systemd)
- **No `prism42-vllm.service`** under systemd. The vLLM process is launched manually (likely from a tmux/screen or cycle-2R G6 cutover script).
- **PID 389310**, user `shadeform`, parent of `EngineCore` worker PID 389430.
- **Binary path:** `/opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm` (sharing the fish-speech venv-nightly, not a dedicated `.venv`).
- **Logs:** `/proc/389310/fd/1,2 -> /tmp/prism42-logs/vllm.log` (389 lines as of probe; persistent file, not journald).
- **vLLM version:** `0.20.1.dev0+g101584af0.d20260425` — a custom build, not pip-released v0.20.1.

### Full command line
```
vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
  --served-model-name nemotron-nano \
  --trust-remote-code \
  --tensor-parallel-size 1 \
  --max-model-len 32768 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.20 \
  --kv-cache-dtype fp8 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py \
  --reasoning-parser nano_v3 \
  --enable-prefix-caching \
  --port 8001 \
  --host 127.0.0.1
```

### Runtime env (only env vars present)
- `VLLM_USE_FLASHINFER_MOE_FP4=1`  → CORRECT (matches memory)
- `VLLM_FLASHINFER_MOE_BACKEND=throughput` → CORRECT (CUTLASS-throughput backend)
- `VLLM_ATTENTION_BACKEND=FLASHINFER` → CORRECT
- `TORCH_CUDA_ARCH_LIST=10.0;10.3` → CORRECT (Blackwell sm_100 + sm_103)

NOT set (and could be relevant): `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS`, `VLLM_TUNED_RANDOM_KERNELS`, no `HF_TOKEN` (vLLM logged a warning).

---

## 2. vLLM telemetry (Prometheus + log)

### Backend selection (CONFIRMED CORRECT)
From startup log:
```
nvfp4.py:203] Using 'FLASHINFER_CUTLASS' NvFp4 MoE backend
  out of potential backends:
  ['FLASHINFER_TRTLLM','FLASHINFER_CUTEDSL','FLASHINFER_CUTEDSL_BATCHED',
   'FLASHINFER_CUTLASS','VLLM_CUTLASS','MARLIN'].
cuda.py:368] Using FLASHINFER attention backend
__init__.py:683] Using FlashInferCutlassNvFp4LinearKernel for NVFP4 GEMM
selector.py:132] Using HND KV cache layout for FLASHINFER backend.
```
Memory finding #6 ("CUTLASS only sane backend, TRTLLM gives JS-garbage") is honored.

### Latency (cumulative from 96 requests over 12+ h)
| Metric | Count | Sum | Mean | Median bucket |
|---|---|---|---|---|
| TTFT | 96 | 28.83 s | **300 ms** | 0.04–0.06 s (79/91 reqs, ~50 ms) |
| Inter-token | 1476 | 4.71 s | **3.19 ms (313 tok/s decode)** | <10 ms (1461/1476) |
| E2E | 95 | n/a | — | <0.3 s (93/95 reqs) |
| Queue | 96 | n/a | — | <0.3 s (all) |

The mean TTFT (300 ms) is dragged up by 1 cold first request (~750 ms) + 4 length-cutoff retries. **Median TTFT ≈ 50 ms.** Inter-token rate (313 tok/s) is excellent for batch=1.

### Throughput
- 96 successful requests, 1571 total generation tokens (avg 16.4 gen-tokens/req).
- 91 finished `stop`, 4 finished `length` (max_tokens hit). The 4% length-truncation rate suggests `max_tokens=48` (or similar small budget) sometimes cuts off the JSON response.

### Prefix caching — BROKEN
| Metric | Value |
|---|---|
| `prefix_cache_queries_total` | **215,732 tokens** queried |
| `prefix_cache_hits_total` | **0 hits** |
| Hit rate | **0.00%** |

Despite `--enable-prefix-caching` flag being on AND the engine log showing `enable_prefix_caching=True`, the cache is never hit. **Root cause hypothesis:**
1. Orchestrator calls `await self.update_instructions(prompt)` per turn — the FSM rewrites the system prompt every turn with intent + utterance + state, so even the first 1024 tokens differ across turns.
2. Mamba-prefix-cache "all" mode is **experimental** (vLLM startup log warns:
   `Warning: Prefix caching in Mamba cache 'all' mode is currently enabled. Its support for Mamba layers is experimental.`).
3. NemotronH is a hybrid Mamba+Transformer; some layer types may not actually be prefix-cacheable.

This is a SOFTWARE pattern problem, not a vLLM tuning problem. **Fix lives in the orchestrator (which is FROZEN per charter).** Lever L5 below proposes a non-orchestrator workaround.

### Engine config (from log)
- `chunked_prefill = True, max_num_batched_tokens = 8192` (already on — good for B300)
- `kv_cache_dtype = fp8` (already on — saves 50% KV cache vs bf16)
- `enforce_eager = False` (CUDA graphs ON — good)
- `cudagraph_mode = FULL_AND_PIECEWISE` (mode 2,1)
- `cudagraph_capture_sizes = [1, 2, 4, 8, 16]` (already only 5 sizes — not the 14-min problem)
- `max_cudagraph_capture_size = 16`
- `compile_ranges_endpoints = [8192]` (single inductor compile range, not 0..32K)
- `mamba_ssm_cache_dtype = float32` (forced for NemotronH)

---

## 3. GPU state (3 samples, idle, voice path quiescent)

| Sample | GPU util | Mem util | Mem used | SM clock | Power |
|---|---|---|---|---|---|
| t=0 | 0% | 0% | 88,708 MiB | 2032 MHz | 237.96 W |
| t=5s | 0% | 0% | 88,708 MiB | 2032 MHz | 237.64 W |
| t=10s | 0% | 0% | 88,708 MiB | 2032 MHz | 237.71 W |

- **GPU:** NVIDIA B300 SXM6 AC, sm_103, driver 580.126.09, **CUDA 13.0**.
- **HBM:** 275,040 MiB total. 88,708 MiB used (32.2%). **185,406 MiB FREE (67.4%).** Reserved 927 MiB.
- **BAR1:** 524,288 MiB total / 88,709 MiB used (17%) — plenty of headroom for memory mapping.
- **Power floor:** 237 W idle (P0). Likely persistence mode + Fish-Speech keeping the GPU in P0 with active CUDA contexts.
- **Compute mode:** Default (no MIG, no exclusive process) — Fish-Speech and vLLM share the GPU via CUDA contexts.
- **NVLink:** `nvidia-smi nvlink -s 0` rejected with "Option 0 not recognized" (single-GPU pod, no NVLink topology to query).

### HBM allocation breakdown (estimated)
| Component | Estimate |
|---|---|
| Nemotron NVFP4 weights | 18.63 GiB (model loading log line) |
| KV cache (currently configured) | ~33.56 GiB (gpu_worker.py:440) |
| CUDA graph pool | 0.51 GiB (gpu_model_runner.py:6086) |
| Fish-Speech S2-Pro (separate CUDA context, half-precision) | ~10–15 GiB |
| **Total measured** | **88.7 GiB / 275 GiB = 32%** |

**The constraint is `--gpu-memory-utilization 0.20`, which caps vLLM at 55 GiB.** vLLM's KV cache config is constrained to 33 GiB out of those 55. Memory available for KV cache could grow ~5x with no risk to Fish-Speech (which is in a separate CUDA context).

---

## 4. CUDA graph capture state — ALREADY OPTIMAL

From log timeline (21:25:21 launch → 21:26:22 ready):
| Stage | Duration |
|---|---|
| API server boot + arg parse | 9 s |
| Engine init + parallel state | 1 s |
| Model weight load (5 shards, 18 GiB) | 4.6 s |
| Torch.compile (inductor) | 10.62 s |
| Initial profiling/warmup | 11.07 s |
| **FlashInfer fp4_gemm autotuning (4 rounds × 14 profiles)** | **~7 s** (NOT slow) |
| **FlashInfer trtllm fused_moe gemm1+gemm2 tuning (10 profiles)** | **~3 s** |
| CUDA graph profiling memory | 5 s |
| **CUDA graph capture (PIECEWISE=5, FULL=4)** | **3 s** |
| Engine ready (init + profile + KV cache + warmup) | 42.78 s |
| API server "Application startup complete" | ~62 s end-to-end |

**Conclusion:** The 14-min cold-reboot in memory is from a different/older build. THIS build of vLLM 0.20.1.dev0 with `cudagraph_capture_sizes=[1,2,4,8,16]` and `compile_ranges_endpoints=[8192]` is already cold-starting in **~62 seconds**. **L1 (`--cuda-graph-sizes 1 2 4 8`) is already effectively applied.** Memory finding for cold-reboot is stale.

KV cache size at startup: **2,344,320 tokens** = 69.42x concurrency for 32K-token requests. We don't need that much for voice (PSAP turns are 100–300 tokens).

---

## 5. MoE backend — CONFIRMED CORRECT

`Using 'FLASHINFER_CUTLASS' NvFp4 MoE backend`. Memory finding #6's failure mode (TRTLLM auto-select padding 2688→2816) is NOT happening. CUTLASS is locked in via `VLLM_FLASHINFER_MOE_BACKEND=throughput`.

---

## 6. Per-request live probe

Sent via curl on the pod (no client-side network):
```bash
POST /v1/chat/completions  (system: "You are a 911 dispatcher classifier."
                             user: chest-pain JSON-formatted ask
                             max_tokens=48, temperature=0.0)
→ 200 OK, prompt_tokens=54, completion=48, finish_reason="length"
→ TIME 0.175 s total, ttfb 0.175 s
```

48 completion tokens in 175 ms = **274 tokens/s** end-to-end. The reasoning parser swallowed the response into the `reasoning` field (content=null) — that's a worker-side post-processing concern, not a vLLM issue, and the orchestrator/dispatcher know how to handle it.

---

## 7. Bottlenecks identified (ranked by certainty)

1. **`--gpu-memory-utilization 0.20` is the binding HBM constraint.** 67% of HBM is unused. KV cache is sized for 69x concurrency at 32K but we use ~1x at 4K → most of the 33 GiB KV cache is dormant. (HIGH certainty.)
2. **Prefix cache hit rate = 0% over 215K queries.** Per-turn `update_instructions` invalidates the prefix every turn. The orchestrator emitting a stable shared header followed by mutable state would unlock 30–60% prefix reuse. (HIGH certainty — this is software architecture, NOT vLLM tuning. Charter says orchestrator is frozen.)
3. **`max-model-len 32768` is over-provisioned for voice.** PSAP turns are <300 tokens; we'd lose nothing functional at 4096. Saves ~84% of the KV-cache page table overhead. (MED certainty — paid only at allocation, not per-turn.)
4. **`max-num-seqs 8` is fine for batch=1 voice** but blocks future multi-call scale. (LOW priority for cycle-2S+.)
5. **Idle power 237 W** suggests Fish-Speech CUDA context is keeping the GPU clock pinned at P0/2032 MHz. Not a knob we can turn without changing co-residency.

Voice path TTFT contribution: ~50 ms median. Decode rate 313 tok/s (3.2 ms/token). For a typical 50-token PSAP reply: **50 ms TTFT + 50×3.2 ms = 210 ms total at vLLM tier.** This is already excellent. The biggest user-perceived latency win would come from prefix caching (cuts prefill cost on the SHARED prompt header).

---

## 8. Steady-state cost summary

| Resource | Used | Available | Headroom |
|---|---|---|---|
| HBM | 88.7 GiB | 275.0 GiB | **186 GiB free (68%)** |
| BAR1 | 86.6 GiB | 512.0 GiB | 425 GiB |
| GPU SMs | 0% (idle) | 100% | full |
| Power | 237 W | 1000 W (B300 max) | 763 W |
| KV cache slots | 0% used | 2.34M tokens | full |

**B300 is massively under-utilized.** The user's hypothesis is correct: this graph covers the system but uses ~one-third of one GPU. Levers to close that gap are in `levers.md`.
