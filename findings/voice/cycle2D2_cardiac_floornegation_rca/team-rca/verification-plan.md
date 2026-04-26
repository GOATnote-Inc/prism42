# Cycle-2D2 — Team RCA — Verification Plan

Synthetic test scenarios for the 4 fix candidates. All scenarios run against
`agents/livekit/dispatcher_fsm.py` post-fix; current behavior is captured as
baseline so ship/no-ship is measurable.

## How to run

```bash
cd /Users/kiteboard/prism42
python3 -m pip install --break-system-packages structlog --quiet
python3 - <<'PY'
import sys
sys.path.insert(0, 'agents/livekit')
from dispatcher_fsm import classify, DispatcherFSM, Intent, State

# ... per-scenario asserts below
PY
```

Or wire into `agents/livekit/critic_eval_harness.py` as four new fixtures
(out of scope for this RCA; recommended for the ship cycle).

---

## Bug 1 — trauma-context preservation (Candidate 1A)

### Scenario 1A-1 — live user case: car accident → not breathing

```python
fsm = DispatcherFSM()
fsm.transition("Uh 100 Ocean Avenue. My my friend's been in a car accident. "
               "Will you send some people? He's not he's not, he doesn't seem "
               "like he's doing good.")
assert fsm.complaint == "trauma"
assert fsm.is_cardiac_arrest is False
assert fsm.state == State.ADDRESS_CONFIRMED

fsm.transition("Okay, okay.")  # backchannel turn
# Should land in REASSURANCE_DELIVERED, complaint still "trauma"
assert fsm.complaint == "trauma"

fsm.transition("Okay, thanks. He he doesn't she's not breathing.")
# CURRENT BEHAVIOR: complaint flips to "medical", traumatic context lost.
# POST-FIX (1A): complaint stays "trauma", cardiac latches True (dual-rail).
assert fsm.is_cardiac_arrest is True
assert fsm.complaint == "trauma"   # KEY ASSERTION (will fail before fix)
assert fsm.state == State.CRITICAL_VERIFY
```

### Scenario 1A-2 — pure medical (no regression)

```python
fsm = DispatcherFSM()
fsm.transition("123 Main Street. My husband is having chest pain.")
fsm.transition("Okay.")
fsm.transition("He just stopped breathing.")
assert fsm.is_cardiac_arrest is True
assert fsm.complaint == "medical"  # baseline; no trauma cue ever seen
```

### Scenario 1A-3 — fall + arrest (pre-existing trauma should pin)

```python
fsm = DispatcherFSM()
fsm.transition("456 Oak Drive. My dad fell down the stairs.")
assert fsm.complaint == "trauma"
fsm.transition("He's not responding.")  # ambiguous_arrest_cue + third_party
# Per Team-P A1 gate, this should latch cardiac via ambiguous-cue + 3rd party
assert fsm.is_cardiac_arrest is True
assert fsm.complaint == "trauma"   # KEY ASSERTION post-fix
```

---

## Bug 2 — floor-negation extension (Candidates 2A + 2B)

### Scenario 2A-1 — live user case: "No, he's on the street."

```python
fsm = DispatcherFSM()
# Set up to CRITICAL_VERIFY state.
fsm.transition("100 Ocean Avenue. My friend's been in a car accident.")
fsm.transition("Okay.")
fsm.transition("She's not breathing.")
assert fsm.last_intent == Intent.VERIFY_SURFACE

intent = fsm.transition("No, he's on the street.")
# CURRENT BEHAVIOR: re-emit VERIFY_SURFACE (regex miss).
# POST-FIX (2A or 2B): emit INSTRUCT_CPR_REPOSITIONING.
assert intent == Intent.INSTRUCT_CPR_REPOSITIONING   # KEY ASSERTION
assert fsm._reposition_emits == 1
```

### Scenario 2A-2 — outdoor surfaces (each must trigger reposition)

```python
for utterance in [
    "He's on the sidewalk.",
    "On the pavement.",
    "He's on the grass in the backyard.",
    "On the lawn.",
    "He's on the asphalt.",
    "On concrete.",
    "He's in the parking lot.",
    "Outside on the porch.",
    "On the stairs.",
    "In the driveway.",
    "Behind the wheel.",
]:
    fsm = DispatcherFSM()
    fsm.transition("100 Main Street. He stopped breathing.")
    intent = fsm.transition(utterance)
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING, f"failed: {utterance!r}"
```

### Scenario 2B-1 — bare-no replies

```python
for utterance in ["No.", "Nope.", "No, ", "Negative.", "Nah.", "Uh-uh."]:
    fsm = DispatcherFSM()
    fsm.transition("100 Main Street. He stopped breathing.")
    assert fsm.last_intent == Intent.VERIFY_SURFACE
    intent = fsm.transition(utterance)
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING, f"failed: {utterance!r}"
```

### Scenario 2B-2 — bare-no with breathing context (must NOT misroute)

```python
fsm = DispatcherFSM()
fsm.transition("100 Main Street. He stopped breathing.")
intent = fsm.transition("No, he's actually breathing now.")
# Bare-no negative-lookahead filters this — must NOT route to reposition.
assert intent != Intent.INSTRUCT_CPR_REPOSITIONING

fsm = DispatcherFSM()
fsm.transition("100 Main Street. He stopped breathing.")
intent = fsm.transition("No, he has a pulse.")
assert intent != Intent.INSTRUCT_CPR_REPOSITIONING
```

### Scenario 2B-3 — true negative (caller affirms floor)

```python
fsm = DispatcherFSM()
fsm.transition("100 Main Street. He stopped breathing.")
intent = fsm.transition("Yes, he's on the floor flat on his back.")
# floor_flat=True → surface_confirmed → next intent is VERIFY_BREATHING
assert intent == Intent.VERIFY_BREATHING
assert fsm.surface_confirmed is True
```

---

## Regression scenarios (must not break)

### R-1 — chair / bed cases (existing 2R3 path)

```python
for utterance in [
    "He's in a chair.",
    "He's on the couch.",
    "She's sitting up in bed.",
    "He's slumped over.",
    "He's standing.",
]:
    fsm = DispatcherFSM()
    fsm.transition("100 Main Street. He stopped breathing.")
    intent = fsm.transition(utterance)
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING, f"regression on {utterance!r}"
```

### R-2 — backchannel guard (existing 2R3 B2-A path)

```python
fsm = DispatcherFSM()
fsm.transition("100 Main Street. He stopped breathing.")
prior = fsm.last_intent
intent = fsm.transition("Yeah.")  # 5 chars, backchannel
# State = CRITICAL_VERIFY (not in the backchannel-guarded list).
# So bare-no does NOT apply, "yeah" does not trigger anything.
# Intent should fall through to verify_cpr_surface re-emit.
assert intent == Intent.VERIFY_SURFACE
```

### R-3 — direct-question priority (Team-P A3 path)

```python
fsm = DispatcherFSM()
fsm.transition("100 Main Street. He stopped breathing.")
intent = fsm.transition("How long until they get here?")
# Direct question takes priority over re-emitting verify.
assert intent == Intent.ANSWER_HOW_LONG
```

### R-4 — Bug-1 fix does not interfere with non-trauma path

```python
fsm = DispatcherFSM()
fsm.transition("100 Main Street. My husband has chest pain.")
assert fsm.complaint == "medical"
fsm.transition("He stopped breathing.")
assert fsm.complaint == "medical"  # no trauma, stays medical
```

---

## Pre-ship checklist

- [ ] All 1A scenarios pass.
- [ ] All 2A scenarios pass.
- [ ] All 2B scenarios pass (including negative-lookahead R-2B-2).
- [ ] All R-1 to R-4 regression scenarios pass.
- [ ] `agents/livekit/critic_eval_harness.py` re-run with 4 new fixtures added.
- [ ] Worker log replay against the live RM_9dQUQKjdSsmA session shows:
  - turn 3 emits `verify_cpr_surface` AND `complaint=trauma` (post-1A).
  - turn 4 emits `instruct_cpr_repositioning` (post-2A or 2B).
- [ ] Physician sign-off (Brandon Dent, MD) per CLAUDE.md §10 — flag the
  outdoor-surface decision as the load-bearing physician call.

## Live re-test plan

After ship:
1. ssh prism-mla-b300-h4h5
2. Place a synthetic test call via the public LiveKit room.
3. Speak the verbatim user-attestation utterances:
   - "Uh 100 Ocean Avenue. My friend's been in a car accident. Will you send some people? He's not he's not, he doesn't seem like he's doing good."
   - "Okay, okay."
   - "Okay, thanks. He he doesn't she's not breathing."
   - "No, he's on the street."
4. Inspect `/tmp/prism42-logs/worker.log`:
   - Turn 1 fsm.transition shows `complaint=trauma`.
   - Turn 3 fsm.transition shows `cardiac=True complaint=trauma` (post-1A).
   - Turn 4 fsm.transition shows `intent=instruct_cpr_repositioning reposition_emits=1` (post-2A/2B).
5. Confirm dispatcher response on turn 4 reads "Move them flat on the floor, on their back. Compressions cannot start on a chair or bed." instead of repeating "Are they on the floor, flat on their back?".

## Rollback plan

- 1A: revert single-line change (`elif self.complaint != "trauma":` → `else:`).
- 2A: revert the entire `_RE_FLOOR_NEGATION` regex constant to prior value.
- 2B: delete `_RE_BARE_NO_SURFACE` constant and the 7-line `transition()` block.

Each fix is independently revertable. No state-machine schema or template
text changes; behavior reverts deterministically.
