"""LiveKit Agents worker entry point — Prism42 voice runtime.

Run modes:
  uv run python worker.py dev       # hot-reload, console + LiveKit room
  uv run python worker.py start     # production (B300 pod, systemd unit)
  uv run python worker.py console   # text-only smoke test

Environment (required):
  LIVEKIT_URL              wss://livekit.thegoatnote.com
  LIVEKIT_API_KEY
  LIVEKIT_API_SECRET
  ANTHROPIC_API_KEY        Opus 4.7 + Sonnet 4.6 specialists
  OPENAI_API_KEY           GPT-5.5 / GPT-5.4 rubric grader

Environment (optional; defaults assume services run on this pod):
  PARAKEET_URL             default http://127.0.0.1:9100  (self-hosted STT)
  PARAKEET_MODEL           default nvidia/parakeet-tdt-0.6b-v3
  FISH_SPEECH_URL          default http://127.0.0.1:9200  (self-hosted TTS)
  FISH_SPEECH_VOICE        default "default"
  REDIS_URL                default redis://127.0.0.1:6379
  PRISM42_LOG_DIR          default /var/log/prism42
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog
from livekit.agents import (
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import silero

from livekit.agents.voice import speech_handle as _lk_speech_handle

# Override the 5-second "speech not done in time after interruption" cancel
# timer. Our orchestrator does Opus-4.7 → 4 parallel sonnet tools → Opus-4.7
# STEP 2 — total ~7-12s for the first turn. The default 5s aborts the
# response before TTS fires (the symptom the user observed: tools complete
# in the log but Fish never receives a POST). 30s gives the full hop room.
_lk_speech_handle.INTERRUPTION_TIMEOUT = 30.0

from fish_speech_tts import FishSpeechOptions, FishSpeechTTS
from grader import grade_turn_with_shim_fallback
from orchestrator import make_orchestrator
from parakeet_stt import ParakeetOptions, ParakeetSTT
from state import (
    SessionStore,
    write_session_summary,
    write_turn_log,
)

log = structlog.get_logger()


def _force_additional_properties_false(node: Any) -> None:
    """Anthropic API (2026+) rejects tool input schemas where any object
    type has additionalProperties != false. dict[str, Any] hints in
    @function_tool produce schemas that EXPLICITLY emit `true`, and for
    Optional[dict] hints Pydantic emits `type: ["object", "null"]` (a
    list) — both must match. Walk recursively and force the field to
    false on every object-like node. Safe across {anyOf, oneOf, $defs,
    properties, custom, tools, tuples, Optional}.

    Guard fix (2026-04-24 per livekit-kb/05-debugging-playbook.md): the
    previous guard `node.get("type") == "object"` missed nullable dicts
    because Pydantic emits the type as a list there.
    """
    if isinstance(node, dict):
        t = node.get("type")
        is_object = t == "object" or (isinstance(t, list) and "object" in t)
        if is_object and node.get("additionalProperties") is not False:
            node["additionalProperties"] = False
        for v in node.values():
            _force_additional_properties_false(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _force_additional_properties_false(v)


def _patch_anthropic_tool_schemas() -> None:
    """Monkey-patch the AnthropicLLM serialization so every tool schema
    we send has additionalProperties: false. Idempotent.

    The livekit-plugins-anthropic plugin sends tools in the 2026+ wrapped
    format `{"type":"custom","custom":{"name":..., "input_schema":{...}}}`.
    Anthropic's API rejects any `type:object` schema whose
    `additionalProperties` is true (or omitted). dict[str,Any] type hints
    in @function_tool produce exactly that. We walk the ENTIRE call
    kwargs recursively and force-false on every object node.
    """
    from anthropic.resources.messages import AsyncMessages  # noqa: PLC0415

    if getattr(AsyncMessages, "_prism42_patched", False):
        return
    original_create = AsyncMessages.create

    async def patched_create(self, *args, **kwargs):
        _force_additional_properties_false(kwargs)
        _force_additional_properties_false(list(args))
        return await original_create(self, *args, **kwargs)

    AsyncMessages.create = patched_create
    AsyncMessages._prism42_patched = True
    log.info("anthropic.tool_schema_patched")


_patch_anthropic_tool_schemas()


# ---------------------------------------------------------------------
# Singletons. The session store is shared across all rooms this worker
# handles; Anthropic/OpenAI clients are created on-demand inside the
# specialists/grader.
# ---------------------------------------------------------------------


_SESSION_STORE: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Lazy singleton — specialists.py imports this at call time."""
    global _SESSION_STORE
    if _SESSION_STORE is None:
        _SESSION_STORE = SessionStore()
    return _SESSION_STORE


# ---------------------------------------------------------------------
# Entry — runs once per LiveKit room (i.e. per call).
# ---------------------------------------------------------------------


async def entrypoint(ctx: JobContext) -> None:
    """LiveKit invokes this when a caller joins a room.

    The room name carries the prism42 session_id (the same id the
    Next.js frontend mints from /prism42/api/session/start). This
    keeps the dispatcher UI subscribed to the right stream.
    """
    session_id = ctx.room.name  # convention: room name == session_id
    log.info("entrypoint.start", session_id=session_id, room=ctx.room.name)

    store = get_session_store()
    store.open(session_id)

    # AgentSession composition — STT + LLM + TTS + VAD + turn detection.
    # The LLM is set per-Agent (orchestrator), so AgentSession's `llm`
    # is the default fallback. We keep it Anthropic Opus 4.7 for any
    # turn where the orchestrator decides to speak directly (rare —
    # we want it always going through specialists).
    from livekit.plugins.anthropic import LLM as AnthropicLLM  # noqa: PLC0415

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=ParakeetSTT(ParakeetOptions()),
        llm=AnthropicLLM(model="claude-opus-4-7"),
        tts=FishSpeechTTS(FishSpeechOptions()),
    )

    orchestrator = make_orchestrator(session_id)

    # ---- post-turn hook: rubric grade + observability writes -------
    @session.on("agent_state_changed")  # type: ignore[arg-type]
    def _on_state(_state: Any) -> None:
        # Hook for live UI bridge in a follow-on PR.
        pass

    # When the LLM finishes a response (the orchestrator chose a
    # specialist, the specialist returned spoken_content, TTS spoke
    # it), record the turn-log line. The store is already updated by
    # the specialist tool; this is the observability sidecar.
    @session.on("conversation_item_added")  # type: ignore[arg-type]
    def _on_item(item: Any) -> None:
        try:
            state = store.get(session_id)
            if not state or not state.turns:
                return
            latest = state.turns[-1]
            line = {
                "ts_ms": int(time.time() * 1000),
                "session_id": session_id,
                "turn_id": latest.turn_id,
                "phase": state.phase,
                "specialist": latest.agent,
                "self_verify_passed": latest.self_verify.all_passed,
                "contract_satisfied": latest.contract_satisfied,
                "alerts": [a.model_dump() for a in latest.alerts],
            }
            write_turn_log(line)
            # Fire-and-forget rubric grade for speak turns only.
            if latest.action == "speak" and latest.content:
                asyncio.create_task(_grade_async(session_id, latest, item))
        except Exception as e:  # noqa: BLE001
            log.warning("on_item.error", err=str(e)[:200])

    await session.start(agent=orchestrator, room=ctx.room)

    # Pre-roll utterance: PSAP dispatchers answer first. Saying this BEFORE
    # waiting on the orchestrator's first LLM round-trip gives the caller
    # immediate audible confirmation that the line is live, and buys ~5-10s
    # of pipeline time during which the (slower) orchestrator+specialist
    # hop can complete without the caller hanging up in silence.
    try:
        await ctx.wait_for_participant()
    except Exception as e:  # noqa: BLE001
        log.warning("wait_for_participant.failed", err=str(e)[:200])
    try:
        await session.say(
            "Nine one one. What's your emergency?",
            allow_interruptions=True,
        )
        log.info("preroll.spoken", session_id=session_id)
    except Exception as e:  # noqa: BLE001
        log.warning("preroll.failed", err=str(e)[:200])

    # When the room closes, fire the auditor + write the session
    # summary. Phase 3a writes the summary directly; the auditor
    # invocation lands in a follow-on PR.
    state = store.get(session_id)
    if state:
        write_session_summary(
            {
                "session_id": session_id,
                "duration_s": (state.last_touched_ms - state.started_at_ms) // 1000,
                "phases_visited": list({t.debug.get("phase") for t in state.turns if t.debug.get("phase")}),
                "turns": len(state.turns),
                "weighted_score_mean": (
                    sum(g.weighted_score for g in state.grades) / len(state.grades)
                    if state.grades
                    else None
                ),
                "alerts_by_severity": _count_by_severity(state.alerts),
            }
        )
    log.info("entrypoint.end", session_id=session_id)


async def _grade_async(session_id: str, turn: Any, _item: Any) -> None:
    """Fire-and-forget rubric grade. Never blocks the voice loop."""
    try:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        anthropic_client = AsyncAnthropic()
        store = get_session_store()
        # Pull the most recent caller text from the session — best-effort.
        state = store.require(session_id)
        caller_text = ""
        for t in reversed(state.turns):
            if t.debug.get("caller_text"):
                caller_text = t.debug["caller_text"]
                break
        grade = await grade_turn_with_shim_fallback(
            turn=turn,
            caller_text=caller_text,
            phase=state.phase,
            anthropic_client=anthropic_client,
        )
        store.record_grade(session_id, grade)
    except Exception as e:  # noqa: BLE001
        log.warning("grade.failed", err=str(e)[:200])


def _count_by_severity(alerts: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {"info": 0, "medium": 0, "high": 0, "critical": 0}
    for a in alerts:
        sev = getattr(a, "severity", None)
        if sev in out:
            out[sev] += 1
    return out


# ---------------------------------------------------------------------
# CLI — `uv run python worker.py [dev|start|console]`
# ---------------------------------------------------------------------


if __name__ == "__main__":
    # Fail-fast on missing critical env vars; B300 systemd unit will
    # crashloop with clear errors if the .env is incomplete.
    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing required env vars: {missing}")

    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
