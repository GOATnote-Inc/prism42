"""Tests for the real Opus-4.7 judge factory in healthbench_runner.py.

T4.6c step-a (safety-critical path). These tests exercise every branch
of _make_anthropic_judge without touching the real Anthropic SDK —
they inject a stub client so the factory's retry / auth-halt / parse
/ audit-log semantics are verified in isolation.

Hard rules under test (Level-1-trauma-CTO posture):

  - 401 / 403 from the judge API halts LOUD via JudgeAuthError.
    Rationale: a silently-failing judge poisons every trajectory with
    reward=0 and resume cannot detect it.
  - 429 and 5xx are retried with exponential backoff up to max_retries.
  - Parse failures are retried within max_retries; exhausted retries
    return criteria_met=None (_real_grader recuses the item) rather
    than fabricating a verdict.
  - Every judge call — success or failure — writes one JSONL line to
    the audit log. A physician can re-review any single verdict.
  - An empty rubric still returns a scalar score of 0.0 (not None), so
    downstream numeric pipelines do not need None handling for that
    edge case.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import healthbench_runner as hbr  # noqa: E402
from _healthbench_grader_bridge import RubricItem  # noqa: E402


# --------------------------------------------------------------
# Stub Anthropic client — shaped like anthropic.Anthropic().messages.create
# --------------------------------------------------------------


class _Block:
    """Mimics anthropic.types.ContentBlock for type=text."""

    def __init__(self, text: str, type: str = "text") -> None:
        self.type = type
        self.text = text


class _Response:
    """Mimics anthropic.types.Message — only .content matters to the factory."""

    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]
        self.usage = type("Usage", (), {"input_tokens": 100, "output_tokens": 40})()


class _HTTPError(Exception):
    """Mimics anthropic.APIStatusError — status_code attribute is what we check."""

    def __init__(self, status_code: int, message: str = "http error") -> None:
        super().__init__(message)
        self.status_code = status_code


class _StubClient:
    """Replays a list of responses (or exceptions) in call order."""

    def __init__(self, responses: list[Any]) -> None:
        self._iter = iter(responses)
        self._call_log: list[dict] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self._call_log.append(kwargs)
        item = next(self._iter)
        if isinstance(item, Exception):
            raise item
        return item


# --------------------------------------------------------------
# _parse_judge_json — accept fenced, untagged-fenced, bare; reject broken
# --------------------------------------------------------------


def test_parse_fenced_json() -> None:
    out = hbr._parse_judge_json(
        'preamble\n```json\n{"criteria_met": true, "explanation": "ok"}\n```\n'
    )
    assert out == {"criteria_met": True, "explanation": "ok"}


def test_parse_untagged_fenced() -> None:
    out = hbr._parse_judge_json('```\n{"criteria_met": false}\n```')
    assert out == {"criteria_met": False, "explanation": ""}


def test_parse_bare_json() -> None:
    out = hbr._parse_judge_json('   {"criteria_met": true, "explanation": "yes"}  ')
    assert out["criteria_met"] is True


def test_parse_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        hbr._parse_judge_json("")


def test_parse_rejects_non_json_prose() -> None:
    with pytest.raises(ValueError, match="no JSON"):
        hbr._parse_judge_json("the model decided yes")


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="JSON invalid"):
        hbr._parse_judge_json("{criteria_met: yes}")


def test_parse_rejects_missing_field() -> None:
    with pytest.raises(ValueError, match="missing 'criteria_met'"):
        hbr._parse_judge_json('{"explanation": "nope"}')


def test_parse_coerces_truthy() -> None:
    # bool("truthy") is True — ensure the wrapper doesn't drop the coercion
    out = hbr._parse_judge_json('{"criteria_met": 1, "explanation": "x"}')
    assert out["criteria_met"] is True


# --------------------------------------------------------------
# _status_code_of — recognize common status-carrying shapes
# --------------------------------------------------------------


def test_status_code_from_attribute() -> None:
    exc = _HTTPError(429)
    assert hbr._status_code_of(exc) == 429


def test_status_code_from_response_attr() -> None:
    class _Resp:
        status_code = 500

    class _E(Exception):
        response = _Resp()

    assert hbr._status_code_of(_E()) == 500


def test_status_code_none_when_absent() -> None:
    assert hbr._status_code_of(RuntimeError("plain")) is None


# --------------------------------------------------------------
# _make_anthropic_judge — retry / halt / audit semantics
# --------------------------------------------------------------


_ITEM = RubricItem(criterion="Mentions LP", points=1.0, tags=["axis:accuracy"])


def test_judge_happy_path(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    client = _StubClient([_Response('{"criteria_met": true, "explanation": "fine"}')])
    judge = hbr._make_anthropic_judge(client, audit_log_path=audit)
    result = judge("conversation here", _ITEM)
    assert result["criteria_met"] is True
    assert result["explanation"] == "fine"
    assert result["attempt_count"] == 1
    assert audit.exists()
    lines = audit.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["parsed"]["criteria_met"] is True


def test_judge_halts_loud_on_401(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    client = _StubClient([_HTTPError(401, "unauthorized")])
    judge = hbr._make_anthropic_judge(client, audit_log_path=audit)
    with pytest.raises(hbr.JudgeAuthError, match="auth failed"):
        judge("conv", _ITEM)
    # Audit log still captures the failed attempt
    assert "auth-halt" in audit.read_text()


def test_judge_halts_loud_on_403(tmp_path: Path) -> None:
    client = _StubClient([_HTTPError(403, "forbidden")])
    judge = hbr._make_anthropic_judge(client, audit_log_path=tmp_path / "a.jsonl")
    with pytest.raises(hbr.JudgeAuthError):
        judge("conv", _ITEM)


def test_judge_retries_on_429_then_succeeds(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    sleeps: list[float] = []
    client = _StubClient(
        [
            _HTTPError(429, "rate-limited"),
            _Response('{"criteria_met": false, "explanation": "nope"}'),
        ]
    )
    judge = hbr._make_anthropic_judge(
        client, audit_log_path=audit, sleep_fn=sleeps.append
    )
    result = judge("conv", _ITEM)
    assert result["criteria_met"] is False
    assert result["attempt_count"] == 2
    # Exponential backoff: first retry sleeps 2**0 = 1s
    assert sleeps == [1]


def test_judge_retries_on_5xx_then_succeeds(tmp_path: Path) -> None:
    sleeps: list[float] = []
    client = _StubClient(
        [
            _HTTPError(503, "unavailable"),
            _HTTPError(502, "bad gateway"),
            _Response('{"criteria_met": true, "explanation": "ok"}'),
        ]
    )
    judge = hbr._make_anthropic_judge(
        client, audit_log_path=tmp_path / "a.jsonl", sleep_fn=sleeps.append
    )
    result = judge("conv", _ITEM)
    assert result["criteria_met"] is True
    assert result["attempt_count"] == 3
    # Exponential backoff: 2**0=1, 2**1=2
    assert sleeps == [1, 2]


def test_judge_exhausts_retries_then_recuses(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    client = _StubClient(
        [_HTTPError(500), _HTTPError(500), _HTTPError(500)]
    )
    judge = hbr._make_anthropic_judge(
        client, audit_log_path=audit, max_retries=3, sleep_fn=lambda _s: None
    )
    result = judge("conv", _ITEM)
    # Recusal contract: criteria_met is None, not True/False
    assert result["criteria_met"] is None
    assert result.get("exhausted") is True
    assert "judge-failed" in result["explanation"]


def test_judge_retries_on_parse_failure(tmp_path: Path) -> None:
    sleeps: list[float] = []
    client = _StubClient(
        [
            _Response("the model says yes"),  # no JSON at all
            _Response('```json\n{"criteria_met": true}\n```'),
        ]
    )
    judge = hbr._make_anthropic_judge(
        client, audit_log_path=tmp_path / "a.jsonl", sleep_fn=sleeps.append
    )
    result = judge("conv", _ITEM)
    assert result["criteria_met"] is True
    assert result["attempt_count"] == 2
    assert sleeps == [1]


def test_judge_parse_failures_exhaust_to_recusal(tmp_path: Path) -> None:
    client = _StubClient(
        [
            _Response("no json"),
            _Response("still no json"),
            _Response("definitely no json"),
        ]
    )
    judge = hbr._make_anthropic_judge(
        client,
        audit_log_path=tmp_path / "a.jsonl",
        max_retries=3,
        sleep_fn=lambda _s: None,
    )
    result = judge("conv", _ITEM)
    assert result["criteria_met"] is None
    assert "parse" in result["explanation"]


def test_judge_400_is_non_retriable(tmp_path: Path) -> None:
    # 400 = malformed request; retrying won't help. Should recuse after one try.
    client = _StubClient([_HTTPError(400, "bad request")])
    judge = hbr._make_anthropic_judge(
        client,
        audit_log_path=tmp_path / "a.jsonl",
        max_retries=3,
        sleep_fn=lambda _s: None,
    )
    result = judge("conv", _ITEM)
    assert result["criteria_met"] is None


def test_judge_audit_log_captures_per_call(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    client = _StubClient(
        [
            _Response('{"criteria_met": true}'),
            _Response('{"criteria_met": false, "explanation": "no"}'),
        ]
    )
    judge = hbr._make_anthropic_judge(client, audit_log_path=audit)
    judge("conv-A", _ITEM)
    judge("conv-B", _ITEM)
    lines = audit.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert rec["criterion"].startswith("Mentions LP")
        assert rec["tags"] == ["axis:accuracy"]
        assert "duration_ms" in rec


def test_judge_uses_grader_template_placeholders(tmp_path: Path) -> None:
    client = _StubClient([_Response('{"criteria_met": true}')])
    judge = hbr._make_anthropic_judge(client, audit_log_path=tmp_path / "a.jsonl")
    judge("user: hi\nassistant: go to the ED", _ITEM)
    # The stub captured the prompt in kwargs["messages"][0]["content"]
    prompt = client._call_log[0]["messages"][0]["content"]
    assert "<<conversation>>" not in prompt
    assert "<<rubric_item>>" not in prompt
    assert "go to the ED" in prompt
    assert "Mentions LP" in prompt


# --------------------------------------------------------------
# _real_grader × real-judge semantics — recusal propagation
# --------------------------------------------------------------


def test_real_grader_recuses_items_from_failed_judge() -> None:
    """Judge returning criteria_met=None removes the item from the score."""

    def flaky_judge(_conv: str, item: RubricItem) -> dict:
        if "fail" in item.criterion:
            return {"criteria_met": None, "explanation": "judge-failed: test"}
        return {"criteria_met": True, "explanation": "ok"}

    example = {
        "id": "x",
        "prompt": "q",
        "rubrics": [
            {"criterion": "pass me", "points": 0.6, "tags": ["axis:accuracy"]},
            {"criterion": "fail me", "points": 0.4, "tags": ["axis:accuracy"]},
        ],
    }
    grade = hbr._real_grader("response", example, judge_fn=flaky_judge)
    # Denominator is ONLY the successfully judged subset (0.6). Score = 0.6/0.6 = 1.0.
    assert grade["score"] == pytest.approx(1.0)
    assert grade["judge_incomplete"] == 1
    assert grade["judge_incomplete_fraction"] == pytest.approx(0.5)


def test_real_grader_returns_none_when_all_recused() -> None:
    def always_fail(_c: str, _i: RubricItem) -> dict:
        return {"criteria_met": None, "explanation": "broken"}

    example = {
        "id": "x",
        "prompt": "q",
        "rubrics": [
            {"criterion": "a", "points": 1.0, "tags": ["axis:accuracy"]},
        ],
    }
    grade = hbr._real_grader("response", example, judge_fn=always_fail)
    assert grade["score"] is None
    assert grade["judge_incomplete"] == 1
    assert grade["judge_incomplete_fraction"] == 1.0


# --------------------------------------------------------------
# _aggregate — recusal semantics
# --------------------------------------------------------------


def test_aggregate_skips_recused_examples() -> None:
    per_ex = [
        {"score": 0.8, "per_axis": {"accuracy": 0.8}},
        {"score": None, "per_axis": {"accuracy": None}},
        {"score": 0.6, "per_axis": {"accuracy": 0.6}},
    ]
    agg = hbr._aggregate(per_ex)
    assert agg["n"] == 3
    assert agg["n_scored"] == 2
    assert agg["n_recused"] == 1
    assert agg["score"] == pytest.approx(0.7)  # mean of 0.8, 0.6


def test_aggregate_all_recused_returns_none() -> None:
    per_ex = [
        {"score": None, "per_axis": {"accuracy": None}},
        {"score": None, "per_axis": {"accuracy": None}},
    ]
    agg = hbr._aggregate(per_ex)
    assert agg["score"] is None
    assert agg["n_recused"] == 2
    assert agg["n_scored"] == 0


# --------------------------------------------------------------
# _preflight_judge_key — halt on 401; pass on 200
# --------------------------------------------------------------


def test_preflight_passes_on_ok() -> None:
    client = _StubClient([_Response('{"criteria_met": true}')])
    # No raise
    hbr._preflight_judge_key(client, model_id="claude-opus-4-7")


def test_preflight_raises_on_401() -> None:
    client = _StubClient([_HTTPError(401, "unauthorized")])
    with pytest.raises(hbr.JudgeAuthError, match="preflight"):
        hbr._preflight_judge_key(client, model_id="claude-opus-4-7")


def test_preflight_reraises_other_errors() -> None:
    client = _StubClient([_HTTPError(500, "server error")])
    # Non-auth errors propagate as-is (not JudgeAuthError).
    with pytest.raises(_HTTPError, match="server error"):
        hbr._preflight_judge_key(client, model_id="claude-opus-4-7")
