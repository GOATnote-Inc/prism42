# Voice — post-hackathon roadmap

Append-only backlog of work that is genuinely useful but **deferred** so
the active iteration loop (live attestation → fix displayed text + voice
response → re-attest) stays unbroken. Each item has a *trigger* —
something concrete that makes it the right next move. Until the trigger
fires, leave the item here.

Order is rough leverage / blast-radius, not priority. Promote to a
real cycle when a trigger fires; do **not** preemptively scope.

---

## R1 — Geocoded address echo (Nominatim / OSM)

**Problem.** Today the address echo is a regex passthrough of the STT
transcript ("Two hundred oceanfront avenue"). When STT mishears, the
echo also mishears. There is no canonical-form normalization, no
cross-street, no lat/lon for CAD dispatch.

**Approach.** Self-hosted Nominatim + OSM extract for the deployment
region. Async lookup hook between FSM `address_text` latch and the
`confirm_address` template emit. Geocode result returns canonical
address + lat/lon + confidence score. High-confidence: echo canonical
("I have you at 200 Oceanfront Avenue, near Cedar Street — is that
right?"). Low-confidence: fall back to the verbatim regex echo we
ship today.

**Trigger.** Any of:
- A real CAD/dispatch system needs lat/lon (we are no longer in pure
  voice-demo land).
- Address-echo accuracy becomes the gating issue in live attestation
  (multiple mishears per session, not isolated incidents).
- The deployment region narrows to one PSAP we can pre-extract OSM
  for in <1 GB.

**Effort.** ~1 day. Docker container for Nominatim, OSM region extract,
Redis cache layer, FSM hook (~30 LOC), template rewrite.

**Why deferred today.** Current iteration is voice/text fidelity on the
demo path. Maps integration doesn't help with FSM cadence, dispatcher
phrasing, or transcript completeness. It is a layer that *uses* the
correct passthrough, not one that fixes the passthrough.

---

## R2 — Critic eval timeout investigation (Opus 4.7 vs 750 ms)

**Problem.** Cycle-2BC critic eval re-run on 100 fixtures with the
correct API key returned 100% timeouts at the 750 ms budget. Opus 4.7
inline-critic latency exceeds the budget consistently. Without
actionable critic output the eval is dark.

**Approach.** Pilot with budget=3000 ms, n=10 fixtures. Measure p50/p95
of actual Opus 4.7 critic-call latency. If p95 < 3000 ms, ship the
larger budget for the off-path eval (the budget only matters for the
inline-fusion path; the eval can afford to wait). Also try Sonnet 4.6
as the critic — it is faster and the rubric work is well within its
capability per cycle-2BC plan.

**Trigger.** Phase-3 perception fusion gate (R5) is the consumer of
the critic eval. When R5 is being scoped, R2 must land first.

**Effort.** ~2 hours. One-off pilot run, write up findings, update
`cycle2BC_critic_eval/` interpretation framework.

---

## R3 — Cycle-2D5-C: KQ-loop on STT mishear

**Problem.** From cycle-2D5 plan, parked. When the caller answers a
key question with apparent gibberish ("Uh it's honest." was likely
"chest"), the FSM doesn't latch progress, the anti-repetition guard
doesn't fire fast enough, and the dispatcher re-emits the same KQ
on consecutive turns. User attested this in the 2026-04-26 1:09 PM
screenshot (turn 4 + turn 5 dispatcher both said "Where is the bleeding,
and how heavy?").

**Approach.** Two options:
- (a) Anti-repetition: after 1 verbatim re-emit of the same KQ on
  consecutive turns, the FSM rephrases via LLM with the constraint
  "do not repeat the previous question verbatim, ask the same intent
  differently." Touches the response gate's KQ path.
- (b) Hedge detector: extend the classifier to flag low-confidence
  caller utterances (Deepgram confidence < 0.7, OR utterance is
  syntactically broken). When flagged, the FSM emits a structured
  observation prompt instead of re-asking the same KQ. (Ties to R6.)

**Trigger.** Live attestation surfaces a repeat-question scenario
(again). Currently no signal that today's KQ logic is the dominant
failure mode.

**Effort.** Option (a): ~2 hours. Option (b): ~half day.

---

## R4 — Defensive transcript completeness

**Problem.** The earlier 1:09 PM session had caller turns missing from
the transcript pane (only 1 caller row visible despite 4 dispatcher
emits). Subsequent sessions look fine. Hypothesis: when LiveKit's
turn-detector doesn't commit a turn (very short utterance, trailing
off, interrupted), `on_user_turn_completed` doesn't fire, and the
worker never calls `publish_turn`. The caller_partial event fires
but is cleared on next turn.

**Approach.** When `caller_partial` fires with `is_final=True` and
no `publish_turn` has fired within ~2s, manually publish a synthetic
`turn` event so the caller's text surfaces in the transcript even
when LiveKit didn't commit a full turn. Preserves the "all user
statements transcribed" contract the user explicitly asked for.

**Trigger.** Live attestation surfaces another missing-caller-turn
scenario. If today's sessions stay clean, defer indefinitely — this
is a defense-in-depth fix without a confirmed reproducer.

**Effort.** ~3 hours. Worker-side timer + dedup logic, no FSM change.

---

## R5 — Phase-3 perception fusion

**Problem.** Cycle-2C Phase-1 ships the shadow classifier (observed,
not fused). Phase-2 ships the Claude critic eval (off-path scorer).
Phase-3 fuses classifier output into the FSM's intent decision when
classifier-FSM disagreement exceeds a threshold. Currently dark.

**Approach.** Per `cycle2BC_critic_eval/team-b-critic/interpretation-framework.md`,
ship `PRISM42_ENABLE_CLASSIFIER_FUSION=1` only when:
1. `state_mismatch_rate >= 0.05` in eval data
2. Critic latency p95 < 500 ms
3. Critic refusal rate < 2%
4. Top-K disagreements include classes the existing R3 fixes don't
   cover
5. No `risk_flag=high` cases that recommend an action the FSM gate
   would over-rule

**Trigger.** R2 (eval running) lands AND ≥ 4/5 fusion-readiness
criteria are green.

**Effort.** ~half day implementation + ~half day soak.

---

## R7 — Breathing-verify question + non-arrest answer handling

**Problem.** User-flagged 2026-04-26 16:05: the binary template "Are
they breathing normally, or only gasping?" doesn't accommodate
several real caller answers — "I don't know," "wheezing," "asthma,"
"struggling," "shallow." The FSM has no quality category for
*labored-but-alive* (between 'normal' and 'agonal'). Result: caller
loops on VERIFY_BREATHING until the cycle-2D6 force-advance fires.

**Approach.**
1. New `breathing_quality='labored'` value. Patient is alive but
   distressed. Routes to KEY_QUESTIONS (not CRITICAL_CPR).
2. Extend the answer-detector regex for "wheez\w+", "asthma", "labored",
   "shallow", "struggling", "I don't know" → 'labored' or 'unknown'.
3. Consider rewording VERIFY_BREATHING template with structured
   observation per Missel et al. 2023 ("Look at their chest — is it
   rising and falling?"). Open-ended, catches more answer shapes.

**Trigger.** Live attestation surfaces a wheezing / asthma / "I don't
know" loop. (No live signal yet beyond user's hypothesis.)

**Effort.** ~half day. Requires physician sign-off (CLAUDE.md §10) on
both the new breathing_quality value semantics AND any template
re-wording.

---

## R6 — Hedged-answer escalation (Missel et al. "look-listen-feel")

**Problem.** Per cycle-2D4 research (Missel et al. 2023, *Prehospital
Emergency Care*): callers who hedge ("kind of breathing", "sort of
conscious", "I think so") are routinely misclassified by yes/no probes.
Structured physical-observation prompts ("look at their chest — is it
rising and falling?") yielded 100% recognition (19/19) vs lower rates
with yes/no.

**Approach.** Extend the classifier to flag hedged caller utterances
(regex: `\b(kind of|sort of|i think|maybe|might be|sort|kinda)\b`).
When flagged on a VERIFY_BREATHING or VERIFY_SURFACE turn, emit a
structured-observation template instead of repeating the binary
question.

**Trigger.** Live attestation surfaces a hedged-answer failure (caller
answers "kind of breathing" → FSM treats as ambiguous → loops). If
no live signal, defer.

**Effort.** ~half day. New regex + new templates + physician sign-off
on the observation prompt phrasing (CLAUDE.md §10).

---

## Discipline

- **Append, don't reshape.** Promoting an item out doesn't reorder the
  others. Mark `STATUS: SHIPPED IN cycle-XX` rather than deleting.
- **Triggers, not dates.** A trigger is a real signal we're now blocked
  *by* the deferred item. Without a trigger, leave it parked.
- **Don't accumulate beyond one screen.** If this doc grows past 6-8
  items, bias toward shipping or deleting.
