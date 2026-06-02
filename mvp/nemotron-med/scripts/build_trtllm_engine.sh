#!/usr/bin/env bash
# build_trtllm_engine.sh — quantize Llama-3.1-Nemotron-70B-Instruct to fp8 and
# build a TensorRT-LLM engine. Hopper-native (sm_90); fits H200 141 GiB with
# headroom for KV at 8k context.
#
# Run on the H200 pod inside the tritonserver:24.10-trtllm-python-py3 container,
# or in a venv with tensorrt-llm + nvidia-modelopt installed.
#
# One-time cost: ~30-90 min on H200 first build. Engine is cached and reused.

set -euo pipefail

MODEL_ID="${MODEL_ID:-nvidia/Llama-3.1-Nemotron-70B-Instruct-HF}"
HF_CACHE="${HF_CACHE:-/opt/prism42-nemotron-med/hf_cache}"
QUANT_DIR="${QUANT_DIR:-/opt/prism42-nemotron-med/checkpoints/llama31-nemotron-70b-fp8}"
ENGINE_DIR="${ENGINE_DIR:-/opt/prism42-nemotron-med/engines/llama31-nemotron-70b-fp8}"
MAX_INPUT_LEN="${MAX_INPUT_LEN:-7168}"
MAX_OUTPUT_LEN="${MAX_OUTPUT_LEN:-1024}"
MAX_BATCH_SIZE="${MAX_BATCH_SIZE:-8}"
MAX_NUM_TOKENS="${MAX_NUM_TOKENS:-8192}"

: "${HF_TOKEN:?HF_TOKEN must be set}"

log() { printf "[build_trtllm_engine] %s\n" "$*" >&2; }

mkdir -p "$HF_CACHE" "$QUANT_DIR" "$ENGINE_DIR"

log "downloading $MODEL_ID to $HF_CACHE (one-time)"
HF_TOKEN="$HF_TOKEN" huggingface-cli download "$MODEL_ID" \
  --local-dir "$HF_CACHE/$(basename "$MODEL_ID")" \
  --local-dir-use-symlinks False

log "fp8 quantization via ModelOpt"
python -m modelopt.torch.quantization \
  --model_dir "$HF_CACHE/$(basename "$MODEL_ID")" \
  --quant_format=fp8 \
  --output_dir "$QUANT_DIR" \
  --calib_dataset cnn_dailymail \
  --calib_size 512

log "trtllm-build: convert HF -> TRT-LLM checkpoint"
python -m tensorrt_llm.commands.convert_checkpoint \
  --model_dir "$QUANT_DIR" \
  --output_dir "$QUANT_DIR/trt_ckpt" \
  --dtype float16 \
  --use_fp8_rowwise

log "trtllm-build: compile engine"
trtllm-build \
  --checkpoint_dir "$QUANT_DIR/trt_ckpt" \
  --output_dir "$ENGINE_DIR" \
  --gemm_plugin float16 \
  --gpt_attention_plugin float16 \
  --use_paged_context_fmha enable \
  --use_fp8_context_fmha enable \
  --max_input_len "$MAX_INPUT_LEN" \
  --max_seq_len "$((MAX_INPUT_LEN + MAX_OUTPUT_LEN))" \
  --max_batch_size "$MAX_BATCH_SIZE" \
  --max_num_tokens "$MAX_NUM_TOKENS" \
  --workers 1

log "engine built at $ENGINE_DIR"
ls -lh "$ENGINE_DIR"
