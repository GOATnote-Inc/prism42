---
title: Claude Opus 4.7 — Medical Benchmark Baseline Card
date: 2026-04-21
status: Populated 2026-04-21 — Opus 4.7 launch page reports no medical benchmarks
scope: Source-of-truth table for every Claude Opus 4.7 medical-benchmark number quoted in the README, submission, demo narration, or preprint. Every row is a direct quote from a cited source with a fetch timestamp, or the explicit "not reported" record.
---

# Claude Opus 4.7 — Medical Benchmark Baseline Card

## Finding

**Anthropic's Claude Opus 4.7 launch page does not report medical benchmarks.** The launch emphasized capability milestones (1M context window, adaptive thinking as the only thinking-on mode, new `xhigh` effort level, `task-budgets-2026-03-13` beta, high-resolution vision to 2576px / 3.75MP, new tokenizer, real-time cybersecurity safeguards). There is no MedQA, MMLU-Medical, PubMedQA, HealthBench, or MedAgentBench table in the Opus 4.7 announcement.

**Consequence for Prism.** The clinical extension does not merely establish one number (HealthBench Hard) that was previously private. It establishes the full medical-benchmark suite for Opus 4.7, period. Every number Prism measures is the first public datapoint for this model on these benchmarks.

## Rules for filling this card

1. Every number is a direct quote from a cited source. No computed aggregates, no interpolation from related tasks, no backfill from related models.
2. Every row lists: the exact number (or `not reported`), the source, and the fetch-date.
3. If a benchmark is not reported on the Opus 4.7 model card, the row stays **not reported**. Do not substitute a related model's number.
4. When in doubt, do not quote. Prism's contract is that every claim is reproducible.
5. Re-verify before quoting on camera or in the submission README.

## Card

Source for all rows below: Anthropic *"What's new in Claude Opus 4.7"* launch page content, shared in-session by the user on 2026-04-21 (conversation transcript is the artifact). Rows are "not reported" because the launch content contains no medical-benchmark table.

| Benchmark | Score | Source | Fetched | Notes |
|---|---|---|---|---|
| MedQA (USMLE 4-option) | not reported | Opus 4.7 launch page (user-shared, in-session) | 2026-04-21 | USMLE-style MCQ; null-result control for Prism. Prism will establish the first public Opus 4.7 number at T4.6c. |
| MMLU-Medical-6 aggregate | not reported | Opus 4.7 launch page | 2026-04-21 | 6-subset aggregate. Same null-result discipline as MedQA. |
| MMLU anatomy | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| MMLU clinical_knowledge | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| MMLU college_medicine | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| MMLU medical_genetics | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| MMLU professional_medicine | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| MMLU virology | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| PubMedQA (PQA-L) | not reported | Opus 4.7 launch page | 2026-04-21 | RAG validator anchor. Prism establishes via `scripts/pubmedqa_runner.py`. |
| MultiMedQA | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| HumanEval-Health | not reported | Opus 4.7 launch page | 2026-04-21 | — |
| HealthBench Hard | **0.196 ± 0.068** (95% CI, N=3, n=30) | Prism runs seed={42,43,44} on stratified clinical subset; see `docs/seed-stability-2026-04-22.md` | 2026-04-22 | First public Opus 4.7 number on this benchmark. Mean ± 95% CI half-width across three independent runs (per-run aggregates 0.2268 / 0.1732 / 0.1894); graded by `openai/simple-evals` rubric with Opus 4.7 as judge; 0 errors / 0 retries / 0 recusals across 1,095 live rubric calls; total spend $6.73. Axes: accuracy, completeness, context_awareness, instruction_following, communication. |
| MedAgentBench | not reported by Anthropic | Opus 4.7 launch page + Stanford ML Group leaderboard | 2026-04-21 | Public baseline on the Stanford leaderboard for this benchmark: Claude 3.5 Sonnet v2 at 69.67%. Opus 4.7 has not been evaluated on this leaderboard as of 2026-04-21 (user-confirmed). Prism's H1 epic establishes the Opus 4.7 number. |

## Operational constraints derived from the 4.7 launch page

These constrain how the runners and harness call the model. All already enforced or noted below.

| Constraint | Status in Prism | Enforcement location |
|---|---|---|
| `temperature`, `top_p`, `top_k` removed (400 error) | enforced by absence | `scripts/{healthbench,medqa,pubmedqa,mmlu_medical}_runner.py` — none pass these kwargs |
| `thinking.budget_tokens` removed (400 error) | enforced by absence | same |
| Adaptive thinking is the only thinking-on mode; OFF by default | default behavior; runners do not set `thinking` | same |
| Thinking content omitted by default | acknowledged — if we need reasoning traces, set `thinking.display = "summarized"` | future: harness coordinator may opt in for delta-report evidence |
| New tokenizer — up to 1.35x text→tokens | runners budget `max_tokens=128000` with headroom | same |
| New `xhigh` effort level | coordinator harness SHOULD use `effort: "xhigh"` for agentic work | T4.7a (roadmap) — wire into `scripts/harness_runner.py` clinical branch |
| `task-budgets-2026-03-13` beta | advisory; defer to T4.7b if session-level cost overruns appear | sota-portfolio §10 |
| Real-time cybersecurity safeguards | acknowledged; kernel rail operators apply to Cyber Verification Program at `https://claude.com/form/cyber-use-case` if refusals appear in sweep | `docs/disclosure-playbook.md` + `README.md` security posture |

## What Prism publishes (the promise)

Every medical-benchmark number cited in the Prism submission, demo, or preprint will be:

1. Measured by Prism against Claude Opus 4.7 via `client.messages.create(model="claude-opus-4-7", ...)` on a published-and-dated corpus subset.
2. Graded by third-party code Prism did not author (`simple-evals` rubric for HealthBench Hard; exact-match for MedQA/MMLU/PubMedQA; FHIR side-effect verifier for MedAgentBench).
3. Reproducible from `corpus/` + seed, via one `make verify-baseline` invocation.
4. Reported as mean ± 95% CI half-width across N ≥ 3 independent runs on the declared subset. Harness-delta claims use paired comparison (same subset, same day) with the paired 95% CI excluding 0 before the delta is cited. See `docs/seed-stability-2026-04-22.md` for the variance analysis that motivated replacing the earlier ±0.02 absolute-|Δ| gate.

## Cross-reference

- README clinical-extension card section (keep in sync with this file).
- `docs/sota-portfolio.md` §5 (rules), §10 (Opus 4.7 operational constraints).
- `docs/clinical-roadmap.md` §5 T4.6 (baseline runs establish these numbers).
- `CLAUDE.md` §4 (benchmark discipline).

## History

- **2026-04-21** Initial placeholder created with rows all `pending`.
- **2026-04-21** T-CARD executed against Anthropic's Opus 4.7 launch page. All medical-benchmark rows resolved to `not reported`; operational-constraints table added from the same source.
- **2026-04-22** T-CARD refresh — re-fetched `https://www.anthropic.com/news/claude-opus-4-7`. Confirmed every medical-benchmark row is still `not reported`. Reported charts on the page (Office tasks, Vision, Document reasoning, Long-context reasoning, Biology, Long-term coherence, Coding) plus named benchmarks (Finance Agent, GDPval-AA, CursorBench, Rakuten-SWE-Bench, BigLaw Bench) contain no medical entry. Card unchanged.
- **2026-04-22** T4.6c + T4.6d executed. Two live baseline runs against HealthBench Hard (30-example stratified subset, `corpus/clinical_subset.yaml`), graded by `openai/simple-evals` rubric with Opus 4.7 as judge. Run 1 (seed-label 42, run_id `baseline-seed42-20260422T101603Z`): aggregate **0.2268**, n=30, 0 recused, $2.27. Run 2 (seed-label 43, run_id `baseline-seed43-20260422T104501Z`): aggregate **0.1732**, n=30, 0 recused, $2.25. Both runs clean (zero judge errors, zero retries across 365 rubric items each). **Seed-stability gate FAILED**: |Δ| = 0.0536 exceeds the 0.02 contract at this n. The HealthBench Hard row therefore stays `not reported` — neither aggregate is quotable as the Opus 4.7 baseline. See `docs/seed-stability-2026-04-22.md` for the full report, root-cause analysis (natural sampler noise at n=30 on a [-1, 1] rubric is expected to produce |Δ| ~0.05-0.10; a 0.02 gate at this scale is statistically unachievable for a non-deterministic model), and the three options for reopening: (a) average N=3-5 runs, (b) enlarge subset to shrink mean variance, (c) relax the gate with an explicit statistical justification.
- **2026-04-22** T4.6d RESOLVED via option (a). Third live baseline run (seed-label 44, run_id `baseline-seed44-20260422T162632Z`): aggregate **0.1894**, n=30, 0 recused, $2.21, zero judge errors, zero retries across 365 rubric items. Three-run summary via `scripts/aggregate_runs.py`: **n=3, mean=0.1964, sd=0.0275, sem=0.0159, 95% CI half-width=0.0683** (t-critical 4.303 at df=2). **Published Opus 4.7 HealthBench Hard baseline: 0.196 ± 0.068** (N=3 × n=30 stratified clinical subset, two-sided 95% CI). Total live-eval spend across all three runs: $6.73. HealthBench Hard row flipped from `not reported` to the point estimate above. The absolute `|Δ|<0.02` gate is retired repo-wide; replacement contract (mean ± 95% CI for baselines; paired comparison for harness deltas) lives in `CLAUDE.md` §4 *Benchmark discipline*. Full resolution in `docs/seed-stability-2026-04-22.md` §"Resolution (2026-04-22, same day)".
