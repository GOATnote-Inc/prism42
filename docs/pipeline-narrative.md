---
title: Prism42 — full-stack trust-and-performance pipeline
scope: the four stages and the evidence each produces, plus how the stages compose into the 911 call-center narrative
audience: reviewers, partners, PSAPs evaluating the stack, engineers onboarding into any one layer
date: 2026-04-23
---

# Prism42 — full-stack trust-and-performance pipeline

## One-paragraph thesis

Prism42 turns frontier agents into deployable high-stakes systems by proving
three things before the demo runs: they are **correct**, **fast**, and
**clinically safer than baseline**. The pipeline has four stages that
compose into a single deployable stack. Every stage ships a runnable
artifact, not an aspiration — a compiled PoC on real GPU hardware, a
measured latency with full p50/p95/p99 distribution, a paired rubric
delta whose 95 % CI excludes zero, and a managed-agent stack that
handles live voice calls end-to-end. The final stage takes the audited,
measured, rubric-graded agents and packages them into a 911 call-center
simulation: the public interacts with the same agents whose correctness,
performance, and clinical lift were measured in the first three stages.
That continuity is the credibility mechanism.

## The four stages

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  1. FIND        │───▶│  2. OPTIMIZE    │───▶│  3. PROVE       │───▶│  4. DEPLOY      │
│ correctness     │    │ the compute     │    │ clinical-       │    │ the agent       │
│ failures at     │    │ path            │    │ reasoning lift  │    │ stack           │
│ kernel layer    │    │                 │    │                 │    │                 │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │                      │
         ▼                      ▼                      ▼                      ▼
  executed PoC on        measured latency       paired HBH-Hard         live agents, rubric-
  real hardware          with full distrib.     delta, CI excl 0        graded per turn, QI
                                                                        loop in minutes

                                           ┌──────────────────────────────────────┐
                                           │  5. PACKAGE INTO 911 NARRATIVE        │
                                           │  www.thegoatnote.com/prism42          │
                                           │  public interacts with the benchmarked│
                                           │  agents — live call, dispatcher view  │
                                           └──────────────────────────────────────┘
```

---

### Stage 1 — Find correctness failures at the kernel layer

**Question answered**: does the kernel produce numerically correct outputs
under adversarial input?

**Method**: five-role adversarial dialectic (defender / attacker /
synthesizer / executor / adjudicator, coordinated) targeting open-source
attention and MLA-decode implementations on flagship NVIDIA hardware.
Defender asserts an invariant; attacker crafts a counterexample;
synthesizer packages a reproducer; executor compiles and runs on real
H100 / B200; adjudicator scores against the executed exit code plus
cross-checks.

**Hard rule**: every finding ships with a proof — a PoC that exits with
`VIOLATION: <invariant_id>` on real hardware. No speculative findings.
See `CLAUDE.md` §4 ("Verification discipline — the hard rule").

**Artifacts**: verdict JSON (case-id, run-id, verdict, severity,
cross-checks, rationale), PoC log, invariants manifest. Synthetic
regression fixture at `corpus/golden-cases/KERNEL-GOLDEN/` exercises the
whole L3 verification layer without needing a real vendor finding.

**Why this is hard**: the "AI-slop vulnerability report" counter-pattern.
Unvalidated LLM vulnerability reports have gotten authors banned from
curl and the Linux kernel. Prism42's hard gate (L1–L5 verification
layers; exit-0 proves the claim) is the answer. See
`scripts/validate_artifacts.py` + `schemas/verdict.schema.json`.

**Evidence this layer is real**: the existing 6 managed agents
(`prism-coordinator` + 5 dialectic roles, all on `claude-opus-4-7`)
are live in the workspace. 9 agent skills bound. Session stream
end-to-end green. See `agents/manifest.yaml`.

---

### Stage 2 — Optimize the compute path

**Question answered**: how fast does the kernel run, and what is the
measurement rubric?

**Method**: clean-process measurement discipline — fresh subprocess per
run, 200 CUDA-event samples, 3 replicates, std/mean ≤ 5 %, full
distribution (p10 / p50 / p90 / p99), compile cost reported alongside
steady-state. Reproducibility pinned by git SHA + GPU UUID + clocks.
Any performance claim that can't cite a rubric-compliant session_id
is treated as inconclusive.

**Hard rule**: no performance claim without a logged session artifact.
The "AI-slop benchmark number" counter-pattern is addressed by requiring
every reported latency to trace back to a specific
`mla/results/logs/isolated_bench_*.jsonl` record that reproduces on
request.

**Artifacts**: per-run JSONL with full distribution, summary JSON with
{mean, p50, p95, p99, compile_cost}, attached `ralph_decisions.jsonl`
capturing which autotune parameters were explored. Evolutionary search
discipline in `mla/` (two-tier validator + Pareto loop + six
benchmark-gaming detectors).

**Why this is hard**: benchmark numbers in the kernel community are
frequently gamed — trivial delegation to a reference implementation,
cached compilation, missing variance reporting. Six detectors in
`mla/prism/gaming_patterns.py` catch the most common patterns.

**Anchor claim**: see `mla/results/logs/` for the current measured p50
attention-forward latency at kv=4096 on H100 SXM5 (self-reported with
rubric-compliant session_id; reproducible with
`mla/scripts/isolated_bench.py`).

---

### Stage 3 — Prove clinical-reasoning lift

**Question answered**: does the managed-agent stack produce better
clinical reasoning than stock Opus 4.7 on a published benchmark?

**Method**: HealthBench Hard (OpenAI simple-evals, Apache 2.0, vendored
at `third_party/simple-evals/`) as the primary rubric grader. Baseline
= mean of N ≥ 3 independent Opus 4.7 runs. Harness delta = paired
comparison on the same subset, same day. Gate: paired mean Δ's 95 % CI
excludes 0 at α = 0.05. Null-result controls on MedQA + MMLU-Medical-6
(`|Δ|` must be small). RAG validator PubMedQA (lift ≥ 10 pp before any
R1/R2 technique ships).

**Hard rule**: no technique ships without a measured delta on a Phase B
scorer. See `CLAUDE.md` §4 ("Benchmark discipline"). Paired design
cancels per-example sampler variance; both arms see the same Opus 4.7
noise. Absolute-|Δ| gates on two independent baseline runs fight the
variance instead of cancelling it — that's the lesson from T4.6c/d.

**Landed baseline**: Opus 4.7 HealthBench Hard = `0.196 ± 0.068`
(mean of N = 3 runs, 95 % CI half-width, 30-example subset). First
public Opus-4.7 HealthBench Hard number. Canonical 1000-example parent
pinned via `corpus/pins/healthbench-hard-1000.yaml` (dataset_id, split,
SHA256, field selection, verify command).

**Why this is hard**: published clinical benchmarks are susceptible to
contamination (model saw items at training time) and grader drift
(rubric changes between runs). The paired-design gate addresses the
first (both arms see contamination equally); the pinned grader
(vendored simple-evals at a specific commit) addresses the second.

**Physician-in-loop**: every rubric card carries a `physician_review`
field that only a human physician can set. Code never pre-signs it.
Enforced by `scripts/validate_artifacts.py` L1 schema check.

---

### Stage 4 — Deploy the agent stack

**Question answered**: can the audited, measured, rubric-graded agents
handle a live voice call end-to-end with the same verification
discipline?

**Method**: ElevenLabs Conversational AI custom-LLM front end over the
Managed Agents session layer. Opus 4.7 with `thinking: off` by default
for voice-latency (Phase V rule: cut at p95 > 4 s). Safety preamble in
the translator layer, not ElevenLabs-side. Async rubric grader (SOTA
model — GPT-5.5 or Opus 4.7) on a parallel session, 2-4 s behind
real-time, publishes per-turn grades to the dispatcher UI. Buffer-word
pattern `"... "` keeps TTS flowing during slow LLM turns.

**Hard rule**: the live-voice stack is rubric-graded per turn. Every
public demo call produces a structured post-call verdict from the same
dialectic that audits kernels — `psap-auditor` wraps the benchmarked
6 agents around the call transcript after the session ends, and
publishes the verdict at `findings/public-demo/<session_id>/verdict.json`.

**Agent topology**: see `agents/topology.md` (to be landed). Live-call
voice-facing agents are phase-based (intake → triage → dispatch → PDI
→ handoff). In-session oversight agents (safety-monitor,
ohca-detector, intent-verifier, rubric-live) run in parallel on every
turn. Post-session agents (auditor, qi-reviewer) produce the quality
artifact. Governance agents (ci-safety-expert, release-gate) wrap the
whole lifecycle.

**Why this is hard**: voice-latency budgets (< 1 s to first audio is
"natural", > 4 s is "broken") collide with high-stakes reasoning
demands. The split-brain solution — fast voice-facing agent + async
high-fidelity grader — keeps the call snappy while the evidence stack
still produces rubric-compliant artifacts.

**Clinical trajectory**: Phase 0 synthetic-fixture validation (here) →
Phase 1 IRB pilot → Phase 2 prospective paired pre/post → Phase 3 FDA
SaMD filing. Current stage is Phase 0; all PSAP demo fixtures are
synthetic. No PHI, no real ANI/ALI, no patient data. Physician of
record: Brandon Dent, MD (emergency medicine).

---

## Stage 5 — Package into the 911 call-center narrative

**Where the pipeline becomes a product.**

Public URL: `www.thegoatnote.com/prism42` (Vercel hosting, ElevenLabs
voice front end, Managed Agents LLM back end, Anthropic + OpenAI
behind the same authentication posture).

Visitor experience:
1. Landing: the four evidence tiles from stages 1–4, with live numbers.
2. "Try a simulated 911 call" — caller speaks to the voice-facing
   agent phase stack; the dispatcher console (see `mvp/911-console/`)
   shows everything the call taker would see, from the caller's
   viewpoint.
3. Post-call: the auditor verdict and the physician-facing QI summary
   appear, anchored to timestamps in the caller's own transcript.

Safety gates for the public demo:
- Disclaimer modal every session: "simulation only; if real, call 9-1-1."
- Real-emergency detection in the agent: refuse + redirect + end session.
- No PHI intake; agent refuses real names / addresses / patient IDs.
- Rate limit: 1 call per IP per 10 min, 3-minute session cap, daily IP
  cap.
- Budget cap per session + daily domain cap.
- Transcript logging anonymized (IP hashed, timestamp rounded to hour),
  30-day retention, never shared externally.
- Physician of record visible in footer; "Research instrument. Not FDA
  cleared."

---

## What makes this pipeline different from the incumbents

US PSAP incumbents (Motorola VESTA + Hyper, Axon 911 via Prepared +
Carbyne, Aurelian) all now ship live transcription + translation +
non-emergency offload. None publish a physician-reviewed rubric over
a public clinical benchmark; none compute the MPDS determinant from
the conversation to prevent drift; none gate their agents behind a
paired-design benchmark delta that would survive JAMA-quality review;
none ship with an evidence stack that traces every public claim back
to a runnable artifact.

That gap is prism42's trust story. Every number on the landing page
traces to a session ID. Every session ID reproduces with a shell
command. Every agent the public talks to has an auditor running the
same dialectic that found the kernel bugs.

Correctness begets performance begets clinical lift begets deployment
begets narrative. The pipeline is the product.
