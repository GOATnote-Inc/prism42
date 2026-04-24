# Parakeet ASR service for prism42.
#
# Wraps NVIDIA NeMo's Parakeet model in a FastAPI server that exposes
# both POST /transcribe (WAV in → JSON out, batch) and a WebSocket at
# WS /ws (bidirectional streaming) at http://127.0.0.1:9100. The /ws
# endpoint requires `uvicorn[standard]` (pulls in `websockets` for
# the WS protocol stack) — see install line below.
#
# Model: nvidia/parakeet-tdt-0.6b-v3 by default; override via the
# MODEL env var. Weights auto-downloaded to /models on first boot.
#
# Base: NVIDIA's NeMo container, which already has CUDA / PyTorch /
# cuDNN / NeMo pinned to a known-good trio. This is the path of
# least resistance — we don't fight dependency hell.
#
# 25.09 (not 25.02) is required for B300: sm_103 compiler targets
# landed in CUDA 12.9 (NVIDIA CUDA 12.9 release notes: "CUDA Toolkit
# 12.9 adds compiler target support for SM architecture 10.3
# (sm_103, sm_103f, sm_103a) ..."). NeMo 25.09 ships CUDA 12.9.1 /
# PyTorch 2.8.0a0. NeMo 25.02 predates CUDA 12.9 and will silently
# emit "no kernel image is available" on a B300 rebuild — see
# docs/livekit-kb/12-parakeet-stt-component.md §4 for the warning.
# References:
#   https://catalog.ngc.nvidia.com/orgs/nvidia/containers/nemo
#   https://docs.nvidia.com/nemo-framework/user-guide/latest/softwarecomponentversions.html
#   https://docs.nvidia.com/cuda/archive/12.9.0/cuda-toolkit-release-notes/
#   https://docs.nvidia.com/cuda/blackwell-compatibility-guide/ (13.2)
#   https://github.com/pytorch/pytorch/issues/159779

FROM nvcr.io/nvidia/nemo:25.09

WORKDIR /app

# Arch list covers Ampere (A100/A40), Ada (L40), Hopper (H100),
# Blackwell datacentre (B200 sm_100, B300 sm_103), and Blackwell
# GeForce (sm_120/sm_121) with +PTX fallback for forward-compat.
# Needed whenever a pip install inside this image compiles CUDA
# kernels from source (e.g. flash-attn, torch-scatter). See
# CLAUDE.md "Recent best-practice synthesis" → B300 section.
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0 10.0 10.3 12.0 12.1+PTX"

# FastAPI + uvicorn + multipart form handling (for audio uploads).
RUN pip install --no-cache-dir \
    fastapi==0.115.* \
    uvicorn[standard]==0.32.* \
    python-multipart==0.0.12

COPY server.py /app/server.py

# Port convention (prism42-wide): 9100 ASR, 9200 TTS.
EXPOSE 9100

CMD ["python", "server.py"]
