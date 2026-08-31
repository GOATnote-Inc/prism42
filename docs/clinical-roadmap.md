---
title: Prism — Clinical Extension Task Graph & Long-Horizon Roadmap
status: Draft
date: 2026-04-21
scope: Executable decomposition of `docs/clinical-extension-spec.md` into agent-sized work packets, with dependency DAG, agent-type assignment, and per-task verification gates. Covers hackathon window (Apr 21-26, 2026) and post-hackathon long-horizon work.
hard_constraint: Normative source is `docs/clinical-extension-spec.md`. This doc is derivative. Any conflict — spec wins.
---

# Prism — Clinical Extension Task Graph

## 0. Reading order

1. `docs/clinical-extension-spec.md` — normative thesis, gates, budget, branding.
2. This doc — executable decomposition. Task IDs here map 1:1 with spec §5 tasks where they overlap; P-phase and H-phase tasks are new.
3. `docs/sota-portfolio.md` — SOTA alignment layer: verifiable-benchmark portfolio (Phase B), harness technique portfolio (Phase R), voice surface (Phase V), Claude Opus 4.7 baseline card, competitive context. Adds Phase B/R/V tasks to this graph.
4. `CLAUDE.md` (if present) — session-level operating rules.

## 1. Dependency DAG

```
Phase P (pre-gate, safe now)          Phase G (kernel gate)          Phase T (clinical, spec §5)
┌────────────────────────────┐        ┌───────────────────┐         ┌──────────────────────────────┐
│ P1 schema-clinical ───┐     │        │ G1 T4 gate pass   │         │ T4.5a  30-example selection  │
│ P2 script scaffolds ──┤     │        │    (external)     │         │ T4.5b  corpus/clinical YAML  │
│ P3 synth golden ──────┼── ≫ │── ≫ ───┤                   │── ≫ ──▶│ T4.5c  manifest.yaml live    │
│ P4 dual-target thesis ┤     │        │ G2 gate artifact  │         │ T4.6a  simple-evals clone    │
│ P5 clinical-handling ─┤     │        │    recorded       │         │ T4.6b  healthbench_runner    │
│ P6 clinical tests ────┤     │        └───────────────────┘         │ T4.6c  baseline run #1       │
│ P7 NOTICE + 3rdparty ─┘     │                                      │ T4.6d  baseline run #2 ✓repr │
└────────────────────────────┘                                      │ T4.7a  harness_runner clin   │
                                                                     │ T4.7b  harness sweep (30)    │
                                                                     │ T4.7c  delta + durability    │
                                                                     │ T4.8   demo beats cut        │
                                                                     │ T4.9   (opt) voice surface   │
                                                                     └──────────────────────────────┘
                                                                                    │
Phase D (demo/submission) ◀────────────────────────────────────────────────────────┘
┌────────────────────────────┐
│ D1 README rewrite          │
│ D2 video cut review        │
│ D3 submission form         │
└────────────────────────────┘
                                                                                    │
Phase H (post-hackathon long-horizon) ◀────────────────────────────────────────────┘
┌──────────────────────────────────────────────────┐
│ H1 MedAgentBench extension                       │
│ H2 third-rail proposal (legal | bio kernels)     │
│ H3 preprint: adversarial-dialectic, two targets  │
│ H4 public harness skeleton release               │
│ H5 model-behavior disclosure workflow            │
│ H6 physician cohort 30 → 300 examples            │
└──────────────────────────────────────────────────┘
```

## 2. Agent-type legend

| Tag | Agent type | When to use |
|---|---|---|
| `EXPL` | Agent subagent, `subagent_type: Explore` | Codebase reconnaissance, "where does X live?" |
| `PLAN` | Agent subagent, `subagent_type: Plan` | Multi-step planning before implementation |
| `GP-WT` | Agent subagent, `subagent_type: general-purpose`, `isolation: "worktree"` | Isolated implementation work (writes code) |
| `GP` | Agent subagent, general-purpose, no worktree | Small diffs in main tree |
| `MA` | Claude Managed Agents session | Runtime finding adjudication (coordinator-spawned) |
| `CI` | GitHub Actions runner | Automated verification on every push |
| `HUMAN` | Brandon (or designated physician reviewer) | Judgment calls, clinical accuracy review |

## 3. Phase P — Pre-gate scaffolding

Seven tasks that do not touch clinical corpus content, do not make live API calls, and do not violate spec §10 "Do not start T4.5 before T4 passes." Each is inert until the gate clears; running them now shortens post-gate wall-clock.

### P1 — Clinical schema rail conditional required-fields
- **Agent**: `GP-WT`
- **Blocks**: T4.5b, T4.6b, T4.7a
- **Blocked by**: — (safe now)
- **Inputs**: `schemas/case.schema.json`, `schemas/invariants.schema.json`, `schemas/exec.schema.json`, `schemas/verdict.schema.json`, spec §4.3
- **Outputs**: schemas patched with `if rail == "clinical" then require [healthbench_hard_example_id, target_axis, rubric_ref]`; new `schemas/clinical-rubric.schema.json`
- **Verification**: (a) all existing tests still pass (85/85), (b) `jsonschema.Draft202012Validator.check_schema(...)` on edited schemas, (c) negative-control: clinical case missing `target_axis` MUST fail validation
- **Size**: ~3 hours

### P2 — Script scaffolding with dry-run defaults + double-gate
- **Agent**: `GP-WT`
- **Blocks**: T4.6b, T4.6c, T4.7a
- **Blocked by**: P1 (need clinical schemas to validate against)
- **Inputs**: spec §5 T4.6/T4.7, existing `scripts/harness_runner.py` as double-gate pattern template
- **Outputs**: `scripts/healthbench_runner.py`, `scripts/compare_runs.py`, `scripts/spot_check.py`, `scripts/delta_report.py`, `scripts/verify_session_durability.py` — all default `--dry-run`, live paths require `--commit` AND `PRISM_CLINICAL_COMMIT=1`
- **Verification**: (a) `scripts/check_sdk_containment.py` passes on each new script (Anthropic/OpenAI imports inside `do_commit()` only), (b) dry-run invocations from `make verify-t3` don't fire live APIs
- **Size**: ~5 hours

### P3 — Clinical synthetic golden-case fixture
- **Agent**: `GP-WT`
- **Blocks**: T4.6b (reference fixture for tests), P6
- **Blocked by**: P1
- **Inputs**: existing `corpus/golden-cases/KERNEL-GOLD-001/` as structural template
- **Outputs**: `corpus/golden-cases/HBH-CLN-SYNTH/` with `case.json` (rail=clinical, invented but plausible), `invariants.json`, `attacks.json`, `exec.json` (clinical verdict path), `verdict.json`, `report.md`, `poc.py` stub. Marked `notes: "synthetic fixture for validator tests, not a real HealthBench example"`
- **Verification**: `python scripts/validate_artifacts.py --case-dir corpus/golden-cases/HBH-CLN-SYNTH` exit 0
- **Size**: ~2 hours

### P4 — `docs/dual-target-thesis.md`
- **Agent**: `GP` (short doc, no worktree needed)
- **Blocks**: D1 README, "Keep Thinking" prize artifact
- **Blocked by**: —
- **Inputs**: spec §1, §4.5, author's working theory of kernel-vs-clinical failure-mode crosswalk
- **Outputs**: 400-800 word doc with a failure-taxonomy crosswalk table (numerical/memory/concurrency/precision ↔ premature-closure/context-loss/safety-rail-bypass/hallucination) and a "what this buys you" paragraph
- **Verification**: (a) `wc -w` between 400 and 800, (b) link-check passes (no dead internal refs), (c) HUMAN read-through before committing
- **Size**: ~2 hours

### P5 — `docs/clinical-handling.md`
- **Agent**: `GP`
- **Blocks**: T4.7c (disclosure action on confirmed_delta findings)
- **Blocked by**: —
- **Inputs**: spec §4.4 ("Clinical findings get a separate disclosure path…"), Anthropic model-feedback workflow (thumbs-down + direct email)
- **Outputs**: doc specifying: (i) what kinds of clinical findings get reported, (ii) to whom (Anthropic feedback email vs. upstream clinical-reasoning researchers vs. internal only), (iii) explicit NOT-a-CVE framing, (iv) redaction rules (no PHI — corpus is synthetic/public)
- **Verification**: HUMAN review — clinical ethics read from Brandon as physician
- **Size**: ~2 hours

### P6 — Test scaffolding for clinical validators
- **Agent**: `GP-WT`
- **Blocks**: CI gate on all later tasks
- **Blocked by**: P1, P3
- **Inputs**: existing `tests/test_artifact_validation.py`, `tests/test_golden_case.py`
- **Outputs**: `tests/test_clinical_case.py` (parametrized over rail=clinical requirements), extension to `tests/test_golden_case.py` asserting `HBH-CLN-SYNTH` validates
- **Verification**: `pytest tests/ -q` shows >85 passing (currently 85; target 100+)
- **Size**: ~3 hours

### P7 — `NOTICE` + `third_party/README.md` scaffold
- **Agent**: `GP`
- **Blocks**: T4.6a (simple-evals clone)
- **Blocked by**: —
- **Inputs**: spec §5 T4.6 (Apache 2.0 attribution)
- **Outputs**: `NOTICE` file (empty skeleton ready for simple-evals attribution), `third_party/README.md` explaining vendoring policy (no binaries in-tree; clone-on-demand with pinned commit SHA)
- **Verification**: files exist, `grep -i apache third_party/README.md` hits
- **Size**: ~1 hour

**Phase P total**: ~18 hours of agent-time, all parallelizable after P1 lands. P1→P2→P6 is the critical path (~11 hours sequential); P3/P4/P5/P7 run in parallel.

## 4. Phase G — Kernel gate

### G1 — T4 kernel-corpus validation pass
- **Agent**: external (parallel session owns this; do not interfere)
- **Blocks**: all T-phase work
- **Blocked by**: parallel session completing T4
- **Gate criteria** (from spec §1): ≥80% recall on known-fixed bugs, ≤20% false-positive rate on kernel-bug corpus
- **Verification**: parallel session writes gate-pass artifact; this session reads it (no modifications to `corpus/reproducers/*`)

### G2 — Record T4 gate result machine-readably
- **Agent**: `GP`
- **Blocks**: T4.5a
- **Blocked by**: G1
- **Outputs**: `findings/kernel/t4-gate-result.json` with `{recall, false_positive_rate, commit_sha, timestamp, verdict: "pass"|"fail"}`
- **Verification**: JSON schema-validates, `verdict == "pass"`, numbers meet gate

## 5. Phase T — Clinical extension (spec §5)

Each row is one task packet. All marked with spec cross-ref.

### T4.5a — HealthBench Hard 30-example selection
- **Agent**: `HUMAN` (Brandon) with `EXPL` assist for candidate-set exploration
- **Spec**: §5 T4.5 item 1
- **Blocks**: T4.5b
- **Blocked by**: G2
- **Outputs**: candidate list of 30 example IDs with distribution annotations (10 emergency, 5 peds, 5 OBGYN, 5 psych, 5 general)
- **Verification**: distribution counts match, no duplicates, every ID resolves in HealthBench Hard dataset
- **Size**: ~3 hours (physician time)

### T4.5b — `corpus/clinical_subset.yaml`
- **Agent**: `GP-WT`
- **Spec**: §5 T4.5 item 1
- **Blocks**: T4.6b
- **Blocked by**: T4.5a, P1
- **Outputs**: `corpus/clinical_subset.yaml` v0.1.0 with 30 entries per spec schema
- **Verification**: `make verify-clinical-corpus` (new Makefile target — see §8)
- **Size**: ~2 hours

### T4.5c — `agents/manifest.yaml` populated live
- **Agent**: `GP` running `scripts/register_agents.py --commit` locally
- **Spec**: §5 T4.5 item 2
- **Blocks**: T4.7a
- **Blocked by**: G2 (don't spend before gate)
- **Outputs**: `agents/manifest.yaml` with 6 registered `{id, version}` pairs from Managed Agents API
- **Verification**: `make verify-agents-registered` prints "6 agents registered … OK"
- **Cost**: <$0.10 (agent-create calls only)

### T4.6a — `third_party/simple-evals` clone + NOTICE audit
- **Agent**: `GP`
- **Spec**: §5 T4.6
- **Blocks**: T4.6b
- **Blocked by**: G2, P7
- **Outputs**: `third_party/simple-evals/` at pinned commit, `NOTICE` updated with Apache 2.0 attribution
- **Verification**: `grep -r "Apache License" third_party/simple-evals/LICENSE`; pinned commit SHA recorded in `third_party/README.md`

### T4.6b — `scripts/healthbench_runner.py` implementation
- **Agent**: `GP-WT`
- **Spec**: §5 T4.6
- **Blocks**: T4.6c
- **Blocked by**: P2, T4.5b, T4.6a
- **Outputs**: runner calls Claude Opus 4.7 via Messages API (not Managed Agents), grades via simple-evals, emits per-example + aggregate scores
- **Verification**: dry-run produces zero API calls; `--commit` gate wired correctly

### T4.6c — Baseline run #1
- **Agent**: `GP` invoking runner with `--commit PRISM_CLINICAL_COMMIT=1 --seed 42`
- **Spec**: §5 T4.6
- **Blocks**: T4.6d, T4.7b
- **Blocked by**: T4.6b
- **Outputs**: `results/baseline-opus47-YYYYMMDD-HHMM-1.json`
- **Verification**: 30 example scores present; aggregate is a number in [0,1]
- **Cost**: ~$15

### T4.6d — Baseline runs #2..N + CI report (revised 2026-04-22)
- **Agent**: `GP`
- **Spec**: §5 T4.6 verification; `docs/seed-stability-2026-04-22.md` (variance analysis)
- **Blocks**: T4.7b
- **Blocked by**: T4.6c
- **Outputs**: `results/baseline-opus47-seedNN.json` for N ≥ 3 runs + `results/seed-stability-report.json` (or tracked `docs/seed-stability-YYYY-MM-DD.md`)
- **Verification**: compute mean and 95% CI half-width of aggregates across N ≥ 3 runs. **Gate for publication:** 95% CI half-width ≤ 0.05 on the 30-example stratified subset (achievable at N=3 under Opus 4.7 variance); below that, quote the point estimate with its CI as-is — the CI itself is the honest uncertainty statement. Halt only on safety-contract failures (judge auth, recusal storm, budget overrun), not on aggregate spread — spread is reported, not gated.
- **Cost**: ~$7 for N=3 on 30-example subset; ~$15 budgeted remains the cap.

### T4.7a — `scripts/harness_runner.py` clinical branch
- **Agent**: `GP-WT`
- **Spec**: §5 T4.7
- **Blocks**: T4.7b
- **Blocked by**: T4.5c, T4.6d, P2
- **Outputs**: existing harness_runner.py extended: if case rail == "clinical", executor thread calls Anthropic Messages API against the rubric rather than GPU SSH exec
- **Verification**: unit test with `HBH-CLN-SYNTH` fixture runs end-to-end dry-run

### T4.7b — Harness sweep (30 coordinator sessions)
- **Agent**: `GP` invoking runner with full gates
- **Spec**: §5 T4.7
- **Blocks**: T4.7c
- **Blocked by**: T4.7a, T4.6d
- **Outputs**: `results/harness-YYYYMMDD.json` with 30 verdicts
- **Verification**: non-zero `confirmed_delta` count; durability test runs mid-sweep (`verify_session_durability.py --sample 3`) and passes
- **Cost**: ~$100 (tokens + ~$2 session-hr)

### T4.7c — Delta report + regression triage
- **Agent**: `GP` + `HUMAN` (triage)
- **Spec**: §5 T4.7
- **Blocks**: T4.8
- **Blocked by**: T4.7b
- **Outputs**: `results/delta-report.md` with: baseline aggregate, modified aggregate, per-example deltas, regressions explained (or flagged as real findings per §4.4 → disclosure path from P5)
- **Verification**: report parses; regressions have human triage notes

### T4.8 — Demo cut (clinical beat + Managed Agents beat)
- **Agent**: `HUMAN` (video craft) + `PLAN` for storyboard
- **Spec**: §5 T4.8
- **Blocks**: D2
- **Blocked by**: T4.7c
- **Outputs**: two video segments (30s clinical, 20s Managed Agents) with stopwatch-verified timing

### T4.9 — (Optional) ElevenLabs voice surface
- **Agent**: `GP-WT`
- **Spec**: §5 T4.9
- **Blocks**: — (optional)
- **Blocked by**: T4.8, ≥4h remaining before submission
- **Outputs**: SSE endpoint wrapping harness, 20s demo clip
- **Skip trigger**: round-trip >4s OR <4h remaining

## 6. Phase D — Demo & submission

### D1 — README rewrite
- **Agent**: `GP` with `PLAN` for structure
- **Blocks**: D3
- **Blocked by**: T4.7c, P4
- **Outputs**: top-level README leading with spec §9 one-liner, then three sections: (i) GPU primary, (ii) clinical extension, (iii) methodology
- **Verification**: link-check, dead-code scan; HUMAN read cold next morning

### D2 — 3-min video cut review
- **Agent**: `HUMAN`
- **Blocks**: D3
- **Blocked by**: T4.8
- **Outputs**: final cut file
- **Verification**: watched cold; each beat within spec timing

### D3 — Submission form + links
- **Agent**: `HUMAN`
- **Blocks**: hackathon deadline
- **Blocked by**: D1, D2
- **Outputs**: submitted form, repo visibility decision made, disclosure embargo status confirmed (see H5)

## 7. Phase H — Long-horizon (post-Apr 26)

Each H-task is a standalone 1-3 week project suitable for a single subagent team or dedicated sprint.

### H1 — MedAgentBench extension
- **Agent**: `PLAN` → `GP-WT` team
- **Blocked by**: D3
- **Thesis**: port the same harness to agentic clinical workflows (300 tasks, FHIR environment). Docker `jyxsu6/medagentbench` on port 8080.
- **Gate**: baseline + harness deltas that survive a 3-trial reproducibility check
- **Size**: ~2 weeks

### H2 — Third-rail proposal
- **Agent**: `PLAN`, then user decision
- **Blocked by**: D3
- **Candidate rails**: (a) legal-reasoning (LegalBench-style), (b) bioinformatics kernels (HMMER, BLAST inner loops), (c) formal-verification proofs (miniF2F)
- **Output**: 3-page proposal per candidate with failure-mode taxonomy, corpus availability, demo potential
- **Gate**: user picks one; rejected candidates archived in `docs/rails-considered.md`

### H3 — Preprint: "Adversarial-dialectic auditing across two targets"
- **Agent**: `PLAN` → `HUMAN` (physician-engineer co-author) + `GP-WT` for figures/code
- **Blocked by**: T4.7c, H1 (ideally)
- **Output**: arXiv preprint, ~12 pages, code + corpus links, reproducibility section
- **Venue targets**: NeurIPS D&B 2026 (healthcraft precedent), or MLSys 2027

### H4 — Public harness skeleton release
- **Agent**: `GP-WT` team
- **Blocked by**: D3 and disclosure embargo lift
- **Output**: `prism-skel` repo with: (i) 6-agent template YAMLs, (ii) schemas, (iii) double-gate + containment patterns, (iv) example `hello_world` case, (v) apache-2.0 license — **without** the GPU reproducer corpus or HealthBench Hard selections
- **Verification**: a third party can clone, run `make verify-all`, and get green on a fresh machine

### H5 — Model-behavior disclosure workflow
- **Agent**: `HUMAN` (Brandon + clinical/legal advisors) → `GP` for automation
- **Blocked by**: P5, T4.7c
- **Output**: `scripts/disclose_clinical_finding.py` that takes a `confirmed_delta` case and produces the packet (redacted conversation, rubric excerpt, delta evidence) for Anthropic feedback channel
- **Gate**: two dry-run packets reviewed and approved before first real submission

### H6 — Physician cohort scale-up (30 → 300 examples)
- **Agent**: `HUMAN` (cohort recruiter) + `GP-WT` (pipeline scale)
- **Blocked by**: D3, budget
- **Output**: expanded HealthBench Hard subset, multi-physician adjudication overlay (~3-reviewer κ ≥0.6 per safety-critical case)
- **Budget**: ~$1500 API + reviewer honoraria
- **Unblocks**: H3 main-text table replacement

## 8. Makefile surface to add (in Phase T)

Append-only extension of the existing T3 appendix. Land in T4.5b / T4.6b / T4.7a commits respectively.

```make
verify-clinical-corpus:
	@$(PY) scripts/validate_clinical_subset.py corpus/clinical_subset.yaml

verify-agents-registered:
	@$(PY) scripts/verify_agents.py --manifest agents/manifest.yaml

verify-baseline:
	@for seed in 42 43 44; do \
		$(PY) scripts/healthbench_runner.py --manifest corpus/clinical_subset.yaml \
			--out results/baseline-$$seed.json --seed $$seed $(COMMIT) ; \
	done
	@$(PY) scripts/aggregate_runs.py results/baseline-42.json results/baseline-43.json results/baseline-44.json

verify-harness:
	@$(PY) scripts/harness_runner.py --manifest corpus/clinical_subset.yaml --baseline results/baseline-1.json --out results/harness.json $(COMMIT)
	@$(PY) scripts/delta_report.py results/baseline-1.json results/harness.json
	@$(PY) scripts/verify_session_durability.py --sample 3

verify-clinical: verify-clinical-corpus verify-agents-registered
	@echo "verify-clinical: scaffolding checks passed (live runs gated by COMMIT=1)"

verify-all-with-clinical: verify-all verify-clinical
	@echo "verify-all-with-clinical: ALL LAYERS GREEN (offline + clinical scaffold)"
```

## 9. Agent-handoff protocol

When dispatching a task packet to a subagent, the invocation MUST include:

1. **Task ID** (e.g., "P1" or "T4.6b") — the agent references back to this doc.
2. **Spec cross-ref** — the agent must read the spec section before acting.
3. **Inputs** — files/paths the agent may read.
4. **Outputs** — files/paths the agent may write.
5. **Frozen paths** — `.env`, `.state/`, `docs/clinical-extension-spec.md` — agent must not touch these.
6. **Verification command** — the exact shell command whose exit 0 proves the task done.
7. **Commit rule** — one commit per task, message template: `T-{id}: {subject}`, co-author footer `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`, no `git push`.
8. **Budget** — token/$ ceiling; the agent halts on hit.

Template dispatch prompt (for P1 as example):

```
Task P1 — clinical schema rail conditional required-fields.

Read first:
- docs/clinical-extension-spec.md §4.3, §5 T4.5
- docs/clinical-roadmap.md §3 P1
- schemas/*.schema.json (all six)

Frozen paths (do not touch): .env .state/ corpus/reproducers/* docs/clinical-extension-spec.md

Scope: patch schemas so that when rail == "clinical", the case requires
healthbench_hard_example_id, target_axis, rubric_ref. Existing GPU rails
unchanged. Write schemas/clinical-rubric.schema.json for the rubric doc.

Verification (must all pass before you commit):
1. python -c "import json, jsonschema; [jsonschema.Draft202012Validator.check_schema(json.load(open(f))) for f in <edited files>]"
2. python scripts/validate_artifacts.py --case-dir corpus/golden-cases/KERNEL-GOLD-001  (expect PASS — no regression)
3. python -m pytest tests/ -q  (expect 85+ passed, 0 failed)
4. negative-control: a synthetic clinical case missing target_axis must fail
   python scripts/validate_artifacts.py

One commit, message "T3 P1: clinical schema rail conditional required-fields",
with Co-Authored-By footer. Do NOT push.
```

## 10. Status snapshot (this session)

- Phase P: not started (gated by user decision, not by T4 — can start anytime).
- Phase G: G1 in-flight in parallel session.
- Phase T: blocked on G1.
- Phase D: blocked on T4.8.
- Phase H: planning only; all blocked on D3.
