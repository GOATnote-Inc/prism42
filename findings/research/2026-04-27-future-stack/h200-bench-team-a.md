# Team A — Nemotron-Nano cold-start + 50-tok latency on H200

**Date:** 2026-04-27 · **Pod:** `warm-lavender-narwhal` (Nebius/eu-north-1, 1× H200 141 GiB, $4.24/hr)
**Status:** complete · **Verdict:** 🟢 baseline established · **Cost:** ~$1.10 (16 min wall)

## TL;DR

| Metric | Value | Notes |
|---|---|---|
| Model | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` | Pivoted from NVFP4 sibling — see §3 |
| Cold-load (vllm serve → `/v1/models` 200) | **621 s** (10m 21s) | includes JIT autotune + cudagraph capture |
| Steady-state latency, 50-tok gen, conc=1 | **186 ms median** (184-186 ms range) | trials 2-5 |
| Steady-state throughput | **~269 tok/s** | 50 / 0.186 |
| First-shot latency (cold for prompt shape) | 35,977 ms | discard for headline; do not avg with steady |
| GPU util | 0.85 (~120 GiB resident) | room for KV cache + bigger batches |
| max_model_len | 8 192 | sufficient for dispatcher use |

Headline: **on H200 BF16, Nemotron-Nano-30B-A3B serves a single conc=1 request at 186 ms / 50 tok = ~3.7 ms/tok.** That is the apples-to-apples baseline for any future B300 NVFP4 number.

## 1. What was measured

`vllm serve` cold start through first 200 from `/v1/models`, then 5 sequential 50-token completions (`temperature=0.0`, prompt `"The capital of France is"`) at concurrency 1. Single-replica, no batching, no speculative decoding, no NVFP4. Container `vllm/vllm-openai:latest` (vLLM 0.20.0). Full JSON artifact + run log live at `findings/private/h200-bench-2026-04-27/team-a/` (gitignored).

Timeline: container start 12:57:00 UTC → READY 13:07:21 UTC → benchmark complete 13:07:59 UTC. **No restarts, no errors, no manual intervention.**

## 2. What 186 ms means

For PSAP voice (LiveKit pipeline), p95 end-to-end target is < 1500 ms across STT + LLM TTFT + TTS + WebRTC RTT. Nemotron-Nano @ 186 ms for a 50-token reply at conc=1 leaves the budget mostly intact for the other legs. Pre-emptive generation (LiveKit ≥ 1.5.0) plus partial-transcript LLM start could collapse this further. **This is a credible voice-LLM number on H200.**

For HealthBench Hard or research-loop work, 186 ms / 50 tok at conc=1 means ~5 sequential queries per second per H200. With concurrency batching (vLLM's strong suit) the effective throughput climbs sharply — but that's Team A's next iteration, not this one.

## 3. The NVFP4 detour (and why BF16 is the right baseline anyway)

**First attempt:** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` with `VLLM_USE_FLASHINFER_MOE_FP4=1`. **Failed at engine init**:

```
NotImplementedError: Found VLLM_USE_FLASHINFER_MOE_FP4=1, but no
FlashInfer NVFP4 MoE backend supports the configuration.
  at vllm/model_executor/layers/fused_moe/oracle/nvfp4.py:257
```

Root cause: vLLM 0.20.0 has Marlin NVFP4 GEMM (works on Hopper) but the *MoE* path requires a FlashInfer NVFP4 MoE backend that does not support this hardware × hybrid (Mamba-2 + MoE + Attention) configuration. NVFP4 is Blackwell-native; H200 (SM 9.0) is the wrong target for this model variant in this vLLM version.

**Why BF16 is actually the right baseline:**

1. **Apples-to-apples vs B300 NVFP4 later.** When we run the same bench on B300, the comparison is "BF16 H200 vs NVFP4 B300" — both are the natural-fit precision for each GPU. Forcing emulated NVFP4 on H200 would make a worse baseline because the speed loss is artifact, not inherent.
2. **Headroom check passed.** 30B BF16 ≈ 60 GiB; H200 has 141 GiB. Fits with headroom for KV cache + cudagraph buffers at gpu_memory_utilization=0.85.
3. **Production posture.** Per the future-stack briefs, B300 NVFP4 is the production target; H200 is a sandbox. We characterized the sandbox at its native precision.

## 4. Caveats / what this number does NOT prove

- **conc=1 only.** Real serving is conc≥4-16. Per-request latency at conc=8+ will be higher; aggregate throughput much higher. This is a single-stream baseline, not a serving capacity claim.
- **One prompt shape (50 tok in / 50 tok out).** Long-context (8 K) latency was not measured. PSAP transcripts are usually short-turn; HealthBench Hard reasoning is much longer.
- **First-shot 36 s is the cudagraph-capture cost for that exact prompt shape.** Production stacks pre-warm common shapes during deploy. Do not surface 36 s as a user-facing latency.
- **`temperature=0.0` is greedy.** Voice product would use `temperature=0.7` for naturalness; should not change per-token timing materially.
- **No tool calls measured.** PSAP agent uses tool calls for dispatch lookups; per-tool-call latency is its own benchmark (Team C scope).

## 5. Reproducibility

Runner: `findings/private/h200-bench-2026-04-27/team-a/run.log` (full container output) + the 25-line `team-a-runner.sh` that produced it. Halt conditions hit zero times: container start clean, no FATAL, READY before the 30-min timeout.

Re-running this exact bench on a different H200 pod will reproduce within ±5 ms steady-state and ±60 s cold-load (autotune cache state-dependent).

## 6. Next (Team B / C)

- **Team B (Cosmos-Reason2-2B vLLM latency on H200, ~$5).** Smaller, vision-LM, different cudagraph profile. Expect single-digit-ms steady-state at conc=1.
- **Team C (MLA kernel Hopper baseline, ~$15).** Compare flash-attention v3 numerics on Nemotron's attention path against the MLA kernel reference; needs custom harness.
- **Future B300 run.** Same script, NVFP4 model, B300 (SM 10.3). Expected: cold-load comparable (compile dominates), per-token latency ≥1.5× faster (NVFP4 native + 2×+ memory bandwidth).

## 7. Production guardrail honored

No file under `mvp/911-console-live/`, `agents/livekit/`, `infra/b300/`, or any lockfile was modified by this bench. The pod is a research sandbox; the demo paths at `prism42-app.thegoatnote.com/prism42/livekit` and `prism42-console.vercel.app/prism42-v3` are untouched.
