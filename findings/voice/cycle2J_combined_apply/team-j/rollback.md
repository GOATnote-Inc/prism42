# Cycle-2J — Rollback Procedures (Team J)

Three independent kill-switches. Rollback is granular: revert one cycle
at a time, or all three in order.

---

## Per-flag rollback (preferred — no code changes)

Each cycle's behavior is gated by env flag(s) read by the worker process.
Removing the flag reverts behavior to the cycle-2Q baseline on next
worker restart.

### Cycle-2I rollback

```
ssh prism-mla-b300-h4h5 'sudo rm /etc/systemd/system/prism42-worker.service.d/130-cycle2I-barge-in.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
```

Result: filler suppression OFF (P1 disabled because
`PRISM42_FILLER_INTAKE_DISABLE` unset → defaults to "1" in the code,
so to *fully* revert, set the flag to "0":

```
echo '[Service]
Environment="PRISM42_FILLER_INTAKE_DISABLE=0"
Environment="PRISM42_ENDPOINT_MIN_DELAY_S=0.6"
Environment="PRISM42_ENDPOINT_MAX_DELAY_S=4.0"
Environment="PRISM42_VAD_MIN_SILENCE_S=0.55"' | \
  ssh prism-mla-b300-h4h5 'sudo tee /etc/systemd/system/prism42-worker.service.d/130-cycle2I-barge-in.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
```

That restores cycle-2Q values byte-equivalently
(`min_delay=0.6`, `max_delay=4.0`, `min_silence_duration=0.55` which is
the Silero default — equivalent to omitting the kwarg).

### Cycle-2T rollback

```
ssh prism-mla-b300-h4h5 'sudo rm /etc/systemd/system/prism42-worker.service.d/140-cycle2T-response-gate.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
```

Result: `should_use_response_gate()` returns False, gate is None,
`on_user_turn_completed` skips the gate branch entirely and falls through
to the cycle-2Q LLM path. Byte-equivalent to pre-2T behavior.

### Cycle-2U rollback

```
ssh prism-mla-b300-h4h5 'sudo rm /etc/systemd/system/prism42-worker.service.d/150-cycle2U-dispatch-publisher.conf'
ssh prism-mla-b300-h4h5 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
```

Result: `is_enabled()` returns False, the publisher is constructed but
all `publish_*` methods short-circuit on the `if not self._enabled: return`
check. Frontend's `dataReceived` listener gets zero events; UI falls back
to whatever the SSE bus is providing (the existing `_post_turn_to_bus`
path is unaffected).

### Full rollback (all three)

```
ssh prism-mla-b300-h4h5 '\
  sudo rm /etc/systemd/system/prism42-worker.service.d/130-cycle2I-barge-in.conf \
         /etc/systemd/system/prism42-worker.service.d/140-cycle2T-response-gate.conf \
         /etc/systemd/system/prism42-worker.service.d/150-cycle2U-dispatch-publisher.conf && \
  sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
```

Worker restarts in ~3 s, returns to cycle-2Q FSM-only behavior. (Same
behavior as `5b455f6` PASS_2R baseline.)

---

## Per-commit rollback (revert source-of-truth)

Each cycle was committed atomically so individual reverts are clean:

| Cycle | Commit | Revert |
|---|---|---|
| 2U | `bf41a2d` | `git revert bf41a2d` (touches 4 files) |
| 2T | `9149dfc` | `git revert 9149dfc` (touches `agents/livekit/orchestrator.py`) |
| 2I | `a2bffe1` | `git revert a2bffe1` (touches `agents/livekit/worker.py`) |

To revert all three:

```
git revert -m 1 bf41a2d 9149dfc a2bffe1
```

(Or one-by-one, in reverse chronological order, to keep the chain linear.)

After revert, re-deploy:

```
# From repo root, with mvp/911-console-live/.vercel/project.json swap trick:
cp .vercel/project.json /tmp/prism42-root-project.json.bak
cp mvp/911-console-live/.vercel/project.json .vercel/project.json
vercel deploy --prod --yes
cp /tmp/prism42-root-project.json.bak .vercel/project.json

# scp + install on pod, then daemon-reload + restart.
```

---

## Frontend-only rollback (Vercel)

If the issue is purely the new TS code (DispatchPanel.tsx caller_partial
arm), revert just that and re-deploy:

```
git checkout HEAD~3 -- mvp/911-console-live/components/DispatchPanel.tsx
# (commit + redeploy)
```

The worker continues publishing dispatch events; the frontend just
ignores `caller_partial` events instead of rendering a transient line.
(Same behavior as the 31-LoC minimum variant of cycle-2U.)

---

## What rollback does NOT touch

- `response_gate.py`, `templates.py`, `dispatch_publisher.py` — these
  are NEW modules. They remain on disk but are unreachable when env
  flags are off (lazy-import + `if not enabled: return`).
- Caddy / DNS / LiveKit-server config.
- Parakeet / Fish / Nemotron / vLLM service config.
- Pre-existing systemd drop-ins (50-/70-/100-/110-/120-).
- Cycle-2R cutover state — worker stays on selfhost
  `wss://prism42.thegoatnote.com`.

---

## Single-command sanity after rollback

```
curl -sIo /dev/null -w "%{http_code}\n" https://prism42-console.vercel.app/prism42/livekit
ssh prism-mla-b300-h4h5 'systemctl is-active prism42-worker'
ssh prism-mla-b300-h4h5 'cd /opt/prism42/agents/livekit && timeout 60 .venv/bin/python synthetic_caller.py 2>&1 | tail -10'
```

Expected: `200`, `active`, and `VERDICT: PASS — agent spoke ...`.
