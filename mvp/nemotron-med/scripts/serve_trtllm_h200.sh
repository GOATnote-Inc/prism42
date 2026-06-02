#!/usr/bin/env bash
# serve_trtllm_h200.sh — sovereign serve of Llama-3.1-Nemotron-70B-Instruct
# on the warm-lavender-narwhal H200 pod via TensorRT-LLM + Triton.
#
# Strategy:
#   1. Try NIM (one-flag deploy with fp8 already wired)
#   2. If NIM unavailable / not yet released, fall back to NGC tritonserver
#      with a hand-built fp8 engine via ModelOpt + trtllm-build.
#
# Run ON the pod (after scp'ing this file there). Reads HF_TOKEN + NGC_API_KEY
# from env. Listens on localhost:8000 (no public ingress — ssh tunnel only).
#
# Usage on laptop:
#   scp -i ~/.brev/brev.pem scripts/serve_trtllm_h200.sh warm-lavender-narwhal:~/
#   ssh warm-lavender-narwhal 'HF_TOKEN=hf_xxx NGC_API_KEY=nvapi_xxx bash serve_trtllm_h200.sh'

set -euo pipefail

MODEL_ID="${MODEL_ID:-nvidia/Llama-3.1-Nemotron-70B-Instruct-HF}"
SERVE_PORT="${SERVE_PORT:-8000}"
ENGINE_DIR="${ENGINE_DIR:-/opt/prism42-nemotron-med/engines/llama31-nemotron-70b-fp8}"
NIM_IMAGE="${NIM_IMAGE:-nvcr.io/nim/nvidia/llama-3.1-nemotron-70b-instruct:latest}"
TRITON_IMAGE="${TRITON_IMAGE:-nvcr.io/nvidia/tritonserver:24.10-trtllm-python-py3}"

: "${HF_TOKEN:?HF_TOKEN must be set}"
: "${NGC_API_KEY:?NGC_API_KEY must be set}"

log() { printf "[serve_trtllm_h200] %s\n" "$*" >&2; }

require() {
  command -v "$1" >/dev/null 2>&1 || { log "missing required tool: $1"; exit 2; }
}

require docker
require nvidia-smi

log "GPU before serve:"
nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total --format=csv,noheader

# ---------------------------------------------------------------------------
# Login to NGC registry
# ---------------------------------------------------------------------------
log "logging in to NGC..."
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin

# ---------------------------------------------------------------------------
# Path A — NIM (preferred)
# ---------------------------------------------------------------------------
log "trying NIM image: $NIM_IMAGE"
if docker pull "$NIM_IMAGE" 2>&1 | tee /tmp/nim_pull.log; then
  log "NIM available; launching..."
  mkdir -p "$ENGINE_DIR"
  docker run --rm -d \
    --name prism42-nemotron-serve \
    --gpus all \
    --shm-size=16g \
    -e HF_TOKEN="$HF_TOKEN" \
    -e NIM_MODEL_NAME="$MODEL_ID" \
    -e NIM_LOG_LEVEL=INFO \
    -p "127.0.0.1:${SERVE_PORT}:8000" \
    -v "$ENGINE_DIR:/opt/nim/cache" \
    "$NIM_IMAGE"
  log "NIM container started; waiting for /v1/models to respond..."
  for i in $(seq 1 60); do
    sleep 10
    if curl -sf "http://127.0.0.1:${SERVE_PORT}/v1/models" >/dev/null; then
      log "NIM up at http://127.0.0.1:${SERVE_PORT}/v1 after ${i}0s"
      curl -s "http://127.0.0.1:${SERVE_PORT}/v1/models" | head -50
      exit 0
    fi
  done
  log "NIM did not become healthy in 600s; tearing down and falling through"
  docker logs prism42-nemotron-serve 2>&1 | tail -50 || true
  docker rm -f prism42-nemotron-serve || true
fi

# ---------------------------------------------------------------------------
# Path B — Hand-built TRT-LLM (fallback)
# ---------------------------------------------------------------------------
log "falling back to NGC tritonserver + hand-built fp8 engine"
log "pulling $TRITON_IMAGE (this is large; may take 5-10 min first time)"
docker pull "$TRITON_IMAGE"

if [[ ! -f "$ENGINE_DIR/rank0.engine" ]]; then
  log "building fp8 engine via ModelOpt + trtllm-build (one-time, ~30-90 min)"
  bash "$(dirname "$0")/build_trtllm_engine.sh"
else
  log "reusing cached engine at $ENGINE_DIR"
fi

# Triton model repository scaffold
MODEL_REPO=/opt/prism42-nemotron-med/triton_repo
mkdir -p "$MODEL_REPO/llama31-nemotron-70b-fp8/1"
cp -p "$ENGINE_DIR"/* "$MODEL_REPO/llama31-nemotron-70b-fp8/1/"

cat > "$MODEL_REPO/llama31-nemotron-70b-fp8/config.pbtxt" <<EOF
backend: "tensorrtllm"
max_batch_size: 8
model_transaction_policy { decoupled: true }
input  [ { name: "input_ids" data_type: TYPE_INT32 dims: [ -1 ] } ]
output [ { name: "output_ids" data_type: TYPE_INT32 dims: [ -1, -1 ] } ]
parameters { key: "FORCE_CPU_ONLY_INPUT_TENSORS" value { string_value: "no" } }
parameters { key: "gpt_model_path" value { string_value: "$ENGINE_DIR" } }
parameters { key: "use_paged_context_fmha" value { string_value: "true" } }
EOF

log "starting tritonserver on :${SERVE_PORT}"
docker run --rm -d \
  --name prism42-nemotron-serve \
  --gpus all \
  --shm-size=16g \
  -p "127.0.0.1:${SERVE_PORT}:8000" \
  -p "127.0.0.1:8002:8002" \
  -v "$MODEL_REPO:/models" \
  "$TRITON_IMAGE" \
  tritonserver \
    --model-repository=/models \
    --log-verbose=1 \
    --strict-model-config=false

log "waiting for /v2/health/ready..."
for i in $(seq 1 60); do
  sleep 10
  if curl -sf "http://127.0.0.1:${SERVE_PORT}/v2/health/ready" >/dev/null; then
    log "Triton up at http://127.0.0.1:${SERVE_PORT} after ${i}0s"
    curl -s "http://127.0.0.1:${SERVE_PORT}/v2/models" | head -100
    exit 0
  fi
done

log "FAIL: Triton did not become ready in 600s"
docker logs prism42-nemotron-serve 2>&1 | tail -100
exit 1
