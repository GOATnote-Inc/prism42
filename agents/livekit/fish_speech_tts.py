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
import time
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
    # chunk_length = semantic-token chunk size. Fish's ServeTTSRequest
    # Pydantic schema enforces 100 <= chunk_length <= 1000 — values below
    # 100 (we previously tried 50) return 422. 200 is the schema default.
    chunk_length: int = 200
    normalize: bool = True
    # DETERMINISTIC SAMPLING — 2026-04-24 fix for multi-voice symptom:
    # Fish's text2semantic inference is torch.manual_seed-addressable via
    # the top-level `seed` field on the TTS request. Research probe
    # (agent a62ed52f) confirmed: two calls with seed=911 produce
    # byte-identical output (sha256 match). temperature/top_p stay at
    # schema floor for narrowest sampling within determinism.
    temperature: float = 0.1
    top_p: float = 0.7
    repetition_penalty: float = 1.1
    request_timeout_s: float = 30.0
    # Fish text2semantic seed. Setting this makes voice identity
    # reproducible call-to-call. Earlier 422 was from chunk_length=50,
    # not from this field being unsupported.
    seed: int = 911


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
        # Timing budget (the real bottleneck lives here).
        # TTS_T0 = _run entry (immediately after LLM emits the full text
        #          block and livekit-agents schedules the TTS stream)
        # TTS_T_POST = moment we send the HTTP POST to Fish
        # TTS_T_FIRST_BYTE = first response byte from Fish (HTTP TTFB)
        # TTS_T_FIRST_PUSH = first emitter.push(bytes) call (frames start
        #                    flowing into the AudioEmitter → LiveKit)
        # TTS_T_FLUSH = end-of-synthesis flush (total duration)
        t0 = time.monotonic()
        # AudioEmitter frame_size_ms defaults to 200 → first audio frame
        # arrives after we've pushed >= 200ms of samples. Drop to 40ms
        # so the first audible frame reaches WebRTC as soon as Fish emits
        # its first ~3.5KB (~40ms * 44100 * 2 bytes).
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
            mime_type="audio/pcm",
            stream=False,
            frame_size_ms=40,
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
            # "on" reuses internal KV cache across calls, safe once seed
            # locks voice (otherwise cache hits could leak previous
            # voice samples into the current response).
            "use_memory_cache": "on",
            "seed": self._opts.seed,
            "references": [],
        }
        if self._opts.reference_id:
            body["reference_id"] = self._opts.reference_id

        t_post = time.monotonic()
        log.info(
            "fishspeech.t0",
            text_len=len(self._text),
            chunk_length=self._opts.chunk_length,
        )
        try:
            async with self._client.stream(
                "POST",
                f"{self._opts.url}/v1/tts",
                content=ormsgpack.packb(body),
                headers={"Content-Type": "application/msgpack"},
            ) as resp:
                resp.raise_for_status()
                buf = bytearray()
                t_first_byte = None
                t_first_push = None
                total_bytes = 0
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    if t_first_byte is None:
                        t_first_byte = time.monotonic()
                        log.info(
                            "fishspeech.t_first_byte",
                            ms_since_t0=int((t_first_byte - t0) * 1000),
                            ms_since_post=int((t_first_byte - t_post) * 1000),
                        )
                    buf.extend(chunk)
                    total_bytes += len(chunk)
                    # AudioEmitter expects whole 16-bit samples; trim odd byte.
                    if len(buf) % 2 == 1:
                        odd = bytes(buf[-1:])
                        del buf[-1:]
                    else:
                        odd = b""
                    if buf:
                        if t_first_push is None:
                            t_first_push = time.monotonic()
                            log.info(
                                "fishspeech.t_first_push",
                                ms_since_t0=int((t_first_push - t0) * 1000),
                                ms_since_first_byte=int(
                                    (t_first_push - t_first_byte) * 1000
                                ),
                                first_push_bytes=len(buf),
                            )
                        output_emitter.push(bytes(buf))
                    buf.clear()
                    buf.extend(odd)
            output_emitter.flush()
            t_flush = time.monotonic()
            log.info(
                "fishspeech.done",
                total_ms=int((t_flush - t0) * 1000),
                total_bytes=total_bytes,
                audio_duration_ms=int(
                    total_bytes / 2 / SAMPLE_RATE * 1000
                ),
            )
        except httpx.HTTPError as e:
            log.warning("fishspeech.transport_error", err=str(e)[:200])
            # Push 100ms of silence so the agent doesn't deadlock waiting
            # for any audio at all.
            silent = np.zeros(SAMPLE_RATE // 10, dtype=np.int16)
            output_emitter.push(silent.tobytes())
            output_emitter.flush()
