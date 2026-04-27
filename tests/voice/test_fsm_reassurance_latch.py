"""dispatcher_fsm — reassurance-latch regression tests.

Per `findings/research/2026-04-27-future-stack/fsm-routing-bug-diagnosis.md`,
the FSM bug was that `_intent_in_address_confirmed` could re-enter the
reassurance path on a second visit to ADDRESS_CONFIRMED, emitting a
second `DELIVER_REASSURANCE_*` intent and producing the "I'm with you /
help is on the way / stay with me" template loop the user observed.

The fix (`dispatcher_fsm.py:_intent_in_address_confirmed`) short-circuits
when `reassurance_done` is already True and defers to
`_intent_in_after_reassurance`, which handles direct-question routing
and KEY_QUESTIONS advancement without re-firing reassurance.

These tests call the helper directly with a hand-built `Features` object
to isolate the routing decision from upstream classification (e.g. the
backchannel guard at transition():618 which short-circuits before the
helper for utterances like "okay" / "yeah" / "uh-huh").
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_LIVEKIT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_LIVEKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_LIVEKIT_DIR))

from dispatcher_fsm import DispatcherFSM, Features, Intent, State  # noqa: E402


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _no_signal_features() -> Features:
    """A Features object with no question / cardiac / backchannel signals.

    The defaults of the dataclass are already all-False / empty-string,
    so a bare `Features()` is sufficient — but constructing here makes
    the test's assumptions explicit and lets us tune in one place if
    Features grows new required fields.
    """
    return Features()


def _reassurance_intents() -> set[Intent]:
    return {
        Intent.DELIVER_REASSURANCE,
        Intent.DELIVER_REASSURANCE_TRAUMA,
        Intent.DELIVER_REASSURANCE_MEDICAL,
    }


# ---------------------------------------------------------------------
# Regression: reassurance fires exactly once on first ADDRESS_CONFIRMED.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "complaint,expected_intent",
    [
        ("medical", Intent.DELIVER_REASSURANCE_MEDICAL),
        ("trauma", Intent.DELIVER_REASSURANCE_TRAUMA),
        ("unknown", Intent.DELIVER_REASSURANCE),
        ("", Intent.DELIVER_REASSURANCE),
    ],
)
def test_first_visit_emits_complaint_specific_reassurance(complaint, expected_intent):
    """First arrival in ADDRESS_CONFIRMED with no question signals
    must emit the complaint-specific reassurance variant and latch
    `reassurance_done=True`. Regression check on the existing path."""
    fsm = DispatcherFSM()
    fsm.state = State.ADDRESS_CONFIRMED
    fsm.address_known = True
    fsm.emergency_known = True
    fsm.complaint = complaint
    fsm.reassurance_done = False

    intent = fsm._intent_in_address_confirmed(_no_signal_features(), t0=0.0)

    assert intent == expected_intent
    assert fsm.reassurance_done is True
    assert fsm.state == State.REASSURANCE_DELIVERED


# ---------------------------------------------------------------------
# The bug case: a second visit must NOT re-emit reassurance.
# ---------------------------------------------------------------------


def test_second_visit_does_not_re_emit_reassurance():
    """If the FSM is back in ADDRESS_CONFIRMED with `reassurance_done=True`,
    no `DELIVER_REASSURANCE_*` intent should fire. The fix routes through
    `_intent_in_after_reassurance` which advances to KEY_QUESTIONS when
    no question is pending."""
    fsm = DispatcherFSM()
    fsm.state = State.ADDRESS_CONFIRMED
    fsm.address_known = True
    fsm.emergency_known = True
    fsm.complaint = "medical"
    fsm.reassurance_done = True  # <-- bug condition

    intent = fsm._intent_in_address_confirmed(_no_signal_features(), t0=0.0)

    assert intent not in _reassurance_intents(), (
        f"second visit must NOT re-emit reassurance, got {intent}"
    )
    # The fix should advance to KEY_QUESTIONS (no question pending).
    assert fsm.state == State.KEY_QUESTIONS


def test_second_visit_with_question_routes_to_question_not_reassurance():
    """With `reassurance_done=True` and the caller asking a direct
    question, the answer must take priority over reassurance — but not
    re-emit reassurance either. The after-reassurance helper handles it."""
    fsm = DispatcherFSM()
    fsm.state = State.ADDRESS_CONFIRMED
    fsm.address_known = True
    fsm.emergency_known = True
    fsm.complaint = "medical"
    fsm.reassurance_done = True

    f = _no_signal_features()
    f.asks_heard_address = True  # caller asking "did you get my address?"

    intent = fsm._intent_in_address_confirmed(f, t0=0.0)
    assert intent not in _reassurance_intents()
    assert intent == Intent.ANSWER_HEARD_ADDRESS


def test_second_visit_with_do_not_move_question_routes_correctly():
    """Different direct-question signal — the path is the same: answer,
    don't reassure."""
    fsm = DispatcherFSM()
    fsm.state = State.ADDRESS_CONFIRMED
    fsm.address_known = True
    fsm.emergency_known = True
    fsm.complaint = "trauma"
    fsm.reassurance_done = True

    f = _no_signal_features()
    f.asks_do_not_move = True

    intent = fsm._intent_in_address_confirmed(f, t0=0.0)
    assert intent not in _reassurance_intents()
    assert intent == Intent.ANSWER_DO_NOT_MOVE


# ---------------------------------------------------------------------
# Defense in depth: bug doesn't reappear when state is hand-set to
# ADDRESS_CONFIRMED in REASSURANCE_DELIVERED-equivalent contexts.
# ---------------------------------------------------------------------


def test_state_is_set_to_reassurance_delivered_after_short_circuit():
    """When the short-circuit fires, FSM state must end up in either
    REASSURANCE_DELIVERED (transient — for after_reassurance to advance
    from) or KEY_QUESTIONS (after after_reassurance advances). Never
    stuck in ADDRESS_CONFIRMED with `reassurance_done=True`."""
    fsm = DispatcherFSM()
    fsm.state = State.ADDRESS_CONFIRMED
    fsm.address_known = True
    fsm.emergency_known = True
    fsm.complaint = "medical"
    fsm.reassurance_done = True

    fsm._intent_in_address_confirmed(_no_signal_features(), t0=0.0)
    assert fsm.state in (State.REASSURANCE_DELIVERED, State.KEY_QUESTIONS), (
        f"after short-circuit, state must advance — got stuck at {fsm.state}"
    )
    # Critically: NOT stuck in ADDRESS_CONFIRMED
    assert fsm.state != State.ADDRESS_CONFIRMED
