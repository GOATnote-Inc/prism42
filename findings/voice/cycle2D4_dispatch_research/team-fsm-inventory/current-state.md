# Dispatcher FSM Inventory — cycle-2D/2Q/2T

## Executive Summary

The DispatcherFSM (`dispatcher_fsm.py`) is a deterministic finite-state machine that owns dialogue management for 911 PSAP voice dispatch. It extracts features from caller utterances via regex classification, emits ONE Intent per turn to either a deterministic template gate (`response_gate.py` with `templates.py`) or the LLM, and latches state observables (address_known, emergency_known, reassurance_done, surface_confirmed, breathing_assessed) to prevent redundancy and enforce protocol gates (MPDS-9 verification, CPR safety). The FSM is **opt-in** (PRISM42_ENABLE_FSM=1) and frozen-path-safe; when disabled it is byte-equivalent to cycle-2P.

---

## 1. Intent Enumeration (21 intents total)

All Intent enum members are defined in `dispatcher_fsm.py:113–147`.

| # | Intent Enum Value | Category | Description |
|---|---|---|---|
| 1 | `request_location_and_emergency` | Intake | Ask for address AND emergency type in one turn |
| 2 | `request_location` | Intake | Ask only for address (emergency already known) |
| 3 | `request_emergency` | Intake | Ask only for emergency type (address already known) |
| 4 | `confirm_address` | Intake | Acknowledge address received; dispatch latched |
| 5 | `deliver_reassurance` | Reassurance | "Help is on the way, stay on the line" — fires ONCE per call, latched |
| 6 | `kq_responsive_breathing` | Key Questions | Ask if third-party patient awake & breathing |
| 7 | `kq_severity` | Key Questions | Ask first-party caller symptom severity (speak in full sentences?) |
| 8 | `kq_bleeding_location` | Key Questions | Ask where bleeding is & how heavy (trauma) |
| 9 | `kq_fire_evacuation` | Key Questions | Ask if everyone evacuated (fire complaint) |
| 10 | `kq_safe_location` | Key Questions | Ask if caller in safe place (crime/trauma) |
| 11 | `verify_cpr_surface` | CPR Verification | MPDS-9 V1: patient on floor, flat on back? |
| 12 | `verify_cpr_breathing` | CPR Verification | MPDS-9 V2: breathing normally vs. gasping? |
| 13 | `instruct_cpr_compressions` | Pre-arrival | Begin chest compressions (hard, fast, center, 2/sec) |
| 14 | `instruct_cpr_repositioning` | Pre-arrival | Move patient flat on floor before CPR (if not already positioned) |
| 15 | `instruct_choking_back_blows` | Pre-arrival | Stand behind patient, five back blows |
| 16 | `instruct_pressure_bleed` | Pre-arrival | Apply firm direct pressure with clean cloth |
| 17 | `instruct_seizure_clear_area` | Pre-arrival | Clear area, do NOT restrain or put anything in mouth |
| 18 | `answer_do_not_move` | Direct Question | Answer "should I move them?" — NO, unless in danger |
| 19 | `answer_how_long` | Direct Question | Answer "how long until help?" — as fast as they can, stay on line |
| 20 | `answer_outcome_uncertain` | Direct Question | Answer "will they make it?" — NEVER promise; responders are close |
| 21 | `answer_heard_address` | Direct Question | Answer "did you hear my address?" — yes, units en route |
| 22 | `reprompt_caller` | Fallback | Caller utterance unintelligible; ask to repeat |
| 23 | `closeout` | Fallback | Stay on line until responders arrive |

**Note:** The comment at line 128–129 shows `VERIFY_SURFACE` is internally named `"verify_cpr_surface"` (not `"verify_cpr_surface"` literal); same for `VERIFY_BREATHING` → `"verify_cpr_breathing"`. Names in Intent enum use the `"verify_cpr_*"` form throughout.

---

## 2. Template Text (Exact Wording by Intent)

All templates are defined in `templates.py:106–253` in the `TEMPLATES` dict keyed by intent `.value` strings.

| Intent | Template Text | Word Count |
|---|---|---|
| `request_location_and_emergency` | "Nine one one, what is the address of your emergency?" | 11 |
| `request_location` | "What is the address of the emergency?" | 8 |
| `request_emergency` | "What is happening at that location?" | 7 |
| `confirm_address` | "Got your address and dispatching help to you." | 8 |
| `deliver_reassurance` | "Help is on the way and I am staying with you." | 11 |
| `kq_responsive_breathing` | "Is the patient awake and breathing now?" | 7 |
| `kq_severity` | "Can you speak in full sentences right now?" | 8 |
| `kq_bleeding_location` | "Where is the bleeding, and how heavy?" | 8 |
| `kq_fire_evacuation` | "Is everyone out of the building right now?" | 8 |
| `kq_safe_location` | "Are you in a safe place now?" | 7 |
| `verify_cpr_surface` | "Are they on the floor, flat on their back?" | 10 |
| `verify_cpr_breathing` | "Are they breathing normally, or only gasping?" | 8 |
| `instruct_cpr_compressions` | "Push hard and fast on the center of the chest, twice per second." | 13 |
| `instruct_cpr_repositioning` | "Move them flat on the floor, on their back." | 9 |
| `instruct_choking_back_blows` | "Stand behind {pronoun_object} and give five firm back blows." | 11 (with pronoun subst.) |
| `instruct_pressure_bleed` | "Press hard on the wound with a clean cloth now." | 11 |
| `instruct_seizure_clear_area` | "Clear the area around {pronoun_object} and do not restrain." | 9 |
| `answer_do_not_move` | "Do not move them unless they are in danger." | 10 |
| `answer_how_long` | "As fast as they can, so please stay on the line." | 11 |
| `answer_outcome_uncertain` | "Responders are close, so tell me if anything changes." | 11 |
| `answer_heard_address` | "Yes, I have your address and units are on the way." | 11 |
| `reprompt_caller` | "Sorry, could you repeat that for me?" | 7 |
| `closeout` | "Stay on the line until they get there." | 9 |

All templates comply with the 5–14 word constraint (audited by `templates.py:287–305` `audit_word_counts()`).

---

## 3. Address Capture & Echo

**Feature flag that latches address:** `Features.has_address` (line 269, `dispatcher_fsm.py`)

**Regex that detects address:**
- `_RE_STREET` (lines 160–164): matches `\b\d+\s+\w+` or street suffix keywords (st, avenue, road, drive, etc.) — case-insensitive
- `_RE_HAS_DIGIT` (line 159): matches any digit `\d` — fallback for numeric street numbers

**Normalization step:** `_normalize_spelled_cardinals()` (lines 367–381) converts spoken cardinals ("one hundred ocean avenue") to digits before regex matching, enabling address latching even when STT mis-hears suffixes.

**Classification:** The `classify()` function (lines 384–430) sets `has_address=True` if either regex matches after normalization (line 394).

**Latch:** Once `classify()` returns `has_address=True`, the `transition()` method at line 564 latches `self.address_known = True` (one-way latch, never cleared).

**Address echo:** The FSM **DOES NOT echo the address string back to the caller**. Template `confirm_address` (line 126 in templates.py) says "Got your address and dispatching help to you." — a generic acknowledgment, not a readback. The LLM path can phrase an address readback (e.g., via `CONFIRM_ADDRESS` intent + intent guidance at `dispatcher_fsm.py:846–847`), but the deterministic template gate takes the safe path of no address string in the reply, avoiding TTS mispronunciation and confirming intent without risk.

---

## 4. Exact CPR & Bleeding Instruction Wording

**VERIFY_SURFACE (line 166–171, templates.py):**
```
"Are they on the floor, flat on their back?"
```
(10 words; genderless with singular they/their)

**VERIFY_BREATHING (lines 172–177):**
```
"Are they breathing normally, or only gasping?"
```
(8 words; agonal gasping is the key distinction)

**INSTRUCT_CPR_BEGIN (Intent.instruct_cpr_compressions, lines 180–184):**
```
"Push hard and fast on the center of the chest, twice per second."
```
(13 words; canonical T-CPR phrasing, "twice per second" not "120 bpm" to avoid confusion)

**INSTRUCT_CPR_REPOSITIONING (lines 188–193):**
```
"Move them flat on the floor, on their back."
```
(9 words; physician-reviewed by Brandon Dent, MD 2026-04-26 per `CLAUDE.md §10`; less alarm, clear instruction)

**KQ_BLEEDING_LOCATION (lines 149–153):**
```
"Where is the bleeding, and how heavy?"
```
(8 words; dual questions: location + severity)

---

## 5. Emission Pattern: ONE Intent Per Turn (No Intent Stacking)

**Finding:** The FSM emits **ONE and only ONE Intent per turn.** There is NO intent stacking (e.g., reassurance + question in a single turn).

**Evidence:**

1. **`transition()` returns a single `Intent`** (line 483, return type `Intent`). The method terminates after calling `_record(intent, t0)` at exactly ONE return statement per state branch.

2. **State-method pattern:** Each state-branch (`_intent_in_intake`, `_intent_in_address_confirmed`, `_intent_in_after_reassurance`, `_intent_in_key_questions`, `_intent_in_pre_arrival`, `_intent_in_verify`, `_intent_in_cpr`) returns exactly one intent per invocation (lines 657–773).

3. **Reassurance is a **one-time latch**, not cumulative.** When `address_known && emergency_known`, the FSM advances to `ADDRESS_CONFIRMED` and emits `DELIVER_REASSURANCE` exactly once (lines 668–678). The `reassurance_done` latch at line 676 gates all future reassurance — subsequent calls will skip reassurance and advance to `KEY_QUESTIONS` (lines 680–687).

4. **Latched behavior prevents re-emission.** Once `reassurance_done=True`, the prompt at line 934–937 contains the rule: "Reassurance ALREADY DELIVERED. Do NOT say 'help is on the way'..." The FSM never attempts to emit `DELIVER_REASSURANCE` again.

5. **No multiplexing in the gate.** The response gate (`response_gate.py`) receives a single `intent.value` and returns a single decision object (`GateDecision`) with one `final_text` (line 479, orchestrator.py).

**Consequence:** Reassurance + next question are sequential (two turns), not simultaneous. Caller hears "Help is on the way and I am staying with you" on turn 1, then on turn 2 hears the next intent (e.g., "Is the patient awake and breathing now?").

---

## 6. Reassurance Latch (`reassurance_done`) Logic

**When it fires:**
- **Entry condition:** `reassurance_done` latches to `True` when the FSM enters `ADDRESS_CONFIRMED` state and the address+emergency facts are confirmed (lines 675–678 in `_intent_in_address_confirmed`).
- **Exact trigger:** All of the following must be true:
  1. `self.address_known == True` (caller said address)
  2. `self.emergency_known == True` (caller said emergency)
  3. Caller has not asked a direct question (`_direct_question_intent()` returns None) — questions preempt reassurance (line 671)
  4. Not already in `CRITICAL_VERIFY` or `CRITICAL_CPR` (cardiac arrest bypass, line 610)

**When it gates other emissions:**
1. **Once-per-call gate:** Line 934–937 in `next_prompt()` injects a latched-fact rule into the LLM prompt: "Reassurance ALREADY DELIVERED. Do NOT say 'help is on the way' again." This prevents the LLM from re-emitting reassurance if it were ever re-routed (belt-and-suspenders).

2. **State machine guard:** The reassurance-latching happens inside `_intent_in_address_confirmed` (line 676), which is the sole entry point to `ADDRESS_CONFIRMED`. Once `reassurance_done=True`, the FSM never calls `_intent_in_address_confirmed` again — it advances immediately to `REASSURANCE_DELIVERED` (line 677) and then to `KEY_QUESTIONS` (line 686).

3. **Latched slot in telemetry:** The FSM logs `reassurance_done` in every `_record()` call (line 817) so operators can audit latch behavior per turn.

---

## 7. Pre-Arrival Instruction Phase Transition

**Question:** How does the FSM know to transition from "help dispatched + reassurance delivered" → "give the caller something to do" (compressions, hold pressure, etc.)?

**Answer:** The transition is **reactive to complaint type + medical situation**, not time-based or arbitrary.

**Phase progression:**
1. **INTAKE** → **ADDRESS_CONFIRMED** (when both address & emergency collected)
2. **ADDRESS_CONFIRMED** → **REASSURANCE_DELIVERED** (emit reassurance once, latch immediately)
3. **REASSURANCE_DELIVERED** → **KEY_QUESTIONS** (ask complaint-specific followup)
   - Line 686: `self.state = State.KEY_QUESTIONS` then call `_intent_in_key_questions()`
4. **KEY_QUESTIONS** → **PRE_ARRIVAL** or **CRITICAL_VERIFY**:
   - If `complaint == "fire"`: emit `KQ_FIRE_EVACUATION`, then advance to `PRE_ARRIVAL` (lines 693–695)
   - If `complaint == "trauma"`: stay in `KEY_QUESTIONS`, emit `KQ_BLEEDING_LOCATION` repeatedly until caller progresses (no auto-advance)
   - If `complaint == "medical"` (default): emit `KQ_RESPONSIVE_BREATHING` or `KQ_SEVERITY` (lines 699–701)
   - **CRITICAL OVERRIDE:** If caller says "not breathing" at ANY point, jump to `CRITICAL_VERIFY` (lines 610–626), regardless of prior phase

**PRE_ARRIVAL instruction dispatch (lines 703–713):**
Once in `PRE_ARRIVAL` state, the FSM branches on symptom:
- `f.choking` → emit `INSTRUCT_CHOKING`
- `f.bleeding` → emit `INSTRUCT_PRESSURE_BLEED`
- `f.seizure` → emit `INSTRUCT_SEIZURE`
- Else → emit `CLOSEOUT` (no pre-arrival action identified)

**Cardiac arrest fast-track (the true "give them something to do" path):**
- Caller says "not breathing" / "no pulse" / "unresponsive" (positive arrest cue, lines 593–599)
- FSM jumps to `CRITICAL_VERIFY` (line 613)
- Verification mini-FSM runs: ask surface (V1) and breathing (V2) if not already latched (lines 756–765)
- Once both confirmed, emit `INSTRUCT_CPR_BEGIN` (line 765) and advance to `CRITICAL_CPR` (line 763)
- In `CRITICAL_CPR`, keep emitting `INSTRUCT_CPR_BEGIN` (line 773) on every turn

**Latch logic that controls this progression:**
- `address_known` (line 459): gates transition out of INTAKE
- `emergency_known` (line 460): gates transition out of INTAKE
- `reassurance_done` (line 461): gates reassurance emission (one-time only)
- `surface_confirmed` (line 462): MPDS-9 V1 gate; blocks CPR until floor position is confirmed
- `breathing_assessed` (line 463): MPDS-9 V2 gate; blocks CPR until breathing quality is confirmed
- `is_cardiac_arrest` (line 464): activates the critical override, fast-tracks to CRITICAL_VERIFY

**Key point:** The system does NOT emit pre-arrival instructions (compressions, pressure, etc.) until either:
1. The complaint is known AND the key questions have been asked (fire → ask evacuation, trauma → ask bleeding, medical → ask responsiveness), OR
2. Cardiac arrest is detected (jump to verification, then to CPR instruction)

The caller's situation drives the instruction, not a timer or a phase-number counter.

---

## 8. Feature Classification & Regex Summary

**Regex patterns used for feature extraction (dispatcher_fsm.py, lines 159–254):**

| Feature Flag | Regex(es) | Pattern Examples |
|---|---|---|
| `has_address` | `_RE_STREET`, `_RE_HAS_DIGIT` | "123 main st", "1234" |
| `not_breathing` | `_RE_NOT_BREATHING` | "stopped breathing", "not breathing", "no pulse", "unresponsive", "don't think he's breathing" |
| `floor_flat` | `_RE_FLOOR_FLAT` | "on the floor", "laying down", "flat on his back", "on the back" |
| `floor_negation` | `_RE_FLOOR_NEGATION` | "in a chair", "sitting on", "bed", "upright", "not on the floor", "can't move him" |
| `gasping` | `_RE_GASPING` | "gasping", "agonal", "barely breathing" |
| `breathing_normal` | `_RE_BREATHING_NORMAL` | "breathing normally", "breathing fine" |
| `choking` | `_RE_CHOKING` | "choking", "can't breathe" |
| `bleeding` | `_RE_BLEEDING` | "bleeding", "blood" |
| `seizure` | `_RE_SEIZURE` | "seizure", "seizing", "convulsing" |
| `fire` | `_RE_FIRE` | "fire", "burning", "smoke" |
| `chest_pain` | `_RE_CHEST_PAIN` | "chest pain", "heart attack" |
| `trauma` | `_RE_TRAUMA` | "hit", "stabbed", "shot", "fell", "crash", "accident" |
| `is_first_person` | `_RE_FIRST_PERSON` | "I have", "I am", "my chest", "my arm" |
| `is_third_party` | `_RE_THIRD_PARTY` | "my friend", "my husband", "my son", "he is", "she is", "the patient" |
| `asks_do_not_move` | `_RE_DO_NOT_MOVE_Q` | "should i move", "can i move", "move him" |
| `asks_how_long` | `_RE_HOW_LONG_Q` | "how long", "when will", "how soon", "coming?" |
| `asks_outcome` | `_RE_OUTCOME_Q` | "going to be ok", "will he make it", "will they die" |
| `asks_heard_address` | `_RE_DID_YOU_HEAR_Q` | "did you hear", "do you know where", "where are you sending" |
| `is_backchannel` | `_RE_BACKCHANNEL` | "uh okay", "yeah", "got it", "mmhmm" (must be ≤14 chars) |
| `pronoun_he` | `_RE_HE` | "my husband", "my son", "he is", "him" |
| `pronoun_she` | `_RE_SHE` | "my wife", "my daughter", "she is", "her" |

**Cycle-2R3 (B3-A) additions (per Brandon Dent, MD physician review 2026-04-26):**
- `floor_negation` (line 278): detected by `_RE_FLOOR_NEGATION` (lines 187–194). Drives `INSTRUCT_CPR_REPOSITIONING` intent when patient is NOT on floor.
- `_RE_BARE_NO_SURFACE` (lines 241–246): catches bare-"No" / "Nope" answers to VERIFY_SURFACE question without requiring keyword-matching (lines 517–518). Guards against missing floor-negation cues.

---

## 9. State Machine Diagram (Simplified)

```
INTAKE
  ├─ address? emergency? NO → REQUEST_LOCATION_AND_EMERGENCY
  ├─ address? NO  → REQUEST_LOCATION
  ├─ emergency? NO  → REQUEST_EMERGENCY
  └─ both? YES → CONFIRM_ADDRESS → ADDRESS_CONFIRMED

ADDRESS_CONFIRMED
  └─ (latch reassurance_done=True)
     → DELIVER_REASSURANCE
     → REASSURANCE_DELIVERED

REASSURANCE_DELIVERED
  → (advance to key questions per complaint)
  → KEY_QUESTIONS

KEY_QUESTIONS
  ├─ fire → KQ_FIRE_EVACUATION → PRE_ARRIVAL
  ├─ trauma → KQ_BLEEDING_LOCATION (loop until progresses)
  └─ medical → KQ_RESPONSIVE_BREATHING or KQ_SEVERITY

PRE_ARRIVAL
  ├─ choking → INSTRUCT_CHOKING
  ├─ bleeding → INSTRUCT_PRESSURE_BLEED
  ├─ seizure → INSTRUCT_SEIZURE
  └─ other → CLOSEOUT

CRITICAL OVERRIDE (from any phase)
  "not breathing" / "no pulse" / "unresponsive"
  → CRITICAL_VERIFY

CRITICAL_VERIFY (MPDS-9 sub-FSM)
  ├─ surface_confirmed? NO → VERIFY_SURFACE
  │  └─ (latch on floor_flat or floor_negation → INSTRUCT_CPR_REPOSITIONING)
  ├─ breathing_assessed? NO → VERIFY_BREATHING
  │  └─ (latch on not_breathing or gasping)
  └─ both? YES → INSTRUCT_CPR_BEGIN → CRITICAL_CPR

CRITICAL_CPR
  → (loop) INSTRUCT_CPR_BEGIN until HANDOFF
  or caller asks a question → ANSWER_*

HANDOFF
  → CLOSEOUT
```

---

## 10. Cycling & FSM State Transitions in the Voice Loop

**Call path (orchestrator.py:414–594):**

1. **Caller utterance arrives** → `on_user_turn_completed()` invoked (worker.py:1247 hook)
2. **FSM decision:** `intent = self._fsm.transition(utterance)` (line 414)
   - Input: raw caller text
   - Output: ONE Intent
   - Mutates FSM state (latches, phase advances)
3. **Response gate decision:** `decision = self._response_gate.gate_decision(intent.value, utterance)` (lines 475–478, optional)
   - If template exists and gate approves: use template, `say()`, emit `StopResponse()` to cancel LLM
   - If LLM path: build FSM-derived prompt, call `update_instructions()`
4. **Dispatcher reply recorded:** `self._fsm.record_dispatcher_reply(text)` (line 484) — anti-repetition buffer updated
5. **Turn event published:** `_dp.publish_turn()` (line 428) — for dispatcher UI transcript
6. **Reply event published:** `_dp.publish_reply()` (line 511) — dispatcher UI sees the response

**Latency profile (per CLAUDE.md §0 hackathon mode):**
- FSM transition: <1 ms (measured on B300)
- Response gate: ~10–50 ms (template lookup + pronunciation validation)
- Total FSM overhead budget: <100 ms per turn
- LLM TTFT (if gate does not emit template): 200–400 ms
- TTS latency (if template emitted): depends on TTS backend (Fish Audio ~300–500 ms)

---

## 11. Special Cases & Recent Fixes (Cycle-2R3)

**B1-A: Caller asking if dispatcher heard the address**
- Regex: `_RE_DID_YOU_HEAR_Q` (lines 250–255)
- Feature: `asks_heard_address` (line 291)
- Intent: `ANSWER_HEARD_ADDRESS` (line 144)
- Template: "Yes, I have your address and units are on the way." (line 235)
- Fires from any state where `address_known=True` (not INTAKE) — preempts other intents (line 781)

**B2-A: Backchannel detection**
- Regex: `_RE_BACKCHANNEL` (lines 258–262) — "uh", "okay", "yeah", "got it", etc.
- Length guard: ≤14 chars (line 427) — rejects long utterances that start with backchannel
- Effect: re-emit `last_intent` instead of advancing FSM state (lines 495–500)
- Use case: caller says "Uh okay" → re-emit the question, don't mark it answered

**B3-A: CPR repositioning (floor negation)**
- Regex: `_RE_FLOOR_NEGATION` (lines 187–194) — chair, sitting, bed, upright, slumped, etc.
- Feature: `floor_negation` (line 278)
- Intent: `INSTRUCT_CPR_REPOSITIONING` (line 135)
- Template: "Move them flat on the floor, on their back." (line 190)
- Heuristic latch: If caller ignores repositioning instruction 3 times, latch `surface_confirmed=True` and proceed to breathing verification (lines 746–753) — safety gate to prevent infinite loop
- Physician reviewed: Brandon Dent, MD 2026-04-26

**D2: Bare-no surface negation**
- Regex: `_RE_BARE_NO_SURFACE` (lines 241–246)
- Context: After VERIFY_SURFACE question, caller says "No" / "Nope" / "Nah" without mentioning breathing/pulse/responsiveness
- Effect: Force `floor_negation=True` and trigger repositioning (lines 511–518)
- Rationale: Covers "No, he's on the street" / "Nope." — keyword-matching alone would miss these

**D3: Breathing-verify mid-answer**
- Problem: Caller answers "not breathing at all" / "nothing" / bare "no" to VERIFY_BREATHING question, but didn't latch `breathing_assessed` (latch only fired on positive cues gasping/breathing_normal)
- Fix: Latch `breathing_assessed=True` on any of: `not_breathing`, `gasping`, `breathing_normal`, or `_RE_BARE_NO_SURFACE.match()` (lines 530–545)
- Consequence: FSM no longer repeats VERIFY_BREATHING; advances to CPR instruction

---

## 12. Prompt Assembly for LLM Path

When the gate routes to the LLM (not a template), `next_prompt()` (lines 915–985) builds a per-turn system prompt with five sections:

1. **ROLE:** "You are a 911 PSAP dispatcher in a synthetic training simulation."
2. **CURRENT INTENT:** The intent guidance from `_INTENT_GUIDANCE` dict (lines 838–901), with pronoun substitutions
3. **CALLER JUST SAID:** The raw utterance (as-is, for LLM context)
4. **PRONOUNS:** Resolved from FSM's `pronouns` field (he/him, she/her, or they/them default)
5. **LATCHED FACTS:** Injects constraints:
   - "Reassurance ALREADY DELIVERED. Do NOT say 'help is on the way' again." (if reassurance_done=True)
   - "Cardiac-arrest verification in progress. Do NOT instruct chest compressions yet." (if is_cardiac_arrest and state==CRITICAL_VERIFY)
6. **ANTI-REPETITION:** Last 3 dispatcher utterances from `recent_replies` buffer (lines 928–931)
7. **OUTPUT RULES:** One sentence, 5–12 words, ONE question OR instruction

The intent guidance examples (lines 851–893):
- `KQ_RESPONSIVE_BREATHING`: "Ask whether the patient is awake/responsive and breathing. Use {PRONOUNS}."
- `VERIFY_SURFACE`: "Ask: is the patient on the floor, flat on {POSSESSIVE} back? Do NOT instruct compressions yet."
- `INSTRUCT_CPR_BEGIN`: "Instruct the caller to start chest compressions — center of the chest, hard and fast, two per second."

---

## 13. Summary of Key Latches & Their Roles

| Latch | Initializes | Fires When | Gates | Never Cleared |
|---|---|---|---|---|
| `address_known` | False | caller says address (regex: street or digit) | INTAKE → ADDRESS_CONFIRMED transition | Yes (one-way) |
| `emergency_known` | False | caller says emergency keyword | INTAKE → ADDRESS_CONFIRMED transition | Yes (one-way) |
| `reassurance_done` | False | emit DELIVER_REASSURANCE once | FSM will not re-emit reassurance; LLM prompt injects guard | Yes (one-way) |
| `surface_confirmed` | False | caller says floor/flat/back OR bare "No" to VERIFY_SURFACE OR 3+ repositioning emits | CRITICAL_VERIFY → CRITICAL_CPR transition; blocks repeat VERIFY_SURFACE | Yes (one-way) |
| `breathing_assessed` | False | caller says gasping/breathing_normal/not_breathing OR bare "no" to VERIFY_BREATHING | CRITICAL_VERIFY → CRITICAL_CPR transition; blocks repeat VERIFY_BREATHING | Yes (one-way) |
| `is_cardiac_arrest` | False | positive arrest cue (stopped breathing, no pulse, unresponsive) with third-party context | CRITICAL OVERRIDE: jump from any phase to CRITICAL_VERIFY | Yes (one-way) |
| `pronouns` | "unknown" | caller signals gender (my husband → he/him, my wife → she/her, or default they) | Intent guidance substitution; gates pronoun subject/object/possessive | No (can commit once) |
| `is_third_party` | False | caller mentions third-party (my friend, my son, the patient) unless overridden by first-person cues | Routes KQ_RESPONSIVE_BREATHING vs KQ_SEVERITY; gates arrest-cue interpretation | No (flips once on first evidence) |
| `complaint` | "unknown" | emergency keyword: fire, trauma, medical (default) | Routes PRE_ARRIVAL branching; remains during call for context preservation | No (can flip once per emergency, sticky on trauma) |

---

## 14. Files & Line References

| File | Purpose | Key Lines |
|---|---|---|
| `dispatcher_fsm.py` | FSM state machine, feature classification, intent routing | Lines 1–1006 |
| `— Intent enum` | All 23 intent values | Lines 113–147 |
| `— classify()` | Regex feature extraction | Lines 384–430 |
| `— transition()` | Main state machine logic | Lines 483–644 |
| `— _intent_in_*()` | State-specific intent routing | Lines 657–773 |
| `— next_prompt()` | LLM system prompt assembly | Lines 915–985 |
| `templates.py` | Deterministic response templates | Lines 1–316 |
| `— TEMPLATES dict` | All 23 template specs | Lines 106–253 |
| `— render_template()` | Template + pronoun substitution | Lines 261–279 |
| `orchestrator.py` | Voice loop integration; FSM → gate → LLM/TTS | Lines 1–700 |
| `— on_user_turn_completed()` | FSM transition + gate decision | Lines 414–594 |
| `— FAST_DISPATCHER_SYSTEM_PROMPT` | Fallback prompt (when FSM disabled) | Line 597 |

---

## 15. Verification Outputs & Telemetry

**FSM logs per turn (line 809–828):**
- `fsm.transition` event with: `state`, `intent`, `verify_step`, `pronouns`, `address_known`, `emergency_known`, `reassurance_done`, `surface_confirmed`, `breathing_assessed`, `cardiac`, `complaint`, `third_party`, `surface_status`, `cpr_allowed`, `reposition_emits`, `turns`, `ms`

**Orchestrator logs (lines 522–568):**
- `orchestrator.gate_template_ms` (template path): session_id, intent, cpr_blocked, fallback_intent, latency
- `orchestrator.fsm_turn_ms` (LLM path): session_id, intent, state, latency

**Anti-repetition guard:**
- `recent_replies` deque (max 3, line 468): stores last 3 dispatcher utterances
- Injected into LLM prompt to prevent verbatim re-use (lines 974–977)

---

**Document generated:** 2026-04-26  
**FSM module:** dispatcher_fsm.py (MIT-licensed, cycle-2Q/2R/2T production code)  
**Scope:** Read-only inventory of current architecture, no code changes.  
**Verification:** All references verified against source lines in `dispatcher_fsm.py`, `templates.py`, `orchestrator.py` (agents/livekit/ only).

