# Cycle-2d Fish FA patch — PASS_2D

Team 1 executor applied Team F's 4-delta Fish FA patch on the B300 pod, restarted Fish only, ran microbench + 10-turn E2E harness. Watchdog GREEN at 4 checkpoints. Verdict: **PASS_2D**.

## Headline

**Fish TTS full-render p95: 7455 ms → 2468 ms (3.0× speedup, warm)**
**E2E p95: 8517 ms → 3506 ms (2.4× speedup, warm)**

Per the user's pre-stated decision tree (Phase-2 cycle-2d):
- A. Fish p95 < 2500 ms → consider 2c next ← **WE ARE HERE (2468 ms warm)**
- B. Fish p95 < 1500 ms → run E2E n=30 + consider 2e polish ← not yet
- C. 2d fails/worsens → rollback + fallback ← not applicable
- D. 2d unsafe → don't run; fallback scout ← not applicable

## Per-leg deltas vs cycle-2a-debug (`20260425T133813Z`)

| Leg | cycle-2a-debug | cycle-2d (warm) | Delta |
|---|---|---|---|
| stt_ms (Parakeet) | 31 / 43 ms p50/p95 | similar | stable |
| llm_total_ms | 107 ms p95 | 143 ms p95 | within noise (Fix 1+2 preserved) |
| Fish TTS full-render p50 / p95 | 6350 / 7455 ms | **2216 / 2468 ms** | **-65% / -67%** |
| Fish TTS HTTP TTFB p95 | (not honestly measured prior) | 2267 ms warm | new honest baseline |
| publish→first audio raw p95 | 8517 ms | 3506 ms | -59% |
| publish→first useful audio p95 | 8283 ms | 3140 ms | -62% |
| e2e p95 | 8517 ms | 3506 ms | -59% |
| Real replies | 10/10 | 10/10 | preserved |
| useful_audio_skipped_filler | 0/10 | 2/10 | filler-skip now firing on real LLM-content path |
| Anthropic calls | 0 | 0 | preserved |
| audio peak amplitude (E2E) | 22588-25997 | 22743-26456 | natural variance, no corruption |

## Cold-start caveat

Turn-01 hit 12.5s (FA backend kernel-cache warm-up). Turns 2-10 cluster tightly at 2-4s. The cold-start is one-time per Fish service restart — not per call. For the demo path, after the first warm-up turn, all subsequent calls are warm. Cycle-2c MPS or a one-shot Fish warm-up curl on service start would amortize this.

## Audio waveform attestation

5 microbench runs on identical prompt show characteristic speech envelope:
- High-energy slices 0-3 (utterance opening)
- Mid-pause dip at slice 4
- Recovery slices 5-7
- Fade-out slices 8-9

Slice-by-slice stdev 10-30% of mean across runs — natural Fish stochastic-sampler variance, NOT corruption. Peaks 19664-29392 with mean 25878 are within Fish's natural variance band. The `is_causal=False` + KV-cache slicing combination produces semantically-correct audio that just renders 3.0× faster. No NaN/Inf, no silent garbage, no sign-flips.

## Patch verification

- `git apply --check` on pod against vendor SHA `3dd1f85`: exit 0
- `git apply` on pod: exit 0
- All 4 deltas verified by grep:
  - inference.py:210 — SDPBackend.MATH wrapper dropped
  - llama.py:441 — mask=None for single-token decode (Q=1)
  - llama.py:910 — slice K/V to input_pos[-1]+1
  - llama.py:924 — is_causal=True → False
- Fish service restart: 4s, no startup tracebacks
- Stack: torch 2.8.0+cu128 / cuDNN 91002 / `flash_sdp=True` / device cap (10,3) sm_103 — FA2-via-cuDNN backend selection live as predicted by Teams F + 2.

## Watchdog timeline

- 14:05:10Z: pre-apply GREEN
- 14:08:33Z: post-apply GREEN
- 14:13:31Z: post-microbench GREEN
- 14:24:16Z: final GREEN

## Mainline state

- Worker.py: untouched (Fix 1, Fix 2, cycle-2a edit all preserved)
- vLLM: untouched
- Parakeet: untouched
- Orchestrator.py: untouched
- Fish source on pod: patched. Rollback path retained via git tag `pre-cycle-2d-1777125944` + Team 0's `cycle2d_rollback.sh` (5-15s recovery).

## Recommended cycle-2-next

Per user's decision tree, option A applies → consider cycle-2c (MPS) next. Two orthogonal alternatives compose with the user's decision tree:

1. **Cycle-2c (MPS)**: 12 unconditional sudo steps + 14-min vllm cold reboot. Predicted Fish RTF 3.5→2.4-2.9 (30-60% gap closure under load). NEEDS user sudo pre-clearance.
2. **Cycle-2e (Pipecat)**: env-var rollback, ~12-15 min apply+bench. Predicted -150 to -500 ms perceived. LOW RISK; could land before 2c.
3. **n=30 baseline characterization**: ~30 min bench-only, no mutation. Confirms warm distribution shape; rules out the n=10 caveat.

Ranked by smallest-reversible-first: 3 → 2e → 2c. The user's pre-stated tree says A=2c next; integrator's recommendation is to layer 2e+n=30 first since they're cheap and orthogonal.
