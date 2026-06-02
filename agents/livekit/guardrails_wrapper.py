"""guardrails_wrapper — NeMo Guardrails 0.21.0 input/output rails for prism42.

Per nvidia-voice-stack-architecture.md §1, the NVIDIA reference architecture
puts NeMo Guardrails between Riva ASR → Nemotron-LLM → Riva TTS as an
input rail (jailbreak / off-topic detection) and an output rail (medical
safety / harmful-content veto). v0.21.0 (March 12 2026 stable) supports
parallel rail execution via `ExecutionMode.ASYNC`, avoiding the ~150 ms
sequential penalty documented in §4 of the brief.

This module is the thin async-friendly wrapper that the prism42 voice
worker calls. The actual rail definitions live in
`agents/livekit/guardrails-config/` (config.yml + prompts.yml).

Wiring
------
Two hooks in the voice loop:

1. `check_input(caller_utterance) → result | None` — runs after STT, before
   the FSM/LLM. On `result["allowed"] is False`, the dispatcher should
   short-circuit to a deterministic refusal phrase via response_gate.
2. `check_output(dispatcher_reply) → result | None` — runs in parallel
   with TTS chunking. On `result["allowed"] is False` for a chunk that
   has not yet been emitted, the orchestrator can intercept; for chunks
   already in flight, the audit is recorded for post-session review.

Both default to `asyncio.create_task(...)` invocation so they never block
the hot path; the caller decides whether to await with a tight timeout.

Default OFF
-----------
`PRISM42_ENABLE_GUARDRAILS=1` to enable. With the flag unset, the
functions return None immediately — no `nemoguardrails` import, no
network call, byte-equivalent to current voice loop.

Backend
-------
Guardrails delegates to the configured provider in `config.yml`. Default
config uses Anthropic Claude Sonnet 4.6 (cheap, fast, already on the
ANTHROPIC_API_KEY env path used by `worker.py`). On a pod with local
vLLM Nemotron available, swap `models[0].engine` to `openai` with a
custom `base_url` pointing at `http://127.0.0.1:8001/v1` for sub-100 ms
rail latency.

Output schema
-------------
```
{
  "allowed":     bool,    # rail's verdict on whether content passes
  "reason":      str,     # one-sentence rationale from the rail prompt
  "severity":    str,     # "low" | "medium" | "high"  (heuristic)
  "rail":        str,     # "input" | "output"
  "elapsed_ms":  int,
}
```

References
----------
- v0.21 docs: https://docs.nvidia.com/nemo/guardrails/0.21.0/
- Parallel mode: https://docs.nvidia.com/nemo/guardrails/0.21.0/user-guides/configuration-guide.html#rail-execution-modes
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger("prism42.guardrails")

DEFAULT_CONFIG_DIR = os.environ.get(
    "PRISM42_GUARDRAILS_CONFIG_DIR",
    str(Path(__file__).parent / "guardrails-config"),
)
DEFAULT_TIMEOUT_MS = int(os.environ.get("PRISM42_GUARDRAILS_TIMEOUT_MS", "500"))

_rails_singleton: Any = None
_rails_init_lock = asyncio.Lock()


def should_use_guardrails() -> bool:
    """Env-flag accessor — `PRISM42_ENABLE_GUARDRAILS=1` to enable."""
    return os.environ.get("PRISM42_ENABLE_GUARDRAILS", "0") == "1"


async def _get_rails() -> Any:
    """Lazy-init the LLMRails singleton on first use.

    Held behind a lock so concurrent first-callers don't double-init.
    Returns None if the SDK can't be imported or config is missing.
    """
    global _rails_singleton
    if _rails_singleton is not None:
        return _rails_singleton

    async with _rails_init_lock:
        if _rails_singleton is not None:
            return _rails_singleton
        try:
            from nemoguardrails import LLMRails, RailsConfig  # noqa: PLC0415

            cfg = RailsConfig.from_path(DEFAULT_CONFIG_DIR)
            _rails_singleton = LLMRails(cfg)
        except Exception as exc:
            log.warning(
                "guardrails.init_failed",
                reason=type(exc).__name__,
                detail=str(exc)[:200],
                config_dir=DEFAULT_CONFIG_DIR,
            )
            return None
    return _rails_singleton


def _extract_severity(reason: str) -> str:
    lower = (reason or "").lower()
    if "high" in lower or "severe" in lower or "critical" in lower:
        return "high"
    if "medium" in lower or "moderate" in lower:
        return "medium"
    return "low"


async def _run_rail(
    *,
    text: str,
    role: str,
    rail: str,
    session_id: str | None,
    turn_idx: int | None,
) -> dict[str, Any] | None:
    if not should_use_guardrails():
        return None

    rails = await _get_rails()
    if rails is None:
        return None

    start = time.monotonic()
    try:
        coro = rails.generate_async(messages=[{"role": role, "content": text}])
        response = await asyncio.wait_for(coro, timeout=DEFAULT_TIMEOUT_MS / 1000.0)
    except asyncio.TimeoutError:
        log.debug(
            "guardrails.timeout",
            rail=rail,
            session_id=session_id,
            turn_idx=turn_idx,
            timeout_ms=DEFAULT_TIMEOUT_MS,
        )
        return None
    except Exception as exc:
        log.debug(
            "guardrails.skip",
            rail=rail,
            reason=type(exc).__name__,
            detail=str(exc)[:200],
            session_id=session_id,
            turn_idx=turn_idx,
        )
        return None

    elapsed_ms = int((time.monotonic() - start) * 1000)
    reply_text = response.get("content", "") if isinstance(response, dict) else str(response)
    lower_reply = reply_text.lower()
    refused = (
        "i can't" in lower_reply
        or "i cannot" in lower_reply
        or "not allowed" in lower_reply
        or "off-topic" in lower_reply
        or "off topic" in lower_reply
        or "unsafe" in lower_reply
    )

    result: dict[str, Any] = {
        "allowed": not refused,
        "reason": reply_text[:280],
        "severity": _extract_severity(reply_text),
        "rail": rail,
        "elapsed_ms": elapsed_ms,
    }
    log.info(
        "guardrails.check",
        rail=rail,
        allowed=result["allowed"],
        severity=result["severity"],
        elapsed_ms=elapsed_ms,
        session_id=session_id,
        turn_idx=turn_idx,
        reason=result["reason"],
    )
    return result


async def check_input(
    caller_utterance: str,
    *,
    session_id: str | None = None,
    turn_idx: int | None = None,
) -> dict[str, Any] | None:
    """Input-rail check. Returns None when disabled or on backend failure."""
    return await _run_rail(
        text=caller_utterance,
        role="user",
        rail="input",
        session_id=session_id,
        turn_idx=turn_idx,
    )


async def check_output(
    dispatcher_reply: str,
    *,
    session_id: str | None = None,
    turn_idx: int | None = None,
) -> dict[str, Any] | None:
    """Output-rail check. Returns None when disabled or on backend failure."""
    return await _run_rail(
        text=dispatcher_reply,
        role="assistant",
        rail="output",
        session_id=session_id,
        turn_idx=turn_idx,
    )
