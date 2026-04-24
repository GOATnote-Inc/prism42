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

  POST /stream                 (WebSocket)
    Client sends binary PCM16 chunks (20ms @ 16kHz = 640 bytes)
    Server sends text frames:
      {"type":"partial","text":"...","stability":0.0-1.0}
      {"type":"final","text":"...","confidence":0.0-1.0,"words":[...]}

For Phase 3a we ship the batch (POST /transcribe) path — LiveKit's
base STT class already handles streaming via buffered utterances.
Phase 3b switches to the WebSocket streaming path for sub-100ms
first-partial latency.
"""
from __future__ import annotations

import asyncio
import io
import os
import struct
import wave
from dataclasses import dataclass

import httpx
import numpy as np
import structlog
from livekit import rtc
from livekit.agents import stt, utils
from livekit.agents.stt import (
    SpeechData,
    SpeechEvent,
    SpeechEventType,
    STTCapabilities,
)

log = structlog.get_logger()

DEFAULT_URL = os.environ.get("PARAKEET_URL", "http://127.0.0.1:9100")
DEFAULT_MODEL = os.environ.get("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
SAMPLE_RATE = 16_000
CHANNELS = 1


@dataclass
class ParakeetOptions:
    url: str = DEFAULT_URL
    model: str = DEFAULT_MODEL
    language: str = "en"
    confidence_floor: float = 0.0
    # If the service's reported confidence drops below this, we still
    # emit the transcript but the specialist's rationale can reference
    # it to prompt for repeat.
    request_timeout_s: float = 10.0


class ParakeetSTT(stt.STT):
    """LiveKit STT adapter for NVIDIA Parakeet on B300.

    Inherits the non-streaming `recognize` interface; LiveKit's
    `StreamAdapter` wraps it with VAD-driven utterance chunking. If
    the Parakeet service exposes /stream (WebSocket), subclass this
    and override `stream()` with a direct binding.
    """

    def __init__(self, opts: ParakeetOptions | None = None) -> None:
        super().__init__(
            capabilities=STTCapabilities(
                streaming=False,
                interim_results=False,
            )
        )
        self._opts = opts or ParakeetOptions()
        self._client = httpx.AsyncClient(timeout=self._opts.request_timeout_s)

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: str | None = None,
        conn_options: object | None = None,
    ) -> SpeechEvent:
        """Called by LiveKit when a full utterance is ready for ASR."""
        del conn_options  # we don't honor per-call overrides yet
        lang = language or self._opts.language

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
            # Emit empty speech event — the orchestrator will prompt
            # for repeat via the "one-moment-please" fallback.
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

    async def aclose(self) -> None:
        await self._client.aclose()


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
