# Cycle-2D5 — Dispatch cadence + address echo plan

**Date:** 2026-04-26
**Inputs:**
- User attestation 2026-04-26 (screenshots): three regressions on `/prism42/livekit`
- Team-research findings: `cycle2D4_dispatch_research/team-research/dispatch-patterns.md`
- Team-FSM-inventory findings: `cycle2D4_dispatch_research/team-fsm-inventory/current-state.md`

**Status:** Plan only. No code changes. Awaiting Brandon Dent, MD sign-off (CLAUDE.md §10).

---

## What the user reported

1. **Address didn't show in transcript.** Dispatcher said "Got your address" without echoing the actual address back.
2. **"Help is on the way and I am staying with you" leaves the caller unsure of what to do next.** The caller said "Okay, but what do I do?" right after.
3. **Repeat-question:** turn-4 dispatcher and turn-5 dispatcher both emitted "Where is the bleeding, and how heavy?" — the caller's intervening answer ("Uh it's honest." — likely STT mishear of "chest") didn't advance the FSM.

## What the research says

Three findings from the public dispatch literature converge on the same operator move:

1. **Echo, don't acknowledge.** Public PSAP guidance is uniform: read the address back verbatim and ask the caller to confirm. "Got your address" without the actual address is a documented failure pattern (Sarpy County, Caldwell County, MACC 911, NAEMD curricula). Caller has no way to catch STT mishears, and the address phase never closes — anxious callers re-introduce the address mid-CPR-coaching, derailing the instruction stream. (Potomac drowning case: bare acknowledgment dropped the "in Virginia" clause; responders went to the wrong side of the river.)

2. **Reassurance must be glued to a redirect.** "Help is on the way" alone leaves the caller in the listening role. Trained dispatchers chain three moves in a single turn: (a) status report on dispatch, (b) co-presence ("I'm staying with you"), (c) **immediate first physical action**, expressed as an imperative with a return-token ("…tell me when you've done that"). StatPearls (NIH Bookshelf NBK470543): _"It should be assumed and never asked that they are willing to provide aid. Offering options may discourage participation."_ The shift from interrogative to imperative is the central operator move.

3. **Hedged answers escalate to structured observation, not yes/no re-ask.** Missel et al. 2023 (Prehospital Emergency Care): 100% of cardiac arrests recognized when dispatchers used "look, listen, feel" structured assessment vs. lower rate with yes/no probes. When the caller says "I don't think he's breathing" or "kind of breathing," the FSM should escalate to a structured prompt, not loop on the same yes/no.

## What changes in the FSM

### Bug 1 — address echo (cycle-2D5-A)

Three coupled changes:

**1A.** `dispatcher_fsm.py` — extract the captured address string, not just the boolean. The classifier currently sets `has_address=True` but discards the matched text. Add a new field `Features.address_text: str | None` populated from the regex match span.

**1B.** `DispatcherFSM` state — store the captured address as `self.address_text: str | None`, latched once on first capture (mirrors `address_known`).

**1C.** `templates.py` — replace `confirm_address` with a parameterized template:

```python
"confirm_address": TemplateSpec(
    # 11-13 words depending on address length. Echo + dispatch +
    # explicit confirmation handle, per AHA / NHTSA EMD / APCO P33.
    text="I have you at {address}. Help is on the way.",
    notes="Echoes captured address verbatim. Caller can correct STT mishears.",
    fillers={"address"},  # template-gate fills from FSM.address_text
),
```

The `response_gate.py` already supports filler substitution for `{pronoun_object}` (used in `instruct_choking_back_blows`). Extending the filler dict to include `{address}` is a small typed change. If `self.address_text` is `None` (defensive — should not happen if `address_known=True`), the template falls back to the previous wording.

**Word count:** `"I have you at twelve riverside drive. Help is on the way."` = 12 words. Within the 5-14 constraint.

**Risk:** TTS mispronunciation of the address. Cartesia Sonic-3 handles street names well in our experience, but addresses with unusual spelling ("12 Riverside Dr." vs "twelve riverside drive") may surface mispronunciations. Mitigation: the FSM normalizes spelled cardinals before regex match (lines 367–381 of `dispatcher_fsm.py`); reuse the normalized form in the echo so we read back what the FSM understood, not the raw STT string.

### Bug 2 — reassurance dead-end (cycle-2D5-B)

**The FSM stays one-intent-per-turn.** The fix is to change *what* the deliver-reassurance intent emits, so the single template includes reassurance + co-presence + first imperative + return-token.

The right shape is **complaint-specific reassurance variants**, because the appropriate first imperative differs by chief complaint. Three variants:

```python
# Trauma / bleeding (from trauma key questions, before pre-arrival)
"deliver_reassurance_trauma": TemplateSpec(
    # 13 words. Reassurance + co-presence + imperative + return-token.
    text="Help is on the way. Press hard on the wound — tell me when ready.",
    notes="Trauma redirect. Replaces standalone deliver_reassurance for trauma rail.",
),

# Cardiac (in CRITICAL_VERIFY before T-CPR)
"deliver_reassurance_cardiac": TemplateSpec(
    # 14 words.
    text="Help is on the way. Get them flat on the floor on their back, now.",
    notes="Cardiac redirect. Aligns with INSTRUCT_CPR_REPOSITIONING.",
),

# Medical / general (no specific imperative yet)
"deliver_reassurance_medical": TemplateSpec(
    # 11 words. No specific imperative — keep caller talking instead.
    text="Help is on the way. Stay with me — tell me what's happening.",
    notes="Generic redirect; verbal task assigned ('tell me') keeps caller active.",
),
```

The existing standalone `deliver_reassurance` template is retained as a fallback (when complaint=unknown).

**FSM dispatch logic** (`_intent_in_address_confirmed`, lines 668-678):

```python
# Cycle-2D5-B: complaint-specific reassurance variants.
if self.complaint == "trauma":
    intent = Intent.DELIVER_REASSURANCE_TRAUMA
elif self.complaint == "cardiac" or self.is_cardiac_arrest:
    intent = Intent.DELIVER_REASSURANCE_CARDIAC
elif self.complaint == "medical":
    intent = Intent.DELIVER_REASSURANCE_MEDICAL
else:
    intent = Intent.DELIVER_REASSURANCE  # fallback
self.reassurance_done = True
self.state = State.REASSURANCE_DELIVERED
return self._record(intent, t0)
```

Add three new Intent enum members. All four reassurance variants share the same `reassurance_done` latch — emit any one, latch them all.

**Risk:** template-gate `_SAFETY_TEMPLATE_ONLY` set must be expanded to include the new intents (LLM cannot rephrase safety-critical reassurance). Adds three entries to the frozenset.

**Physician sign-off needed (Brandon Dent, MD):**
- Trauma redirect: is "Press hard on the wound — tell me when ready" the right first imperative for an unknown-trauma context where bleeding location hasn't been asked yet? Alternative: defer the imperative to the *next* turn (KQ_BLEEDING_LOCATION) and use a softer redirect: "Help is on the way. Stay with me — where is the bleeding?" (the question itself becomes the redirect).
- Cardiac redirect: is "get them flat on the floor on their back, now" the right first imperative when surface_confirmed is still False? It pre-empts VERIFY_SURFACE. Alternative: keep VERIFY_SURFACE as the next turn and use a softer redirect: "Help is on the way. I'm staying with you — are they on the floor?" (turning the verification into the redirect).

The "softer" alternatives may actually be more correct: they preserve the FSM's verification-before-instruction discipline while still gluing reassurance to a directive. The first turn after reassurance in either rail already asks a key question — we just need to make sure that question fires on the *same* turn as reassurance, not the next one.

**Recommended (softer) variants:**

```python
"deliver_reassurance_trauma": TemplateSpec(
    # 12 words. Reassurance + redirect (the bleeding location KQ).
    text="Help is on the way. Stay with me — where is the bleeding?",
),
"deliver_reassurance_cardiac": TemplateSpec(
    # 13 words. Reassurance + redirect (the surface verification).
    text="Help is on the way. I am with you — are they on the floor?",
),
"deliver_reassurance_medical": TemplateSpec(
    # 11 words. Reassurance + redirect (verbal task).
    text="Help is on the way. Stay with me — tell me what's happening.",
),
```

These collapse the previous turn-pair (reassurance → KQ) into a single utterance. Saves a turn, removes the dead-air gap.

### Bug 3 — repeat-question after caller answer (cycle-2D5-C)

Separate investigation: why did the FSM emit `KQ_BLEEDING_LOCATION` on turn 4 AND turn 5 when the caller answered "Uh it's honest." between them? Likely a Deepgram mishear of "chest" → "honest" caused the classifier to not match `_RE_BLEEDING_LOCATION` cues, leaving the FSM in trauma-KQ-loop. Anti-repetition guard (line ~840 in dispatcher_fsm.py) should have advanced after one repeat.

**Investigation needed:** read the `_intent_in_key_questions` loop logic + the anti-repetition logic. May not need a code change — could just be the STT mishear surfacing as a real failure. Still worth confirming what the FSM should do when the caller answers a KQ with apparent gibberish: re-prompt? Anti-repeat by skipping forward? Defer to LLM?

This is `cycle-2D5-C`. Lower priority than 2D5-A and 2D5-B since it's STT-driven and harder to reproduce deterministically. Park for now; come back after the address-echo + reassurance-redirect changes have soaked.

---

## Recommended ship order

1. **Cycle-2D5-A (address echo).** Lowest-risk, highest-leverage. Pure template + FSM-state change. No new control flow. Physician review: trivial — just confirms an existing fact to the caller.

2. **Cycle-2D5-B (reassurance + redirect — softer variants).** Requires Brandon Dent, MD sign-off. The softer variants (preserving verify-before-instruct discipline) are recommended over the imperative-first variants.

3. **Cycle-2D5-C (KQ-loop anti-repetition).** Investigate first, then propose. Park.

## Verification plan

- **Unit tests:** new fixtures in `tests/voice/test_cpr_repositioning.py` (rename to `test_dispatch_cadence.py`?) for:
  - "twelve riverside drive" → confirm_address echoes "twelve riverside drive"
  - cardiac latch + reassurance fires once with redirect → expect single turn containing both reassurance and the surface-verification question
  - regression: existing repositioning + breathing-verify tests still pass

- **End-to-end repro on `/prism42/livekit`:**
  1. "Twelve Riverside Drive."
  2. "My friend was shot in the chest, he's not breathing."
  3. → expect: "I have you at twelve riverside drive. Help is on the way." (turn fused, address echoed)
  4. → next dispatcher turn: "I am with you — are they on the floor?" (cardiac reassurance with redirect, fused into VERIFY_CPR_SURFACE)
  5. → no dead-air gap, no "what do I do?" from caller

## Risk register

- **TTS mispronunciation of address echo.** Cartesia Sonic-3 has historically handled US street names well; numbered cardinals are read as "twelve" not "one-two." If a specific address surfaces a mispronunciation, the fallback to the previous generic template kicks in.
- **Template word-count creep.** All proposed templates are within 5-14. The existing audit (`templates.py:287-305`) catches violations at startup.
- **`_SAFETY_TEMPLATE_ONLY` expansion.** Three new intents added. The existing tests at `tests/voice/test_response_gate.py` enforce that every reassurance/instruction intent is in the safety-only set; new tests required.
- **Behavior regression on the medical rail.** The medical reassurance variant's "tell me what's happening" overlaps with the existing `kq_severity` ("Can you speak in full sentences right now?"). Need to make sure the FSM advances cleanly to the actual KQ on the next turn rather than looping on "tell me what's happening."

## Out of scope for cycle-2D5

- Auto-rerouting on hedged answers (Missel et al. "look, listen, feel" pattern). Park for cycle-2D6.
- Critic-eval timeout investigation (separate cycle, not user-facing).
- Phase-3 fusion (gated on critic-eval success rate).
