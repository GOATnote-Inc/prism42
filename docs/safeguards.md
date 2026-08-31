---
title: Prism — Physician-Facing Safeguards
date: 2026-04-21
audience: Clinicians, hospital CIOs, compliance reviewers
scope: One page. What Prism will and will not do on the clinical rail.
---

# Prism — Safeguards (Clinical Rail)

This page is written for a senior clinician who will spend 60 seconds
deciding whether Prism is safe to evaluate. If any row below fails, stop
and contact the maintainer before running anything.

## What Prism is

Prism is a research harness that tests whether a five-agent dialectic
around Claude Opus 4.7 produces rubric-graded deltas on **published,
public clinical-reasoning benchmarks** (HealthBench Hard by OpenAI,
MedQA, MMLU-Medical, PubMedQA). It is **not a clinical decision-support
tool** and **not approved for any patient-facing use**.

## Hard rules

| # | Rule | Enforced by |
|---|---|---|
| 1 | Never read or store PHI. Benchmarks are public, de-identified. | `corpus/` is public-fixture only; `.gitignore` excludes `.env` and private findings. |
| 2 | The harness does not grade itself. Every rubric score is produced by external third-party code (`simple-evals`, exact-match graders). | `scripts/healthbench_runner.py` calls the external grader; the harness code path cannot bypass it. |
| 3 | No clinical claim ships without a measured delta on a named Phase-B scorer, physician sign-off, and a paired-design gate whose 95% CI excludes 0 (baselines reported as mean ± 95% CI across N ≥ 3 runs). | `docs/sota-portfolio.md` §0, §1, §10; `CLAUDE.md` §4; `docs/seed-stability-2026-04-22.md`. |
| 4 | Clinical findings are model-behavior observations, **not CVEs**. They route through the Anthropic feedback channel under physician review — never social media, never a preprint before review. | `docs/clinical-handling.md`. |
| 5 | Any automated LLM call requires two independent gates: `--commit` flag + `PRISM_*_COMMIT=1` env var. Dry-run is default. | `scripts/check_sdk_containment.py` + `CLAUDE.md` §5. |
| 6 | The Anthropic SDK is imported only inside `do_commit()`. A dry-run path cannot accidentally bill or send. | AST-verified by `scripts/check_sdk_containment.py`. |
| 7 | Every released artifact is reproducible from `corpus/` + a seed. No hand-edited numbers. | `make verify-baseline` + canonical-numbers tag (planned T4.6d). |

## Physician-in-loop gate

Before a clinical finding moves from `results/harness-*.json` to any
disclosure channel:

1. A board-certified physician (Brandon Dent, MD — emergency medicine)
   reads the baseline response, the modified response, and the rubric
   delta.
2. The physician signs the `physician_review` field in the adjudicator
   verdict. Without that signature, the finding stays in
   `findings/clinical-log.jsonl` (gitignored) and is not shared.
3. The adjudicator verdict must list `disclosure_target:
   Anthropic model-feedback channel` — not a public issue tracker, not
   a social platform, not a preprint server.

## Refusal list — what Prism will not do

- Generate a clinical recommendation for a real patient from real
  chart data. (Benchmarks only.)
- Publish a HealthBench-Hard example identifier before OpenAI has
  released the scoring fixture for that example.
- Claim a model "beats" a physician on any axis. The harness measures
  rubric deltas, not clinical competence.
- Compile or run a kernel proof-of-concept on rented hardware without
  a live maintainer under embargo awareness (the GPU rail has its own
  `docs/disclosure-playbook.md` for this).
- Execute a finding packet against the Anthropic feedback channel
  without the physician-review signature described above.

## What a reviewer can verify in 60 seconds

```
git clone https://github.com/GOATnote-Inc/prism   # when public
cd prism
make verify-all                                    # 137 tests, 5 layers green
ls results/demo/                                   # flip-summary + methodology
  || make disclosure-artifacts-commit              # generates drafts locally
```

Nothing above requires an API key, cloud credentials, or a GPU.
The commands do not make any paid calls. The clinical demo artifacts
produced by `make clinical-demo-artifacts-commit` are synthetic
fixtures; no Opus 4.7 calls are made, no PHI is involved.

## AI self-disclosure (voice surfaces)

The 911-simulation voice agents role-play a PSAP dispatcher and are
instructed not to refuse dispatcher work. They are ALSO instructed
(2026-08-24, P1-6) that when a caller directly asks whether they are
talking to an AI, a bot, or a real person, the agent answers truthfully
in one short sentence and then continues the protocol. No prompt or
runtime filter rewrites honest self-disclosure into scripted human-
dispatcher speech; the runtime block list matches refusal-of-service
phrases and medically harmful instructions only. Every page of the
public demo additionally carries a persistent "synthetic fixtures only"
banner.

## Contact

Clinical findings, questions about the rubric, or physician-review
capacity requests: **b@thegoatnote.com** (Brandon Dent, MD;
GOATnote-Inc). Security findings on the GPU rail follow the
private-disclosure playbook in `docs/disclosure-playbook.md`.
