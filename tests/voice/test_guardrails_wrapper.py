"""guardrails_wrapper — unit tests.

Covers the off-path safety invariants of the NeMo Guardrails 0.21.0
wiring without requiring the SDK or the Anthropic API key on the test
runner:

  - default-OFF (env unset) returns None and DOES NOT import nemoguardrails
    (verified by ensuring the rails singleton stays None)
  - check_input/check_output return dict-only (no chat_ctx-shaped keys)
  - timeout returns None instead of raising into the hot path
  - SDK init failure (config dir missing / class import fails) returns
    None instead of crashing the worker
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_LIVEKIT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_LIVEKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_LIVEKIT_DIR))

import guardrails_wrapper as gw  # noqa: E402


# ---------------------------------------------------------------------
# Default-OFF
# ---------------------------------------------------------------------


def test_default_off_check_input(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_GUARDRAILS", raising=False)
    # Reset the singleton so a previous test can't leak SDK state
    gw._rails_singleton = None
    result = asyncio.run(gw.check_input("hello"))
    assert result is None
    # SDK must NOT have been initialized when disabled
    assert gw._rails_singleton is None


def test_default_off_check_output(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_GUARDRAILS", raising=False)
    gw._rails_singleton = None
    result = asyncio.run(gw.check_output("dispatcher reply"))
    assert result is None
    assert gw._rails_singleton is None


def test_should_use_env_flag(monkeypatch):
    monkeypatch.delenv("PRISM42_ENABLE_GUARDRAILS", raising=False)
    assert gw.should_use_guardrails() is False
    monkeypatch.setenv("PRISM42_ENABLE_GUARDRAILS", "1")
    assert gw.should_use_guardrails() is True


# ---------------------------------------------------------------------
# SDK init failure paths — never crash the worker
# ---------------------------------------------------------------------


def test_init_failure_returns_none(monkeypatch):
    """If RailsConfig.from_path raises (e.g. config dir missing), the
    wrapper logs and returns None — does NOT propagate to the caller."""
    monkeypatch.setenv("PRISM42_ENABLE_GUARDRAILS", "1")
    monkeypatch.setenv(
        "PRISM42_GUARDRAILS_CONFIG_DIR", "/nonexistent/path/nope-not-here"
    )
    gw._rails_singleton = None
    result = asyncio.run(gw.check_input("x"))
    assert result is None


# ---------------------------------------------------------------------
# Schema + off-path invariant — when rails fire successfully
# ---------------------------------------------------------------------


class _FakeRails:
    """In-memory stand-in for nemoguardrails.LLMRails."""

    def __init__(self, response_text: str = "NO (allow) low.",
                 sleep_s: float = 0.0,
                 raise_exc: Exception | None = None) -> None:
        self._response_text = response_text
        self._sleep_s = sleep_s
        self._raise_exc = raise_exc

    async def generate_async(self, *, messages: list[dict]) -> dict:
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        if self._raise_exc is not None:
            raise self._raise_exc
        return {"role": "assistant", "content": self._response_text}


def _force_rails(monkeypatch, rails: _FakeRails) -> None:
    """Bypass _get_rails() lazy-init by stuffing the singleton directly."""
    gw._rails_singleton = rails


def test_check_input_returns_dict_not_string(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_GUARDRAILS", "1")
    _force_rails(monkeypatch, _FakeRails("NO (allow) low — looks routine."))
    try:
        result = asyncio.run(gw.check_input("my friend collapsed"))
    finally:
        gw._rails_singleton = None
    assert isinstance(result, dict)
    assert set(result.keys()) == {"allowed", "reason", "severity", "rail", "elapsed_ms"}
    assert "content" not in result
    assert "messages" not in result
    assert result["rail"] == "input"
    assert result["allowed"] is True


def test_check_output_blocks_when_refused(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_GUARDRAILS", "1")
    _force_rails(monkeypatch, _FakeRails("YES (block) high — unsafe medical advice."))
    try:
        result = asyncio.run(gw.check_output("Take three of the patient's pills."))
    finally:
        gw._rails_singleton = None
    assert result is not None
    assert result["allowed"] is False
    assert result["severity"] == "high"
    assert result["rail"] == "output"


def test_check_input_timeout_returns_none(monkeypatch):
    """If the rail takes longer than PRISM42_GUARDRAILS_TIMEOUT_MS, the
    wrapper returns None — never blocks the hot path."""
    monkeypatch.setenv("PRISM42_ENABLE_GUARDRAILS", "1")
    monkeypatch.setenv("PRISM42_GUARDRAILS_TIMEOUT_MS", "10")  # 10 ms
    # Reload module-level constant; the wrapper reads on import, so we
    # patch the runtime value directly.
    monkeypatch.setattr(gw, "DEFAULT_TIMEOUT_MS", 10)
    _force_rails(monkeypatch, _FakeRails(sleep_s=0.5))  # 500 ms > 10 ms timeout
    try:
        result = asyncio.run(gw.check_input("x"))
    finally:
        gw._rails_singleton = None
    assert result is None


def test_check_input_backend_exception_returns_none(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_GUARDRAILS", "1")
    _force_rails(monkeypatch, _FakeRails(raise_exc=RuntimeError("backend down")))
    try:
        result = asyncio.run(gw.check_input("x"))
    finally:
        gw._rails_singleton = None
    assert result is None
