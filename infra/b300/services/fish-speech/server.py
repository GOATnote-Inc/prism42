"""Fish Speech S2 Pro TTS FastAPI server on SGLang.

Contract matches agents/livekit/fish_speech_tts.py:
  POST /tts  {"text","voice_id","speed","format","sample_rate",
              "stream","chunk_samples"}
       → chunked PCM16 response (24 kHz mono by default)
  GET  /healthz  → {"status","model","sample_rate","backend"}

Model weights auto-download to /models/hf on first boot. The SGLang
backend co-locates TTS decoding with the GPU residency of the LLM
(Phase 3b when vLLM lands on the same pod), so we pay one warmup
cost for the whole stack.

TODO Phase 3b:
  - Voice cloning endpoint (/voices/create) gated by SP-002 scope;
    healthcare posture: keep presets only for public demo
  - Custom CUDA decoder hook for the S2-Pro VQ codebook
"""
from __future__ import annotations

import os
import time

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

MODEL_NAME = os.environ.get("MODEL", "fishaudio/s2-pro")
BACKEND = os.environ.get("BACKEND", "sglang")
BIND = os.environ.get("BIND", "127.0.0.1")
PORT = int(os.environ.get("PORT", "9200"))
DEFAULT_SR = 24_000

app = FastAPI(title="prism42-fish-speech", version="0.1.0")
_ENGINE = None


def _load_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    print(f"[fish-speech] loading {MODEL_NAME} via {BACKEND} ...", flush=True)
    t0 = time.time()
    # Lazy import so /healthz responds even before the engine warms.
    from fish_speech.inference import InferenceEngine  # type: ignore[import-not-found]

    engine = InferenceEngine(
        model=MODEL_NAME,
        backend=BACKEND,
        device="cuda",
    )
    print(f"[fish-speech] loaded in {time.time() - t0:.1f}s", flush=True)
    _ENGINE = engine
    return _ENGINE


class TTSRequest(BaseModel):
    text: str
    voice_id: str = "default"
    speed: float = 1.0
    format: str = "pcm16"
    sample_rate: int = DEFAULT_SR
    stream: bool = True
    chunk_samples: int = 2880  # 120 ms @ 24 kHz


@app.on_event("startup")
async def _warm():
    try:
        _load_engine()
    except Exception as e:  # noqa: BLE001
        print(f"[fish-speech] engine load failed at startup: {e}", flush=True)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok" if _ENGINE is not None else "loading",
        "model": MODEL_NAME,
        "sample_rate": DEFAULT_SR,
        "backend": BACKEND,
    }


@app.post("/tts")
async def tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    if req.format != "pcm16":
        raise HTTPException(status_code=400, detail="only pcm16 is implemented")
    if req.sample_rate != DEFAULT_SR:
        raise HTTPException(
            status_code=400,
            detail=f"only {DEFAULT_SR} Hz is implemented in Phase 3a",
        )

    engine = _load_engine()

    async def gen():
        # Each chunk is an int16 numpy array yielded by the SGLang
        # backend. We forward raw bytes. Total TTFA target on B300:
        # ≤ 80 ms per the user's spec (100 ms on H200 baseline).
        for chunk in engine.stream_tts(
            text=req.text,
            voice=req.voice_id,
            speed=req.speed,
            sample_rate=req.sample_rate,
            chunk_samples=req.chunk_samples,
        ):
            if isinstance(chunk, np.ndarray):
                yield chunk.astype(np.int16).tobytes()
            elif isinstance(chunk, (bytes, bytearray)):
                yield bytes(chunk)
            else:
                continue

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={
            "X-Accel-Buffering": "no",
            "X-Prism42-Sample-Rate": str(DEFAULT_SR),
            "X-Prism42-Channels": "1",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=BIND, port=PORT, log_level="info")
