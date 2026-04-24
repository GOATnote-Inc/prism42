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
import random
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


# ---------------------------------------------------------------------
# Bridge / filler utterances — played while the real LLM+TTS reply is
# still synthesizing. Fish TTS has a ~5-7 s first-token latency; without
# a filler the caller hears 7-9 s of dead air after finishing their
# utterance, which feels "erratic" for a 911 call. Real dispatchers fill
# that window with short acknowledgements ("Okay, stay with me.") while
# they type into the CAD. The filler plays ~300 ms after the caller
# stops speaking, is fully interruptible, and the real reply preempts
# it the moment Fish returns the first audio frame.
# ---------------------------------------------------------------------

FILLERS: tuple[str, ...] = (
    "Okay, stay with me.",
    "Got it, one moment.",
    "I hear you.",
    "Alright, hold on.",
    "Okay.",
)

# Delay before the filler fires — gives a beat of silence after the
# caller finishes so we don't clip the tail of their utterance, and
# lets very-fast replies (unlikely with Fish but possible) preempt
# without ever speaking a filler.
FILLER_DELAY_S: float = 0.3


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
    #
    # LLM = claude-sonnet-4-6 for the FAST single-LLM path (2026-04-24).
    # The archived orchestrator_full.py used Opus 4.7 + 4 parallel tools +
    # a STEP 2 Opus call → 14-20s reply latency, fatal for voice demo.
    # Sonnet 4.6 streaming TTFT ~500ms puts first audio in the caller's
    # ears in ~2-3s. See docs/livekit-kb/08-opus-47-refusal-patterns.md §7.
    from livekit.plugins.anthropic import LLM as AnthropicLLM  # noqa: PLC0415

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=ParakeetSTT(ParakeetOptions()),
        llm=AnthropicLLM(model="claude-sonnet-4-6"),
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

    # Pre-roll gate: the caller may start talking BEFORE we get a chance
    # to speak the "Nine one one. What's your emergency?" greeting (their
    # phone rang, they heard the connect tone, they launched into the
    # incident). If we play the greeting on top of that we talk over the
    # caller — a real PSAP violation, and the exact bug reported:
    #   "i started talking right away then was met with
    #    911 whats your emergency"
    #
    # We subscribe to two AgentSession events before session.start() so
    # handlers are in place as soon as the first audio frame arrives:
    #
    #   - "user_state_changed" → new_state == "speaking": fastest signal,
    #     fires on raw VAD start-of-speech (see livekit/agents/voice/
    #     agent_activity.py:1650-1654 → _session._update_user_state(
    #     "speaking") → voice/agent_session.py:1557-1563 emits the event).
    #
    #   - "user_input_transcribed": backup signal, fires on every STT
    #     chunk (interim + final) — see voice/agent_session.py:1574-1579
    #     (`self.emit("user_input_transcribed", ev)`). Covers the rare
    #     case where VAD is configured off but STT is still streaming.
    #
    # If either fires during the 500 ms grace window, we skip the preroll
    # and let the caller drive the turn; the orchestrator will reply via
    # its normal LLM path.
    caller_spoke = asyncio.Event()

    @session.on("user_state_changed")  # type: ignore[arg-type]
    def _on_user_state(ev: Any) -> None:
        # ev.new_state is one of: "speaking" | "listening" | "away".
        try:
            if getattr(ev, "new_state", None) == "speaking":
                caller_spoke.set()
        except Exception:  # noqa: BLE001
            pass

    @session.on("user_input_transcribed")  # type: ignore[arg-type]
    def _on_user_transcribed(_ev: Any) -> None:
        caller_spoke.set()

    await session.start(agent=orchestrator, room=ctx.room)

    # Pre-roll utterance: PSAP dispatchers answer first. Saying this BEFORE
    # waiting on the orchestrator's first LLM round-trip gives the caller
    # immediate audible confirmation that the line is live, and buys ~5-10s
    # of pipeline time during which the (slower) orchestrator+specialist
    # hop can complete without the caller hanging up in silence.
    #
    # HOWEVER: if the caller has ALREADY started speaking by the time we
    # get here, we MUST NOT play the greeting on top of their utterance.
    # Give a 500 ms grace window — if they haven't spoken, we lead with
    # the greeting; otherwise we stay silent and let the orchestrator
    # respond to what they actually said.
    try:
        await ctx.wait_for_participant()
    except Exception as e:  # noqa: BLE001
        log.warning("wait_for_participant.failed", err=str(e)[:200])

    try:
        await asyncio.wait_for(caller_spoke.wait(), timeout=0.5)
        log.info("preroll.skipped_caller_spoke_first", session_id=session_id)
    except asyncio.TimeoutError:
        try:
            await session.say(
                "Nine one one. What's your emergency?",
                allow_interruptions=True,
            )
            log.info("preroll.spoken", session_id=session_id)
        except Exception as e:  # noqa: BLE001
            log.warning("preroll.failed", err=str(e)[:200])

    # ---- Bridge / filler utterance ---------------------------------
    # Fish TTS adds ~5-7s to first-audio latency. To avoid dead air
    # after the caller finishes speaking, we play a short dispatcher
    # acknowledgement the moment we detect end-of-speech. The real
    # reply will interrupt it as soon as Fish returns audio.
    #
    # Event choice (verified against installed livekit-agents):
    #   voice/agent_activity.py:1701-1704 `on_end_of_speech` calls
    #   `self._session._update_user_state("listening", ...)`, which at
    #   voice/agent_session.py:1557-1564 emits "user_state_changed"
    #   with `old_state="speaking"` and `new_state="listening"`.
    # This fires on VAD end-of-speech (~0 ms), BEFORE STT finalizes the
    # transcript (~600 ms on Parakeet). `user_input_transcribed` is the
    # fallback (voice/agent_session.py:1574-1579) if VAD is disabled
    # but STT still streams — it fires on every transcript chunk, so
    # we gate it to `is_final` to avoid firing on interims.
    filler_state = {
        "turns_seen": 0,       # skip first turn (pre-roll covers it)
        "last_filler": None,   # avoid repeating the same line twice
        "pending_task": None,  # cancellable delayed-say handle
    }

    async def _fire_filler() -> None:
        """After a short pause, speak one filler. Fully interruptible —
        the real reply preempts as soon as Fish streams audio."""
        try:
            await asyncio.sleep(FILLER_DELAY_S)
            choices = [f for f in FILLERS if f != filler_state["last_filler"]]
            text = random.choice(choices) if choices else FILLERS[0]
            filler_state["last_filler"] = text
            await session.say(text, allow_interruptions=True)
            log.info("filler.spoken", session_id=session_id, text=text)
        except asyncio.CancelledError:
            # Reply arrived before our delay finished — the right thing.
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("filler.failed", err=str(e)[:200])

    def _schedule_filler() -> None:
        # Skip first turn: pre-roll already gave the caller audio.
        filler_state["turns_seen"] += 1
        if filler_state["turns_seen"] <= 1:
            return
        prev = filler_state["pending_task"]
        if prev is not None and not prev.done():
            prev.cancel()
        filler_state["pending_task"] = asyncio.create_task(_fire_filler())

    @session.on("user_state_changed")  # type: ignore[arg-type]
    def _on_user_state_filler(ev: Any) -> None:
        try:
            if (
                getattr(ev, "old_state", None) == "speaking"
                and getattr(ev, "new_state", None) == "listening"
            ):
                _schedule_filler()
        except Exception:  # noqa: BLE001
            pass

    # Fallback: if VAD is off / turn-detector fires without a clean
    # speaking→listening transition, use the STT final transcript.
    @session.on("user_input_transcribed")  # type: ignore[arg-type]
    def _on_user_transcribed_filler(ev: Any) -> None:
        try:
            if getattr(ev, "is_final", False) and filler_state["pending_task"] is None:
                _schedule_filler()
        except Exception:  # noqa: BLE001
            pass

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
