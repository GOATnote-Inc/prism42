# Reproducibility design — every layer pinned, every artifact hashed

**Date**: 2026-04-29.
**Source**: parallel research agent + frontier-lab patterns (Anthropic, OpenAI, HuggingFace, PyTorch, vLLM, NVIDIA).
**Disposition**: 9-layer cake; v0 ships the digest+seed level (~80% of claims defensible); v1 ships full 9-layer (~98% defensible). Cost-vs-coverage trade-off explicit.

## 1. The 9 layers we pin

| Layer | What gets pinned | Where it lives |
|---|---|---|
| 1. Bare metal | GPU driver version, CUDA toolkit, NCCL | pod image declaration |
| 2. Container runtime | Docker version, nvidia-container-toolkit | host setup script |
| 3. GPU stack | CUDA 13.2 + cuDNN 9.21.1 + NCCL 2.21+ + cuVS + RAPIDS + nx-cugraph (exact tags) | Dockerfile / NGC base |
| 4. Inference engine | vLLM container **SHA-256 digest** (not tag), TRT-LLM digest, NIM digest | manifest |
| 5. Model weights | HuggingFace **revision SHA per checkpoint** (Omni NVFP4, NV-Embed-v2, Llama-Guard-3, Llama-Nemotron-Rerank-VL) | manifest |
| 6. Data + graphs | OpenEM commit SHA, PubMed snapshot date, LazyGraph build artifact SHA | manifest |
| 7. Eval framework | test-fixture hash, rubric version SHA, judge-model + version, `simple-evals` SHA `ee3b0318` | manifest |
| 8. Hyperparameters | seed, temperature, top_p, max_tokens, batch_size, sampling-mode YAML | manifest |
| 9. Result artifact | output JSON SHA + CARD.md SHA | results/ + manifest cross-link |

## 2. NVIDIA's blueprint, applied here

- **Digest pinning, never tag**: `nvcr.io/nvidia/cuda@sha256:...` not `nvcr.io/nvidia/cuda:13.2`. ([Craig Andrews on digest pinning](https://candrews.integralblue.com/2023/09/always-use-docker-image-digests/).)
- **CUDA 13.2 driver matrix**: Linux ≥570.26, Windows ≥570.65; cuDNN 9.21.1 requires CUDA ≥12.8.
- **Hopper vs Blackwell**: cubin compute_90a for H100/H200; Blackwell needs native compute_capability 10.0 — PTX-from-Hopper does NOT run on Blackwell.

Source: <https://docs.nvidia.com/cuda/pdf/Blackwell_Compatibility_Guide.pdf>

## 3. Frontier-lab patterns we adopt

- **Anthropic** (per their [Demystifying Evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)): immutable content-addressed dataset registry; manifest cites source pointer + commit SHA + config + schema. **We adopt this for the rubric + fixture cycle.**
- **OpenAI** (per their [Reproducible Outputs cookbook](https://developers.openai.com/cookbook/examples/reproducible_outputs_with_the_seed_parameter)): seed mitigates but doesn't guarantee determinism; cite the seed in every metric. **We adopt seed-citation in every CARD.**
- **HuggingFace**: `set_seed()` for {random, numpy, torch, tf}; for full distributed-training determinism use `enable_full_determinism()` (small perf cost). **We adopt this in the eval-runner harness.**
- **PyTorch**: `torch.backends.cudnn.deterministic=True`, `torch.backends.cudnn.benchmark=False`. cuDNN can nondeterministically select algorithms on new tensor shapes. **Trade-off: slower kernels selected; but deterministic.** **We adopt this for eval, NOT for autoresearch (where speed matters more than reproducibility per-experiment).**
- **Karpathy autoresearch**: immutable evaluator (`prepare.py` is sacred), git-rollback on failed experiments, fixed budget per experiment. **We adopt this for the v0.5 autoresearcher loop.**
- **DSPy GEPA**: `random_seed` parameter controls golden splits + minibatch sampling + Pareto selection. **We adopt this when GEPA lands.**

## 4. The buildable design — five-step recipe + Makefile target + CI gate

### Step 1 — `reproducibility/manifest-template.yaml`
Per-session manifest schema; one file per (date, run-id) tuple under `reproducibility/captured/`.

### Step 2 — `scripts/freeze_snapshot.py`
Captures the current state of every layer into a manifest YAML:
- Polls running pods for driver/CUDA versions, container digests
- Reads HF cache for revision SHAs
- Hashes graph artifacts in `data/lazygraph/`
- Reads rubric SHA, simple-evals SHA
- Writes to `reproducibility/captured/manifest-<date>-<runid>.yaml`

### Step 3 — `scripts/freeze_verify_all.py`
Diffs the current state against a pinned manifest; exits non-zero on any drift.

### Step 4 — `Makefile` target `make reproduce SESSION=<id>`
Reads `reproducibility/captured/manifest-<id>.yaml`, pulls each digest, restores hyperparameters, re-runs the eval against the same fixture, regenerates CARD.

### Step 5 — CI gate (already partially in `Makefile freeze-verify`)
Every commit on the architecture branch runs `freeze_verify_all`. Drift requires explicit `[allow-drift-reason: ...]` in commit message.

## 5. CUDA 13.2 specifics for our hardware

| Hardware | Compute capability | CUDA 13.2 status | NVFP4? |
|---|---|---|---|
| H100 (Hopper) | 9.0 | ✓ — PTX compiled for compute_90a | ✓ Hopper-native (per NVIDIA dev blog) |
| H200 (Hopper) | 9.0 | ✓ | ✓ |
| B200 (Blackwell) | 10.0 | ✓ — needs native cubin | ✓ but V1-engine bug; workaround `--no-async-scheduling` |
| RTX Pro 6000 SE | 12.x | ✓ — but consumer Blackwell; quirks | ⚠ |

For our 3-GPU setup (H100/H200/H100), CUDA 13.2 is universally fine.

## 6. Honest cost-of-reproducibility trade-off

| Level | Cost | Coverage | Use |
|---|---|---|---|
| **v0 — tag-based** | low | ~70 % (tag can shift) | fast prototyping |
| **v0.5 — digest + seed** | moderate | ~90 % | publishable comparative claims |
| **v1 — full 9-layer manifest** | high (rebuild time, CI gates) | 99 % within hardware | regulatory / hospital pilot |
| **v1.5 — autoresearch loop** | very high (multiple seeds per param set) | ~95 % (can't beat noise floor) | long-running auto-improve |

**Realistic v0 target**: digest pin + seed + per-CARD manifest. **v1 target (week 3-4)**: full 9-layer with `make reproduce`.

## 7. The autoresearcher loop reproducibility (from agent)

Agentic loops mutate code/prompts; reproducibility is hard. Pattern from Karpathy autoresearch + DSPy GEPA:

- **Immutable `eval/prepare.py`** (nobody modifies; locked at start of each campaign)
- **Mutable `auto-research/train.py`** (agent modifies; git tracks all changes)
- **Deterministic seed schedule**: `seed = hash(commit_sha) % 2^31` — same seed for same code state
- **Finite budget per experiment**: 5-min cap (Karpathy) OR fixed eval sample (GEPA)
- **Rollback on failure**: `git reset --hard HEAD~1`

We adopt all five for the v0.5 autoresearcher.

## 8. Sources

- NVIDIA NIM / NGC: <https://developer.nvidia.com/nim>
- NVIDIA AI Workbench: <https://docs.nvidia.com/ai-workbench/user-guide/latest/overview/introduction.html>
- CUDA 13.2 + Blackwell compatibility: <https://docs.nvidia.com/cuda/pdf/Blackwell_Compatibility_Guide.pdf>
- Anthropic Engineering — Demystifying Evals: <https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents>
- OpenAI Cookbook — Reproducible Outputs: <https://developers.openai.com/cookbook/examples/reproducible_outputs_with_the_seed_parameter>
- HuggingFace datasets cache: <https://huggingface.co/docs/datasets/cache>
- PyTorch reproducibility: <https://docs.pytorch.org/docs/stable/notes/randomness.html>
- vLLM Docker reproducibility: <https://inference.net/content/vllm-docker-deployment/>
- Karpathy autoresearch: <https://github.com/karpathy/autoresearch>
- DSPy GEPA: <https://dspy.ai/api/optimizers/GEPA/overview/>
- Docker digest pinning: <https://candrews.integralblue.com/2023/09/always-use-docker-image-digests/>
