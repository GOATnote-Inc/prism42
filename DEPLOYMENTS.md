# Pod Deployments Ledger

**Purpose:** worktrees fix git divergence; they do NOT fix *pod-state*
divergence. The repo has one source of truth (`main` HEAD), but the
two GPU pods can run different versions of the code in main if only
one of them is redeployed after a merge. This file is the durable
record of which commit was deployed to which pod and when, so the
operator can detect asymmetry at a glance.

Per the policy in `findings/ops/parallel-session-coord.md` §6, every
merge of a worktree branch to `main` that affects pod-side code must
be reflected here. Either session may append.

## Schema

```
| timestamp_utc | commit | files_changed | affected_pods | deployed_to | verified_by | notes |
|---|---|---|---|---|---|---|
```

- **timestamp_utc** — ISO-8601 (`2026-04-27T20:24Z`).
- **commit** — short SHA.
- **files_changed** — comma-separated paths of pod-relevant files (worker.py, orchestrator.py, dispatcher_fsm.py, attacker.py, rule_adjudicator.py, guardrails_wrapper.py, parakeet_stt.py, fish_speech_tts.py, prism42-worker.service.d/*.conf, etc.). Skip pure docs / tests unless they touch a pod.
- **affected_pods** — `prism-mla-h100`, `warm-lavender-narwhal`, or `both`. If a commit only touches H100-relevant code, H200 doesn't need to redeploy.
- **deployed_to** — comma-separated list of pods where the new code is *actually running* (after `scp` + service restart). If a pod row is missing, that pod is running stale code from a prior deploy.
- **verified_by** — short tag identifying the verification method (`syscheck` = systemctl is-active green, `attest` = synthetic caller end-to-end pass, `unit-tests` = pytest green, `manual` = human voice round-trip, `none` = not yet verified).
- **notes** — anything operationally important (rollback path, downtime window, freeze status).

## Pre-populated history (left session, retrospective up to 2026-04-27 21:30Z)

| timestamp_utc | commit | files_changed | affected_pods | deployed_to | verified_by | notes |
|---|---|---|---|---|---|---|
| 2026-04-27T13:07Z | (image build) | infra/b300/services/parakeet/Dockerfile | `prism-mla-h100` | h100 | syscheck | Parakeet 0.6B-TDT-v3 container started, /healthz green, 3.3 GB GPU |
| 2026-04-27T14:00Z | `aa23de6` | dispatcher_fsm.py + tests/voice/test_fsm_reassurance_latch.py | `prism-mla-h100` | h100 | unit-tests (165 pass / 0 fail) | FSM reassurance-latch fix; backup at `dispatcher_fsm.py.pre-bugfix.bak` on pod |
| 2026-04-27T19:45Z | `16ec5c3` | orchestrator.py + prism42-worker.service.d/130-5role-enable.conf | `prism-mla-h100` | h100 | syscheck (env-flags verified in /proc/<pid>/environ) | 5-role activation wiring + drop-in; rollback by removing drop-in |
| 2026-04-27T20:00Z | (host install, no commit) | apt cuda-toolkit-13-2 + uv pip nx-cugraph-cu13 / cudf-cu13 | `prism-mla-h100` | h100 | syscheck (nvcc 13.2 + venv import) | CUDA 13.2.1 toolkit + RAPIDS 26.04 cu13 wheels; container untouched (NeMo 25.09 stays on 12.x base) |
| 2026-04-27T20:21Z | `f9377b4` | worker.py (agent_name env), orchestrator.py (NameError hoist), prism42-worker.service.d/130-5role-enable.conf (PRISM42_AGENT_NAME, PRISM42_PARAKEET_STREAMING) | `prism-mla-h100` | h100 | attest (synthetic_caller_full audio round-trip 1.96 MB) | H100 worker registered as `prism42-h100`; STT still blocked by /ws subprotocol gap (separate finding) |
| 2026-04-27T20:25Z | (uv pip install, no commit) | livekit-plugins-elevenlabs in venv | `prism-mla-h100` | h100 | syscheck (lazy-import resolves) | Pinned in pyproject.toml in commit `f9377b4` for fresh-venv reproducibility |
| 2026-04-27T~20:00Z | `a38c0a3` (right session) | worker.py (env import-time defaults) | `warm-lavender-narwhal` (per right session intent) | h200 (presumed; unverified by left) | unknown | Right session's fix; left has not deployed to H100 — H100 is frozen and running pre-`a38c0a3` worker.py |
| 2026-04-27T~20:00Z | `2140dee` (right session) | worker.py (FILLER_DELAY_S=0.3 revert) | `warm-lavender-narwhal` (per right session intent) | h200 (presumed; unverified by left) | unknown | Same as above — H100 still on FILLER_DELAY_S=99 |
| 2026-04-27T21:00Z | `0a4ed22` (right session) | worker.py (TTS default = nvidia_magpie) | `warm-lavender-narwhal` | unknown (right session is mid-Fish-build) | unknown | Right session reverted from `b8dbcca` ElevenLabs detour; sovereignty thesis |

## Drift snapshot (current state, 2026-04-27 21:30Z)

**Known asymmetry:** the H100 pod's `/opt/prism42/agents/livekit/worker.py` is the version I scp'd at the time of commit `f9377b4`. Right session pushed `0a4ed22` after that, so `main` now has a `worker.py` that the H100 hasn't seen. The drift is:

- main: TTS default = `nvidia_magpie` (sovereign-thesis-correct)
- H100 pod: TTS default = `elevenlabs` (cloud, fallback) per the version that was scp'd
- H200 pod: presumed running latest main (right session is iterating actively there)

Per the H100 freeze certificate (`findings/voice/h100-freeze-2026-04-27.md`), the H100 stays on the cloud-ElevenLabs fallback — the sovereign demo lives on H200. So this drift is *intentional* during the freeze, not a bug. When the freeze lifts, redeploy main to H100 and re-row this ledger.

## Append protocol

When you (either session) deploy a commit to a pod, append a row here. Keep the table sorted by timestamp ascending. If you redeploy the same commit to a second pod later, append a new row rather than editing the old one — preserves audit trail.

If a deploy is rolled back, document the rollback as its own row with the prior commit and `notes: rollback from <bad-commit>`.

For pure-docs commits (this file, parallel-session-coord.md, README, findings/research/*) skip the row — they don't change pod runtime.
