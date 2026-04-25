# B300 purr — concrete migration plan

> Synthesis of 4 parallel research briefings (KB 21-24). Goal: take
> the prism42 voice stack from "audio works but feels clunky"
> (current TTFA ~5-7 s) to "perceptually instant" (target TTFA <500 ms)
> by pinning the LLM to B300 and finishing the existing Parakeet
> streaming lever. Mainline-frozen-friendly: every step ships behind
> an env flag with zero-regression rollback.

## Why this exists

The B300 SXM6 currently runs Parakeet (~9 GB) + Fish (~8 GB) on a
275 GB card. **236 GB GPU free**, **0% utilization at idle**. We
bought a Blackwell datacenter card to do TLS round-trips to a
Kubernetes cluster in some other region. The LLM hop is the latency
ceiling, and it lives off-card.

The path to "purr" is architectural, not tactical:

```
                                BEFORE                        AFTER
LLM hop      Anthropic Cloud (TLS round-trip ~500 ms)    Nemotron Nano 3 MoE on B300 (~25 ms)
STT hop      Parakeet TDT v3 batch /transcribe (~614 ms) Parakeet TDT v3 streaming /ws (~200 ms)
                                                          + future: Nemotron Speech (~24 ms)
TTS hop      Fish S2-Pro eager mode (RTF 1.96)            Fish + torch.compile via nightly (RTF ~0.7)
GPU util     0% idle → 3% peak                            0% idle → 60-90% during synth
TTFA p50     ~5-7 s ("first word, then pauses")           <500 ms ("snappy")
```

## Reading order

Read these four briefings before executing the plan; this doc
references their findings without re-citing:

1. [`21-nemotron-nano-3-moe-vllm-b300.md`](21-nemotron-nano-3-moe-vllm-b300.md) — model architecture, vllm serve recipe, license.
2. [`22-nvidia-riva-nemotron-asr.md`](22-nvidia-riva-nemotron-asr.md) — Riva vs raw NeMo, why we skip Riva NIM, Nemotron Speech path.
3. [`23-vllm-020-nvfp4-b300-deployment.md`](23-vllm-020-nvfp4-b300-deployment.md) — vLLM 0.20 ops on B300, NVFP4, co-residency.
4. [`24-livekit-llm-backend-swap.md`](24-livekit-llm-backend-swap.md) — `livekit-plugins-openai` drop-in pattern, tool-schema gotcha.

Plus the upstream context: [`20-blackwell-b300-torch-compile-discovery.md`](20-blackwell-b300-torch-compile-discovery.md) (the Triton PTXAS sm_103a regression we discovered + PR'd to fishaudio/fish-speech#1274 — same bug bites vLLM).

## Pod baseline (probed 2026-04-25 07:31 UTC)

| Item | State |
|---|---|
| NGC docker auth | absent |
| NGC CLI | not installed |
| HF token cache | absent |
| `vllm` (system Python) | not installed |
| `nemo_toolkit` (system Python) | not installed |
| `riva.client` (system Python) | not installed |
| GPU memory used | 29 GB / 275 GB |
| `.venv-nightly` (existing) | torch 2.13.0.dev20260424+cu130 + Triton 3.7.0+git88b227e ✓ sm_103a-aware |

**Implication**: this is essentially a bare-metal NVIDIA-stack bring-up. Every credential, every install, every env var has to be staged.

## Phase plan — six phases, env-flag-gated, rollback-clean

### Phase A — Finish lever #2 (Parakeet streaming `/ws` prod swap) | 30 min, zero new infra

Already coded (commit `2644b29`, branch landed on main). Server.py has the `/ws` endpoint emitting `partial`/`preflight`/`final`. parakeet_stt.py has `ParakeetSpeechStream` wired to consume it. **Blocker**: pid 60210 still runs the old batch-only server.

```
# operator action — single SSH command:
ssh prism-mla-b300-h4h5 "sudo kill 60210 && sleep 2 && \
  sudo systemctl restart prism42-parakeet"
# verify:
curl -sS http://127.0.0.1:9100/openapi.json | python3 -c \
  'import json,sys; d=json.load(sys.stdin); print(sorted(d[\"paths\"].keys()))'
# expect: ['/healthz', '/transcribe', '/ws']
```

Then on the worker side: env flip `PRISM42_PARAKEET_STREAMING=1` (already True by default; we set it to 0 as fallback when /ws was 404'ing). Restart prism42-worker.

**Acceptance**: `t_stt_ms` median drops 614 → ~200 ms. `overlap.early_llm_trigger` log line fires (lever #11/#12 unblocked).

### Phase B — Wire `LLM_BACKEND` env flag on worker.py | 15 min, no deploy yet

Land the 12-line diff (per KB 24) on `voice/llm-backend-flag` branch. Default `LLM_BACKEND=anthropic` keeps current behavior. Setting `LLM_BACKEND=vllm-local` swaps to OpenAI-shape pointing at `VLLM_BASE_URL`.

**Acceptance**: `voice/llm-backend-flag` branch merges to main. Pod git pull. Worker restarts with default flag = anthropic. Zero behavior change. The wiring is now ready.

### Phase C — Provision credentials + venv | 30-60 min

Bottleneck inventory (everything missing):

```
On the pod:
  HF_TOKEN              huggingface.co/settings/tokens — read-only, free
                        export HF_TOKEN=hf_...
                        echo $HF_TOKEN > ~/.cache/huggingface/token
  NGC_API_KEY           ngc.nvidia.com — Developer Program, free for R&D
                        ngc config set --api-key ...
                        docker login nvcr.io  (uses NGC key)

In .env on the pod:
  HF_TOKEN=hf_...
  NGC_API_KEY=...
  LLM_BACKEND=anthropic                                 # default; flip to vllm-local later
  VLLM_BASE_URL=http://127.0.0.1:8001/v1
  VLLM_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
  VLLM_USE_FLASHINFER_MOE_FP4=1                         # silent fallback if missing
  VLLM_FLASHINFER_MOE_BACKEND=throughput
  VLLM_ATTENTION_BACKEND=FLASHINFER
  VLLM_WORKER_MULTIPROC_METHOD=spawn                    # vs fork; CUDA-state safety
  TORCH_CUDA_ARCH_LIST=10.0;10.3                        # B300 sm_103a
  PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512

vLLM install (uses the existing .venv-nightly with sm_103a-aware Triton):
  /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/pip install \
    --no-deps vllm==0.20.* flashinfer-python
  pip install httpx pydantic uvicorn fastapi   # vLLM runtime deps
  # OR: install vllm[full] in a NEW venv if .venv-nightly conflicts

Custom reasoning parser plugin (Nemotron-specific):
  curl -L https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py \
    -o /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py
```

**Acceptance**: `vllm --version` returns 0.20.x. `python -c 'import flashinfer'` succeeds. `nano_v3_reasoning_parser.py` exists at the expected path.

### Phase D — `vllm serve` Nemotron + smoke test | 30 min first boot, 5 min subsequent

Full one-liner (per KB 23, with Phase-C env vars already exported):

```bash
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
  --enforce-eager \
  --port 8001 \
  --host 127.0.0.1
```

Three flags worth flagging:

- `--gpu-memory-utilization 0.20` — DEFAULT 0.90 would over-commit alongside Parakeet + Fish. 0.20 = 55 GB ceiling, covers 19.4 GB NVFP4 weights + FP8 KV cache + CUDA-graph buffers.
- `--enforce-eager` — skip CUDA-graph capture on first boot to dodge the Triton PTXAS sm_103a regression. Drop this flag once we know nightly torch + Triton 3.7 lets graphs capture cleanly. Latency cost: ~10-20 % slower decode but no engine-init crash.
- `--tensor-parallel-size 1` — TP > 1 + NVFP4 is broken on B300 per NIM 2.0.1 release notes. Model fits anyway.

First-boot weight download: ~20 GB (NVFP4 checkpoint), 3-8 min on a typical Brev pod.

**Smoke test**:
```bash
curl -sS http://127.0.0.1:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron-nano","messages":[{"role":"user","content":"911 what is your emergency"}],"max_tokens":24,"stream":false}' | jq .
# expect: choices[0].message.content with a coherent dispatcher reply
```

Then a streaming smoke + TTFT measurement:
```bash
time curl -sN http://127.0.0.1:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron-nano","messages":[{"role":"user","content":"911 what is your emergency"}],"max_tokens":24,"stream":true}' | \
  awk 'NR==1 { print "first byte:", systime(); }'
# expect TTFT 30-80ms on B300 (warm)
```

**Acceptance**: 200 OK, streaming TTFT < 100 ms warm, GPU memory rises to ~50 GB while serving.

### Phase E — Flip `LLM_BACKEND=vllm-local` on the worker + bench | 15 min

```
ssh prism-mla-b300-h4h5 "echo 'LLM_BACKEND=vllm-local' | sudo tee -a \
  /opt/prism42/agents/livekit/.env && \
  sudo systemctl restart prism42-worker"
# bench:
scripts/ralph_loop.sh --iter 6 --bench-n 3
# A/B vs Anthropic baseline:
grep llm_ms /tmp/prism42-logs/worker.log | tail -20
```

Compare `llm_ms` distribution: anthropic baseline ~500 ms, vllm-local target ~30-80 ms.

**Acceptance**: median `llm_ms` < 100 ms on 18 samples. End-to-end `t_reply_e2e_ms` drops to <2 s (with Phase A's STT win + Phase D's LLM win). No new errors in worker.log.

### Phase F (later, after the demo) — Nemotron Speech ASR + Fish torch.compile

- **STT**: Bump infra/b300/services/parakeet/Dockerfile from NeMo 25.09 → 25.11. Set `MODEL_NAME=nvidia/nemotron-speech-streaming-en-0.6b` in server.py. Preserve the `/ws` endpoint contract. Expected drop: ~200 ms → ~24 ms streaming-final median (per NVIDIA's published number).
- **TTS**: Resume the PyTorch-nightly experiment branch. Install fish-speech runtime deps in `.venv-nightly`. Launch a second Fish on port 9201 with `--compile`. Bench RTF 1.96 → ~0.7. Migrate prism42-fish.service to use `.venv-nightly` once verified.

These are post-hackathon. Acceptance: `t_stt_ms` p50 < 50 ms; `t_fish_total_ms` < `audio_duration_ms`.

## Consolidated bottleneck inventory

(From all 4 agent briefings; cite this section when running the migration.)

| # | Bottleneck | Symptom | Fix |
|---|---|---|---|
| 1 | Triton PTXAS sm_103a regression in stable PyTorch | `Internal Triton PTX codegen error` on first inference | Use `.venv-nightly` (torch 2.13.dev + Triton 3.7) OR `--enforce-eager` |
| 2 | Missing `VLLM_USE_FLASHINFER_MOE_FP4=1` | NVFP4 throughput silently halves; no warning | Set the env var BEFORE `vllm serve` |
| 3 | Default `--gpu-memory-utilization 0.90` | OOM kills Parakeet or Fish | Set to `0.20` (55 GB ceiling) |
| 4 | Default `_strict_tool_schema=True` in livekit-plugins-openai | vLLM `qwen3_coder` parser silently mishandles tools | Pass `_strict_tool_schema=False` on `OpenAILLM(...)` |
| 5 | `--tensor-parallel-size > 1` + NVFP4 on B300 | Engine init RuntimeError per NIM 2.0.1 release notes | TP=1 only (model fits anyway) |
| 6 | Missing `nano_v3_reasoning_parser.py` | vLLM startup fails to load reasoning parser plugin | Pre-download from HF model card |
| 7 | Missing `HF_TOKEN` | Weight download 401s | Provision via HF settings; cache at `~/.cache/huggingface/token` |
| 8 | Missing `NGC_API_KEY` | NeMo + Riva container pulls fail | Free Developer Program tier suffices |
| 9 | Port 8000 default vs co-resident services | None today; documented for future | Use 8001 for clean separation |
| 10 | `livekit-plugins-nvidia` doesn't emit PREFLIGHT | Lose lever #12 (preemptive LLM on stable partial) | Stay on raw NeMo + custom server.py with /ws (Phase A); skip Riva NIM |
| 11 | `--kv-cache-dtype` not specified | Model card mandates `fp8` for NVFP4 | Set `--kv-cache-dtype fp8` |
| 12 | `VLLM_WORKER_MULTIPROC_METHOD` default `fork` | CUDA state corruption with co-resident processes | Set to `spawn` |

## Acceptance criteria (across all phases)

- Mainline LiveKit voice path stays functional throughout. Each phase is env-flag-gated with one-command rollback.
- `t_reply_e2e_ms` p50 drops monotonically: ~5-7 s (current) → ~2-3 s (after Phase A) → <1 s (after Phase E).
- GPU utilization rises from 0% idle / 3% peak (current) to 60-90% during a session (after Phase E).
- No regression on existing demo URLs: `https://prism42-console.vercel.app/prism42/livekit` continues to serve.

## What "B300 purr" actually means after this plan

```
caller speaks
  → Parakeet streaming /ws (partial → preflight → final)             ~30 ms
    → Nemotron Nano 3 MoE on local vLLM (B300 NVFP4)                  ~30 ms TTFT
      → Fish + torch.compile (RTF 0.7 once Phase F lands)             ~80 ms first-byte
        → audio out to caller                                         total: <200ms first-audio

GPU util during synth: 60-90%
GPU mem during synth: ~70 GB (Parakeet 9 + Fish 8 + vLLM 55)
Network round-trips off-card: ZERO
```

That's the picture worth shipping toward.
