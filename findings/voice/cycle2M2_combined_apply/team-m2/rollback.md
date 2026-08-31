# Cycle-2M2 Team M2 — rollback procedures

**Granularity:** per-fix git revert + worker restart. Each of the 5 commits is independent so any one can be reverted without disturbing the others.

## Commit chain (newest first)

```
f670979 voice/cycle2P2-fix-C3: dispatcher_fsm.py — spelled-cardinal -> digit normalizer in classify()
8710f6b voice/cycle2P2-fix-A3: dispatcher_fsm.py — _intent_in_verify routes direct questions
d232b44 voice/cycle2P2-fix-A1: dispatcher_fsm.py — gate cardiac short-circuit on positive cue or third-party context
b7eb08c voice/cycle2Q2-fix-2: worker.py — extend filler-suppress to CRITICAL_VERIFY and KEY_QUESTIONS
fce8115 voice/cycle2Q2-fix-1: orchestrator.py — remove return inside try so StopResponse actually fires
```

## Single-fix revert procedure

For ANY individual fix, the workflow is identical (substitute the SHA):

```
# 1. Revert in the local repo (creates a new commit; does NOT rewrite history)
cd ~/prism42
git revert <SHA>

# 2. scp the affected file(s) back to the pod
scp ~/prism42/agents/livekit/<file>.py b300-pod:/tmp/

# 3. Install on the pod
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/<file>.py /opt/prism42/agents/livekit/<file>.py'

# 4. Restart worker
ssh b300-pod 'sudo systemctl restart prism42-worker && sleep 5 && systemctl is-active prism42-worker'

# 5. Confirm worker re-registered
ssh b300-pod 'tail -20 /tmp/prism42-logs/worker.log | grep "registered worker" | tail -1'
```

## Per-fix rollback recipes

### Rollback Q-fix-1 (orchestrator.py StopResponse fix)

```
git revert fce8115
scp ~/prism42/agents/livekit/orchestrator.py b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/orchestrator.py /opt/prism42/agents/livekit/orchestrator.py'
ssh b300-pod 'sudo systemctl restart prism42-worker'
```

Effect: the dead-code `raise StopResponse()` returns; double-utterance bug returns. Use only if the StopResponse cancel breaks the LLM-fallthrough path.

### Rollback Q-fix-2 (worker.py filler suppress)

```
git revert b7eb08c
scp ~/prism42/agents/livekit/worker.py b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/worker.py /opt/prism42/agents/livekit/worker.py'
ssh b300-pod 'sudo systemctl restart prism42-worker'
```

Effect: filler `"I'm with you."` returns to firing in CRITICAL_VERIFY and KEY_QUESTIONS phases.

### Rollback P-fix-A1 (dispatcher_fsm.py cardiac short-circuit gate)

```
git revert d232b44
scp ~/prism42/agents/livekit/dispatcher_fsm.py b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/dispatcher_fsm.py /opt/prism42/agents/livekit/dispatcher_fsm.py'
ssh b300-pod 'sudo systemctl restart prism42-worker'
```

Effect: cardiac short-circuit reverts to wide-net behavior; first-person "I can't breathe" mis-routes to CRITICAL_VERIFY again.

Note: dispatcher_fsm.py contains 3 fixes (A1 + A3 + C3). When reverting one, the other two remain because they're separate commits. Git revert applies cleanly via the patch model.

### Rollback P-fix-A3 (dispatcher_fsm.py direct-question router)

```
git revert 8710f6b
scp ~/prism42/agents/livekit/dispatcher_fsm.py b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/dispatcher_fsm.py /opt/prism42/agents/livekit/dispatcher_fsm.py'
ssh b300-pod 'sudo systemctl restart prism42-worker'
```

Effect: `_intent_in_verify` no longer routes direct questions; "Should I move him?" mid-verify gets re-asked the verify question.

### Rollback P-fix-C3 (dispatcher_fsm.py spelled-cardinal normalizer)

```
git revert f670979
scp ~/prism42/agents/livekit/dispatcher_fsm.py b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/dispatcher_fsm.py /opt/prism42/agents/livekit/dispatcher_fsm.py'
ssh b300-pod 'sudo systemctl restart prism42-worker'
```

Effect: "one hundred ocean avenue" no longer latches address on turn 1; STT output must contain a literal digit.

## Full rollback (all 5 patches)

```
git revert f670979 8710f6b d232b44 b7eb08c fce8115
scp ~/prism42/agents/livekit/orchestrator.py    b300-pod:/tmp/
scp ~/prism42/agents/livekit/worker.py          b300-pod:/tmp/
scp ~/prism42/agents/livekit/dispatcher_fsm.py  b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/orchestrator.py    /opt/prism42/agents/livekit/orchestrator.py'
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/worker.py          /opt/prism42/agents/livekit/worker.py'
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/dispatcher_fsm.py  /opt/prism42/agents/livekit/dispatcher_fsm.py'
ssh b300-pod 'sudo systemctl restart prism42-worker && sleep 5 && systemctl is-active prism42-worker'
```

Returns the agent to its pre-cycle-2M2 state (cycle-2L deploy with the dead-code StopResponse).

## Safety notes

- Do NOT touch `/etc/systemd/system/prism42-worker.service.d/*.conf` for these rollbacks. The fixes are pure source-level; no env-flag changes were introduced.
- Do NOT use `--force` on the worker restart unless the simple `restart` command stalls. The systemd service has watchfiles which catches SIGTERM cleanly.
- Do NOT restart vLLM as part of any rollback. None of the 5 patches touched vLLM-adjacent code.
- All commits use the standard footer with `Co-Authored-By: Claude Opus 4.7`. Reverts will preserve traceability.
