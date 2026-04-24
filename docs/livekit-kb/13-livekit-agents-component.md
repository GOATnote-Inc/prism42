# 13 — LiveKit Agents 1.5.6 deep-dive

Scope: `livekit-agents==1.5.6` at
`/opt/prism42/agents/livekit/.venv/.../livekit/agents/`.
Inspection copy: `/tmp/lkdeepdive/.venv/.../livekit/agents/`. Worker:
`/Users/kiteboard/prism42/agents/livekit/worker.py`. Net-new vs 02/03/04/05/08.

## 1. Top lever

**Make Parakeet STT streaming with `PREFLIGHT_TRANSCRIPT` events.** Preemptive
gen in 1.5.6 only fires on partial-transcript events
(`voice/audio_recognition.py:777-819` → `on_preemptive_generation` on
`SpeechEventType.PREFLIGHT_TRANSCRIPT`). Our plugin declares
`STTCapabilities(streaming=False, interim_results=False)`
(`parakeet_stt.py:80-86`) and only emits `FINAL_TRANSCRIPT` (line 119, 126). Net:
LLM never starts until STT ships the full utterance — lose ~400-700 ms of
overlap. Nothing else here moves P50 as much.

## 2. Preemptive generation

Config (`voice/turn.py:115-142`). Defaults: `enabled=True, preemptive_tts=False,
max_speech_duration=10.0, max_retries=3`.

Trigger (`voice/audio_recognition.py`):
- `PREFLIGHT_TRANSCRIPT` → hook fires at line 813 with a running-mean
  confidence. No hard threshold — STT plugin owns its stability bar.
- `FINAL_TRANSCRIPT` + `transcript_changed` also fires (line 758-771) so a
  final can diverge from the preflight-triggered gen.

`agent_activity.py:1798-1845` cancels any in-flight preemptive handle and calls
`_generate_reply(schedule_speech=False)`; the LLM streams into a buffered
`SpeechHandle` that is scheduled (turn confirmed) or cancelled (over
`max_speech_duration`). `preemptive_tts=True` spends speculative TTS tokens for
a latency win. On local B300 Fish the marginal cost is ~0 → set `True`.

## 3. VAD / endpointing / interruption

Defaults (`voice/turn.py:65-112`): `endpointing.mode="fixed", min_delay=0.5,
max_delay=3.0`; `interruption.enabled=True, min_duration=0.5,
false_interruption_timeout=2.0`.

**Adaptive interruption is NOT running on us.** `agent_activity.py:3486-3534`
needs: (1) STT streaming + `aligned_transcript`, (2) VAD, (3) turn_detection
not manual/realtime_llm, (4) not RealtimeModel, (5)
`LIVEKIT_INFERENCE_API_KEY` OR `utils.is_hosted()`/`is_dev_mode()`. We fail
(1) and likely (5). Line 3524: **self-hosted prod silently falls back to
VAD-only** unless `interruption={"mode":"adaptive"}` is set explicitly.

911 profile (hesitating callers, real barge-ins):
```python
turn_handling = {
  "endpointing":  {"mode": "dynamic", "min_delay": 0.6, "max_delay": 4.0},
  "interruption": {"enabled": True, "min_duration": 0.35,
                    "min_words": 2, "false_interruption_timeout": 1.5},
  "preemptive_generation": {"enabled": True, "preemptive_tts": True,
                             "max_speech_duration": 12.0},
}
```
`DynamicEndpointing` rides caller pace via EMA
(`voice/endpointing.py:49-120`). `min_words=2` blocks cough-cancels. Flip
interruption to adaptive once `LIVEKIT_INFERENCE_API_KEY` is wired.

## 4. `metrics_collected` (team β audit)

`events.py:151-156` + `metrics/base.py:20-192`. Union is `STTMetrics |
LLMMetrics | TTSMetrics | VADMetrics | EOUMetrics | RealtimeModelMetrics |
InterruptionMetrics`. **No `PipelineEOUMetrics` exists** — `worker.py:278`
has it in the branch; dead code, delete.

Field map (s → ms):
- `LLMMetrics.ttft` → `llm_ms` (first-token).
- `TTSMetrics.ttfb` → `tts_ms`.
- `STTMetrics.duration` is valid only when `streamed=False` (our case). When
  Parakeet goes streaming, `duration=0.0` — switch to
  `EOUMetrics.transcription_delay` (`metrics/base.py:102-105`).
- `EOUMetrics.end_of_utterance_delay` explains `total_ms > stt+llm+tts` —
  the VAD-EOS → turn-commit gap.

`worker.py:286-297` is correct for current non-streaming Parakeet.

## 5. The `INTERRUPTION_TIMEOUT=30` monkey-patch

`speech_handle.py:14` — module-level `float`, consumed only inside
`_cancel()` (lines 218-229), fired when `SpeechHandle.interrupt()` or
preemptive cancel runs (`agent_activity.py:1217, 1241, 1809, 2044`). The
5 s default says "if the speech tail still plays 5 s after we chose to
cancel, force-cancel tasks." Old orchestrator exceeded 5 s → reply lost.

There is **no public `TurnHandlingOptions` key** for this in 1.5.6. Field is
a module-level `float`, not in any `TypedDict`. `false_interruption_timeout`
is different (false-barge classification). **Keep the monkey-patch.** Add a
TODO to re-check on 1.6. Harmless on the current Sonnet fast path.

## 6. b3-latency data channel

`rtc/participant.py:200-244` — one FFI call per message. SCTP caps
~64 KB/message; our JSON payloads <300 B. `reliable=True` is right for a
5-10 Hz UI feed. Stay on JSON; protobuf saves ~40% bytes, not worth it below
1 KB/frame.

**Bug**: `conversation_item_added` fires for BOTH user and assistant items
(`agent_activity.py:2305`; `audio_recognition.py`). Our `_on_item`
(`worker.py:313-359`) doesn't gate on role and finalizes timings on the user's
chat item too. Add `if getattr(item, "role", None) != "assistant": return`.

## 7. Delegation

1.5.6 supports intra-session handoff via `AgentHandoff` (`events.py:172`,
`agent.py:921`). **No first-reply latency advantage** on single-LLM path —
useful later for dispatcher/triage split. Managed-Agents `callable_agents`
is orthogonal (CLAUDE.md §8: silently stripped on our workspace).

## 8. Anti-patterns to remove

1. `worker.py:278` — drop `"PipelineEOUMetrics"`.
2. `worker.py:313` — gate `_on_item` on assistant role.
3. `parakeet_stt.py:80-86` — flip to streaming + preflight (§1).
4. Do NOT replace `INTERRUPTION_TIMEOUT=30.0` — no 1.5.6 equivalent.

## 9. Ideal `AgentSession` for 911 dispatcher

```python
session = AgentSession(
    vad=silero.VAD.load(min_speech_duration=0.15,
                        min_silence_duration=0.4),
    stt=ParakeetSTT(ParakeetOptions(streaming=True)),   # anti-pattern #3
    llm=AnthropicLLM(model="claude-sonnet-4-6"),
    tts=FishSpeechTTS(FishSpeechOptions()),
    turn_handling={
        "endpointing":  {"mode": "dynamic",
                           "min_delay": 0.6, "max_delay": 4.0},
        "interruption": {"enabled": True, "min_duration": 0.35,
                           "min_words": 2,
                           "false_interruption_timeout": 1.5},
        "preemptive_generation": {"enabled": True,
                                    "preemptive_tts": True,
                                    "max_speech_duration": 12.0},
    },
    aec_warmup_duration=3.0,
    user_away_timeout=None,     # never auto-away a 911 caller
    max_tool_steps=3,
)
await session.start(agent=orchestrator, room=ctx.room)
```

Ship behind a flag; measure P50 via b3-latency over ~20 synthetic calls
before promoting.
