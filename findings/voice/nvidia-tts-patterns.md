# NVIDIA production-TTS patterns for B300 + co-residency

Researched 2026-04-25 from publicly indexed NVIDIA docs, NVIDIA AI Blueprints, NVIDIA developer blog, Pipecat reference repos, Daily.co engineering blog, and the NVIDIA NIM Speech support matrix. Stack we are stuck on: Fish Speech S2-Pro standalone HTTP service on B300 (sm_103, Blackwell Ultra), co-resident with vLLM 0.20 + Nemotron-3-Nano NVFP4 + Parakeet TDT v3, measured TTS TTFB p95=2627ms / RTF=2.07. SOTA bar is <300ms TTFB.

Independent of prior expert-wiring research at `~/prism42/findings/b300_bench/nvidia-research/expert-wiring.md` which covered Nemotron LLM tuning. This file is orthogonal — TTS, STT, and same-GPU multi-model co-residency.

## Bottom line (must answer)

**NVIDIA's published TTFB for production streaming TTS on Blackwell:** **55.1 ms first-chunk latency at 1 stream**, **63.77 ms at 8 streams**, **126.24 ms at 32 streams**, **184.15 ms at 64 streams** for **Magpie TTS Multilingual** on **B200 (sm_100)** measured via Riva NIM TTS perf client [ref #2, retrieved 2026-04-25, last updated 2026-04-20]. **No published B300/sm_103 numbers exist for Magpie-TTS as of 2026-04-25.** Riva FastPitch+HiFiGAN on H100 single-stream is **21.5 ms TTFB** [ref #1] but FastPitch is the previous-generation legacy stack — Magpie has replaced it in NVIDIA's current voice-agent reference.

**NVIDIA's sanctioned pattern for TTS + LLM + STT on one GPU:** The official NVIDIA Nemotron Voice Agent Blueprint **does not co-resident them on one GPU** — it uses **4× H100** with one-Parakeet, one-Magpie, two-Nemotron-3-Nano [ref #3, ref #6]. The sanctioned same-GPU pattern when you must share is **CUDA MPS / MLOPart** (Memory Locality Optimized Partition), with B300 specifically rated for **2 MLOPart devices per GPU, ~70 SMs each on the 148-SM HGX B200 chip** [ref #4]. Triton dynamic-batching + multiple `instance_group` is the alternative when all models live in one Triton process.

**The single biggest pattern we are missing that NVIDIA has published:** **Speculative speech processing as a streaming-pipeline technique** — interleave the LLM-first-segment (capped to ~24 tokens) with TTS warm-start so audio rendering begins before LLM finishes the response. NVIDIA's Pipecat reference target is **500-700ms V2V on a server-side measurement** with **TTS first audio at ~370ms** even when each leg's own service-level TTFB is higher [ref #7]. Our Fish 2627ms TTFB is fundamentally a service-side latency problem, but the speculative-speech wrapper would still mask it during the early conversation turn, buying us ~150-200ms of perceived latency relief without touching Fish itself.

---

## NVIDIA Riva TTS — current state

NVIDIA has migrated their reference TTS twice in 18 months. Riva ships three published architectures — only one is current.

### Generation 1: FastPitch + HiFi-GAN (legacy, 2024-2025)
- **Architecture:** non-autoregressive acoustic model (FastPitch) + GAN vocoder (HiFi-GAN).
- **TTFB:** **A100 single stream 22 ms / H100 single stream 21.5 ms / T4 single stream 17 ms**, all FastPitch+HiFi-GAN [ref #1].
- **Throughput (RTFX):** A100 150.8, H100 162, T4 185 [ref #1].
- **Streaming protocol:** gRPC bidi-streaming via riva_tts_perf_client; one `Synthesize` call returns audio chunks as they're generated [ref #1].
- **Status as of 2026-04:** still supported in Riva, but no longer the model of record for new voice-agent reference builds. The Daily/NVIDIA Pipecat collab from 2025-01 was the last reference build that quoted FastPitch+HiFi-GAN [ref #5]. Tag: **verified-on-Hopper-and-pre-Hopper, not benchmarked-on-Blackwell.**

### Generation 2: Magpie-TTS family (current, 2026)
- **Architecture:** streaming encoder-decoder transformer. **Causal Transformer Encoder (6 layers)** + **Causal Transformer Decoder (12 layers)**, multi-codebook prediction (typically 8 codebooks) with optional local-transformer refinement, attention priors, classifier-free guidance, GRPO alignment [ref #8, ref #9]. **357 M parameters** for the Multilingual variant [ref #8].
- **Variants:** Magpie TTS Multilingual (357M, 9 languages with Hindi/Japanese added v2602 2026-03-03), Magpie TTS Zeroshot (voice-cloning), Magpie TTS Flow (offline-only) [ref #8, ref #10].
- **License:** **NVIDIA Open Model License Agreement (`nvidia-open-model-license`)** [ref #8]. Permissive but NOT BSD/Apache — requires explicit acceptance, attribution, and downstream-distribution rules.
- **TTFB published numbers (Riva NIM perf-client, 20 iterations × 10 LJSpeech inputs, avg of 3 trials [ref #2]):**

  | Hardware | Streams | First-chunk (ms) | Inter-chunk (ms) | RTFX |
  |---|---|---|---|---|
  | **H100** (sm_90) | 1 | **70.0** | 13.22 | 8.78 |
  | H100 | 8 | 76.04 | 13.31 | 72.05 |
  | H100 | 32 | 128.6 | 28.39 | 150.4 |
  | H100 | 64 | 231.26 | 66.08 | 192.18 |
  | **B200** (sm_100) | 1 | **55.1** | 3.55 | 11.78 |
  | B200 | 8 | 63.77 | 9.08 | 76.09 |
  | B200 | 32 | 126.24 | 31.62 | 172.14 |
  | B200 | 64 | 184.15 | 48.66 | 180.81 |
  | DGX Spark (sm_121) | 1 | 61.31 | 6.35 | 7.67 |
  | DGX Spark | 64 | 704.95 | 210.05 | 51.74 |

  Tag: **verified-on-Hopper-sm_90, verified-on-Blackwell-sm_100, NOT verified-on-Blackwell-sm_103 (B300).**

- **Streaming protocol:** gRPC bidirectional streams via Riva NIM; concurrent stream handling caps at 64 per process [ref #2, ref #6].
- **Co-residency footprint:** Multilingual at batch_size=8 needs **10.87 GB GPU memory**, batch_size=32 needs **31.55 GB**, batch_size=64 needs **60.224 GB** [ref #11]. Useful for sizing against B300's 275 GB / 288 GB HBM3e.
- **Critical constraint we found in third-party reporting:** one third-party search-summary aggregation claimed "Magpie TTS Multilingual is not supported on Blackwell platform" and "Blackwell platform currently supports only batch_size=1 in the latest release." **The official NVIDIA support matrix at `docs.nvidia.com/nim/speech/latest/reference/support-matrix/tts.html` does NOT carry this restriction** [ref #11]. NVIDIA's own NIM perf docs publish B200 numbers up to 64 streams [ref #2]. Treat the third-party claim as **likely incorrect or outdated**, but worth a sanity check on B300 specifically before betting the deployment on it.

### Generation 3: Nemotron Speech TTS Magpie (forthcoming/in NeMo, 2026)
- The Nemotron Voice Agent reference [ref #3] and `NVIDIA/voice-agent-examples` repo [ref #6] consistently use the term "Nemotron Speech TTS Magpie" rather than "Riva Magpie TTS." Plausible read: the Nemotron pipeline pulls Magpie weights through NeMo / Pipecat directly, bypassing Riva NIM. Same model architecture, different serving path. No published independent benchmark for the Nemotron-served Magpie path on B200/B300 as of 2026-04-25.

---

## NVIDIA voice-agent reference blueprints

### A. Nemotron Voice Agent (the current canonical NVIDIA reference, 2026-Q1)

**Source:** `github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent` [ref #6], NVIDIA Build catalog [ref #3], Daily.co Jan-2026 collab post [ref #5], Pipecat `nemotron-january-2026` repo [ref #7], Hugging Face NVIDIA Nemotron Speech ASR scaling post 2026-01-05 [ref #12]. Cross-referenced 2026-04-25.

**Architecture (4× H100 reference deployment) [ref #3]:**
| GPU | Model |
|---|---|
| H100 #1 | Parakeet CTC 1.1 B (STT) |
| H100 #2 | Magpie TTS (Multilingual or Streaming variant) |
| H100 #3 | Nemotron-3-Nano LLM (shared with #4) |
| H100 #4 | Nemotron-3-Nano LLM (shared with #3, TP=2) |

**E2E latency claim:** "sub-second End-to-End Latency across up to 64 parallel streams with speculative speech processing enabled" [ref #3].

**Per-leg measured numbers (Daily.co validation post, 2026-01-05) [ref #5]:**
- ASR (Nemotron Speech ASR): **median 24 ms time-to-final-transcript**, independent of utterance length. Measured on H100 → 560 concurrent streams at 320 ms chunk size [ref #12].
- LLM first segment: **100-150 ms** (Nemotron-3-Nano, ~24 token cap on first segment) [ref #7].
- TTS first audio: **~370 ms** in Pipecat conservative streaming preset [ref #7].
- **V2V on RTX 5090 (consumer reference):** Min 415 ms / **p50 508 ms** / p90 544 ms / Max 639 ms [ref #5].
- V2V on DGX Spark (sm_121): Min 759 ms / **p50 1180 ms** / p90 1359 ms / Max 2981 ms [ref #5].

**No B200/B300 V2V published.** Daily/NVIDIA's reference benchmarks only cover RTX 5090 and DGX Spark on the consumer side and 4× H100 on the datacenter side. The 4× H100 setup is "sub-second" without a specific p50 quoted. Tag: **verified-on-Hopper-sm_90 + RTX-5090-sm_120 + DGX-Spark-sm_121, claimed-but-unverified-on-Blackwell-datacenter (B200/B300).**

### B. Tokkio (digital-human / 3D-avatar reference, 2024 → 5.0 in 2026)

**Source:** `docs.nvidia.com/ace/tokkio/5.0/reference-workflow/reference-workflow.html` [ref #13]. Cross-referenced 2026-04-25.

- **Pipeline:** five subsystems — Streaming, Animation, Vision, Audio, Fulfillment. Audio = Riva ASR + Riva TTS + LLM. Vision = NVIDIA Maxine. Animation = Audio2Face-3D.
- **Orchestrator:** Python-native ACE Controller (Tokkio 5.0 Beta).
- **Hardware:** "T4 / L4 / A10 minimum" with scaling 1-6 concurrent streams, "1 stream = 2× GPU, 3 streams = 4× GPU" [ref #13]. **No latency numbers published in the public docs.**
- **TTS used:** generic "Text-to-speech processor" — public docs do not name Magpie or FastPitch.
- **Status:** legacy/avatar-focused; the Nemotron Voice Agent is now NVIDIA's first-class voice-only reference, Tokkio is the avatar superset. Skip Tokkio for our 911 voice path; cross-reference only if an avatar surface is added later.

### C. Pipecat Voice Agent Framework Blueprint (Pipecat-NVIDIA collab)

**Source:** `build.nvidia.com/pipecat/voice-agent-framework-for-conversational-ai` (timed out at fetch, retrieved via search aggregation [ref #14]) and Pipecat's own `nemotron-january-2026` reference [ref #7].

- **Stack:** Pipecat orchestrator + Daily WebRTC transport + NVIDIA Riva STT (Parakeet) + NVIDIA FastPitch-HifiGAN TTS NIM + Llama 3.3-70B-Instruct (in Daily/NVIDIA Jan-2025 build, [ref #15]) → migrated to Magpie + Nemotron-3-Nano in the Jan-2026 build [ref #7].
- **Key pattern (Pipecat doc):** **buffered LLM service emits text at sentence boundaries**; first segment is capped to **`first_segment_max_tokens: 24`**, subsequent at **`segment_max_tokens: 32`** with **`segment_hard_max_tokens: 96`**. **100% KV cache reuse across turns** via single-slot LLM operation.
- **Per-leg measured (server-side, single 4×H100 box) [ref #7]:**
  - VAD silence detection: ~200 ms (caller stopped earlier — VAD lag).
  - STT final transcription: 30-50 ms + 320 ms server padding for context.
  - LLM context processing: ~0 ms on subsequent turns (cached).
  - LLM first segment: 100-150 ms (24-token limit).
  - TTS first audio: **~370 ms** (conservative streaming preset).
  - **Total V2V: 500-700 ms** measured at `BotStartedSpeakingFrame`.

### D. Audio2Face-3D (lip-sync, not TTS but ships in voice pipelines)

**Source:** `docs.nvidia.com/ace/audio2face-3d-microservice/latest/text/architecture/audio2face-ms.html` [ref #16].

- **Architecture:** containerized NIM, gRPC bidi-streaming, **30 inferences per second** of audio output. Stream rates can run faster than realtime ("300 FPS in logs = 10 sec audio per 1 sec compute") [ref #16].
- **Latency note:** "higher stream rates can introduce a brief initial latency due to extra buffering" but does not persist [ref #16].
- **Not relevant to our voice-only stack** — Audio2Face is consumed downstream of TTS, doesn't help the TTFB problem. Listed only because expert-wiring research mentions it; our stack has no avatar surface.

---

## Multi-model co-residency on a single GPU — NVIDIA's sanctioned answer

The reference Nemotron Voice Agent uses **4 separate H100s** [ref #3]. When you cannot afford 4 GPUs and must share, NVIDIA publishes three patterns. **None of them is a free lunch.**

### Pattern 1: CUDA MPS / MLOPart (the closest thing to "sanctioned same-GPU sharing")

**Source:** `developer.nvidia.com/blog/boost-gpu-memory-performance-with-no-code-changes-using-nvidia-cuda-mps` [ref #4], retrieved 2026-04-25.

- **What it is:** Memory Locality Optimized Partition. Splits a Blackwell GPU along the **die boundary** into 2 logical devices. NVIDIA explicitly: "NVIDIA DGX B200 and NVIDIA B300 are capable of two MLOPart devices per GPU" [ref #4].
- **B300 partition arithmetic:** Each B300 → 2 MLOPart devices. B200 has 148 SMs / GPU → 70 SMs per MLOPart partition (the doc-quoted example was an HGX B200 8-GPU system showing 16 MLOPart devices × 70 SMs each). B300 has 160 SMs total → ~80 SMs per partition.
- **Measured gain (from NVIDIA's own blog):** average atomic-op kernel latency went from 2,314.54 ms without MLOPart to **1,480.79 ms with MLOPart enabled — 36% improvement** [ref #4]. Peer-to-peer bandwidth between MLOPart devices on the same GPU: **~2,350 GB/s** (vs ~760 GB/s cross-GPU NVLink) [ref #4].
- **Limitations vs MIG:** "MLOPart **doesn't require superuser privilege** and operates per-user / per-server" but **lacks strict isolation** — "memory from one MLOPart device may corrupt another on the same GPU" [ref #4]. MIG is system-wide and gives strict isolation; MLOPart is the user-level / non-disruptive sibling.
- **Tag:** **verified-on-Blackwell-sm_100 (B200) and sm_103 (B300) per NVIDIA's own statement.** This is the cleanest "Blackwell-sanctioned" co-residency answer we have.

### Pattern 2: Triton dynamic batching with multiple `instance_group` definitions

**Source:** `docs.nvidia.com/deeplearning/triton-inference-server/.../tutorials/Conceptual_Guide/Part_2-improving_resource_utilization` [ref #17], retrieved 2026-04-25.

- **What it is:** put TTS, LLM, STT models into one Triton process. Each model gets its own `instance_group` with `count: N, kind: KIND_GPU, gpus: [0]`. Triton's scheduler interleaves requests across models on the same GPU, plus dynamic batching combines simultaneous requests within each model.
- **Measured gain (NVIDIA's own numbers):** dynamic batching alone — throughput **975 → 3,188 infer/s at 16 concurrent requests**, latency **34,035 µs → 10,567 µs** (3.2× throughput, 3.2× latency improvement) [ref #17]. Numbers are for a text-recognition demo, not a TTS+LLM mix; the architecture-level claim is the principle, not the absolute number.
- **Voice-specific pattern (search aggregation, [ref #18]):** "interleaving small segments of LLM and TTS inference so that GPU resources are dedicated to one model at a time significantly reduces time-to-first-token for each model." This is the same idea as Pipecat's `first_segment_max_tokens=24` cap [ref #7] — interleaved at scheduler level rather than service level.
- **Tag:** **verified-general-Triton-pattern, NOT verified-on-Blackwell-sm_103-with-our-specific-stack.**

### Pattern 3: CUDA stream priority (the underwhelming one)

**Source:** NVIDIA Developer Forums [ref #19], CUDA Programming Guide async-execution chapter.

- **What it is:** assign higher CUDA stream priority to interactive (TTS) and lower priority to batch (LLM prefill).
- **The hard truth:** "Stream priorities will not preempt already executing work, or guarantee any specific execution order. More specifically, stream priorities provide a hint to preferentially run work with higher priority when possible, but **do not preempt already-running work**" [ref #19].
- **Scope limit:** "only compute kernels launched in priority streams are affected by the stream's priority" — H2D/D2H memcpy is unaffected [ref #19].
- **What this means for our stack:** stream priority alone will **not** rescue Fish-Speech from a long-running vLLM kernel. It is a hint, not a preemption. Mention only because forum threads keep pointing voice teams here; the actual answer is MPS/MLOPart (Pattern 1).

### Pattern 4 (sanctioned by absence): just use 4 GPUs

NVIDIA's own canonical Nemotron Voice Agent is 4× H100 [ref #3]. They *did not* publish a 1-GPU-shared reference. Read this as a signal: **NVIDIA does not believe TTS-LLM-STT same-GPU is the right answer for production at any latency above the demo tier.** The published path on Blackwell when you need <500 ms V2V is buy-the-extra-silicon, not share-the-die.

---

## Magpie-TTS / open NVIDIA streaming TTS — comparison vs Fish-Speech S2-Pro

| Dimension | NVIDIA Magpie TTS Multilingual | Fish Speech S2-Pro |
|---|---|---|
| Architecture | Causal encoder-decoder transformer (6L+12L), multi-codebook | Diffusion-based vocoder + GPT-style text encoder |
| Parameters | 357 M | ~1.5 B (S2-Pro) |
| License | NVIDIA Open Model License Agreement | BSD-3 |
| Languages | 9 (En, Es, De, Fr, Vi, It, Zh, Hi, Ja) v2602 | 8 (En, Zh, Ja, Ko, Es, De, Fr, Ar) |
| Published TTFB on B200 (1 stream) | **55.1 ms** (NVIDIA NIM perf doc) | none published; our measurement: **2627 ms p95** |
| Published TTFB on B200 (64 streams) | 184.15 ms | n/a (we don't run >1) |
| RTFX (B200, 1 stream) | 11.78 | our measurement: **0.48** (RTF 2.07) |
| Streaming protocol | gRPC bidi via Riva NIM, or NeMo/Pipecat direct | HTTP service (custom; not gRPC) |
| Voice cloning | Yes (Zeroshot variant) | Yes (S2-Pro fine-tune) |
| Co-residency footprint | Multilingual @ batch=8: 10.87 GB; batch=32: 31.55 GB; batch=64: 60.224 GB | not published; our measurement: ~20 GB |
| Integration cost into LiveKit-Agents | High — no `livekit-plugins-nvidia-tts` exists yet (only STT side has `livekit-agents[nvidia]~=1.4`); requires writing a TTS plugin that speaks Riva gRPC | Already integrated (`livekit-plugins-fishaudio`) |

**Magpie-TTS is ~47× faster TTFB than Fish-S2-Pro on the same B200-class hardware.** The license is permissive but NVIDIA-specific (not BSD-3 like Fish). The integration cost into our LiveKit stack is real — NVIDIA ships a STT plugin for LiveKit but not a TTS plugin yet (as of 2026-04). A Magpie cutover means writing a TTS plugin or proxying through the OpenAI-compatible TTS surface.

---

## Specific patterns to retrofit into our prism42 stack

For each: pattern name, what it solves, NVIDIA citation, retrofit effort, predicted gain.

### P1. Speculative speech processing — buffered LLM with sentence-boundary emission

- **What it solves:** masks Fish's 2627 ms TTFB by starting TTS render before LLM completes.
- **Citation:** Pipecat `nemotron-january-2026` `streaming-pipeline-architecture.md` [ref #7]. Specifically `first_segment_max_tokens: 24` + `segment_max_tokens: 32` + sentence-boundary buffered emission.
- **Retrofit effort:** **Medium.** Already partially present in livekit-agents 1.5+ as `preemptive_generation` and `preemptive_tts`. The piece we are not yet using is the **token-cap on first segment** — 24 tokens hard limit on the first LLM emission so TTS-1 fires within 100-150 ms of LLM-1.
- **Predicted gain:** S-M on perceived V2V latency. Does not fix Fish; masks it.

### P2. CUDA MPS / MLOPart partition for TTS isolation

- **What it solves:** keep Fish-Speech kernels off the same SM-pool as vLLM Nemotron, so vLLM's CUDA-graph capture or a long Mamba-2 kernel cannot block Fish's vocoder kernel for hundreds of ms.
- **Citation:** NVIDIA developer blog "Boost GPU Memory Performance with No Code Changes Using NVIDIA CUDA MPS" [ref #4]. **B300 supports 2 MLOPart partitions; per-partition ~80 SMs and ~128 GB HBM3e** (half of B300's 256 GB usable). Measured 36 % latency improvement on the cited atomic-op kernel.
- **Retrofit effort:** **Medium-Low.** Set `CUDA_VISIBLE_DEVICES` per-process after enabling MLOPart on the B300 host. No code changes inside Fish or vLLM. Restart-required.
- **Predicted gain:** **L on tail latency** if our 2627 ms p95 is being inflated by vLLM CUDA-graph capture or Triton kernel co-location. **S on p50** if Fish is just slow on its own (likely the actual ceiling).
- **Risk:** "memory from one MLOPart device may corrupt another on the same GPU" [ref #4]. Strict isolation requires MIG (which is system-wide and disruptive on B300). For a research/MVP phase, MLOPart is the right tier.

### P3. Switch TTS service from Fish-S2-Pro to Magpie-TTS Multilingual

- **What it solves:** the actual TTFB ceiling. NVIDIA's own B200 number is 55.1 ms vs our 2627 ms — **47× faster**.
- **Citation:** NVIDIA NIM Speech TTS performance docs [ref #2], retrieved 2026-04-25, measurement methodology = 20 iterations × 10 LJSpeech inputs per concurrent stream, 3-trial averaging.
- **Retrofit effort:** **High.** No `livekit-plugins-nvidia-tts` exists yet. Three integration paths:
  1. Run Magpie TTS NIM as a Riva microservice, write a custom LiveKit TTS plugin that speaks Riva gRPC.
  2. Run Magpie via NeMo / Pipecat direct, expose an OpenAI-compatible HTTP surface, point `livekit-plugins-openai`-style TTS at it.
  3. Run Magpie inside the same LiveKit-Agents Python worker as a direct in-process TTS, bypassing the network round-trip.
- **License caveat:** NVIDIA Open Model License Agreement, not BSD-3. Acceptable for a research-mode product; review before commercial-use commit.
- **Predicted gain:** **L on TTFB** — this is the biggest single lever in this entire research. Cuts TTFB from 2627 ms p95 to a target ~60-100 ms p95 on B300, with the caveat that no B300 number is yet published.

### P4. Pin LLM to one MLOPart partition, TTS+STT to the other

- **What it solves:** isolates the long-tail vLLM CUDA-graph capture (14-min boot, captures graphs for batch sizes 1-512) from the time-sensitive TTS path.
- **Citation:** Combination of [ref #4] (MLOPart on B300) and [ref #17] (Triton multi-instance instance_group).
- **Retrofit effort:** **Medium.** Requires restarting all 3 services with explicit `CUDA_VISIBLE_DEVICES` after enabling MLOPart on the host. Plus a small runbook change — vLLM expects 1 GPU device-id, will see partition-0; Fish/Parakeet bind to partition-1. Both partitions still expose ~128 GB HBM3e — well above the 56 GB vLLM and 32 GB Fish+Parakeet need.
- **Predicted gain:** **M-L on tail latency.** Cleanest answer to the "Fish kernel and vLLM Mamba-2 kernel fight for the same SM pool" risk that expert-wiring [b300_bench/nvidia-research/expert-wiring.md] flagged for sm_103.

### P5. Triton multi-model instance_group co-residency (alternative to P4)

- **What it solves:** same problem as P4, different mechanism. Run TTS + STT inside one Triton process, with `instance_group { count: 1, kind: KIND_GPU }` per model. Triton's scheduler interleaves at micro-batch level.
- **Citation:** Triton concurrent model execution doc [ref #17].
- **Retrofit effort:** **High.** Requires re-exporting Fish and Parakeet to Triton-compatible model repos (TensorRT or PyTorch backend). Not zero — Fish is currently a pure HTTP service.
- **Predicted gain:** **M.** Probably not worth doing if P4 (MLOPart) is sufficient. List for completeness.

### P6. Server-side timing instrumentation per leg, p50/p95/p99

- **What it solves:** today we report a single TTFB number. Pipecat's reference [ref #7] separates: VAD latency, STT-final-transcript latency, LLM-first-segment latency, TTS-first-audio latency, BotStartedSpeakingFrame V2V. Without per-leg breakdown we cannot tell whether P2/P4 is the right intervention or whether P3 (replace Fish) is the only path.
- **Citation:** [ref #7], [ref #5].
- **Retrofit effort:** **Low.** Add per-leg timestamps to existing logging.
- **Predicted gain:** **N/A — measurement, not optimization.** But required to attribute any gain from P1-P5.

### P7. Sentence-boundary chunking on the TTS service input (not just output)

- **What it solves:** Fish today receives the full LLM response and renders sequentially. If we chunk the LLM output at sentence boundaries and stream each chunk into Fish independently, Fish can render-and-emit chunk-1 while still receiving chunk-2.
- **Citation:** Pipecat reference [ref #7] documents `BufferedLLMService` with `first_segment_max_tokens: 24` and `segment_hard_max_tokens: 96`. The pattern works for any TTS, not just Magpie.
- **Retrofit effort:** **Low-Medium.** A LiveKit-Agents Python worker change. Already partially present as livekit-agents 1.5 `preemptive_tts`.
- **Predicted gain:** **S-M on perceived TTFB** even if Fish's per-chunk render time is unchanged. Hides part of the 2627 ms behind the LLM stream.

---

## What NVIDIA has NOT published (gaps we found)

- **No B300/sm_103-data-center benchmark of Magpie-TTS Multilingual as of 2026-04-25.** Riva NIM perf docs cover A100, H100, L40, B200, DGX Spark; not B300 [ref #2].
- **No published V2V latency on B200 or B300 for the Nemotron Voice Agent.** Daily.co's 2026-01-05 post quoted only RTX 5090 (consumer) and DGX Spark (sm_121); 4× H100 was "sub-second" without a p50 [ref #5, ref #12].
- **No Riva voice-agent reference that explicitly co-resides TTS + LLM + STT on one B300 with MLOPart.** The Nemotron Voice Agent reference uses 4 separate H100s [ref #3]. MLOPart is documented for compute-isolation generally, not as a TTS co-residency recipe.
- **No livekit-plugins-nvidia-tts** package on PyPI as of 2026-04. There is `livekit-agents[nvidia]~=1.4` for STT (Parakeet via Riva) but the TTS side requires writing a plugin.
- **No published comparison of Magpie-TTS to Fish-Speech, XTTS, Cartesia, ElevenLabs on identical hardware.** All TTS perf comparisons are self-reported per-vendor on different hardware.

---

## Sources

All retrieval dates 2026-04-25.

1. **NVIDIA Riva — TTS Performance.** `https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tts/tts-performance.html` — FastPitch+HiFi-GAN benchmarks on A100 / H100 / T4 / L4 / L40 / V100. Riva 2.15.0 on-prem, 2.4.0 cloud. No Blackwell (B200/B300) results.
2. **NVIDIA Speech NIM Microservices — TTS NIM Performance.** `https://docs.nvidia.com/nim/speech/latest/reference/performances/tts/performance.html` — Magpie TTS Multilingual + Zeroshot + Flow benchmarks on A100, H100, L40, B200, DGX Spark. Last updated 2026-04-20.
3. **NVIDIA Build catalog — Nemotron Voice Agent Blueprint.** `https://build.nvidia.com/nvidia/nemotron-voice-agent` — 4× H100 layout (Parakeet + Magpie + 2× Nemotron-3-Nano), "sub-second E2E across 64 parallel streams with speculative speech processing."
4. **NVIDIA Developer Blog — Boost GPU Memory Performance with No Code Changes Using NVIDIA CUDA MPS.** `https://developer.nvidia.com/blog/boost-gpu-memory-performance-with-no-code-changes-using-nvidia-cuda-mps` — MLOPart on B200/B300 (2 partitions per GPU, ~70 SMs each on HGX B200 example), 36 % atomic-op latency improvement, 2,350 GB/s peer-to-peer same-GPU bandwidth, MIG-vs-MLOPart isolation tradeoff.
5. **Daily.co Blog — Building Voice Agents with NVIDIA Open Models.** `https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/` — Published 2026-01-05. RTX 5090 V2V p50 508 ms, DGX Spark V2V p50 1180 ms. ASR median 24 ms. TTS pipeline-mode p50 101 ms (RTX 5090).
6. **GitHub — NVIDIA-AI-Blueprints/nemotron-voice-agent.** `https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent` — Reference implementation, Pipecat + WebRTC, Nemotron Speech ASR Parakeet + Magpie TTS + Nemotron-3-Nano LLM.
7. **GitHub — pipecat-ai/nemotron-january-2026, streaming-pipeline-architecture.md.** `https://github.com/pipecat-ai/nemotron-january-2026/blob/main/docs/streaming-pipeline-architecture.md` — V2V 500-700 ms target; per-leg breakdown VAD ~200 ms / STT 30-50 ms / LLM 100-150 ms / TTS ~370 ms; `first_segment_max_tokens: 24`, `segment_max_tokens: 32`, `segment_hard_max_tokens: 96`; 100% KV cache reuse single-slot LLM.
8. **Hugging Face — nvidia/magpie_tts_multilingual_357m.** `https://huggingface.co/nvidia/magpie_tts_multilingual_357m` — Architecture (6L causal encoder + 12L causal decoder), 357M params, NeMo Framework 25.11 runtime, NVIDIA Open Model License, MagpieTTS v2602 released 2026-03-03 with Hindi/Japanese.
9. **NVIDIA NeMo Framework User Guide — Magpie-TTS.** `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tts/magpietts.html` — multi-codebook prediction, attention priors, classifier-free guidance, GRPO alignment; streaming encoder-decoder.
10. **NVIDIA Build — magpie-tts-multilingual model card.** `https://build.nvidia.com/nvidia/magpie-tts-multilingual/modelcard` — variant list (Multilingual / Zeroshot / Flow), language coverage, NIM container.
11. **NVIDIA NIM Speech — TTS Support Matrix.** `https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/tts.html` — Hardware × model × precision × batch_size matrix. Magpie TTS Multilingual batch=8 needs 10.87 GB, batch=32 needs 31.55 GB, batch=64 needs 60.224 GB. No "not supported on Blackwell" statement on this canonical page (contrary to one third-party search aggregation).
12. **Hugging Face Blog — Scaling Real-Time Voice Agents with Cache-Aware Streaming ASR (NVIDIA).** `https://huggingface.co/blog/nvidia/nemotron-speech-asr-scaling-voice-agents` — Published 2026-01-05. H100 560 concurrent streams at 320 ms chunk; DGX B200 "up to 2× throughput" vs H100 at 160-320 ms configs; ASR median 24 ms time-to-final-transcript; Cache-Aware FastConformer-RNNT eliminates redundant overlap, 3× efficiency vs buffered streaming.
13. **NVIDIA ACE — Tokkio 5.0 Reference Workflow.** `https://docs.nvidia.com/ace/tokkio/5.0/reference-workflow/reference-workflow.html` — 5-pipeline architecture (Streaming/Animation/Vision/Audio/Fulfillment), Python-native ACE Controller orchestrator, T4/L4/A10 minimum, no published latency.
14. **NVIDIA Build — Pipecat Voice Agent Framework Blueprint.** `https://build.nvidia.com/pipecat/voice-agent-framework-for-conversational-ai` — Pipecat-NVIDIA collab. (Page timed out at fetch on 2026-04-25; data sourced from search aggregations citing the same content.)
15. **Daily.co Blog — Daily and NVIDIA collaborate to simplify voice AI at scale.** `https://www.daily.co/blog/daily-and-nvidia-collaborate-to-simplify-voice-agents-at-scale/` — Published 2025-01-06. Pre-Nemotron stack: Riva Parakeet STT + FastPitch-HiFiGAN TTS + Llama 3.3 70B Instruct.
16. **NVIDIA ACE — Audio2Face-3D Microservice Architecture.** `https://docs.nvidia.com/ace/audio2face-3d-microservice/latest/text/architecture/audio2face-ms.html` — gRPC bidi-streaming, 30 inferences per audio second.
17. **NVIDIA Triton — Concurrent Model Execution + Dynamic Batching tutorial.** `https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/tutorials/Conceptual_Guide/Part_2-improving_resource_utilization/README.html` — `instance_group { count: 2, kind: KIND_GPU }`; dynamic-batching demo: 975 → 3,188 infer/s, 34,035 → 10,567 µs latency at 16 concurrent.
18. **NVIDIA Triton — Optimization documentation.** `https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/optimization.html` — model_warmup, interleaving voice/LLM segments. Sourced via search aggregation.
19. **NVIDIA Developer Forums — High Priority Stream Preemption.** `https://forums.developer.nvidia.com/t/how-high-priority-stream-preemption/78183` — Stream priority is a hint, not preemption. Compute-kernel-only, no H2D/D2H effect.

---

*Closing note:* The single biggest gap this research could not close is **no B300/sm_103 production benchmark exists for any production-grade streaming TTS as of 2026-04-25**. NVIDIA's own published B200 Magpie TTS numbers are the closest proxy, and Magpie's B200-vs-H100 delta (55.1 ms → 70.0 ms = ~21 % B200 advantage on TTFB at 1 stream) suggests B300's advantage over B200 will be smaller (the B300 → B200 delta is mostly memory and FP4-throughput, less so for the smaller-model TTS workload that does not saturate either chip). The fastest verifiable path to a sub-300 ms TTFB on our existing B300 is **P3 (Magpie-TTS replaces Fish-S2-Pro)** + **P2 (MLOPart partitioning to keep Fish/Magpie SMs separate from vLLM SMs)** + **P1 / P7 (sentence-boundary chunking + speculative speech processing)**. P1+P7 alone should get Fish from 2627 ms → ~1500 ms perceived TTFB by masking it behind LLM-first-segment streaming, without replacing Fish. P3 is the cliff-edge gain — but costs the LiveKit-TTS plugin work.
