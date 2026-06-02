"""TritonJudge — OpenAI-compatible chat-completions rubric grader.

Targets a locally-served Llama-3.1-Nemotron-70B-Instruct (AWQ-int4 on H100
by default; could be the same H200-served model when no separate judge pod
is available).

Rubric template is verbatim openai/simple-evals GRADER_TEMPLATE — kept in
the bridge module to preserve provenance.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from _healthbench_grader_bridge import GRADER_TEMPLATE, RubricItem  # noqa: E402


class JudgeAuthError(RuntimeError):
    """Raised when the judge endpoint refuses requests (401/403/404).

    Mirrors scripts.healthbench_runner.JudgeAuthError so the run-halt
    semantics match the original Anthropic-judge behavior.
    """


JUDGE_OUTPUT_SCHEMA_HINT = (
    'Return only a JSON object with fields "explanation" (string) and '
    '"criteria_met" (boolean). No markdown, no preamble.'
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_judge_json(raw: str) -> dict[str, Any] | None:
    """Extract a {"criteria_met": bool, "explanation": str} dict.

    Tolerates the model's tendency to wrap in ```json fences. Returns
    None on parse failure so the caller can retry.
    """
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        # First {...} block
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            text = m.group(0)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if "criteria_met" not in obj:
        return None
    obj["criteria_met"] = bool(obj["criteria_met"])
    obj.setdefault("explanation", "")
    return obj


def make_triton_judge(
    *,
    base_url: str,
    model_id: str,
    audit_log_path: Path | None = None,
    max_retries: int = 3,
    max_output_tokens: int = 512,
    timeout_s: float = 120.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Callable[[str, RubricItem], dict]:
    """Return a judge_fn that posts to an OpenAI-compatible chat endpoint.

    The endpoint MUST be a 127.0.0.1 / pod-local URL — never a cloud
    provider. Caller is responsible for the ssh-tunnel that exposes it.

    Retry policy mirrors the Anthropic judge:
      - 429 / 5xx       : exponential backoff up to max_retries
      - 401 / 403 / 404 : raise JudgeAuthError — halt the run
      - JSON parse fail : retry up to max_retries
      - exhausted       : return criteria_met=None, exhausted=True
    """
    if not base_url.startswith(("http://127.0.0.1", "http://localhost")):
        raise ValueError(
            f"sovereign judge endpoint must be 127.0.0.1/localhost, got {base_url!r}. "
            "External URLs defeat the no-cloud-LLM-keys design — see CLAUDE.md §2."
        )

    def _append_audit(record: dict) -> None:
        if audit_log_path is None:
            return
        audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_log_path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    client = httpx.Client(base_url=base_url, timeout=timeout_s)

    def _judge(conversation: str, item: RubricItem) -> dict:
        prompt = (
            GRADER_TEMPLATE.replace("<<conversation>>", conversation).replace(
                "<<rubric_item>>", str(item)
            )
            + "\n\n"
            + JUDGE_OUTPUT_SCHEMA_HINT
        )
        body = {
            "model": model_id,
            "max_tokens": max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        last_error: str | None = None
        raw_text = ""
        for attempt in range(max_retries):
            started = time.time()
            try:
                # base_url is expected to end with /v1; relative path so
                # httpx appends correctly (RFC 3986: leading slash would
                # replace the base_url path and emit /v1/v1/...).
                resp = client.post("chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_error = f"transport: {exc}"
                if attempt + 1 < max_retries:
                    sleep_fn(2**attempt)
                    continue
                _append_audit(
                    {
                        "ts": _now_iso(),
                        "criterion": item.criterion[:200],
                        "tags": list(item.tags),
                        "attempt": attempt,
                        "error": last_error,
                        "duration_ms": int((time.time() - started) * 1000),
                    }
                )
                break

            status = resp.status_code
            if status in (401, 403, 404):
                _append_audit(
                    {
                        "ts": _now_iso(),
                        "criterion": item.criterion[:200],
                        "tags": list(item.tags),
                        "attempt": attempt,
                        "error": f"auth-halt: {status}",
                        "duration_ms": int((time.time() - started) * 1000),
                    }
                )
                raise JudgeAuthError(
                    f"sovereign judge at {base_url} returned {status}; halting. "
                    "Check the Triton model is loaded and the ssh tunnel is open."
                )
            if status == 429 or 500 <= status < 600:
                last_error = f"http-{status}"
                if attempt + 1 < max_retries:
                    sleep_fn(2**attempt)
                    continue
                break

            try:
                payload = resp.json()
                raw_text = payload["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                last_error = f"bad-response: {exc}: {resp.text[:200]}"
                if attempt + 1 < max_retries:
                    sleep_fn(1)
                    continue
                break

            parsed = _parse_judge_json(raw_text)
            if parsed is None:
                last_error = f"json-parse-failed: {raw_text[:200]}"
                if attempt + 1 < max_retries:
                    sleep_fn(1)
                    continue
                break

            verdict = {
                "criteria_met": parsed["criteria_met"],
                "explanation": parsed.get("explanation", ""),
                "judge": "triton",
                "judge_model": model_id,
                "raw": raw_text[:2000],
                "duration_ms": int((time.time() - started) * 1000),
                "attempt": attempt,
            }
            _append_audit(
                {
                    "ts": _now_iso(),
                    "criterion": item.criterion[:200],
                    "tags": list(item.tags),
                    **verdict,
                }
            )
            return verdict

        # Exhausted retries — recuse the item.
        return {
            "criteria_met": None,
            "explanation": last_error or "exhausted",
            "judge": "triton",
            "judge_model": model_id,
            "raw": raw_text[:2000],
            "exhausted": True,
        }

    return _judge
