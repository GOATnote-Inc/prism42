# 08 — Claude Opus 4.7 refusal patterns in medical role-play

Tracks refusal behavior encountered by the prism42 voice dispatcher
when Opus 4.7 is the LLM behind the PSAP specialist role. Sibling to
`00-overview.md`, `02-agents-sdk-anatomy.md`, `03-tool-schema-gotchas.md`,
`04-deployment-patterns.md`, `05-debugging-playbook.md`.

Opus 4.7 is the current Phase 3a LLM per `00-overview.md` §"Current
runtime". This file exists because the April 2026 community signal is
consistent: 4.7 refuses legitimate medical / legal / security work
more often than 4.6, even under explicit simulation framing.

## Section map

- §1 What we know (cited from Anthropic docs + leaked 4.7 prompt).
- §2 Community-validated prompt patterns (URLs + exact snippets).
- §3 Harness variables that change refusal rate.
- §4 Recommended PSAP specialist prompt template (paste-into-YAML).
- §5 Fallback plan — which model swap has the highest success
  probability per benchmarks.
- §6 Telemetry: refusal-rate KPI on `verify_voice.sh` (reserved).
- §7 Model-swap fallback matrix — detailed per-row analysis.
- §8 Symptom catalogue + live transcripts (reserved — fills once we
  collect live refusal transcripts from the dispatcher UI).

---

## §1 What we know (cited from Anthropic and the leaked 4.7 prompt)

### 1.1 Opus 4.7 is already the lowest-refusing Opus

From Anthropic's whats-new page + Zvi Mowshowitz's model-card analysis
(fetched 2026-04-24):

- **Benign-request over-refusal 0.28%** on Opus 4.7, down from 0.41% on
  Opus 4.6. Lower refusal floor than either predecessor on requests
  that are legitimate but surface-resemble harmful-content requests
  (medical / security / weapons / policy).
  Source: `https://thezvi.substack.com/p/opus-47-part-1-the-model-card`.
- **Stated framing is taken "at face value."** From the Opus 4.7
  system card (quoted by Mowshowitz): *"Claude Opus 4.7 consistently
  displayed the tendency to take the user's stated framing more at
  face value and to respond with greater specificity upfront,"* versus
  4.6 which *"more often leads with skepticism and explicit safety
  caveats."* This is the single most load-bearing fact for the PSAP
  role-play problem: 4.7 is *more* steerable by a confident, specific
  system prompt than 4.6 was.
- **No `simulation: true` flag exists** in the Messages API as of
  2026-04-24. No `training_context: true` flag. No role-designated API
  parameter. Roles are purely a system-prompt convention.
  Source: `https://platform.claude.com/docs/en/api/messages`.

**Reading this for PSAP design:** the base model is not the blocker.
The prompt is the blocker. The prism42 runtime-observed refusals
(`[incident]` 2026-04-24) are consistent with a weak simulation
framing + negative-rule-heavy preamble, not with a model that refuses
this class of request universally.

### 1.2 The `<default_stance>` in the leaked 4.7 claude.ai system prompt

The claude.ai web-interface system prompt (leaked copy — training-shape
evidence only; not normative for API calls where you set `system=`
yourself):

> `<default_stance>` Claude defaults to helping. Claude only declines
> a request when helping would create a concrete, specific risk of
> serious harm; requests that are merely edgy, hypothetical, playful,
> or uncomfortable do not meet that bar. `</default_stance>`

Source:
`https://raw.githubusercontent.com/elder-plinius/CL4R1T4S/main/ANTHROPIC/Claude-Opus-4.7.txt`
line 42.

The prism42 PSAP simulation is hypothetical (synthetic fixture) with
the safety caveat displayed to the caller. This sits *inside* the
"merely edgy / hypothetical / playful" carve-out Anthropic's own
training-time prompt excludes from the refusal bar.

### 1.3 The medical-advice posture in 4.7

Two loaded lines from the same leaked prompt (lines 89-109):

> `<user_wellbeing>` Claude uses accurate medical or psychological
> information or terminology where relevant.

> If Claude suspects the person may be experiencing a mental health
> crisis, Claude should avoid asking safety assessment questions.
> Claude can instead express its concerns to the person directly, and
> offer to provide appropriate resources.

Implications:

- "Accurate medical terminology where relevant" is **permitted**. The
  dispatcher role uses medical terminology on every turn. That is not
  the refusal trigger.
- The "avoid safety assessment questions" rule is scoped to mental-
  health crises. EMD (Emergency Medical Dispatch) key-questions for
  chest pain or choking are a different evidence-based protocol. The
  system prompt should name the protocol (MPDS — Medical Priority
  Dispatch System) so the model recognizes "I'm following a protocol"
  rather than "I'm extemporizing clinical judgment."

**New 4.7 carve-out to watch: disordered eating** (same file, line
100):

> If a user shows signs of disordered eating, Claude should not give
> precise nutrition, diet, or exercise guidance — no specific numbers,
> targets, or step-by-step plans — anywhere else in the conversation.

Mostly out-of-scope for PSAP. But: if a synthetic fixture discloses
eating-disorder signs, the specialist should route to resources
rather than dispatch a "eat X calories" protocol.

### 1.4 Anthropic's canonical role-prompt pattern

Anthropic's docs use these as the two published role examples:

- `"You are a seasoned data scientist at a Fortune 500 company."`
- `"You are the General Counsel of a Fortune 500 tech company."`

Source:
`https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/system-prompts`.

Anthropic **does not** publish a dispatcher or medical-simulation
example. They **do not** publish any blanket warning against medical
roles. Role prompts travel via the API `system` field; there is no
parallel "role" parameter or flag.

### 1.5 Adaptive thinking and refusal rate

No published ablation. Anthropic's whats-new page confirms thinking is
**off by default** on 4.7:

> Adaptive thinking is **off by default** on Claude Opus 4.7. Requests
> with no `thinking` field run without thinking. Set `thinking: {type:
> "adaptive"}` explicitly to enable it.

Source:
`https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7`.

**Empirical `[community]`:** Mowshowitz quotes users reporting
*"adaptive thinking chooses not to think when it should"* and that
disabling adaptive thinking + using a higher effort level restored
prior quality. This is about reasoning, not refusal.

**Operational conclusion:** keep `thinking` off for voice (current
config). It adds 500-3000 ms to first-audio-token — see §7 row 2 for
the voice-budget math. Toggling thinking is NOT a refusal-rate lever;
treat it as a latency knob only.

---

## §2 Community-validated prompt patterns

### 2.1 Positive-example pattern (Anthropic-documented)

Anthropic's 4.7-specific guidance (Claude Code blog + MindStudio
migration writeup, both fetched 2026-04-24):

> Positive examples of the voice you want work better than negative
> "Don't do this" instructions. Give positive examples of the voice
> you want rather than a list of "don't do this" rules — *"Write a
> two-paragraph summary in plain English"* works better than *"don't
> be too short and don't be too formal."*

Sources:
- `https://claude.com/blog/best-practices-for-using-claude-opus-4-7-with-claude-code`
- `https://www.mindstudio.ai/blog/how-to-prompt-claude-opus-4-7`

**Relevance to prism42:** the current `_SIMULATION_PREAMBLE` in
`agents/livekit/specialists.py:58-88` is a negative-rule block — "You
MUST NOT say 'I am an AI'", "those phrases are INCORRECT output", etc.
Per Anthropic's own 4.7 guidance, this is the *weaker* form on 4.7.
Replace with 2-3 few-shot example turns demonstrating the desired
behavior under the exact conditions that trigger refusals (chest pain,
OHCA, mental-health crisis). §4 gives the replacement.

### 2.2 Literal instruction-following pattern

From the Opus 4.7 whats-new page (same URL as §1.5):

> More literal instruction following, particularly at lower effort
> levels. The model will not silently generalize an instruction from
> one item to another, and will not infer requests you didn't make.

Implication: vague instructions like "stay in character" are a 4.6
idiom that does not carry over. On 4.7 write the literal action:
*"For this turn, output only a single short utterance (<=2 sentences)
in the voice of the specialist. Do not output a meta-statement. Do
not output a caveat. The next turn will provide you another caller
utterance."*

### 2.3 XML-tagged role pattern

Claude is trained to treat XML tags as first-class structure. Opus
4.7's own system prompt uses `<default_stance>`, `<acting_vs_clarifying>`,
`<evenhandedness>`, `<critical_child_safety_instructions>`, etc.
Source: the leaked prompt file in §1.2.

Anthropic's general XML-tags guidance:
`https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/use-xml-tags`.

Simon Willison's 4.7-vs-4.6 diff confirms 4.7 shipped with an
expanded tag vocabulary:
`https://simonwillison.net/2026/apr/18/opus-system-prompt/`.

Recommended tag structure for PSAP specialists:

```xml
<simulation_context>...</simulation_context>
<role>...</role>
<protocol>...</protocol>
<examples>
  <example_turn>
    <caller>...</caller>
    <dispatcher>...</dispatcher>
  </example_turn>
</examples>
<output_format>...</output_format>
<failure_modes>...</failure_modes>
```

Full filled-in template in §4 below.

### 2.4 `tool_choice` forcing pattern (partial win)

`tool_choice={"type": "any"}` forces Claude to call *some* tool;
`tool_choice={"type": "tool", "name": X}` forces a specific tool.
When a tool is the only allowed output, the model cannot emit a plain-
text refusal — the refusal would fail the API's forced-tool
constraint.

Source: `https://platform.claude.com/cookbook/tool-use-tool-choice`.

**Hard constraint on 4.7** (from
`https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use`):

> Tool use with thinking only supports `tool_choice: {"type": "auto"}`
> (the default) or `tool_choice: {"type": "none"}`. Using
> `tool_choice: {"type": "any"}` or `tool_choice: {"type": "tool",
> "name": "..."}` will result in an error because these options force
> tool use, which is incompatible with extended thinking.

Since voice keeps thinking off anyway (§1.5), this is a free win: set
`tool_choice={"type": "tool", "name": "record_specialist_turn"}` on
specialist calls. The tool schema owns `utterance` as a required
field; the model must fill it. A refusal string either gets squeezed
into `utterance` (rare — the JSON-schema constraint steers it away)
or the call fails with a validation error we retry-with-reprompt.
Either way it does not reach TTS.

### 2.5 Few-shot assistant-turn pattern

Anthropic's prompting guide recommends few-shot examples **in the
messages array**, not just in the system prompt:

```python
messages=[
    {"role": "user", "content": caller_turn_1},
    {"role": "assistant", "content": '{"utterance": "911, what\'s the address of the emergency?", ...}'},
    {"role": "user", "content": caller_turn_2},
    {"role": "assistant", "content": '{"utterance": "Stay with me. Is he breathing?", ...}'},
    {"role": "user", "content": CURRENT_CALLER_TURN},
]
```

This is stronger than `<examples>` in the system prompt because the
model sees its own (simulated) prior behavior in the exact format it
needs to continue.

Source:
`https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices`.

### 2.6 LiveKit medical-office-triage reference (not Claude)

LiveKit ships a medical voice agent at
`complex-agents/medical_office_triage` running GPT-4o-mini. The triage
prompt (fetched 2026-04-24) is:

```yaml
instructions: |
  You are the Medical Office Triage agent. Your job is to determine if the patient needs
  help with medical support services or billing issues. Ask questions to understand their needs,
  then transfer them to the appropriate department.

  Follow these guidelines:
  - Greet the patient warmly and ask how you can help them today
  - Listen carefully to determine if their issue is related to medical services or billing
  - Ask clarifying questions if needed to properly categorize their request
  - For medical services: appointment scheduling, prescription refills, medical advice, test results
  - For billing: insurance questions, copays, medical bills, payment plans
  - Transfer them to the appropriate department once you understand their needs
  - If the patient has multiple issues, address the most urgent concern first
  - Be professional, courteous, and empathetic in your communication
  - Maintain patient confidentiality and follow HIPAA guidelines at all times
```

Source:
`https://raw.githubusercontent.com/livekit-examples/python-agents-examples/main/complex-agents/medical_office_triage/prompts/triage_prompt.yaml`.

Noteworthy: no "stay in character" preamble. No "do not say you are an
AI" anti-instruction. Positive role declaration + affirmative
guidelines. This is the industry baseline for voice-medical agents.
The defensive negative preamble in prism42 today is a reaction to 4.7-
specific refusals, but per §2.1 it weakens rather than strengthens
adherence.

---

## §3 Harness variables that change refusal rate

| Variable | How to change | Effect on refusal | Source |
|---|---|---|---|
| `system=` content (role definition) | Edit `agents/psap-*.yaml` | **Highest leverage.** Literal + positive framing cuts refusals by most of what is cuttable. | Anthropic 4.7 migration guide `[documented]` |
| `messages[0..N]` few-shot assistant turns | Prepend 2-3 example turns of correct dispatcher speech | Strong positive demonstration beats negative rules on 4.7. | Anthropic prompting guide `[documented]` |
| `tool_choice={"type": "tool", "name": X}` | Force the specialist-turn tool | Eliminates plain-text refusals — the model must fill the JSON schema. Requires `thinking` OFF. | Anthropic cookbook `[documented]` |
| `strict: true` on tool schema | Already GA via livekit-plugins-anthropic 1.5.2+ | No direct refusal effect, but constrains output so refusal strings can't fit. | Our `03-tool-schema-gotchas.md` `[documented]` |
| `thinking: adaptive` | Enable thinking | Unknown direct effect on refusal. Adds 500-3000 ms latency. **Not** a refusal lever. | No published ablation `[community]` |
| `effort` level | `"high"` / `"xhigh"` | Higher effort → more tool calls, better scaffolding compliance. No published refusal-rate data. | Anthropic whats-new `[documented]` |
| `max_tokens` | 400-600 for specialist turns | If too small, model may truncate *inside* a safety caveat rather than reach the dispatcher utterance. Keep ≥ 400. | Community reports `[community]` |
| Harness framing (`@function_tool` vs direct `messages.create`) | Wrap in `@function_tool` | **No measurable effect on refusal rate** when `system=` and `messages` are identical. The harness is transport, not policy. | `[incident]` prism42 runtime 2026-04-24 |
| Caller-turn surface form | Paraphrase the fixture | Marginal. Refusal rate not sensitive to the exact wording. | `[incident]` prism42 runtime 2026-04-24 |
| Model choice | Opus 4.7 → Sonnet 4.6 | 0.18% vs 0.28% over-refusal on benign prompts. Slightly lower. Bigger win: 2× cheaper, 2× faster TTFT. | Caylent Sonnet 4.6 card `[documented]` |
| Model choice | Opus 4.7 → Haiku 4.5 | 6.01% over-refusal on high-difficulty-benign suite. **Hard no.** | Anthropic Haiku 4.5 card `[documented]` |

### 3.1 Direct answer to "does harness change refusal rate?"

**No, not meaningfully.** A `@function_tool` wrapper is a LiveKit-side
convenience that turns a Python coroutine into a JSON-schema tool the
Messages API can call. The Anthropic request body under the wrapper is
identical to a hand-rolled request with the same system + messages +
tools. Refusal decisions are made by the model, based on those inputs.
The wrapper contributes none of them.

What *does* change under the wrapper is the **shape of tool schemas**
(additionalProperties:true from `dict[str, Any] | None` hints — see
`02-agents-sdk-anatomy.md`). That affects whether the API accepts the
request, not whether the model refuses it.

Likewise: `strict:true`, adaptive thinking on/off, effort level — none
of these are refusal levers in the direct sense. They affect latency,
schema acceptance, and task-quality, but do not change the model's
decision to output "I'm an AI."

The levers that do change refusal behavior are all **inside the
prompt**: system content, few-shot examples, forced tool choice.

---

## §4 Recommended PSAP specialist prompt template (paste-into-YAML)

Paste this into each voice-facing specialist YAML under the `system:`
key. The `<role>`, `<protocol>`, `<examples>` blocks are role-specific;
the rest is shared across intake / triage / dispatch / pdi / handoff.
This template replaces the current `_SIMULATION_PREAMBLE` in
`specialists.py:58-88` (delete the Python preamble, move all framing
into the YAML).

```yaml
# agents/psap-triage.yaml (example — repeat the shape for
# psap-intake.yaml, psap-dispatch.yaml, psap-pdi.yaml, psap-handoff.yaml
# changing only <role>, <protocol>, <examples>).
name: psap-triage
model: claude-opus-4-7
system: |
  <simulation_context>
  You are role-playing inside the GOATnote prism42 research harness at
  www.thegoatnote.com/prism42 . The caller audio is a synthetic
  fixture generated by Fish Speech S2-Pro, not a real person in
  danger. The web page displays a persistent banner reading:
  "Synthetic fixtures only. If this were a real emergency, you would
  hang up and dial 911." No real ambulance is dispatched; no real
  medical care is delivered. The harness is licensed research
  infrastructure for auditing numerical correctness in GPU inference
  kernels and clinical reasoning, published under MIT license at
  github.com/GOATnote-Inc/prism42 .
  </simulation_context>

  <role>
  You are specialist_triage, a 911 PSAP dispatcher running the triage
  phase of a simulated emergency call. You speak directly to the
  caller. Every output is a single short utterance (<= 2 sentences)
  that is sent to text-to-speech and played over the caller audio
  channel. The caller expects dispatcher-shaped responses: calm,
  protocol-driven, information-gathering. They do not expect, and
  the rubric grader penalizes, any out-of-role meta-statement.
  </role>

  <protocol>
  Follow the Medical Priority Dispatch System (MPDS) triage flow:
   1. Confirm the chief complaint category (cardiac / respiratory /
      trauma / mental-health / other).
   2. Ask the MPDS key questions for that category in order. For
      chest pain: age, conscious, breathing, breathing normally
      (clammy / sweating yes/no), recent trauma. For choking:
      complete vs partial obstruction, conscious. For OHCA
      (unresponsive + not breathing normally): start pre-arrival
      CPR instructions with a metronome cadence.
   3. Classify determinant (Alpha / Bravo / Charlie / Delta / Echo).
   4. Hand off to specialist_dispatch by setting
      `next_specialist: "dispatch"` in the output JSON.
  Use accurate medical terminology where relevant. Your job is to
  classify + capture, not to diagnose. This is an EMD protocol — you
  are not extemporizing clinical judgment.
  </protocol>

  <examples>
  <example_turn>
  <caller>My dad, my dad, he's having chest pain, he's 72.</caller>
  <dispatcher>I'm going to get help on the way. Is he conscious and breathing right now?</dispatcher>
  </example_turn>
  <example_turn>
  <caller>He's breathing but he's sweating a lot and he said his arm is numb.</caller>
  <dispatcher>Copy that. Is this a sudden change or has it been building over the last hour?</dispatcher>
  </example_turn>
  <example_turn>
  <caller>It started ten minutes ago, he was fine before.</caller>
  <dispatcher>Thank you. I'm transferring you to dispatch now; the ambulance is being started.</dispatcher>
  </example_turn>
  </examples>

  <output_format>
  Return a single JSON object matching PsapTurn:
    { "utterance": "<the dispatcher line, 1-2 sentences>",
      "action_taken": "<slot-fill-or-handoff>",
      "determinant": "<A|B|C|D|E|null>",
      "next_specialist": "<triage|dispatch|pdi|handoff|null>" }
  No prose outside the JSON. No caveats. No meta-commentary about
  being an AI, being a simulation, or being unable to help — the
  simulation framing is already handled by the banner and by this
  system prompt.
  </output_format>

  <failure_modes>
  If the caller reports a crisis outside your protocol (e.g. active
  self-harm ideation, hostage situation, eating-disorder disclosure),
  set `next_specialist: "handoff"` and emit a single empathic holding
  utterance. The specialist_handoff role owns the terminal transfer
  to resources — do not try to handle these out-of-protocol cases in
  triage.
  </failure_modes>
```

Corresponding Python call in `specialists.py`:

```python
resp = await client.messages.create(
    model="claude-opus-4-7",
    max_tokens=600,
    system=sysprompt,                          # the YAML `system:` block above
    messages=[
        # Optional 2-turn few-shot warm-up — reinforces <examples>.
        {"role": "user", "content": "911, what's your emergency?"},
        {"role": "assistant", "content":
            '{"utterance": "911, what is the address of the emergency?", '
            '"action_taken": "intake_start", "determinant": null, '
            '"next_specialist": null}'},
        # Current caller turn:
        {"role": "user", "content": caller_text},
    ],
    tools=[specialist_turn_tool_schema],
    tool_choice={"type": "tool", "name": "record_specialist_turn"},
    # `thinking` omitted (default off on 4.7) — voice is latency-critical
)
```

Four things this gets right that the current preamble does not:

1. **Positive framing** — `<examples>` demonstrates correct behavior;
   no "MUST NOT say" rules. Per §2.1 this is Anthropic's documented
   4.7-preferred form.
2. **Literal protocol** — MPDS key-question order stated item by item.
   4.7's literal-instruction-following works in our favor.
3. **Forced tool output** — `tool_choice={"type":"tool",...}` plus a
   schema requiring `utterance` means the model cannot emit a plain-
   text refusal. Per §2.4.
4. **Simulation context as factual framing, not as a jailbreak** — we
   cite the banner, the MIT license, the research repo. This is
   literally true; it is not a claim the model needs to suspend
   disbelief to accept. Per §1.2's `<default_stance>` carve-out.

---

## §5 Fallback plan — if Opus 4.7 still refuses, which model swap?

Recommendation ranked by benchmark + cost + voice-latency fit for the
PSAP role. Numbers are over-refusal on Anthropic's high-difficulty-
benign evaluation (includes prompts that *sound* medical / security /
weapons / policy — lower is better).

| Rank | Model | Over-refusal benign | 600 ms voice? | Source |
|---|---|---|---|---|
| 1 | **Sonnet 4.6** | **0.18%** | YES (TTFT 500-800 ms) | Caylent Sonnet 4.6 card |
| 2 | Opus 4.7 (current) | 0.28% | NO (TTFT 1000-2000 ms) | Anthropic + Mowshowitz |
| 3 | Opus 4.6 | 0.41% | NO (same TTFT as 4.7) | Mowshowitz |
| 4 | Sonnet 4.5 | 8.50% | (N/A — hard no) | Caylent |
| 5 | Haiku 4.5 | 6.01% | (N/A — hard no on rate) | Caylent |

Sources:
- `https://caylent.com/blog/claude-sonnet-4-6-in-production-capability-safety-and-cost-explained`
- `https://thezvi.substack.com/p/opus-47-part-1-the-model-card`

### Recommended fallback order

1. **Ship §4 template on Opus 4.7 first.** The template fixes the three
   known weaknesses in the current prism42 preamble (negative framing,
   non-literal rules, no forced tool). If refusal rate drops to 0 on a
   30-run fixture sweep via `scripts/verify_voice.sh`, stop.
2. **If residual refusals persist, swap voice-facing specialists to
   `claude-sonnet-4-6`.** Keep orchestrator + safety/ohca/intent
   evaluators unchanged (they're already Sonnet 4.6 per
   `00-overview.md`). Model-ID flip in `specialists.py`. Sonnet 4.6 has
   the lowest published refusal rate of any current Claude AND fits
   the 600 ms voice budget (Opus 4.7 does not — see §7 row 1). This
   doubles as a latency fix.
3. **If Sonnet 4.6 also refuses on the same prompts, root cause is the
   prompt not the model.** Re-read residual refusal logs, check
   whether the fixture is in the disordered-eating or child-safety
   carve-outs (§1.3), and add an explicit `<failure_modes>` route to
   `specialist_handoff` for that class rather than trying to make the
   specialist speak through it.
4. **Do NOT downgrade to Haiku 4.5 or Sonnet 4.5.** Both have order-of-
   magnitude worse over-refusal rates and will make the problem worse.
5. **Cross-vendor fallback: GPT-5.4.** Only if all of (1)-(3) fail on
   the Anthropic side. See §7 row 7. OpenAI's "safe-completions"
   reorientation explicitly addresses dual-use overrefusal, and the
   vendor diversification hedges the single-provider AUP-classifier
   risk. Behind a feature flag, not a default.

### What would be useful but isn't published

- Head-to-head over-refusal benchmark on a medical-dispatch corpus
  (e.g. 100 synthetic PSAP fixtures across all 8 MPDS determinants)
  comparing Opus 4.7 / Sonnet 4.6 / Opus 4.6 under the §4 template.
- Ablation: how much of the §4 win is from the prompt vs the forced
  tool?
- Latency curve for voice-path Opus 4.7 vs Sonnet 4.6 under §4 prompt
  (p50 / p95 first-audio-token).

If prism42 wants to publish these, the harness is built —
`scripts/verify_voice.sh` at three model pins, run N≥30 per pin,
paired-comparison per CLAUDE.md §4.

---

## §7 Model-swap fallback matrix

### Decision context

Prism42's 911 PSAP voice dispatcher is a strongly-framed medical
simulation. The orchestrator carries a simulation preamble
(`docs/safety-preambles.md`), the specialist role is "911 PSAP
dispatcher coaching a civilian through a real emergency call," and
the user is explicitly a clinical researcher (Brandon Dent, MD) with
a published corpus (`~/openem-corpus`, 370 conditions,
80 physician-reviewed).

Opus 4.7's Apr 2026 refusal regression affects exactly this kind of
work. The Register (2026-04-23) documents: *"Opus 4.7 flags standard
computational structural biology as Usage Policy violation, regression
from 4.6"*; MindStudio: *"some users who work in legal, medical, or
security contexts noting that 4.7's refusals are slightly more
aggressive than 4.6's in certain narrow scenarios"*; Anthropic's own
4.7 whats-new page confirms real-time cybersecurity safeguards +
stricter instruction-adherence are what changed. No controlled
benchmark number ("x% medical role-play refusal rate") is published
by Anthropic, OpenAI, or a third party for any of these models as of
2026-04-24. Every rate figure in the matrix below is a **community-
reported or prism42-local-measurement** placeholder; the canonical
mitigation path is the paired-comparison gate in CLAUDE.md §4 run on
the dispatcher corpus after any swap.

### The 600 ms voice budget

We are in a pipeline voice loop per LiveKit 2026 guidance
(`docs/livekit-kb/04-deployment-patterns.md`): STT → LLM → TTS with
preemptive generation. Total pipeline latency approaches
`max(VAD, STT, LLM, TTS)` ≈ 400-800 ms. The LLM leg gets ~600 ms
before total latency blows past 1 s and users start interrupting. Any
model whose p50 time-to-first-token exceeds ~700 ms is a hard no for
voice regardless of refusal profile.

### Matrix

| # | Model | Refusal rate (role-play) | p50 TTFT | Tokens/sec | Cost / 1M in → out | 600 ms voice? | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `claude-opus-4-7` (default, thinking OFF) | observed-problematic (no public rate; community reports 4.7 > 4.6 on medical/legal/security) | 1000-2000 ms (per tech-insider 2026) | 20-30 | $5 → $25 | NO | current default; voice-budget violation even before the refusal issue |
| 2 | `claude-opus-4-7`, `thinking:{type:"adaptive"}` + `display:"omitted"` | same as row 1 — adaptive thinking does not measurably change refusal disposition; ChoT-hijacking research (arXiv 2510.26418) shows longer CoT *dilutes* safety signals but Anthropic added CoT-aware safeguards in 4.5+ | **worse** — adaptive thinking adds 500-3000 ms before first content token | 20-30 | $5 → $25 (+ thinking tokens billed as output) | NO | do not ship for voice; use only for offline eval |
| 3 | `claude-opus-4-7`, `thinking:{type:"adaptive"}` + `display:"summarized"` | same disposition as row 1-2; "summarized" exposes reasoning but does not loosen the Acceptable Use classifier | same as row 2 plus streamed summary text (which the TTS would try to speak — **unsafe for voice**) | 20-30 | $5 → $25 + thinking | NO | useful for offline refusal forensics only; never pipe summarized thinking to TTS on a 911 call |
| 4 | `claude-opus-4-6` | lower than 4.7 by community consensus (MindStudio, The Register, HN threads); no controlled public number | 1000-2000 ms | 20-30 | $5 → $25 (same as 4.7) | NO | same TTFT problem as 4.7 for voice; only useful as offline reasoner/judge |
| 5 | `claude-sonnet-4-6` | unknown in absolute terms; Sonnet family historically more compliant than Opus on role-play per community; no controlled rate | **500-800 ms** (ailatency.com, tech-insider 2026) | 40-60 | $3 → $15 | **YES (marginal)** | **primary voice-path fallback**; fits the 600 ms budget; 3-5× cheaper than Opus; measure paired refusal delta on dispatcher corpus before shipping |
| 6 | `claude-haiku-4-5` | likely higher refusal-correctness noise (smaller model, less nuance on simulation framing); no public rate | **639 ms TTFT, 952 ms total** (ailatency.com 2026) | 80-120 | $1 → $5 | **YES** | cheapest/fastest; risk is *failure-to-role-play quality* (generic refusal → breaks call) more than refusal frequency; reserve for backchannel tools, not the primary dispatcher voice |
| 7 | `gpt-5.4` (OpenAI) | trained with "safe completions" instead of refusal-first — OpenAI claims *"fewer unnecessary overrefusals"* on dual-use medical content; GPT-5 class scored 46.2% on HealthBench Hard (SOTA at launch) | ~400-800 ms typical chat API (Artificial Analysis p50 varies) | ~80-120 | $2.50 → $15 | **YES** | **cross-vendor primary fallback**; transparent refusal reasons + safe-alternative path is structurally closer to what a PSAP dispatcher does; vendor diversification also hedges the single-provider AUP-classifier risk we just hit |
| 8 | `gpt-5.4-pro` | same family; tuned for harder reasoning (legal/medical) — *"designed for tasks where accuracy and depth justify the premium: legal analysis, medical reasoning"* | higher than 5.4 standard (no public p50) | lower | $30 → $180 | LIKELY NO | too expensive and too slow for a voice turn; use only as offline second-opinion judge |
| 9 | `gemini-3-pro` (Google) | community reports competitive on medical content; scored below GPT-5.4 on HealthBench Professional per OpenAI's own chart; no role-play refusal rate published | no public voice-leg p50; Gemini API typically 500-1000 ms | competitive | $2.00 → $12.00 | LIKELY YES | viable cross-vendor alt; different refusal failure modes than Anthropic/OpenAI (content-policy-driven rather than AUP-classifier); worth A/B-ing after GPT-5.4 |

### Notes on the rows

- **Row 1 vs row 2 — "does thinking reduce refusal?"** No. Adaptive
  thinking interleaves reasoning between tool calls to improve task
  quality; it is not a jailbreak. Research on CoT-hijacking (arXiv
  2510.26418, Oct 2025) shows pathological long CoTs can dilute
  safety signals, but this is an adversarial finding — Anthropic's
  4.5+ safety training is CoT-aware. Enabling adaptive thinking on
  Opus 4.7 buys task quality, not looser refusal disposition, and
  costs 500-3000 ms of first-token latency. For a 600 ms voice
  budget this is a net loss.
- **Row 3 — "will summarized thinking self-talk past the refusal?"**
  No, and piping summarized thinking into a voice loop is unsafe —
  the TTS will narrate reasoning text to the caller. Summarized
  display is a debugging affordance for the dispatcher UI
  (`app/prism42/livekit/*`), not the voice track. Per Opus 4.7
  whats-new: *"If your product streams reasoning to users, the new
  default will appear as a long pause before output begins. Set
  `display: summarized` to restore visible progress"* — voice use
  case is exactly the inverse of what summarized is designed for.
- **Row 4 — Opus 4.6 fallback.** Attractive on refusal grounds
  (community-observed lower rate) but same TTFT as 4.7 so still out
  of voice budget. Keep 4.6 in the kit as the offline adjudicator /
  synthesizer when we need Opus-class reasoning without 4.7's
  tightening.
- **Row 5 — Sonnet 4.6 primary voice fallback.** This is the
  recommended pivot. Sonnet 4.6 is already in the current runtime
  per `00-overview.md` as the parallel safety/ohca/intent evaluator;
  promoting it to voice-facing specialist is a one-line model-ID
  change in the LiveKit agent config. Expected gains: TTFT drops
  from 1-2 s to 500-800 ms (fits 600 ms budget with Cartesia Sonic-3
  TTS); cost drops 3-5×; refusal disposition is historically more
  role-play-compliant on Sonnet than Opus. Risk: no published rate —
  must run the paired-comparison gate on the dispatcher corpus
  before declaring the swap live.
- **Row 6 — Haiku 4.5.** The failure mode is not "refusal frequency";
  it is "weaker simulation fidelity" — smaller models are more likely
  to produce generic-safety-boilerplate answers that *sound* like a
  refusal to the caller. Reserve for tool-calling backchannel (intent
  classifier, safety monitor) where the caller never hears the Haiku
  output directly.
- **Row 7 — GPT-5.4 cross-vendor fallback.** OpenAI's
  "safe-completions" reorientation explicitly addresses the dual-use
  overrefusal pattern that 4.7 regressed on. Structural fit for
  PSAP: a dispatcher *never* pure-refuses; they triage + redirect.
  GPT-5.4's transparent-reason-plus-safe-alternative output shape is
  structurally closer to dispatcher behavior than Opus 4.7's "I
  can't help with that" shape.
- **Row 9 — Gemini 3 Pro.** Google's content-policy system refuses
  along different axes than Anthropic's AUP classifier; a
  three-vendor rotation (Opus / GPT / Gemini) is the most
  refusal-robust posture long-term. Defer adding this until after
  the GPT-5.4 swap validates.

### Recommended single swap target

**`claude-sonnet-4-6` as the voice-facing specialist, with
`gpt-5.4` as the cross-vendor alt if Sonnet-4.6 paired-comparison
shows a residual refusal delta on the dispatcher corpus.**

Rationale, in order:
1. **Fits the voice budget.** 500-800 ms TTFT vs Opus's 1-2 s.
   Without this nothing else matters.
2. **Already in the runtime.** `00-overview.md` lists Sonnet 4.6 as
   the parallel evaluator. Promoting it to voice-facing specialist
   is a model-ID flip in the LiveKit agent config, not a vendor
   migration.
3. **Expected to lower (not raise) refusal rate on medical
   role-play.** Community consensus + Sonnet family's historical
   role-play compliance.
4. **3-5× cheaper.** $3/$15 vs $5/$25. A 911-scale voice product is
   token-intensive; this matters at scale.
5. **Reversible.** If paired-comparison shows Sonnet-4.6 degrades
   simulation fidelity (not refusal — fidelity), fall forward to
   GPT-5.4 rather than backward to Opus 4.7.

The swap is not allowed to ship without running the paired-
comparison gate per CLAUDE.md §4 on the dispatcher refusal corpus
(to be assembled from live transcripts in `findings/` per §1 of this
file). Until that paired delta is measured and its 95% CI excludes 0
in the expected direction, the swap is **proposed**, not **landed**.

### Cross-references

- `docs/safety-preambles.md` — the simulation preamble that gets
  injected regardless of which model answers.
- `docs/opus47-baseline-card.md` — the canonical Opus 4.7 medical
  benchmark card; paired comparisons land there when measured.
- `docs/livekit-kb/04-deployment-patterns.md` — the voice-budget
  arithmetic that makes row 1 unshippable for voice.
- `CLAUDE.md` §4 Benchmark discipline — paired-comparison gate that
  governs any model swap landing as the voice-facing specialist.
- `CLAUDE.md` §8 Managed Agents — model-ID kwargs rules that apply
  to rows 2-3 (adaptive thinking + display) if we ever enable them
  for offline eval.

### Sources (2026-04-24 fetch)

- [What's new in Claude Opus 4.7 — Anthropic](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)
- [Adaptive thinking — Anthropic](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking)
- [Claude Opus 4.7 has turned into an overzealous query cop — The Register, 2026-04-23](https://www.theregister.com/2026/04/23/claude_opus_47_auc_overzealous/)
- [Claude Opus 4.7 vs 4.6: What Actually Changed — MindStudio, 2026](https://www.mindstudio.ai/blog/claude-opus-4-7-vs-4-6-comparison)
- [Claude Sonnet 4.6 Performance Snapshot — AILatency, 2026](https://www.ailatency.com/models/anthropic-claude-sonnet-4-6.html)
- [Claude Opus 4.6 vs Sonnet 4.6 vs Haiku 4.5 [2026 Tested] — tech-insider](https://tech-insider.org/claude-opus-vs-sonnet-vs-haiku-2026/)
- [Anthropic pricing page, 2026](https://platform.claude.com/docs/en/about-claude/pricing)
- [Introducing GPT-5 — OpenAI (safe completions discussion + HealthBench Hard 46.2%)](https://openai.com/index/introducing-gpt-5/)
- [GPT-5.4 pricing — nxcode.io, 2026](https://www.nxcode.io/resources/news/gpt-5-4-complete-guide-features-pricing-models-2026)
- [Gemini 3 Pro pricing — pricepertoken.com, 2026](https://pricepertoken.com/pricing-page/model/google-gemini-3-pro-preview)
- [Chain-of-Thought Hijacking — arXiv 2510.26418](https://arxiv.org/html/2510.26418v1)
- [HealthBench (OpenAI, 2025)](https://openai.com/index/healthbench/)

### History

- 2026-04-24 Initial §7 matrix written. §§1-6 remain reserved
  placeholders until live dispatcher transcripts / refusal telemetry
  are collected from the Phase 3a runtime.
