---
title: PSAP agent topology
scope: the 20-agent stack (6 existing benchmarked + 14 new PSAP-specific), their phase state machine, and the coordinator decision tree
audience: engineers wiring sessions, physician reviewing escalation paths, safety auditors
date: 2026-04-23
---

# PSAP agent topology

## 1. Stack overview

Twenty agents, four tiers. Every live call touches 6–8 of them
concurrently; the remaining agents run post-session or on governance
triggers. All on `claude-opus-4-7` unless noted; async rubric grader
uses the SOTA non-Anthropic model for cross-vendor independence (no
self-grading on load-bearing decisions — the HealthBench Hard discipline
applied to live calls).

### Tier A — Voice-facing (phase-based; one holds mic at a time)
```
  psap-intake  →  psap-triage  →  psap-dispatch  →  psap-pdi  →  psap-handoff
     │               │                │               │             │
     └ first 30 s    └ key questions  └ CAD entry     └ instructions └ close/transfer
```
All stream caller-facing text to ElevenLabs. All emit a structured
turn record per `schemas/psap-turn.schema.json`.

### Tier B — In-session oversight (parallel to Tier A; every turn)
```
  psap-safety-monitor   ─┐
  psap-ohca-detector    ─┼─ subscribe to every turn; emit alerts
  psap-intent-verifier  ─┘
  psap-rubric-live      ──── grades each dispatcher turn (GPT-5.5 preferred)
```
None stream to ElevenLabs. All emit structured output only. Fast + cheap.

### Tier C — Post-session (run once per call, after session closes)
```
  psap-auditor       ─── invokes the existing 6-agent dialectic over the call transcript
  psap-qi-reviewer   ─── consolidates into a physician-readable 200-word summary
```
Produces `findings/public-demo/<session_id>/verdict.json` + `qi-summary.md`.

### Tier D — Orchestration (glue + governance)
```
  psap-team-coordinator      ── decides which Tier A agent holds the mic
  prism-ci-safety-expert     ── reviews every GitHub commit
  prism-release-gate         ── pre-deploy go/no-go
```

### Tier E — Existing benchmarked (reused by psap-auditor)
```
  prism-coordinator + prism-defender + prism-attacker + prism-synthesizer + prism-executor + prism-adjudicator
```
No new registration. `psap-auditor` invokes these via the existing skill
bindings — the continuity claim the pipeline narrative depends on.

---

## 2. Phase state machine (Tier A)

```
                  ┌──────────────────────────────────────────────────────┐
                  │                    SESSION OPEN                       │
                  └─────────────────┬────────────────────────────────────┘
                                    │ caller connects, disclaimer ticked
                                    ▼
                  ┌──────────────────────────────────────────────────────┐
                  │ psap-intake                                            │
                  │ goal: address + chief complaint + caller state          │
                  │ exit: {address_confirmed, chief_complaint_family,       │
                  │        caller_state}                                    │
                  └────────┬─────────────────────────────────────┬─────────┘
             address unconfirmed after 3 attempts     exit condition met
                         (escalate to supervisor)              │
                                                               ▼
                  ┌──────────────────────────────────────────────────────┐
                  │ psap-triage                                            │
                  │ goal: key-question flow → GEDP determinant + severity │
                  │ exit: {determinant_code, severity, dispatch_required} │
                  └────────┬─────────────────────────────────────┬─────────┘
              caller becomes unresponsive            exit condition met
              (jump directly to psap-pdi for CPR)              │
                                                               ▼
                  ┌──────────────────────────────────────────────────────┐
                  │ psap-dispatch                                          │
                  │ goal: CAD record + unit manifest + ETAs                │
                  │ exit: {cad_record_finalized, units_en_route}           │
                  └────────┬─────────────────────────────────────┬─────────┘
                           │                                     │
                           ▼                                     ▼
          (non-PDI dispatches — no instructions needed)   (PDI applicable: CPR,
                           │                               choking, bleeding, etc.)
                           │                                     │
                           │                                     ▼
                           │                ┌──────────────────────────────────┐
                           │                │ psap-pdi                          │
                           │                │ goal: deliver GEDP-v0.1 script    │
                           │                │ exit: {pdi_delivered,             │
                           │                │        caller_confirmed_steps}    │
                           │                └────────┬─────────────────────────┘
                           │                         │
                           ▼                         ▼
                  ┌──────────────────────────────────────────────────────┐
                  │ psap-handoff                                           │
                  │ goal: close or transfer                                │
                  └──────────────────────┬───────────────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────────────┐
                  │                   SESSION CLOSED                      │
                  └─────────────────────┬────────────────────────────────┘
                                        │
                                        ▼
                                  psap-auditor runs
                                  psap-qi-reviewer runs
```

**Non-linear transitions**:

- Any phase → `end` if session-budget-exceeded or real-emergency-detected or kill-switch
- `psap-intake` → `psap-pdi` directly if caller reports active arrest and address is already captured (bypass triage for life-over-paperwork)
- `psap-triage` ↔ `psap-intake` if address becomes uncertain mid-KQ
- `psap-pdi` → `psap-handoff` on: caller completes instructions · patient recovers · units arrive
- `psap-dispatch` → `psap-triage` if new information invalidates the determinant

All transitions are logged by `psap-team-coordinator` with {trigger, source_turn, target_agent, reason}.

---

## 3. Coordinator decision tree (Tier D)

`psap-team-coordinator` owns the mic. On every alert from Tier B, it
decides:

```
alert arrives → classify by kind → apply priority rubric:

  real-emergency-claimed (critical)    → END session immediately
  ohca-signal prob>0.6 (critical)      → hand mic to psap-pdi for CPR
  caller-distress-crossed (high)       → inject psap-safety-monitor utterance, stay with current agent
  contraindicated-instruction (high)   → override current agent's stream with safe fallback + psap-pdi re-delivers
  phi-detected (high)                  → inject refusal template SP-003; continue session
  intent-ambiguous (medium)            → hand mic to current agent with {ask_clarifying: true} flag
  verify-failed (medium)               → substitute safe-message stub + retry current agent once
  latency-breach (low)                 → log; if repeated, trip circuit breaker
```

If two alerts arrive in the same turn, the higher-severity wins; ties
resolve by order: real-emergency > ohca > contraindicated > phi > other.

---

## 4. Structured-output contract (frontier-lab gate)

Every agent emits per `schemas/psap-turn.schema.json`. Required fields:

- `agent`, `turn_id`, `action`, `rationale`, `cites`, `confidence`,
  `confidence_basis`, `self_verify`.
- `content` required when `action="speak"`; otherwise null.
- `refuse` required when `action="refuse"`.
- `next_phase` required when `action="handoff"`.

**The hard gate**: before the caller-facing `content` streams to
ElevenLabs, the coordinator verifies `self_verify.all_passed === true`.
If false, the stream is blocked, a pre-approved safe message is
substituted, and the safety-monitor decides recovery.

This is the frontier-lab principle applied: nothing the caller hears
bypasses the structured verification record. Free-form prose is not
the load-bearing output; the JSON is.

### Streaming architecture

ElevenLabs custom-LLM expects OpenAI-compatible SSE with streaming
text content. We satisfy this as follows:

```
(1) voice-facing agent receives input from coordinator
(2) coordinator injects SP-001 through SP-010 preambles + the agent's
    role-specific prompt + knowledge-pack excerpts per cites[]
(3) agent generates a response in TWO PARALLEL channels:
    · text chunks streamed to ElevenLabs SSE as {delta:{content:"..."}}
    · a final structured turn-record emitted on session close
(4) coordinator inspects the turn-record's self_verify.all_passed
    · true  → let the streamed chunks play
    · false → interrupt TTS at next turn boundary, inject safe-message,
              escalate to safety-monitor
```

The ~500 ms latency cost of structured emission is acceptable for
safety-gated healthcare dispatch. The Phase V rule (cut at p95 > 4 s
end-to-end) remains in effect.

---

## 5. Independent verification (psap-rubric-live)

Parallel to the voice-facing agent, `psap-rubric-live` receives the
same input + the agent's output and produces a rubric score against 5
GEDP-aligned criteria:

1. **Clinical accuracy** — does the response match GEDP v0.1 +
   AHA BLS 2025 content for the given complaint + patient age?
2. **Scope adherence** — does the response stay within dispatcher
   authority (no diagnosis, no prescribing, no out-of-scope advice)?
3. **Safety preservation** — no blind finger-sweep, no blind
   medication dosing, no "move the patient" advice for suspected
   spinal injury, etc.
4. **Clarity for caller** — instructions are in plain language at
   8th-grade reading level; no jargon without definition.
5. **Protocol adherence** — phase transition follows GEDP §3 state
   machine; caller-facing text matches the phase's allowed intents.

`psap-rubric-live` runs on a SOTA non-Anthropic model (GPT-5.5 preferred,
GPT-5.4 fallback) to preserve cross-vendor independence. Grades stream
to the dispatcher UI as they complete (2–4 s behind real-time) and
are logged for per-call QI review.

This is "the harness does not grade itself" applied to live calls.

---

## 6. Governance tier

### `prism-ci-safety-expert`
- Triggered by every GitHub push or PR.
- Inputs: diff, current manifest, last audit verdict.
- Output: `{"status": "pass"|"fail", "findings": [...], "suggested_fixes": [...]}`
- Self-verify: every finding cites a file:line and a specific rule
  (GEDP section, pre-commit hook pattern, schema constraint, safety
  preamble). Failures without a cited rule are themselves a failure.
- Posts as a GitHub PR comment. Blocking for merges to main.

### `prism-release-gate`
- Triggered pre-Vercel production deploy.
- Checks: agent manifest matches registered IDs; safety preamble
  intact in every voice-facing agent; Turnstile active; rate limits
  configured; budget alarms wired; last CI-safety-expert status is pass.
- Output: `{"status": "go"|"hold", "checks": [...]}` — each check has a
  runtime verify command included.

---

## 7. Registration + deployment plan

Landing order:

1. **Phase 1a (this commit series)**: schemas + safety preambles + topology +
   three anchor agents (psap-intake, psap-safety-monitor, psap-rubric-live).
2. **Phase 1b (next)**: the remaining 4 voice-facing agents (triage, dispatch,
   pdi, handoff) + `psap-team-coordinator` + `scripts/register_psap_agents.py`.
3. **Phase 2**: dispatch protocol v0.1 expanded to 20+ chief complaints (currently
   Phase 1b has 5 anchor complaints).
4. **Phase 3**: Vercel frontend app (`mvp/911-console-live/`).
5. **Phase 4**: CI safety-expert GitHub Action; release-gate Vercel hook.
6. **Phase 5**: post-session agents (auditor, qi-reviewer) wired to real
   session log store.

Each phase passes the verify-all gate before the next starts.

---

## 8. Cross-agent communication pattern

All agents write/read from a single session store (Vercel KV or a
managed session store per Anthropic's platform). Keys:

```
session:<id>:state              → phase, active agent, coordinator stamps
session:<id>:turns              → ordered list of turn records
session:<id>:alerts             → ordered list of alerts emitted by Tier B
session:<id>:rubric             → per-turn grades from psap-rubric-live
session:<id>:budget             → remaining time, remaining turns, remaining $
session:<id>:refusals           → refusal events with timestamps
```

No agent reads another agent's output directly; all pass through the
coordinator or the shared store. Debug-level inter-agent chatter is
logged but never streamed to the caller.

---

## 9. Fail-closed defaults

On any ambiguity — a missing self-verify block, an unparseable turn
record, a timeout — the system fails CLOSED:

- The coordinator substitutes the safe-message template.
- The voice-facing agent is halted for the turn.
- The safety-monitor receives an `unknown-failure` alert.
- The session continues to the next turn if the safety-monitor clears,
  else the session closes gracefully.

The caller is never left without a response; the agent is never
allowed to hallucinate under time pressure.
