# Cycle-2R Team A — LiveKit data-track JSON spec for the dispatcher UI

**Author:** Team A (cycle-2R, 2026-04-26)
**Code skeleton:** `/Users/kiteboard/prism42/agents/livekit/dispatch_publisher.py`

## Goal

Let the PSAP-CAD-style frontend (Team F) render dispatcher state turn-by-turn
without hooking into Python — by streaming structured JSON over an existing
LiveKit data-track. Default OFF, additive-only, fail-soft. Voice components
(Parakeet, Fish, Nemotron, MW voice, FSM, voice logic) are **frozen** —
this publisher only READS from them.

## Topic + transport

- **Topic:** `prism42.dispatch`
- **Reliability:** `reliable=True` (loss would be visible in the UI; data is
  small).
- **Channel:** `room.local_participant.publish_data(payload, reliable=True,
  topic="prism42.dispatch")` — the same surface already used by
  `_publish_latency_dict` in `worker.py:1419` and `_publish_latency` at
  `worker.py:1419` (1.5.6 surface; do NOT use the `kind=DataPacket_Kind.RELIABLE`
  legacy form — it's gone in livekit-agents 1.5.6).
- **Frontend filter:**
  ```js
  room.on('dataReceived', (payload, participant, kind, topic) => {
    if (topic !== 'prism42.dispatch') return;
    const ev = JSON.parse(new TextDecoder().decode(payload));
    if (ev.type === 'turn')   handleTurn(ev);
    if (ev.type === 'reply')  handleReply(ev);
  });
  ```
- **Coexistence:** The `b3-latency` topic is already used for the V2 latency
  strip (`worker.py:1422`, `worker.py:1478`). `prism42.dispatch` is a
  separate topic; the two streams are independent and the frontend MUST
  filter on `topic` before parsing.

## Why two event types

`turn` fires in `on_user_turn_completed` AFTER the FSM has advanced and
AFTER `update_instructions(prompt)` — at that moment we know the new state +
the new intent + the caller utterance, but the dispatcher has not yet
spoken. This is the right slice for the CAD-style left-rail to render
"current state / current intent / latched facts."

`reply` fires in the `conversation_item_added` (assistant role) handler
AFTER the dispatcher utterance has been finalized and TTS is in flight — at
that moment we know the realized text and have the TTS timing fields. This
is the right slice for the CAD-style transcript panel to render the
dispatcher line.

Two events keep the UI's render contract simple: state always renders before
the line that came out of that state.

## Event schemas

### `turn`

```json
{
  "type": "turn",
  "session_id": "<lk-session-id>",
  "turn_index": 1,
  "timestamp_ms": 1714150000000,
  "caller_utterance": "He's not breathing!",
  "fsm": {
    "state": "critical_verify",
    "intent": "verify_cpr_surface",
    "verify_step": "q_surface",
    "pronouns": "he/him",
    "reassurance_done": true,
    "is_cardiac_arrest": true,
    "address_known": true,
    "emergency_known": true,
    "complaint": "medical",
    "turns": 4
  },
  "latched_facts": [
    "address_known",
    "emergency_known",
    "reassurance_delivered",
    "cardiac_arrest",
    "third_party_caller"
  ],
  "recent_replies": [
    "What's the address of the emergency?",
    "OK, help is coming. Stay with me.",
    "Is he on the floor flat on his back?"
  ],
  "latency_ms": {
    "stt": 312,
    "llm_ttft": 420,
    "tts_ttfb": 0
  }
}
```

Refinements vs the brief:
- **`fsm.state` enum** is the actual `State` enum (lowercase string from
  `State.<X>.value`): `intake`, `address_confirmed`,
  `reassurance_delivered`, `key_questions`, `pre_arrival`,
  `critical_verify`, `critical_cpr`, `handoff`. Note: `critical_cpr`, not
  `handoff` only — there are 8 states, not 7.
- **`fsm.intent`** is `Intent.<X>.value` — see `dispatcher_fsm.py:113-141`
  for the full 22-value enum (e.g. `verify_cpr_surface`,
  `instruct_cpr_compressions`, `closeout`).
- **`fsm.verify_step`** is `q_surface | q_breathing | done` (the
  `VerifyStep` enum). Outside `critical_verify` this remains the most
  recent value (FSM never resets it after exiting verify) — frontend
  should ignore unless `state == 'critical_verify'`.
- **`fsm.pronouns`** is `unknown | they | he/him | she/her` — note the
  `he/him` form (the FSM stores the slash form, not bare `he`).
- **`fsm.complaint`** is `medical | fire | trauma | crime | unknown` —
  added because the FSM tracks it and the UI may want to color-code.
- **`fsm.emergency_known`** added — symmetric with `address_known`,
  exposed on the FSM dataclass.
- **`fsm.turns`** is the total turn count from the FSM (separate from the
  publisher's `turn_index` so the UI can detect drops).
- **`latched_facts`** is the projected flat string list — not a duplicate
  of the booleans in `fsm`. Includes `cpr_surface_confirmed`,
  `cpr_breathing_assessed`, `third_party_caller`. UI uses this for the
  chip-strip; the booleans in `fsm` are the source of truth.
- **`recent_replies`** = `list(fsm.recent_replies)` (deque of last 3).
- **`latency_ms`** is best-effort. At `on_user_turn_completed` time the
  STT duration is usually known but LLM TTFT and TTS TTFB are not (LLM
  hasn't started). The publisher should be called with whatever timing
  exists in the `_timing_bucket` at that instant; missing fields = 0.

### `reply`

```json
{
  "type": "reply",
  "session_id": "<lk-session-id>",
  "turn_index": 1,
  "timestamp_ms": 1714150001234,
  "text": "OK, is he on the floor flat on his back?",
  "tts_ttfb_ms": 198,
  "tts_total_ms": 920
}
```

`turn_index` MUST equal the most recent `turn` event's `turn_index` so the
UI can pair them. The publisher (`dispatch_publisher.py`) holds a counter
that's incremented in `publish_turn` and re-used in `publish_reply` until
the next `publish_turn` increments it.

## Hook points (NOT yet wired)

This deliverable produces the spec + the publisher class. Wiring is a
follow-up minimal patch, not done here.

### Hook 1 — turn

`agents/livekit/orchestrator.py:288` —
`FsmDispatcherAgent.on_user_turn_completed`. The current implementation
already runs `intent = self._fsm.transition(utterance)` then
`prompt = self._fsm.next_prompt(utterance, intent)` then
`await self.update_instructions(prompt)`. Insert ONE line right after
`update_instructions` to call the publisher. Because the agent doesn't
hold a reference to `Room` today, the cleanest path is:

1. Worker constructs the `DispatchPublisher` in `entrypoint` after
   `orchestrator = make_orchestrator(session_id)` and BEFORE
   `await session.start(...)`.
2. Worker attaches the publisher to the orchestrator as
   `orchestrator._dispatch_publisher = publisher` (no API change to
   `make_orchestrator`).
3. `on_user_turn_completed` reads it via
   `getattr(self, "_dispatch_publisher", None)` — same defensive pattern
   already used for `getattr(orchestrator, "fsm", None)` in
   `worker.py:911`.

### Hook 2 — reply

`agents/livekit/worker.py:898` — `_on_item` (the `conversation_item_added`
listener). Already handles `role == "assistant"` and already extracts
`text = getattr(item, "text_content", None)`. Add ONE call to
`publisher.publish_reply(text=text, tts_ttfb_ms=..., tts_total_ms=...)`
inside the existing `try` block, AFTER the `fsm.record_dispatcher_reply`
call (so the FSM rolling buffer is updated before the publish — the publish
captures the pre-update view of `recent_replies`, which is what the UI
wants for "what just got said").

The TTS timings come from the same `bucket = _timing_bucket(session_id)`
already populated by the metrics_collected listener.

## Integration patch (minimal-diff additions)

Below shows the exact additive-only diffs. Voice path is byte-equivalent
when `PRISM42_ENABLE_DISPATCH_PUBLISHER=0` (default).

### `agents/livekit/worker.py`

Add an import near the existing FSM lazy-import block (around line 56):
```python
# (additive) cycle-2R Team A — dispatcher data-track publisher.
try:
    from dispatch_publisher import DispatchPublisher, is_enabled as _dp_enabled
except Exception:  # noqa: BLE001
    DispatchPublisher = None  # type: ignore[assignment]
    def _dp_enabled() -> bool:  # type: ignore[no-redef]
        return False
```

After `orchestrator = make_orchestrator(session_id)` (line 813) add:
```python
    # (additive) cycle-2R Team A — wire dispatch publisher (no-op when flag OFF).
    if DispatchPublisher is not None and _dp_enabled():
        try:
            _dp = DispatchPublisher(ctx.room, session_id)
            orchestrator._dispatch_publisher = _dp  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            log.warning("dispatch_publisher.init_failed", err=str(e)[:200])
```

Inside `_on_item` (around line 915), AFTER
`fsm.record_dispatcher_reply(text)` and BEFORE the existing
`bucket = _timing_bucket(session_id)` block, add:
```python
        # (additive) cycle-2R Team A — emit reply event for dispatcher UI.
        try:
            _dp = getattr(orchestrator, "_dispatch_publisher", None)
            if _dp is not None:
                _bucket_now = _timing_bucket(session_id)["current"]
                _dp.publish_reply(
                    text=getattr(item, "text_content", "") or "",
                    tts_ttfb_ms=int(_bucket_now.get("tts_ttfb_ms", 0) or 0),
                    tts_total_ms=int(_bucket_now.get("tts_ms", 0) or 0),
                )
        except Exception as e:  # noqa: BLE001
            log.warning("on_item.dispatch_publish_failed", err=str(e)[:200])
```

Net delta: ~16 added lines, 0 modified, 0 deleted.

### `agents/livekit/orchestrator.py`

Inside `FsmDispatcherAgent.on_user_turn_completed` (around line 304),
AFTER `await self.update_instructions(prompt)` and BEFORE the
`local_log.info("orchestrator.fsm_turn_ms", ...)` call, add:
```python
            # (additive) cycle-2R Team A — emit turn event for dispatcher UI.
            try:
                _dp = getattr(self, "_dispatch_publisher", None)
                if _dp is not None:
                    _dp.publish_turn(
                        caller_utterance=utterance,
                        fsm=self._fsm,
                        latency_ms={},  # latency populated by reply event
                    )
            except Exception as e:  # noqa: BLE001
                local_log.warning(
                    "orchestrator.dispatch_publish_failed", err=str(e)[:200]
                )
```

Net delta: ~10 added lines, 0 modified, 0 deleted.

## Failure modes + safety

- **Publisher fails to import** → wrapped in try/except; voice path unchanged.
- **Flag off** → publisher is a no-op (early return in `publish_turn` /
  `publish_reply`); zero allocations, zero queue, zero worker task.
- **Queue full** → drop-oldest, never block. UI gets a discontinuity (the
  `turn_index` jump tells it).
- **`local_participant.publish_data` raises** → caught in worker task; voice
  path unaffected (worker is a separate asyncio task on the event loop).
- **Frontend not subscribed** → LiveKit drops to floor; reliable channel
  reconnect handles late-joiner state via the room's per-track buffers
  (LiveKit's default reliable-channel semantics).

## Testing plan (post-integration; not part of this deliverable)

1. With `PRISM42_ENABLE_DISPATCH_PUBLISHER=0` (default): run the
   synthetic_caller harness and confirm zero log lines containing
   `dispatch_publisher.*`. Ensures OFF-mode is byte-equivalent.
2. With `PRISM42_ENABLE_DISPATCH_PUBLISHER=1`: capture LiveKit data events
   on the frontend and verify `turn` events fire on every caller utterance,
   `reply` events fire on every dispatcher utterance, `turn_index` is
   monotonic and `reply.turn_index == turn.turn_index` for the same pair.
3. Latency budget: the publisher's `publish_turn` is synchronous (enqueue)
   and the actual `publish_data` runs in the background worker task; turn
   handler latency MUST not regress beyond noise on the
   `orchestrator.fsm_turn_ms` log line. Sanity check: <2 ms regression at
   p50.

## Reference: per-event-types vs single-event-type

Considered combining into one `event` schema with a discriminator field.
Rejected — the two events have meaningfully different lifetimes (turn fires
before reply, both per logical turn) and pairing them in a single payload
would force the publisher to buffer until the reply lands, which adds state
the publisher should not own. Two events, paired by `turn_index`, is the
standard pattern (matches LiveKit's own state events).
