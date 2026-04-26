# Cycle-2X — Autonomic Ops Charter (Team X)

**Status:** SPEC ONLY. No code executed against the pod. No services touched. The integrator decides when (and whether) to deploy.
**Author:** Team X, 2026-04-26
**Scope:** Design the always-on, Claude-orchestrated control plane that wraps the prism42 voice stack — heartbeat + ralph-loop, agent-orchestrated GPU-direct storage, on-demand Nsight profiling, `cuda-checkpoint`-driven elasticity, and cuTILE-aware kernel-shape steering.

---

## 1. Problem statement

The voice stack today is **observable but not autonomic**. Eight things break in a way the integrator finds out about only after a degraded call:

1. vLLM cold-restarts take ~62 s — and the worker dies silent if `:8001` returns 5xx.
2. Fish TTS spike (utterance queue depth > 3) starves vLLM of HBM until somebody opens `nvidia-smi`.
3. Auto-Mode classifier blocked a multi-service shutdown last cycle (memory note `prism42_b300_voice_durable_findings.md`); we still have no agent-side guard against multi-service shutdowns.
4. No structured heartbeat into the LiveKit data plane; the frontend renders FSM via `dispatch_publisher.py` but has no view of GPU memory, kernel shapes, or service health.
5. Nsight profiling is human-driven (somebody SSHes in, runs `nsys profile -t cuda,nvtx,cudnn,cublas`). Reports get parsed by hand or not at all.
6. `cuda-checkpoint` exists on driver 570+ (we are on driver 580) but is not wired — we have **resiliency** (services restart on crash) without **elasticity** (no live workload migration, no pause-and-resume).
7. Kernel-tile shapes are picked by FlashInfer / CUTLASS auto-tuners that have **no idea** the workload is `batch=1, ctx=32k, NVFP4, MoE 30B-A3B`. The autotuner sees a generic prompt and picks generically.
8. The LiveKit Cloud rollback (`restore.sh`) is the only safety net and it is human-triggered.

The mission is **not** to put Claude inside the voice critical path. The mission is to put a Claude-orchestrated **sidecar** beside it that observes, diagnoses, and — within bounded gates — repairs.

---

## 2. Pillar 1 — Heartbeat + ralph-loop (small effort)

**Pattern source.** SG2's ralph-loop pattern (`scripts/ralph_loop.sh` archetype, memory task #115): an outer bash loop wrapping a Claude session that drives one bounded objective per iteration, writes structured artifacts, halts on budget or invariant violation. Adapted here as a **Managed Agent session** + a thin host-side supervisor that respects the existing single-service-at-a-time discipline from `prism42_b300_voice_durable_findings.md`.

**Agent design.**
- One **coordinator** Managed Agent (`claude.beta.agents.create(model="claude-opus-4-7", tools=[agent_toolset_20260401, ...custom...])`), beta header `managed-agents-2026-04-01`. Single agent — `callable_agents` is silently stripped on this workspace per CLAUDE.md §8 and memory note `managed_agents_multi_agent_verified.md`. Upgrade path documented in `agent-skeleton.py`.
- Cadence: 30-second heartbeat tick (configurable via `PRISM42_AUTONOMIC_TICK_S`). Lower bound 10 s to stay below LiveKit's keepalive; upper bound 5 min to keep MTTD < 1 turn for a typical 911 call.
- Per tick the agent:
  1. Reads telemetry via `nvidia-smi` (custom tool), `journalctl -u prism42-worker -n 50 --since "60 seconds ago"` (custom tool), `:8001/health` (custom tool, read-only HTTP).
  2. Emits a `prism42.heartbeat` data-track event onto the LiveKit room (mirroring `dispatch_publisher.py`'s topic-segmented additive pattern).
  3. Classifies state into one of `nominal | warn | degraded | failing`.
  4. On `warn` or worse: writes a structured incident JSON to `findings/voice/cycle2X_autonomic_ops/incidents/<ts>.json` + emits a `prism42.alert` event. **Does not auto-act unless the incident matches an allow-listed recovery rule (see below).**

**Failure-mode catalog** (each row is one allowed auto-recovery rule; everything else escalates to a human gate).

| Symptom | Detector | Auto-recovery (G_n) | Escalation |
|---|---|---|---|
| `prism42-worker` exits within 10 s of start | `journalctl` parse | none — hold + alert | always escalate |
| `vllm :8001/health` 5xx for >2 ticks | HTTP probe | `systemctl restart prism42-vllm` (if user pre-armed `PRISM42_AUTONOMIC_AUTORESTART_VLLM=1`) | always alert; auto-act ONLY if pre-armed |
| Fish synth queue depth > 3 for >3 ticks | metrics scrape | none — emit elasticity hint (Pillar 4) | always escalate; integrator decides whether to evict vLLM |
| HBM > 85% for >5 ticks | `nvidia-smi --query-gpu=memory.used` | none — emit elasticity hint | escalate |
| LiveKit room count = 0 for > 10 min | LiveKit Cloud REST or `lk room list` | none | informational only |
| Worker re-registered with wrong URL | log grep | none — flag for `restore.sh` | always escalate |

**Bounded auto-recovery rules — the contract.**
- Auto-recovery is **OFF by default**. Each rule has its own env-flag (`PRISM42_AUTONOMIC_AUTORESTART_*`); none is auto-armed by `agent-skeleton.py`.
- Auto-recovery NEVER touches more than one service per tick (Auto-Mode classifier discipline).
- Auto-recovery NEVER runs a destructive command without a successful state-probe immediately before AND after.
- After every auto-recovery action the agent enters a 5-tick (~150 s) cooldown during which only observation is allowed.
- Three consecutive auto-recovery actions on the same service in a 30-min window halts the loop and pages the integrator.

**Citations.**
- Anthropic Managed Agents overview, fetched 2026-04-26: "the harness and infrastructure for running Claude as an autonomous agent." `https://platform.claude.com/docs/en/managed-agents/overview`.
- Anthropic generator-evaluator pattern (Rajasekaran 2026-03-24): the heartbeat agent is the *evaluator* of voice-path health; the voice path itself is the *generator*. `https://www.anthropic.com/engineering/harness-design-long-running-apps`.

---

## 3. Pillar 2 — cuFILE-equivalent, Claude-orchestrated (medium effort)

**Capability we need.** Direct-to-GPU storage paths so that:
- Model-weight prefetch into HBM bypasses CPU bounce-buffers (NVFP4 30B = ~18.6 GiB; on a cold restart we currently round-trip through page cache → host RAM → HBM, which is ~half of the 62 s cold-start budget).
- KV-cache spill, *if* HBM pressure rises, can stream to NVMe without involving the worker's Python event loop.
- Checkpoint streams (Pillar 4) can land on disk without stalling vLLM.

**Why NOT NVIDIA's reference daemon.** The cuFile / GPUDirect Storage API ships as kernel module + user library (`nvidia-fs.ko` + `libcufile.so`); per docs fetched 2026-04-26 there is **no separate userland daemon** in the canonical deployment, but the recommended NVIDIA orchestration pattern bundles cuFile under their `gds-tools` and `gds-fs` rpm — opaque, vendor-lock, and not introspectable from Python. We want the *capability*, not the orchestration layer. `https://docs.nvidia.com/gpudirect-storage/overview-guide/index.html`.

**Claude-orchestrated alternative.** The Claude managed agent owns the **policy**; the cuFile primitives stay as the **mechanism**.
- Mechanism: `kvikio` (RAPIDS) or `cuda-python`'s emerging cuFile bindings expose `cuFileRead` / `cuFileWrite` / `cuFileBatchIOSubmit` / `cuFileStreamRegister` from Python. The fetched docs enumerate these primitives. We call them directly; no NVIDIA-managed daemon required.
- Policy (the agent's job):
  - Decide *when* to prefetch weights (e.g. before a planned vLLM restart, hint via heartbeat).
  - Decide *what* to spill if HBM pressure rises (e.g. cold KV blocks before warm ones).
  - Decide *where* to stage checkpoints (NVMe scratch vs `/opt/prism42/checkpoints`).
- **Custom tool exposed to the agent**: `gds_op` with subcommands `prefetch_weights`, `spill_kv`, `stage_checkpoint`, `status`. Each subcommand wraps a standalone Python script the integrator owns; the agent never executes raw cuFile calls — it asks the script.

**Effort estimate.** Medium. The Python script that wraps `cuFileRead` / `cuFileWrite` is ~150-300 LoC and benefits from existing RAPIDS / `kvikio` bindings. The harder part is HBM-pressure modeling (Pillar 1 telemetry must already produce reliable HBM utilization numbers). De-scope from cycle-2X: actual eviction policy. Land in cycle-2Y once heartbeat is steady-state.

---

## 4. Pillar 3 — Nsight integration (small-medium effort)

**Capability we need.** Profile the running vLLM (or Fish, or Parakeet) on demand, parse the report, surface the top-N hot kernels with optimization candidates.

**Pattern.**
1. Heartbeat detects a latency anomaly (e.g. p95 TTFT regression > 20% over 30-min baseline) OR the integrator manually requests a profile via a custom tool.
2. Agent calls custom tool `nsys_profile_attach` with args `{"pid": <vllm_pid>, "duration_s": 30, "trace": "cuda,nvtx,cudnn,cublas"}`.
3. The wrapped script runs `nsys profile --gpu-metrics-devices=all --duration=30 --trace=cuda,nvtx,cudnn,cublas --output=/tmp/prism42-nsys/<ts> --force-overwrite=true --attach <pid>` (per `nsys` docs fetched 2026-04-26: trace options `cuda,nvtx,cudnn,cublas` all valid for Blackwell). `https://docs.nvidia.com/nsight-systems/UserGuide/index.html`.
4. Agent calls `nsys_export` to dump SQLite/JSON-Lines from the `.nsys-rep` (one of the supported export formats per the same docs).
5. Agent reads the export, ranks kernels by (a) total time on critical path, (b) achieved occupancy delta vs theoretical, (c) memory-bound vs compute-bound classification.
6. Agent writes a ranked recommendations file under `findings/voice/cycle2X_autonomic_ops/profiles/<ts>/recommendations.md`.

**Risk: Nsight overhead.** The NVIDIA docs explicitly call out "Significant runtime overhead may occur" for `--cuda-trace-all-apis`, `--cudabacktrace`, `--cuda-um-cpu-page-faults`. We **never** enable those. We use only `cuda,nvtx,cudnn,cublas` and disable CPU sampling (`--sample=none`). Even then, profiling vLLM during a live 911 call would be reckless.

**Mitigation: shadow profiling via cuda-checkpoint** (cycle-2Y). The agent can:
1. `cuda-checkpoint --action checkpoint --pid <vllm>` — freeze.
2. Restore the snapshot into a *parallel* vLLM process on a spare context (assuming HBM headroom from Pillar 4's policy — currently a stretch; mark as future-cycle).
3. Profile the parallel process; the live vLLM is unaffected.

If the spare-context approach is infeasible on B300 (single GPU, full HBM budget under load), fall back to scheduling profiles only during low-call windows (heartbeat already knows room count).

**Effort estimate.** Small for the on-demand profile-and-parse path. Medium-large for the shadow-profile / parallel-vLLM path. Land the simple path first.

---

## 5. Pillar 4 — `cuda-checkpoint` for elasticity (medium effort)

**Quote the user's framing.** "cuda-checkpoint for elasticity instead of resiliency which can be powerful." Resiliency = the service restarts after it crashes. Elasticity = the running workload can be paused, evicted, migrated, restored — *without* a crash. We are designing the second.

**Capability we need.** Take a running vLLM process, snapshot its full CUDA state, evict from HBM, page back in later — all without a model reload.

**Pattern.** From the cuda-checkpoint README fetched 2026-04-26 (`https://github.com/NVIDIA/cuda-checkpoint`):
- `cuda-checkpoint --action lock --pid <pid>` blocks new GPU API calls.
- `cuda-checkpoint --action checkpoint --pid <pid>` flushes pending work, copies device memory to host, releases GPU resources. The process is now CPU-resident.
- `cuda-checkpoint --action restore --pid <pid>` re-allocates GPU resources, copies host memory back to device.
- `cuda-checkpoint --action unlock --pid <pid>` resumes GPU API calls.
- `cuda-checkpoint --get-state --pid <pid>` returns the current state (used by the agent to verify each transition before proceeding).

**Driver requirement.** Driver 550+ for the basic flow; 570+ for NVML / CRIU integration; 580 added GPU migration. The pod is on driver 580 per memory (B300 voice stack), so all features are available.

**CUDA version constraint.** Memory note says the pod is on CUDA 13.0 and MLOPart needs 13.1. `cuda-checkpoint` itself is bundled with the driver, not the CUDA toolkit — checked against the README — so this is fine. If a future Pillar 5 task wants `cuda-checkpoint --action migrate`, re-verify against driver 580+ release notes.

**Concrete elasticity scenario (full runbook in `elasticity-runbook.md`).** Fish TTS demand-spike during a long 911 multi-turn:
1. Heartbeat detects Fish queue depth > 3, p95 synth latency > 800 ms.
2. Agent decision: *evict vLLM HBM during the next dispatcher-pause window* (FSM is in `gather_address` state, expected silence ≥ 2 s).
3. `cuda-checkpoint --action lock --pid <vllm_pid>` — block new requests.
4. Drain in-flight requests (max 2 s based on current decode rate).
5. `cuda-checkpoint --action checkpoint --pid <vllm_pid>` — HBM freed.
6. Fish gets full HBM budget; spike clears.
7. `cuda-checkpoint --action restore --pid <vllm_pid>`.
8. `cuda-checkpoint --action unlock --pid <vllm_pid>`.
9. Verify TTFT regression < 10% via 5-probe smoke.

**Limitations from the README** (must be respected): "does not support UVM or IPC memory" and "is x64 only" as of driver 570. vLLM does not currently use UVM in our config; verify before first use. IPC memory (NCCL) is N/A on a single-GPU pod.

**Effort estimate.** Medium. The elasticity decision policy is the hard part; the `cuda-checkpoint` calls themselves are ~10 lines of bash.

---

## 6. Pillar 5 — cuTILE / kernel-shape steering (large effort, future-cycle)

**Capability we want.** When vLLM compiles or auto-tunes its attention / GEMM kernels, give the autotuner a *workload prior* — "this is batch=1, 32k context, NVFP4, MoE 30B-A3B PSAP voice traffic" — so it picks tile shapes from the right corner of the search space instead of generic shapes.

**Mechanism candidates.**
- vLLM startup flags + `cudagraph_capture_sizes` already encode some of this; Team M's recommendation tunes those for our specific batch-1 shape.
- CUTLASS Python DSL (`CuTeDSL`) is the building block for FA / GEMM / FlashInfer; B300 (sm_103) tile shapes target `tcgen05.mma.cta_group::1` (5th-gen tensor cores) per CLAUDE.md §"State-of-the-art open-source attention kernels" research notes. **License gotcha** from memory note `prism-mla-archive.md`: CUTLASS C++ is BSD-3 but `python/CuTeDSL/` is NVIDIA EULA. We can read but cannot redistribute modifications.
- The agent can **inform** without compiling: emit a workload prior JSON (`{"batch": 1, "ctx": 32768, "dtype": "nvfp4", "model": "nemotron-30b-a3b-moe", "phase": "decode"}`) into a structured file the launch scripts consume. A future cycle wires this into a CUTLASS DSL pre-tune step.

**Status today.** Feasibility of agent-driven kernel re-tuning on B300 is **future-cycle**. Cycle-2X ships only the workload-prior JSON producer (~30 LoC) so cycle-2Z can consume it. CUTLASS DSL is a Python surface, no C++ compile chain required, but tuning runs are 10s-100s of minutes — not heartbeat-cadence.

**Effort estimate.** Large. De-scope to a follow-on cycle. Cycle-2X delivers only the workload-prior emitter.

**Reference (no public B300 tile-shape numbers as of April 2026, per CLAUDE.md research).** The research synthesis in this repo's CLAUDE.md states: "No B300-specific re-tuning published as of April 2026 — assume these kernels run on B300 via PTX JIT but have not been re-tuned." So this pillar is genuinely greenfield work, and the agent's most useful contribution today is *informing the system more about the work*, exactly as the user said.

---

## 7. Pillar 6 — Tool surface

The custom tool surface bound to the coordinator agent on `claude.beta.agents.create(...)`. Full schema is `tool-surface.yaml` (this directory). Summary:

| Tool | Read/Mutate | Gate level | Purpose |
|---|---|---|---|
| `agent_toolset_20260401` | mixed | passive_read | Anthropic-built (bash/read/write/edit/glob/grep/web_fetch/web_search) |
| `pod_ssh_readonly` | read | passive_read | `ssh prism-mla-b300-h4h5 <whitelisted-cmd>` — `nvidia-smi`, `journalctl`, `systemctl is-active`, `vllm-health-curl` only |
| `pod_smi` | read | passive_read | `nvidia-smi --query-gpu=...` shorthand |
| `pod_journalctl` | read | passive_read | scoped to `prism42-worker`, `prism42-fish`, `prism42-vllm`, `caddy`, `b300-livekit-1` |
| `livekit_health` | read | passive_read | `curl https://prism42.thegoatnote.com/` + LiveKit Cloud REST list-rooms |
| `vercel_status` | read | passive_read | `vercel inspect` for the `911-console-live` project; no env mutations |
| `synthetic_caller` | read | passive_read | invokes `agents/livekit/synthetic_caller.py` for a smoke turn |
| `nsys_profile_attach` | mutate (host fs only) | active_mutate | runs `nsys profile` against a target PID; writes `.nsys-rep` to scratch |
| `nsys_export` | read | passive_read | exports `.nsys-rep` to JSON Lines |
| `gds_op` | mutate (filesystem + HBM) | active_mutate | `prefetch_weights / spill_kv / stage_checkpoint / status` |
| `cuda_checkpoint_ctl` | mutate (process state) | gated_destructive | `lock / checkpoint / restore / unlock / get_state` against vLLM PID |
| `service_restart` | mutate (process lifecycle) | gated_destructive | `systemctl restart prism42-vllm` (and others) — gate `PRISM42_AUTONOMIC_AUTORESTART_*` |
| `restore_invoke` | mutate (multi-system) | gated_destructive | invokes the existing `restore.sh` — only on explicit user `--restore` flag |
| `workload_prior_emit` | mutate (filesystem only) | active_mutate | writes the cuTILE workload-prior JSON for the launch scripts |

**Gate semantics** (mirror the existing G1-G7 pattern from `cycle2R/team-r/run.sh`):
- **passive_read** — auto-allowed. No env-flag.
- **active_mutate** — auto-allowed *only* when the agent's loop is in the appropriate state (e.g. an Nsight profile only runs after a heartbeat-detected anomaly OR an explicit user request). Otherwise the agent must request and wait.
- **gated_destructive** — requires a per-tool env flag pre-armed by the integrator before agent start. Agent fails loud if the flag is missing.

---

## 8. Generator-evaluator separation (charter §"Recent best-practice synthesis")

Per CLAUDE.md and Anthropic's harness-design post:
- **Generator** = the live voice path (worker.py + orchestrator.py + dispatcher_fsm.py + fish_speech_tts.py + dispatch_publisher.py). Frozen by charter.
- **Evaluator** = the autonomic agent. It judges generator output (latency, GPU memory, log patterns), but cannot rewrite the generator.
- This separation is the *whole point* of the sidecar architecture. A managed agent that sits inside `worker.py` would couple generator and evaluator and lose the variance-cancelling property Anthropic flags. The autonomic agent runs in its own process, talks to the generator only through read-only telemetry + tightly scoped mutate tools, and writes its findings to the same incident JSONL the integrator audits offline.

---

## 9. Munger-inversion section ("how does this fail?")

- **Auto-Mode classifier kills the agent mid-restart.** Mitigation: single-service-at-a-time + state-probe between every transition (memory note `prism42_b300_voice_durable_findings.md`); gates default OFF.
- **Heartbeat agent itself is on the voice critical path.** Mitigation: it is a separate process with its own LiveKit data-track; if it dies, voice path is unaffected. Verified by reading `worker.py` import graph — no agent-side imports.
- **`cuda-checkpoint` reduces vLLM but vLLM was holding the only HBM bank Fish needed.** Mitigation: rehearse the full elasticity sequence on a low-call window before relying on it during a real spike. `elasticity-runbook.md` includes the pre-flight.
- **Nsight profiling pegs CPU/GPU during a live call.** Mitigation: profile only when room count = 0 OR explicit user override; never enable verbose tracing.
- **Multi-agent feature suddenly available, code path not ready.** Mitigation: skeleton documents the upgrade path but does not rely on `callable_agents` (CLAUDE.md §8 + memory note `managed_agents_multi_agent_verified.md`).
- **`gds_op` writes to wrong NVMe mount and floods `/`.** Mitigation: hard-coded scratch path `/opt/prism42/scratch/`, agent has no shell access to write outside it.
- **Agent halts loop but heartbeat keeps emitting "nominal".** Mitigation: heartbeat watchdog — if no heartbeat tick for 2× cadence, host supervisor restarts the agent (one-shot, then escalate).
- **Restore script gets invoked by the agent in the wrong direction.** Mitigation: `restore_invoke` is `gated_destructive` and requires `PRISM42_AUTONOMIC_RESTORE=1` plus a freshly-provided `--restore-confirm` token in the prompt.

---

## 10. What I de-scoped

- **Pillar 5 cuTILE re-tuning execution.** Ships only the workload-prior emitter; actual CUTLASS DSL pre-tune is cycle-2Z.
- **Pillar 3 shadow profiling** via parallel vLLM context. Single-GPU pod + full HBM under load makes this unsafe today.
- **Multi-agent fan-out.** `callable_agents` is silently stripped on this workspace per CLAUDE.md §8. Skeleton uses one coordinator agent.
- **Auto-recovery beyond `vllm restart`.** All other auto-recovery is alert-only in cycle-2X. Integrator adds rules incrementally.
- **Cross-pod migration via `cuda-checkpoint --action migrate`.** Single pod today; not relevant.

---

## 11. Sequencing

1. **Land cycle-2X spec** (this directory). Integrator review.
2. **Cycle-2X.1**: `agent-skeleton.py --create` registers the agent (no session start). Verify with `make ant-check`-style read-only probe.
3. **Cycle-2X.2**: heartbeat-only mode. No mutate tools enabled. Run for 24 h. Confirm `prism42.heartbeat` events visible in browser console under `/prism42/livekit`.
4. **Cycle-2X.3**: enable `nsys_profile_attach` + `nsys_export` (Pillar 3 simple path). Agent profiles only on explicit user trigger.
5. **Cycle-2X.4**: enable `cuda_checkpoint_ctl` for the elasticity scenario (Pillar 4). Rehearse on a quiet window before depending on it.
6. **Cycle-2Y / 2Z**: Pillar 2 (cuFile policy) + Pillar 5 (cuTILE re-tune).

Total cycle-2X effort: small + small-medium + small + medium + tiny-Pillar-5 stub ≈ **3-5 days of integrator time** to land 2X.1 → 2X.4. No code execution by Team X.
