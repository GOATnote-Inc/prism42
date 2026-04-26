# Team R3 — cycle2R3 live regression diagnosis (post-cycle-2M2)

Session under audit: `74d90ae3-b31a-a68e-4560-a2eae44be959` (live, 2026-04-26 17:46:45 → 17:48:44).
Voice quality is praised by the user; all three bugs are response-logic regressions in the post-cycle-2M2 FSM + gate stack with `PRISM42_ENABLE_FSM=1` and `PRISM42_ENABLE_RESPONSE_GATE=1`.

## TL;DR

| Bug | Root cause | Severity | One-line fix |
|---|---|---|---|
| 1 — direct questions ignored in KEY_QUESTIONS | `_direct_question_intent()` only matches `do_not_move` / `how_long` / `outcome` regexes; "did you hear my address?" matches NONE. The A3 fix wired the router into `_intent_in_verify`, but the router itself has no pattern for the meta-question "did you hear ___" | High — caller perceives non-listening | Add `asks_did_you_hear` feature + `ANSWER_HEARD_ADDRESS` intent + template |
| 2 — phantom progression on backchannels | FSM `transition()` advances state on EVERY non-empty utterance, including 10-char backchannel "uh okay". `_intent_in_address_confirmed` unconditionally latches reassurance; `_intent_in_after_reassurance` unconditionally advances to KEY_QUESTIONS | Medium — wastes a turn slot without caller reply substance | Gate state-advance on substantive utterance (length / content) — keep state on backchannel-only turns |
| 3 — verify_cpr_surface re-asked despite "in a chair" | `_intent_in_verify` has no negation/contradiction handler. It re-emits `VERIFY_SURFACE` until `surface_confirmed=True`. Caller's "they're in a chair" sets nothing; FSM loops | High (life-safety) | Add `floor_negation` feature; route to a new `INSTRUCT_CPR_REPOSITIONING` intent + template |

---

## Bug 1 — Direct caller questions are STILL ignored in KEY_QUESTIONS

### What the user observed

Session 74d90ae3, second scenario (third-party medical, post-reassurance):

| Time | Role | Utterance |
|---|---|---|
| 17:47:26 | Dispatcher | "Is the patient awake and breathing now?" (kq_responsive_breathing) |
| 17:47:37 | Caller TURN 5 | "Did did you did you hear my address?" (transcript len=36) |
| 17:47:37 | Dispatcher | "Is the patient awake and breathing now?" (kq_responsive_breathing — IGNORED) |
| 17:47:50 | Caller TURN 6 | "Uh none of this matters if you did not hear my address. Do you know where you're sending? You said helps on the way. Where are you sending them to?" (transcript len=147) |
| 17:47:50 | Dispatcher | "Is the patient awake and breathing now?" (STILL IGNORED) |

### Worker.log evidence (post-cycle-2M2, FSM=ON, GATE=ON)

```
17:47:37 fsm.transition  state=key_questions intent=kq_responsive_breathing turns=5 third_party=True
17:47:37 response_gate.decision  intent=kq_responsive_breathing used_template=True final_text='Is the patient awake and breathing now?'
17:47:50 fsm.transition  state=key_questions intent=kq_responsive_breathing turns=6 third_party=True
17:47:50 response_gate.decision  intent=kq_responsive_breathing used_template=True final_text='Is the patient awake and breathing now?'
```

### Root cause

The user hypothesized: "did Team P A3 cover the KEY_QUESTIONS phase too, or only CRITICAL_VERIFY?"

Answer: **A3 wired `_direct_question_intent` into `_intent_in_verify` (`dispatcher_fsm.py:585-587`). KEY_QUESTIONS already had the same router call (`dispatcher_fsm.py:548-550`).** So the routing IS in place for KEY_QUESTIONS. The bug is one layer deeper: `_direct_question_intent()` only inspects three regex feature flags (`asks_do_not_move`, `asks_how_long`, `asks_outcome` at `dispatcher_fsm.py:609-616`), and **NONE of these patterns match "did you hear my address?"**

Patterns at `dispatcher_fsm.py:199-208`:

```
_RE_DO_NOT_MOVE_Q = r"\bshould i move|can i move|do i move|move (him|her|them)"
_RE_HOW_LONG_Q   = r"\bhow long|when (?:are|will|is)|how soon|coming\??$"
_RE_OUTCOME_Q    = r"\b(?:going to (be ok|...)|will (he|she|they) (be|live|die))"
```

The caller's question "Did you hear my address?" / "do you know where you're sending?" / "where are you sending them to?" matches NONE of these. The router returns `None`, the per-state helper falls through to `KQ_RESPONSIVE_BREATHING`, and the gate emits the same template again.

This is a **classifier coverage gap**, not a routing bug. Team P A3's CRITICAL_VERIFY guard helps for "should I move them?" but not for the meta-question class "did you hear ___?" / "where are you sending ___?".

### Citations

- Router definition: `agents/livekit/dispatcher_fsm.py:609-616`
- KEY_QUESTIONS already calls router: `agents/livekit/dispatcher_fsm.py:547-550`
- Patterns missing: `agents/livekit/dispatcher_fsm.py:199-208`

---

## Bug 2 — "Phantom progression" — FSM advances on backchannels

### What the user observed

The user reported "3 dispatcher turns fired between caller-turn-2 and caller-turn-5 with no caller turn in between."

### Worker.log evidence — actual ground truth

```
17:46:55 fsm.transition  state=intake          intent=request_emergency        turns=1   (caller len=29)
17:47:05 fsm.transition  state=address_confirmed intent=confirm_address        turns=2   (caller len=71 — chest pain + unconscious)
17:47:17 fsm.transition  state=reassurance_delivered intent=deliver_reassurance turns=3   (caller len=10 — backchannel "uh okay"-ish)
17:47:26 fsm.transition  state=key_questions   intent=kq_responsive_breathing  turns=4   (caller len=45)
17:47:37 fsm.transition  state=key_questions   intent=kq_responsive_breathing  turns=5   (caller len=36)
```

Three dispatcher emissions land in 21 seconds (17:47:05, :17, :26) but they correspond to THREE separate caller turns — including a 10-char backchannel at 17:47:17. There is **no double-emit per turn**; cycle-2M2's StopResponse fix is holding.

### Root cause — reframed

The actual bug is: **the FSM advances state on every non-empty caller utterance, including a 10-char backchannel.** The user perceived "phantom progression" because:

1. Caller TURN 2 ("my friend… chest pain… unconscious", 71 chars) → FSM goes intake → address_confirmed → emits `confirm_address`.
2. Caller TURN 3 (10 chars; per len, likely "uh okay" / "right" / a brief acknowledgment) → FSM does NOT recognize this as a backchannel. `_intent_in_address_confirmed()` (`dispatcher_fsm.py:526-536`) latches `reassurance_done=True` and emits `deliver_reassurance` unconditionally. State → `reassurance_delivered`.
3. Caller TURN 4 (45 chars, more substantive) → FSM goes reassurance_delivered → key_questions, emits `kq_responsive_breathing`.

The FSM has NO concept of "non-progressive utterance." Every caller turn that classifies (which means every utterance with text) drives a state transition. 10-char backchannels burn a state slot that the caller did not intend to commit.

This is consistent with the user's original framing of "phantom" — what the caller does NOT realize is that their own backchannel triggered the progression. The dispatcher is then "talking past" the caller from the caller's POV.

### Why this is NOT a transition() loop / cascade bug

I traced `on_user_turn_completed` in `agents/livekit/orchestrator.py:324-492`:

- Each invocation calls `self._fsm.transition(utterance)` exactly once (line 342).
- Each invocation evaluates the gate exactly once (line 372-444).
- Each invocation either emits ONE template via `session.say()` (line 386-389) OR falls through to ONE `update_instructions()` (line 451-455).
- `StopResponse()` is raised at line 491-492 only when `gate_emitted_template=True`.
- No re-entrancy; no internal loop calling `transition()` again.

The FSM module itself: `transition()` (`dispatcher_fsm.py:408-502`) calls one per-state helper, which returns one `Intent` via `_record()` and exits. No recursion.

So Bug 2 is NOT a cascade / feedback loop — it is the FSM treating every utterance, including backchannels, as a state-advancing turn.

### Citations

- `_intent_in_address_confirmed` (always advances): `agents/livekit/dispatcher_fsm.py:526-536`
- `_intent_in_after_reassurance` (always advances to KEY_QUESTIONS): `agents/livekit/dispatcher_fsm.py:538-545`
- One-call-per-turn proof: `agents/livekit/orchestrator.py:342`, `:372`, `:451`

---

## Bug 3 — Contradiction-blind repetition (verify_cpr_surface)

### What the user observed

Cardiac scenario, ~17:48:34 onward:

| Time | Role | Utterance |
|---|---|---|
| 17:48:33 | Caller TURN 7 | (cardiac arrest cue, len=33 — likely "they're not breathing" / "stopped breathing") |
| 17:48:34 | Dispatcher | "Are they on the floor, flat on their back?" (verify_cpr_surface) |
| 17:48:43 | Caller TURN 8 | "Yeah, I mean they're in a chair." (transcript len=34) |
| 17:48:44 | Dispatcher | "Are they on the floor, flat on their back?" (REPEATED — should redirect to "Move them to the floor right now") |

### Worker.log evidence

```
17:48:34 fsm.transition  state=critical_verify cardiac=True surface_confirmed=False intent=verify_cpr_surface turns=7 verify_step=q_surface
17:48:34 response_gate.decision  intent=verify_cpr_surface used_template=True final_text='Are they on the floor, flat on their back?'
17:48:44 fsm.transition  state=critical_verify cardiac=True surface_confirmed=False intent=verify_cpr_surface turns=8 verify_step=q_surface
17:48:44 response_gate.decision  intent=verify_cpr_surface used_template=True final_text='Are they on the floor, flat on their back?'
```

`surface_confirmed` stays False on turn 8 even though the caller answered.

### Root cause

The user hypothesized: "does the FSM track caller's negative answer to verify_cpr_surface? Or does it treat any caller utterance as 'non-answer, re-ask'?"

Answer: **Treats every utterance as non-answer.** The FSM has positive cues only:

```python
_RE_FLOOR_FLAT = r"\b(?:on the (?:floor|ground)|laying down|lying flat|flat on (?:his|her|their) back|on (?:his|her|their) back|on the back)\b"
```

(`agents/livekit/dispatcher_fsm.py:165-169`)

`floor_flat=True` ONLY sets when the caller speaks one of those positive phrases. "Yeah, I mean they're in a chair" matches NONE — `floor_flat=False`. In `_intent_in_verify`:

```python
if not self.surface_confirmed:           # still False
    self.verify_step = VerifyStep.Q_SURFACE
    return self._record(Intent.VERIFY_SURFACE, t0)   # re-emit
```

(`agents/livekit/dispatcher_fsm.py:588-590`)

There is **no negation pattern** (`in a chair`, `sitting`, `standing`, `not on the floor`, `on the couch`, `in bed sitting up`) and **no `INSTRUCT_CPR_REPOSITIONING` intent**. The verify loop is monotonic: it only escapes when surface_confirmed flips to True. A caller who says the patient is in a chair gets the same question on infinite repeat.

Consequence: in real cardiac arrest, every second of CPR delay matters. Re-asking instead of issuing the reposition instruction is a life-safety gap.

### Citations

- Verify loop: `agents/livekit/dispatcher_fsm.py:588-590`
- floor_flat positive-only regex: `agents/livekit/dispatcher_fsm.py:165-169`
- No INSTRUCT_CPR_REPOSITIONING intent in `Intent` enum: `agents/livekit/dispatcher_fsm.py:113-141`
- No template for repositioning in `TEMPLATES`: `agents/livekit/templates.py:106-235`

---

## Cross-cutting note: cycle-2M2 fixes ARE working

Live-log evidence confirms cycle-2M2's five Q+P fixes landed:

- Fix-1 (StopResponse not dead-code): No `orchestrator.fsm_turn_failed` lines for the gate-template path; one `orchestrator.gate_template_ms` per caller turn → no double-emit.
- Fix-2 (filler-suppress in CRITICAL_VERIFY/KEY_QUESTIONS): `filler.suppressed_intake phase=key_questions` and `phase=critical_verify` lines fire correctly.
- Fix-A1 (cardiac short-circuit ambiguous→third-party-only): cardiac latched correctly at TURN 7 (`cardiac=True third_party=True`).
- Fix-A3 (`_intent_in_verify` calls `_direct_question_intent`): wired but ineffective for Bug 1 because the router itself doesn't recognize the question class.
- Fix-C3 (spelled-cardinal normalizer): TURN 1 had `address_known=True` after caller len=29, so the normalizer is doing its job.

The three bugs in this report are NEW failure modes exposed BECAUSE cycle-2M2 fixed the upstream issues — the call now reaches CRITICAL_VERIFY cleanly, exposing the negation gap. Without 2M2 it would have failed earlier.

---

## What we did NOT find

- No double-emission per turn (cycle-2L StopResponse holding).
- No `fsm.transition` cascade calls (one per `on_user_turn_completed`).
- No gate decision drift (every caller turn → exactly one `response_gate.decision`).
- No transcript-pane regression (publish_turn + publish_reply both fire — cycle-2T2 wiring intact).
