# cycle-2U / Team U — Transcript pane diagnosis

**Author:** Team U, 2026-04-26
**Scope:** Read-only diagnosis of the empty `<DispatchPanel />` transcript on `https://prism42-console.vercel.app/prism42/livekit`. No source modified.

## TL;DR

The frontend listener is wired correctly. The Python publisher exists on disk but is not imported. The page swapped its old SSE-driven chat-bubble transcript out for `<DispatchPanel />`, which renders ONLY data-track events on topic `prism42.dispatch`. No code path emits those events today, so the panel sits at "Waiting for the first caller utterance." even when the voice loop is fully alive (audio + SSE + b3-latency all flow normally).

This is the 10% gap Team A + Team F left for the integrator.

## What is wired

**Frontend — fully wired, no events to render:**

- `mvp/911-console-live/components/DispatchPanel.tsx:25` — `export const DISPATCH_TOPIC = "prism42.dispatch"` (matches publisher).
- `mvp/911-console-live/components/DispatchPanel.tsx:332-349` — `<DispatchSubscription onEvent={...} />` calls `useDataChannel(DISPATCH_TOPIC, ...)`, decodes the `payload` bytes, parses JSON, and forwards `type: "turn" | "reply"` events. Topic-filter is correct per @livekit/components-react docs (verified 2026-04-26: `useDataChannel(topic, onMessage)` filters out non-matching topics automatically).
- `mvp/911-console-live/components/LiveCallRoom.tsx:30,164` — `<DispatchSubscription onEvent={onDispatchEvent} />` is mounted inside `<LiveKitRoom>` (line 144-166 wraps it correctly so `useRoomContext` finds the room).
- `mvp/911-console-live/app/prism42/livekit/page.tsx:114` — `const [dispatchEvent, setDispatchEvent] = useState<DispatchEvent | null>(null)`.
- `mvp/911-console-live/app/prism42/livekit/page.tsx:618` — `<VoiceHost ... onDispatchEvent={setDispatchEvent} />`.
- `mvp/911-console-live/app/prism42/livekit/page.tsx:375` — `<DispatchPanel externalEvent={dispatchEvent} />`.

The frontend will render any well-formed event the moment one arrives.

**Publisher module — written, NOT imported:**

- `agents/livekit/dispatch_publisher.py:1-241` — full implementation. `DispatchPublisher.publish_turn(...)` and `.publish_reply(...)` enqueue JSON onto an asyncio queue; a worker task drains via `local_participant.publish_data(payload, reliable=True, topic=TOPIC)` (the 1.5.6 surface). Default OFF behind `PRISM42_ENABLE_DISPATCH_PUBLISHER=1` (`is_enabled()` at line 48-50). Drop-oldest queue (line 200-208), fail-soft worker (line 234-240). API matches Team A's data-track-spec.md schemas exactly.
- `grep -n "dispatch_publisher\|DispatchPublisher\|prism42.dispatch" agents/livekit/worker.py agents/livekit/orchestrator.py` returns **nothing**. The file exists, it is committed, no other Python file references it.

**Spec — written, integration not applied:**

- `findings/voice/cycle2R_livekit_selfhost/team-a/data-track-spec.md:148-258` — explicit 16-LoC + 10-LoC additive integration patches. Section "Hook 1 — turn" wires `orchestrator.py:288 on_user_turn_completed` → `_dp.publish_turn(...)`. Section "Hook 2 — reply" wires `worker.py:898 _on_item` → `_dp.publish_reply(...)`. The publisher is constructed in `worker.py:813` right after `make_orchestrator` and attached as `orchestrator._dispatch_publisher` (read-only attribute add, no API change to `make_orchestrator`).

## What is NOT wired (the gap)

No path in the running worker imports `dispatch_publisher` or constructs a `DispatchPublisher` instance, so:

1. `orchestrator.on_user_turn_completed` (`agents/livekit/orchestrator.py:288-322`) advances the FSM and updates instructions — no `publish_turn` call. The `local_log.info("orchestrator.fsm_turn_ms", ...)` at line 306 is the last side-effect before the LLM call returns.
2. `worker.py _on_item` (`agents/livekit/worker.py:898-968`) records dispatcher reply into FSM (line 915), writes turn-log (line 955), grades + posts to SSE bus (lines 957-966) — but never emits a `reply` data-track event.

The b3-latency channel (`worker.py:1419, 1478`) is the proof that the publish_data pattern works on this codebase — same surface, different topic. The SSE bus (`worker.py:_post_turn_to_bus` at lines 461-497, called at lines 1105 and 965) is the proof that the worker already harvests both caller-final and assistant-final text. Re-using those exact text values for the data-track event is a strict subset of what's already happening.

## Why the user calls v3 "contemporaneous"

The ElevenLabs page (`/prism42`) and the LiveKit page (`/prism42/livekit`) **both** consume the same SSE endpoint `/prism42/api/session/:id/stream`. On the ElevenLabs path, the chat-completions API route (`mvp/911-console-live/app/prism42/api/chat/completions/route.ts`) calls `recordTurn()` server-side, which fans the event out to all SSE subscribers. The user sees turns the moment the server commits them.

On the LiveKit page, the DispatcherShell's old SSE-driven chat-bubble transcript was **replaced** by `<DispatchPanel />` in cycle-2R (page.tsx:368-375 explicitly notes this). DispatchPanel's reducer hydrates ONLY from `prism42.dispatch` data-track events (DispatchPanel.tsx:139-228). The SSE turns are still being delivered (the worker calls `_post_turn_to_bus` at worker.py:965 + 1105 — verified live by the `setTurns` state still updating from the SSE reader on page.tsx:209), but the LiveKit page no longer renders them in any transcript surface — `setTurns` only feeds tabs V2/V3/V4 and the rubric/grade panels (page.tsx:225-228 comment is explicit).

So: ElevenLabs feels contemporaneous because its UI still consumes SSE; LiveKit feels broken because its UI moved to data-track BEFORE the data-track publisher landed.

## Conclusion

This is a wiring gap, not a design flaw. Team A's publisher schema matches Team F's reducer one-to-one (DispatchPanel.tsx:84-108 — `DispatchTurnEvent` and `DispatchReplyEvent` shapes are identical to dispatch_publisher.py:144-176 emissions). Applying Team A's integration patch verbatim closes the loop with ~26 added lines and zero modified lines, default-OFF.
