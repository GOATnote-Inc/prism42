"""Custom LiveKit TTS plugin for NeMo Magpie-TTS Multilingual (357M).

Loads `nvidia/magpie_tts_multilingual_357m` in-process — no NIM, no Riva,
no NGC auth at runtime. NVIDIA Open Model License, freely downloadable
from HuggingFace. ~16 GB VRAM on H100/H200 alongside Parakeet + Nemotron.

Operator architecture decision (2026-04-27, parallel-session-coord §6.5):
NVIDIA-first ≠ Riva-first. Magpie the model is canonical sovereign TTS;
Magpie-the-NIM is the broken layer (no H200 profile in its manifest).
This plugin sidesteps the NIM by loading the same Magpie checkpoint
directly via NeMo.

Output: PCM mono @ 22 kHz from the 22kHz NeMo nano codec
(`nemo-nano-codec-22khz-1.89kbps-21.5fps`). LiveKit's mixer resamples
to the WebRTC negotiated rate at the publish boundary.

Implements the livekit-agents 1.5.x ChunkedStream + AudioEmitter API;
mirrors the structure of `fish_speech_tts.py` (streaming=False,
synthesize-only).

Sources:
- https://huggingface.co/nvidia/magpie_tts_multilingual_357m
- https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tts/magpietts.html
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
from livekit.agents import APIConnectOptions, tts, utils

log = structlog.get_logger()

SAMPLE_RATE = 22_050  # NeMo nano-codec rate; LiveKit handles resample to 48 kHz
CHANNELS = 1

DEFAULT_MODEL = os.environ.get(
    "PRISM42_MAGPIE_MODEL", "nvidia/magpie_tts_multilingual_357m"
)
DEFAULT_LANGUAGE = os.environ.get("PRISM42_MAGPIE_LANGUAGE", "en")
DEFAULT_SPEAKER_INDEX = int(os.environ.get("PRISM42_MAGPIE_SPEAKER_INDEX", "0"))
# do_tts() in standard mode caps at 20 s. We sentence-chunk long replies
# to avoid mid-utterance truncation; tunable for A/B with longform mode.
MAX_CHARS_PER_CHUNK = int(os.environ.get("PRISM42_MAGPIE_MAX_CHARS", "300"))

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class MagpieOptions:
    model_id: str = DEFAULT_MODEL
    language: str = DEFAULT_LANGUAGE
    speaker_index: int = DEFAULT_SPEAKER_INDEX
    max_chars_per_chunk: int = MAX_CHARS_PER_CHUNK
    apply_text_normalization: bool = False


class MagpieTTS(tts.TTS):
    """In-process Magpie-TTS LiveKit plugin.

    Loads the NeMo `MagpieTTSModel` once at __init__; subsequent
    `synthesize()` calls reuse the resident model on GPU. Lazy-imports
    NeMo so the module can be imported without NeMo installed
    (worker.py only instantiates this when TTS_BACKEND=magpie_nemo).
    """

    def __init__(self, opts: MagpieOptions | None = None) -> None:
        self._opts = opts or MagpieOptions()
        # Lazy import; NeMo is heavy and only needed when this backend is selected.
        from nemo.collections.tts.models import MagpieTTSModel  # noqa: PLC0415

        log.info(
            "magpie_tts.loading",
            model_id=self._opts.model_id,
            language=self._opts.language,
        )
        t0 = time.monotonic()
        self._model = MagpieTTSModel.from_pretrained(self._opts.model_id)
        self._model.eval()
        try:
            self._model = self._model.cuda()
            self._device = "cuda"
        except Exception as e:  # noqa: BLE001
            log.warning("magpie_tts.cuda_failed", err=str(e)[:200])
            self._device = "cpu"
        log.info(
            "magpie_tts.loaded",
            device=self._device,
            load_ms=int((time.monotonic() - t0) * 1000),
        )
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
        )

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions,
    ) -> tts.ChunkedStream:
        return _MagpieStream(
            tts=self,
            text=text,
            opts=self._opts,
            model=self._model,
            conn_options=conn_options,
        )

    async def aclose(self) -> None:
        # NeMo model holds a single GPU allocation; no client to close.
        pass


def _split_sentences(text: str, max_chars: int) -> list[str]:
    """Split text into ≤max_chars chunks at sentence boundaries when possible."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sentences = _SENTENCE_SPLIT.split(text)
    out: list[str] = []
    cur = ""
    for s in sentences:
        if not s:
            continue
        if len(cur) + len(s) + 1 <= max_chars:
            cur = (cur + " " + s).strip()
        else:
            if cur:
                out.append(cur)
            # Sentence longer than max_chars — emit as-is; Magpie will
            # truncate at 20 s but better than dropping the turn.
            cur = s
    if cur:
        out.append(cur)
    return out


class _MagpieStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: MagpieTTS,
        text: str,
        opts: MagpieOptions,
        model: Any,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=text, conn_options=conn_options)
        self._text = text
        self._opts = opts
        self._model = model

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        t0 = time.monotonic()
        _frame_ms = int(os.environ.get("PRISM42_TTS_FRAME_MS", "200"))
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
            mime_type="audio/pcm",
            stream=False,
            frame_size_ms=_frame_ms,
        )

        chunks = _split_sentences(self._text, self._opts.max_chars_per_chunk)
        if not chunks:
            output_emitter.flush()
            return

        first_push_logged = False
        total_pcm_bytes = 0
        for i, chunk in enumerate(chunks):
            try:
                # do_tts is synchronous; runs in calling thread. NeMo
                # holds the GIL during inference. Acceptable here because
                # TTS calls are infrequent (one per agent reply) and
                # short (< 20 s of audio max).
                audio, audio_len = self._model.do_tts(
                    transcript=chunk,
                    language=self._opts.language,
                    apply_TN=self._opts.apply_text_normalization,
                    speaker_index=self._opts.speaker_index,
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "magpie_tts.synth_failed",
                    chunk_index=i,
                    chunk_chars=len(chunk),
                    err=str(e)[:200],
                )
                continue

            # `audio` is a torch.Tensor or numpy array; convert to int16 PCM bytes.
            try:
                audio_np = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            except Exception as e:  # noqa: BLE001
                log.warning("magpie_tts.tensor_convert_failed", err=str(e)[:200])
                continue
            audio_np = np.squeeze(audio_np)
            if audio_np.ndim != 1:
                audio_np = audio_np.reshape(-1)
            # Trim by audio_len if model exposes valid sample count.
            try:
                valid = int(audio_len) if audio_len is not None else audio_np.shape[0]
                audio_np = audio_np[:valid]
            except Exception:  # noqa: BLE001
                pass
            # Float32 [-1, 1] → int16 PCM
            audio_np = np.clip(audio_np, -1.0, 1.0)
            pcm16 = (audio_np * 32767.0).astype(np.int16).tobytes()
            if not pcm16:
                continue
            output_emitter.push(pcm16)
            total_pcm_bytes += len(pcm16)
            if not first_push_logged:
                log.info(
                    "magpie_tts.first_push_ms",
                    ms=int((time.monotonic() - t0) * 1000),
                    chunk_index=i,
                )
                first_push_logged = True

        output_emitter.flush()
        log.info(
            "magpie_tts.flush",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            pcm_bytes=total_pcm_bytes,
            audio_seconds=round(total_pcm_bytes / (SAMPLE_RATE * 2), 2),
            chunks=len(chunks),
        )
