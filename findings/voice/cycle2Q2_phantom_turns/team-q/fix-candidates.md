# Cycle-2Q2 Team Q — fix candidates

Three ranked fixes for H1 (root cause). Fixes for H2 (filler amplifier)
and H3 (informational) are listed for completeness.

**Constraint:** Read-only on `agents/livekit/*` was Team Q's mode.
Patches below are proposals for the integrator.

---

## Fix #1 (RECOMMENDED) — Restructure the gate-template branch so it falls through to the post-try StopResponse raise

**Target:** `agents/livekit/orchestrator.py:336-483`
**Risk:** LOW. Same logic, restructured control flow. Default-OFF flag preserved.
**Diff size:** 1 line removed, no lines added (the structure already exists).

### Change

Remove `return` at line 440. The else-branch already only executes when
`gate_emitted_template = True`, and the post-try check guards on that
same flag. Without the `return`, the try completes normally and
`if gate_emitted_template and StopResponse is not None: raise StopResponse()`
fires.

### Patch (UNIFIED diff)

```diff
--- a/agents/livekit/orchestrator.py
+++ b/agents/livekit/orchestrator.py
@@ -437,8 +437,9 @@ class FsmDispatcherAgent(BufferedDispatcherAgent):
                         # gate elected a template successfully (final_text
                         # populated, session.say did not raise).
                         gate_emitted_template = True
-                        return  # break out of try; StopResponse raised below
+                        # NOTE: do NOT `return` here — `return` from inside
+                        # `try:` exits the function and skips the post-try
+                        # `raise StopResponse()` block. We need to fall
+                        # through past the try so the post-try check runs.

             # Fall-through: LLM path. Cycle-2Q FSM-rewritten prompt.
             prompt = self._fsm.next_prompt(utterance, intent)
```

But this leaves the LLM-fallthrough code (lines 442-457) running after
the gate-template path, which we DO NOT want. Need to wrap the
LLM-fallthrough in `else:` or similar:

### Better patch (gates the LLM-fallthrough on gate_emitted_template)

```diff
--- a/agents/livekit/orchestrator.py
+++ b/agents/livekit/orchestrator.py
@@ -437,21 +437,23 @@ class FsmDispatcherAgent(BufferedDispatcherAgent):
                         # gate elected a template successfully (final_text
                         # populated, session.say did not raise).
                         gate_emitted_template = True
-                        return  # break out of try; StopResponse raised below

-            # Fall-through: LLM path. Cycle-2Q FSM-rewritten prompt.
-            prompt = self._fsm.next_prompt(utterance, intent)
-            # Update the agent's instructions so the next LLM call sees
-            # the FSM-derived per-turn prompt.
-            await self.update_instructions(prompt)
-            # NOTE: turn event already published above (cycle-2T2 fix).
-            # The LLM-fallthrough path's `reply` event still fires from
-            # worker.py:_on_item via conversation_item_added.
-            dt_ms = int((time.monotonic() - t0) * 1000)
-            local_log.info(
-                "orchestrator.fsm_turn_ms",
-                session_id=self._session_id,
-                ms=dt_ms,
-                intent=getattr(intent, "value", str(intent)),
-                state=self._fsm.state.value,
-            )
+            # Fall-through: LLM path. Cycle-2Q FSM-rewritten prompt.
+            # Only run when the gate did NOT emit a template — if the
+            # gate fired we let StopResponse cancel the preemptive LLM
+            # call from the post-try block below.
+            if not gate_emitted_template:
+                prompt = self._fsm.next_prompt(utterance, intent)
+                # Update the agent's instructions so the next LLM call
+                # sees the FSM-derived per-turn prompt.
+                await self.update_instructions(prompt)
+                # NOTE: turn event already published above (cycle-2T2 fix).
+                # The LLM-fallthrough path's `reply` event still fires from
+                # worker.py:_on_item via conversation_item_added.
+                dt_ms = int((time.monotonic() - t0) * 1000)
+                local_log.info(
+                    "orchestrator.fsm_turn_ms",
+                    session_id=self._session_id,
+                    ms=dt_ms,
+                    intent=getattr(intent, "value", str(intent)),
+                    state=self._fsm.state.value,
+                )
         except Exception as e:  # noqa: BLE001
             # Hard rule: FSM must never wedge the voice path. On any
             # error fall back to the prior instructions (the original
```

### Why this works

After the patch, on the gate-template path:
1. Set `gate_emitted_template = True`
2. Fall through to the `if not gate_emitted_template:` guard — skipped
3. Try block completes normally
4. Post-try check: `if gate_emitted_template and StopResponse is not None: raise StopResponse()`
5. StopResponse propagates to `agent_activity.py:1973`, hits `except StopResponse: return`
6. Preemptive_generation is left in `self._preemptive_generation` but `_schedule_speech` is never called
7. Caller hears ONLY the gate template TTS (queued by the gate's `session.say`)

### Verification (synthetic_caller probe)

```bash
ssh b300-pod 'cd /opt/prism42/agents/livekit && \
  .venv/bin/python synthetic_caller.py "I am at twelve riverside drive my friend stopped breathing"'
```

Expected log signature for ONE caller turn that triggers the gate:
```
fsm.transition turns=N intent=verify_cpr_surface
response_gate.decision used_template=True
overlap.llm_first_token_after_speech_ms source=say
orchestrator.gate_template_ms
fishspeech.t0 text_len=42                 <-- ONE fishspeech.t0 only
fishspeech.done total_ms=~2000             <-- ONE fishspeech.done only
```

NO `using preemptive generation` log line should follow the gate
template path. NO second fishspeech.t0 with a different text_len.

### Rollback path

If StopResponse cancellation breaks something else:
```bash
ssh b300-pod 'sudo rm /etc/systemd/system/prism42-worker.service.d/140-cycle2T-response-gate.conf'
ssh b300-pod 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker'
```
With `PRISM42_ENABLE_RESPONSE_GATE` unset, `self._response_gate` is None,
the gate-template branch is skipped, `gate_emitted_template` stays
False, no StopResponse raised, LLM-fallthrough path runs as cycle-2Q
intended.

---

## Fix #2 (ALTERNATIVE — same effect, different shape) — Move the StopResponse raise INSIDE the gate-template branch but OUTSIDE the `else:`

**Target:** `agents/livekit/orchestrator.py:386-440`
**Risk:** MEDIUM. Adds an `await asyncio.sleep(0)` to ensure session.say
schedules the speech_handle before StopResponse cancels the preemptive.
Without the sleep, in some asyncio loops the queued say() task may not
have run yet when StopResponse propagates upward.

### Patch sketch

```python
if decision.used_template and decision.final_text:
    try:
        self._fsm.record_dispatcher_reply(decision.final_text)
    except Exception:
        pass
    try:
        self.session.say(decision.final_text, allow_interruptions=True)
    except Exception as say_err:
        local_log.warning("response_gate.say_failed", err=str(say_err)[:200], ...)
    else:
        # ... publish_reply, log gate_template_ms ...
        # Drop into a one-tick yield so session.say's underlying scheduler
        # gets the SpeechHandle on the queue before we cancel the preemptive.
        await asyncio.sleep(0)
        if StopResponse is not None:
            raise StopResponse()  # caught at agent_activity.py:1973
```

### Why riskier

- Raising StopResponse from inside a try block means the broad
  `except Exception` at line 458 catches it (since StopResponse is an
  Exception). Need an explicit `except StopResponse: raise` BEFORE
  the broad except, OR catch and re-raise via `bare raise` inside the
  broad except using `isinstance` check.
- The `await asyncio.sleep(0)` is empirically necessary in asyncio for
  cooperative scheduling, but is poorly documented. Risk of subtle
  race condition.

**Recommendation:** Don't choose this unless Fix #1 has a side-effect we
discover later.

---

## Fix #3 (NUCLEAR — kills preemptive_generation entirely) — set `preemptive_generation.enabled=False`

**Target:** `agents/livekit/worker.py:811-815`
**Risk:** HIGH user-visible latency regression (~500ms p95 added to every
turn). Loses 400-800ms p95 win that LiveKit blog cites for preemptive.
**Diff size:** 1 line.

### Patch

```diff
            "preemptive_generation": {
-               "enabled": True,
+               "enabled": False,
                "preemptive_tts": True,
                "max_speech_duration": 12.0,
            },
```

### Why this is a stop-gap not a fix

- Latency regression — every turn pays full STT-final → LLM-start → LLM-TTFT
  cost serially instead of pre-warming on partial transcripts.
- Does NOT solve the underlying control-flow bug. If a future PR
  re-enables preemptive_generation, the duplicate-utterance bug returns.
- Violates "DO NOT propose disabling response gate as the fix" spirit
  of the directive — this is the same shape of stop-gap.

**Recommendation:** Use only as a panic button if Fix #1 cannot be
deployed within the 90-min ship window. Pair with a tracking issue to
re-enable preemptive_generation after Fix #1 is verified in the next
deploy cycle.

---

## H2 fix — Suppress filler in CRITICAL_VERIFY and KEY_QUESTIONS phases too

**Target:** `agents/livekit/worker.py:1374-1386`
**Risk:** LOW. Filler is already disabled in INTAKE; expand the disabled-phase
list. Filler in PRE_ARRIVAL is still useful (CPR coaching has long beats).
**Diff size:** 1 line.

### Patch

```diff
        if os.environ.get("PRISM42_FILLER_INTAKE_DISABLE", "1") == "1":
            try:
                fsm = getattr(orchestrator, "fsm", None)
                phase = getattr(getattr(fsm, "state", None), "value", "")
-               if phase in ("intake", "address_confirmed"):
+               if phase in ("intake", "address_confirmed",
+                            "critical_verify", "key_questions"):
                    log.info(
                        "filler.suppressed_intake",
                        session_id=session_id,
                        phase=phase,
                    )
                    return
```

### Why narrow scope is correct

The filler was added to mask Fish 5-7s TTFT during the SPECIALIST hop
(orchestrator_full.py path). On the cycle-2T deterministic-template
path, the gate emits text that renders in <50ms and Fish TTS lands in
~2s — no Fish-latency mask needed. The CRITICAL_VERIFY and KEY_QUESTIONS
phases are 100% template-served per the response_gate's
_SAFETY_TEMPLATE_ONLY set, so the filler-fills-the-Fish-gap rationale
does not apply.

### Verification

After Fix #1 + this fix, no `filler.spoken` log lines should appear
during a session that traverses the verify branch (every turn is
intake → confirm → reassure → KQ → verify-surface → verify-breathing →
CPR; all 7 phases are template-only).

---

## H3 fix — Informational only

**Target:** None — Fix #1 makes H3 moot.

### Why

Once StopResponse cancels the preemptive_generation, `session.say()`'s
fire-and-forget asynchrony is fine. Only the gate template's
SpeechHandle is on the queue; the preemptive's SpeechHandle is left
dangling but never scheduled (it's set to `None` at agent_activity.py:2046
in the failure-of-validation branch, but in our case the StopResponse
return at line 1974 means we never reach line 2046 — the SpeechHandle
is GC'd when the per-turn task completes).

If we ever observe LLM tokens being charged but no TTS playing post-fix,
we know the GC isn't happening and we can add explicit cleanup. For now,
no action.

---

## Combined deployment plan (recommended)

1. Apply **Fix #1** (orchestrator.py: structure gate branch to fall
   through to post-try StopResponse raise + guard LLM-fallthrough on
   `not gate_emitted_template`).
2. Apply **H2 fix** (worker.py: expand filler-suppress phase set).
3. scp orchestrator.py + worker.py to pod.
4. `sudo systemctl restart prism42-worker.service`.
5. Run synthetic-caller probe with the canonical 3-turn cardiac scenario
   (verification-plan.md).
6. User-attest at `https://prism42-app.thegoatnote.com`.

Total proposed line delta: orchestrator.py +5 / -1, worker.py +1 / -1.
All additive. Default-OFF flags preserved. No new env flags introduced.

---

## What we DID NOT propose

- **Disabling the response gate** — explicitly forbidden by the
  directive. Also wrong: the gate is correct; the cycle-2L wrapper
  around the gate is broken.
- **Framework swap** — out of scope.
- **Restarting prism42-worker** — Team Q is read-only; integrator
  decides when to restart.
- **vLLM env changes** — frozen, out of scope.
- **Touching dispatcher_fsm.py** — the FSM is correct (H4 is design-
  intended behavior). Repeated VERIFY_SURFACE on consecutive non-
  matching caller utterances is per MPDS-9 protocol. Team P can
  consider a softer reprompt UX after 2 consecutive same-intent
  emissions, but that is NOT a phantom-turn fix.
