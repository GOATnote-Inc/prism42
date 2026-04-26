# Cycle-2D2 — Team RCA — Diagnosis

Session: `RM_9dQUQKjdSsmA` / `05415707-8b26-08dd-d118-e179eb811998`, B300 pod, 2026-04-26 19:32 UTC.
Source-of-truth: `agents/livekit/dispatcher_fsm.py` HEAD; `/tmp/prism42-logs/worker.log` lines 59100–59700.

## TL;DR

- **Bug 1 ("cardiac on a car-accident") is partially mis-attributed.** The cardiac latch did NOT fire on the trauma turn. It fired one turn later, on **caller turn 3** ("Okay, thanks. He he doesn't she's not breathing."), where the literal phrase "not breathing" is a true positive arrest cue. The user attestation showed cumulative LATCHED FACTS at the time of inspection (post-turn-3), not a turn-1 mis-fire.
- **The genuine Bug 1 is one level up:** the FSM's complaint-state silently flipped `trauma → medical` on turn 3 because `_RE_NOT_BREATHING.search` set `has_emergency=True` again, re-running the complaint discriminator. Trauma context was lost, so when the patient is verified as breathing (or LLM cannot get an answer) the FSM has no path back to trauma-specific KQs (`KQ_BLEEDING_LOCATION`, `KQ_SAFE_LOCATION`).
- **Bug 2 is real and clear-cut.** Turn 4 caller said "No, he's on the street." `_RE_FLOOR_NEGATION` did not match (regex covers chair/bed/couch/sitting but not outdoor surfaces or bare-no replies). FSM re-emitted `verify_cpr_surface` template instead of routing to `INSTRUCT_CPR_REPOSITIONING`.

## Bug 1 — full trace

### Live evidence (worker.log)

```
19:32:03  user: "Uh 100 Ocean Avenue. My my friend's been in a car accident. Will you send some
                 people? He's not he's not, he doesn't seem like he's doing good."
19:32:03  fsm.transition  state=address_confirmed  cardiac=False  complaint=trauma  intent=confirm_address  third_party=True

19:32:13  user: "Okay, okay."
19:32:14  fsm.transition  state=reassurance_delivered  cardiac=False  complaint=trauma  intent=deliver_reassurance

19:32:26  user: "Okay, thanks. He he doesn't she's not breathing."
19:32:26  fsm.transition  state=critical_verify  cardiac=True  complaint=medical  intent=verify_cpr_surface

19:32:34  user: "No, he's on the street."
19:32:34  fsm.transition  state=critical_verify  cardiac=True  reposition_emits=0  intent=verify_cpr_surface  (REPEAT)
```

### Local repro of `classify()`

```
TURN 1 utterance:
  not_breathing = False        <- regex correctly does NOT match the stutter "he's not he's not"
  trauma        = True
  third_party   = True
TURN 3 utterance:
  not_breathing = True         <- regex correctly matches the literal "not breathing"
  match span: 'not breathing'
```

So `_RE_NOT_BREATHING` is **already tight enough on the turn-1 stutter case**. The Team-P A1 short-circuit gate (line 532) is also working: `positive_arrest_cue=True` on turn 3, branch fires deterministically.

### Where the trauma-context loss happens (line by line)

| File:line | Code | Effect on this scenario |
|-----------|------|--------------------------|
| `dispatcher_fsm.py:497-506` | `if f.has_emergency:  self.emergency_known = True; if f.fire: complaint='fire'  elif f.trauma: complaint='trauma'  else: complaint='medical'` | Turn 3 utterance has `trauma=False, fire=False`, so `complaint` is **overwritten to `medical`**, dropping the prior `complaint=trauma` latch. |
| `dispatcher_fsm.py:508-551` | Cardiac short-circuit gate. Sets `is_cardiac_arrest=True`, `state=CRITICAL_VERIFY` whenever `positive_arrest_cue` matches, regardless of complaint context. | Hard-jumps the FSM to the cardiac mini-FSM. There is no consideration that the prior `complaint` was `trauma`, no protection for the trauma KQ branch. |

The user's intuition is correct **but at one level up from the regex**: the cardiac short-circuit is too eager when prior complaint is `trauma` AND third-party caller. A car-accident victim who "doesn't seem like doing good" then "isn't breathing" might still be **traumatic arrest** — but T-CPR on a trauma victim has different priorities (C-spine consideration, hemorrhage control before compressions). A pure "verify surface + verify breathing → start compressions" track misses bleeding control and KQ_SAFE_LOCATION.

The MPDS-9 verify gate is still appropriate (life-safety: do not start compressions on a chair/bed). The fix is to **preserve `complaint=trauma`** through the cardiac branch so that:
1. Trauma-aware framing in subsequent KQ phases can re-engage.
2. Telemetry shows the dual-rail nature of the call (cardiac+trauma).
3. Future Phase-3 fusion can route to compression+bleeding-control coaching.

### Munger inversion — what could a tightening break?

- If we tighten `_RE_NOT_BREATHING` further (e.g. require "breathing" within 3 words of negation), we risk **missing** the Spanish-influenced English phrasing "she no breath" or aphasic dispatch ("no breath, no pulse"). Current regex already accepts both `no pulse` and `not responding` — removing those would degrade detection.
- If we add `is_trauma_dominant` gating (skip cardiac short-circuit if `complaint==trauma`), we risk **blocking compressions** in a pure traumatic arrest where the patient genuinely needs CPR. Field protocols (NAEMSP 2024) DO support CPR in blunt traumatic arrest after airway/hemorrhage, so we cannot suppress the verify gate; we can only **preserve trauma context** alongside it.

## Bug 2 — full trace

### Live evidence

```
19:32:34  user: "No, he's on the street."
19:32:34  fsm.transition  intent=verify_cpr_surface  reposition_emits=0  surface_confirmed=False
19:32:34  response_gate.decision  final_text='Are they on the floor, flat on their back?'  used_template=True
```

The dispatcher repeated the same surface-verify template. **`reposition_emits` stayed at 0**, which proves `f.floor_negation=False` — the regex did not match.

### Local repro of `_RE_FLOOR_NEGATION`

```
"No, he's on the street."        floor_negation=False
"No."                            floor_negation=False
"Nope."                          floor_negation=False
"On the sidewalk."               floor_negation=False
"He is on the grass."            floor_negation=False
"On concrete."                   floor_negation=False
"Outside, in the parking lot."   floor_negation=False
"On the lawn."                   floor_negation=False
```

### Root cause

`_RE_FLOOR_NEGATION` (`dispatcher_fsm.py:180-187`) was authored against the canonical chair/bed/couch/sitting/standing distress pattern. The regex covers:

- `in (a|the) (chair|recliner|car seat|bed|couch|sofa|wheelchair)`
- `sitting (up|on|in) | seated | standing | upright | slumped`
- `on the (couch|sofa|bed)` or `in (his|her|their) (chair|bed)`
- `not (on the floor|flat|laying down)`
- `can't (move|get) (him|her|them)`

It does NOT cover:

1. **Bare-no replies** to a verify-surface question. "No." / "Nope." / "Negative." with the FSM in `state=CRITICAL_VERIFY, verify_step=Q_SURFACE` is a strong, intent-driven negation signal that the surface regex cannot infer from text alone.
2. **Outdoor / non-canonical surfaces.** `street`, `sidewalk`, `pavement`, `parking lot`, `parking garage`, `outside`, `grass`, `lawn`, `dirt`, `concrete`, `asphalt`, `road`. None of these are chairs/beds, so the regex misses them. For CPR, hard surfaces (street, concrete, sidewalk, asphalt) are technically acceptable — but soft surfaces (grass, lawn, dirt, mud, snow) are NOT. Treating all of them as `floor_negation` is the safer default; the dispatcher will instruct repositioning to a known-flat-and-firm surface, which is the conservative life-safety call.
3. **Vehicle surfaces.** "In the car", "in the seat", "behind the wheel" — partially covered (`car seat`, `in (a|the) chair`) but not "in the car" or "behind the wheel".

### Why the bare-no fix is high-leverage

The FSM already knows it just emitted `VERIFY_SURFACE`. A turn that begins with `^(no|nope|negative|nah)` while `state=CRITICAL_VERIFY AND verify_step=Q_SURFACE` is **almost always a surface-negation**. This is a context-aware signal that the regex cannot derive from the utterance text alone — it requires the dispatcher's prior intent. Adding it as a feature in `transition()` (not in `classify()`) keeps regex pure and adds intent-aware dispatch.

### Munger inversion — what could the bare-no fix break?

- If a caller says "No, he's actually breathing fine" while we are in `Q_SURFACE`, the bare-no regex would still mis-route to repositioning. Mitigation: add a **negative lookahead** for breathing keywords (`breath`, `pulse`, `responsive`, `awake`) so "No, he's breathing" does NOT trigger floor_negation. The regex stays bare-no but the gate is "bare-no AND no breathing-keyword in same utterance".
- Extending `_RE_FLOOR_NEGATION` to include "concrete" / "asphalt" technically negates the floor-flat regex on a SUITABLE hard surface. **Physician decision required** — recommended default: treat all outdoor surfaces as floor_negation and emit `INSTRUCT_CPR_REPOSITIONING` template, which says "move them flat on the floor, on their back". On a sidewalk, the patient IS effectively on the floor; the reposition instruction redundantly tells the caller to ensure flat-on-back, which is what we want regardless of substrate. A physician (Brandon Dent, MD) should sign off on whether to keep the reposition instruction OR to add a parallel `surface_acceptable` template for hard outdoor surfaces. **Default: emit reposition; flag for physician confirmation before ship.**

## Cross-cutting findings

- The **classifier-perception** structured classifier (line `classifier.perception` in worker.log) ALSO returned `intent=reprompt confidence=0.15` on turn 2 ("Okay, okay.") and timed out (`classifier.timeout latency_ms=600`) on turns 1 and 3. The structured classifier was unavailable when the cardiac branch fired — the FSM fell back to its own deterministic regex path, which is the intended graceful-degradation. Out of scope for this RCA, but worth noting that the structured classifier was NOT contributing on the affected turns.
- `_reposition_emits` only ever increments inside `_intent_in_verify` when `f.floor_negation=True`. Since turn 4's classify returned floor_negation=False, the counter stayed at 0 and the heuristic latch (≥3 emits → surface_confirmed=True) never triggered. This is the right design — the heuristic should not advance state on regex misses.
- The `_RE_BACKCHANNEL` guard (line 474) correctly did NOT consume turn 4 ("No, he's on the street.") because the utterance is 23 chars (over the 14-char guard) and does not match the backchannel pattern. The bug is purely floor-negation regex coverage.
