# cycle-2R baseline manifest — 2026-04-26 09:03 UTC

This is the BEHAVIOR-restore point captured BEFORE any cycle-2R migration
work touches shared infrastructure. Re-running `./restore.sh` returns the
prism42 voice demo to the exact behavior the user attested as working
(voice quality "best your work", FSM controlling logic, MW reference
voice + cycle-2P file-backed greeting + LiveKit Cloud media plane).

The behavior, not the files. The script is idempotent and restores:

1. Pod systemd drop-ins (`/etc/systemd/system/prism42-worker.service.d/*.conf`)
2. Pod agent worker source (`/opt/prism42/agents/livekit/{worker,orchestrator,dispatcher_fsm,fish_speech_tts}.py`)
3. Pod `.env` (the worker's environment file — pinning Fish reference, Nemotron URL, etc.)
4. Pod voice-refs (`mw_sample.wav`, `mw_intro_greeting.wav`, others)
5. Vercel production env vars (`NEXT_PUBLIC_LIVEKIT_URL` back to LiveKit Cloud)
6. Pod systemd state (worker active + restart, vLLM running, Fish active)

## Baseline state captured

**Pod**: `b300-pod` / public IPv4 `31.22.104.100`

**Service states at capture**:
- `prism42-worker.service` = `active`
- `prism42-fish.service` = `active`
- vLLM serve = pid `389310` (active)
- bare-process `livekit-server` = pid `76823` (running but not exposed)

**Systemd drop-ins** (`/etc/systemd/system/prism42-worker.service.d/`):
- `10-vllm-model.conf`
- `20-vllm-max-tokens.conf`
- `50-cycle2i-greeting.conf`
- `70-cycle2k-pacetag.conf`
- `100-cycle2N-mwref.conf`
- `110-cycle2P-greeting-file.conf`
- `120-cycle2Q-fsm.conf`

**UFW state**: only SSH open (`22/tcp`, `2222/tcp`).

**Git**:
- Pod `/opt/prism42` HEAD = `36ede0c9f3cd3f23bfec4b39c95560cdace3e880`
- Local repo HEAD = `43c727b` (cycle-2Q FSM-on)

**Vercel project**: `prism42-console` (`prj_UCqQGmKnXhmqeQgwIHWJ9zzfX4vP`)

**Vercel production env (names only, values are encrypted at rest in Vercel)**:
- `NEXT_PUBLIC_LIVEKIT_URL` = `wss://ai-therapy-v3svfd9o.livekit.cloud` (LiveKit Cloud — restoration target)
- `NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID`
- `NEXT_PUBLIC_ELEVENLABS_AGENT_ID`
- `LIVEKIT_API_KEY` (cloud key)
- `LIVEKIT_API_SECRET` (cloud secret)
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `PRISM42_COORDINATOR_AGENT_ID`

## Files in this baseline directory

| File | Purpose | Sensitive? |
|---|---|---|
| `manifest.md` | This document | No |
| `pod-state.local.tgz` | Pod systemd drop-ins + worker source + .env + voice-refs | **YES** (gitignored) |
| `pod-state.sha256` | Tarball checksum | No |
| `restore.sh` | Idempotent rollback script | No |
| `vercel-env-snapshot.txt` | Vercel production env names + targets (no values) | No |

## Restore procedure

```bash
cd ~/prism42/findings/voice/cycle2R_livekit_selfhost/baseline-2026-04-26
./restore.sh                # full restore
./restore.sh --pod-only     # restore only pod state
./restore.sh --vercel-only  # restore only Vercel env
./restore.sh --check        # dry-run; print what would change
```

The script verifies the tarball SHA256 matches `pod-state.sha256` before
extracting. If the SHA mismatches, it aborts (don't trust modified
backups).

## Provenance

- Tarball captured 2026-04-26 ~09:03 UTC by main agent
- SHA256: `107f8aa68522dc9c6155526610100de3bc4cb0e39587bcf1be2ec4c0e5e50581`
- Captured BEFORE any cycle-2R team output was applied
- Reflects: cycle-2N MW reference voice + cycle-2P file-backed greeting + cycle-2Q FSM-on + LiveKit Cloud media plane
