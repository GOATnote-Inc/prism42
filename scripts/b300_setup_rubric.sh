#!/usr/bin/env bash
# Idempotent setup of a vLLM-served Llama-3-70B (bf16 on B300; NVFP4 if
# a quantized checkpoint is available) on the prism-mla-b300-h4h5 pod.
#
# Invocation:
#   brev copy scripts/b300_setup_rubric.sh prism-mla-b300-h4h5:/tmp/
#   brev exec prism-mla-b300-h4h5 -- bash /tmp/b300_setup_rubric.sh
#
# Expected outcome: vLLM OpenAI-compatible endpoint on 0.0.0.0:8000.
# The host side then:
#   brev port-forward prism-mla-b300-h4h5 --port=8000:8000
#   export PRISM42_B300_RUBRIC_URL=http://localhost:8000/v1/chat/completions

set -euo pipefail

PORT="${PRISM42_B300_RUBRIC_PORT:-8000}"
# Default to Qwen2.5-72B-Instruct — ungated on HF, no auth token needed,
# fits on a single B300 in bf16 (~144 GB of 275 GB HBM3e). Quality is
# competitive with Llama-3-70B for instruction-following / JSON-output
# tasks (the rubric grader's specific ask). Override to
# meta-llama/Meta-Llama-3-70B-Instruct with PRISM42_B300_RUBRIC_MODEL
# if HF_TOKEN is available.
MODEL="${PRISM42_B300_RUBRIC_MODEL:-Qwen/Qwen2.5-72B-Instruct}"
SERVED_NAME="${PRISM42_B300_RUBRIC_SERVED_NAME:-local_llama70b_nvfp4}"

# preflight
echo "[b300-rubric] host: $(hostname)"
nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv | head -3
/usr/local/cuda/bin/nvcc --version | tail -1 || true
echo "[b300-rubric] python: $(python3 --version)"

# venv
WORKDIR="${HOME}/workspace/prism-rubric"
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# deps
pip install --quiet --upgrade pip
pip install --quiet "vllm==0.14.1" "torch>=2.6" "huggingface-hub>=0.26" "ninja"

# blackwell FP4 MoE per vLLM GB300 DeepSeek blog reference
export VLLM_USE_FLASHINFER_MOE_FP4=1

# HF auth if token provided
if [[ -n "${HF_TOKEN:-}" ]]; then
  python3 -c "from huggingface_hub import login; login(token='${HF_TOKEN}')" || true
fi

# short-circuit if already up
if curl -s --max-time 2 "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
  echo "[b300-rubric] already serving on :${PORT} — leaving it alone"
  curl -s "http://127.0.0.1:${PORT}/v1/models"
  exit 0
fi

mkdir -p logs
LOG="${WORKDIR}/logs/vllm-$(date +%Y%m%dT%H%M%SZ).log"
echo "[b300-rubric] starting vLLM — log: ${LOG}"

nohup vllm serve "${MODEL}" \
  --served-model-name "${SERVED_NAME}" \
  --port "${PORT}" \
  --host 0.0.0.0 \
  --tensor-parallel-size 1 \
  --max-model-len 8192 \
  --dtype bfloat16 \
  > "${LOG}" 2>&1 &

echo "[b300-rubric] vllm pid: $!"
for i in $(seq 1 90); do
  if curl -s --max-time 2 "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
    echo "[b300-rubric] healthy after ${i} polls (~${i}s)"
    curl -s "http://127.0.0.1:${PORT}/v1/models"
    exit 0
  fi
  sleep 2
done

echo "[b300-rubric] FAILED to become healthy — tail of log:"
tail -60 "${LOG}"
exit 1
