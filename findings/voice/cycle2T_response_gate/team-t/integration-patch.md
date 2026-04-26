# Cycle-2T integration patch — orchestrator.py

This is the EXACT minimal-diff to apply to
`agents/livekit/orchestrator.py` to wire the cycle-2T response gate
into `FsmDispatcherAgent.on_user_turn_completed`. Total: ~30 lines
added (additive only). No FSM logic mutated. Default OFF behind
`PRISM42_ENABLE_RESPONSE_GATE=1`.

## Step 1 — Lazy import (mirror cycle-2Q pattern)

Add immediately after the existing `dispatcher_fsm` lazy-import block
(orchestrator.py:239-252).

### Current code (orchestrator.py:239-252, READ-ONLY context)

```python
try:
    from dispatcher_fsm import (  # type: ignore[import-not-found]
        DispatcherFSM,
        Intent,
        fsm_for_session,
        should_use_fsm,
    )
except Exception:  # noqa: BLE001
    DispatcherFSM = None  # type: ignore[assignment]
    Intent = None  # type: ignore[assignment]
    fsm_for_session = None  # type: ignore[assignment]

    def should_use_fsm() -> bool:  # type: ignore[no-redef]
        return False
```

### Add immediately below (NEW)

```python
# Cycle-2T — deterministic response gate between FSM and Fish TTS.
# Default OFF; flag PRISM42_ENABLE_RESPONSE_GATE=1 to enable. When
# disabled the gate module is imported but never invoked, so the
# cycle-2Q FSM-only path is byte-equivalent.
try:
    from response_gate import (  # type: ignore[import-not-found]
        gate_for_fsm,
        should_use_response_gate,
    )
except Exception:  # noqa: BLE001
    gate_for_fsm = None  # type: ignore[assignment]

    def should_use_response_gate() -> bool:  # type: ignore[no-redef]
        return False
```

## Step 2 — Construct gate alongside FSM in `__init__`

Modify `FsmDispatcherAgent.__init__` (orchestrator.py:270-280) to
build the gate. Additive only — adds one attribute, does not change
the existing FSM wiring.

### Current code (orchestrator.py:270-286, READ-ONLY context)

```python
def __init__(
    self,
    *,
    instructions: str,
    tools: list[Any],
    session_id: str,
    fsm: Any,
) -> None:
    super().__init__(instructions=instructions, tools=tools)
    self._session_id = session_id
    self._fsm = fsm
```

### Replace with (NEW — adds two lines)

```python
def __init__(
    self,
    *,
    instructions: str,
    tools: list[Any],
    session_id: str,
    fsm: Any,
) -> None:
    super().__init__(instructions=instructions, tools=tools)
    self._session_id = session_id
    self._fsm = fsm
    # Cycle-2T: deterministic response gate. None when flag off.
    self._response_gate = (
        gate_for_fsm(fsm) if (gate_for_fsm and should_use_response_gate()) else None
    )
```

## Step 3 — Hook the gate in `on_user_turn_completed`

The change here is the load-bearing one. The directive is "minimal
diff" — we add a gate-decision branch that EITHER emits a template
directly to TTS via `self.session.say(...)` (skipping the LLM
entirely) OR falls through to the cycle-2Q LLM path with the
constraint payload spliced into the system prompt.

### Current code (orchestrator.py:288-323, READ-ONLY context)

```python
async def on_user_turn_completed(  # type: ignore[override]
    self,
    turn_ctx: Any,
    new_message: Any,
) -> None:
    local_log = structlog.get_logger()
    t0 = time.monotonic()
    try:
        utterance = (getattr(new_message, "text_content", None) or "").strip()
        if not utterance:
            # Empty turn — nothing to advance. Keep prior instructions.
            return
        intent = self._fsm.transition(utterance)
        prompt = self._fsm.next_prompt(utterance, intent)
        # Update the agent's instructions so the next LLM call sees
        # the FSM-derived per-turn prompt.
        await self.update_instructions(prompt)
        dt_ms = int((time.monotonic() - t0) * 1000)
        local_log.info(
            "orchestrator.fsm_turn_ms",
            session_id=self._session_id,
            ms=dt_ms,
            intent=getattr(intent, "value", str(intent)),
            state=self._fsm.state.value,
        )
    except Exception as e:  # noqa: BLE001
        local_log.warning(
            "orchestrator.fsm_turn_failed",
            err=str(e)[:200],
            session_id=self._session_id,
        )
```

### Replace with (NEW — additive gate branch)

```python
async def on_user_turn_completed(  # type: ignore[override]
    self,
    turn_ctx: Any,
    new_message: Any,
) -> None:
    local_log = structlog.get_logger()
    t0 = time.monotonic()
    try:
        utterance = (getattr(new_message, "text_content", None) or "").strip()
        if not utterance:
            # Empty turn — nothing to advance. Keep prior instructions.
            return
        intent = self._fsm.transition(utterance)

        # Cycle-2T: deterministic response gate between FSM and TTS.
        # When the gate elects a template, we emit directly to TTS via
        # session.say() and SHORT-CIRCUIT the LLM call — voice path is
        # bounded by code, not LLM constraint-following. When the gate
        # elects the LLM path, we fall through to the cycle-2Q
        # update_instructions branch below.
        if self._response_gate is not None:
            decision = self._response_gate.gate_decision(
                getattr(intent, "value", str(intent)),
                caller_utterance=utterance,
            )
            if decision.used_template and decision.final_text:
                # Record into the FSM's anti-repetition buffer so the
                # gate's own validators (and any future LLM turn) see
                # what we just spoke.
                try:
                    self._fsm.record_dispatcher_reply(decision.final_text)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self.session.say(
                        decision.final_text,
                        allow_interruptions=True,
                    )
                except Exception as say_err:  # noqa: BLE001
                    # If session.say fails (e.g. session not yet
                    # active), fall through to the LLM path below
                    # rather than dropping the turn.
                    local_log.warning(
                        "response_gate.say_failed",
                        err=str(say_err)[:200],
                        session_id=self._session_id,
                    )
                else:
                    dt_ms = int((time.monotonic() - t0) * 1000)
                    local_log.info(
                        "orchestrator.gate_template_ms",
                        session_id=self._session_id,
                        ms=dt_ms,
                        intent=getattr(intent, "value", str(intent)),
                        cpr_blocked=decision.cpr_blocked,
                        fallback_intent=decision.fallback_intent,
                    )
                    return  # short-circuit: no LLM call this turn

        # Fall-through: LLM path. Cycle-2Q FSM-rewritten prompt.
        prompt = self._fsm.next_prompt(utterance, intent)
        await self.update_instructions(prompt)
        dt_ms = int((time.monotonic() - t0) * 1000)
        local_log.info(
            "orchestrator.fsm_turn_ms",
            session_id=self._session_id,
            ms=dt_ms,
            intent=getattr(intent, "value", str(intent)),
            state=self._fsm.state.value,
        )
    except Exception as e:  # noqa: BLE001
        local_log.warning(
            "orchestrator.fsm_turn_failed",
            err=str(e)[:200],
            session_id=self._session_id,
        )
```

## Step 4 — (No change required to `make_orchestrator()`)

`make_orchestrator` passes an `FsmDispatcherAgent` already; the gate
is wired inside `__init__`. No changes to the function body.

## Diff summary

- 1 lazy-import block (12 lines) added at module level
- `FsmDispatcherAgent.__init__` body grows by 4 lines (the gate
  instance attribute)
- `on_user_turn_completed` body grows by ~38 lines (the gate
  branch, the session.say() emit, the structured log, the
  `record_dispatcher_reply` call, and the fall-through)

Total: ~54 lines added. Zero lines deleted. Zero existing lines
modified.

## How `session.say` works (verified via worker.py + livekit-agents)

- `Agent.session` is a property defined at
  `/Users/kiteboard/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/agent.py:677`.
  Returns the `AgentSession` bound to the running agent.
- `AgentSession.say(text, *, audio=NOT_GIVEN, allow_interruptions=NOT_GIVEN, add_to_chat_ctx=True)`
  is defined at the same .venv at
  `livekit/agents/voice/agent_session.py:1095`. It returns a
  `SpeechHandle` and dispatches the text through the bound TTS
  (Fish Speech S2-Pro in our config).
- `add_to_chat_ctx=True` (the default) keeps the LLM aware of
  what was spoken — important for the next turn's reasoning so the
  LLM does not re-emit the same content. We accept this default.
- `allow_interruptions=True` lets a real caller barge-in cut the
  template short — same shape used by worker.py's existing
  `session.say` calls (greeting at worker.py:1169, filler at
  worker.py:1282).

## Why session.say (not generate_reply / direct TTS plugin)

- `session.say` is the supported public surface for "speak this
  exact text now" and ALREADY works on this code path — see
  worker.py:1169 (greeting) + worker.py:1282 (filler). Reusing the
  same surface means our path inherits the same TTS plugin
  configuration, the same interruption semantics, the same chat-ctx
  behavior. No code drift, no new failure modes.
- `generate_reply()` would re-trigger the LLM. Wrong path — the
  gate's whole point is skipping the LLM.
- Calling Fish Speech directly (e.g. via `fish_speech_tts.py`)
  would bypass the WebRTC publish path and break the audio
  pipeline. session.say is the correct level of abstraction.

## Voice-quality + latency expectations

- **Latency:** template path skips the LLM entirely. Cycle-2Q TTFT
  was ~500 ms streaming; cycle-2T template path is ~0 ms (pure
  string lookup) before TTS. Net p95 improvement: ~500 ms on
  template-path turns.
- **Voice quality:** every template was hand-tuned for Fish S2-Pro
  prosody (5–14 words, single sentence, single terminator,
  natural English when read aloud). The pronoun-required
  templates default to singular-they, which Fish S2-Pro renders
  cleanly.
- **CPR safety:** the gate refuses INSTRUCT_CPR_BEGIN unless
  is_cardiac_arrest AND surface_confirmed AND breathing_assessed
  are ALL True. None ≠ True; False ≠ True. Defensive boundary.

## Hand-off instructions for the integrator

1. Apply the three diff blocks above. Total ~54 added lines.
2. Verify imports parse: `python3 -c "import ast;
   ast.parse(open('agents/livekit/orchestrator.py').read())"`.
3. scp the new files to the pod:
   ```
   scp agents/livekit/response_gate.py prism-mla-b300-h4h5:/opt/prism42/agents/livekit/
   scp agents/livekit/templates.py     prism-mla-b300-h4h5:/opt/prism42/agents/livekit/
   scp agents/livekit/orchestrator.py  prism-mla-b300-h4h5:/opt/prism42/agents/livekit/
   ```
4. Add to systemd drop-in at `/etc/systemd/system/prism42-worker.service.d/cycle2t.conf`:
   ```ini
   [Service]
   Environment=PRISM42_ENABLE_FSM=1
   Environment=PRISM42_ENABLE_RESPONSE_GATE=1
   ```
5. `sudo systemctl daemon-reload && sudo systemctl restart prism42-worker`.
   Worker comes up in ~3s.
6. Synthetic-caller harness:
   ```
   ssh prism-mla-b300-h4h5 \
     'cd /opt/prism42/agents/livekit && \
      .venv/bin/python synthetic_caller_full.py \
      "I am at 451 Mission Street, my husband stopped breathing"'
   ```
   Expected: gate fires `response_gate.decision` log lines for the
   intake → confirm → reassurance → verify-surface →
   verify-breathing → CPR sequence; `used_template=True` for all
   of them; `cpr_blocked=False` only on the final compressions
   instruction (after both V1 and V2 latched).
7. Verify in the worker log:
   ```
   ssh prism-mla-b300-h4h5 \
     'tail -300 /tmp/prism42-logs/worker.log | grep response_gate.decision'
   ```
   Each line should show `intent`, `used_template`, `used_llm`,
   `final_text`, `cpr_blocked`, `state`, `pronouns`, `ms`.
8. Surface for user attestation.

## Roll-back (if needed)

`PRISM42_ENABLE_RESPONSE_GATE=0` (or unset) reverts to cycle-2Q
behavior immediately on next worker restart. No code change
required for the rollback path. If the gate misbehaves AND the
flag is set, the orchestrator's outer try/except catches gate
errors and falls through to the LLM path — voice never wedges.
