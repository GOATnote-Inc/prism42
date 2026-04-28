# prism42-nemotron-med

**Sovereign NVIDIA medical-LLM stack on Brev Hopper GPUs. Private. Air-gapped from the prism42 production surface.**

A demonstration that GOATnote can serve, judge, evaluate, and (round 3) fine-tune a frontier NVIDIA-stack medical LLM end-to-end on its own GPUs — with zero cloud LLM API keys in any code path.

## What's running

| Layer | Component | Status |
|---|---|---|
| Inference | vLLM 0.x serving NVIDIA Nemotron on H200 (TRT-LLM is the post-hackathon polish path; vLLM is the judging-tonight path) | **R1 live** |
| Base model | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` — NVIDIA's latest Nemotron-3 MoE family (3B active params, BF16 on Hopper; sister to the Blackwell-only NVFP4 variant on the B300 prod pod) | **R1 live** |
| Judge | Same Nemotron-3-Nano endpoint (same-family bias documented in CARD as a limitation; Reward-model judge on H100 is the R2 sovereign-judge polish) | **R1 live** |
| RAG | NV-Embed-v2 + nx-cugraph over OpenEM-expanded medical KG | R2 scaffold |
| Guardrails | NeMo Guardrails 0.21+ Colang 2.0 + Llama-Guard-3-8B, all local | R2 scaffold |
| Specialization | NeMo Framework PEFT LoRA → `Nemotron-3-Nano-30B-Med` | R3 (post-judging) |

## What ships in this commit

- `scripts/sovereign_bench.py` — drop-in sovereign replacement for the Opus-4.7 path. Posts to OpenAI-compatible local endpoints; 401 / 403 / 404 halt loudly per the judge-401-silent-zero rule.
- `mla/judges/triton.py` — sovereign chat-rubric judge with localhost-only enforcement, JSON-parse retry, audit log.
- `mla/judges/reward.py` — sovereign Reward-model judge via FastAPI shim (R1 spare, R2 primary).
- `scripts/serve_trtllm_h200.sh` + `scripts/serve_judge_h100.sh` — NIM-first deploy scripts for the post-hackathon polish path.
- `scripts/preflight.sh` — six refuses-to-proceed gates: HF token, serve, judge, GPU, no prod-URL leak, public prism42 freeze intact.
- `scripts/run_demo.sh` — orchestrator: preflight → 1-example smoke → READ-the-JSON gate → N-trial paired sweep.
- `corpus/clinical_subset.yaml` — 30-example stratified HealthBench Hard pin (seed=42), the same subset the public prism42 Opus 4.7 baseline (`0.196 ± 0.068`, N=3) was scored on.

## Quickstart (replication on the existing pods)

```bash
# 1. open the laptop-side ssh tunnel to the running H200 vllm-nemotron
ssh -fN -L 8000:127.0.0.1:8000 warm-lavender-narwhal
curl -s http://127.0.0.1:8000/v1/models | jq -r .data[0].id
# → nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16

# 2. clone the simple-evals upstream pin (one-time)
git clone --depth 1 https://github.com/openai/simple-evals.git third_party/simple-evals
git -C third_party/simple-evals fetch --depth 1 origin ee3b0318d8d1d9d72755a4120879be65f7c07e9e
git -C third_party/simple-evals checkout ee3b0318d8d1d9d72755a4120879be65f7c07e9e

# 3. run the sovereign sweep (N=2 trials × 30 examples ≈ 100 min)
.venv/bin/python scripts/sovereign_bench.py \
  --manifest corpus/clinical_subset.yaml \
  --serve-url http://127.0.0.1:8000/v1 \
  --serve-model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --judge-url  http://127.0.0.1:8000/v1 \
  --judge-model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --n 30 --trials 2 --max-tokens 768 \
  --out results/r1-pilot/healthbench-hard-n30.json
```

A score card lands at `results/r1-pilot-<date>/CARD.md` with paired-design CI vs the published Opus 4.7 baseline.

## Hardware

- `prism-mla-h100` — Hyperstack H100 80 GiB, montreal-canada-2, ID `x3rytha2l`. Idle tonight; reserved for R2 sovereign judge / R3 PEFT LoRA.
- `warm-lavender-narwhal` — Nebius H200 141 GiB, eu-north1, ID `pdlpt96nl`. Hot — the running vllm-nemotron container is what every benchmark in this repo speaks to.

Both Hopper (compute_cap 9.0). NVFP4 is Blackwell-only (B300 prod pod) and is **not** used here. BF16 is the format on H200; fp8 is the planned R1.5 polish for higher throughput.

The voice-freeze H100 in the public-repo `findings/voice/freeze-cert*.md` is **distinct hardware** — same SKU, different pod, different region, different role. This repo never ssh's into it.

## Sovereignty by construction

`grep -rE "(OPENAI_API_KEY|ANTHROPIC_API_KEY)" --include="*.py" mla/judges/ scripts/sovereign_bench.py` returns zero matches. The pre-commit hook blocks any future addition outside the legacy paths flagged for refactor (see `.pre-commit-config.yaml`).

A runtime check confirms the import path doesn't transitively pull either SDK:

```python
import sovereign_bench
assert "anthropic" not in sys.modules and "openai" not in sys.modules
```

## Isolation contract

See [`CLAUDE.md`](./CLAUDE.md) §1 — the eight non-negotiable do-not-touch zones absorbed from the audit of the public surface. Every commit is hash-checked against the public repo's HEAD + worktree-diff to verify the freeze still holds. `make freeze-baseline` captures the baseline; `make freeze-verify` diffs.

Provenance: derived from `github.com/GOATnote-Inc/prism42` HEAD `e02e62dd` on 2026-04-28 via squash-import (no git history). Only the medical-LLM eval harness was lifted; voice / LiveKit / Vercel / ElevenLabs / B300 surfaces stayed in the public repo per its own freeze posture.

## What this is NOT

- Not a fork of public prism42 (no shared history, no shared deployment surface).
- Not running on the production B300 pod.
- Not pinning to the prod `Nemotron-3-Nano-30B-A3B-NVFP4` weights (NVFP4 is Blackwell-only; BF16 is the Hopper sister).
- Not using any cloud LLM API key. The only credentials in this repo's `.env.example` are HF read-only token + NGC registry token.
