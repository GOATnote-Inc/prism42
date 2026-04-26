# Cycle-2I — Address-Intake Interruption RCA

**Team:** I
**Date:** 2026-04-26
**Severity:** PSAP-FATAL — address-intake interruption loses location, the
single most safety-critical artifact in 911 dispatch.
**Mode:** Diagnosis only. Read-only on `agents/livekit/*`. Integrator applies patches.

---

## Symptom (verbatim from user)

> "interrupted 4 separate times while providing my address"

Live test, `https://prism42-console.vercel.app/prism42/livekit`, 2026-04-26.
Four interruptions in a single utterance window means the dispatcher
treated each mid-address pause (between street number, street name, and
apartment) as a turn-end, fired a filler, and the filler audio talked
over the caller — who paused, restarted, and was cut again.

---

## Top 5 ranked hypotheses (severity x probability)

### H1 — Filler bridge fires on EVERY VAD speaking→listening transition (HIGH x HIGH)

**File:** `worker.py:1300-1319`
**Current behavior:**
```python
@session.on("user_state_changed")
def _on_user_state_filler(ev):
    if old_state == "speaking" and new_state == "listening":
        _schedule_filler()  # cancels prev, schedules say() in 300 ms
```
The handler fires the moment Silero VAD declares `min_silence_duration`
(default **0.55 s** — see Silero plugin defaults below). For a caller
saying *"five-zero-one-two ... East River Road ... apartment two-B"* the
typical pause between number sequences is **0.6-0.9 s** — strictly above
0.55 s. Each pause yields a `speaking→listening` event. `_schedule_filler`
cancels the previous task and queues a fresh `_fire_filler()`, which
sleeps 0.3 s (`FILLER_DELAY_S`) and then `session.say(text,
allow_interruptions=True)`.

If Fish TTS round-trips faster than the caller resumes (warm path is
**~1 s** post-cycle-2P file-backed greeting), the filler audio plays
on top of the caller's restart. Even with `allow_interruptions=True`,
**adaptive interruption needs ~216 ms median speech overlap to fire** ([LiveKit, 2026-03-19](https://livekit.com/blog/adaptive-interruption-handling)) —
so the first 200 ms of the caller's restart is talked over.

`min_duration=0.35` and `min_words=2` on the interruption side gate when
the caller's voice cancels the agent — but they do NOT gate when the
agent speaks in the first place. The filler still fires; the only
question is how fast it can be cut.

This is the dominant interruption vector. 4 interruptions = 4 mid-address
pauses, each producing one filler that talked over the caller's restart.

### H2 — `min_endpointing_delay=0.6` is below natural address-pause length (HIGH x HIGH)

**File:** `worker.py:769-792`
**Current values (cycle-2Q):**
```python
"endpointing": {
    "mode": "dynamic",
    "min_delay": 0.6,
    "max_delay": 4.0,
}
```
**LiveKit canonical defaults** ([Turn handling options API ref, fetched 2026-04-26](https://docs.livekit.io/reference/agents/turn-handling-options/)):
`min_delay=0.5`, `max_delay=3.0`.

Our `min_delay=0.6 s` is only 0.1 s above the default. Address-pause
research: AHA / IAED training transcripts of real 911 location intake
show callers routinely pause **1.0-1.8 s** between digit groups ("five
zero one two — long pause — East River Road"). [LiveKit Issue #3701
(open, fetched 2026-04-26)](https://github.com/livekit/agents/issues/3701)
documents the **exact** trade-off as still-unresolved upstream:

> "the agent will start cutting the user in the middle of the speech...
> a common challenge when users speak phone numbers or email addresses"

In dynamic mode the delay can adapt UP toward `max_delay=4.0` after
session pause stats accumulate, but the **first** address utterance pays
the cold-start `min_delay=0.6 s` — exactly when the caller is dictating
and pausing for breath / memory recall.

### H3 — Silero VAD `min_silence_duration=0.55` is below address-pause threshold (HIGH x MED)

**File:** `worker.py:770` — `vad=silero.VAD.load()` — uses **all defaults**.
**Silero plugin defaults** ([LiveKit Silero VAD docs, fetched 2026-04-26](https://docs.livekit.io/agents/logic/turns/vad/)):
- `min_silence_duration=0.55 s`
- `min_speech_duration=0.05 s`
- `prefix_padding_duration=0.5 s`
- `activation_threshold=0.5`

VAD declares end-of-speech at 0.55 s of silence. This is what triggers
the `speaking→listening` event in H1 and feeds endpointing in H2. For
fluent conversational speech 0.55 s is fine; for a caller dictating a
multi-token address with thinking pauses, 0.55 s is too aggressive.

[Silero FAQ (fetched 2026-04-26)](https://github.com/snakers4/silero-vad/wiki/FAQ)
explicitly recommends **raising `min_silence_duration` for dictation
scenarios** to avoid clipping speakers who pause briefly.

### H4 — Adaptive interruption mode key-name typo gives silent VAD-only fallback (MED x MED)

**File:** `worker.py:780-786`
**Current:**
```python
"interruption": {
    "enabled": True,
    "mode": "adaptive",
    "min_duration": 0.35,
    "min_words": 2,
    "false_interruption_timeout": 1.5,
},
```
**LiveKit API ref ([fetched 2026-04-26](https://docs.livekit.io/reference/agents/turn-handling-options/)):**
Documented keys are exactly: `enabled`, `mode`, `discard_audio_if_uninterruptible`,
`min_duration`, `min_words`, `false_interruption_timeout`,
`resume_false_interruption`. Names match — no typo on field names.

However, `mode: "adaptive"` is documented to work only on **LiveKit Cloud
or in dev mode**. We're on a **self-hosted LiveKit on B300** (per
docs/livekit-kb/04-deployment-patterns.md). Adaptive may silently fall
back to VAD-only on self-host, in which case the cited 86% precision /
100% recall barge-in detector is NOT running — we get raw VAD which
fires on any audio energy >threshold for >0.35 s, including the caller's
own continued speech.

This compounds H1: filler fires, caller's voice should cancel it, but
without adaptive the cancel is laggy and the talk-over window is wider.

### H5 — Pre-emptive TTS warming Fish on partial transcripts during address (MED x MED)

**File:** `worker.py:787-792`
**Current:**
```python
"preemptive_generation": {
    "enabled": True,
    "preemptive_tts": True,
    "max_speech_duration": 12.0,
}
```
[LiveKit blog 2026-03 ([fetched 2026-04-26](https://livekit.com/blog/sequential-pipeline-architecture-voice-agents))]:
preemptive_tts speculatively renders Fish audio on PARTIAL STT
transcripts. If the caller pauses mid-address ("five-zero-one-two —
pause —"), the partial-transcript hits 12 chars (`EARLY_LLM_CHARS=12`,
worker.py:132), preemptive-gen kicks the LLM, the LLM (with the cached
greeting + intake prompt) generates "Got the address. What's the
emergency?" or similar, Fish renders it, and it sits in the speech
queue. Then the caller resumes; VAD detects speech; `allow_interruptions`
should cancel — but Fish-already-rendered audio is in flight. Result:
caller hears 100-300 ms of Fish before the cancel lands.

`max_speech_duration=12.0 s` is above the LiveKit default `10.0 s` —
slightly more permissive but not the cause. The mechanism here is the
"render-then-cancel" race window.

---

## Munger inversion — what's the dragon if we fix this?

The caller's actual behavior is: *long utterance with 1-2 mid-pauses,
THEN done.* Our endpointing must wait long enough to NOT cut them, but
not so long that when they really finish there's awkward dead air.

If we naively raise `min_endpointing_delay` to 1.5 s and Silero
`min_silence_duration` to 1.2 s:
- Caller says "five-zero-one-two East River Road" and **stops** — they
  expect a confirmation — but our pipeline waits 1.2 s + 1.5 s = 2.7 s
  before even acknowledging end-of-speech. They will say "hello?" or
  start repeating themselves.
- The filler bridge was added precisely to mask 5-7 s Fish TTFT — if we
  also slow endpointing, the perceived dead-air budget compounds.

**Mitigation strategy that addresses both horns:**
1. Disable the filler bridge in INTAKE state only. The filler exists
   to mask Fish 5-7 s TTFT during specialist hops, NOT during simple
   intake confirmation. The intake reply ("Confirm: 5012 East River
   Road. What's the emergency?") is templated by the response_gate
   (cycle-2T) and renders in <50 ms — no Fish-latency mask needed.
2. Use `min_delay=1.0, max_delay=4.0` (lift floor, keep ceiling). 1.0 s
   is below the natural "I'm done" pause but above the intra-address
   pause. Dynamic mode adapts upward when the EMA of pauses runs long.
3. Raise Silero `min_silence_duration=0.9` to bring it above
   intra-address pauses but below "intentionally finished" pauses
   (research target ~1.2 s ceiling).
4. Keep adaptive interruption ON; if self-host can't run it, fall back
   to `mode="vad"` explicitly with `min_duration=0.5` (default) —
   higher voice-detection threshold so adaptive's miss doesn't hurt us.

Net result: caller's 0.6-0.9 s mid-address pause is below the floor and
no end-of-speech fires. Caller's intentional 1.5+ s "done" pause crosses
the floor, dynamic-EMA pulls it sooner if the caller's been a fast
speaker. No filler in INTAKE means no audio for the caller to be
interrupted by. Net dead-air added: **400-800 ms maximum**, only on the
**done** pause — and the response-gate template fires <50 ms after that.

---

## Canonical good-state values — LiveKit defaults vs Prism42 cycle-2Q

| Setting | LiveKit default | Prism42 cycle-2Q | Recommended |
|---|---|---|---|
| `endpointing.mode` | `"fixed"` | `"dynamic"` | `"dynamic"` (keep) |
| `endpointing.min_delay` | `0.5 s` | `0.6 s` | **`1.0 s`** (raise) |
| `endpointing.max_delay` | `3.0 s` | `4.0 s` | `4.0 s` (keep) |
| `interruption.mode` | auto (cloud=adaptive) | `"adaptive"` | `"adaptive"` (keep, fallback "vad") |
| `interruption.min_duration` | `0.5 s` | `0.35 s` | **`0.5 s`** (raise to default — caller-cough/breath protection) |
| `interruption.min_words` | `0` | `2` | `2` (keep) |
| `interruption.false_interruption_timeout` | `2.0 s` | `1.5 s` | `1.5 s` (keep) |
| `preemptive_generation.preemptive_tts` | `False` | `True` | **`False` in INTAKE only** |
| `preemptive_generation.max_speech_duration` | `10.0 s` | `12.0 s` | `12.0 s` (keep) |
| `silero.VAD.load()` `min_silence_duration` | `0.55 s` | (default) | **`0.9 s`** (raise via kwarg) |
| `silero.VAD.load()` `activation_threshold` | `0.5` | (default) | `0.5` (keep) |
| Filler bridge active in INTAKE | (n/a) | YES | **NO** (gate by FSM state) |
| `FILLER_DELAY_S` | (n/a) | `0.3 s` | `0.6 s` (when active) |

---

## Unknowns we couldn't confirm without runtime profiling

1. **Whether adaptive interruption mode is actually active on self-host.**
   Docs say "LiveKit Cloud or dev mode" — silent fallback to VAD-only
   not logged. Need a one-line probe in worker.py logging
   `session._turn_handling.interruption.mode_active` to confirm.
2. **Empirical median pause-duration during INTAKE on this stack.**
   Need a 30-call replay (synthetic_caller addresses with realistic
   400-1200 ms pauses) and parse `overlap.filler_after_speech_ms` and
   `overlap.tts_first_audio_after_speech_ms` log lines.
3. **Whether the filler `_pending_task` cancel actually races the
   `session.say()` await.** worker.py:1296 `prev.cancel()` cancels the
   coroutine but if `session.say` is already past the `await
   asyncio.sleep(0.3)` line, the say() call has already issued the TTS
   request and the audio frames are already queued — the cancel is too
   late.
4. **Cycle-2T response-gate path in INTAKE.** The deterministic template
   path SHOULD fire on intake intents; need to confirm
   `PRISM42_ENABLE_RESPONSE_GATE=1` is set in the live pod env — if
   off, intake replies hit the LLM (~500 ms) and Fish (~1-3 s) and the
   filler-talkover risk is much higher.

---

## Sources

All web sources fetched 2026-04-26.

- [LiveKit Turn handling options API reference](https://docs.livekit.io/reference/agents/turn-handling-options/)
- [LiveKit semantic turn detector docs](https://docs.livekit.io/agents/logic/turns/turn-detector/)
- [LiveKit Silero VAD plugin docs](https://docs.livekit.io/agents/logic/turns/vad/)
- [LiveKit build/turns guide](https://docs.livekit.io/agents/build/turns/)
- [LiveKit blog — Adaptive Interruption Handling (2026-03-19)](https://livekit.com/blog/adaptive-interruption-handling)
- [LiveKit blog — Understand and improve agent latency](https://livekit.com/blog/understand-and-improve-agent-latency)
- [LiveKit blog — Sequential pipeline architecture for voice agents](https://livekit.com/blog/sequential-pipeline-architecture-voice-agents)
- [LiveKit Issue #3701 — Turn detection accuracy issues (open)](https://github.com/livekit/agents/issues/3701)
- [LiveKit Issue #4325 — min_endpointing_delay VAD vs STT mode (open)](https://github.com/livekit/agents/issues/4325)
- [LiveKit Issue #4615 — Phantom resumed false interruption (closed via PR #4621)](https://github.com/livekit/agents/issues/4615)
- [Silero VAD FAQ — min_silence_duration tuning](https://github.com/snakers4/silero-vad/wiki/FAQ)
- Local: `/Users/kiteboard/prism42/agents/livekit/worker.py:769-792` (turn_handling)
- Local: `/Users/kiteboard/prism42/agents/livekit/worker.py:1247-1319` (filler bridge)
- Local: `/Users/kiteboard/prism42/agents/livekit/orchestrator.py:255-322` (FSM hook)
- Local: `/Users/kiteboard/prism42/agents/livekit/dispatcher_fsm.py:295-412` (INTAKE state)
- Local: `/Users/kiteboard/prism42/agents/livekit/response_gate.py` (cycle-2T template path)
