# Orchestrator Hook — Patch Spec for Pattern 2 + Pattern 6

Team B, cycle-2B, 2026-04-26. **Spec only — do NOT apply during cycle-2B research.** Wiring lands in a separate cycle-2C ship after this spec is reviewed.

## Files touched

- `agents/livekit/orchestrator.py` — additive ~25 LoC inside `FsmDispatcherAgent.on_user_turn_completed` (after the existing FSM/gate decision, before the LLM-fallthrough branch).
- `agents/livekit/worker.py` — additive ~10 LoC at the existing parallel-evaluator wiring site (`on_user_turn_completed` background tasks).

Total: ~35 LoC additive. Zero existing-line modifications. Both behind env flags that default OFF — when both flags are unset, the byte-for-byte behaviour matches today.

## orchestrator.py — Pattern 2 (Fallback) hook

### Current control flow (orchestrator.py §324-492, summarized)

```
on_user_turn_completed(turn_ctx, new_message):
    utterance = new_message.text
    intent = self._fsm.transition(utterance)
    publish_turn(...)                                  # cycle-2T2
    if self._response_gate is not None:
        decision = response_gate.gate_decision(intent, utterance)
        if decision.used_template:
            session.say(decision.final_text)
            publish_reply(...)
            gate_emitted_template = True               # cycle-2L
    if not gate_emitted_template:
        prompt = self._fsm.next_prompt(utterance, intent)
        await self.update_instructions(prompt)         # LLM falls through
    if gate_emitted_template:
        raise StopResponse()                           # cancel preemptive LLM
```

### Hook for Pattern 2 — added immediately AFTER `await self.update_instructions(prompt)` and BEFORE the StopResponse re-raise

The fallback fires only when:
1. `gate_emitted_template is False` (LLM-fallthrough path).
2. `claude_brain.should_use_claude_brain()` returns True.
3. The Nemotron output (which arrives later in `worker.py`'s `conversation_item_added` handler) fails one of the three validators: gendered_without_commit, repeats_prior_phrase, exceeds_word_cap.

Because the Nemotron stream is preemptive — already kicked off by LiveKit by the time `on_user_turn_completed` runs (CLAUDE.md / orchestrator.py §428-438) — the fallback **cannot run synchronously inside `on_user_turn_completed`**. Instead the hook stashes the FSM context onto `self._pending_fallback`; `worker.py`'s `conversation_item_added` handler reads it after the LLM yields its full reply, runs the validators, and only then dispatches to `claude_brain.regenerate(...)`.

#### Patch sketch

```python
# orchestrator.py §451-466 — extend the LLM-fallthrough branch.

if not gate_emitted_template:
    prompt = self._fsm.next_prompt(utterance, intent)
    await self.update_instructions(prompt)
    # CYCLE-2B Pattern 2 — stash the per-turn fallback context for
    # worker.py's post-LLM hook to pick up. This is just a metadata
    # write; the actual claude_brain.regenerate(...) call happens after
    # Nemotron finishes streaming, in worker.py.
    try:
        from claude_brain import should_use_claude_brain  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        should_use_claude_brain = lambda: False  # type: ignore[assignment]
    if should_use_claude_brain():
        self._pending_fallback = {
            "session_id": self._session_id,
            "caller_text": utterance,
            "intent": getattr(intent, "value", str(intent)),
            "prior_dispatcher_reply": (
                self._fsm.last_dispatcher_reply()
                if hasattr(self._fsm, "last_dispatcher_reply")
                else ""
            ),
            "pronoun_committed": (
                getattr(self._fsm, "pronouns", "unknown") != "unknown"
            ),
        }
    else:
        self._pending_fallback = None

    dt_ms = int((time.monotonic() - t0) * 1000)
    local_log.info(
        "orchestrator.fsm_turn_ms",
        session_id=self._session_id,
        ms=dt_ms,
        intent=getattr(intent, "value", str(intent)),
        state=self._fsm.state.value,
        fallback_armed=self._pending_fallback is not None,
    )
```

A new instance attribute `_pending_fallback: dict | None` initialized to `None` in `__init__` (after the existing `self._response_gate = ...` line). Default of None means worker.py's hook is a no-op — and on the gate-template path the fallback never arms.

### worker.py — wire the fallback execution

The existing `conversation_item_added` handler (`worker.py:_on_item`) is where the assistant turn lands after the LLM yields. Add a post-yield validator + claude_brain call. Sketch:

```python
# worker.py — inside the conversation_item_added handler, after the
# existing record-into-FSM + publish_reply lines.

agent = session.agent  # FsmDispatcherAgent or BufferedDispatcherAgent
pending = getattr(agent, "_pending_fallback", None)
if pending is not None and item.role == "assistant":
    rejected_text = item.text_content or ""
    # Reuse the existing validators from response_gate.py — DO NOT
    # duplicate the regex/word-cap logic here; keep one source of truth.
    from response_gate import validate_llm_output  # noqa: PLC0415
    vresult = validate_llm_output(
        rejected_text,
        pronoun_committed=pending["pronoun_committed"],
    )
    if not vresult.ok:
        # Lazy import to keep claude_brain off the default-OFF path.
        from claude_brain import regenerate  # noqa: PLC0415
        result = await regenerate(
            session_id=pending["session_id"],
            caller_text=pending["caller_text"],
            rejected_reply=rejected_text,
            prior_dispatcher_reply=pending["prior_dispatcher_reply"],
            intent=pending["intent"],
            pronoun_committed=pending["pronoun_committed"],
        )
        if result.final_text is not None:
            # Speak the rewrite. session.say is the same hammer the
            # response_gate template path uses (orchestrator.py §386).
            session.say(result.final_text, allow_interruptions=True)
            try:
                agent.fsm.record_dispatcher_reply(result.final_text)
            except Exception:  # noqa: BLE001
                pass
        # On any failure_mode, leave the original Nemotron output in
        # place — Fish has already started speaking it; we accept the
        # validator-flagged output rather than the silence of a failed
        # rewrite.
    agent._pending_fallback = None  # consume one-shot
```

**Critical:** the `session.say(result.final_text)` path will overlay the rewrite **after** Fish has spoken the rejected text. This is acceptable for a hackathon-ship of a backstop — the operator hears "Caller: I think he's not breathing." → "He stopped breathing — keep him still." (rejected, gendered) → "They stopped breathing — keep them still." (rewrite, ungendered). Two replies in series.

A future enhancement (cycle-2C) is to **interrupt** the queued Fish playback before it begins by stalling on `session.tts.is_speaking()` and only releasing the LLM output once the validator passes. That requires deeper LiveKit Agents 1.5.x plumbing and is out of scope for cycle-2B.

## worker.py — Pattern 6 (Critic) hook

### Current parallel-evaluator wiring (worker.py:786 + specialists.py:206-323)

The safety-monitor / ohca-detector / intent-verifier triplet already runs as `asyncio.create_task(...)` on `on_user_turn_completed` via the LiveKit agent's background-task mechanism. The critic mirrors this exactly — same place, same pattern, no new infra.

### Patch sketch

```python
# worker.py — alongside the existing triplet's create_task wiring.
# Path: search for `run_safety_monitor` invocations; add the critic
# as a fourth task at the same call site.

from claude_brain import score as critic_score, should_use_claude_critic  # noqa: PLC0415

if should_use_claude_critic():
    asyncio.create_task(
        critic_score(
            session_id=session_id,
            caller_text=utterance,
            dispatcher_reply=last_dispatcher_reply,   # from SessionStore
            prior_dispatcher_reply=prior_dispatcher_reply,
            intent=intent_value,
        )
    )
```

The `CriticScore` returned is awaited inside the task; on completion the task's structlog `claude_critic.score` event lands in the dashboard via the existing structlog pipeline. No additional plumbing required for the demo path.

For the dashboard surface, `claude_brain.get_token_usage_snapshot()` exposes a synchronous read that `dispatch_publisher.py` can poll once per turn.

## Verification

Both hooks land behind env flags. `make verify-all` is green when both flags are unset (default-OFF). With each flag flipped on, add two unit tests under `tests/`:

1. `test_claude_brain_fallback_default_off.py` — assert `should_use_claude_brain()` returns False without the env flag, and that `regenerate(...)` returns `BrainResult(final_text=None, ...)` with `failure_mode == ""` (the no-op path).
2. `test_claude_brain_critic_default_off.py` — same shape for the critic.

Plus one integration test (using a mocked `AsyncAnthropic`):

3. `test_claude_brain_timeout_falls_back.py` — assert that when the mocked `messages.create` sleeps for 600ms, `regenerate(...)` returns within 500ms ± 50ms with `failure_mode == "timeout"`.

## Not included in this patch

- No prompt caching (`cache_control: ephemeral`) on the system prompts — adds ~3 LoC and cuts cost ~50%, but increases the patch surface. Defer to cycle-2C.
- No regression-detector wiring on the critic output — the rubric lands in structlog and that's enough for the demo. Wiring rubric → SessionStore.alerts is a follow-up.
- No fine-grained rate limiting beyond the per-process semaphore — if you need cross-worker rate limiting (multiple LiveKit workers per pod), wire the existing Redis SessionStore as the counter source.
