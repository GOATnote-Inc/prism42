# Parakeet ASR service for prism42.
#
# Wraps NVIDIA NeMo's Parakeet model in a FastAPI server that exposes
# POST /transcribe (WAV in → JSON out) at http://127.0.0.1:9100.
#
# Model: nvidia/parakeet-tdt-0.6b-v3 by default; override via the
# MODEL env var. Weights auto-downloaded to /models on first boot.
#
# Base: NVIDIA's NeMo container, which already has CUDA / PyTorch /
# cuDNN / NeMo pinned to a known-good trio. This is the path of
# least resistance — we don't fight dependency hell.

FROM nvcr.io/nvidia/nemo:25.02

WORKDIR /app

# FastAPI + uvicorn + multipart form handling (for audio uploads).
RUN pip install --no-cache-dir \
    fastapi==0.115.* \
    uvicorn[standard]==0.32.* \
    python-multipart==0.0.12

COPY server.py /app/server.py

# Port convention (prism42-wide): 9100 ASR, 9200 TTS.
EXPOSE 9100

CMD ["python", "server.py"]
