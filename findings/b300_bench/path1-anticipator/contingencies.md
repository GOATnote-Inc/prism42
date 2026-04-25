# Path 1 Anticipator: B300 / SM103 + vLLM 0.20 + Nemotron-NVFP4 Contingency Map

Researched: 2026-04-24. All claims tagged verified-on-Blackwell or claimed-unverified.

---

## Failure Mode 1: NVFP4 MoE backend hard-fails — "NvFp4 MoE backend 'FLASHINFER_CUTLASS' does not support the deployment configuration"

**Symptom**

Gate startup check sees: `ValueError: NvFp4 MoE backend 'FLASHINFER_CUTLASS' does not support the deployment configuration since kernel does not support current device.`
Server exits at model load, before serving a single token.

**Root cause**

vLLM's NVFP4 MoE backend selection picks FLASHINFER_CUTLASS but the cubin was compiled for SM100 (B200) and does not match SM103 (B300). Separately observed on SM120 consumer Blackwell where CUTLASS GEMM kernels declare SM100 MoE functions but the implementation file is never compiled for the actual arch, producing undeclared-symbol crashes at import.
(verified-on-Blackwell: sm_120; claimed-unverified: sm_103 specifically, but root cause is identical arch-selection logic)

**Fix**

Set env before launching vLLM serve:
```bash
export VLLM_USE_FLASHINFER_MOE_FP4=1
export VLLM_FLASHINFER_MOE_BACKEND=throughput
```
If CUTLASS still selected, also set:
```bash
export VLLM_NVFP4_GEMM_BACKEND=MARLIN
```
Note: `VLLM_NVFP4_GEMM_BACKEND=MARLIN` causes a crash on MoE models in vLLM <= 0.19 (per issue #38971 — no override existed then); confirm whether 0.20 exposes `VLLM_NVFP4_MOE_BACKEND` as a separate knob. Fallback: `--moe-backend marlin` CLI flag, verified working on SM120 at ~46 tok/s.

**Source**

- https://github.com/vllm-project/vllm/issues/33333 (opened 2026-01, sm_120)
- https://github.com/vllm-project/vllm/issues/35065 (opened 2026-02, sm_120 RTX 5090)
- https://github.com/vllm-project/vllm/issues/38971 (opened 2026-03, no MARLIN override in 0.19, 20-25% throughput loss from CUTLASS regression)
- https://github.com/flashinfer-ai/flashinfer/issues/2723 (CUTLASS grouped block-scaled GEMM garbage output on SM120, fix = compute_120f + CUDA 13.0)
- https://github.com/vllm-project/vllm/issues/29030 (undefined symbol cutlass_moe_mm_sm100 on SM12.0, root cause = declare without compile)

---

## Failure Mode 2: CUDA graph capture crash — Illegal Instruction / cudaErrorIllegalInstruction on NVFP4 Mamba-MoE with batch > 1

**Symptom**

Gate warmup request (batch_size > 1) raises `cudaErrorIllegalInstruction`. vLLM V1 engine dies during CUDA graph record step. Single-request (batch=1) may succeed but concurrent batch fails silently or dumps core.

**Root cause**

Nemotron-3-Nano's hybrid Mamba-2 + attention architecture triggers an invalid instruction during CUDA graph capture at batch_size > 1 on Blackwell sm_121 (DGX Spark). The graph-capture path attempts to record a batch covering Mamba SSM cache alignment that has no valid kernel for the active arch/batch-size combination.
(verified-on-Blackwell: sm_121 DGX Spark; claimed-unverified: sm_103 B300 specifically)

**Fix**

```bash
# Disable V1 engine + eager mode
export VLLM_USE_V1=0
vllm serve ... --enforce-eager --no-async-scheduling
```
Cost: CUDA graphs deliver roughly 8x throughput vs eager on matched hardware. On a B300 with native sm_103 binaries from this build, re-test without `--enforce-eager` first at batch=1, then batch=2, before assuming eager is required. If graphs capture cleanly at all tested batch sizes, drop `--enforce-eager`.

**Source**

- https://github.com/NVIDIA-NeMo/Nemotron/issues/125 (opened 2026-03, DGX Spark / sm_121, verified)
- https://github.com/vllm-project/vllm/issues/37242 (sm_120 RTX 5090 WSL2: CUDA graphs work without --enforce-eager after sm_120 cubin fix, 2026-03)
- https://docs.vllm.ai/en/stable/design/cuda_graphs/ (FULL_AND_PIECEWISE most performant for MoE, also most memory + longest capture)

---

## Failure Mode 3: FlashInfer cubin ABI mismatch / "module not found" at runtime — JIT fallback to missing system deps

**Symptom**

Gate health-check response is slow or fails with: `RuntimeError: No supported CUDA architectures found` or `ImportError: flashinfer._kernels` or JIT compile hangs because `nvcc`, `ninja-build`, or CUDA headers are absent on the pod.

**Root cause**

Two distinct sub-causes:
1. FlashInfer cubin package (`flashinfer-cubin`) is pinned to SM100/SM103 prebuilt cubins. If the installed version predates SM103 support or mismatches the vLLM 0.20 ABI (which moved to PyTorch 2.11 + CUDA 13.0), the runtime falls back to JIT. JIT then requires `gcc`, `python3-dev`, `nvcc`, and `ninja-build` on the pod — all commonly absent in minimal NGC containers.
2. vLLM's version-comparison logic for flashinfer has a known string-comparison bug (vLLM <= 0.10.0, fixed in PR #22314): "0.2.10" < "0.2.3" as strings, causing silent fallback even with correct version installed.
(verified-on-Blackwell: sm_120 SM121; string comparison bug verified-on-all)

**Fix**

```bash
# Verify flashinfer version semantically
python -c "import flashinfer; print(flashinfer.__version__)"

# Install system JIT deps as insurance
apt-get install -y gcc python3-dev ninja-build

# Pin flashinfer-cubin to the version vLLM 0.20 requires (FlashInfer 0.6.6 per v0.19/0.20 release notes)
pip install "flashinfer-python==0.6.6" "flashinfer-cubin==0.6.6"

# Confirm cubin is sm103-capable
python -c "import flashinfer; print(dir(flashinfer))"
```
Also check: `VLLM_USE_FLASHINFER_MOE_FP4=1` must be set or vLLM 0.20 will not route NVFP4 MoE through FlashInfer at all.

**Source**

- https://github.com/vllm-project/vllm/issues/37714 (5 sequential Blackwell SM120+CUDA13 pip-install failures, 2026-03; failure #2 = JIT missing system deps)
- https://github.com/vllm-project/vllm/issues/22297 (string version comparison bug, fixed PR #22314, 2025)
- https://discuss.vllm.ai/t/flashinfer-latest-version-is-not-working-with-vllm/1424 (FlashInfer 0.2.10 treated as < 0.2.3 due to string compare, 2025)
- vLLM v0.19.0 release notes: FlashInfer 0.6.6 update — https://github.com/vllm-project/vllm/releases/tag/v0.19.0

---

## Failure Mode 4: sm_103 silently absent from compiled binaries — TORCH_CUDA_ARCH_LIST="10.0;10.3" drops 10.3 at cmake step

**Symptom**

Gate runs but all B300 NVFP4 GEMM kernels fall through to PTX JIT path — extreme TTFT (30-90s first token). `cuobjdump` on the installed vLLM .so shows no `sm_103` section. Or: cmake emits no sm_103 objects because the conditional gate `CMAKE_CUDA_COMPILER_VERSION >= 12.8` or `cuda_archs_loose_intersection` filtered it.

**Root cause**

vLLM CMakeLists.txt gates SM103 kernel compilation on CUDA compiler >= 12.8 AND the arch surviving `cuda_archs_loose_intersection()` against `CUDA_SUPPORTED_ARCHS`. If torch was compiled for `10.0` only (the B200 wheel), the intersection check drops `10.3`. Additionally, SM103 only appears in conditional Blackwell-specific sections in CMakeLists.txt — it is not in the baseline `CUDA_SUPPORTED_ARCHS` list. Result: build completes without error but emits zero sm_103-specific code.
(claimed-unverified for sm_103 specifically; verified pattern for sm_120 in issue #29030)

**Fix**

```bash
# Before source build, force both archs
export TORCH_CUDA_ARCH_LIST="10.0+PTX;10.3+PTX"

# Confirm nvcc version supports 10.3
nvcc --version  # must be >= 12.8 (CUDA 13.0 ships 12.8+ nvcc)

# After build, verify sm_103 binary presence
python -c "
import torch, vllm
import subprocess, glob
sos = glob.glob('/opt/venv/lib/python*/site-packages/vllm/*.so')
for s in sos[:3]:
    out = subprocess.run(['cuobjdump', '-lelf', s], capture_output=True, text=True)
    if 'sm_103' in out.stdout:
        print(f'sm_103 found in {s}')
"
```
If sm_103 is absent: rebuild with `TORCH_CUDA_ARCH_LIST="10.0;10.3"` and `CMAKE_CUDA_ARCHITECTURES="1000a;1030a"` explicitly passed to cmake.

**Source**

- https://github.com/vllm-project/vllm/blob/main/CMakeLists.txt (cuda_archs_loose_intersection logic, 10.3a in conditional Blackwell blocks)
- https://github.com/vllm-project/vllm/issues/29030 (undefined symbol pattern from arch/compile mismatch, SM12.0, 2025)
- https://docs.vllm.ai/en/stable/getting_started/installation/gpu/ (TORCH_CUDA_ARCH_LIST usage)

---

## Failure Mode 5: reasoning-parser plugin not found / qwen3_coder tool-call parser drops tool_calls in streaming

**Symptom A (reasoning-parser)**

Gate sees: `FileNotFoundError: nano_v3_reasoning_parser.py` or `ModuleNotFoundError: nano_v3`. Server starts but all responses return empty reasoning field. Or: reasoning content leaks into `content` field and `tool_calls` array is empty.

**Symptom B (qwen3_coder streaming)**

Gate streaming tool-call test returns first chunk missing `"type":"function"` field. Strict-schema consumers (livekit-plugins-openai) reject the chunk; tool invocation silently fails or errors 500.

**Root cause A**

`nano_v3_reasoning_parser.py` must be in the cwd at vLLM serve launch OR an absolute path must be passed to `--reasoning-parser-plugin`. The HuggingFace card requires manually `wget`-ing the file before launch. If it is absent, vLLM falls back to no reasoning parser; combined with tool-call parsing, the model bleeds reasoning tokens into content.

**Root cause B**

vLLM issue #16340 (reported 0.8.3, fixed in PR #17340): streaming tool calls with `tool_choice: {type: function}` omit `"type":"function"` in the first delta chunk. vLLM 0.19+ improved this but qwen3_coder parser has a separate known bug: tool-call XML emitted inside `<think>` reasoning region is not extracted into `tool_calls` (issue #39056, vLLM 0.19, 2026-04). With long system prompts, the parser produces an infinite `!!!!` stream (issue #22975).

**Fix A**

```bash
# Download parser before server launch
wget -q https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py \
  -O /workspace/nano_v3_reasoning_parser.py

# Launch with absolute path
vllm serve ... \
  --reasoning-parser-plugin /workspace/nano_v3_reasoning_parser.py \
  --reasoning-parser nano_v3 \
  --tool-call-parser qwen3_coder
```

**Fix B**

For livekit-plugins-openai's `_strict_tool_schema=False` workaround: also set `enable_thinking=false` in client requests if the prism42 voice path does not need reasoning on every turn (reduces chance of think-region tool-call bleed). If reasoning is required: ensure vLLM >= 0.20 which has PR #30671 merged (tool + reasoning parser coexistence fix).

**Source**

- https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 (official launch command, reasoning-parser-plugin path requirement, 2026-01)
- https://github.com/vllm-project/vllm/issues/16340 (missing "type":"function" in streaming, vLLM 0.8.3, PR #17340 fix)
- https://github.com/vllm-project/vllm/issues/39056 (tool-call XML inside think region lost, vLLM 0.19, 2026-04)
- https://github.com/vllm-project/vllm/issues/22975 (qwen3_coder infinite "!" stream on long input, 2025)
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3 (reasoning+tool-call coexistence bug, fixed PR #30671)

---

## Failure Mode 6: Attention backend mis-selection — FA4 "Unsupported FA version: None" or falling back to vllm-internal MLA

**Symptom**

Gate observes TTFT >> baseline, or server logs show `Unsupported FA version: None` and falls back to FA2/FA3. Or logs show "using vllm-internal MLA" instead of FlashInfer MLA (the expected default on Blackwell per vLLM 0.18+).

**Root cause**

`VLLM_FLASH_ATTN_VERSION=4` is not accepted by vLLM <= 0.12 (only 2 and 3 valid). vLLM 0.20 re-enabled FA4 as default MLA prefill backend on SM90+ — but the env var override path for FA4 may not be wired for SM103 if the build dropped sm_103 binaries (see Failure Mode 4). Additionally, TRTLLM GEN is the default prefill backend on SM100/SM103 per vLLM 0.18+; FA4 is the MLA path, not the dense attention path. Mis-setting both can produce a no-op that silently stays on FA2.
(claimed-unverified: exact FA4 behavior on sm_103 specifically)

**Fix**

```bash
# Do NOT set VLLM_FLASH_ATTN_VERSION=4 — it is not a valid override key in vLLM 0.20
# FA4 is auto-selected for MLA prefill on SM100/103 if the binary is present
# To verify backend actually selected:
vllm serve ... 2>&1 | grep -i "attention backend\|flash_attn\|trtllm\|flashinfer"

# If TRTLLM is missing on sm_103, disable it and let FlashInfer take over:
vllm serve ... --attention-config '{"use_trtllm_attention": 0}'
```

**Source**

- https://discuss.vllm.ai/t/how-to-apply-fa4-on-b200/2133 (FA4 not in vLLM 0.12.0, env var invalid, 2026)
- https://docs.vllm.ai/en/latest/design/attention_backends/ (FA4 default on SM100+ for MLA prefill)
- vLLM v0.20.0 release notes: "FA4 re-enabled as the default MLA prefill backend" — https://github.com/vllm-project/vllm/releases/tag/v0.20.0

---

## Failure Mode 7: Prefix caching silently disabled or causing accuracy regression with NVFP4 + FP8 KV cache

**Symptom**

Gate correctness check fails: responses differ between cached and uncached identical prefixes. Or gate startup emits warning that prefix caching was disabled. Or VRAM OOMs faster than expected on repeated identical system prompts.

**Root cause**

`--enable-prefix-caching` with `--kv-cache-dtype fp8` (required for Nemotron NVFP4) has a reported incompatibility path: issue #37714 (failure #4) specifically names `FLASH_ATTN backend incompatible with FP8 KV cache`. Prefix caching with quantized KV cache requires the attention backend to support quantized block reuse; if the backend selected (e.g., FLASH_ATTN fallback) does not, vLLM either silently disables it or raises at startup. Separately, vLLM bug #8242 shows prefix caching lowers gpu_memory_utilization unexpectedly.
(verified pattern for FLASH_ATTN + FP8 KV; claimed-unverified for FlashInfer + FP8 KV on sm_103)

**Fix**

```bash
# Recommended: do NOT enable prefix caching on first gate run
# Omit --enable-prefix-caching entirely for gate validation

# If required: use FlashInfer backend (not FLASH_ATTN) with fp8 KV
vllm serve ... \
  --kv-cache-dtype fp8 \
  # no --enable-prefix-caching on first pass
```
Add prefix caching only after baseline gate passes, then re-run gate with it enabled as a separate test.

**Source**

- https://github.com/vllm-project/vllm/issues/37714 (failure #4: FLASH_ATTN + FP8 KV incompatibility, 2026-03)
- https://github.com/vllm-project/vllm/issues/8242 (prefix caching + gpu_memory_utilization regression, 2024)
- vLLM search results showing `--no-enable-prefix-caching` used as workaround in NVFP4 MoE test configs (April 2026)

---

## Failure Mode 8: Co-residency VRAM exhaustion — CUDA graph persistent buffers starve Fish/Parakeet allocations

**Symptom**

Gate co-residency check: Fish (ASR) or Parakeet (STT) fails to allocate after vLLM warms up, or latency p99 spikes when vLLM CUDA graph buffers are allocated during warmup. OOM kill on Fish/Parakeet process.

**Root cause**

vLLM CUDA graph capture (FULL_AND_PIECEWISE mode for MoE) pre-allocates persistent replay buffers for every batch-size bucket. These are not released during inference. On B300 with 192 GB HBM, this is less acute than smaller GPUs, but with `gpu_memory_utilization=0.90` (default), the graph buffers plus KV cache pool can leave Fish/Parakeet with no contiguous allocation window for their own CUDA contexts.
(claimed-unverified: no published B300 co-residency latency-jitter measurement found; general CUDA graph memory behavior verified-on-vLLM)

**Fix**

```bash
# Lower vLLM memory ceiling to leave headroom for co-residents
vllm serve ... --gpu-memory-utilization 0.80

# Or reduce graph capture bucket count
vllm serve ... \
  --compilation-config '{"cudagraph_num_of_warmups": 1}' \
  --max-num-seqs 8

# Verify sum of gpu_memory_utilization across all processes <= 1.0
# Fish/Parakeet set their own CUDA memory limits; check their config.
```

**Source**

- https://docs.vllm.ai/en/latest/configuration/conserving_memory/ (CUDA graphs take extra memory; adjust compilation_config)
- https://github.com/vllm-project/vllm/issues/14632 (free GPU memory when using CUDA graphs, pattern discussion)
- https://docs.vllm.ai/projects/vllm-omni/en/stable/configuration/gpu_memory_utilization/ (co-residency: sum of gpu_memory_utilization must not exceed 1.0)

---

## Failure Mode 9: First-token JIT spike — TTFT 30-90s on first NVFP4 forward with missing native sm_103 binary

**Symptom**

Gate TTFT check: first request takes 30-90 seconds. Subsequent requests are fast. Server logs show nvcc invoked or `triton` JIT compilation during first forward pass.

**Root cause**

If the source build did not successfully emit sm_103 binaries (Failure Mode 4), vLLM falls through to Triton JIT or FlashInfer JIT for NVFP4 GEMM kernels on first call. FlashInfer JIT cache is cold on pod startup. On Blackwell, NVFP4 JIT compilation is non-trivial: the nvcc bundled with torch < 2.11 does not understand `compute_120f` flags, but sm_103 has a different flag (`compute_103a`). If nvcc version is mismatched, JIT can fail silently and fall back to emulation.
(claimed-unverified: specific TTFT numbers on sm_103 B300; verified JIT pattern on sm_120 from search results)

**Fix**

```bash
# Prime the JIT cache explicitly before gate runs
python -c "
import vllm
from vllm import LLM
# Just instantiate — triggers kernel compilation
print('Kernel warm-up complete')
"

# Or: run one warm-up inference request before gate timer starts
curl -s -o /dev/null http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"model","messages":[{"role":"user","content":"hi"}],"max_tokens":1}'
```
If JIT is the culprit: verify sm_103 binary presence (see Failure Mode 4 fix). If absent, rebuild.

**Source**

- https://www.edge-ai-vision.com/2025/10/nvidia-blackwell-the-impact-of-nvfp4-for-llm-inference/ (NVFP4 TTFT performance on Blackwell)
- https://github.com/vllm-project/vllm/issues/37714 (JIT missing system deps as failure mode, SM120 CUDA13)
- Medium post: Gemma 4 NVFP4 on vLLM Desktop Blackwell WSL2 — FlashInfer JIT doesn't know SM12.x (2026-04)

---

## Likelihood Ranking (highest first)

1. Failure Mode 1 — NVFP4 MoE backend hard-fail (FLASHINFER_CUTLASS not matching sm_103)
2. Failure Mode 5 — reasoning-parser plugin path + qwen3_coder streaming tool_calls drop
3. Failure Mode 4 — sm_103 silently absent from build (TORCH_CUDA_ARCH_LIST drop)
4. Failure Mode 3 — FlashInfer cubin ABI mismatch / JIT fallback
5. Failure Mode 2 — CUDA graph Illegal Instruction on Mamba-MoE batch > 1

---

*Research completed 2026-04-24. All URLs accessed during this session. "verified-on-Blackwell" = confirmed in a filed GitHub issue or official blog on a Blackwell GPU. "claimed-unverified" = extrapolated from analogous sm_120/sm_121 evidence to sm_103 B300.*
