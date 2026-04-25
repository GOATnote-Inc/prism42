# E2E Voice Cycle-1 — 2026-04-25 12:36Z

## Verdict: PARTIAL

Fix 1 (`enable_thinking=False`) was a decisive engine-leg win. Fix 2 (caller_spoke gate) wired correctly but inert in the synthetic harness. Headline e2e p95 went up but the new number is honest where the old one wasn't.

## Headline

`publish_end_to_first_returned_audio_ms` **p95 = 7010 ms** (target 1500 ms; FAIL by 5510 ms).

The 4510→7010 ms increase vs the prior Team E run is **methodological, not regression** — Team E's harness was capturing filler/preroll audio as "reply" on 3-4 turns, giving artificially low numbers. With cleaner LLM content this run, those turns now wait for real-content TTS to start after the preroll completes.

## Per-leg deltas vs Team E (`20260425T113808Z`)

| Leg | Team E p50 / p95 | Cycle-1 p50 / p95 | Delta | Note |
|---|---|---|---|---|
| stt_ms (Parakeet) | 31 / 56 | 31 / 43 | -23% p95 | Parakeet stable |
| llm_total_ms | 797 / 803 | **104 / 157** | **-87% / -80%** | Fix 1 decisive win |
| llm_first_token_ms | 133 / 2246 | 182 / 2131 | comparable | filler+say outliers |
| tts_ttfb_ms (Fish) | 1488 / 2627 | 1483 / 2956 | within noise | Fish unchanged |
| publish→first_audio | 3000 / 4510 | 5010 / 7010 | +67% / +55% | clean content vs filler-detect |
| non_empty_reply_audio_count | 10 / 10 | 10 / 10 | parity | both detected reply audio |

## Fix verification

- **Fix 1 (enable_thinking=False, worker.py:358)**: VERIFIED. LLM total p50 dropped 87%, p95 dropped 80%. Reply audio amplitude 22020-25364 (silence ceiling ~500) on every turn. vLLM `generation_tokens_total` advanced ~30k tokens during the run.
- **Fix 2 (caller_spoke gate, worker.py:683-797)**: WIRED, INERT in this test. 0/10 `preroll.skipped_caller_spoke_*` events; 10/10 `preroll.spoken`. The synthetic caller publishes at +6 s while preroll fires at +1-2 s, so the caller never wins the race. The gate would help in real human flow where the caller may interrupt. Recommend keep, not rollback.

## Bottleneck breakdown post-cycle-1

```
LLM leg              ~157 ms  ← FAST (fixed)
Preroll always-on    ~2400 ms ← largest fixed cost
Fish TTFB            ~1500 ms ← second-largest, T1 fork-analysis maps to SDPBackend.MATH
                    ─────────
Floor                ~4000 ms before real-content audio can begin
```

Plus per-load RTF degradation +95% under vLLM contention (T2 finding) compounds the Fish portion when sustained.

## Acceptance gate breakdown

| Gate | Pass? | Evidence |
|---|---|---|
| 10/10 turns produced non-empty assistant content | YES | Fix 1 verified |
| 0 Anthropic API calls | YES | engine_path_attestation in result.json |
| publish→first_audio p95 ≤ 1500 ms | NO | 7010 ms (FAIL by 5510 ms) |
| All 4 services healthy | YES | rollback_status in result.json |

## Rollback status

NOT performed. Both fixes are correct and addressing real failure modes:
  - Fix 1 unblocked the LLM (without it, 0/10 turns produced real replies — Team E was attesting silent failure)
  - Fix 2 is dormant under synthetic load but useful under human-caller flow

Backup at `/opt/prism42/agents/livekit/worker.py.pre-cycle1` retained for emergency rollback.
Phase E env vars untouched. vLLM not restarted. Systemd drop-ins unchanged.

## Recommended cycle-2

Two paths to land e2e p95 ≤ 1500 ms, ranked by smallest-reversible-first:

1. **Drop preroll always-on**: gate ALL preroll on `caller_spoke.is_set()` (always skip if caller is publishing) OR remove the preroll-emit entirely for the demo. One-line worker.py change. Predicted impact: **-2400 ms** → e2e p95 ~4600 ms. Not enough on its own but decisive contribution.
2. **Cartesia Sonic-3 TTS swap**: env flag already wired in `worker.py:368-396` behind `LIVEKIT_TTS_BACKEND=cartesia`. Cartesia published TTFB 200 ms vs Fish 1500 ms. Predicted impact: **-1300 ms** → composes with #1 to ~3300 ms. Still above target but inside industry-comp band.

Combining 1+2 predicts e2e p95 ~3300 ms. To hit ≤1500 ms target we'd also need:
3. **MPS + Fish patches** (T2 + T1 from synthesis.md) — open-source path, multi-day cycle.
4. **Pipecat speculative speech** (T4) — orchestrator-layer win, masks Fish further.

For the Sunday deadline: cycle-2a = drop preroll + Cartesia swap. Cycle-2b (post-deadline) = MPS + Fish patches.
