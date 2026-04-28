#!/usr/bin/env bash
# serve_judge_h100.sh — sovereign judge stack on prism-mla-h100 (Hyperstack
# Montreal-canada-2). Distinct from the voice-freeze H100 in public-repo
# deployment ledger.
#
# Two services:
#   - Llama-3.1-Nemotron-70B-Reward-HF on :8001 via FastAPI shim (transformers
#     AutoModelForSequenceClassification — Reward heads aren't standard Triton)
#   - Llama-3.1-Nemotron-70B-Instruct-HF (AWQ-int4) on :8000 for rubric grading
#
# 80 GiB H100 with both: Reward (~70 GB fp16 -> 35 GB awq-int4 also viable) +
# Instruct AWQ-int4 (~35 GB) does NOT both fit. So this script picks ONE based
# on JUDGE_MODE env:
#
#   JUDGE_MODE=reward    serve only the Reward model (default)
#   JUDGE_MODE=rubric    serve only the AWQ-int4 Instruct model
#   JUDGE_MODE=both      tries both but will likely OOM (kept for testing)
#
# Run on the prism-mla-h100 pod after scp.

set -euo pipefail

JUDGE_MODE="${JUDGE_MODE:-reward}"
REWARD_MODEL_ID="${REWARD_MODEL_ID:-nvidia/Llama-3.1-Nemotron-70B-Reward-HF}"
RUBRIC_MODEL_ID="${RUBRIC_MODEL_ID:-hugging-quants/Llama-3.1-Nemotron-70B-Instruct-AWQ-INT4}"
REWARD_PORT="${REWARD_PORT:-8001}"
RUBRIC_PORT="${RUBRIC_PORT:-8000}"

: "${HF_TOKEN:?HF_TOKEN must be set}"

log() { printf "[serve_judge_h100] %s\n" "$*" >&2; }

require() { command -v "$1" >/dev/null 2>&1 || { log "missing $1"; exit 2; }; }
require docker
require nvidia-smi

log "GPU before judge serve:"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader

# ---------------------------------------------------------------------------
# Reward model — FastAPI shim (transformers, not Triton)
# ---------------------------------------------------------------------------
serve_reward() {
  log "starting Llama-3.1-Nemotron-70B-Reward FastAPI shim on :$REWARD_PORT"
  mkdir -p /opt/prism42-nemotron-med/judge
  # Materialize the shim script if absent
  cat > /opt/prism42-nemotron-med/judge/reward_shim.py <<'PYEOF'
"""Tiny FastAPI shim wrapping the Llama-3.1-Nemotron-70B-Reward model.

POST /score  body: {"prompt": "...", "response": "..."}  -> {"reward": float}

Reward models output a scalar; we expose it as-is. The healthbench grader
bridge converts this into a rubric pass/fail by thresholding (configurable
in mla/judges/triton_judge.py).
"""
from __future__ import annotations

import os

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_ID = os.environ.get("REWARD_MODEL_ID", "nvidia/Llama-3.1-Nemotron-70B-Reward-HF")

app = FastAPI()

print(f"loading {MODEL_ID} ...", flush=True)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=os.environ["HF_TOKEN"])
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.bfloat16,
    device_map="auto",
    token=os.environ["HF_TOKEN"],
)
model.eval()
print("loaded", flush=True)


class ScoreRequest(BaseModel):
    prompt: str
    response: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_ID}


@app.post("/score")
def score(req: ScoreRequest) -> dict:
    text = (
        f"<|start_header_id|>user<|end_header_id|>\n\n{req.prompt}<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\n{req.response}<|eot_id|>"
    )
    with torch.inference_mode():
        toks = tokenizer(text, return_tensors="pt", truncation=True, max_length=8192).to(model.device)
        out = model(**toks)
    return {"reward": float(out.logits.squeeze().item())}
PYEOF

  docker run --rm -d \
    --name prism42-judge-reward \
    --gpus all \
    --shm-size=8g \
    -e HF_TOKEN="$HF_TOKEN" \
    -e REWARD_MODEL_ID="$REWARD_MODEL_ID" \
    -p "127.0.0.1:${REWARD_PORT}:${REWARD_PORT}" \
    -v /opt/prism42-nemotron-med/judge:/judge \
    -v /opt/prism42-nemotron-med/hf_cache:/root/.cache/huggingface \
    nvcr.io/nvidia/pytorch:24.10-py3 \
    bash -c "pip install --quiet fastapi uvicorn pydantic && cd /judge && uvicorn reward_shim:app --host 0.0.0.0 --port ${REWARD_PORT}"

  for i in $(seq 1 90); do
    sleep 10
    if curl -sf "http://127.0.0.1:${REWARD_PORT}/health" >/dev/null; then
      log "Reward judge up at :$REWARD_PORT after ${i}0s"
      return 0
    fi
  done
  log "FAIL: Reward judge not ready in 900s"
  docker logs prism42-judge-reward 2>&1 | tail -50
  return 1
}

# ---------------------------------------------------------------------------
# Rubric grader — vLLM serving AWQ-int4 Llama-3.1-Nemotron-70B-Instruct
# ---------------------------------------------------------------------------
serve_rubric() {
  log "starting Llama-3.1-Nemotron-70B-Instruct (AWQ-int4) on :$RUBRIC_PORT"
  docker run --rm -d \
    --name prism42-judge-rubric \
    --gpus all \
    --shm-size=8g \
    -e HF_TOKEN="$HF_TOKEN" \
    -p "127.0.0.1:${RUBRIC_PORT}:8000" \
    -v /opt/prism42-nemotron-med/hf_cache:/root/.cache/huggingface \
    vllm/vllm-openai:v0.6.6 \
    --model "$RUBRIC_MODEL_ID" \
    --quantization awq \
    --dtype float16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.85

  for i in $(seq 1 60); do
    sleep 10
    if curl -sf "http://127.0.0.1:${RUBRIC_PORT}/v1/models" >/dev/null; then
      log "Rubric judge up at :$RUBRIC_PORT after ${i}0s"
      return 0
    fi
  done
  log "FAIL: Rubric judge not ready in 600s"
  docker logs prism42-judge-rubric 2>&1 | tail -50
  return 1
}

case "$JUDGE_MODE" in
  reward)
    serve_reward
    ;;
  rubric)
    serve_rubric
    ;;
  both)
    log "WARNING: 'both' mode will likely OOM on H100 80GiB; this exists only for benchmarking."
    serve_reward && serve_rubric
    ;;
  *)
    log "unknown JUDGE_MODE=$JUDGE_MODE (reward|rubric|both)"
    exit 2
    ;;
esac

log "judge stack ready (mode=$JUDGE_MODE)"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
