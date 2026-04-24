"""Custom LiveKit TTS plugin for Fish Speech S2 Pro.

Talks to the upstream `tools/api_server.py` from fishaudio/fish-speech
running locally on the B300 pod. Wire format is ormsgpack (the upstream
server's native body codec); endpoint is POST /v1/tts.

S2-Pro DAC decoder outputs PCM at 44.1 kHz mono; LiveKit's mixer handles
resampling to the WebRTC negotiated rate.

Implements the livekit-agents 1.5.x ChunkedStream + AudioEmitter API:
- synthesize() returns a ChunkedStream subclass
- ChunkedStream._run(output_emitter) pushes raw PCM bytes to the emitter
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import numpy as np
import ormsgpack
import structlog
from livekit.agents import APIConnectOptions, tts, utils

log = structlog.get_logger()

DEFAULT_URL = os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:9200")
DEFAULT_REFERENCE_ID = os.environ.get("FISH_SPEECH_REFERENCE_ID", "")
SAMPLE_RATE = 44_100
CHANNELS = 1


@dataclass
class FishSpeechOptions:
    url: str = DEFAULT_URL
    reference_id: str = DEFAULT_REFERENCE_ID
    chunk_length: int = 200
    normalize: bool = True
    temperature: float = 0.8
    top_p: float = 0.8
    repetition_penalty: float = 1.1
    request_timeout_s: float = 30.0


class FishSpeechTTS(tts.TTS):
    def __init__(self, opts: FishSpeechOptions | None = None) -> None:
        self._opts = opts or FishSpeechOptions()
        # streaming=False: we implement chunked-stream synthesize() only,
        # not the framework's stream() method. livekit-agents will route
        # to synthesize() for full-utterance synthesis. Per
        # docs/livekit-kb/05-debugging-playbook.md (2026-04-24): claiming
        # streaming=True without implementing stream() raises
        # NotImplementedError mid-call and the agent emits no audio.
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
        )
        self._client = httpx.AsyncClient(timeout=self._opts.request_timeout_s)

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions,
    ) -> tts.ChunkedStream:
        return _FishSpeechStream(
            tts=self,
            text=text,
            opts=self._opts,
            client=self._client,
            conn_options=conn_options,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class _FishSpeechStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: FishSpeechTTS,
        text: str,
        opts: FishSpeechOptions,
        client: httpx.AsyncClient,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=text, conn_options=conn_options)
        self._text = text
        self._opts = opts
        self._client = client

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
            mime_type="audio/pcm",
            stream=False,
        )
        body = {
            "text": self._text,
            # Fish Speech upstream rejects "pcm" with 500 "Unknown format"; only
            # accepts "wav" or "mp3" at /v1/tts. Under streaming=True the WAV
            # branch returns RAW 16-bit PCM samples at SAMPLE_RATE/CHANNELS
            # without a RIFF header — verified 2026-04-24 against
            # fish-speech api_server.py upstream behavior.
            "format": "wav",
            "chunk_length": self._opts.chunk_length,
            "normalize": self._opts.normalize,
            "streaming": True,
            "max_new_tokens": 1024,
            "top_p": self._opts.top_p,
            "repetition_penalty": self._opts.repetition_penalty,
            "temperature": self._opts.temperature,
            "use_memory_cache": "off",
            "references": [],
        }
        if self._opts.reference_id:
            body["reference_id"] = self._opts.reference_id

        try:
            async with self._client.stream(
                "POST",
                f"{self._opts.url}/v1/tts",
                content=ormsgpack.packb(body),
                headers={"Content-Type": "application/msgpack"},
            ) as resp:
                resp.raise_for_status()
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    # AudioEmitter expects whole 16-bit samples; trim odd byte.
                    if len(buf) % 2 == 1:
                        odd = bytes(buf[-1:])
                        del buf[-1:]
                    else:
                        odd = b""
                    if buf:
                        output_emitter.push(bytes(buf))
                    buf.clear()
                    buf.extend(odd)
            output_emitter.flush()
        except httpx.HTTPError as e:
            log.warning("fishspeech.transport_error", err=str(e)[:200])
            # Push 100ms of silence so the agent doesn't deadlock waiting
            # for any audio at all.
            silent = np.zeros(SAMPLE_RATE // 10, dtype=np.int16)
            output_emitter.push(silent.tobytes())
            output_emitter.flush()
