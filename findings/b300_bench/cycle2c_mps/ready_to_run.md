# Cycle-2c MPS — ready-to-execute runbook

Compiled 2026-04-25 from Team M runbook (`findings/voice/cycle-2c-mps/runbook.md`),
T2 ablation (`findings/voice/coresidency/ablation.json`), and Team 0 baseline state
(`findings/b300_bench/cycle2_guard/2026-04-25T13-56-50Z/state/`).

Pod: `prism-mla-b300-h4h5`. Single GPU 0, no MIG, CUDA 13.0, sm_103.
Variant: A (full activation, all 4 services restarted) per Team M §3.
All commands bash -n clean. Read-only verification first; state-changing commands flagged sudo.

---

## 0. Context lock-in (cite before executing)

| Service | Supervisor | PID (T0 snap) | Mem | Restart command |
|---|---|---|---|---|
| Fish (`:9200`) | systemd `prism42-fish` | 217878 | 20 GB | `sudo systemctl {start,stop} prism42-fish` |
| vLLM (`:8001`) | NOT systemd; nohup | 285796 | 56 GB | `pkill -TERM -f "vllm.*serve"` + manual relaunch |
| Parakeet (`:9100`) | NOT systemd; nohup | 236296 | 5.9 GB | `pkill` + nohup relaunch |
| Worker | systemd `prism42-worker` | (varies) | — | `sudo systemctl {start,stop} prism42-worker` |

Source: `state/cuda_processes.txt`, `state/fish_systemd.txt`, `state/health_baseline.txt`, `state/worker_evidence.txt`.

vLLM ExecStart (single line, copy verbatim from `state/vllm_cmdline.txt`):

```
/opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/python /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1
```

Parakeet relaunch baseline (from `state/health_baseline.txt`):

```
cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown
```

---

## 1. Pre-flight (read-only) — Team M §2

All sudo: NO. All bash -n clean. Estimate: ~30 s wall-clock.

```bash
# 1.1 MIG mode disabled? (sudo: NO)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=mig.mode.current --format=csv,noheader'
# expect: Disabled

# 1.2 No daemon already running? (sudo: NO)
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo "OK: no daemon"'
ssh prism-mla-b300-h4h5 'ls /tmp/nvidia-mps 2>/dev/null && echo WARN || echo "OK: no pipe dir"'

# 1.3 mps-control binary present? (sudo: NO)
ssh prism-mla-b300-h4h5 'which nvidia-cuda-mps-control && nvidia-cuda-mps-control -h 2>&1 | head -1'
# expect: /usr/bin/nvidia-cuda-mps-control + usage banner

# 1.4 Compute mode currently DEFAULT? (sudo: NO)
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
# expect: "Compute Mode : Default"

# 1.5 Driver/CC/CUDA confirmation (sudo: NO)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=driver_version,compute_cap --format=csv,noheader'
# expect: 580.126.09, 10.3
ssh prism-mla-b300-h4h5 'nvidia-smi | grep "CUDA Version"'
# expect: CUDA Version: 13.0  (basic MPS supported; MLOPart NOT — it needs 13.1)

# 1.6 Snapshot service PIDs to /tmp on pod (sudo: NO)
ssh prism-mla-b300-h4h5 'pgrep -af "fish|parakeet|vllm|prism42-worker" | tee /tmp/cycle-2c-preflight-pids.txt'

# 1.7 Capture baseline GPU state for diff (sudo: NO)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv > /tmp/cycle-2c-pre.csv && cat /tmp/cycle-2c-pre.csv'
```

**Halt conditions:** any of (1.1 != Disabled), (1.2 daemon already running), (1.3 binary missing) — abort, do not touch state.

---

## 2. Pre-bench: Fish-alone baseline under DEFAULT mode (Bench 1 reference)

This baseline is required so we can measure the post-MPS Fish-alone delta and confirm MPS itself does not regress single-tenant Fish. Estimate: ~3 min.

```bash
# 2.1 Stop vLLM + Parakeet (Fish + worker stay up). sudo: YES (pkill is fine without sudo,
#     but the kill targets root processes for vLLM if launched by root user)
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" ; pkill -TERM -f "parakeet/server.py"'
ssh prism-mla-b300-h4h5 'while pgrep -f "vllm.*serve|parakeet/server.py" > /dev/null; do sleep 1; done'

# 2.2 Run Fish-alone bench (5 samples, same shape as T2 ablation). sudo: NO.
#     [CLARIFY] - Team M does not specify a canonical bench script. Use the same
#     payload as T2 measured (chunk_length=200, seed=911, temp=0.1, top_p=0.7, use_memory_cache=on,
#     911-utterance: "Nine one one, what is your location and emergency?").
#     Capture into findings/b300_bench/cycle2c_mps/state-pre/fish-alone-defaultmode.json.
```

[CLARIFY: Team M did not ship a runnable Fish-alone bench script. Use T2's protocol from `coresidency/ablation.json` lines 9-15 verbatim; integrator should re-use the harness that produced `findings/voice/coresidency/fish-alone.raw.log` if it still exists. If it does not, this step is a CLARIFY-blocker — flag to Team M before proceeding to §3.]

---

## 3. Service shutdown — Team M §3A.1

Compute mode change is undefined while CUDA contexts are live. All 4 services stop FIRST.

Estimate: ~30 s. **Recommended order** (Team M §3A.1 explicit + my fingerprint analysis):

1. **Fish first** (it is the latency-critical service we are protecting; fastest to stop)
2. **Worker second** (depends on vLLM + Fish; clean stop avoids retry storms)
3. **vLLM third** (slowest CUDA-context teardown; ~5-10 s for clean exit)
4. **Parakeet last** (small footprint; nohup so SIGTERM is straightforward)

```bash
# 3.1 Fish (sudo: YES, systemctl)
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-fish'

# 3.2 Worker (sudo: YES, systemctl)
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-worker'

# 3.3 vLLM (sudo: NO if processes are user-owned; YES if root-owned — confirm with ps)
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve"'

# 3.4 Parakeet (sudo: NO assuming user-owned nohup; YES if started under sudo originally)
ssh prism-mla-b300-h4h5 'pkill -TERM -f "parakeet/server.py"'

# 3.5 Wait for clean drain
ssh prism-mla-b300-h4h5 'while pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null; do sleep 1; done'

# 3.6 Verify no GPU compute apps remain (sudo: NO)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-compute-apps=pid,process_name --format=csv'
# expect: header only (no rows)
```

---

## 4. MPS daemon launch — Team M §3A.2-3A.4

Estimate: ~10 s. ALL sudo.

```bash
# 4.1 Set EXCLUSIVE_PROCESS compute mode (sudo: YES)
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c EXCLUSIVE_PROCESS'
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
# expect: Exclusive_Process

# 4.2 Pre-create daemon dirs (sudo: YES)
ssh prism-mla-b300-h4h5 'sudo mkdir -p /tmp/nvidia-mps /var/log/nvidia-mps'

# 4.3 Start MPS control daemon (sudo: YES — mode-EXCLUSIVE_PROCESS daemon must be root)
ssh prism-mla-b300-h4h5 'sudo CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_LOG_DIRECTORY=/var/log/nvidia-mps nvidia-cuda-mps-control -d'
sleep 2
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control'
# expect: daemon PID present

# 4.4 Probe daemon liveness via control socket (sudo: NO; client mode reads only)
ssh prism-mla-b300-h4h5 'echo "get_server_list" | nvidia-cuda-mps-control'
# expect: empty list (no servers spawned yet — they spawn on first client connect)
```

---

## 5. Service restart under MPS — Team M §3A.5

Each service must export `CUDA_MPS_PIPE_DIRECTORY` AND `CUDA_MPS_CLIENT_PRIORITY` at CUDA-init time. For systemd services, this requires a drop-in file (NOT `systemctl set-environment`, which is system-wide and would also affect non-MPS workloads).

Order: Fish (HIGH) → Parakeet (HIGH) → vLLM (DEFAULT) → Worker (DEFAULT).

### 5.1 Fish drop-in + restart (sudo: YES, ~5 s + ~30 s warm)

```bash
ssh prism-mla-b300-h4h5 'sudo mkdir -p /etc/systemd/system/prism42-fish.service.d'
ssh prism-mla-b300-h4h5 "sudo tee /etc/systemd/system/prism42-fish.service.d/30-mps.conf >/dev/null <<'CONF'
[Service]
Environment=CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
Environment=CUDA_MPS_CLIENT_PRIORITY=0
CONF"
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish'
sleep 30  # Fish compile cold-start per fish_systemd.txt header
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:9200/'  # Fish has Swagger root, NOT /v1/health
```

### 5.2 Parakeet relaunch (sudo: NO if owned by `shadeform` user, YES if originally root-launched — verify with `state/health_baseline.txt` line 11)

```bash
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_CLIENT_PRIORITY=0 nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'
sleep 5
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:9100/healthz'
# expect: {"status":"ok",...}  (Team M §5.5 says /health — that is wrong; baseline shows /healthz)
```

[CLARIFY: Team M §5.5 lists `:9100/health`; Team 0 baseline shows `/healthz`. Use `/healthz` per ground truth.]

### 5.3 vLLM relaunch (sudo: see note; ~14 min cold)

```bash
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_CLIENT_PRIORITY=1 nohup /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/python /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 & disown'

# Background readiness probe (poll every 30s up to 20 min)
ssh prism-mla-b300-h4h5 'for i in $(seq 1 40); do
  if curl -sf http://127.0.0.1:8001/v1/models > /dev/null 2>&1; then
    echo "vLLM ready @ ${i} x 30s = $((i*30))s"; break
  fi; sleep 30
done'
# expect: ready in 14-18 min (CUDA-graph capture). Halt if >20 min — see R1.
```

[CLARIFY: vLLM is not systemd. Original launch user/sudo unknown from snapshots; integrator confirms with `ps -o user= -p 285796` BEFORE shutdown. If output shows `root`, prepend `sudo` to relaunch; if `shadeform`, no sudo.]

### 5.4 Worker drop-in + restart (sudo: YES, ~30 s)

```bash
ssh prism-mla-b300-h4h5 'sudo mkdir -p /etc/systemd/system/prism42-worker.service.d'
ssh prism-mla-b300-h4h5 "sudo tee /etc/systemd/system/prism42-worker.service.d/30-mps.conf >/dev/null <<'CONF'
[Service]
Environment=CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
Environment=CUDA_MPS_CLIENT_PRIORITY=1
CONF"
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload && sudo systemctl start prism42-worker'
sleep 5
ssh prism-mla-b300-h4h5 'sudo systemctl is-active prism42-worker'
# expect: active
```

---

## 6. Verification harness

### 6.1 MPS bookkeeping (sudo: NO)

```bash
# 6.1.a Daemon + compute mode
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control && nvidia-smi -q -d COMPUTE | grep "Compute Mode"'

# 6.1.b Server status (after first client attaches)
ssh prism-mla-b300-h4h5 'echo "get_server_list" | nvidia-cuda-mps-control'
# expect: 1 server PID
ssh prism-mla-b300-h4h5 'SPID=$(echo "get_server_list" | nvidia-cuda-mps-control | head -1); echo "get_server_status $SPID" | nvidia-cuda-mps-control'
# expect: ACTIVE

# 6.1.c All 4 services attached
ssh prism-mla-b300-h4h5 'echo "ps" | nvidia-cuda-mps-control'

# 6.1.d Per-client priority via /proc/<pid>/environ
ssh prism-mla-b300-h4h5 'for svc in fish parakeet vllm prism42-worker; do
  for pid in $(pgrep -f "$svc"); do
    echo -n "$svc[$pid]: "
    tr "\0" "\n" < /proc/$pid/environ 2>/dev/null | grep CUDA_MPS_CLIENT_PRIORITY || echo "(unset)"
  done
done'
# expect: fish=0, parakeet=0, vllm=1, worker=1
```

### 6.2 Functional health (sudo: NO)

```bash
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:9200/ > /dev/null && echo fish=ok || echo fish=FAIL'
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:8001/v1/models > /dev/null && echo vllm=ok || echo vllm=FAIL'
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:9100/healthz > /dev/null && echo parakeet=ok || echo parakeet=FAIL'
ssh prism-mla-b300-h4h5 'sudo systemctl is-active prism42-worker'
```

### 6.3 Validation benches (3 named)

T2 baselines for comparison: Fish-alone p50=1.969, Fish-vllm-busy p50=3.499, Fish-all-busy p50=3.834. PASS thresholds derived from Team M §8 (predicted post-MPS range 2.4-2.9 under all-busy).

#### Bench 1 — Fish-alone post-MPS (sanity check; MPS should not regress single-tenant)

- Stop vLLM + Parakeet (`pkill -TERM -f "vllm.*serve"`, `pkill -TERM -f "parakeet/server.py"`).
- Drive Fish with the T2 protocol: `POST http://127.0.0.1:9200/v1/tts`, `chunk_length=200, seed=911, temperature=0.1, top_p=0.7, use_memory_cache=on`, utterance "Nine one one, what is your location and emergency?".
- N=5 samples (drop the warm call).
- Capture `total_ms_p50`, `rtf_p50` to `findings/b300_bench/cycle2c_mps/<ts>/fish-alone.json`.
- **PASS:** RTF p50 in [1.95, 2.10]. Anything >2.15 means MPS adds intrinsic single-tenant overhead — abort, rollback per §7. Anything <1.95 is noise (T2 measured 1.969 with min/max range of ±0.005).
- After bench: relaunch vLLM + Parakeet per §5.2-5.3 before Bench 2.

#### Bench 2 — Fish-under-vLLM (the headline number; this is the +78% degradation T2 isolated)

- Drive vLLM with the T2 protocol: back-to-back streaming chat-completions, `max_tokens=300`, single-flight, ~36 in-flight rollouts target.
- Concurrently drive Fish with the same payload as Bench 1, N=5.
- Capture `findings/b300_bench/cycle2c_mps/<ts>/fish-vllm.json` + `dmon-vllm.log` (nvidia-smi dmon during the bench).
- **PASS gate** (revised from Team M §8 + R5 trade-off acceptance):
  - Strong PASS: Fish RTF p50 ≤ 2.5 (≥65% gap closure of the 1.530 RTF gap).
  - Acceptable PASS: Fish RTF p50 in (2.5, 2.9] AND vLLM TPOT degradation ≤25% (Pebble bound).
  - FAIL: Fish RTF p50 > 2.9 OR vLLM TPOT degrades >25% — rollback per §7, escalate to MLOPart (CUDA 13.1 prereq) or T4 P4 GPU-split.

#### Bench 3 — Fish-full-stack (cycle-2a-debug 10-prompt harness equivalent)

- Run the existing E2E voice harness shape proven in `findings/b300_bench/e2e_voice/20260425T133813Z/` (10 PSAP prompts: P1×3 critical, P2×3 urgent, P3×2 routine, P4×2 nuisance).
- The harness invokes `/opt/prism42/agents/livekit/synthetic_caller_full.py` per prompt; orchestrator hits Parakeet→vLLM→Fish→worker pipeline end-to-end.
- Capture per-turn `publish_end_to_first_useful_audio_ms` (the headline metric per `aggregate_metrics.py`).
- **PASS gate:**
  - Strong PASS: p50 first-useful-audio < 4500 ms AND p95 < 7000 ms.
  - Acceptable PASS: p50 < 5500 ms (T2's all-busy baseline was 14245 ms total; this would be a >60% reduction in the dominant contention component).
  - FAIL: p50 ≥ 5500 ms OR any turn returns exit-code-5 (orchestrator hung) — rollback.
- Bench 3 is the integration test. Benches 1+2 must PASS before Bench 3 runs (do not waste 10-turn budget on a degraded base layer).

[CLARIFY: T2 measured 5 samples per condition; cycle-2a-debug ran 10 prompts. We keep N=5 for Bench 1+2 (apples-to-apples with T2) and 10 for Bench 3 (matches existing E2E harness contract).]

---

## 7. Rollback procedure — Team M §6

Triggers (any one): §6.1 daemon FAULT, §6.2 health-check FAIL, Bench 1 RTF >2.15, Bench 2 RTF >2.9, Bench 3 p50 ≥5500 ms or hung turn, vLLM never reaches /v1/models 200, R1/R2/R5 fired.

Estimate: ~16 min (vLLM cold reboot dominates).

```bash
# 7.1 Stop services in reverse activation order (sudo: YES for systemd, MAYBE for nohup)
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-worker prism42-fish'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" ; pkill -TERM -f "parakeet/server.py"'
ssh prism-mla-b300-h4h5 'while pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null; do sleep 1; done'

# 7.2 Quit MPS daemon (sudo: YES — daemon was launched as root)
ssh prism-mla-b300-h4h5 'echo quit | sudo nvidia-cuda-mps-control'
sleep 2
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo "daemon stopped"'

# 7.3 Restore compute mode (sudo: YES)
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c DEFAULT'
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
# expect: Default

# 7.4 Remove drop-ins so services return to no-MPS env (sudo: YES)
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-fish.service.d/30-mps.conf /etc/systemd/system/prism42-worker.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'

# 7.5 Clear stale pipe-dir (sudo: YES)
ssh prism-mla-b300-h4h5 'sudo rm -rf /tmp/nvidia-mps'

# 7.6 Restart services WITHOUT CUDA_MPS_* env (back to T0 baseline)
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish prism42-worker'
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && nohup /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/python /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 & disown'
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'

# 7.7 Verify baseline restored (sudo: NO)
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'  # Default
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo "no daemon (correct)"'
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:9200/ > /dev/null && echo fish=ok'
# Wait ~14 min for vLLM cold reboot before declaring rollback complete
ssh prism-mla-b300-h4h5 'for i in $(seq 1 40); do curl -sf http://127.0.0.1:8001/v1/models > /dev/null 2>&1 && echo "vllm ready" && break; sleep 30; done'
ssh prism-mla-b300-h4h5 'curl -sf http://127.0.0.1:9100/healthz > /dev/null && echo parakeet=ok'
```

---

## 8. Sudo requirements (FLAG TO INTEGRATOR — pre-clear with user)

Per user-stated rule: sudo requires explicit re-authorization. The following steps fire sudo:

| Step | Command | Why root |
|---|---|---|
| 3.1, 3.2 | `sudo systemctl stop prism42-fish`, `prism42-worker` | systemctl-stop on system units |
| 4.1 | `sudo nvidia-smi -i 0 -c EXCLUSIVE_PROCESS` | compute mode is a privileged GPU op |
| 4.2 | `sudo mkdir -p /tmp/nvidia-mps /var/log/nvidia-mps` | log dir under `/var/log` |
| 4.3 | `sudo CUDA_MPS_*=... nvidia-cuda-mps-control -d` | MPS daemon under EXCLUSIVE_PROCESS must be root |
| 5.1 | `sudo mkdir -p` + `sudo tee` for fish drop-in + `sudo systemctl daemon-reload` + `sudo systemctl start prism42-fish` | systemd drop-in writes |
| 5.4 | same pattern for prism42-worker | systemd drop-in |
| 7.1 | `sudo systemctl stop` (×2) | rollback teardown |
| 7.2 | `echo quit \| sudo nvidia-cuda-mps-control` | daemon was root |
| 7.3 | `sudo nvidia-smi -i 0 -c DEFAULT` | privileged GPU op |
| 7.4 | `sudo rm -f` + `sudo systemctl daemon-reload` | drop-in removal |
| 7.5 | `sudo rm -rf /tmp/nvidia-mps` | created by daemon as root |
| 7.6 | `sudo systemctl start` (×2) | systemd start |

**Conditional sudo (depends on original launch user — confirm before §3.3, §3.4, §5.2, §5.3):**

- vLLM and Parakeet are nohup'd, NOT systemd. If `ps -o user= -p <pid>` shows `root`, both stop AND restart need sudo. If `shadeform`, neither does.

**No-sudo steps:** all of §1, §6.1, §6.2, the bench drives in §6.3.

---

## 9. Estimated downtime (authorization → first cycle-2c bench landed)

| Phase | Wall-clock |
|---|---|
| Pre-flight §1 | 30 s |
| Pre-bench Fish-alone-DEFAULT (Bench 1 reference, optional) | 3 min |
| Service shutdown §3 | 30 s |
| MPS daemon launch §4 | 10 s |
| Fish restart §5.1 | 30 s + 30 s warm = 1 min |
| Parakeet restart §5.2 | 5 s + 5 s warm = 10 s |
| **vLLM cold reboot §5.3** | **14 min** (CUDA-graph capture; range 14-18 min, halt at 20 min per R1) |
| Worker restart §5.4 | 30 s |
| Verification §6.1, §6.2 | 1 min |
| **Bench 1 (Fish-alone-MPS) §6.3** | **3 min** (5 samples × ~13 s + setup) |
| Bench 2 (Fish-under-vLLM) §6.3 | 4 min |
| Bench 3 (Fish-full-stack 10-prompt) §6.3 | 8 min |

**Critical-path total to first bench (Bench 1 landing): ~17-18 min from authorization.**

**Total to all 3 benches landed: ~31-33 min.**

If rollback fires after Bench 2 fails: +16 min (vLLM cold reboot dominates again). Net round-trip if cycle fails: ~50 min from go to baseline-restored.

Honest risks to schedule:
- vLLM CUDA-graph capture under MPS may exceed 14 min (Team M §3 cites 14 min as the historical figure; under EXCLUSIVE_PROCESS mode this could stretch).
- Fish `--compile` cold-start adds 30-60 s on first synth (per `state/fish_systemd.txt` header). Already in §5.1 budget.
- Bench 3 has 10 turns × ~5 s/turn + warmups ≈ 8 min if every turn passes; failures (exit 5) add ~30 s timeout per failed turn.

---

## 10. Risk register (Team M §7 + cycle-2a-debug deltas)

| # | Risk | Detection | Mitigation | Δ since Team M |
|---|---|---|---|---|
| R1 | vLLM hangs at startup under MPS (SGLang-style) | §5.3 readiness loop never returns 200 within 20 min | Add `--enforce-eager` to vLLM serve; if still hangs, rollback §7 | unchanged |
| R2 | EXCLUSIVE_PROCESS set, daemon fails | nvidia-smi shows mode but `pgrep nvidia-cuda-mps-control` empty | rollback §7.3 immediately | unchanged |
| R3 | Priority hint has no effect; Fish RTF p50 still ~3.5 | Bench 2 ≥3.4 | tune vLLM `--max-num-seqs`/`--cuda-graph-sizes`; OR escalate to MLOPart (needs CUDA 13.1 — pod is 13.0, so this means a separate pod) | unchanged |
| R4 | Service ran with wrong priority (silent) | §6.1.d `/proc/<pid>/environ` mismatch | restart only that service with corrected drop-in | unchanged |
| R5 | MPS adds vLLM overhead (Pebble: TPOT +19.5%) | compare vLLM TPOT pre vs post in Bench 2 | accept iff Fish RTF gain seconds > vLLM TPOT loss seconds; T2's gap is 6.93 s p50 so even 30% Fish recovery (~2 s) outweighs 20% vLLM TPOT delta | unchanged |
| **R6 (NEW)** | Fish `--compile` graph misses MPS interaction; first synth post-restart hangs >60 s | §5.1 health curl times out OR Bench 1 turn 1 latency >10 s | Drop `--compile` in fish service drop-in (set `Environment=PRISM_FISH_COMPILE=0` if respected, or modify `ExecStart` via second drop-in to omit the flag); restart Fish only; rerun Bench 1 | observed in T0 baseline (`fish_systemd.txt` describes compile path) — Team M did not flag |
| **R7 (NEW)** | systemd drop-in `Environment=` does NOT propagate to nohup'd vLLM/Parakeet (they need inline env vars per §5.2, §5.3) | §6.1.d shows vllm/parakeet env unset | the inline `CUDA_MPS_*=val` in the relaunch command IS the correct pattern; verify it is preserved in the nohup'd process tree | unique to this pod since vLLM and Parakeet are NOT systemd-managed |
| **R8 (NEW)** | Worker systemd drop-in conflicts with existing `/etc/systemd/system/prism42-worker.service.d/{10-vllm-model.conf,20-vllm-max-tokens.conf}` (per `state/worker_dropins.txt`) | `systemctl cat prism42-worker` after §5.4 daemon-reload shows missing/duplicate Env | name new drop-in `30-mps.conf` (already done in §5.4) so it sorts after existing drop-ins; systemd merges additively | drop-in coexistence — Team M did not enumerate existing drop-ins |
| **R9 (NEW)** | Parakeet was originally launched by root via `sudo`; user-mode relaunch gets EACCES on /tmp/prism42-logs | §5.2 nohup write fails | check `state/health_baseline.txt` line 11 (`sudo kill 60210`) — Parakeet WAS root-owned in last restart cycle. Relaunch with `sudo` if so, AND ensure `CUDA_MPS_*` propagates through `sudo` (use `sudo -E` or explicit `sudo CUDA_MPS_*=... env -i ...`) | not in Team M; visible only from baseline state |

R5 remains the most likely "successful but undesirable" outcome. Accept iff Bench 2 Fish RTF gain in seconds exceeds Bench 2 vLLM TPOT loss in seconds.

R6 + R9 are the two new traps the integrator should pre-think before pulling the trigger. R6 is mitigatable in <5 min (drop the --compile flag); R9 is also mitigatable but changes the "no sudo" classification of §5.2.

---

## 11. Acceptance gate (re-read before executing)

- [ ] All §1 pre-flight outputs match expected values
- [ ] User has explicitly authorized every sudo step listed in §8
- [ ] vLLM original launch user confirmed (sudo or no — affects §3.3, §5.3, §7.6)
- [ ] Parakeet original launch user confirmed (R9)
- [ ] Bench 1 RTF p50 in [1.95, 2.10] before proceeding to Bench 2
- [ ] Bench 2 RTF p50 + vLLM TPOT delta both within R5 acceptance trade
- [ ] Bench 3 only runs if Bench 1 + 2 PASS
- [ ] Rollback §7 sequence is linearizable from any halt point — confirmed

---

## Sources

- Team M runbook: `findings/voice/cycle-2c-mps/runbook.md` (sections cited inline)
- T2 ablation: `findings/voice/coresidency/ablation.json`
- T0 baseline state: `findings/b300_bench/cycle2_guard/2026-04-25T13-56-50Z/state/`
  - `cuda_processes.txt`, `fish_systemd.txt`, `vllm_cmdline.txt`, `gpu_snapshot.txt`,
    `health_baseline.txt`, `worker_evidence.txt`, `worker_dropins.txt`
- E2E harness pattern: `findings/b300_bench/e2e_voice/20260425T133813Z/aggregate_metrics.py`
- Synthetic caller: `agents/livekit/synthetic_caller_full.py`

All `[CLARIFY]` flags must be resolved before execution. None are blocking on Team 1 (cycle-2d).
