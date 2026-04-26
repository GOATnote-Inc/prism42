"""Cycle-2T response gate — pytest unit tests.

Covers:
  - All 21 Intent values: gate_decision returns either valid template
    or sane LLM-constraint config
  - CPR safety gate positive: arrest+surface+breathing -> green
  - CPR safety gate negative: any latch missing -> blocked
  - CPR boundary: None vs False vs True
  - Validators: word count, terminator count, gendered pronouns,
    repeat phrases
  - Default-OFF: should_use_response_gate() reads env
  - Logging: structured log fires on every decision

The tests do not need the pod, do not depend on livekit-agents at
runtime (only response_gate / templates / dispatcher_fsm), and run
green on a laptop. They share the existing tests/voice/conftest.py
fixtures but use none of the integration-marked ones.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# response_gate / templates / dispatcher_fsm live under
# agents/livekit/, NOT on the default Python path. Inject so pytest
# can resolve them without a conftest path-hack on every test.
_LIVEKIT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_LIVEKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_LIVEKIT_DIR))

# Intentional re-import inside test_default_off so the env-var test can
# toggle the flag and re-read.
import response_gate  # noqa: E402
import templates  # noqa: E402
from dispatcher_fsm import DispatcherFSM, Intent  # noqa: E402
from response_gate import (  # noqa: E402
    GateDecision,
    ResponseGate,
    ValidationResult,
    gate_for_fsm,
    should_use_response_gate,
    validate_llm_output,
)
from templates import (  # noqa: E402
    TEMPLATES,
    audit_word_counts,
    pronoun_substitutions,
    render_template,
)


# ---------------------------------------------------------------------
# Coverage: every Intent value has either a template OR is routed to
# the LLM path with constraints. (No silent omissions.)
# ---------------------------------------------------------------------


def test_every_intent_has_template_or_llm_path():
    """Every Intent.<X>.value must produce a non-empty GateDecision.

    Either:
      - (template path) used_template=True, final_text is a non-empty
        rendered string, no LLM constraints needed
      - (LLM path) used_llm=True, constraints_for_llm is a dict with
        at minimum {min_words, max_words, terminators_max}

    Catches the failure mode where a future Intent is added but no
    template wired up.
    """
    fsm = DispatcherFSM()
    gate = gate_for_fsm(fsm)
    for intent in Intent:
        # Reset CPR latches so INSTRUCT_CPR_BEGIN is "safe" for this
        # generic coverage check (the actual safety gate is exercised
        # by dedicated tests below).
        fsm.is_cardiac_arrest = True
        fsm.surface_confirmed = True
        fsm.breathing_assessed = True
        d = gate.gate_decision(intent.value, caller_utterance="")
        assert isinstance(d, GateDecision)
        assert d.intent == intent.value
        assert d.used_template ^ d.used_llm, (
            f"intent={intent.value} must be exactly one of template|llm"
        )
        if d.used_template:
            assert d.final_text and d.final_text.strip(), (
                f"intent={intent.value} template path returned empty text"
            )
        else:
            assert isinstance(d.constraints_for_llm, dict)
            assert d.constraints_for_llm["max_words"] == 14
            assert d.constraints_for_llm["min_words"] == 5
            assert d.constraints_for_llm["terminators_max"] == 1


def test_template_keys_align_with_intent_enum():
    """TEMPLATES must use exactly the Intent.value strings the FSM
    emits — drift here means a future intent rename silently breaks the
    gate.
    """
    intent_values = {i.value for i in Intent}
    template_keys = set(TEMPLATES.keys())
    # Every templated key must correspond to a real Intent value.
    unknown = template_keys - intent_values
    assert not unknown, f"templates.py has keys not in Intent enum: {unknown}"
    # Every intent currently in the gate's "deterministic" class should
    # have a template.
    missing = intent_values - template_keys
    assert not missing, f"Intent values without a template: {missing}"


# ---------------------------------------------------------------------
# Word-count + terminator + genderless-by-default audits.
# ---------------------------------------------------------------------


def test_word_counts_in_5_to_14():
    """Every template, after they/them substitution, is in [5, 14] words.

    Prints each count so failures localize. Mirrors the design-doc
    Phase 4 verification step.
    """
    counts = audit_word_counts()
    assert counts, "TEMPLATES is empty"
    for intent_value, n in counts.items():
        assert 5 <= n <= 14, (
            f"template '{intent_value}' word_count={n} not in [5,14]: "
            f"{TEMPLATES[intent_value].text!r}"
        )


def test_one_terminator_per_template():
    """Every template has exactly one of {. ! ?}, after substitution."""
    import re
    for intent_value, spec in TEMPLATES.items():
        rendered = render_template(intent_value, "they") or ""
        n = len(re.findall(r"[.!?]", rendered))
        assert n == 1, (
            f"template '{intent_value}' has {n} terminators: {rendered!r}"
        )


def test_no_gendered_pronouns_in_literal_templates():
    """Literal template text (pre-substitution) contains no he/him/his/
    she/her/hers — pronouns are only introduced via {placeholder}
    substitution from the FSM's pronouns latch.
    """
    import re
    banned = re.compile(r"\b(he|him|his|she|her|hers)\b", re.IGNORECASE)
    for intent_value, spec in TEMPLATES.items():
        m = banned.search(spec.text)
        assert m is None, (
            f"template '{intent_value}' has hardcoded gendered pronoun "
            f"{m.group(0)!r}: {spec.text!r}"
        )


def test_default_pronouns_are_singular_they():
    """When fsm.pronouns is 'unknown' the substitution table renders
    they/them/their, not he/him/his.
    """
    sub = pronoun_substitutions("unknown")
    assert sub["pronoun_subject"] == "they"
    assert sub["pronoun_object"] == "them"
    assert sub["possessive"] == "their"


def test_pronoun_substitution_he_him():
    sub = pronoun_substitutions("he/him")
    assert sub["pronoun_subject"] == "he"
    assert sub["pronoun_object"] == "him"
    assert sub["possessive"] == "his"


def test_pronoun_substitution_she_her():
    sub = pronoun_substitutions("she/her")
    assert sub["pronoun_subject"] == "she"
    assert sub["pronoun_object"] == "her"
    assert sub["possessive"] == "her"


# ---------------------------------------------------------------------
# CPR safety gate.
# ---------------------------------------------------------------------


def _arrest_fsm(*, surface, breathing, arrest=True):
    fsm = DispatcherFSM()
    fsm.is_cardiac_arrest = arrest
    fsm.surface_confirmed = surface
    fsm.breathing_assessed = breathing
    return fsm


def test_cpr_safe_when_all_latches_true():
    fsm = _arrest_fsm(surface=True, breathing=True)
    gate = gate_for_fsm(fsm)
    assert gate.cpr_safe() is True
    d = gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    assert d.used_template is True
    assert d.cpr_blocked is False
    # The compressions instruction text MUST be the canonical one.
    assert "compressions" in (d.final_text or "").lower() or \
           "push hard and fast" in (d.final_text or "").lower()


def test_cpr_blocked_when_surface_unconfirmed():
    fsm = _arrest_fsm(surface=False, breathing=True)
    gate = gate_for_fsm(fsm)
    assert gate.cpr_safe() is False
    d = gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    assert d.cpr_blocked is True
    assert d.fallback_intent == "verify_cpr_surface"
    # Returns a deterministic verification template, not blank.
    assert d.final_text and "floor" in d.final_text.lower()


def test_cpr_blocked_when_breathing_unassessed():
    fsm = _arrest_fsm(surface=True, breathing=False)
    gate = gate_for_fsm(fsm)
    assert gate.cpr_safe() is False
    d = gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    assert d.cpr_blocked is True
    assert d.fallback_intent == "verify_cpr_breathing"


def test_cpr_boundary_none_blocked():
    """CPR safety is conservative — None ≠ True. Per the directive's
    'awake=None, breathing=False -> blocked' boundary case.
    """
    fsm = DispatcherFSM()
    # is_cardiac_arrest defaults to False per dataclass; explicitly set
    # the latches to None to simulate a partially-initialized state.
    fsm.is_cardiac_arrest = None  # type: ignore[assignment]
    fsm.surface_confirmed = None  # type: ignore[assignment]
    fsm.breathing_assessed = None  # type: ignore[assignment]
    gate = gate_for_fsm(fsm)
    assert gate.cpr_safe() is False
    d = gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    assert d.cpr_blocked is True


def test_cpr_blocked_when_not_cardiac_arrest():
    """Defense in depth — even if both verification latches are True,
    the gate refuses compressions when is_cardiac_arrest is False.
    """
    fsm = _arrest_fsm(surface=True, breathing=True, arrest=False)
    gate = gate_for_fsm(fsm)
    assert gate.cpr_safe() is False
    d = gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    assert d.cpr_blocked is True


def test_cpr_blocked_falls_back_to_verify_template_text():
    """When CPR is blocked, the gate emits a deterministic verification
    template (not silence). Voice path must never emit empty audio.
    """
    fsm = _arrest_fsm(surface=False, breathing=False)
    gate = gate_for_fsm(fsm)
    d = gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    assert d.cpr_blocked is True
    assert d.final_text and len(d.final_text.split()) >= 5


def test_logging_includes_cpr_blocked_field(capsys):
    """The cycle-2T directive's log requirement enumerates cpr_blocked
    as a required field. Gate must surface it on every decision.
    """
    fsm = _arrest_fsm(surface=False, breathing=False)
    gate = gate_for_fsm(fsm)
    gate.gate_decision(Intent.INSTRUCT_CPR_BEGIN.value)
    out = capsys.readouterr().out
    assert "response_gate.decision" in out
    assert "cpr_blocked=True" in out
    assert "fallback_intent=" in out


# ---------------------------------------------------------------------
# Validators (LLM-path post-processing).
# ---------------------------------------------------------------------


def test_validator_too_short():
    r = validate_llm_output("Help now please.")
    assert r.ok is False
    assert any("word_count" in s for s in r.reasons)


def test_validator_too_long():
    text = "This is a sentence that has very many words on purpose so it goes over the limit easily today."
    r = validate_llm_output(text)
    assert r.ok is False
    assert any("word_count" in s for s in r.reasons)


def test_validator_two_terminators():
    r = validate_llm_output("Help is on the way. Stay on the line.")
    assert r.ok is False
    assert any("terminators" in s for s in r.reasons)


def test_validator_gendered_when_unknown():
    """'him' in output AND pronouns_known=False -> reject."""
    r = validate_llm_output(
        "Tell him to stay still right now please.",
        pronouns_known=False,
    )
    assert r.ok is False
    assert any("gendered_pronoun" in s for s in r.reasons)


def test_validator_gendered_when_known_passes():
    """'him' in output AND pronouns_known=True -> allowed."""
    r = validate_llm_output(
        "Tell him to stay still right now please.",
        pronouns_known=True,
    )
    assert r.ok is True, f"expected ok, got reasons={r.reasons}"


def test_validator_repeat_phrase():
    """A verbatim phrase from recent_replies must be rejected."""
    recent = ["Help is on the way and I am staying with you."]
    r = validate_llm_output(
        "Help is on the way and I am staying with you.",
        recent_replies=recent,
    )
    assert r.ok is False
    assert any("repeat" in s for s in r.reasons)


def test_validator_passes_clean_output():
    r = validate_llm_output("What is happening at that location?")
    assert r.ok is True, f"reasons={r.reasons}"


def test_validator_window_repeat():
    """A 6-word substring overlap with recent_replies should be flagged."""
    recent = ["Press hard on the wound with a clean cloth now."]
    r = validate_llm_output(
        "Press hard on the wound with a cloth.",
        recent_replies=recent,
    )
    assert r.ok is False


# ---------------------------------------------------------------------
# Default-OFF env flag.
# ---------------------------------------------------------------------


def test_default_off_when_env_unset(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_RESPONSE_GATE", raising=False)
    importlib.reload(response_gate)
    assert response_gate.should_use_response_gate() is False


def test_on_when_env_is_one(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_RESPONSE_GATE", "1")
    importlib.reload(response_gate)
    assert response_gate.should_use_response_gate() is True


def test_off_when_env_is_zero(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_RESPONSE_GATE", "0")
    importlib.reload(response_gate)
    assert response_gate.should_use_response_gate() is False


def test_off_when_env_is_garbage(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_RESPONSE_GATE", "yes")
    importlib.reload(response_gate)
    assert response_gate.should_use_response_gate() is False


# ---------------------------------------------------------------------
# Logging — every gate_decision emits structured log.
# ---------------------------------------------------------------------


def test_gate_decision_emits_log(capsys):
    """A gate_decision call must emit a structured log line containing
    intent, used_template, used_llm, final_text, cpr_blocked, ms.

    structlog (default config) renders to stdout, so we capture via
    capsys and assert the canonical event name + the load-bearing
    fields the cycle-2T directive enumerates.
    """
    fsm = DispatcherFSM()
    fsm.is_cardiac_arrest = True
    fsm.surface_confirmed = True
    fsm.breathing_assessed = True
    gate = gate_for_fsm(fsm)
    d = gate.gate_decision(Intent.REQUEST_LOCATION.value)
    assert d.used_template is True
    captured = capsys.readouterr().out
    assert "response_gate.decision" in captured
    # Required fields per the cycle-2T directive's "Log: intent,
    # used_template, used_llm, final_text" rule.
    assert "intent=request_location" in captured
    assert "used_template=True" in captured
    assert "used_llm=False" in captured
    assert "final_text=" in captured
    assert "cpr_blocked=False" in captured


# ---------------------------------------------------------------------
# Per-intent template content sanity checks.
# ---------------------------------------------------------------------


def test_request_location_template_is_iaed_opener():
    text = render_template("request_location_and_emergency", "unknown")
    assert text == "Nine one one, what is the address of your emergency?"


def test_reassurance_is_one_sentence():
    text = render_template("deliver_reassurance", "unknown")
    assert text and text.count(".") + text.count("!") + text.count("?") == 1


def test_cpr_template_is_genderless_and_actionable():
    text = render_template("instruct_cpr_compressions", "unknown")
    assert text and text.lower().startswith("push")
    # "compressions" or "push hard and fast" must appear.
    assert "push" in text.lower()


def test_cpr_template_does_not_use_him_or_her_default():
    text = render_template("instruct_cpr_compressions", "unknown") or ""
    import re
    assert re.search(r"\b(he|him|his|she|her)\b", text, re.IGNORECASE) is None


def test_pronoun_required_template_substitutes_he_when_committed():
    text = render_template("instruct_choking_back_blows", "he/him") or ""
    assert "him" in text


def test_pronoun_required_template_substitutes_they_when_unknown():
    text = render_template("instruct_choking_back_blows", "unknown") or ""
    assert "them" in text


# ---------------------------------------------------------------------
# Integration smoke: gate sits BETWEEN FSM and TTS without mutating
# the FSM. (Calling gate_decision must not change FSM state.)
# ---------------------------------------------------------------------


def test_gate_does_not_mutate_fsm():
    fsm = DispatcherFSM()
    gate = gate_for_fsm(fsm)
    snapshot_before = (
        fsm.state.value,
        fsm.address_known,
        fsm.emergency_known,
        fsm.reassurance_done,
        fsm.surface_confirmed,
        fsm.breathing_assessed,
        fsm.is_cardiac_arrest,
        fsm.pronouns,
        fsm.is_third_party,
        fsm.complaint,
        fsm.turns,
    )
    for intent in Intent:
        gate.gate_decision(intent.value, caller_utterance="anything")
    snapshot_after = (
        fsm.state.value,
        fsm.address_known,
        fsm.emergency_known,
        fsm.reassurance_done,
        fsm.surface_confirmed,
        fsm.breathing_assessed,
        fsm.is_cardiac_arrest,
        fsm.pronouns,
        fsm.is_third_party,
        fsm.complaint,
        fsm.turns,
    )
    assert snapshot_before == snapshot_after, (
        "ResponseGate must not mutate FSM state — that's the FSM's job."
    )
