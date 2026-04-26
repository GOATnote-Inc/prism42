# Pattern Catalog — Combining On-Pod Nemotron with Remote Claude

Team B, cycle-2B. Prepared 2026-04-26 for the prism42 voice agent.

## Glossary

- **Nemotron** = `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` served by vLLM 0.20 on the B300 pod at `127.0.0.1:8001`. Observed TTFT ~50 ms (worker.py §674), full reply ~313 tok/s.
- **Claude** = Anthropic Messages API, model id `claude-opus-4-7` or `claude-sonnet-4-6`. Pricing rows below are quoted from `https://platform.claude.com/docs/en/about-claude/pricing` (fetched 2026-04-26). No provider-side TTFT SLA is published; observed p50 from prism42's own `specialists.py` and KB-08 references is **Sonnet 4.6 TTFT ~600 ms**, **Opus 4.7 TTFT ~3-7 s** for short prompts. Tokenizer note: Opus 4.7 uses 1.0x-1.35x the tokens of Opus 4.6 for the same text (CLAUDE.md §"Recent best-practice synthesis").
- **Hot path** = the leg from STT-final to first TTS audio frame. Budget per CLAUDE.md §0: p95 < 1.5 s end-to-end. Spending here erodes voice quality directly.

## Pricing reference (Anthropic, fetched 2026-04-26)

Source: `https://platform.claude.com/docs/en/about-claude/pricing`.

| Model | Input ($/MTok) | 5m cache write | Cache hit | Output ($/MTok) | Batch in/out |
|---|---|---|---|---|---|
| Opus 4.7 | $5 | $6.25 | $0.50 | $25 | $2.50 / $12.50 |
| Sonnet 4.6 | $3 | $3.75 | $0.30 | $15 | $1.50 / $7.50 |
| Haiku 4.5 | $1 | $1.25 | $0.10 | $5 | $0.50 / $2.50 |

Voice-PSAP turn assumption used below: ~150 input tokens (system prompt cached + last 2-3 turns) + 300 output tokens. Without caching that is `(150 × $5 + 300 × $25) / 1e6 = $0.0083` per Opus 4.7 turn and `(150 × $3 + 300 × $15) / 1e6 = $0.0050` per Sonnet 4.6 turn. With cache reads on the system prompt, Opus drops to **~$0.0076/turn**, Sonnet to **~$0.0046/turn**.

## Pattern 1 — Cascade (review-and-regenerate)

**Definition.** Every Nemotron output passes to Claude. Claude scores it; if it fails a rule (gendered pronoun, repeated phrase, off-protocol instruction), Claude rewrites and the rewrite is what TTS speaks.

**Latency tax.** Worst-case 2× LLM. Even with parallel hedged streaming, the gate only releases the rewrite on Claude's last-token, so **+600 ms minimum (Sonnet) or +3+ s (Opus 4.7)**. Eats the entire 1.5 s budget.

**Cost tax.** 2× LLM tokens per turn. At `$0.0046 + $0.0076 = $0.012/turn` if Sonnet wraps Opus, or just `$0.005/turn` for Sonnet-only. 1k turns/day = $5-12, 10k/day = $50-120.

**Reliability impact.** Negative on the hot path — Claude API hiccups now block speech. Mitigation: hard timeout + Nemotron-only fallback, but that defeats the cascade's purpose.

**Failure modes.** Claude API 5xx or 429 ⇒ caller hears a long pause. Claude's rewrite slowly arrives mid-Fish-stream ⇒ overlapping audio. Claude refuses the medical role ⇒ caller hears a refusal disclaimer.

## Pattern 2 — Fallback (Nemotron primary, Claude on failure)

**Definition.** Nemotron handles every turn. Claude is invoked **only when Nemotron output fails validation** (repeated phrase, banned token, exceeds word cap, returns empty after N regens).

**Latency tax.** Hot path = Nemotron only (~50 ms TTFT). When fallback fires, +600 ms-3 s. If response_gate catches the validation failure first and emits a deterministic template, Claude never runs.

**Cost tax.** Tied to Nemotron failure rate. Cycle-2T notes "Nemotron-3-Nano's 30% per-instruction failure rate" but the response_gate templates 20/21 intents — so empirically <10% of turns reach an LLM at all, and of those, well under half fail validation. **Estimate 5-10% of turns hit Claude ⇒ $0.0003-0.0008/turn average.** 1k turns = $0.30-0.80; 10k turns = $3-8.

**Reliability impact.** Net positive — Nemotron handles the steady state and the slow path is reserved for the cases where speech quality matters most (validator-flagged outputs).

**Failure modes.** Claude down during a validator-flagged turn ⇒ fall back to a template (still safe). Validator misfires ⇒ unnecessary Claude call ⇒ extra $0.005 + +600 ms.

## Pattern 3 — Specialist (Claude on hard intents only)

**Definition.** The FSM's intent classification routes specific intents (e.g. `INSTRUCT_CPR_BEGIN`, `ANSWER_OUTCOME_UNCERTAIN`, multi-clause caller questions) to Claude; routine intents (`REQUEST_LOCATION`, `CONFIRM_ADDRESS`, `KQ_*`) stay on Nemotron + templates.

**Latency tax.** Per-intent. CPR/outcome/complex-question turns gain +600-3000 ms; routine turns unchanged. Because these intents fire ≤2× per call, **average end-to-end p95 stays inside budget if specialist intents pick Sonnet 4.6**.

**Cost tax.** ~2 specialist turns per call × $0.005 (Sonnet) = $0.01 per call. 1k calls/day = $10. 10k/day = $100.

**Reliability impact.** Best precision-to-latency ratio of any always-on pattern: the model with stronger instruction-following lands exactly where it matters (CPR safety, outcome questions) without paying on routine address capture.

**Failure modes.** Intent classifier mismatches ⇒ Claude paid for unimportant turns OR Nemotron handling something it shouldn't. CPR-blocked path needs **synchronous** Claude — if Claude is down, that turn falls back to the deterministic CPR template (worker safe) but you lose the precision win.

## Pattern 4 — Parent (Claude orchestrates, Nemotron speaks)

**Definition.** Claude receives the caller utterance + transcript, decides intent + content, emits a structured plan; Nemotron renders the plan into a 5-12-word PSAP utterance; TTS speaks Nemotron's render.

**Latency tax.** Sequential Claude → Nemotron. Worst observed in `orchestrator_full.py` (the archived two-step pattern): 14-20 s end-to-end. Even with Sonnet 4.6 + Nemotron streaming = ~600 + 50 ms TTFT but you wait for Claude to produce the structured plan before Nemotron starts ⇒ p50 ~1.0-1.5 s, p95 way over.

**Cost tax.** Claude on every turn = ~$0.005-0.008/turn. 1k turns = $5-8.

**Reliability impact.** Highest "intelligence" but slowest. The exact pattern that prism42 already moved away from in cycle-2d (orchestrator_full.py archived). Re-introducing it without solving streaming-the-plan-while-Nemotron-renders is a regression.

**Failure modes.** Claude plan parse error ⇒ no Nemotron rendering ⇒ silence. Claude refuses ⇒ same. Slow Claude ⇒ caller hangs up.

## Pattern 5 — Ensemble + judge

**Definition.** Nemotron + Claude both run in parallel; a third (small, fast) model — Haiku 4.5 or a local rule-based scorer — picks the better output.

**Latency tax.** `max(Nemotron, Claude)` + small judge time. If Claude is Sonnet 4.6 streamed, ≈600 ms + ~50 ms judge = 650 ms on the hot path. Marginally worse than Nemotron alone.

**Cost tax.** 2× LLM tokens + judge tokens. Sonnet 4.6 ($0.005) + Nemotron ($0) + Haiku 4.5 judge (~$0.002) = ~$0.007/turn. 1k turns = $7. 10k = $70.

**Reliability impact.** If one provider is down, the other still ships an answer. Best uptime profile of any pattern.

**Failure modes.** Judge picks the wrong output ⇒ user hears the worse answer (and you can't easily detect this offline). Two Fish TTS frames slightly different in prosody ⇒ no observable issue if you only release one.

## Pattern 6 — Critic (off-path async scoring)

**Definition.** Nemotron renders. After audio ships, an async task posts the (caller_utterance, dispatcher_reply, transcript_so_far) tuple to Claude for a quality score. Scores feed an offline regression detector + auto-tuned prompt drift bench.

**Latency tax.** Zero on hot path. Critic runs in `asyncio.create_task(...)` on `on_user_turn_completed`, just like the existing safety-monitor / ohca-detector / intent-verifier triplet (specialists.py §206-323).

**Cost tax.** Sample rate determines cost. At 100% scoring with Sonnet 4.6: $0.005/turn. At 10%: $0.0005/turn. 10k turns/day at 10% = $5/day.

**Reliability impact.** Zero impact on caller experience. Pure observability win — surfaces regressions before the operator hears them.

**Failure modes.** Score never lands ⇒ silent dashboard gap (acceptable). False alarms ⇒ noisy Slack channel (tune the rubric). The critic learns the wrong rubric ⇒ regression detector blind ⇒ caught only at QI review.

## Pattern 7 — Distillation collector

**Definition.** Nemotron renders + speaks. On a sample (e.g. 5%), Claude gets the same input and writes its "ideal" output. Both pairs are stored under `findings/voice/distillation/<date>/*.jsonl`. Used as fine-tuning data for the next Nemotron checkpoint.

**Latency tax.** Zero on hot path (collector is async like Pattern 6).

**Cost tax.** 5% × Sonnet = $0.00025/turn. 10k turns = $2.50. The Opus 4.7 variant doubles it but produces stronger labels.

**Reliability impact.** None. This is a long-loop investment — it pays back when the next Nemotron checkpoint trains on the collected pairs.

**Failure modes.** Collected pairs leak something we shouldn't ship (PII, off-protocol Claude output) into a training set ⇒ governance failure. Mitigated by routing distillation through `state.py`'s SessionState scrubber + a manual physician review queue.

## Cross-cutting risks every pattern must mitigate

1. **Claude API 429 / 5xx.** Every hot-path pattern needs a hard timeout (≤500 ms) + Nemotron-only fallback path. Never wait for retry on the hot path. Critic/distillation can retry asynchronously.
2. **Anthropic refusal of medical role.** Sonnet 4.6 refusal rate on this exact role-play is **0.18%** (KB-08 §7), Opus 4.7 is **0.28%**. Even at 0.18%, expect 1-2 refusals per 1k turns — must be caught and fall back to a template.
3. **Tokenizer drift.** Opus 4.7 ⇒ 1.0-1.35× tokens vs 4.6 (CLAUDE.md). Re-measure after any Opus 4.6 → 4.7 prompt migration.
4. **Sampling-param 400.** Opus 4.7 rejects `temperature`, `top_p`, `top_k`, `budget_tokens` — must omit. The skeleton in `skeleton/claude_brain.py` enforces this.
5. **Workspace `callable_agents` strip.** Prism's API key strips multi-agent silently (CLAUDE.md §8). Keep the design to direct `messages.create(...)` from the worker — do not propose sub-agent delegation patterns until the workspace flag flips.
