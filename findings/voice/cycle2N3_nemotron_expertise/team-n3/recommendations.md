# Recommendations — top 5 Nemotron-leveraging improvements for the PSAP voice path

**Author:** Team N3, prism42 cycle-2N3
**Charter:** READ-ONLY in this cycle; recommendations are for cycle-2N3-apply / cycle-2T2 / etc.
**Decision principle:** ship what closes the largest IFBench gap or correctness gap *per minute of integration time*, with hard rollback.

I am not enumerating six paths and asking the user to pick. The ranked single path below is **R2 → R3 → R5 → R1 → R4**, with R2 and R3 as the only ones that should land in the next 24 h. R1 and R4 are forward-looking; R5 is opportunistic.

---

## R1 — Expose FSM intents as a tool surface (`dispatcher.emit(intent, text)`)

**The user explicitly asked about this in the directive.**

**Cost:** ~80 LoC across `orchestrator.py` (tool definition) + `dispatcher_fsm.py` (constraint payload) + `worker.py` (parse `tool_calls` and route to TTS instead of streaming `content`). About 4 hours of dev + a smoke call.

**Mechanism.** Define one OpenAI-schema function:

```python
TOOLS = [{
  "type": "function",
  "function": {
    "name": "dispatcher_emit",
    "description": "Emit one PSAP dispatcher reply.",
    "parameters": {
      "type": "object",
      "properties": {
        "intent": {
          "type": "string",
          "enum": ["request_location_and_emergency", "request_location",
                   "confirm_address", "deliver_reassurance",
                   "kq_responsive_breathing", "kq_severity",
                   "verify_cpr_surface", "verify_cpr_breathing",
                   "instruct_cpr_compressions", "answer_do_not_move",
                   "answer_how_long", "answer_outcome_uncertain",
                   "reprompt_caller", "closeout", ...]
        },
        "text": {
          "type": "string",
          "description": "The 5-12-word spoken reply realizing the intent."
        }
      },
      "required": ["intent", "text"]
    }
  }
}]
```

Pass it in `extra_body` (or top-level `tools=...`) on every voice turn. Nemotron's `qwen3_coder` parser pulls a structured `{intent, text}` JSON out, the worker validates `intent` against the FSM's currently-permissible intent set, and only then does Fish TTS speak the `text`. If the intent is wrong or the text fails validators, the response gate's existing template path fires.

**Benefit.**
1. **The FSM and the LLM finally agree on a contract.** Today the LLM is given a free-text reply slot and a 4 KB rulebook; tomorrow it is given a constrained intent enum and a `text` slot. Constraint-following on a typed enum is materially easier than constraint-following on prose. Empirically, Nemotron's BFCL v4 = 53.8 (function calling) is plausibly better than its raw prose-IFBench-71.5 once you measure first-token-of-`text` against the protocol — because the model is being graded on a JSON shape it has 22 K SFT trajectories of, not on prose constraints.
2. **Telemetry becomes free.** `intent` is a categorical label; the worker can log `(predicted_intent, fsm_intent, agreement)` and we get a per-turn audit trail of "did the model pick the right intent" without a separate evaluator agent.
3. **Hallucination becomes a parse error, not a voice incident.** If Nemotron tries to speak "I am an AI", we never see it — the validator on `text` rejects, and we fall through to the template.

**Risk.**
- HF discussion #3 documents "hallucinated tools" (the model occasionally calls `str_replace_editor`). Mitigation: validate tool name; fall through to template on any unknown name. We already have the template fallback.
- Tool catalog renders into the system prompt at ~250 tokens per tool. One tool = +250 tokens prefix per turn. Trivial at our prefill rate.
- **Reasoning ON + tools = the discussion-#3 bug class.** Mitigation: pair this change with R2 (disable reasoning on tool-call turns) — `extra_body` accepts both `chat_template_kwargs.enable_thinking=False` AND `tools=[...]`.

**Dependencies:** R2 must land first.

---

## R2 — Disable reasoning on the voice hot path (`enable_thinking: False`)

**This is the single highest-ROI change in this whole document. Land it first.**

**Cost:** 1-line worker change. Set `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` on the chat-completion call that drives Fish TTS. Zero LoC in `orchestrator.py`/`dispatcher_fsm.py`/`response_gate.py`. ~10 minutes.

**Benefit.**
- **Hard latency win.** Per `chat_template.jinja` (fetched 2026-04-26) and our measured 313 tok/s decode (Team M `profile.md:65-69`), reasoning ON inflates first-speakable-token TTFB by **150-950 ms per turn**. PSAP turns are 5-12 spoken words = 10-30 emitted tokens. The reasoning trace is ALL latency you cannot hear. Killing it moves median TTFT from ~50 ms (vLLM tier, prefill) + ~150 ms (reasoning fence) → ~50 ms.
- **No accuracy loss for our task.** NVIDIA model card: *"a slight decrease in accuracy for harder prompts that require reasoning"*. Our task is "respond with one 5-12 word PSAP line at a known intent" — closer to template-fill than to AIME math. The reasoning trace is wasted; you can prove it locally by running the cycle-2T templates side-by-side with reasoning ON vs OFF and checking the user-visible content stays equivalent.
- **Closes finding A3.** With reasoning OFF, `max_tokens=64` is sufficient and we stop hitting `finish_reason=length`.

**Risk.**
- LOW. The toggle is per-request; we can A/B by env-flagging it (`PRISM42_NEMOTRON_THINKING=0/1`).
- One known caveat: `enable_thinking=False` short replies very rarely return `content=""` (vLLM issue #30904) when `max_tokens` is too small. Set `max_tokens>=64` and the bug does not appear.
- The response gate's deterministic templates fire on 20/21 intents and bypass the LLM entirely; this change only affects the REPROMPT-class fallback path. Even there the template-only mode is dominant.

**Verification.**
1. Live curl probe with `enable_thinking=False`, measure TTFB; expect ~50 ms.
2. Same probe with reasoning ON; expect 200-1000 ms.
3. Run the cycle-2T regression set; expect zero new failures.

**Numeric estimate of IFBench delta:** none — IFBench is graded on prose instruction-following, which already benefits from reasoning. We are *not* trying to lift IFBench. We are trying to lift **TTFT and TPS for tightly-constrained 5-12 word PSAP replies**, where reasoning is pure overhead. Target: -150 ms median, -500 ms p95, -0 word-error.

**Dependencies:** none. Land alone. Risk-free, reversible per-request.

---

## R3 — Per-intent system-prompt rotation (FSM-state-aware system message)

**Cost:** ~40 LoC in `dispatcher_fsm.py:next_prompt()`. Already partially implemented — the FSM already produces a per-turn system prompt in `next_prompt()` at line 720. The proposal is to make that prompt **shorter and more intent-specific**.

**Mechanism.** Today `next_prompt()` produces a ~600-token prompt with role + intent guidance + caller utterance + pronouns + latched facts + anti-repetition + output rules. The 4 KB `FAST_DISPATCHER_SYSTEM_PROMPT` (`orchestrator.py:495-729`) is *also* injected at agent-construction time and never replaced. We are paying the cost of both. The FSM `next_prompt` was supposed to *replace* the verbose protocol prompt, not add to it; verify in `worker.py` that `update_instructions(prompt)` actually clobbers the old system message rather than appending. (If it appends, that's a bug and the fix is one line.)

The bigger win: **shrink the per-state prompt to ~150 tokens**. For INTAKE state: only the IAED opener and the address-first rule. For CRITICAL_VERIFY: only the MPDS-9 two-question gate. For PRE_ARRIVAL: only the relevant pre-arrival instruction. The model's working memory is finite; cluttering the system prompt with rules that don't apply *to this state* makes it harder to follow the rules that *do*. This is the "bloated CLAUDE.md causes Claude to ignore the actual rules" principle from CLAUDE.md, applied to Nemotron.

**Benefit.**
- Shorter system prompt → faster prefill (saves ~10-30 ms per turn).
- Better instruction following on the rules that matter (estimate: +5-10 percentage points of IFBench-style adherence on the *narrow* per-state ruleset, even if global IFBench is unchanged).
- Smaller cache-invalidation surface — if we ever fix the orchestrator-frozen issue and split into stable header + mutable footer, a 150-token mutable footer is much more cacheable than a 600-token one.

**Risk.** MED. We risk losing a rule that the LLM was relying on. Mitigation: ship behind `PRISM42_NEMOTRON_PER_INTENT_PROMPT=1` and run the cycle-2T regression set first. Rollback is one env var.

**Dependencies:** none, but compounds well with R2 (shorter prompt + no reasoning trace = much tighter token budget per turn).

---

## R4 — Few-shot PSAP examples in the system prompt

**Cost:** ~30 LoC; one new file `agents/livekit/few_shots.py` with 8-12 caller/dispatcher exchange pairs covering each intent.

**Mechanism.** Append a `# EXAMPLES` block to the per-intent prompt with 1-2 demos like:

```
# EXAMPLES
Caller: "9-1-1 my husband is having chest pain at 421 Maple"
You: "Help is on the way and I am staying with you."

Caller: "yes I think so, he's awake"
You: "Can you tell me how severe the pain is, one to ten?"
```

Few-shot prompting in the system message is a well-known IFBench lifter for ChatML-style models — the demos give the model concrete templates to imitate.

**Benefit.** Estimated +3-7 IFBench-points-equivalent on PSAP turn shape (5-12 word, single-question constraint). The model is good at imitation; cheap to give it examples.

**Risk.** LOW for accuracy; MED for prompt size. Each demo costs ~30 tokens; 12 demos = +360 tokens per turn → +5-10 ms prefill. Pair with R3 to net out neutral.

**Dependencies:** R3. (Don't add few-shots to the 4 KB monolith; add them to the per-intent prompts where they actually help.)

---

## R5 — Use `guided_json` / `guided_regex` to bound the response gate's regen path

**Cost:** ~20 LoC in `response_gate.py` to wire `extra_body={"guided_regex": "<5-12 word, one-terminator regex>"}` on the LLM-fallback path.

**Mechanism.** Today `response_gate.validate_llm_output` (response_gate.py:120-184) post-validates LLM output against four rules (5-14 words, one terminator, no banned pronouns, no repeats from rolling buffer). When validation fails, we currently fall through to a template. Replace post-hoc validation with `guided_regex` constraint sent to vLLM, so the model **cannot emit invalid output** in the first place.

**Benefit.** Eliminates the regen latency of the post-hoc retry path. Hard correctness guarantee on word-count and terminator (no validator drift).

**Risk.** MED — vLLM issue #37362 documents that `guided_*` constrains tokens during the `<think>` phase too, which produces garbage. **Pre-requisite: R2 must be on** (reasoning OFF). With reasoning OFF the constraint applies only to the user-visible content, which is what we want.

**Dependencies:** R2 (hard).

---

## Why this ordering, not yours

The directive listed five examples as starting points. Re-ranked by leverage × shippability:

1. **R2 (reasoning OFF) ships in 10 min and removes 150-950 ms of pure latency.** The original directive treated this as a tradeoff to "quantify"; the data says it's a one-way Pareto improvement for our 5-12 word task — we should not be paying for thinking on a constraint-fill task.
2. **R3 (per-intent prompt) is mostly already built** — we just have to verify `update_instructions` is replacing not appending, and shrink the prompts. Big leverage relative to LoC.
3. **R5 (guided_regex)** locks the gate's regen path to a hard correctness guarantee — small change, eliminates a class of bugs forever, but only safe after R2.
4. **R1 (FSM-as-tool)** is the biggest architectural improvement and the user's own example. It is also the most code (4 hr) and the one with the most coupled risk (tool catalog + tool-call-with-reasoning interaction). Land R2/R3/R5 first; come back to R1 with a clean baseline.
5. **R4 (few-shot)** is easy but lower-leverage; only worth it after R3 (otherwise we are stuffing demos into a monolith that already loses signal).

Do **not** ship them all at once. R2 and R3 can be flagged on independently; R5 requires R2; R1 should land in its own cycle with full smoke coverage.

Word count: ~1280.
</content>
</invoke>