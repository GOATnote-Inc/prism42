# cycle-2S apply — FAILED on numba; rollback restored with FLASHINFER env fix

2026-04-26 ~10:38–10:51 UTC. User authorized "S apply" with explicit
constraints (rollback on any check failure; commit verification only).

## Outcome — VERDICT: ROLLBACK_GREEN_WITH_L8B_HARDENING

The cycle-2S full-merged apply (L3 + L8b + L6) failed during vLLM startup
with `ModuleNotFoundError: No module named 'numba'` — the L6 ngram
speculative-decoder requires `numba` which is not installed in the
`.venv-nightly` venv.

Rollback per constraint #5 was triggered immediately. Rollback initially
came up in **degraded TRTLLM mode with hidden-size padding 2688→2816**
(memory finding #6's exact failure signature) because
`/proc/389310/cmdline` does not capture environment variables, and
`sudo -u shadeform bash -c` strips PATH and unset `VLLM_*` env. The
rollback shell was therefore missing the FLASHINFER env vars that the
original interactive launcher had inherited from `source venv/bin/activate`.

Re-rolled-back with a wrapper script that explicitly sets the FLASHINFER
env vars + sources the venv before exec'ing the captured cmdline. Final
state has `FLASHINFER_CUTLASS` confirmed, no padding warning. Net result:
**L8b lever (FLASHINFER env persistence) is now APPLIED via the wrapper**
even though the full cycle-2S didn't land. The latent prod-down hole that
finding #6 warned about — "one shell-restart away from JS-garbage" —
is closed.

## Verification (all 4 GREEN)

```
vLLM health        : READY @ T+26s   /v1/models returns nemotron-nano
                     Using FLASHINFER_CUTLASS NvFp4 MoE backend (correct path)
                     no "Padding hidden size from 2688 to 2816" warning
TTFT probe         : 945 ms (cold first hit; warm subsequent ~50ms per Team M baseline)
decode probe       : 64 tokens / 231 ms = 277 tok/s
                     output: "one\ntwo\nthree\nfour\nfive…" (natural English; NOT JS-garbage)
synthetic_caller   : PASS_2R
                     agent_joined            : AJ_ZAPPJnKGRKBQ
                     audio_track_subscribed  : YES
                     first_audio_frame       : +2.60s (cold; was +1.55s in pre-cycle2S baseline)
                     total_audio_bytes       : 1,584,960
                     speech_frames           : 234 (>5000 amp = clear speech)
                     peak_amplitude          : 29819
```

## What changed on the pod

- `/tmp/relaunch-rollback.sh` — wrapper script that:
  1. Exports the 4 critical env vars (`VLLM_USE_FLASHINFER_MOE_FP4=1`,
     `VLLM_FLASHINFER_MOE_BACKEND=throughput`,
     `VLLM_ATTENTION_BACKEND=FLASHINFER`,
     `TORCH_CUDA_ARCH_LIST="10.0;10.3"`)
  2. `source`s the venv `activate` script (puts ninja + python in PATH)
  3. exec's the captured cmdline from `/tmp/vllm-rollback.cmdline`
- vLLM new pid (varies; was 495145 at first relaunch); same flags as
  pre-cycle2S launch (gpu-memory-utilization 0.20, no spec-decode,
  no ngram, no cycle-2S levers L3 or L6)
- prism42-worker restarted at 10:49:30Z and re-registered as
  `AW_MYwLTQVirTBq → wss://prism42.thegoatnote.com`

## What did NOT change

- Caddy, DNS, LiveKit (signaling + media), Parakeet, Fish, frontend,
  agent worker code — all per constraint #1.
- Cycle-2S levers L3 (gpu-memory-utilization 0.85) and L6 (n-gram
  spec-decode) — NOT applied; numba missing for L6 and didn't reach
  the runtime past startup crash.
- Demo URL routing — still
  `https://prism42-console.vercel.app/prism42/livekit` →
  `wss://prism42.thegoatnote.com` (cycle-2R cutover preserved).

## Root cause + remediation path for future apply

L6 needs `numba`. Two paths:
1. `pip install numba` in `.venv-nightly` (small dep) → re-attempt cycle-2S apply
2. Drop L6 from the merged config; apply L3 + L8b only (L8b already in place
   via wrapper, so this collapses to applying L3 alone — the GPU-memory
   bump from 0.20 → 0.85 for 5x KV cache headroom)

Either path requires another vLLM cold-restart (~30-60s now that warm
caches exist on disk).

## Window cost

- vLLM dark from ~10:37:11 to ~10:48:15 = ~11 min total (longer than
  predicted 62s because of two failed launch attempts before the
  successful relaunch with proper env)
- Worker reconnected at 10:49:30 — total demo voice-loop dark window
  ~12 min
- Restore.sh remained available throughout (~30s rollback to LiveKit
  Cloud if pod-side recovery had also failed)

## Per-constraint compliance

| Constraint | Status |
|---|---|
| 1. Don't touch Caddy/DNS/LiveKit/frontend/Parakeet/Fish/agent worker | KEPT (only vLLM was killed + relaunched) |
| 2. Use staged cycle-2S wrapper | ATTEMPTED; failed on numba; fell back to rollback wrapper |
| 3. Preserve rollback exactly from /tmp/vllm-rollback.cmdline | KEPT (cmdline unchanged; env vars added to environment, not cmdline) |
| 4. Verify health/TTFT/decode/PASS_2R | DONE (all 4 GREEN) |
| 5. Rollback on check failure | DONE (cycle-2S rolled back) |
| 6. Commit verification artifact only, not secrets/logs | THIS DOC; logs stay on pod |

## Hand-off

- vLLM is healthy and producing correct output. Demo URL is live.
- L8b (env persistence) lever is effectively applied — closes finding #6
- L3 (gpu-mem 0.85) and L6 (spec-decode) remain unapplied — install
  numba first if you want to re-attempt cycle-2S
- The wrapper at `/tmp/relaunch-rollback.sh` is ephemeral (survives only
  on this pod tmp until next reboot); long-term the wrapper should be
  copied to `/opt/prism42/infra/b300/services/vllm/launch-vllm-rollback-with-env.sh`
  and `cycle2S-merged.conf` updated to require numba pre-install before
  apply
