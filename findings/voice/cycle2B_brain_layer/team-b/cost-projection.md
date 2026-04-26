# Cost Projection — Pattern 2 + Pattern 6 on prism42

Team B, cycle-2B, 2026-04-26. All numbers based on Anthropic pricing fetched 2026-04-26 from `https://platform.claude.com/docs/en/about-claude/pricing` (see `pattern-catalog.md` §"Pricing reference" for the exact table).

## Inputs

- **PSAP turn shape (assumed).** 150 input tokens (system prompt + last 2-3 turns + caller utterance), 300 output tokens (5-12-word PSAP reply + JSON wrapping for the critic). These are conservative — actual token counts on Sonnet 4.6 measured 150/240 on cycle-2T traces; bump 25% for Opus 4.7's 1.0-1.35× tokenizer ratio per CLAUDE.md.
- **Hot-path fallback fire rate.** Empirically <10% of turns reach the LLM-fallthrough branch (response_gate templates 20/21 intents). Of those, validators reject ~30-50% of Nemotron's outputs (cycle-2T's Nemotron 30% per-instruction failure rate). Fallback fires on **5-7% of all turns**. Use 7% upper bound below.
- **Critic fire rate.** 100% of turns at default; configurable down to e.g. 10% via `PRISM42_CLAUDE_CRITIC_SAMPLE_RATE`.

## Per-call cost

Without prompt caching:

| Path | Model | Input cost | Output cost | Per-call |
|---|---|---|---|---|
| Fallback (only when fired) | Sonnet 4.6 | 150 × $3/MTok = $0.00045 | 300 × $15/MTok = $0.0045 | **$0.00495** |
| Critic | Opus 4.7 | 200 × $5/MTok = $0.0010 | 100 × $25/MTok = $0.0025 | **$0.0035** |
| Critic (low-cost variant) | Sonnet 4.6 | 200 × $3/MTok = $0.0006 | 100 × $15/MTok = $0.0015 | **$0.0021** |

With prompt caching (1.25× write once, 0.1× cache reads thereafter — applies most strongly to the system prompt, which is identical across all turns of a session):

- Sonnet 4.6 system prompt ~600 tokens cached at $0.30/MTok read = $0.00018 vs $0.0018 uncached ⇒ savings ~$0.0016/call after the first turn of a session.
- Opus 4.7 system prompt ~600 tokens cached at $0.50/MTok read = $0.00030 vs $0.003 uncached ⇒ savings ~$0.0027/call after first turn.

A typical 8-turn 911 call therefore amortizes the cache-write cost in turn 2 and saves ~$0.012 over the call when both fallback and critic run with caching. For the projections below we use **uncached** numbers — caching is upside.

## Daily cost at four call volumes

Demo profile (assumed): 8 turns per call, mix of routine + a few hard intents.

| Daily calls | Daily turns | Fallback fires (7%) | Fallback $ (Sonnet 4.6) | Critic $ (100% Opus 4.7) | Critic $ (10% sample, Opus) | **Total (full critic)** | **Total (10% critic)** |
|---|---|---|---|---|---|---|---|
| 100 | 800 | 56 | $0.28 | $2.80 | $0.28 | **$3.08/day** | **$0.56/day** |
| 1,000 | 8,000 | 560 | $2.77 | $28.00 | $2.80 | **$30.77/day** | **$5.57/day** |
| 10,000 | 80,000 | 5,600 | $27.72 | $280.00 | $28.00 | **$307.72/day** | **$55.72/day** |
| 100,000 | 800,000 | 56,000 | $277.20 | $2,800.00 | $280.00 | **$3,077.20/day** | **$557.20/day** |

For the hackathon demo (<100 calls/day to beta testers), the **expected cost is well under $1/day** with both flags on at the default 100% critic sample.

## Comparison to current spend

Current state: **$0/turn**. All voice path components run on the B300 pod (Nemotron, Parakeet, Fish). Anthropic spend on the voice path is zero (Sonnet 4.6 only fires on legacy `LLM_BACKEND=anthropic`, not the production `LLM_BACKEND=vllm-local`).

Adding both patterns at full sample at hackathon-demo volume (~100 calls/day): incremental Anthropic spend ~$3/day. **Negligible against the $280 cap** that is already mostly spent on the eval baselines (CLAUDE.md §9).

## $280 cap headroom

Per CLAUDE.md §9 the hackathon cap is $280 total, with $30 (T4.6 baselines) + $100 (T4.7 sweep) + $120 (SOTA additions) ≈ $250 already committed. Remaining headroom ≈ $30. At demo volume ($3/day) this covers **10 days** of full-sample operation, more than enough for the hackathon window plus dev cycles.

If beta testers drive 1,000 calls/day, full-sample cost is $30/day — exhausts headroom in 1 day. Mitigation: drop critic sample rate to 10% (default-overridable via `PRISM42_CLAUDE_CRITIC_SAMPLE_RATE=0.1`), bringing daily cost to $5.57. That gives 5+ days of beta-test headroom.

If beta testers drive 10,000 calls/day, even 10% critic sample exceeds headroom in ~12 hours. At that point the operator should disable the critic (`PRISM42_ENABLE_CLAUDE_CRITIC=0`) and run fallback-only at $28/day.

## Hard ceilings the skeleton enforces

The `claude_brain.py` module ships three independent cost ceilings:

1. **Daily token budget.** `PRISM42_CLAUDE_BRAIN_DAILY_TOKEN_CAP` (default `5_000_000` = ~$20/day on Sonnet input + output mix). Counter resets at UTC midnight; once hit, both flags self-disable.
2. **Per-session token cap.** `PRISM42_CLAUDE_BRAIN_PER_SESSION_TOKEN_CAP` (default `100_000`) protects against pathological transcript explosion.
3. **In-flight concurrency cap.** `PRISM42_CLAUDE_BRAIN_INFLIGHT_MAX` (default `8`) — bounds asyncio queue depth so a Claude latency spike does not spawn unbounded tasks.

All three caps log a single structlog warning when triggered and silently drop subsequent calls — they never wedge the voice path.

## Forward investment

The fallback's 5-7% fire rate is the metric that matters: each fall-back call is a candidate trajectory for the Pattern 7 distillation collector. By the time we have 1,000 fallback fires logged (<3 weeks of beta-test traffic at 100 calls/day), there is enough labeled data to retrain Nemotron with rejection samples — at which point the fallback rate should drop and the per-day cost shrinks proportionally.
