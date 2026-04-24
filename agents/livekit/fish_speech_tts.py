"""Custom LiveKit TTS plugin for Fish Speech S2 Pro on SGLang.

Replaces livekit-plugins-cartesia. Fish Speech S2 Pro runs on the
B300 pod at http://127.0.0.1:9200 with SGLang as the inference
backend (see infra/b300/services/fish-speech/). Co-located; zero
cloud hop.

Rationale — user 2026-04-23:
  "Fish Speech S2 Pro for TTS — currently beats ElevenLabs on two of
   three major quality benchmarks, runs on SGLang, ~100ms TTFA on
   H200 and faster on B300."

Contract with the Fish Speech service:
  POST /tts
    { "text": "...", "voice_id": "default", "format": "pcm16",
      "sample_rate": 24000, "stream": true }
    → chunked response of raw PCM16 frames; each chunk is ~120 ms
      of audio suitable for direct injection into LiveKit's audio
      pipeline with no further resampling.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import numpy as np
import structlog
from livekit import rtc
from livekit.agents import tts, utils

log = structlog.get_logger()

DEFAULT_URL = os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:9200")
DEFAULT_VOICE = os.environ.get("FISH_SPEECH_VOICE", "default")
SAMPLE_RATE = 24_000
CHANNELS = 1


@dataclass
class FishSpeechOptions:
    url: str = DEFAULT_URL
    voice_id: str = DEFAULT_VOICE
    # S2 Pro's "speed" knob; 1.0 is the stock cadence tuned for
    # English. Dispatcher UX wants crisp, fast delivery; keep 1.0
    # unless we see latency budget pressure.
    speed: float = 1.0
    # SGLang streaming chunk size. 120 ms @ 24 kHz = 2880 samples.
    chunk_samples: int = 2880
    request_timeout_s: float = 30.0


class FishSpeechTTS(tts.TTS):
    """LiveKit TTS adapter for Fish Speech S2 Pro on B300.

    LiveKit's `TTS` base class handles text normalization + the
    synth-buffer dance. We only need to implement `synthesize()`
    as a generator of audio frames (`rtc.AudioFrame`).
    """

    def __init__(self, opts: FishSpeechOptions | None = None) -> None:
        self._opts = opts or FishSpeechOptions()
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
        )
        self._client = httpx.AsyncClient(timeout=self._opts.request_timeout_s)

    def synthesize(
        self,
        text: str,
        *,
        conn_options: object | None = None,
    ) -> tts.ChunkedStream:
        del conn_options
        return _FishSpeechStream(tts=self, text=text, opts=self._opts, client=self._client)

    async def aclose(self) -> None:
        await self._client.aclose()


class _FishSpeechStream(tts.ChunkedStream):
    """Streams PCM16 chunks from the Fish Speech service to LiveKit.

    Each yielded frame is a 120 ms PCM16 block that LiveKit sends
    straight to the caller's audio track — no resampling, no codec
    conversion.
    """

    def __init__(
        self,
        *,
        tts: FishSpeechTTS,
        text: str,
        opts: FishSpeechOptions,
        client: httpx.AsyncClient,
    ) -> None:
        super().__init__(tts=tts, input_text=text)
        self._text = text
        self._opts = opts
        self._client = client

    async def _run(self) -> None:
        try:
            async with self._client.stream(
                "POST",
                f"{self._opts.url}/tts",
                json={
                    "text": self._text,
                    "voice_id": self._opts.voice_id,
                    "speed": self._opts.speed,
                    "format": "pcm16",
                    "sample_rate": SAMPLE_RATE,
                    "stream": True,
                    "chunk_samples": self._opts.chunk_samples,
                },
            ) as resp:
                resp.raise_for_status()
                # SGLang streams raw PCM16 bytes; each chunk is already
                # sized to chunk_samples × 2 bytes.
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    # Guard against odd-sized chunks from the wire.
                    if len(chunk) % 2 != 0:
                        chunk = chunk[:-1]
                    samples = np.frombuffer(chunk, dtype=np.int16)
                    if samples.size == 0:
                        continue
                    frame = rtc.AudioFrame(
                        data=samples.tobytes(),
                        sample_rate=SAMPLE_RATE,
                        num_channels=CHANNELS,
                        samples_per_channel=samples.size // CHANNELS,
                    )
                    self._event_ch.send_nowait(
                        tts.SynthesizedAudio(
                            request_id=utils.shortuuid(),
                            frame=frame,
                        )
                    )
        except httpx.HTTPError as e:
            log.warning("fishspeech.transport_error", err=str(e)[:200])
            # Emit one silent frame so LiveKit doesn't hang on the
            # missing-audio edge — caller hears nothing for this
            # turn. Orchestrator's safe-fallback path will replay
            # "one moment please" on the NEXT turn if this was a
            # speak action that dropped.
            silent = np.zeros(self._opts.chunk_samples, dtype=np.int16)
            self._event_ch.send_nowait(
                tts.SynthesizedAudio(
                    request_id=utils.shortuuid(),
                    frame=rtc.AudioFrame(
                        data=silent.tobytes(),
                        sample_rate=SAMPLE_RATE,
                        num_channels=CHANNELS,
                        samples_per_channel=silent.size,
                    ),
                )
            )
