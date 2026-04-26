# System Prompt Spec — Nemotron-3-Nano structured classifier for PSAP

**Author:** Team C-Architect, prism42 cycle-2C.
**Sources:** Team N3 `prompt-template-spec.md` (chat template), schema.json (this directory), HF Nemotron model card sampling guidance, all fetched 2026-04-26.

The classifier is a single chat-completions call per caller turn. Reasoning is OFF. The output is a JSON object that conforms to `psap_classification.schema.json`. The model is being graded on classification, not prose.

---

## 1. Token-level skeleton (what vLLM emits at generation time)

Per Team N3 §4.3, with `chat_template_kwargs.enable_thinking=False` AND `response_format=json_schema`:

```
<|im_start|>system
{SYSTEM_PROMPT — see §3 below}<|im_end|>
<|im_start|>user
{caller_utterance}<|im_end|>
<|im_start|>assistant
<think></think>{model emits JSON object matching schema}<|im_end|>
```

The `<think></think>` empty pair is template-emitted (Team N3 §4.3) — the model never produces a reasoning trace. xgrammar's JSON-schema FSM activates immediately after `</think>` and constrains every subsequent token to match the schema.

---

## 2. Exact request body the worker will send

```python
import json
from pathlib import Path

SCHEMA = json.loads(
    (Path(__file__).parent / "psap_classification.schema.json").read_text()
)

# In structured_classifier.py (new file).
async def classify_async(client, utterance: str, *, seed: int = 0) -> dict:
    """Send one classifier turn; return parsed JSON dict matching SCHEMA.

    Caller's responsibility: pass-through schema validation + fallback.
    """
    response = await client.chat.completions.create(
        model="nemotron",  # alias for nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": utterance},
        ],
        # Schema-constrained JSON. xgrammar backend (vLLM auto).
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "psap_classification",
                "schema": SCHEMA,
                "strict": True,
            },
        },
        # MUST pair with reasoning OFF — see knowledge-base.md §3.1 (vLLM #37362).
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False},
        },
        # Greedy decode with seed for reproducibility. Classifier, not creative surface.
        temperature=0.0,
        seed=seed,
        # Generous budget. Schema renders to ~80-120 tokens of JSON; budget covers
        # the long-tail of address strings + null variants. Lower bound prevents
        # vLLM #30904 (empty content with tight max_tokens).
        max_tokens=192,
    )
    raw = response.choices[0].message.content
    return json.loads(raw)  # caller validates against SCHEMA
```

---

## 3. The system prompt (verbatim — copy/paste into worker.py constant)

The prompt is intentionally short (~250 tokens). Long monolith prompts dilute instruction following on the constraint that matters (Team N3 §4 R3 thesis applies here).

```text
You are a 911 PSAP utterance classifier. Read the caller's last
utterance and output ONE JSON object that matches the provided
schema EXACTLY. You are NOT the dispatcher — you do not speak to
the caller. You only classify.

OUTPUT RULES
- Output one JSON object. No prose, no markdown, no explanation.
- All schema fields are required. If a field is unknown, emit:
    string enums       -> "unknown"
    booleans            -> null  (NEVER guess; null = caller did not say)
    address_candidate.raw_text / normalized -> null
    address_candidate.has_digit -> false
- Do not invent. If the caller did not state a fact, the field is null
  or "unknown" — that is the correct answer, not a guess.
- 'awake' is true only if the caller affirmed the patient is awake.
  'breathing' is true only if the caller affirmed normal breathing.
  Gasping / agonal -> 'breathing': false. Unresponsive -> 'awake': false.
- 'negation_signal' is true if the caller's utterance CONTRADICTS the
  dispatcher's last question. E.g. dispatcher asked 'are they on the
  floor?' and caller said 'no, they're in a chair' -> negation_signal
  true AND surface "chair".
- 'caller_question' is true if the caller asked the dispatcher a
  question. 'direct_question_kind' is the sub-category — pick "none"
  when caller_question is false.
- 'intent' is the BROAD action category (intake / key_question /
  verify / instruct / answer / reprompt). The dispatcher's finite
  state machine picks the exact 21-value intent based on its current
  state plus your category. Do not try to pick the 21-value name.

EXAMPLES — caller utterance, then exact JSON to emit.

EXAMPLE 1
Caller: "9-1-1 my husband is having chest pain at four hundred twenty
one Maple"
JSON:
{"intent":"intake","acuity":"P1","address_candidate":{"raw_text":"four hundred twenty one Maple","normalized":"421 Maple","has_digit":true},"awake":null,"breathing":null,"surface":"unknown","caller_question":false,"caller_role":"third_party","complaint_category":"medical","negation_signal":false,"direct_question_kind":"none","confidence":0.95}

EXAMPLE 2
Caller: "yeah he's just lying there not breathing"
JSON:
{"intent":"verify","acuity":"P1","address_candidate":{"raw_text":null,"normalized":null,"has_digit":false},"awake":false,"breathing":false,"surface":"unknown","caller_question":false,"caller_role":"third_party","complaint_category":"medical","negation_signal":false,"direct_question_kind":"none","confidence":0.92}

EXAMPLE 3
Caller: "yeah, I mean they're in a chair"
JSON:
{"intent":"verify","acuity":"P1","address_candidate":{"raw_text":null,"normalized":null,"has_digit":false},"awake":null,"breathing":null,"surface":"chair","caller_question":false,"caller_role":"third_party","complaint_category":"medical","negation_signal":true,"direct_question_kind":"none","confidence":0.88}

EXAMPLE 4
Caller: "did you did you hear my address?"
JSON:
{"intent":"answer","acuity":"unknown","address_candidate":{"raw_text":null,"normalized":null,"has_digit":false},"awake":null,"breathing":null,"surface":"unknown","caller_question":true,"caller_role":"unknown","complaint_category":"unknown","negation_signal":false,"direct_question_kind":"did_you_hear","confidence":0.93}

EXAMPLE 5
Caller: "uh okay"
JSON:
{"intent":"reprompt","acuity":"unknown","address_candidate":{"raw_text":null,"normalized":null,"has_digit":false},"awake":null,"breathing":null,"surface":"unknown","caller_question":false,"caller_role":"unknown","complaint_category":"unknown","negation_signal":false,"direct_question_kind":"none","confidence":0.15}

OUTPUT ONLY THE JSON OBJECT.
```

### 3.1 Why these five examples specifically

| Example | What it teaches |
|---|---|
| 1 — chest pain + spelled cardinal address | (a) intake category, (b) third-party medical, (c) acuity P1 from chest-pain language, (d) the model SHOULD normalize "four hundred twenty one" → "421" in the `normalized` field even though the deterministic normalizer in dispatcher_fsm.py also runs — redundancy is fine, |
| 2 — explicit "not breathing" | (a) verify category, (b) `breathing: false`, (c) `awake: false` from "lying there", (d) `surface: "unknown"` (caller said "lying there" but did not specify floor — be honest, don't infer floor) |
| 3 — Bug 3 case | (a) `surface: "chair"` (the LLM extracts what the caller actually said), (b) `negation_signal: true` (the caller is contradicting the previous dispatcher question), (c) `caller_role: "third_party"` retained from earlier context — even though this single utterance does not say "they", the model must remember that the conversation is about a third party |
| 4 — Bug 1 case | (a) `caller_question: true`, (b) `direct_question_kind: "did_you_hear"`, (c) `intent: "answer"` — the broad category that routes to the FSM's ANSWER_HEARD_ADDRESS template, (d) `caller_role: "unknown"` because this single utterance is meta and does not indicate first/third party |
| 5 — Bug 2 case | (a) `intent: "reprompt"`, (b) `confidence: 0.15` (low) — the orchestrator can dispatch on this and skip merging the LLM features, (c) all other fields null/"unknown" — backchannels carry no signal |

These five examples cover the three Team R3 bugs explicitly. Adding more examples reduces the prefill cost benefit; five is the minimum we need to demonstrate the schema's tri-state and negation discipline.

---

## 4. Multi-turn context — does the classifier need history?

The classifier is per-utterance. **It does NOT receive prior turns by default.** Reasons:

1. **Cost.** Each prior turn adds ~50-100 tokens of prefill. For a 10-turn call that is +500-1000 tokens per classifier call — 1.5-3 ms prefill at our pod rate, negligible numerically but compounding once we measure end-to-end p95.
2. **Determinism.** A stateless classifier per turn is easier to test, audit, and replay. The FSM holds the state; the classifier observes the local utterance.
3. **Stale-state risk.** If we replay history into the classifier and the FSM has corrected an earlier classification, the classifier's view diverges from the FSM's view — a bug class we do not need.

**Exception (Example 3 above):** caller_role is the only field where the LLM benefits from history. We handle this by **prefixing the user message with the FSM's current caller_role belief**:

```python
# In structured_classifier.classify_async, BEFORE the api call:
context_hint = f"[fsm_state: caller_role={fsm.caller_role}, last_dispatcher_question={fsm.last_intent.value if fsm.last_intent else 'none'}]"
user_content = f"{context_hint}\n{utterance}"
```

The hint is ~30 tokens, hard-formatted, parsed by no one — it is purely a few-shot conditioning prefix the model is trained to attend to. Crucially the LLM's caller_role output is still ADVISORY; the FSM's actual caller_role state is what matters. If the LLM emits "first_party" but the FSM has already latched "third_party" from a prior turn, the merge rule (knowledge-base.md §6) keeps third_party.

The hint prefix is the simplest path that makes Example 3 work in a pure no-history setup. Alternatives (pass `messages=[prior turns]`) are deferred — measure first.

---

## 5. Sampling parameters

| Param | Value | Justification |
|---|---|---|
| `temperature` | `0.0` | Greedy. Classifier is not a creative surface. The xgrammar FSM is the constraint; sampling at temperature 0 picks the highest-prob token at each masked position. Reproducible across pods given fixed `seed`. |
| `seed` | `0` (or per-session deterministic) | Reproducibility for replay debugging. Ignored by Opus 4.7 (which removed `seed`) but honored by vLLM (Team N3 §1 Identity — Nemotron retains it). |
| `top_p` | omitted | Greedy makes top_p moot; sending it is harmless but adds noise to the request. |
| `max_tokens` | `192` | Schema renders to ~80-120 tokens; +50 % headroom. Avoids vLLM #30904 (empty content) and never truncates a long address string. |
| `chat_template_kwargs.enable_thinking` | `False` | HARD requirement — paired with `response_format` to avoid vLLM #37362. See knowledge-base.md §3.1. |
| `response_format` | json_schema(strict=True) | OpenAI standard shape. `strict: True` enforces `additionalProperties: false` at the grammar level. |

Note vs Nemotron model card guidance (Team N3 §6.3): the card recommends `temperature=0.6, top_p=0.95` for tool-calling and `temperature=1.0, top_p=1.0` for reasoning. Neither applies here — we are doing schema-constrained classification, not reasoning and not tool-calling. Greedy decoding under a hard FSM mask is the canonical pattern.

---

## 6. Token-budget arithmetic

| Component | Tokens |
|---|---|
| System prompt (§3 above) | ~250 |
| User message (utterance + caller_role hint) | ~30-100 |
| Empty `<think></think>` | 2 |
| JSON output | ~80-120 |
| **Total per turn** | **~360-470** |

vs Team N3's R2+R3 path (160-180 tokens): the classifier is ~2.5x larger because of the schema-conditioning examples. But the LLM-fallback in cycle-2T (the `REPROMPT` path) is ~1010 tokens total. So the structured classifier on EVERY turn costs less than the LLM-fallback on a SUBSET of turns. Net: same or better cumulative LLM cost, plus we get features for every turn.

---

## 7. Prompt-quality validation steps (offline, before live)

Before integrating, the integrator must:

1. Run the system prompt + each of the 5 examples through `tests/voice/test_structured_classifier_offline.py` (new) using a mock vLLM endpoint that ignores the model and returns the schema-default. This proves the request body shape is correct.
2. Run against the real B300 vLLM endpoint with each of the 5 example utterances and check:
   - Output is valid JSON (jsonschema-validates against SCHEMA).
   - For Example 4 ("did you hear..."), `direct_question_kind == "did_you_hear"` AND `caller_question == true`.
   - For Example 3 ("in a chair"), `surface == "chair"` AND `negation_signal == true`.
   - For Example 5 ("uh okay"), `confidence < 0.4`.
3. Stress test with 50 synthetic-caller utterances from cycle-2T regression set (`tests/voice/fixtures/synthetic_caller_*.txt`). Manually score:
   - Per-field accuracy ≥ 90 % on each enum.
   - `confidence` calibration — inspect distribution; flag if all replies cluster ≥0.95 (over-confident) or all <0.5 (under-confident).
   - JSON-validity rate ≥ 99 % (the FSM grammar should make this 100 %; below 99 % means xgrammar bug).
4. Latency probe: measure TTFT and total time for 20 calls. Expected: TTFT ~50 ms, total ~280 ms (~120 tokens at 313 tok/s + xgrammar ~3-5 ms overhead).

If steps 2-3 fail, the prompt needs more examples or shorter constraints. Step 4 failure is a deeper symptom — likely vLLM env regression.

---

## 8. What this prompt does NOT do

- Does not classify Spanish or other-language utterances. Out of scope; deferred.
- Does not extract a "list of facts the caller stated" — keeps to schema fields. Free-text extraction is the regex's job.
- Does not produce dispatcher prose. The model is forbidden from speaking to the caller; the schema has no `reply_text` field.
- Does not call tools. `tools=[]` (omitted) — see knowledge-base.md §3.2.
- Does not mutate FSM state. Side-effect-free; the orchestrator merges into Features.

---

## 9. References

- Team N3 prompt-template-spec.md (chat template, sampling baseline)
- knowledge-base.md (this directory) §3.1 (mandatory `enable_thinking=False` pairing)
- schema.json (this directory)
- vLLM stable Structured Outputs: <https://docs.vllm.ai/en/stable/features/structured_outputs.html> (fetched 2026-04-26)
- HF Nemotron-3-Nano BF16 model card sampling guidance: <https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16> (fetched 2026-04-26)
- vLLM issue #37362: <https://github.com/vllm-project/vllm/issues/37362> (fetched 2026-04-26)
- vLLM issue #30904: <https://github.com/vllm-project/vllm/issues/30904> (fetched 2026-04-26)
