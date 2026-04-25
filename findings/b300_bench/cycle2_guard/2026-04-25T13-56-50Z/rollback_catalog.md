# Cycle-2 rollback catalog

UTC capture: 2026-04-25T13-56-50Z
Pod: `prism-mla-b300-h4h5` (B300 SXM6 AC, sm_103, driver 580.126.09, CUDA 13.0).
Baseline worker.py SHA: `42c8d2e8b5930c470fb04c3b0ee0834158ad66090d6c524bd3dd283b9186d3ab`.
All commands `bash -n` syntax-verified. None executed by sentinel.

---

## 1. Cycle-2d Fish FlashAttention patch — rollback

**Mutation scope:** `recipe.patch` modifies 2 files in the upstream Fish-Speech repo:
- `fish_speech/models/text2semantic/inference.py` (1 hunk, +14 LoC)
- `fish_speech/models/text2semantic/llama.py` (3 hunks, +30 LoC)

**Application location:** the Fish source tree on the **pod** at `/opt/prism42/infra/b300/services/fish-speech/src/`. This IS a git checkout (`origin = https://github.com/fishaudio/fish-speech.git`, HEAD = `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`). Local `vendor/fish-speech/` does NOT exist (gitignored, never created); the recipe.md verification line about `/Users/kiteboard/prism42/vendor/fish-speech` predates that confirmation.

**Editable install:** `pip show fish-speech` reports `Editable project location: /opt/prism42/infra/b300/services/fish-speech/src` — patch edits take effect on Fish service restart, no rebuild step. `.venv-nightly` is the active venv.

### Rollback commands

```bash
# 1. Discard the edits in the editable git checkout (returns the two
#    modified files to their HEAD state at SHA 3dd1f85).
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech/src && git checkout HEAD -- fish_speech/models/text2semantic/inference.py fish_speech/models/text2semantic/llama.py'

# 2. Verify clean checkout matches expected SHA.
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech/src && git status -s fish_speech/ && git rev-parse HEAD'
# expected: empty `git status -s` line, and HEAD = 3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139

# 3. Restart Fish service so the editable import re-loads pristine code.
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-fish'

# 4. Wait for the service to come up + health-check.
ssh prism-mla-b300-h4h5 'for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf -o /dev/null http://127.0.0.1:9200/ && echo "fish-up after ${i}s" && break; sleep 1; done'
```

**Expected exit-success signal:** `git status -s` empty, `git rev-parse HEAD` = `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`, `curl http://127.0.0.1:9200/` returns `200` within 10 s.

**Time-to-recover estimate:** 5-15 s (Fish loads from RAM; checkpoint already on disk). NO 14-min cold-start cost — Fish is much smaller than vLLM.

---

## 2. Cycle-2c CUDA-MPS — rollback (canonical, copied verbatim)

Source: `findings/voice/cycle-2c-mps/runbook.md` §6 "Rollback procedure" (Team M's deliverable).

**Mutation scope:** install `nvidia-cuda-mps-control` daemon + flip GPU compute mode to `EXCLUSIVE_PROCESS` + restart all 4 services with `CUDA_MPS_PIPE_DIRECTORY` and `CUDA_MPS_CLIENT_PRIORITY` envs.

### Rollback commands (verbatim from runbook §6)

```bash
# 6.1. Stop all 4 services first (clean MPS client disconnect)
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-fish prism42-worker'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" ; pkill -TERM -f parakeet'
ssh prism-mla-b300-h4h5 'while pgrep -f "fish|parakeet|vllm|prism42-worker" > /dev/null; do sleep 1; done'

# 6.2. Quit daemon (waits for clients to drain)
ssh prism-mla-b300-h4h5 'echo quit | sudo nvidia-cuda-mps-control'
ssh prism-mla-b300-h4h5 'sleep 2 && pgrep -a nvidia-cuda-mps-control || echo daemon-stopped'

# 6.3. Restore compute mode to DEFAULT
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c DEFAULT'
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
# expected: "Default"

# 6.4. Clear stale pipe-dir
ssh prism-mla-b300-h4h5 'sudo rm -rf /tmp/nvidia-mps'

# 6.5. Restart services WITHOUT CUDA_MPS_* env vars
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish prism42-worker'
# vLLM relaunch: use the canonical command from state/vllm_cmdline.txt:
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech && nohup .venv-nightly/bin/vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --served-model-name nemotron-nano --trust-remote-code --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8 --gpu-memory-utilization 0.20 --kv-cache-dtype fp8 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py --reasoning-parser nano_v3 --enable-prefix-caching --port 8001 --host 127.0.0.1 > /tmp/prism42-logs/vllm.log 2>&1 &disown'
# Parakeet relaunch (no systemd unit; nohup on pid 236296 was relaunched by the same pattern earlier today):
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && nohup .venv/bin/python server.py > /tmp/prism42-logs/parakeet.log 2>&1 &disown'

# 6.6. Verify
ssh prism-mla-b300-h4h5 'nvidia-smi -q -d COMPUTE | grep "Compute Mode"'
# expected: "Default"
ssh prism-mla-b300-h4h5 'pgrep -a nvidia-cuda-mps-control || echo no-daemon'
# expected: empty / "no-daemon"
```

**Expected exit-success signal:** Compute Mode = `Default`, no `nvidia-cuda-mps-control` daemon, all 4 services healthy via `health_check.sh`.

**Time-to-recover estimate:** ~14 min (vLLM CUDA-graph capture is the long pole). Fish + Parakeet + worker each <30 s. Budget for this in any cycle-2c rollback. Canonical citation: runbook.md §6 "vLLM will pay the 14-min CUDA-graph capture cost again on this restart. Budget for it."

---

## 3. Cycle-2e orchestrator/worker patch — rollback

**Mutation scope:** subclass `BufferedDispatcherAgent(Agent)` added to `agents/livekit/orchestrator.py` (and minor telemetry hooks in `worker.py`). Exact retrofit map: `findings/voice/cycle-2e-pipecat/worker-target-locations.md`.

**Backup expectation:** the cycle-2e executor is contracted to write `worker.py.pre-cycle2e` AND `orchestrator.py.pre-cycle2e` before mutating. Rollback = restore both backups + restart worker.

### Rollback commands

```bash
# 1. Restore orchestrator.py from .pre-cycle2e backup
ssh prism-mla-b300-h4h5 'sudo cp /opt/prism42/agents/livekit/orchestrator.py.pre-cycle2e /opt/prism42/agents/livekit/orchestrator.py'

# 2. Restore worker.py from .pre-cycle2e backup (this preserves Fix 1 + Fix 2 + cycle-2a edit which are already in the .pre-cycle2e snapshot — confirmed by current SHA 42c8d2e8...)
ssh prism-mla-b300-h4h5 'sudo cp /opt/prism42/agents/livekit/worker.py.pre-cycle2e /opt/prism42/agents/livekit/worker.py'

# 3. Verify SHA matches today's baseline
ssh prism-mla-b300-h4h5 'sha256sum /opt/prism42/agents/livekit/worker.py'
# expected: 42c8d2e8b5930c470fb04c3b0ee0834158ad66090d6c524bd3dd283b9186d3ab  /opt/prism42/agents/livekit/worker.py

# 4. Restart worker
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-worker'

# 5. Verify worker active
ssh prism-mla-b300-h4h5 'systemctl is-active prism42-worker'
# expected: active
```

**Expected exit-success signal:** `sha256sum worker.py` matches `42c8d2e8b5930c470fb04c3b0ee0834158ad66090d6c524bd3dd283b9186d3ab`, `systemctl is-active prism42-worker` = `active`, watchdog clean.

**Fallback if `.pre-cycle2e` backup is missing:** restore from the pre-existing `.pre-cycle2a` backup which contains Fix 1 (line 358 `enable_thinking=False`) + Fix 2 (caller_spoke gate at lines 783-797) + cycle-2a edit (line 799 preroll-disabled). Note: this fallback loses any Fix 3 the executor planned; it's a strict regression to the 13:07 UTC state, not the 14:00 UTC state. SHA of `.pre-cycle2a` should match today's pre-mutation SHA = `42c8d2e8...`.

```bash
# Fallback rollback (only if .pre-cycle2e missing):
ssh prism-mla-b300-h4h5 'sudo cp /opt/prism42/agents/livekit/worker.py.pre-cycle2a /opt/prism42/agents/livekit/worker.py'
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-worker'
```

**Time-to-recover estimate:** 5-10 s (Python import + systemd restart). No vLLM impact.

---

## 4. Verification table

| Cycle | Mutation | Backup file | Restore method | Time-to-recover | bash -n |
|---|---|---|---|---|---|
| 2d | Fish FA + drop-mask patch | git tracked at SHA 3dd1f85 | `git checkout HEAD -- fish_speech/...` + `systemctl restart prism42-fish` | 5-15 s | PASS |
| 2c | MPS daemon + EXCLUSIVE_PROCESS | (none — config change) | quit daemon → `nvidia-smi -c DEFAULT` → relaunch all 4 services | ~14 min (vLLM cold reboot) | PASS |
| 2e | orchestrator.py BufferedDispatcherAgent | `.pre-cycle2e` (executor must write) | `cp .pre-cycle2e ./` + `systemctl restart prism42-worker` | 5-10 s | PASS |

**`bash -n` verification command (re-runnable):**

```bash
for f in /tmp/cycle2d_rollback.sh /tmp/cycle2c_rollback.sh /tmp/cycle2e_rollback.sh; do
    bash -n "$f" && echo "OK $f" || echo "FAIL $f"
done
```

(All three fragments above are already extracted into separate `*.sh` files alongside this catalog so the integrator can `bash -n` each one.)

---

## 5. Pre-existing recovery anchors (do not lose these)

- `/opt/prism42/agents/livekit/worker.py.pre-cycle1` (root-owned, 48437 bytes, 12:34 UTC) — original pre-Fix-1 snapshot
- `/opt/prism42/agents/livekit/worker.py.pre-cycle2a` (root-owned, 50015 bytes, 13:07 UTC) — Fix 1 + Fix 2 + (just before) cycle-2a edit
- `/opt/prism42/infra/b300/services/fish-speech/src/.git/` — full git history; `git checkout HEAD --` is safe regardless of which Fish files cycle-2d touches
- vLLM cmdline preserved at `state/vllm_cmdline.txt` so a full vLLM relaunch is reproducible after MPS rollback
