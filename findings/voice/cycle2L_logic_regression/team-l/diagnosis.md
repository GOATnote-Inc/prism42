# Cycle-2L Team L — diagnosis + fix

Dispatcher re-asks opening question after gate template — root cause + minimal patch.

## TL;DR

The cycle-2T integration patch (commit `9149dfc`) emits a deterministic
template via `self.session.say(...)` and returns from
`on_user_turn_completed`. **It does NOT cancel LiveKit Agents 1.5.x's
preemptive-generation LLM stream that has already started in parallel**
(`agent_activity.py:1898` kicks off the LLM generation BEFORE
`on_user_turn_completed` is called). Both fire — caller hears the gate
template, then a second reply from the LLM running against
`FAST_DISPATCHER_SYSTEM_PROMPT`. The LLM has zero FSM state and is told
to say "Nine one one, what is the address of your emergency?" verbatim
on the first turn, so it re-emits that line.

Fix: raise `livekit.agents.llm.StopResponse` from
`on_user_turn_completed` after a successful gate template emission.
`agent_activity.py:1973` catches it and `return`s before scheduling the
preemptive speech handle (`agent_activity.py:2040`), so the second reply
never plays.

## Evidence (from /tmp/prism42-logs/worker.log)

Session `64f66f46-4dae-a9cd-5a60-b93583bbecdb`, turn 2 (caller said
"Chest pain and shortness of breath." — note address-known was already
latched on turn 1):

```
11:44:04 fsm.transition          intent=confirm_address state=address_confirmed turns=2
11:44:04 response_gate.decision  intent=confirm_address used_template=True final_text='Got your address and dispatching help to you.'
11:44:04 overlap.llm_first_token_after_speech_ms ms=8050 source=say     <-- gate template via session.say
11:44:04 orchestrator.gate_template_ms intent=confirm_address
11:44:04 overlap.llm_first_token_after_speech_ms ms=8051 source=generate_reply  <-- LLM ALSO ran
11:44:07 fishspeech.done audio_duration_ms=2461  total_ms=2168          <-- TTS playback #1 (template)
11:44:08 fishspeech.done audio_duration_ms=1811  total_ms=3440          <-- TTS playback #2 (LLM reply)
```

Two TTS playbacks per turn. The first is the gate template; the second
is the LLM-driven reply from `FAST_DISPATCHER_SYSTEM_PROMPT` ("First
turn — verbatim: Nine one one, what is the address of your emergency?").
The LLM has no per-turn state across the gate path, so its reply is
governed entirely by the static system prompt.

## Hypothesis ranking (per directive)

1. ~~Address-detection regex~~ — falsified by logs: `address_known=True`
   is set correctly on turn 1.
2. ~~Template mapping bug in templates.py~~ — falsified: gate emits the
   correct templates ("What is happening...", "Got your address...",
   "Help is on the way..."). Mapping is correct.
3. ~~Stale state in `gate_decision`~~ — falsified: gate logs the right
   intent and the right final_text every turn.
4. **`update_instructions(prompt)` not relevant — the regression is a
   different mechanism**. The LLM path that re-asks the address is the
   PREEMPTIVE-GENERATION path that started BEFORE on_user_turn_completed
   ran, so it never sees `update_instructions`. It uses the agent's
   constructor-time `instructions` (FAST_DISPATCHER_SYSTEM_PROMPT).
5. ~~Intent classifier mis-fire~~ — falsified: intent classifier emits
   `confirm_address` / `request_emergency` / etc. correctly. The bug is
   the LLM running IN PARALLEL with the gate, not the FSM mis-firing.

True root cause is closest to hypothesis 4 but differs in mechanism:
the LLM path runs even when the gate emits a template, because the
preemptive generation has already started and is not cancelled by
`return` from `on_user_turn_completed`.

## The fix (applied)

`agents/livekit/orchestrator.py`:

1. Import `StopResponse` from `livekit.agents.llm` (with try/except
   shim for backward compat — the import lands on 1.5+).
2. Set a local flag `gate_emitted_template` when the gate emits a
   template successfully (after `session.say` did not raise).
3. After the existing broad `try/except Exception` (which exists to
   prevent the FSM from wedging the voice path), raise `StopResponse`
   when `gate_emitted_template` is True. The raise is OUTSIDE the
   `except Exception` so it cannot be silenced.

The fix is ~25 lines additive. No FSM mutated. No template mutated. No
gate logic mutated. Default-OFF preserved by reusing the existing
`self._response_gate is not None` guard (which is `None` unless
`PRISM42_ENABLE_RESPONSE_GATE=1`).

## Rollback paths (in order of preference)

1. **Revert this commit** — `git revert <cycle-2L-commit>`. Worker
   restart picks up.
2. **Disable response gate** — set `PRISM42_ENABLE_RESPONSE_GATE=0` in
   the systemd drop-in (`/etc/systemd/system/prism42-worker.service.d/`).
   `systemctl daemon-reload && systemctl restart prism42-worker`. The
   StopResponse code path is gated on `self._response_gate is not None`
   (which is `None` when the flag is off), so disabling the gate
   automatically disables the StopResponse path. Worker reverts to
   cycle-2Q FSM-rewritten-prompt + LLM behavior.
3. **Disable FSM entirely** — `PRISM42_ENABLE_FSM=0`. Reverts to
   cycle-2P system-prompt-only behavior.

## Verification commands

On B300 after deploy:

```bash
ssh b300-pod
sudo systemctl restart prism42-worker.service
tail -F /tmp/prism42-logs/worker.log | grep -E "fsm\.transition|response_gate|orchestrator\.gate_template_ms|fishspeech.done"
```

User-driven verification on https://prism42-console.vercel.app/prism42/livekit:

3-turn test script:

1. After greeting "Nine one one, what is the address of your
   emergency?", say: **"Twelve Riverside Drive."**
   - Expected: ONE reply — "What is happening at that location?"
   - Bug repro pre-fix: ALSO heard "Nine one one, what is the address..."
   - Verify in log: ONE `fishspeech.done` per turn (NOT two).
2. Say: **"Chest pain and shortness of breath."**
   - Expected: ONE reply — "Got your address and dispatching help to
     you." (or similar gate template).
3. Say: **"My friend stopped breathing."**
   - Expected: ONE reply — "Are they on the floor, flat on their back?"
     (verify-CPR-surface gate template).

If all three turns have exactly one `fishspeech.done` event per turn
and no `request_location_and_emergency` template fires after turn 1,
the regression is fixed.

## Files touched

- `agents/livekit/orchestrator.py` — +25 lines, additive only

## Files NOT touched

- `agents/livekit/dispatcher_fsm.py` — frozen
- `agents/livekit/templates.py` — frozen
- `agents/livekit/response_gate.py` — frozen (gate logic correct)
- `agents/livekit/worker.py` — frozen
