# 12. Parakeet STT on B300 — component deep-dive

Measured: **606 ms mean / 614 ms median / 628 ms p95** (`agents/livekit/bench_b300.py` 10-run, "I have chest pain and shortness of breath"). That number is `transcript_delay` — **VAD end-of-speech → final transcript**. It is **not** partial-transcript TTFT; our plugin never emits partials.

## 1. What our plugin actually does

`agents/livekit/parakeet_stt.py:79-87` declares `STTCapabilities(streaming=False, interim_results=False)`. Only `_recognize_impl` (`:89-128`) is implemented — batch POST to `127.0.0.1:9100/transcribe` with a WAV of the whole utterance. `server.py:69-121` calls `model.transcribe([wav_path], batch_size=1)` — NeMo's offline entrypoint. Docstring (`:24-27`) is explicit: Phase 3a is batch; Phase 3b adds `POST /stream` WebSocket.

livekit-agents wraps us in `StreamAdapter`, which buffers audio until Silero fires `END_OF_SPEECH`, then sends the whole buffer to `_recognize_impl` (LiveKit docs). 606 ms = NeMo encode+decode of a 2-3 s utterance on B300 + HTTP + WAV. Does **not** include the 500 ms default Silero `min_endpointing_delay` — charged separately before STT starts.

## 2. NVIDIA streaming recommendations

`nvidia/parakeet-tdt-0.6b-v3` (our model, Aug 2025) supports chunked streaming via `speech_to_text_streaming_infer_rnnt.py` but emits **finals only, no interims** (HF model card). Open-ASR RTFx 3,332× — decode is not our bottleneck, the batch wrapper is.

The April 7 2026 successor `nvidia/parakeet-unified-en-0.6b` is streaming-first: **Unified-FastConformer-RNNT, 160 ms min latency** at `left=5.6/chunk=0.08/right=0.08` (HF card). Blackwell supported. Nemotron-Speech blog: **cache-aware FastConformer = 24 ms median time-to-final** on H100 vs 90 ms L40, 200+ ms APIs. Cache-aware = each frame encoded once, encoder state reused; buffered streaming (NeMo's default chunked CLI) re-encodes overlapping windows.

## 3. livekit-agents integration: what we're missing

`livekit-plugins-nvidia` ships `parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer` with `streaming=True, interim_results=True` and a `server` param for self-hosted Riva endpoints. The 1.1B variant is **not** our TDT-0.6B-v3.

Preemptive generation is on by default in 1.5.0+ (LiveKit release notes). It fires the LLM on **PREFLIGHT_TRANSCRIPT** events — interims the STT marks stable-enough-not-to-change. Our plugin emits zero PREFLIGHT because `interim_results=False`, so preemptive-gen degrades to turn-boundary and buys nothing. **Every ms we save via stable partials feeds Sonnet-4.6 earlier.** GH #4219: `preemptive_generation=True` has double-billed on some providers — verify with Anthropic.

## 4. B300 sm_103 NeMo pitfalls

Container is `nvcr.io/nvidia/nemo:25.02` (`infra/b300/services/parakeet/Dockerfile:13`). sm_103 needs CUDA 12.9+ (PyTorch issue #159779, NVIDIA Blackwell Compatibility Guide 13.2); NeMo 25.02 predates that. If a rebuild hits `CUDA error: no kernel image`, pin `TORCH_CUDA_ARCH_LIST="8.0 8.6 8.9 9.0 10.0 10.3 12.0 12.1+PTX"` and bump to `nemo:25.05+`.

## 5. Comparison

| STT | Partial-TTFT | Mode | Cost |
|---|---|---|---|
| Deepgram Nova-3 | ~150 ms | cloud streaming | paid |
| AssemblyAI Universal-Streaming | ~300 ms | cloud streaming | paid |
| Parakeet-unified-en-0.6b (B300) | 160 ms claimed | self-hosted cache-aware | $0 |
| **Our Parakeet-tdt-v3 (current)** | **606 ms final, no partials** | **self-hosted batch** | $0 |
| Whisper large-v3 | N/A | batch-only | $0 |

Sources: Deepgram "Measuring Streaming Latency" + Nova-3 announcement; AssemblyAI "300ms rule"; HF parakeet-unified card; our bench.

## Top lever

**Wire streaming + interims. Expected gain: ~400 ms off caller-perceived latency.**

1. Add `POST /stream` to `server.py` via `speech_to_text_streaming_infer_rnnt` with `chunk_secs=0.08, right_context_secs=0.08` (160 ms NeMo floor).
2. Migrate to `parakeet-unified-en-0.6b` — same 600M params, streaming-first, Blackwell-supported.
3. In `parakeet_stt.py`, implement `stream()` returning `RecognizeStream` that emits `SpeechEventType.INTERIM_TRANSCRIPT` per partial + `FINAL_TRANSCRIPT` on endpoint. Flip capabilities to `streaming=True, interim_results=True`.
4. Keep default `preemptive_generation=True`; monitor GH #4219 for double-billing on Anthropic.
5. Re-run `bench_b300.py`; expected `t_stt_ms` 606 → ~200 ms, with LLM TTFT overlapping the speech tail rather than waiting for it.

Evidence: Nemotron-Speech on H100 holds 24 ms median time-to-final under 127 concurrent streams; B300 is strictly faster per-SM for FP8/FP4.
