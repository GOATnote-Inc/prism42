# E2E Voice Machine-Attestation — 2026-04-25 11:38Z

## Verdict: FAIL on strict acceptance, DEGRADED in functional terms

The B300 engine path is fully operational under the new vllm-local backend. The E2E voice round-trip works for ~7-8 of 10 turns, but Fish Speech TTS time-to-first-byte (p95 = 2.6 s) plus its bursty chunk-emission pattern (max chunk gap p95 = 2.6 s) push the headline `publish_end_to_first_returned_audio_ms` to p95 = 4510 ms — far above the 1500 ms accepted ceiling. The remaining bottlenecks cannot be addressed within the spec's mainline-safe rails.

## Headline number

**`publish_end_to_first_returned_audio_ms` p95 = 4510 ms** (target 1500 ms accepted; FAIL by 3010 ms).
- p50 = 3000 ms
- min = 500 ms (multiple turns where the harness picked up the pre-roll greeting tail)
- max = 4510 ms

## Per-leg breakdown (10 turns, post-Fix 1)

| Leg | p50 | p95 | max | n |
|---|---|---|---|---|
| `stt_ms` (Parakeet) | 31 | 56 | 56 | 10 |
| `llm_first_token_ms` | 133 | 2246 | 2246 | 10 |
| `llm_total_ms` | 797 | 803 | 803 | 10 |
| `tts_ttfb_ms` (Fish) | 1488 | 2627 | 2627 | 7 |
| `tts_first_audio_after_speech_ms` | 3461 | 4744 | 4744 | 7 |
| `reply_chunk_count` | 2 | 3 | 6 | 7 |
| `reply_max_chunk_gap_ms` | 1484 | 2623 | 6255 | 7 |

## Engine-path attestation (PASS)

- 42 successful `POST /v1/chat/completions` to vLLM in the 19-minute test window (200 OK each)
- 0 Anthropic API calls in worker.log during the test window
- All 10+ post-Fix-1 sessions logged `llm.backend backend=vllm-local model=nemotron-nano`
- vLLM model name confirmed via `curl http://127.0.0.1:8001/v1/models`

## What broke and what was fixed

### Fix 1 — VLLM_MODEL mismatch
vLLM was started with `--served-model-name nemotron-nano` but worker.py default `VLLM_MODEL` was the full HF path `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`. Every request returned 404. Resolved via systemd drop-in `10-vllm-model.conf`.

### Fix 2 — Reasoning-content token-budget exhaustion (Anticipator #3)
3 of 10 turns had `llm_first_token_ms` logged but no `LLMMetrics` and no `transcript.post_ok role=assistant`. Nemotron-3-Nano emits early tokens to `delta.reasoning_content`; with `VLLM_MAX_COMPLETION_TOKENS=256`, model exhausted budget inside `<think>` -> empty assistant content. Resolved via systemd drop-in `20-vllm-max-tokens.conf` setting 1024.

### Fix 3 — BLOCKED by mainline rail
Intended `chunk_length=100` env-config tweak in `fish_speech_tts.py` was correctly refused per the rail.

## Bottleneck (with proof)

Fish Speech S2-Pro TTFT (1.1-2.6 s) and bursty chunk emission. RTF=2.07 means Fish takes 2x audio duration to synthesize.

```
2026-04-25 11:42:39 fishspeech.done audio_duration_ms=2368 chunk_count=6 max_chunk_gap_ms=4641 rtf=2.07 total_ms=4911
2026-04-25 11:42:45 fishspeech.done audio_duration_ms=697  chunk_count=2 max_chunk_gap_ms=1484 rtf=2.43 total_ms=1691
```

## Rollback status

- Fix 1 + Fix 2 drop-ins present, in effect, fix real bugs (do NOT recommend rolling back)
- Phase E env vars unchanged. vllm serve not restarted.
- All 4 services healthy at end of test.

## Proposed next commands for human

1. **Switch TTS to Cartesia Sonic-3** — `LIVEKIT_TTS_BACKEND=cartesia` env. Streaming TTFT ~150-250 ms would close the gap.
2. **Lower Fish `chunk_length` to 100** — 1-line edit to fish_speech_tts.py (spec rail must be lifted).
3. **Add `enable_thinking=False`** via extra_body to the OpenAILLM constructor — fully eliminates reasoning_content swallow.
4. **Patch synthetic_caller_full.py verdict ordering** so reply detection wins over pre-roll detection.
5. **Place a real call via the LiveKit dispatcher console** for human attestation.

---

B300 engine PASS + E2E machine voice DEGRADED (Fish Speech latency dominant) + remaining human attestation needed + ship-quality fix pending Cartesia Sonic-3 cutover.
