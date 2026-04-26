# Cycle-2X — Elasticity Runbook (Team X)

**Status:** SPEC ONLY. Do not execute. Integrator runs each step manually the first time, with the agent observing-only. After three successful manual rehearsals, the agent may run the full sequence under `PRISM42_AUTONOMIC_ELASTICITY=1`.

**Scenario.** Fish TTS demand-spike during a long 911 multi-turn call. Heuristic: utterance queue depth > 3 OR Fish synth p95 latency > 800 ms for 3 consecutive heartbeat ticks (~90 s).

**Goal.** Free vLLM HBM for the duration of the spike, restore vLLM after the spike clears, with TTFT regression < 10% post-restore.

**Pod facts (frozen, see `restore.sh`):**
- Pod hostname: `prism-mla-b300-h4h5`
- vLLM service unit: `prism42-vllm` (per Team M drop-ins; if not yet adopted, vLLM runs as a manual screen process and `pid` must be discovered via `pgrep -f vllm`)
- Driver: 580 (cuda-checkpoint full feature set available)
- CUDA: 13.0 (no MLOPart, but `cuda-checkpoint` is driver-bundled and unaffected)

---

## Pre-flight (always run; never skip)

```
# 1. Confirm we are in a low-call window OR have explicit user override
ssh prism-mla-b300-h4h5 'docker exec b300-livekit-1 lk room list | wc -l'
# Expected: 0-1 (1 = the in-progress call we are protecting)

# 2. Discover vLLM PID
VLLM_PID=$(ssh prism-mla-b300-h4h5 'pgrep -f "vllm.*--model.*nemotron" | head -1')
[ -z "$VLLM_PID" ] && { echo "FATAL: vLLM PID not found"; exit 1; }
echo "vLLM PID = $VLLM_PID"

# 3. Confirm cuda-checkpoint is present + driver supports it
ssh prism-mla-b300-h4h5 'cuda-checkpoint --get-state --pid '"$VLLM_PID"
# Expected output: "running" (verifies tool works AND PID has CUDA state to checkpoint)

# 4. Confirm UVM is NOT in use (cuda-checkpoint limitation per README)
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=name --format=csv | head -1'
ssh prism-mla-b300-h4h5 'grep -l "uvm" /proc/'"$VLLM_PID"'/maps' && {
    echo "FATAL: UVM detected in vLLM process; cuda-checkpoint cannot snapshot UVM mappings"
    exit 1
}

# 5. Snapshot current TTFT baseline
ssh prism-mla-b300-h4h5 'curl -fsS -X POST http://127.0.0.1:8001/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"nemotron\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":8}" \
    -o /dev/null -w "%{time_starttransfer}\n"'
# Save the value. Post-restore TTFT must be within 10%.
```

If any pre-flight check fails, **abort and emit `prism42.alert` severity `degraded`**. Do NOT proceed.

---

## Step 1 — Lock vLLM (block new requests)

```
ssh prism-mla-b300-h4h5 'cuda-checkpoint --action lock --pid '"$VLLM_PID"' --timeout 5000'
ssh prism-mla-b300-h4h5 'cuda-checkpoint --get-state --pid '"$VLLM_PID"
# Expected: "locked"
```

`--timeout 5000` per the cuda-checkpoint README: "(optional) for lock operations to prevent deadlocks." 5 s is long enough for in-flight CUDA work to drain on a batch=1 PSAP load (decode rate 313 tok/s ≈ 3.2 ms per token; longest in-flight reply is < 50 tokens ≈ 160 ms).

**Failure mode:** lock returns nonzero. Recovery: assume nothing happened (lock is atomic on this driver per docs), emit alert, abort.

---

## Step 2 — Drain in-flight requests

```
# Wait up to 3 s for any in-flight HTTP requests to vLLM to drain.
# Voice path will see locked vLLM and queue locally; that's expected.
sleep 3
```

The dispatcher FSM is engineered to tolerate brief LLM unavailability — `response_gate.py` (cycle-2T) holds the turn until LLM responds OR a fallback path triggers. Drain window must be < the gate timeout. **Verify with the integrator before first run that `response_gate.py`'s timeout exceeds 5 s.**

---

## Step 3 — Checkpoint (HBM → host RAM)

```
ssh prism-mla-b300-h4h5 'cuda-checkpoint --action checkpoint --pid '"$VLLM_PID"
ssh prism-mla-b300-h4h5 'cuda-checkpoint --get-state --pid '"$VLLM_PID
# Expected: "checkpointed"
ssh prism-mla-b300-h4h5 'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader'
# Expected: memory.used drops by ~89 GiB (was 89 GiB before; should be ~0-5 GiB after)
```

This is the moment of truth. The README says: "(1) locks APIs that modify GPU state, (2) completes pending work, (3) copies device memory to host, and (4) releases GPU resources." Step (3) is the slow part — copy speed is bounded by PCIe; 89 GiB at ~50 GB/s ≈ 1.8 s on B300 PCIe Gen 5. Budget 5 s.

**Failure mode:** checkpoint returns nonzero OR `--get-state` shows anything other than `checkpointed`. Recovery: `cuda-checkpoint --action unlock --pid <pid>` to restore the running state without ever moving to the checkpointed state. Emit alert.

---

## Step 4 — Wait for spike to clear

```
# Heartbeat tick decides this; the autonomic loop polls Fish queue depth + p95 latency.
# Manual rehearsal: wait until queue depth < 2 for 3 consecutive ticks (90 s).
```

While vLLM is checkpointed, the voice path is in **TTS-only mode** for any turn that requires LLM reasoning. The dispatcher FSM has hand-coded fallback templates for the most common turns (greeting, address-gather, dispatch-confirm) — verify with the integrator which intents *cannot* fall back. If a "must-LLM" intent fires while checkpointed, the agent must roll back immediately (skip Step 5; jump to Step 6).

---

## Step 5 — Restore (host RAM → HBM)

```
ssh prism-mla-b300-h4h5 'cuda-checkpoint --action restore --pid '"$VLLM_PID
ssh prism-mla-b300-h4h5 'cuda-checkpoint --get-state --pid '"$VLLM_PID
# Expected: "locked" (post-restore, still locked from Step 1's lock)
```

Restore is the PCIe copy in reverse; budget 5 s.

---

## Step 6 — Unlock vLLM

```
ssh prism-mla-b300-h4h5 'cuda-checkpoint --action unlock --pid '"$VLLM_PID
ssh prism-mla-b300-h4h5 'cuda-checkpoint --get-state --pid '"$VLLM_PID
# Expected: "running"
```

---

## Step 7 — Post-restore verification (TTFT regression check)

```
# Run 5 TTFT probes; compute mean.
for i in $(seq 1 5); do
    ssh prism-mla-b300-h4h5 'curl -fsS -X POST http://127.0.0.1:8001/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"nemotron\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":8}" \
        -o /dev/null -w "%{time_starttransfer}\n"'
done

# Compare mean to pre-flight baseline. Pass if mean < 1.10 * baseline.
```

If TTFT regression > 10%: emit `prism42.alert` severity `warn` and recommend a manual vLLM restart at the next quiet window. Do NOT auto-restart from inside this runbook (that's a separate `service_restart` tool gated by its own env-flag).

---

## Rollback path (any step fails)

| Failure step | Recovery |
|---|---|
| Pre-flight | abort, no state changed |
| Step 1 lock | nothing to undo, abort |
| Step 2 drain | rare; if drain hangs, `cuda-checkpoint --action unlock` and abort |
| Step 3 checkpoint | `cuda-checkpoint --action unlock` (skips checkpoint state); vLLM resumes; emit alert |
| Step 4 must-LLM intent fires | jump to Step 5 (restore) immediately, skip the wait-for-spike-clear |
| Step 5 restore | **most dangerous failure mode**. If restore fails, the host RAM still holds the snapshot. Try `cuda-checkpoint --action restore` once more after 10 s. If still fails, the only recovery is `systemctl restart prism42-vllm` (or equivalent for the manual-launch case) — accept the 62 s cold-start cost and emit `prism42.alert` severity `failing` |
| Step 6 unlock | run unlock manually with no timeout; if still failing, `systemctl restart` |
| Step 7 verify | informational; voice path is already running |

---

## Auto-recovery preconditions (for `PRISM42_AUTONOMIC_ELASTICITY=1` mode)

1. The pod has been on this driver + CUDA combination for ≥ 24 h with no vLLM crashes.
2. `synthetic_caller.py` has run a clean smoke turn within the last 60 min.
3. The integrator has manually rehearsed Steps 1-7 successfully ≥ 3 times.
4. `response_gate.py` is confirmed (read-only inspection) to have a timeout ≥ 5 s on LLM unavailability.
5. The "must-LLM" intent allow-list (i.e. intents that have no FSM fallback) is encoded in the agent's prompt.

If any precondition is missing, the agent must NOT auto-execute this runbook. It may emit an `prism42.alert` recommending manual execution, with this file's path attached.

---

## Citation block (for the agent's own provenance log)

- `cuda-checkpoint` action semantics: `https://github.com/NVIDIA/cuda-checkpoint` (fetched 2026-04-26).
- Driver requirement (550+; full features 580+): same source.
- "does not support UVM or IPC memory" + "x64 only": same source, "Limitations" section.
- LiveKit data-track topic-segmented additive pattern: `agents/livekit/dispatch_publisher.py:43-44, 233`.
- Single-service-at-a-time discipline: memory note `prism42_b300_voice_durable_findings.md`.
