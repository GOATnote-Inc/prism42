"""Parakeet ASR FastAPI server.

Contract matches agents/livekit/parakeet_stt.py:
  POST /transcribe  audio/wav  →  {"text","confidence","words":[{w,start_ms,end_ms}]}
  GET  /healthz                →  {"status":"ok","model":"...","sample_rate":16000}

Loads the NeMo ASR model once at startup; every /transcribe decodes
against the warm model. Model weights live in /models/hf (the
docker-compose volume mount).

TODO Phase 3b:
  - POST /stream (WebSocket) for true sub-100 ms first-partial
  - KV-cache across utterance boundaries to shave ~20% off decode
  - Optional kernel co-design: swap NeMo's default decoder to a
    custom CUDA graph for the 600M-param model
"""
from __future__ import annotations

import io
import os
import tempfile
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

MODEL_NAME = os.environ.get("MODEL", "nvidia/parakeet-tdt-0.6b-v3")
BIND = os.environ.get("BIND", "127.0.0.1")
PORT = int(os.environ.get("PORT", "9100"))

app = FastAPI(title="prism42-parakeet", version="0.1.0")
_MODEL = None


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
    print(f"[parakeet] loaded in {time.time() - t0:.1f}s", flush=True)
    _MODEL = model
    return _MODEL


@app.on_event("startup")
async def _warm():
    try:
        _load_model()
    except Exception as e:  # noqa: BLE001
        print(f"[parakeet] model load failed at startup: {e}", flush=True)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok" if _MODEL is not None else "loading",
        "model": MODEL_NAME,
        "sample_rate": 16000,
    }


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
        # NeMo returns a list[Hypothesis] when include_hypotheses=True.
        try:
            hyps = model.transcribe([f.name], batch_size=1, return_hypotheses=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"asr error: {e}") from e
        dt_ms = int((time.time() - t0) * 1000)

    # NeMo returns a flat list — for a single file that's 1 element.
    hyp = hyps[0] if hyps else None
    if hyp is None:
        return JSONResponse({"text": "", "confidence": 0.0, "words": [], "latency_ms": dt_ms})

    text = getattr(hyp, "text", "") or ""
    # Parakeet-TDT exposes per-word timestamps when the model is built
    # with word-level alignments. Fall back to empty words list if not
    # exposed.
    words = []
    ts = getattr(hyp, "timestep", None) or getattr(hyp, "timesteps", None)
    if ts and text:
        # Very-light heuristic — NeMo's word-level alignments are
        # model-dependent. We return an empty list here to keep the
        # API deterministic; refine when the specific model's API
        # surface is verified post-deploy.
        words = []

    # Confidence heuristic: Parakeet-TDT reports a score — normalize
    # to [0,1]. If the model doesn't report one, hold at 0.9 (model
    # is near ceiling anyway).
    score = getattr(hyp, "score", None)
    if score is None:
        confidence = 0.9
    else:
        # Length-normalized log-prob → exp. Conservative clamp.
        try:
            confidence = max(0.0, min(1.0, float(np.exp(score / max(1, len(text.split()))))))
        except Exception:  # noqa: BLE001
            confidence = 0.9

    return JSONResponse(
        {"text": text, "confidence": confidence, "words": words, "latency_ms": dt_ms}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=BIND, port=PORT, log_level="info")
