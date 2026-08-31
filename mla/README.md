# prism-mla
Evolutionary MLA/NVFP4 kernel search with two-tier numerical validator.

## Quickstart
```bash
python3.13 -m venv .venv
.venv/bin/pip install -e .[test]
.venv/bin/pytest -q
```

## Evaluation rubric
**`docs/EVALUATION_RUBRIC.md` v1.0** — every performance claim in a commit
message, paper, deck, or demo must cite a session ID that passed this
protocol. No exceptions. Drafted after an earlier "1.31x FlashInfer" number
was traced to same-process autotune contamination (real clean-process number
is 3.68x at that config). Short version: one fresh subprocess per run,
200 CUDA-event samples, 3 replicates, stdev/mean ≤ 5%, full distribution
(p10/p50/p90/p99), compile cost reported alongside steady-state, reproducibility
pinned by commit SHA + GPU UUID + clocks. Implementation in
`scripts/isolated_bench.py` + `scripts/_bench_worker.py`.

## Current state (2026-04-22)
- **Validator** (`prism/`): two-tier, 35 tests.
- **Kernels** (`kernels/base/mla_decode_numpy.py`): `mla_decode_naive` (golden) + `mla_decode_absorbed` (first mutation).
- **Runner** (`runner/numpy_runner.py`): perf_counter benchmark. FlashInfer runner is a stub until GPU.
- **Agent** (`agent/`): StubClient (offline, deterministic) + AnthropicClient (Opus 4.7, opt-in). Safety gate rejects imports, eval/exec, subprocess, etc.
- **Critique** (`agent/critique.py`): structured four-field verdict (numerical_risk, efficiency_risk, novelty, recommendation ∈ {accept, revise, reject}). Gate, not a score term.
- **Pareto** (`loop/pareto.py`): three-axis dominance on (tokens/sec, stability, -max_abs_error). Retains trade-off kernels the linear score would drop.
- **Loop** (`loop/evolve.py`): three-island evolutionary loop with per-iteration validation, benchmarking, scoring, migration, optional critique gate, optional Pareto keep.
- **FlashInfer runner** (`runner/flashinfer_runner.py`): real MLA decode via `flashinfer.mla.BatchMLAPagedAttentionWrapper`; torch-float32 reference; CUDA-event benchmark; DeepSeek dims (128 heads × 512 kv_lora + 64 rope).
- **H100 verify** (`scripts/verify_h100.sh`): single-command parseable report. See `docs/H100_RUNBOOK.md`.
- **Tests:** 84 pass + 6 CUDA-gated (skipped on CPU) in <0.3s.
- **Demos:**
  - `python loop/manual_mutation.py` — baseline vs first mutation (naive→absorbed), 17× median.
  - `python loop/evolve_demo.py` — 3-island evolve with critique + Pareto by default (toggle via `PRISM_CRITIQUE=0` / `PRISM_PARETO=0`).

## Why two tiers
Per `mental-models/munger-inversion.md` §1-3 in the archive: a single 1e-2 max-error threshold on a single input is the most common failure mode for kernel-evolution loops. The two-tier design is the direct counter. See `prism-mla-archive/papers/notes-*.md` for the prior-art analysis.

## Layout
```
prism-mla/
├── prism/                    numerical validator + invariants + gaming checks
│   ├── validator.py          validate(candidate, reference, inputs, ...)
│   ├── invariants.py         physics checks (softmax-sum, row-norm bound, top-k)
│   ├── adversarial.py        input battery for Tier-2 hostile probes
│   └── gaming_patterns.py    six Robust-KBench detectors
├── tests/
│   ├── test_validator.py
│   └── test_gaming_patterns.py
├── kernels/                  base/, candidates/, best/ (empty; next step)
├── runner/                   FlashInfer runner (empty; next step)
├── agent/                    mutation + critique prompts (empty; next step)
├── loop/                     evolution loop (empty; next step)
└── results/                  logs
```

## Anchor references
- Archive root: `~/prism-mla-archive/`
- Scaffold spec: `prism-mla-archive/scaffold/prism-mla-scaffold.md`
- State of the art: `prism-mla-archive/STATE-OF-THE-ART.md`
- Physics ceiling: `prism-mla-archive/mental-models/einstein-first-principles.md`

## Switching stub → real Claude
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export PRISM_USE_ANTHROPIC=1
.venv/bin/python loop/evolve_demo.py
```
Model pinned to `claude-opus-4-7`. StubClient otherwise.

## What's intentionally not here yet
- Real FlashInfer / CUDA runner (arrives when the loop moves to H100/B200).
- CuTe DSL mutation targets (CUTLASS C++ BSD-3 is the mutation layer; the Python CuTeDSL is under NVIDIA EULA — see `prism-mla-archive/mental-models/red-team-adversarial.md` §1).
- Multi-vendor dispatch (Pallas TPU + NKI Trainium ports — the archive's open white-space; `cross-pollination/tcu-gpu-tpu-trainium-playbook.md`).
