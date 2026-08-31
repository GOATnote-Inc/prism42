# B300 voice-pipeline optimization roadmap

> Synthesis of the 5-agent component deep-dive (docs 11–15) into a
> single prioritized lever list. Target: close the gap from current
> `/prism42/livekit` (~10 s median end-to-end per KB 09) to
> `/prism42-v4` (ElevenLabs-native, ~1.2 s feel, "amazing" per user).
> All numbers cite the component doc they come from.

## Measured floor vs. target

- Current `/prism42/livekit` p50 reply: **9.0 s** (KB 09, N=10).
- `/prism42-v4` subjective floor: **~1.2 s first audio**.
- Gap: **~7–8 s of fat to trim.**

## Tier 1 — lifts that land in < 1 h + cut > 2.5× latency

### 1. TTS: swap Fish S2-Pro → Cartesia Sonic-3 behind env flag
Biggest single lever. Fish's 9.9 s audio TTFB (KB 09) is the villain;
Cartesia Sonic-3 is published at **~90 ms** TTFB (KB 15). Patch shape
is in KB 15 §"proposed patch": 10-line env-flag in `worker.py:243`,
`TTS_BACKEND=fish|cartesia|deepgram_aura|elevenlabs`, default `fish`
so there's no regression. **Expected drop: 9.9 s → 0.1 s** on the TTS
hop alone. Requires CARTESIA_API_KEY in `.env`.

### 2. STT streaming + preemptive generation
KB 12 + KB 13 both flag this independently. `parakeet_stt.py:80-86`
declares `STTCapabilities(streaming=False, interim_results=False)`;
livekit-agents 1.5.6 gates preemptive generation on
`PREFLIGHT_TRANSCRIPT` events (`voice/audio_recognition.py:777-819`),
which we never emit. Result: LLM waits on VAD-endpoint (500 ms default)
+ final transcript instead of streaming as the user speaks.
Two steps:
- Migrate to `nvidia/parakeet-unified-en-0.6b` (HF, shipped 2026-04-07;
  Blackwell-supported; 160 ms min latency at `chunk=0.08/right=0.08`).
- Implement `stream()` with interims in `parakeet_stt.py`, declare
  `streaming=True, interim_results=True`.
**Expected drop: t_stt_ms 606 → ~250 ms, plus 400-700 ms of LLM/STT
overlap via preemptive gen.**

## Tier 2 — Claude plugin config (< 5 min each)

### 3. Turn on prompt caching
KB 14 §2: `livekit-plugins-anthropic 1.5.6` accepts
`caching: Literal["ephemeral"]`; stamps `cache_control={"type":
"ephemeral"}` on the last system/tool/user/assistant blocks. Anthropic
claims "up to 85% TTFT reduction on hits." One-liner:
```python
AnthropicLLM(model="claude-sonnet-4-6", caching="ephemeral")
```
Edit `~/prism42/agents/livekit/worker.py:242`.

### 4. Confirm the Sonnet-4.6 pin actually holds
KB 14 §1 flags a bench-vs-repo mismatch: `worker.py:242` says
`claude-sonnet-4-6` but the 10-run bench ran on `claude-opus-4-7`
(KB 09:35). Opus 4.7 + adaptive-thinking public TTFT is 10-14 s, which
matches our 8.5 s p50 / 15.4 s p99 too cleanly to ignore. SSH the pod,
read the actually-loaded config:
```bash
ssh b300-pod 'grep -n "claude-" /opt/prism42/agents/livekit/worker.py'
```
If it's Opus 4.7, changing the literal to `claude-sonnet-4-6` is an
immediate 5× LLM-hop improvement.

### 5. Explicit `interruption={"mode":"adaptive"}` + TurnHandlingOptions
KB 13 §3: adaptive interruption is silently disabled for self-hosted
deployments (five gates, we fail at streaming STT — lever 2 fixes this
transitively). Also the 1.5.6 public surface is `TurnHandlingOptions`;
deprecated kwargs forward through `_migrate_turn_handling` in
`turn.py:197-248`. KB 13 §9 has the ideal 911 profile:
```python
session.start(
    agent=orchestrator, room=ctx.room,
    turn_handling=TurnHandlingOptions(
        mode="dynamic", min_delay=0.6, max_delay=4.0,
        min_words=2, preemptive_tts=True,
        max_speech_duration=12.0,
    ),
    interruption={"mode": "adaptive"},
)
```

## Tier 3 — correctness / dead-code (< 10 min each)

### 6. `_on_item` role gating
KB 13 §5: `conversation_item_added` fires for BOTH user and assistant
items. Our `worker.py:313-359` handler doesn't gate on `item.role` and
finalizes timings on the user's chat-item submission too. Add:
```python
if getattr(item, "role", None) != "assistant":
    return
```

### 7. Remove phantom `PipelineEOUMetrics`
KB 13 §2: the class doesn't exist in 1.5.6. The actual union at
`metrics/base.py:184` is `STTMetrics | LLMMetrics | TTSMetrics |
VADMetrics | EOUMetrics | RealtimeModelMetrics | InterruptionMetrics`.
Team β's code at `worker.py:278` references the phantom — dead branch.

### 8. Fish voice drift: inline `references=[...]`
KB 11 §3 + KB 15 already imply this. Seed alone is insufficient
(issue #836). Real fix: inline `references=[{audio: base64, text: "..."}]`
per call, or a stored `reference_id`. Only relevant if Tier 1 lever 1
doesn't ship (we keep Fish).

## Tier 4 — deferred (heroic work, skip unless time + need)

### 9. Partial-DAC-decode patch on Fish
KB 11 §1 — novel patch (upstream rejected in issues #1020, #417, #692;
we'd own it). Math is sound: hop_length=512 at 44.1 kHz = 11.6 ms
per semantic frame; DAC `from_indices()` accepts arbitrary T (:925).
Smallest safe version: monkey-patch `decode_n_tokens` to yield every
40 tokens, rewire `TTSInferenceEngine.inference` to call
`decode_vq_tokens(codes[:, last_t:])`. Expected 9.9 s → ~1.2 s.
Hour-plus effort. Only worth it if we reject the cloud TTS swap.

### 10. Parakeet container bump
KB 12 §5: `nemo:25.02` in `Dockerfile:13` but sm_103 needs CUDA 12.9+
per NVIDIA Blackwell Compatibility Guide 13.2 + PyTorch issue #159779.
Bump to `nemo:25.05+` and pin `TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0
10.0 10.3 12.0 12.1+PTX"` before any rebuild.

## Projected latency after Tier 1 + Tier 2

| Hop | Current (KB 09, N=10) | After Tier 1+2 | Source |
|---|---|---|---|
| STT partial-TTFT | 606 ms final only | ~250 ms partial | KB 12 |
| LLM TTFT | 8.5 s p50 | ~1.3 s p50 | KB 14 |
| TTS TTFB | 9.9 s first-audio | ~100 ms | KB 15 |
| STT/LLM overlap | 0 ms | -400 ms | KB 13 |
| **E2E reply** | **9.0 s p50 / 16 s p99** | **~1.5 s p50** | synthesis |

Matches `/prism42-v4` floor.

## Execution order

Day-of-demo order (if we need the floor in ≤30 min):
1. Lever 4 (check Opus vs Sonnet, 2 min) — if wrong, free 5× win.
2. Lever 3 (`caching="ephemeral"`, 2 min edit + worker restart).
3. Lever 1 (Cartesia swap, 10 min — provision key, patch worker.py,
   `systemctl restart prism42-worker`).
4. Verify via `bench_b300.py --n 5 --sleep-s 15`. Target p50 ≤ 2 s.
5. Lever 2 (streaming Parakeet) is the next multi-hour piece to
   reach the < 1 s floor but ships after the demo.

Everything else (Tier 3/4) is cleanup or hero-work. Don't block the
demo on any of it.
