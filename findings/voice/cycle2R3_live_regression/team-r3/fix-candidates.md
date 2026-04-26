# Team R3 — Fix candidates (read-only research; no code changes)

Format mirrors Team P/Q `fix-candidates.md`: ranked by confidence and impact, with file:line, LoC, risk, and rollback per fix.

All paths relative to `/Users/kiteboard/prism42/agents/livekit/`. All flags default OFF — these add behavior under the existing `PRISM42_ENABLE_FSM=1 + PRISM42_ENABLE_RESPONSE_GATE=1` posture.

---

## Bug 1 — Direct caller questions ignored in KEY_QUESTIONS

### Fix R3-B1-A (recommended) — Add `asks_did_you_hear` + `asks_destination` features and an `ANSWER_HEARD_ADDRESS` intent

**Diff target:** `dispatcher_fsm.py` + `response_gate.py` + `templates.py`. ~25 LoC.

**`dispatcher_fsm.py:199-208`** — extend the question-feature regex set:
```python
_RE_DID_YOU_HEAR_Q = re.compile(
    r"\bdid (?:you|ya) (?:hear|get|catch)\b|"
    r"\bdo you (?:know|have) (?:where|the address|my address)\b|"
    r"\bwhere are you sending\b|\bdid (?:you|that) go through\b",
    re.IGNORECASE,
)
```

**`dispatcher_fsm.py:212-233`** — add to `Features`:
```python
asks_heard_address: bool = False
```

**`dispatcher_fsm.py:354-356`** — set in `classify()`:
```python
asks_heard_address=bool(_RE_DID_YOU_HEAR_Q.search(t)),
```

**`dispatcher_fsm.py:113-141`** — add intent:
```python
ANSWER_HEARD_ADDRESS = "answer_heard_address"
```

**`dispatcher_fsm.py:609-616`** — extend `_direct_question_intent`:
```python
if f.asks_heard_address:
    return Intent.ANSWER_HEARD_ADDRESS
```

**`templates.py:204-219`** — add a template:
```python
"answer_heard_address": TemplateSpec(
    text="Yes, I have your address and units are on the way.",
    notes="Reassures caller their address was captured. Re-confirms dispatch.",
),
```

**`response_gate.py:193-204`** — add to `_SAFETY_TEMPLATE_ONLY` (consider — it's a comfort line, not life-safety; can stay non-safety).

**Rationale:** The router pattern is sound; it just needs broader question recognition. `_intent_in_key_questions` already calls `_direct_question_intent` (line 548-550), so once the router fires, the new intent takes priority. The `confirm_address` template already says "Got your address and dispatching help to you", so we have the latched address fact — the new template just acknowledges that the caller's question was heard.

**Risk:** Low. Pure additive — new regex, new intent, new template. No path that previously emitted other intents now diverts.

**Rollback:** Remove the four additions; FSM falls back to current behavior.

**Verification:** Run synthetic caller test (see `verification-plan.md` §B1) — feed transcript "Did you hear my address?" while FSM in `key_questions` → expect new intent emitted.

---

### Fix R3-B1-B (alternative) — Anti-repetition guard on intent emission

**Diff target:** `dispatcher_fsm.py` `_record()` at lines 620-640. ~10 LoC.

When the same intent is about to be emitted for the third turn in a row AND the caller's last utterance was substantive (>20 chars), force-route to `REPROMPT` so the gate emits the canonical "Sorry, could you repeat that for me?" template instead. This won't answer the caller's question correctly, but it stops the loop and surfaces that the dispatcher heard something different.

**Risk:** Medium — `REPROMPT` doesn't actually answer the caller's question, just signals listening.

**Rollback:** Trivial — remove the guard.

**Why R3-B1-A is preferred:** B1-A actually answers the question; B1-B just stops the broken record but the caller still doesn't get confirmation their address was received.

---

### Fix R3-B1-C (defense-in-depth) — LLM fallthrough for unmatched questions in KEY_QUESTIONS

**Diff target:** `response_gate.py` `gate_decision()` at lines 288-351. ~15 LoC.

When the FSM is in `key_questions` and the caller utterance has any "?" terminator OR question-leading bigram (`do you`, `did you`, `where`, `when`, `how`), and the routed intent is the SAME as the last template emitted, route to LLM with a constraint payload that says "answer the caller's question first." This puts the LLM in the loop only when the deterministic router fails.

**Risk:** Medium-high — LLM responses can drift gendered pronouns / introduce filler. The validators in `validate_llm_output` (`response_gate.py:120-183`) catch most of that, but not all.

**Rollback:** Remove the heuristic; FSM falls back to template.

**Why this is C-tier:** Re-introduces LLM nondeterminism into a path the gate explicitly removed. Use only if R3-B1-A's coverage proves insufficient.

---

## Bug 2 — FSM advances state on backchannels

### Fix R3-B2-A (recommended) — Backchannel detection blocks state advance

**Diff target:** `dispatcher_fsm.py:322-359` (`classify()`) + `408-484` (`transition()` head). ~20 LoC.

Add a backchannel detector:
```python
_RE_BACKCHANNEL = re.compile(
    r"^\s*(?:uh+|um+|ah+|oh+|ok(?:ay)?|alright|right|yeah|yep|yes|"
    r"got it|sure|mm+hmm+|hmm+)[.,!?\s]*$",
    re.IGNORECASE,
)
```

In `classify()`, add:
```python
is_backchannel: bool = False
```
…and set:
```python
is_backchannel=bool(_RE_BACKCHANNEL.match(t)) and len(t) <= 12,
```

In `transition()` near the head, BEFORE state machine dispatch:
```python
if f.is_backchannel and self.state in (
    State.ADDRESS_CONFIRMED, State.REASSURANCE_DELIVERED, State.KEY_QUESTIONS
):
    # Caller is back-channeling, not committing a new turn. Re-emit the
    # last intent (or REPROMPT after 2 consecutive backchannels) instead
    # of advancing state.
    return self._record(self.last_intent or Intent.REPROMPT, t0)
```

**Risk:** Low. Conservative — only fires when utterance fully matches backchannel regex AND <=12 chars. State machine still advances on substantive utterances.

**Side effect:** Re-emitting `last_intent` could repeat the same template back to the caller. To avoid this, route to `REPROMPT` after the FIRST backchannel instead of the second. Compromise: re-emit on first backchannel (caller may be processing); REPROMPT on second consecutive backchannel.

**Rollback:** Remove regex + `is_backchannel` field + branch in `transition`.

**Verification:** Synthetic test — FSM in `address_confirmed`, send "uh okay" → expect `last_intent` re-emit, NOT `deliver_reassurance` advance.

---

### Fix R3-B2-B (alternative) — Make `deliver_reassurance` require substantive caller utterance

**Diff target:** `dispatcher_fsm.py:526-536` (`_intent_in_address_confirmed`). ~5 LoC.

Add a length gate:
```python
def _intent_in_address_confirmed(self, f: Features, t0: float) -> Intent:
    q = self._direct_question_intent(f)
    if q is not None:
        return self._record(q, t0)
    # Don't latch reassurance on a sub-12-char backchannel — wait for
    # a real second utterance from the caller.
    if not getattr(self, "_last_utterance_len", 99) >= 12:  # see note
        return self._record(Intent.DELIVER_REASSURANCE, t0)  # still emit; just don't latch advance
    self.reassurance_done = True
    self.state = State.REASSURANCE_DELIVERED
    return self._record(Intent.DELIVER_REASSURANCE, t0)
```

**Risk:** Medium — needs to plumb `len(utterance)` from `transition()` into the helper. Asymmetric — only fixes the `address_confirmed` slot; the same problem could recur in `key_questions` later.

**Rollback:** Remove the gate.

**Why R3-B2-A is preferred:** B2-A is general (covers all phases that have the issue); B2-B fixes only one specific transition.

---

### Fix R3-B2-C (research-only) — Use semantic-turn-detector confidence

LiveKit's semantic turn detector (`livekit-agents[turn-detector]~=1.4`) returns a confidence score per turn-end. We could thread that into `on_user_turn_completed` and gate state advance on `confidence > 0.7`. Backchannels typically score low.

**Risk:** High — turn-detector model is CPU-bound (50-160ms), and we'd be adding a runtime dependency. Confidence semantics aren't documented for "is this a substantive turn vs backchannel."

**Why this is C-tier:** Pattern matching (R3-B2-A) achieves 90% of the win at 1% of the integration cost.

---

## Bug 3 — verify_cpr_surface contradiction-blind repetition

### Fix R3-B3-A (recommended) — `floor_negation` + `INSTRUCT_CPR_REPOSITIONING` intent

**Diff target:** `dispatcher_fsm.py` + `templates.py`. ~30 LoC.

**`dispatcher_fsm.py:165-169`** — add negation regex:
```python
_RE_FLOOR_NEGATION = re.compile(
    r"\b(?:in (?:a |the )?(?:chair|recliner|car seat|bed)|"
    r"sitting (?:up|on)|standing|on the (?:couch|sofa|bed)|"
    r"upright|in (?:his|her|their) chair|not on the floor|"
    r"can'?t move (?:him|her|them)|too heavy)\b",
    re.IGNORECASE,
)
```

**`dispatcher_fsm.py:212-233`** — add to `Features`:
```python
floor_negation: bool = False
```

**`dispatcher_fsm.py:344-346`** — set in `classify()`:
```python
floor_negation=bool(_RE_FLOOR_NEGATION.search(t)),
```

**`dispatcher_fsm.py:113-141`** — add intent:
```python
INSTRUCT_CPR_REPOSITIONING = "instruct_cpr_repositioning"
```

**`dispatcher_fsm.py:573-597`** — extend `_intent_in_verify`:
```python
def _intent_in_verify(self, f: Features, t0: float) -> Intent:
    q = self._direct_question_intent(f)
    if q is not None:
        return self._record(q, t0)
    # Cycle-2R3 (Bug 3): caller signaled patient is NOT on the floor.
    # Issue reposition instruction instead of re-asking the same question.
    if (not self.surface_confirmed) and f.floor_negation:
        return self._record(Intent.INSTRUCT_CPR_REPOSITIONING, t0)
    if not self.surface_confirmed:
        self.verify_step = VerifyStep.Q_SURFACE
        return self._record(Intent.VERIFY_SURFACE, t0)
    if not self.breathing_assessed:
        self.verify_step = VerifyStep.Q_BREATHING
        return self._record(Intent.VERIFY_BREATHING, t0)
    self.state = State.CRITICAL_CPR
    self.verify_step = VerifyStep.DONE
    return self._record(Intent.INSTRUCT_CPR_BEGIN, t0)
```

**`templates.py:106-235`** — add a template:
```python
"instruct_cpr_repositioning": TemplateSpec(
    text="Move them to the floor on their back right now.",
    notes="MPDS-9: caller indicated patient not on floor — reposition before CPR.",
),
```

**`response_gate.py:193-204`** — add to `_SAFETY_TEMPLATE_ONLY`:
```python
"instruct_cpr_repositioning",  # life-safety; never let LLM rephrase
```

**State semantics:** Once we emit `INSTRUCT_CPR_REPOSITIONING`, the next caller turn either confirms ("got him on the floor" → `floor_flat=True` → `surface_confirmed=True` → flow proceeds to `VERIFY_BREATHING`) or repeats the negation. Loop guard: track `repositioning_emitted` and after 2nd consecutive emit, latch `surface_confirmed=True` heuristically (caller is doing what they can — proceed to compressions because every second matters).

**Risk:** Medium — life-safety path. The template phrasing must be vetted clinically before ship. Recommend physician review (Brandon Dent, MD per CLAUDE.md §10) of "Move them to the floor on their back right now."

**Rollback:** Remove the regex, intent, template, branch. FSM falls back to current loop behavior.

**Verification:** Synthetic test — FSM in `critical_verify`, send "they're in a chair" → expect `INSTRUCT_CPR_REPOSITIONING` emitted; subsequent "ok got them on the floor" advances to `VERIFY_BREATHING`.

---

### Fix R3-B3-B (alternative) — Generic contradiction detection

**Diff target:** `dispatcher_fsm.py` `_record()` at lines 620-640. ~10 LoC.

Track repeat-emit count per intent. If the SAME intent emits twice in a row AND the caller's intervening utterance was substantive (>15 chars) AND contained any negation word ("no", "not", "n't", "but"), force-route to LLM path with a constraint: "Caller answered NO to your question. Take the next protocol action."

**Risk:** High — re-introduces LLM in life-safety verify path. CPR safety gate (`response_gate.py:227-244`) protects against compressions, but mis-phrased pre-CPR instructions can still cost time.

**Why R3-B3-A is preferred:** R3-B3-A is deterministic, has a hand-tuned safe template, and is auditable. B3-B opens a non-deterministic path in the safety-critical branch.

---

### Fix R3-B3-C — Force-advance after N repeats

**Diff target:** `dispatcher_fsm.py:573-597`. ~5 LoC.

After the FSM emits `VERIFY_SURFACE` 3 times consecutively, force `surface_confirmed=True` and advance regardless. Caller is presumed to be doing what they can.

**Risk:** Medium — false positive if caller really hasn't moved patient. CPR on a chair is not effective.

**Why this is C-tier:** Solves the loop but not the safety gap. R3-B3-A solves both.

---

## Recommended ship order

1. **R3-B3-A** first (life-safety, must ship clinically vetted).
2. **R3-B1-A** second (caller trust — acknowledging "did you hear" preserves rapport).
3. **R3-B2-A** third (cosmetic — advances aren't wrong, just premature).

Together: ~75 LoC across 3 files, all additive, all with rollbacks.

---

## DO-NOT list (per directive)

- Did NOT propose disabling the response gate.
- Did NOT propose vLLM env / framework / voice-quality changes.
- Did NOT propose touching frozen paths (`docs/clinical-extension-spec.md`, `.env`, `.state/`).
- All proposed fixes preserve voice quality (Fish TTS path unchanged).
- All proposed fixes default-OFF compatible (gate by existing `PRISM42_ENABLE_FSM` flag).
