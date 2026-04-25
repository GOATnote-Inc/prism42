#!/usr/bin/env bash
# Cycle-2c MPS rollback (bash -n verification target). Verbatim from runbook.md §6.
set -e
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-fish prism42-worker'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" ; pkill -TERM -f parakeet'
ssh prism-mla-b300-h4h5 'while pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null; do sleep 1; done'
ssh prism-mla-b300-h4h5 'echo quit | sudo nvidia-cuda-mps-control'
ssh prism-mla-b300-h4h5 'sleep 2 && pgrep -a nvidia-cuda-mps-control || echo daemon-stopped'
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c DEFAULT'
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
ssh prism-mla-b300-h4h5 'sudo rm -rf /tmp/nvidia-mps'
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish prism42-worker'
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && nohup .venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 &disown'
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 &disown'
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo no-daemon'
