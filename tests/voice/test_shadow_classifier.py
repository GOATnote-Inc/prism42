"""Cycle-2C Phase 1 — shadow structured classifier tests (mock-only).

The classifier is the FIRST observer added to the voice path that calls a
SECOND vLLM endpoint. Failure must NOT regress FSM behavior. These tests
prove:

1. Default-OFF: should_use_shadow_classifier() returns False unless the
   env flag is explicitly "1".
2. Schema validation drops malformed JSON (returns None + logs).
3. The 600 ms hard timeout is enforced via asyncio.wait_for.
4. FSM behavior is BYTE-EQUIVALENT regardless of classifier output —
   the WHOLE point of shadow mode. The classifier output is observed,
   not consumed.
5. dispatch_publisher.publish_perception is called when the classifier
   returns a valid result via the orchestrator hook helper.

All tests run offline. No vLLM or pod required.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add agents/livekit to sys.path so the modules import standalone.
_AGENT_DIR = Path(__file__).resolve().parents[2] / "agents" / "livekit"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import structured_classifier as sc  # noqa: E402
from dispatcher_fsm import DispatcherFSM, Intent  # noqa: E402


# ---------------------------------------------------------------------
# Helpers — fabricate a fake AsyncOpenAI-shaped client.
# ---------------------------------------------------------------------


def _make_mock_client(*, content: str | None = None, raise_exc: Exception | None = None,
                     delay_s: float = 0.0) -> MagicMock:
    """Build a stand-in for AsyncOpenAI exposing .chat.completions.create."""
    client = MagicMock()

    async def _create(**kwargs):
        if delay_s:
            await asyncio.sleep(delay_s)
        if raise_exc is not None:
            raise raise_exc
        # Mirror the shape openai >=1.x uses for parsed responses.
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    index=0,
                )
            ]
        )

    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = _create
    return client


_VALID_PAYLOAD = {
    "intent": "intake",
    "acuity": "P1",
    "address_candidate": {
        "raw_text": "421 Maple",
        "normalized": "421 Maple",
        "has_digit": True,
    },
    "awake": None,
    "breathing": None,
    "surface": "unknown",
    "caller_question": False,
    "caller_role": "third_party",
    "complaint_category": "medical",
    "negation_signal": False,
    "direct_question_kind": "none",
    "confidence": 0.95,
}


# ---------------------------------------------------------------------
# 1. Env flag default-OFF.
# ---------------------------------------------------------------------


def test_default_off(monkeypatch):
    """Without the env flag, the classifier is disabled."""
    monkeypatch.delenv("PRISM42_ENABLE_SHADOW_CLASSIFIER", raising=False)
    assert sc.should_use_shadow_classifier() is False


def test_explicit_zero_off(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_SHADOW_CLASSIFIER", "0")
    assert sc.should_use_shadow_classifier() is False


def test_explicit_one_on(monkeypatch):
    monkeypatch.setenv("PRISM42_ENABLE_SHADOW_CLASSIFIER", "1")
    assert sc.should_use_shadow_classifier() is True


# ---------------------------------------------------------------------
# 2. classify_async — the happy path returns a normalized result.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_async_valid_payload():
    client = _make_mock_client(content=json.dumps(_VALID_PAYLOAD))
    result = await sc.classify_async(client, "9-1-1 my husband has chest pain at 421 Maple")
    assert result is not None
    assert result.intent == "intake"
    assert result.acuity == "P1"
    assert result.address_candidate.has_digit is True
    assert result.address_candidate.raw_text == "421 Maple"
    assert result.caller_role == "third_party"
    assert result.complaint_category == "medical"
    assert result.confidence == pytest.approx(0.95)
    assert result.raw_json  # populated
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_classify_async_chair_negation_example():
    """Cycle-2R3 Bug 3 case — Example 3 from system-prompt-spec."""
    payload = dict(_VALID_PAYLOAD)
    payload.update(
        intent="verify",
        surface="chair",
        negation_signal=True,
        confidence=0.88,
        address_candidate={"raw_text": None, "normalized": None, "has_digit": False},
        awake=None,
        breathing=None,
    )
    client = _make_mock_client(content=json.dumps(payload))
    result = await sc.classify_async(client, "yeah, I mean they're in a chair")
    assert result is not None
    assert result.surface == "chair"
    assert result.negation_signal is True


# ---------------------------------------------------------------------
# 3. Failure modes — timeout, parse error, schema error, vllm error.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_async_timeout_returns_none():
    """The 600 ms hard timeout MUST fire; result MUST be None."""
    # Delay 0.7 s; timeout is 0.2 s for speed of the test.
    client = _make_mock_client(content=json.dumps(_VALID_PAYLOAD), delay_s=0.7)
    result = await sc.classify_async(client, "anything", timeout_ms=200)
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_default_timeout_is_600ms():
    """Verify the default ceiling matches Munger inversion §3."""
    import inspect
    sig = inspect.signature(sc.classify_async)
    assert sig.parameters["timeout_ms"].default == 600


@pytest.mark.asyncio
async def test_classify_async_invalid_json_returns_none():
    client = _make_mock_client(content="this is not json {")
    result = await sc.classify_async(client, "anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_schema_violation_returns_none():
    """Valid JSON but missing a required field — must return None."""
    bad = dict(_VALID_PAYLOAD)
    bad.pop("acuity")
    client = _make_mock_client(content=json.dumps(bad))
    result = await sc.classify_async(client, "anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_bad_enum_returns_none():
    """Enum violation in 'surface' must be rejected."""
    bad = dict(_VALID_PAYLOAD)
    bad["surface"] = "spaceship"  # not in enum
    client = _make_mock_client(content=json.dumps(bad))
    result = await sc.classify_async(client, "anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_vllm_exception_returns_none():
    client = _make_mock_client(raise_exc=RuntimeError("vllm down"))
    result = await sc.classify_async(client, "anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_empty_utterance_returns_none():
    client = _make_mock_client(content=json.dumps(_VALID_PAYLOAD))
    result = await sc.classify_async(client, "")
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_none_client_returns_none():
    result = await sc.classify_async(None, "anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_async_confidence_out_of_range_rejected():
    bad = dict(_VALID_PAYLOAD)
    bad["confidence"] = 1.5
    client = _make_mock_client(content=json.dumps(bad))
    result = await sc.classify_async(client, "anything")
    assert result is None


# ---------------------------------------------------------------------
# 4. FSM byte-equivalence — the classifier MUST NOT mutate FSM state.
# ---------------------------------------------------------------------


def _trace_fsm(utterances: list[str]) -> list[Intent]:
    """Drive a fresh FSM through `utterances`, return the intent sequence."""
    fsm = DispatcherFSM()
    return [fsm.transition(u) for u in utterances]


def test_fsm_unchanged_when_classifier_disabled(monkeypatch):
    """Sanity baseline — FSM intent trace is deterministic."""
    monkeypatch.delenv("PRISM42_ENABLE_SHADOW_CLASSIFIER", raising=False)
    seq = ["100 main street", "my husband has chest pain", "yeah he's in a chair"]
    trace1 = _trace_fsm(seq)
    trace2 = _trace_fsm(seq)
    assert trace1 == trace2


@pytest.mark.asyncio
async def test_fsm_byte_equivalent_with_or_without_classifier(monkeypatch):
    """The classifier is SHADOW — running it (or not) MUST NOT change the
    FSM intent trace. Phase 1 contract."""
    seq = ["100 main street", "my husband has chest pain", "yeah he's in a chair"]
    # Trace 1: never call the classifier.
    baseline = _trace_fsm(seq)
    # Trace 2: actually call the classifier with valid output for each
    # utterance, but feed an INDEPENDENT FSM. The mocked classifier
    # returns valid results; if anything in the wrapper accidentally
    # side-effected the FSM, the next FSM's trace would diverge.
    monkeypatch.setenv("PRISM42_ENABLE_SHADOW_CLASSIFIER", "1")
    fsm2 = DispatcherFSM()
    trace2: list[Intent] = []
    client = _make_mock_client(content=json.dumps(_VALID_PAYLOAD))
    for u in seq:
        intent = fsm2.transition(u)  # FSM transitions FIRST
        trace2.append(intent)
        # Then the shadow classifier runs (would-be fire-and-forget
        # in production). We `await` here to deterministically observe
        # that even when the classifier completes, the FSM state did
        # not get mutated by the wrapper.
        result = await sc.classify_async(client, u)
        assert result is not None  # mock always returns valid
    assert baseline == trace2


# ---------------------------------------------------------------------
# 5. publish_perception is called when the classifier returns a result.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_perception_called_on_valid_result():
    """The orchestrator hook calls dispatch_publisher.publish_perception
    after a successful classify_async. Use the helper from orchestrator.py
    directly — it's the contract."""
    import orchestrator as orch

    client = _make_mock_client(content=json.dumps(_VALID_PAYLOAD))
    dp = MagicMock()
    dp.publish_perception = MagicMock()

    await orch._run_shadow_classifier(
        client=client,
        utterance="9-1-1 my husband has chest pain at 421 Maple",
        turn_index=7,
        dispatch_publisher=dp,
        session_id="test-session",
    )
    dp.publish_perception.assert_called_once()
    kwargs = dp.publish_perception.call_args.kwargs
    assert kwargs["turn_index"] == 7
    payload = kwargs["classifier_payload"]
    assert payload["intent"] == "intake"
    assert payload["acuity"] == "P1"
    assert payload["address_candidate"]["has_digit"] is True
    assert payload["confidence"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_publish_perception_skipped_on_classifier_failure():
    """When classify_async returns None, we MUST NOT publish a perception."""
    import orchestrator as orch

    client = _make_mock_client(content="garbage not json")
    dp = MagicMock()
    dp.publish_perception = MagicMock()

    await orch._run_shadow_classifier(
        client=client,
        utterance="anything",
        turn_index=3,
        dispatch_publisher=dp,
        session_id="test-session",
    )
    dp.publish_perception.assert_not_called()


@pytest.mark.asyncio
async def test_publish_perception_skipped_when_no_publisher():
    """If dispatch_publisher is None, the helper exits silently."""
    import orchestrator as orch

    client = _make_mock_client(content=json.dumps(_VALID_PAYLOAD))
    # Should not raise.
    await orch._run_shadow_classifier(
        client=client,
        utterance="anything",
        turn_index=0,
        dispatch_publisher=None,
        session_id="test-session",
    )


# ---------------------------------------------------------------------
# 6. dispatch_publisher.publish_perception event shape contract.
# ---------------------------------------------------------------------


def test_publish_perception_event_shape(monkeypatch):
    """The published event must carry type='perception', turn_index,
    timestamp_ms, and classifier payload. Verifies contract with the
    DispatchPanel reducer in mvp/911-console-live."""
    monkeypatch.setenv("PRISM42_ENABLE_DISPATCH_PUBLISHER", "1")
    from dispatch_publisher import DispatchPublisher

    captured: list[dict] = []

    class _FakeRoom:
        local_participant = None

    dp = DispatchPublisher(_FakeRoom(), "test-session")
    # Monkeypatch the encoder to capture the event before enqueue.
    real_enqueue = dp._enqueue

    def _spy(evt):
        captured.append(evt)
        # Don't actually enqueue (no event loop in this test).

    dp._enqueue = _spy  # type: ignore[assignment]
    dp.publish_perception(
        turn_index=4,
        classifier_payload={"intent": "intake", "acuity": "P1", "raw_json": "{...}"},
    )
    assert len(captured) == 1
    evt = captured[0]
    assert evt["type"] == "perception"
    assert evt["turn_index"] == 4
    assert "timestamp_ms" in evt
    # Flat shape: schema fields spread onto the event, not nested.
    # raw_json is dropped from the wire payload to keep events lean.
    assert evt["intent"] == "intake"
    assert evt["acuity"] == "P1"
    assert "raw_json" not in evt
    assert "classifier" not in evt
    assert evt["session_id"] == "test-session"


def test_publish_perception_noop_when_publisher_disabled(monkeypatch):
    """When PRISM42_ENABLE_DISPATCH_PUBLISHER is unset, publish_perception
    is a no-op (mirrors publish_turn / publish_reply)."""
    monkeypatch.delenv("PRISM42_ENABLE_DISPATCH_PUBLISHER", raising=False)
    from dispatch_publisher import DispatchPublisher

    captured: list[dict] = []

    class _FakeRoom:
        local_participant = None

    dp = DispatchPublisher(_FakeRoom(), "test-session")
    dp._enqueue = lambda evt: captured.append(evt)  # type: ignore[assignment]
    dp.publish_perception(turn_index=1, classifier_payload={"intent": "intake"})
    assert captured == []
