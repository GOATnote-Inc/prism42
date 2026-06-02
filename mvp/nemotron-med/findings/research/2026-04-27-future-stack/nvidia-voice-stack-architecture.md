# NVIDIA Voice-Stack Architecture for prism42 (April 2026)

**Date:** 2026-04-27 · **Status:** synthesis of 4 research agents · **Verdict:** 🟢 align to NVIDIA reference; ship in 2 phases

This brief answers: *what would NVIDIA's own solutions architect deploy this week on H200 today and B300 next?* It picks the canonical NVIDIA voice-AI stack as the spine, identifies what's actually GA in April 2026 (not vaporware), and gives concrete next-step engineering with cost + latency budgets.

## 1. Reference architecture (NVIDIA-blessed, GA today)

NVIDIA ships **`NVIDIA-AI-Blueprints/nemotron-voice-agent`** as the canonical full-stack reference. Pipeline shape:

```
caller audio → Riva ASR (Parakeet 1.1B CTC) → NeMo Guardrails (input rails)
            → Nemotron-Nano LLM (vLLM, OpenAI-compat) → NeMo Guardrails (output rails)
            → Riva TTS (Magpie Multilingual) → caller audio
```

Retrieval lane (parallel to the LLM): entity-link the utterance → nx-cugraph traversal of medical KG → NV-Embed-QA rerank → top-K context injected into the LLM prompt before output rails fire.

**Source:** [`NVIDIA-AI-Blueprints/nemotron-voice-agent`](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent), [`build.nvidia.com/nvidia/nemotron-voice-agent`](https://build.nvidia.com/nvidia/nemotron-voice-agent).

## 2. Component selection — what's GA in April 2026

| Slot | Pin | Container / package | Resident on H200 | Notes |
|---|---|---|---|---|
| ASR (streaming) | **Parakeet 1.1B CTC** | `nvcr.io/nim/nvidia/parakeet-streaming` | ~2.5 GiB | Riva canonical streaming. WER ~6-8% clean. gRPC. |
| TTS | **Magpie TTS Multilingual** | `nvcr.io/nim/nvidia/magpie-tts` | ~4-6 GiB | GA in Riva 2.15. Token-codec → lower TTFB than Fastpitch+HifiGAN. en-US + 8 others. |
| LLM | **Nemotron-Nano-30B-A3B BF16** | `vllm/vllm-openai:latest` | ~60 GiB | Already serving on pod (Team A — 186 ms / 50 tok @ conc=1). |
| Guardrails | **NeMo Guardrails v0.21.0** | `pip install nemoguardrails==0.21.0` | <1 GiB CPU | **Note:** v0.23.0 not GA as of Apr 2026; pin 0.21.0 (Mar 12 2026 stable). |
| Embeddings | **`nvidia/llama-3.2-nv-embedqa-1b-v2`** | NV-Embed-QA NIM | ~2 GiB | Med-specialized variant. ~2-4 ms/embed batch=32 on H200. |
| Reranker | **`nvidia/llama-3.2-nv-rerankqa-1b-v2`** | NV-Rerank-QA NIM | ~2 GiB | ~8-15 ms batch=8 (estimated). |
| KG (medical) | **nx-cugraph 26.04.00** | `pip install nx-cugraph-cu13` | runtime | Was 🔴 at 4K nodes (healthcraft); 🟡 → 🟢 once medical corpus is at 100K-1M nodes (SNOMED + ICD-10 + StatPearls + AHA). |
| RAPIDS ETL | **RAPIDS 26.04** | conda/pip cu13 | offline-only | cuDF for SNOMED → Parquet (30-40× Pandas). Build-time, not inference-time. |
| Runtime | **Riva server 2.15.0** | `nvcr.io/nvidia/riva/riva-speech:2.15.0` | shared | Blackwell SM 10.3 supported in 2.15. CUDA 12.x base. |

**Total resident on H200 (single GPU):** ~80 GiB, leaves ~60 GiB headroom for KV cache + cudagraph buffers. Verified fit from Team A (Nemotron BF16 alone uses 120 GiB at gpu_mem_util=0.85; lowering to 0.50 frees room for Riva + Embed + Rerank).

## 3. CUDA 13.2 reality check

User's ambition: CUDA 13.2 / nx-cugraph 26.04 / RAPIDS 26.04 as the substrate. Reality April 2026:

- **CUDA 13.2.1 GA** — installs cleanly, native sm_90 (H200) and sm_103 (B300).
- **B300 sm_103 codegen partially broken in the ecosystem**: Triton 3.4 doesn't recognize `sm_103a`; PyTorch 2.9 stable wheels lack sm_103 (need source build with `TORCH_CUDA_ARCH_LIST=10.3a`). **Affects B300 deploy, not H200.**
- **Riva 2.15 still CUDA 12.x base** — no CUDA 13.2 native container yet. Runs native on H200 SM 9.0; runs on B300 only via PTX-JIT (driver ≥545).
- **NeMo containers 25.09 / 25.11**: also CUDA 12.x base. Co-locating Riva + Parakeet + Magpie on a single pod requires either (a) multi-container orchestration or (b) waiting for unified CUDA 13.2 base images.
- **RAPIDS 26.04 cu13 wheels**: install fine; no SM 10.3 caveats at the library level.

**Implication for sprint (H200 only):** every component ships native today. No source builds, no PTX fallback drama.

**Implication for B300 (post-sprint):** plan for source-built PyTorch, expect Triton workarounds, accept Riva PTX-JIT fallback until 2026 H2 when CUDA 13.2-native Riva is expected.

## 4. Latency budget (H200, target p95 end-to-end < 1500 ms)

Voice TTFB = STT → Guardrails-input → LLM TTFT → Guardrails-output → TTS first-frame.

| Leg | Target | Source / measured |
|---|---|---|
| STT (Parakeet streaming, partial) | 100-200 ms | NVIDIA published; gRPC streaming with VAD endpointing |
| Guardrails input rail (parallel) | ≤50 ms | Parallel-rail mode; sequential adds ~150 ms |
| LLM TTFT (Nemotron BF16, vLLM) | 80-120 ms | Extrapolated from Team A 186 ms /50-tok; first token comes well before 50th |
| Guardrails output rail (streaming chunks) | 0-100 ms in critical path | Streaming-mode rails, runs concurrent with TTS chunking |
| TTS TTFB (Magpie token-codec) | 200-400 ms | Riva published; lower than Fastpitch path |
| WebRTC RTT (LK Cloud → caller) | 30-100 ms | LiveKit edge-PoP routing |
| **Total p95** | **~700-1100 ms** | Comfortably under 1500 ms target |

This is the headline number to commit to. **Voice-LLM on H200 with full NVIDIA stack hits p95 < 1.1 s end-to-end before any tuning.**

## 5. Two-phase execution plan

### Phase 1 — H200 sprint, today (this session + parallel)

Goal: working public URL with NVIDIA-stack voice loop on H200.

| Step | Owner | ETA | Blocker |
|---|---|---|---|
| Vercel public URL `prism42-h200-demo.vercel.app` | shipped | done | — |
| Worker registered as `prism42-h200` on LK Cloud | shipped | done | — |
| Nemotron BF16 vLLM serving | shipped | done | — |
| **Populate `NVIDIA_API_KEY` in `.env`** | user | 30 s | hard blocker |
| Pull `nvcr.io/nim/nvidia/parakeet-streaming` to pod | assistant | 5 min | NVIDIA_API_KEY |
| Pull `nvcr.io/nim/nvidia/magpie-tts` | assistant | 5 min | NVIDIA_API_KEY |
| Patch `worker.py`: `STT_BACKEND=riva_parakeet` (gRPC client) | assistant | 15 min | needs Parakeet NIM running |
| Patch `worker.py`: `TTS_BACKEND=riva_magpie` (gRPC client) | assistant | 15 min | needs Magpie NIM running |
| Restart worker; smoke-test from public URL with synthetic caller | assistant | 5 min | — |
| Real-user listen-test (you) | user | 1 min | — |

**Total Phase 1 wall clock with key in hand: ~50 min.**

### Phase 2 — Guardrails + KG (post-sprint, when corpus is built)

Order matters: corpus first, then KG, then Guardrails retrieval rail. Without the corpus, Guardrails fact-check is just a rate-limiter, not a clinical safety net.

1. Build the medical corpus per [`medical-corpus-skeleton.md`](medical-corpus-skeleton.md). User-led; assistant scopes only.
2. Offline KG build with RAPIDS 26.04: `cudf.read_csv(snomed_subset)` → Parquet → networkx graph → `nx_cugraph` runtime.
3. Wire NV-Embed-QA NIM + cuVS index of corpus chunks; NV-Rerank-QA on top-K.
4. NeMo Guardrails 0.21.0 with `models.yaml` pointing at vLLM OpenAI-compat endpoint; retrieval rail is a custom LangChain retriever wrapping the KG traversal.
5. Streaming-mode rails with parallel input/output execution (avoid the 150 ms sequential cost).

### Phase 3 — B300 promotion (when scribegoat-class B300 access lands)

Same containers, same wiring. Expect to revisit Triton/PyTorch source-builds for sm_103 native; Riva on PTX-JIT until late 2026.

## 6. The polite divergence from user-stated versions

Three places where user-stated pins didn't match April 2026 reality:

1. **NeMo Guardrails 0.23.0** → actual current stable is **0.21.0** (Mar 12 2026). v0.22 / v0.23 not yet GA per [`NVIDIA-NeMo/Guardrails/releases`](https://github.com/NVIDIA-NeMo/Guardrails/releases). Pin 0.21.0; revisit when 0.23 ships.
2. **CUDA 13.2 native everywhere** → CUDA 13.2.1 is GA, but Riva 2.15 / NeMo 25.09 still ship CUDA 12.x base images. CUDA 13.2 is the substrate of the *driver* and the next NeMo / Riva refresh; today's stack runs CUDA 12.x containers on a 13.2-capable driver.
3. **nx-cugraph for the prism42 graph today** → 🔴 RED at the current 4K-node healthcraft graph (below GPU break-even). 🟡 → 🟢 once the medical KG is at 100K-1M nodes per the medical-corpus build. The runtime is right; the data isn't there yet.

None of this changes the strategic answer (align to NVIDIA's reference). It just means we sequence: ship Riva today, sequence Guardrails 0.21.0 + KG when the corpus is ready, and re-pin to 0.23+ / CUDA-13.2-native containers when those land.

## 8. Sovereign-stack thesis (2026-04-27 update)

The product is a 911 dispatch backup that **must keep working when Cloudflare / AWS / cloud-SaaS layers fail.** That elevates "follow NVIDIA's reference architecture" from a preference to a hard rule: NVIDIA is the trust anchor at the bottom of the stack. Cloud STT / TTS / LLM are acceptable as *fallbacks*; they cannot be the canonical path.

### 8.1 H100 PCIe 80 GB fit (the substitute for the lost B300)

The production target is B300; the working substitute today is the H100 PCIe pod (`prism-mla-h100`, 62.169.159.15). The same NVIDIA-blessed components fit:

| Component | VRAM on H100 PCIe | Notes |
|---|---|---|
| Parakeet 1.1B CTC (NIM) | ~2.5 GB | gRPC streaming, telephony-tuned. **Upgrade from `parakeet-tdt-0.6b-v3` (3.3 GB) currently running.** |
| Magpie TTS Multilingual (NIM) | ~5 GB | gRPC, 200-400 ms TTFB. Replaces ElevenLabs / StyleTTS2+BigVGAN as the canonical sovereign TTS. |
| Nemotron-Nano-30B-A3B **FP8** (vLLM 0.12+) | ~32 GB | NVIDIA's blessed quantization for Hopper SM 9.0 (NVFP4 is Blackwell-only). 1-2% accuracy delta vs BF16 for ~2× throughput. |
| Headroom for KV cache + cudagraph | ~40 GB | comfortable |

Total resident: ~40 GB out of 80 GB. Leaves the BF16 fallback (60 GB) accessible if FP8 accuracy regresses on a clinical eval.

### 8.2 Cloudflare + Tailscale dual-stack ingress

Cloudflare-down resilience requires more than CF Tunnel. Three-tier ingress that degrades gracefully:

| Tier | Path | Latency | Survives "CF down"? |
|---|---|---|---|
| 1 (primary) | CF Tunnel: `cloudflared tunnel run prism42-h100` → `prism42-h100.thegoatnote.com` | 30-100 ms | no |
| 2 (secondary) | Tailscale Funnel: `tailscale serve http://localhost:7880` | 10-50 ms | yes (Tailscale's coordination plane is independent) |
| 3 (on-site fallback) | Direct UDP WebRTC over the pod's static IPv4 (62.169.159.15:7880) | 0-20 ms | yes (no internet intermediary) |

Tier 3 is the canonical 911 dispatch deployment — local fiber from the dispatch console to the pod, no internet at all between caller and AI. Tiers 1 and 2 are public demo / remote-test paths. Worker config publishes both as alternatives the LiveKit room can negotiate.

### 8.3 What's still BLOCKED on the medical-corpus build

The retrieval lane is the half of the architecture that requires real data, not just real runtime:

- nx-cugraph 26.04 substrate is fine, but the graph it traverses is empty. Seed-graph-of-100-nodes (top-50 911 chief complaints + top-30 MPDS-9 protocol references + top-20 ICD-10 codes + 150 edges) is the minimum-viable demonstration that lands TODAY without the full SNOMED/StatPearls/ICD-10 license trail. See `data/seed_kg/` (this commit cycle).
- NV-Embed-QA + NV-Rerank-QA NIMs are on standby — wire-able now, but they only earn their VRAM cost once the corpus has indexable mass.
- NeMo Guardrails *retrieval* rail (medical fact-check) is blocked on the corpus too; the input + output rails (jailbreak / off-topic / unsafe medical advice) ship now via `agents/livekit/guardrails_wrapper.py`.

Sequence stays: corpus → KG → retrieval rail → fact-check Guardrails rail. Input/output rails do not wait.

## 7. References

- [NVIDIA-AI-Blueprints/nemotron-voice-agent](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent)
- [Riva 2.15 release notes](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/release-notes.html)
- [Magpie TTS overview](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tts/tts-overview.html)
- [NeMo Guardrails 0.21 docs](https://docs.nvidia.com/nemo/guardrails/latest/index.html)
- [Guardrails streaming safety blog](https://developer.nvidia.com/blog/stream-smarter-and-safer-learn-how-nvidia-nemo-guardrails-enhance-llm-output-streaming/)
- [NV-Embed-QA / NV-Rerank-QA NIMs](https://docs.nvidia.com/nim/benchmarking/llm/latest/performance.html)
- [nx-cugraph zero-code accel](https://developer.nvidia.com/blog/networkx-introduces-zero-code-change-acceleration-using-nvidia-cugraph/)
- [NVIDIA context-aware-rag](https://github.com/NVIDIA/context-aware-rag)
- [CUDA 13.2 release notes](https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html)
- [Blackwell compatibility guide](https://docs.nvidia.com/cuda/blackwell-compatibility-guide/)
- Existing prism42 briefs: [`rapids-26.04.md`](rapids-26.04.md), [`nx-cugraph-26.04.md`](nx-cugraph-26.04.md), [`tensorrt-llm-on-b300.md`](tensorrt-llm-on-b300.md), [`cosmos-reason2-2b.md`](cosmos-reason2-2b.md), [`h200-bench-team-a.md`](h200-bench-team-a.md), [`medical-corpus-skeleton.md`](medical-corpus-skeleton.md)
