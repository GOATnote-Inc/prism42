"""Parakeet ASR FastAPI server.

Contract matches agents/livekit/parakeet_stt.py:

  POST /transcribe  audio/wav  →  {"text","confidence","words":[{w,start_ms,end_ms}]}
        (legacy batch path — still used by any offline / fallback call)

  WS  /ws          WebSocket — TRUE bidirectional streaming.
        Client sends binary frames of PCM16 mono @ 16 kHz (any chunk
        size, server doesn't care; 20 ms / 640 bytes is recommended).
        Client sends text frame `{"type":"flush"}` to mark end-of-
        utterance (server emits a final and accepts more audio for
        the next utterance) or text frame `{"type":"close"}` /
        WebSocket close to end the session.
        Server sends text frames:
          {"type":"partial","text":"...","ms":123}
          {"type":"preflight","text":"...","ms":234}
          {"type":"final","text":"...","ms":456,"confidence":0.92}

  POST /stream      application/octet-stream  (legacy SSE — deprecated)
        request body is a stream of 20 ms PCM16 frames @ 16 kHz mono.
        Response is text/event-stream. Use /ws instead — under HTTP/1.1
        the SSE response cannot flush in real time while the request
        body is still being written. /ws is the correct shape for
        bidirectional streaming over a single TCP connection.

  GET  /healthz                →  {"status":"ok","model":"...","sample_rate":16000}

Loads the NeMo ASR model once at startup. /ws accumulates a growing
float32 PCM buffer per utterance and transcribes the whole buffer
every INTERIM_INTERVAL_MS of audio. On client flush / disconnect,
a final transcribe pass emits the `final` event.

Why re-transcribe-the-growing-buffer instead of cache-aware chunked
streaming: parakeet-tdt-0.6b-v3 has `att_context_style: regular`
(i.e. NOT cache-aware — the cache-aware attribute is `chunked_limited`
only on the FastConformer-streaming checkpoints). B300 measured per-
transcribe of a 1.5 s buffer: ~19 ms. Re-encoding the prefix every
160 ms is cheap enough that we can ship without a custom cache-aware
pipeline, and the text is monotonic enough for LiveKit's preemptive
generation hook to fire on stable-prefix PREFLIGHT events.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.websockets import WebSocketState

MODEL_NAME = os.environ.get("MODEL", "nvidia/parakeet-tdt-0.6b-v3")
BIND = os.environ.get("BIND", "127.0.0.1")
PORT = int(os.environ.get("PORT", "9100"))

# How much audio we accumulate between interim transcribes. Default
# 160 ms = every 8 × 20 ms input frames. Trades interim-rate against
# GPU pressure.
INTERIM_INTERVAL_MS = int(os.environ.get("INTERIM_INTERVAL_MS", "160"))
# We cap the rolling buffer at this many seconds of audio. Longer
# utterances are still transcribed; the cap just prevents per-chunk
# latency from growing unboundedly on a stuck stream.
MAX_BUFFER_S = float(os.environ.get("PARAKEET_MAX_BUFFER_S", "15.0"))
SAMPLE_RATE = 16_000
BYTES_PER_FRAME = 640  # 20 ms @ 16 kHz PCM16 = 320 samples × 2 bytes
INTERIM_INTERVAL_BYTES = (INTERIM_INTERVAL_MS // 20) * BYTES_PER_FRAME

app = FastAPI(title="prism42-parakeet", version="0.2.0")
_MODEL = None
# One inference at a time per GPU — NeMo's transcribe isn't reentrant-
# safe on a single model instance. Held for the duration of each
# transcribe call (not across the whole stream).
_MODEL_LOCK = asyncio.Lock()


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    # Lazy import — keeps startup/health checks fast on cold container.
    import nemo.collections.asr as nemo_asr

    print(f"[parakeet] loading {MODEL_NAME} ...", flush=True)
    t0 = time.time()
    model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
    model.eval()
    if torch.cuda.is_available():
        model = model.to("cuda")
        print("[parakeet] moved model to cuda", flush=True)
    print(f"[parakeet] loaded in {time.time() - t0:.1f}s", flush=True)
    _MODEL = model
    return _MODEL


@app.on_event("startup")
async def _warm():
    try:
        model = _load_model()
        # Cold-start transcribe: 1 s of silence. Amortizes NeMo's
        # lazy-init on the first real request.
        pcm = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with torch.inference_mode():
            _ = model.transcribe([pcm], batch_size=1, verbose=False)
        print("[parakeet] warm-up transcribe complete", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[parakeet] model load failed at startup: {e}", flush=True)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok" if _MODEL is not None else "loading",
        "model": MODEL_NAME,
        "sample_rate": SAMPLE_RATE,
        "streaming": True,
        "interim_interval_ms": INTERIM_INTERVAL_MS,
    }


def _extract_text_score(hyps) -> tuple[str, float]:
    """Normalize a NeMo `transcribe` result into (text, confidence).

    NeMo returns either a list[str] or list[Hypothesis] depending on
    model + flags. We ask for `return_hypotheses=True` in the batch
    path, and plain transcribe (returns strings) in the stream path —
    the stream path does not need per-word alignments.
    """
    if not hyps:
        return "", 0.0
    h = hyps[0]
    if isinstance(h, str):
        return h, 0.9
    text = getattr(h, "text", "") or ""
    score = getattr(h, "score", None)
    if score is None:
        return text, 0.9
    try:
        conf = max(0.0, min(1.0, float(np.exp(score / max(1, len(text.split()))))))
    except Exception:  # noqa: BLE001
        conf = 0.9
    return text, conf


@app.post("/transcribe")
async def transcribe(req: Request):
    body = await req.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")
    model = _load_model()

    # Write WAV to a temp file (NeMo's transcribe() takes paths).
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
        f.write(body)
        f.flush()
        t0 = time.time()
        try:
            async with _MODEL_LOCK:
                hyps = model.transcribe([f.name], batch_size=1, return_hypotheses=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"asr error: {e}") from e
        dt_ms = int((time.time() - t0) * 1000)

    text, confidence = _extract_text_score(hyps)
    return JSONResponse(
        {"text": text, "confidence": confidence, "words": [], "latency_ms": dt_ms}
    )


@app.post("/stream")
async def stream(req: Request):
    """Streaming transcription.

    Request body: concatenated PCM16 frames @ 16 kHz mono. No framing
    header — the frame boundary is every 640 bytes. The client half-
    closes the body when the speaker finishes.

    Response: text/event-stream. One `data: {...}\\n\\n` chunk per
    interim + one final.
    """
    model = _load_model()

    async def event_gen():
        pcm_bytes = bytearray()
        since_last_interim = 0
        t0 = time.monotonic()
        last_text = ""

        async def _do_transcribe(final: bool):
            """Run transcribe on the current buffer, yield SSE line."""
            nonlocal last_text
            if len(pcm_bytes) < BYTES_PER_FRAME:
                return None
            pcm = np.frombuffer(bytes(pcm_bytes), dtype=np.int16).astype(np.float32) / 32768.0
            try:
                async with _MODEL_LOCK:
                    with torch.inference_mode():
                        if final:
                            hyps = model.transcribe(
                                [pcm],
                                batch_size=1,
                                return_hypotheses=True,
                                verbose=False,
                            )
                            text, conf = _extract_text_score(hyps)
                        else:
                            hyps = model.transcribe([pcm], batch_size=1, verbose=False)
                            text, conf = _extract_text_score(hyps)
            except Exception as e:  # noqa: BLE001
                return f"data: {json.dumps({'type':'error','err':str(e)[:200]})}\n\n"
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if final:
                payload = {
                    "type": "final",
                    "text": text,
                    "ms": elapsed_ms,
                    "confidence": conf,
                }
            elif text and text == last_text:
                # Stable-prefix — emit preflight so LiveKit's preemptive
                # generation hook fires (voice/audio_recognition.py:777
                # keys on SpeechEventType.PREFLIGHT_TRANSCRIPT).
                payload = {"type": "preflight", "text": text, "ms": elapsed_ms}
            else:
                payload = {"type": "partial", "text": text, "ms": elapsed_ms}
            last_text = text
            return f"data: {json.dumps(payload)}\n\n"

        try:
            async for chunk in req.stream():
                if not chunk:
                    continue
                pcm_bytes.extend(chunk)
                # Trim oldest audio if the buffer grew past MAX_BUFFER_S.
                max_bytes = int(MAX_BUFFER_S * SAMPLE_RATE * 2)
                if len(pcm_bytes) > max_bytes:
                    drop = len(pcm_bytes) - max_bytes
                    drop -= drop % BYTES_PER_FRAME
                    if drop > 0:
                        del pcm_bytes[:drop]
                since_last_interim += len(chunk)
                if since_last_interim >= INTERIM_INTERVAL_BYTES:
                    since_last_interim = 0
                    line = await _do_transcribe(final=False)
                    if line:
                        yield line
            # End-of-input — emit final.
            line = await _do_transcribe(final=True)
            if line:
                yield line
        except asyncio.CancelledError:
            # Client disconnected mid-stream.
            raise

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.websocket("/ws")
async def ws_stream(ws: WebSocket):
    """Bidirectional streaming transcription.

    Protocol per utterance:
      client -> binary PCM16 frames (any chunk size; server treats it
                as a continuous stream of int16 little-endian @ 16 kHz)
      client -> {"type":"flush"} text frame to mark end-of-utterance
      server -> {"type":"partial"|"preflight"|"final","text":...,"ms":...}
                text frames; emits a `final` after each flush, then
                resets buffer and is ready for the next utterance.

      client -> {"type":"close"} or close the WebSocket to end the
                session entirely.

    Sessions can carry multiple utterances back-to-back without
    reconnecting. This is the shape LiveKit's `RecognizeStream` wants:
    one stream per call session, FlushSentinel marks utterance end.
    """
    await ws.accept(subprotocol="prism42-parakeet-v1")
    model = _load_model()

    pcm_bytes = bytearray()
    bytes_since_interim = 0
    utterance_t0: float | None = None
    last_text = ""

    async def transcribe_buf(final: bool) -> dict | None:
        nonlocal last_text
        if len(pcm_bytes) < BYTES_PER_FRAME:
            return None
        pcm = np.frombuffer(bytes(pcm_bytes), dtype=np.int16).astype(np.float32) / 32768.0
        try:
            async with _MODEL_LOCK:
                with torch.inference_mode():
                    if final:
                        hyps = model.transcribe(
                            [pcm],
                            batch_size=1,
                            return_hypotheses=True,
                            verbose=False,
                        )
                    else:
                        hyps = model.transcribe([pcm], batch_size=1, verbose=False)
            text, conf = _extract_text_score(hyps)
        except Exception as e:  # noqa: BLE001
            return {"type": "error", "err": str(e)[:200]}
        elapsed_ms = (
            int((time.monotonic() - utterance_t0) * 1000)
            if utterance_t0 is not None
            else 0
        )
        if final:
            payload = {
                "type": "final",
                "text": text,
                "ms": elapsed_ms,
                "confidence": conf,
            }
        elif text and text == last_text:
            payload = {"type": "preflight", "text": text, "ms": elapsed_ms}
        else:
            payload = {"type": "partial", "text": text, "ms": elapsed_ms}
        last_text = text
        return payload

    async def reset_utterance() -> None:
        nonlocal pcm_bytes, bytes_since_interim, utterance_t0, last_text
        pcm_bytes = bytearray()
        bytes_since_interim = 0
        utterance_t0 = None
        last_text = ""

    try:
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                break
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break
            if mtype != "websocket.receive":
                continue

            if "bytes" in msg and msg["bytes"] is not None:
                data = msg["bytes"]
                if utterance_t0 is None:
                    utterance_t0 = time.monotonic()
                pcm_bytes.extend(data)
                # Cap buffer.
                max_bytes = int(MAX_BUFFER_S * SAMPLE_RATE * 2)
                if len(pcm_bytes) > max_bytes:
                    drop = len(pcm_bytes) - max_bytes
                    drop -= drop % BYTES_PER_FRAME
                    if drop > 0:
                        del pcm_bytes[:drop]
                bytes_since_interim += len(data)
                if bytes_since_interim >= INTERIM_INTERVAL_BYTES:
                    bytes_since_interim = 0
                    payload = await transcribe_buf(final=False)
                    if payload is not None:
                        await ws.send_json(payload)
                continue

            if "text" in msg and msg["text"] is not None:
                try:
                    ctrl = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                ctype = ctrl.get("type")
                if ctype == "flush":
                    payload = await transcribe_buf(final=True)
                    if payload is not None:
                        await ws.send_json(payload)
                    await reset_utterance()
                elif ctype == "close":
                    break
                # Other ctrl types ignored.
    except asyncio.CancelledError:
        raise
    finally:
        if ws.application_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    import uvicorn

    # ws="auto" picks websockets-the-package if installed, falls back
    # to wsproto. Either is fine for our protocol.
    uvicorn.run(app, host=BIND, port=PORT, log_level="info", ws="auto")
