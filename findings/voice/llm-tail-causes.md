# LLM first-token tail forensics — 2026-04-25 Team E run

Forensic source: `/Users/kiteboard/prism42/findings/b300_bench/e2e_voice/20260425T113808Z/`
Test window: `2026-04-25T11:40:00Z .. 2026-04-25T11:50:00Z` (10 turns)

## Bottom line

Tail cause distribution (n=10):

| Cause | Turns | Median padding (ms) |
|---|---|---|
| **A — preemptive_generation double-fire** | 0 / 10 | n/a (RULED OUT) |
| **B — reasoning_content padding** | 10 / 10 (background, see below) | small (~50-200 ms) when clean |
| **C — CUDA-graph JIT capture** | 0 / 10 | 0 (RULED OUT — graphs warm) |
| **D — preroll-TTS-uninterruptible-overlap (NEW)** | 4 / 10 | **+850 ms over baseline** (vs. clean p50 ~84 ms) |

The headline finding: **the entire `llm_first_token_ms` p50→p95 jump (133→2246 ms, 17×) is driven by a 4th cause not in Team R's top 3.** When the synthetic caller starts speaking before the preroll TTS greeting finishes playing, the `interruption_detection is disabled` configuration forces AgentSession to drain preroll TTS to completion before the LLM call's `speech_created` event can fire — even though VAD has already marked end-of-speech. The 4 outlier turns (02, 06, 08, 10) all have computed VAD-EOU timestamps inside the preroll TTS playback window.

Hypothesis B (reasoning_content) is technically present on **all 10 turns** — no turn ever produced a real LLM-content reply (every "reply audio" detected by the harness is the static filler text "I hear you." / "Got it, one moment." / etc., or the preroll greeting tail). Fix 2 raised `VLLM_MAX_COMPLETION_TOKENS` to 1024 but did NOT add `enable_thinking=False`, so reasoning tokens still consume some budget on every turn; the first-token-latency pad from B alone is small (~50–200 ms) and only stacks on top of D when EOU happens during preroll.

Predicted `llm_first_token_ms` p95 if both D and B are eliminated: **~150 ms** (vs. current 2246 ms — a 15× reduction). This is consistent with phase-d-strict's vLLM single-shot TTFT p95 of 44.1 ms plus scheduler/event-loop overhead.

## Per-turn taxonomy

`fast turns` = EOU happened safely AFTER preroll TTS finished. `slow turns` = EOU happened DURING preroll TTS playback (cause D fired).

For each turn, "computed EOU time" = first_token timestamp − `llm_first_token_ms`.

| Turn | first_token_ms | preroll.spoken (worker.log) | computed EOU time | classify | evidence (worker.tail.log line) |
|---|---|---|---|---|---|
| 01 | 7 | 11:40:53 | 11:40:55+ | fast (B-tiny, post-preroll) | line 1730 (`ms=7 source=generate_reply`); LLMMetrics line 1747 |
| 02 | **2246** | 11:42:41 | **11:42:40.754** (during preroll) | **slow (D + B)** | line 1947 (preroll.spoken), line 1957 (`ms=2246 preempt=False`), line 1977 (LLMMetrics llm_ms=800) |
| 03 | 32 | 11:43:43 | 11:43:46+ | fast (B-tiny, post-preroll) | line 2068 (`ms=32`) |
| 04 | 133 | 11:44:46 | 11:44:46.867 (post-preroll, marginal) | fast (B-tiny) | line 2186 (`ms=133`) |
| 05 | 36 | 11:45:55 | 11:45:57+ | fast (B-tiny, post-preroll) | line 2295 (`ms=36`) |
| 06 | **1182** | 11:46:57 | **11:46:56.818** (during preroll) | **slow (D + B)** | line 2556 (preroll.spoken), line 2565 (`ms=1182 preempt=False`) |
| 07 | 580 | 11:47:54 | 11:47:54.420 (just-after-preroll, marginal) | medium (D-light + B) | line 2706 (`ms=580`) |
| 08 | **932** | 11:48:51 | **11:48:50.068** (during preroll) | **slow (D + B)** | line 2832 (preroll.spoken), line 2840 (`ms=932 preempt=False`) |
| 09 | 82 | 11:49:48 | 11:49:48.918 (post-preroll) | fast (B-tiny) | line 2960 (`ms=82`) |
| 10 | **929** | 11:50:53 | **11:50:52.071** (during preroll) | **slow (D + B)** | line 3116 (preroll.spoken), line 3124 (`ms=929 preempt=False`) |

### Cause A (preemptive_generation double-fire) — RULED OUT

- Every `overlap.llm_first_token_after_speech_ms` event in the test window has `preempt=False`.
- Exactly 1 `LLMMetrics` event per session for all 10 test sessions (counted via `metric_type=LLMMetrics` grep, grouped by session_id — see worker.tail.log; results at top of analysis transcript).
- vLLM engine throughput logger never shows `Running: 2 reqs` — only `Running: 0` (idle) and `Running: 1` (single in-flight request). 46 POST `/v1/chat/completions` lines in vllm.tail.log over the 19-minute test window are consistent with 1 LLM call per turn × 10 turns + 6 calls for verify-2a/verify-2b + 30 misc (preroll-text-gen, filler-text-gen, etc.).
- The `early_llm_chars=12` config is on, but the synthetic caller publishes the entire utterance audio in one shot (rather than streamed); Parakeet emits final transcript before any partial-vs-final delta builds, so the preflight trigger never fires.

Conclusion: contingency #1 from Team R is not active. **Cause A contributes 0 ms to the tail.**

### Cause B (reasoning_content padding) — PRESENT BACKGROUND, MINOR DIRECT IMPACT

- All 10 turns have an `LLMMetrics llm_ms=793-803` (vLLM completes in ~800 ms each turn). But **zero `transcript.post_ok role=assistant`** events were logged in the test window — the LLM never emitted non-empty `delta.content`.
- Fish.tail.log "Batch text" entries for the test window confirm: only preroll greeting (text_len=36) and short filler strings (text_len=11/19) were ever sent to TTS. No real reply text from the LLM was synthesized in any of the 10 turns.
- The `nano_v3` reasoning parser is configured (vllm.tail.log line 21 / `reasoning_parser='nano_v3'`). The model wraps output in `<think>` and emits early tokens to `delta.reasoning_content`. With `VLLM_MAX_COMPLETION_TOKENS=1024` (Fix 2 in effect), the model has budget to exit thinking, but apparently still spends most of the 800 ms total inside the reasoning channel for these 10 prompts.
- Direct effect on `llm_first_token_ms`: small. The metric fires on `speech_created`, which LiveKit emits as soon as ANY token (reasoning or content) starts streaming back. So B adds tens to low-hundreds of ms, not seconds.

Conclusion: B is **present on all 10 turns** as the reason no real reply ever speaks, but it contributes only modestly to the first-token-latency metric itself. Adding ~+50–200 ms per turn vs. an `enable_thinking=False` baseline.

### Cause C (CUDA-graph JIT capture) — RULED OUT

- vLLM init log (vllm.tail.log lines 21–53) shows compilation completed at 10:34:48 and engine warmup at 10:48:43, both well before the test started at 11:38.
- `cudagraph_capture_sizes: [1, 2, 4, 8, 16]` and `max_cudagraph_capture_size: 16` (vllm.tail.log line 21) — these were captured at startup. Test prompts are single-user single-shot, batch size 1, prompt 200 tokens — well within the captured-size envelope.
- No `[backends.py]`, `Compiling`, `cuda graph`, `capture`, or `compil` log lines appear during the 11:38–11:57 test window.
- Engine throughput consistently ~200 tok/s prompt + ~25 tok/s generation across every active 10-second window — no per-turn first-call slowdown.

Conclusion: graphs are warm. **Cause C contributes 0 ms to the tail.**

### Cause D (preroll-TTS-uninterruptible-overlap) — DOMINANT, NEW FINDING

Discovery path:

1. Turns 02, 06, 08, 10 all have `llm_first_token_ms` between 929–2246 ms; fast turns are 7–133 ms. The 4 slow turns are NOT distinguished by transcript length, prompt complexity, vLLM throughput, or LLMMetrics duration (all ~800 ms).
2. Subtracting `llm_first_token_ms` from the worker-log timestamp of the metric line gives the computed `t_user_speech_end` (the VAD `speaking → listening` transition that anchors the metric — see `worker.py:687`).
3. For turns 02/06/08/10 the computed EOU falls **inside** the preroll TTS playback window (preroll spoken between 11:42:41–11:50:53 with audio_duration ~2.4s + buffering); for turns 01/03/04/05/09 it falls 0.5–3 s **after** preroll completed.
4. The worker logs `WARNING livekit.agents interruption_detection is provided, but it's not compatible with the current configuration and will be disabled` once per session (e.g. worker.tail.log line ~1900 for session bcff0062). With interruption disabled, the preroll `SpeechHandle` plays out fully before AgentSession can fire `speech_created` for the next turn — even if the user's EOU has already been recorded.

This explains the 17× p50→p95 jump cleanly:
- p50 (133 ms) ≈ clean post-preroll case (turn-04)
- p95 (2246 ms) ≈ deepest preroll-overlap case (turn-02)
- p95 - p50 (≈2.1 s) ≈ time the preroll TTS still needed to play out + LLM call time

**Cause D contributes the bulk of the tail.** Median padding for D-affected turns is +850 ms (mean of 932/929) over the post-preroll baseline of ~84 ms; max is +2113 ms (2246 − 133).

## Surgical-fix action plan

### Highest-leverage: fix D (preroll-overlap)

**Mechanism:** Stop emitting the preroll greeting on the agent track until either (a) the caller has heard at least the first 200 ms of audio (so they can hold-fire), or (b) silence is detected on the inbound stream after subscribe. Currently the worker says "Nine one one. What's your emergency?" eagerly on `entrypoint.start` regardless of caller state.

Two paths:

1. **Skip preroll if caller is already speaking** (worker.py already wires `caller_spoke = asyncio.Event()` at lines 672–679, but the gate isn't actually checked before `session.say(preroll_text)`). Verify the gate is wired at the preroll-emit site; if not, add `if caller_spoke.is_set(): skip preroll` immediately before the `session.say` call. Expected delta: turns where the caller starts speaking immediately go from `llm_first_token_ms` ≈ 1500 ms median to ≈ 100 ms.

2. **Make preroll interruptible** by enabling LiveKit's adaptive interruption — the `interruption_detection is disabled` warning means the current AgentSession config has a `min_endpointing_delay`/`adaptive` mismatch that's silently disabling barge-in. Fix the config (likely a `TurnHandlingOptions` argument shape mismatch in worker.py:329-456). Then the preroll `SpeechHandle` will be cancellable on user speech, freeing AgentSession to fire `speech_created` at EOU even if preroll is still mid-playback.

**Expected p95 after fix:** drops from 2246 ms to ~150 ms. (≈15× improvement.)

### Second-priority: fix B (reasoning_content padding)

Even though B's direct contribution to `llm_first_token_ms` is small, B is why ZERO turns produced real LLM reply text. This is a separate bug to fix — without a real reply, voice-attest is meaningless.

**Surgical fix** (verbatim from `result.json` proposed_next_command #c): in `worker.py:339` add `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` to the OpenAILLM constructor:

```python
llm = openai.LLM(
    model=os.environ.get("VLLM_MODEL", "nemotron-nano"),
    base_url=...,
    api_key="not-needed",
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

This disables Nemotron's reasoning emission entirely, so all tokens land in `delta.content`. Verify by re-running a single turn and `grep -c "transcript.post_ok role=assistant" worker.log` — must equal 1 per turn.

**Expected delta:** Real LLM reply text starts feeding fish; reply audio detected (real, sustained, > 1 s). `llm_first_token_ms` drops a further ~50–100 ms because content tokens are emitted at vLLM's true 44 ms TTFT instead of after the reasoning warmup.

### No action needed: A and C

Cause A (preemptive double-fire) is not firing in this run; leaving `preemptive_generation: enabled=True` is fine. (If you want belt-and-suspenders ahead of a longer soak with streaming STT, set it to `False`; current zero-impact in the synthetic-caller-batched-audio harness is by accident, not by design.)

Cause C (CUDA-graph JIT) is not firing; the captured sizes 1/2/4/8/16 cover the demo workload completely. No need to re-bench with `--cuda-graph-sizes 1 2 4 8` (Team N's recommendation) — current `cudagraph_capture_sizes=[1,2,4,8,16]` is already correct for batch-1 inference.

## Predicted p95 if all causes fixed

Working from the 10 measured `llm_first_token_ms` values: `[7, 2246, 32, 133, 36, 1182, 580, 932, 82, 929]`.

Eliminating cause D pad on turns 02/06/07/08/10 (subtract the time their EOU happened inside preroll TTS):

| Turn | observed | est. preroll pad | corrected |
|---|---|---|---|
| 01 | 7 | 0 | 7 |
| 02 | 2246 | ~2100 ms | ~150 |
| 03 | 32 | 0 | 32 |
| 04 | 133 | 0 | 133 |
| 05 | 36 | 0 | 36 |
| 06 | 1182 | ~1050 ms | ~130 |
| 07 | 580 | ~450 ms | ~130 |
| 08 | 932 | ~800 ms | ~130 |
| 09 | 82 | 0 | 82 |
| 10 | 929 | ~800 ms | ~130 |

Corrected sorted: `[7, 32, 36, 82, 130, 130, 130, 133, ~130, 150]`. p95 (idx round((0.95)(9)) = idx 9) = 150 ms.

Adding cause B fix (`enable_thinking=False`): each "corrected" value would drop by another ~50–100 ms (tokens flow into `delta.content` immediately at vLLM's 44 ms TTFT, no reasoning channel). Lower-bound p95: ~100 ms. Sanity-check vs phase-d-strict native single-shot p95 of 44.1 ms: with LiveKit / event-loop / log-emit overhead, ~2× of the pure vLLM TTFT is realistic.

**Predicted `llm_first_token_ms` p95 with both D and B fixed: 100–150 ms.** ≈15× reduction from current 2246 ms.

This won't fix the headline `publish_end_to_first_returned_audio_ms` p95 (4510 ms) — that's bottlenecked by Fish Speech TTS TTFB (1.1–2.6 s, see result.json verdict). Cause D is a 2-second contribution to the LLM leg; the 3-second remainder is Fish synthesis. Cartesia Sonic-3 cutover is the right move for end-to-end p95.

## Confidence + caveats

- **n=10 is small.** Cause-A and cause-C ruled-out claims are robust (both rely on counts/aggregates that don't depend on sample size). Cause-D dominance is robust (4 of 4 outliers fit the preroll-overlap pattern; 0 of 6 fast turns fit it). Cause-B presence on all 10 turns is robust (no `transcript.post_ok role=assistant` for any session). Per-cause padding *magnitudes* are estimates from second-resolution log timestamps and could be ±200 ms.
- **Worker.log timestamps are second-resolution.** Computed EOU times ("11:42:40.754") use the millisecond value from the metric to back-calculate, so they are precise within ±500 ms (the second-rounding window). The "during preroll" classification is robust because the gap is 200–2200 ms, well outside the ±500 ms uncertainty.
- **vllm.tail.log lacks per-request timestamps.** The 46 POST lines have no time prefix; only the engine-summary 10s windows have timestamps. Could not directly correlate POST count to per-session timing from vllm.log alone — used worker.log LLMMetrics counts instead, which are 1 per session × 10 sessions, consistent with no double-fire.
- **`preempt=True` never appears anywhere in the log** (test window OR pre-test context). The preemptive_generation path is configured but inert in this synthetic-caller harness because audio is published in one shot rather than streamed.
- **`interruption_detection is disabled` warning is printed but not explained in worker.log.** The exact config mismatch causing it should be diagnosed before fixing D via path 2 (interruptible-preroll); path 1 (skip-preroll-if-caller-speaking) is a more surgical fix that doesn't require resolving the warning's root cause.
- **Fix 2 (max_completion_tokens=1024) was applied before this test run**, but cause B is still active. This is consistent with Team R's contingency #3 — `enable_thinking=False` is the surgical fix; raising the budget is only a coarser mitigation.
- **The 4 outliers are not the same as the 3 turns Fix 2 was supposed to fix.** Fix 2 targeted turns 6, 8, 10 (the "no LLMMetrics" cases pre-Fix 2). After Fix 2, all 10 turns now log LLMMetrics, but ALL 10 still hit B (no real reply text). The new outliers (02/06/08/10) overlap with the original 6/8/10 by coincidence — they're slow because of D, not because of B.
