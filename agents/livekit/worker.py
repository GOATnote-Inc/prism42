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
import threading
import time
from typing import Any, AsyncIterator

import httpx
import ormsgpack
import structlog
from livekit import rtc
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
# (additive) cycle-2R Team A — dispatcher data-track publisher.
try:
    from dispatch_publisher import DispatchPublisher, is_enabled as _dp_enabled
except Exception:  # noqa: BLE001
    DispatchPublisher = None  # type: ignore[assignment]
    def _dp_enabled() -> bool:  # type: ignore[no-redef]
        return False
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

# Cycle-2f (2026-04-25) — env-flagged FILLERS variant.
#   PRISM42_ENABLE_TTS_PROSODY_TAGS=0 (default): plain fillers, byte-for-byte
#       identical to cycle-2d/2e baseline.
#   PRISM42_ENABLE_TTS_PROSODY_TAGS=1: tagged fillers — Fish S2-Pro consumes
#       the [soft] tag as voice direction (silent). Verified via brackets-
#       not-spoken audio probe in the cycle-2f bench.
# Tone constraint: NEVER tell the caller to "calm down" (Tracy & Whittaker
# S36); fillers are dispatcher-side acknowledgements, not directives at
# the caller's emotional state.
_FILLERS_PLAIN: tuple[str, ...] = (
    "I hear you.",
    "I'm right here.",
    "Tell me what's happening.",
    "I'm with you.",
)
_FILLERS_TAGGED: tuple[str, ...] = (
    "[soft] I'm here.",
    "[soft] I hear you.",
    "[soft] Tell me when you're ready.",
    "[soft] One moment.",
)
_PROSODY_TAGS_ENABLED: bool = (
    os.environ.get("PRISM42_ENABLE_TTS_PROSODY_TAGS", "0") == "1"
)
FILLERS: tuple[str, ...] = (
    _FILLERS_TAGGED if _PROSODY_TAGS_ENABLED else _FILLERS_PLAIN
)
log.info(
    "worker.cycle2f_prosody_init",
    cycle2f_prosody="enabled" if _PROSODY_TAGS_ENABLED else "disabled",
    fillers_variant="tagged" if _PROSODY_TAGS_ENABLED else "plain",
    filler_count=len(FILLERS),
)

# Delay before the filler fires — gives a beat of silence after the
# caller finishes so we don't clip the tail of their utterance, and
# lets very-fast replies (unlikely with Fish but possible) preempt
# without ever speaking a filler.
#
# Tunable via PRISM42_FILLER_DELAY_S. Perceptual-SOTA target per Team A
# overlap timing (2026-04-24): 300-500 ms from caller end-of-speech to
# first filler audio. <300 ms risks clipping the tail; >700 ms feels
# like dead air. Keep default at 0.3 to preserve baseline — the env
# flag makes A/B sweeps single-dial.
FILLER_DELAY_S: float = float(os.environ.get("PRISM42_FILLER_DELAY_S", "0.3"))

# Length-gated early-LLM telemetry hook. livekit-agents 1.5.6 already
# fires preemptive generation on PREFLIGHT_TRANSCRIPT events when the
# STT plugin advertises streaming=True + interim_results=True (see
# voice/audio_recognition.py:777-822). This env var is NOT a second
# trigger — it's a log-assertion of what the livekit pipeline is
# doing on OUR stream, so Team B's test suite can parse a single-line
# numeric ms value back out. 0 disables the hook; default 12 chars
# ≈ "I have chest pain" prefix from the canonical bench utterance.
EARLY_LLM_CHARS: int = int(os.environ.get("PRISM42_EARLY_LLM_CHARS", "12"))


# ---------------------------------------------------------------------
# Cycle-2i: NENA-STA-020.1-2020 §2.2.3 identity greeting.
#
# Restores PSAP-compliant identification: every 9-1-1 line must be
# answered with the phrase "9-1-1" before any other audio. Cycle-2a
# disabled the live preroll session.say() to drop +850 ms of TTS
# scheduling latency on the first turn. That tradeoff dropped identity
# below the standard — the user attested:
#   me: "Can you hear me?"  →  app: "What's your location?"
#
# Fix: pre-synthesize the canonical greeting ONCE per worker process,
# cache the resulting AudioFrames, and play them via session.say(
# text=..., audio=cached_iter) on session start. This bypasses the
# Fish synth round-trip on the hot path — first-byte latency is the
# WebRTC publish latency (~50-100 ms), not the 2-3 s render budget.
#
# Spelled-out form ("Nine one one") chosen over digit form ("9-1-1")
# because Fish renders digits less reliably for TTS naturalness; the
# spelled form is the verbatim NENA-recommended PSAP phrasing.
#
# Default OFF in code (PRISM42_ENABLE_911_GREETING=0) to preserve
# wire-equivalence smoke baselines. Enabled via systemd drop-in
# 50-cycle2i-greeting.conf for production use.
# ---------------------------------------------------------------------

ENABLE_911_GREETING: bool = (
    os.environ.get("PRISM42_ENABLE_911_GREETING", "0") == "1"
)
GREETING_TEXT: str = "Nine one one, what is the address of your emergency?"
GREETING_AUDIO_PATH: str = os.environ.get(
    "PRISM42_GREETING_AUDIO_PATH", "/tmp/prism42-greeting.wav"
)
# Fish S2-Pro native rate (44.1 kHz mono PCM16). LiveKit's mixer handles
# resampling to the WebRTC negotiated rate, so we frame-build at Fish's
# native rate to keep the cache exactly equal to the wire bytes.
_GREETING_SAMPLE_RATE: int = 44_100
_GREETING_CHANNELS: int = 1
# 20-ms frames (882 samples per frame at 44.1 kHz mono) are the
# AudioFrame chunk size that LiveKit's audio output expects for its
# 50-Hz frame loop. Short enough that the caller's barge-in detection
# can interrupt within ~40 ms.
_GREETING_FRAME_MS: int = 20

# Module-level cache. Populated once per worker process by
# `_warm_greeting_cache_blocking()`. Subsequent calls return the cached
# bytes instantly. The lock guards the critical section so concurrent
# first-session entries don't double-synthesize.
_GREETING_PCM_BYTES: bytes | None = None
_GREETING_AUDIO_DURATION_MS: int = 0
_GREETING_CACHE_LOCK = threading.Lock()
_GREETING_WARM_FAILED: bool = False


def _strip_wav_header(wav_bytes: bytes) -> bytes:
    """Strip the RIFF header from a Fish WAV blob to get raw PCM16.

    Fish's /v1/tts streaming=True format=wav path emits a real RIFF WAV
    (RIFF/WAVE/fmt /data chunks). For session.say(audio=...) we need
    raw 16-bit PCM samples that we can wrap in rtc.AudioFrame, so the
    header bytes must come off — otherwise LiveKit treats them as PCM
    samples and the caller hears a 0.5 ms tick of garbage at frame 0.
    """
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF":
        # Not a RIFF WAV — assume bare PCM (forward compatibility).
        return wav_bytes
    # Find the "data" chunk header. Fish puts it at byte 36 in practice
    # but the spec allows arbitrary inter-chunk metadata; scan for it.
    idx = wav_bytes.find(b"data", 12)
    if idx == -1:
        return wav_bytes
    # data subchunk: 4-byte "data" tag + 4-byte size + payload
    return wav_bytes[idx + 8 :]


def _warm_greeting_cache_blocking(fish_url: str) -> bool:
    """Synthesize the greeting via Fish HTTP, cache PCM bytes + write WAV.

    Synchronous on purpose — called inside an asyncio.to_thread() at the
    top of entrypoint() so the first entrypoint pays the warm cost
    (~2-3 s) but every subsequent session starts at <1 ms cache hit.

    Returns True on success, False on any failure (caller should fall
    back to NOT firing the greeting rather than hanging the session).
    """
    global _GREETING_PCM_BYTES, _GREETING_AUDIO_DURATION_MS, _GREETING_WARM_FAILED
    # Cycle-2P (2026-04-26): if PRISM42_GREETING_AUDIO_FILE points at an
    # existing WAV, load it from disk and skip Fish synthesis entirely.
    # This guarantees the cached greeting is the curated MW reference clip
    # (assets/MWintro.mp3 → mw_intro_greeting.wav) byte-for-byte, with
    # zero Fish render variance. Falls through to the existing Fish-synth
    # path (cycle-2N Q4-B references_payload) when the env is unset or
    # the file is missing — preserves backward compatibility.
    _greeting_file = os.environ.get("PRISM42_GREETING_AUDIO_FILE", "").strip()
    if _greeting_file:
        if os.path.exists(_greeting_file):
            try:
                with open(_greeting_file, "rb") as f:
                    wav_bytes = f.read()
                pcm_bytes = _strip_wav_header(wav_bytes)
                bytes_per_frame = (
                    _GREETING_SAMPLE_RATE * _GREETING_FRAME_MS // 1000
                ) * 2 * _GREETING_CHANNELS
                rem = len(pcm_bytes) % bytes_per_frame
                if rem:
                    pcm_bytes = pcm_bytes + b"\x00" * (bytes_per_frame - rem)
                with _GREETING_CACHE_LOCK:
                    _GREETING_PCM_BYTES = pcm_bytes
                    _GREETING_AUDIO_DURATION_MS = int(
                        len(pcm_bytes) / 2 / _GREETING_SAMPLE_RATE * 1000
                    )
                    _GREETING_WARM_FAILED = False
                # Mirror archive write so /tmp/prism42-greeting.wav reflects
                # the active cache source (downstream tools probe this path).
                try:
                    with open(GREETING_AUDIO_PATH, "wb") as f:
                        f.write(wav_bytes)
                except OSError as e:
                    log.warning(
                        "greeting.911.archive_write_failed",
                        path=GREETING_AUDIO_PATH,
                        err=str(e)[:200],
                    )
                log.info(
                    "greeting.911.cache_loaded_from_file",
                    source_path=_greeting_file,
                    text=GREETING_TEXT,
                    wav_bytes=len(wav_bytes),
                    pcm_bytes=len(pcm_bytes),
                    duration_ms=_GREETING_AUDIO_DURATION_MS,
                    archive_path=GREETING_AUDIO_PATH,
                    sample_rate=_GREETING_SAMPLE_RATE,
                )
                return True
            except OSError as e:
                log.warning(
                    "greeting.911.cache_file_load_failed",
                    path=_greeting_file,
                    error=str(e)[:200],
                )
                # fall through to Fish synth path
        else:
            log.warning(
                "greeting.911.cache_file_missing",
                path=_greeting_file,
            )
            # fall through to Fish synth path
    # Cycle-2N Q4-B fix (2026-04-26): the greeting was bypassing the
    # FishSpeechTTS adapter's references_payload logic and rendering in
    # Fish's untrained stock voice. Mirror the cycle-2j adapter pattern
    # here so the greeting uses the MW reference voice when env is set.
    # Engine semantics (vendor/.../inference_engine/__init__.py:48-57):
    # when reference_id is non-None, `references` is silently dropped.
    _ref_path = os.environ.get("PRISM42_FISH_REFERENCE_AUDIO", "").strip() or None
    _ref_text = os.environ.get("PRISM42_FISH_REFERENCE_TEXT", "").strip() or None
    _ref_id = os.environ.get("FISH_SPEECH_REFERENCE_ID", "").strip() or None
    references_payload: list[dict] = []
    if not _ref_id and _ref_path and _ref_text:
        try:
            with open(_ref_path, "rb") as f:
                _audio_bytes = f.read()
            references_payload = [{"audio": _audio_bytes, "text": _ref_text}]
            log.info(
                "greeting.911.reference_voice_loaded",
                path=_ref_path,
                bytes=len(_audio_bytes),
                text_chars=len(_ref_text),
            )
        except OSError as e:
            log.warning(
                "greeting.911.reference_voice_load_failed",
                path=_ref_path,
                error=str(e)[:200],
            )
            references_payload = []
    body = {
        "text": GREETING_TEXT,
        "format": "wav",
        "chunk_length": 200,
        "normalize": True,
        # streaming=True is the only path Fish accepts for our msgpack
        # body (streaming=False returns 500 for this build); the data
        # comes back as a real RIFF WAV with header.
        "streaming": True,
        "max_new_tokens": 1024,
        "top_p": 0.7,
        "repetition_penalty": 1.1,
        "temperature": 0.1,
        "use_memory_cache": "on",
        "seed": 911,
        "references": references_payload,
    }
    if _ref_id:
        body["reference_id"] = _ref_id
    try:
        with httpx.Client(timeout=30.0) as client:
            with client.stream(
                "POST",
                f"{fish_url}/v1/tts",
                content=ormsgpack.packb(body),
                headers={"Content-Type": "application/msgpack"},
            ) as resp:
                resp.raise_for_status()
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    if chunk:
                        buf.extend(chunk)
        wav_bytes = bytes(buf)
        pcm_bytes = _strip_wav_header(wav_bytes)
        # Pad to a whole frame so the last AudioFrame is full.
        bytes_per_frame = (
            _GREETING_SAMPLE_RATE * _GREETING_FRAME_MS // 1000
        ) * 2 * _GREETING_CHANNELS
        rem = len(pcm_bytes) % bytes_per_frame
        if rem:
            pcm_bytes = pcm_bytes + b"\x00" * (bytes_per_frame - rem)
        with _GREETING_CACHE_LOCK:
            _GREETING_PCM_BYTES = pcm_bytes
            _GREETING_AUDIO_DURATION_MS = int(
                len(pcm_bytes) / 2 / _GREETING_SAMPLE_RATE * 1000
            )
            _GREETING_WARM_FAILED = False
        # Archival WAV file (use the original RIFF blob so we keep
        # the standard header for analysts who download it).
        try:
            with open(GREETING_AUDIO_PATH, "wb") as f:
                f.write(wav_bytes)
        except OSError as e:
            log.warning(
                "greeting.911.archive_write_failed",
                path=GREETING_AUDIO_PATH,
                err=str(e)[:200],
            )
        log.info(
            "greeting.911.cache_warmed",
            text=GREETING_TEXT,
            wav_bytes=len(wav_bytes),
            pcm_bytes=len(pcm_bytes),
            duration_ms=_GREETING_AUDIO_DURATION_MS,
            archive_path=GREETING_AUDIO_PATH,
            sample_rate=_GREETING_SAMPLE_RATE,
        )
        return True
    except Exception as e:  # noqa: BLE001
        with _GREETING_CACHE_LOCK:
            _GREETING_WARM_FAILED = True
        log.warning(
            "greeting.911.cache_warm_failed",
            err=str(e)[:200],
            fish_url=fish_url,
        )
        return False


async def _ensure_greeting_cache(fish_url: str) -> bool:
    """Idempotent warm — first caller pays the synth cost, rest cache-hit.

    Runs the blocking synth in a worker thread so the asyncio loop
    keeps serving heartbeats / WebRTC frames while Fish renders.
    """
    if _GREETING_PCM_BYTES is not None:
        return True
    return await asyncio.to_thread(_warm_greeting_cache_blocking, fish_url)


def _greeting_audio_iter() -> AsyncIterator[rtc.AudioFrame]:
    """Yield cached AudioFrames for session.say(audio=...).

    Each call returns a fresh async iterator that walks the cached
    PCM bytes once. session.say expects an AsyncIterable[AudioFrame],
    not a list — the iterator pattern lets LiveKit pace frame delivery
    (e.g. interruption mid-greeting just stops pulling).
    """
    pcm = _GREETING_PCM_BYTES
    if pcm is None:
        async def _empty() -> AsyncIterator[rtc.AudioFrame]:
            if False:
                yield  # pragma: no cover - never runs
        return _empty()

    samples_per_frame = _GREETING_SAMPLE_RATE * _GREETING_FRAME_MS // 1000
    bytes_per_frame = samples_per_frame * 2 * _GREETING_CHANNELS

    async def _iter() -> AsyncIterator[rtc.AudioFrame]:
        for offset in range(0, len(pcm), bytes_per_frame):
            chunk = pcm[offset : offset + bytes_per_frame]
            if len(chunk) < bytes_per_frame:
                # Pad final frame so AudioFrame's data-length check passes.
                chunk = chunk + b"\x00" * (bytes_per_frame - len(chunk))
            yield rtc.AudioFrame(
                data=chunk,
                sample_rate=_GREETING_SAMPLE_RATE,
                num_channels=_GREETING_CHANNELS,
                samples_per_channel=samples_per_frame,
            )

    return _iter()


# ---------------------------------------------------------------------
# Transcript bus — POST each finalized turn (caller + dispatcher) to
# the Vercel SSE endpoint so the /prism42/livekit dispatcher UI renders
# the live transcript that the ElevenLabs path already shows. Without
# this, the LiveKit voice path's transcript panel stays at "0 turns ·
# state no-transcript" even with audio flowing.
#
# Endpoint: POST {PRISM42_BASE_URL}/prism42/api/session/{id}/turn
# Body: {"role": "user"|"assistant", "content": "...", "ts_ms": ...}
# Header: x-prism42-worker-key (only required when the env is set on
#         the Vercel side; absent = open for demo/private use).
# ---------------------------------------------------------------------

PRISM42_BASE_URL = os.environ.get(
    "PRISM42_BASE_URL", "https://prism42-console.vercel.app"
)
PRISM42_WORKER_KEY = os.environ.get("PRISM42_WORKER_KEY", "")

_TRANSCRIPT_CLIENT: httpx.AsyncClient | None = None


def _transcript_client() -> httpx.AsyncClient:
    global _TRANSCRIPT_CLIENT
    if _TRANSCRIPT_CLIENT is None:
        _TRANSCRIPT_CLIENT = httpx.AsyncClient(timeout=5.0)
    return _TRANSCRIPT_CLIENT


async def _post_turn_to_bus(session_id: str, role: str, content: str) -> None:
    """Fire-and-forget transcript POST.

    Failures log a warning but never raise — the voice pipeline must
    not block on a frontend SSE bus that may be cold-starting on
    Vercel. Worst case the dispatcher UI just doesn't see the turn;
    audio still plays.
    """
    if not content or not session_id:
        return
    url = f"{PRISM42_BASE_URL}/prism42/api/session/{session_id}/turn"
    headers = {"Content-Type": "application/json"}
    if PRISM42_WORKER_KEY:
        headers["x-prism42-worker-key"] = PRISM42_WORKER_KEY
    body = {"role": role, "content": content, "ts_ms": int(time.time() * 1000)}
    try:
        client = _transcript_client()
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code != 200:
            log.warning(
                "transcript.post_non_200",
                status=resp.status_code,
                session_id=session_id,
                role=role,
                body=resp.text[:200] if resp.text else None,
            )
        else:
            log.debug(
                "transcript.post_ok",
                session_id=session_id,
                role=role,
                len=len(content),
            )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "transcript.post_error", err=str(e)[:200], session_id=session_id, role=role
        )


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
        # Overlap-timing instrumentation (Team A, 2026-04-24).
        "t_first_filler_audio": None,   # monotonic, first filler TTS frame
        "t_first_tts_audio": None,      # monotonic, first reply TTS frame
        "preempt_gen_fired": False,     # livekit preemptive gen triggered
        "early_llm_logged": False,      # dedup guard for the telemetry event
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

    # Cycle-2i: kick off the 911 greeting cache warm in the background
    # the moment we get a session. First entrypoint pays the ~2-3 s synth
    # cost on a worker thread; every subsequent session hits the module-
    # level cache for free. Spawning here (not at module import) keeps
    # logging set up and the Fish health-check decisional — if Fish is
    # down at startup we log the failure and the hot-path cache_miss
    # fallback handles it gracefully.
    if ENABLE_911_GREETING and _GREETING_PCM_BYTES is None and not _GREETING_WARM_FAILED:
        _fish_url = os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:9200")
        asyncio.create_task(
            _ensure_greeting_cache(_fish_url),
            name="greeting-911-warm",
        )

    # AgentSession composition — STT + LLM + TTS + VAD + turn detection.
    #
    # LLM backend selector — Phase B of the B300 purr migration plan
    # (docs/livekit-kb/25-b300-purr-migration-plan.md). Default
    # LLM_BACKEND=anthropic preserves the current Sonnet 4.6 cloud path.
    # LLM_BACKEND=vllm-local routes to a local vLLM 0.20 server (default
    # http://127.0.0.1:8001/v1, configurable via VLLM_BASE_URL) hosting
    # Nemotron Nano 3 MoE NVFP4 on B300 — 15-30 ms TTFT vs Sonnet 4.6's
    # 500 ms cloud round-trip. Each branch lazy-imports its plugin so a
    # missing dep only breaks the backend that needs it, not the other.
    _llm_backend = os.environ.get("LLM_BACKEND", "anthropic").lower()
    if _llm_backend == "vllm-local":
        from livekit.plugins.openai import LLM as OpenAILLM  # noqa: PLC0415

        # _strict_tool_schema=False is REQUIRED — the openai plugin's
        # default True injects "strict": true + additionalProperties:false
        # into every tool schema, which vLLM's qwen3_coder tool-call
        # parser does not handle correctly. KB 24 §3 documents the
        # symptom (silent mishandling of tool turns).
        # Cycle-1 Fix 1 (2026-04-25): disable Nemotron nano_v3 reasoning-parser
        # think-region generation. T5 forensic + synthesis.md showed that
        # 10/10 turns produced empty `delta.content` because the model routed
        # initial tokens to `delta.reasoning_content` and exhausted the budget
        # inside <think> without emitting reply text. The model card for
        # NVIDIA-Nemotron-3-Nano honors `chat_template_kwargs.enable_thinking`
        # to skip the think-region entirely. Forwarded to vLLM via the
        # OpenAI-plugin's typed `extra_body` kwarg (verified against
        # livekit-plugins-openai 1.5.6 signature).
        _llm: Any = OpenAILLM(
            model=os.environ.get(
                "VLLM_MODEL",
                "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4",
            ),
            base_url=os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8001/v1"),
            api_key="EMPTY",  # vLLM doesn't enforce
            _strict_tool_schema=False,
            max_completion_tokens=int(
                os.environ.get("VLLM_MAX_COMPLETION_TOKENS", "256")
            ),
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        log.info("llm.backend", backend="vllm-local", model=getattr(_llm, "model", "?"))
    else:
        # Cloud Anthropic baseline. Sonnet 4.6 + ephemeral caching.
        # Archived orchestrator_full.py used Opus 4.7 + 4 parallel tools +
        # STEP 2 Opus → 14-20 s reply latency, fatal for voice demo.
        # Sonnet 4.6 streaming TTFT ~500 ms puts first audio in the
        # caller's ears in ~2-3 s. See KB 08 §7.
        from livekit.plugins.anthropic import LLM as AnthropicLLM  # noqa: PLC0415

        _llm = AnthropicLLM(model="claude-sonnet-4-6", caching="ephemeral")
        log.info("llm.backend", backend="anthropic", model="claude-sonnet-4-6")

    # TTS backend selector — Lever 1 (KB 15).
    # Default stays "fish" (self-hosted B300) for zero regression.
    # Flip to "cartesia"/"deepgram_aura"/"elevenlabs" via env var once
    # the corresponding API key is provisioned in the pod .env.
    # Each import lives inside its branch so a missing plugin only
    # breaks that backend, not Fish.
    _tts_backend = os.environ.get("TTS_BACKEND", "fish").lower()
    if _tts_backend == "cartesia":
        from livekit.plugins import cartesia  # noqa: PLC0415
        _tts: Any = cartesia.TTS(
            model="sonic-3",
            voice=os.environ.get(
                "CARTESIA_VOICE_ID",
                # Sonic-3 "Professional Woman" (most professional female voice
                # in Cartesia's public roster as of 2026-04 per KB 15 snippet).
                "f786b574-daa5-4673-aa0c-cbe3e8534c02",
            ),
        )
        log.info("tts.backend", backend="cartesia", model="sonic-3")
    elif _tts_backend == "deepgram_aura":
        from livekit.agents import inference  # noqa: PLC0415
        _tts = inference.TTS(
            model="deepgram/aura-2",
            voice=os.environ.get("DEEPGRAM_VOICE", "athena"),
            language="en",
        )
        log.info("tts.backend", backend="deepgram_aura", model="aura-2")
    elif _tts_backend == "elevenlabs":
        from livekit.plugins import elevenlabs  # noqa: PLC0415
        _tts = elevenlabs.TTS(
            model="eleven_flash_v2_5",
            voice_id=os.environ.get("ELEVEN_VOICE_ID", "ODq5zmih8GrVes37Dizd"),
            streaming_latency=4,
        )
        log.info("tts.backend", backend="elevenlabs", model="eleven_flash_v2_5")
    else:
        _tts = FishSpeechTTS(FishSpeechOptions())
        log.info("tts.backend", backend="fish", model="s2-pro")

    # turn_handling — Lever 5 (KB 13 §9 911-dispatcher profile).
    # `TurnHandlingOptions` is a TypedDict of nested dicts in
    # livekit-agents 1.5.6 (voice/turn.py:145). Adaptive interruption
    # mode only activates once streaming STT lands (KB 13 §3 gate list);
    # until then the "adaptive" key is inert and falls back to VAD, so
    # setting it here is safe.
    #
    # Rationale per KB 13 §9:
    #   - endpointing.mode="dynamic": EMA-based pacing for hesitating
    #     911 callers; min_delay=0.6 gives the caller a beat to resume,
    #     max_delay=4.0 caps the wait before we assume turn-end.
    #   - interruption: adaptive when available, min_duration=0.35 +
    #     min_words=2 block cough-cancels, false_interruption_timeout
    #     1.5s resumes after a burp/cough.
    #   - preemptive_generation: preemptive_tts=True speculatively
    #     warms Fish for a latency win; max_speech_duration=12 covers
    #     longer 911 utterances.
    session = AgentSession(
        # Cycle-2I: raise min_silence_duration above the 0.55 s default
        # so caller pauses between street number, street name, and
        # apartment do not register as end-of-speech. Silero FAQ
        # explicitly recommends raising this for dictation scenarios.
        # Tunable via PRISM42_VAD_MIN_SILENCE_S (default 0.9 s).
        vad=silero.VAD.load(
            min_silence_duration=float(
                os.environ.get("PRISM42_VAD_MIN_SILENCE_S", "0.9")
            ),
        ),
        stt=ParakeetSTT(ParakeetOptions()),
        llm=_llm,
        tts=_tts,
        turn_handling={
            "endpointing": {
                "mode": "dynamic",
                # Cycle-2I: raise min_delay floor to 1.0 s so address-
                # dictation mid-pauses (0.6-0.9 s typical) do not fire
                # end-of-speech. Dynamic-EMA pulls effective delay back
                # down for fluent callers. max_delay=4.0 preserved.
                "min_delay": float(os.environ.get(
                    "PRISM42_ENDPOINT_MIN_DELAY_S", "1.0"
                )),
                "max_delay": float(os.environ.get(
                    "PRISM42_ENDPOINT_MAX_DELAY_S", "4.0"
                )),
            },
            "interruption": {
                "enabled": True,
                "mode": "adaptive",
                "min_duration": 0.35,
                "min_words": 2,
                "false_interruption_timeout": 1.5,
            },
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": True,
                "max_speech_duration": 12.0,
            },
        },
    )

    # One-shot assertion of the overlap-timing config for this session.
    # Emitted before any session event so Team B's parser can tie a run
    # window to the flags that produced it. Keep in sync with the env
    # vars documented under FILLERS / EARLY_LLM_CHARS above.
    _cycle2e_enabled = os.environ.get("PRISM42_CYCLE_2E_BUFFER", "0") == "1"
    log.info(
        "overlap.config",
        session_id=session_id,
        filler_delay_s=FILLER_DELAY_S,
        early_llm_chars=EARLY_LLM_CHARS,
        preemptive_generation_enabled=True,
        preemptive_tts_enabled=True,
        tts_backend=_tts_backend,
        cycle_2e_buffer_enabled=_cycle2e_enabled,
        cycle_2e_first_tokens=int(os.environ.get("PRISM42_CYCLE_2E_FIRST_TOKENS", "24")),
        cycle_2e_min_chars=int(os.environ.get("PRISM42_CYCLE_2E_MIN_CHARS", "8")),
    )

    orchestrator = make_orchestrator(session_id)
    # (additive) cycle-2R Team A — wire dispatch publisher (no-op when flag OFF).
    # cycle-2T2 — log init-attempt at INFO so blank-panel diagnosis can
    # confirm init is being invoked (vs flag off / module import failed).
    log.info(
        "dispatch_publisher.attach_attempt",
        session_id=session_id,
        flag_enabled=_dp_enabled(),
        module_loaded=DispatchPublisher is not None,
    )
    if DispatchPublisher is not None and _dp_enabled():
        try:
            _dp = DispatchPublisher(ctx.room, session_id)
            orchestrator._dispatch_publisher = _dp  # type: ignore[attr-defined]
            log.info(
                "dispatch_publisher.attached", session_id=session_id
            )
        except Exception as e:  # noqa: BLE001
            log.warning("dispatch_publisher.init_failed", err=str(e)[:200])

    # ---- post-turn hook: rubric grade + observability writes -------
    @session.on("agent_state_changed")  # type: ignore[arg-type]
    def _on_state(_state: Any) -> None:
        # Hook for live UI bridge in a follow-on PR.
        pass

    # ---- Pipeline-latency instrumentation (b3-latency channel) -----
    #
    # livekit-agents 1.5.6 emits a single `metrics_collected` event with
    # a discriminated-union payload — STTMetrics | LLMMetrics |
    # TTSMetrics | VADMetrics | EOUMetrics | RealtimeModelMetrics |
    # InterruptionMetrics — after each stage of the voice pipeline
    # completes (metrics/base.py:184). There is NO PipelineEOUMetrics
    # class in 1.5.6 — a phantom reference was removed per KB 13 §2.
    # Field names are the LiveKit public
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
            if cls_name in ("STTMetrics", "EOUMetrics"):
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
                # Overlap assertion: first TTS audio frame wallclock delay
                # since end-of-caller-speech. Fires once per turn (the first
                # TTSMetrics after user_speech_end; filler or reply). Team B
                # expects this parseable line under `overlap.*_ms`.
                t_end = cur.get("t_user_speech_end")
                now = time.monotonic()
                if t_end is not None and cur.get("t_first_tts_audio") is None:
                    cur["t_first_tts_audio"] = now
                    dt_ms = int((now - t_end) * 1000)
                    log.info(
                        "overlap.tts_first_audio_after_speech_ms",
                        session_id=session_id,
                        ms=dt_ms,
                        ttfb_ms=cur.get("tts_ms", 0),
                    )
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
        # Lever 6 (KB 13 §5): `conversation_item_added` fires for BOTH
        # user and assistant items in 1.5.6. Finalizing timings on the
        # user's chat-item submission pollutes the assistant-turn
        # metrics. Gate on role.
        if getattr(item, "role", None) != "assistant":
            return
        # Cycle-2Q: feed the realized dispatcher utterance into the
        # FSM's anti-repetition rolling buffer. No-op when the FSM is
        # disabled (orchestrator returned a vanilla Agent without a
        # `.fsm` attr). Best-effort — never block the latency path.
        try:
            fsm = getattr(orchestrator, "fsm", None)
            if fsm is not None:
                text = getattr(item, "text_content", None)
                if text:
                    fsm.record_dispatcher_reply(text)
        except Exception as e:  # noqa: BLE001
            log.warning("on_item.fsm_record_failed", err=str(e)[:200])
        # (additive) cycle-2R Team A — emit reply event for dispatcher UI.
        try:
            _dp = getattr(orchestrator, "_dispatch_publisher", None)
            if _dp is not None:
                _bucket_now = _timing_bucket(session_id)["current"]
                _dp.publish_reply(
                    text=getattr(item, "text_content", "") or "",
                    tts_ttfb_ms=int(_bucket_now.get("tts_ms", 0) or 0),
                    tts_total_ms=int(_bucket_now.get("tts_ms", 0) or 0),
                )
        except Exception as e:  # noqa: BLE001
            log.warning("on_item.dispatch_publish_failed", err=str(e)[:200])
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
            # Push assistant turn to the dispatcher SSE bus so the
            # /prism42/livekit transcript panel renders live.
            if latest.action == "speak" and latest.content:
                asyncio.create_task(
                    _post_turn_to_bus(session_id, "assistant", str(latest.content))
                )
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

            # Preemptive-gen detection + overlap.llm_first_token_after_speech
            # assertion. If speech_created fires BEFORE t_stt_end is set, that
            # means livekit started generation on a PREFLIGHT_TRANSCRIPT — i.e.
            # the STT plugin's `preflight` frames successfully kicked
            # `on_preemptive_generation()` in audio_recognition.py:777-822.
            # Emitted as a single parseable line with a numeric delay so
            # Team B's suite can assert ms ranges.
            t_end = cur.get("t_user_speech_end")
            if t_end is not None:
                dt_ms = int((now - t_end) * 1000)
                # Negative dt means speech_created fired BEFORE we even
                # saw VAD end-of-speech — extreme preemptive win.
                src = getattr(ev, "source", None) or getattr(ev, "kind", None)
                is_preempt = cur.get("t_stt_end") is None
                if is_preempt:
                    cur["preempt_gen_fired"] = True
                log.info(
                    "overlap.llm_first_token_after_speech_ms",
                    session_id=session_id,
                    ms=dt_ms,
                    preempt=is_preempt,
                    source=str(src) if src else None,
                )
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
            text = getattr(ev, "transcript", "") or ""
            is_final = bool(getattr(ev, "is_final", False))
            is_preflight = bool(
                getattr(ev, "is_preflight", False)
                or getattr(ev, "stable", False)
            )
            bucket = _timing_bucket(session_id)
            cur = bucket["current"]

            # Early-LLM telemetry hook. This does NOT trigger a second
            # generation — livekit-agents 1.5.6 already fires preemptive
            # gen on PREFLIGHT_TRANSCRIPT under the hood. We log a single
            # assertion per turn so bench_b300.py + Team B's test suite
            # can prove that early triggering is actually happening on
            # THIS pod+stream (not merely promised by the plugin
            # `capabilities.streaming=True` advertisement).
            if (
                EARLY_LLM_CHARS > 0
                and not is_final
                and len(text) >= EARLY_LLM_CHARS
                and not cur.get("early_llm_logged", False)
            ):
                log.info(
                    "overlap.early_llm_trigger",
                    session_id=session_id,
                    chars=len(text),
                    is_preflight=is_preflight,
                    text=text[:40],
                )
                cur["early_llm_logged"] = True

            # (additive) cycle-2T2 — emit caller_partial to the dispatch
            # data-track for BOTH interim and final transcripts so the UI
            # transcript pane shows the live "speaking..." pulse during
            # the caller's utterance, then promotes to a canonical
            # transcript row on the next `turn` event. Previously this
            # was gated under `if is_final:` which only emitted at the
            # tail of each utterance — fine for transcript correctness
            # but no live-pulse signal. Lifting this above the is_final
            # branch is safe because publish_caller_partial does NOT
            # increment turn_index and the reducer treats interim+final
            # symmetrically.
            try:
                _dp = getattr(orchestrator, "_dispatch_publisher", None)
                if _dp is not None and text:
                    _dp.publish_caller_partial(text=text, is_final=is_final)
            except Exception as e:  # noqa: BLE001
                log.warning("on_user_transcribed.dispatch_publish_failed", err=str(e)[:200])

            if is_final:
                now = time.monotonic()
                if cur.get("t_stt_end") is None:
                    cur["t_stt_end"] = now
                # LLM request kicks off as soon as the transcript is final.
                if cur.get("t_llm_start") is None:
                    cur["t_llm_start"] = now
                # Push caller turn to the dispatcher SSE bus so the
                # /prism42/livekit transcript panel renders live.
                if text:
                    asyncio.create_task(
                        _post_turn_to_bus(session_id, "user", text)
                    )
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

    # Cycle-2i: warm the 911 greeting cache BEFORE session.start() so the
    # greeting is ready to fire the moment the caller's audio track
    # subscribes. Order matters: if we wait until after session.start()
    # the LiveKit preemptive-generation pipeline can race ahead and queue
    # the LLM reply for an early caller utterance BEFORE our greeting,
    # which puts the greeting in second-position in the speech queue and
    # the harness times out before it plays.
    if ENABLE_911_GREETING and _GREETING_PCM_BYTES is None:
        # Block on cold-cache warm (~3 s Fish synth). Subsequent sessions
        # in the same Python subprocess hit the module cache for free.
        # Worth the ~3 s on the very first session because NENA identity
        # is mandatory and the alternative is no greeting at all.
        await _ensure_greeting_cache(
            os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:9200")
        )

    await session.start(agent=orchestrator, room=ctx.room)

    # Cycle-2i: dispatch the NENA-STA-020.1-2020 §2.2.3 identity greeting
    # IMMEDIATELY after session.start() returns, BEFORE wait_for_participant
    # and BEFORE any preemptive-generation pipeline can fire on caller
    # audio. PSAP standard requires the operator answer with "9-1-1" before
    # any other audio. session.say(audio=...) bypasses TTS inference and
    # forwards the cached AudioFrames directly to the WebRTC output queue,
    # so the greeting is first-position in the playback queue regardless
    # of whether the caller is mid-utterance. allow_interruptions=True
    # lets LiveKit's adaptive interruption-detection cut the greeting
    # short if the caller's barge-in is detected as a real interruption
    # (vs backchannel cough/breath).
    greeting_dispatched = False
    if ENABLE_911_GREETING:
        cache_source = "cached" if _GREETING_PCM_BYTES is not None else "miss"
        if _GREETING_PCM_BYTES is None:
            # Last-chance synth; warm above already tried but Fish may
            # have been transiently down.
            ok = await _ensure_greeting_cache(
                os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:9200")
            )
            cache_source = "resynth" if ok else "miss"
        if _GREETING_PCM_BYTES is not None:
            try:
                log.info(
                    "greeting.911.played",
                    session_id=session_id,
                    source=cache_source,
                    text=GREETING_TEXT,
                    duration_ms=_GREETING_AUDIO_DURATION_MS,
                )
                handle = session.say(
                    GREETING_TEXT,
                    audio=_greeting_audio_iter(),
                    allow_interruptions=True,
                    # add_to_chat_ctx=False keeps the LLM ChatContext
                    # clean — the greeting is operator identity, not
                    # a user-visible turn the model should echo back.
                    add_to_chat_ctx=False,
                )
                log.info(
                    "greeting.911.dispatched",
                    session_id=session_id,
                    handle_id=getattr(handle, "id", None),
                )
                greeting_dispatched = True
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "greeting.911.failed",
                    session_id=session_id,
                    err=str(e)[:200],
                )
        else:
            log.info(
                "greeting.911.skipped",
                session_id=session_id,
                reason="cache_miss",
            )

    # Pre-roll utterance: PSAP dispatchers answer first. Saying this BEFORE
    # waiting on the orchestrator's first LLM round-trip gives the caller
    # immediate audible confirmation that the line is live, and buys ~5-10s
    # of pipeline time during which the (slower) orchestrator+specialist
    # hop can complete without the caller hanging up in silence.
    #
    # When ENABLE_911_GREETING is OFF, this falls through to the legacy
    # cycle-2a preroll-disabled path (no greeting, first audio is the
    # real reply). When the flag is ON, the greeting was already
    # dispatched above and this block is just a no-op tail.
    try:
        await ctx.wait_for_participant()
    except Exception as e:  # noqa: BLE001
        log.warning("wait_for_participant.failed", err=str(e)[:200])

    try:
        await asyncio.wait_for(caller_spoke.wait(), timeout=0.5)
        if not greeting_dispatched:
            log.info("preroll.skipped_caller_spoke_first", session_id=session_id)
    except asyncio.TimeoutError:
        # Cycle-1 Fix 2 (2026-04-25): T5 forensic showed 4/10 turns paid
        # +850 ms median pad because preroll TTS blocked `speech_created`
        # firing. The wait_for timeout above only catches caller speech
        # within the first 500 ms — but the caller can also start
        # speaking between the timeout and the session.say() launch
        # (race window) OR while session.say() is mid-utterance.
        if greeting_dispatched:
            # Greeting already played; nothing more to do here.
            pass
        elif caller_spoke.is_set():
            log.info("preroll.skipped_caller_spoke_race", session_id=session_id)
        else:
            log.info("preroll.disabled_for_demo", session_id=session_id)  # cycle-2a: drop preroll-always-on; first audio = real reply

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
            # t_filler_scheduled: right before session.say dispatches the
            # filler text to TTS. This is our best proxy for "first filler
            # audio" because session.say returns AFTER the whole utterance
            # plays — too late for a meaningful ms delta. The actual first-
            # audio-frame wallclock is captured by the TTSMetrics path
            # (overlap.tts_first_audio_after_speech_ms) which covers the
            # filler too.
            bucket = _timing_bucket(session_id)
            cur = bucket["current"]
            t_end = cur.get("t_user_speech_end")
            t0 = time.monotonic()
            if cur.get("t_first_filler_audio") is None:
                cur["t_first_filler_audio"] = t0
            dt_ms = int((t0 - t_end) * 1000) if t_end is not None else -1
            log.info(
                "overlap.filler_after_speech_ms",
                session_id=session_id,
                ms=dt_ms,
                filler_delay_s=FILLER_DELAY_S,
                text=text,
            )
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
        # Cycle-2I: do NOT fire fillers during INTAKE phase. Address
        # dictation has natural intra-utterance pauses (0.6-0.9 s
        # between digit groups + street name + apt) that VAD reads as
        # end-of-speech. Filler audio talks over the caller's resume.
        # The cycle-2T response_gate template path renders intake
        # confirmation in <50 ms — no Fish-latency mask needed here.
        # PRISM42_FILLER_INTAKE_DISABLE=0 reverts to cycle-2Q behavior.
        if os.environ.get("PRISM42_FILLER_INTAKE_DISABLE", "1") == "1":
            try:
                fsm = getattr(orchestrator, "fsm", None)
                phase = getattr(getattr(fsm, "state", None), "value", "")
                if phase in ("intake", "address_confirmed"):
                    log.info(
                        "filler.suppressed_intake",
                        session_id=session_id,
                        phase=phase,
                    )
                    return
            except Exception:  # noqa: BLE001
                pass  # fall through to default behavior on error
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
