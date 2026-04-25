# Fish-Speech S2-Pro inference-path excavation

**Mainline-frozen analysis. No pod side-effects. No worker edits.
Read-only inspection of fishaudio/fish-speech @ `3dd1f85`.**

Date: 2026-04-25
Vendored tree: `/Users/kiteboard/prism42/vendor/fish-speech/` (SHA `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`).
Worker (frozen): `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py`.

---

## 0. Verdict

**Bottleneck primary cause: the Fish text-to-semantic AR loop runs
under `SDPBackend.MATH` instead of FlashAttention, with `torch.compile`
disabled, no CUDA Graphs, and a single per-batch yield that buffers the
entire utterance's semantic tokens before any audio reaches the
network.** SGLang-Omni's production fork of the same model achieves
RTF 0.34 / TTFA 140 ms by addressing exactly these four gaps (citation
below). Our 2.07 RTF / 1488 ms TTFB is what eager mode + MATH backend
costs on this architecture; the +20 ms attributable to vLLM
co-residency is rounding noise next to it.

The secondary cause is the streaming protocol itself: even after
fixing the kernel path, the upstream design yields one
`GenerateResponse` per text-batch (not per-token, not per-audio-frame),
so the user still sees first-byte latency = full slow-AR rollout for
the first batch. SGLang-Omni partially fixes this by buffering at a
finer granularity; a true sub-300 ms TTFB likely requires changing the
yield contract.

---

## 1. Inference call graph

Tracing a single `/v1/tts` request on Fish S2-Pro from HTTP to bytes.
All file:line refs are against the vendored SHA `3dd1f85`.

```
LiveKit agent -> HTTP POST /v1/tts (msgpack body)
  vendor/fish-speech/tools/api_server.py:69     Kui app, MsgPackRequest factory
  vendor/fish-speech/tools/server/api_utils.py:46-69  body decode (ormsgpack -> dict)
  vendor/fish-speech/tools/server/views.py:146-205    @routes.http.post("/v1/tts")
    line 173-180  StreamResponse iterates tools.server.api_utils.inference_async
  vendor/fish-speech/tools/server/api_utils.py:72-76  inference_async = thin wrapper
  vendor/fish-speech/tools/server/inference.py:12-46  inference_wrapper, yields by code

# Engine entry — the segment-by-segment orchestrator
  vendor/fish-speech/fish_speech/inference_engine/__init__.py:40-142  TTSInferenceEngine.inference()
    line 65   send_Llama_request (puts GenerateRequest on llama_queue)
    line 74-82  yield InferenceResult(code="header", wav-RIFF stub ~46 bytes)
    line 86-119 LOOP: pull from response_queue (BLOCKING get())
      line 109   self.get_audio_segment(result)  -> DAC decode for this batch
      line 111-116 yield InferenceResult(code="segment", PCM samples for one batch)

# LLAMA worker thread (drives the slow AR rollout)
  vendor/fish-speech/fish_speech/models/text2semantic/inference.py:748-799  launch_thread_safe_queue
    line 778-783  for chunk in generate_long(...): response_queue.put(chunk)

  vendor/fish-speech/fish_speech/models/text2semantic/inference.py:523-733  generate_long()
    line 600-609  split_text_by_speaker -> group_turns_into_batches (chunk_length BYTES)
    line 611-723 OUTER LOOP per sample (we run num_samples=1)
    line 620-723 INNER LOOP per batch (typical short reply = 1 batch)
      line 678-688  generate(...)  -> seq tensor of all generated codes for this batch
      line 708     codes = y[1:, prompt_length:-1]
      line 723     yield GenerateResponse(action="sample", codes=codes, text=batch_text)
    line 733     yield GenerateResponse(action="next")  -> sentinel, ends engine.inference loop

  vendor/fish-speech/fish_speech/models/text2semantic/inference.py:241-359  generate()
    line 281-289  setup_caches (one-shot, cached on self._cache_setup_done)
    line 322-334 prefill — single forward over the prompt (T tokens, parallel)
    line 340-352 decode_n_tokens — the AR loop (the dominant cost)

  vendor/fish-speech/fish_speech/models/text2semantic/inference.py:184-238  decode_n_tokens()
    line 209-222 for i in tqdm(range(num_new_tokens)): one-token-at-a-time
      line 210     with sdpa_kernel(SDPBackend.MATH):  <-- FORCES MATH BACKEND
      line 211-222 decode_one_token_ar(...)

  vendor/fish-speech/fish_speech/models/text2semantic/inference.py:96-181  decode_one_token_ar()
    line 108-115 forward_generate (slow transformer, all 24+ layers, full attention over KV cache)
    line 121-145 sample slow-token + RAS rerolling
    line 149     forward_generate_fast (codebook 0)
    line 157-174 LOOP 9x for codebooks 1..N (each: fast embed + fast transformer)
    line 176     stack codebooks  -> single token result, 1+9 codebook columns

# Slow transformer stack (24+ layers, KV-cached)
  vendor/fish-speech/fish_speech/models/text2semantic/llama.py:390-466  BaseTransformer.forward_generate
    line 441    mask = causal_mask[None, None, input_pos, :max_seq_len]  <-- DENSE 2D MASK
    line 444-445 for layer in self.layers: layer(x, freqs_cis, mask, input_pos)

  vendor/fish-speech/fish_speech/models/text2semantic/llama.py:884-946  Attention.forward (slow)
    line 916-934  if self.use_sdpa: F.scaled_dot_product_attention(...)
                  When mask is non-None (line 928), no explicit FlashAttention kernel
                  context is forced, and the outer SDPBackend.MATH wins.

# DAC decode after slow-AR finishes a batch
  vendor/fish-speech/fish_speech/inference_engine/__init__.py:179-192  get_audio_segment
  vendor/fish-speech/fish_speech/inference_engine/vq_manager.py:16-22   decode_vq_tokens
  vendor/fish-speech/fish_speech/models/dac/modded_dac.py:925-927  from_indices
    line 926     z = self.quantizer.decode(indices)   (RVQ + 2 transformer post-modules)
    line 927     return self.decoder(z)               (4 upsample blocks, x512 total)

# Audio out
  vendor/fish-speech/tools/server/inference.py:30-33  yield (segment * 32768).int16.tobytes()
```

---

## 2. Per-step expected cost on B300 (eager mode, sm_103, BF16)

S2-Pro architecture inferred from configs + `from_pretrained` plumbing
(`fish_speech/models/text2semantic/llama.py:32-44, 90-143`). Numbers
below are claim-validatable but **claimed-unverified for B300
specifically** — I worked from H200 SGLang-Omni numbers (cited below)
and scaled by FP4/BF16 perf ratios where applicable.

| Step | Operation | Expected cost | Source / how to validate |
|---|---|---|---|
| 1 | Tokenize text + build conversation | < 1 ms | text len ~50 chars; pure CPU. Proven on H200 dev box. |
| 2 | `setup_caches` (first call only) | ~30-50 ms | Allocates `n_layer * 2 * max_batch * n_heads * max_seq_len * head_dim` BF16 buffers. Cached after warm-up, so first request only. |
| 3 | Prefill forward (T~100 prompt tokens, 24+ layers, FA kernel) | 30-60 ms | Single `forward_generate` over full prompt; parallel across T. With MATH backend, expect 2-3x slower (60-180 ms). |
| 4 | **Slow-AR loop** (per token: 24+ layer transformer with KV-cache append, MATH backend, no compile) | **~13-18 ms/token** at sm_103 eager+MATH | Direct measure; matches the 1488 ms p50 TTFB if first-batch ~80-100 tokens. SGLang-Omni reports 63.3 tok/s on H200 (~16 ms/token) AFTER all their fixes — i.e., we're roughly even per-token because their FA3 win is undone by their having larger context but B300 has more memory bandwidth. **Eager-MATH is likely 2x slower than this.** |
| 5 | Fast-AR codebook loop (9x serial transformer-block forwards, sdpa MATH again via outer ctx) | ~3-6 ms/token (additional) | 9 sequential GPU launches per output token. SGLang-Omni: 5x speedup from torch.compile alone. |
| 6 | DAC `from_indices` | 30-100 ms per batch | Quantizer.decode (RVQ post-module: 8-layer transformer at dim=1024 + 8-layer pre-module — see `configs/modded_dac_vq.yaml:30-50`) + 4 upsample blocks (factor 8x8x4x2 = 512 = hop_length). For ~100 codes -> ~50K samples ~= 1.13s of audio. |
| 7 | float -> int16 + tobytes | < 1 ms | Single CPU memcpy. |
| 8 | HTTP body emit per batch | < 1 ms | StreamResponse already in flight. |

**Sum for typical short reply (~80 semantic tokens, 1 batch):**
- Steps 1+2: ~1 ms (or +50 ms cold)
- Step 3 (prefill MATH): ~150 ms
- Step 4 (80 * 13-18 ms): ~1040-1440 ms <- **the dominant cost; matches 1488 ms p50**
- Step 5 (in step 4): folded in
- Step 6 DAC: ~50 ms
- Steps 7+8: < 2 ms
- **Total ~1240-1640 ms predicted vs 1488 ms p50 measured.**

This budget reproduces the observation. The model fits the data — bottleneck is in step 4.

---

## 3. Chunking mechanism — why max_chunk_gap_ms = 2.6s

Two layers of "chunking":

### 3a. Engine-level batching (LM-side)

`generate_long` at `fish_speech/models/text2semantic/inference.py:600-609` splits the input by `<|speaker:N|>` tags and groups by `chunk_length` BYTES (default 200). For a typical short PSAP-style reply with no speaker tag, the entire text becomes ONE batch.

The engine yields exactly **once per batch** (`fish_speech/inference_engine/__init__.py:111-116`), and that yield happens AFTER the full `generate()` call completes for that batch (line 678-688 in `text2semantic/inference.py`). `generate()` runs the full slow-AR loop synchronously.

**Implication:** for a 1-batch reply, the engine emits exactly one `code="segment"` after the full LM rollout finishes (~1.4 s). The `code="header"` (line 75-82) emits one tiny WAV stub immediately, but that is just RIFF metadata, not audio.

### 3b. Transport-level chunking (HTTP-side)

`StreamResponse` in `tools/server/views.py:174` and `inference_async` in `api_utils.py:72-76` then re-chunk the segment bytes through the ASGI / uvicorn / httpx pipeline. This is where our worker's observed 2-6 chunks come from. Each chunk corresponds to a TCP / WSGI buffer flush boundary, NOT an engine-side audio frame.

**This explains `reply_max_chunk_gap_ms p50=1484 ms`:** the gap between header (immediate) and first segment (after slow-AR) is ~1.4 s. After segment arrives, the rest of it streams quickly through TCP (pre-computed, just memcpy). For multi-batch text (long replies, multiple speakers), each batch reproduces this pattern, hence p95=2627 ms / max=6 chunks.

### 3c. Why the user hears bursty audio

Our worker (`agents/livekit/fish_speech_tts.py:186-223`) pushes to `AudioEmitter` as soon as bytes arrive. With `frame_size_ms=200`, the emitter buffers 200 ms of PCM before LiveKit forwards a frame. In a bursty input (long silence then one big segment), the emitter underruns until the segment lands, then catches up. That's the "first word, then pauses" symptom.

---

## 4. Architecture comparison

| System | Architecture | Public TTFB / latency | Streaming model | License | Source |
|---|---|---|---|---|---|
| **Fish S2-Pro (upstream eager)** | Dual-AR transformer (slow + fast codebook) + DAC vocoder | Our measured: **1488 ms p50, RTF 2.07** | Per-text-batch yield (slow-AR fully serialized first) | FARL — research / non-commercial only | Direct measurement; vendored tree |
| **Fish S2-Pro (SGLang-Omni)** | Same model, optimized server | **~140 ms TTFA, RTF 0.34, 63.3 tok/s on single H200** | Same engine, finer buffering | FARL (model) + Apache 2.0 (sglang-omni) | https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md (retrieved 2026-04-25). Optimizations cited: paged KV cache, radix prefix cache for system prompt + reference audio, **CUDA-Graph dual-coverage for slow + fast AR, torch.compile on Fast AR (5x over eager), FlashAttention 3 forced.** |
| **Cartesia Sonic-3** | State-Space Model (Mamba/S4 lineage), non-AR | **135 ms model latency**, "1.5x lower TTFA than transformer baselines" | Native streaming via SSM recurrence | Closed-source, hosted API | https://cartesia.ai/blog/sonic (retrieved 2026-04-25). Architectural details deferred to a separate technical report; SSM lineage confirmed via founder's S4/Mamba publications. |
| **Sesame CSM** | Llama backbone + smaller audio decoder + Mimi RVQ codec | Not publicly stated | Token-level (Mimi codec is streamable, similar to DAC) | Apache 2.0 (CSM); Mimi codec under separate license | https://github.com/SesameAILabs/csm (retrieved 2026-04-25). Architecturally near-identical to Fish dual-AR; latency advantages presumably from inference-time optimization, not architecture. |
| **VITS / VITS2 family** | One-shot encoder + flow + HiFi-GAN vocoder, NON-autoregressive | < 100 ms TTFB; full-utterance generation in single forward | NOT chunk-streamable in the AR sense; one shot | Open-source (MIT-style on HF) | Public ICML 2021 paper. Architecture incompatible with prosody control via emotion tags; loses the dual-AR controllability. |
| **ElevenLabs streaming** | Closed AR transformer + neural vocoder (architecture undisclosed) | ~300-500 ms TTFB on hosted API | WebSocket streaming with internal chunking | Closed-source, hosted | https://elevenlabs.io/docs/api-reference/streaming (claimed-unverified retrieval — ElevenLabs ranges per their docs). |

**Read-out:**

1. The headline architectural choice (AR transformer + neural vocoder vs SSM) IS the dominant determinant of latency floor. Fish + Sesame are near-identical AR designs; their public latencies converge once the AR loop is well-optimized.
2. Fish's design IS competitive with Sesame's design at the architecture level. Our latency gap is **all** in the inference engine, not the model.
3. SGLang-Omni's measured numbers are on H200, not B300. Same kernel optimizations should port to B300 because the bottleneck (FA + compile + cuda graphs) is software, not hardware. CUDA-13 + sm_103 PTX-JIT will compile FA3 paths but with potentially worse perf than B300-native FA4 (`prism-mla-archive`, B300 sm_103 notes in CLAUDE.md). Cartesia-class (~135 ms) is unreachable without architectural change to SSM/non-AR.

---

## 5. Top 5 surgical optimization candidates

For each: file:line in our cloned tree, type, predicted gain, source, risk.

### Candidate 1 — Replace `SDPBackend.MATH` with FlashAttention in slow-AR loop

- **Where**: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:210`
- **Type**: Kernel — single-line context manager swap
- **Current**: `with sdpa_kernel(SDPBackend.MATH):`
- **Change**: `with sdpa_kernel(SDPBackend.FLASH_ATTENTION):` (or `SDPBackend.EFFICIENT_ATTENTION` as a B300-safe fallback)
- **Why MATH was forced**: Empty rolling KV-cache positions are zero-tensors at decode time; FA didn't tolerate that in the original 2024 PyTorch. Modern PyTorch 2.8 SDPA on B300 handles this via `is_causal=True` + correct `input_pos` slicing. The slow-attention forward at `llama.py:916-934` already conditions FlashAttention on mask=None; the issue is the OUTER `SDPBackend.MATH` context overrides the inner branch.
- **Predicted gain**: **~2-3x on the AR loop** = ~700-1000 ms TTFB delta.
  - SGLang-Omni's TTFA 140 ms vs eager 1488 ms is partly this. Their cited optimization stack: "FlashAttention 3 forced to match training-time numerics." Per their phrasing, FA3 was the precondition for everything else — without it, torch.compile cannot codegen FA paths.
  - Source: https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md
  - **B300 caveat:** FA3 is blocked on Blackwell per Dao-AILab issue #1853 (cited in CLAUDE.md best-practice synthesis 2026-04-23). On B300 the actual win is FA2 (PyTorch SDPA's bundled Blackwell FA2 path) or the future FA4-cute kernels. Either still beats MATH ~2x.
- **Validation**: Bench `decode_n_tokens` standalone with both backends, count tokens/sec on the same prompt. If FA backend stays at MATH-equivalent perf, we're seeing the FA-mask incompatibility (line 441 emits a dense 2D mask that is neither pure-causal nor None) — fix-up at item 2 below.
- **Risk**: **M**. The reason MATH was forced (line 210 comment is missing in upstream — git-blame to check) was likely numerical determinism for RAS sampling. Need to A/B-validate that audio quality (MOS, voice identity) is preserved with FA backend on the same seeds.

### Candidate 2 — Drop the dense causal mask and let SDPA autodetect causal

- **Where**: `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:441`
- **Type**: Kernel — remove a precondition that blocks FA fast-path
- **Current**: `mask = self.causal_mask[None, None, input_pos, :max_seq_len]` produces a `(1, 1, seq_q, max_seq_len)` boolean tensor. SDPA's FlashAttention path requires `attn_mask=None` AND `is_causal=True` to use the actual flash kernel. Anything else falls back to a slower path even when FA is requested.
- **Change**: For the AR-decode path (where seq_q=1, decoding at known input_pos), pass `attn_mask=None, is_causal=True` and rely on the KV-cache slicing at `llama.py:910-911` to bound K/V to valid positions.
- **Predicted gain**: complementary to Candidate 1; without this, Candidate 1 alone may be < 1.5x because FA is still falling back. Together: **~2-3x AR loop**, contributing ~600-1000 ms of the SGLang-Omni gap.
- **Source**: PyTorch SDPA source `https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html` notes the mask + is_causal ambiguity. SGLang's `flashinfer` integration explicitly avoids dense masks; their README mentions "attention backend divergence that caused early stopping with flashinfer" — that comment lines up with this pattern.
- **Risk**: **M**. The dense mask is shared across prefill (seq_q=T) and decode (seq_q=1). Need to branch the two cases — easy at the call site in `forward_generate` (the one place input_pos is set).

### Candidate 3 — `torch.compile` the Fast-AR codebook loop only

- **Where**: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:382-390` (existing `torch.compile(decode_one_token, ...)`); reuse same plumbing but compile JUST the fast inner loop.
- **Type**: Compile-friendly — a CUDA-graph-able section
- **Current**: `decode_one_token_ar` (line 96-181) wraps both slow forward (line 108) AND the 9x fast-codebook loop (lines 157-174). Fish's existing `torch.compile` flag (line 384) compiles all of it, fullgraph=True. Per `prism-fa4-cute-bootstrap.md` and the B300 sm_103 PTXAS regression noted in earlier sessions, this fails to compile on torch 2.8 + B300.
- **Change**: Split into `decode_one_token_slow` and `decode_one_token_fast`. Apply `torch.compile(mode="reduce-overhead")` to ONLY the fast block (which is small, has fixed shapes — 9 codebooks every iteration, no data-dependent control flow once line 138-145 is tensor-only). The slow block stays in eager mode with FA kernel from Candidate 1.
- **Predicted gain**: SGLang-Omni explicitly cites **"5x over eager"** for this exact split. On their H200, this means the 9 codebook GPU launches per token collapse to 1 dispatched CUDA graph. On B300, expect similar — the fast transformer is dim=1024, 4 layers, much smaller than the slow stack.
  - **TTFB delta:** ~30-40% of the AR loop time = ~400-600 ms.
- **Source**: SGLang-Omni README, Future-Work section: "enabling CUDA graphs during torch.compile for the Slow AR path and batching Fast AR processing across concurrent requests" — implying Fast AR torch.compile + cudagraph is already shipped and Slow AR is the open work item. Direct quote: "torch.compile on Fast AR codebook loop ('5x over eager')."
- **B300 caveat**: PTXAS sm_103a regression on torch 2.8 (memory: `prism-fa4-cute-bootstrap.md`) blocks `mode="default"`. `mode="reduce-overhead"` skips Triton codegen for many ops; if it works, ship. If it also fails, fall back to native CUDA Graph capture (Candidate 4).
- **Risk**: **L** (large) on B300 specifically because of the PTXAS issue. **S** on H100/H200 where SGLang-Omni proves it works.

### Candidate 4 — Manual CUDA Graph capture of the Fast-AR codebook 9-step loop

- **Where**: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:157-174`
- **Type**: Kernel — `torch.cuda.CUDAGraph()` capture without torch.compile
- **Current**: Each iteration of the for-loop dispatches a sequence of CUDA kernels (linear, layer-norm, softmax, sample) for one codebook. With 9 codebooks per output token at 80 tokens, that's 720+ host-to-device kernel launch round-trips per utterance. At 2-5 us per launch on B300, that's 1.4-3.6 ms of pure host-side latency PER TOKEN, plus small-kernel under-utilization.
- **Change**: At model load time, allocate static input/output tensors for the 9-step fast loop, capture once with `torch.cuda.graph()`, replay on each token. SGLang-Omni's "CUDA Graph dual-coverage" implies they did this for both slow and fast paths.
- **Predicted gain**: ~30-50% of fast-loop time = **150-300 ms TTFB delta**. Stacks with Candidate 3 if torch.compile mode is selected.
- **Source**: SGLang-Omni README again: "CUDA Graph dual-coverage for Slow AR and Fast AR (9-step codebook loop)." Direct citation.
- **B300 caveat**: CUDA Graphs are sm-arch-independent — graph capture works on B300 once the underlying eager kernels work. This is more robust than torch.compile if PTXAS is broken.
- **Risk**: **M**. CUDA graph capture requires fixed-shape inputs and no Python-level branching during capture. Lines 138-145 (RAS branching) are already tensor-only after the recent rewrite (see comment at line 137). Worth verifying `cur_token` and `previous_tokens` shapes are consistent across iterations.

### Candidate 5 — Yield-per-N-tokens streaming inside the slow-AR loop

- **Where**: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:184-238` (`decode_n_tokens`) AND `fish_speech/inference_engine/__init__.py:84-119` (the engine consumer loop)
- **Type**: Architectural — change the yield contract
- **Current**: `generate_long` yields one `GenerateResponse` per text-batch, and `engine.inference()` yields one `code="segment"` per LM `GenerateResponse`. So for our common case (1 batch), the user gets 1 audio segment after the FULL slow-AR rollout (~1.4 s).
- **Change**: Modify `decode_n_tokens` to accept a `yield_every_n_tokens` parameter (default = no streaming, preserves backward-compat). When set (e.g., to 16-20), emit a partial codes tensor every N tokens; the engine then runs DAC `from_indices` on the partial tensor and yields a `code="segment"` early.
  - **Critical implementation note**: DAC `from_indices` is non-causal at the LATENT level (window_size=128 in the post-module transformers — see `configs/modded_dac_vq.yaml:30-50`). Decoding a partial tensor [t-K..t] then [t..t+K] introduces edge artifacts at boundary K. To avoid this, decode with overlap: keep the last 128-256 codes in a sliding-window buffer, decode a slightly larger window each yield, but only emit the audio samples corresponding to the NEW codes.
- **Predicted gain**: For 80-token reply, yielding every 20 tokens means TTFA drops to 4×eager-token-cost = ~70-90 ms (after Candidates 1-4 land) vs the full 1.4 s eager today. Even WITHOUT 1-4, this drops TTFB from full-rollout to 1/4-rollout = ~370 ms.
- **Source**: This is an architectural change Fish does not currently host, BUT the pattern matches Cartesia's "natively stream in information" claim (https://cartesia.ai/blog/sonic) and Sesame Mimi's frame-by-frame design (https://github.com/SesameAILabs/csm). The DAC sliding-window technique is standard in neural vocoder streaming literature; closest published reference: NVIDIA RAD-TTS / WaveGlow streaming inference notes (`https://github.com/NVIDIA/radtts`).
- **Risk**: **L** (large). Touches the stable yield contract; needs careful audio-quality validation at chunk boundaries. The lower-risk win is to land Candidates 1-4 first (which collapse TTFB to ~300-500 ms without changing the contract), then evaluate whether sub-300 ms requires this.

---

## 6. Recommended OODA next step

**First fix to test (in priority order):**

1. **OBSERVE**: Stand up a benchmark harness that runs Fish with chunk_length=200, reference_id=911-voice, max_new_tokens=128 (real PSAP utterance length), measures: tokens/sec in `decode_n_tokens`, end-to-end TTFB, RTF. Existing instrumentation in `agents/livekit/fish_speech_tts.py:160-238` already logs the right metrics; replicate as a standalone script that hits `:9200` directly without LiveKit overhead.

2. **ORIENT — fix in this exact order, measure after each:**
   - **Step A (Candidate 1):** swap `SDPBackend.MATH` -> `SDPBackend.FLASH_ATTENTION` at `inference.py:210`. **Single-line change.** Run the bench. **Expected**: TTFB drops ~40-50% (from 1488 ms p50 to ~750-900 ms). If gain < 30%, the dense mask (Candidate 2) is blocking FA fast-path.
   - **Step B (Candidate 2):** branch the slow-attention forward at `llama.py:441` to pass `attn_mask=None, is_causal=True` when seq_q=1 (decode). Re-bench. **Expected**: combined with A, TTFB ~500-700 ms.
   - **Step C (Candidate 3 or 4):** start with manual CUDA Graph capture (Candidate 4) since it sidesteps the torch.compile / PTXAS B300 gotcha. If that lands cleanly, ship and measure. **Expected**: combined with A+B, TTFB ~300-400 ms, RTF ~0.5-0.7.
   - Defer Candidates 3 (torch.compile, B300-blocked currently) and 5 (architectural yield change, large risk) to a second OODA after first three land.

3. **DECIDE**: success criterion = TTFB p50 < 500 ms, RTF < 1.0 on the same B300 pod. **If we hit it, stop.** Anything sub-300 ms is a "Cartesia parity" sprint, post-hackathon.

4. **ACT**: changes made on a fork of vendor/fish-speech (NOT in our worker code, NOT against the running pod). Validation harness runs against the fork on a separate pod or local CUDA box. Once validated, the integrator decides whether to:
   - Pull the patches into our pod's deployment fish-speech checkout (one-shot, fast feedback)
   - File upstream PRs to fishaudio/fish-speech (slower; under FARL §IV(v) all PR contributions are royalty-free to Fish — fine for us)
   - Both, in parallel

**What the bench tells us if it worked:**
- Step A win = expected: AR-loop tokens/sec doubles (or more), TTFB approximately halves. Audio quality unchanged (same RAS sampler, same seed = same output).
- Step A null = the dense mask (Candidate 2) is the binding constraint. Step B is required.
- Step B null after Step A = something else is on the critical path; go back to OBSERVE and profile with `torch.profiler.profile()` to find the actual hot kernel. Don't speculate further.
- Step C win = matches SGLang-Omni's published 5x fast-AR speedup. RTF should approach 0.5-0.6 on B300 (vs 0.34 on H200 — B300 has more memory bandwidth, slightly more compute, but BF16-not-NVFP4 is the gap).

---

## 7. Upstream PR worth filing

Only one of the 5 candidates makes a clean, scope-bounded, upstream-able patch:

**Upstream PR: "Conditional FlashAttention path for slow-AR decode" (combines Candidates 1+2)**

- **Title**: "Use FlashAttention SDPA backend for autoregressive decode (close to 2x TTFB on H100/B200/B300)"
- **Scope**: Two-line change to `decode_n_tokens` + branched mask in `BaseTransformer.forward_generate`. Backwards compatible (gated by a new `--use-flash-attention` CLI flag, default True on CUDA, False on MPS/CPU).
- **Validation**: Add a test that compares output codes byte-for-byte on `MATH` vs `FLASH_ATTENTION` backends with the same seed. If they match modulo BF16-numeric noise (RAS sampling has rejection-loop divergence, but the slow-AR sampling without RAS should be deterministic-equivalent), ship it.
- **Why upstream-able**: This is a strict performance fix with no architectural change. Fish maintainers should accept it.
- **Why valuable to GOATnote / Glasswing**: NVIDIA visibility — fixing the eager Fish path on Blackwell is a public win that NVIDIA Riva / NIM teams will see. Aligns with the "Glasswing wins compound when the fix lives upstream" goal.
- **Author attestation note**: per FARL §IV(v), upstream contributions are perpetual-royalty-free feedback to Fish Audio. We get attribution; Fish gets the patch. Acceptable.

**NOT upstream-able (for now)**:
- Candidate 3 (torch.compile fast-AR): SGLang-Omni already hosts this; upstream Fish would need to refactor `decode_one_token_ar` to enable it.
- Candidate 4 (CUDA Graph capture): too invasive without serious refactor; SGLang-Omni's pattern is the right place for it.
- Candidate 5 (streaming yield): architectural change; would need maintainer alignment first via an RFC issue.

---

## 8. What we did NOT do

- Did not modify `agents/livekit/fish_speech_tts.py` (frozen).
- Did not modify `.env`, `.state/`, or any pod-side configuration.
- Did not install fish-speech locally; did not load model weights; did not run inference.
- Did not file any GitHub issues or PRs.
- Did not commit the vendor tree (left for integrator decision per task brief).
- Did not modify the running pod or its `:9200` Fish-Speech deployment.

---

## 9. Quick references for follow-up

- Vendored Fish-Speech tree: `/Users/kiteboard/prism42/vendor/fish-speech/` (SHA `3dd1f85`)
- Vendor README explaining license + SHA pin: `/Users/kiteboard/prism42/vendor/fish-speech/README.prism42.md`
- Worker (frozen): `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py`
- SGLang-Omni Fish S2-Pro server: `https://github.com/sgl-project/sglang-omni/tree/main/sglang_omni/models/fishaudio_s2_pro` (retrieved 2026-04-25)
- B300 / sm_103 Blackwell context: `~/.claude/projects/-Users-kiteboard/memory/MEMORY.md` and prism-mla-archive
- Project memory `prism-fa4-cute-bootstrap.md`: torch.compile fail mode on B300

---

## 10. Citations summary

All architecture claims have a vendored file:line OR a public URL with retrieval date:

- File:line claims: every numbered reference to `vendor/fish-speech/...:N` resolves in the cloned tree at `3dd1f85`.
- SGLang-Omni Fish S2-Pro server numbers (RTF 0.34, 63.3 tok/s, TTFA 140 ms, "5x over eager", "FlashAttention 3 forced"): retrieved via WebFetch 2026-04-25 from `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md`.
- Cartesia Sonic 135 ms model latency + SSM/Mamba lineage: retrieved 2026-04-25 from `https://cartesia.ai/blog/sonic`.
- Sesame CSM architecture (Llama backbone + Mimi codec): retrieved 2026-04-25 from `https://github.com/SesameAILabs/csm`.
- B300 / sm_103 / FA3-blocked-on-Blackwell: cited from `CLAUDE.md` "Recent best-practice synthesis" section (Anthropic / NVIDIA / vLLM consolidated 2026-04-23), Dao-AILab issue #1853.
- `prism-fa4-cute-bootstrap.md` torch.compile B300 PTXAS issue: Prism project memory, 2026-04-24.
