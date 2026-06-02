#!/usr/bin/env bash
# swap_to_omni_h200.sh — replace the running vllm-nemotron container on
# warm-lavender-narwhal H200 with Nemotron-3-Nano-Omni-30B-A3B-Reasoning.
#
# DOUBLE-GATED. Refuses to run unless BOTH signals are set:
#   --commit                      on the command line
#   PRISM42_OMNI_SWAP=1           in the environment
#
# Either alone stays dry-run (prints what it would do, exits 0).
# Both = destructive op on shared infra: stops the existing container.
#
# Backout is one command on the same pod:
#   ssh warm-lavender-narwhal 'docker stop vllm-nemotron-omni && docker start vllm-nemotron'
#
# Run from laptop. ssh access to warm-lavender-narwhal required.
# See findings/research/2026-04-28-nemotron-omni/brief.md before running.

set -uo pipefail

POD="${POD:-warm-lavender-narwhal}"
QUANT="${QUANT:-NVFP4}"            # NVFP4 | FP8 | BF16
NEW_MODEL_ID="nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-${QUANT}"
NEW_CONTAINER="vllm-nemotron-omni"
OLD_CONTAINER="vllm-nemotron"
VLLM_TAG="${VLLM_TAG:-v0.20.0}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.85}"

COMMIT_FLAG=0
for arg in "$@"; do
  [[ "$arg" == "--commit" ]] && COMMIT_FLAG=1
done

PRISM42_OMNI_SWAP_VAL="${PRISM42_OMNI_SWAP:-0}"

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

cat <<EOF
=== Nemotron-3-Nano-Omni swap on $POD ===
  old container : $OLD_CONTAINER  (kept stopped, not removed; backout = docker start)
  new container : $NEW_CONTAINER
  model         : $NEW_MODEL_ID
  vLLM image    : vllm/vllm-openai:$VLLM_TAG
  max-model-len : $MAX_MODEL_LEN
  gpu-mem-util  : $GPU_MEM_UTIL
  HF_TOKEN      : ${HF_TOKEN:+set (length: ${#HF_TOKEN})} ${HF_TOKEN:-NOT SET}
EOF
echo

if [[ -z "${HF_TOKEN:-}" ]]; then
  red "FAIL: HF_TOKEN not set; Omni weights are gated. Source .env first."
  exit 2
fi

if [[ "$COMMIT_FLAG" -eq 0 || "$PRISM42_OMNI_SWAP_VAL" != "1" ]]; then
  yellow "DRY RUN (gates not met)."
  yellow "Both required: --commit on the command line AND PRISM42_OMNI_SWAP=1 in env."
  yellow "Currently:  --commit=$COMMIT_FLAG   PRISM42_OMNI_SWAP=$PRISM42_OMNI_SWAP_VAL"
  echo
  echo "Would execute on $POD:"
  echo "  docker stop $OLD_CONTAINER"
  echo "  docker pull vllm/vllm-openai:$VLLM_TAG"
  echo "  docker run -d --name $NEW_CONTAINER \\"
  echo "    --gpus all --shm-size=16g \\"
  echo "    -e HF_TOKEN=<redacted> \\"
  echo "    -p 127.0.0.1:8000:8000 \\"
  echo "    -v /opt/prism42-nemotron-med/hf_cache:/root/.cache/huggingface \\"
  echo "    vllm/vllm-openai:$VLLM_TAG \\"
  echo "    --model $NEW_MODEL_ID \\"
  echo "    --hf-overrides='{\"architectures\":[\"NemotronH_Nano_VL_V2\"]}' \\"
  echo "    --trust-remote-code \\"
  echo "    --max-model-len $MAX_MODEL_LEN \\"
  echo "    --gpu-memory-utilization $GPU_MEM_UTIL"
  exit 0
fi

# ==========================================================================
# COMMITTED PATH — destructive op begins here
# ==========================================================================
green "GATES MET — proceeding with destructive swap on $POD."
echo

ssh -o BatchMode=yes "$POD" bash -s <<EOF
set -uo pipefail
echo "=== pre-swap state ==="
docker ps --filter name=$OLD_CONTAINER --format "{{.Names}} {{.Status}}"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

echo
echo "=== stop old container (kept, not removed; rollback ready) ==="
docker stop $OLD_CONTAINER || true

echo
echo "=== pull new image: vllm/vllm-openai:$VLLM_TAG ==="
docker pull vllm/vllm-openai:$VLLM_TAG

echo
echo "=== launch Omni container ==="
mkdir -p /opt/prism42-nemotron-med/hf_cache
docker run -d --name $NEW_CONTAINER \
  --gpus all --shm-size=16g \
  -e HF_TOKEN="$HF_TOKEN" \
  -p 127.0.0.1:8000:8000 \
  -v /opt/prism42-nemotron-med/hf_cache:/root/.cache/huggingface \
  vllm/vllm-openai:$VLLM_TAG \
  --model $NEW_MODEL_ID \
  --hf-overrides='{"architectures":["NemotronH_Nano_VL_V2"]}' \
  --trust-remote-code \
  --max-model-len $MAX_MODEL_LEN \
  --gpu-memory-utilization $GPU_MEM_UTIL

echo
echo "=== wait for /v1/models (cold start ~12-18 min) ==="
for i in \$(seq 1 30); do
  sleep 60
  if curl -sf http://127.0.0.1:8000/v1/models >/dev/null; then
    echo "Omni up at \${i}-min mark"
    curl -s http://127.0.0.1:8000/v1/models | head -50
    exit 0
  fi
done
echo "FAIL: Omni did not become ready in 30 min"
docker logs $NEW_CONTAINER 2>&1 | tail -50
echo
echo "Backout suggestion:"
echo "  docker stop $NEW_CONTAINER && docker start $OLD_CONTAINER"
exit 1
EOF
