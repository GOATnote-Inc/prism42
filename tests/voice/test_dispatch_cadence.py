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


def test_address_text_captures_four_word_address():
    """Cycle-2D7: '<digit/word> <word> <word> <suffix>' captures intact.

    Repro from user attestation 2026-04-26 14:03: caller said "Two hundred
    oceanfront avenue" but dispatcher echoed "hundred oceanfront avenue"
    because the {0,1} middle-word allowance dropped the leading "Two".
    """
    f = classify("Two hundred oceanfront avenue")
    assert f.address_text == "Two hundred oceanfront avenue"

    f2 = classify("1234 east main boulevard")
    assert f2.address_text == "1234 east main boulevard"

    f3 = classify("twelve north shore drive")
    assert f3.address_text == "twelve north shore drive"


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


# ------------------------------------------------------------------
# Cycle-2D6 — VERIFY_SURFACE loop guard + extended floor_negation regex
# ------------------------------------------------------------------


def test_verify_surface_loop_bounded_when_caller_silent_on_surface():
    """When the caller never says anything floor-related, the FSM
    must not loop on VERIFY_SURFACE forever. After 2 emits with no
    floor signal in either direction, surface_confirmed latches
    heuristically and the FSM advances to breathing-verify.

    Repro from user attestation 2026-04-26 13:53: dispatcher emitted
    'Are they on the floor, flat on their back?' three times in a row
    while caller said off-topic things ('why? bleeding so much',
    'he wanted to sit up', 'but he's not breathing anymore').
    """
    fsm = DispatcherFSM()
    fsm.transition("twelve riverside drive")
    fsm.transition("my friend is shot in the chest, he is not breathing")
    assert fsm.state == State.CRITICAL_VERIFY
    assert fsm.surface_confirmed is False

    # Caller says nothing surface-related — 1st re-emit is VERIFY_SURFACE.
    i1 = fsm.transition("why is this happening to him")
    assert i1 == Intent.VERIFY_SURFACE

    # 2nd re-emit still VERIFY_SURFACE (counter=2, threshold not hit).
    i2 = fsm.transition("he is bleeding so much")
    # On this transition the loop guard latches and FSM advances.
    # Either VERIFY_SURFACE (counter=2, still loops) or VERIFY_BREATHING
    # (counter=3, latch fired). Document the actual behavior:
    assert i2 in (Intent.VERIFY_SURFACE, Intent.VERIFY_BREATHING)

    # 3rd transition: surface MUST be latched by now, FSM must NOT
    # still be on VERIFY_SURFACE.
    i3 = fsm.transition("but he is not breathing anymore")
    assert fsm.surface_confirmed is True, (
        f"After 3 turns of caller silence on surface, FSM must heuristically "
        f"latch surface_confirmed=True. Got surface_confirmed={fsm.surface_confirmed}, "
        f"intent={i3}"
    )
    assert i3 != Intent.VERIFY_SURFACE


def test_floor_negation_catches_sit_up_variants():
    """Cycle-2D6: extended _RE_FLOOR_NEGATION catches 'sit up' / 'to sit up'
    in addition to the prior 'sitting up' pattern. Caller's actual
    transcribed phrase: 'made him feel better to sit up'."""
    cases = [
        ("he wants to sit up", True),
        ("made him feel better to sit up", True),
        ("she sits up", True),
        # Existing patterns still work
        ("sitting up", True),
        ("sitting on the chair", True),
        # Negative cases still don't trigger
        ("she is on the floor", False),
        ("flat on his back", False),
    ]
    for utterance, expected in cases:
        f = classify(utterance)
        assert f.floor_negation == expected, (
            f"{utterance!r} -> floor_negation={f.floor_negation}, expected {expected}"
        )


# ------------------------------------------------------------------
# Cycle-2D8 — cardiac short-circuit on natural-language not-breathing
#             + STT disfluency stripping in address echo
# ------------------------------------------------------------------


def test_cardiac_short_circuit_on_natural_language_not_breathing():
    """Caller says 'I don't think he's breathing anymore' AFTER reassurance
    fired. The FSM must jump to CRITICAL_VERIFY, not stay in trauma KQ.

    Repro from user attestation 2026-04-26 14:15: cardiac short-circuit
    used a stricter inline regex than _RE_NOT_BREATHING. Cycle-2D3 added
    natural-language patterns to _RE_NOT_BREATHING but missed the inline
    positive_arrest_cue; result was f.not_breathing=True but the FSM
    stayed in KEY_QUESTIONS emitting KQ_BLEEDING_LOCATION on loop.
    """
    fsm = DispatcherFSM()
    fsm.transition("200 river drive")
    fsm.transition("my friend was shot in the chest")
    fsm.transition("uh okay help me")  # advances out of confirm; trauma reassurance fires
    assert fsm.state == State.REASSURANCE_DELIVERED

    # Now the cardiac cue with apostrophe — must trigger short-circuit.
    intent = fsm.transition(
        "Uh in his chest and uh I d I don't think he's breathing anymore."
    )
    assert fsm.is_cardiac_arrest is True
    assert fsm.state == State.CRITICAL_VERIFY
    assert intent in (Intent.VERIFY_SURFACE, Intent.VERIFY_BREATHING)


def test_cardiac_short_circuit_tolerates_stt_dropped_apostrophes():
    """Parakeet/Deepgram occasionally transcribe 'he's' as 'hes' and
    'don't' as 'dont'. The regex must catch both forms."""
    fsm = DispatcherFSM()
    fsm.transition("200 river drive")
    fsm.transition("my friend was shot in the chest")
    fsm.transition("uh okay")
    intent = fsm.transition("dont think hes breathing anymore")
    assert fsm.is_cardiac_arrest is True
    assert fsm.state == State.CRITICAL_VERIFY


def test_address_echo_strips_stt_disfluencies():
    """Cycle-2D8: 'uh', 'um', 'er', 'ah', 'like', 'y'know' are STT-captured
    disfluencies. They must NOT appear in the echoed address.

    Repro from 2026-04-26 14:15: caller said '200 river drive' but STT
    captured '200 uh river drive' which echoed verbatim.
    """
    cases = [
        ("200 uh river drive", "200 river drive"),
        ("two hundred uh oceanfront avenue", "two hundred oceanfront avenue"),
        ("twelve um riverside drive", "twelve riverside drive"),
        ("100 ah ocean ave", "100 ocean ave"),
        # Negative case: clean address passes through
        ("100 ocean avenue", "100 ocean avenue"),
        ("twelve riverside drive", "twelve riverside drive"),
    ]
    for utterance, expected in cases:
        f = classify(utterance)
        assert f.address_text == expected, (
            f"{utterance!r} -> address_text={f.address_text!r}, expected {expected!r}"
        )


# ------------------------------------------------------------------
# Cycle-2D9 — anti-stuck KQ loop guard
# ------------------------------------------------------------------


def test_kq_bleeding_loop_force_advances_after_two_emits():
    """Trauma rail: when caller's answer to 'where is the bleeding'
    is partial / off-topic / panicking on consecutive turns, the FSM
    force-advances to PRE_ARRIVAL after 2 emits rather than looping
    on the same question.

    Repro from user attestation 2026-04-26 14:28: dispatcher emitted
    'Where is the bleeding, and how heavy?' three times in a row even
    though caller said 'his bone is sticking out of his legs, and he's
    got some blood on his chest.'
    """
    fsm = DispatcherFSM()
    fsm.transition("200 river drive")
    fsm.transition("my friend was shot in the chest")
    fsm.transition("uh okay help")  # advances; reassurance fires
    assert fsm.last_intent == Intent.DELIVER_REASSURANCE_TRAUMA

    # Two off-topic answers to KQ_BLEEDING_LOCATION.
    i4 = fsm.transition("uh it seems like his bone is sticking out of his legs")
    assert i4 == Intent.KQ_BLEEDING_LOCATION
    i5 = fsm.transition("there is blood everywhere uh I don't know what to do")
    assert i5 == Intent.KQ_BLEEDING_LOCATION

    # 3rd turn: FSM must NOT emit KQ_BLEEDING_LOCATION again. It must
    # force-advance to PRE_ARRIVAL with INSTRUCT_PRESSURE_BLEED (trauma
    # rail's safe default).
    i6 = fsm.transition("please help him")
    assert i6 == Intent.INSTRUCT_PRESSURE_BLEED, (
        f"After 2 KQ_BLEEDING_LOCATION emits the FSM must advance, "
        f"not repeat. Got intent={i6}, state={fsm.state}"
    )
    assert fsm.state == State.PRE_ARRIVAL


def test_kq_emits_resets_on_different_intent():
    """Counter resets when the FSM emits a different intent (e.g.
    direct-question handler interrupts the KQ loop). Prevents
    spurious force-advances."""
    fsm = DispatcherFSM()
    fsm.transition("200 river drive")
    fsm.transition("my friend was shot in the chest")
    fsm.transition("uh okay")
    fsm.transition("blood is on his chest")  # 1st KQ_BLEEDING emit
    assert fsm._kq_emits == 1

    # Caller asks "should I move him?" -> direct-question handler fires.
    fsm.transition("should I move him")
    # Counter retained but next KQ emit will reset it (last_intent != KQ).
    fsm.transition("just blood")
    assert fsm._kq_emits == 1, (
        f"After non-KQ interrupt, next KQ emit should reset counter. "
        f"Got _kq_emits={fsm._kq_emits}"
    )


def test_pre_arrival_defaults_to_pressure_bleed_for_trauma():
    """When force-advance lands in PRE_ARRIVAL with no current-turn
    f.bleeding/f.choking/f.seizure but complaint=trauma, default to
    INSTRUCT_PRESSURE_BLEED. Avoids the previous CLOSEOUT fallthrough
    which would leave the caller with no instruction at all."""
    fsm = DispatcherFSM()
    fsm.complaint = "trauma"
    fsm.state = State.PRE_ARRIVAL
    from dispatcher_fsm import classify
    f = classify("please help him")  # no specific feature
    intent = fsm._intent_in_pre_arrival(f, 0.0)
    assert intent == Intent.INSTRUCT_PRESSURE_BLEED


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
