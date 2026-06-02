"""Custom LiveKit STT plugin for NVIDIA Parakeet (NeMo).

Replaces livekit-plugins-deepgram. Parakeet runs as a local HTTP
service on the B300 pod at http://127.0.0.1:9100 (see
infra/b300/services/parakeet/). Co-location eliminates the cloud
round-trip.

Rationale — user 2026-04-23:
  "Parakeet for STT — not because it's the most accurate, but
   because it's ~6× faster than the accuracy leaders and accuracy
   is already above the practical ceiling for voice agents."

Contract with the Parakeet service:
  POST /transcribe
    Content-Type: audio/wav  (16kHz mono PCM wrapped in minimal WAV)
    →  {"text": "...", "confidence": 0.0-1.0, "words": [{"w":"hi","start_ms":0,"end_ms":80}]}

  WS  /ws         (aiohttp WebSocket — true bidirectional)
    Client sends binary frames of PCM16 mono @ 16 kHz (any chunk
      size; 20 ms / 640 bytes is recommended).
    Client sends text frame `{"type":"flush"}` to mark end-of-
      utterance (server emits a `final` and accepts more audio for
      the next utterance) or `{"type":"close"}` to end the session.
    Server sends text frames:
      {"type":"partial","text":"...","ms":123}
      {"type":"preflight","text":"...","ms":234}
      {"type":"final","text":"...","ms":456,"confidence":0.92}

Phase 3b wires /ws with `streaming=True, interim_results=True`,
which flips preemptive generation on in livekit-agents 1.5.6
(voice/audio_recognition.py:777 fires the LLM on PREFLIGHT_TRANSCRIPT).
See KB 12 + KB 13 — this is the single biggest latency lever.

Why WebSocket and not POST + SSE: under HTTP/1.1, an httpx/aiohttp
streaming-body POST cannot interleave reads of the SSE response
while the request body is still being sent. The response chunks
buffer until the request body is complete, which defeats interim
results. WebSocket is the only correct shape for bidirectional
streaming over a single TCP connection. (Verified empirically
2026-04-24 against this exact pod — see Team S findings.)
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import wave
from dataclasses import dataclass, field

import aiohttp
import httpx
import numpy as np
import structlog
from livekit import rtc
from livekit.agents import stt, utils
from livekit.agents.stt import (
    RecognizeStream,
    SpeechData,
    SpeechEvent,
    SpeechEventType,
    STTCapabilities,
)
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

log = structlog.get_logger()

DEFAULT_URL = os.environ.get("PARAKEET_URL", "http://127.0.0.1:9100")
DEFAULT_MODEL = os.environ.get("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
SAMPLE_RATE = 16_000
CHANNELS = 1
BYTES_PER_FRAME = 640  # 20 ms @ 16 kHz PCM16


def _env_bool(name: str, default: bool) -> bool:
    """Lightweight env bool parser — returns default if unset."""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ParakeetOptions:
    url: str = DEFAULT_URL
    model: str = DEFAULT_MODEL
    language: str = "en"
    confidence_floor: float = 0.0
    # If the service's reported confidence drops below this, we still
    # emit the transcript but the specialist's rationale can reference
    # it to prompt for repeat.
    request_timeout_s: float = 30.0
    # When True, the plugin advertises streaming + interim capabilities
    # and uses /stream for every utterance. Kept as a flag so the batch
    # path stays available as a fallback.
    #
    # PRISM42_PARAKEET_STREAMING=0 flips to batch (/transcribe) mode —
    # useful when the streaming `/ws` endpoint is down or when A/B
    # benching streaming vs batch on the same pod. Overlap-timing
    # bench needs this while Team S's streaming server rolls out.
    streaming: bool = field(
        default_factory=lambda: _env_bool("PRISM42_PARAKEET_STREAMING", True)
    )


class ParakeetSTT(stt.STT):
    """LiveKit STT adapter for NVIDIA Parakeet on B300.

    Defaults to streaming via POST /stream (SSE). Batch `recognize`
    remains available and points at POST /transcribe.
    """

    def __init__(self, opts: ParakeetOptions | None = None) -> None:
        _opts = opts or ParakeetOptions()
        super().__init__(
            capabilities=STTCapabilities(
                streaming=_opts.streaming,
                interim_results=_opts.streaming,
            )
        )
        self._opts = _opts
        # One httpx client shared by the batch path. The streaming
        # path opens its own short-lived client per utterance because
        # httpx.AsyncClient's stream() response is tied to the client
        # lifecycle.
        self._client = httpx.AsyncClient(timeout=self._opts.request_timeout_s)

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "parakeet-nemo"

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> SpeechEvent:
        """Called by LiveKit when a full utterance is ready for ASR.

        This path is used when `capabilities.streaming=False` or when
        the caller explicitly invokes `recognize()` (fallback + offline
        scoring).
        """
        del conn_options  # we don't honor per-call overrides yet
        lang = language if isinstance(language, str) else self._opts.language

        # Merge AudioBuffer frames → single PCM16 numpy array.
        frames = utils.merge_frames(buffer)
        pcm = np.frombuffer(frames.data, dtype=np.int16)
        wav_bytes = _pcm_to_wav(pcm, frames.sample_rate, frames.num_channels)

        try:
            resp = await self._client.post(
                f"{self._opts.url}/transcribe",
                content=wav_bytes,
                headers={"Content-Type": "audio/wav"},
                params={"model": self._opts.model, "language": lang},
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            log.warning("parakeet.transport_error", err=str(e)[:200])
            return SpeechEvent(
                type=SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[SpeechData(language=lang, text="", confidence=0.0)],
            )

        text = payload.get("text", "")
        conf = float(payload.get("confidence", 0.0))
        return SpeechEvent(
            type=SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[SpeechData(language=lang, text=text, confidence=conf)],
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "ParakeetSpeechStream":
        return ParakeetSpeechStream(
            stt=self,
            opts=self._opts,
            language=language if isinstance(language, str) else self._opts.language,
            conn_options=conn_options,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class ParakeetSpeechStream(RecognizeStream):
    """Bidirectional streaming STT over WebSocket.

    Input side: LiveKit pushes `rtc.AudioFrame`s into `self._input_ch`
    via `push_frame()`. We send them as binary WebSocket frames to
    `/ws` on the Parakeet server.

    Output side: we read text frames from the WebSocket and emit
    `SpeechEvent`s of type:
      - INTERIM_TRANSCRIPT   for {"type":"partial"}
      - PREFLIGHT_TRANSCRIPT for {"type":"preflight"} (stable prefix —
                             triggers preemptive generation in 1.5.6)
      - FINAL_TRANSCRIPT     for {"type":"final"}

    The lifecycle: one WebSocket per session (multiple utterances).
    On each LiveKit FlushSentinel we send `{"type":"flush"}`, the
    server emits a final and resets, and we keep the same WS open for
    the next utterance. On session close we send `{"type":"close"}`.
    """

    def __init__(
        self,
        *,
        stt: ParakeetSTT,
        opts: ParakeetOptions,
        language: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=SAMPLE_RATE)
        self._opts = opts
        self._language = language
        self._rebuffer = utils.audio.AudioByteStream(
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
            samples_per_channel=SAMPLE_RATE // 50,  # 20 ms frames
        )

    @property
    def _ws_url(self) -> str:
        # http://host:port → ws://host:port/ws ; https → wss
        u = self._opts.url.rstrip("/")
        if u.startswith("https://"):
            return "wss://" + u[len("https://") :] + "/ws"
        if u.startswith("http://"):
            return "ws://" + u[len("http://") :] + "/ws"
        # Already ws/wss?
        return u + "/ws"

    async def _run(self) -> None:
        """Run one WebSocket session for the lifetime of this stream.

        Within the session we expect zero-or-more utterances. Each
        FlushSentinel on the input channel maps to a `flush` control
        frame. Session ends when the input channel is closed.
        """
        ws_url = self._ws_url
        utterance_active = False
        utt_start_loop_time = 0.0
        sent_start_of_speech = False
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=5.0, sock_read=None)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as http:
                # Cycle-2Q6 (parallel-session-coord §4 finding 1, operator
                # OK 2026-04-27): drop the `prism42-parakeet-v1` subprotocol
                # negotiation. The Parakeet container's `@app.websocket("/ws")`
                # handler in infra/b300/services/parakeet/server.py:262 does
                # not validate or accept that subprotocol; FastAPI/Starlette
                # rejects with HTTP 400 before the WebSocket upgrade
                # completes. Symptom: every session showed stt_ms=0 with
                # no caller-turn events. Falling back to no-subprotocol
                # negotiation is the one-line client-side fix.
                async with http.ws_connect(
                    ws_url,
                    max_msg_size=0,  # no cap; binary audio is small per-frame
                    heartbeat=None,
                ) as ws:
                    log.debug("parakeet.ws.connected", url=ws_url)

                    async def reader() -> None:
                        """Receive text frames → emit SpeechEvents."""
                        nonlocal utterance_active, sent_start_of_speech
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    payload = json.loads(msg.data)
                                except json.JSONDecodeError:
                                    continue
                                kind = payload.get("type")
                                text = payload.get("text", "") or ""
                                if kind == "partial":
                                    if not sent_start_of_speech:
                                        self._event_ch.send_nowait(
                                            SpeechEvent(type=SpeechEventType.START_OF_SPEECH)
                                        )
                                        sent_start_of_speech = True
                                    self._event_ch.send_nowait(
                                        SpeechEvent(
                                            type=SpeechEventType.INTERIM_TRANSCRIPT,
                                            alternatives=[
                                                SpeechData(
                                                    language=self._language,
                                                    text=text,
                                                    confidence=0.0,
                                                )
                                            ],
                                        )
                                    )
                                elif kind == "preflight":
                                    if not sent_start_of_speech:
                                        self._event_ch.send_nowait(
                                            SpeechEvent(type=SpeechEventType.START_OF_SPEECH)
                                        )
                                        sent_start_of_speech = True
                                    self._event_ch.send_nowait(
                                        SpeechEvent(
                                            type=SpeechEventType.PREFLIGHT_TRANSCRIPT,
                                            alternatives=[
                                                SpeechData(
                                                    language=self._language,
                                                    text=text,
                                                    confidence=0.0,
                                                )
                                            ],
                                        )
                                    )
                                elif kind == "final":
                                    conf = float(payload.get("confidence", 0.0))
                                    self._event_ch.send_nowait(
                                        SpeechEvent(
                                            type=SpeechEventType.FINAL_TRANSCRIPT,
                                            alternatives=[
                                                SpeechData(
                                                    language=self._language,
                                                    text=text,
                                                    confidence=conf,
                                                )
                                            ],
                                        )
                                    )
                                    self._event_ch.send_nowait(
                                        SpeechEvent(type=SpeechEventType.END_OF_SPEECH)
                                    )
                                    sent_start_of_speech = False
                                    utterance_active = False
                                elif kind == "error":
                                    log.warning(
                                        "parakeet.ws.server_error",
                                        err=payload.get("err", ""),
                                    )
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                return
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                log.warning(
                                    "parakeet.ws.transport_error",
                                    err=str(ws.exception())[:200],
                                )
                                return

                    reader_task = asyncio.create_task(reader(), name="ParakeetSTT.ws_reader")
                    try:
                        async for data in self._input_ch:
                            if isinstance(data, self._FlushSentinel):
                                # End of utterance — flush the local
                                # 20 ms rebuffer, then send flush ctrl.
                                for chunk in _frame_to_20ms_flush(self._rebuffer):
                                    if chunk:
                                        await ws.send_bytes(chunk)
                                await ws.send_str(json.dumps({"type": "flush"}))
                                continue
                            # AudioFrame → 20 ms chunks → binary frames.
                            if not utterance_active:
                                utterance_active = True
                                utt_start_loop_time = asyncio.get_event_loop().time()
                            for chunk in _frame_to_20ms_bytes(data, self._rebuffer):
                                if chunk:
                                    await ws.send_bytes(chunk)
                        # Input channel closed — flush + close.
                        for chunk in _frame_to_20ms_flush(self._rebuffer):
                            if chunk:
                                await ws.send_bytes(chunk)
                        if utterance_active:
                            await ws.send_str(json.dumps({"type": "flush"}))
                        await ws.send_str(json.dumps({"type": "close"}))
                    finally:
                        # Wait briefly for any final frames the reader
                        # is still consuming, then cancel.
                        try:
                            await asyncio.wait_for(reader_task, timeout=2.0)
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            reader_task.cancel()
                            try:
                                await reader_task
                            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                                pass
                        log.debug(
                            "parakeet.ws.utterance_done",
                            ms=int((asyncio.get_event_loop().time() - utt_start_loop_time) * 1000)
                            if utt_start_loop_time
                            else 0,
                        )
        except aiohttp.ClientError as e:
            log.warning("parakeet.ws.connect_error", err=str(e)[:200])
            # Emit a final-empty so AudioRecognition doesn't hang.
            self._event_ch.send_nowait(
                SpeechEvent(
                    type=SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        SpeechData(
                            language=self._language,
                            text="",
                            confidence=0.0,
                        )
                    ],
                )
            )
            self._event_ch.send_nowait(
                SpeechEvent(type=SpeechEventType.END_OF_SPEECH)
            )


def _frame_to_20ms_bytes(
    frame: rtc.AudioFrame, rebuffer: utils.audio.AudioByteStream
) -> list[bytes]:
    """Push a LiveKit AudioFrame through the 20 ms rebuffer and
    return the list of 20 ms PCM16 byte-chunks ready for the server.
    """
    out: list[bytes] = []
    for buf in rebuffer.write(frame.data.tobytes()):
        out.append(buf.data.tobytes())
    return out


def _frame_to_20ms_flush(rebuffer: utils.audio.AudioByteStream) -> list[bytes]:
    out: list[bytes] = []
    for buf in rebuffer.flush():
        out.append(buf.data.tobytes())
    return out


def _pcm_to_wav(pcm: np.ndarray, sample_rate: int, channels: int) -> bytes:
    """Wrap PCM16 in a minimal WAV container. The Parakeet service
    prefers this over raw PCM — sample rate + channel metadata is
    inlined instead of tunneled through query params.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
