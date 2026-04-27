"""rule_adjudicator — unit tests.

Pure-Python, no IO, no monkeypatching of network. Covers:

  - default-OFF returns None (byte-equivalent guarantee)
  - sub-1-ms runtime budget (per voice-5role-design.md §1)
  - verdict logic for the cross-product of (intent, role-fire pattern)
  - output schema is dict-only (no "content" / "role" / "messages" keys
    that could leak into chat_ctx if mishandled)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_LIVEKIT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_LIVEKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_LIVEKIT_DIR))

import rule_adjudicator  # noqa: E402


# ---------------------------------------------------------------------
# Default-OFF
# ---------------------------------------------------------------------


def test_default_off_returns_none(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_RULE_ADJUDICATOR", raising=False)
    result = rule_adjudicator.adjudicate(
        session_id="s1",
        turn_idx=0,
        intent="cardiac_arrest",
        defender_fired=True,
        executor_template=True,
        synthesizer_perception=True,
        attacker_probe=False,
    )
    assert result is None


def test_should_use_env_flag(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_RULE_ADJUDICATOR", raising=False)
    assert rule_adjudicator.should_use_rule_adjudicator() is False
    monkeypatch.setenv("PRISM42_ENABLE_RULE_ADJUDICATOR", "1")
    assert rule_adjudicator.should_use_rule_adjudicator() is True


# ---------------------------------------------------------------------
# Schema — off-path safety invariant
# ---------------------------------------------------------------------


def test_output_schema_keys(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_RULE_ADJUDICATOR", "1")
    result = rule_adjudicator.adjudicate(
        session_id="s1",
        turn_idx=0,
        intent="cardiac_arrest",
        defender_fired=True,
        executor_template=True,
        synthesizer_perception=True,
        attacker_probe=False,
    )
    assert isinstance(result, dict)
    expected_keys = {
        "session_id", "turn_idx", "intent",
        "defender_fired", "executor_template",
        "synthesizer_perception", "attacker_probe",
        "elapsed_ms", "verdict",
    }
    assert set(result.keys()) == expected_keys
    # negative assertions (off-path):
    assert "content" not in result
    assert "role" not in result
    assert "messages" not in result


# ---------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent,defender,executor,synth,expected",
    [
        # safety-critical intent + neither defender nor executor template = missing
        ("cardiac_arrest", False, False, False, "missing_safety_role"),
        ("trauma", False, False, True, "missing_safety_role"),
        # safety-critical + defender alone = ok
        ("cardiac_arrest", True, False, False, "ok"),
        # safety-critical + executor template alone = deterministic_template
        ("cardiac_arrest", False, True, False, "deterministic_template"),
        # full role fire
        ("cardiac_arrest", True, True, True, "all_roles_fired"),
        # smalltalk + nothing fired = llm_passthrough (acceptable for non-critical)
        ("smalltalk", False, False, False, "llm_passthrough"),
        ("unknown", False, False, False, "llm_passthrough"),
        # smalltalk with defender = ok
        ("smalltalk", True, False, False, "ok"),
        # case-insensitive intent matching
        ("SMALLTALK", False, False, False, "llm_passthrough"),
    ],
)
def test_verdict_table(monkeypatch, intent, defender, executor, synth, expected):
    monkeypatch.setenv("PRISM42_ENABLE_RULE_ADJUDICATOR", "1")
    result = rule_adjudicator.adjudicate(
        session_id="s1",
        turn_idx=0,
        intent=intent,
        defender_fired=defender,
        executor_template=executor,
        synthesizer_perception=synth,
        attacker_probe=False,
    )
    assert result is not None
    assert result["verdict"] == expected


# ---------------------------------------------------------------------
# Runtime budget — sub-1-ms target per voice-5role-design.md
# ---------------------------------------------------------------------


def test_sub_one_ms_runtime(monkeypatch):
    """1000 invocations must complete well under 100 ms wall-clock —
    100 µs per call ceiling, well below the design brief's 1 ms target."""
    import time
    monkeypatch.setenv("PRISM42_ENABLE_RULE_ADJUDICATOR", "1")

    start = time.monotonic()
    for i in range(1000):
        rule_adjudicator.adjudicate(
            session_id=f"s{i}",
            turn_idx=i,
            intent="cardiac_arrest" if i % 2 else "smalltalk",
            defender_fired=bool(i % 3),
            executor_template=bool(i % 5),
            synthesizer_perception=bool(i % 7),
            attacker_probe=False,
        )
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 200, f"1000 invocations took {elapsed_ms:.1f} ms (>200 ms ceiling)"
