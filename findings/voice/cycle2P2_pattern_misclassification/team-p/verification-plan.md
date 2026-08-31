# Cycle-2P2 Verification plan — test cases per fix

Author: Team P · Date: 2026-04-26 · Status: research-only, no code changes

This is the test matrix the integrator should add to `tests/voice/` BEFORE
applying any of the fix candidates in `fix-candidates.md`. Each row is a
caller utterance, the FSM state expected after `transition()`, and the
fix candidate(s) it exercises.

The harness pattern to follow is in `tests/voice/test_response_gate.py` —
construct a `DispatcherFSM`, call `transition(utterance)`, assert on the
returned `Intent` AND on the FSM's facts (`address_known`, `is_cardiac_arrest`,
`complaint`, etc.).

## Test fixture: `tests/voice/test_dispatcher_fsm_p2.py` (proposed)

```python
import pytest
from dispatcher_fsm import DispatcherFSM, Intent, State

@pytest.fixture
def fsm():
    return DispatcherFSM()
```

## A. Address-capture cases (B1 / C3 fix coverage)

| # | Caller utterance | Expected after one turn | Exercises |
|---:|---|---|---|
| A-01 | `"100 Ocean Avenue"` | `address_known=True`, `intent in (request_emergency, request_location_and_emergency)` | baseline (passes today) |
| A-02 | `"One hundred Ocean Avenue"` | `address_known=True` | baseline (passes today via Avenue) |
| A-03 | `"One hundred ocean of new"` | `address_known=True` | **FAILS today**; B1 (ITN) or C3 (spelled-cardinal normalizer) fixes |
| A-04 | `"5012 East River Road, apartment 2B"` | `address_known=True` | baseline (passes today via digit) |
| A-05 | `"Twelve Riverside"` | `address_known=True` | **FAILS today**; B1/C3 fixes (12 -> digit) |
| A-06 | `"Twenty Lakeside"` | `address_known=True` | **FAILS today**; B1/C3 fixes |
| A-07 | `"My address is 200"` (just digits, no street) | `address_known=True` | passes (digit fires) |
| A-08 | `"Apartment 2B"` (apt only, no street) | `address_known=True` (current behavior) OR `address_known=False` (tightened) | shows current over-fire on apt-only |

## B. Cardiac false-positive cases (A1 fix coverage)

| # | Caller utterance | Expected after one turn | Exercises |
|---:|---|---|---|
| B-01 | `"My friend stopped breathing"` | `is_cardiac_arrest=True`, `intent=verify_cpr_surface` | baseline (passes today, must continue to pass) |
| B-02 | `"He's not responding"` (no third-party prior) | A1: stays in INTAKE / KQ; today: jumps to CRITICAL_VERIFY | A1 fix |
| B-03 | `"My neighbor isn't responding to my texts"` | `is_cardiac_arrest=False`, stays in INTAKE | A1 + general regex tightening |
| B-04 | `"I'm not breathing fast enough"` (first-person caller) | `is_cardiac_arrest=False`, route to `kq_severity` | A1 fix (first-person guard) |
| B-05 | `"I can't breathe"` (first-person) | `is_cardiac_arrest=False`, route to `kq_severity` | A1 fix |
| B-06 | `"unresponsive"` (single-word context-free) | A1: stays put; today: jumps to CRITICAL_VERIFY | A1 fix |
| B-07 | `"My phone won't wake up"` | `is_cardiac_arrest=False` | A1 fix |
| B-08 | `"He's not breathing well"` (positive cue, third-party from "he") | `is_cardiac_arrest=True` | baseline + A1 (positive cue branch) |

## C. Complaint stickiness (A2 fix coverage)

| # | Sequence (multi-turn) | Expected end state | Exercises |
|---:|---|---|---|
| C-01 | T1: `"there's been a shooting"` (trauma) <br> T2: `"and he stopped breathing"` | `complaint=trauma` (not overwritten) | A2 fix |
| C-02 | T1: `"there's a fire"` <br> T2: `"and someone got hit by debris"` | `complaint='fire'` (fire higher priority than trauma) | A2 design |
| C-03 | T1: `"my husband fell"` (trauma latched) <br> T2: `"and he's bleeding"` | `complaint=trauma`, route to `kq_bleeding_location` | baseline |
| C-04 | T1: `"chest pain"` (medical) <br> T2: `"on the floor"` | `complaint=medical` (no trauma signal in T2) | baseline |

## D. Direct-question router in CRITICAL_VERIFY (A3 fix coverage)

| # | State entry | Caller utterance | Expected intent | Exercises |
|---:|---|---|---|---|
| D-01 | already in CRITICAL_VERIFY | `"Should I move him?"` | `answer_do_not_move` | A3 fix |
| D-02 | already in CRITICAL_VERIFY | `"How long until they get here?"` | `answer_how_long` | A3 fix |
| D-03 | already in CRITICAL_VERIFY | `"Will he be OK?"` | `answer_outcome_uncertain` | A3 fix |
| D-04 | already in CRITICAL_VERIFY | `"What did you hear me say?"` | (already-failing today) — no route, repeats `verify_cpr_surface` | A3 partial fix; also a hint that the question router needs broader patterns |

## E. End-to-end Test 3 reproducer (the user-attested bug)

A multi-turn integration test that mirrors the real session b4880122:

```python
def test_test3_reproducer_after_fixes(fsm):
    # T1: STT mis-heard the address.
    intent1 = fsm.transition("One hundred ocean of new.")
    # WITH B1/C3 fix: address_known should now be True (ITN converts to "100").
    assert fsm.address_known, "B1/C3 should latch address from spelled-cardinal"

    # T2: Caller repeats more clearly.
    intent2 = fsm.transition("One hundred Ocean Avenue.")
    assert fsm.address_known
    assert intent2 == Intent.REQUEST_EMERGENCY  # or CONFIRM_ADDRESS

    # T3: Caller hesitates.
    intent3 = fsm.transition("Uh my")
    # Should NOT be CRITICAL_VERIFY.
    assert fsm.state != State.CRITICAL_VERIFY

    # T4: Caller reports actual cardiac event.
    intent4 = fsm.transition("My husband's not breathing.")
    assert fsm.is_cardiac_arrest
    assert intent4 == Intent.VERIFY_SURFACE
```

## F. End-to-end Test 4 reproducer (cardiac scenario, currently passes)

```python
def test_test4_reproducer_cardiac(fsm):
    # T1: address.
    fsm.transition("Uh one hundred Ocean Avenue.")
    assert fsm.address_known
    # T2: trauma + cardiac signal in one breath.
    intent2 = fsm.transition(
        "There has been a shooting and uh there are um some people dead "
        "and uh my friend was shot in the chest and he's not breathing good."
    )
    assert fsm.is_cardiac_arrest
    # AFTER A2 fix: complaint should be 'trauma' not 'medical'.
    assert fsm.complaint == "trauma", "A2 sticky-trauma fix"
    assert intent2 == Intent.VERIFY_SURFACE  # cardiac short-circuit wins

    # T3: caller asks a question mid-verify.
    intent3 = fsm.transition("What did you hear me say?")
    # AFTER A3 fix: should NOT just repeat verify_cpr_surface.
    # (Note: "What did you hear me say?" doesn't match any direct-question
    # regex today — A3 also benefits from broadening _RE_*_Q surfaces.)
```

## G. Regex-test fixtures (cheap, no FSM construction needed)

These hot-path tests catch regex regressions without spinning up the full
FSM. Add to `tests/voice/test_dispatcher_fsm_p2.py`:

```python
from dispatcher_fsm import classify

@pytest.mark.parametrize("utterance,expected", [
    ("100 Ocean Avenue", {"has_address": True}),
    ("One hundred ocean of new", {"has_address": False}),  # documents bug
    ("My friend stopped breathing", {"not_breathing": True, "is_third_party": True}),
    ("I can't breathe", {"not_breathing": True, "is_first_person": True}),
    ("My neighbor isn't responding to my texts", {"not_breathing": False}),
    ("on the back of the truck", {"floor_flat": True}),  # documents over-fire
    ("blood pressure is 130 over 80", {"bleeding": True}),  # documents over-fire
])
def test_classify_regression(utterance, expected):
    f = classify(utterance)
    for attr, want in expected.items():
        got = getattr(f, attr)
        assert got == want, f"{utterance!r}: {attr}={got}, want {want}"
```

## H. Pod-side smoke (B1/B2 only)

These run against the live Parakeet service. Read-only.

```bash
# B1 (ITN) smoke — the integrator runs this AFTER B1 ships.
ssh b300-pod 'curl -s -X POST \
  http://127.0.0.1:9100/transcribe \
  -H "Content-Type: audio/wav" \
  --data-binary @/path/to/one_hundred_ocean.wav | jq .text'
# Expected: "100 Ocean Avenue" or close.

# B2 (GPU-PB) smoke — bench delta.
ssh b300-pod 'cd /opt/prism42/agents/livekit && \
  .venv/bin/python bench_b300.py --runs 10 --utt "100 Ocean Avenue"'
# Expected: p95 delta vs baseline within +20 ms; "Avenue" stability up.
```

## What success looks like

Per Brandon Dent, MD: "this website will be beta tested by numerous people
with no predetermined scripts." The fix is successful when:

1. **A-01 / A-02 / A-03 / A-04 / A-05 all pass** (addresses with or without
   spelled cardinals AND with or without clean street suffixes latch on
   turn 1).
2. **B-02 / B-03 / B-04 / B-05 / B-06 / B-07 all pass** (cardiac short-
   circuit no longer fires on social-context "not responding" or
   first-person caller distress).
3. **E (Test 3 reproducer) passes** end-to-end.
4. **No regression on B-01 / B-08 / F (Test 4)** — real cardiac arrests
   still latch and route correctly.
5. **Pod bench p95 +/- 25 ms vs current** (no STT slowdown shipped).

If those five hold, beta-test risk drops materially.
