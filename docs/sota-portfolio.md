---
title: Prism — SOTA Portfolio Addendum
date: 2026-04-21
status: Draft
scope: State-of-the-art alignment layer over docs/clinical-roadmap.md. Verifiable-benchmark portfolio (Phase B), harness technique portfolio (Phase R), voice surface (Phase V), competitive context, Claude Opus 4.7 medical-benchmark card. Every technique ships with an external scorer.
---

# Prism — SOTA Portfolio Addendum

Companion to `docs/clinical-roadmap.md`. The roadmap enumerates work packets; this doc locks in the *what-we're-measuring-against* layer so every harness iteration has an external, objective scorer. **No technique ships without a measured delta on a Phase B scorer.**

## 0. Framing principle

**Give Claude a way to verify its work — always set up a verification step.**

For Prism that verification step is an external, objective scorer the harness does not control. The harness improves the score by construction or it does not. There is no unmarked progress, no "trust me" demos.

Two kinds of scorer:

| Type | Example | Verifies |
|---|---|---|
| Deterministic I/O | kernel PoC exits with `VIOLATION ...` line | Kernel rail. Binary pass/fail. |
| Rubric grader | HealthBench Hard `simple-evals` grader; MedAgentBench FHIR side-effect check; MedQA exact-match | Clinical rail. Numeric per-axis or binary. |

Every item in Phase B below has a named grader. Any technique in Phase R or V must demonstrate its lift on at least one Phase B scorer before it ships in the demo.

---

## 1. Phase B — Verifiable-benchmark portfolio

The clinical rail's scoring substrate. All public; all reproducible on the runner's machine; all graded by code Prism did not write.

### B1 — HealthBench Hard (OpenAI, 2025)
- **Size**: 1,000 physician-authored multi-turn conversations; 30-example subset for the hackathon, 5,000 full for H6.
- **Grader**: `simple-evals` (Apache 2.0, cloned at T4.6a). Five axes: accuracy / completeness / context_awareness / instruction_following / communication.
- **Public baselines at release (2025)**: GPT-5 0.46, GPT-5.2 0.42, GPT-5.1 0.40, Grok 3 0.23, Gemini 2.5 Pro 0.19, Claude 3.7 Sonnet 0.02.
- **Claude Opus 4.7**: **no publicly reported HealthBench Hard score as of 2026-04-21.** Establishing this baseline is the headline empirical contribution of the clinical extension.
- **Baseline reporting**: mean of N ≥ 3 independent runs ± 95% CI half-width on the declared subset (T4.6d). The prior `|Δ| < 0.02` absolute gate is retired — statistically unachievable at n=30 under Opus 4.7's sampler variance (see `docs/seed-stability-2026-04-22.md`).
- **Roadmap tasks**: T4.6c baseline, T4.6d reproducibility, T4.7b harness delta.

### B2 — MedQA (USMLE-style, Jin et al. 2020)
- **Size**: ~12,700 questions; USMLE Step 1/2/3-level, 4-option MCQ.
- **Grader**: exact-match to answer letter. Fully deterministic, zero rubric ambiguity.
- **Role in Prism**: **null-result control.** The adversarial-dialectic harness is not expected to move a closed-book MCQ score beyond noise. If it does, the harness is leaking (e.g. retrieving the answer key) and methodology is broken — investigate before reporting.
- **Gate**: harness - baseline MedQA delta must satisfy `|delta| <= 0.01` (noise floor).
- **New task**: `scripts/medqa_runner.py` (spec mirrors `healthbench_runner.py`). See §6.

### B3 — PubMedQA (Jin et al. 2019)
- **Size**: 1,000 expert-labeled questions (PQA-L) with yes/no/maybe answers grounded in PubMed abstracts.
- **Grader**: exact-match.
- **Role in Prism**: **RAG validation scorer.** Baseline run (no retrieval) vs. R1-augmented run (MedlinePlus / PubMed retrieval before answering). Expected lift >=10pp when R1 is correctly wired. If lift is <5pp, retriever is not firing or context is being ignored.
- **Gate**: R1/R2 ship only when PubMedQA lift >=10pp.

### B4 — MMLU-Medical-6 aggregate
- **Subsets**: anatomy, clinical_knowledge, college_medicine, medical_genetics, professional_medicine, virology.
- **Grader**: MMLU framework exact-match, aggregated.
- **Role**: breadth check. Same null-result expectation as B2 — harness not expected to move closed-book knowledge recall.

### B5 — MedAgentBench (Stanford ML Group, NEJM AI)
- **Size**: 300 clinician-authored tasks across 10 categories; FHIR environment with 100 de-identified profiles, 700,000+ data elements.
- **Grader**: mock-FHIR side-effect verifier — each task has required FHIR read/write operations; grader checks the post-state against the rubric.
- **Public baseline**: Claude 3.5 Sonnet v2 leads at 69.67% at dataset release.
- **Docker**: `jyxsu6/medagentbench` on port 8080.
- **Role in Prism**: **H1 stretch (post-hackathon).** Bridge is R3 FHIR tool adapter. Tests agentic workflow lift from the harness + MCP FHIR tools.

### B6 — HealthBench full (5,000 examples)
- **Deferred to H6** (physician-cohort scale-up). 30-example hackathon subset suffices for the demo.

### B-table — summary

| ID | Benchmark | Grader type | Role | Gate |
|---|---|---|---|---|
| B1 | HealthBench Hard | rubric (simple-evals) | primary clinical metric | paired-delta 95% CI excludes 0 (baseline reported as mean ± 95% CI across N ≥ 3 runs) |
| B2 | MedQA | exact-match | null-result control | \|harness - baseline\| <= 0.01 |
| B3 | PubMedQA | exact-match | RAG validator | R1/R2 lift >= 10pp |
| B4 | MMLU-Med-6 | exact-match | breadth / null-result | same as B2 |
| B5 | MedAgentBench | FHIR side-effect | agentic (H1) | beat Claude 3.5 Sonnet v2 baseline |
| B6 | HealthBench full | rubric | H6 cohort scale-up | (deferred) |

---

## 2. Phase R — Retrieval + tool grounding

**Anthropic's enterprise recommendation hierarchy for domain-performance lift, in expected-yield order**: (1) better prompting, (2) tool use, (3) retrieval-augmented generation, (4) extended thinking / compute scaling, (5) multi-agent workflows. **LoRA / fine-tuning is NOT available on Claude via the public API** — the harness lives entirely above the model. Skills (Anthropic's 2026 spec) sit between prompting and tool-use and are Prism-native.

### R1 — MedlinePlus retriever (RAG-1)
- **Corpus**: MedlinePlus Connect (NIH-curated, public, XML/JSON API, zero cost).
- **Use**: when a HealthBench Hard / PubMedQA question references a condition, the harness retrieves the MedlinePlus entry and passes it to the executor as context.
- **Graded on**: B3 PubMedQA (primary), B1 HealthBench Hard accuracy axis (secondary).
- **Gate**: PubMedQA lift >= 10pp to ship.
- **Blocked by**: P2.

### R2 — PubMed search tool (RAG-2)
- **Corpus**: PubMed via NCBI E-utilities (free; 3 req/s without API key, 10 with).
- **Use**: harness exposes a `pubmed_search(query)` tool. Tool returns top-K abstracts; executor cites them verbatim when claiming a fact.
- **Graded on**: synthetic 30-query set with known PubMed answers; recall@5 >= 0.7 to ship.
- **Blocked by**: R1.

### R3 — FHIR tool adapter
- **Role**: bridge to B5 MedAgentBench in H1.
- **Tools exposed** (14 standard MedAgentBench tools): readPatient, readObservation, readMedication, readCondition, createCondition, createObservation, createMedication, readEncounter, createDocumentReference, readDiagnosticReport, readAllergyIntolerance, createAllergyIntolerance, searchProcedure, readCarePlan.
- **Graded on**: B5.
- **Blocked by**: H1 kickoff.

### R4 — Skills (Anthropic Skills spec)
- **Skills to define (3 minimum)**:
  - `clinical-review`: physician-tone formatter with safety-checklist preamble ("Did we consider: red flags? differentials? contraindications?").
  - `differential-diagnosis`: structured DDx output with prior probability per item.
  - `dosage-check`: cross-reference drug dose to weight / age / renal function; flags contraindications.
- **Graded on**: B1 HealthBench Hard — `clinical-review` against communication axis; `differential-diagnosis` against completeness; `dosage-check` against accuracy.
- **Gate**: per-axis delta >= 0.05 to ship the skill.
- **Blocked by**: T4.7a.
- **Status (2026-04-22)**: SKILL.md files landed at `skills/prism-{clinical-review,differential-diagnosis,dosage-check}/SKILL.md`. `scripts/register_skills.py` ROLES tuple extended; dry-run plan shows idempotent-extend (adopt 6 existing, upload 3 new, rebind all 9 to coordinator). Live upload + rebind pending `PRISM_SKILLS_COMMIT=1 python scripts/register_skills.py --commit` (free API, ~$0 cost). R4-GATE measurement is still blocked on T4.7b harness sweep running against the 30-example subset.

### R5 — Self-critique inner pass
- **Description**: before emitting its final clinical response, the executor runs one inner self-critique turn: "given the above draft, what would be unsafe, incomplete, or missing context? Revise." Mirrors the defender pattern, self-applied.
- **Cost**: ~2x tokens per case.
- **Graded on**: B1 completeness + context_awareness axes.
- **Blocked by**: T4.7a.

### R6 — Extended thinking condition
- **Description**: enable Opus 4.7 extended-thinking (<= 8k thinking-token budget) on clinical cases as a separate condition. Hackathon main run uses thinking=off for reproducibility; thinking=on run is the model-contribution attribution.
- **Graded on**: B1 aggregate.
- **Reported separately** — this is the model's contribution, not the harness's.

### Technique attribution table (populated during T4.7c)

| Technique | Isolation | Expected gain axis | Graded on | Ships if |
|---|---|---|---|---|
| Harness (full 5-agent dialectic) | vs. direct Messages API | accuracy, completeness | B1 | paired-delta 95% CI excludes 0 (two-sided, α=0.05) |
| R1 MedlinePlus RAG | vs. no retrieval | accuracy | B1, B3 | B3 lift >= 10pp |
| R2 PubMed tool | vs. no tool | accuracy | B1 (cited-answer subset) | recall@5 >= 0.7 on synthetic set |
| R4 Skills | vs. no skill | per-axis (see R4) | B1 | axis delta >= 0.05 |
| R5 Self-critique | vs. no critique | completeness, context_awareness | B1 | axis delta >= 0.03 |
| R6 Extended thinking | vs. thinking=off | accuracy | B1 | reported regardless (informational) |

---

## 3. Phase V — Voice surface (ElevenLabs)

**Reference frame.** The 2026 voice-AI healthcare bar is set by Abridge (physician-scribe, JAMA-reviewed), Ambience (ambient clinical listening), OpenEvidence (retrieval-grounded clinical Q&A, Mayo partnership), and the Gemini-in-Healthcare family. Ops-side, ElevenLabs already powers QSR drive-thru and call-center voice agents through OpenAI-compatible SSE endpoints. A Prism voice demo has to clear that bar or skip clean — no toy demos.

### V1 — OpenAI-compatible SSE endpoint (clinical rail, realtime subset)
- **Endpoint**: `POST /v1/chat/completions` (streaming) or `POST /v1/responses`. Wraps the harness's clinical fast path: incoming message -> `clinical-review` skill (R4.1) -> Opus 4.7 streaming -> tokens out.
- **Latency budget**: <= 4 s round-trip end-to-end (ElevenLabs target). Breakdown target:
  - STT (ElevenLabs): ~400 ms
  - LLM first token (Opus 4.7 streaming): ~600 ms
  - LLM complete (2-3 sentence reply): ~1,500 ms
  - TTS (ElevenLabs): ~400 ms
  - Network + overhead: ~1,000 ms
  - Total target: ~3.9 s. **No budget for the full 5-agent dialectic on the realtime path.** Full dialectic runs async out-of-band; realtime uses skill R4.1 only.
- **Gate**: p95 <= 4 s, p99 <= 5 s across 20 sample queries. Higher -> cut V entirely (see V4).

### V2 — ElevenLabs agent config
- **Agent**: custom-LLM-backed conversational agent per ElevenLabs conversational-AI docs.
- **Voice preset**: ElevenLabs default clinical-tone voice; no voice cloning.
- **System prompt**: <= 200 tokens; skill R4.1 inline.
- **Tool surface**: R2 PubMed search callable from voice ("cite a recent paper on X"); returns 1-sentence summary read back.

### V3 — Demo script + stopwatch verification
Three recorded queries (<= 20 s each):
- (a) "What's first-line treatment for community-acquired pneumonia in a healthy adult?"
- (b) "Patient is 84 kg, creatinine clearance 45. Dose vancomycin."
- (c) "Differential for acute chest pain in a 35-year-old with no cardiac history?"

Verification:
- Stopwatch latency per query; p95 computed.
- Transcript auto-graded out-of-band against an HBH-style rubric by the `clinical-review` skill as a sanity read — not the demo decision, but a sanity net.

### V4 — Cut signal
Cut all of Phase V if any of:
- V1 p95 > 4 s.
- < 4 h remaining before submission.
- Realtime path starts to compromise the dialectic-harness contract (e.g., skipping R4 safety preamble to hit latency).

Voice is the bow. Never sacrifice the cake.

---

## 4. Competitive context (2026-04-21 snapshot)

Reference frame for what a real voice + clinical-AI surface looks like in 2026. Prism is not positioning against these products — it is borrowing their design discipline.

| Reference | What they do | What Prism borrows |
|---|---|---|
| OpenEvidence | Clinical Q&A grounded in peer-reviewed literature; Mayo Clinic partnership; free tier for verified clinicians. | Retrieval-first posture for clinical claims (R1, R2). Cite-before-claim discipline. |
| Abridge | Ambient physician scribe; 55+ health-system deployments; JAMA-reviewed evaluation. | Transcribe -> structure -> clinician-review loop — maps onto Prism's ambient -> draft -> adjudicator loop. |
| Ambience | Ambient clinical listening across the full encounter; Cleveland Clinic deployment. | Ambient-input -> structured-output pattern; privacy-first posture. |
| Gemini in Healthcare (MedPaLM lineage) | Multimodal clinical reasoning; enterprise channel. | Multi-axis rubric grading precedent; scale-up methodology. |
| ElevenLabs drive-thru / call-center | Sub-second voice AI for ops-heavy domains (QSR order-taking, L1 support); OpenAI-compatible SSE. | V1 endpoint shape and the 4-s round-trip bar. Proof that voice AI is a solved engineering problem at this latency budget. |

**What Prism does that none of the above claim as a headline contract:** *every finding ships with a runnable proof-of-concept the harness executed on real infrastructure before reporting.* OpenEvidence cites. Abridge transcribes. Ambience listens. Prism reproduces.

---

## 5. Claude Opus 4.7 baseline card (verification required)

The README will carry a baseline card for Claude Opus 4.7 on established medical benchmarks. Rows below are placeholders; each requires source verification before publication. See §6 T-CARD for the fetch-and-verify task.

| Benchmark | Score | Source | Verified? |
|---|---|---|---|
| MedQA (USMLE) | pending | Claude Opus 4.7 model card | pending (T-CARD) |
| MMLU-Medical (6-subset aggregate) | pending | Claude Opus 4.7 model card | pending |
| PubMedQA | pending | Claude Opus 4.7 model card / third-party if absent | pending |
| MultiMedQA (if reported) | pending | Claude Opus 4.7 model card | pending |
| HealthBench Hard | *no public score* | — | N/A (Prism establishes — see B1) |
| MedAgentBench | pending | Stanford ML Group leaderboard | pending |

Rules for populating this card:
- Every number is a direct quote from a cited source — no computed aggregates, no interpolation from related tasks.
- Every row lists the source URL + fetch timestamp.
- The README card links back to this file; this file is the source of truth.
- If a benchmark is not reported on the Opus 4.7 model card, the row stays "not reported" — do not backfill with a related model's number.

---

## 6. Task graph extensions (update to `docs/clinical-roadmap.md`)

The following tasks extend the roadmap's Phase T and add Phase B, R, V. Agent-handoff protocol from roadmap §9 applies to all.

### Phase B (benchmarks) — new
- **B2-RUNNER** `scripts/medqa_runner.py` — MedQA exact-match runner, dry-run default, double-gate. GP-WT. Blocked by P2.
- **B3-RUNNER** `scripts/pubmedqa_runner.py` — PubMedQA runner. Same shape as B2. GP-WT. Blocked by P2.
- **B4-RUNNER** `scripts/mmlu_medical_runner.py` — MMLU-Medical-6 aggregate runner. GP-WT. Blocked by P2.
- **B-VERIFY** `make verify-benchmarks` — one-shot target that runs all four clinical-rail benchmark runners in dry-run and validates output schemas. GP. Blocked by B2-RUNNER, B3-RUNNER, B4-RUNNER.

### Phase R (retrieval + tools) — new
- **R1-IMPL** `scripts/retriever_medlineplus.py` — stateless MedlinePlus lookup. Cached locally. GP-WT. Blocked by P2.
- **R1-GATE** PubMedQA lift measurement (R1 on/off). GP. Blocked by R1-IMPL, B3-RUNNER.
- **R2-IMPL** `scripts/tool_pubmed.py` — PubMed E-utilities wrapper (rate-limit-aware). GP-WT. Blocked by R1-IMPL.
- **R2-GATE** Synthetic recall@5 measurement. GP.
- **R3-IMPL** FHIR tool adapter (14 tools). GP-WT. Blocked by H1 kickoff.
- **R4-IMPL** Three Skills: clinical-review, differential-diagnosis, dosage-check. GP-WT. Blocked by T4.7a.
- **R4-GATE** Per-skill per-axis delta on HealthBench Hard. GP. Blocked by R4-IMPL + T4.7b.
- **R5-IMPL** Self-critique inner pass (executor prompt extension). GP. Blocked by T4.7a.
- **R5-GATE** Completeness + context_awareness delta on HealthBench Hard. GP.
- **R6-IMPL** Extended-thinking condition runner. GP. Blocked by T4.6b.
- **R6-GATE** Thinking-on vs. thinking-off aggregate on HealthBench Hard. GP.

### Phase V (voice) — new
- **V1-IMPL** `scripts/voice_sse_endpoint.py` — FastAPI OpenAI-compatible SSE endpoint wrapping clinical fast-path. GP-WT. Blocked by R4-IMPL (skill) + T4.7a.
- **V1-GATE** p95 latency <= 4 s across 20 queries. GP. Blocked by V1-IMPL.
- **V2-CONFIG** `voice/elevenlabs-agent.yaml` — agent config per ElevenLabs docs (verify docs at implementation time). GP.
- **V3-DEMO** Recorded 20-second clip, stopwatch-verified latencies. HUMAN + GP. Blocked by V2-CONFIG.

### Phase T (clinical extension) — additions
- **T-CARD** `docs/opus47-baseline-card.md` + README card section. Fetch Opus 4.7 model card numbers verbatim; record URL + timestamp; populate §5 of this doc. GP + WebFetch (user-confirmed URL). Blocked by — (safe now).
- **T-README** README rewrite with card section, one-liner lead, dual-target framing. GP. Blocked by T-CARD, P4 (thesis), D2.

### DAG update
Phase B and Phase R run in parallel with Phase T after Phase P completes. Phase V gates on R4-IMPL (skills) landing green. T-CARD is safe to start now (unblocks README shape).

---

## 7. Budget update (extends spec §7)

| Task | Delta cost | Notes |
|---|---|---|
| B2 MedQA run | ~$8 | 12.7k MCQ x ~$0.0006 |
| B3 PubMedQA | ~$2 | 1k Q x tiny tokens |
| B4 MMLU-Medical-6 | ~$5 | ~3k questions aggregate |
| R1 MedlinePlus | ~$2 | free API; retrieval-context tokens |
| R2 PubMed | ~$3 | free API; retrieval-context tokens |
| R4 Skills | $0 | already in T4.7 budget |
| R5 Self-critique | ~$50 | doubles T4.7 token cost |
| R6 Extended thinking | ~$30 | thinking tokens billed |
| V1-V3 ElevenLabs | ~$20 | free tier + small topup |
| T-CARD | $0 | pure doc work |

**New total cap: $280** (original $160 + $120 SOTA additions). Hard stop regardless of progress.

---

## 8. Standing rules (updates to spec §8)

All original rules apply. Additions:

- **No technique ships without a measured delta on a Phase B scorer.** If it doesn't move a number, it doesn't appear in the demo, even if it "feels better" in spot-checks.
- **MedQA and MMLU-Medical are null-result controls.** Harness not expected to move closed-book knowledge recall beyond noise (±0.01). If it does, investigate for leakage before reporting.
- **Voice is the bow.** If V1 p95 > 4 s, cut V entirely — do not compromise the dialectic contract to save latency.
- **Claude Opus 4.7 card numbers must be direct quotes.** No computed aggregates. No backfill from related models. "Not reported" is a valid value.
- **RAG cite-before-claim.** Any factual clinical claim in the harness's output must either cite a retrieved source (R1/R2) or carry a "no citation — claim is model-recall" flag.

---

## 9. Re-verification pointers

Re-check before quoting on camera or in the submission README:

| Fact | Source | Re-verify via |
|---|---|---|
| HealthBench Hard baselines (GPT-5/5.1/5.2, Grok 3, Gemini 2.5 Pro, Claude 3.7 Sonnet) | OpenAI simple-evals README | clone + read |
| MedAgentBench leader (Claude 3.5 Sonnet v2, 69.67%) | Stanford ML Group leaderboard, NEJM AI publication | fetch leaderboard |
| Opus 4.7 medical-benchmark scores | Anthropic Claude Opus 4.7 launch page | T-CARD executed 2026-04-21 — all rows "not reported"; see `docs/opus47-baseline-card.md` |
| ElevenLabs SSE endpoint shape | platform.elevenlabs.io conversational-AI docs | fetch docs (V2) |
| Anthropic Skills spec details | platform.claude.com Skills docs | fetch docs (R4) |
| Anthropic extended-thinking API | platform.claude.com docs | fetch docs (R6) |
| NCBI E-utilities rate limits | ncbi.nlm.nih.gov/books | fetch docs (R2) |
| MedlinePlus Connect API | medlineplus.gov/connect | fetch docs (R1) |

---

## 10. Claude Opus 4.7 operational constraints (2026-04-21)

Derived from the Opus 4.7 launch page (user-shared in-session, 2026-04-21). These shape how the runners and harness call the model. Most are enforced-by-absence today; two open items are flagged.

### 10.1 API compliance (hard errors on violation)

| Parameter | Status in Opus 4.7 | Prism enforcement |
|---|---|---|
| `temperature` | 400 error on non-default | not passed by any runner — AST-verifiable |
| `top_p` | 400 error on non-default | not passed |
| `top_k` | 400 error on non-default | not passed |
| `thinking.budget_tokens` | 400 error | adaptive thinking only; budget field never set |

### 10.2 Thinking behavior

- **Adaptive thinking** is the only supported thinking-on mode.
- **Off by default.** Requests without a `thinking` field run without thinking.
- **Thinking content omitted by default.** To surface summaries (useful for delta-report evidence and PoC pre-conditions), set `thinking: {"type": "adaptive", "display": "summarized"}`.
- **Prism default**: baseline runners leave `thinking` off (closed-book MCQ does not need it). The harness coordinator may opt in to `adaptive` + `display: "summarized"` when T4.7a ships, so the delta report can cite reasoning traces when a case flips.

### 10.3 Tokenizer + budget

- New tokenizer: up to 1.35× text→tokens vs Opus 4.6. Runners budget `max_tokens=128000` with headroom; cost ceilings account for the upper end.
- 1M context window at standard pricing; 128k max output.

### 10.4 Effort levels

- New `xhigh` top level. Anthropic recommends `xhigh` for coding/agentic; minimum `high` for intelligence-sensitive work.
- **Prism baseline runners**: `effort="high"` (single-turn MCQ/rubric grading).
- **Prism harness coordinator (T4.7a)**: `effort="xhigh"`. The five-agent adversarial dialectic is the intelligence-sensitive inner loop.
- (Managed Agents handles effort automatically — the harness coordinator session does not need to pass `effort`.)

### 10.5 `task-budgets-2026-03-13` beta

- Advisory per-agentic-loop token cap. Minimum 20k. Beta header `task-budgets-2026-03-13`.
- **Prism stance**: defer to Phase V (post-T4.7b observation). If harness sessions run over the $100 sweep budget, add `output_config: {"effort": "xhigh", "task_budget": {"type": "tokens", "total": <N>}}` + beta header to `scripts/harness_runner.py`. Do not speculate on a number before we have real session cost traces.

### 10.6 Real-time cybersecurity safeguards

- Opus 4.7 may refuse requests that involve prohibited or high-risk cybersecurity topics.
- **Prism kernel rail** performs security research against open-source GPU kernels under authorized disclosure — exactly the legitimate-security-work case Anthropic points to the Cyber Verification Program to cover: `https://claude.com/form/cyber-use-case`.
- **Action**: if the kernel-rail sweep (T4.7b, when live) surfaces refusals on the attacker or synthesizer agent, submit the Cyber Verification application before re-running. Document the outcome in `docs/disclosure-playbook.md`.

### 10.7 Behavior changes that affect our prompts

- **More literal instruction following** — remove hedged scaffolding from agent system prompts; write direct, specific instructions.
- **Fewer tool calls by default** — `effort: xhigh` is the lever to raise tool usage on the coordinator; agent-specific prompts should name the exact tools expected.
- **Fewer subagents spawned by default** — when the coordinator is a session with `callable_agents`, name each expected callee explicitly in the coordinator system prompt.
- **Thinking/progress updates** come for free; remove any "emit interim status" scaffolding from existing prompts.

### 10.8 What this means for the card

The Opus 4.7 launch page emphasized agentic capability and infrastructure (context, thinking, effort, budgets, tokenizer, vision, cybersecurity) — not medical benchmarks. `docs/opus47-baseline-card.md` records every expected medical row as `not reported`, sourced to the launch page + fetch date. Prism's clinical extension therefore establishes the first public Opus 4.7 scores across the full suite, not a single headline number.
