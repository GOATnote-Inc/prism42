# cycle-2U / Team U — External research

**Author:** Team U, 2026-04-26
**Fetch-date for every URL below:** 2026-04-26
**Scope:** What does LiveKit ship as the canonical 2026-04 transcript-to-frontend surface, and how does it interact with the team-A `prism42.dispatch` custom-topic plan.

## Headline finding (changes the option set)

LiveKit Agents 1.5.x **already publishes BOTH caller STT and agent TTS text** to a built-in topic `lk.transcription` automatically when STT is enabled. No Python-side wiring required. Clients receive it via `room.registerTextStreamHandler('lk.transcription', handler)` (or `useTextStream` on the React side). This is a **second, independent surface** that we are currently ignoring on the frontend, and it is on by default in 1.5.6 (the version pinned in our worker.py:43).

Implications for the action plan are in `action-plan.md`. Below is the citation set.

---

## Citations

### LiveKit text streams (the new transport)

- **`https://docs.livekit.io/home/client/data/text-streams/`**
  Text streams are the higher-level abstraction LiveKit recommends over raw `publish_data` for string payloads. Senders use `sendText()` / `streamText()` with a topic; receivers register handlers via `registerTextStreamHandler('topic-name', handler)`. The doc explicitly says: *"You must register a handler to receive incoming streams for that topic."* Filtering via `room.on('dataReceived')` is **not** mentioned as a current pattern — handler-registration is the canonical path.
  *Relevance:* Our `prism42.dispatch` publisher uses raw `publish_data` (the older surface) which the @livekit/components-react `useDataChannel` hook still subscribes to correctly (see below). Migrating to text-streams is non-zero work — keep using raw `publish_data` for the cycle-2U fix.

- **`https://docs.livekit.io/agents/multimodality/text/`**
  The transcript surface for AgentSession. Verbatim: transcripts use the `lk.transcription` text-stream topic; metadata includes `lk.transcribed_track_id` and `lk.transcription_final`; **two streams per turn** — `interim_stream` (fires while STT/TTS is still streaming) and `final_stream` (fires once on commit). Default behavior is automatic emission. Disable with `text_output=False` in `RoomOptions` (Python) or `transcriptionEnabled: false` (Node.js).
  *Relevance:* This is the mechanism that delivers the "contemporaneous" feel the user wants — it streams interim STT tokens to the frontend as they arrive, BEFORE the dispatcher even speaks. We get this for free in 1.5.6.

- **`https://docs.livekit.io/agents/voice-agent/transcriptions/`**
  Confirms the reception pattern explicitly:
  ```
  room.registerTextStreamHandler('lk.transcription', async (reader, participantInfo) => {
    const message = await reader.readAll();
    // check participantInfo.identity to distinguish agent from caller
    // check attributes['lk.transcription_final'] to skip interim fragments
  });
  ```
  Sender identity = the speaking participant; agent transcripts have the agent's identity, caller transcripts have the caller's identity.
  *Relevance:* Single SDK call on the React side gets us caller + dispatcher transcript with no Python change.

### LiveKit data-channel React surface (what DispatchPanel currently uses)

- **`https://docs.livekit.io/reference/components/react/hook/usedatachannel/`**
  `useDataChannel<T>(topic: T, onMessage?: (msg: ReceivedDataMessage<T>) => void)` — verbatim from the doc page: *"Passing a topic does not open a new data channel. It is only used to filter out messages with no or a different topic."*
  *Relevance:* Confirms `DispatchPanel.tsx:337` `useDataChannel(DISPATCH_TOPIC, ...)` is correctly filtering on `prism42.dispatch`. The frontend is not the bug.

- **`https://github.com/livekit/components-js/blob/main/packages/react/src/hooks/useDataChannel.ts`**
  Source. Returns `{message, send, isSending}`; the message structure on the callback is `ReceivedDataMessage<T>` with `payload: Uint8Array`, `topic: string`, `from?: Participant`, `kind?: DataPacket_Kind`. `DispatchPanel.tsx:337-348` decodes `msg.payload` correctly.
  *Relevance:* Frontend handler is contract-correct against the current SDK.

### LiveKit agents version + features

- **`https://github.com/livekit/agents/releases`**
  v1.5.6 (2026-04-22) ships STT diarization + speaker_id on TimedString. v1.5.0 (2026-03-19) introduced preemptive generation + adaptive interruption. None of the 1.5.x release notes call out a transcript-surface change — `lk.transcription` predates 1.5.0.
  *Relevance:* The transcription surface has been on by default through the entire 1.5.x line. We do not need to upgrade.

- **`https://livekit.com/blog/sequential-pipeline-architecture-voice-agents`** (cited in CLAUDE.md)
  LiveKit's own April 2026 latency post. Preemptive generation collapses pipeline latency to `max(VAD, STT, LLM, TTS)` rather than sum. Streaming transcript is part of the same architecture: interim STT events fire as the STT plugin emits partials, BEFORE the LLM has decided what to say.
  *Relevance:* The "contemporaneous" feel of the v3 page is partly because ElevenLabs ConvAI streams interim user transcripts to the client as they finalize. LiveKit gives us the same property via `lk.transcription` interim_stream.

### ElevenLabs comparison (why the v3 page "feels contemporaneous")

- **`https://docs.elevenlabs.io/docs/conversational-ai/usage/web-sdk`** (referenced via existing `mvp/911-console-live/components/CallerExperience.tsx:19` import of `useConversation`)
  ElevenLabs ConvAI's `useConversation` hook exposes `onMessage` for transcript events. Fires server-pushed events as STT-final and TTS-streaming arrive.
  *Relevance:* Looking at our actual ElevenLabs page (`/prism42` → `DispatcherShell.tsx`), the transcript ACTUALLY comes from our SSE endpoint `/prism42/api/session/:id/stream` (DispatcherShell.tsx:58, 98), NOT from the ElevenLabs SDK. The "contemporaneous" feel on v3 is because the SSE bus is updated server-side at chat-completions time. Our LiveKit worker does the analogous thing (worker.py:1105, 965 → `_post_turn_to_bus`), but the LiveKit page no longer renders the SSE turns in any transcript view (page.tsx:225-228 explicitly noted).

### Issue tracker — recent transcript-related agents issues

- **`https://github.com/livekit/agents/issues?q=transcript+text-stream`**
  Recent issues (Feb-April 2026) consistently steer integrators toward `registerTextStreamHandler('lk.transcription', ...)` rather than custom data-track topics for transcript display. Custom topics remain the recommended path for **structured, non-transcript** dispatcher state (FSM state, latched facts, latency annotations, intent labels).
  *Relevance:* Validates the hybrid approach in `action-plan.md` Option #2 — `lk.transcription` for the words-on-screen, `prism42.dispatch` for the FSM-derived chrome.

---

## Summary: three usable transports + their fitness for the gap

| Transport | What it carries | Status today | Effort to use |
|---|---|---|---|
| `prism42.dispatch` (custom data-track) | Structured turn + reply JSON with FSM state, latched facts, latency, recent_replies | Publisher written but unwired; subscriber wired | **~26 lines** of additive Python (Team A's existing patch) |
| `lk.transcription` (built-in text-stream) | Caller STT (interim + final) + agent TTS text, per-token streaming | Emitting from the worker by default; **frontend not subscribed** | **~30 lines** of TS in a new `<TranscriptionTap />` component |
| `/prism42/api/session/:id/stream` (SSE) | Server-side `recordTurn()` events: turn, grade, alert, phase_change | Worker calls it (worker.py:965, 1105); LiveKit page consumes for grades/alerts but NOT transcript | Already plumbed; would require putting back the chat-bubble transcript that cycle-2R removed |

The action plan picks the path that gets the user "contemporaneous" without abandoning Team A's work.
