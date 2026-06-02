# Nemotron-3-Nano-Omni — canonical capability brief

**Status**: distributable reference. Every agent + subagent in this stack reads this first when reasoning about Omni. Compiled by parallel research agent on 2026-04-29; verified against authoritative URLs cited inline.

**Lessons baked in**: Karpathy/Glasswing/Omni-day-zero audits taught us that under-claim beats over-claim. Claims tagged "verified" trace to a specific URL. Claims tagged "uncertain" mean the data was not in primary sources at the time of writing.

## 1. Architecture

- **Total parameters**: 31 B (notation: 30B-A3B). [verified — HF model card]
- **Active parameters per token**: 3 B (top-6 of 128 experts + 1 shared expert). [verified — HF blog]
- **Layer composition** (52 total): 23 Mamba-2 selective state-space + 23 MoE + 6 grouped-query attention. [verified — HF blog]
- **Expert routing**: 128 experts/MoE layer; top-6 routed + 1 always-on shared. Router NOT quantized in FP8/NVFP4 variants (preserves routing precision). [verified — HF model card]
- **Context length**: 256 K native (262 144 tokens); 1 M reported in some deployments via sliding-window — NVIDIA caps recommended `max-model-len` at 262 144. [verified — vLLM recipe]
- Hidden dim, attention-head count, vocab size, position-encoding: not disclosed in primary public sources (uncertain).

Sources:
- <https://huggingface.co/nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16>
- <https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence>
- <https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html>

## 2. Input modalities (all four)

### Text
- Format: standard chat-template token IDs.
- Max: 256 K context shared across all modalities.
- vLLM message shape: `{"type": "text", "text": "..."}`.

### Image
- Encoder: **C-RADIOv4-H** (NVIDIA's dynamic-resolution vision encoder).
- Format: base64 JPEG/PNG or `file://` URI; data-URL accepted.
- Patch budget: **1024 – 13 312 patches** per image, dynamically scaled to preserve aspect.
- Native res tested: 1920 × 1080 (computer-use scenarios).
- vLLM message shape: `{"type": "image_url", "image_url": {"url": "..."}}`.

### Video
- Encoder: **Conv3D tubelet embedding + Efficient Video Sampling (EVS)** layer; EVS drops redundant static frames at inference.
- Format: MP4 file URI.
- Max duration: 2 min nominal; 5 + h sampling capacity at inference time.
- Recommended sampling: **2 FPS × 256 frames** (720 p) or **1 FPS × 128 frames** (1080 p).
- vLLM message shape: `{"type": "video_url", "video_url": {"url": "file://path"}}`.
- vLLM flags: `--video-pruning-rate 0.5`, `--media-io-kwargs '{"video": {"fps": 2, "num_frames": 256}}'`.

### Audio
- Encoder: **Parakeet-TDT-0.6B-v2** (NVIDIA's speech encoder; native, not external ASR).
- Format: WAV / MP3 file URI.
- Sample rate: 16 kHz mono recommended; 8 kHz+ accepted.
- Max duration: 1 h nominal; 5 + h training capacity.
- ASR side-channel: produces **word-level timestamps**.
- vLLM message shape: `{"type": "audio_url", "audio_url": {"url": "file://path"}}`.
- ⚠ **Critical constraint**: reasoning **must be disabled** for audio inputs (`enable_thinking: false`, `temperature: 0.2`). Audio + reasoning is mutually exclusive at the vLLM layer.

## 3. Output capabilities

- **Text generation**: default mode.
- **Tool calling**: OpenAI-compatible function schemas. vLLM flags: `--enable-auto-tool-choice --tool-call-parser qwen3_coder`.
- **JSON mode**: supported via `response_format={"type":"json_object"}`. Schema-enforcement strength: uncertain.
- **Reasoning / thinking trace**: native chain-of-thought; configurable `thinking_token_budget` (default 16 384, hard ceiling +500 grace tokens). Default: **OFF**. Enable via `chat_template_kwargs={"enable_thinking": True}` or `extra_body={"thinking_token_budget": N}`. vLLM parser: `--reasoning-parser nemotron_v3`.
- **Transcription with timestamps**: supported via Parakeet output for audio inputs.

## 4. Quantization variants

| Variant | Disk size | Active VRAM (model only) | Hardware floor | NVFP4 vs BF16 delta |
|---|---|---|---|---|
| **BF16** | 61.5 GB | ~62 GB | A100 80 GB · H100 · H200 · B200 · L40S | baseline |
| **FP8** | 32.8 GB | ~33 GB | A100 80 GB · H100 · H200 · B200 | within 1 pt |
| **NVFP4** | 20.9 GB | ~21 GB | A100 · H100 · H200 · B200 · RTX Pro 6000 SE · DGX Spark · Jetson Thor | **−0.38 pt mean** across 9 multimodal benchmarks; max delta −1.15 (CharXiv) |

NVFP4 was trained with **Quantization-Aware Distillation (QAD)** — that's how it stays within 0.38 pt of BF16. It's not a post-hoc PTQ.

KV-cache budget at `--max-model-len 131072` with `--kv-cache-dtype fp8`: ~2-4 GB on top of weights for NVFP4; ~4-8 GB for FP8; ~8-16 GB for BF16.

## 5. Recommended vLLM launch command (NVFP4 / single GPU)

```bash
vllm serve nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 \
  --host 0.0.0.0 \
  --max-model-len 131072 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --video-pruning-rate 0.5 \
  --max-num-seqs 384 \
  --reasoning-parser nemotron_v3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --kv-cache-dtype fp8
```

Container: `vllm/vllm-openai:v0.20.0` (or later); pin to digest for reproducibility.

## 6. Throughput (H200 baseline)

- vs Qwen3-30B: **3.3× higher throughput** at fixed interactivity target.
- vs Nemotron Nano V2: **3× higher throughput** at fixed batch.
- Batch=384 / 8 K context: **15 828 output tok/s**, **52–63 ms inter-token latency**.
- Cold-start (full weight load): uncertain — not benchmarked publicly.

## 7. Reasoning mode specifics

- **Default**: OFF.
- **Enable**: `chat_template_kwargs={"enable_thinking": True}` (for chat templates) OR `extra_body={"thinking_token_budget": <int>}`.
- **Budget mechanism**: fixed-per-request (NOT adaptive like Anthropic's `thinking: adaptive`). Hard cutoff at `budget + 500` tokens if no newline.
- **Output shape**: thinking trace appears in the `reasoning` field of the OpenAI-compatible streaming response; final answer in `content`.
- **Recommended temperature**: 0.6 with reasoning ON; 0.2 with reasoning OFF (instruct mode).
- **Audio input + reasoning**: incompatible. Force reasoning OFF for any audio request.

## 8. Safety & red-teaming

- Trained with safety data: Nemotron Content Safety v2, Gretel Safety Alignment v1, Harmful Tasks, Red-Team-2K.
- Refusal behaviors: SFT-shaped; e.g., self-harm prompts return crisis-line templates.
- ⚠ **Known vulnerability**: NR Labs published a system-prompt-override policy bypass enabling malware generation. NVIDIA has not published a patch statement as of 2026-04-29. Source: <https://www.nrlabs.com/blog-posts/bypassing-nemotron-v3-policy-protections>. **Implication for MedOmni**: do not rely solely on Omni's built-in refusal; add Llama-Guard-3-8B on the orchestrator pod as the input/output rail.
- No published Llama-Guard-equivalent classifier shipped alongside Omni — safety filtering is implicit within the model.

## 9. Knowledge cutoff & training data

- **Knowledge cutoff**: 2025-06-25.
- **Training span**: 2019 – 2025.
- **Training samples**: 354.6 M multimodal across 1 395 datasets (~717 B tokens).
- **Modality split**: text+audio 259 M · text+image 70 M · text+video 16 M · text+video+audio 9 M.
- **Synthetic data**: 11.4 M synthetic QA pairs (~45 B tokens) generated from PDFs via NeMo Data Designer.
- **Filters**: CSAM scanning + content-safety filtering applied.

## 10. Fine-tuning support

- **Full fine-tune**: NVIDIA NeMo Megatron-Bridge. Bidirectional HF ↔ NeMo checkpoint conversion.
- **LoRA**: supported via Megatron-Bridge + NeMo Automodel. SFT recipes on the `nemotron_3_omni` branch.
- **QAT**: NVFP4 trained with Quantization-Aware Distillation (NVIDIA-original method). Approximation ≈ 0.38 pt vs BF16.
- **Router-only fine-tune**: not published as a blessed pattern; the EASY-EP precedent is community.
- Source: <https://docs.nvidia.com/nemo/megatron-bridge/latest/models/llm/nemotron3.html>

## 11. Published benchmarks (launch-day; multimodal-leaning)

| Benchmark | Score |
|---|---|
| OCRBenchV2-En | 65.8 % |
| MMLongBench-Doc | 57.5 % |
| CharXiv (technical reasoning) | 63.6 % |
| Video-MME | 72.2 % |
| WorldSense (video+audio) | 55.4 % |
| VoiceBench (speech understanding) | 89.4 % |
| HF Open ASR (WER) | 5.95 (lower better) |
| OSWorld (computer use) | 47.4 % (+76.58 % vs prior gen) |
| ScreenSpot-Pro | leads benchmark (exact pp uncertain) |

**Pure-reasoning text benchmarks NOT published** (MMLU, GPQA, HumanEval) — Omni is optimized for multimodal, not pure reasoning leaderboards. Don't claim text-only reasoning parity with Llama-3-Nemotron-70B-Instruct without measuring.

## 12. Known foot-guns (deploy-blocking; baked into MedOmni runtime)

| # | Issue | Workaround |
|---|---|---|
| 1 | Blackwell V1 engine + NVFP4: `cudaErrorIllegalInstruction` at batch >1 | `--no-async-scheduling` OR disable V1 engine. <https://github.com/NVIDIA-NeMo/Nemotron/issues/125> |
| 2 | TRTLLM attention backend + Blackwell: breaks on `is_strictly_contiguous` | `--disable-attention-backend trtllm`. <https://github.com/vllm-project/vllm/issues/32353> |
| 3 | `max-model-len 1000000` (1 M context): CUDA OOM | cap at 262 144 (256 K) per NVIDIA recipe |
| 4 | Audio input + reasoning ON: errors / invalid output | force `enable_thinking: false`, `temperature: 0.2` for audio requests |
| 5 | Image > 13 312 patches: silent degrade or fail | downsample first; respect dynamic patch ceiling |
| 6 | Video > 2 min: untested; likely context overrun | chunk into ≤2 min segments |
| 7 | Mixed-modality token interleaving: ordering not documented | safest: text → image → video → audio in `content` array |

## 13. Agentic role NVIDIA documents

NVIDIA positions Omni as a **multimodal perception sub-agent** in larger stacks alongside:
- Nemotron-3-Super (120 B) — high-frequency planning/execution.
- Nemotron-3-Ultra (1 T+) — long-horizon reasoning.
- Cloud frontier models (Anthropic, OpenAI) for specialized tasks.

This means Omni-as-the-whole-brain is a stretch; Omni-as-the-perception-and-grounding-layer with another model orchestrating is closer to NVIDIA's intent. **For MedOmni**: Omni + Claude Code (or OpenClaw) as orchestrator on the RunPod H100 fits exactly this pattern.

NeMo Agent Toolkit primitives:
- NeMo-RL — multi-environment reinforcement learning training.
- NeMo Data Designer — synthetic-data generation pipelines.
- NeMo Megatron-Bridge — checkpoint management + fine-tune recipes.

## 14. MedOmni deployment checklist

| Requirement | Status |
|---|---|
| Architecture verified | ✓ — 52-layer hybrid Mamba2-Transformer-MoE; 3 B active per token |
| Text input | ✓ — 256 K context max |
| Image input | ✓ — C-RADIOv4-H, 1 K – 13 K patches |
| Video input | ✓ — MP4, 2 min, 2 FPS / 256 frames |
| Audio input | ✓ — WAV/MP3 16 kHz, word-level timestamps |
| Tool calling | ✓ — OpenAI-compatible, `qwen3_coder` parser |
| Reasoning mode | ✓ — fixed-budget thinking, OFF by default, mutually exclusive with audio |
| Quantization | ✓ — BF16 / FP8 / NVFP4; NVFP4 at −0.38 pt vs BF16 |
| vLLM v0.20.0+ | ✓ |
| Safety | ⚠ — implicit; rely on Llama-Guard-3-8B as input/output rail |
| Pure-reasoning benchmarks | ✗ — not published; measure ourselves |
| Fine-tuning | ✓ — NeMo Megatron-Bridge LoRA + Full |
| Blackwell stability | ⚠ — V1 engine bug; workaround required |

## 15. Sources index (for verification)

- HF model cards: <https://huggingface.co/nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16>, `-FP8`, `-NVFP4`
- HF blog: <https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence>
- NVIDIA developer blog: <https://developer.nvidia.com/blog/nvidia-nemotron-3-nano-omni-powers-multimodal-agent-reasoning-in-a-single-efficient-open-model/>
- NVIDIA blogs main: <https://blogs.nvidia.com/blog/nemotron-3-nano-omni-multimodal-ai-agents/>
- vLLM recipe: <https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html>
- NeMo Megatron-Bridge: <https://docs.nvidia.com/nemo/megatron-bridge/latest/models/llm/nemotron3.html>
- NemoQAD research: <https://research.nvidia.com/labs/nemotron/nemotron-qad/>
- OpenRouter listing (audio/reasoning constraint): <https://openrouter.ai/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free>
- Blackwell V1 engine bug: <https://github.com/NVIDIA-NeMo/Nemotron/issues/125>
- TRTLLM attention bug: <https://github.com/vllm-project/vllm/issues/32353>
- NR Labs policy-bypass disclosure: <https://www.nrlabs.com/blog-posts/bypassing-nemotron-v3-policy-protections>

This document is the canonical Omni reference for every agent in the MedOmni stack. Any agent reasoning about Omni capabilities should read this brief and cite it in their plans.
