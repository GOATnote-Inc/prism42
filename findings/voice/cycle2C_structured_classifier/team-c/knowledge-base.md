# Knowledge Base — vLLM `guided_json` for Nemotron-3-Nano structured classification

**Author:** Team C-Architect, prism42 cycle-2C
**Charter:** READ-ONLY research; no code in `agents/livekit/`.
**Fetch date for every external citation:** 2026-04-26.
**Companion docs:** Team N3 `nemotron-knowledge-base.md` (model + chat template), Team T `design.md` (FSM + 21 templates), Team R3 `diagnosis.md` (3 live bugs).

---

## 1. The shift in one sentence

Today Nemotron is asked to GENERATE the dispatcher reply prose under a 4 KB constraint manual. Tomorrow Nemotron is asked to CLASSIFY the caller's last utterance into a structured `{intent, acuity, awake, breathing, surface, …}` JSON object, the FSM consumes those structured features, and `templates.py` renders the deterministic reply. The LLM moves from "dispatcher" to "classifier" — the role it is statistically much better at (BFCL 53.8 + IFBench 71.5 vs free-form prose where 30 % of constraints leak; Team N3 §3).

This is the "supervisors not dispatchers" pivot. The deterministic FSM + templates is the spine; the LLM is a feature extractor on the side.

---

## 2. vLLM structured outputs — current syntax (vLLM 0.20.x, our pinned build)

Source: [vLLM stable docs — Structured Outputs](https://docs.vllm.ai/en/stable/features/structured_outputs.html), [vLLM latest docs](https://docs.vllm.ai/en/latest/features/structured_outputs.html), [vLLM v0.10.1 docs](https://docs.vllm.ai/en/v0.10.1/features/structured_outputs.html), all fetched 2026-04-26.

### 2.1 Two API surfaces

vLLM exposes structured output through **two equivalent surfaces** in the OpenAI-compatible chat-completions endpoint:

**(A) OpenAI-standard `response_format` (recommended for portability):**

```python
completion = client.chat.completions.create(
    model="nemotron",
    messages=[{"role": "system", "content": SYSTEM},
              {"role": "user",   "content": utterance}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "psap_classification",
            "schema": SCHEMA_DRAFT_07_DICT,
        },
    },
)
```

**(B) vLLM-native `extra_body.guided_json` (older, still works):**

```python
completion = client.chat.completions.create(
    model="nemotron",
    messages=[...],
    extra_body={"guided_json": SCHEMA_DRAFT_07_DICT,
                "chat_template_kwargs": {"enable_thinking": False}},
)
```

Both reach the same FSM-decoding path inside vLLM; `response_format` is a convenience wrapper that the OpenAI server routes to `guided_json` internally. **Decision (deferred to integration plan):** use `response_format`. It is the OpenAI-standard shape, the LiveKit `livekit-plugins-openai` plugin already understands `extra_body` for the `enable_thinking` toggle (Team N3 §5), and `response_format` survives an SDK upgrade unchanged.

### 2.2 The five constraint shapes

vLLM advertises five guided-decoding parameters (stable docs §"Structured Outputs"):

| Param | Use | Our use |
|---|---|---|
| `choice` | output is one of a fixed list | not used (we want multi-field JSON) |
| `regex` | output matches a regex | already in scope for cycle-2T2 LLM-fallback (see Team R3 R5); not used here |
| `json` | output matches a JSON Schema | **YES — this is the cycle-2C surface** |
| `grammar` | output matches an EBNF grammar | overkill |
| `structural_tag` | JSON inside HTML/XML tags | not applicable |

We use `json`. JSON Schema Draft-07 is supported (vLLM uses xgrammar's Draft-07 compiler).

### 2.3 Backends

vLLM stable docs name three structured-output backends: **`xgrammar`**, **`guidance`**, **`outlines`** (also referenced: `lm-format-enforcer`). Default is `auto` which selects per-request — usually xgrammar for a JSON Schema. xgrammar's own README claims "near-zero overhead in JSON generation" ([xgrammar README](https://github.com/mlc-ai/xgrammar) fetched 2026-04-26). The vLLM docs do not publish a backend benchmark.

**Pick:** stay on `auto` (xgrammar). Reasons:

1. xgrammar is the vLLM default and gets the most upstream attention.
2. Our schema is small (~10 fields) and shallow (no nested objects). xgrammar's compile time on Draft-07 schemas this size is sub-millisecond per session — irrelevant compared to the 50 ms vLLM TTFT we already measure.
3. `outlines` is the older path; `lm-format-enforcer` is a regex-only fallback not relevant for JSON Schema; `guidance` is a Microsoft project with worse vLLM integration (vLLM issue #37362 specifically calls out "guidance" as the broken-with-reasoning backend — see §3.1 below).

We do NOT need to set `--guided-decoding-backend` explicitly. If we ever need to (e.g. a regression where xgrammar mishandles a Draft-07 keyword), the vLLM serve flag is `--structured-outputs-config.backend xgrammar`.

### 2.4 What `response_format` actually constrains

The model emits **tokens that match the JSON schema FSM, starting from the very first generation step**. xgrammar / outlines compile the schema into a token-level mask that vLLM applies inside the sampler. Concretely:

- Field order: any order is valid by Draft-07; the schema tells the FSM which keys are still unfilled at any position.
- Enums: at the value position for an `enum` field, only tokens that prefix one of the enum strings are unmasked.
- Booleans: only `true` / `false` (and optionally `null` if the field is `nullable`) tokens are unmasked.
- Numbers: only digits, decimal points, signs, and exponents are unmasked at number positions.

This is a **hard guarantee on the parse-ability** of the output; it is NOT a guarantee on the **semantic correctness** of the value (the model can still classify intent wrongly). Munger inversion §1 below addresses this.

---

## 3. Nemotron-specific gotchas

### 3.1 Guided-output during `<think>` is broken

Source: [vllm-project/vllm#37362](https://github.com/vllm-project/vllm/issues/37362) opened 2026-03-18, **unresolved as of 2026-04-26**. The issue is: when `guided_json` is set AND `enable_thinking=True` (default), xgrammar's FSM applies the JSON grammar starting from the very first emitted token — including the `<think>` block tokens. The model emits 8192 `{` characters and never reaches the JSON proper. vLLM bug, not Nemotron bug.

**Workaround that we use:** **always pair `response_format` with `chat_template_kwargs: {enable_thinking: False}`** in the same request body. Already on for the voice path (worker.py:706). With reasoning OFF the structural-output FSM activates after the empty `<think></think>` pair (which is template-emitted, not model-emitted), so the constraint applies only to the user-visible content. This is the correct combination.

This is a hard precondition: **the structured-classifier mode does not work without `enable_thinking=False`.** Failure mode if violated: empty / garbage classification, full max_tokens consumed in a `{` storm. Schema validation in our `structured_classifier.py` would catch and fall back to the regex path; but the latency penalty (256 tokens at 313 tok/s = 800 ms wasted) is unacceptable. The integration plan §3 mandates this pairing.

### 3.2 Nemotron tool-calling parser does not interfere

We are NOT using `tools=[...]`. The classifier output is plain JSON in `choice.message.content`, not in `choice.message.tool_calls`. Therefore:
- The `qwen3_coder` tool-call parser is bypassed.
- The `nano_v3` reasoning parser sees `<think></think>` (empty) followed by `{...}` and returns `{...}` in `content`.
- No `str_replace_editor` hallucination risk (Team N3 §8.5) — that bug only fires when `tools=[...]` is non-empty.

### 3.3 Empty-content bug (vLLM #30904)

Source: [vllm-project/vllm#30904](https://github.com/vllm-project/vllm/issues/30904). With `enable_thinking=False` and a tight `max_tokens` (~32), the model occasionally exits the empty-think block and STOPS without emitting `content`. Result: `content == ""`. Mitigation: `max_tokens >= 96` for the classifier (our schema realistically renders to ~80-120 tokens of JSON; budget is generous). This budget bumps end-to-end latency by < 5 ms vs `max_tokens=64` because the model does not actually emit unused tokens, only the budget is wider. Already addressed by the schema-design choice in §6 below to keep field count modest.

### 3.4 Determinism

Opus 4.7 lost determinism (`seed` removed). **Nemotron retains it** — vLLM's OpenAI server honors `seed`. For the classifier path we recommend `seed=0, temperature=0.0, top_p=1.0` to make the structured output reproducible across pods and across replays. Sampling is not a creativity surface here; it is a classifier head. Greedy decoding under the JSON grammar is what we want.

(Caveat: vLLM batched decoding with seed-pinning is reproducible per-batch but not across batches with different concurrent traffic. For our 1-call-per-turn voice path with `max_num_seqs=1` decoding budget, this is moot.)

### 3.5 Context budget under structured output

Schema-based decoding adds a constant prefill cost: the schema FSM is compiled once per session and cached. xgrammar compile is single-digit milliseconds for our size. There is no per-token prefill regression vs unconstrained generation; xgrammar's "near-zero overhead" claim is consistent with the vLLM blog framing. Decode-time per token is ~5-10 % slower because the sampler does an extra mask lookup. For our 80-120 token JSON output at 313 tok/s, the absolute cost is ~25-40 ms decode (vs ~25-38 ms unconstrained) — a ~3 ms tax. Negligible vs the 150-950 ms reasoning-trace cost we already removed.

---

## 4. JSON Schema Draft-07 — the keywords we need

Source: [json-schema.org/draft-07/schema](https://json-schema.org/draft-07/schema) fetched 2026-04-26.

Confirmed-supported keywords (vLLM xgrammar): `type`, `properties`, `required`, `additionalProperties`, `enum`, `const`, `oneOf`, `anyOf`, `nullable` (via `type: ["string", "null"]`), `pattern`, `minimum`, `maximum`, `minLength`, `maxLength`, `description`, `title`. Type values: `array | boolean | integer | null | number | object | string`.

**Schema-design rules we will follow** (from Pydantic structured-output best practice + our voice latency budget):

1. **Flat, no nested objects.** Every nesting level adds JSON-grammar branches the model has to navigate. Keep the schema 1 level deep.
2. **Always `additionalProperties: false`.** Stops the model from inventing extra fields under the JSON-grammar's permissive default.
3. **Always `required`.** Every classifier field must be present — even if the value is `null` or `"unknown"`. The regex fallback in dispatcher_fsm.py treats absence and presence-with-default identically; missing fields would force an extra defensive pass.
4. **Enums everywhere a categorical fits.** `intent`, `acuity`, `surface`, `caller_role`, `complaint_category`, `direct_question_kind`. Booleans for the truly binary fields (`awake`, `breathing`, `caller_question`, `negation_signal`).
5. **Tri-state booleans via `["boolean", "null"]`.** The user's spec explicitly uses `true|false|null` for `awake` and `breathing` — null means "caller did not state, do not infer". Schema expression: `{"type": ["boolean", "null"]}`. xgrammar handles this.
6. **`description` per field.** The schema is sent to the model as part of the response_format payload AND can be referenced in the system prompt via few-shots. Descriptions help the model (Pydantic structured-output recipe; OpenAI structured-outputs guide both recommend it).
7. **`confidence: number` with `minimum: 0, maximum: 1`.** Single scalar — see schema-design discussion in `schema.json` for why one float, not per-field.

---

## 5. Anthropic-style harness pattern: LLM-as-classifier, not LLM-as-actor

Source: [Anthropic engineering — Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) fetched 2026-04-26 (Prithvi Rajasekaran, 2026-03-24).

Verbatim quote: *"Separating the agent doing the work from the agent judging it proves to be a strong lever."* Cycle-2C re-frames this as: separate the agent CLASSIFYING the inputs from the deterministic engine ACTING on the classification.

Mapping to our stack:

| Role | Today | Cycle-2C |
|---|---|---|
| Classifier (caller utterance → structured features) | regex `classify()` only | regex `classify()` AND Nemotron `guided_json` |
| Decider (features → next intent) | FSM `transition()` | FSM `transition()` (unchanged) |
| Actor (intent → speakable text) | template OR LLM prose | template (cycle-2T) |
| Critic (post-hoc audit) | none | Claude Opus 4.7 async (Team B-Critic) |

Cycle-2C sits at the classifier seat. The FSM does not change shape; it gets a richer `Features` dataclass populated from JSON instead of regex. The actor is unchanged (cycle-2T templates already deterministic). The critic is parallel work — Team B-Critic.

### 5.1 Why classifier > actor for Nemotron

1. **BFCL v4 = 53.8 vs IFBench prose = 71.5** (Team N3 §3). The model is materially better at producing structured JSON than at honoring 4 KB of free-form constraints. The 53.8 figure is on a generic function-calling eval; PSAP is narrower (8-10 categorical fields) and Nemotron will outperform that ceiling. Numerical estimate (defensible upper bound): 90-95 % per-field correctness on first emit, 99 %+ when grammar-constrained AND the FSM regex is allowed to override the LLM on disagreement.
2. **The 30 % IFBench prose-violation rate becomes a `null` field, not a "dial 911" disclaimer.** When the model isn't confident about `surface`, it emits `"unknown"` or null. The FSM's regex fallback fills the gap. The voice path never speaks the LLM's mistake.
3. **Confidence is grounded.** The model emits `confidence: 0.0-1.0` on each turn. The integration plan can dispatch on confidence: high → trust the LLM features; low → fall back to regex; very low → REPROMPT. We have NO such signal today — every prose reply is delivered with the same (unknown) trust level.

---

## 6. What the cycle-2C surface looks like end-to-end

```
caller-audio → Parakeet STT → utterance string
                                  │
              ┌───────────────────┴───────────────────┐
              ▼                                       ▼
  deterministic normalizer            Nemotron structured-classifier
  (cycle-2P2 spelled-cardinal)        (vLLM response_format=json_schema)
              │                                       │
              ▼                                       ▼
            regex classify()  ──── merge ───────►  llm_features
                                  │
                          merged Features dataclass
                                  ▼
                       FSM.transition(features)  ◄── cycle-2T response gate
                                  │
                                  ▼
                       templates.render(intent)  ────► Fish TTS
                                  │
                                  └──── (in parallel) ────► Claude critic (Team B)
```

Key invariants:

- **Normalizer is FIRST**, not replaced. The cycle-2P2 spelled-cardinal pass mutates `"one hundred ocean of new"` → `"100 ocean of new"` before any feature extractor sees it. Both regex `classify()` AND the LLM classifier see the normalized string. Reasons: address-digit recognition is a deterministic invariant we already trust; LLM should not relitigate it.
- **Regex `classify()` runs always.** It is the floor. The LLM features ADD signal; they do NOT replace the regex output. Merge rule (justified in `schema.json` notes): **regex wins on hard signals (`has_address`, `has_emergency`, `not_breathing`, `floor_flat`, `gasping`, `breathing_normal`); LLM wins on soft signals (`acuity`, `caller_role`, `surface`, `negation_signal`, `direct_question_kind`).** Disagreement on hard signals is a structured log, not a behavior change.
- **FSM consumes a strictly-superset Features.** New fields are additive. When the env flag is OFF, the new fields are all default values, the FSM behaves identically to today.

---

## 7. Default-OFF env flag + backwards-compat

The integration plan §4 specifies `PRISM42_ENABLE_STRUCTURED_CLASSIFIER=1` as the gate. When OFF (default), `worker.py` does not pass `response_format` and `orchestrator.py` does not invoke the LLM-classifier path; `Features` are populated by regex `classify()` only. Byte-for-byte equivalent to today.

When ON, the worker call site sends `response_format` AND `chat_template_kwargs.enable_thinking=False`; the orchestrator's `on_user_turn_completed` invokes a new `structured_classifier.classify_async(utterance)` BEFORE `fsm.transition`, merges into the Features, and proceeds.

This mirrors the cycle-2T pattern (`PRISM42_ENABLE_RESPONSE_GATE=1`) — same shape, same rollback semantics, same single-flag rollout discipline.

---

## 8. Critical sources (all fetched 2026-04-26)

- vLLM stable structured outputs: <https://docs.vllm.ai/en/stable/features/structured_outputs.html>
- vLLM latest structured outputs: <https://docs.vllm.ai/en/latest/features/structured_outputs.html>
- vLLM v0.10.1 structured outputs: <https://docs.vllm.ai/en/v0.10.1/features/structured_outputs.html>
- vLLM Nemotron-3-Nano recipe: <https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html>
- vLLM v0.20.0 release notes: <https://github.com/vllm-project/vllm/releases/tag/v0.20.0>
- vLLM issue #37362 (guided-output during think broken): <https://github.com/vllm-project/vllm/issues/37362>
- vLLM issue #30904 (empty content): <https://github.com/vllm-project/vllm/issues/30904>
- xgrammar README (near-zero overhead claim): <https://github.com/mlc-ai/xgrammar>
- outlines README: <https://github.com/dottxt-ai/outlines>
- JSON Schema Draft-07: <https://json-schema.org/draft-07/schema>
- Anthropic harness design (generator-evaluator separation): <https://www.anthropic.com/engineering/harness-design-long-running-apps>
- HF Nemotron-3-Nano BF16 model card: <https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16>
- HF discussion #3 (tool-calling + reasoning bug): <https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3>

Internal:
- Team N3 nemotron-knowledge-base.md
- Team N3 prompt-template-spec.md
- Team N3 recommendations.md
- Team T design.md
- Team R3 diagnosis.md
- Team R3 fix-candidates.md
- agents/livekit/dispatcher_fsm.py:113-141 (Intent enum), :228-254 (Features), :343-387 (classify())
- agents/livekit/templates.py:106-244 (TEMPLATES, 21 entries)
- agents/livekit/orchestrator.py:324-492 (on_user_turn_completed)
- agents/livekit/worker.py:680-707 (LLM construction site)
