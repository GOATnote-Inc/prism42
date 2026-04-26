"""DispatchPublisher — additive-only LiveKit data-track publisher (cycle-2R Team A).

Emits structured per-turn JSON events to the LiveKit room data channel under
topic `prism42.dispatch` so a PSAP-CAD-style frontend can render dispatcher
state turn-by-turn (FSM state, intent, transcript, latched facts, latency).

Design constraints (cycle-2R brief)
-----------------------------------
- ADDITIVE-ONLY. Reads existing FSM + timing state; never mutates voice path.
- Default OFF behind PRISM42_ENABLE_DISPATCH_PUBLISHER. When OFF every method
  is a no-op so import + construction are safe in production until enabled.
- Failures NEVER block the voice loop. All publishes go through an asyncio
  Queue + worker task; the queue drops oldest on overflow, never blocks.
- Lazy-imports `livekit.rtc` so the orchestrator path's import-graph doesn't
  change when the flag is OFF.
- Mirrors the existing `_publish_latency_dict` pattern in worker.py:1419 —
  `await room.local_participant.publish_data(payload=..., reliable=True,
  topic="prism42.dispatch")`. NOT the older `kind=DataPacket_Kind.RELIABLE`
  form (livekit-agents 1.5.6 surface).

Topic
-----
`prism42.dispatch` — frontend filter:
  room.on('dataReceived', (payload, participant, kind, topic) => {
    if (topic !== 'prism42.dispatch') return;
    const ev = JSON.parse(new TextDecoder().decode(payload));
    if (ev.type === 'turn') ...;
    if (ev.type === 'reply') ...;
  });
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import structlog

log = structlog.get_logger()

TOPIC = "prism42.dispatch"
_ENV_FLAG = "PRISM42_ENABLE_DISPATCH_PUBLISHER"
_QUEUE_MAX = 64  # turns-worth; drop-oldest on overflow.


def is_enabled() -> bool:
    """Single source of truth for the env-flag gate."""
    return os.environ.get(_ENV_FLAG, "0") == "1"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fsm_snapshot(fsm: Any) -> dict[str, Any]:
    """Read a JSON-safe snapshot of DispatcherFSM. Tolerates None/missing fields."""
    if fsm is None:
        return {}
    try:
        state = getattr(fsm, "state", None)
        intent = getattr(fsm, "last_intent", None)
        verify = getattr(fsm, "verify_step", None)
        return {
            "state": getattr(state, "value", str(state) if state else None),
            "intent": getattr(intent, "value", str(intent) if intent else None),
            "verify_step": getattr(verify, "value", str(verify) if verify else None),
            "pronouns": getattr(fsm, "pronouns", "unknown"),
            "reassurance_done": bool(getattr(fsm, "reassurance_done", False)),
            "is_cardiac_arrest": bool(getattr(fsm, "is_cardiac_arrest", False)),
            "address_known": bool(getattr(fsm, "address_known", False)),
            "emergency_known": bool(getattr(fsm, "emergency_known", False)),
            "complaint": getattr(fsm, "complaint", "unknown"),
            "turns": int(getattr(fsm, "turns", 0)),
        }
    except Exception as e:  # noqa: BLE001
        log.warning("dispatch_publisher.snapshot_failed", err=str(e)[:200])
        return {}


def _latched_facts(fsm: Any) -> list[str]:
    """Project FSM latches into a flat string list for UI rendering."""
    if fsm is None:
        return []
    out: list[str] = []
    if getattr(fsm, "address_known", False):
        out.append("address_known")
    if getattr(fsm, "emergency_known", False):
        out.append("emergency_known")
    if getattr(fsm, "reassurance_done", False):
        out.append("reassurance_delivered")
    if getattr(fsm, "is_cardiac_arrest", False):
        out.append("cardiac_arrest")
    if getattr(fsm, "surface_confirmed", False):
        out.append("cpr_surface_confirmed")
    if getattr(fsm, "breathing_assessed", False):
        out.append("cpr_breathing_assessed")
    if getattr(fsm, "is_third_party", False):
        out.append("third_party_caller")
    return out


def _recent_replies(fsm: Any) -> list[str]:
    if fsm is None:
        return []
    buf = getattr(fsm, "recent_replies", None)
    if buf is None:
        return []
    try:
        return [str(x) for x in list(buf)]
    except Exception:  # noqa: BLE001
        return []


class DispatchPublisher:
    """Per-room publisher of structured dispatcher events.

    Construction is cheap and side-effect-free; the worker task is started
    lazily on first publish so OFF-mode pays nothing.
    """

    def __init__(self, room: Any, session_id: str) -> None:
        self._room = room
        self._session_id = session_id
        self._enabled = is_enabled()
        self._queue: asyncio.Queue[bytes] | None = None
        self._task: asyncio.Task[None] | None = None
        self._turn_index = 0
        # cycle-2T2 — log init at INFO so a single grep on the worker log
        # confirms whether DispatchPublisher was ever attached to a room.
        log.info(
            "dispatch_publisher.init",
            session_id=session_id,
            enabled=self._enabled,
            topic=TOPIC,
        )

    # ---- public API --------------------------------------------------

    def publish_turn(
        self,
        *,
        caller_utterance: str,
        fsm: Any,
        latency_ms: dict[str, int] | None = None,
    ) -> None:
        """Fire a `turn` event after on_user_turn_completed has updated the FSM."""
        if not self._enabled:
            return
        self._turn_index += 1
        evt = {
            "type": "turn",
            "session_id": self._session_id,
            "turn_index": self._turn_index,
            "timestamp_ms": _now_ms(),
            "caller_utterance": caller_utterance or "",
            "fsm": _fsm_snapshot(fsm),
            "latched_facts": _latched_facts(fsm),
            "recent_replies": _recent_replies(fsm),
            "latency_ms": dict(latency_ms or {}),
        }
        self._enqueue(evt)

    def publish_reply(
        self,
        *,
        text: str,
        tts_ttfb_ms: int = 0,
        tts_total_ms: int = 0,
    ) -> None:
        """Fire a `reply` event after the dispatcher utterance is finalized."""
        if not self._enabled:
            return
        evt = {
            "type": "reply",
            "session_id": self._session_id,
            "turn_index": self._turn_index,  # pairs with most recent turn
            "timestamp_ms": _now_ms(),
            "text": text or "",
            "tts_ttfb_ms": int(tts_ttfb_ms or 0),
            "tts_total_ms": int(tts_total_ms or 0),
        }
        self._enqueue(evt)

    def publish_caller_partial(
        self,
        *,
        text: str,
        is_final: bool,
    ) -> None:
        """Fire a `caller_partial` event for streaming caller-side STT.
        Lives within the current turn — does NOT increment turn_index."""
        if not self._enabled:
            return
        evt = {
            "type": "caller_partial",
            "session_id": self._session_id,
            "turn_index": self._turn_index,
            "timestamp_ms": _now_ms(),
            "text": text or "",
            "is_final": bool(is_final),
        }
        self._enqueue(evt)

    async def aclose(self) -> None:
        """Cancel the worker task; drains best-effort."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    # ---- internals ---------------------------------------------------

    def _enqueue(self, evt: dict[str, Any]) -> None:
        try:
            payload = json.dumps(evt, default=str).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("dispatch_publisher.encode_failed", err=str(e)[:200])
            return
        q = self._ensure_queue()
        if q is None:
            return
        # Drop-oldest overflow strategy — never block the voice path.
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
        try:
            q.put_nowait(payload)
        except Exception as e:  # noqa: BLE001
            log.warning("dispatch_publisher.enqueue_failed", err=str(e)[:200])

    def _ensure_queue(self) -> asyncio.Queue[bytes] | None:
        if self._queue is not None:
            return self._queue
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop yet (called from sync code outside async ctx).
            return None
        self._queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._task = loop.create_task(self._worker())
        return self._queue

    async def _worker(self) -> None:
        assert self._queue is not None
        # cycle-2T2 — sample-log the first 3 publishes per session so a tail
        # of /tmp/prism42-logs/worker.log proves the data-channel is hot
        # without flooding (~3-5 events/turn x N turns).
        n = 0
        while True:
            try:
                payload = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                lp = getattr(self._room, "local_participant", None)
                if lp is None:
                    log.warning(
                        "dispatch_publisher.no_local_participant",
                        session_id=self._session_id,
                    )
                    continue
                await lp.publish_data(payload=payload, reliable=True, topic=TOPIC)
                n += 1
                if n <= 3:
                    log.info(
                        "dispatch_publisher.published",
                        session_id=self._session_id,
                        topic=TOPIC,
                        bytes=len(payload),
                        seq=n,
                    )
            except Exception as e:  # noqa: BLE001
                # Failures here MUST NOT propagate — voice path is upstream.
                log.warning(
                    "dispatch_publisher.publish_failed",
                    err=str(e)[:200],
                    session_id=self._session_id,
                )
