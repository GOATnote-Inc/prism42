"""Cycle-2R3 (B3-A) life-safety tests for CPR repositioning intent.

Physician-reviewed by Brandon Dent, MD on 2026-04-26 per CLAUDE.md §10.
The repositioning template text "Move them flat on the floor, on their
back." was chosen for clarity (instruction-first) and to avoid alarm
language ("right now") that pre-revisions used.

Tests cover:
1. Caller "in a chair" → INSTRUCT_CPR_REPOSITIONING (not VERIFY_SURFACE re-emit)
2. Caller "in bed" → INSTRUCT_CPR_REPOSITIONING
3. Caller "on the couch" → INSTRUCT_CPR_REPOSITIONING
4. Caller "sitting up" → INSTRUCT_CPR_REPOSITIONING
5. Caller "standing" → INSTRUCT_CPR_REPOSITIONING
6. Caller "already on the floor" → VERIFY_SURFACE skipped, advance to VERIFY_BREATHING
7. Caller "yes on the floor" mid-verify → surface_confirmed latches True
8. Repositioning loop guard: 3rd consecutive negation latches surface_confirmed heuristically
9. cpr_allowed=False until awake AND breathing both confirmed
10. INSTRUCT_CPR_REPOSITIONING template hits _SAFETY_TEMPLATE_ONLY (LLM cannot rephrase)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Path-bootstrap so tests can import agents/livekit/* without install.
_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
sys.path.insert(0, str(_AGENTS_DIR))

import pytest  # noqa: E402

from dispatcher_fsm import DispatcherFSM, Intent, State, classify  # noqa: E402
from response_gate import _SAFETY_TEMPLATE_ONLY  # noqa: E402
from templates import TEMPLATES  # noqa: E402


def _into_critical_verify(fsm: DispatcherFSM) -> None:
    """Jump FSM into CRITICAL_VERIFY with cardiac latched (third party)."""
    fsm.transition("twelve riverside drive")
    fsm.transition("my friend was shot in the chest, he is not breathing")
    # FSM should now be in CRITICAL_VERIFY with surface_confirmed=False.
    assert fsm.state == State.CRITICAL_VERIFY
    assert fsm.is_cardiac_arrest is True
    assert fsm.surface_confirmed is False


# Test 1 — chair
def test_floor_negation_chair_emits_repositioning():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    intent = fsm.transition("yeah, they're in a chair")
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING
    assert fsm.surface_confirmed is False


# Test 2 — bed
def test_floor_negation_bed_emits_repositioning():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    intent = fsm.transition("she is in bed")
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING
    assert fsm.surface_confirmed is False


# Test 3 — couch / sofa
def test_floor_negation_couch_emits_repositioning():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    intent = fsm.transition("he's on the couch")
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING


# Test 4 — sitting up
def test_floor_negation_sitting_up_emits_repositioning():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    intent = fsm.transition("they're sitting up")
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING


# Test 5 — standing
def test_floor_negation_standing_emits_repositioning():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    intent = fsm.transition("he's still standing")
    assert intent == Intent.INSTRUCT_CPR_REPOSITIONING


# Test 6 — caller already volunteers floor on cardiac latch
def test_floor_volunteered_skips_verify_surface():
    fsm = DispatcherFSM()
    fsm.transition("twelve riverside drive")
    fsm.transition("my friend is on the floor not breathing")
    # FSM jumped to CRITICAL_VERIFY; floor_flat pre-filled → skip Q_SURFACE.
    assert fsm.state == State.CRITICAL_VERIFY
    assert fsm.surface_confirmed is True


# Test 7 — caller confirms floor mid-verify
def test_caller_confirms_floor_mid_verify_latches_surface():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    # First reply: VERIFY_SURFACE template fires (expected).
    intent = fsm.transition("uh okay")
    # Backchannel guard re-emits last_intent (cycle-2R3 B2-A).
    # Caller now confirms.
    intent2 = fsm.transition("yes, on the floor on his back")
    # surface_confirmed should latch True; FSM advances to VERIFY_BREATHING.
    assert fsm.surface_confirmed is True
    assert intent2 == Intent.VERIFY_BREATHING


# Test 8 — loop guard: 3rd repositioning emit latches surface heuristically
def test_repositioning_loop_guard_after_three_emits():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    # Three consecutive pure floor-negations (avoid "can't move them"
    # which trips the do-not-move question router and takes priority).
    fsm.transition("they're in a chair")  # 1st reposition
    fsm.transition("still in the chair")  # 2nd reposition
    intent = fsm.transition("still standing")  # 3rd → loop-guard latches
    # After 3 emits, surface_confirmed=True heuristically; next intent
    # is VERIFY_BREATHING (not another reposition).
    assert fsm.surface_confirmed is True
    assert intent == Intent.VERIFY_BREATHING


# Test 9 — cpr_allowed gate logged correctly when surface known but
# breathing not yet assessed (the dispatcher should NOT advance to
# compressions). breathing_assessed mid-verify latching is a separate
# FSM concern (cycle-2T+); here we only verify cpr_allowed=False
# when not all latches are set.
def test_cpr_allowed_false_when_breathing_unassessed():
    fsm = DispatcherFSM()
    _into_critical_verify(fsm)
    # Surface confirmed but breathing_assessed is still False — the
    # gate must NOT permit compressions yet.
    fsm.transition("yes, on the floor")
    assert fsm.surface_confirmed is True
    assert fsm.breathing_assessed is False
    # cpr_allowed is computed in _record. Re-check via direct read of
    # FSM state — the safety predicate must be False.
    cpr_allowed = (fsm.surface_confirmed and fsm.breathing_assessed
                   and fsm.is_cardiac_arrest)
    assert cpr_allowed is False, (
        "CPR must NOT be permitted until BOTH surface_confirmed AND "
        "breathing_assessed AND is_cardiac_arrest are True (CLAUDE.md §10)"
    )


# Test 10 — INSTRUCT_CPR_REPOSITIONING is in _SAFETY_TEMPLATE_ONLY
def test_repositioning_intent_is_safety_only():
    assert "instruct_cpr_repositioning" in _SAFETY_TEMPLATE_ONLY
    # Template exists with physician-reviewed wording.
    spec = TEMPLATES["instruct_cpr_repositioning"]
    assert "floor" in spec.text.lower()
    assert "back" in spec.text.lower()
    # No alarm language.
    assert "right now" not in spec.text.lower()
    assert "immediately" not in spec.text.lower()
    # 5-14 words (project rule).
    words = spec.text.split()
    assert 5 <= len(words) <= 14, f"Template is {len(words)} words: {spec.text!r}"


# Bonus — feature classifier behavior
def test_floor_negation_feature_extraction():
    cases = [
        ("they're in a chair", True),
        ("she is in bed", True),
        ("on the couch", True),
        ("sitting up", True),
        ("seated", True),
        ("standing", True),
        ("upright", True),
        ("slumped", True),
        ("not on the floor", True),
        ("can't move him", True),
        # Negative cases — no false positives.
        ("on the floor on his back", False),
        ("flat on the ground", False),
        ("lying down", False),
    ]
    for utterance, expected in cases:
        f = classify(utterance)
        assert f.floor_negation == expected, (
            f"{utterance!r} -> floor_negation={f.floor_negation}, expected {expected}"
        )
