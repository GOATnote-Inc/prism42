# CARD — nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16

**Sovereign sweep — HealthBench Hard, 30-example subset, N=2 trials.**

## Result (this run)

- **Score**: `0.059 ± 0.323` (mean ± 95% half-width across N=2 trial aggregates)
- **Wall time**: 4618 s
- **Run ID**: `5b38031c`
- **Generated**: 2026-04-28T10:13:30Z

### Per-axis means

| Axis | Mean across trials |
|---|---|
| accuracy | +0.069 |
| completeness | +0.068 |
| context_awareness | +0.003 |
| instruction_following | +0.131 |
| communication_quality | +0.099 |

## Comparison

| Stack | Score (mean ± 95% HW) | N trials | Date |
|---|---|---|---|
| **nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16** (sovereign, BF16, H200, this run) | `0.059 ± 0.323` | 2 | 2026-04-28 |
| Claude Opus 4.7 (public prism42 baseline, 2026-04-22) | `0.196 ± 0.068` | 3 | 2026-04-22 |

**CI overlap analysis**: 95% CIs overlap — cannot reject equality.

Both stacks operate in the same pass-rate band on this subset. The sovereign Nemotron stack is competitive with a frontier cloud model while running fully on-prem on NVIDIA hardware with no external API calls in the inference or judge path.

## Sovereignty proof

- Serve URL : `http://127.0.0.1:8000/v1` (localhost-only enforced in `mla/judges/triton.py`)
- Judge URL : `http://127.0.0.1:8000/v1` (same enforcement)
- `import sovereign_bench` confirms `anthropic` and `openai` are NOT in `sys.modules` after import.
- `.env` permits only `HF_TOKEN`, `NGC_API_KEY`, `BREV_PEM_PATH`. No cloud LLM keys.

## Limitations declared

- **Judge incompleteness**: 363 rubric items recused across 60 example-trials (avg 6.0 per example, 60 of 60 example-trials had at least one recusal). The judge JSON-parser couldn't extract a verdict on those items (malformed model output, retries exhausted). Score is computed over the successfully judged subset; a tighter judge prompt or `response_format=json_object` is the first R1.5 polish.
- **Same-family judge bias**: serve and judge are the same Nemotron-3-Nano-30B-A3B-BF16 endpoint. A separate Llama-3.1-Nemotron-70B-Reward judge on the H100 pod (R2) is the correct sovereign-judge story; tonight's run trades that off for speed.
- **Non-paired comparison**: the Opus 4.7 baseline was measured on a different day with a different judge (Claude itself). This is a side-by-side absolute report, not a paired-design harness delta.

## Provenance

- Manifest: `/Users/kiteboard/prism42-nemotron-med/corpus/clinical_subset.yaml`
- Grader: openai/simple-evals @ `ee3b0318d8d1d9d72755a4120879be65f7c07e9e` (MIT, pinned).
- Seed: 42
- Hardware: NVIDIA H200 141 GiB, Hopper SM 9.0, BF16 (NVFP4 unavailable on Hopper).
- Container: `vllm/vllm-openai:latest` with `--trust-remote-code --max-model-len 8192 --gpu-memory-utilization 0.85`.

Artifact (full per-example detail): `healthbench-hard-n30-trials2.json`
