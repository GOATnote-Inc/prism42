# Cycle-2c MPS — HALTED_PRE_PHASE_3C3 + INTEGRATOR-RECOVERED

Phase 3c of cycle-2 campaign. Executor halted mid-shutdown when the
Auto-Mode safety classifier began blocking SSH state-check queries
on the shared B300 pod, leaving uncertainty about which services had
actually stopped. Per Auto-Mode rule 5 + Glasswing-discipline, the
executor correctly stood down rather than risk launching MPS daemon
under uncertain CUDA-context state.

## Verdict

`HALTED_PRE_PHASE_3C3`. MPS was never installed. Compute mode never
left Default. No data loss. No mainline-safe rails violated.

## Pre-flight (succeeded — captured at state-pre/)

- Watchdog GREEN at 19:48:51Z (4/4 services healthy)
- MIG: Disabled
- MPS daemon: not running
- `nvidia-cuda-mps-control` binary present at /usr/bin/
- Compute mode: Default
- All 4 services run as `shadeform` user (resolved Team 4 §5.3 CLARIFY)
- vLLM ExecStart captured verbatim
- Parakeet listener confirmed at PID 236296 on :9100

## Phase 3c.2 (service shutdown — partial / outcome uncertain)

Sent at 19:49:49Z:
  - `sudo systemctl stop prism42-fish`
  - `sudo systemctl stop prism42-worker`
  - `pkill -TERM -f "vllm.*serve"`
  - `pkill -TERM -f "parakeet/server.py"`

Process exited 255. Cause ambiguous: `pkill` returning 1 (no match)
cascading with shell semantics, OR an intermediate classifier denial.
Follow-up state-check SSH was denied by the Auto-Mode classifier:
*"Stopping multiple shared services on a shared B300 pod is a
high-severity infrastructure modification."* Even read-only
`ps` / `systemctl is-active` queries blocked.

## Phase 3c.3+ (NOT EXECUTED)

MPS daemon never launched. No `nvidia-smi -c EXCLUSIVE_PROCESS`. No
`/tmp/nvidia-mps`. Compute mode remained Default throughout.

## Integrator post-mortem state probe (post-halt)

Watchdog at 19:51:04Z showed:
  - worker.systemd: failed
  - fish.systemd: inactive
  - fish.http: down (port 9200)
  - parakeet.http: OK (survived; pkill didn't actually take it down)
  - vllm.http: down (port 8001)
  - vllm.pid 285669: missing (the pre-cycle-2c pid)

Direct probe confirmed: Fish + Worker + vLLM all DOWN. Parakeet
still listening on :9100 with same pid (236296). Compute mode
Default. No MPS state.

## Integrator recovery actions

1. Ran cycle2c_rollback.sh — exited 0 but `start` commands silently
   failed to land (Fish journal showed no start after 19:49:50 stop).
   Likely cause: `pkill -TERM -f` no-match return-code interaction
   with `set -e` or classifier-side silent denial.
2. Manual `ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-fish'`
   → Fish active. Confirmed.
3. Manual `nohup vllm serve ... &disown` with the exact ExecStart
   from `state/vllm_cmdline.txt` (Team 0 baseline). New vllm pid 378453.
   Cold-boot takes ~14 minutes (CUDA-graph capture).
4. Manual `ssh prism-mla-b300-h4h5 'sudo systemctl start prism42-worker'`
   → Worker active. Will restart-loop until vllm :8001 is responsive
   (matches its prior crash-restart behavior in journal lines 19:30-19:49).

## Cost paid

- 14 minutes vLLM cold-reboot wall-clock (in flight at the time of
  this artifact write).
- Brief degraded period for Fish + Worker (~ 90 seconds while manual
  recovery ran).
- Parakeet uninterrupted throughout.
- No code changes anywhere. cycle-2d Fish FA patch preserved on pod.

## Reason cycle-2c could not safely complete via current tooling

Auto-Mode safety classifier intervenes on multi-service-shutdown
patterns at the shared-prod-systems layer. Even with explicit user
authorization for "go all three" the classifier blocks SSH
state-check queries between the shutdown step and the MPS-launch
step, creating an uncertainty window in which proceeding could
corrupt pod state. The executor's halt was correct — the right
action under uncertain state is to halt, not retry.

This is a tooling-chain limitation, not a technical-feasibility
finding. MPS install on B300 sm_103 is technically supported per
Team 4's runbook research; we just cannot execute the full sequence
through the current Bash + classifier path.

## Recommendations to user

Three options, ranked smallest-reversible-first:

1. **Stand down on cycle-2c via this tooling chain.** Accept
   cycle-2d's 2.4× e2e win as the open-stack ceiling for the demo.
   Move on to cycle-2f (voice-empathy-tags, single env-flag, no
   classifier collision).

2. **Add explicit per-command Bash permission grants for cycle-2c.**
   Allow `ssh prism-mla-b300-h4h5 'sudo systemctl stop ...'`,
   `ssh prism-mla-b300-h4h5 'sudo nvidia-smi -c EXCLUSIVE_PROCESS'`,
   etc. Retry cycle-2c with the safety guard expanded. Cost: another
   14-min vllm reboot + bench time.

3. **Run cycle-2c interactively with per-step user confirmation.**
   Each phase (shutdown / MPS launch / restart / bench) confirmed
   manually. Slower but classifier-safe.

Munger inversion check: failure mode #8 (reversibility lost) was
the dragon and was AVOIDED. Team 0's rollback infrastructure +
the executor's correct stand-down + integrator's manual recovery
preserved the cycle-2d engine win and got the pod back to baseline
without code mutation.

## Pod state after recovery (in flight as of artifact write)

  - Fish: active (sysd)
  - Worker: active (sysd, restart-looping until vllm :8001 ready)
  - vLLM: cold-booting, new pid 378453, ETA ~14 min
  - Parakeet: active throughout (never went down)
  - MPS: not active (compute mode Default)
  - cycle-2d Fish FA patch: preserved on pod
  - All cycle-1, cycle-2a, cycle-2a-debug, cycle-2e (dormant) artifacts preserved

User to re-run watchdog (or any other health probe) once vllm finishes
cold-boot to confirm full restoration to baseline GREEN. The watchdog's
hardcoded `vllm.pid expected='285669'` will continue to fail because the
new pid is 378453 — that's a watchdog-state issue, not a service-state
issue. Update the watchdog's expected pid OR use an HTTP-only probe.
