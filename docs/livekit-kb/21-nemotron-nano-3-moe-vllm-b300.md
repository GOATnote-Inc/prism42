# Nemotron Nano 3 MoE — vLLM / B300 Deep-Dive Brief

**Purpose**: Pre-build reference for pinning Nemotron Nano 3 MoE as the local LLM on the B300 pod, replacing Sonnet 4.6 cloud round-trips.
**Date compiled**: 2026-04-24
**Status of claims**: marked `[NVIDIA marketing]`, `[measured on H200]`, `[measured on B200]`, or `[measured on B300/GB300]` where hardware is known; `[inferred]` where extrapolated.

---

## 1. Model Architecture

**Name**: NVIDIA Nemotron 3 Nano 30B-A3B
**Announced**: December 15, 2025 (NVIDIA Research / Newsroom)
**Technical report**: arXiv:2512.20848 (Dec 25, 2025)

### Parameter counts
| Metric | Value |
|--------|-------|
| Total parameters | 31.6 B |
| Active parameters per forward pass | 3.2 B (3.6 B with embeddings) |

### Architecture type
Hybrid Mamba-Transformer MoE — unique in combining three layer types:

| Layer type | Count |
|------------|-------|
| Mamba-2 SSM layers | 23 |
| MoE (Mixture-of-Experts) transformer layers | 23 |
| Attention layers (GQA, 2 groups) | 6 |
| **Total layers** | **52** |

Each MoE layer: **128 routed experts + 1 shared expert**, with **top-6** activation per token. The GQA attention layers use 2 groups (very aggressive — contributes to low active-param count).

### Context length
- Native training sequence length: 8,192 tokens
- Post-trained context window: **1,000,000 tokens** (1M)
- Default vLLM deployment: **262,144 tokens** (256K)
- 1M requires `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1`

### Training corpus
- Nemotron-CC-v2.1: 2.5 trillion English tokens from Common Crawl
- Nemotron-CC-Code-v1: 428 billion code tokens from Common Crawl
- Nemotron-Pretraining-Code-v2: curated GitHub + synthetic code
- Nemotron-Pretraining-Specialized-v1: synthetic STEM + scientific data
- Total pretraining: approximately 25 trillion tokens at 8K sequence length

The Mamba-2 layers handle long-range sequence compression without attention O(n²) cost — this is the architectural reason 1M context is achievable. The Mamba layers effectively function as efficient state-space compression before the sparse attention layers.

---

## 2. Sizes and Variants Available

All checkpoints are on the official `nvidia` HuggingFace namespace. Access requires HF account + accepting license on the model page, but the models are NOT fully gated in the hard sense — no NVIDIA Enterprise account is required.

### Official HuggingFace checkpoints

| Variant | HF URL | Precision | Notes |
|---------|--------|-----------|-------|
| Post-trained instruct (BF16) | [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) | BF16 | Full-precision instruct; ~60 GB |
| Post-trained instruct (FP8) | [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8) | FP8 | Half the disk of BF16; ~30 GB |
| Post-trained instruct (NVFP4) | [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4) | NVFP4 + FP8 KV cache | Blackwell-native; ~18-20 GB; released Jan 28, 2026 |
| Pre-trained base (BF16) | [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-Base-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-Base-BF16) | BF16 | Raw pretrain, no RLHF |
| 4B dense model (GGUF) | [nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF) | GGUF | Separate model — not the 30B MoE |

**For B300 deployment: use NVFP4.** It is the Blackwell-native format (4-bit floating point with 5th-gen tensor cores), enables 4x FLOPS over BF16, and fits the full model in ~20 GB — leaving ~216 GB free alongside Parakeet + Fish.

### Quantization methodology (NVFP4)
NVIDIA used Quantization-Aware Distillation (QAD): a frozen BF16 teacher, NVFP4 student, KL divergence training on the student's logits. Selective quantization keeps the 6 attention layers and the Mamba layers that feed into attention in BF16. The rest (MoE + remaining Mamba layers) is quantized to NVFP4 with FP8 KV cache. This preserves accuracy at near-BF16 levels while cutting weight memory by ~1.7x vs FP8, ~3x vs BF16. (arXiv:2601.20088, Jan 2026 [NVIDIA marketing + peer-reviewed])

### License
**NVIDIA Nemotron Open Model License** — commercial use explicitly permitted, no sector restrictions, no user-count threshold, no restrictions on emergency services/government applications. Redistribution requires retaining the license notice. No NVIDIA Enterprise license required. AS-IS warranty disclaimer; standard indemnification clause (you hold NVIDIA harmless). Confirmed at: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license/

---

## 3. vLLM 0.20 Deployment

### Prerequisites
- vLLM >= 0.20.0 (has explicit B300/sm_103 support with allreduce fusion enabled by default)
- CUDA 13 (required for B300 — CUDA 12.8 covers B200 only)
- torch nightly >= 2.13.dev (`.venv-nightly`) to avoid the sm_103a PTXAS regression in stable 2.8
- Download the custom reasoning parser (required for tool-use-compatible output):

```bash
wget https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py
```

### Recommended vllm serve command (NVFP4, B300, voice agent use case)

```bash
export HF_TOKEN="<your_hf_token>"
export HF_HOME="/path/to/hf_cache"
export VLLM_USE_FLASHINFER_MOE_FP4=1
export VLLM_FLASHINFER_MOE_BACKEND=throughput
export VLLM_ATTENTION_BACKEND=FLASHINFER
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1

vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
  --served-model-name nemotron-nano \
  --trust-remote-code \
  --tensor-parallel-size 1 \
  --max-model-len 262144 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.80 \
  --kv-cache-dtype fp8 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser-plugin nano_v3_reasoning_parser.py \
  --reasoning-parser nano_v3 \
  --enable-prefix-caching \
  --port 8001 \
  --host 0.0.0.0
```

**Flag rationale:**

| Flag | Why |
|------|-----|
| `--tensor-parallel-size 1` | NVFP4 fits on a single B300 GPU (~20 GB). TP > 1 with NVFP4 on B300 is known to fail (see §6). |
| `--max-model-len 262144` | 256K covers any realistic 911 call transcript with history. 1M possible but increases KV cache pressure. |
| `--max-num-seqs 8` | Matches `--max-num-seqs` from NVIDIA's official recipe. Tune up for higher concurrency once baseline is stable. |
| `--gpu-memory-utilization 0.80` | Conservative — leaves headroom for Parakeet (port 9100) and Fish (port 9200) on the same 275 GB pool. Adjust upward after measuring actual memory. |
| `--kv-cache-dtype fp8` | Required alongside NVFP4 weights per NVIDIA's model card. |
| `--enable-auto-tool-choice` + `--tool-call-parser qwen3_coder` | Enables function calling in OpenAI-compatible format. The parser translates the model's native Qwen3-style tool tokens to JSON. |
| `--reasoning-parser nano_v3` | Strips internal `<thinking>` tokens from the streamed response. Without this, CoT tokens leak into the voice stream. |
| `--enable-prefix-caching` | System prompt + call-context prefix is static per session — prefix cache eliminates those tokens from TTFT on turn 2+. |
| `--port 8001` | Avoids conflict with Fish (9200), Parakeet (9100). vLLM's default 8000 is not taken by our stack, but 8001 is an explicit safe pick. |

**Do NOT use `--enforce-eager`** unless debugging. Eager mode disables CUDA graphs and wrecks throughput. The Triton PTXAS regression is already solved by `.venv-nightly`.

### Environment variables reference

| Var | Required | Purpose |
|-----|----------|---------|
| `HF_TOKEN` | Yes | Download gated weights from HF |
| `HF_HOME` | Recommended | Cache weights to a mounted volume across restarts |
| `VLLM_USE_FLASHINFER_MOE_FP4=1` | Yes for NVFP4 | Activates FlashInfer FP4 MoE kernel on Blackwell |
| `VLLM_FLASHINFER_MOE_BACKEND=throughput` | Yes for NVFP4 | Selects throughput-optimized MoE kernel path |
| `VLLM_ATTENTION_BACKEND=FLASHINFER` | Yes | Required for FP8 KV cache + FlashInfer attention |
| `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` | Only if > 262144 context | Unlocks 1M context (not needed for voice) |

### Expected first-boot behavior
- Weight download: NVFP4 checkpoint is ~18-20 GB (safetensors format). At typical pod network speeds (1 Gbps), expect 3-5 minutes first boot. Pre-download with `huggingface-cli download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`.
- Model load time (after download): 60-120 seconds for weight materialization + CUDA graph capture.
- **Historical shard corruption**: shards 6-10 of the NVFP4 checkpoint were corrupted (40-byte Xet pointer stubs) at initial release. NVIDIA resolved this March 4, 2026. Verify a clean download with `huggingface-cli scan-cache` or check file sizes > 1 GB each.

---

## 4. Performance Claims on Blackwell

### What is actually measured vs claimed

**NVIDIA marketing claims [NVIDIA marketing, unverified on B300]:**
- NVFP4 delivers 4x FLOPS over BF16 on Blackwell (via 5th-gen tensor core native FP4 support)
- NVFP4 delivers 1.65x better cost efficiency than FP8 by fitting on one GPU instead of two
- On a single 8-GPU B200 node: 8 NVFP4 instances at ~124,000 tok/s aggregate vs 4 FP8 instances at ~75,000 tok/s

**Measured on H200 (vLLM official recipes, FP8 variant) [measured on H200]:**
- Request throughput: 15.46 req/s
- Output token throughput: 15,828 tok/s
- Median TTFT: **1,534 ms** (this is high-load batch TTFT, not streaming TTFT)
- Median TPOT: 61 ms

**Measured on H200/DeepInfra API (likely BF16 or FP8, non-reasoning mode) [measured on H200]:**
- TTFT: **0.45s (450 ms)** at 10,000-token input
- Output speed: **93.7 tokens/s** (P50 over 72 hours)
- End-to-end latency for 500 tokens: 5.78 seconds

**Measured on DGX Spark (GB10, NVFP4, `VLLM_USE_FLASHINFER_MOE_FP4=1`) [measured on GB10, not B300]:**
- Peak prompt processing: 11,707 ± 14 tokens/s
- Sustained throughput at 198 concurrent requests: 1,365 tokens/s average generation
- Single-request text generation: ~52-56 tokens/s

**Measured on GB300 (vLLM v0.14.1, CUDA 13.0, DeepSeek-V3.2 proxy for NVFP4 MoE class) [measured on GB300]:**
- Prefill-only throughput: 7,360 TGS (tokens/GPU/second) for a DeepSeek-class MoE
- Mixed-context (ISL=2K, OSL=1K): 2,816 TGS
- GB300 vs B300: 14% higher prefill, 12% higher in short output scenarios

No published B300-specific benchmark for Nemotron Nano 3 MoE NVFP4 exists as of April 2026. The GB300 DeepSeek numbers are the closest structural analog.

### Latency-budget projection for voice

**Sonnet 4.6 streaming TTFT (cloud)**: ~500 ms (per project context)

**Nemotron Nano 3 MoE NVFP4 on B300, single-request TTFT projection [inferred]:**
- The 0.45s TTFT on H200 was at 10K input tokens in non-reasoning mode
- B300 has 55% more FP4 FLOPS and 65% more HBM bandwidth than B200
- B300 vs H200: ~8-10x prefill throughput improvement on mixed-context scenarios (DeepSeek GB300 blog)
- For a voice-agent input (200-2000 tokens), TTFT on B300 with NVFP4 should be well under 100 ms [inferred]
- Decode (TPOT): with 3.2B active params and NVFP4, target ~30-50 ms/token at concurrency 1 [inferred]
- At concurrency 1 for a voice agent, the LLM hop should contribute **under 200 ms total** (TTFT + first 50 tokens at ~5-10ms/token on B300 NVFP4) [inferred from GB300 DeepSeek data + H200 measurements]

**Verdict**: Nemotron Nano 3 MoE NVFP4 on B300 should **beat Sonnet 4.6's 500 ms cloud TTFT** significantly at concurrency 1, likely landing under 100 ms TTFT. This eliminates the cloud round-trip entirely. There are no verified B300-specific numbers for this model to cite — this is an engineering inference.

---

## 5. OpenAI-Compatible API Surface

vLLM 0.20 exposes `/v1/chat/completions` with full OpenAI streaming format. Nemotron Nano 3 emits OpenAI-shape streamed responses when served through vLLM.

### Tool use / function calling
- `--enable-auto-tool-choice` enables the function calling path
- `--tool-call-parser qwen3_coder` handles the model's native tool-token format and translates to OpenAI JSON
- Function calls are emitted as standard `tool_calls` chunks in the streamed delta
- **Known gap**: Nemotron's tool format is Qwen3-derived, not Anthropic's `tool_use` blocks. The vLLM parser handles the translation to OpenAI format, which means the LiveKit OpenAI plugin picks it up cleanly

### LiveKit integration
The `livekit-plugins-openai` plugin's `openai.LLM()` class accepts `base_url`:

```python
from livekit.plugins import openai

llm = openai.LLM(
    model="nemotron-nano",
    base_url="http://localhost:8001/v1",
    api_key="not-needed",  # vLLM does not require a real key
)
```

This is the canonical pattern per LiveKit docs for any OpenAI-compatible local endpoint. The plugin uses the Chat Completions API path, which is what vLLM's OpenAI server exposes. Function calling via `FunctionTool` or `RawFunctionTool` works through this path.

**Note**: The `livekit-plugins-anthropic` plugin uses Anthropic's native Messages API format (`tool_use` blocks, `input_json_delta` events) — it does NOT work with a vLLM OpenAI-compatible proxy. You must switch from `livekit-plugins-anthropic` to `livekit-plugins-openai` for the local Nemotron path.

### Reasoning mode
The model has an internal CoT reasoning mode (toggled via chat template: `enable_thinking=true/false`). For voice latency, disable it:

```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron-nano",
    "messages": [{"role": "user", "content": "..."}],
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

Without disabling reasoning, the model emits `<thinking>` tokens before the actual response — the `--reasoning-parser nano_v3` strips these from the streamed output, but they still consume decode time. For latency-critical voice turns, set `enable_thinking=false` in the system prompt template or per-request.

---

## 6. Anticipated Bottlenecks for 911 Voice Agent Migration

### Missing tokens / access
- **HF_TOKEN is required**: The NVFP4 checkpoint page requires accepting the NVIDIA Open Model License on HuggingFace. The license accept is per-account; the `HF_TOKEN` you set must belong to the account that accepted it. If the pod's token is different from the dev account that accepted, the download will 403.
- **No NGC API key needed**: NVIDIA's HF-hosted checkpoints do not require NGC. The NGC NIM path (separate container) does require NGC, but we are not using NIM.
- **No NVIDIA Enterprise license**: confirmed by the Open Model License text. Consumer HF access is sufficient.

### Missing env vars (will cause silent failures or wrong kernels)
- `VLLM_USE_FLASHINFER_MOE_FP4=1` — without this, NVFP4 MoE falls back to a non-optimized path or fails with `No NvFp4 MoE backend supports the deployment configuration`
- `VLLM_FLASHINFER_MOE_BACKEND=throughput` — without this, even with the above, you get the latency-optimized (lower throughput) kernel
- `VLLM_ATTENTION_BACKEND=FLASHINFER` — without this, FP8 KV cache may not initialize correctly
- `TORCH_CUDA_ARCH_LIST` — should include `10.3` for sm_103a on B300. If building any custom extension from source, set `TORCH_CUDA_ARCH_LIST="10.0;10.3"`. Pre-built vLLM wheels should handle this automatically.

### NVFP4 + TP > 1 failure on B300 — the single highest-risk issue
- NVFP4 + `--tensor-parallel-size 8` on B300 fails with `RuntimeError` (reported in NVIDIA NIM release notes). The error manifests as engine core initialization failure.
- On RTX 5090 (SM12x), the exact error is: `NvFp4 MoE backend 'FLASHINFER_CUTLASS' does not support the deployment configuration since kernel does not support current device.` SM12x ≠ SM10x; this specific error may not reproduce on SM103a. But TP > 1 on B300 NVFP4 is separately documented as failing in NIM 2.0.1 release notes.
- **The safe path is `--tensor-parallel-size 1`** — the NVFP4 checkpoint fits comfortably on a single B300 (20 GB vs 275 GB available). No TP needed.
- Workaround if TP is desired: use FP8 instead of NVFP4, which has confirmed single-GPU and multi-GPU support.

### Port conflicts
| Service | Port |
|---------|------|
| Parakeet STT | 9100 |
| Fish TTS | 9200 |
| vLLM default | 8000 |
| Recommended vLLM | **8001** |

vLLM's default 8000 is not occupied by the current stack, but using 8001 explicitly avoids any future conflict if a health-check service or metrics endpoint lands on 8000.

### Memory pressure with concurrent Parakeet + Fish
- Fish TTS (S2-Pro) GPU footprint: approximately 8-12 GB depending on batch size
- Parakeet STT (1.1B streaming): approximately 4-6 GB
- Nemotron NVFP4 weights: ~20 GB
- Nemotron KV cache (at `--gpu-memory-utilization 0.80`, 256K context, 8 sequences): estimated 20-40 GB depending on sequence lengths
- **Total estimate: 52-78 GB of 275 GB** — well within budget even at `--gpu-memory-utilization 0.90`
- Start with `0.80` and increase if vLLM logs `KV cache has 0 blocks`. Check with `nvidia-smi` after model load.

### Logging / diagnostics
- vLLM logs go to stdout by default. Structured JSON logging: add `--log-level info` and pipe to `journalctl` or a file. There is no separate vLLM log path by default — capture systemd stdout.
- KV cache utilization visible via `/metrics` endpoint (Prometheus format) at `http://localhost:8001/metrics`
- Token-level throughput: `vllm_request_prompt_tokens_total`, `vllm_request_generation_tokens_total`

### Custom reasoning parser requirement
The `nano_v3_reasoning_parser.py` must be present in the working directory (or a path accessible to vLLM). This is a model-specific file from NVIDIA's HF repo. Without it, `--reasoning-parser nano_v3` fails at startup. Download it before the first `vllm serve` invocation.

### Tokenizer compatibility
- Nemotron Nano 3 uses a custom tokenizer (requires `--trust-remote-code`). This is a Mamba-hybrid tokenizer, not a standard Llama/Mistral tokenizer.
- livekit-plugins-openai is tokenizer-agnostic (it sends text strings, not token IDs) — no tokenizer compatibility issue on the LiveKit side.
- If any existing prism42 code assumes Anthropic tokenization for context budgeting, those estimates will be wrong for Nemotron. Use vLLM's `/v1/completions` token count endpoint for accurate budgeting.

### Plugin swap required
Currently: `livekit-plugins-anthropic` -> Claude Sonnet 4.6
After swap: `livekit-plugins-openai` -> vLLM at `http://localhost:8001/v1`

The session code in the agent worker must change the LLM constructor. No other LiveKit pipeline changes are needed (Parakeet, Fish, turn detection all remain on their current paths).

---

## 7. Latency-Budget Realism

### Current baseline: Sonnet 4.6 cloud TTFT ~500 ms

This 500 ms includes: network RTT to Anthropic edge (~30-80 ms on a well-peered Brev pod) + Anthropic scheduling + prefill + first-token decode.

### Projected Nemotron Nano 3 NVFP4 on B300 at concurrency 1

| Segment | Estimate | Basis |
|---------|----------|-------|
| Prefill (200-token 911 system prompt + transcript) | 5-15 ms | [inferred from GB300 DeepSeek 7360 TGS prefill] |
| First decode token | 5-10 ms | [inferred: 3.2B active params, NVFP4 on 14 PFLOPS] |
| Network RTT (B300 pod to LiveKit) | 0 ms (on-pod) | [empirical] |
| **Total TTFT at concurrency 1** | **~15-30 ms** | [inferred] |

**At concurrency 8** (8 simultaneous calls): TTFT degrades to ~100-200 ms [inferred from H200 batch numbers scaled for B300].

**At concurrency 32**: TTFT likely 400-800 ms — approaching Sonnet 4.6 territory. Nemotron Nano 3's 3.2B active params give it a major throughput advantage over dense models at high concurrency, but the non-attention Mamba layers do not parallelize across batch the same way. No B300 concurrency benchmark for this model exists in the public record as of April 2026.

**Bottom line**: For a single active call (the primary 911 console case), Nemotron Nano 3 NVFP4 on B300 should deliver a **10-30x TTFT improvement** over Sonnet 4.6 cloud. The 93.7 tokens/s sustained output on H200 (non-reasoning, cloud API) suggests decode quality is competitive with Sonnet 4.6 for factual retrieval tasks like 911 dispatch triage. There are no verified B300 numbers for this model specifically — ship only after measuring first-turn TTFT on the actual pod.

---

## 8. License / Commercial Use Posture

**License**: NVIDIA Nemotron Open Model License (custom, not Apache-2 or MIT)

**Key terms confirmed**:
- Commercial use: **permitted, explicitly stated**
- Emergency services / government / PSAP deployment: **no restrictions identified**
- User count threshold: **none**
- Redistribution: permitted with attribution
- Warranties: AS-IS (standard)
- Liability: indemnification clause — you hold NVIDIA harmless for downstream use claims

**What this means for the 911 PSAP demo on prism42**:
The NVIDIA Open Model License does not block deployment as a 911 PSAP demo. The AS-IS disclaimer means NVIDIA does not guarantee model accuracy — standard for research-grade inference. For a clinical or public safety production deployment (beyond demo), legal should review the indemnification clause, but there is no technical or license blocker for the current PSAP demo use case.

**Compare to Apache-2**: The NVIDIA Open Model License is more restrictive than Apache-2 (it is model-specific, not software-specific), but it is permissive enough for the demo use case. There is no "no AI use" carve-out, no sector restriction, and no registration requirement beyond the HF license acceptance.

---

## Sources

| Source | URL | Date / Note |
|--------|-----|-------------|
| NVIDIA Nemotron 3 family announcement | https://nvidianews.nvidia.com/news/nvidia-debuts-nemotron-3-family-of-open-models | Dec 15, 2025 |
| Nemotron 3 Nano technical report (arXiv) | https://arxiv.org/abs/2512.20848 | Dec 25, 2025 |
| NVIDIA Nemotron 3 white paper | https://arxiv.org/abs/2512.20856 | Dec 24, 2025 |
| QAD tech report (NVFP4 methodology) | https://arxiv.org/abs/2601.20088 | Jan 2026 |
| NVIDIA Research Nemotron-3 page | https://research.nvidia.com/labs/nemotron/Nemotron-3/ | Announced Dec 2025 |
| NVIDIA QAD page | https://research.nvidia.com/labs/nemotron/nemotron-qad/ | Jan 2026 |
| HF model card: NVFP4 instruct | https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 | Jan 28, 2026 (NVFP4 release) |
| HF model card: FP8 instruct | https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8 | Dec 2025 |
| HF model card: BF16 instruct | https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 | Dec 2025 |
| HF model card: BF16 base | https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-Base-BF16 | Dec 2025 |
| HF blog: Nemotron 3 Nano launch | https://huggingface.co/blog/nvidia/nemotron-3-nano-efficient-open-intelligent-models | Dec 2025 |
| vLLM blog: Run Nemotron 3 Nano | https://vllm.ai/blog/run-nvidia-nemotron-3-nano | Dec 15, 2025 |
| vLLM recipes: Nemotron-3-Nano-30B-A3B | https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html | 2026 |
| vLLM blog: GB300 DeepSeek performance | https://vllm.ai/blog/gb300-deepseek | Feb 13, 2026 |
| vLLM GitHub issue #34452: NVFP4 sm12x failure | https://github.com/vllm-project/vllm/issues/34452 | Feb 22, 2026 |
| vLLM GitHub issue #35065: Nemotron NVFP4 no backend | https://github.com/vllm-project/vllm/issues/35065 | Feb 2026 |
| vLLM GitHub issue #31782: compressed-tensors NVFP4 MoE | https://github.com/vllm-project/vllm/issues/31782 | 2026 |
| NVIDIA NIM LLM release notes (TP8 B300 fail) | https://docs.nvidia.com/nim/large-language-models/2.0.1/about-nim-llm/release-notes.html | 2026 |
| DeepInfra benchmarks: Nemotron 3 Nano | https://deepinfra.com/blog/nvidia-nemotron-3-nano-30b-a3b-api-benchmarks | 2026 |
| NVIDIA Developer blog: Nemotron 3 internals | https://developer.nvidia.com/blog/inside-nvidia-nemotron-3-techniques-tools-and-data-that-make-it-efficient-and-accurate/ | 2026 |
| NVIDIA Nemotron Open Model License | https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license/ | Current |
| HF NVFP4 corrupted shards discussion (resolved) | https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/discussions/7 | Resolved Mar 4, 2026 |
| LiveKit OpenAI-compatible LLMs doc | https://docs.livekit.io/agents/models/llm/openai-compatible-llms/ | 2026 |
| NVIDIA Nemotron cookbook (vLLM) | https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3-Nano/vllm_cookbook.ipynb | 2026 |
| Verda B200/B300 architecture comparison | https://verda.com/blog/nvidia-b200-and-b300-gpu-architecture-and-software-stack | 2026 |
