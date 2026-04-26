# Cycle-2D2 — Team RCA — Fix Candidates

Format: file:line, diff, risk, rollback. All proposals are READ-ONLY; do not edit the FSM in this RCA.

---

## Bug 1 — preserve trauma context across cardiac short-circuit

The literal Bug-1 framing ("cardiac on a car-accident") is a misread of the live trace — the cardiac latch fired on turn 3 ("she's not breathing"), not turn 1. So the regex `_RE_NOT_BREATHING` is not the actual bug.

The genuine bug is the silent **complaint flip from `trauma` → `medical`** when the cardiac short-circuit re-runs the complaint discriminator on a turn that has `not_breathing=True` but no `trauma=True`. We need to preserve the prior trauma context.

### Candidate 1A — sticky-trauma latch (recommended)

`agents/livekit/dispatcher_fsm.py:497-506` — the complaint-assignment block.

Current:
```python
        if f.has_emergency:
            self.emergency_known = True
            if f.fire:
                self.complaint = "fire"
            elif f.trauma:
                self.complaint = "trauma"
            else:
                self.complaint = "medical"
```

Proposed:
```python
        if f.has_emergency:
            self.emergency_known = True
            # Cycle-2D2 (B1-A): trauma is sticky once latched. Subsequent turns
            # that introduce a medical cue (e.g. "not breathing") on a known-
            # trauma victim represent dual-rail (traumatic arrest) — preserve
            # both the cardiac short-circuit AND the trauma context so future
            # KQ branching can re-engage hemorrhage/safe-location flows.
            if f.fire:
                self.complaint = "fire"
            elif f.trauma:
                self.complaint = "trauma"
            elif self.complaint != "trauma":
                # Only flip to 'medical' if not already on a trauma rail.
                self.complaint = "medical"
```

Plus, in `_record()` (line 718-754), add a new telemetry field `traumatic_arrest=bool(self.is_cardiac_arrest and self.complaint == "trauma")` so the dual-rail nature surfaces in logs.

**Risk:**
- A caller who initially mentions a generic word that hits `_RE_TRAUMA` ("My friend fell") and then clarifies "actually, it's a stroke" would have their complaint pinned to trauma. Mitigation: only PINs in cases where trauma was set on a turn ≠ 1 — but that's brittle. Simpler alternative: keep the sticky-trauma latch and accept the false-positive cost; falls remain trauma even if the medical cue arrives later, which is medically defensible (mechanism-of-injury triage).
- KQ_BLEEDING_LOCATION may not be appropriate for the actual injury pattern. Mitigation: this is a TELEMETRY fix, not a KQ-routing fix — the cardiac short-circuit still wins, and the trauma context only re-engages when the FSM exits CRITICAL_VERIFY/CRITICAL_CPR.

**Rollback:** revert the `elif self.complaint != "trauma":` to `else:`. Single 1-line change.

### Candidate 1B — defer cardiac short-circuit on first trauma turn (NOT recommended for ship)

Add a guard in the cardiac short-circuit (line 532-551): if `self.complaint == "trauma"` AND this is the first turn after `complaint=trauma` was set AND `positive_arrest_cue=True`, require a SECOND positive-cue confirmation on the next turn before jumping to `CRITICAL_VERIFY`.

```python
        # Cycle-2D2 (B1-B): on a known trauma rail, require two consecutive
        # positive arrest cues before short-circuiting. Single-cue path on
        # trauma is too aggressive — caller hesitation / stutter / agonal-
        # gasp confusion benefits from a verification turn.
        trauma_double_check = (
            self.complaint == "trauma"
            and not getattr(self, "_pending_arrest_confirm", False)
        )
        if positive_arrest_cue and trauma_double_check:
            self._pending_arrest_confirm = True
            return self._intent_in_key_questions(f, t0)  # stay in trauma KQs one more turn
        if positive_arrest_cue and getattr(self, "_pending_arrest_confirm", False):
            self._pending_arrest_confirm = False
            should_jump_to_verify = True
```

**Risk:** delays compressions by one full turn (~5–10 s) on a real traumatic arrest. **This is a life-safety regression.** The AHA T-CPR guidance is "verify before instruct" — adding a second verification step contradicts that.

**Recommendation: do NOT ship Candidate 1B.** Ship 1A only.

**Rollback:** delete the `_pending_arrest_confirm` block.

---

## Bug 2 — floor-negation regex undercoverage

### Candidate 2A — extend `_RE_FLOOR_NEGATION` to outdoor + bare-no surfaces (recommended)

`agents/livekit/dispatcher_fsm.py:180-187` — `_RE_FLOOR_NEGATION`.

Current:
```python
_RE_FLOOR_NEGATION = re.compile(
    r"\b(?:in (?:a |the )?(?:chair|recliner|car seat|bed|couch|sofa|wheelchair)|"
    r"sitting (?:up|on|in)|seated|standing|upright|slumped|"
    r"on the (?:couch|sofa|bed)|in (?:his|her|their) (?:chair|bed)|"
    r"not (?:on the floor|flat|laying down)|"
    r"can'?t (?:move|get) (?:him|her|them))\b",
    re.IGNORECASE,
)
```

Proposed:
```python
_RE_FLOOR_NEGATION = re.compile(
    r"\b(?:in (?:a |the )?(?:chair|recliner|car seat|bed|couch|sofa|wheelchair|car|vehicle)|"
    r"sitting (?:up|on|in)|seated|standing|upright|slumped|"
    r"on the (?:couch|sofa|bed|street|sidewalk|pavement|asphalt|concrete|"
    r"road|grass|lawn|dirt|ground outside|porch|stairs|staircase|stairwell)|"
    r"in (?:his|her|their) (?:chair|bed|car)|"
    r"in (?:a |the )?(?:parking lot|parking garage|driveway|alley|"
    r"garage|garden|yard|hallway|stairwell)|"
    r"behind the wheel|on the steering wheel|"
    r"outside(?: on| at| in)?|"
    r"not (?:on the floor|flat|laying down)|"
    r"can'?t (?:move|get) (?:him|her|them))\b",
    re.IGNORECASE,
)
```

**Risk:**
- "On the street" semantically IS a hard floor surface. The reposition template ("move them flat on the floor, on their back") still applies to ensure flat-on-back, so the instruction is medically appropriate even on a sidewalk. **Physician sign-off required (Brandon Dent, MD)** — recommended default: treat all outdoor surfaces as floor_negation; the reposition template is conservative.
- "Outside" alone may be too aggressive — caller could say "He fell outside, on the patio" where the patient is already on a flat surface. Mitigation: anchor "outside" with `(?:on|at|in)?` and rely on the dispatcher's reposition template being a no-op when patient is already prone.
- The expanded pattern increases regex compile size from ~250 chars to ~450 chars. Compile cost is paid once at import. Match cost on 30-char utterances is sub-microsecond.

**Rollback:** revert to the original 6-line regex; one-shot diff.

### Candidate 2B — bare-no surface-negation feature (recommended; pairs with 2A)

This catches the "No." / "Nope." / "No, he's on the X" cases where the regex cannot infer surface negation from the utterance alone — it requires the FSM's prior intent context.

`agents/livekit/dispatcher_fsm.py:640-690` — inside `_intent_in_verify`, before the existing `f.floor_negation` check.

Add a new module-level regex near the other regexes (~line 235):
```python
# Cycle-2D2 (B2-B): bare-no surface negation. Caller answers "No" / "Nope" /
# "Negative" to a VERIFY_SURFACE question. The bare-no signal alone (without
# a positive surface keyword) does not match _RE_FLOOR_NEGATION but is a
# strong intent-driven floor-negation cue. Combined with a negative
# lookahead for breathing keywords so "No, he's breathing" does NOT
# trigger reposition.
_RE_BARE_NO_SURFACE = re.compile(
    r"^\s*(?:no+|nope|negative|nah|uh[- ]?uh)\b"
    r"(?!.*\b(?:breath|pulse|responsive|responding|awake|conscious|alert|"
    r"gasping|moving|alive|talking|crying)\b)",
    re.IGNORECASE,
)
```

Then in `_intent_in_verify` (line 640), after the floor_flat/floor_negation checks, add:

```python
        # Cycle-2D2 (B2-B): intent-aware bare-no detection. If the FSM just
        # asked VERIFY_SURFACE and the caller's reply opens with "no" /
        # "nope" / "negative" AND does not mention breathing / pulse /
        # responsiveness, treat it as floor_negation regardless of whether
        # _RE_FLOOR_NEGATION matched. This covers "No, he's on the street",
        # "Nope.", "No he is not", and other context-driven negations.
        if (not self.surface_confirmed
                and self.last_intent == Intent.VERIFY_SURFACE
                and _RE_BARE_NO_SURFACE.match(utterance)
                and not f.floor_flat):
            f.floor_negation = True  # mutate the local Features view
```

NOTE: this requires `_intent_in_verify` to receive `utterance` — currently it only receives `f` and `t0`. Either (a) plumb `utterance` through, or (b) lift the check into `transition()` and set `f.floor_negation = True` before dispatching to `_intent_in_verify`. Option (b) is the smaller diff.

**Smaller diff (option b):** in `transition()` near line 540, after `should_jump_to_verify` is computed and before the cardiac branch returns, add:

```python
        # Cycle-2D2 (B2-B): intent-aware bare-no surface negation. Lifts
        # the check from _intent_in_verify so it sees the raw utterance.
        if (self.last_intent == Intent.VERIFY_SURFACE
                and self.state == State.CRITICAL_VERIFY
                and not self.surface_confirmed
                and _RE_BARE_NO_SURFACE.match(utterance)
                and not f.floor_flat):
            f.floor_negation = True
```

**Risk:**
- "No, he's actually breathing fine" → caught by the negative lookahead, returns False. Verified by repro.
- "No, he is on the floor" → unusual phrasing; the negative lookahead won't filter, and floor_flat would also match, so the `not f.floor_flat` guard prevents the misroute.
- "Nope, on the street" → triggers floor_negation correctly. Without 2A, the reposition template still fires; with 2A, the regex would also match. Both paths converge on the right intent.
- Only fires on the turn IMMEDIATELY after VERIFY_SURFACE was emitted. If the caller delays their answer by an intermediate turn (e.g. asks a question first), the `last_intent` will not be VERIFY_SURFACE and the bare-no fix won't fire. Mitigation: rely on _RE_FLOOR_NEGATION extension (2A) to catch the substantive "on the street" / "on the sidewalk" pattern.

**Rollback:** delete the new regex constant + the 7-line block in `transition()`. Two-spot revert.

### Recommended ship set

- **2A + 2B together.** They are complementary: 2A covers substantive surface keywords, 2B covers context-driven bare-no replies. Either alone leaves a gap.
- **1A standalone.** It is purely a telemetry/context-preservation change; no behavior shift in the cardiac path.
- **Skip 1B.** Adds a turn of latency to compressions on real traumatic arrest. Not worth the corner case.

---

## Verification before any ship

1. Run `python3 -c "from agents.livekit.dispatcher_fsm import classify; ..."` against the synthetic test scenarios in `verification-plan.md`. All scenarios must pass.
2. Diff-only ship: confirm only the targeted regex constants and `transition()` block change. No template text changes, no FSM control-flow refactor.
3. Physician sign-off (Brandon Dent, MD) on Bug 2's "outside surfaces are floor_negation" decision — the reposition template is medically sound regardless of substrate, but the ship gate per CLAUDE.md §10 is physician sign-off on every life-safety code path.
