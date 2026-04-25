# Cycle-2 baseline-sentinel snapshot

UTC: `2026-04-25T13-56-50Z`
Pod: `prism-mla-b300-h4h5` (B300 SXM6 AC, sm_103, driver 580.126.09, CUDA 13.0)
Sentinel role: read-only / capture-only. NO mutations applied.

---

## Health verdict: GREEN

All 4 services confirmed healthy. Watchdog (`health_check.sh`) ran clean on first invocation:

```
OK   worker.systemd
OK   fish.systemd
OK   fish.http
OK   parakeet.http
OK   vllm.http
OK   vllm.pid
=== PASS: all 4 services green ===
```

Mutating executors are AUTHORIZED to proceed.

---

## State surface (frozen as of capture)

### worker.py (livekit dispatcher)

- Path: `/opt/prism42/agents/livekit/worker.py`
- Owner: `shadeform:shadeform`, 49793 bytes, mtime 13:07 UTC
- SHA256: `42c8d2e8b5930c470fb04c3b0ee0834158ad66090d6c524bd3dd283b9186d3ab` (this is THE pre-cycle-2-mutation reference SHA — every executor must compare against this before mutating)
- Verified content markers:
  - **Fix 1** (line 358): `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` — PRESENT
  - **Fix 2** (lines 783-797): `caller_spoke.wait()` gate with race-window `is_set()` follow-up — PRESENT
  - **Cycle-2a edit** (line 799): `log.info("preroll.disabled_for_demo", session_id=session_id)` — PRESENT
- Backups on disk:
  - `worker.py.pre-cycle1` (root, 48437 bytes, 12:34 UTC) — pre-Fix-1 original
  - `worker.py.pre-cycle2a` (root, 50015 bytes, 13:07 UTC) — Fix 1 + Fix 2 + immediately-pre-cycle-2a-edit (same SHA family as today's HEAD)

### vLLM serve (Nemotron-Nano)

- Parent pid: 285669; CUDA child (`VLLM::EngineCore`): 285796 (~56,602 MiB GPU mem)
- Port: 127.0.0.1:8001
- Cmdline (full):
  ```
  /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/python
  /opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/vllm serve
  nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
  --served-model-name nemotron-nano --trust-remote-code
  --tensor-parallel-size 1 --max-model-len 32768 --max-num-seqs 8
  --gpu-memory-utilization 0.20 --kv-cache-dtype fp8
  --enable-auto-tool-choice --tool-call-parser qwen3_coder
  --reasoning-parser-plugin /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py
  --reasoning-parser nano_v3 --enable-prefix-caching
  --port 8001 --host 127.0.0.1
  ```
- Process env keynames captured (no values; see `state/vllm_env_keynames.txt`):
  - vLLM-flavor: `VLLM_ATTENTION_BACKEND`, `VLLM_USE_FLASHINFER_MOE_FP4`, `VLLM_FLASHINFER_MOE_BACKEND`, `VLLM_WORKER_MULTIPROC_METHOD`
  - PyTorch: `PYTORCH_CUDA_ALLOC_CONF`, `TORCH_CUDA_ARCH_LIST`, `CUDA_HOME`
  - SSH transport (passive): `SSH_AUTH_SOCK`, `SSH_CONNECTION`, `SSH_CLIENT`
  - No credential-shaped names observed.
- Health: `curl /v1/models` → 200 in <1 ms
- Cold-reboot cost: 14 min CUDA-graph capture (per cycle-2c runbook)

### Fish-Speech S2-Pro TTS

- systemd: `prism42-fish.service` (active)
- Drop-ins: `10-vllm-model.conf` (`VLLM_MODEL=nemotron-nano`), `20-vllm-max-tokens.conf` (`VLLM_MAX_COMPLETION_TOKENS=1024`) — note these envs are owned by the Fish unit but consumed downstream
- Port: 127.0.0.1:9200
- Source: editable git checkout at `/opt/prism42/infra/b300/services/fish-speech/src/`
  - Remote: `https://github.com/fishaudio/fish-speech.git`
  - HEAD: `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`
- Venv: `.venv-nightly` (active), `.venv` (legacy, retained)
- pip: `fish-speech 2.0.0` editable, location `/opt/prism42/infra/b300/services/fish-speech/.venv-nightly/lib/python3.12/site-packages`
- GPU mem (CUDA child pid 217878): 20,068 MiB
- Health: HTTP root → 200 (Swagger UI page); `/healthz` is 404 (no separate health endpoint exposed, root-200 is the live signal)

### Parakeet TDT v3 STT

- systemd: **NONE** (no `parakeet*` unit on the system; this differs from prompt's expectation)
- Process: nohup-launched bash supervisor (pid 236295) → `python server.py` (pid 236296)
- Working dir: `/opt/prism42/infra/b300/services/parakeet/`
- Port: 127.0.0.1:9100
- GPU mem: 5,924 MiB
- Health: `/healthz` returns `{"status":"ok","model":"nvidia/parakeet-tdt-0.6b-v3","sample_rate":16000,"streaming":true,"interim_interval_ms":160}`
- **Operational note for executors:** any cycle that intends to "restart all 4 services" cannot use `systemctl restart parakeet` — it must `pkill -TERM -f parakeet` and relaunch via the canonical `nohup .venv/bin/python server.py` pattern (already memorialized in `state/health_baseline.txt` and the cycle-2c runbook). Watchdog measures Parakeet via HTTP probe, not systemd.

### prism42-worker (LiveKit Agent worker)

- systemd: `prism42-worker.service` (active)
- Drop-ins: `10-vllm-model.conf`, `20-vllm-max-tokens.conf` (same shape as Fish — both units share these env-overlays)
- Endpoint: LiveKit Cloud signaling (`livekit.thegoatnote.com`) — not a local port

### GPU state

- 1× B300 SXM6 AC, sm_103, driver 580.126.09
- VRAM: 88,474 / 275,040 MiB used (32%) — comfortable headroom
- Util: 0% at capture time (idle between turns)
- Compute apps:
  - 285796 `VLLM::EngineCore` 56,602 MiB
  - 217878 `fish-speech .venv` 20,068 MiB
  - 236296 `parakeet .venv` 5,924 MiB
  - 173799 `.venv` 5,834 MiB (likely worker)
- Compute mode: `Default` (not yet `EXCLUSIVE_PROCESS` — confirms cycle-2c MPS not yet activated)

---

## Discrepancies vs. mission prompt

1. **Parakeet is NOT a systemd unit.** The prompt expected `systemctl is-active prism42-worker prism42-fish parakeet` to read `active active active`; the third name returns `inactive` because no such unit exists. Parakeet is a nohup-launched python process. The watchdog uses an HTTP probe for Parakeet (`/healthz` substring match on `parakeet-tdt-0.6b-v3`) which is the truthful signal. Reported here so the executor does not mistake it for a service-down condition.
2. **Local `vendor/fish-speech/` does not exist.** The cycle-2d recipe.md documents `git apply --check` against `/Users/kiteboard/prism42/vendor/fish-speech` which is gitignored and never created on this machine. The Fish source is a git checkout on the **pod** at `/opt/prism42/infra/b300/services/fish-speech/src/` (HEAD = `3dd1f85`). Cycle-2d will need to apply on the pod, not locally. Rollback catalog reflects this.

Both are documented for the executor's awareness; neither blocks the campaign.

---

## Acceptance checklist

- [x] All 4 services confirmed healthy at baseline (worker, fish, parakeet, vllm — see watchdog output above)
- [x] Rollback commands syntax-verified (`bash -n PASS` for all 3: cycle2c, cycle2d, cycle2e)
- [x] `health_check.sh` runs clean on first invocation
- [x] No secret values printed (only env keynames recorded)
- [x] No mutations applied (read-only sentinel)

---

## Files in this snapshot

- `baseline.md` — this file
- `rollback_catalog.md` — per-cycle rollback commands with bash -n verification
- `health_check.sh` — re-runnable 4-service watchdog (exit 0 = green)
- `cycle2c_rollback.sh`, `cycle2d_rollback.sh`, `cycle2e_rollback.sh` — extracted rollback scripts (also embedded in catalog)
- `state/worker_sha.txt` — pre-cycle-2 worker.py SHA
- `state/worker_evidence.txt` — verified content markers + backup file inventory
- `state/fish_systemd.txt` — `systemctl cat prism42-fish` (full unit + drop-ins)
- `state/vllm_cmdline.txt` — exact vLLM cmdline (for relaunch after MPS rollback)
- `state/vllm_env_keynames.txt` — vLLM env variable NAMES only (no values, secrets-safe)
- `state/worker_dropins.txt` — prism42-worker.service.d drop-ins
- `state/gpu_snapshot.txt` — nvidia-smi inventory + compute-apps
- `state/cuda_processes.txt` — CUDA-attached process list
- `state/health_baseline.txt` — full service-health probe output

---

## Hand-off contract

Any cycle-2 executor (2c, 2d, 2e) MUST:

1. Run `./health_check.sh` BEFORE its mutation. Halt if non-zero exit.
2. Apply mutation per its task.
3. Run `./health_check.sh` AFTER its mutation. If non-zero, run the corresponding rollback script from this catalog.
4. Re-run `./health_check.sh` after rollback. Continue rolling back (next-deeper backup) until green.

Sentinel is on standby through campaign Phase 1.
