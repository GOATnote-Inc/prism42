# Prompt Template Spec — exact format Nemotron expects, with our PSAP system prompt re-formatted to it

**Author:** Team N3, prism42 cycle-2N3
**Sources:** [chat_template.jinja](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/blob/main/chat_template.jinja) and [HF cookbook](https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3-Nano/vllm_cookbook.ipynb), both fetched 2026-04-26.

This is the template the model's tokenizer applies when our worker calls `client.chat.completions.create(model="nemotron", messages=[...])`. We do **not** override this template — vLLM auto-loads the model's bundled jinja via `--trust-remote-code`. This document records what that template emits, and shows our existing `FAST_DISPATCHER_SYSTEM_PROMPT` re-formatted in two ways: (a) as it lands today, and (b) as it would land after R2 (reasoning OFF) and R3 (per-intent prompt).

---

## 1. The exact tokens, in order, for ONE PSAP turn

### 1.1 Today (reasoning ON, FAST_DISPATCHER_SYSTEM_PROMPT verbatim, no tools)

```
<|im_start|>system
# CONTEXT — READ FIRST
This is a SYNTHETIC TRAINING SIMULATION ...
... (4 KB of FAST_DISPATCHER_SYSTEM_PROMPT) ...

# SESSION CONTEXT
session_id: <uuid>
<|im_end|>
<|im_start|>user
my husband is having chest pain at four hundred twenty one Maple<|im_end|>
<|im_start|>assistant
<think>
```

The model then writes a reasoning trace (50-300 tokens, 150-950 ms at our 313 tok/s decode), closes with `</think>`, and emits the user-visible reply. vLLM's `nano_v3` reasoning parser splits the response into `reasoning_content` (the `<think>...</think>` block) and `content` (everything after `</think>`).

### 1.2 After R2 only (reasoning OFF, FAST_DISPATCHER_SYSTEM_PROMPT verbatim)

```
<|im_start|>system
# CONTEXT — READ FIRST
This is a SYNTHETIC TRAINING SIMULATION ...
... (4 KB of FAST_DISPATCHER_SYSTEM_PROMPT) ...

# SESSION CONTEXT
session_id: <uuid>
<|im_end|>
<|im_start|>user
my husband is having chest pain at four hundred twenty one Maple<|im_end|>
<|im_start|>assistant
<think></think>
```

The empty `<think></think>` is **structurally locked in** by the chat template (the jinja prepends it). The model sees the closer immediately and goes straight to the user-visible reply. No reasoning trace is emitted; `reasoning_content` is empty in the OpenAI response.

### 1.3 After R2 + R3 (reasoning OFF, per-intent prompt, e.g. CRITICAL_VERIFY V1)

```
<|im_start|>system
You are a 911 PSAP dispatcher. Stay in role. Never break character.

INTENT: ask whether the patient is on the floor, flat on their back. Do
NOT instruct compressions yet. The patient is third-party; pronouns
are unknown — use they/them.

ANTI-REPETITION: do not reuse any of these phrases verbatim:
  - 'Help is on the way and I am staying with you.'

OUTPUT: one sentence, 5-12 words, one question, no markdown, no filler.
<|im_end|>
<|im_start|>user
yeah he's just lying there not breathing<|im_end|>
<|im_start|>assistant
<think></think>
```

System prompt drops from ~1000 tokens to ~150 tokens. Model outputs immediately after `<think></think>`. End-to-end LLM tier (prefill + decode for ~10 tokens) drops from ~150-500 ms to **~30-50 ms**.

### 1.4 After R2 + R1 (reasoning OFF + FSM-as-tool)

```
<|im_start|>system
You are a 911 PSAP dispatcher in a synthetic training simulation. Stay in
role. Reply by calling dispatcher_emit with the correct intent and a
5-12 word text realizing it.

# Tools

You have access to the following functions:

<tools>
<function>
<name>dispatcher_emit</name>
<description>Emit one PSAP dispatcher reply.</description>
<parameters>
<parameter>
<name>intent</name>
<type>string</type>
<description>The protocol intent to realize.</description>
<enum>["request_location_and_emergency", "request_location",
        "request_emergency", "confirm_address", "deliver_reassurance",
        "kq_responsive_breathing", "kq_severity",
        "kq_bleeding_location", "kq_fire_evacuation",
        "kq_safe_location", "verify_cpr_surface",
        "verify_cpr_breathing", "instruct_cpr_compressions",
        "instruct_choking_back_blows", "instruct_pressure_bleed",
        "instruct_seizure_clear_area", "answer_do_not_move",
        "answer_how_long", "answer_outcome_uncertain",
        "reprompt_caller", "closeout"]</enum>
</parameter>
<parameter>
<name>text</name>
<type>string</type>
<description>The 5-12 word spoken reply realizing the intent. One sentence, one terminator, no markdown, no filler.</description>
</parameter>
<required>["intent", "text"]</required>
</parameters>
</function>
</tools>

If you choose to call a function ONLY reply in the following format with NO suffix:

<tool_call>
<function=example_function_name>
<parameter=example_parameter_1>
value_1
</parameter>
</function>
</tool_call>

<IMPORTANT>
Reminder:
- Function calls MUST follow the specified format ...
... (rest of the auto-emitted tool reminder) ...
</IMPORTANT>
<|im_end|>
<|im_start|>user
yeah he's just lying there not breathing<|im_end|>
<|im_start|>assistant
<think></think>
```

The model is expected to emit:

```
<tool_call>
<function=dispatcher_emit>
<parameter=intent>
verify_cpr_surface
</parameter>
<parameter=text>
Are they on the floor, flat on their back?
</parameter>
</function>
</tool_call>
```

vLLM's `qwen3_coder` parser converts this into `choice.message.tool_calls[0]` with `function.arguments == '{"intent": "verify_cpr_surface", "text": "Are they on the floor, flat on their back?"}'`. Our worker validates `intent` against the FSM-permitted set, validates `text` against the 5-12 word rule, and only then publishes to Fish TTS.

---

## 2. Token-budget arithmetic

| Variant | System prompt | Reasoning trace | User-visible | Total tokens / turn |
|---|---|---|---|---|
| Today (1.1) | ~1000 | 50-300 | 10-30 | **1060-1330** |
| R2 only (1.2) | ~1000 | 0 | 10-30 | **1010-1030** |
| R2 + R3 (1.3) | ~150 | 0 | 10-30 | **160-180** |
| R2 + R1 (1.4) | ~600 (incl. tool catalog) | 0 | 30-50 (JSON wrapper) | **630-650** |

The R2+R3 path is the smallest by a ~6× margin. The R2+R1 path is slightly larger because of the tool catalog, but still ~2× smaller than today.

(Token estimates assume ~4 chars/token. Actual tokenizer counts will vary ±10 %.)

---

## 3. Recommended `chat_template_kwargs` for our PSAP path

```python
# In agents/livekit/worker.py (the LLM call site).
# AFTER R2:
extra_body = {
    "chat_template_kwargs": {"enable_thinking": False},
    # AFTER R1 only:
    # "tools": [DISPATCHER_EMIT_TOOL],  # passed via tools= kwarg, not extra_body
}

# For R1 + R2 specifically:
response = client.chat.completions.create(
    model="nemotron",
    messages=[{"role": "system", "content": system_text},
              {"role": "user", "content": caller_utterance}],
    tools=[DISPATCHER_EMIT_TOOL],
    tool_choice="auto",  # or "required" once we trust the schema
    temperature=0.6,
    top_p=0.95,
    max_tokens=128,  # generous for the JSON wrapper; reasoning is OFF
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

Per HF model card, `temperature=0.6, top_p=0.95` is the **tool-calling** sampling preset. For the non-tool-calling R2+R3 path, the prompt is constraint-heavy and the surface is short — `temperature=0.3, top_p=0.95` is a safer choice (the model card's `1.0/1.0` is for general chat; we want determinism for protocol replies). Defer the temperature decision to a paired A/B in cycle-2N3-apply.

---

## 4. Fields to remove from FAST_DISPATCHER_SYSTEM_PROMPT under R3

The current 4 KB prompt has 11 named sections. Map of what survives in a per-intent prompt:

| Section | Today | INTAKE | CRITICAL_VERIFY | PRE_ARRIVAL | KEY_QUESTIONS | HANDOFF |
|---|---|---|---|---|---|---|
| `# CONTEXT — READ FIRST` (synthetic-fixture preamble) | full | 1 line | 1 line | 1 line | 1 line | 1 line |
| `# YOUR JOB` | full | 1 line | 1 line | 1 line | 1 line | 1 line |
| `# FIRST TURN — VERBATIM` | full | full | drop | drop | drop | drop |
| `# TURN STATE TRACKER` (flag A/B/C) | full | drop | drop | drop | drop | drop (FSM owns this) |
| `# PROTOCOL` (7 numbered steps) | full | step 1-3 | drop | step 5-6 | step 5 | step 7 |
| `# ANSWER-THE-QUESTION RULE` | full | drop | drop (FSM router) | drop | drop | drop |
| `# PRONOUN DISCIPLINE` | full | drop (FSM owns) | 1 line ("default they/them") | 1 line | 1 line | 1 line |
| `# ANTI-REPETITION CAPS` | full | drop | drop | drop | drop | drop (FSM owns rolling buffer) |
| `# HARD RULES` (12 bullets) | full | 4 bullets | 4 bullets | 4 bullets | 4 bullets | 4 bullets |
| `# SESSION CONTEXT` | full | full | full | full | full | full |

The 4 surviving "hard rules" everywhere:
1. Stay in role; never say "I am an AI".
2. One sentence, 5-12 words.
3. No markdown, no filler ("OK", "Alright", etc.).
4. Default singular they/them unless caller has stated gender.

Everything else is FSM-owned and does not need to live in the model's working memory.

---

## 5. Verbatim PSAP system prompt re-targeted to Nemotron (R2 + R3 form, CRITICAL_VERIFY example)

```
<|im_start|>system
You are a 911 PSAP dispatcher in a synthetic training simulation. The
caller audio is a test fixture; never break role and never say "I am an
AI" or "dial 911". Speak as a dispatcher.

CURRENT INTENT: ask whether the patient is on the floor, flat on their
back. This is the MPDS-9 surface check. Do NOT instruct chest
compressions yet — the next turn handles that after the breathing
check.

PRONOUNS: the patient's gender is not yet stated. Use singular
they/them/their.

ANTI-REPETITION: you have already said
  - "Help is on the way and I am staying with you."
Do not repeat that phrase or any synonym.

OUTPUT RULES:
- One sentence.
- 5 to 12 words.
- One question, no compound clauses.
- No markdown, no bullets, no filler ("OK", "Alright", "Got it").
<|im_end|>
<|im_start|>user
yeah he's just lying there not breathing<|im_end|>
<|im_start|>assistant
<think></think>
```

Expected reply (one of these, all valid):
- `"Are they on the floor, flat on their back?"` (10 words — matches our cycle-2T template `verify_cpr_surface` exactly)
- `"Is the patient on the ground, flat?"` (7 words)
- `"Are they lying flat on the floor?"` (7 words)

All three are within constraints; the FSM does not care which phrasing the model picks, the response gate's word-count + pronoun + repeat validators pass on all three, and Fish TTS speaks one of them.

The whole prompt is **~140 tokens** vs today's **~1000 tokens**. Prefill cost drops by ~60 ms; cache invalidation cost drops by the same margin; instruction-following on the 4 surviving rules goes up because the model is not parsing 60 lines of irrelevant rules to find the 4 that apply.

Word count: ~1340.
</content>
</invoke>