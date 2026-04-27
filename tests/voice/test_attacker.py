"""attacker — unit tests.

Mocks `httpx.AsyncClient.post` so the suite runs without a live vLLM
server. Covers the off-path safety invariants from voice-5role-design.md:

  - default-OFF (env unset) is a no-op (no network)
  - probe() returns a structured dict, not a raw string (so the caller
    physically cannot append the output to LLM chat_ctx by accident)
  - severity is extracted heuristically from "low/medium/high" tag
  - on backend timeout / HTTP error / malformed response, returns None
    (never raises into the hot path)
  - PROBE_TEMPLATES selection is deterministic per turn_idx (so the
    same turn always asks the same probe question across reruns)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")  # CI may not have httpx; skip cleanly if absent

_LIVEKIT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_LIVEKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_LIVEKIT_DIR))

import attacker  # noqa: E402


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str = "NO (allow) low.", status_code: int = 200) -> None:
        self._text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": self._text}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }


class _FakeAsyncClient:
    """Async-context-manager replacement for httpx.AsyncClient."""

    def __init__(self, response: _FakeResponse | None = None,
                 raise_exc: Exception | None = None) -> None:
        self._response = response or _FakeResponse()
        self._raise_exc = raise_exc

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_a: object) -> None:
        return None

    async def post(self, *_a: object, **_kw: object) -> _FakeResponse:
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


# ---------------------------------------------------------------------
# Default-OFF (byte-equivalent invariant)
# ---------------------------------------------------------------------


def test_default_off_no_network(monkeypatch):
    """With PRISM42_ENABLE_ATTACKER unset, probe() returns None and never
    constructs an httpx client."""
    monkeypatch.delenv("PRISM42_ENABLE_ATTACKER", raising=False)

    sentinel = SimpleNamespace(constructed=False)

    def _explode(*_a, **_kw):
        sentinel.constructed = True
        raise AssertionError("AsyncClient should not be constructed when disabled")

    monkeypatch.setattr(attacker.httpx, "AsyncClient", _explode)

    result = asyncio.run(
        attacker.probe(
            caller_utterance="my friend collapsed",
            dispatcher_reply="Help is being sent.",
            session_id="s1",
            turn_idx=0,
        )
    )
    assert result is None
    assert sentinel.constructed is False


def test_should_use_attacker_env_flag(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_ATTACKER", raising=False)
    assert attacker.should_use_attacker() is False
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "1")
    assert attacker.should_use_attacker() is True
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "0")
    assert attacker.should_use_attacker() is False


# ---------------------------------------------------------------------
# Schema + off-path invariant
# ---------------------------------------------------------------------


def test_probe_returns_dict_not_string(monkeypatch):
    """Off-path guarantee: probe() returns a dict whose keys exclude any
    field that could be tokenized into chat_ctx if a careless caller
    `chat_ctx.add(...)` it. Specifically: no "content" / "role" key."""
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "1")
    monkeypatch.setattr(
        attacker.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(_FakeResponse("NO (allow) low.")),
    )

    result = asyncio.run(
        attacker.probe(
            caller_utterance="caller text",
            dispatcher_reply="dispatcher text",
            session_id="s1",
            turn_idx=0,
        )
    )
    assert isinstance(result, dict)
    assert set(result.keys()) == {"probe", "finding", "severity", "elapsed_ms"}
    # negative assertions — keys that would betray off-path violation:
    assert "role" not in result
    assert "content" not in result
    assert "messages" not in result


@pytest.mark.parametrize(
    "text,expected_severity",
    [
        ("NO (allow) low.", "low"),
        ("YES (block) medium.", "medium"),
        ("YES (block) high.", "high"),
        ("YES (block) critical risk.", "low"),  # only "low/medium/high" tags recognized
        ("YES (block) MODERATE.", "medium"),
        ("yes high — multiple unsafe assumptions", "high"),
    ],
)
def test_severity_extraction(monkeypatch, text, expected_severity):
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "1")
    monkeypatch.setattr(
        attacker.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(_FakeResponse(text)),
    )
    result = asyncio.run(
        attacker.probe(
            caller_utterance="x",
            dispatcher_reply="y",
            session_id="s1",
            turn_idx=0,
        )
    )
    assert result is not None
    assert result["severity"] == expected_severity


# ---------------------------------------------------------------------
# Error-handling — never raise into the hot path
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("read timeout"),
        httpx.HTTPStatusError("500", request=None, response=None),
    ],
)
def test_backend_failure_returns_none(monkeypatch, exc):
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "1")
    monkeypatch.setattr(
        attacker.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(raise_exc=exc),
    )
    result = asyncio.run(
        attacker.probe(
            caller_utterance="x",
            dispatcher_reply="y",
            session_id="s1",
            turn_idx=0,
        )
    )
    assert result is None


def test_malformed_json_returns_none(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "1")

    class _BadJsonResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": []}  # missing message → IndexError

    monkeypatch.setattr(
        attacker.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(_BadJsonResponse()),
    )
    result = asyncio.run(
        attacker.probe(
            caller_utterance="x",
            dispatcher_reply="y",
            session_id="s1",
            turn_idx=0,
        )
    )
    assert result is None


# ---------------------------------------------------------------------
# Determinism — same turn_idx → same probe template
# ---------------------------------------------------------------------


def test_probe_template_is_deterministic_per_turn(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_ATTACKER", "1")
    seen_prompts: list[str] = []

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, _url: str, *, json: dict, **_kw) -> _FakeResponse:
            seen_prompts.append(json["messages"][0]["content"])
            return _FakeResponse("NO (allow) low.")

    monkeypatch.setattr(attacker.httpx, "AsyncClient", lambda *a, **kw: _CapturingClient())

    asyncio.run(attacker.probe(caller_utterance="x", dispatcher_reply="y", turn_idx=0))
    asyncio.run(attacker.probe(caller_utterance="x", dispatcher_reply="y", turn_idx=0))
    assert seen_prompts[0] == seen_prompts[1]
