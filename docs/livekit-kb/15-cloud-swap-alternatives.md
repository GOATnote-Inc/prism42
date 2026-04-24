---
title: Cloud TTS swap alternatives — closing the latency gap to /prism42-v4
date: 2026-04-24
status: decision matrix, not applied
scope: Drop-in replacements for Fish S2-Pro behind a feature flag. STT
       (Parakeet) + LLM (Sonnet 4.6) + orchestrator stay on B300.
---

# 15 — Cloud TTS swap alternatives

## Why TTS, not STT or LLM

`09-b300-voice-bench.md` (N=10) measured Fish TTFB at 4 ms but
`t_fish_total_ms` 6.4-13.8 s. LiveKit forwards as Fish emits, but the
orchestrator buffers the full reply before `ChunkedStream._run` opens
the emitter, so the caller hears nothing for 9-16 s. `/prism42-v4`
(ElevenLabs ConvAI) streams natively and lands ~1-1.5 s. Swapping Fish
for a streaming-native cloud TTS collapses the TTS leg to cloud-native
latency while keeping Parakeet + Sonnet + orchestrator self-hosted.

## Decision matrix

| Candidate              | TTFB              | Voice quality         | Price / 1M chars | Verdict           |
|------------------------|-------------------|-----------------------|------------------|-------------------|
| **Cartesia Sonic-3**   | **~90 ms**        | very high, 40+ langs  | ~$30 (pay-go)    | **swap-in-now**   |
| Deepgram Aura-2        | ~90-200 ms        | high, 40 EN voices    | **$30 / $27**    | **keep-in-reserve** |
| ElevenLabs Flash v2.5  | ~75 ms model      | best-in-class prosody | ~$50-$100        | voice-parity path |
| OpenAI tts-1-hd        | ~500 ms           | ok, 13 voices         | $30              | plain fallback    |
| WebSpeech (browser)    | <10 ms local      | robotic               | $0               | panic-button only |

Weighting: 40% TTFB, 30% quality, 20% integration, 10% price. Cartesia
wins on TTFB + maintained `livekit-plugins-cartesia`. Deepgram is the
reserve — same `inference.TTS` surface, identical price — flip one env
var if Cartesia throttles. ElevenLabs is worse on price for the same
TTFB class; pick only for voice parity with v4.

## Plugin snippets

### Cartesia Sonic-3 (winner)
```bash
uv add "livekit-agents[cartesia]~=1.5"   # .env: CARTESIA_API_KEY=...
```
```python
from livekit.plugins import cartesia
tts = cartesia.TTS(model="sonic-3",
                   voice="f786b574-daa5-4673-aa0c-cbe3e8534c02")
```

### Deepgram Aura-2 (reserve)
```bash
uv add "livekit-agents[deepgram]~=1.5"   # .env: DEEPGRAM_API_KEY=...
```
```python
from livekit.agents import inference
tts = inference.TTS(model="deepgram/aura-2", voice="athena", language="en")
# or: tts = "deepgram/aura-2:athena"
```

### ElevenLabs Flash v2.5 (voice-parity with v4)
```bash
uv add "livekit-agents[elevenlabs]~=1.5"   # .env: ELEVEN_API_KEY=...
```
```python
from livekit.plugins import elevenlabs
tts = elevenlabs.TTS(model="eleven_flash_v2_5",
                     voice_id="ODq5zmih8GrVes37Dizd",  # Sarah (v4 voice)
                     streaming_latency=4)
```

### OpenAI tts-1-hd (fallback)
```bash
uv add "livekit-agents[openai]~=1.5"       # OPENAI_API_KEY already set
```
```python
from livekit.plugins import openai as lk_openai
tts = lk_openai.TTS(model="tts-1-hd", voice="nova")
```

### WebSpeech — client-only, no LiveKit plugin
`window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))` on
the Next.js page, fed by text over the `b3-latency` data channel. No
worker change. Include only as a panic button.

## 10-line patch to `agents/livekit/worker.py`

Replace `tts=FishSpeechTTS(FishSpeechOptions())` (line 243) with a
backend selector. Default stays `fish` — zero regression without the
env var.

```python
# worker.py — at the top of entrypoint(), before AgentSession(...)
_TTS_BACKEND = os.environ.get("TTS_BACKEND", "fish").lower()
if _TTS_BACKEND == "cartesia":
    from livekit.plugins import cartesia
    _tts = cartesia.TTS(model="sonic-3",
        voice=os.environ.get("CARTESIA_VOICE_ID", "f786b574-daa5-4673-aa0c-cbe3e8534c02"))
elif _TTS_BACKEND == "deepgram_aura":
    from livekit.agents import inference
    _tts = inference.TTS(model="deepgram/aura-2",
        voice=os.environ.get("DEEPGRAM_VOICE", "athena"), language="en")
elif _TTS_BACKEND == "elevenlabs":
    from livekit.plugins import elevenlabs
    _tts = elevenlabs.TTS(model="eleven_flash_v2_5",
        voice_id=os.environ.get("ELEVEN_VOICE_ID", "ODq5zmih8GrVes37Dizd"),
        streaming_latency=4)
else:
    _tts = FishSpeechTTS(FishSpeechOptions())
# then in AgentSession(...): tts=_tts
```

A/B in seconds: `TTS_BACKEND=cartesia systemctl restart prism42-worker`.
Each import lives inside its branch, so a missing plugin only breaks
that backend, not Fish.

## Expected latency post-swap (Cartesia)

STT 614 ms + Sonnet 4.6 TTFT ~500 ms + Cartesia TTFB ~90 ms + net ≈
**1.3-1.6 s end-to-end**, matching `/prism42-v4` within noise. Verify
via `bench_b300.py --n 10 --sleep-s 15` after the env flip.

## Sources

- `https://cartesia.ai/sonic`, `https://cartesia.ai/pricing`
- `https://deepgram.com/learn/introducing-aura-2-enterprise-text-to-speech`, `https://deepgram.com/pricing`
- `https://elevenlabs.io/docs/best-practices/latency-optimization`
- `https://platform.openai.com/docs/models/tts-1-hd`
- `https://docs.livekit.io/agents/models/tts/plugins/{cartesia,deepgram,elevenlabs,openai}/`
- `docs/livekit-kb/09-b300-voice-bench.md`
