---
title: vLLM 0.20 + NVFP4 + B300 — Deployment Briefing for Nemotron Nano 3 MoE
date: 2026-04-24
status: research briefing (pre-deploy)
scope: Authoritative operational guidance for migrating the Glasswing LLM hop
       from Anthropic Cloud (Sonnet 4.6) to B300-local Nemotron Nano 3 MoE on
       vLLM 0.20 with NVFP4 quantization.
hardware: NVIDIA B300 SXM6, sm_103a, 275 GB HBM3E, CUDA 13
---

# 23 — vLLM 0.20 + NVFP4 + B300 Deployment Briefing

## Background

Current voice path (see `09-b300-voice-bench.md`): Parakeet STT (9 GB, port 9100)
+ Fish TTS (8 GB, port 9200) + Anthropic Cloud LLM. Measured p50 `t_llm_proxy_ms`
= 8.5 s; this is ~80% of total E2E latency. Goal: replace the cloud LLM hop with
a pod-local model serving the OpenAI-compatible `/v1/chat/completions` API so the
orchestrator swaps endpoints without code surgery.

---

## 1. vLLM v0.20 + B300 — Known-Good Recipe

**Release notes URL:** https://github.com/vllm-project/vllm/releases/tag/v0.20.0

**Release date:** April 23, 2026 (aligned with our sprint window — this is new).

**Key v0.20 requirements:**
- PyTorch 2.11 + CUDA 13.0 (breaking change from prior wheels)
- Transformers v5 (v4 compatibility shim included but v5 required for new models)
- FA4 re-enabled as the default MLA prefill backend on SM100/SM103

The v0.20 release notes do **not** mention B300/sm_103a by name, but earlier
v0.17-v0.19 work established FA4 as the default attention backend on
Blackwell SM100/SM103 GPUs, and v0.20 adds explicit `NVFP4 W4A4 CUTLASS MoE for
SM100` kernels and tuned allreduce for GB300/B300 (noted in v0.19 release as
`allreduce fusion enabled by default`). The authoritative B300 deployment reference
in the vLLM ecosystem is the February 2026 GB300 + DeepSeek write-up:
https://vllm.ai/blog/gb300-deepseek

### sm_103a auto-detect status

**vLLM 0.20 does NOT reliably auto-detect sm_103a.** Bug report
vllm-project/vllm#30245 (filed December 2025, still tracked "in progress" as of
April 2026) documents the exact error:

```
ptxas fatal: Value 'sm_103a' is not defined for option 'gpu-name'
```

This is the same Triton / bundled-PTXAS regression we hit with fish-speech
(see `20-blackwell-b300-torch-compile-discovery.md`). The mechanism: vLLM's
bundled Triton emits PTX targeting sm_103a, then calls its own bundled ptxas,
which doesn't recognize the architecture string.

**Critical distinction from fish-speech case:** vLLM 0.20 ships on PyTorch 2.11
+ CUDA 13.0. Our `.venv-nightly` uses torch 2.13.dev20260424+cu130 + Triton
3.7.0+git88b227e, which recognizes sm_103a. But `pip install vllm==0.20.0` will
install its own torch 2.11 wheel + bundled Triton, which may or may not carry the
fix. The safe path is to install vLLM inside `.venv-nightly` or use the NGC
container so the vLLM wheel runs against the Triton that already works on this pod.

**Required env override:**
```bash
export TORCH_CUDA_ARCH_LIST="10.0;10.3"
```

The `10.0+PTX` pattern shown in vLLM's arm64/Grace-Blackwell docs is for build
time. At runtime the critical variable is whether Triton's bundled ptxas handles
sm_103a. Set the arch list explicitly and use `.venv-nightly` as the base
environment.

**Ptxas symlink workaround (if bundled Triton ptxas fails):**
```bash
# Replace vLLM's bundled ptxas with the CUDA 13 system ptxas
TRITON_PTXAS=$(python -c "import triton; import os; \
  print(os.path.join(os.path.dirname(triton.__file__), \
  'backends/nvidia/bin/ptxas'))")
ln -sf /usr/local/cuda/bin/ptxas "$TRITON_PTXAS"
```
This is the community workaround from vLLM forums. Requires CUDA 13 system ptxas
to understand sm_103a — which it does on this pod.

### Core serve flags

For Nemotron Nano 3 MoE NVFP4 on a single B300 with co-resident Parakeet + Fish:

```bash
--tensor-parallel-size 1          # single-GPU; model fits in ~20 GB of VRAM
--max-model-len 32768              # trim from 262144 default; saves KV-cache VRAM
--gpu-memory-utilization 0.50      # see §3 for co-residency math
--kv-cache-dtype fp8               # required by NVFP4 model card
--max-num-seqs 8                   # official NVIDIA recommendation for this model
--enforce-eager                    # recommended for first boot; see §4
```

`--enforce-eager` is NOT required for stable operation but disables CUDA graph
capture, eliminating the ptxas-at-capture-time risk on first boot. Remove it once
you confirm CUDA graphs capture cleanly (i.e., after verifying the Triton ptxas
path).

---

## 2. NVFP4 on Blackwell — Deploy Flag and Model Availability

### Quantization flag

There is **no `--quantization nvfp4` flag** in vLLM 0.20. NVFP4 is handled
automatically when the model weights contain NVFP4 quantization metadata
(stored in `config.json` as `quant_type: nvfp4`). The correct pattern:

```bash
vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
  --trust-remote-code \         # required for custom modeling code
  --kv-cache-dtype fp8          # required alongside NVFP4 weights
```

The critical env var for MoE NVFP4 routing (FlashInfer FP4 kernel path):

```bash
export VLLM_USE_FLASHINFER_MOE_FP4=1
export VLLM_FLASHINFER_MOE_BACKEND=throughput
```

Without `VLLM_USE_FLASHINFER_MOE_FP4=1`, vLLM falls back to a slower non-FP4
MoE kernel. This is silently degraded, not an error.

### Nemotron Nano 3 MoE — NVFP4 native weights confirmed

Model: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`
HuggingFace: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4

**Gating status:** Ungated, publicly accessible. No HF_TOKEN required.
No NGC API key required for weight download.

**Disk size:** 19.4 GB total (5 safetensor shards: 4×4 GB + 1×3.34 GB).

**BF16 variant** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`): ~58 GB.
Also ungated. NVFP4 is the preferred path — 3× smaller footprint, no accuracy
gating requirement.

**Architecture detail that matters for vLLM:**
The model is a hybrid Mamba-2 + MoE + Attention architecture (52 layers total:
23 Mamba-2, 23 MoE, 6 Attention). NVFP4 quantization is selectively applied:
- MoE layers: NVFP4
- Most Mamba-2 layers: NVFP4
- Attention layers: BF16 (kept full precision for accuracy)
- Mamba-2 layers that feed attention: BF16

This means the model is effectively a mixed-precision checkpoint. vLLM 0.20
supports this via `trust-remote-code` (the model ships custom modeling code).
The `--tool-call-parser qwen3_coder` is required for tool call parsing (NVIDIA
uses Qwen3-Coder formatting for tool calls in this model family).

**Other NVFP4 models available on HuggingFace (April 2026) for reference:**
- `nvidia/DeepSeek-V3.2-NVFP4` (full DeepSeek V3.2, requires 2×B300)
- `nvidia/DeepSeek-R1-0528-NVFP4`
- `nvidia/Llama-4-Scout-17B-16E-Instruct-FP4`
- `nvidia/Gemma-4-31B-IT-NVFP4`
- `nvidia/Llama-3.1-405B-Instruct-NVFP4`
- `nvidia/Llama-3.3-70B-Instruct-NVFP4`

Nemotron Nano 3 is the only one that fits on a B300 sharing VRAM with Parakeet
and Fish (all others require dedicated card or 2+ GPUs).

---

## 3. Co-Residency with Parakeet + Fish

**Current co-resident footprint:**
- Parakeet TDT 0.6B v3: ~9 GB VRAM active
- Fish S2-Pro: ~8 GB VRAM active
- CUDA context overhead per process: 300–800 MB × 2 processes = ~1–1.5 GB

Total resident: ~18–19 GB already consumed.

**B300 available:** 275 GB HBM3E. Pod reports 236 GB free before vLLM.

**vLLM default `--gpu-memory-utilization` is 0.90**, which on 275 GB = 247.5 GB
claimed by vLLM. With 236 GB free, this would over-commit. On this specific pod
configuration:

| Allocation | VRAM |
|---|---|
| Parakeet | ~9 GB |
| Fish S2-Pro | ~8 GB |
| CUDA context (2 existing processes) | ~1.5 GB |
| vLLM CUDA context | ~0.5 GB |
| Nemotron NVFP4 weights | ~20 GB |
| KV cache (fp8, 8 seq × 32k ctx) | ~6–8 GB |
| CUDA graph buffers (if enabled) | ~2–4 GB |
| **Total estimated** | ~47–51 GB |
| **Safe ceiling (leave 5 GB headroom)** | 55 GB |

With 275 GB total, a `--gpu-memory-utilization` of **0.20** (55 GB) gives vLLM
enough room while leaving Parakeet and Fish untouched:

```bash
--gpu-memory-utilization 0.20
```

If you want to increase KV cache size for longer context or higher concurrency,
go up to 0.30 (82.5 GB), which still leaves 192 GB free for the STT/TTS processes.
Do NOT exceed 0.80 — vLLM pre-allocates the KV cache as a contiguous block at
startup and will OOM-kill Parakeet or Fish if their pages get evicted.

**CUDA context isolation:**
vLLM, Parakeet (NeMo/RIVA), and Fish (SGLang) each run in separate Python
processes with separate CUDA contexts. CUDA contexts on the same device share the
physical memory but do NOT share page tables — each process has its own virtual
address space on the GPU. There is no risk of vLLM's KV-cache buffers corrupting
Fish's model weights.

**Isolation risk that IS real:** memory pressure. If vLLM's pre-allocated KV
cache + CUDA graph buffers consume the contiguous block that Parakeet or Fish
would need for a new allocation (e.g., Fish needs a 500 MB arena for a long TTS
request), those allocations fail with CUDA OOM. The `--gpu-memory-utilization 0.20`
ceiling prevents this. Set `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512` in all
three process environments to reduce fragmentation.

**No NeMo–vLLM isolation problem beyond the above.** NeMo (Parakeet's backend)
and vLLM both use PyTorch's CUDA allocator; they do not share allocator state
across processes. The only shared resource is raw HBM pages via the driver.

---

## 4. CUDA Graph Capture vs torch.compile

### Does vLLM's CUDA graph capture hit the Triton PTXAS sm_103a bug?

**Yes, on first boot with stable PyTorch wheels.** CUDA graph capture in vLLM
triggers Triton kernel compilation (autotuning) during the warmup eager pass that
precedes graph capture. If the bundled Triton ptxas does not recognize sm_103a,
capture fails at startup (not at first inference). The error signature is identical
to the fish-speech failure:

```
PTXASError: Internal Triton PTX codegen error
ptxas fatal: Value 'sm_103a' is not defined for option 'gpu-name'
```

**vLLM's kernel routing on B300:**
- Dense attention: FA4 (CUTLASS-based, NOT Triton-compiled at
  runtime — FA4 kernels are pre-compiled into the wheel). Safe.
- MoE routing (NVFP4 path): FlashInfer `VLLM_USE_FLASHINFER_MOE_FP4=1` uses
  precompiled FlashInfer CUTLASS kernels. Safe.
- Activation functions, sampling, and some utility ops: Triton JIT. Vulnerable
  to PTXAS regression.

**Safe paths on our pod:**

Option A (recommended): Install vLLM inside `.venv-nightly` which already has
Triton 3.7.0+git88b227e with sm_103a support confirmed.

```bash
source /path/to/.venv-nightly/bin/activate
pip install vllm==0.20.0 --no-deps  # avoid overwriting the working torch+triton
pip install vllm==0.20.0            # if dependency resolution is acceptable
```

Option B: Start with `--enforce-eager` (disables all CUDA graph capture). This
avoids the Triton compilation path entirely. Performance penalty: ~20-30%
throughput reduction vs full CUDA graph mode. For the voice latency use case
(single-request TTFT-critical), eager mode may be acceptable or even preferred
since graph capture primarily benefits high-concurrency batch throughput.

Option C: ptxas symlink (see §1). Riskier — the system ptxas path can change on
pod reimage.

**torch.compile:** vLLM 0.20 does not call `torch.compile` directly for inference
(unlike fish-speech's optional `--compile` flag). vLLM uses CUDA graphs (which
are different from torch.compile/inductor). CUDA graphs pre-record kernel launch
sequences; they don't trigger Triton's autotuning in the same path as inductor.
However, the eagerness warmup pass before CUDA graph capture does trigger Triton
JIT for non-FA4/non-FlashInfer ops. Summary: same bug class, different trigger
path.

---

## 5. OpenAI-Compatible API Surface

`vllm serve --port 8000` exposes:
- `GET  /v1/models` — model list
- `POST /v1/chat/completions` — chat completions (streaming via `stream: true`)
- `POST /v1/completions` — legacy completions
- `POST /v1/embeddings` — if embedding model

**Streaming format:** Standard SSE with `data: {"choices": [{"delta": ...}]}` lines,
terminated by `data: [DONE]`. Compatible with the OpenAI Python client and the
LiveKit OpenAI plugin.

**Tool-call shape:** When `--enable-auto-tool-choice --tool-call-parser qwen3_coder`
is set (required for Nemotron Nano 3), tool calls are emitted in OpenAI's
`function_call` / `tool_calls` format in the streaming delta. The shape is
OpenAI-API-compatible.

**LiveKit integration — drop-in replacement confirmed:**

```python
from livekit.plugins import openai as lk_openai

session = AgentSession(
    llm=lk_openai.LLM(
        model="model",                          # matches --served-model-name
        base_url="http://127.0.0.1:8000/v1",   # pod-local vLLM
        api_key="EMPTY",                        # vLLM accepts any string
    ),
    ...
)
```

LiveKit's `openai.LLM` accepts a `base_url` parameter; it uses the standard
OpenAI Python client under the hood. Any OpenAI Chat Completions-compatible
endpoint works. No code changes required beyond the constructor call.

**Caveat:** Nemotron Nano 3 requires `--reasoning-parser-plugin nano_v3_reasoning_parser.py`
for the internal reasoning trace. This parser plugin must be present in vLLM's
working directory. Without it, reasoning traces bleed into response text. For
voice dispatch where we want no reasoning trace, pass `enable_thinking=False`
in the chat template applied at the orchestrator layer, or set the model to
non-reasoning mode via the system prompt.

---

## 6. Anticipated Bottlenecks — Full List

### NGC API key tier
**Not required.** Nemotron Nano 3 NVFP4 weights are ungated on HuggingFace.
NGC containers (NeMo 25.11.01, vLLM 25.12.post1) require an NGC Developer
account (free tier, no payment) to pull. If you use `pip install vllm` without
NGC containers, no NGC key is needed at all.

### HF_TOKEN
**Not required for NVFP4 variant.** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`
and `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` are both ungated. Download
with `huggingface-cli download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` with
no token.

### VLLM_USE_FLASHINFER_MOE_FP4
Must be set to `1` before launch. If missing, MoE layers silently downgrade to
a slower non-FP4 kernel. There is no warning in vLLM logs.

### VLLM_WORKER_MULTIPROC_METHOD
Default is `fork` on Linux. With Parakeet and Fish already holding CUDA contexts,
forking can corrupt inherited CUDA state. Set:
```bash
export VLLM_WORKER_MULTIPROC_METHOD=spawn
```
This avoids the fork-after-CUDA-init hazard. Slower startup (~10s extra) but safe.

### PYTORCH_CUDA_ALLOC_CONF
```bash
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
```
Reduces fragmentation from mixed large (KV cache) and small (sampling) allocations.
Set this in all three process environments (vLLM, Parakeet service, Fish service).

### Port 8000 conflict
vLLM defaults to port 8000. Check:
```bash
ss -tlnp | grep 8000
```
Existing services are on 9100 (Parakeet), 9200 (Fish), 7880-7882 (LiveKit).
Port 8000 should be free. Confirm before launch; use `--port 8001` if another
service has claimed it.

### Logging — vLLM stdout vs structlog
vLLM emits Python `logging` to stdout with its own formatter (timestamps,
log-level prefixes). Our `worker.py` uses structlog JSON. These do not interfere:
they're separate processes. Redirect vLLM stdout to a dedicated log file:
```bash
vllm serve ... 2>&1 | tee /tmp/prism42-logs/vllm.log
```
Or use a systemd unit with `StandardOutput=journal` so `journalctl -u prism42-vllm`
keeps it separate from the worker log.

### Disk — weight download
| Variant | Disk |
|---|---|
| NVFP4 (recommended) | **19.4 GB** |
| BF16 | **~58 GB** |

NVFP4 is the clear choice. The pod needs 19.4 GB free in the model cache directory
(typically `~/.cache/huggingface/hub/`). Confirm with `df -h` before downloading.

### First-boot warm-up time
Two components:
1. **Weight loading + model init:** ~60–90 s for 19.4 GB NVFP4 weights over NVMe
   to HBM (NVMe bandwidth typically 5–7 GB/s → ~3–4 s I/O; model materialization
   and CUDA allocation adds ~60 s).
2. **CUDA graph capture (if enabled):** ~54 s baseline per vLLM's own
   documentation, plus Triton kernel autotuning during the pre-capture eager pass.
   On B300 with `.venv-nightly` Triton (sm_103a safe), this is ~90–120 s total
   on first cold start. Subsequent starts use kernel caches (~30–45 s).

With `--enforce-eager`: skip the 54 s CUDA graph capture. Total warm-up ~60–90 s.

**No NVFP4 calibration pass at startup.** NVFP4 weights are pre-calibrated
(PTQ + QAD was done by NVIDIA offline). Unlike FP8 dynamic quantization, there
is no calibration dataset pass at serve time.

### Concurrent requests vs Fish/Parakeet contention
With `--max-num-seqs 8` (NVIDIA's recommendation), vLLM queues up to 8 simultaneous
decode streams. In our single-caller PSAP scenario, concurrency is 1–2. The KV
cache allocation for 8 sequences × 32k context at FP8 = ~6–8 GB is pre-reserved.

Fish and Parakeet are not GPU-concurrent with decode (each processes one request
at a time per their server implementations). There is no GPU kernel-level conflict
because CUDA time-slices across processes via the MPS scheduler if active, or via
green context switching otherwise. On B300, NVIDIA MPS is recommended for
multi-process GPU sharing to reduce context-switch overhead:
```bash
nvidia-cuda-mps-control -d  # start MPS daemon
```

### Tokenizer compatibility
Nemotron Nano 3 uses a Qwen3-family tokenizer (HuggingFace Transformers compatible).
vLLM handles tokenization server-side. The LiveKit `openai.LLM` plugin sends raw
text strings in the `messages` payload; vLLM tokenizes internally. No tokenizer
compatibility issue between livekit-anthropic-plugin and livekit-openai-plugin —
you're switching the `llm=` argument in `AgentSession`, not the tokenizer. The
orchestrator sends text; vLLM tokenizes it. This is a non-issue.

---

## 7. Comparable Deployments

**vLLM official — GB300 + DeepSeek (February 13, 2026):**
https://vllm.ai/blog/gb300-deepseek
The authoritative vLLM team write-up for Blackwell B300/GB300 production
deployment. Uses NVFP4, `-tp 2` (for DeepSeek-class models that require 2
GPUs). Demonstrates the `VLLM_USE_FLASHINFER_MOE_FP4=1` pattern.

**NVIDIA vLLM blog — Nemotron Nano 3 on vLLM (December 15, 2025):**
https://vllm.ai/blog/run-nvidia-nemotron-3-nano
Official NVIDIA-authored post on Nemotron Nano 3 with vLLM. Includes BF16
and NVFP4 serve commands. Covers DGX Spark (GB10, SM 12.1) which has similar
Blackwell new-arch challenges to our B300.

**Lambda Labs — Deploying Nemotron 3 Nano with vLLM (2026):**
https://docs.lambda.ai/education/large-language-models/deploying-nemotron-3-nano/
Lambda's cloud GPU deployment guide. BF16 variant. Does not cover NVFP4 but
confirms the model is freely accessible and provides the `VLLM_SERVER_DEV_MODE=1`
flag for dev mode. BF16 disk size confirmed as ~58 GB.

**NVIDIA vLLM recipes — Nemotron-3-Nano-30B-A3B user guide:**
https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
NVIDIA's vLLM-published recipe guide. Canonical flag reference for both BF16
and NVFP4 variants. Most authoritative source for serve command flags.

**Red Hat Developer — NVFP4 quantization on Blackwell (February 4, 2026):**
https://developers.redhat.com/articles/2026/02/04/accelerating-large-language-models-nvfp4-quantization
Overview of NVFP4 deployment. Confirms ~3× smaller storage vs FP16 and
immediate deployability via vLLM on HuggingFace-hosted weights.

**Red Hat Developer — Configuring Blackwell GPUs for Red Hat AI (March 16, 2026):**
https://developers.redhat.com/articles/2026/03/16/configure-nvidia-blackwell-gpus-red-hat-ai-workloads
Production RHEL config guide for Blackwell. Relevant for systemd service setup.

**Spheron Blog — FP4 quantization on Blackwell cost analysis (2026):**
https://www.spheron.network/blog/fp4-quantization-blackwell-gpu-cost/
Throughput and cost comparison. Documents `VLLM_USE_FLASHINFER_MOE_FP4=1` for
MoE FP4 models. Recommends TRT-LLM over vLLM for dense NVFP4 models if maximum
throughput is the goal (not our scenario — we need OpenAI API compatibility).

No production write-up found specifically for a single-GPU B300 + vLLM 0.20 +
Nemotron Nano 3 + co-resident STT/TTS stack as of April 2026. Our deployment
is first-of-kind in this specific configuration.

---

## 8. Startup Script — `vllm-serve.sh`

```bash
#!/usr/bin/env bash
# vllm-serve.sh — B300 + Nemotron Nano 3 MoE NVFP4
# Run inside .venv-nightly (torch 2.13.dev+cu130, Triton 3.7.0+git88b227e)
# which has confirmed sm_103a support. Do NOT run against stable venv.
# Usage: bash vllm-serve.sh [--with-cuda-graphs]
set -euo pipefail

# ---------- environment ----------

# Tell the CUDA JIT compiler to target both SM100 (B200) and SM103 (B300).
# Required because vLLM's build-time arch list may not include 10.3.
export TORCH_CUDA_ARCH_LIST="10.0;10.3"

# FlashInfer NVFP4 MoE kernel: required for Nemotron's MoE layers to use
# the Blackwell-native FP4 GEMM path instead of a slower fallback.
export VLLM_USE_FLASHINFER_MOE_FP4=1

# FlashInfer MoE backend: "throughput" maximizes batch throughput.
# Alternative: "latency" (lower per-request latency at low concurrency).
# For PSAP voice (1-2 concurrent callers), "latency" may be better —
# test both after first boot confirms stability.
export VLLM_FLASHINFER_MOE_BACKEND=throughput

# Worker spawn method: avoids CUDA state corruption from forking after
# Parakeet and Fish have already initialized CUDA contexts on this card.
export VLLM_WORKER_MULTIPROC_METHOD=spawn

# PyTorch allocator: limits max split size to reduce HBM fragmentation
# when vLLM's large KV-cache blocks and Parakeet/Fish's smaller buffers
# compete for contiguous memory.
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512

# Enable NVIDIA MPS for lower-overhead context switching across the three
# GPU processes (vLLM + Parakeet + Fish). Start MPS daemon before this script.
# nvidia-cuda-mps-control -d  # run once at pod startup

# Uncomment if CUDA 13 system ptxas is needed to supplement vLLM's bundled
# Triton ptxas (workaround for sm_103a PTXAS regression):
# TRITON_PTXAS=$(python -c "import triton,os; \
#   print(os.path.join(os.path.dirname(triton.__file__),'backends/nvidia/bin/ptxas'))")
# ln -sf /usr/local/cuda/bin/ptxas "$TRITON_PTXAS"

# ---------- parse args ----------

ENFORCE_EAGER="--enforce-eager"           # safe default; remove after first confirmed boot
if [[ "${1:-}" == "--with-cuda-graphs" ]]; then
    ENFORCE_EAGER=""                       # enables CUDA graph capture (~54s extra warmup)
fi

# ---------- serve ----------

MODEL="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4"
SERVED_NAME="model"                        # matches base_url usage in worker.py
PORT=8000                                  # confirm free: ss -tlnp | grep 8000

exec vllm serve "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --port "$PORT" \
  --host 127.0.0.1 \                       # bind loopback only; LK worker is pod-local
  --tensor-parallel-size 1 \              # single GPU; model is 19.4 GB, fits comfortably
  --max-model-len 32768 \                 # trims default 262144 ctx; saves ~40 GB KV cache;
  \                                       #   voice turns are <2k tokens anyway
  --gpu-memory-utilization 0.20 \         # 275 GB × 0.20 = 55 GB claimed by vLLM; leaves
  \                                       #   ~220 GB free for Parakeet + Fish
  --kv-cache-dtype fp8 \                  # required by NVFP4 model card; matches PTQ path
  --max-num-seqs 8 \                      # NVIDIA recommended for this model; 8 concurrent
  \                                       #   decode streams
  --trust-remote-code \                   # required: model ships custom Mamba/MoE code
  --enable-auto-tool-choice \             # enables OpenAI tool_calls format in responses
  --tool-call-parser qwen3_coder \        # Nemotron Nano 3 uses Qwen3-Coder tool format
  --reasoning-parser-plugin nano_v3_reasoning_parser.py \  # suppress internal reasoning
  --reasoning-parser nano_v3 \            #   traces from leaking into response text
  $ENFORCE_EAGER \                        # disable CUDA graphs on first boot
  2>&1 | tee /tmp/prism42-logs/vllm.log  # separate from worker.log

# Worker.py integration:
#   llm=openai.LLM(model="model", base_url="http://127.0.0.1:8000/v1", api_key="EMPTY")
```

**First-boot checklist:**
1. Confirm `nvidia-smi` shows CUDA 13.x and ~236 GB free
2. Run: `ss -tlnp | grep 8000` — must return empty
3. Source `.venv-nightly`: `source /path/to/.venv-nightly/bin/activate`
4. Launch: `bash vllm-serve.sh` (with `--enforce-eager`, the default)
5. Wait ~90 s for model load. Look for `INFO: Application startup complete.`
6. Smoke test: `curl -s http://127.0.0.1:8000/v1/models | python -m json.tool`
7. Send one chat completion to confirm FP4 MoE kernel fires:
   `grep "NVFP4\|fp4\|flashinfer" /tmp/prism42-logs/vllm.log | head -5`

**Systemd unit** (drop in `/etc/systemd/system/prism42-vllm.service`):
```ini
[Unit]
Description=prism42 vLLM Nemotron Nano 3 NVFP4
After=prism42-fish.service prism42-parakeet.service
Requires=prism42-fish.service prism42-parakeet.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/prism42
EnvironmentFile=/opt/prism42/.env.agent
ExecStart=/opt/prism42/.venv-nightly/bin/bash /opt/prism42/scripts/vllm-serve.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## One-liner (systemd-style, for copy-paste)

```bash
TORCH_CUDA_ARCH_LIST="10.0;10.3" \
VLLM_USE_FLASHINFER_MOE_FP4=1 \
VLLM_FLASHINFER_MOE_BACKEND=throughput \
VLLM_WORKER_MULTIPROC_METHOD=spawn \
PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512 \
  vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
    --served-model-name model --port 8000 --host 127.0.0.1 \
    --tensor-parallel-size 1 --max-model-len 32768 \
    --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 \
    --max-num-seqs 8 --trust-remote-code --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --reasoning-parser-plugin nano_v3_reasoning_parser.py \
    --reasoning-parser nano_v3
```

---

## Citations

- vLLM v0.20.0 release notes: https://github.com/vllm-project/vllm/releases/tag/v0.20.0
- vLLM GB300 + DeepSeek blog (Feb 2026): https://vllm.ai/blog/gb300-deepseek
- vLLM Nemotron Nano 3 blog (Dec 2025): https://vllm.ai/blog/run-nvidia-nemotron-3-nano
- vLLM Nemotron recipes guide: https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
- Nemotron NVFP4 HuggingFace model card: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
- Nemotron BF16 HuggingFace model card: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
- NVIDIA NVFP4 QAD research page: https://research.nvidia.com/labs/nemotron/nemotron-qad/
- vLLM issue #30245 (sm_103a ptxas): https://github.com/vllm-project/vllm/issues/30245
- Red Hat NVFP4 article (Feb 2026): https://developers.redhat.com/articles/2026/02/04/accelerating-large-language-models-nvfp4-quantization
- Red Hat Blackwell config (Mar 2026): https://developers.redhat.com/articles/2026/03/16/configure-nvidia-blackwell-gpus-red-hat-ai-workloads
- Spheron FP4 on Blackwell: https://www.spheron.network/blog/fp4-quantization-blackwell-gpu-cost/
- Lambda Nemotron deploy guide: https://docs.lambda.ai/education/large-language-models/deploying-nemotron-3-nano/
- vLLM conserving memory docs: https://docs.vllm.ai/en/latest/configuration/conserving_memory/
- vLLM CUDA graphs design: https://docs.vllm.ai/en/latest/design/cuda_graphs/
- vLLM GPU install guide: https://docs.vllm.ai/en/latest/getting_started/installation/gpu/
- LiveKit OpenAI-compatible LLMs: https://docs.livekit.io/agents/models/llm/openai-compatible-llms/
- Triton issue #8539 (ptxas sm_121a / Blackwell): https://github.com/triton-lang/triton/issues/8539
- Tensorfuse — reducing vLLM cold start: https://tensorfuse.io/docs/blogs/reducing_gpu_cold_start
- Prism42 B300 bench: docs/livekit-kb/09-b300-voice-bench.md
- Prism42 Triton PTXAS discovery: docs/livekit-kb/20-blackwell-b300-torch-compile-discovery.md
