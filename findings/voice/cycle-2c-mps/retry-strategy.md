# Cycle-2c retry strategy — single-page

Compiled 2026-04-25 evening, after the cycle-2c halt postmortem. Distills `runbook-v2.md` and `documentation-refresh.md` to the minimum-viable retry plan.

---

## 1. Smallest reversible step set (8 atomic stages)

Each stage is one classifier-judgeable atomic unit. Cost-of-stopping is bounded at every K.

| K | Stage | Wall-clock | Cost-of-stopping-here |
|---|---|---|---|
| **0** | §3 Pre-flight (10 read-only probes, no state change) | 30 s | $0 — pure inspection |
| **1** | §4 Stage A1-A4 — stop 4 services individually with classifier-safe probes between each | 60 s | One vLLM cold-reboot (~14 min) to restore baseline |
| **2** | §5 Stage B1 — `nvidia-smi -c EXCLUSIVE_PROCESS` (compute mode change) | 5 s | Same as K=1 + `nvidia-smi -c DEFAULT` (5 s) |
| **3** | §5 Stage B2-B3 — pre-create dirs + start MPS daemon | 15 s | Same as K=2 + `quit` daemon (5 s) |
| **4** | §6 Stage C1 — Fish drop-in + restart with priority=0 | 60 s | Same as K=3 + remove drop-in (5 s) + restart Fish (35 s) |
| **5** | §6 Stage C2 — Parakeet relaunch with inline env priority=0 | 10 s | Same as K=4 + Parakeet restart (5 s) |
| **6** | §6 Stage C3 — **vLLM PROBE-MODE relaunch with `--enforce-eager` and priority=1** | **3-5 min** | Same as K=5 + vLLM cold-reboot (~14 min if production mode) — TOTAL ~16 min |
| **7** | §6 Stage C4 — Worker drop-in + restart priority=1 | 10 s | Same as K=6 + remove drop-in + restart worker |
| **8** | §6 Stage C5 — Bench 1 (Fish-alone post-MPS) | 3 min | If FAIL: full §7.A rollback ~16 min |

**The hard ship-by gate is K=8.** Bench 1 PASS unlocks the production vLLM relaunch (Stage C5.bench-pass, 14-18 min) + Bench 2 + Bench 3.

If Bench 1 FAILS at K=8: the cost is ~16 min to restore baseline. Total round-trip cost of a failed retry: ~24 min.

If Bench 1 PASSES at K=8: ~14-18 min production vLLM reboot, then ~12 min for Bench 2+3. Total to "cycle-2c verdict landed": ~32-40 min.

---

## 2. Permission grants the user needs to pre-approve (exact patterns)

Group these into ONE grant block before kickoff. The classifier should see these as approved before each is invoked.

### One-time grants (5 commands; each runs once)

```bash
# G1: Compute mode flip (privileged GPU op, one-time)
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c EXCLUSIVE_PROCESS'

# G2: Compute mode restore (rollback-only)
ssh prism-mla-b300-h4h5 'sudo nvidia-smi -i 0 -c DEFAULT'

# G3: MPS daemon dirs (one-time)
ssh prism-mla-b300-h4h5 'sudo mkdir -p /tmp/nvidia-mps /var/log/nvidia-mps'

# G4: MPS daemon launch (one-time)
ssh prism-mla-b300-h4h5 'sudo CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps CUDA_MPS_LOG_DIRECTORY=/var/log/nvidia-mps nvidia-cuda-mps-control -d'

# G5: MPS daemon quit (rollback-only)
ssh prism-mla-b300-h4h5 'echo quit | sudo nvidia-cuda-mps-control'
```

### Recurring grants (repeated per service per stage)

```bash
# G6: systemctl stop/start prism42-fish (run once forward, once on rollback if needed)
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-fish'
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish'

# G7: systemctl stop/start prism42-worker (same pattern)
ssh prism-mla-b300-h4h5 'sudo systemctl stop prism42-worker'
ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-worker'

# G8: pkill (always with || true to avoid set -e + pkill silent-fail)
ssh prism-mla-b300-h4h5 'pkill -TERM -f "vllm.*serve" || true'
ssh prism-mla-b300-h4h5 'pkill -TERM -f "parakeet/server.py" || true'

# G9: systemd drop-in writes (one-time forward, one-time rollback)
ssh prism-mla-b300-h4h5 'sudo mkdir -p /etc/systemd/system/prism42-fish.service.d'
ssh prism-mla-b300-h4h5 "sudo tee /etc/systemd/system/prism42-fish.service.d/30-mps.conf >/dev/null <<'CONF' [...]"
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-fish.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo mkdir -p /etc/systemd/system/prism42-worker.service.d'
ssh prism-mla-b300-h4h5 "sudo tee /etc/systemd/system/prism42-worker.service.d/30-mps.conf >/dev/null <<'CONF' [...]"
ssh prism-mla-b300-h4h5 'sudo rm -f /etc/systemd/system/prism42-worker.service.d/30-mps.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload'

# G10: vLLM relaunch (run once forward in probe mode; once forward in production mode; once on rollback)
# Long; see runbook-v2 §6 for the full inline command.

# G11: Parakeet relaunch (run once forward; once on rollback)
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/parakeet && [...] nohup [...] & disown'

# G12: Stale pipe-dir cleanup (rollback-only)
ssh prism-mla-b300-h4h5 'sudo rm -rf /tmp/nvidia-mps'
```

### Read-only probes (NO grant required, classifier-safe)

All §3 / §4-verify / §5-verify / §6-verify / §7 probes use ONLY these patterns:

- `pgrep -a <name>`
- `curl -sf -m 5 http://...`
- `[ -S /path/socket ]` or `[ -d /path/dir ]`
- `tr '\0' '\n' < /proc/<pid>/environ`
- `nvidia-smi --query-gpu=<col> --format=csv,noheader`
- `ps -o user= -p <pid>`
- `pgrep -af "..." | head -N`
- `echo "get_server_list" | nvidia-cuda-mps-control` (read-only daemon socket query)
- `echo "ps" | nvidia-cuda-mps-control`

These should NEVER need grants. If the classifier blocks any of them, that's the bug — escalate immediately rather than retry.

---

## 3. Bench protocol (no `systemctl is-active`)

| Bench | Drives | Probes | Pass-gate |
|---|---|---|---|
| **Bench 1 — Fish-alone post-MPS** | T2 protocol on Fish (chunk_length=200, seed=911, temp=0.1, top_p=0.7, use_memory_cache=on, "Nine one one, what is your location and emergency?"); N=5 | `curl /v1/tts` for samples; capture `total_ms_p50`, `rtf_p50` to JSON | RTF p50 in [1.95, 2.10] |
| **Bench 2 — Fish-under-vLLM** | T2 protocol Fish + concurrent T2 protocol vLLM (back-to-back streaming, max_tokens=300, ~36 in-flight); N=5 | curl for both; capture | Fish RTF p50 ≤ 2.5 (Strong) or ≤ 2.9 + vLLM TPOT ≤ +25% (Acceptable) |
| **Bench 3 — Full-stack 10-prompt** | `synthetic_caller_full.py` shape, 10 PSAP prompts (P1×3, P2×3, P3×2, P4×2) | `aggregate_metrics.py` on resulting JSON; capture `publish_end_to_first_useful_audio_ms` | p50 < 4500 ms AND p95 < 7000 ms (Strong) or p50 < 5500 ms (Acceptable) |

All bench probes are HTTP curl (Probe-1 family). Zero `systemctl is-active`. Zero `nvidia-smi -q -d COMPUTE | grep`.

---

## 4. Abort-and-rollback decision tree

```
Stage K result
├── PASS → next stage
├── PARTIAL (some sub-probe FAIL) → run per-stage rollback, halt
└── FAIL → run per-stage rollback FROM stage K back to stage 0 (or to last green checkpoint)
                      ↓
             If per-stage rollback FAILS:
                      ↓
             §7.A emergency rollback (~16 min full reset)
                      ↓
             Verify baseline restored (Probe-1 family for all 4 services)
                      ↓
             If baseline NOT restored after §7.A:
                      ↓
             ESCALATE — manual integrator intervention required, do NOT retry
```

### Specific abort signals → action

| Signal | Stage | Action |
|---|---|---|
| Pre-flight §3 fails any check | K=0 | Halt; do not touch state. |
| `pgrep -a nvidia-cuda-mps-control` returns no PID after §5 B3 | K=3 | Per-stage rollback B3 (`echo quit \| sudo nvidia-cuda-mps-control`) + B1 (`-c DEFAULT`); investigate daemon log at `/var/log/nvidia-mps/`. |
| Fish HTTP 200 not seen within 60s after §6 C1 | K=4 | Per-stage rollback C1 (remove drop-in + restart Fish); halt. |
| vLLM HTTP `/v1/models` 200 not seen within 10 min after §6 C3 (**eager mode**) | K=6 | Per-stage rollback C3 (kill vLLM); investigate `/tmp/prism42-logs/vllm.log`; if FlashInfer error, try R14 (downgrade 0.6.9→0.6.8); if persistent, §7.A. |
| Bench 1 RTF p50 > 2.15 | K=8 | §7.A emergency rollback; cycle-2c verdict = FAIL_INTRINSIC_OVERHEAD; do not retry without different MPS approach. |
| vLLM HTTP `/v1/models` 200 not seen within 20 min after C5.bench-pass production reboot | post-K=8 | §7.A emergency rollback. Production-mode CUDA-graph-capture failure. |
| Bench 2 Fish RTF p50 > 2.9 OR vLLM TPOT > +25% | post-K=8 | §7.A emergency rollback; verdict = FAIL_TRADE_OFF_NEGATIVE; consider MLOPart upgrade (CUDA 13.1) or T4 P4 GPU-split. |
| Bench 3 p50 ≥ 5500 ms OR exit-code-5 hung turn | post-K=8 | §7.A emergency rollback; verdict = FAIL_E2E. |

---

## 5. Predicted gain reconciled with 2026-04-15→25 findings

### Team M's predicted Fish RTF p50 under all-busy: **2.4 - 2.9 (range)**

This was based on:
1. NVIDIA's MLOPart benchmark on B200 (atomic-ops, not vLLM): 36% latency cut [src 5]. Team M correctly noted this is the CEILING for hard partitioning, not basic-MPS-priority-hint.
2. Pebble case study: vLLM under MPS loses 7.5% throughput, gains 19.5% TPOT. Cost-side; Fish (HIGH priority) gets the benefit.
3. NVIDIA forum: stream priority is a hint, not preemption — wins occur at scheduling boundaries, not via preemption.

### Has anything published since changed Team M's prediction?

- **MLOPart shipped on CUDA 13.1 in 2025-12-04** (NOT in the last 10 days; older than Team M's runbook). Pod is still 13.0. **No upgrade pressure from the 10-day window.**
- **Static SM partitioning shipped on CUDA 13.1.** New finding; Team M did not enumerate this. **Does not affect today's retry on CUDA 13.0.**
- **FlashInfer 0.6.9 (2026-04-24, yesterday) added SM_103 mm_M1 path; 0.6.8 (2026-04-16) cut FP64 from sampling on SM103.** Material for B300 (FP64-gutted), but unrelated to MPS specifically. Engine state is already current. **No prediction change.**
- **Allen Kuo Apr 8 RTX PRO 6000 number: `--enforce-eager` cost is 40% TPS, 97% TTFT, 44% concurrent throughput.** This DOES change the strategy (probe-mode → production-mode 2-step instead of 1-step), but does not change the Fish RTF prediction.

**Reconciled prediction:** Fish RTF p50 **2.4 - 2.9 under all-busy** stands. No new evidence to widen the band higher or lower.

### MLOPart upgrade path documentation (next-cycle prep, not this retry)

If basic MPS yields RTF p50 > 2.9 (FAIL trade-off), the next escalation is:

1. Upgrade pod to CUDA 13.1 (significant: nvcc + cuBLAS + cuFFT + cuSOLVER + cuSPARSE + nvcurand reinstall; full toolchain rebuild of vLLM ~35 min per phase-d-rebuild).
2. EITHER
   - **MLOPart path:** `start_server -uid <uid> -mlopart`. Hardware split along die boundaries on B300. Each MPS client sees N "smaller" virtual GPUs. **Risk:** vLLM (which expects 1 device with full tensor-parallel-size=1) may require code change to attach to a specific MLOPart sub-device. Untested.
   - **Static SM partitioning path:** `nvidia-cuda-mps-control -d -S` then `sm_partition add <uuid> <chunks>`. Asymmetric: 50% to vLLM, 25% Fish, 15% Parakeet, 10% worker. **Better for our asymmetric workload.** Untested with vLLM-class workloads in public docs.

These are fundamentally a separate research cycle. **Do not bundle MLOPart with cycle-2c retry.** This retry is basic-MPS-only.

---

## 6. Recommended retry strategy (one paragraph)

Run the 8-stage runbook-v2 sequentially with one classifier-safe probe between each stage and per-stage rollback at every K. Use `--enforce-eager` on the **first** vLLM relaunch (Stage C3) to land Bench 1 in 7-9 min from authorization (vs 17-18 min in Team M v1). If Bench 1 PASSES (Fish RTF p50 in [1.95, 2.10]), drop `--enforce-eager` and pay the 14-18 min production cold-reboot before Bench 2. If Bench 1 FAILS, run §7.A emergency rollback (~16 min), accept verdict FAIL_INTRINSIC_OVERHEAD, and do NOT retry without a different MPS approach. The total round-trip cost of a failed retry is ~24 min (vs ~50 min in Team M v1). The 8-stage decomposition + classifier-safe probes (5 families: HTTP, pgrep, fs, /proc/environ, nvidia-smi --query-...) eliminate the auto-mode classifier collision that halted today. Pre-approve the 5 one-time + 7 recurring command patterns in §2; everything else is read-only and should never need a grant. Do not bundle MLOPart or static-partitioning into this retry — those require CUDA 13.1, which the pod doesn't have, and they are a separate research cycle.

---

## 7. Sources

`runbook-v2.md` and `documentation-refresh.md` in this directory; numeric refs in `sources.md`.
