# B300 pod runbook — when the voice demo breaks mid-show

This file is the first page you open when the `/prism42/livekit` voice path
stops working. It is deliberately short — the one-command diagnostic lives in
`scripts/b300_runbook.sh` (installed on the pod at `/opt/prism42/scripts/b300_runbook.sh`).
Everything below is the "what do I read when that script says FAIL" layer.

## First thing to run, always

From the laptop:

```
brev exec prism-mla-b300-h4h5 'bash /opt/prism42/scripts/b300_runbook.sh'
```

Add `--heal` to attempt auto-recovery on any failing service:

```
brev exec prism-mla-b300-h4h5 'bash /opt/prism42/scripts/b300_runbook.sh --heal'
```

Exit 0 means the full voice path (Parakeet → Redis → worker → Fish) round-trips
through `synthetic_caller.py`. Exit 1 means at least one stage is down; the
script tells you which.

## Common incidents + one-line fix

| Symptom | Fix |
| --- | --- |
| Fish TTS returns 500 with `nvrtc: NVRTC_ERROR` | `brev exec prism-mla-b300-h4h5 'pkill -9 -f services/fish-speech; systemctl restart prism42-fish 2>/dev/null \|\| true'` — Fish's SGLang backend needs a fresh CUDA context after a long idle. |
| Worker disappears when SSH session ends | Means it was launched ad-hoc, not via systemd. Run `systemctl restart prism42-worker` on the pod. The starter unit is at `agents/livekit/prism42-worker.service` — `systemctl enable --now prism42-worker`. |
| Browser connects but agent never speaks | Check `/tmp/prism42-logs/worker.log` for `registered worker` AND the LiveKit URL. If URL mismatches the token-mint URL, the worker is registered against the wrong LiveKit cluster. |
| Vercel alias `prism42-console.vercel.app` serves an old build | Git-based auto-deploy is wired (see Part 1 of the durability task) but Root Directory must be `mvp/911-console-live/` in the Vercel dashboard or the build fails silently. If the alias is stale, `vercel --prod` from `mvp/911-console-live/` as a recovery path. |
| `synthetic_caller.py` says `agent published audio but it's all silence` | Fish TTS ran but returned zeros — almost always a bad `FISH_VOICE_ID` in `/opt/prism42/.env.agent`. Fall back to `default` and re-run. |

## Logs to tail

```
tail -f /tmp/prism42-logs/worker.log          # LiveKit agent
tail -f /tmp/prism42-logs/worker-starter.log  # Deepgram+Cartesia escape-hatch
tail -f /tmp/prism42-logs/parakeet.log        # STT (only for ad-hoc nohup runs)
tail -f /tmp/prism42-logs/fish.log            # TTS (only for ad-hoc nohup runs)
```

For systemd-managed services, `journalctl -u prism42-worker -f` supersedes
the file tail.

## Env vars that MUST be present in `/opt/prism42/.env.agent`

- `ANTHROPIC_API_KEY` (Opus 4.7 for the agent)
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (must match the
  cluster the Vercel token-mint route is using)
- `PARAKEET_URL` (default `http://127.0.0.1:9100`)
- `FISH_SPEECH_URL` (default `http://127.0.0.1:9200`)
- `REDIS_URL` (default `redis://127.0.0.1:6379`)

For the starter (escape-hatch) worker only: `DEEPGRAM_API_KEY`,
`CARTESIA_API_KEY`. If either is missing the starter unit stays disabled
(by design — main worker path is self-hosted).
