---
title: Fish Speech S2-Pro on B300 (sm_103) — deep-dive
date: 2026-04-24
status: research-only
scope: `/opt/prism42/infra/b300/services/fish-speech/` (127.0.0.1:9200)
measured: TTFB 3.6 ms; first-audio-byte 9.9 s
---

# Fish Speech S2-Pro on B300 — component knowledge

## Summary

- **Lowest-latency achievable on B300 today ~1.0-1.5 s first-audio-byte.** Monkey-patch `decode_n_tokens` ([`fish_speech/models/text2semantic/inference.py:184-238`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/text2semantic/inference.py#L184)) to emit `codes[:, :t]` through `decode_vq_tokens` every ~40 semantic frames (≈465 ms of audio at 44.1 kHz × hop 512). DAC decoder is causal window-limited transformer (`window_size=512`, [`modded_dac.py:50`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/dac/modded_dac.py#L50)); partial slices decode cleanly.
- **Upstream has rejected progressive streaming.** Issue [#1020](https://github.com/fishaudio/fish-speech/issues/1020) closed not-planned; maintainer AnyaCoder in [#692](https://github.com/fishaudio/fish-speech/discussions/692): *"tokens must be generated completely at once because it requires context."* We're on our own for this patch.
- **SGLang-Omni achieves 140 ms TTFA on H200** but has **no B300/sm_103 validation**. Realistic B300 win with SGLang vs our runtime: 2-4×, not 10×.

## Top 3 win levers (latency × risk × effort)

| # | Lever | First-audio | Risk | Effort |
|---|---|---|---|---|
| 1 | **Partial DAC streaming patch** | 9.9 s → ~1.2 s | Medium — click boundaries, RAS window | 1-2 days |
| 2 | **Sentence pre-chunking upstream** | 9.9 s → ~3 s | Low — uses `chunk_length` path | 2 hrs |
| 3 | **Swap to Cartesia Sonic-3** | 9.9 s → 90 ms wire | Low — plugin swap | 1 hr |

### Lever A — partial DAC streaming (biggest lever)

**Why it works.** DAC: `sample_rate=44100`, `encoder_rates=[2,4,8,8]` → `hop_length=512` = **11.6 ms audio/frame** ([`modded_dac_vq.yaml:3`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/configs/modded_dac_vq.yaml#L3); [`modded_dac.py:833`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/dac/modded_dac.py#L833)). `from_indices()` ([`modded_dac.py:925`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/dac/modded_dac.py#L925)) accepts arbitrary `T`; decoder is causal window-limited ([`modded_dac.py:50,351`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/dac/modded_dac.py#L50)) so `codes[:, :t]` decodes cleanly.

**Changes.** (1) In `decode_n_tokens` replace `new_tokens=[]` + final `torch.cat` with `yield` every `STREAM_EVERY=40` tokens. (2) In [`TTSInferenceEngine.inference`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/inference_engine/__init__.py#L86), consume partial yields and call `self.decode_vq_tokens(codes=partial[:, last_t:])`, emit `code="segment"`. (3) Cross-fade 11-23 ms at boundaries.

**Landmines.** RAS `previous_tokens` window ([`inference.py:198`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/text2semantic/inference.py#L198)) must not be perturbed — pass by ref. `@torch.compile(fullgraph=True)` on `decode_one_token` ([`inference.py:385`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/text2semantic/inference.py#L385)) is safe; yield is in outer Python loop. Run DAC decode on a separate `torch.cuda.Stream` to overlap with next-token LLAMA.

### Lever B — sentence pre-chunking (fallback)

`chunk_length=200` ([`schema.py:83`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/utils/schema.py#L83)) groups by speaker turn + UTF-8 bytes, NOT punctuation. For a single-speaker reply everything batches together. Splitting text at `. ! ? 。` upstream and sending one `/v1/tts` call per sentence yields usable audio after ~1 clause (~2-3 s). No Fish code edit.

### Lever C — swap to Cartesia Sonic-3

See table below. Only reason to avoid C: Prism's LiveKit charter favors self-hosted + audit-heavy for PSAP; Sonic adds a network hop + vendor dep.

## Proven-to-fail paths

1. **`@torch.jit.script` on `snake()` (`dac/nn/layers.py:18`)** — nvrtc sm_103 compile fails. Already patched off. Related [#919](https://github.com/fishaudio/fish-speech/issues/919): `cudagraph_mark_step_begin()` fixes sm_12x crash but gives no compile speedup.
2. **`chunk_length < 200`** — [#853](https://github.com/fishaudio/fish-speech/discussions/853): *"below 200 worse results."* Schema bound `conint(ge=100)` exists because Dual-AR slow model loses voice identity below ~100 bytes.
3. **`/partial` endpoint** — referenced in [#1053](https://github.com/fishaudio/fish-speech/issues/1053) but **removed from main**. Only `/v1/tts`, `/v1/vqgan/*`, `/v1/references/*` exist ([`views.py`](https://github.com/fishaudio/fish-speech/blob/main/tools/server/views.py)).
4. **`workers>1`** — each worker instantiates ~22 GB. [#1025](https://github.com/fishaudio/fish-speech/issues/1025) documents 10-20 MiB/call leak → OOM under sustained load. Use in-process `llama_queue` ([`inference_engine/__init__.py:34`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/inference_engine/__init__.py#L34)) with `workers=1`.
5. **Seed-only voice lock** — [#836](https://github.com/fishaudio/fish-speech/issues/836): same text+seed produces different voices across chunks. Seed locks sampling, not identity. Must pass `references=[{audio, text}]` ([`schema.py:60`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/utils/schema.py#L60)) or `reference_id`.
6. **Concurrency via `workers>1`** — [#1092](https://github.com/fishaudio/fish-speech/issues/1092) closed not-planned. Our 3-run `ConnectError` is uvicorn backlog; see Concurrency section.

## Alternative TTS swap table

| TTS | TTFB vendor | TTFB independent | $/1M chars | 5-line swap |
|---|---|---|---|---|
| **Fish S2-Pro (self, today)** | 100 ms (SGLang/H200) | 9.9 s on B300 (ours) | GPU-$ only | — |
| **Cartesia Sonic-3** | 90 ms | 40-90 ms (Mar 2026) | $38-50 | `tts=cartesia.TTS(model="sonic-3", voice="<uuid>")` |
| **Deepgram Aura-2** | 90 ms optimized | 150 ms typical | $27-30 | `tts=deepgram.TTS(model="aura-2")` |
| **ElevenLabs Flash v2.5** | 50-75 ms model | 150-500 ms e2e | $30-180 | `tts=elevenlabs.TTS(model="eleven_flash_v2")` |

```python
from livekit.plugins import cartesia, deepgram, openai
session = AgentSession(
    stt=deepgram.STT(model="nova-3"),
    llm=openai.LLM(model="claude-opus-4-7"),
    tts=cartesia.TTS(model="sonic-3", voice="<uuid>"),
)
```

## Concurrency on B300

Keep `workers=1`; in-process `llama_queue` ([`inference_engine/__init__.py:34`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/inference_engine/__init__.py#L34)) already serializes. Our `ConnectError` at 3 concurrent runs is uvicorn backlog — raise `--backlog 128 --limit-concurrency 32`, gate at livekit-agents with a per-GPU semaphore = 1. CUDA MPS + 2nd instance fits in 288 GB HBM3E but is less win than Lever A. Recycle systemd unit every ~2000 calls to avoid [#1025](https://github.com/fishaudio/fish-speech/issues/1025) leak.

## Evidence trail (non-obvious only)

- DAC frame math: [`modded_dac_vq.yaml:3`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/configs/modded_dac_vq.yaml#L3); [`modded_dac.py:50,351,833,925`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/dac/modded_dac.py#L50)
- Batch-granular yields: [`inference.py:723,733`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/models/text2semantic/inference.py#L723)
- Queue blocks: [`inference_engine/__init__.py:88`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/inference_engine/__init__.py#L88)
- Upstream stream-refusal: [#1020](https://github.com/fishaudio/fish-speech/issues/1020), [#417](https://github.com/fishaudio/fish-speech/issues/417), [#692](https://github.com/fishaudio/fish-speech/discussions/692)
- Voice identity requires references: [#836](https://github.com/fishaudio/fish-speech/issues/836); schema [`schema.py:60-94`](https://github.com/fishaudio/fish-speech/blob/main/fish_speech/utils/schema.py#L60)
- SGLang-Omni H200 140 ms, no B300: [sglang-omni README](https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md)
- torch ≥ 2.11.0.dev20251215+cu130 for sm_103: [pytorch#164342](https://github.com/pytorch/pytorch/issues/164342), [#145949](https://github.com/pytorch/pytorch/issues/145949)
- Cartesia 90 ms, $38-50/M: [docs](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest), [pricing](https://cartesia.ai/pricing)
- Deepgram Aura-2 90 ms, $27-30/M: [launch](https://deepgram.com/learn/introducing-aura-2-enterprise-text-to-speech)
- ElevenLabs Flash 50-75 ms: [docs](https://elevenlabs.io/docs/best-practices/latency-optimization)
- livekit-plugins TTS list: [docs](https://docs.livekit.io/agents/integrations/tts/)
