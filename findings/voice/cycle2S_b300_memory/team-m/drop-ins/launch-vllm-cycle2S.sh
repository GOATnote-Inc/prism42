#!/usr/bin/env bash
# /opt/prism42/infra/b300/services/vllm/launch-vllm-cycle2S.sh
#
# Cycle-2S+ wrapper for the CURRENT manual-launch reality.
# vLLM is launched directly (no systemd) per current pod state. This script
# bundles the env vars + flags so a restart from any shell uses the same config.
#
# Use: nohup /opt/prism42/infra/b300/services/vllm/launch-vllm-cycle2S.sh > /tmp/prism42-logs/vllm.log 2>&1 &
#
# Or, when systemd is set up, source this file from a wrapper unit's ExecStart.
#
# Levers applied:
#   L3:  --gpu-memory-utilization 0.85    (was 0.20)
#   L8b: env vars baked in                (was: shell-only, would vanish on fresh restart)
#   L6:  --speculative-config ngram(3,2-4)  (was: not set, no spec decode)
#
# Rollback: stop this process, run the original launcher (whatever it was).
#
# Pre-flight: confirm Fish-Speech is up (port 9200) and the worker isn't actively
# servicing a 911 call. Cold-start budget ~62s; voice will be DOWN during that.

set -euo pipefail

# --- Lever L8b: persistent env ---
export VLLM_USE_FLASHINFER_MOE_FP4=1
export VLLM_FLASHINFER_MOE_BACKEND=throughput
export VLLM_ATTENTION_BACKEND=FLASHINFER
export TORCH_CUDA_ARCH_LIST="10.0;10.3"

# Optional: set HF_TOKEN to avoid unauthenticated-rate-limits warning
# export HF_TOKEN="hf_xxx"

# Path to the venv that has the patched vLLM 0.20.1.dev0 + flashinfer
VLLM_BIN=/opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm
[[ -x "$VLLM_BIN" ]] || { echo "FATAL: $VLLM_BIN not executable" >&2; exit 2; }

# Reasoning parser plugin — keep aligned with current launcher
PARSER_PLUGIN=/opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py
[[ -f "$PARSER_PLUGIN" ]] || { echo "FATAL: $PARSER_PLUGIN missing" >&2; exit 3; }

# Pre-flight: GPU has enough free HBM (>= 150 GiB) before raising vLLM budget?
FREE_MIB=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ')
if [[ "$FREE_MIB" -lt 150000 ]]; then
    echo "WARNING: only ${FREE_MIB} MiB GPU free; raising util to 0.85 may OOM" >&2
    echo "         Continuing anyway — vLLM will refuse to start if it OOMs." >&2
fi

exec "$VLLM_BIN" serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
    --served-model-name nemotron-nano \
    --trust-remote-code \
    --tensor-parallel-size 1 \
    --max-model-len 32768 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.85 \
    --kv-cache-dtype fp8 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser-plugin "$PARSER_PLUGIN" \
    --reasoning-parser nano_v3 \
    --enable-prefix-caching \
    --speculative-config '{"method":"ngram","num_speculative_tokens":3,"prompt_lookup_max":4,"prompt_lookup_min":2}' \
    --port 8001 \
    --host 127.0.0.1
