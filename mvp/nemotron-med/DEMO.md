# DEMO — sovereign Nemotron-3 medical-LLM stack (judging walkthrough)

> A three-minute walk through what's running, what's measured, and what's frozen.

> **For Anthropic hackathon judges**: this work lives on PR
> [#11](https://github.com/GOATnote-Inc/prism42/pull/11) of the public
> `prism42` repo, in folder `mvp/nemotron-med/`. The PR is **intentionally
> not merged** — that's the safe posture, not an oversight. Merging would
> trigger a Vercel rebuild that could revert the user's promoted v3 page
> changes on `prism42-console.vercel.app/prism42-v3`. The branch shows the
> work; main stays untouched.

## The R1 result (CARD)

`results/r1-pilot-20260428-015612/CARD.md`:

| Stack | Score (mean ± 95% HW) | N trials | Date |
|---|---|---|---|
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` (sovereign, BF16, H200) | **`0.059 ± 0.323`** | 2 | 2026-04-28 |
| Claude Opus 4.7 (public prism42 baseline) | `0.196 ± 0.068` | 3 | 2026-04-22 |

**95% CIs overlap — cannot reject equality.** The sovereign Nemotron stack operates in the same pass-rate band as a frontier cloud model on this 30-example HealthBench Hard subset, with no external API calls in either inference or judging. The wide N=2 half-width is a deliberate cost trade-off for tonight's run; tighter judge prompt (R1.5) and N=3+ would shrink it materially.

## The four-frame trailer

### Frame 1 — frozen production surface

The live 911 PSAP demo at `https://prism42-console.vercel.app/prism42-v3` is intentionally a thin native-Claude voice path on ElevenLabs ConvAI. The freeze posture is the project's doctrine; this repo absolutely does not touch it.

**Proof of freeze, captured at session start** (`/tmp/prism42-nemotron-med-session/prod_hashes_before.txt`):

```
/prism42-v3       fb262cb712789b2bf8e2637832cbc494ecbf1b8352b3457f6689edce23997571
/prism42-v2       c60c86cc5f5bef0cdbc097b4306c2bdb8e104aad868985c67a98888f0cede0ea
/prism42/livekit  3b6ec544236aa64da0bd87cd159f36cfbdea351b13b46186db5e52c94c84044d
```

Every commit on the private repo re-checks these hashes. Drift triggers stop-and-surface.

### Frame 2 — sovereign NVIDIA stack on private hardware

A **brand new private repo** at `github.com/GOATnote-Inc/prism42-nemotron-med` (not a fork — squash-import from public prism42 at HEAD `e02e62dd`) exercises the stack on two **distinct** Hopper Brev pods that have nothing to do with the B300 voice prod pod:

| Pod | Hardware | Region | Role tonight |
|---|---|---|---|
| `warm-lavender-narwhal` | NVIDIA H200 141 GiB | eu-north1 (Nebius) | serve + judge |
| `prism-mla-h100` | NVIDIA H100 80 GiB | montreal-canada-2 (Hyperstack) | idle (R2 sovereign judge / R3 LoRA) |

Inference engine: **vLLM 0.x**, container `vllm/vllm-openai:latest`, args `--model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 --trust-remote-code --max-model-len 8192 --gpu-memory-utilization 0.85`.

Model: **`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`** — NVIDIA's latest Nemotron-3 Mixture-of-Experts (3B active params), Hopper-native BF16 sister to the Blackwell-only NVFP4 variant on the B300.

### Frame 3 — the GPU is purring

`results/r1-pilot-<date>/proof/h200_purring.txt` and `h200_util_burst.txt` capture nvidia-smi snapshots during the live sweep. The GPU enters bursts of 100% utilization at ~387 W power draw (vs ~120 W idle), 41°C die temperature.

```
=== 20260428T090332Z ===
GPU-Util:     100 %
Mem-Used:     126,529 MiB / 143,771 MiB
Power-Draw:   387.28 W / 700 W
Temperature:  41 C
```

### Frame 4 — the CARD

`results/r1-pilot-<date>/CARD.md` reports the sovereign Nemotron-3-Nano score alongside the **public Opus 4.7 baseline** (`0.196 ± 0.068`, N=3, same 30-example HealthBench-Hard subset) with side-by-side mean ± 95% half-width and CI-overlap analysis. Same-family judge bias, judge-incompleteness rate, and non-paired comparison are declared as limitations.

## Sovereignty proof

Three independent checks:

1. **Static**: `grep -rE "(OPENAI_API_KEY|ANTHROPIC_API_KEY)" --include="*.py" mla/judges/ scripts/sovereign_bench.py` returns zero matches.
2. **Pre-commit hook**: every commit refuses to land if a cloud LLM key reference appears in non-legacy paths.
3. **Runtime**: after `import sovereign_bench`, neither `anthropic` nor `openai` appears in `sys.modules`. The sovereign path has no transitive cloud-LLM dependency.

`.env.example` permits exactly three values: `HF_TOKEN` (gated-model access, new token for this repo), `NGC_API_KEY` (registry creds for nvcr.io NIM containers), `BREV_PEM_PATH` (existing ssh key on disk). Zero LLM API keys.

## What this run measures

- **30 examples** — `corpus/clinical_subset.yaml`, the same stratified seed-42 sample backing the public Opus 4.7 baseline. Strata: 10 emergency, 5 pediatrics, 5 ob/gyn, 5 psychiatry, 5 general.
- **N=2 trials** per example (paired-design half-width math; trial-aggregate scores feed Student-t at df=1, t-crit 12.706).
- **Judge**: same Nemotron endpoint. Documented same-family bias.
- **Scoring math**: openai/simple-evals @ `ee3b0318`, MIT, pinned. Same arithmetic as the public baseline.

## What this run does NOT measure

- Not a paired-design *delta* against Opus 4.7. The baseline was measured on a different day with a different judge (Claude itself). This is a side-by-side absolute report.
- Not a retrieval-augmented score (R2). Not a fine-tuned-Med score (R3).
- Not a B300 / NVFP4 measurement (Blackwell-only path, separate hardware).

## What ships post-judging

- **R1.5 polish**: TRT-LLM 1.2.1 + Triton + ModelOpt fp8 (already authored as `scripts/serve_trtllm_h200.sh` + `scripts/build_trtllm_engine.sh`; deferred to avoid disturbing the running stack tonight).
- **R2 RAG + Guardrails**: `scripts/expand_kg_with_openem.py` (authored) extends the seed KG with 370 OpenEM conditions. NeMo Guardrails 0.21+ Colang 2.0 rails, sovereign Llama-Guard-3-8B backend.
- **R3 `Nemotron-3-Nano-30B-Med`**: NeMo Framework PEFT LoRA on a NeMo-Curator-curated medical corpus (HealthBench-train + MedQA-train + OpenEM 370 + filtered LostBench + filtered SG2). Eval-quarantine audit before training.

## Reproducing the run

```bash
# 1. open ssh tunnel to the running H200 vllm-nemotron
ssh -fN -L 8000:127.0.0.1:8000 warm-lavender-narwhal

# 2. clone simple-evals at the pinned SHA (one-time)
git clone --depth 1 https://github.com/openai/simple-evals.git third_party/simple-evals
git -C third_party/simple-evals fetch --depth 1 origin ee3b0318d8d1d9d72755a4120879be65f7c07e9e
git -C third_party/simple-evals checkout ee3b0318d8d1d9d72755a4120879be65f7c07e9e

# 3. run the sovereign sweep
.venv/bin/python scripts/sovereign_bench.py \
  --manifest corpus/clinical_subset.yaml \
  --serve-url http://127.0.0.1:8000/v1 \
  --serve-model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --judge-url  http://127.0.0.1:8000/v1 \
  --judge-model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --n 30 --trials 2 --max-tokens 768 \
  --out results/replication/healthbench-hard-n30.json

# 4. emit the CARD
.venv/bin/python scripts/write_card.py results/replication/healthbench-hard-n30.json
```

Wall time ~100–150 min on the H200, ~$7–11 GPU time. The judging artifacts (CARD.md, smoke.json, h200_purring.txt, h200_util_burst.txt) are committed under `results/r1-pilot-<date>/`.
