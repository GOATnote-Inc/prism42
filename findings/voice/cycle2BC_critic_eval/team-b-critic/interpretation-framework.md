# Critic eval interpretation framework — pre-staged 2026-04-26

When the eval run lands, these are the questions to answer + how to read
the aggregate JSON before the user sees raw output.

## What the eval produces

Per `critic_eval_harness.py:580+` the run writes:
- `eval-rows.jsonl` — one line per (fixture × turn) with FSM state +
  classifier output + critic score
- `aggregate-metrics.json` — counts + distributions
- `aggregate-metrics.md` — human-readable summary

## Decision rules (read this before fusion)

### Trust-the-critic threshold

If aggregate `state_mismatch_rate >= 0.20` (1 in 5 turns), the critic is
flagging substantial FSM gaps. We should:
- Investigate top-K disagreement classes
- Likely escalate Phase-3 fusion sooner

If `state_mismatch_rate < 0.05` (1 in 20), FSM is in good shape:
- Phase-3 fusion is a defense-in-depth nice-to-have
- Most "perception" disagreements are critic mis-judgments, not FSM bugs

### High-risk-flag triage

Per call: `risk_flag` ∈ {none, low, medium, high}.

- `risk_flag=high` count > 0: investigate EVERY one. Could be safety bugs
- `risk_flag=medium` rate > 10%: prompt-tune the critic OR review the
  scenarios producing them
- `risk_flag=low` rate is informational only

### Cost / latency sanity

- Cost should be roughly $0.03-$0.08 per turn (Opus 4.7 on ~500 token I/O)
- 100 fixtures × ~2-3 turns avg = 200-300 calls = $6-24 total
- Latency p95 should be <750ms per critic call (the timeout)
- Latency p99 hitting 750ms means the timeout is firing: increase OR accept

### Refusal rate

If `claude_critic.refused` count > 5% of calls:
- Anthropic's medical-role refusal rate is biting (per CLAUDE.md research:
  Sonnet 4.6 0.18%, Opus 4.7 0.28% baseline)
- Consider refining the critic system prompt to flag the role more clearly
- Or accept — refused calls log nothing, FSM proceeds normally

## Top-K disagreements review

For the 10 most-common `suggested_correction` strings, print:
- The caller utterance that produced it
- The FSM intent that fired
- Classifier's broad-category intent (if perception data also available)
- The critic's recommended action

Group by recurring patterns:
- "Should reposition before CPR" — Phase 3 fusion will surface this; check
  R3-B3-A coverage
- "Did not acknowledge caller question" — R3-B1-A coverage check
- "Treated backchannel as new turn" — R3-B2-A coverage check
- NEW classes (not yet addressed by R3) — these become next-cycle research
  team inputs

## Fusion-readiness criteria

Before flipping `PRISM42_ENABLE_CLASSIFIER_FUSION=1` in Phase 3, the
eval needs to show:

1. `state_mismatch_rate >= 0.05` — there's meaningful signal to fuse on
2. Critic latency p95 <500ms — fusion can stay within budget
3. Critic refusal rate <2% — the layer is reliable
4. Top-K disagreements include AT LEAST ONE class the existing R3 fixes
   don't cover — fusion adds real value vs being redundant
5. No `risk_flag=high` cases that recommend an action the FSM gate
   would over-rule (i.e., the critic isn't trying to bypass safety
   templates)

If 4/5 criteria fail, defer Phase 3 — fusion would mostly add latency for
marginal accuracy gain.

## How the eval compares to live data

The 100 fixtures are SYNTHETIC. They cover 30 cardiac, 20 trauma, 15
medical, 10 fire, 10 crime, 10 misclassification-likely, 5 direct-question.
The mix is reasonable for beta-testers but skews toward textbook scenarios.

Live unscripted attestation (the user's beta-tester load) will produce a
different mix. Expect:
- More "what's happening" wandering openings
- More STT mishears than fixtures simulate
- More callers asking the dispatcher questions
- More long pauses and backchannels

Plan: after the eval, run the harness AGAIN against a smaller set of
real-attestation transcripts (capturable from worker.log). That second
eval is the "real" calibration; this one is the smoke.

## Pre-staged commit plan

When the eval lands:
1. `git add findings/voice/cycle2BC_critic_eval/team-b-critic/`
2. Commit with: aggregate metrics summary + top-3 disagreement classes
   + cost actual + latency p50/p95
3. Surface to user: did the eval clear all 5 fusion-readiness criteria?
   YES → recommend Phase 3 ship; NO → recommend defer + which gates failed
