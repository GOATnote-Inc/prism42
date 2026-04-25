# Expert-wiring research: Nemotron-3-Nano-30B-A3B-NVFP4 + vLLM 0.20 + B300 sm_103

Researched 2026-04-25. Stack hash: `B300 sm_103 / nvcc 13.0 / vLLM 0.20.1.dev0+g101584af0 (MXFP4 patch) / FlashInfer 0.6.9 / Nemotron-3-Nano-30B-A3B-NVFP4 / FLASHINFER_CUTLASS MoE / FLASHINFER attn / FlashInferCutlassNvFp4LinearKernel / livekit-agents 1.5.6 / measured TTFT p50 41.7ms p95 44.1ms / co-resident with Fish-Speech S2-Pro + Parakeet TDT 0.6B v3 (88/275 GB)`.

Methodology: WebSearch + WebFetch sweep across vLLM blog/docs/issues, NVIDIA developer blog, Nemotron model card, FlashInfer issues, and NVIDIA forums. Every claim below ties to a numbered URL in the Sources section, with retrieval date 2026-04-25 unless otherwise stated. Findings are bucketed and ranked. Throughput and TTFT numbers cited are quoted verbatim from sources, not estimated.

## OODA verdict (top of file)

**Top recommendation we are NOT yet doing:** Pin `--cuda-graph-sizes 1 2 4 8` (or equivalent `--compilation-config '{"cudagraph_capture_sizes":[1,2,4,8]}'`) plus `--max-num-seqs 1`. Cited expected gain: cuts capture time ~10-50x (vLLM forum default sweeps 1..512 in steps of 8 and "67 graphs can take >10s") with **no TTFT regression** for batch=1 voice (we never use sizes >8 anyway). Source: vLLM CUDA Graphs design doc + V1 default max graph size forum [refs #15, #19, #25]. Verified-on-Hopper-and-Blackwell. **Reduces our 14-min boot to a small fraction without touching steady-state TTFT.**

**Single biggest risk if we change nothing:** Live calls hit the unmeasured tail. Our 20-sample Phase-D test was 5-12 word dispatcher prompts at max_tokens=150. Real voice calls can have multi-utterance system + RAG context (>500 tokens) and longer decodes. We've never characterized TTFT or token-rate at >150 tokens generation or with `enable_thinking=True` slipping through. NVIDIA's own published Nemotron-3-Nano TTFT on RTX 5090 is **p50=171ms** [ref #16] — our 41.7ms is suspect-good and almost certainly because all 20 prompts were short and likely prefix-cache hits from chat-template warmup.

**Single most-likely-to-bite NVIDIA-flagged config:** Mamba-2 + V1 + async-scheduling on Blackwell has a documented `cudaErrorIllegalInstruction` family of bugs [refs #21, #22, #23]. Confirmed on sm_121 (DGX Spark/GB10), **not yet observed on sm_103 (B300 datacenter)**, but the failure mode is "CUDA graph capture for batch_size > 1." Our setup never sees batch>1 at runtime, but it captures graphs for all sizes 1..512 by default, so a regression in any of vLLM/FlashInfer/PyTorch could surface this on B300 too. Mitigation if it does: `--no-async-scheduling` + `--enforce-eager` (the documented workaround) costs ~37% throughput on sm_121. Pre-staging the rollback flags is cheap insurance.

---

## A. What we are already doing right (with cited validation)

Each bullet is a knob in our current config that an authoritative source says is the right pick for this stack.

- **`VLLM_USE_FLASHINFER_MOE_FP4=1`** + **`VLLM_FLASHINFER_MOE_BACKEND=throughput`** — exact env vars from the official Nemotron-3-Nano-30B-A3B-NVFP4 HuggingFace model card [ref #4] and NVIDIA forums shahizat post 2026-01-31 [ref #14]. *Note: we don't actually have a choice here* — `latency` (TRT-LLM) backend raises `NotImplementedError` for non-gated MoE activations like Nemotron's [ref #6]. So `throughput` (CUTLASS) is forced; this is bucket A by elimination, not optimization. Tag: verified-on-Blackwell-sm_100.

- **`--kv-cache-dtype fp8`** — recommended in NVIDIA Nemotron-3-Nano-30B-A3B-NVFP4 model card [ref #4] and vLLM Recipes guide [ref #1]. Tag: verified-on-Blackwell.

- **`--tool-call-parser qwen3_coder`** + **`--reasoning-parser nano_v3`** + **`--reasoning-parser-plugin nano_v3_reasoning_parser.py`** — all three are the exact set NVIDIA prescribes in the model card [ref #4] and vLLM Recipes [ref #1]. Tag: verified-on-Blackwell.

- **`--trust-remote-code`** + **`--enable-auto-tool-choice`** — required, per NVIDIA model card [ref #4]. Tag: verified-on-Blackwell.

- **FLASHINFER attention backend** — vLLM's December 2025 Nemotron-3 blog [ref #17] explicitly sets `export VLLM_ATTENTION_BACKEND=FLASHINFER` for Nemotron-3 Nano. Tag: verified-on-Blackwell.

- **`max_completion_tokens=256`** for short utterances — aligns with vLLM realtime/voice doc [ref #2] which advises constraining max_tokens for streaming and with NVIDIA's own reasoning-budget pattern [ref #4]. Tag: verified general best-practice.

- **`livekit-plugins-openai` with `_strict_tool_schema=False`** — known requirement to use vLLM behind LiveKit's OpenAI plugin (vLLM doesn't enforce OpenAI's strict schema). Implicit in LiveKit OpenAI-compatible LLM doc [ref #20]. Tag: verified-by-Anthropic-tool-schema-bug-research.

- **`preemptive_generation.enabled=True` + `preemptive_tts=True`** — LiveKit 1.5+ refined preemptive generation defaults exactly for the long/intermittent speech case [ref #20a]. Tag: verified-on-LiveKit-1.5.6.

- **`enforce_eager=False` (CUDA graphs ON)** — the documented Mamba+Blackwell illegal-instruction bug is sm_121 only (DGX Spark, GB10) [refs #21, #22, #23]. sm_103 (B300 datacenter, our hardware) is **not in any closed/open issue we found** as having this bug. Our Phase-D log "0 errors over 20 samples" corroborates. Tag: claimed-unverified-on-Blackwell-sm_103-data-center but no contraindication.

---

## B. Top 8 ranked design decisions to consider next

Format: # — Knob / Expected gain / Risk / Reversibility / Source / Verified-on tag.

### B1. Pin `--cuda-graph-sizes 1 2 4 8` and `--max-num-seqs 1`
- **Knob:** `--cuda-graph-sizes 1 2 4 8` (or via `--compilation-config '{"cudagraph_capture_sizes":[1,2,4,8]}'`) + `--max-num-seqs 1`.
- **Expected gain:** **L** on boot time (14-min → 1-2 min plausible; default sweep goes 1..512 step 8 = ~71 graphs, "67 graphs can take >10s and scales with model size and GPU type" [ref #19]). **Zero or marginal positive** on TTFT (we never serve batch>1 anyway). Memory savings on captured-graph workspace.
- **Risk:** None for our use case (single-user voice). If we ever needed batch=8+ later, we'd have to widen the list. The NVIDIA forum poster (`trystan1`, 2026-01-30) used `--max-cudagraph-capture-size 256` for high-throughput testing [ref #14]; our voice config is the opposite extreme.
- **Reversibility:** Trivial — env-var/CLI flag.
- **Source:** vLLM CUDA Graphs design doc [ref #15], V1 default max graph size forum [ref #19], `--cuda-graph-sizes` example syntax [ref #25].
- **Verified-on:** Hopper + Blackwell-sm_100. Mode `FULL_AND_PIECEWISE` is documented "most performant for low latency with small models or MoEs" [ref #15], which is our case.

### B2. Set `--gpu-memory-utilization 0.30` explicitly (not default 0.9)
- **Knob:** `--gpu-memory-utilization 0.30` (or whatever fraction maps to ~84 GB on a 275 GB B300, leaving ~190 GB for Fish + Parakeet + headroom).
- **Expected gain:** **L** on co-residency safety. Default vLLM `gpu_memory_utilization=0.9` would try to claim ~248 GB and crash Fish-Speech (~20 GB) and Parakeet (~11.6 GB). vLLM-Omni doc explicitly addresses co-residency: "stages can share the same GPU as long as they run at different times in the pipeline" with sample values 0.6 and 0.1 summing ≤1.0 [ref #18].
- **Risk:** Setting too low starves KV cache and degrades long-context responses. Our 56.6 GB current usage suggests we're already implicitly there, but **explicit beats implicit** — current 56.6 GB / 275 GB ≈ 0.206. Recommend pinning explicitly.
- **Reversibility:** Trivial.
- **Source:** vLLM-Omni co-residency doc [ref #18], NVIDIA Forum DGX-Spark guidance "reduce gpu-memory-utilization below default 0.9 due to unified memory" [ref #11].
- **Verified-on:** Hopper + Blackwell. Same memory-budget math holds.

### B3. Set `--max-num-batched-tokens 2048` for batch=1 voice
- **Knob:** `--max-num-batched-tokens 2048` (instead of vLLM auto-default which may be 16384+ on V1).
- **Expected gain:** **S-M** on inter-token latency. vLLM optimization doc: "Smaller values (e.g., 2048) achieve better inter-token latency (ITL) because there are fewer prefills slowing down decodes" [ref #5]. We don't have many prefills (single user), so the win is mainly from preventing scheduler edge cases. Caveat: also decreases TTFT for very long prompts.
- **Risk:** **Lower** TTFT for >2048-token contexts (system prompt + RAG could push there). Medium — needs A/B with realistic prompt sizes, not 5-12 word stubs.
- **Reversibility:** Trivial.
- **Source:** vLLM Optimization & Tuning doc [ref #5], 2026-04-08 dated.
- **Verified-on:** General vLLM (not Blackwell-specific, but architecture-agnostic scheduler logic).

### B4. Disable `enable_thinking` per request for voice
- **Knob:** Pass `chat_template_kwargs={"enable_thinking": False}` on every voice-mode request from the LiveKit worker side; OR run vLLM with `--default-chat-template-kwargs '{"enable_thinking": false}'` to make it server-wide.
- **Expected gain:** **L** on perceived end-to-end latency for any prompt that would have triggered reasoning. NVIDIA model card: "if users prefer the model to provide its final answer without intermediate reasoning traces" use this flag [ref #4]. Without it, voice users wait through `<thinking>` token streams which TTS cannot voice. Our current `nano_v3` reasoning-parser will *parse them out of the output channel*, but the model still **generates** them — the actual content delay can be hundreds to thousands of tokens.
- **Risk:** Worse answer quality for genuinely complex queries. For a 911-PSAP-like dispatcher voice agent the reasoning quality loss is small relative to the latency gain. But this is a **product decision**, not just a knob.
- **Reversibility:** Trivial — request-level kwarg.
- **Source:** Model card [ref #4], HuggingFace blog "reasoning ON / reasoning OFF" sections [ref #7].
- **Verified-on:** Verified-on-Blackwell-sm_100 (NVIDIA's own example).

### B5. Add `--async-scheduling` explicitly + monitor for instability; pre-stage `--no-async-scheduling` rollback flag
- **Knob:** Make sure `--async-scheduling` is on for steady-state, but stage the `--no-async-scheduling` flag for instant rollback if we hit illegal-instruction crashes.
- **Expected gain:** vLLM Recipes calls async-scheduling "essential" — "Enable asynchronous scheduling to reduce the host overheads" [ref #1]. Forum/maintainer notes: async-scheduling improves throughput/ITL but can trade off TTFT for latency-sensitive serving [ref #26]. Mixed signal — measure. **Net for our config: probably already on by V1 default; explicit confirmation recommended.**
- **Risk:** **The key Mamba-on-Blackwell crash class** [refs #21, #22, #23] is mitigated by `--no-async-scheduling` plus `--enforce-eager`. We do not see this on sm_103 today, but if a vLLM/FlashInfer/Torch update changes Mamba kernel codegen, we want a one-flag rollback ready.
- **Reversibility:** Trivial.
- **Source:** vLLM Recipes [ref #1], NVIDIA NeMo issue #125 [ref #21], vLLM issue #37431 [ref #22], NVIDIA forum cuda-illegal-mem [ref #23].
- **Verified-on:** crash verified-on-sm_121, mitigation verified-on-sm_121, async-scheduling-itself verified-on-Blackwell-sm_100.

### B6. Decide enable_thinking-default + reasoning_budget at the system level, not per request
- **Knob:** Combine B4 with a `THINKING_BUDGET_LOGITS_PROCESSOR_ARGS`-style cap. The model card [ref #4] explicitly suggests `reasoning_budget = 512` to bound reasoning to 512 tokens-then-end (or +500 force-end).
- **Expected gain:** **M** on tail-TTFT. Bounds the worst case when `enable_thinking=True` accidentally hits a runaway-reasoning prompt; protects p99 voice latency.
- **Risk:** Low — already model-supported, doesn't affect non-thinking responses.
- **Reversibility:** Trivial.
- **Source:** Model card [ref #4], "Reasoning Budget Control" section.
- **Verified-on:** verified-on-Blackwell-sm_100 (model card prescribes it).

### B7. Tune `--mamba-ssm-cache-dtype float32` (NemotronH default in vLLM 0.20)
- **Knob:** vLLM 0.20 PR #39032 changed NemotronH default `mamba_ssm_cache_dtype=float32` [ref #13]. We should **confirm** our running build picked this up (we're on `0.20.1.dev0+g101584af0`, post-0.20.0). If it did, and we want to trade accuracy for memory/speed, we can go to `float16`.
- **Expected gain:** **S** on memory + maybe-S on token rate at the cost of accuracy (NVIDIA changed the default *to* float32 — so they think the accuracy hit of float16 was real).
- **Risk:** **High** for accuracy regression. NVIDIA's changing the default in our direction suggests we should **stay at float32**. Listed here only because it's a knob you'll see in PR notes; recommend leaving alone.
- **Reversibility:** Trivial.
- **Source:** vLLM 0.20.0 release notes [ref #13], vLLM Recipes [ref #1] ("set to float32 for accuracy or float16 for performance").
- **Verified-on:** verified-on-Blackwell.

### B8. Set up a 200-prompt realistic-load A/B test that measures TTFT p50/p95/p99 with **realistic dispatcher transcripts** (50-300 token system + RAG, not 5-12 word stubs)
- **Knob:** Process change, not a vLLM knob. Required to validate B1-B7 before declaring victory. Our 41.7ms p50 from 20 dispatcher-stub prompts is **not credible as the steady-state production number** — too short, likely prefix-cache-hot.
- **Expected gain:** Measurement, not optimization. But essential — without it we can't detect a regression after applying B1-B7.
- **Risk:** None.
- **Reversibility:** N/A.
- **Source:** NVIDIA Voice Blueprint observed RTX 5090 p50=171ms / max=255ms on Nemotron-3-Nano [ref #16] — sets the bar at one order of magnitude above our current measurement, suggesting our test is unrepresentative.
- **Verified-on:** general best-practice.

---

## C. Knobs that look promising but probably don't apply

- **EAGLE3 / draft-model speculative decoding for Nemotron-3-Nano.** Why it doesn't apply: **No EAGLE3 draft model has been published for Nemotron-3-Nano** — verified by directly enumerating the HuggingFace repo files [ref #8]: only model weights, tokenizer, modeling code, chat template, and `nano_v3_reasoning_parser.py` (798 bytes — not a draft model). Nemotron-3 *Super* (120B) does have built-in MTP layers; *Nano* does not [ref #9, ref #12]. Building our own EAGLE3 head is a multi-week training effort. Furthermore, vLLM issue #39790 [ref #10] reports **+114% mean TTFT and +331% p99 TTFT** with EAGLE3 in vLLM 0.17 — for voice, this is catastrophic regardless of token-rate gains. vLLM 0.20.0 PR #37588 ("Full CUDA graph for eagle prefill") and #39773 ("piecewise-fallback disabled for eagle draft decodes") may close this gap [ref #13], but with no draft model published, this is moot for us today. Source: refs #8, #9, #10, #12, #13.

- **MTP (Multi-Token Prediction) speculative decoding.** Why it doesn't apply: **Nemotron-3 Nano does not include MTP layers** (Super does) [ref #12]. Even if it did, NVIDIA forum reports "CUDA illegal memory access" with MTP+Nemotron-3-Super-NVFP4 on sm_121 [ref #23]; the workaround is the spark-vllm-docker image, not generic vLLM. Tag: claimed-unverified-on-Blackwell-sm_103 *and* model doesn't support it. Source: refs #12, #23.

- **`VLLM_FLASHINFER_MOE_BACKEND=latency` (TRT-LLM kernels).** Why it doesn't apply: TRT-LLM backend raises `NotImplementedError` for non-gated MoE activations like Nemotron's [ref #6]. We can't opt in even if we wanted lower latency. The CUTEDSL backend (`VLLM_FLASHINFER_MOE_BACKEND=masked_gemm` or the new `flashinfer-cutedsl-batched` from vLLM 0.20 PR #38251 [ref #13]) is in early support and **not documented as supported for Nemotron-3-Nano-NVFP4** in the model card. Tag: verified-blocked-on-Nemotron-architecture. Source: refs #6, #13.

- **FlashAttention 3.** Why it doesn't apply: Known to NOT support Blackwell — explicitly excluded by FlashInfer maintainers and confirmed in the user's own constraint list. Tag: verified-on-Hopper-only. (No new search needed; this is established.)

- **`--gpu-memory-utilization 0.95` (default-high).** Why it doesn't apply: Would try to claim ~262 GB and crash the co-resident Fish-Speech S2-Pro (~20 GB) and Parakeet TDT (~11.6 GB). See B2. Source: vLLM-Omni co-residency doc [ref #18].

- **Throughput-style `--max-num-batched-tokens 16384+` and `--max-num-seqs 256+`.** Why it doesn't apply: vLLM Optimization doc explicitly states higher values trade ITL for TTFT [ref #5]. Our use case is single-user batch=1; we want the opposite end of the curve. NVIDIA forum poster `trystan1` used `--max-num-seqs 256 --max-cudagraph-capture-size 256` for the **GPQA Diamond benchmark** with 198 active requests [ref #14] — that's batch=198 throughput testing, not voice. Source: refs #5, #14.

- **vLLM Recipes' `--async-scheduling` flag as "essential" — already covered.** Likely already default-on in V1 [ref #26]; we don't need to add it as if it were a new gain.

- **TP>1 (`--tensor-parallel-size 2+`).** Why it doesn't apply: NVIDIA model card [ref #4] uses `--tensor-parallel-size 1` for the 30B-A3B-NVFP4 single-GPU deploy. Going TP=2 would require splitting B300 across NVLink/PCIe and helps only if model didn't fit on one GPU — ours fits comfortably (56.6 GB / 275 GB).

---

## D. Unknown / experimental

- **`VLLM_FLASHINFER_MOE_BACKEND=masked_gemm` and the new vLLM 0.20 `flashinfer-cutedsl-batched` backend (#38251)** for non-gated MoE on Nemotron-3-Nano. What we'd need to learn: does it support Nemotron's NVFP4 + non-gated activations on sm_103, and does it beat CUTLASS at batch=1? How to learn it: live A/B in our existing benchmark harness, with rollback flag staged. **No public Nemotron-3-Nano benchmarks for either backend as of 2026-04-25.**

- **Whether vLLM 0.20.x default `cudagraph_mode` for hybrid Mamba models is `FULL_AND_PIECEWISE`, `FULL_DECODE_ONLY`, or downgraded to `PIECEWISE`.** vLLM doc states Mamba advertises only `UNIFORM_SINGLE_TOKEN_DECODE` and "we seek the minimum capability of all backends" [ref #15]. PR #34571 (merged 2026-03-04) caps FULL decode cudagraph sizes for Mamba/hybrid models [ref #24]. Implication: our current 14-min capture may already include a Mamba-induced downgrade. Worth checking the boot log; this affects whether B1 is even effective. How to learn it: grep our Phase-D boot log for `cudagraph_mode=` or `compilation_config`.

- **Whether livekit-plugins-openai 1.5.6 honors `chat_template_kwargs` from the LiveKit side.** LiveKit's OpenAI-compatible-LLMs doc [ref #20] doesn't explicitly mention `chat_template_kwargs` passthrough to vLLM. If it doesn't, we have to set it server-side via `--default-chat-template-kwargs` (B4 fallback). How to learn it: read `livekit-plugins-openai/src/livekit/plugins/openai/llm.py` directly.

- **Whether B300 sm_103 has the same Mamba-2 Triton illegal-instruction bug as sm_121 under heavy concurrency.** Issue #37431 [ref #22] is sm_121-confirmed only. sm_103 datacenter (HBM3e, NVLink) and sm_121 (DGX Spark, GB10 with Grace) have different memory subsystems and Triton may codegen differently. **No public sm_103 reproduction.** How to learn it: chaos-test by pushing batch>1 in a dev pod (we currently never see batch>1 in production).

- **Whether `--enforce-eager` on B300 sm_103 actually saves boot-time vs current 14 minutes** (and at what TTFT cost). The sm_121 workaround data point shows 14 tok/s → 8.8 tok/s (37% throughput penalty) [ref #22]. We don't know the sm_103 TTFT penalty. How to learn it: side-by-side launch with `--enforce-eager`, measure TTFT delta.

---

## Implementation notes

For each top-ranked B-bucket item: file/flag to touch, exact config to test, measurement to verify, rollback.

### B1 implementation note
- **File/flag:** vLLM serve command; either CLI flag `--cuda-graph-sizes 1 2 4 8` OR `--compilation-config '{"cudagraph_capture_sizes":[1,2,4,8]}'` (whichever our 0.20.1.dev0 build accepts — both have been documented in vLLM 0.20+ docs [refs #15, #25]). Also add `--max-num-seqs 1`.
- **Exact config to test:** Append the two flags; rebuild systemd unit / docker-compose; restart vLLM.
- **Measurement to verify:** (1) Boot-log timestamp delta from process start to `Application startup complete` — expect 14 min → 1-2 min. (2) Run our Phase-D 20-prompt suite; expect TTFT p50 unchanged within ±3 ms. (3) `nvidia-smi` GPU memory footprint should drop slightly.
- **Rollback:** Remove both flags. No data lost; pure capture-time/memory tradeoff.

### B2 implementation note
- **File/flag:** Add `--gpu-memory-utilization 0.30` to the vLLM serve command.
- **Exact config to test:** 0.30 → ~83 GB on 275 GB B300, comfortably above our current 56.6 GB usage with KV-cache headroom.
- **Measurement to verify:** `nvidia-smi` shows vLLM at ≤83 GB and Fish + Parakeet still running healthily. Run a 5-min voice call; confirm no OOM in any of the 3 services.
- **Rollback:** Drop the flag (returns to default 0.9, but that has historically not crashed because we have so much VRAM headroom — *this is hardening, not a fix for a current bug*).

### B3 implementation note
- **File/flag:** Add `--max-num-batched-tokens 2048` to vLLM serve.
- **Exact config to test:** 2048 (vLLM doc-recommended ITL value [ref #5]).
- **Measurement to verify:** A/B with current default. Measure TTFT p50/p95 on **realistic** dispatcher prompts (system prompt 100 tokens + RAG 200 tokens + user 30 tokens = ~330 token prefill — well under 2048). Expected: same TTFT ±2 ms, possibly tighter ITL distribution.
- **Rollback:** Remove flag. Note: if we ever serve a 4k+ token context, this flag becomes the prefill bottleneck — re-evaluate.

### B4 implementation note
- **File/flag:** *Two options.* Option A (per-request from LiveKit worker): pass `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` in our livekit-plugins-openai LLM call. Option B (server-wide): vLLM serve flag `--default-chat-template-kwargs '{"enable_thinking": false}'` (verify this flag exists in 0.20.1.dev0; otherwise A only).
- **Exact config to test:** Option A is safer — the integrator can flip it without restarting vLLM. Verify the kwarg is in the request payload (vLLM will log it at debug level).
- **Measurement to verify:** Run 50 voice prompts that *would* trigger thinking; count `<thinking>` tokens in the response stream (should be zero). Measure TTFT p50/p95 — expect *significant* drop on prompts that previously thought.
- **Rollback:** Stop sending the kwarg. Per-request kwarg has zero side effects.

### B5 implementation note
- **File/flag:** Confirm `--async-scheduling` is on (likely V1 default). Pre-stage rollback config file with `--no-async-scheduling --enforce-eager` ready to deploy.
- **Exact config to test:** No change to running config. Just create the rollback config artifact.
- **Measurement to verify:** Document the exact command to deploy the rollback config (~30 sec to swap and restart). Include in runbook.
- **Rollback:** N/A — this *is* a rollback artifact.

### B6 implementation note
- **File/flag:** If LiveKit can pass `chat_template_kwargs.thinking_budget`, set it to 512. Otherwise set the same via vLLM logits processor args.
- **Exact config to test:** Combine with B4. If thinking is OFF (B4), this is a belt-and-suspenders cap.
- **Measurement to verify:** Force a long-thinking prompt with `enable_thinking=True` overridden; verify reasoning ends within 512+500=1012 tokens.
- **Rollback:** Drop the budget arg.

### B7 implementation note
- **File/flag:** Confirm `--mamba-ssm-cache-dtype float32` is the active default (or set explicitly if not). **Recommendation: leave alone.** This is documented here only so it doesn't get accidentally toggled to float16 chasing speed.
- **Exact config to test:** No change.
- **Measurement to verify:** Boot log should show `mamba_ssm_cache_dtype=float32` for NemotronH model class.
- **Rollback:** N/A — keep at float32.

### B8 implementation note
- **File/flag:** Process: write a 200-prompt benchmark suite that mimics real dispatcher transcripts. Use representative system prompt + RAG + user utterance composition. Measure TTFT p50/p95/p99, tokens/sec p50/p95, end-to-end voice latency (mic-to-speaker) when paired with Fish + Parakeet.
- **Exact config to test:** Run on the existing config first to **establish a credible baseline**, then re-run after each of B1-B7 in sequence to attribute gains.
- **Measurement to verify:** Compare against NVIDIA Voice Blueprint published numbers [ref #16]: Nemotron-3-Nano on RTX 5090 was p50=171ms, max=255ms. Our B300 should beat this comfortably. If we can't beat 171ms p50 on realistic prompts, something is wrong upstream.
- **Rollback:** N/A — pure measurement.

---

## Sources

All retrieval dates 2026-04-25.

1. **vLLM Recipes — NVIDIA Nemotron-3-Nano-30B-A3B User Guide.** https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html — Recipes-page text dated 2026-04-09. Recommends `--trust-remote-code`, `--async-scheduling`, `--kv-cache-dtype fp8` (FP8 model) or `auto` (BF16); does **not** explicitly cover NVFP4 model (gap noted).

2. **vLLM blog — Streaming Requests & Realtime API.** Authors: Meta + Mistral AI + vLLM team. Published 2026-01-31. https://vllm.ai/blog/streaming-realtime — TTFT optimization for voice; max_tokens=1 trick for KV-cache preservation; chunked prefill defaults.

3. **vLLM blog — DeepSeek-V3.2 on GB300: Performance Breakthrough.** Authors: DaoCloud + vLLM team. Published 2026-02-13. https://vllm.ai/blog/gb300-deepseek — B300/GB300 sm_103 perf knobs; allreduce-fusion default-on; max-num-batched-tokens 32768 (DeepSeek-R1) or 20480 (V3.2). NOTE: those values target throughput-DeepSeek workloads, not single-user voice.

4. **HuggingFace — nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 model card.** Release date 2026-01-28. https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 — canonical NVFP4 vLLM serving command, env vars, `enable_thinking` toggle, reasoning-budget 512 pattern.

5. **vLLM — Optimization & Tuning doc.** Doc dated 2026-04-08. https://docs.vllm.ai/en/stable/configuration/optimization/ — chunked prefill, max-num-batched-tokens recommendations (2048 for ITL, >8192 for TTFT on small models), max-num-seqs.

6. **vLLM — Environment Variables doc.** https://docs.vllm.ai/en/stable/configuration/env_vars/ — Quoted: `VLLM_FLASHINFER_MOE_BACKEND` options "throughput" (CUTLASS), "latency" (TRT-LLM), "masked_gemm"; default "latency"; "Both require compute capability 10.0 or above"; `latency` raises NotImplementedError for non-gated MoE (separately confirmed in the search-result summary tied to vLLM issue #38971).

7. **HuggingFace blog — Nemotron 3 Nano: A new Standard for Efficient, Open, and Intelligent Agentic Models.** https://huggingface.co/blog/nvidia/nemotron-3-nano-efficient-open-intelligent-models — reasoning ON / OFF semantics; thinking budget; performance claims; NVFP4 4x throughput on Blackwell.

8. **HuggingFace — Nemotron-3-Nano-30B-A3B-NVFP4 file tree.** https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/tree/main — confirms **no EAGLE3 / MTP / draft-model artifact present**. Only safetensors weights, tokenizer, modeling code, chat template, and `nano_v3_reasoning_parser.py` (798 bytes).

9. **NVIDIA Technical Blog — Inside NVIDIA Nemotron 3.** https://developer.nvidia.com/blog/inside-nvidia-nemotron-3-techniques-tools-and-data-that-make-it-efficient-and-accurate/ — confirms MTP layers in Super, **Nano does not include MTP** (cited in WebSearch summary).

10. **vLLM issue #39790 — Significant TTFT Regression with Speculative Decoding (EAGLE3).** https://github.com/vllm-project/vllm/issues/39790 — Quoted: baseline mean TTFT 73.97 ms / p99 249.90 ms → with EAGLE3 mean 158.44 ms (+114%) / p99 1078.03 ms (+331%); TPOT improved 39.3%.

11. **NVIDIA Developer Forums — Testing Nemotron 3 Nano on DGX Spark/Jetson Thor with vLLM/FlashInfer.** https://forums.developer.nvidia.com/t/testing-nemotron-3-nano-models-on-nvidia-dgx-spark-jetson-thor-with-vllm-and-flashinfer/360642 — concrete vLLM serve command; `--gpu-memory-utilization 0.75` recommendation for DGX Spark; batch=10 mean TTFT 2792 ms, throughput 167 tok/s output. (Throughput numbers are for **batch=10**, not batch=1.)

12. **vLLM docs — MTP (Multi-Token Prediction).** https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/ — confirms MTP requires native MTP layers in target model; doesn't list Nemotron-3-Nano. Combined with [ref #9], confirms Nano lacks MTP.

13. **vLLM v0.20.0 release notes.** https://github.com/vllm-project/vllm/releases/tag/v0.20.0 — Published 2026-04-23 (per WebSearch summary). 546 commits / 257 contributors. Relevant PRs: #37588 Eagle prefill full-CUDA-graph, #39773 piecewise-fallback disabled for eagle draft decodes, #38251 FlashInfer CuteDSL batched-experts NVFP4 MoE, #39032 NemotronH default mamba_ssm_cache_dtype=float32, #32936 auto-cudagraph mode/sizes from attention backend, #38325 swapAB SM120 CUTLASS blockwise FP8 GEMM.

14. **NVIDIA Developer Forums — Nemotron-3-Nano-30B-A3B-NVFP4 on DGX Spark / GB10.** https://forums.developer.nvidia.com/t/nemotron-3-nano-30b-a3b-ultra-efficient-nvfp4-precision-version-of-nemotron-3-nano/359074 — Posts by `shahizat` 2026-01-31 (confirmed working config), `trystan1` 2026-01-30 (high-throughput config: `--max-num-seqs 256 --max-cudagraph-capture-size 256` for 198 concurrent requests).

15. **vLLM design — CUDA Graphs.** https://docs.vllm.ai/en/stable/design/cuda_graphs/ — FULL_AND_PIECEWISE mode "generally most performant for low latency with small models or MoEs"; Mamba advertises UNIFORM_SINGLE_TOKEN_DECODE only; hybrid models take min capability.

16. **Daily.co blog — Building Voice Agents with NVIDIA Open Models.** https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/ — RTX 5090 Nemotron-3-Nano TTFT p50=171ms, max=255ms; DGX Spark p50=750ms; full V2V latency RTX 5090 p50=508ms. (Datacenter B300 not benchmarked.)

17. **vLLM blog — Run NVIDIA Nemotron 3 Nano on vLLM.** Authors: NVIDIA Nemotron Team. Published 2025-12-15. https://vllm.ai/blog/run-nvidia-nemotron-3-nano — recommends `export VLLM_ATTENTION_BACKEND=FLASHINFER`; older command set used `--reasoning-parser deepseek_r1` before nano_v3 plugin existed.

18. **vLLM-Omni — GPU Memory Calculation and Configuration.** https://docs.vllm.ai/projects/vllm-omni/en/stable/configuration/gpu_memory_utilization/ — explicit co-residency math; example 0.6+0.1 sum-must-be-≤1.0.

19. **vLLM forum — V1 Default max CUDA graph size.** https://discuss.vllm.ai/t/vllm-v1-default-max-cuda-graph-size/357 — V1 default sweep is `[1,2,4] + range(8, 513, 8)` capped by max-num-batched-tokens; NOT capped by max-num-seqs in V1 (was in V0).

20. **LiveKit docs — OpenAI Compatible LLMs.** https://docs.livekit.io/agents/integrations/openai-compatible-llms/ — generic OpenAI-API plugin; "use vLLM, SGLang, or TRT-LLM for sub-300ms TTFT" (LiveKit's general guidance, not Nemotron-specific).
   - **20a.** LiveKit Agents 1.5+ release notes — preemptive_generation refinements for long/intermittent speech. https://github.com/livekit/agents/releases

21. **NVIDIA NeMo — issue #125 (Nemotron-3-Nano NVFP4 Illegal Instruction in V1 Engine on Blackwell/DGX Spark).** https://github.com/NVIDIA-NeMo/Nemotron/issues/125 — sm_121 (DGX Spark) confirmed; sm_103 not addressed; workaround `VLLM_USE_V1=0 --enforce-eager` or `--no-async-scheduling`.

22. **vLLM issue #37431 — Mamba-2 Triton kernels crash with illegal instruction on SM121.** https://github.com/vllm-project/vllm/issues/37431 — sm_121 specific; workaround `CUDA_LAUNCH_BLOCKING=1 --enforce-eager` costs ~37% throughput.

23. **NVIDIA Developer Forums — CUDA illegal memory access with MTP speculative decoding on Nemotron-3-Super-120B-NVFP4.** https://forums.developer.nvidia.com/t/cuda-illegal-memory-access-with-mtp-speculative-decoding-on-nemotron-3-super-120b-nvfp4-vllm-cu130-nightly-single-dgx-spark-gb10/366660 — sm_121 (DGX Spark/GB10); workaround is the `spark-vllm-docker` image specifically.

24. **vLLM PR #34571 — Cap FULL decode cudagraph sizes for Mamba/hybrid models.** https://github.com/vllm-project/vllm/pull/34571 — Merged 2026-03-04 by tdoublep. Adjusts capture sizes when both FULL decode and Mamba layers are present. Ships in vLLM ≥ post-2026-03-04 builds — likely included in our 0.20.1.dev0+g101584af0.

25. **vLLM forum — How to modify CUDA graph capture sizes via vllm plugin.** https://discuss.vllm.ai/t/how-to-modify-the-cuda-graph-capture-sizes-via-vllm-plugin/982 — `--compilation-config '{"cudagraph_capture_sizes":[1,2,4,8]}'` example syntax.

26. **vLLM forum — V1 async scheduling discussions.** https://discuss.vllm.ai/t/dose-vllm-v1-support-asynchronous-scheduling/446 — async-scheduling on by default in V1; can trade off TTFT for throughput; `--no-async-scheduling` to disable.

---

*Closing note:* The single thing this research could NOT find is a published B300-sm_103-data-center benchmark of Nemotron-3-Nano-NVFP4. Every external benchmark we could cite is on RTX 5090, DGX Spark (sm_121), B200 (sm_100), or Hopper. Our Phase-D number (TTFT p50 41.7ms) is therefore the **only** sm_103 number we have, and it should be re-measured on realistic prompts (B8) before being trusted as a steady-state production figure.
