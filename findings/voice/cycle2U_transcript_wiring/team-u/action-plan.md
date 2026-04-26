# cycle-2U / Team U — Action plan

**Author:** Team U, 2026-04-26
**Recommended path:** **Option #1 with a preemptive STT add-on** — wire Team A's existing `dispatch_publisher.py` per the data-track-spec patch, AND add one new event type `caller_partial` emitted from the existing `user_input_transcribed` handler so the caller's STT shows up while they're still speaking. Lowest risk, highest leverage, single source of truth, retains "contemporaneous" feel.

## Why not Option #2 (`lk.transcription` text-stream)

Tempting because we get streaming transcripts free from the SDK. Rejected because:

1. **Two sources of truth.** Caller text would arrive on `lk.transcription`; FSM state + latched facts + latency would arrive on `prism42.dispatch`. The DispatchPanel reducer is currently a single state machine fed by ONE event stream. Splitting it forces a join that's painful to keep in sync (which event arrived first? which `turn_index` does the transcription belong to?).
2. **`registerTextStreamHandler` is a low-level Room API call** — needs an effect that calls `room.registerTextStreamHandler` on `useRoomContext()` and unregisters on unmount. New code surface in DispatchPanel.tsx, not just a new component.
3. **Team A's spec already includes `caller_utterance` in the `turn` event** (data-track-spec.md:67) — the dispatch_publisher already plans to ship the caller's final transcript on the same data-track. We only need ONE additive event type to recover the streaming-while-speaking behavior.

## Why not Option #3 (full data-track redesign)

Option #1 + the small `caller_partial` add-on covers Option #3's "interim STT" goal while staying within Team A's spec discipline. No reason to rewrite.

## Recommended path — file-by-file change list

### 1. Apply Team A's integration patch verbatim

#### `agents/livekit/worker.py`

- **+5 lines after line 56** (the existing imports block): try-import `DispatchPublisher` + `is_enabled`. Default to `None` if the module is missing.
- **+6 lines after line 813** (`orchestrator = make_orchestrator(session_id)`): if flag enabled, construct `DispatchPublisher(ctx.room, session_id)` and attach as `orchestrator._dispatch_publisher`. Wrapped in try/except that warns and continues.
- **+10 lines inside `_on_item` (around line 915, after `fsm.record_dispatcher_reply(text)`)**: read `orchestrator._dispatch_publisher`; if non-None, call `_dp.publish_reply(text=..., tts_ttfb_ms=..., tts_total_ms=...)` from `_timing_bucket(session_id)["current"]`. Wrapped in try/except.

**Risk:** None when flag OFF — the imports tolerate missing module, the publisher is `None`, the calls become no-ops. Voice path byte-equivalent.
**Rollback:** `unset PRISM42_ENABLE_DISPATCH_PUBLISHER && systemctl restart prism42-worker`.

#### `agents/livekit/orchestrator.py`

- **+10 lines inside `on_user_turn_completed` (after line 304 `await self.update_instructions(prompt)`)**: read `getattr(self, "_dispatch_publisher", None)`; if non-None, call `_dp.publish_turn(caller_utterance=utterance, fsm=self._fsm, latency_ms={})`. Wrapped in try/except that logs and continues.

**Risk:** Add-only; the `try` block already catches anything from the FSM transition path; the new try is independent. Voice path unchanged when `_dp is None`.
**Rollback:** Same as above.

### 2. Add the new `caller_partial` event (small additive change)

#### `agents/livekit/dispatch_publisher.py`

- **+~15 lines** — add a third public method `publish_caller_partial(text: str, is_final: bool)` that emits an `{"type": "caller_partial", "text": ..., "is_final": ..., "turn_index": ..., "timestamp_ms": ...}` event on the same topic. Same enqueue path. Re-uses `self._turn_index` (does NOT increment — partials live within the current turn).

#### `agents/livekit/worker.py`

- **+~6 lines inside the existing `user_input_transcribed` handler (around line 1059-1106)**: after the existing `caller_spoke.set()` call, if the publisher is attached, call `_dp.publish_caller_partial(text=text, is_final=is_final)`. The handler already receives both interim and final events.

#### `mvp/911-console-live/components/DispatchPanel.tsx`

- **+~20 lines** — extend `DispatchEvent` union with `DispatchCallerPartialEvent`; add a `caller_partial` reducer case that overwrites a transient "current caller line" state slot. Render that slot at the bottom of the transcript with a subtle "speaking…" indicator. On `turn` event, the partial slot is cleared because the `turn.caller_utterance` becomes the canonical row.

**Risk:** Frontend reducer is the only state owner; the `caller_partial` action only mutates one new field, the existing `transcript` array is untouched.
**Rollback:** Revert the DispatchPanel.tsx hunk; the dispatch_publisher caller-partial method becomes harmless emissions the frontend ignores.

## Default-OFF env-flag pattern

The whole feature gates on the existing `PRISM42_ENABLE_DISPATCH_PUBLISHER=1` flag. When unset:

- `dispatch_publisher.is_enabled()` returns False.
- `DispatchPublisher` is constructed (cheap), but every public method early-returns at the `if not self._enabled: return` guard (existing lines 141-142, 165-166).
- No queue, no worker task, no `publish_data` calls. Zero cost.
- Worker.py's import is wrapped in try/except → import failures don't even crash the worker.

Optional `PRISM42_ENABLE_CALLER_PARTIAL=1` sub-flag if we want to gate the partials separately (e.g. ship dispatch publisher first, prove it on staging, then turn partials on). Default OFF if added; keep it simple unless the demo today needs the toggle.

## Verification

**ON-mode (transcript should populate):**

1. On the pod: `export PRISM42_ENABLE_DISPATCH_PUBLISHER=1 && systemctl restart prism42-worker`.
2. From a browser, open `https://prism42-console.vercel.app/prism42/livekit`, click "Speak to the dispatcher", say one short sentence (e.g. "There's been an accident on Main Street").
3. **Expected on the page:** within ~300 ms of speech-end the caller line appears in the DispatchPanel transcript ("There's been an accident on Main Street."), and within ~5-10 s the dispatcher's reply appears below it. The FSM state badge updates from `intake` → `address_confirmed` (or whatever the FSM transitioned to).
4. **Browser DevTools console** — confirm `[useDataChannel] received message on topic prism42.dispatch` (or a JSON-decoded `{type:"turn",...}` log if you add one).
5. **Pod log** — `journalctl -u prism42-worker | grep dispatch_publisher` should show the publisher worker task running. NO `dispatch_publisher.publish_failed` lines on a healthy room.

**OFF-mode (voice path byte-equivalent):**

1. `unset PRISM42_ENABLE_DISPATCH_PUBLISHER && systemctl restart prism42-worker`.
2. Repeat the call.
3. **Expected:** voice loop indistinguishable from current behavior — same TTS first-frame latency, same b3-latency events, same SSE turn events. The DispatchPanel stays at "Waiting for the first caller utterance." (the bug we're fixing only when ON).
4. **Pod log** — zero lines containing `dispatch_publisher.*`. If any line appears, the OFF-gate has a leak.

**Latency regression check:** the existing `orchestrator.fsm_turn_ms` log line at orchestrator.py:306 should not move by >2 ms p50 between OFF and ON modes. The `publish_turn` call is enqueue-only; the actual `publish_data` runs on the worker task. Acceptable budget per data-track-spec.md:281-286.

## Ship-by

This is a ~50-line additive change (26 from Team A's spec verbatim + ~25 for the partial extension). One commit per file: worker.py / orchestrator.py / dispatch_publisher.py / DispatchPanel.tsx. Total integrator time ~30-45 min including the verification call. Fits well inside the 90-min ship-by budget for cycle-2U.

## What NOT to do

- Do not register `lk.transcription` in parallel — single source of truth. If we discover later that streaming-tokens-while-LLM-generates is needed, that's a cycle-2V, not now.
- Do not put the chat-bubble SSE transcript back. The DispatchPanel is the new UI contract; we close the gap by feeding it events, not by reverting it.
- Do not skip the env flag. Default-OFF is the contract; the dispatcher voice path is frozen this sprint and the publisher must be a clean side-effect.
