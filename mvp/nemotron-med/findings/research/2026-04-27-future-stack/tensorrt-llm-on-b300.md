# vLLM + CUDA 13.2.1 on B300 Upgrade Brief

**Date:** 2026-04-27 · **Status:** research-only · **Verdict:** 🟡 YELLOW —
sandbox-first cutover, never both pods at once.

## 1. Current state (do not modify)

- **vLLM pinned:** v0.20 (`agents/livekit/worker.py:705` comment;
  `dispatcher_fsm.py`; CLAUDE.md "vLLM v0.20.0 has B300/GB300 (SM 10.3)
  support with allreduce fusion enabled by default").
- **Model:** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`
  (`agents/livekit/worker.py:731`).
- **Stack on B300 pod:**
  - Parakeet (ASR): NeMo 25.09 → CUDA 12.9.1
    (`infra/b300/services/parakeet/Dockerfile:30`)
  - Fish Speech (TTS): PyTorch 25.02 → CUDA 12.8 + SGLang ≥ 0.4.0
    (`infra/b300/services/fish-speech/Dockerfile:14`)
  - vLLM serve at `http://127.0.0.1:8001/v1`
- **Compiler arch list:** `TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0 10.0 10.3 12.0 12.1+PTX"`
  ensures SM 10.3 (Blackwell Ultra) coverage.

## 2. Target state (post-cutover, sandbox first)

- **vLLM:** latest stable (v0.19.x line confirmed shipping on PyPI as of
  late April 2026; NVFP4 + B300 tuning improvements in v0.19.0+).
- **CUDA:** 13.2.1 driver on host; CUDA 13.0 vLLM wheels are
  forward-compatible per NVIDIA Blackwell Compatibility Guide.
- **Transformers:** ≥ 5.x is now a hard requirement in v0.19+ (breaking
  change from v4).
- **Allreduce fusion:** enabled by default; B300 tuning re-applied via
  vllm-project/vllm PR #30629.

Sources:
- https://pypi.org/project/vllm/
- https://github.com/vllm-project/vllm/releases
- https://docs.vllm.ai/en/stable/getting_started/installation/gpu/
- https://docs.nvidia.com/cuda/blackwell-compatibility-guide/
- https://blog.vllm.ai/2026/02/13/gb300-deepseek.html
- https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html

## 3. Delta — what would change

| Layer | Current | Target | Scope |
|---|---|---|---|
| vLLM version | 0.20 (pinned) | latest stable (0.19.x line + NVFP4 fixes) | docker-compose pin + serve flags |
| CUDA host driver | 12.x | 13.2.1 | Brev pod driver upgrade (host-level) |
| CUDA wheel for vLLM | (matches host) | CUDA 13.0 (forward-compatible) | wheel install only |
| Transformers | inferred v4.x | ≥ 5.x | one-line bump in pyproject; verify model card parses |
| AllReduce fusion | on (default) | on (default, retuned for B300) | no action |

**Files that would change** (none modified today):
- `infra/b300/docker-compose.yml` — vLLM service pin (currently commented
  out at lines 94-116; if activating, pin `vllm/vllm-openai:<ver>`)
- `agents/livekit/worker.py:705` — comment update only
- Parakeet Dockerfile — likely no change (NeMo 25.09 is forward-compat)
- Fish Dockerfile — bump base to `nvcr.io/nvidia/pytorch:25.03-py3` if
  CUDA 13.0 alignment is desired (not strictly required)

## 4. Risk surface

| Risk | Severity | Mitigation |
|---|---|---|
| **NVFP4 CUDA-Graph regression on Blackwell** with batch > 1 (`cudaErrorIllegalInstruction`, reported in vllm-project/vllm tracker 2026) | HIGH | `--disable-cuda-graph` flag, OR fall back to BF16 for the regression window. Test at batch sizes 1, 4, 8 in sandbox. |
| **Transformers v5 breaking change** | MEDIUM | Pre-flight: `python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4')"` before deploy. |
| **CUDA 13.2.1 driver mismatch with v13.0 wheel** | LOW–MEDIUM | NVIDIA guarantees forward compat; verify with `nvidia-smi` + `python -c "import torch; print(torch.cuda.get_device_capability(0))"` returning `(10, 3)`. |
| **Latency regression** vs current 0.20 + 12.9 | MEDIUM | Measure p50/p95 in sandbox; gate cutover on < 10% delta from baseline. |
| **Voice end-to-end p95 > 1.5 s** (CLAUDE.md §0 hackathon target) | HIGH if it slips | 2-minute live-call test in sandbox before any prod traffic shift. |

## 5. B300 compatibility checklist

Pre-deployment, on the **sandbox pod** (not the live demo pod):

- [ ] `nvidia-smi` reports CUDA 13.2.1 + driver ≥ 555.x
- [ ] `python -c "import torch; print(torch.cuda.get_device_capability(0))"` → `(10, 3)`
- [ ] `transformers.__version__` ≥ 5.0
- [ ] Model load: `AutoModelForCausalLM.from_pretrained('nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4')` succeeds
- [ ] vLLM serve: 100-token gen × 8 parallel requests, p95 < 150 ms
- [ ] Voice pipeline: full STT → LLM → TTS turn, end-to-end p95 < 1.5 s

Expected wins on B300 vs B200 (per NVIDIA architecture guide):
- +55.6% FP4 perf (14 PFLOPS NVFP4)
- +55.6% HBM (288 GB HBM3E)
- 8 TB/s vs 7.7 TB/s bandwidth

Expected wins from latest vLLM vs 0.20: 5–15% TTFT reduction *if* NVFP4
kernels stay on the fast path.

## 6. Recommendation — test order

🟡 **YELLOW. Sandbox-first, parallel-canary, never both pods at once.**

1. **Sandbox pod A** (fresh Brev instance, isolated from prod):
   - Deploy CUDA 13.2.1 + latest vLLM + Nemotron-Nano-NVFP4.
   - Go gate: 100-token × 8-parallel p95 < 150 ms; voice end-to-end p95 < 1.5 s.
   - Abort: CUDA-Graph error at batch > 1 → `--disable-cuda-graph` or revert
     to BF16.
2. **Live-call sandbox test:** 2-minute synthetic 911 call, full pipeline,
   measure all four legs (STT, LLM TTFT, TTS, RTT).
3. **Production pod B** stays on 0.20 + 12.9. Run sandbox A in parallel for
   1 week; canary 5% of inbound LiveKit traffic to A, 95% to B.
4. **Cutover** only if A's p95 latency is within 10% of B's baseline AND
   error rate < 0.1%.

**Never both pods upgraded simultaneously.** The ElevenLabs fallback
(`prism42-console.vercel.app/prism42-v3`) does NOT touch this stack — it
calls the Anthropic API directly via the Next.js function — so it is not
affected by this change. Keep it as the safety-net path during the cutover.

---

## Sources

- https://pypi.org/project/vllm/
- https://github.com/vllm-project/vllm/releases
- https://docs.vllm.ai/en/stable/getting_started/installation/gpu/
- https://docs.nvidia.com/cuda/blackwell-compatibility-guide/
- https://blog.vllm.ai/2026/02/13/gb300-deepseek.html
- https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
- https://github.com/vllm-project/vllm/pull/30629
- https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-25-02.html
