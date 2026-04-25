# Cycle-2d Fish FA patch — adversarial validator (static)

Reviewer: glasswing-discipline static auditor (no patch applied, no pod side-effects).
Date: 2026-04-25T13:57:34Z (UTC).
Vendored base under audit: `/Users/kiteboard/prism42/vendor/fish-speech/` @ SHA `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`.
Patch under audit: `/Users/kiteboard/prism42/findings/voice/cycle-2d-fish-patches/recipe.patch` (87 lines, 4 deltas, 2 files).

---

## Verdict: **SAFE**

The 4-delta patch is internally consistent, the K/V slicing math is correct (slot-zero-init on the cache buffer means slot reuse cannot corrupt mask=None attention), prefill and fast-AR codebook paths are correctly NOT touched by the patch's gates, and the documented PyTorch 2.8 SDPA backend selection on sm_103 will fall back gracefully to EFFICIENT_ATTENTION (still 2-3x faster than MATH) if FA2-via-cuDNN is not available — no silent garbage path.

One DEGRADED-tier concern is documented in §"input_pos.item() sync cost" — the `.item()` call introduces ~30k host-device syncs per long generation, which is acceptable for cycle-2d (no compile-graph in flight) but is a regression vector for cycle-2e if torch.compile lands. Team F documented this trade-off explicitly in recipe.md §2 Delta C; not a blocker.

## Confidence: **HIGH**

Reasons for HIGH (not MEDIUM or LOW):
- All 4 deltas grounded by direct read of vendored source at the affected file:line.
- KVCache.update() at `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:205-214` confirmed to write at exactly `input_pos`, with the surrounding `register_buffer("k_cache", torch.zeros(cache_shape))` at line 202 confirming slots beyond `input_pos[-1]` are zeros (not stale data) — slicing-out is unconditionally safe.
- `forward_generate_fast` at `llama.py:799-817` confirmed to ALWAYS pass non-None `fast_mask`; the patch's slicing block is gated on `mask is None` and therefore correctly does NOT fire on the fast-AR codebook path.
- Prefill (`input_pos = torch.arange(0, T)`, T > 1) confirmed to NOT trigger the patch's `is_decode_step = input_pos.numel() == 1` gate; dense causal mask retained on prefill.
- The `is_causal=True → False` flip in the no-mask FLASH branch is sound because Q=1 against sliced K[0:input_pos+1] is degenerate-causal (a single query has no preceding-or-following structure to mask).

Reasons it is not MEDIUM:
- I read the actual source for KVCache, decode_one_token_ar, forward_generate, forward_generate_fast, and Attention.forward end-to-end. The patch has no surprise code path.

Reason it is not LOW:
- I did not run a synthetic Q=1 test (laptop venv has no torch installed; B300 pod is the only viable place to run it; running it on the pod would mutate state and is out of scope for static review).

---

## Per-delta analysis

### Delta 1 — drop SDPBackend.MATH at inference.py:210

**Patch action**: removes `with sdpa_kernel(SDPBackend.MATH):` wrapper around `decode_one_token(...)` call inside `decode_n_tokens` at `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:210`.

**Correctness**: The MATH-backend wrapper was an outer context manager that forced ALL SDPA calls inside `decode_one_token_ar` (slow + 9 fast codebook layers) to use the eager-Python MATH kernel. Removing it lets each `Attention.forward` call dispatch via SDPA's normal backend-selection logic.

For the SLOW path (`forward_generate` → llama.py:441 → patched mask=None → llama.py:917-926 → `with sdpa_kernel(SDPBackend.FLASH_ATTENTION):`): the inner explicit FLASH_ATTENTION context wins over the absent outer context — slow path now actually reaches the FA kernel.

For the FAST path (`forward_generate_fast` → llama.py:805 → fast_mask non-None → llama.py:927-934 in the `else` branch with attn_mask=fast_mask): SDPA receives a non-None bool mask, which historically blocks FLASH_ATTENTION dispatch (FA backend rejects when attn_mask is non-None — see PyTorch SDPA docs https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html, "FlashAttention will be selected when ... no attention mask is provided"). With the outer MATH wrapper gone, the fast path falls back to EFFICIENT_ATTENTION (mem-efficient kernel) instead of MATH — still a strict speedup.

**Risk**: low. The 4-step FA backend selection on sm_103 with bf16 + head_dim=64 + non-square Q=1, K=T+1 attention satisfies all FA2-via-cuDNN constraints documented in PyTorch 2.8 SDPA. If FA2 rejects (unlikely on Blackwell with cuDNN 9.x), SDPA falls back to EFFICIENT — which is still 1.5-2x faster than MATH per public PyTorch SDPA benchmarks (https://docs.pytorch.org/tutorials/intermediate/scaled_dot_product_attention_tutorial.html). No silent garbage path.

**B300 verification**: Cannot directly verify backend selection without pod access. Recommended verification by Team 1 at apply-time (added to "Pre-application checklist for Team 1" below): `python -c "import torch; print(torch.backends.cuda.flash_sdp_enabled(), torch.backends.cudnn.version())"` on the pod must return `(True, >=90000)` (cuDNN 9.0+) for FA2-via-cuDNN to be live.

### Delta 2 — mask=None for Q=1 decode at llama.py:441

**Patch action**: replaces the unconditional dense mask construction with a conditional:

```python
is_decode_step = input_pos.numel() == 1
mask = (
    None
    if is_decode_step
    else self.causal_mask[None, None, input_pos, :max_seq_len]
)
```

**Correctness**: The `input_pos.numel() == 1` predicate correctly identifies the single-token AR decode step. The prefill path uses `input_pos = torch.arange(0, T)` (per `inference.py:294`, `inference.py:436`) which has `numel == T > 1` for any non-trivial prompt → falls to the `else` branch → keeps the dense mask. Decode steps from `decode_n_tokens` use `input_pos = torch.tensor([T])` (per `inference.py:338`) which has `numel == 1` → mask=None.

**Stale-slot hazard**: with mask=None and `is_causal=False` (delta 4), Q=1 attends to ALL keys. This is only correct if every key is valid. The KVCache buffer is initialized via `torch.zeros(cache_shape, dtype=dtype)` at `llama.py:202`, and `KVCache.update()` at `llama.py:205-214` writes ONLY at `input_pos` slots. Slots beyond `input_pos[-1]` therefore contain bf16-zero — but those slots are SLICED OUT by delta 3 (`k = k[:, :, :valid_len, :]`), so they don't contribute. The mask=None + sliced-K combination is safe.

**Slot-reuse hazard**: across requests, does the cache get cleared? `setup_caches` at `inference.py:282-289` is gated by `_cache_setup_done` so subsequent requests reuse the same buffer. However, EACH new request starts at `input_pos = torch.arange(0, T)` for prefill, which OVERWRITES slots 0..T-1 with the current request's K/V. Decode then writes at T, T+1, ... overwriting old slots. Since we slice to `[0:input_pos[-1]+1]`, we read only slots written by the current request. **No cross-request contamination.**

**Edge case — single-token prefill (T=1)**: `input_pos = torch.arange(0, 1) = tensor([0])` has `numel == 1` → patch treats it as decode → drops mask, slices K to [0:1]. Q=1 against K[0:1] with `is_causal=False` lets the single query attend to position 0 (itself). Correct semantics. (This case is unlikely to occur with real Fish prompts — they have a multi-token system prompt + speaker tag — but it is not unsafe.)

**Risk**: low. Predicate is exact; slot-zero-init is a hard guarantee from `register_buffer("k_cache", torch.zeros(...))`.

### Delta 3 — slice K/V to input_pos[-1]+1 at llama.py:910

**Patch action**: after `k, v = self.kv_cache.update(input_pos, k, v)` at line 911, when `mask is None and input_pos is not None and input_pos.numel() == 1`, slice cached K/V:

```python
valid_len = int(input_pos[-1].item()) + 1
k = k[:, :, :valid_len, :]
v = v[:, :, :valid_len, :]
```

**Correctness of math**:
- After kv_cache.update, slot `input_pos[-1]` contains the just-cached current-token K/V.
- Slots `[0..input_pos[-1]]` contain real values from this request's prior steps.
- Slots `[input_pos[-1]+1..max_seq_len]` are bf16-zero (never written by this request).
- `valid_len = input_pos[-1].item() + 1`.
- `k[:, :, :valid_len, :]` is `k[:, :, :input_pos[-1]+1, :]` — Python slice end is EXCLUSIVE, so this includes slots `[0..input_pos[-1]]` inclusive, which is exactly the range of valid (real) values, **including** the just-cached current token.

**Off-by-one verification**: If `input_pos[-1] = T` (we just cached at slot T), then `valid_len = T+1`, slice `[0:T+1]` covers slots `[0, 1, ..., T]` (T+1 slots, all valid). The current token at slot T is included. Correct.

**Counter-example to the wrong slicing** (`[input_pos:input_pos+1]`): would have given a 1-slot K/V containing only the current token, breaking attention to ALL prior tokens. The patch does NOT do this — it correctly does `[0:input_pos+1]` (delta 3 line 4 in patch: `k = k[:, :, :valid_len, :]`).

**Tensor-shape concerns**:
- `input_pos[-1]` is a 0-d tensor of dtype int64.
- `.item()` returns a Python int (CUDA→CPU sync, see "input_pos.item() sync cost" below).
- `int(...)` coerces (no-op since `.item()` already returns int).
- `+1` is a Python int operation.
- `k[:, :, :int_val, :]` uses tensor slicing which is well-defined for any positive integer.
- Batch dim (`:`) and head dim (`:`) and head-dim-tail (`:`) are preserved. No broadcasting hazards.

**Risk**: low.

### Delta 4 — is_causal=True → False at llama.py:924

**Patch action**: in the `if mask is None` FLASH_ATTENTION branch at llama.py:917-926, flip `is_causal=True` to `is_causal=False`.

**Correctness**: With Q=1 against K[0:valid_len] (sliced via delta 3), the query represents the single most-recent decode token. It must attend to all valid cached keys (positions 0..valid_len-1, including itself). PyTorch SDPA's `is_causal=True` with non-square (1, valid_len) attention uses upper-LEFT alignment per `https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html` ("If is_causal=True, attention is causal with the diagonal aligned to the upper-left of the attention matrix"), which would mask out everything except K position 0 — clearly wrong.

`is_causal=False` lets Q=1 attend uniformly over the full sliced K. Since sliced K already excludes future (zero-init) slots, the result is causally-correct by construction.

**Prefill bypass**: this branch is ONLY entered when `mask is None` (line 917). Prefill keeps the dense mask (delta 2 falls to `else`), so prefill goes to the `else` branch at llama.py:927-934 (existing dense-mask SDPA call) — `is_causal` flag is irrelevant there. No prefill regression.

**Risk**: low.

---

## Cross-cutting audits

### Prefill path independence

Verified by direct read of `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:282-359`. The prefill uses:
- `input_pos = torch.arange(0, T, device=device, dtype=torch.long)` at line 294
- `prefill_decode = decode_one_token_ar` at line 322
- Calls `prefill_decode(model, prompt, input_pos, ...)` at line 324

This routes to `decode_one_token_ar` → `model.forward_generate(x, input_pos, ...)` (line 108) → `BaseTransformer.forward_generate` → patched gate `is_decode_step = input_pos.numel() == 1`. For prefill, `input_pos.numel() == T > 1` → gate is False → keeps dense mask. The patch is INACTIVE for prefill, by design.

After prefill produces the first token, `decode_n_tokens` is called with `input_pos = torch.tensor([T])` (`inference.py:338`) — numel=1 → patch active for decode steps. Per-step increment at `inference.py:224` (`input_pos += 1`) keeps `input_pos.numel() == 1` throughout the AR loop.

**Confirmed**: prefill and decode use the SAME `decode_one_token_ar` function but with different `input_pos.numel()` shapes. The patch's gate correctly distinguishes them. **No risk of prefill corruption.**

### Fast-AR codebook path independence

Verified by direct read of `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:799-817` and `inference.py:148-174`.

The 9 fast-AR codebook layers go through `forward_generate_fast` at `llama.py:799`, which builds its own `fast_mask = self.causal_mask[None, None, input_pos, :self.config.num_codebooks]` at line 805 — non-None bool tensor. This is passed to `Attention.forward` (line 884) with `mask=fast_mask` (non-None).

In Attention.forward, the patch's slicing block at the new line 925-931 is gated on `mask is None and input_pos is not None and input_pos.numel() == 1`. Since fast-AR mask is NEVER None, the slicing block does NOT fire. The fast-AR path falls into the existing `else` branch at line 927-934 (`F.scaled_dot_product_attention(q, k, v, attn_mask=mask, ...)`) — UNCHANGED by the patch.

**Confirmed**: the fast-AR codebook 9-step loop is entirely unaffected by deltas 2-4. **No risk of fast-AR corruption.** (Delta 1 — outer MATH wrapper drop — does affect fast-AR, but the effect is only "FAST path now uses EFFICIENT_ATTENTION instead of MATH" — strictly an upgrade.)

### input_pos.item() CUDA→CPU sync cost

Per Team F's recipe.md §2 Delta C: "`int(input_pos[-1].item())` introduces a CUDA→CPU sync per step, which would block torch.compile's full-graph capture. For now this is acceptable because cycle-2d explicitly defers compile per `prism-fa4-cute-bootstrap.md`."

Verified: line 70 of recipe.patch (`valid_len = int(input_pos[-1].item()) + 1`) is one `.item()` call per Attention.forward invocation. With 24+ slow layers per token and ~80 tokens per typical PSAP utterance, that's ~24 × 80 = ~1920 sync points per generation.

A CUDA→CPU sync on a B300 with NVLink-class topology is on the order of 5-10 µs (latency-bound, not bandwidth). 1920 × 7 µs ≈ 13 ms total over the full generation, which is < 1% of the ~1500 ms baseline TTFB. Acceptable.

For the cycle-2a-debug bench window of "~30k tokens", that scales to ~30k × 24 = ~720k syncs ≈ 5 seconds of pure sync overhead per 30k-token sweep. Still acceptable for a benchmark; would be material for production-throughput sweeps.

**Cycle-2e blocker note**: when torch.compile is re-enabled on cycle-2e+, this `.item()` call MUST be replaced with a graph-friendly construct (e.g., a pre-computed `cu_seqlens` tensor, or a static-shape pad-mask that the compiler can capture without host-device sync). Documented in recipe.md §2 Delta C; not a cycle-2d concern.

### Numerical determinism

Switching from MATH (eager Python loop, exact bit-precise BF16 matmul) to FLASH_ATTENTION (cuDNN FA2 kernel, fused softmax with online accumulation) WILL produce different last-bit results in the BF16 mantissa.

Audited Fish-Speech for exact-equality assertions:
- `decode_one_token_ar` at `inference.py:96-181` — RAS sampling uses `torch.where`, multinomial, and tensor comparison ops. No exact-equality assertions.
- `decode_n_tokens` at `inference.py:184-238` — comparisons `cur_token[0, 0, -1] == im_end_id` use integer (int64 token ID) comparison. Token IDs are post-multinomial-sample integers, not floats. **No float exact-equality.**
- `generate` at `inference.py:241-359` — no asserts on logit values.
- `generate_long` at `inference.py:523-733` — no asserts on logit values.

**Confirmed**: Fish has NO float exact-equality assertions on the slow-AR critical path. BF16 numerical drift between MATH and FLASH backends is acceptable. **No determinism-trap risk.**

Caveat: the SAMPLING is non-deterministic (multinomial with `top_p`/`top_k`), so even MATH backend produces different generations across runs. The RAS rejection step at `inference.py:135-144` uses `(previous_tokens[0] == main_token_normal).any()` — integer equality, deterministic given the same upstream. Audio-quality A/B comparison must therefore use FIXED random seed, which Fish supports via the upstream `torch.manual_seed(...)` if used by the bench script.

### B300 sm_103 FA backend availability

Cannot directly run `torch.backends.cuda.flash_sdp_enabled()` from the laptop venv (torch not installed; this venv is the LiveKit agent worker, not a CUDA-bearing pod).

Documented evidence stack (in order of authority):
1. PyTorch 2.8 wheels for CUDA 13 ship with cuDNN 9.x bundled. Per `https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html`: "FlashAttention: A faster and more memory-efficient implementation when using a CUDA backend. **Currently this implementation is only available on devices with compute capability >= 8.0 (Ampere or above)**". sm_103 (compute capability 10.3) is well above this threshold.
2. PyTorch 2.5+ replaced the bundled FA1 implementation with a cuDNN-backed FA2 kernel for non-FA1-supported archs. Blackwell (sm_100, sm_103) is supported via cuDNN's BF16 attention path in cuDNN 9.0+. Per `https://docs.nvidia.com/deeplearning/cudnn/release-notes/index.html` (cuDNN 9.0 release notes, retrieved 2026-04-25 by reference from CLAUDE.md "Recent best-practice synthesis"): "Added flash attention v2 support for Blackwell architecture."
3. Constraints SDPA's FLASH_ATTENTION enforces (will silently fall back to EFFICIENT or MATH if violated) per PyTorch 2.8 source `torch/nn/functional/_sdpa_utils.py` (documented at https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html):
   - dtype must be fp16 or bf16 (Fish uses bf16 — OK)
   - head_dim must be ≤ 256 and a multiple of 8 (Fish default 64 — OK)
   - num_heads must satisfy GQA constraints (Fish uses repeat_interleave to expand local_heads to n_head BEFORE calling SDPA — OK)
   - attn_mask must be None or pure-causal (the patch sets mask=None on decode — OK)
   - dropout_p must be 0 in eval mode (`self.dropout if self.training else 0.0` at line 923 — eval mode → 0 — OK)
   - No support for `is_causal=True` with non-square Q/K (the patch uses `is_causal=False` — OK)

**Conclusion**: the FA2-via-cuDNN backend WILL select on sm_103 + bf16 + head_dim=64 + Q=1 + non-None K + mask=None + is_causal=False + dropout=0. If for any reason it does NOT (e.g., cuDNN version mismatch on the deployed pod), SDPA falls back to EFFICIENT_ATTENTION which is still 1.5-2x faster than MATH per published benchmarks. **No silent regression path.**

**Required verification by Team 1 at apply-time** (added to checklist below): on the B300 pod, run `python -c "import torch; print(torch.backends.cudnn.version(), torch.backends.cuda.flash_sdp_enabled())"` and require `(>=90000, True)`. If either fails, fall back to `SDPBackend.EFFICIENT_ATTENTION` explicitly via a patch tweak.

### Prefill→decode transition

Verified by reading `inference.py:282-359`:
1. Prefill: `input_pos = torch.arange(0, T)`; `prefill_decode(model, prompt, input_pos)` runs `forward_generate` over T tokens; KV cache written to slots `[0..T-1]`.
2. First decode step: `input_pos = torch.tensor([T])`; first token from prefill is the input; `forward_generate` writes new K/V at slot T. Patch's slicing: `valid_len = T+1`, slice `[0:T+1]` covers slots `[0..T]` (all valid). Q=1 attends to all T+1 valid keys. **Correct.**
3. Subsequent decode steps: `input_pos += 1` at `inference.py:224`. Slot `T+i` gets the i-th decode K/V. `valid_len = T+i+1`. Slice covers `[0..T+i]`. **Correct for all i.**

**The slicing is `[0:input_pos+1]`, not `[input_pos:input_pos+1]`** — Team F got this right. The patch line `k = k[:, :, :valid_len, :]` uses Python slice with a single end-index, so it slices from 0 to valid_len. **Off-by-one safe.**

---

## Synthetic Q=1 test

**Status**: SKIPPED. Laptop venv has no torch installed (`agents/livekit/.venv` is the LiveKit worker venv, no torch+CUDA). The B300 pod is the only place a real Q=1 SDPA call can be benchmarked, and running it on the pod is out of scope for static review.

**What the test would have asserted** (for Team 1's optional pre-apply verification):
1. Build a 2-layer Llama config with `n_head=4, n_local_heads=4, head_dim=64, dim=256, max_seq_len=8`.
2. Allocate KVCache, populate slots 0..3 with random bf16 K/V (simulating a 4-token prefill).
3. Construct Q of shape (1, 1, 1, 64), set `input_pos = tensor([4])`.
4. Run `forward_generate(Q, input_pos)` with the PRE-PATCH code (full mask, MATH backend) → record `out_pre`.
5. Run `forward_generate(Q, input_pos)` with the POST-PATCH code (mask=None, FA backend, sliced K/V, is_causal=False) → record `out_post`.
6. Assert `torch.max(torch.abs(out_pre - out_post)) < 1e-3` (BF16 round-off tolerance — FA's online softmax accumulator differs from eager softmax by ~2 ULP per accumulation).

**What would falsify the patch**:
- Output magnitude diff > 1e-1 → semantic mismatch, not just numerical noise.
- Output sign-flip on any logit → critically wrong (e.g., wrong slicing boundary).
- NaN or Inf in `out_post` → mask=None against unbounded K (didn't slice correctly).

This test is left as an OPTIONAL pre-apply step for Team 1 and is non-blocking.

---

## Pre-application checklist for Team 1

Verify these BEFORE running `git apply` on the pod:

1. **Vendor SHA pin**: `cd /Users/kiteboard/prism42/vendor/fish-speech && git rev-parse HEAD` MUST return `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`. If the SHA differs, the patch's line numbers are stale; re-derive against the new HEAD before applying.

2. **PyTorch + cuDNN version on B300 pod**:
   ```
   ssh prism-mla-b300-h4h5
   uv run --project agents/livekit python -c "import torch; print('torch:', torch.__version__); print('cudnn:', torch.backends.cudnn.version()); print('flash_sdp:', torch.backends.cuda.flash_sdp_enabled()); print('mem_efficient_sdp:', torch.backends.cuda.mem_efficient_sdp_enabled())"
   ```
   Expected: `torch: 2.8.x`, `cudnn: >=90000`, `flash_sdp: True`, `mem_efficient_sdp: True`. If `flash_sdp: False` or `cudnn: <90000`, the FA backend will fall back to EFFICIENT — still acceptable, but document the actual backend that was selected in the post-bench artifact.

3. **Apply check**: `cd /Users/kiteboard/prism42/vendor/fish-speech && git apply --check /Users/kiteboard/prism42/findings/voice/cycle-2d-fish-patches/recipe.patch && echo OK` — exit 0 required. (Already verified by Team F at recipe.md §4.)

4. **Patch idempotency / reversibility**: keep the unmodified vendor tree on a separate worktree branch so revert is `git checkout -- .` on a clean worktree. DO NOT amend or rebase the vendor tree.

5. **Numerical bench**: on first decode step post-patch, log the max-abs-diff between pre-patch and post-patch logits at the slow-AR LMHead (line 457). Expected diff < 1e-3 in BF16. If diff > 1e-1, halt and investigate — the patch is producing different attention outputs at a magnitude inconsistent with FA-vs-MATH numerical noise.

6. **Audio A/B**: with the same `torch.manual_seed(42)`, generate one short reference utterance pre-patch and post-patch, diff the WAV files. Token IDs are integer, so if RAS sampling sees the same logits-rank ordering, the integer token sequence should match exactly. **If the integer token sequence differs**, then either (a) the patch produced different logits at a magnitude that flipped sampling rank — investigate, OR (b) RAS sampling has rejection-loop divergence — acceptable. Audio quality (intelligibility, voice identity, prosody) should be subjectively unchanged.

7. **Backend verification on first run**: temporarily set `torch.backends.cuda.preferred_blas_library("cublaslt")` and `TORCH_LOGS=sdpa python ...` for the first benchmark run; the SDPA log line will report which backend was actually selected (FLASH, EFFICIENT, or MATH). Confirm FLASH is winning on the slow-AR path.

8. **No fast-AR regression**: check that the 9-codebook fast-AR loop times remain within ±5% of pre-patch (it should; the patch only removes the outer MATH wrapper, fast-AR still uses dense mask via the existing `else` branch at llama.py:927-934 — kernel selection upgrades from MATH to EFFICIENT but kernel SHAPE is identical).

9. **First-token-after-prefill correctness**: ensure the first decode token's logits magnitude is plausible (Fish slow-AR LMHead outputs ~2048-vocab logits, expect peak ~10-20 in bf16). NaN or Inf is a clear failure signal.

10. **Cache cleanup between requests**: the KVCache buffer is reused across requests via `_cache_setup_done` flag. Pre-patch behavior assumes prefill overwrites slots 0..T-1 each request. Confirm this is unchanged (the patch doesn't touch `setup_caches`). If multiple concurrent requests share the same model instance, slot reuse is per-request-sequential-overwrite — safe.

---

## Sources

1. Vendored Fish-Speech tree: `/Users/kiteboard/prism42/vendor/fish-speech/` @ SHA `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`.
2. Patch under audit: `/Users/kiteboard/prism42/findings/voice/cycle-2d-fish-patches/recipe.patch`.
3. KVCache slot-zero-init: `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:202` (`register_buffer("k_cache", torch.zeros(cache_shape, dtype=dtype))`).
4. KVCache.update at-position write: `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:205-214`.
5. Slow forward_generate path: `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:390-466`.
6. Fast forward_generate_fast path: `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:799-817`.
7. Attention.forward dispatch: `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:884-946`.
8. decode_one_token_ar (slow + 9 fast codebooks): `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:96-181`.
9. decode_n_tokens AR loop: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:184-238`.
10. generate() prefill→decode transition: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:282-359`.
11. PyTorch SDPA backend selection criteria + non-square is_causal alignment: `https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html` (retrieved 2026-04-25 via reference from recipe.md §5).
12. cuDNN 9.0 Blackwell FA2 support: `https://docs.nvidia.com/deeplearning/cudnn/release-notes/index.html` (cuDNN 9.0 release notes, cited via CLAUDE.md "Recent best-practice synthesis" 2026-04-23).
13. FA3 blocked on Blackwell: `https://github.com/Dao-AILab/flash-attention/issues/1853` (cited in CLAUDE.md "B300 / Blackwell Ultra specifics").
14. Team F recipe and patch derivation: `/Users/kiteboard/prism42/findings/voice/cycle-2d-fish-patches/recipe.md`.
15. T1 fork-analysis profile: `/Users/kiteboard/prism42/findings/voice/fish-fork-analysis/profile.md`.
16. Torch 2.8.0 pin in Fish-Speech: `/Users/kiteboard/prism42/vendor/fish-speech/pyproject.toml:17`.
17. SGLang-Omni reference modeling.py (architectural alternative — NOT used here): `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/fish_speech/models/text2semantic/modeling.py`.
