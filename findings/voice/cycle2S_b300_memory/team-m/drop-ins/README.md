# Cycle-2S+ vLLM drop-ins — installation guide

Authored by Team M. **Authoring only — DO NOT auto-install.** The integrator
(human) decides when to pay the ~62-second cold-start cost and restart vLLM.

## What's here

| File | Purpose | Path on pod |
|---|---|---|
| `00-cycle2S-merged.conf` | **Recommended.** Single drop-in with all 3 levers (L3 + L8b + L6). | `/etc/systemd/system/prism42-vllm.service.d/00-cycle2S-merged.conf` |
| `10-cycle2S-gpu-memory.conf` | L3 only — for incremental rollout. | same dir, name 10- |
| `20-cycle2S-moe-env.conf` | L8b only — env vars only. | same dir, name 20- |
| `30-cycle2S-spec-decode.conf` | L6 only — adds spec-decode flag. | same dir, name 30- |
| `prism42-vllm.service` | The base systemd unit (none exists today on the pod). | `/etc/systemd/system/prism42-vllm.service` |
| `launch-vllm-cycle2S.sh` | **Alternative.** Wrapper script for the current manual-launch reality (no systemd). | `/opt/prism42/infra/b300/services/vllm/launch-vllm-cycle2S.sh` |

## Two paths to apply (pick ONE)

### Path A — Stay with the current manual launch (least invasive)

Today vLLM PID 389310 was launched from a shell with `nohup`. To keep that
pattern but apply the levers:

```bash
# 1. SCP the wrapper to the pod:
scp launch-vllm-cycle2S.sh shadeform@31.22.104.100:/tmp/launch-vllm-cycle2S.sh

# 2. SSH and install:
ssh b300-pod
sudo install -m 0755 -d /opt/prism42/infra/b300/services/vllm/
sudo install -m 0755 -o shadeform -g shadeform \
    /tmp/launch-vllm-cycle2S.sh \
    /opt/prism42/infra/b300/services/vllm/launch-vllm-cycle2S.sh

# 3. Stop the running vLLM (voice will go down for ~62s):
kill $(pgrep -f "vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4")
sleep 30  # wait for clean shutdown + GPU memory release

# 4. Launch the new wrapper:
nohup /opt/prism42/infra/b300/services/vllm/launch-vllm-cycle2S.sh \
    >> /tmp/prism42-logs/vllm.log 2>&1 &
disown

# 5. Verify (see "Verification" below)
```

**Rollback:**

```bash
kill $(pgrep -f "vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4")
# then re-launch with the original command line.
# The original was:
#   VLLM_USE_FLASHINFER_MOE_FP4=1 VLLM_FLASHINFER_MOE_BACKEND=throughput \
#   VLLM_ATTENTION_BACKEND=FLASHINFER TORCH_CUDA_ARCH_LIST="10.0;10.3" \
#   /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm serve \
#     nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
#     --served-model-name nemotron-nano --trust-remote-code \
#     --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 \
#     --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 \
#     --enable-auto-tool-choice --tool-call-parser qwen3_coder \
#     --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py \
#     --reasoning-parser nano_v3 --enable-prefix-caching \
#     --port 8001 --host 127.0.0.1
```

### Path B — Bring vLLM under systemd (more durable)

```bash
# 1. SCP both files to the pod:
scp prism42-vllm.service 00-cycle2S-merged.conf \
    shadeform@31.22.104.100:/tmp/

# 2. SSH and install:
ssh b300-pod
sudo install -m 0644 /tmp/prism42-vllm.service /etc/systemd/system/prism42-vllm.service
sudo install -m 0755 -d /etc/systemd/system/prism42-vllm.service.d
sudo install -m 0644 /tmp/00-cycle2S-merged.conf \
    /etc/systemd/system/prism42-vllm.service.d/00-cycle2S-merged.conf
sudo systemctl daemon-reload

# 3. Stop the manual vLLM + start the systemd one:
kill $(pgrep -f "vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4")
sleep 30
sudo systemctl enable --now prism42-vllm.service

# 4. Verify (see "Verification" below)
```

**Rollback:**

```bash
sudo systemctl disable --now prism42-vllm.service
sudo rm /etc/systemd/system/prism42-vllm.service.d/00-cycle2S-merged.conf
sudo rm /etc/systemd/system/prism42-vllm.service
sudo systemctl daemon-reload
# then re-launch the manual vLLM (see Path A rollback for command).
```

## Verification (after either path)

Run on the pod:

```bash
# 1. Process is up + has the right flags:
ps -o pid,cmd --no-headers $(pgrep -f "vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4") \
    | grep -E "gpu-memory-utilization 0.85.*speculative-config.*ngram"

# 2. Env vars are persistent:
sudo cat /proc/$(pgrep -f "vllm serve")/environ | tr '\0' '\n' \
    | grep -E "^(VLLM|TORCH)" | sort
# Expected output (4 lines):
#   TORCH_CUDA_ARCH_LIST=10.0;10.3
#   VLLM_ATTENTION_BACKEND=FLASHINFER
#   VLLM_FLASHINFER_MOE_BACKEND=throughput
#   VLLM_USE_FLASHINFER_MOE_FP4=1

# 3. MoE backend is FLASHINFER_CUTLASS (NOT TRTLLM):
grep "Using.*MoE backend" /tmp/prism42-logs/vllm.log | tail -1
# Expected: Using 'FLASHINFER_CUTLASS' NvFp4 MoE backend

# 4. KV cache size grew (was 33.56 GiB at gpu-mem-util 0.20):
grep "Available KV cache memory" /tmp/prism42-logs/vllm.log | tail -1
# Expected: Available KV cache memory: 14X.X GiB  (4-5x larger)

# 5. Speculative decoding is wired in:
grep -i "speculative_config\|spec.*decode\|ngram" /tmp/prism42-logs/vllm.log | head -10
# Expected: lines mentioning ngram method and num_speculative_tokens=3

# 6. Live probe — TTFT + decode rate (with spec-decode it should be FASTER):
curl -s -w "\n[TIME] %{time_total}s\n" \
    -X POST http://127.0.0.1:8001/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"nemotron-nano","messages":[
        {"role":"system","content":"You are a 911 dispatcher classifier."},
        {"role":"user","content":"Caller said: my chest hurts. Output JSON: {\"intent\":\"emergency|info|other\",\"severity\":1-5}"}],
        "max_tokens":64,"temperature":0.0}'
# Baseline (pre-cycle2S): 174 ms total for 48 tokens.
# Expected post-cycle2S: ~140 ms total for 64 tokens (33% decode speedup).

# 7. Spec-decode acceptance rate (after ~10 voice turns):
curl -s http://127.0.0.1:8001/metrics | grep -E "spec_decode|num_accepted"
# Expected: vllm:spec_decode_num_accepted_tokens_total > 0,
#           acceptance rate 30-50% on PSAP outputs.

# 8. Voice path end-to-end smoke (place a test call):
#    - Call the dispatch number, say "my chest hurts", verify reply makes sense.
#    - Pre-cycle2S: typical reply latency 1.5-2.0 s end-to-end.
#    - Post-cycle2S: should match or be slightly faster.
```

## Risk gates — before applying

1. **Fish-Speech is up** (port 9200): `curl -s http://127.0.0.1:9200/health` returns OK.
2. **No active 911 call** in progress (check LiveKit dispatch dashboard).
3. **Worker has redundant LLM path** (or accept ~62s downtime). The agent worker
   uses vLLM via `:8001`; during cold-start it will return 5xx.
4. **GPU has >= 150 GiB free** (verified by launcher pre-flight check).
5. **Spec-decode pre-flight FAILED?** Remove the `--speculative-config` flag and re-launch.
   If vLLM aborts at startup due to incompatibility with NemotronH spec-decode,
   that's the most likely failure — easy revert, 30 seconds.
