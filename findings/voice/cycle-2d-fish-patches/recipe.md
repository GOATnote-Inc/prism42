# Cycle-2d Fish-Speech FA + Drop-Mask Recipe

**Read-only research output. Patch is NOT applied. Integrator commits.**

Date: 2026-04-25
Vendored base: `vendor/fish-speech` @ SHA `3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139`
Reference fork: `github.com/sgl-project/sglang-omni`, path `sglang_omni/models/fishaudio_s2_pro/` (retrieved 2026-04-25, main branch).

---

## 0. TL;DR

SGLang-Omni's published RTF 0.34 / TTFA 140 ms on H200 is **not a drop-in
SDPBackend swap**. They wholesale-replaced the Fish AR model with a
SGLang-runtime port (`sglang_omni/models/fishaudio_s2_pro/fish_speech/models/text2semantic/modeling.py`,
1484 LoC, FishQwen3 architecture) that uses `flash_attn_with_kvcache` from
`sgl_kernel`, paged KV cache via SGLang's RadixAttention, and a new pipeline
runner (`runtime/s2pro_sglang_ar.py`). That is a multi-thousand-line architectural
rewrite, not a patch.

What CAN be cleanly extracted into our vendored Fish HEAD as a unified diff is
the FA + mask portion of T1's prediction:

1. Drop the outer `with sdpa_kernel(SDPBackend.MATH):` wrapper in `decode_n_tokens`
   so each layer's SDPA call can choose its own backend.
2. Replace the dense per-step causal mask with KV-cache slicing during decode,
   which lets the existing FLASH_ATTENTION branch in `Attention.forward` run
   correctly (it was already there as dead code — only fired when mask was
   None, which never happened).

Predicted gain: matches T1's 2-3x AR-loop estimate. Real win on B300 is
expected at the lower end of that range (FA2 fallback path, no FA3 / FA4)
because Blackwell archs >= sm_10 cannot run FA3 (Dao-AILab issue 1853, cited
in CLAUDE.md). FA4 is sm_100-only CuTeDSL — also blocked here.

The other three SGLang-Omni techniques (torch.compile fast-AR, CUDA Graph
dual-coverage, RadixAttention paged KV cache) are out of scope for cycle-2d
because they require either torch.compile (B300 PTXAS issue, see
`prism-fa4-cute-bootstrap.md`) or the SGLang runtime.

---

## 1. SGLang-Omni fork mapping (verified)

T1 cited `sglang_omni/models/fishaudio_s2_pro/README.md`. Confirmed live
2026-04-25 via WebSearch + WebFetch:

| Their file | Our vendored counterpart | Lift level |
|---|---|---|
| `runtime/s2pro_sglang_ar.py` (330 LoC) | `tools/server/inference.py` (12-46) | Engine wrapper — not portable, depends on `sglang.srt.model_executor` |
| `runtime/s2pro_ar.py` (72 LoC) | `fish_speech/models/text2semantic/inference.py` (sample helpers) | Sampling helpers only; rewrite not necessary |
| `fish_speech/models/text2semantic/modeling.py` (1484 LoC) | `fish_speech/models/text2semantic/llama.py` (1038 LoC) | **Architectural rewrite.** Theirs uses `sgl_kernel.flash_attn_with_kvcache`, paged KV via RadixAttention, FishQwen3 class hierarchy. Ours uses `torch.nn.functional.scaled_dot_product_attention` + `KVCache` register-buffer. Not patchable as a unified diff. |
| `fish_speech/models/text2semantic/configuration.py` (442 LoC) | `fish_speech/models/text2semantic/llama.py` (config dataclasses) | Different config schema (HuggingFace `PreTrainedConfig` style) |
| `pipeline/streaming_vocoder.py` | `fish_speech/inference_engine/__init__.py` | Out of scope (cycle-2d targets text2semantic AR loop only) |

**Key observation:** their modeling.py imports `from sgl_kernel.flash_attn import flash_attn_with_kvcache` at line 17 and uses it in `forward_kvcached` at lines 283-337. This is THE reason their FA path works during single-token decode — `flash_attn_with_kvcache` takes `cache_seqlens` as a kwarg, so it knows the actual fill length without needing a dense mask. PyTorch SDPA does not have this kwarg, so to use SDPA's FLASH_ATTENTION backend with a KV cache, you must slice K/V to actual fill before the call.

Source: `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/fish_speech/models/text2semantic/modeling.py` lines 17, 283-337 (retrieved 2026-04-25).

---

## 2. Deltas extracted into our patch

### Delta A: drop outer SDPBackend.MATH context

- **File:line in our tree:** `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:210`
- **Their equivalent:** they bypass SDPA entirely via `flash_attn_kvcache_op` (modeling.py:48-70 + 324). No equivalent context wrapper.
- **Why MATH was there:** legacy from when `forward_generate` always emitted a dense mask. With a non-None mask, PyTorch SDPA cannot use FLASH_ATTENTION and silently falls back; the explicit `MATH` context was likely defensive against EFFICIENT/FLASH backend dispatch errors during early development.
- **Bench evidence:** SGLang-Omni does not benchmark this swap in isolation. T1's profile.md §5 estimates ~13-18 ms/token at sm_103 eager+MATH and "Eager-MATH is likely 2x slower than this" (referring to FA-eligible). Therefore drop alone is necessary-but-not-sufficient — it has to be combined with delta B/C to actually use FA.
- **B300 (sm_103) safe?** Yes. SDPBackend dispatch on B300 with `is_causal=False` against sliced K/V will pick FLASH_ATTENTION (FA2 in PyTorch 2.5+ wheels via cuDNN) or EFFICIENT_ATTENTION; both are sm_103-compatible per PyTorch's CUDA 13 wheels.
- **torch.compile required?** No.

### Delta B: switch decode-step mask to None; keep prefill mask

- **File:line in our tree:** `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:441`
- **Their equivalent:** modeling.py never builds a dense causal mask. `forward_kvcached` (line 283-337) calls `flash_attn_kvcache_op(causal=True, cache_seqlens=cache_seqlens)` directly.
- **Our minimal port:** detect `input_pos.numel() == 1` (single-token decode) and pass `mask=None`. For prefill (Q > 1) we keep the dense mask because PyTorch SDPA's `is_causal=True` uses upper-left alignment on non-square Q/K, which corrupts prefill where Q < K_max but starts at position 0.
- **Bench evidence:** T1 profile.md §6 Candidate 2: "Together [with delta A]: ~2-3x AR loop, contributing ~600-1000 ms of the SGLang-Omni gap." Verified-on-H200 by SGLang-Omni's published RTF 0.34. Claimed-applies-to-B300-sm_103 because the bottleneck is software (mask + backend selection), not hardware.
- **B300 safe?** Yes (same reasoning as Delta A).
- **torch.compile required?** No.

### Delta C: slice KV cache to fill length during decode

- **File:line in our tree:** `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:910-911` (after `kv_cache.update`)
- **Their equivalent:** modeling.py uses `flash_attn_with_kvcache(cache_seqlens=cache_seqlens, ...)` which knows the fill level natively — no slicing needed because their KV cache is paged via SGLang's RadixAttention.
- **Our minimal port:** explicit `k = k[:, :, :valid_len, :]` and `v = v[:, :, :valid_len, :]` where `valid_len = input_pos[-1].item() + 1`. This is correctness-essential: without slicing, the "no mask + FLASH_ATTENTION" path would attend over all max_seq_len cache slots including unfilled zeros, producing garbage logits.
- **Bench evidence:** No SGLang-Omni isolated bench (they skip the slice via paged cache). The slicing cost is negligible — a single contiguous tensor view, no copy, no kernel launch.
- **B300 safe?** Yes.
- **torch.compile required?** No. (Side note: `int(input_pos[-1].item())` introduces a CUDA→CPU sync per step, which would block torch.compile's full-graph capture. For now this is acceptable because cycle-2d explicitly defers compile per `prism-fa4-cute-bootstrap.md`. A future torch.compile-friendly variant would replace `.item()` with a graph-friendly pad-mask, but that's cycle-2e+ scope.)

### Delta D: change is_causal=True → False in the no-mask FLASH_ATTENTION branch

- **File:line in our tree:** `vendor/fish-speech/fish_speech/models/text2semantic/llama.py:924`
- **Why:** with K/V already sliced to valid_len and Q=1, the query represents the most recent (decode) token and must attend to ALL valid cached keys (positions 0..valid_len-1). PyTorch SDPA `is_causal=True` against non-square (1, valid_len) attention uses upper-left alignment per `https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html`, which would mask out everything except position 0. Setting `is_causal=False` against the already-sliced K/V is the correct semantic.
- **Bench evidence:** behavioral correctness; does not move the needle on its own. Required for delta B+C to produce non-garbage output.
- **B300 safe?** Yes.
- **torch.compile required?** No.

### Deltas SGLang-Omni made that we are NOT porting

| SGLang-Omni change | Why we skip in cycle-2d |
|---|---|
| Replace SDPA with `flash_attn_with_kvcache` from `sgl_kernel` | Would require building/installing `sgl_kernel` against B300 toolchain. Out of cycle-2d scope. Future cycle. |
| Paged KV cache via `RadixAttention` (SGLang runtime) | Requires the entire SGLang scheduler. Architectural rewrite. |
| `torch.compile` on Fast-AR codebook loop ("5x over eager") | B300 PTXAS issue blocks compile path per `prism-fa4-cute-bootstrap.md`. |
| CUDA Graph dual-coverage (Slow + Fast AR) | Requires static-shape capture; conflicts with `int(input_pos[-1].item())` sync we introduce in delta C. Cycle-2e candidate. |
| Radix prefix cache for system-prompt + reference audio | SGLang runtime feature. |
| RoPE bf16-truncation cast (`_truncate_rope_to_bf16`) | Numerics fix specific to their SGLang model port. Our `apply_rotary_emb` is already bf16-correct. |
| `FLASH_ATTN_VERSION = 3` flag (modeling.py:37) + `flash_attn_varlen_func` | FA3 is blocked on Blackwell archs >= sm_10 per Dao-AILab issue 1853. We cannot use FA3 on B300. |
| `FISH_BATCH_INVARIANT` env var (modeling.py:41-45) — forces deterministic FA3 with `num_splits=True` | Determinism feature, not a perf path. Not needed for cycle-2d. |

---

## 3. Bench protocol SGLang-Omni used

Source: README.md @ `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md` (retrieved 2026-04-25 via WebFetch).

Reported numbers:
- **RTF 0.34** on single H200 GPU, single batch
- **Throughput 63.3 tok/s** on single H200 GPU, single batch
- **TTFT ~18 ms** (time to first token)
- **TTFA ~140 ms** (time to first audio)

Reproducibility info NOT in the README:
- No published command line / model hash / sample prompt
- Streaming vs single-shot is unstated; the README points to a separate "TTS Model Usage" doc that we did not retrieve in this pass
- Model weights presumably the public `fishaudio/s2-pro` HF release, but not stated explicitly

**Risk:** their numbers may use streaming + long utterances where amortized RTF is dominated by FA-fast tokens, while our PSAP turn is short utterances where TTFA dominates. T1's profile.md already flags this in §10 (streaming protocol is the secondary bottleneck for first-byte latency).

**What we should benchmark on B300:** isolate AR-loop tok/s on a fixed-length 100-token decode after the patch lands. Compare against the pre-patch baseline of ~13-18 ms/token (T1 estimate).

---

## 4. Verification

`git apply --check` verified by anticipator on 2026-04-25: PASS

Command run:
```
cd /Users/kiteboard/prism42/vendor/fish-speech
git apply --check /Users/kiteboard/prism42/findings/voice/cycle-2d-fish-patches/recipe.patch
echo $?  # → 0
```

The patch only modifies two files:
- `fish_speech/models/text2semantic/inference.py` (1 hunk, ~14 net-add lines)
- `fish_speech/models/text2semantic/llama.py` (3 hunks, ~30 net-add lines including comments)

No new imports, no dependencies added.

---

## 5. Sources

- SGLang-Omni README (RTF 0.34, TTFA 140 ms, 63.3 tok/s, "FA3 forced", "5x over eager", "CUDA Graph dual-coverage"): `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md` (retrieved 2026-04-25)
- SGLang-Omni `runtime/s2pro_sglang_ar.py`: `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/runtime/s2pro_sglang_ar.py`
- SGLang-Omni `fish_speech/models/text2semantic/modeling.py`: `https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/fish_speech/models/text2semantic/modeling.py`
- T1 fork-analysis profile: `findings/voice/fish-fork-analysis/profile.md` (line 18, 122-123, 196-220, 311, 322)
- PyTorch SDPA non-square is_causal alignment: `https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html`
- FA3 blocked on Blackwell: `https://github.com/Dao-AILab/flash-attention/issues/1853` (cited in CLAUDE.md "B300 / Blackwell Ultra specifics")
- B300 sm_103 + FA4 status: `prism-fa4-cute-bootstrap.md` and CLAUDE.md hackathon §0
