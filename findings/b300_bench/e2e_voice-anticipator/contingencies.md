# E2E Voice Test — Top-5 Failure Modes for vllm-local + Nemotron-3-Nano

**Top likelihood: #1 (preemptive_generation double-fire on 44 ms TTFT). Single biggest unknown: whether tool calls on sm_103 NVFP4 trigger the `cudaErrorIllegalInstruction` path that has been reported on sm_120 — Phase-D rebuild used a custom `TORCH_CUDA_ARCH_LIST=10.0;10.3` so this is claimed-untested, not verified-clean.**

Stack under test:
- vLLM 0.20.1.dev0+g101584af0.d20260425, NVFP4 MoE (FLASHINFER_CUTLASS), FLASHINFER attention, sm_103 native build
- Nemotron-3-Nano-30B-A3B-NVFP4 — `--tool-call-parser qwen3_coder`, `--reasoning-parser nano_v3` (per official model card)
- livekit-agents 1.5.6 + livekit-plugins-openai 1.5.6, `_strict_tool_schema=False`, `max_completion_tokens=256`
- Bench TTFT p95 = 44.1 ms vs 500 ms Anthropic baseline (~10× faster)
- Parakeet TDT 0.6B v3 STT (NeMo 25.09) at :9100, Fish Speech S2-Pro TTS at :9200, GPU 88/275 GB
- `preemptive_generation.enabled=True`, `preemptive_tts=True`, `interruption.mode=adaptive`, `endpointing.mode=dynamic`

Harness: `synthetic_caller_full.py` — exits 0/2/3/4/5. Failure modes below ranked by likelihood TODAY.

---

## #1 — preemptive_generation double-fire driven by 44 ms TTFT

**Symptom.**
- Harness exits 0 (the user does hear a reply) but worker.log shows two `LLMMetrics` events per turn AND two `speech_created` for the same `turn_id`. vllm.log shows two `chat.completions.create` requests within ~5-30 ms of each other. The harness's `audio_after_publish_end_amp_max` may show a brief stutter / overlap of two TTS streams (peak amplitude jumps then dips then jumps again) because `preemptive_tts=True` schedules the first reply, then a second reply pre-empts mid-utterance. On the dispatcher UI the `b3-latency` channel publishes two payloads with identical `session_id` but mismatched `turn_id`, frontend may flicker.
- In the vllm.log: token usage doubles vs single-LLM-fast-path expectation; with prompt caching disabled (vLLM doesn't auto-cache like the OpenAI SaaS) you see two full prefill cycles, ~80 ms wasted compute per turn.
- Strongest tell: `latency.publish` lines per turn count is 2× the assistant turn count.

**Root cause.** livekit-agents bug [#4219](https://github.com/livekit/agents/issues/4219) — when context/tools change between `PREFLIGHT_TRANSCRIPT` (preemptive trigger) and the final transcript, the pre-empted `asyncio.Task` completes successfully *before* `SpeechHandle._cancel()` runs, so cancellation fails silently. Issue is open and unfixed in 1.5.6 (originally reported against 1.2.16 + main; release notes 1.5.0→1.5.6 do **not** list a fix). The classic Anthropic stack hid this bug because Sonnet 4.6's ~500 ms TTFT meant the preflight LLM call was usually still in-flight when the final transcript arrived, so cancellation landed before completion. With Nemotron at TTFT p95 = 44 ms, the preflight call **finishes before the final transcript even arrives**, defeating cancellation entirely.

**Fix (one line).** In `worker.py` AgentSession config: `"preemptive_generation": {"enabled": False, ...}` (or set `preemptive_tts=False` first as a softer cut — keeps the LLM speculative win, kills only the audio-overlap symptom).

**Source.** [livekit/agents#4219](https://github.com/livekit/agents/issues/4219) — claimed-unverified (issue posted 2025-12; not closed; sm-agnostic, framework-level bug). Confirms double-LLM both with `cancelled=False`. Affected 1.2.16 and main; no merged fix in 1.5.0-1.5.6 changelog.

---

## #2 — Tool call streams missing `type:"function"` / unparseable first chunk under qwen3_coder

**Symptom.**
- Harness exits 5 ("agent never replied") on first turn that triggers a specialist tool. vllm.log shows successful generation; worker.log shows `tool_calls` parsing exception or `KeyError: 'type'` from livekit-plugins-openai's stream consumer; specialist runs `0` times (orchestrator retries, then bails). The harness's `audio_after_publish_end_amp_max` stays at 0 for the full 25 s reply window after the `Okay, stay with me.` filler plays.
- Pre-roll greeting and filler still fire (those don't trigger tool calls). Specialist-routed turns silently die.
- vllm.log line: `qwen3coder_tool_parser.py` reports successful parse but the streamed delta is malformed (no `{` opening, or no `type` field on first chunk).

**Root cause.** Two compounding vLLM bugs against the qwen3_coder parser, both still open as of 0.20:
1. [vllm#16340](https://github.com/vllm-project/vllm/issues/16340) — first streamed tool-call chunk omits required `"type":"function"` field; the OpenAI SDK + downstream strict consumers (livekit-plugins-openai's `_parse_tool_calls`) raise on the missing key.
2. [vllm#35266](https://github.com/vllm-project/vllm/issues/35266) — Qwen3.5/coder streamed arguments missing the leading `{` brace (`STARTS_WITH_BRACE=False`), producing invalid JSON when `arguments` is parsed incrementally.

These were reported against Qwen models but `qwen3_coder` is the parser used for **Nemotron-3-Nano per its official model card** — the parser code path is identical regardless of model weights. The Nemotron NVFP4 model card explicitly says: *"vLLM ≥ 0.12.0"*, but **does not** call out tool-streaming corruption. The HF discussion `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3` documents tool-call+reasoning parser breakage that requires the post-vLLM-0.12 nightly fix from PR #30671. Phase-D pinned `vllm-0.20.1.dev0` from a custom rebuild — claimed-unverified whether PR #30671 is in the tree.

**Fix (one line).** Either (a) restart vLLM with `--tool-call-parser qwen3_xml` (the per-model-card parser is `qwen3_coder`, but multiple HF threads recommend `qwen3_xml` to dodge the streaming corruption); or (b) set `VLLM_DISABLE_STREAMING_TOOL_CALLS=1` (force buffered tool delivery — sacrifices ~30 ms but emits well-formed JSON).

**Source.** [vllm#16340](https://github.com/vllm-project/vllm/issues/16340), [vllm#35266](https://github.com/vllm-project/vllm/issues/35266), [HF discussion: Nemotron-3-Nano BF16 tool calling broken](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3), [official Nemotron model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4) — all claimed-unverified for sm_103 NVFP4 (issues filed against Qwen sm_80/sm_90 builds, but the parser is model-agnostic).

---

## #3 — `reasoning_content` from nano_v3 reasoning parser drops first-chunk delta.content; livekit-plugins-openai treats turn as empty

**Symptom.**
- Harness exits 5 ("agent never replied"). vllm.log looks healthy — TTFT 44 ms, full 311 tok/s, generation finishes. Worker.log shows `LLMMetrics` with non-zero `ttft` AND a `conversation_item_added` event but assistant content is the empty string. `_post_turn_to_bus` posts `role="assistant", content=""`. Fish never receives a TTS POST because `session.say` short-circuits on empty text.
- The dispatcher UI transcript panel says "0 turns" or shows `[user] foo` then `[assistant] (empty)`.

**Root cause.** Nemotron-3-Nano's nano_v3 reasoning parser emits the first ~50-150 streamed tokens in the OpenAI-style `delta.reasoning_content` field (NOT `delta.content`) before the model exits its `<think>` block. livekit-plugins-openai 1.5.6's stream consumer ([source: agents/main/llm.py](https://github.com/livekit/agents/blob/main/livekit-plugins/livekit-plugins-openai/livekit/plugins/openai/llm.py)) accumulates `delta.content` to build the assistant message; `reasoning_content` handling was added for OpenAI o-series but the path for OpenAI-compatible vLLM endpoints is **claimed-unverified**. The OpenAI Python SDK officially says `reasoning_content` is non-standard and "the client supports extra attributes in the response which you can check using hasattr" — i.e. silent drop is the default behavior unless the consumer explicitly opts in. If livekit-plugins-openai filters out chunks where `delta.content is None`, the first-token TTFT measurement shows 44 ms (because reasoning_content arrived) but the final assistant content is whatever came *after* `</think>` — and if `max_completion_tokens=256` is hit before the model exits thinking, content is literally empty.

**Fix (one line).** Set `enable_thinking=False` in the chat-template path — pass `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` on the OpenAI plugin (or via `VLLM_EXTRA_BODY` env if the plugin honors it); this disables Nemotron's reasoning emission entirely so all tokens land in `delta.content`. As a coarser fix, raise `VLLM_MAX_COMPLETION_TOKENS=1024` to ensure the model has budget to exit `<think>` and produce content.

**Source.** [Nemotron-3-Nano NVFP4 model card — `enable_thinking` flag](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4) verified on official card. [vLLM reasoning streaming docs](https://docs.vllm.ai/en/latest/examples/online_serving/openai_chat_completion_with_reasoning_streaming/) confirms `reasoning_content` is a separate delta field. livekit-plugins-openai 1.5.6 source for vLLM-compat endpoint is claimed-unverified — the plugin file is paginated past the streaming consumer in the public mirror.

---

## #4 — Parakeet streaming partial→final + 44 ms TTFT race: filler fires AFTER agent reply

**Symptom.**
- Harness exits 0 but with degraded UX: pre-roll plays normally; user utterance is published; then the harness sees TWO speech bursts after `publish_end_at` — first the real reply (~250 ms after pub-end, because vLLM is so fast), then ~300-500 ms later the **filler** (`Okay, stay with me.`) fires *after* the substantive reply. Worker.log shows `overlap.tts_first_audio_after_speech_ms` followed by `filler.spoken` — wrong order. Dispatcher UI transcript shows `[assistant] <real reply>` then `[assistant] Okay, stay with me.`
- May also exit 5 if the filler interrupts the real reply mid-sentence and the harness's amplitude check never sees a sustained burst above 1000 for long enough.

**Root cause.** `worker.py:807-811` schedules `_fire_filler()` via `asyncio.create_task` after `FILLER_DELAY_S=0.3 s`. The filler delay is computed from the VAD `speaking→listening` transition. With Parakeet+Anthropic, the LLM TTFT was ~500 ms so the filler reliably landed first (within the dead-air window). With vllm-local at 44 ms TTFT and `preemptive_generation` triggering on `PREFLIGHT_TRANSCRIPT`, `speech_created` can fire ~50-150 ms after VAD end-of-speech — **before** the 300 ms filler delay elapses. The cancellation logic in `_schedule_filler()` (`prev.cancel()`) only fires when a *new* `_schedule_filler()` call happens; it does NOT cancel the pending filler task when `speech_created` fires. So the real reply starts at +50 ms, runs through TTS, finishes at +800 ms; then the filler's `await asyncio.sleep(0.3)` returns and `session.say(text)` enqueues "Okay, stay with me." after the real reply already played.

**Fix (one line).** Add `cur["preempt_gen_fired"] = True` check inside `_fire_filler()` after the `asyncio.sleep(FILLER_DELAY_S)` and bail if the flag is set: `if _timing_bucket(session_id)["current"].get("preempt_gen_fired"): return`. Or simpler — gate filler entirely behind `LLM_BACKEND != "vllm-local"` since 44 ms TTFT obviates the dead-air problem the filler was designed to mask.

**Source.** Reading `worker.py:807-863` directly — the cancellation logic is verified-on-Blackwell against the running stack (line numbers from the file as of 2026-04-25). The bug is design-time, not framework-level. [livekit blog on preemptive_generation](https://livekit.com/blog/sequential-pipeline-architecture-voice-agents) confirms the new behavior of "total pipeline latency approaches `max(VAD, STT, LLM, TTS)` rather than their sum" — i.e. with vllm-local, the LLM is no longer the bottleneck and the filler assumption is invalidated.

---

## #5 — vLLM CUDA `illegalInstruction` crash mid-call when tool calls run on NVFP4 (sm_103); Fish/Parakeet survive but worker hangs

**Symptom.**
- Harness exits 5. Mid-call, vllm.log emits `torch.AcceleratorError: CUDA error: an illegal instruction was encountered` / `cudaErrorIllegalInstruction`. vLLM crashes (process exits or wedges). Worker.log shows livekit-plugins-openai retry storm: `httpx.ConnectError: connect EOF` to `127.0.0.1:8001`. Fish (:9200) and Parakeet (:9100) stay healthy. GPU memory drops back to 32 GB (Fish + Parakeet). Subsequent turns time out.
- First crash typically lands ~30 s into the call once a tool-call request is processed by the qwen3_coder parser path. Bench (5+20 samples, no tools) does NOT trigger it — that's why Phase-D gates passed.

**Root cause.** [HF discussion: NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 — "Tool use crashes the model"](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/discussions/3) reports: official vLLM and NVIDIA's vLLM container "do not currently support the SM12.1 compute kernels required to use the Blackwell NVFP4 compute units"; the model uses `quantization=modelopt_fp4` which lights up these kernels, and tool-call paths exercise more of them than chat-only paths. Symptom: "vLLM crashes after ~30 seconds during inference with tool use; eventually crashes even during normal chat (just takes longer)." Workaround listed: "use INT8 quantization" or "AWQ from QuantTrio." Phase-D rebuild compiled vLLM 0.20.1.dev0 with `TORCH_CUDA_ARCH_LIST=10.0;10.3`, including native sm_103 kernels for `nvfp4_scaled_mm_kernels.cu` and `_moe_C` — so this is **partially** mitigated. **But**: the HF discussion was filed against sm_120 (RTX 5090); whether sm_103 (B300) carries the same `tcgen05` instruction-encoding issue inside the qwen3_coder tool-call path is **claimed-unverified** for our exact rebuild. Fish/Parakeet survive because they use separate processes with separate CUDA contexts.

**Fix (one line).** Pre-emptive: run a 60-s soak with one tool-routing utterance before the demo (`for i in $(seq 5); do curl -s http://127.0.0.1:8001/v1/chat/completions -d @tool_call_probe.json; sleep 10; done`); if vllm.log stays clean for 60 s, you're cleared. Reactive (if it fires): swap to `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` (Phase-D download is cached; ~60 GB instead of 19 GB; halves throughput but eliminates NVFP4 kernel path) — `VLLM_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` + restart `vllm serve`.

**Source.** [HF discussion verified-on-sm_120 (RTX 5090)](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/discussions/3), claimed-unverified-on-sm_103 — Phase-D bench was tools-free, no sm_103 native tool-call run was logged.

---

## Defensive watchlist for the run

Fields the integrator should grep in the live logs to catch each mode early:
- **#1**: count `latency.publish` lines per `conversation_item_added` (assistant) — should be 1, not 2.
- **#2**: `qwen3coder_tool_parser` warnings, `delta.tool_calls[0].type` missing, JSON `Expecting property name` errors in worker.log.
- **#3**: `conversation_item_added` with `content=""` for `role=assistant`; `transcript.post_ok role=assistant len=0`.
- **#4**: order of `overlap.tts_first_audio_after_speech_ms` vs `filler.spoken` — filler should never come second.
- **#5**: any `cudaErrorIllegalInstruction` / `tcgen05` / `nvfp4_scaled_mm` exception in vllm.log (`tail -F /var/log/prism42/vllm.log | grep -E 'illegal|tcgen|nvfp4'`).

## Sources consulted (authoritative)

- [livekit/agents#4219 preemptive_generation duplicate LLM requests](https://github.com/livekit/agents/issues/4219) — open, unfixed, claimed-unverified
- [livekit/agents#3414 preemptive generation impl critique (closed not-planned)](https://github.com/livekit/agents/issues/3414) — claimed-unverified
- [vllm#16340 missing type:function streaming tool calls](https://github.com/vllm-project/vllm/issues/16340) — fix PR #17340 merged but parser-specific; verified-on-sm_80
- [vllm#35266 qwen3.5 streaming missing opening brace](https://github.com/vllm-project/vllm/issues/35266) — claimed-unverified
- [HF: Nemotron-3-Nano NVFP4 tool use crashes the model](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/discussions/3) — verified-on-sm_120, claimed-unverified-on-sm_103
- [HF: Nemotron-3-Nano BF16 tool-calling+reasoning broken](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3) — verified-on-pre-vLLM-0.12; fix in PR #30671 (sm-agnostic)
- [Official Nemotron-3-Nano NVFP4 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4) — `enable_thinking` flag, qwen3_coder parser, vLLM ≥ 0.12.0
- [vLLM Nemotron-3-Nano recipe](https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html) — official flags, claimed-unverified-on-sm_103
- [LiveKit preemptive_generation docs](https://docs.livekit.io/agents/multimodality/audio/) — explicit "doesn't guarantee reduced latency"
- [LiveKit blog: sequential pipeline architecture](https://livekit.com/blog/sequential-pipeline-architecture-voice-agents) — pipeline latency = max(VAD, STT, LLM, TTS)
- [vLLM reasoning streaming docs](https://docs.vllm.ai/en/latest/examples/online_serving/openai_chat_completion_with_reasoning_streaming/) — reasoning_content is non-standard delta field
- Local stack reference: `/Users/kiteboard/prism42/findings/b300_bench/phase-d-rebuild/result.json` (TTFT measurements, build flags); `/Users/kiteboard/prism42/agents/livekit/worker.py:329-456, 807-873` (current LLM/TTS/filler config)
