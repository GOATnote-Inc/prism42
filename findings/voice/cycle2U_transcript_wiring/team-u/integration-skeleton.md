# cycle-2U / Team U — Integration skeleton (mechanical patches)

**Author:** Team U, 2026-04-26
**Status:** Read-only patch authoring. The integrator applies these mechanically. Every block is **additive only** — no existing line is modified or deleted.

Convention used below: `[ADD AFTER LINE N]` means insert the new lines so the first new line becomes line N+1; the existing line N stays put. All line numbers are against the current `main` HEAD as observed by Team U on 2026-04-26.

---

## Patch 1 — `agents/livekit/worker.py` (try-import the publisher)

**Current code at lines 54-57** (existing imports):
```python
from fish_speech_tts import FishSpeechOptions, FishSpeechTTS
from grader import grade_turn_with_shim_fallback
from orchestrator import make_orchestrator
from parakeet_stt import ParakeetOptions, ParakeetSTT
```

**[ADD AFTER LINE 57]** (one new import block, 5 lines):
```python
# (additive) cycle-2R Team A — dispatcher data-track publisher.
try:
    from dispatch_publisher import DispatchPublisher, is_enabled as _dp_enabled
except Exception:  # noqa: BLE001
    DispatchPublisher = None  # type: ignore[assignment]
    def _dp_enabled() -> bool:  # type: ignore[no-redef]
        return False
```

---

## Patch 2 — `agents/livekit/worker.py` (construct + attach publisher)

**Current code at line 813**:
```python
    orchestrator = make_orchestrator(session_id)
```

**[ADD AFTER LINE 813]** (6 new lines):
```python
    # (additive) cycle-2R Team A — wire dispatch publisher (no-op when flag OFF).
    if DispatchPublisher is not None and _dp_enabled():
        try:
            _dp = DispatchPublisher(ctx.room, session_id)
            orchestrator._dispatch_publisher = _dp  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            log.warning("dispatch_publisher.init_failed", err=str(e)[:200])
```

---

## Patch 3 — `agents/livekit/worker.py` (publish_reply on assistant item)

**Current code at lines 913-917** (inside `_on_item`, after the role gate):
```python
            fsm = getattr(orchestrator, "fsm", None)
            if fsm is not None:
                text = getattr(item, "text_content", None)
                if text:
                    fsm.record_dispatcher_reply(text)
```

**[ADD AFTER LINE 917]** (10 new lines, BEFORE the existing `try:` block at line 918):
```python
        # (additive) cycle-2R Team A — emit reply event for dispatcher UI.
        try:
            _dp = getattr(orchestrator, "_dispatch_publisher", None)
            if _dp is not None:
                _bucket_now = _timing_bucket(session_id)["current"]
                _dp.publish_reply(
                    text=getattr(item, "text_content", "") or "",
                    tts_ttfb_ms=int(_bucket_now.get("tts_ms", 0) or 0),
                    tts_total_ms=int(_bucket_now.get("tts_ms", 0) or 0),
                )
        except Exception as e:  # noqa: BLE001
            log.warning("on_item.dispatch_publish_failed", err=str(e)[:200])
```

(Note: `tts_total_ms` re-uses `tts_ms` because the live worker's `_timing_bucket` does not separately track TTS-total — only TTFB. If a future cycle tracks both, the second arg can be swapped without UI change; the frontend treats `tts_total_ms == tts_ttfb_ms` gracefully.)

---

## Patch 4 — `agents/livekit/worker.py` (publish_caller_partial on STT)

**Current code at lines 1094-1106** (inside `_on_user_transcribed`, the `if is_final:` block):
```python
            if is_final:
                now = time.monotonic()
                if cur.get("t_stt_end") is None:
                    cur["t_stt_end"] = now
                # LLM request kicks off as soon as the transcript is final.
                if cur.get("t_llm_start") is None:
                    cur["t_llm_start"] = now
                # Push caller turn to the dispatcher SSE bus so the
                # /prism42/livekit transcript panel renders live.
                if text:
                    asyncio.create_task(
                        _post_turn_to_bus(session_id, "user", text)
                    )
```

**[ADD AFTER LINE 1106]** (6 new lines, BEFORE the existing `# If we missed the VAD ...` comment at line 1107):
```python
                # (additive) cycle-2U — caller-partial → dispatch data-track.
                try:
                    _dp = getattr(orchestrator, "_dispatch_publisher", None)
                    if _dp is not None and text:
                        _dp.publish_caller_partial(text=text, is_final=is_final)
                except Exception as e:  # noqa: BLE001
                    log.warning("on_user_transcribed.dispatch_publish_failed", err=str(e)[:200])
```

(Indented 16 spaces to live inside the `if is_final:` block. If we want partials BEFORE final too, hoist the call out of the `if is_final` block and indent 12 spaces — but ship the final-only version first; it already gives the user a row that appears the moment STT commits.)

---

## Patch 5 — `agents/livekit/orchestrator.py` (publish_turn on FSM advance)

**Current code at lines 304-312** (inside `on_user_turn_completed`):
```python
            await self.update_instructions(prompt)
            dt_ms = int((time.monotonic() - t0) * 1000)
            local_log.info(
                "orchestrator.fsm_turn_ms",
                session_id=self._session_id,
                ms=dt_ms,
                intent=getattr(intent, "value", str(intent)),
                state=self._fsm.state.value,
            )
```

**[ADD AFTER LINE 304]** (10 new lines, BEFORE the existing `dt_ms = ...` at line 305):
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

---

## Patch 6 — `agents/livekit/dispatch_publisher.py` (add publish_caller_partial)

**Current code at lines 176-177** (end of `publish_reply`, before `aclose`):
```python
        }
        self._enqueue(evt)

    async def aclose(self) -> None:
```

**[ADD AFTER LINE 177]** (15 new lines, BEFORE `async def aclose`):
```python
    def publish_caller_partial(
        self,
        *,
        text: str,
        is_final: bool,
    ) -> None:
        """Fire a `caller_partial` event for streaming caller-side STT.
        Lives within the current turn — does NOT increment turn_index."""
        if not self._enabled:
            return
        evt = {
            "type": "caller_partial",
            "session_id": self._session_id,
            "turn_index": self._turn_index,
            "timestamp_ms": _now_ms(),
            "text": text or "",
            "is_final": bool(is_final),
        }
        self._enqueue(evt)

```

---

## Patch 7 — `mvp/911-console-live/components/DispatchPanel.tsx` (consume caller_partial)

**Current code at lines 100-110** (the event-type union):
```typescript
export interface DispatchReplyEvent {
  type: "reply";
  session_id: string;
  turn_index: number;
  timestamp_ms: number;
  text: string;
  tts_ttfb_ms: number;
  tts_total_ms: number;
}

export type DispatchEvent = DispatchTurnEvent | DispatchReplyEvent;
```

**[ADD AFTER LINE 108]** (10 new lines, BEFORE the existing `DispatchEvent` union):
```typescript
export interface DispatchCallerPartialEvent {
  type: "caller_partial";
  session_id: string;
  turn_index: number;
  timestamp_ms: number;
  text: string;
  is_final: boolean;
}
```

**MODIFY LINE 110** to add the new arm to the union:
```typescript
export type DispatchEvent = DispatchTurnEvent | DispatchReplyEvent | DispatchCallerPartialEvent;
```

(This is the one non-additive line in the integration — extending a union type.)

**[ADD AFTER LINE 142]** (the existing `Action` type, add a new arm):
```typescript
  | { kind: "caller_partial"; ev: DispatchCallerPartialEvent }
```

**[ADD AFTER LINE 224]** (the existing `case "reply":` block — add a new case before `default:`):
```typescript
    case "caller_partial": {
      // Partials live in a transient slot, not the transcript array.
      // The next `turn` event clears the slot since `turn.caller_utterance`
      // becomes the canonical caller line for that turn_index.
      return {
        ...state,
        partial_caller_line: action.ev.is_final ? null : action.ev.text,
      };
    }
```

**[ADD `partial_caller_line: string | null` to `DispatchState` (line 137) and `INITIAL_STATE` (line 154).]**

**[ADD a render slot** at the bottom of the transcript-list JSX showing `state.partial_caller_line` with class `b3-cad-caller-partial` and text "speaking…" or similar — exact selector depends on existing layout in the un-shown lines 400-700 of DispatchPanel.tsx.]

**[ADD case to DispatchSubscription (line 341)]**:
```typescript
      if (parsed.type === "turn" || parsed.type === "reply" || parsed.type === "caller_partial") {
        onEvent(parsed);
      }
```

**[ADD reducer wire-through inside DispatchPanel main component (around line 770, where it dispatches the externalEvent)]** to also dispatch `{kind:"caller_partial", ev}` for `caller_partial` events.

---

## Net delta summary

| File | Added lines | Modified lines | Deleted lines |
|---|---|---|---|
| `agents/livekit/worker.py` | 27 (5 + 6 + 10 + 6) | 0 | 0 |
| `agents/livekit/orchestrator.py` | 10 | 0 | 0 |
| `agents/livekit/dispatch_publisher.py` | 15 | 0 | 0 |
| `mvp/911-console-live/components/DispatchPanel.tsx` | ~25 | 1 (union extension) | 0 |
| **Total** | **~77** | **1** | **0** |

If the integrator chooses to ship the **minimum viable fix first** (Team A patch only, skipping caller_partial), the totals shrink to:

| File | Added lines | Modified lines | Deleted lines |
|---|---|---|---|
| `agents/livekit/worker.py` | 21 (5 + 6 + 10) | 0 | 0 |
| `agents/livekit/orchestrator.py` | 10 | 0 | 0 |
| **Total minimum** | **31** | **0** | **0** |

The minimum gets the user a populated transcript pane (caller line at STT-final + dispatcher line at TTS-start) without any frontend change. The caller-partial extension is a follow-up if the demo wants the streaming-while-speaking feel.
