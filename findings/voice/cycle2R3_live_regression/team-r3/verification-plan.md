# Team R3 — verification plan (synthetic test scenarios per fix)

These tests run against the FSM module **in isolation** (no LiveKit, no TTS). They unit-test `dispatcher_fsm.transition()` and `response_gate.gate_decision()`. All paths in `tests/voice/test_dispatcher_fsm.py` and `tests/voice/test_response_gate.py` (or new files at the same path).

Run via:
```
cd /Users/kiteboard/prism42 && pytest tests/voice/test_cycle2R3_*.py -v
```

No B300 pod restart required. No service interruption.

---

## §B1 — Bug 1 verification (Fix R3-B1-A: did-you-hear question recognition)

### Test B1-1: caller asks "did you hear my address?" mid KEY_QUESTIONS

```python
def test_b1_did_you_hear_routes_to_answer_heard_address():
    fsm = DispatcherFSM()
    # Pre-load: caller gave address + emergency in turn 1 + 2.
    fsm.transition("123 main street my friend has chest pain")
    fsm.transition("yeah he's unconscious now")
    # Should be in KEY_QUESTIONS.
    assert fsm.state == State.KEY_QUESTIONS
    # The new question pattern.
    intent = fsm.transition("Did you hear my address?")
    assert intent == Intent.ANSWER_HEARD_ADDRESS  # NEW intent
    # State should NOT regress.
    assert fsm.state == State.KEY_QUESTIONS
```

### Test B1-2: caller asks "where are you sending them"

```python
def test_b1_where_are_you_sending_routes_to_answer_heard_address():
    fsm = DispatcherFSM()
    fsm.transition("100 ocean ave my mom is having a heart attack")
    fsm.transition("she's not breathing")
    # In CRITICAL_VERIFY now (cardiac override fired).
    assert fsm.state == State.CRITICAL_VERIFY
    intent = fsm.transition("where are you sending them?")
    assert intent == Intent.ANSWER_HEARD_ADDRESS
```

### Test B1-3: gate emits the new template via `session.say()` path

```python
def test_b1_gate_emits_heard_address_template():
    fsm = DispatcherFSM()
    fsm.address_known = True
    gate = ResponseGate(fsm=fsm)
    decision = gate.gate_decision("answer_heard_address")
    assert decision.used_template is True
    assert decision.final_text is not None
    assert "address" in decision.final_text.lower()
    # Word count check.
    assert 5 <= len(decision.final_text.split()) <= 14
```

### Test B1-4: pattern does NOT mis-fire on similar non-questions

```python
def test_b1_did_you_hear_pattern_specificity():
    # Should NOT match these.
    f = classify("they did hear him gasping")
    assert f.asks_heard_address is False
    f = classify("did you hear him scream")
    assert f.asks_heard_address is False  # not address-related
    # SHOULD match these.
    f = classify("Did you hear my address?")
    assert f.asks_heard_address is True
    f = classify("Do you know where you're sending them?")
    assert f.asks_heard_address is True
```

---

## §B2 — Bug 2 verification (Fix R3-B2-A: backchannel suppress state advance)

### Test B2-1: backchannel does not advance from ADDRESS_CONFIRMED to REASSURANCE_DELIVERED

```python
def test_b2_backchannel_holds_state_in_address_confirmed():
    fsm = DispatcherFSM()
    fsm.transition("100 main street my friend has chest pain")
    # Now in ADDRESS_CONFIRMED with last_intent=CONFIRM_ADDRESS.
    assert fsm.state == State.ADDRESS_CONFIRMED
    intent = fsm.transition("uh okay")
    # Should NOT have advanced to REASSURANCE_DELIVERED yet.
    assert fsm.state == State.ADDRESS_CONFIRMED
    assert fsm.reassurance_done is False
    # Should have re-emitted last intent OR REPROMPT.
    assert intent in (Intent.CONFIRM_ADDRESS, Intent.REPROMPT)
```

### Test B2-2: substantive utterance DOES advance after a backchannel

```python
def test_b2_substantive_utterance_resumes_progression():
    fsm = DispatcherFSM()
    fsm.transition("100 main street my friend has chest pain")
    fsm.transition("uh okay")  # backchannel — holds state
    intent = fsm.transition("he's unconscious now")  # substantive
    # Now reassurance should latch.
    assert fsm.reassurance_done is True
    assert fsm.state == State.REASSURANCE_DELIVERED
```

### Test B2-3: backchannel detector specificity

```python
def test_b2_backchannel_pattern():
    assert classify("uh").is_backchannel is True
    assert classify("um okay").is_backchannel is True
    assert classify("yeah").is_backchannel is True
    assert classify("got it").is_backchannel is True
    # Substantive — should NOT be backchannel.
    assert classify("yeah he stopped breathing").is_backchannel is False
    assert classify("ok he's not moving").is_backchannel is False
    # Long utterance even if it starts with backchannel word.
    assert classify("ok so what should I do now").is_backchannel is False
```

### Test B2-4: real session replay against fix

Replay the actual session 74d90ae3 timeline:
```python
def test_b2_session_74d90ae3_replay():
    fsm = DispatcherFSM()
    # Turn 1 — address + emergency
    i1 = fsm.transition("100 ocean of new")
    # Turn 2 — third party medical
    i2 = fsm.transition("my friend was said he had chest pain in the knee is unconscious now")
    assert i2 == Intent.CONFIRM_ADDRESS
    # Turn 3 — backchannel (10 chars)
    i3 = fsm.transition("uh okay")
    # POST-FIX expectation: should NOT have already latched reassurance_done.
    assert fsm.reassurance_done is False  # FAILS pre-fix; PASSES post-fix
```

---

## §B3 — Bug 3 verification (Fix R3-B3-A: floor_negation routes to repositioning)

### Test B3-1: "in a chair" routes to INSTRUCT_CPR_REPOSITIONING

```python
def test_b3_chair_routes_to_repositioning():
    fsm = DispatcherFSM()
    fsm.transition("100 main street my friend stopped breathing")
    # Now in CRITICAL_VERIFY (cardiac arrest cue triggered).
    assert fsm.state == State.CRITICAL_VERIFY
    # Caller answers "in a chair" instead of "yes on floor"
    intent = fsm.transition("yeah I mean they're in a chair")
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING
    # State stays in CRITICAL_VERIFY (not on floor yet).
    assert fsm.state == State.CRITICAL_VERIFY
    assert fsm.surface_confirmed is False
```

### Test B3-2: subsequent "ok on floor now" advances to verify_breathing

```python
def test_b3_repositioning_then_floor_advances():
    fsm = DispatcherFSM()
    fsm.transition("100 main st my dad isn't breathing")
    fsm.transition("they're in a chair")  # → INSTRUCT_CPR_REPOSITIONING
    intent = fsm.transition("ok he's on the floor flat on his back now")
    # Now should advance to VERIFY_BREATHING.
    assert fsm.surface_confirmed is True
    assert intent == Intent.VERIFY_BREATHING
```

### Test B3-3: gate emits repositioning template

```python
def test_b3_gate_emits_repositioning_template():
    fsm = DispatcherFSM(state=State.CRITICAL_VERIFY)
    gate = ResponseGate(fsm=fsm)
    decision = gate.gate_decision("instruct_cpr_repositioning")
    assert decision.used_template is True
    assert "floor" in decision.final_text.lower()
    assert 5 <= len(decision.final_text.split()) <= 14
    # Safety-only: must NOT route to LLM.
    assert decision.used_llm is False
```

### Test B3-4: floor_negation pattern specificity

```python
def test_b3_floor_negation_patterns():
    # Should match.
    for utt in [
        "they're in a chair",
        "he's sitting on the couch",
        "she's standing in the kitchen",
        "in a recliner",
        "on the bed sitting up",
        "I can't move him too heavy",
        "not on the floor",
    ]:
        assert classify(utt).floor_negation is True, f"failed: {utt}"
    # Should NOT match (positive floor cues / unrelated).
    for utt in [
        "he's on the floor flat on his back",
        "yes on the ground",
        "lying down already",
        "she's responsive but breathing weird",
    ]:
        assert classify(utt).floor_negation is False, f"false-pos: {utt}"
```

### Test B3-5: repositioning loop has an escape hatch

```python
def test_b3_repositioning_force_advance_after_2_emits():
    fsm = DispatcherFSM()
    fsm.transition("100 main st he stopped breathing")
    # First negation
    i1 = fsm.transition("they're in a chair")
    assert i1 == Intent.INSTRUCT_CPR_REPOSITIONING
    # Second negation — caller can't physically move patient
    i2 = fsm.transition("they're too heavy I can't move them")
    # Recommended: force-advance to VERIFY_BREATHING (every second matters)
    # OR emit INSTRUCT_CPR_BEGIN with caller-on-chair caveat.
    # This test verifies SOMETHING other than infinite re-emit happens.
    assert i2 != Intent.INSTRUCT_CPR_REPOSITIONING  # break the loop
```

---

## §C — Live verification (post-merge, before announcing fix)

Run a synthetic-caller session locally (no pod restart needed):

```bash
cd /Users/kiteboard/prism42/agents/livekit
PRISM42_ENABLE_FSM=1 PRISM42_ENABLE_RESPONSE_GATE=1 \
  python synthetic_caller.py --scenario cardiac_arrest_in_chair \
  --turns "100 main st my dad isn't breathing" \
  --turns "they're in a chair" \
  --turns "ok he's on the floor"
```

Expected dispatcher emissions in order:
1. "Got your address and dispatching help to you."
2. (cardiac override fires) "Are they on the floor, flat on their back?"
3. **(NEW) "Move them to the floor on their back right now."**
4. **(NEW) "Are they breathing normally, or only gasping?"**

Pre-fix the third dispatcher line is "Are they on the floor, flat on their back?" again; post-fix it is the repositioning instruction.

---

## §D — Real-session re-test plan (no service restart)

Once fixes land, run two LIVE test calls to `https://prism42-app.thegoatnote.com`:

**Call 1 — KEY_QUESTIONS direct question:**
1. Greet → "100 ocean avenue"
2. "my friend had chest pain and is unconscious"
3. "did you hear my address?"

**Expected:** Dispatcher says "Yes, I have your address and units are on the way." (or similar), NOT "Is the patient awake and breathing now?"

**Call 2 — cardiac in-chair:**
1. Greet → "200 elm street"
2. "my dad just collapsed and isn't breathing"
3. "yeah he's in a chair"

**Expected:** Dispatcher says "Move them to the floor on their back right now.", NOT "Are they on the floor, flat on their back?"

**Pass criteria:** worker.log shows `intent=answer_heard_address` (call 1) and `intent=instruct_cpr_repositioning` (call 2). No `orchestrator.fsm_turn_failed`. No double-emit.

---

## §E — Regression guards

Add CI guards to `tests/voice/test_response_gate.py`:

1. `_SAFETY_TEMPLATE_ONLY` includes `"instruct_cpr_repositioning"` (life-safety hard-route).
2. Every Intent enum value has a template OR is REPROMPT (audit_word_counts coverage).
3. `_RE_FLOOR_NEGATION` and `_RE_FLOOR_FLAT` are mutually exclusive on the test corpus — no utterance matches both.

These guards prevent future fixes from regressing the cycle-2R3 behavior.
