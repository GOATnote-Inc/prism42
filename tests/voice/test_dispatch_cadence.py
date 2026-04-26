"""Cycle-2D5 dispatch-cadence tests.

Cycle-2D5-A: confirm_address echoes the captured address back to the caller
(per public PSAP discipline — Sarpy County, Caldwell County, NHTSA EMD,
NAEMD all require verbatim readback so the caller can correct STT mishears).

Cycle-2D5-B: complaint-specific reassurance variants fuse reassurance +
co-presence + first directive into a single turn (per StatPearls NBK470543,
AHA T-CPR research). Eliminates the dead-air gap that produced the
user-attested "okay, but what do I do?" failure.

Source: findings/voice/cycle2D4_dispatch_research/team-research/dispatch-patterns.md
"""
from __future__ import annotations

import sys
from pathlib import Path

# Path-bootstrap so tests can import agents/livekit/* without install.
_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
sys.path.insert(0, str(_AGENTS_DIR))

import pytest  # noqa: E402

from dispatcher_fsm import DispatcherFSM, Intent, State, classify  # noqa: E402
from response_gate import ResponseGate  # noqa: E402


# ------------------------------------------------------------------
# Cycle-2D5-A — address echo
# ------------------------------------------------------------------


def test_address_text_captured_from_cardinal_address():
    """`classify` extracts the spoken-cardinal address span un-normalized."""
    f = classify("twelve riverside drive")
    assert f.address_text == "twelve riverside drive"


def test_address_text_captured_from_numeric_address():
    """Numeric addresses captured intact, not truncated to '<digit> <name>'."""
    f = classify("100 ocean avenue")
    assert f.address_text == "100 ocean avenue"


def test_address_text_captured_from_combined_turn():
    """Combined turn with address + emergency captures only the address span."""
    f = classify("twelve riverside drive my friend was shot in the chest")
    assert f.address_text == "twelve riverside drive"


def test_address_text_none_when_only_digit_no_street():
    """Bare digits without a street suffix → no echo span (fallback path)."""
    f = classify("apartment 3")
    # has_address may still be True via _RE_HAS_DIGIT, but address_text=None
    assert f.address_text is None


def test_fsm_latches_address_text_on_first_capture():
    """`address_text` latches once and does not get overwritten."""
    fsm = DispatcherFSM()
    fsm.transition("twelve riverside drive")
    assert fsm.address_text == "twelve riverside drive"
    fsm.transition("twenty fourth street")  # second clean address
    # Should NOT overwrite — first capture wins.
    assert fsm.address_text == "twelve riverside drive"


def test_confirm_address_echoes_captured_text():
    """Gate renders confirm_address with the captured address echoed."""
    fsm = DispatcherFSM()
    fsm.transition("twelve riverside drive")
    fsm.transition("my friend was shot in the chest")
    gate = ResponseGate(fsm=fsm)
    text = gate.render_template_for("confirm_address")
    assert text == "I have you at twelve riverside drive, help is on the way."


def test_confirm_address_falls_back_when_no_address_text():
    """When address_text is None, the gate emits the no-echo form."""
    fsm = DispatcherFSM()
    # has_address=True via _RE_HAS_DIGIT, but no street suffix → address_text None
    fsm.address_known = True
    fsm.address_text = None
    gate = ResponseGate(fsm=fsm)
    text = gate.render_template_for("confirm_address")
    assert text == "I have your address, help is on the way."


def test_confirm_address_template_static_audit_passes():
    """The default template (no echo substitution) is still 5-14 words,
    one terminator. Runtime substitution stays within the same envelope."""
    from templates import render_template, audit_word_counts
    counts = audit_word_counts()
    assert 5 <= counts["confirm_address"] <= 14
    rendered = render_template("confirm_address", "they")
    assert rendered.count(".") + rendered.count("?") + rendered.count("!") == 1


# ------------------------------------------------------------------
# Cycle-2D5-B — complaint-specific reassurance variants
# ------------------------------------------------------------------


def _into_address_confirmed(fsm: DispatcherFSM, address: str, emergency: str) -> Intent:
    """Drive the FSM into ADDRESS_CONFIRMED, return the next intent."""
    fsm.transition(address)
    fsm.transition(emergency)  # turn 2 emits CONFIRM_ADDRESS, state→ADDRESS_CONFIRMED
    # turn 3 caller speaks → _intent_in_address_confirmed runs
    return fsm.transition("uh okay")


def test_trauma_reassurance_variant_fires():
    fsm = DispatcherFSM()
    intent = _into_address_confirmed(
        fsm, "twelve riverside drive", "my friend was shot in the chest"
    )
    assert intent == Intent.DELIVER_REASSURANCE_TRAUMA
    assert fsm.reassurance_done is True
    assert fsm.complaint == "trauma"


def test_medical_reassurance_variant_fires():
    fsm = DispatcherFSM()
    intent = _into_address_confirmed(
        fsm, "one hundred ocean avenue", "my mother is having chest pain"
    )
    assert intent == Intent.DELIVER_REASSURANCE_MEDICAL
    assert fsm.reassurance_done is True
    assert fsm.complaint == "medical"


def test_fire_falls_back_to_legacy_reassurance():
    """Fire (and crime/unknown) keep the legacy standalone reassurance."""
    fsm = DispatcherFSM()
    intent = _into_address_confirmed(
        fsm, "twelve riverside drive", "the kitchen is on fire"
    )
    assert intent == Intent.DELIVER_REASSURANCE
    assert fsm.complaint == "fire"


def test_trauma_template_renders_with_kq():
    """The trauma variant text fuses reassurance + bleeding KQ."""
    fsm = DispatcherFSM()
    fsm.complaint = "trauma"
    gate = ResponseGate(fsm=fsm)
    text = gate.render_template_for("deliver_reassurance_trauma")
    assert text == "Help is on the way, stay with me, where is the bleeding?"


def test_medical_template_renders_with_verbal_task():
    fsm = DispatcherFSM()
    fsm.complaint = "medical"
    gate = ResponseGate(fsm=fsm)
    text = gate.render_template_for("deliver_reassurance_medical")
    assert text == "Help is on the way, stay with me, tell me what is happening."


def test_reassurance_variants_in_template_audit():
    """All new reassurance intents have templates in TEMPLATES + audit ok."""
    from templates import TEMPLATES, audit_word_counts
    assert "deliver_reassurance_trauma" in TEMPLATES
    assert "deliver_reassurance_medical" in TEMPLATES
    counts = audit_word_counts()
    assert 5 <= counts["deliver_reassurance_trauma"] <= 14
    assert 5 <= counts["deliver_reassurance_medical"] <= 14


def test_cardiac_short_circuit_bypasses_reassurance_variants():
    """When 'not breathing' fires on the same turn as address+emergency,
    the cardiac short-circuit jumps to CRITICAL_VERIFY and the reassurance
    variant path is never reached. Validates the design assumption that
    DELIVER_REASSURANCE_CARDIAC is unreachable (we did not add it)."""
    fsm = DispatcherFSM()
    fsm.transition("twelve riverside drive")
    intent = fsm.transition("my friend was shot in the chest, he is not breathing")
    # Should jump straight to verify_cpr_surface — not reassurance.
    assert intent == Intent.VERIFY_SURFACE
    assert fsm.state == State.CRITICAL_VERIFY
    assert fsm.is_cardiac_arrest is True
    assert fsm.reassurance_done is False  # never delivered


# ------------------------------------------------------------------
# End-to-end repro of the user's attested failure
# ------------------------------------------------------------------


def test_e2e_user_repro_address_echoed_and_no_dead_air():
    """End-to-end: caller's screenshot scenario.

    Before cycle-2D5:
      Turn 2 dispatcher: 'Got your address and dispatching help to you.'
      Turn 3 dispatcher: 'Help is on the way and I am staying with you.'
      Turn 4 dispatcher: 'Where is the bleeding, and how heavy?'
      Caller turn 3 said 'okay, but what do I do?' (the bug).

    After cycle-2D5:
      Turn 2 dispatcher: 'I have you at twelve riverside drive, help is on the way.'
      Turn 3 dispatcher: 'Help is on the way, stay with me, where is the bleeding?'
      Caller has no dead-air gap — the dispatcher's first reassurance turn
      already asks the next question.
    """
    fsm = DispatcherFSM()
    gate = ResponseGate(fsm=fsm)

    # Turn 1: caller says address only.
    fsm.transition("twelve riverside drive")
    # Turn 2: caller says emergency. FSM emits CONFIRM_ADDRESS.
    intent2 = fsm.transition("my friend has been uh shot in the chest")
    assert intent2 == Intent.CONFIRM_ADDRESS
    text2 = gate.render_template_for(intent2.value)
    assert "twelve riverside drive" in (text2 or ""), (
        f"Address must echo. Got: {text2!r}"
    )
    assert "help is on the way" in (text2 or "").lower()

    # Turn 3: caller speaks (substantive — not bare backchannel).
    # FSM emits trauma reassurance variant which fuses reassurance
    # with the bleeding-location KQ.
    intent3 = fsm.transition("okay but what do I do")
    assert intent3 == Intent.DELIVER_REASSURANCE_TRAUMA
    text3 = gate.render_template_for(intent3.value)
    assert "where is the bleeding" in (text3 or "").lower()
    # No second turn of standalone reassurance — directive is in the same turn.
    assert fsm.reassurance_done is True
