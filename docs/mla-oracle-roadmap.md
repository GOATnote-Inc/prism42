---
title: Prism — Phase M (MLA Decode Oracle) Roadmap
status: Draft
date: 2026-04-22
scope: Executable decomposition of the Multi-head Latent Attention (MLA) decode-oracle extension. Adds two executor rails (`cute-mla` GPU, `tpu-pallas` TPU) and a correctness oracle that any current or future MLA decode kernel can self-certify against. Target artifact is an arxiv preprint submitted before the MLSys 2026 FlashInfer kernel-contest deadline (2026-04-24), plus three executed bug reproductions against already-public GitHub issues.
hard_constraint: Normative contracts are `CLAUDE.md` (operating charter) and `docs/sota-portfolio.md` §0 (external-scorer discipline). Any conflict — those win.
---

# Prism — Phase M (MLA Decode Oracle)

## 0. Why this phase exists

Prism's kernel rail audits GPU-kernel numerical correctness. Multi-head Latent Attention (MLA) decode kernels on Blackwell (sm_100) are the hot path for 2026-era inference of DeepSeek V2/V3/V3.2/R1, Kimi K2/K2.6, and Ant Ling-2.5. Three public GitHub issues (SGLang #10284, vLLM #38439, FlashInfer #3047) report correctness failures on B200 under FP4/NVFP4 quantization — "fast but wrong" is the current SOTA failure mode. DeepSeek's own FlashMLA README self-describes B200 sparse MLA decode as "not really optimized yet" at 350 TFLOPS (vs the ~1,600 TFLOPS production-attention ceiling on the same silicon).

Phase M extends Prism's PoC-validator discipline to this target: every MLA kernel (reference, production, future) can be checked against the same executable oracle, on GPU (B200) and TPU (Trillium) rails, with ULP + logit-KL + task-delta tolerances declared upfront.

## 1. Dependency DAG

```
Phase M (MLA Decode Oracle)                              Phase D (submission)
┌─────────────────────────────────────────────────┐      ┌──────────────────┐
│ M0 roadmap doc (this file) ──┐                  │      │  D3 SUBMISSION    │
│ M1 schema patch: rails ──────┤                  │      │     (references   │
│ M2 reference impls (fp32 ──┐ │                  │      │      arxiv ID)    │
│    PyTorch, bf16 JAX)      │ │                  │      └──────────────────┘
│ M3 oracle harness ─────────┼─┤                  │               ▲
│ M4 runner + executor ──────┤ │                  │               │
│    (GCP TPU exec)          │ │                  │               │
│ M5 corpus + cases + ───────┘ │                  │               │
│    repros (3 public bugs)    │                  │               │
│ M6 B200 executed run ──────┐ │                  │               │
│ M7 Trillium executed run ──┼─┴─▶ oracle verdicts ──▶ M8 arxiv ──┘
│                            │     + cross-rail                paper
│                            │     concordance table
└─────────────────────────────────────────────────┘
```

M0–M5 are offline (no GPU / TPU spend). M6 / M7 are the live execution gates. M8 bundles the arxiv submission.

## 2. Agent-type legend (reuse `docs/clinical-roadmap.md` §2)

`GP-WT` = general-purpose in worktree · `GP` = general-purpose in main tree · `EXPL` = Explore · `HUMAN` = Brandon sign-off.

## 3. Tasks

### M0 — This roadmap doc
- **Agent**: `GP`
- **Blocks**: M1–M8 (so commits can cite M-task-IDs)
- **Blocked by**: — (safe now)
- **Outputs**: `docs/mla-oracle-roadmap.md`
- **Verification**: `make verify-all` green; no schema touched.
- **Size**: 30 min.

### M1 — Schema patch: add rails + target_domain
- **Agent**: `GP-WT`
- **Blocks**: M2, M3, M5
- **Blocked by**: M0
- **Inputs**: `schemas/case.schema.json` (NOT frozen). The existing `allOf` conditional is backward-compatible: new rails fall in the `else` branch and require `target_domain`.
- **Outputs**: `rail` enum gains `"cute-mla"` and `"tpu-pallas"`; `target_domain` enum gains `"tpu"`. No `class`-enum changes (FP4 correctness issues fit the existing `"precision"` class per the failure-taxonomy in `docs/dual-target-thesis.md` §2).
- **Verification**: (a) `python -c "import json, jsonschema; jsonschema.Draft202012Validator.check_schema(json.load(open('schemas/case.schema.json')))"` exits 0; (b) existing 272 tests still pass; (c) negative control: a synthetic cuda-rail case still validates.
- **Size**: 45 min.

### M2 — Reference MLA decode implementation (numpy FP32)
- **Agent**: `GP-WT`
- **Blocks**: M3, M6, M7
- **Blocked by**: M1
- **Inputs**: DeepSeek-V2-Lite MLA shape (d_c=512 latent, d_h^R=64 decoupled RoPE, 16 heads × 128 per-head-dim). DeepSeek-V2 paper arXiv:2405.04434 §2.1.3 (absorption).
- **Outputs**: `corpus/mla/reference/mla_decode_numpy.py` (numpy FP32, both non-absorbed and absorbed decode forms, forms cross-checked to agree within 1e-4 relative); `corpus/mla/reference/generate_golden_vectors.py` (deterministic golden-JSON generator); `corpus/mla/reference/golden_vectors/{small,v2_lite}_decode_s16_w42.json` (committed FP32 golden outputs with seeds + sha256 integrity hash). Torch / JAX framework reference impls are **deferred to M6 (B200) and M7 (Trillium) respectively**, installed on rental hardware only — keeps the Prism venv lean and the oracle executable offline.
- **Note on RoPE**: the reference omits RoPE rotation for auditability; candidate kernels must apply RoPE consistently (both-sides-applied or both-sides-skipped) for direct comparison. The tolerance contract in M3 accounts for this.
- **Verification**: `python corpus/mla/reference/mla_decode_numpy.py` exits 0 (self-test asserts absorbed ≡ non-absorbed, prints sha256); `pytest tests/test_mla_reference.py -q` passes 6 tests (both-forms-agree × {small, v2_lite}; golden-reproduces-exactly × {small, v2_lite}; golden-schema × {small, v2_lite}).
- **Size**: 3 hours.

### M3 — Oracle harness
- **Agent**: `GP-WT`
- **Blocks**: M4, M6, M7
- **Blocked by**: M2
- **Inputs**: `corpus/mla/reference/*` from M2.
- **Outputs**: `corpus/mla/oracle/harness.py` (ULP bound + logit-KL + 200-example GSM8K-Lite task-accuracy delta); `corpus/mla/oracle/tolerances.py` (declared per-dtype bounds). API: `verdict = oracle.check(reference_output, candidate_output, tolerances) → {pass, reasons[], ulp_max, kl, task_delta}`.
- **Verification**: `pytest tests/test_mla_oracle.py -q` — deliberately-corrupted output must FAIL oracle; untouched reference must PASS; golden fixture committed.
- **Size**: 3 hours.

### M4 — Runner + GCP TPU executor branch
- **Agent**: `GP-WT`
- **Blocks**: M7
- **Blocked by**: M3
- **Inputs**: Existing double-gate pattern from `scripts/harness_runner.py`. Existing `scripts/ssh_exec.sh` pattern (RunPod / Lambda SSH). GCP `prism421` project, Trillium (v6e) quota already green per session 2026-04-22.
- **Outputs**: `scripts/mla_oracle_runner.py` (double-gated: `--commit` + `PRISM_MLA_ORACLE_COMMIT=1`); `scripts/gcp_tpu_exec.sh` (provider-agnostic exec contract — mirrors `ssh_exec.sh` signature); `environments/prism-standard-env.yaml` egress allowlist gains `compute.googleapis.com`, `tpu.googleapis.com`, `storage.googleapis.com`, `oauth2.googleapis.com`; `scripts/check_sdk_containment.py` TARGETS extended to include the new runner.
- **Verification**: (a) `python scripts/check_sdk_containment.py` passes; (b) dry-run `python scripts/mla_oracle_runner.py` does not import Google Cloud SDK; (c) `make verify-t3` passes including the new env invariant.
- **Size**: 2.5 hours.

### M5 — Corpus + cases + reproducers (3 public bugs)
- **Agent**: `GP-WT`
- **Blocks**: M6, M7
- **Blocked by**: M1, M3
- **Inputs**: `corpus/kernel_bugs.yaml` as structural template (but MLA entries go to a parallel file, never inside `corpus/reproducers/*` which is frozen). Three live public GitHub issues: SGLang #10284 (FP4 + FlashInfer MLA accuracy on B200), vLLM #38439 (NVFP4 + MLA pipeline-mismatch), FlashInfer #3047 (MLA chunked-prefill batch-composition divergence on Blackwell).
- **Outputs**: `corpus/mla/mla_bugs.yaml` (parallel to `corpus/kernel_bugs.yaml`); `cases/MLA-BUG-001.json`, `MLA-BUG-002.json`, `MLA-BUG-003.json` (rail=`cute-mla`, target_domain=`gpu`, class=`precision`); `corpus/mla/reproducers/MLA_BUG_001_sglang_10284.py` etc., each guarding on `REQUIRED_CC=(10, 0)` and deferring cleanly on SM90.
- **Verification**: `python scripts/validate_artifacts.py --case-dir cases/MLA-BUG-001` (and 002, 003) exits 0 for each.
- **Size**: 3 hours.

### M6 — B200 executed run (GPU rail)
- **Agent**: `GP-WT` + live execution
- **Blocks**: M8
- **Blocked by**: M4, M5
- **Inputs**: RunPod B200 Secure (~$5.49/hr per M0-prerequisite README correction); M5 reproducers; M3 oracle.
- **Outputs**: `findings/mla-oracle-session-2026-04-24.md` logging (hardware_id, commit_SHA, timestamp, bug_id, baseline_output_hash, oracle_verdict, reference_output_hash) for each of three bugs. Executed artifacts live under `results/mla-oracle/<run_id>/`.
- **Verification**: All three bugs produce `oracle.verdict = FAIL` on baseline kernel (the live bug), `oracle.verdict = PASS` on our reference. Real exit codes. Hardware ID captured via `nvidia-smi -q`.
- **Size**: 3 hours (incl. capacity wait, if any).
- **Cost cap**: $30 on RunPod B200.

### M7 — Trillium executed run (TPU rail)
- **Agent**: `GP-WT` + live execution
- **Blocks**: M8
- **Blocked by**: M4, M5
- **Inputs**: GCP `prism421` project, v6e-1 (preemptible for iteration, on-demand for final); M2 JAX reference; M3 oracle.
- **Outputs**: Cross-rail concordance table in the same session log. Per-prompt: (FP32 CPU reference, B200 FP8 baseline, B200 NVFP4 baseline, Trillium bf16 reference) — agreement rates.
- **Verification**: Oracle PASS on Trillium bf16 for all three cases. Concordance between B200 reference and Trillium bf16 within declared tolerance.
- **Size**: 3 hours (incl. first-time TPU provisioning).
- **Cost cap**: $20 on GCP (v6e-1 preemptible ~$1.20/hr × 10h + v6e-8 on-demand burst).

### M8 — arxiv paper draft + submission
- **Agent**: `GP-WT` + `HUMAN` (final review)
- **Blocks**: D3 SUBMISSION reference (arxiv ID citable in `docs/SUBMISSION.md`)
- **Blocked by**: M6, M7
- **Inputs**: Executed artifacts from M6/M7. Canonical numbers from M2/M3.
- **Outputs**: `docs/papers/mla-oracle/paper.tex` (8–10 pages main, four tables + two figures); `docs/papers/mla-oracle/refs.bib`; `docs/papers/mla-oracle/figures/` (heatmap + architecture diagram). Arxiv submission tarball under `docs/papers/mla-oracle/arxiv-v1/`.
- **Verification**: (a) `pdflatex` clean build; (b) every quantitative claim traces to an M6/M7 logged artifact; (c) HUMAN read-through before upload.
- **Size**: 4 hours.

## 4. Frozen-path respect

Phase M **never touches**:
- `corpus/reproducers/*` (kernel reproducers are frozen; MLA reproducers go to `corpus/mla/reproducers/*` — parallel, not inside).
- MLA verdict ledger is `corpus/mla/mla_bugs.yaml`; MLA oracle runner is `scripts/mla_oracle_runner.py`, an independent script.
- `docs/clinical-extension-spec.md` (frozen). Phase M additive only.
- `.env`, `.state/` (frozen).

## 5. Disclosure posture

The three target bugs (SGLang #10284, vLLM #38439, FlashInfer #3047) are **already public** GitHub issues filed by other users. Prism's role is **executed verification**, not zero-day disclosure. The arxiv paper cites them by issue number directly.

Novel correctness failures (not covered by any public issue) route off-tree via the research posture described in `docs/kernel-research-posture.md` — private channels maintained by the research lead, never through this repo.

## 6. Budget

| Item | Est cost |
|---|---|
| RunPod B200 Secure (M6, ~6h incl. capacity wait) | $30 |
| GCP Trillium v6e-1 preemptible + v6e-8 burst (M7) | $20 |
| Opus 4.7 tokens for M8 paper drafting | $10 |
| Arxiv submission | $0 |
| **Phase M total** | **~$60** |

Phase M cost is small enough to absorb under the original $280 hackathon cap with ~$140 headroom.

## 7. Arxiv submission gate

- `paper.tex` must build clean with `pdflatex` (no warnings about missing refs).
- Every quantitative claim cites an `M6/M7` logged artifact with `(hardware_id, commit_SHA, timestamp)` triple.
- `docs/papers/mla-oracle/arxiv-v1/reproduction.sh` must replay the entire experiment end-to-end (modulo rental).
- License: MIT (repo default). Code on GitHub, paper on arxiv, both public same day.
- **Priority anchor fallback**: if arxiv moderation delays public appearance past 2026-04-24, the signed git tag + GitHub release at HEAD of the merged `t-mla` branch establishes priority. Arxiv timestamp locks it formally.

## 8. Post-merge

Phase M closes when `t-mla` branch merges to `main` via PR with CI green. `docs/SUBMISSION.md` gains an "arxiv: Phase M (MLA oracle)" row.
