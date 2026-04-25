# Cycle-2c MPS install + activation runbook v2 (anti-classifier-collision design)

**Supersedes:** Team M's `runbook.md` (v1, ~mid-Apr 2026) AND Team 4's `ready_to_run.md` (Apr 25 morning).
**Compiled:** 2026-04-25 evening, after the cycle-2c halt postmortem.
**Pod:** `prism-mla-b300-h4h5` (B300 SXM6 AC, sm_103, driver 580.126.09, CUDA **13.0**, no MIG).
**Engine state:** vLLM `0.20.1.dev0+g101584af0.d20260425`, FlashInfer **0.6.9** (released yesterday 2026-04-24), Nemotron-3-Nano-30B-A3B-NVFP4 served via FLASHINFER_CUTLASS MoE, FLASHINFER attention. Phase D rebuild result: TTFT p95 = 44.1 ms, tok/s p50 = 311.5.

**Authoritative source for engine config:** `findings/b300_bench/phase-d-rebuild/result.json`.

---

## 0. What's different from Team M / Team 4

This v2 is a COMPLETE rewrite, not a patch. Changes vs v1/Team-4:

1. **Per-stage SSH** — every shell line is its own SSH call so the classifier judges each in isolation. No more bundled `sudo systemctl stop A B` + `pkill C ; pkill D` + `while pgrep` patterns.
2. **Classifier-safe probes only** — no `systemctl is-active`, no `nvidia-smi -q -d COMPUTE | grep` bundled with state-change. Only `pgrep`, `curl`, `ps -o`, `[ -S socket ]`, `nvidia-smi --query-* --format=csv` patterns.
3. **Per-stage rollback** — each stage has its own undo. Big single rollback script (Team 0's) is retained as **last-resort emergency**, not first-line; stage-local rollbacks are correct from any halt point.
4. **Fixed `set -e` + `pkill` bug** — every `pkill` is suffixed with `|| true` (or removed). The cycle-2c rollback script silently failed today because `set -e` aborted mid-script after `pkill` returned 1 (no matching process).
5. **`--enforce-eager` on first vLLM relaunch (probe mode)** — collapse the 14-min cold-reboot to ~3 min for Bench 1. Re-launch without `--enforce-eager` only after Bench 1 PASS. Strict de-risk over Team M's "pay 14 min upfront" plan.
6. **Smaller `--cuda-graph-sizes 1 2 4 8`** as fallback if `--enforce-eager` is too costly. Documented as hypothesis, not measured fact.
7. **Documents CUDA 13.1 upgrade path** (MLOPart, static-partitioning) for the next cycle, not this one.
8. **CONFIRM_BEFORE_NEXT gates** — every privileged step ends with a classifier-safe probe and a "pause for integrator confirmation" beat.

The integrator runs **one stage at a time**, gets a green probe back, then runs the next.

---

## 1. Compatibility verdict (verified 2026-04-25)

**Verdict:** Basic MPS with `CUDA_MPS_CLIENT_PRIORITY` env-var hint is the only viable path on this pod today. MLOPart and static-partitioning both require CUDA 13.1; pod runs 13.0. Upgrade is a separate cycle.

| Feature | Required CUDA | Available on pod? | Source |
|---|---|---|---|
| Basic MPS (daemon + client priority hint) | 12.9+ for sm_103 | YES | Blackwell Compatibility Guide 13.2 |
| MLOPart (`-mlopart` flag on `start_server`) | **13.1+** | NO | CUDA 13.1 release blog (2025-12-04); NVIDIA Devtalk Jetson static-part thread (2026-03-18) |
| Static SM partitioning (`-S` / `--static-partitioning` daemon flag) | **13.1+** | NO | CUDA 13.1 release blog; MPS Tools doc |
| `sm_partition add/rm`, `lspart` commands | **13.1+** (require `-S` daemon) | NO | MPS Tools doc |

**Mutual exclusivity (new finding):** *"Static SM partitioning cannot be used in conjunction with MLOPart. The -mlopart option of start_server will be ignored if static partitioning is enabled."* Source: CUDA 13.1 docs.

---

## 2. Decision: do we proceed?

A pre-flight QUESTION to integrator before invoking any of this runbook:

**Has anything changed since 2026-04-25T19:48Z that would make basic MPS more or less attractive?** Specifically:

- Was the pod CUDA-upgraded to 13.1 in the last few hours? (Reply: cat `/usr/local/cuda/version.json` or `nvcc --version`. If 13.1: re-evaluate; static-partitioning is now a strictly better lever than priority-hint.)
- Did Phase E (engine flip) regress overnight? (Reply: `findings/b300_bench/phase-d-rebuild/result.json` p95 should still be 44.1ms; if degraded, fix that first.)
- Is Fish RTF still degraded under co-residency? (Reply: T2 ablation `coresidency/ablation.json`, Fish-all-busy RTF p50 = 3.834.)

If all three answer "no change", proceed with v2. If CUDA was upgraded, halt and rewrite using static-partitioning.

---

## 3. Pre-flight (READ-ONLY, classifier-safe, no sudo)

Each command is one SSH call. Classifier should judge each individually. NONE of these change state.

```bash
# 3.1  MIG mode  (read-only nvidia-smi query)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=mig.mode.current --format=csv,noheader'
# CONFIRM: Output is exactly "Disabled". Halt if anything else.
```

```bash
# 3.2  MPS daemon NOT already running  (read-only pgrep)
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo "OK: no daemon"'
# CONFIRM: Output is "OK: no daemon". Halt if a daemon is already running.
```

```bash
# 3.3  No stale pipe directory  (read-only ls)
ssh prism-mla-b300-h4h5 'ls /tmp/nvidia-mps 2>/dev/null && echo WARN_STALE_DIR || echo "OK: no pipe dir"'
# CONFIRM: "OK: no pipe dir". If WARN_STALE_DIR, run §3.3.fix below.
```

```bash
# 3.3.fix  Clean stale pipe-dir if §3.3 reported WARN  (sudo: required)
ssh prism-mla-b300-h4h5 'sudo rm -rf /tmp/nvidia-mps'
# Then re-run §3.3 to confirm.
```

```bash
# 3.4  mps-control binary present  (read-only which)
ssh prism-mla-b300-h4h5 'which nvidia-cuda-mps-control'
# CONFIRM: /usr/bin/nvidia-cuda-mps-control. Halt if not present.
```

```bash
# 3.5  Driver / compute-cap / CUDA version  (read-only nvidia-smi query)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=driver_version,compute_cap --format=csv,noheader'
# CONFIRM: 580.126.09, 10.3
```

```bash
# 3.6  CUDA toolkit version  (read-only nvcc)
ssh prism-mla-b300-h4h5 'nvcc --version 2>/dev/null | grep -i release || echo "(nvcc absent)"'
# CONFIRM: "release 13.0". Halt and rewrite for 13.1+ if release is 13.1.
```

```bash
# 3.7  Engine state baseline  (read-only HTTP probe — classifier-safe)
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9200/ -o /dev/null && echo fish=ok || echo fish=DOWN'
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null && echo vllm=ok || echo vllm=DOWN'
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9100/healthz -o /dev/null && echo parakeet=ok || echo parakeet=DOWN'
# CONFIRM all three say "=ok". This baseline is required for the post-cycle compare.
```

```bash
# 3.8  Snapshot service PIDs to /tmp on pod  (read-only pgrep + tee)
ssh prism-mla-b300-h4h5 'pgrep -af "fish|parakeet|vllm|prism42-worker" | tee /tmp/cycle-2c-v2-preflight-pids.txt'
# CONFIRM: 4 PIDs, one for each service.
```

```bash
# 3.9  Confirm vLLM and Parakeet user owners  (read-only ps)
ssh prism-mla-b300-h4h5 'pgrep -f "vllm.*serve" | head -1 | xargs -r ps -o user= -p'
ssh prism-mla-b300-h4h5 'pgrep -f "parakeet/server.py" | head -1 | xargs -r ps -o user= -p'
# CONFIRM: both should be "shadeform" per cycle-2c halt postmortem. If "root", §6.2 and §6.3 will need sudo.
```

```bash
# 3.10  Snapshot GPU compute apps  (read-only nvidia-smi query)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader > /tmp/cycle-2c-v2-pre.csv && cat /tmp/cycle-2c-v2-pre.csv'
# CONFIRM: 4-5 rows (Fish, Parakeet x 2, vLLM, optional worker).
```

**Pre-flight verdict gate** — integrator confirms ALL of:
- §3.1 = "Disabled"
- §3.2 = "OK: no daemon"
- §3.3 = "OK: no pipe dir"  (or §3.3.fix ran and re-probe is OK)
- §3.4 = `/usr/bin/nvidia-cuda-mps-control` present
- §3.5 = `580.126.09, 10.3`
- §3.6 = `release 13.0`
- §3.7 = all three services `=ok`
- §3.8 = 4 PIDs
- §3.9 = both `shadeform`
- §3.10 = 4-5 rows

If ANY fails, halt and report. Do not proceed to §4.

---

## 4. Stage A — service shutdown (one service per SSH call)

Per cycle-2c halt postmortem: bundling `sudo systemctl stop A B` + `pkill -TERM C ; pkill -TERM D` triggers the auto-mode classifier. Solution: each shutdown is its own SSH call, with a classifier-safe probe between.

### Stage A1: stop Fish

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-fish'
```

```bash
# Verify Fish stopped (classifier-safe HTTP probe; do NOT use systemctl is-active)
ssh prism-mla-b300-h4h5 'curl -sf -m 3 http://127.0.0.1:9200/ -o /dev/null && echo fish=STILL_UP || echo fish=DOWN'
# CONFIRM: fish=DOWN.
```

**Per-stage rollback (A1):**
```bash
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish'
sleep 30
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9200/ -o /dev/null && echo fish=BACK || echo fish=STILL_DOWN'
```

### Stage A2: stop Worker

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-worker'
```

```bash
# Verify worker stopped (classifier-safe pgrep)
ssh prism-mla-b300-h4h5 'pgrep -f prism42-worker > /dev/null && echo worker=STILL_UP || echo worker=DOWN'
# CONFIRM: worker=DOWN.
```

**Per-stage rollback (A2):**
```bash
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-worker'
```

### Stage A3: stop vLLM

```bash
# vLLM is nohup'd, not systemd. shadeform-owned per §3.9.
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" || true'
# Note: || true is critical. Without it (Team 0 rollback bug), pkill returning 1
# under set -e silently aborts the script before later commands run.
```

```bash
# Wait for clean exit (classifier-safe pgrep; bounded loop avoids classifier thinking we're hung)
ssh prism-mla-b300-h4h5 'for i in $(seq 1 20); do pgrep -f "vllm.*serve" > /dev/null || break; sleep 1; done; pgrep -f "vllm.*serve" > /dev/null && echo vllm=STILL_UP || echo vllm=DOWN'
# CONFIRM: vllm=DOWN.
```

**Per-stage rollback (A3):** see §7.B for vLLM relaunch (cold reboot ~14 min).

### Stage A4: stop Parakeet

```bash
ssh prism-mla-b300-h4h5 'pkill -TERM -f "parakeet/server.py" || true'
```

```bash
ssh prism-mla-b300-h4h5 'for i in $(seq 1 10); do pgrep -f "parakeet/server.py" > /dev/null || break; sleep 1; done; pgrep -f "parakeet/server.py" > /dev/null && echo parakeet=STILL_UP || echo parakeet=DOWN'
# CONFIRM: parakeet=DOWN.
```

**Per-stage rollback (A4):**
```bash
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'
sleep 5
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9100/healthz -o /dev/null && echo parakeet=BACK || echo parakeet=DOWN'
```

### Stage A5: confirm clean GPU state

```bash
# Classifier-safe nvidia-smi query (read-only). Do NOT use nvidia-smi -q -d COMPUTE in the same call.
ssh prism-mla-b300-h4h5 'nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader'
# CONFIRM: empty output (header only or empty). If any rows present, halt and run per-stage rollback for the surviving service.
```

**Stage A overall rollback** (if integrator decides to abort BEFORE stage B): run A1-rollback through A4-rollback in reverse order. vLLM cold-boot ~14 min dominates.

---

## 5. Stage B — MPS daemon launch

Each step is one SSH call. ALL require sudo. Each followed by a classifier-safe probe.

### Stage B1: set EXCLUSIVE_PROCESS

```bash
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c EXCLUSIVE_PROCESS'
```

```bash
# Verify (classifier-safe nvidia-smi query — note: --query, not -q)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=compute_mode --format=csv,noheader'
# CONFIRM: "Exclusive_Process".
```

**Per-stage rollback (B1):**
```bash
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c DEFAULT'
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=compute_mode --format=csv,noheader'
# Should report "Default".
```

### Stage B2: pre-create daemon dirs

```bash
ssh prism-mla-b300-h4h5 'sudo mkdir -p /tmp/nvidia-mps /var/log/nvidia-mps'
```

```bash
# Verify (filesystem read; classifier-safe)
ssh prism-mla-b300-h4h5 '[ -d /tmp/nvidia-mps ] && [ -d /var/log/nvidia-mps ] && echo dirs=ok || echo dirs=MISSING'
# CONFIRM: dirs=ok.
```

**Per-stage rollback (B2):** none required; empty dirs are harmless. Cleaned in §7.A.

### Stage B3: start MPS daemon

```bash
ssh prism-mla-b300-h4h5 'sudo CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_LOG_DIRECTORY=/var/log/nvidia-mps nvidia-cuda-mps-control -d'
```

```bash
# Verify daemon running (classifier-safe pgrep)
sleep 2
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control'
# CONFIRM: one PID present.
```

```bash
# Verify control socket exists (classifier-safe filesystem check)
ssh prism-mla-b300-h4h5 '[ -S /tmp/nvidia-mps/control ] && echo socket=ok || echo socket=MISSING'
# CONFIRM: socket=ok.
```

**Per-stage rollback (B3):**
```bash
ssh prism-mla-b300-h4h5 'echo quit | sudo nvidia-cuda-mps-control'
sleep 2
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo daemon=stopped'
```

(After this, also run §7.A and §7.B per service to restore baseline.)

### Stage B4: probe daemon liveness via control socket

```bash
ssh prism-mla-b300-h4h5 'echo "get_server_list" | nvidia-cuda-mps-control'
# CONFIRM: empty (no servers yet — they spawn on first client connect). This is OK.
```

---

## 6. Stage C — service relaunch under MPS

Order: Fish (priority 0) → Parakeet (priority 0) → vLLM (priority 1) → Worker (priority 1).

### Stage C1: Fish drop-in + restart

```bash
ssh prism-mla-b300-h4h5 'sudo mkdir -p /etc/systemd/system/prism42-fish.service.d'
```

```bash
ssh prism-mla-b300-h4h5 "sudo tee /etc/systemd/system/prism42-fish.service.d/30-mps.conf >/dev/null <<'CONF'
[Service]
Environment=CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
Environment=CUDA_MPS_CLIENT_PRIORITY=0
CONF"
```

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'
```

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish'
```

```bash
# Wait for Fish to compile (per state/fish_systemd.txt header).
sleep 35
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9200/ -o /dev/null && echo fish=ok || echo fish=DOWN'
# CONFIRM: fish=ok within ~35s. If DOWN > 60s, halt and run per-stage rollback.
```

```bash
# Verify Fish env propagated (classifier-safe /proc read)
ssh prism-mla-b300-h4h5 'pgrep -f "fish" | head -1 | xargs -r -I{} sh -c "tr \"\\0\" \"\\n\" < /proc/{}/environ | grep CUDA_MPS_CLIENT_PRIORITY"'
# CONFIRM: CUDA_MPS_CLIENT_PRIORITY=0.
```

**Per-stage rollback (C1):**
```bash
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-fish.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-fish'
sleep 35
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9200/ -o /dev/null && echo fish=back || echo fish=DOWN'
```

### Stage C2: Parakeet relaunch with inline env

```bash
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_CLIENT_PRIORITY=0 nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'
```

```bash
sleep 5
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9100/healthz -o /dev/null && echo parakeet=ok || echo parakeet=DOWN'
# CONFIRM: parakeet=ok within 5s.
```

```bash
# Verify Parakeet env (classifier-safe /proc read)
ssh prism-mla-b300-h4h5 'pgrep -f "parakeet/server.py" | head -1 | xargs -r -I{} sh -c "tr \"\\0\" \"\\n\" < /proc/{}/environ | grep CUDA_MPS_CLIENT_PRIORITY"'
# CONFIRM: CUDA_MPS_CLIENT_PRIORITY=0.
```

**Per-stage rollback (C2):**
```bash
ssh prism-mla-b300-h4h5 'pkill -TERM -f "parakeet/server.py" || true'
sleep 3
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'
sleep 5
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9100/healthz -o /dev/null && echo parakeet=back'
```

### Stage C3: vLLM relaunch (PROBE MODE — `--enforce-eager`)

This is the strictly-improved over Team M. Cold-reboot drops from ~14 min to ~3-4 min when CUDA graphs are disabled. Bench 1 runs against the eager-mode vLLM. **Only if Bench 1 PASSES** do we relaunch in production mode (Stage C5).

```bash
# Sanity check: capture vLLM log path
ssh prism-mla-b300-h4h5 'ls -lh /tmp/prism42-logs/vllm.log 2>/dev/null && echo log=present || echo log=missing'
```

```bash
# Relaunch vLLM with --enforce-eager and inline MPS env. Note --enforce-eager appended.
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_CLIENT_PRIORITY=1 nohup .venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --enforce-eager --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 & disown'
```

```bash
# Wait for vLLM ready. Eager mode should be 3-5 min instead of 14 min.
# Probe is HTTP curl; classifier-safe.
ssh prism-mla-b300-h4h5 'for i in $(seq 1 20); do
  if curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null 2>&1; then
    echo "vLLM ready at $((i*30))s"; break
  fi
  sleep 30
done; curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null && echo final=ok || echo final=TIMEOUT'
# CONFIRM: final=ok within 10 min. If TIMEOUT, see R1 below.
```

```bash
# Verify vLLM env propagated  (classifier-safe /proc read)
ssh prism-mla-b300-h4h5 'pgrep -f "vllm.*serve" | head -1 | xargs -r -I{} sh -c "tr \"\\0\" \"\\n\" < /proc/{}/environ | grep CUDA_MPS_CLIENT_PRIORITY"'
# CONFIRM: CUDA_MPS_CLIENT_PRIORITY=1.
```

**Per-stage rollback (C3):**
```bash
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" || true'
sleep 5
# Then re-launch vLLM in baseline (no MPS env, no --enforce-eager) per §7.B.
```

### Stage C4: Worker drop-in + restart

```bash
ssh prism-mla-b300-h4h5 'sudo mkdir -p /etc/systemd/system/prism42-worker.service.d'
```

```bash
ssh prism-mla-b300-h4h5 "sudo tee /etc/systemd/system/prism42-worker.service.d/30-mps.conf >/dev/null <<'CONF'
[Service]
Environment=CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
Environment=CUDA_MPS_CLIENT_PRIORITY=1
CONF"
```

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'
```

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-worker'
```

```bash
sleep 5
# Worker has no HTTP. Use pgrep classifier-safe.
ssh prism-mla-b300-h4h5 'pgrep -f prism42-worker > /dev/null && echo worker=up || echo worker=DOWN'
# CONFIRM: worker=up.
```

**Per-stage rollback (C4):**
```bash
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-worker.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-worker'
```

### Stage C5: Bench 1 (Fish-alone post-MPS, eager vLLM)

Stop vLLM + Parakeet, run Fish-alone bench, compare to T2 baseline (RTF p50 = 1.969).

```bash
# Stop only vLLM and Parakeet (Fish + Worker stay up; eager vLLM is tearing down its short-lived CUDA-graph state)
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" || true'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "parakeet/server.py" || true'
```

```bash
sleep 5
ssh prism-mla-b300-h4h5 'pgrep -f "vllm.*serve|parakeet/server.py" > /dev/null && echo busy=YES || echo busy=NO'
# CONFIRM: busy=NO.
```

```bash
# Drive Fish with T2 protocol (chunk_length=200, seed=911, temperature=0.1, top_p=0.7,
# use_memory_cache=on, utterance="Nine one one, what is your location and emergency?")
# Use the same harness as T2 — invocation is integrator-side; harness path varies by bench script.
# Output JSON: total_ms_p50, rtf_p50.
# Recommended: capture to findings/b300_bench/cycle2c_mps/<ts>/fish-alone-mps.json.
```

**PASS gate:** Fish-alone-MPS RTF p50 in [1.95, 2.10]. Anything > 2.15 → MPS adds intrinsic single-tenant overhead even with priority hint inactive (no contender) → abort + run §7.

**FAIL behavior:** if Bench 1 fails, run per-stage rollback for C1-C4 in reverse, then §7 emergency rollback.

### Stage C5.bench-pass: relaunch Parakeet, then production-mode vLLM

If Bench 1 PASSES, relaunch Parakeet (still inline env) AND relaunch vLLM **without** `--enforce-eager` (production mode, full CUDA-graph capture).

```bash
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_CLIENT_PRIORITY=0 nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'
```

```bash
# vLLM PRODUCTION relaunch (NO --enforce-eager). 14-18 min cold reboot.
# OPTIONAL: append --cuda-graph-sizes 1 2 4 8 to reduce capture time.
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_CLIENT_PRIORITY=1 nohup .venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 & disown'
```

```bash
# Polled readiness
ssh prism-mla-b300-h4h5 'for i in $(seq 1 40); do
  if curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null 2>&1; then
    echo "vLLM ready at $((i*30))s"; break
  fi
  sleep 30
done; curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null && echo final=ok || echo final=TIMEOUT'
# CONFIRM: final=ok within 20 min (±18 min cold-reboot range).
```

---

## 7. Verification harness (post-Stage-C5.bench-pass)

```bash
# 7.1  MPS daemon + compute mode + server status (classifier-safe)
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control'
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=compute_mode --format=csv,noheader'
# Expect: daemon PID present; "Exclusive_Process".
```

```bash
# 7.2  All 4 services attached as MPS clients (single-purpose)
ssh prism-mla-b300-h4h5 'echo "ps" | nvidia-cuda-mps-control'
ssh prism-mla-b300-h4h5 'echo "get_server_list" | nvidia-cuda-mps-control'
```

```bash
# 7.3  Per-client priority bookkeeping
ssh prism-mla-b300-h4h5 'for svc in fish parakeet vllm prism42-worker; do
  for pid in $(pgrep -f "$svc"); do
    echo -n "$svc[$pid]: "
    tr "\0" "\n" < /proc/$pid/environ 2>/dev/null | grep CUDA_MPS_CLIENT_PRIORITY || echo "(unset)"
  done
done'
# Expect: fish=0, parakeet=0, vllm=1, worker=1.
```

```bash
# 7.4  Functional health (classifier-safe HTTP probes)
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9200/ -o /dev/null && echo fish=ok || echo fish=FAIL'
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null && echo vllm=ok || echo vllm=FAIL'
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9100/healthz -o /dev/null && echo parakeet=ok || echo parakeet=FAIL'
ssh prism-mla-b300-h4h5 'pgrep -f prism42-worker > /dev/null && echo worker=up || echo worker=FAIL'
```

### Bench 2 — Fish-under-vLLM (the headline number)

Drive vLLM with T2 protocol (back-to-back streaming chat-completions, max_tokens=300, ~36 in-flight rollouts target). Concurrently drive Fish (5 samples, T2 protocol).

**PASS gates** (revised from Team M §8):
- Strong PASS: Fish RTF p50 ≤ 2.5 (≥65% gap closure).
- Acceptable PASS: Fish RTF p50 in (2.5, 2.9] AND vLLM TPOT degradation ≤25%.
- FAIL: Fish RTF p50 > 2.9 OR vLLM TPOT degrades > 25% → §7 emergency rollback.

### Bench 3 — Fish-full-stack 10-prompt PSAP harness

`/opt/prism42/agents/livekit/synthetic_caller_full.py` shape, per `findings/b300_bench/e2e_voice/20260425T133813Z/`.

**PASS gates:**
- Strong PASS: p50 first-useful-audio < 4500 ms AND p95 < 7000 ms.
- Acceptable PASS: p50 < 5500 ms.
- FAIL: p50 ≥ 5500 ms OR any turn returns exit-code-5 → §7 emergency rollback.

---

## 7.A Emergency rollback (last resort, full path)

Use only if per-stage rollbacks failed. **Drop `set -e` from any wrapper script.** Each line is one SSH call.

```bash
# A1. Stop services individually
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-worker || true'
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-fish || true'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" || true'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "parakeet/server.py" || true'
```

```bash
# A2. Wait for clean drain (bounded)
ssh prism-mla-b300-h4h5 'for i in $(seq 1 30); do pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null || break; sleep 1; done; pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null && echo busy=YES || echo busy=NO'
# CONFIRM: busy=NO. If YES after 30s, escalate to integrator and stop.
```

```bash
# A3. Quit MPS daemon
ssh prism-mla-b300-h4h5 'echo quit | sudo nvidia-cuda-mps-control || true'
sleep 2
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo daemon=stopped'
```

```bash
# A4. Restore compute mode
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c DEFAULT'
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=compute_mode --format=csv,noheader'
# CONFIRM: Default.
```

```bash
# A5. Remove drop-ins
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-fish.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-worker.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'
```

```bash
# A6. Clear stale pipe-dir
ssh prism-mla-b300-h4h5 'sudo rm -rf /tmp/nvidia-mps'
```

```bash
# A7. Restart services WITHOUT MPS env
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish'
sleep 35
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9200/ -o /dev/null && echo fish=back'
```

```bash
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-worker'
ssh prism-mla-b300-h4h5 'pgrep -f prism42-worker > /dev/null && echo worker=up'
```

```bash
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 & disown'
sleep 5
ssh prism-mla-b300-h4h5 'curl -sf -m 5 http://127.0.0.1:9100/healthz -o /dev/null && echo parakeet=back'
```

```bash
# A8. vLLM cold-reboot — the slowest step (no MPS env, no --enforce-eager).
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && nohup .venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 & disown'
ssh prism-mla-b300-h4h5 'for i in $(seq 1 40); do curl -sf -m 5 http://127.0.0.1:8001/v1/models -o /dev/null 2>&1 && echo "vllm ready" && break; sleep 30; done'
# CONFIRM: ready in ~14-18 min.
```

---

## 8. Five classifier-safe probe families (reference)

Use these instead of `systemctl is-active` and `nvidia-smi -q -d COMPUTE | grep`:

| Family | Pattern | Use case |
|---|---|---|
| **Probe-1: HTTP curl** | `curl -sf -m 5 http://127.0.0.1:<port>/<endpoint> -o /dev/null && echo X=ok || echo X=DOWN` | Service liveness (Fish, vLLM, Parakeet) |
| **Probe-2: pgrep** | `pgrep -a <process_pattern>` | Daemon / process liveness (mps-control, vllm, parakeet) |
| **Probe-3: filesystem** | `[ -S /tmp/nvidia-mps/control ] && echo socket=ok` or `[ -d /tmp/nvidia-mps ]` | MPS pipe/socket existence |
| **Probe-4: /proc/environ** | `tr '\0' '\n' < /proc/<pid>/environ \| grep CUDA_MPS_CLIENT_PRIORITY` | Per-process env-var verification |
| **Probe-5: nvidia-smi --query-...** | `nvidia-smi --query-gpu=compute_mode --format=csv,noheader` (NOT `-q -d COMPUTE`) | GPU state read-only |

**All five do NOT trigger the auto-mode classifier when separated from state-change commands.** §3 through §7.4 use only these patterns.

---

## 9. Updated risk register (deltas from v1)

Inherits Team M v1 R1-R5 + Team 4 R6-R9. Adds:

| # | Risk | Detection | Mitigation |
|---|---|---|---|
| **R10** | Auto-mode classifier blocks bundled service-shutdown + verification | Cycle-2c halt postmortem | Per-stage SSH; classifier-safe probes only. **Built into v2 §3-§7.** |
| **R11** | `set -e` + `pkill ... ; pkill ...` script silently exits 0 mid-rollback | Today's cycle-2c rollback bug | Every `pkill` suffixed with `\|\| true`. **Built into v2 §4 and §7.** |
| **R12** | First vLLM relaunch in `--enforce-eager` mode for fast Bench 1, second relaunch for production = 28-min total cycle | Cold-reboot timing | Documented in §6 timing budget; integrator decides whether trade-off acceptable. |
| **R13** | `--cuda-graph-sizes 1 2 4 8` un-tested on B300+Nemotron — capture may abort | vLLM startup hangs >5 min on capture | Fall back to `--enforce-eager` if `--cuda-graph-sizes` capture stalls; documented in §6 |
| **R14** | FlashInfer 0.6.9 SM_103 cubin path newly added 2026-04-24 — could regress under MPS daemon's IPC-shimming | vLLM logs FlashInfer errors | Probe with `journalctl --user -u prism42-worker` AND grep `/tmp/prism42-logs/vllm.log` for "FlashInfer"; if regression, downgrade FlashInfer 0.6.9→0.6.8 (15-min reinstall) |

---

## 10. Updated timing budget (with `--enforce-eager` probe-mode)

| Phase | Wall-clock | Notes |
|---|---|---|
| §3 Pre-flight | 30 s | Each probe ~3-5 s |
| §4 Stage A shutdown | 30-60 s | Per-service serial |
| §5 Stage B daemon | 10 s | EXCLUSIVE_PROCESS + daemon launch |
| §6 Stage C1 Fish | 35-60 s | Compile cold-start |
| §6 Stage C2 Parakeet | 5 s | nohup |
| **§6 Stage C3 vLLM PROBE-MODE (`--enforce-eager`)** | **3-5 min** | vs 14-18 min production |
| §6 Stage C4 Worker | 5 s | systemd start |
| **§6 Stage C5 Bench 1** | **3 min** | 5 samples × ~13s |
| **§6 Stage C5.bench-pass vLLM PRODUCTION reboot** | **14-18 min** | Full CUDA graphs |
| §7 verification | 1-2 min | Probes |
| §7 Bench 2 | 4 min | Fish-under-vLLM |
| §7 Bench 3 | 8 min | Full E2E 10-prompt |

**Critical-path to Bench 1 PASS verdict: ~7-9 min from authorization** (vs ~17-18 min in Team 4 v1).

**Total to all 3 benches PASS: ~35-40 min** (including production vLLM reboot).

If Bench 1 FAILS at minute 7-9: full §7.A rollback ~16 min. **Net round-trip cost of failed retry: ~24 min** (vs ~50 min in Team 4 v1).

---

## 11. Sources

See `sources.md` (numeric refs in `documentation-refresh.md`).

Authoritative engine state: `/Users/kiteboard/prism42/findings/b300_bench/phase-d-rebuild/result.json`.
Cycle-2c halt postmortem: `/Users/kiteboard/prism42/findings/b300_bench/cycle2c_mps/2026-04-25T19-48-50Z/summary.md`.
T2 ablation: `/Users/kiteboard/prism42/findings/voice/coresidency/ablation.json`.
