# Cycle-2c CUDA MPS install + activation runbook

Pre-research team, read-only. All claims sourced. Retrieval 2026-04-25.

Pod: B300 SXM6 AC, sm_103, driver 580.126.09, CUDA 13.0. Services live: prism42-fish (:9200, ~20 GB), parakeet (:9100, ~12 GB), vllm (pid 285669, ~56 GB), prism42-worker. Bottleneck per T2 [`/Users/kiteboard/prism42/findings/voice/coresidency/ablation.json`]: CUDA stream serialization; Fish RTF +95% under vLLM contention; fingerprint SM% +5pp / mem util -27% / power -13%.

---

## 1. Compatibility verdict

**Verdict: BASIC MPS (client-server with priority hints) is supported on B300 / sm_103 / CUDA 13.0. MLOPart static SM partitioning requires CUDA 13.1 and is NOT available on this pod today.**

- MLOPart is a CUDA 13.1 feature on B200/B300 [^cuda131]. Pod runs CUDA 13.0; MLOPart not available.
- sm_103 supported from CUDA 12.9 [^blackwell-compat]. Basic MPS has no compute-cap restriction beyond Volta+; MLOPart is the 13.1 gate.
- vLLM works under MPS — SGLang issue #22192 reporter confirms vLLM nightly loads and serves while SGLang hangs [^sglang-mps]. `--enforce-eager` is the escape hatch [^vllm-graphs].
- Mamba-MoE: no public MPS incompat report for vLLM 0.20+ as of 2026-04-25. Verify with §5 F1 probe.
- Fish (PyTorch HTTP) and Parakeet (Riva-style): no MPS-incompat reports.
- MIG conflict: pod is `single GPU, no MIG` per T2 ablation. MIG and MPS mutually exclusive on the same GPU [^mig-mps-excl] — safe.

Basic MPS gives us: single MPS server multiplexing all 4 contexts; per-client priority via `CUDA_MPS_CLIENT_PRIORITY` env (0=NORMAL/high, 1=BELOW_NORMAL) [^mps-priority]. Without MLOPart we cannot hard-partition SMs; priority hint is the only knob.

---

## 2. Pre-flight checks

Run before any state change. Each line is bash-quotable. Any non-zero or unexpected output -> halt and report.

```bash
# 1. Confirm not in MIG mode (MIG and MPS are mutually exclusive)
nvidia-smi --query-gpu=mig.mode.current --format=csv,noheader
# expected: "Disabled"   (not "Enabled")

# 2. Confirm MPS daemon NOT already running
pgrep -a nvidia-cuda-mps-control || echo "OK: no daemon"
ls /tmp/nvidia-mps 2>/dev/null && echo "WARN: stale pipe dir" || echo "OK: no pipe dir"

# 3. Confirm mps-control binary present (ships with NVIDIA driver, not CUDA toolkit)
which nvidia-cuda-mps-control && nvidia-cuda-mps-control -h 2>&1 | head -1
# expected: /usr/bin/nvidia-cuda-mps-control + usage banner

# 4. Confirm current compute mode (likely DEFAULT)
nvidia-smi -q -d COMPUTE | grep "Compute Mode"
# expected: "Compute Mode : Default"

# 5. Confirm CUDA driver/toolkit
nvidia-smi --query-gpu=driver_version,compute_cap --format=csv,noheader
# expected: 580.126.09, 10.3   (sm_103)

# 6. Confirm CUDA toolkit version (MLOPart needs 13.1, basic MPS does not)
nvcc --version 2>/dev/null | grep release || echo "nvcc not on PATH (OK if driver-only)"
nvidia-smi | grep "CUDA Version"
# expected: CUDA Version: 13.0   (basic MPS supported; MLOPart NOT available on 13.0)

# 7. Snapshot the 4 service PIDs (used in §3 to decide what restarts)
pgrep -af "fish|parakeet|vllm|prism42-worker" | tee /tmp/cycle-2c-preflight-pids.txt
```

If any of (1)-(3) fails, do NOT proceed. (1) = MIG conflict. (2) = stale state. (3) = driver install gap.

---

## 3. Activation procedure

**Restart fact**: MPS clients attach at CUDA-init time via `CUDA_MPS_PIPE_DIRECTORY`. A process whose CUDA context predates the daemon keeps its native context and **bypasses the daemon** [^mps-tools]. To put a service on MPS, that service must restart. No live attach.

So getting the full co-residency benefit requires restarting all 4 services, INCLUDING the 14-min vLLM CUDA-graph capture. Variant A is recommended; Variant B (vLLM keeps running) leaves vLLM off MPS, so the priority hint cannot affect it and the original 78% RTF degradation persists. Pick A.

### Variant A: full activation, 4 service restarts

Order: daemon FIRST, then services. EXCLUSIVE_PROCESS recommended by NVIDIA so only one MPS server claims the GPU [^mps-when].

```bash
# 3A.1. Stop all 4 services BEFORE changing compute mode (changing compute mode while CUDA is in use is undefined)
systemctl stop prism42-fish prism42-worker
# (vllm + parakeet: use whatever supervisor is running them; pkill -TERM as fallback)
pkill -TERM -f "vllm.*serve" ; pkill -TERM -f parakeet
# wait for clean exit
while pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null; do sleep 1; done

# 3A.2. Set compute mode EXCLUSIVE_PROCESS (single GPU; index 0)
sudo nvidia-smi -i 0 -c EXCLUSIVE_PROCESS
nvidia-smi -q -d COMPUTE | grep "Compute Mode"   # expect "Exclusive_Process"

# 3A.3. Configure daemon dirs (use defaults; explicit for documentation)
sudo mkdir -p /tmp/nvidia-mps /var/log/nvidia-mps
export CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
export CUDA_MPS_LOG_DIRECTORY=/var/log/nvidia-mps

# 3A.4. Start the MPS control daemon (background, root)
sudo CUDA_MPS_PIPE_DIRECTORY=$CUDA_MPS_PIPE_DIRECTORY \
     CUDA_MPS_LOG_DIRECTORY=$CUDA_MPS_LOG_DIRECTORY \
     nvidia-cuda-mps-control -d
sleep 2
pgrep -a nvidia-cuda-mps-control   # expect daemon PID

# 3A.5. Start services in priority order. Each must export CUDA_MPS_PIPE_DIRECTORY and CUDA_MPS_CLIENT_PRIORITY.
# Fish FIRST (HIGH priority, 0)
CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps \
CUDA_MPS_CLIENT_PRIORITY=0 \
systemctl start prism42-fish     # or whatever the supervisor incantation is

# Parakeet (HIGH priority, 0 — STT is also latency-critical)
CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps \
CUDA_MPS_CLIENT_PRIORITY=0 \
<parakeet-start-command>

# vLLM LAST (DEFAULT priority, 1) — this is where the 14-min CUDA-graph capture happens
CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps \
CUDA_MPS_CLIENT_PRIORITY=1 \
<vllm-serve-command>

# Worker (DEFAULT priority, 1)
CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps \
CUDA_MPS_CLIENT_PRIORITY=1 \
systemctl start prism42-worker
```

---

## 4. Stream-priority config

Two paths; only one is viable for our stack:

| Path | Mechanism | Fits our code? |
|---|---|---|
| A. `CUDA_MPS_CLIENT_PRIORITY` env-var per process | Sets the entire client process's MPS priority (0=NORMAL/HIGH, 1=BELOW_NORMAL) [^mps-priority] | YES. Works for Fish, Parakeet, vLLM, worker. No code change. |
| B. Programmatic `cudaStreamCreateWithPriority()` per stream | Application-level code creates a high-priority stream and submits kernels there. NVIDIA-Forum text: "stream priority does not preempt already-running work" [^stream-prio] | NO for vLLM (we do not control its internals). Possible for Fish (it's our PyTorch service) but adds code-change complexity that env-var Path A avoids. |

Path A is the choice. Per §3 Variant A: Fish=0, Parakeet=0, vLLM=1, worker=1. NVIDIA documents priorities are hints, not preemption [^mps-priority]. If the result is insufficient, the next lever is reducing vLLM kernel granularity (smaller `--cuda-graph-sizes`, smaller `--max-num-seqs`) so Fish gets more interleave windows — see T2 OODA secondary action.

---

## 5. Verification probes

Run after Variant A completes. Expected outputs in comments.

```bash
# 5.1. Daemon alive + compute mode
pgrep -a nvidia-cuda-mps-control
nvidia-smi -q -d COMPUTE | grep "Compute Mode"   # expect "Exclusive_Process"

# 5.2. Server ACTIVE (not INITIALIZING, not FAULT)
echo "get_server_list" | nvidia-cuda-mps-control
echo "get_server_status <PID>" | nvidia-cuda-mps-control   # expect "ACTIVE"

# 5.3. All 4 services attached as MPS clients (vLLM may take ~14 min to appear)
echo "ps" | nvidia-cuda-mps-control
echo "get_device_client_list" | nvidia-cuda-mps-control

# 5.4. Per-client priority (ps does NOT show priority; inspect env on disk)
for pid in $(awk '{print $1}' /tmp/cycle-2c-preflight-pids.txt); do
  echo -n "$pid: "; tr '\0' '\n' < /proc/$pid/environ | grep CUDA_MPS_CLIENT_PRIORITY || echo "(unset)"
done

# 5.5. F1 functional probe — health-check each service (detects CUDA-graph hang per SGLang risk)
curl -sf http://127.0.0.1:9200/v1/health   # fish
curl -sf http://127.0.0.1:8001/health      # vllm
curl -sf http://127.0.0.1:9100/health      # parakeet

# 5.6. Empirical regression — re-run T2's ablation (fish-vllm-busy condition).
#      Pre-MPS RTF p50 = 3.499; target 2.4-2.9 per §8.
```

---

## 6. Rollback procedure

Use if §5 verification fails OR Fish RTF gets WORSE OR vLLM hangs at startup OR any service crashes.

```bash
# 6.1. Stop all 4 services first (clean MPS client disconnect)
systemctl stop prism42-fish prism42-worker
pkill -TERM -f "vllm.*serve" ; pkill -TERM -f parakeet
while pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null; do sleep 1; done

# 6.2. Quit daemon (waits for clients to drain)
echo quit | sudo nvidia-cuda-mps-control
sleep 2
pgrep -a nvidia-cuda-mps-control || echo "daemon stopped"

# 6.3. Restore compute mode to DEFAULT
sudo nvidia-smi -i 0 -c DEFAULT
nvidia-smi -q -d COMPUTE | grep "Compute Mode"   # expect "Default"

# 6.4. Clear stale pipe-dir (if any)
sudo rm -rf /tmp/nvidia-mps

# 6.5. Restart services WITHOUT CUDA_MPS_* env vars (back to baseline)
systemctl start prism42-fish prism42-worker
<vllm-serve-command>
<parakeet-start-command>

# 6.6. Verify
nvidia-smi -q -d COMPUTE | grep "Compute Mode"   # "Default"
pgrep -a nvidia-cuda-mps-control   # empty
```

vLLM will pay the 14-min CUDA-graph capture cost again on this restart. Budget for it.

---

## 7. Risk register

| # | Risk | Detection | Mitigation |
|---|---|---|---|
| R1 | vLLM hangs at startup under MPS daemon (graph-capture incompat seen on SGLang [^sglang-mps]) | §5.4 `ps` shows vLLM never attaches; vllm log frozen on flashinfer banner > 20 min | Add `--enforce-eager` to vLLM serve command [^vllm-graphs]; if still hangs, rollback per §6 |
| R2 | EXCLUSIVE_PROCESS set but daemon fails to start; no client can claim GPU | `nvidia-smi` works but every service errors `CUDA_ERROR_INVALID_DEVICE` | Rollback compute mode (§6.3) immediately; do not retry without root-cause |
| R3 | Priority hint has no effect; Fish RTF unchanged | T2 regression rerun shows RTF p50 still ~3.5 | Expected outcome class for some workloads. Then: tune vLLM kernel granularity (smaller `--max-num-seqs`, smaller `--cuda-graph-sizes`) per T2 OODA secondary; OR upgrade to CUDA 13.1 + use MLOPart for hard SM partition [^cuda131] |
| R4 | One service ran with wrong priority (e.g. Fish at 1 instead of 0). Silent — `ps` does not display priority. | §5.6 grep of `/proc/<pid>/environ` shows `CUDA_MPS_CLIENT_PRIORITY=1` on Fish | Restart that service with correct env var. No daemon restart needed. |
| R5 | MPS adds inference overhead on vLLM (Pebble case study: -7.5% throughput, +19.5% time-per-output-token under MPS [^pebble-mps]) | Compare vLLM TPOT pre vs post MPS | Accept the trade if Fish RTF improves >2x more than vLLM TPOT degrades. If not, rollback. |

R5 is the most likely "successful but undesirable" outcome. The ablation rerun is what tells us whether the trade is net positive.

---

## 8. Predicted impact

**T2 baseline**: Fish-alone RTF p50 = 1.969. Fish-vllm-busy RTF p50 = 3.499 (+78%). Fish-all-busy RTF p50 = 3.834 (+95%).

**Predicted post-MPS Fish RTF p50 under all-busy**: range **2.4 - 2.9**, recovering **30-60% of the contention gap** (1.865 RTF units), not the full gap. Reasoning:

1. NVIDIA's only Blackwell MPS measurement is MLOPart cutting atomic-op kernel latency 36% [^cuda131-blog]. That is hard SM partition, not basic-MPS priority hint. Basic MPS is strictly weaker — **36% is the CEILING, not the expected gain**.
2. Pebble: vLLM under MPS loses 7.5% throughput, gains 19.5% TPOT [^pebble-mps]. Cost-side. Fish (HIGH priority) gets the benefit.
3. NVIDIA forum: stream priority is a hint, not preemption [^stream-prio]. A vLLM kernel that already won an SM keeps it; the win is at scheduling boundaries.

**Do not predict Fish RTF <2.0 (full alone-baseline recovery)** — that requires MLOPart or moving vLLM off the GPU.

**vLLM cost**: TPOT +10-20% (Pebble-style). Net E2E user latency wins iff Fish RTF gain (seconds) > vLLM TTFT gain (seconds). T2's gap is 6.93 s p50 — even 30% recovery is ~2 s/turn, well above any vLLM TTFT change.

If empirical rerun shows <20% gap closure: rollback per §6, escalate to (a) CUDA 13.1 + MLOPart, or (b) move vLLM to a separate GPU (T4 pattern P4).

---

## Sources

All retrieval date 2026-04-25.

- [^cuda131] NVIDIA blog "CUDA 13.1 Powers Next-Gen GPU Programming" — https://developer.nvidia.com/blog/nvidia-cuda-13-1-powers-next-gen-gpu-programming-with-nvidia-cuda-tile-and-performance-gains/ (MLOPart B200/B300 in 13.1)
- [^cuda131-blog] NVIDIA blog "Boost GPU Memory Performance with No Code Changes Using NVIDIA CUDA MPS" — https://developer.nvidia.com/blog/boost-gpu-memory-performance-with-no-code-changes-using-nvidia-cuda-mps (36% MLOPart improvement on B200/B300, sm_100+sm_103)
- [^blackwell-compat] NVIDIA Blackwell Compatibility Guide 13.2 — https://docs.nvidia.com/cuda/blackwell-compatibility-guide/ (sm_103 from CUDA 12.9)
- [^sglang-mps] sgl-project/sglang issue #22192 — https://github.com/sgl-project/sglang/issues/22192 (SGLang hangs under MPS, vLLM nightly works)
- [^vllm-graphs] vLLM CUDA Graphs design doc — https://docs.vllm.ai/en/stable/design/cuda_graphs/ (`--enforce-eager` escape hatch)
- [^mps-priority] NVIDIA MPS Tools and Interface Reference, `CUDA_MPS_CLIENT_PRIORITY` — https://docs.nvidia.com/deploy/mps/appendix-tools-and-interface-reference.html (0=NORMAL, 1=BELOW_NORMAL; hint not guarantee)
- [^mps-tools] same page — full command list: `get_server_list`, `get_server_status`, `start_server`, `ps`, `get_client_list`, `get_device_client_list`, `quit`, `set_default_client_priority`
- [^mps-when] NVIDIA MPS "When to Use MPS" — https://docs.nvidia.com/deploy/mps/when-to-use-mps.html (EXCLUSIVE_PROCESS recommended; MIG-MLOPart conflict)
- [^stream-prio] NVIDIA Developer Forums — https://forums.developer.nvidia.com/t/how-high-priority-stream-preemption/78183 (stream priority is hint, no preemption; via T4 ref #19)
- [^mig-mps-excl] nebuly-ai/nos partitioning-modes-comparison + Massed Compute MPS+MIG FAQ — MIG and MPS mutually exclusive; pod is no-MIG single GPU
- [^pebble-mps] Pebble Case Study "NVIDIA MPS vs Dedicated GPU Allocation for LLM Inference" — https://www.gopebble.com/case-studies/nvidia-mps-vs-dedicated-gpu-allocation-for-llm-inference (vLLM under MPS: throughput -7.5%, TPOT +19.5%)
- NVIDIA MPS PDF r590 (2025-12-05) — https://docs.nvidia.com/deploy/pdf/CUDA_Multi_Process_Service_Overview.pdf
- T2 ablation: `/Users/kiteboard/prism42/findings/voice/coresidency/ablation.json` ; T4: `/Users/kiteboard/prism42/findings/voice/nvidia-tts-patterns.md` (refs #4, #19)
