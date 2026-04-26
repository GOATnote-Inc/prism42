# Recommendation — Pattern 2 (Fallback) + Pattern 6 (Critic) shipped together

Team B, cycle-2B, 2026-04-26. Confidence: high. Estimated implementation cost: ~150 LoC, ~6 h including verification.

## TL;DR

**Ship Pattern 2 (Fallback) on the hot path. Ship Pattern 6 (Critic) off the hot path. Default OFF behind two independent env flags. No other Claude integration in this hackathon.**

This is the only combination that:

1. Preserves the user's "voice still sounds fantastic" verdict — Nemotron + response_gate + Fish handle every steady-state turn at the existing latency.
2. Touches the user's actual complaint — "caller direct questions ignored, phantom-turn cascading, contradiction-blind repetition" — by adding Claude as a backstop **only on the turns where the existing validators flag failure**. The remaining 90%+ of turns never go remote.
3. Adds **zero hot-path latency** for the critic, while building the regression-detector substrate the user will need next week.
4. Spends well under the remaining $280 cap (projection in `cost-projection.md`: $0.30-$8/day at expected demo volumes).
5. Falls back cleanly if Claude is down — the response_gate template and the FAST_DISPATCHER_SYSTEM_PROMPT path are both already wired.

## Why not the other patterns

- **Pattern 1 (Cascade).** +600 ms minimum per turn destroys the <1.5 s budget. Killed.
- **Pattern 3 (Specialist).** Strong long-term play, but the FSM's intent classifier is the very thing the regression bugs (Team R3's lane) are mistuning right now. Adding Claude routing on top of an unstable classifier ships the bug + the cost. Defer to cycle-2C after Team R3 lands.
- **Pattern 4 (Parent).** This is exactly what `orchestrator_full.py` did and was archived for being 14-20 s end-to-end. Re-introducing it before solving streaming-the-plan-while-Nemotron-renders is a regression.
- **Pattern 5 (Ensemble + judge).** Requires `max(Nemotron, Claude)` on every turn. Adds 600 ms median; net latency loss to gain provider redundancy we don't need yet.
- **Pattern 7 (Distillation collector).** Real value but pays back over weeks (next Nemotron checkpoint). Out of scope for this hackathon.

## Specifics for prism42

### Where the fallback hooks in

In `orchestrator.py:FsmDispatcherAgent.on_user_turn_completed`, **after** the existing response_gate decision and **only on the LLM-fallthrough path** (lines 451-466). The hook:

1. The response_gate's existing 20/21 deterministic templates fire first — unchanged.
2. On the 1/21 LLM path (REPROMPT or future LLM intents), the existing `update_instructions(...)` runs and Nemotron streams.
3. Worker.py post-LLM hook records the dispatcher utterance into the FSM's anti-repetition buffer.
4. **NEW:** if `PRISM42_ENABLE_CLAUDE_BRAIN=1` AND the recorded utterance fails one of three checks (gendered pronoun without commit, repeated phrase, exceeds 14-word cap), the orchestrator:
   - cancels Fish playback if it has not yet begun,
   - issues a single `claude_brain.regenerate(...)` call with a 500 ms timeout,
   - on success, replaces the queued utterance and ships the Claude rewrite to TTS,
   - on timeout / 5xx / 429 / refusal: ships the original Nemotron output (Fish was already buffering it; the validator failure is logged but speech proceeds).

The decision to actually wire the regenerate path post-Fish-buffer-but-pre-playback is a separate ship; for cycle-2B the trigger condition is conservative — **only fire the Claude call when the Nemotron output is rejected by the existing validators**. That keeps p50 latency identical to today.

### Where the critic hooks in

Same `on_user_turn_completed`, after the LLM stream finishes and the dispatcher utterance is final, **as an `asyncio.create_task(...)`** alongside the existing safety-monitor / ohca-detector / intent-verifier triplet (specialists.py §206-323, worker.py §786 wiring). The critic:

1. Receives `(caller_text, dispatcher_reply, intent.value, transcript_tail)` via the same SessionStore handle the other evaluators use.
2. Calls Sonnet 4.6 `messages.create(...)` with a JSON-output rubric (5 booleans + a 0-1 confidence scalar): `repeats_prior_phrase`, `gendered_without_commit`, `ignored_caller_question`, `cpr_unsafe`, `out_of_role`, `confidence`.
3. Posts results to `state.SessionState.alerts` and emits a structlog `critic.score` event.
4. Never blocks the voice path — already in `create_task`, will be reaped at session close like the rest.

### Trigger condition

| Path | Condition | Latency-budget hit |
|---|---|---|
| Fallback (hot) | `PRISM42_ENABLE_CLAUDE_BRAIN=1` AND validator failure on Nemotron output AND fish_buffer_not_yet_played | +500 ms hard ceiling, <10% of turns |
| Critic (off-path) | `PRISM42_ENABLE_CLAUDE_CRITIC=1` AND turn complete | 0 ms |

Both default OFF. Either flag alone activates only its branch. Neither flag affects the response_gate template path (still 20/21 turns).

### Latency-budget impact (with cited numbers)

| Source | Number | Reference |
|---|---|---|
| Nemotron TTFT (B300) | ~50 ms | worker.py §674 comment ("vLLM 0.20 server ... 15-30 ms TTFT") |
| Nemotron full-reply | ~313 tok/s | CLAUDE.md §0 hackathon stack notes (cycle context) |
| Sonnet 4.6 TTFT | ~600 ms | KB 08 §7 ("Sonnet 4.6 hits ~600ms TTFT"), Anthropic Streaming docs do not publish a TTFT SLA |
| Opus 4.7 TTFT (short prompt) | ~3-7 s | specialists.py §369-373 ("Opus 4.7 was ~7s — caller hung up before response") |
| End-to-end target | p95 < 1.5 s | CLAUDE.md §0 |

**Hot-path math when fallback fires:** Nemotron 50 ms TTFT + Sonnet 4.6 regenerate budget 500 ms hard timeout = +500 ms worst case. Fires <10% of turns. Average impact +50 ms. p95 shifts from ~1.4 s to ~1.45 s — still inside budget.

**Why Sonnet 4.6 not Opus 4.7 for the fallback.** Opus 4.7's 3-7 s TTFT is incompatible with a 500 ms hot-path timeout. Sonnet 4.6 is the only option that fits. **Opus 4.7 is reserved for the critic** where the latency does not matter and Opus's stronger instruction-following on the rubric is worth the premium.

### Cost projection (full numbers in cost-projection.md)

- **Fallback** (Sonnet 4.6, 5-10% of turns hit Claude, 150 in / 300 out): $0.0003-0.0008 per call avg.
- **Critic** (Opus 4.7, every turn, 200 in / 100 out scored): $0.0035 per call.
- **Together at 1k turns/day:** $0.30 (fallback) + $3.50 (critic) ≈ **$4/day** if critic runs 100%.
- **At a 10% critic sample:** **$0.65/day**.
- Budget remaining ($280 cap minus prior spend) covers months at this rate.

### Default-OFF env-flag pattern (mandatory)

```bash
# Hot-path fallback. Default OFF.
PRISM42_ENABLE_CLAUDE_BRAIN=0      # default; no hot-path Claude call
PRISM42_ENABLE_CLAUDE_BRAIN=1      # enable fallback regenerate

# Off-path critic. Default OFF.
PRISM42_ENABLE_CLAUDE_CRITIC=0     # default; no critic
PRISM42_ENABLE_CLAUDE_CRITIC=1     # enable async scoring

# Per-second hard ceiling on Claude hot-path budget.
PRISM42_CLAUDE_BRAIN_TIMEOUT_MS=500   # default 500
PRISM42_CLAUDE_BRAIN_MODEL=claude-sonnet-4-6   # default; never override to opus on hot path

# Critic config.
PRISM42_CLAUDE_CRITIC_MODEL=claude-opus-4-7    # default
PRISM42_CLAUDE_CRITIC_SAMPLE_RATE=1.0          # default 100%; lower to e.g. 0.1 to cut cost 10x
```

### Failure-mode mitigation

| Failure | Mitigation |
|---|---|
| Anthropic API 429 throttle | Single retry inside the timeout budget; if still failing, ship Nemotron output. No exponential backoff on hot path. |
| Anthropic API 5xx | Identical: ship Nemotron output, log `claude_brain.api_5xx`. |
| Anthropic SDK timeout | Caught explicitly in `claude_brain.py`'s `asyncio.wait_for`; surfaced as `claude_brain.timeout`. |
| Sonnet 4.6 medical refusal (~0.18%) | Output regex rejects "I am an AI" / "dial 911" / "I cannot" / "as a language model" / "real emergency"; on match, drop the rewrite and ship Nemotron output. |
| ANTHROPIC_API_KEY missing | Module-level lazy import + key check; if missing, the flag self-disables and emits a single warn log. Worker continues on Nemotron-only. |
| Opus 4.7 sampler-param 400 | The skeleton's `messages.create(...)` signature explicitly omits `temperature`, `top_p`, `top_k`, `budget_tokens` per CLAUDE.md §8. |
| Critic eats hot-path memory | Critic uses bounded async queue (max 10 in flight); spillover events drop with a `critic.dropped` log line. |

### Ship sequence

1. Land `claude_brain.py` skeleton (no orchestrator wiring) — 1 commit.
2. Wire critic-only path in `worker.py` `on_user_turn_completed` (mirroring the existing safety-monitor pattern) behind `PRISM42_ENABLE_CLAUDE_CRITIC=1`. Ship as a separate commit.
3. Wire fallback path in `orchestrator.py` `FsmDispatcherAgent.on_user_turn_completed` behind `PRISM42_ENABLE_CLAUDE_BRAIN=1`. Ship as a separate commit.
4. Each commit verified with `make verify-all` per CLAUDE.md §4.

The first two land safely without touching the hot path; only step 3 is hot-path additive.

### Out of scope for cycle-2B (defer)

- Specialist routing (Pattern 3) — depends on Team R3's intent-classifier fix landing first.
- Distillation collector (Pattern 7) — wait until physician review queue exists.
- Migration of existing safety-monitor / ohca-detector / intent-verifier specialists to use prompt caching (`cache_control: ephemeral`) — separate ship, would cut critic cost ~50% but reduces this commit's surface.
- Anthropic Bedrock / Vertex routing — not requested.
