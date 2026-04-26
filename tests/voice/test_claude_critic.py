"""claude_critic — unit tests.

Mocks `anthropic.AsyncAnthropic.messages.create` so the suite runs
without an API key. Covers:

  - default-OFF (env unset) is a no-op (no SDK import, no network)
  - score() parses canonical JSON response
  - timeout enforcement at 750ms (not 500)
  - refusal regex drops the response and bumps the counter
  - cost / token-usage accumulator
  - regenerate() raises NotImplementedError (hot-path disabled cycle-2BC)

The tests share the existing tests/voice/conftest.py path-injection
pattern (sys.path .insert) so claude_critic resolves cleanly without
a top-level package install.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# claude_critic / dispatcher_fsm / templates live under agents/livekit/
# but are NOT on the default path. Mirror the test_response_gate.py pattern.
_LIVEKIT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_LIVEKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_LIVEKIT_DIR))

import claude_critic  # noqa: E402


# ---------------------------------------------------------------------
# Helpers — fake Anthropic client.
# ---------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str, in_tok: int = 500, out_tok: int = 100) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = _FakeUsage(in_tok, out_tok)


class _FakeMessages:
    def __init__(self, response_text: str | None = None, sleep_s: float = 0.0,
                 raise_exc: Exception | None = None) -> None:
        self._text = response_text
        self._sleep = sleep_s
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def create(self, **kwargs):  # noqa: ANN001, ANN201
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        if self._sleep:
            await asyncio.sleep(self._sleep)
        return _FakeResponse(self._text or "{}")


class _FakeClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages


@pytest.fixture(autouse=True)
def _reset_critic_state(monkeypatch):
    """Each test gets a clean accumulator + clean global client."""
    claude_critic.reset_token_usage()
    monkeypatch.setattr(claude_critic, "_CLIENT", None, raising=False)
    yield
    claude_critic.reset_token_usage()


@pytest.fixture
def fake_messages():
    """A configurable fake `messages` object the test sets up before
    calling score()."""
    return _FakeMessages()


@pytest.fixture
def install_fake_client(monkeypatch, fake_messages):
    """Installs a FakeClient as the singleton _client() returns."""

    def _install(text: str = '{"suggested_correction": null, "risk_flag": "none", "state_mismatch": false, "state_mismatch_reason": "", "confidence": 0.9}',
                 sleep_s: float = 0.0,
                 raise_exc: Exception | None = None):
        fake_messages._text = text
        fake_messages._sleep = sleep_s
        fake_messages._raise = raise_exc
        client = _FakeClient(fake_messages)
        monkeypatch.setattr(claude_critic, "_client", lambda: client, raising=True)
        return client

    return _install


# ---------------------------------------------------------------------
# Test 1 — default OFF.
# ---------------------------------------------------------------------


def test_default_off_no_op(monkeypatch):
    """With env flag unset, score() must return immediately and never
    consult the SDK."""
    monkeypatch.delenv("PRISM42_ENABLE_CLAUDE_CRITIC", raising=False)

    # Sentinel: if `_client()` is ever called we'll know.
    called = {"hit": False}

    def _boom():
        called["hit"] = True
        raise AssertionError("client should not be touched in default-OFF")

    monkeypatch.setattr(claude_critic, "_client", _boom, raising=True)

    score = asyncio.run(
        claude_critic.score(
            session_id="test-default-off",
            caller_text="my friend stopped breathing",
            dispatcher_reply="Push hard and fast on the chest.",
            prior_dispatcher_replies=[],
            intent="instruct_cpr_compressions",
            fsm_state="critical_cpr",
            latched_facts={},
        )
    )

    assert called["hit"] is False
    assert score.failure_mode == ""
    assert score.suggested_correction is None
    assert score.risk_flag == "none"
    assert score.state_mismatch is False
    assert score.elapsed_ms == 0


# ---------------------------------------------------------------------
# Test 2 — happy path JSON parsing.
# ---------------------------------------------------------------------


def test_score_parses_canonical_response(monkeypatch, install_fake_client):
    """A well-formed JSON response is parsed into the CriticScore fields."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    install_fake_client(
        text=json.dumps({
            "suggested_correction": "Are they on the floor flat on their back?",
            "risk_flag": "high",
            "state_mismatch": True,
            "state_mismatch_reason": "FSM jumped to CPR before surface verify",
            "confidence": 0.92,
        })
    )

    score = asyncio.run(
        claude_critic.score(
            session_id="test-happy",
            caller_text="my friend stopped breathing",
            dispatcher_reply="Push hard and fast on the chest.",
            prior_dispatcher_replies=[],
            intent="instruct_cpr_compressions",
            fsm_state="critical_cpr",
            latched_facts={"surface_confirmed": False},
        )
    )

    assert score.failure_mode == ""
    assert score.risk_flag == "high"
    assert score.state_mismatch is True
    assert "surface verify" in score.state_mismatch_reason
    assert score.confidence == pytest.approx(0.92, rel=1e-3)
    assert score.suggested_correction is not None
    assert "floor flat" in score.suggested_correction
    assert score.token_usage == {"input_tokens": 500, "output_tokens": 100}


# ---------------------------------------------------------------------
# Test 3 — timeout at 750ms.
# ---------------------------------------------------------------------


def test_timeout_enforced_at_750ms(monkeypatch, install_fake_client):
    """If the SDK takes longer than 750ms, score() returns within the
    timeout window and surfaces failure_mode='timeout'."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    # Confirm default timeout. (We don't override.)

    install_fake_client(sleep_s=2.0)  # 2s > 750ms → must timeout

    score = asyncio.run(
        claude_critic.score(
            session_id="test-timeout",
            caller_text="address only",
            dispatcher_reply="What is happening at that location?",
            prior_dispatcher_replies=[],
            intent="request_emergency",
            fsm_state="intake",
            latched_facts={},
        )
    )

    assert score.failure_mode == "timeout"
    # elapsed_ms is set to the timeout budget on timeout.
    assert score.elapsed_ms == 750
    assert score.suggested_correction is None


def test_timeout_override_via_env(monkeypatch, install_fake_client):
    """Setting PRISM42_CLAUDE_CRITIC_TIMEOUT_MS overrides the 750
    default."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("PRISM42_CLAUDE_CRITIC_TIMEOUT_MS", "200")

    install_fake_client(sleep_s=1.0)  # 1s > 200ms → must timeout

    score = asyncio.run(
        claude_critic.score(
            session_id="test-timeout-override",
            caller_text="x",
            dispatcher_reply="y",
            prior_dispatcher_replies=[],
            intent="reprompt_caller",
            fsm_state="intake",
            latched_facts={},
        )
    )

    assert score.failure_mode == "timeout"
    assert score.elapsed_ms == 200


# ---------------------------------------------------------------------
# Test 4 — refusal regex drops the response.
# ---------------------------------------------------------------------


def test_refusal_regex_drops_response(monkeypatch, install_fake_client):
    """A response containing an Anthropic-style refusal should be
    dropped, the failure_mode set to 'refusal_regex', and the counter
    bumped."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    install_fake_client(
        text="I am an AI assistant and I cannot provide medical instructions for a real emergency."
    )

    score = asyncio.run(
        claude_critic.score(
            session_id="test-refusal",
            caller_text="i need help",
            dispatcher_reply="What is happening?",
            prior_dispatcher_replies=[],
            intent="request_emergency",
            fsm_state="intake",
            latched_facts={},
        )
    )

    assert score.failure_mode == "refusal_regex"
    assert score.suggested_correction is None
    assert score.risk_flag == "none"
    assert score.state_mismatch is False
    snap = claude_critic.get_token_usage_snapshot()
    assert snap["refusals"] >= 1
    # Token usage was still recorded — the call HAPPENED, we just don't
    # trust the rubric.
    assert snap["daily_calls"] >= 1


# ---------------------------------------------------------------------
# Test 5 — token-usage accumulator.
# ---------------------------------------------------------------------


def test_token_usage_accumulator(monkeypatch, install_fake_client):
    """Two successful score() calls should accumulate tokens."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    install_fake_client(
        text=json.dumps({
            "suggested_correction": None,
            "risk_flag": "none",
            "state_mismatch": False,
            "state_mismatch_reason": "",
            "confidence": 0.5,
        })
    )

    for sid in ("s-1", "s-2"):
        asyncio.run(
            claude_critic.score(
                session_id=sid,
                caller_text="hello",
                dispatcher_reply="What is the address of your emergency?",
                prior_dispatcher_replies=[],
                intent="request_location_and_emergency",
                fsm_state="intake",
                latched_facts={},
            )
        )

    snap = claude_critic.get_token_usage_snapshot()
    assert snap["daily_calls"] == 2
    # Each fake response = 500 in / 100 out.
    assert snap["daily_input"] == 1000
    assert snap["daily_output"] == 200
    assert "s-1" in snap["by_session"]
    assert "s-2" in snap["by_session"]


# ---------------------------------------------------------------------
# Test 6 — regenerate() is disabled.
# ---------------------------------------------------------------------


def test_regenerate_raises_not_implemented():
    """Per cycle-2BC user directive: hot-path regenerate() is disabled."""
    with pytest.raises(NotImplementedError):
        asyncio.run(
            claude_critic.regenerate(
                session_id="x",
                caller_text="x",
                rejected_reply="x",
                prior_dispatcher_reply="x",
                intent="x",
                pronoun_committed=False,
            )
        )


# ---------------------------------------------------------------------
# Test 7 — invalid risk_flag coerced to 'none'.
# ---------------------------------------------------------------------


def test_invalid_risk_flag_coerced(monkeypatch, install_fake_client):
    """Out-of-vocabulary risk_flag values must coerce to 'none'."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    install_fake_client(
        text=json.dumps({
            "suggested_correction": None,
            "risk_flag": "extreme",  # not in the allowed set
            "state_mismatch": False,
            "state_mismatch_reason": "",
            "confidence": 0.5,
        })
    )

    score = asyncio.run(
        claude_critic.score(
            session_id="test-coerce",
            caller_text="x",
            dispatcher_reply="y",
            prior_dispatcher_replies=[],
            intent="reprompt_caller",
            fsm_state="intake",
            latched_facts={},
        )
    )
    assert score.risk_flag == "none"
    assert score.failure_mode == ""


# ---------------------------------------------------------------------
# Test 8 — missing API key short-circuits with failure_mode='missing_key'.
# ---------------------------------------------------------------------


def test_missing_api_key(monkeypatch):
    """Even with the flag on, no key means we don't consult the SDK."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    called = {"hit": False}

    def _boom():
        called["hit"] = True
        raise AssertionError("client should not be touched on missing key")

    monkeypatch.setattr(claude_critic, "_client", _boom, raising=True)

    score = asyncio.run(
        claude_critic.score(
            session_id="test-missing-key",
            caller_text="hello",
            dispatcher_reply="hi",
            prior_dispatcher_replies=[],
            intent="reprompt_caller",
            fsm_state="intake",
            latched_facts={},
        )
    )
    assert called["hit"] is False
    assert score.failure_mode == "missing_key"


# ---------------------------------------------------------------------
# Test 9 — non-JSON response handled gracefully.
# ---------------------------------------------------------------------


def test_non_json_response(monkeypatch, install_fake_client):
    """If Opus returns plain prose, score() must surface failure_mode='exception'
    rather than blow up."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    install_fake_client(text="I think this looks fine to me.")

    score = asyncio.run(
        claude_critic.score(
            session_id="x",
            caller_text="x",
            dispatcher_reply="y",
            prior_dispatcher_replies=[],
            intent="reprompt_caller",
            fsm_state="intake",
            latched_facts={},
        )
    )
    assert score.failure_mode == "exception"
    assert score.suggested_correction is None


# ---------------------------------------------------------------------
# Test 10 — 429 / 5xx exception bucketing.
# ---------------------------------------------------------------------


def test_429_exception_bucketed(monkeypatch, install_fake_client):
    """A simulated 429 should land in failure_mode='api_429'."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    exc = SimpleNamespace()
    real_exc = type("RateLimitError", (Exception,), {"status_code": 429})
    install_fake_client(raise_exc=real_exc("rate limit hit"))

    score = asyncio.run(
        claude_critic.score(
            session_id="x",
            caller_text="x",
            dispatcher_reply="y",
            prior_dispatcher_replies=[],
            intent="reprompt_caller",
            fsm_state="intake",
            latched_facts={},
        )
    )
    assert score.failure_mode == "api_429"


def test_5xx_exception_bucketed(monkeypatch, install_fake_client):
    """A simulated 503 should land in failure_mode='api_5xx'."""
    monkeypatch.setenv("PRISM42_ENABLE_CLAUDE_CRITIC", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    real_exc = type("ServerError", (Exception,), {"status_code": 503})
    install_fake_client(raise_exc=real_exc("server down"))

    score = asyncio.run(
        claude_critic.score(
            session_id="x",
            caller_text="x",
            dispatcher_reply="y",
            prior_dispatcher_replies=[],
            intent="reprompt_caller",
            fsm_state="intake",
            latched_facts={},
        )
    )
    assert score.failure_mode == "api_5xx"
