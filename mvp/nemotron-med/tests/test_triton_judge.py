"""Unit tests for mla.judges.triton — pure stdlib + httpx mock."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from _healthbench_grader_bridge import RubricItem  # noqa: E402
from mla.judges.triton import (  # noqa: E402
    JudgeAuthError,
    _parse_judge_json,
    make_triton_judge,
)


class TestParseJudgeJson:
    def test_plain_json(self) -> None:
        out = _parse_judge_json('{"criteria_met": true, "explanation": "yes"}')
        assert out == {"criteria_met": True, "explanation": "yes"}

    def test_fenced_json(self) -> None:
        out = _parse_judge_json(
            '```json\n{"criteria_met": false, "explanation": "no"}\n```'
        )
        assert out == {"criteria_met": False, "explanation": "no"}

    def test_with_preamble(self) -> None:
        out = _parse_judge_json(
            'Sure, here:\n{"criteria_met": true, "explanation": "matches"}'
        )
        assert out == {"criteria_met": True, "explanation": "matches"}

    def test_missing_field_returns_none(self) -> None:
        assert _parse_judge_json('{"explanation": "no field"}') is None

    def test_invalid_json_returns_none(self) -> None:
        assert _parse_judge_json("not json at all") is None


class TestMakeTritonJudge:
    def test_rejects_external_url(self) -> None:
        with pytest.raises(ValueError, match="127.0.0.1"):
            make_triton_judge(
                base_url="https://api.openai.com",
                model_id="gpt-4",
            )

    def test_accepts_localhost(self, tmp_path: Path) -> None:
        judge = make_triton_judge(
            base_url="http://127.0.0.1:8000",
            model_id="local",
            audit_log_path=tmp_path / "audit.jsonl",
        )
        assert callable(judge)

    def test_auth_halt_on_401(self, tmp_path: Path) -> None:
        judge = make_triton_judge(
            base_url="http://127.0.0.1:8000",
            model_id="local",
            audit_log_path=tmp_path / "audit.jsonl",
        )
        item = RubricItem(criterion="x", points=1.0, tags=["a"])

        def raise_401(*args, **kwargs):
            req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
            return httpx.Response(401, request=req)

        with patch("httpx.Client.post", side_effect=raise_401):
            with pytest.raises(JudgeAuthError):
                judge("conversation text", item)

    def test_happy_path(self, tmp_path: Path) -> None:
        judge = make_triton_judge(
            base_url="http://127.0.0.1:8000",
            model_id="local",
            audit_log_path=tmp_path / "audit.jsonl",
            sleep_fn=lambda _: None,
        )
        item = RubricItem(criterion="States red flags", points=0.5, tags=["R1"])

        def ok_response(*args, **kwargs):
            req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
            return httpx.Response(
                200,
                request=req,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"criteria_met": true, '
                                '"explanation": "Mentions red flags."}'
                            }
                        }
                    ]
                },
            )

        with patch("httpx.Client.post", side_effect=ok_response):
            verdict = judge("user: chest pain ...", item)

        assert verdict["criteria_met"] is True
        assert verdict["judge"] == "triton"
        assert verdict["judge_model"] == "local"
        # Audit log written.
        audit = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
        assert len(audit) == 1

    def test_exhausts_after_3_bad_responses(self, tmp_path: Path) -> None:
        judge = make_triton_judge(
            base_url="http://127.0.0.1:8000",
            model_id="local",
            audit_log_path=tmp_path / "audit.jsonl",
            sleep_fn=lambda _: None,
        )
        item = RubricItem(criterion="x", points=1.0, tags=["a"])

        def garbage(*args, **kwargs):
            req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
            return httpx.Response(
                200,
                request=req,
                json={
                    "choices": [
                        {"message": {"content": "I don't know how to JSON."}}
                    ]
                },
            )

        with patch("httpx.Client.post", side_effect=garbage):
            verdict = judge("conv", item)

        assert verdict["criteria_met"] is None
        assert verdict["exhausted"] is True
