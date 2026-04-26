# Cycle-2Q Team-4 — Munger inversion of the FSM-gated voice agent

**Author:** Team 4 (Munger Inversion + NVIDIA LLM-Control specialist)
**Date:** 2026-04-26
**Ship-by:** ~45 min from kickoff
**Audience:** prism42 hackathon — voice-team coordinator deciding whether to merge a hand-coded FSM in front of the existing single-LLM dispatcher.

---

## TL;DR

The single biggest dragon in the user's FSM proposal is **state misclassification on the worst possible utterance** ("they're not responding"), where the FSM picks "interpersonal" instead of "cardiac arrest" and the LLM is now contractually forbidden from using the right script. An FSM is a confidence amplifier — it amplifies the right answer and the wrong answer at the same speed. The voice agent today is wrong about 4 things; an FSM in 2-3h could be wrong about 4 *different* things, on a deadline that doesn't allow a second iteration.

**Recommended approach: G + B, in that order, FSM strictly deferred.**

1. **G — Better single-shot prompt with state injected per turn** (30 min, 0 ms latency, fixes 3/4 user-reported bugs at zero new-bug risk).
2. **B — Structured-output / function-calling pass for the gender-pronoun and repetition guards** (60-90 min, +50-150 ms when the regenerate fires on ~10% of turns, fixes the 4th bug deterministically).
3. **FSM — only if G+B fail** the live-listen test, post-hackathon, with a flag-gated rollout that preserves the cycle-2d hot path verbatim.

This bisects: ship the fastest robust win first, FSM as upgrade not blocker. Munger's rule applies — *avoid the standard stupidities* before chasing brilliance.

---

## Phase 1 — Munger inversion: how does the FSM make the demo worse?

Ranking is severity × probability on a hackathon timeline (hours from now). 5 = catastrophic-and-likely, 1 = mild-and-rare. Severity scoring is grounded in the demo objective: a public 911-themed voice surface that must not look broken for ~5 minutes of judged listening.

### Failure modes, ranked

| # | Failure mode | Severity | Probability | Score |
|---|---|---|---|---|
| F1 | State misclassification on safety-critical utterance | 5 | 4 | **20** |
| F2 | LLM degeneration under heavy template constraint (warmth loss) | 4 | 5 | **20** |
| F3 | Verification sub-FSM fights AHA T-CPR | 5 | 3 | **15** |
| F4 | New surface for bugs (regression in cycle-2d/2e gains) | 4 | 4 | **16** |
| F5 | Brittle FSM vs caller chaos (loops, repeats, multi-intent) | 4 | 4 | **16** |
| F6 | Latency tax (extra LLM call for intent classifier) | 4 | 3 | **12** |
| F7 | State sync across LiveKit reconnects | 3 | 3 | **9** |
| F8 | Hot-reload/A-B difficulty under sprint pressure | 3 | 3 | **9** |
| F9 | Adversarial inputs / jailbreak via magic words | 3 | 2 | **6** |
| F10 | Monitoring + observability cost | 2 | 4 | **8** |

#### F1 — State misclassification on a safety-critical utterance (score 20)

**Scenario.** Caller: *"Oh god, they're not responding."* The FSM has a hand-coded intent set: `{interpersonal_dispute, missing_person, medical_unresponsive, unclear}`. The classifier's training data is 30 example phrases scribbled into a Python dict. "Not responding" matches `interpersonal_dispute` (texts not being answered) 60% of the time on a bag-of-words match. LLM is now told `intent=interpersonal_dispute, phrase: "When did you last hear from them?"` Caller hears that and the demo is dead.

**Why this is worse with FSM than without.** Today's prompt at orchestrator.py:266-313 instructs the LLM to read pronouns, advance phases monotonically, and route on key-question tags. The LLM does this with all 165 lines of context plus the conversation history. If you put a hand-coded FSM in front, you are telling the LLM "the answer is X" before it has read the room. **A correct prior is a feature; a wrong prior is a contract** — the LLM will chase the FSM's intent because the system prompt now contains "Your intent for this turn is: interpersonal_dispute. Phrase that intent in 5-12 words."

**Mitigation.** If FSM ships, the intent classifier has to be at least as smart as the existing prompt, which means it has to be an LLM call, which lands in F6. There is no cheap mitigation — the cheap version *is* the failure mode.

#### F2 — LLM degeneration under heavy template constraint (score 20)

**Scenario.** System prompt becomes: *"Your intent: REASSURE. Constraint: 5-12 words. Vary phrasing. Do not repeat 'help is on the way'."* Nemotron-3-Nano emits stilted, over-deliberated text — *"Your assistance is currently being routed to your location."* — because the template surface area shrank from "natural dispatcher reply" to "realize this label". This is a documented failure mode for instruction-tuned models on narrow constrained generation. The HuggingFace card for Nemotron-3-Nano explicitly warns about *"aggressive filters for pathological repetition patterns during training"* affecting *"certain constrained generation scenarios"* [https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 — fetched 2026-04-26].

**Mitigation.** Don't constrain to label-realization; constrain to behavioral guards (no "OK", neutral pronouns) while keeping the prompt's natural-language frame. This is exactly what option G does.

#### F3 — Verification sub-FSM fights the AHA T-CPR position (score 15)

**Scenario.** User proposes the FSM ask "is the surface flat? are they breathing?" before instructing CPR. AHA T-CPR (`https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures` — fetched 2026-04-26) actually says: a "no" answer to "is the patient conscious?" OR "is the patient breathing normally?" should prompt **immediate dispatch** with target <150 s from call-receipt to first compression. Two questions, then go. **Not zero questions, not five questions.** Adding 4-8 s of dialogue ("is the surface flat? do you have access to their chest? is their head tilted?") is iatrogenic.

The orchestrator.py:359-362 hot path already shorts to *"Lay him flat on his back. Start chest compressions — center of the chest, hard and fast."* on the trigger phrase "not breathing" — which is the AHA-aligned action, not a bug. The user's framing of "unverified CPR" as a bug is half-right: AHA wants TWO confirmation questions before the CPR script; the prompt should ensure those happen, not block on a deeper verification tree.

**Mitigation.** Single prompt addition: when the caller says "not breathing", confirm with one question ("Are they on the floor / on a hard surface?") then go to the existing CPR script. Cost: 2 lines of prompt. Latency: one extra turn (~3-5 s) but only on the cardiac-arrest path. Captures the AHA two-question guard without an FSM.

#### F4 — New 200 LoC surface area for bugs (score 16)

**Scenario.** FSM lands. cycle-2d Fish FA patch (PASS_2D, 3.0× warm RTF) and cycle-2e Pipecat sentence-buffer (BufferedDispatcherAgent overriding `tts_node`) are byte-for-byte preserved per the env-flag discipline (orchestrator.py:406). FSM code is in worker.py or a new `fsm.py`, hooks into `on_user_turn_completed`. A subtle bug: FSM advances phase on `phase=reassurance` *before* the address is captured because intent classifier mis-fired. Now the LLM's first reply is "Help is on the way" before it has the address — a worse failure than what we have today.

**Mitigation.** Mandatory env-flag gate (`PRISM42_CYCLE_2Q_FSM=0` default) so the FSM path can be turned off in seconds without a rebuild. This is required regardless of which option ships.

#### F5 — Brittle FSM vs caller chaos (score 16)

**Scenario.** Caller (real or pre-recorded fixture): *"My husband, oh god, he was cooking and then he just — and the stove is on too, can you hear me, do I leave him there?"* Three intents (medical, fire, action question), one utterance. FSM has to pick one. LLM today handles this gracefully because the prompt says "answer the LAST utterance specifically" (orchestrator.py:319-324) — so it picks the action question first, then loops back. FSM-mediated, the system has to decode multi-intent compositionally, which is research not engineering.

**Mitigation.** None at hackathon scope. Multi-intent handling is the steady-state weakness of FSMs — you fix it with an LLM, which is what we already have.

#### F6 — Latency tax (score 12)

**Scenario.** Option E (LLM-as-FSM) requires two Nemotron calls per turn. With current hot-path TTFT ~500 ms, doubling it pushes p95 above the §0 hackathon-mode 1.5 s end-to-end target. Even worse: cycle-2e BufferedDispatcherAgent's first-segment cap (`PRISM42_CYCLE_2E_FIRST_TOKENS=24`) only helps the *output* side; an extra input-phase LLM call is purely additive.

**Mitigation.** Option B (structured output in a single call) avoids the second call; the regenerate-on-fail path costs ~500 ms and only fires on ~10% of turns. Option F (constrained decoding via guided_json/guided_regex) is single-call and zero added latency, but see F8.

#### F7 — State sync across LiveKit reconnects (score 9)

**Scenario.** WebRTC reconnects mid-call. FSM state lives in worker.py memory. New worker process picks up via session resume. State is gone; FSM resets to `phase=intake`; LLM is told to ask for the address again *after* it's already been captured. Caller hears *"What is your location?"* on the second leg of the same call. Demo embarrassment.

**Mitigation.** Persist FSM state to the same Redis-backed SessionState already mentioned in CLAUDE.md "Recent best-practice synthesis" (the Anthropic Managed Agents engineering post: *"the session provides this same benefit, serving as a context object that lives outside Claude's context window"* — `https://www.anthropic.com/engineering/managed-agents`). This is non-trivial wiring on a hackathon timeline.

#### F8 — Hot-reload + A/B difficulty (score 9)

The FSM is in worker.py. Worker restart is ~30 s (not the 14-min vLLM cold-reboot — Nemotron stays up). Still: any FSM logic change requires code → restart → reconnect a real call. Compare to prompt edits (option G), which redeploy in <15 s with no worker restart needed if the agent re-instantiates per-session.

#### F9 — Adversarial inputs (score 6)

Low for the demo audience (judges, fixtures). Higher in production. Today's prompt has a single hardened refusal pattern at orchestrator.py:381-384 (*"This is a training simulation..."*). An FSM that exposes state-transition triggers as data ("if user says X, transition to Y") is a new attack surface — caller says "skip to closeout" and the FSM advances. Not a hackathon-day risk; a v1.0 risk.

#### F10 — Observability cost (score 8)

Every FSM transition needs a log line. Today's structlog setup at orchestrator.py:40 will absorb it but the dashboard/Grafana side is more work. Manageable; just tax.

### Munger summary

The FSM proposal optimizes for the *visible behavior* of the 4 reported bugs but creates new failure modes that are *less visible* during a 5-minute judged listen and *more catastrophic* when they fire. Inversion: instead of asking "how do I make the FSM right", ask "how do I avoid the wrong-answer trap entirely". The wrong-answer trap is the FSM telling Nemotron the intent. Don't tell Nemotron the intent.

---

## Phase 2 — Alternatives scored

Each option scored 1-5 on five axes (5 = best). Total out of 25.

| Option | Time-to-ship | Robustness on 4 bugs | Risk of new bugs (5=lowest) | Latency (5=lowest) | "Demo wow" | **Total** |
|---|---|---|---|---|---|---|
| **A** Prompt rewrite, no extras | 5 | 3 | 5 | 5 | 1 | **19** |
| **B** Structured output + post-hoc guard | 4 | 5 | 4 | 4 | 3 | **20** |
| **C** Two-pass: LLM → judge | 3 | 4 | 3 | 2 | 4 | **16** |
| **D** Hand-coded FSM (user proposal) | 2 | 4 | 2 | 3 | 5 | **16** |
| **E** LLM-as-FSM (intent + phrase) | 2 | 4 | 3 | 2 | 5 | **16** |
| **F** Constrained decoding (guided_json/regex) | 2 | 4 | 2 | 5 | 3 | **16** |
| **G** Better single-shot prompt with state injection | 5 | 4 | 5 | 5 | 2 | **21** |

**Winner by total: G (21) > B (20) > A (19).** D, E, F all tie at 16.

### Why G wins

G is what option A would be if you took it seriously. The trick is *injecting state in the prompt every turn* — exactly the pattern at orchestrator.py:266-285 today, only the "Turn State Tracker" flags get filled in by the worker before send instead of being mentally computed by the LLM. Nemotron is not being asked to solve a new problem; it's being given the answer to a problem it was already solving inconsistently.

Concrete G-implementation (one diff, ~20 LoC in worker.py):

```python
# In on_user_turn_completed (or before each LLM call)
state = compute_state_from_history(session.history)  # cheap regex pass
turn_prefix = f"""
# RUNTIME STATE (computed by worker, AUTHORITATIVE)
state.address_captured: {state.address_captured}    # Y/N
state.reassurance_delivered: {state.reassurance_delivered}  # Y/N (latches)
state.recent_phrases: {state.recent_phrases}        # last 3 assistant turns
state.pronouns_known: {state.pronouns_known}        # 'they/them' default
state.cardiac_arrest_confirm_step: {state.cardiac_step}  # 0,1,2 (AHA two-question)
"""
# Prepend to the existing system prompt for this turn only.
```

This converts the LLM's *mental computation* of flags [A], [B], [C] into a *server-attested* truth, which is more reliable. Cost: one regex pass per turn (~1 ms), zero added LLM calls, zero TTS impact, zero risk to the cycle-2d/2e hot path.

### Why B is the followup

The pronoun bug is the one user-reported bug G alone won't reliably solve, because Nemotron's instruction-following ceiling on "use 'they/them' unless caller explicitly states gender" is not 100%. IFBench (prompt) for Nemotron-3-Nano-30B-A3B-NVFP4 is **70.7** [https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 — fetched 2026-04-26]. That's good but not gender-bug-proof on a public demo.

Option B's deterministic post-hoc check ("did the reply contain 'him'/'his'/'he'? if so and pronouns_known=False, regenerate with corrected hint") is a 50-LoC addition that fires on ~10% of turns, costs ~500 ms when it does, and *guarantees* the pronoun bug doesn't ship. vLLM 0.20 supports tool calling on Nemotron-3-Nano with `--enable-auto-tool-choice --tool-call-parser qwen3_coder` per the official recipe [https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html — fetched 2026-04-26], so structured emission is on the supported path, not a research project.

### Why D-F lose

- **D (hand-coded FSM):** F1+F4+F5 dominate the score sheet. Building it inside ~3 h on a sprint with no second iteration is the kind of bet Munger calls "standard stupidity #4 — substituting motion for progress".
- **E (LLM-as-FSM):** F6 is fatal. Two calls per turn pushes p95 over 1.5 s, breaks the §0 latency-is-a-feature rule.
- **F (constrained decoding):** vLLM guided_json/guided_regex on Nemotron + B300 sm_103 + FLASHINFER_CUTLASS MoE backend is unproven territory. The `prism42_b300_voice_durable_findings.md` finding #6 already documents one MoE-backend instability (TRTLLM auto-selection produces JS-garbage output); guided decoding adds xgrammar bitmask ops on top of that. **No public B300 confirmation that guided_regex is stable on Nemotron-3-Nano-NVFP4 with FLASHINFER_CUTLASS** as of fetch-date. Unknown unknown on hackathon timeline = no.

---

## Phase 3 — Nemotron-3-Nano-specific considerations

### Instruction-following benchmark performance

| Benchmark | Nemotron-3-Nano-30B-A3B-NVFP4 | Reference |
|---|---|---|
| IFBench (prompt) | **70.7** (NVFP4); 71.5 BF16; 72.2 FP8 | [hf.co — fetched 2026-04-26] |
| MMLU-Pro | 78.3 | [vllm blog — fetched 2026-04-26] |
| Strengths cited | SWE-bench Verified, GPQA Diamond, AIME 2025, Arena Hard v2, IFBench | [vllm blog — fetched 2026-04-26] |

Comparison anchors (caveat: different benchmark configs, different fetch-dates, take ±2 pt):

- **Sonnet-4.6 family / Opus-4.7:** Anthropic does not publish IFBench but reports ~85+ on IFEval-prompt-strict for Sonnet-class models (model card cited in CLAUDE.md whats-new page). Opus 4.7 is *more literal* by design — fewer silent generalizations, calibrates length to task complexity (CLAUDE.md "Behavior changes that matter for Prism prompts" section). For our 5-12 word constraint, Opus 4.7 is structurally better but expensive.
- **Llama-3.3-70B-Instruct:** ~88-90 IFEval-prompt (Meta model card numbers).
- **Qwen3-72B / Qwen3-Coder:** comparable to Nemotron-3-Nano on IFBench; Nemotron's reasoning-parser is forked from Qwen3 territory (`--tool-call-parser qwen3_coder`).

**Implication:** Nemotron-3-Nano is mid-tier on instruction-following. It will *not* perfectly obey "always say 'they/them'" or "never repeat 'help is on the way'" purely from prompt engineering. ~70 IFBench means ~30% of constraint-bearing prompts get partially violated on a per-instruction basis. Option G's per-turn state injection compresses the ask from "remember 8 rules across 50 turns" to "respect 4 booleans this turn" — much better for a 70-IFBench model.

### JSON-mode + tool calling support in vLLM 0.20

Confirmed supported per the official vLLM recipe:

```
--enable-auto-tool-choice
--tool-call-parser qwen3_coder
--reasoning-parser-plugin nano_v3_reasoning_parser.py
--reasoning-parser nano_v3
```

[https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html — fetched 2026-04-26]

vLLM blog (2025-12-15) confirms tool calling is a first-class supported mode [https://vllm.ai/blog/run-nvidia-nemotron-3-nano — fetched 2026-04-26]. Known issue: HF discussion thread #3 reports *"tool calling with reasoning parsing broken"* in some configurations [https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3 — fetched 2026-04-26] — implication: structured output may need `enable_thinking: false` via `chat_template_kwargs` to avoid reasoning-trace contamination.

### Sampling guidance from the model card

- **Reasoning tasks:** `temperature=1.0, top_p=1.0`
- **Tool calling:** `temperature=0.6, top_p=0.95`

[https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 — fetched 2026-04-26]

For our voice path (short reply, deterministic-ish), tool-calling defaults are closer; consider `temperature=0.6, top_p=0.95` for option B's structured pass. Note: the orchestrator passes through whatever vLLM's default is unless explicitly set in worker.py — verify before shipping.

### vLLM constrained decoding on B300 sm_103

vLLM 0.20 ships xgrammar (security-patched) and outlines as guided-decoding backends [https://github.com/vllm-project/vllm/releases — fetched 2026-04-26]. Known caveats relevant to our pod:

- **No public stability confirmation for Nemotron-3-Nano-NVFP4 + FLASHINFER_CUTLASS MoE + guided_regex/guided_json on B300 sm_103.** vLLM issue #34249 documents FP8 MoE backend auto-selection bugs on Hopper [https://github.com/vllm-project/vllm/issues/34249 — fetched 2026-04-26]; issue #33333 documents FLASHINFER_CUTLASS unsupported on sm_120 [https://github.com/vllm-project/vllm/issues/33333 — fetched 2026-04-26]. The MoE-backend selection on our pod is the brittle layer (per `prism42_b300_voice_durable_findings.md` #6 — TRTLLM produces garbage); stacking guided-decoding on top adds risk without a known-good config.
- **Recommendation:** if option B/F is chosen, run guided generation behind a feature flag with a fallback to plain JSON-prompted output. Don't ship a path that hard-depends on guided_regex working.

### Published prompt patterns for Nemotron

- **Standard chat template** with `apply_chat_template(..., add_generation_prompt=True)` per the model card.
- **`enable_thinking: false`** via `chat_template_kwargs` for non-reasoning workloads (voice, JSON output) — per the cookbook.
- **Repetition note:** model was trained with aggressive n-gram-window repetition filters; the model card warns this *"may affect certain constrained generation scenarios"*. Translation: forcing the model to vary phrasing across turns is *more* likely to work on Nemotron than on a vanilla Llama, but constrained-decoded loops that repeat tokens may misbehave.

---

## Phase 4 — Recommendation (the 1-page synthesis)

### The dragon

**State misclassification on a safety-critical utterance.** ("They're not responding" → wrong intent → contractual obligation to phrase the wrong thing.) The user's FSM proposal makes the agent *more confident* about an answer it doesn't have authority to be confident about. An LLM with a hedged prior recovers; an FSM with a wrong label commits. For a 911-themed public demo where the worst-case clip is the one that gets shared, this is the single biggest risk.

### Recommended approach — G first, then B

**Day-of (next 2 hours):**

1. **Option G (30 min):** worker.py computes 4-5 booleans per turn (address captured, reassurance delivered, recent phrases, pronouns known, cardiac-arrest two-question step) and injects them as a runtime-state preamble *above* the existing FAST_DISPATCHER_SYSTEM_PROMPT. Lifts the LLM's job from "remember and compute" to "act on attested state". Zero risk to cycle-2d/2e hot path. Latency impact: +1-2 ms regex parse, no extra LLM call.

   - Fixes: stuck phrasing (state.recent_phrases hint), repeated filler (state.reassurance_delivered latched), AHA two-question CPR (state.cardiac_arrest_confirm_step gates the existing CPR script).
   - Probabilistically reduces gender bug (state.pronouns_known='they/them' attested).

2. **Option B (60-90 min, after G ships and is verified):** add a 50-LoC post-hoc check on the LLM reply. If `pronoun in {him, his, he, she, her, hers}` and `state.pronouns_known='they/them'`, regenerate with explicit retry hint: *"Use neutral pronouns — gender unknown."* Repetition check: if reply contains any phrase from `state.recent_phrases` with >70% n-gram overlap, regenerate with hint *"Vary the phrasing."* Worst case ~10% of turns hit a regenerate, +500 ms.

   - Deterministically fixes the gender bug.
   - Belt-and-suspenders on the repetition bug.

**FSM is deferred** until G+B are validated under real-call conditions. If the live-listen test post-G+B still shows the same 4 bugs, *then* re-open the FSM design with a flag-gated rollout that preserves the cycle-2d hot path verbatim and persists state to Redis.

### Implementation order (bisect)

1. (T+0:00) G prompt + worker state injection. ~20 LoC. Push behind `PRISM42_CYCLE_2Q_STATE=1` env flag, default OFF, parallel to cycle-2e flag pattern at orchestrator.py:406.
2. (T+0:30) Live-call smoke test. Verify the 4 bugs visibly improve. If yes, flip the flag default to ON for the demo.
3. (T+0:45) B structured-output pronoun + repetition guards. Same flag, separate sub-flag `PRISM42_CYCLE_2Q_GUARD=1` so they can be toggled independently.
4. (T+1:30) Live-call smoke test. Verify gender bug is gone deterministically. Done.

**Hard ceiling: T+2:00.** If anything is unstable at T+1:00, revert flags, ship cycle-2e baseline, accept the 4 bugs as known issues for the demo with a one-line caveat ("Synthetic fixtures only — see banner"). Munger's rule: *"It is remarkable how much long-term advantage people like us have gotten by trying to be consistently not stupid, instead of trying to be very intelligent."*

### Don't list (Munger inversion of the build plan)

1. **Don't ship a hand-coded FSM today.** F1+F4+F5 dominate; no time for a second iteration; the demo is hours away.
2. **Don't add a second LLM call per turn (option E).** Latency budget is gone; §0 says latency is a feature. Two calls = blocking.
3. **Don't enable guided_regex or guided_json without a fallback.** vLLM + Nemotron-NVFP4 + FLASHINFER_CUTLASS + guided-decoding is unproven on B300 sm_103. Behind a flag, with a no-guidance fallback, is the only safe shape.
4. **Don't touch the cycle-2d Fish FA patch (PASS_2D, 3.0× warm RTF) or cycle-2e BufferedDispatcherAgent.** Both gains are env-flag-isolated for a reason. Anything new ships parallel-flagged.
5. **Don't tell the LLM the intent is X.** That's the wrong-answer trap. Tell it the *state* (address captured, reassurance delivered, pronouns known) and let it pick the next move.
6. **Don't promise "verification before CPR" as a categorical rule.** AHA T-CPR is two questions then go, target <150 s call-to-first-compression. The existing override at orchestrator.py:359-362 is closer to AHA-correct than a deeper verification tree would be — modify it to ensure the two AHA questions ("conscious?" and "breathing normally?") have been asked, not to add 4-8 s of additional dialogue.
7. **Don't skip the env-flag.** Every cycle-2 finding ships behind a flag (`PRISM42_CYCLE_2E_BUFFER`, `PRISM42_ENABLE_TTS_PROSODY_TAGS`); cycle-2Q ships behind one too. Default OFF, flip ON for demo, flip OFF if anything is wrong.
8. **Don't break the file-backed greeting or the MW reference voice.** Both are sibling-cycle outputs feeding cycle2N_mw_reference and cycle2P_greeting_file artifacts; the option-G state-injection lives upstream of both.
9. **Don't do `git add -A`** (per CLAUDE.md §6 + user MEMORY.md hard rule). Stage `worker.py`, `orchestrator.py` (only if a comment update is required — prefer none), and the new findings file by name.

### Single-paragraph rationale to the coordinator

The user reports 4 bugs that all reduce to one structural gap: the LLM is being asked to recompute conversation-state from scratch every turn, and Nemotron-3-Nano's 70.7 IFBench score isn't high enough to do this perfectly across the demo. The fastest robust win is to compute the state in the worker (deterministic, ~1 ms) and inject it into the prompt as attested truth, reducing the LLM's job from "remember and decide" to "act on flags and pick the next move". A hand-coded FSM does the same thing but with a worse prior (commits to an intent label) and more new surface area for new bugs. The structured-output pronoun guard (option B) deterministically fixes the one bug that prompt-engineering alone can't guarantee. FSM stays on the roadmap but post-hackathon, behind a flag, with Redis-persisted state — not on demo day with hours to ship.

---

## Sources

- [https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 — fetched 2026-04-26] (IFBench 70.7, sampling guidance, repetition-filter caveat)
- [https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html — fetched 2026-04-26] (tool-calling launch flags, qwen3_coder parser)
- [https://vllm.ai/blog/run-nvidia-nemotron-3-nano — fetched 2026-04-26] (benchmark portfolio: SWE-bench Verified, GPQA Diamond, AIME 2025, Arena Hard v2, IFBench; thinking-budget feature)
- [https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3 — fetched 2026-04-26] (tool-calling-with-reasoning-parsing broken in some configs)
- [https://github.com/vllm-project/vllm/releases — fetched 2026-04-26] (vLLM 0.20 xgrammar/outlines guided-decoding, B300 allreduce fusion)
- [https://github.com/vllm-project/vllm/issues/34249 — fetched 2026-04-26] (FP8 MoE backend auto-selection bug on Hopper)
- [https://github.com/vllm-project/vllm/issues/33333 — fetched 2026-04-26] (FLASHINFER_CUTLASS sm_120 unsupported)
- [https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures — fetched 2026-04-26] (AHA T-CPR: two-question recognition then immediate dispatch, <150 s benchmark)
- [https://www.anthropic.com/engineering/managed-agents — fetched 2026-04-23 per CLAUDE.md] (session as context-outside-window — applicable to F7 mitigation)
- [https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7 — fetched 2026-04-23 per CLAUDE.md] (Opus 4.7 is more literal, fewer silent generalizations — comparison anchor)
- Internal: `/Users/kiteboard/prism42/agents/livekit/orchestrator.py` (FAST_DISPATCHER_SYSTEM_PROMPT lines 227-387, BufferedDispatcherAgent line 128, cycle-2e flag line 406)
- Internal: `/Users/kiteboard/.claude/projects/-Users-kiteboard/memory/prism42_b300_voice_durable_findings.md` finding #6 (vLLM Nemotron MoE-backend instability — TRTLLM auto-select produces JS garbage; the unproven-stack risk that drives the don't-ship-guided-decoding-without-fallback recommendation)
