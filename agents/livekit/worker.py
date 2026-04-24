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
import json
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


# ---------------------------------------------------------------------
# Tool-schema compliance (Anthropic Messages API, 2026+)
#
# The Messages API rejects tool input_schema objects whose `type:object`
# nodes emit `additionalProperties` as anything other than `false`.
# Pydantic's default for generic containers like `dict[str, Any]` is
# `additionalProperties: true`, and livekit-agents' strict-mode schema
# pass (`_strict.to_strict_json_schema`) only fills in `false` when the
# field is absent — it will NOT override an explicit `true`.
#
# Previous workaround (deleted 2026-04-24): a runtime monkey-patch on
# `anthropic.resources.messages.AsyncMessages.create` that walked tool-
# call kwargs and force-set `additionalProperties:false` on every
# object-typed node. See git history + docs/livekit-kb/05-debugging-
# playbook.md for the original symptom + diagnosis.
#
# Current fix: specialists.py types every @function_tool parameter as a
# Pydantic BaseModel subclass with `ConfigDict(extra="forbid")`. That
# emits `additionalProperties:false` natively on each object node so
# the strict-mode pass only needs to fill in the outer wrapper. No
# runtime mutation required.
#
# If a future tool reintroduces a `dict[str, Any]` (or any open-schema)
# hint, the Messages API will 400 on the first call. The correct fix
# is a typed BaseModel in specialists.py — NOT a new monkey-patch.
# ---------------------------------------------------------------------


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
# Per-session pipeline timings for the b3-latency data channel.
#
# Keyed by session_id → {"current": <timing_dict>, "last": <timing_dict>}.
# `current` accumulates as STT/LLM/TTS events land during an in-flight
# turn; `last` holds the most-recently-completed turn for _publish_latency
# to read when `conversation_item_added` fires.
#
# Every event-driven write goes through `_record_timing(session_id, key,
# value)` which is monotonic (max-wins for cumulative counters, first-
# write-wins for monotonic-start timestamps). This is intentionally
# duplicated across the two readers (`metrics_collected` canonical path
# and the manual `user_input_transcribed`/`speech_created` fallback path)
# so whichever fires first populates the field.
# ---------------------------------------------------------------------

_SESSION_TIMINGS: dict[str, dict[str, Any]] = {}


def _new_turn_timing() -> dict[str, Any]:
    """Blank timing dict — all durations default 0, start timestamps None."""
    return {
        "turn_id": None,
        "t_user_speech_end": None,   # monotonic, end of caller speech (VAD)
        "t_stt_end": None,           # monotonic, STT final transcript ready
        "t_llm_start": None,         # monotonic, LLM request initiated
        "t_llm_first_token": None,   # monotonic, first assistant token
        "t_tts_first_byte": None,    # monotonic, first TTS audio frame out
        "t_turn_done": None,         # monotonic, conversation_item_added
        "stt_ms": 0,
        "llm_ms": 0,
        "tts_ms": 0,
        "tool_ms": 0,
        "total_ms": 0,
        "speech_id": None,
        "metrics_seen": set(),       # track which metric types arrived
    }


def _timing_bucket(session_id: str) -> dict[str, Any]:
    """Get (or create) the per-session timing bucket."""
    b = _SESSION_TIMINGS.get(session_id)
    if b is None:
        b = {"current": _new_turn_timing(), "last": None}
        _SESSION_TIMINGS[session_id] = b
    return b


def _finalize_current_turn(session_id: str) -> dict[str, Any] | None:
    """Move the in-flight turn into `last` and start a fresh `current`.

    Computes any missing durations from the timestamps we captured so the
    frontend never sees a field at zero when we have the inputs for it.
    """
    b = _timing_bucket(session_id)
    cur = b["current"]
    # Derive durations from timestamps if not already populated by
    # metrics_collected.
    if cur.get("stt_ms", 0) == 0 and cur.get("t_user_speech_end") and cur.get("t_stt_end"):
        cur["stt_ms"] = max(0, int((cur["t_stt_end"] - cur["t_user_speech_end"]) * 1000))
    if cur.get("llm_ms", 0) == 0 and cur.get("t_llm_start") and cur.get("t_llm_first_token"):
        cur["llm_ms"] = max(0, int((cur["t_llm_first_token"] - cur["t_llm_start"]) * 1000))
    if cur.get("tts_ms", 0) == 0 and cur.get("t_llm_first_token") and cur.get("t_tts_first_byte"):
        cur["tts_ms"] = max(0, int((cur["t_tts_first_byte"] - cur["t_llm_first_token"]) * 1000))
    if cur.get("total_ms", 0) == 0 and cur.get("t_stt_end") and cur.get("t_turn_done"):
        cur["total_ms"] = max(0, int((cur["t_turn_done"] - cur["t_stt_end"]) * 1000))
    # If total is still 0 but the parts sum to something, use the sum.
    if cur.get("total_ms", 0) == 0:
        parts_sum = cur.get("stt_ms", 0) + cur.get("llm_ms", 0) + cur.get("tts_ms", 0) + cur.get("tool_ms", 0)
        if parts_sum > 0:
            cur["total_ms"] = parts_sum

    b["last"] = cur
    b["current"] = _new_turn_timing()
    return b["last"]


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

    # ---- Pipeline-latency instrumentation (b3-latency channel) -----
    #
    # livekit-agents 1.5.6 emits a single `metrics_collected` event with
    # a discriminated-union payload — one of STTMetrics, LLMMetrics,
    # TTSMetrics, EOUMetrics, PipelineEOUMetrics — after each stage of
    # the voice pipeline completes. Field names are the LiveKit public
    # contract: `ttft` for LLM, `ttfb` for TTS, `duration` for STT/TTS,
    # `end_of_utterance_delay` for EOU. We normalize to ms ints.
    #
    # We ALSO capture monotonic timestamps in `user_input_transcribed`
    # / `speech_created` / `conversation_item_added` as a belt-and-
    # braces fallback. Whichever path fires first wins; duplicates are
    # harmless because `_finalize_current_turn` only re-derives a field
    # when it is still 0.
    @session.on("metrics_collected")  # type: ignore[arg-type]
    def _on_metrics(ev: Any) -> None:
        try:
            metrics = getattr(ev, "metrics", ev)
            bucket = _timing_bucket(session_id)
            cur = bucket["current"]
            cls_name = type(metrics).__name__
            cur["metrics_seen"].add(cls_name)
            # STT metrics — streaming_duration / duration reflects
            # partial→final finalize window.
            if cls_name in ("STTMetrics", "EOUMetrics", "PipelineEOUMetrics"):
                # EOU = end-of-utterance delay (VAD endpoint → turn-detector fire).
                eou_delay = getattr(metrics, "end_of_utterance_delay", None)
                duration = getattr(metrics, "duration", None)
                if duration is not None and cur.get("stt_ms", 0) == 0:
                    cur["stt_ms"] = max(0, int(float(duration) * 1000))
                if eou_delay is not None and cur.get("stt_ms", 0) == 0:
                    cur["stt_ms"] = max(0, int(float(eou_delay) * 1000))
            elif cls_name == "LLMMetrics":
                ttft = getattr(metrics, "ttft", None)
                duration = getattr(metrics, "duration", None)
                if ttft is not None:
                    # llm_ms = TTFT (first token latency, the user-facing metric)
                    cur["llm_ms"] = max(0, int(float(ttft) * 1000))
                elif duration is not None:
                    cur["llm_ms"] = max(0, int(float(duration) * 1000))
            elif cls_name == "TTSMetrics":
                ttfb = getattr(metrics, "ttfb", None)
                if ttfb is not None:
                    cur["tts_ms"] = max(0, int(float(ttfb) * 1000))
            log.debug(
                "metrics.captured",
                session_id=session_id,
                metric_type=cls_name,
                stt_ms=cur.get("stt_ms"),
                llm_ms=cur.get("llm_ms"),
                tts_ms=cur.get("tts_ms"),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("metrics.error", err=str(e)[:200])

    # When the LLM finishes a response (the orchestrator chose a
    # specialist, the specialist returned spoken_content, TTS spoke
    # it), record the turn-log line. The store is already updated by
    # the specialist tool; this is the observability sidecar.
    @session.on("conversation_item_added")  # type: ignore[arg-type]
    def _on_item(item: Any) -> None:
        try:
            # Mark end of turn and finalize timings BEFORE publishing.
            bucket = _timing_bucket(session_id)
            bucket["current"]["t_turn_done"] = time.monotonic()
            finalized = _finalize_current_turn(session_id)

            state = store.get(session_id)
            if not state or not state.turns:
                # No specialist turn was recorded (single-LLM fast path) —
                # still publish latency so the frontend gets live numbers.
                if finalized:
                    asyncio.create_task(
                        _publish_latency_dict(ctx, session_id, finalized)
                    )
                return
            latest = state.turns[-1]
            # Populate the TurnRecord.debug dict so the legacy
            # _publish_latency path (which reads turn.debug) also works.
            if finalized:
                try:
                    latest.debug.setdefault("stt_ms", finalized.get("stt_ms", 0))
                    latest.debug.setdefault("llm_ms", finalized.get("llm_ms", 0))
                    latest.debug.setdefault("tts_ms", finalized.get("tts_ms", 0))
                    latest.debug.setdefault("tool_ms", finalized.get("tool_ms", 0))
                    latest.debug.setdefault("total_ms", finalized.get("total_ms", 0))
                except Exception:  # noqa: BLE001
                    pass
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
            # Fire-and-forget latency telemetry → /prism42/livekit V2 strip.
            asyncio.create_task(_publish_latency(ctx, session_id, latest))
        except Exception as e:  # noqa: BLE001
            log.warning("on_item.error", err=str(e)[:200])

    # First-token / first-audio timing fallbacks. `speech_created` fires
    # when AgentSession starts synthesizing a reply (i.e. LLM has emitted
    # enough for TTS to begin). We use it as the proxy for
    # `t_llm_first_token` when the LLMMetrics path has not landed yet.
    @session.on("speech_created")  # type: ignore[arg-type]
    def _on_speech_created(ev: Any) -> None:
        try:
            bucket = _timing_bucket(session_id)
            cur = bucket["current"]
            now = time.monotonic()
            if cur.get("t_llm_first_token") is None:
                cur["t_llm_first_token"] = now
            # Try to pull a stable speech_id for cross-event correlation.
            sid = getattr(ev, "speech_id", None) or getattr(
                getattr(ev, "speech_handle", None), "id", None
            )
            if sid and cur.get("speech_id") is None:
                cur["speech_id"] = sid
        except Exception as e:  # noqa: BLE001
            log.warning("speech_created.error", err=str(e)[:200])

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
            # VAD-end-of-speech is the cleanest origin for total_ms.
            if (
                getattr(ev, "old_state", None) == "speaking"
                and getattr(ev, "new_state", None) == "listening"
            ):
                bucket = _timing_bucket(session_id)
                cur = bucket["current"]
                if cur.get("t_user_speech_end") is None:
                    cur["t_user_speech_end"] = time.monotonic()
        except Exception:  # noqa: BLE001
            pass

    @session.on("user_input_transcribed")  # type: ignore[arg-type]
    def _on_user_transcribed(ev: Any) -> None:
        caller_spoke.set()
        try:
            if getattr(ev, "is_final", False):
                bucket = _timing_bucket(session_id)
                cur = bucket["current"]
                now = time.monotonic()
                if cur.get("t_stt_end") is None:
                    cur["t_stt_end"] = now
                # LLM request kicks off as soon as the transcript is final.
                if cur.get("t_llm_start") is None:
                    cur["t_llm_start"] = now
                # If we missed the VAD speaking→listening transition,
                # approximate user_speech_end by subtracting transcript_delay.
                if cur.get("t_user_speech_end") is None:
                    delay = getattr(ev, "transcript_delay", None)
                    if delay is not None:
                        try:
                            cur["t_user_speech_end"] = now - float(delay)
                        except (TypeError, ValueError):
                            cur["t_user_speech_end"] = now
                    else:
                        cur["t_user_speech_end"] = now
        except Exception:  # noqa: BLE001
            pass

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


async def _publish_latency(ctx: JobContext, session_id: str, turn: Any) -> None:
    """Publish per-turn pipeline latency over a LiveKit data channel.

    Contract (topic="b3-latency", reliable=True, JSON):
        {
          "session_id": str,
          "turn_id":    str,
          "ts_ms":      int,    # ms since epoch of turn-complete
          "stt_ms":     int,    # Parakeet partial → final finalize
          "llm_ms":     int,    # first token → last token of Sonnet 4.6
          "tts_ms":     int,    # TTS request → first audio frame (Fish)
          "tool_ms":    int,    # sum of tool hops on this turn (e.g. CAD)
          "total_ms":   int,    # caller end-of-speech → first TTS frame
          "note":       str|None
        }

    Reads timings from (priority order):
      1. `_SESSION_TIMINGS[session_id]["last"]` populated by the
         `metrics_collected` + `user_input_transcribed` +
         `speech_created` + `conversation_item_added` event chain.
      2. `turn.debug` as a legacy fallback for specialists that
         explicitly write stt_ms/llm_ms/tts_ms.

    Frontend subscribes via `useDataChannel("b3-latency")` in
    mvp/911-console-live/app/prism42/livekit/page.tsx — it treats
    `note == null` as "live" and anything else as "awaiting first turn".
    """
    try:
        debug = getattr(turn, "debug", {}) or {}
        bucket = _timing_bucket(session_id)
        last = bucket.get("last") or {}

        def _pick(field: str) -> int:
            # Prefer the event-driven timing dict; fall back to turn.debug.
            v = last.get(field, 0) or debug.get(field, 0)
            try:
                return int(v) if v is not None else 0
            except (TypeError, ValueError):
                return 0

        stt_ms = _pick("stt_ms")
        llm_ms = _pick("llm_ms")
        tts_ms = _pick("tts_ms")
        tool_ms = _pick("tool_ms")
        total_ms = _pick("total_ms")
        if total_ms == 0 and any((stt_ms, llm_ms, tts_ms, tool_ms)):
            total_ms = stt_ms + llm_ms + tts_ms + tool_ms

        note: str | None = None
        if stt_ms == llm_ms == tts_ms == tool_ms == total_ms == 0:
            note = "orchestrator_timing_not_populated"

        payload = json.dumps(
            {
                "session_id": session_id,
                "turn_id": getattr(turn, "turn_id", "") or last.get("turn_id", ""),
                "ts_ms": int(time.time() * 1000),
                "stt_ms": stt_ms,
                "llm_ms": llm_ms,
                "tts_ms": tts_ms,
                "tool_ms": tool_ms,
                "total_ms": total_ms,
                "note": note,
            }
        ).encode("utf-8")

        log.info(
            "latency.publish",
            session_id=session_id,
            stt_ms=stt_ms,
            llm_ms=llm_ms,
            tts_ms=tts_ms,
            tool_ms=tool_ms,
            total_ms=total_ms,
            note=note,
        )
        await ctx.room.local_participant.publish_data(
            payload=payload,
            reliable=True,
            topic="b3-latency",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("latency_publish.failed", err=str(e)[:200])


async def _publish_latency_dict(
    ctx: JobContext, session_id: str, timing: dict[str, Any]
) -> None:
    """Publish latency from a raw timing dict (no TurnRecord available).

    Used on the single-LLM fast path where the orchestrator doesn't
    produce a TurnRecord (no specialist tool call), so there is no
    `turn.debug` to fall back on. Takes the finalized timing dict from
    `_finalize_current_turn` and emits it verbatim.
    """
    try:
        stt_ms = int(timing.get("stt_ms", 0) or 0)
        llm_ms = int(timing.get("llm_ms", 0) or 0)
        tts_ms = int(timing.get("tts_ms", 0) or 0)
        tool_ms = int(timing.get("tool_ms", 0) or 0)
        total_ms = int(timing.get("total_ms", 0) or 0)
        if total_ms == 0 and any((stt_ms, llm_ms, tts_ms, tool_ms)):
            total_ms = stt_ms + llm_ms + tts_ms + tool_ms

        note: str | None = None
        if stt_ms == llm_ms == tts_ms == tool_ms == total_ms == 0:
            note = "orchestrator_timing_not_populated"

        payload = json.dumps(
            {
                "session_id": session_id,
                "turn_id": timing.get("turn_id", "") or "",
                "ts_ms": int(time.time() * 1000),
                "stt_ms": stt_ms,
                "llm_ms": llm_ms,
                "tts_ms": tts_ms,
                "tool_ms": tool_ms,
                "total_ms": total_ms,
                "note": note,
            }
        ).encode("utf-8")

        log.info(
            "latency.publish",
            session_id=session_id,
            stt_ms=stt_ms,
            llm_ms=llm_ms,
            tts_ms=tts_ms,
            tool_ms=tool_ms,
            total_ms=total_ms,
            note=note,
        )
        await ctx.room.local_participant.publish_data(
            payload=payload,
            reliable=True,
            topic="b3-latency",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("latency_publish_dict.failed", err=str(e)[:200])


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
