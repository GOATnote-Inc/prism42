# Pipecat speculative-speech pattern — extracted for cycle-2e retrofit

Researched 2026-04-25, read-only. Sources: `github.com/pipecat-ai/nemotron-january-2026` (the reference implementation T4 cited in [`findings/voice/nvidia-tts-patterns.md`](../nvidia-tts-patterns.md) ref #7), the main `github.com/pipecat-ai/pipecat` repo, livekit-agents 1.5.6 source installed at `/Users/kiteboard/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/`, and `agents/livekit/worker.py` + `orchestrator.py` from this tree. Every architectural claim cites a file:line.

This is the pattern only. No code is applied. The companion file [`worker-target-locations.md`](worker-target-locations.md) maps it onto our worker.

---

## 1. Where the pattern lives in Pipecat's repo

**Reference repo:** `github.com/pipecat-ai/nemotron-january-2026` (the Jan-2026 NVIDIA Nemotron Voice Agent reference build by the Pipecat-Daily-NVIDIA collab — same artifact T4 referenced as the 500-700 ms V2V on 4×H100 / ~370 ms TTS first audio).

**Three load-bearing files:**

| File | Role | Status |
|---|---|---|
| `pipecat_bots/sentence_buffer.py` | Sentence-boundary segmenter + token-bounded force-flush | Code retrieved verbatim |
| `pipecat_bots/llama_cpp_buffered_llm.py` | LLM service that drives the buffer + emits to TTS at sentence boundaries | Key methods retrieved |
| `pipecat_bots/bot_interleaved_streaming.py` | Pipeline assembly — wires LlamaCppBufferedLLMService → MagpieWebSocketTTSService | Wiring shape retrieved |
| `docs/streaming-pipeline-architecture.md` | The doc T4's note #7 cited — VAD ~200 ms / STT 30-50 ms / LLM 100-150 ms / TTS ~370 ms / V2V 500-700 ms | Verbatim configuration values retrieved |

Production-grade, not hypothesis: the same repo's per-leg latency table is the published 500-700 ms V2V number on 4×H100, measured at `BotStartedSpeakingFrame`. Tag: **verified-in-Pipecat-production-reference**, retrieved 2026-04-25.

The **mainline `pipecat-ai/pipecat` repo** also ships `text_aggregation_mode={"SENTENCE","TOKEN"}` on `TTSService` (CHANGELOG v0.0.104, 2026-03-02 — fetched via WebSearch 2026-04-25), but the *first-segment-token-cap* layer is implemented above the TTS service in `LlamaCppBufferedLLMService`, not inside the TTS plugin. That layer is the missing piece in our worker.

---

## 2. The pattern's core mechanism

### 2a. Two-stage token cap (the speculative-speech part)

From `pipecat_bots/llama_cpp_buffered_llm.py`, the `InputParams` model and main generation loop (verbatim quote):

```
class InputParams(BaseModel):
    first_segment_max_tokens: int = 24
    first_segment_hard_max_tokens: int = 24
    segment_max_tokens: int = 32
    segment_hard_max_tokens: int = 96
```

The first segment is a **hard cap of 24 tokens** (`first_segment_max_tokens == first_segment_hard_max_tokens`, not a soft target). Subsequent segments use a **soft cap of 32 with a hard ceiling of 96**. The asymmetry is deliberate: ship the first segment as fast as possible to start the TTS clock, then let later segments accumulate enough text for natural prosody.

**Critically:** the 24-token cap is enforced at the LLM-service layer, **not** inside vLLM/llama.cpp. The pattern repeatedly calls the LLM with `max_tokens=24`, accumulates into a buffer, emits at sentence boundary, then re-calls with `max_tokens=32` and so on. This means it is portable across every OpenAI-compatible backend — including our vLLM 0.20 / Nemotron-3-Nano endpoint.

### 2b. Sentence segmentation

From `pipecat_bots/sentence_buffer.py` (the regex is verbatim from line 64 of the file):

```python
pattern = r'[.!?]["\'\)]*\s'
matches = list(re.finditer(pattern, self.text))
```

That is: any of `.`, `!`, `?`, optionally followed by closing quote/paren/bracket, **followed by whitespace**. The trailing-whitespace requirement is explicit anti-false-positive armor for `Dr.`, `3.14`, `Mr.`. The end-of-response (no trailing space) is handled separately by EOS logic in the LLM service.

`extract_complete_sentences()` finds the **last** match and returns everything up to and including it; the incomplete tail stays in the buffer for the next iteration. `extract_at_boundary()` is the force-flush path when the token-cap is hit before any sentence terminator appears, and it falls through a priority ladder:

1. last sentence boundary (the regex above)
2. last clause boundary (`, `, `; `, `\n`)
3. last word boundary (` `)
4. fallback: emit the full buffer as-is

So `first_segment_max_tokens: 24` is **not** a hard truncate at token 24 — it is "stop generating, then find the best break point in what we have so far." If the model produces "Nine one one, what is your location and emergency? Stay calm." in 18 tokens, the buffer flushes immediately on the `?` regex match. If it produces "I understand you are saying that you are experiencing chest pain" with no terminator, the boundary fallback flushes at the last comma/word-boundary.

### 2c. How the first segment hits TTS earlier

The mechanism is plain: `LlamaCppBufferedLLMService` runs a `while not cancelled` loop. Each iteration:

1. Call the LLM with `max_tokens=current_max` (24 first time, 32 after).
2. Append generated tokens to `SentenceBuffer`.
3. `extract_complete_sentences()` — if a sentence boundary was crossed, push the extracted text to the next pipeline stage as an `LLMTextFrame` and `await self._continue_event.wait()` (the TTS signals back when it has begun consuming).
4. Switch `current_max` to subsequent-segment values.

Each `push_frame(LLMTextFrame(text=...))` IS the TTS dispatch. It is a separate frame in Pipecat's pipeline; the downstream TTS service starts synthesizing on that frame without waiting for the rest of the LLM stream to drain. `_continue_event` is a back-pressure signal — the LLM does not generate the next segment until TTS has acknowledged ingestion of the current one (timeout 30s).

This is **not** "separate TTS call per segment" in the LLM-API sense (vLLM is still doing one logical turn over a re-used KV cache, line 98 of `streaming-pipeline-architecture.md`: "100% KV cache reuse across turns" — the LLM service is single-slot). It is "prefix-stream" at the orchestrator-pipeline level: TTS sees segment 1 → starts speaking → LLM is still generating segment 2 → segment 2 arrives → TTS appends. Barge-prevention is handled by livekit's standard interruption pipeline, not by Pipecat-specific machinery.

### 2d. Configurable knobs we'd care about

| Knob | Default | What it controls | Should we tune? |
|---|---|---|---|
| `first_segment_max_tokens` | 24 | Hard cap on initial LLM emit | **Yes** — start at 24. If Nemotron's reasoning-template emits filler, raise to 32 or 48 (see Risk 4 below) |
| `first_segment_hard_max_tokens` | 24 | (= max for first; reserved for asymmetric tuning) | Leave equal to max for first segment |
| `segment_max_tokens` | 32 | Soft cap on subsequent segments | Default OK |
| `segment_hard_max_tokens` | 96 | Hard ceiling that triggers `extract_at_boundary` force-flush | Default OK; raise to 128 if PSAP replies are unusually long |
| Sentence terminators | `r'[.!?]["\'\)]*\s'` | Which characters end a sentence | Add `:` and `—` if dispatcher prompts emit them; otherwise default OK for our 5–12-word reply protocol |

The dispatcher prompt in `orchestrator.py:48-188` enforces 5–12 word replies and explicitly bans compound sentences. **Our average reply will fit in one segment** under the 24-token cap. The pattern still helps because the cap means we kick TTS the instant the first sentence terminator lands instead of waiting for the LLM stream to fully drain.

---

## 3. Compatibility with livekit-agents 1.5.6

We do **not** import Pipecat. Pipecat is a different orchestrator (its own pipeline-of-frames model). We lift the *pattern* — sentence-boundary buffered emission + first-segment token cap — into livekit-agents' existing extension point.

### 3a. The LiveKit LLM→TTS pipe (verified in installed source)

`livekit/agents/voice/agent_activity.py:2407-2417` is the splice point. With line numbers verbatim from the installed file:

```
2407   text_tee = utils.aio.itertools.tee(llm_gen_data.text_ch, 2)
2408   tts_text_input, tr_input = text_tee
...
2415       tts_task, tts_gen_data = perform_tts_inference(
2416           node=self._agent.tts_node,
2417           input=tts_text_input,
```

`llm_gen_data.text_ch` is an `aio.Chan[str | FlushSentinel]` (defined `voice/generation.py:49`) populated at `voice/generation.py:185` (`text_ch.send_nowait(chunk.delta.content)`). This is per-token streaming text, no aggregation. `tee()` duplicates the stream — one copy goes to TTS, one to the transcription pipeline. **`tts_text_input` is therefore the exact place where Pipecat's `_emit_and_wait` would push text to TTS.**

### 3b. The hook livekit-agents already exposes for this

`livekit/agents/voice/agent.py:342-367` defines `Agent.tts_node()` — explicitly:

> "You can override this node to provide different text chunking behavior, a custom TTS engine, or any other specialized processing." (line 357)

The default implementation (`agent.py:460-493`) takes `text: AsyncIterable[str]` and yields `rtc.AudioFrame`. It already supports a fallback `StreamAdapter` for non-streaming TTS that uses a `tokenize.blingfire.SentenceTokenizer(retain_format=True)` (line 476) — so the **sentence-tokenizer machinery is ALREADY in the box**. What's missing is:

1. Using `BufferedSentenceStream` (already exists at `livekit/agents/tokenize/token_stream.py:112-124`) to gate the text passed into `wrapped_tts.stream(...)`.
2. The token-cap on the first emission.

The first item is a 5-line override. The second is genuinely new code (livekit-agents has no first-segment-token-cap concept — it streams whatever the LLM produces).

### 3c. livekit-plugins-openai is not opaque

`livekit/plugins/openai/llm.py` exposes the per-token stream end-to-end. The `text_ch.send_nowait` call at `voice/generation.py:183-185` is fed by `chunk.delta.content` from the OpenAI chunk stream, so we get every `delta.content` token. There is no callback API per token — it's an `AsyncIterable` we already consume. That's adequate; we don't need a callback layer.

The first-segment-cap can be implemented **without re-calling the LLM**: we accumulate from the existing stream, push to TTS at sentence boundary OR when N tokens have arrived, and then keep accumulating from the same stream for the next segment. The Pipecat re-call pattern is necessary in their model because they want vLLM to *stop* generating after 24 tokens to free the slot for the next segment's LLM call. We don't need that — vLLM happily emits the full reply in one continuous stream; we just throttle our emission *to TTS* at sentence boundaries.

**This is the most important compatibility insight in the research.** Pipecat's two-call pattern (24 tokens, then 32) is a single-slot KV-cache optimization. Our pattern is purely about *when we emit to TTS* from a stream we'd be consuming anyway. The retrofit becomes much smaller.

### 3d. preemptive_tts already on, but doesn't do this

`worker.py:446-450` already enables `preemptive_generation.preemptive_tts: True`. `agent_activity.py:2425-2433` shows what that does: it calls `_start_tts_inference()` *earlier* (right after LLM starts streaming, before the speech_handle is scheduled). **It does not segment the LLM output.** The TTS still receives the full token-by-token stream; preemptive_tts only changes *when the TTS request opens a connection*, not *what it sees first*. Pipecat's pattern is orthogonal — it changes the *content shape* of what TTS sees on the first emit.

So the cycle-2e retrofit is additive on top of preemptive_tts, not a replacement.

---

## 4. Risk register

### Risk 1 — Cut-off mid-thought audio (M)

**Symptom:** TTS speaks "Nine one one, what is your" and stops because the model paused for a tool-call decision or an `<eot>` came mid-sentence.

**Mitigation:** the regex requires *terminator + whitespace*. A bare token-cap-flush goes through `extract_at_boundary()` priority ladder, which prefers a sentence boundary first, then a clause comma. If neither exists, it flushes at the last word boundary — never mid-word. For our 5–12-word PSAP replies the worst case is "Stay calm and tell me " (clause boundary) or "Help is on the way " (word boundary). Both are speakable.

### Risk 2 — Nemotron reasoning-content out-of-order (resolved by cycle-1 Fix 1, verify)

**Symptom:** Nemotron-3-Nano with `enable_thinking=True` would emit `delta.reasoning_content` before `delta.content`, and a naive token-counter would count reasoning tokens against the first-segment cap, then ship 24 tokens of reasoning to TTS.

**Mitigation already in place:** `worker.py:355-358` sets `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`. Verified moot. **Action item for the integrator:** the new sentence-buffer code must read `chunk.delta.content` only and ignore `chunk.delta.reasoning_content` if it appears, so this stays moot if `enable_thinking` flips back on. A two-line guard: `if not chunk.delta.content: continue`.

### Risk 3 — Filler interaction (M)

**Symptom:** `worker.py:823-858` already speaks a filler ("Okay, stay with me.") via `session.say()` 300 ms after end-of-speech. If the first segment of the real reply ships within ~300 ms, the filler-vs-reply race may double-speak.

**Mitigation:** no change required from Pipecat's pattern. Livekit's `allow_interruptions=True` on the filler `session.say()` (line 852) means the real reply preempts the filler. The mid-word cut from preemption is the existing behavior, unchanged.

**Bench obligation:** verify in measurement that we still see the filler→reply preemption as smooth audio, not a doubled "Okay" + "Nine one one." The cycle-2e retrofit may make the reply early enough that the filler never reaches audio, which is **net win** — but we should confirm.

### Risk 4 — Filler tokens at the start of Nemotron replies (M-H)

**Symptom:** Nemotron-3-Nano sometimes prefaces with conversational filler ("I understand. Let me help — Nine one one, what is your location?"). The first 24 tokens become the filler, not the question. `first_segment_max_tokens: 24` is a fixed cap, not a smart-truncate — it ships whatever it has.

**Mitigation:**

1. The dispatcher system prompt in `orchestrator.py:48-188` already bans this with explicit "ONE reply per turn. **5–12 words total**" (line 167). We already see compliance in cycle-1 forensic data.
2. The sentence regex requires terminator + space. If the model emits "I understand. Let me help. Nine one one, what is your location?" the buffer would extract "I understand. Let me help. " as the first segment — wrong content, but speakable.
3. **Real defense:** add a content filter inside the override that strips a known set of filler prefixes ("I understand", "Let me", "Okay, ", etc.) before the first sentence-extract. This is ~10 lines and a simple `re.sub` against a tunable list.

Tag this as **HYPOTHESIS pending pilot**: cycle-1's enable_thinking=False fix may already eliminate enough filler that the prompt's 5–12-word constraint holds. If pilot data shows filler prefixes still leaking, add the strip filter.

### Risks 5–7 (compact)

- **R5 — Force-flush before meaningful content (L):** if the buffer holds < 8 chars when the token cap triggers (e.g. "Stay" alone), it would emit a one-word chunk. Mitigation: a `min_first_segment_chars=8` floor in the override, equivalent to livekit's existing `BufferedSentenceStream(min_token_len=...)`. Default-off; enable if pilot shows it.
- **R6 — Over-fragmentation regresses prosody (M):** if Fish/Cartesia re-initializes per chunk, we add inter-chunk gaps. Both plugins are documented streaming, expected to append, not restart — but this is the actual test in §5, not an assumption.
- **R7 — Sonnet 4.6 (cloud Anthropic) sees smaller win (verified-known):** Sonnet TTFT ~500 ms is mostly network; segmenting the first emission only masks the LLM-drain leg. Retrofit is still backend-agnostic — `tts_node` override sees the same `AsyncIterable[str]` regardless of which plugin filled `text_ch`.

---

## 5. Bench plan — distinguishing real-win from chunked-but-same

### Two metrics that already exist

`worker.py` already emits two parseable log lines per turn:

1. `overlap.tts_first_audio_after_speech_ms` — wallclock from caller end-of-speech to first TTS audio frame (line 532-537). This is the **publish→first useful audio** number. **The retrofit must move this number down or be reverted.**
2. `overlap.llm_first_token_after_speech_ms` — wallclock from caller end-of-speech to first LLM token (line 648-654). This is upstream of the retrofit and should be ~unchanged.

### One metric that does NOT exist yet — must be added

**TTFB → first-segment-publish latency**: the wallclock from the LLM's `text_ch.send_nowait(first_chunk)` to the `tts_text_input` consumer receiving the first non-empty buffer flush. This is the "we're holding tokens back" delta. It should be > 0 (we are deliberately buffering until sentence boundary or 24-token cap).

Add a single log line in the override: `overlap.first_segment_published_after_llm_ms` with the buffered-delay value.

### What "the retrofit is just chunking, not winning" looks like

If `overlap.tts_first_audio_after_speech_ms` is unchanged but `overlap.first_segment_published_after_llm_ms` is high, we are buffering on the LLM side AND the TTS isn't shipping audio earlier — net zero. The retrofit is then doing harm and must be reverted.

### What success looks like (predicted ranges)

Cycle-1 baseline (T5 forensic, post-cycle-1): `overlap.tts_first_audio_after_speech_ms` p50 was ~2700 ms (Fish-bound). With the retrofit:

- **Fish backend:** -150 to -300 ms p50. Fish's per-chunk render time is the floor — we cannot go below that. What we win is the LLM-stream-drain time, which the cap caps at ~24 tokens × ~8 ms/token = ~200 ms.
- **Cartesia backend:** -300 to -500 ms p50. Cartesia is much faster per-chunk, so the LLM-drain time is a bigger fraction of total TTFB.
- **Worst case (no win):** if the LLM produces complete sentences within the cap anyway, TTFB is unchanged (we were already shipping a sentence-boundary chunk by accident; the retrofit just made it explicit).

### Sample size and stat gate

- **N ≥ 30 turns per arm**, paired by canonical bench utterance ("I have chest pain.")
- **Comparison:** paired delta on `overlap.tts_first_audio_after_speech_ms`, 95% CI.
- **Ship gate:** mean delta p50 ≤ -100 ms with 95% CI excluding 0. (CLAUDE.md §4 gate.)
- **Revert gate:** any single trial shows mid-word cut audio in subjective listen, OR mean delta is positive (regression).

### Reproducer command sketch

```
PRISM42_FILLER_DELAY_S=999 TTS_BACKEND=fish LLM_BACKEND=vllm-local \
  uv run python bench_b300.py --turns 30 --record overlap.tts_first_audio_after_speech_ms
```

Run with cycle-2e branch off, then on; paired-delta on the two timeseries.

---

## 6. One-line acceptance

**Estimated retrofit:** 60–90 LOC (within the < 100 LOC glasswing target). **Predicted gain on publish→first useful audio:** -150 to -500 ms p50 (Fish lower end; Cartesia upper end). **Risk:** **M** — cut-off-mid-thought (Risk 1) and filler-prefix (Risk 4) are the two failure modes that can produce bad audio; both are detectable in the bench plan above and revertable with one env-var.

---

## 7. Sources

All retrieval dates 2026-04-25 unless noted.

1. `github.com/pipecat-ai/nemotron-january-2026/blob/main/pipecat_bots/sentence_buffer.py` — full source retrieved; sentence regex `r'[.!?]["\'\)]*\s'` and priority ladder verbatim.
2. `github.com/pipecat-ai/nemotron-january-2026/blob/main/pipecat_bots/llama_cpp_buffered_llm.py` — `InputParams` (token caps), main generation loop, `_emit_and_wait` retrieved verbatim.
3. `github.com/pipecat-ai/nemotron-january-2026/blob/main/docs/streaming-pipeline-architecture.md` — quoted token-cap defaults, "100% KV cache reuse" claim, per-leg latency breakdown.
4. `github.com/pipecat-ai/nemotron-january-2026/blob/main/pipecat_bots/bot_interleaved_streaming.py` — pipeline wiring shape `stt → context_aggregator.user() → context_timing → llm → tts → v2v_metrics → transport.output()`.
5. `github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md` — v0.0.104 (2026-03-02): `text_aggregation_mode={"SENTENCE","TOKEN"}` on `TTSService`, replacing deprecated `aggregate_sentences`. Confirms the segmentation pattern is mainline-Pipecat, not just the Nemotron reference.
6. **Installed livekit-agents 1.5.6 source** at `/Users/kiteboard/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/`:
   - `voice/generation.py:49,183-185` — `text_ch: aio.Chan[str | FlushSentinel]`, populated by `text_ch.send_nowait(chunk.delta.content)`.
   - `voice/agent_activity.py:2407-2417` — `text_tee = utils.aio.itertools.tee(llm_gen_data.text_ch, 2)` then `perform_tts_inference(input=tts_text_input)`.
   - `voice/agent.py:342-367` — `Agent.tts_node()` definition and override docstring.
   - `voice/agent.py:460-493` — default `tts_node()` implementation showing the `wrapped_tts.stream` pattern with a `BlingfireSentenceTokenizer` fallback for non-streaming TTS.
   - `tokenize/token_stream.py:112-139` — `BufferedSentenceStream(BufferedTokenStream, SentenceStream)` with `min_token_len`, `min_ctx_len` knobs.
7. **This tree:** `agents/livekit/worker.py:330-369` (LLM backend selector), `worker.py:428-466` (`AgentSession` construction), `worker.py:446-450` (existing `preemptive_tts: True`), `worker.py:823-858` (filler logic). `agents/livekit/orchestrator.py:48-188` (5-12-word PSAP system prompt). `findings/voice/nvidia-tts-patterns.md` (T4's reference work, ref #7 = Pipecat repo above).
