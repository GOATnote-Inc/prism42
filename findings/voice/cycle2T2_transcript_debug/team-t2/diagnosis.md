# Team T2 — cycle-2T2 transcript-pane diagnosis + fix

Ship-by: 60 min. Status at write-time: **fix applied to local repo, awaiting deploy permission for shared pod**.

## TL;DR

DispatchPanel is blank because the cycle-2T response gate (`PRISM42_ENABLE_RESPONSE_GATE=1`) returns BEFORE the `publish_turn` hook in `orchestrator.py`. Cycle-2J's integration wired `publish_turn` ONLY in the LLM-fallthrough branch (line 372-384), so once cycle-2T flipped on and the gate started electing templates 100% of recent turns (per worker.log), the dispatcher data-channel went silent. Additionally, `publish_reply` only fires from `worker.py:_on_item` via `conversation_item_added`, which doesn't fire for `session.say()` template-only turns — so even when (rare) LLM turns happen, the reply text is missing for templates.

## Phase 1 evidence

| Step | Result | Evidence |
|---|---|---|
| 1. Publisher firing on pod | **NO** | `grep -c "dispatch_publisher" /tmp/prism42-logs/worker.log` = 0 |
| 2. Env flag hot | YES | `systemctl show prism42-worker -p Environment` shows `PRISM42_ENABLE_DISPATCH_PUBLISHER=1` (also `_FSM=1`, `_RESPONSE_GATE=1`) |
| 3. Code-sync local↔pod | YES | sha256 of orchestrator.py + worker.py + dispatch_publisher.py match |
| 4. publish_data reaching LiveKit | **N/A** | publish never called — gate short-circuits before publish_turn. Publisher's `_worker` task never started (lazy init). |
| 5. Browser receives event | **N/A** | nothing to receive — see step 1 |
| 6. DispatchPanel handler bound | YES | `useDataChannel("prism42.dispatch", ...)` is correctly wired in DispatchPanel.tsx:363; LiveCallRoom.tsx:164 mounts `<DispatchSubscription onEvent={onDispatchEvent}/>` inside `<LiveKitRoom>` and forwards via `externalEvent` to DispatchPanel.tsx:786 |

### Worker log (relevant lines, 2026-04-26 11:43-11:44)

```
11:43:47 orchestrator.cycle2q_fsm.enabled session_id=64f66f46...
11:43:49 greeting.911.dispatched         handle_id=speech_7d0d8fe4ca1d
11:43:56 orchestrator.gate_template_ms   intent=request_emergency cpr_blocked=False fallback_intent=None
11:44:04 response_gate.decision          intent=confirm_address used_template=True final_text='Got your address...'
11:44:04 orchestrator.gate_template_ms   intent=confirm_address
11:44:14 orchestrator.gate_template_ms   intent=deliver_reassurance
11:44:21 orchestrator.gate_template_ms   intent=kq_bleeding_location
```

Every turn = template path. Zero `dispatch_publisher.*` log lines. Zero `publish_*` log lines. Cycle-2T short-circuits 100% of recent traffic.

## Phase 2 — top suspect confirmed

Team J's caveat is the actual binding bug:

> "publish_turn only fires on LLM-fallthrough path per the integration spec. With cycle-2T response gate ON (PRISM42_ENABLE_RESPONSE_GATE=1), 20/21 intents are template-only, so they emit caller_partial + reply but NO turn event"

Caveat understated the situation:
- (A) `publish_turn` fires only on LLM-fallthrough. Gate's `return` at orchestrator.py:365 short-circuits.
- (B) `publish_reply` fires from `worker.py:_on_item` via `conversation_item_added` — but template-only turns use `session.say(decision.final_text, allow_interruptions=True)` which does NOT add a chat-context item (the LLM never produces an `assistant` conversation_item). So `publish_reply` is also a no-op for template turns.
- (C) `publish_caller_partial` was previously gated under `if is_final:` — only fires once per turn at STT-final. Should fire for interim transcripts too so the panel feels live.

So the panel is blank because A+B+C all break for the cycle-2T common case. **None of the events ever cross the data-channel boundary.**

## Phase 3 — fix applied (local)

Three additive patches landed locally; pod deploy gated on user permission.

### Patch 1 — orchestrator.py: lift publish_turn ABOVE gate-decision branch

`publish_turn` block moved from line 372-384 (LLM-fallthrough) to immediately after `intent = self._fsm.transition(utterance)`. Fires for every turn regardless of gate decision. (~14 LoC moved up; comment marker `cycle-2T2 Team T2 fix`.)

### Patch 2 — orchestrator.py: emit publish_reply from gate template path

After `self.session.say(decision.final_text, allow_interruptions=True)` succeeds in the gate template branch, also call `_dp.publish_reply(text=decision.final_text, ...)`. Without this the reply text never reaches the panel for the 20/21 template intents. (~14 LoC added inside the existing `else:` branch.)

### Patch 3 — worker.py + dispatch_publisher.py: observability + interim caller_partial

- `worker.py`: `dispatch_publisher.attach_attempt` (INFO) + `dispatch_publisher.attached` (INFO) — confirms init was even invoked.
- `dispatch_publisher.py`: log `dispatch_publisher.init` on construction; log first 3 successful `dispatch_publisher.published` events per session (then quiet); log `dispatch_publisher.no_local_participant` if room has no local participant when worker dequeues.
- `worker.py:_on_user_transcribed`: lift `publish_caller_partial(...)` OUT of `if is_final:` so interim transcripts also emit (panel shows "speaking..." pulse during caller speech instead of only at end-of-turn).

Total LoC delta: orchestrator.py +33 / -8, worker.py +20 / -8, dispatch_publisher.py +25 / -1. All additive; cycle-2T2 marker comments.

### Local verification

```
python3 -c "import ast; ast.parse(open('agents/livekit/orchestrator.py').read()); ast.parse(open('agents/livekit/worker.py').read()); ast.parse(open('agents/livekit/dispatch_publisher.py').read()); print('OK')"
OK: 3 files parse
```

### sha256 of patched files (local)

```
54011efcb47dfb93a90c46529f2d791f93ec21a7f18864eb1fd2e81fba033191  agents/livekit/orchestrator.py
96aa193ac593cffa66310a9b283382e562815c734ef2ce0383d2c67afb9d523b  agents/livekit/worker.py
b11b9947990293fd08d395497ba0902e134e6d7a04902be6f4fbd37637243482  agents/livekit/dispatch_publisher.py
```

### Note on cycle-2L StopResponse interaction

The local orchestrator.py also contains cycle-2L scaffolding (StopResponse import, `gate_emitted_template = False` flag) that the linter intentionally landed alongside the T2 patch. As of this snapshot, `gate_emitted_template = True` is set inside the gate-template branch but the actual `raise StopResponse()` re-raise outside the broad `except` is NOT yet present (the comment "StopResponse raised below" points at code that doesn't exist). This is **separate from T2's scope** — T2 fixes the dispatch-panel-blank failure, not the LLM-after-template-double-speak failure. Cycle-2L's resolution is for a follow-on team. T2's `publish_turn` and `publish_reply` calls live BEFORE and INSIDE the gate branch respectively, so they execute regardless of whether StopResponse is later raised.

## Phase 4 — verification plan (post-deploy)

Once user grants permission to scp + restart:

1. `scp /Users/kiteboard/prism42/agents/livekit/{orchestrator,worker,dispatch_publisher}.py prism-mla-b300-h4h5:/opt/prism42/agents/livekit/`
2. `ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-worker'`
3. `ssh prism-mla-b300-h4h5 'tail -F /tmp/prism42-logs/worker.log | grep dispatch_publisher' &`  → expect:
   - `dispatch_publisher.attach_attempt` (one per session)
   - `dispatch_publisher.attached`
   - `dispatch_publisher.init`
   - `dispatch_publisher.published seq=1` (caller_partial), seq=2 (turn), seq=3 (reply)
4. Open `https://prism42-console.vercel.app/prism42/livekit` in Chrome with DevTools → Network → WS filter. Speak a turn. In the LiveKit WSS frame look for `dataReceived` packets with topic `prism42.dispatch`.
5. If panel renders: GREEN. Surface to user for re-attestation.
6. If still blank but worker.log shows `dispatch_publisher.published`: bug is on the browser side. Check that DispatchSubscription mount is inside the active LiveKitRoom.

## Constraints honored

- ADDITIVE patches only; voice/Fish/Parakeet/Nemotron/vLLM untouched.
- Default-OFF flag respected: `PRISM42_ENABLE_DISPATCH_PUBLISHER=1` was already on (set via cycle-2U drop-in `/etc/systemd/system/prism42-worker.service.d/150-cycle2U-dispatch-publisher.conf`); no new flag introduced.
- Failure paths in patches are best-effort — voice loop never blocked; logs warn-only.

## Per-flag rollback

To roll back without code: `ssh prism-mla-b300-h4h5 'sudo rm /etc/systemd/system/prism42-worker.service.d/150-cycle2U-dispatch-publisher.conf && sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'`. With this drop-in absent, `PRISM42_ENABLE_DISPATCH_PUBLISHER` is unset → `is_enabled()` returns False → every publish call is a no-op.

To roll back orchestrator.py / worker.py / dispatch_publisher.py changes: `git checkout bf41a2d -- agents/livekit/orchestrator.py agents/livekit/worker.py agents/livekit/dispatch_publisher.py` then re-deploy. cycle-2J state restored.

## Files changed (local)

- `/Users/kiteboard/prism42/agents/livekit/orchestrator.py`
- `/Users/kiteboard/prism42/agents/livekit/worker.py`
- `/Users/kiteboard/prism42/agents/livekit/dispatch_publisher.py`
