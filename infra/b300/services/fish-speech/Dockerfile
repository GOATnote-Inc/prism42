# Fish Speech S2 Pro TTS service for prism42.
#
# Wraps fishaudio/fish-speech-s2-pro on the SGLang inference backend
# in a FastAPI server that streams PCM16 chunks at 24 kHz mono via
# POST /tts on 127.0.0.1:9200.
#
# Rationale (user 2026-04-23): beats ElevenLabs on 2 of 3 major
# quality benchmarks; ~100 ms TTFA on H200, faster on B300. SGLang
# backend gives us kernel-co-design leverage downstream.
#
# Model weights auto-download to /models/hf on first run; docker-
# compose mounts /opt/prism42/models as /models.

FROM nvcr.io/nvidia/pytorch:25.02-py3

WORKDIR /app

# Fish Speech + SGLang. Pins held against the versions verified
# against S2 Pro as of 2026-04-23; bump with care.
RUN pip install --no-cache-dir \
    "fish-speech[sglang]>=1.4.0" \
    "sglang>=0.4.0" \
    fastapi==0.115.* \
    uvicorn[standard]==0.32.* \
    numpy==1.26.*

COPY server.py /app/server.py

EXPOSE 9200

CMD ["python", "server.py"]
