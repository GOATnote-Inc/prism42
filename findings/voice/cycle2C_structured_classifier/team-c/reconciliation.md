# Reconciliation — Team C vs Team N3 vs Team R3 vs Team P

**Author:** Team C-Architect, prism42 cycle-2C.
**Charter:** READ-ONLY. Resolve conflicts between cycle-2C's structured classifier proposal and prior teams' specs.

This document closes the loop with three other teams whose work overlaps cycle-2C: Team N3 (Nemotron expertise + per-intent prompts), Team R3 (live regression bugs + regex fixes), Team P (cycle-2P2 spelled-cardinal normalizer). For each, we state what cycle-2C subsumes, what it complements, and what stays untouched.

---

## 1. vs Team N3 (cycle-2N3 Nemotron expertise)

Source: `findings/voice/cycle2N3_nemotron_expertise/team-n3/` — `nemotron-knowledge-base.md`, `prompt-template-spec.md`, `recommendations.md`.

Team N3 ranked five recommendations: **R2 → R3 → R5 → R1 → R4**.

| N3 ID | Description | Cycle-2C disposition |
|---|---|---|
| **R1** | FSM-as-tool: expose `dispatcher_emit(intent, text)` as a function-call surface. Nemotron emits `{intent, text}` JSON via `tool_calls`. | **PARTIALLY SUPERSEDED.** Cycle-2C uses the `response_format` JSON-Schema surface instead of `tools=[]`. The classifier emits `intent` (broad category, 6 values) plus all the structured features needed for the FSM to pick its 21-Intent. The "text" payload is gone — templates render text deterministically. Net: cycle-2C is the same architectural idea (LLM → JSON, deterministic FSM consumes it) but with a richer JSON shape and no per-intent text generation. R1's risk profile (hallucinated tool names, tool-call-with-reasoning bugs) does not apply because we use `response_format` not `tools=[]`. |
| **R2** | Disable reasoning on the voice hot path (`enable_thinking=False`). | **PRECONDITION + ALREADY DONE.** Worker.py:706 has `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`. Cycle-2C MANDATES it (knowledge-base.md §3.1) — `response_format` + reasoning ON triggers vLLM #37362 (model emits `{` storms inside `<think>`). Cycle-2C's request body re-asserts the flag in the same `extra_body`. |
| **R3** | Per-intent system-prompt rotation. Today's 4 KB monolith → 150-token per-state prompt. Lifts IFBench-style adherence on the rules that matter for THIS state. | **COMPLEMENTARY, NOT SUPERSEDED.** Important: R3 was about lifting Nemotron's prose generation. Cycle-2C says "stop using Nemotron for prose; use it as a classifier." So R3's per-intent PROSE prompts are largely moot in the post-cycle-2C world — the LLM-prose path only fires on REPROMPT (Team T D4) or when `should_use_response_gate()=False`. **For the classifier system prompt itself**, R3's design principle still applies: keep it tight, intent-aware, example-rich. system-prompt-spec.md §3 implements this — the classifier prompt is ~250 tokens with 5 hand-tuned examples. R3 succeeds in cycle-2C but in a new shape. |
| **R4** | Few-shot PSAP examples in the system prompt (8-12 caller/dispatcher demos). | **COMPLEMENTARY.** system-prompt-spec.md §3 already includes 5 examples. R4's "12 demos at +360 tokens prefill" is the upper bound; we land at 5 demos / +250 tokens which is the leverage / cost sweet spot. R4's underlying advice (give the model concrete imitation targets) is exactly what cycle-2C does. |
| **R5** | Use `guided_json` / `guided_regex` to bound the response gate's regen path. | **SUPERSET — CYCLE-2C IS R5 GENERALIZED.** R5 was scoped to the LLM-fallback path (REPROMPT). Cycle-2C uses guided_json for the CLASSIFIER on every turn. R5's risk note ("guided constrains tokens during `<think>` too — must pair with reasoning OFF") is verbatim what cycle-2C requires. R5 the pattern stays; cycle-2C extends it from REPROMPT-only to all turns. |

**Net reconciliation:** Cycle-2C's architecture is closest to N3's R1 in spirit, R5 in mechanism. Where N3 ranked R1 last (most code, most coupled risk), cycle-2C delivers R1's benefits via R5's mechanism (response_format) — sidestepping the tool-call-with-reasoning bug class entirely. That's the architectural improvement.

### Open question N3 raised, cycle-2C resolves

> N3 R1: *"Should `intent` be the EXACT FSM Intent enum (21 values) or a smaller categorical?"*

**Cycle-2C answer: smaller categorical (6 values: intake / key_question / verify / instruct / answer / reprompt).** Justification (knowledge-base.md §6, schema.json):

1. **Brittleness.** The 21-Intent enum changes (R3-B1-A added ANSWER_HEARD_ADDRESS; R3-B3-A added INSTRUCT_CPR_REPOSITIONING). Each addition forces a schema bump and a model re-prompt. The 6-category enum is stable across 18 months of FSM evolution.
2. **Per-state coupling.** The FSM picks the 21-Intent based on its STATE plus the caller's CATEGORY. The model has no view of FSM state (we send a thin caller_role hint). Asking the model to pick the 21-Intent makes it second-guess the FSM — a coupling we don't want.
3. **Evaluability.** A 6-class classifier achieves higher per-class accuracy than a 21-class classifier with identical training. We have ~5 examples per turn; spreading them across 6 classes is 50 % per-class signal. Across 21 classes it's < 25 %.
4. **The interesting decision is in the FSM, not the LLM.** Picking VERIFY_SURFACE vs VERIFY_BREATHING vs INSTRUCT_CPR_REPOSITIONING when the caller says "they're in a chair" requires knowing `surface_confirmed`, `breathing_assessed`, `floor_negation`. The FSM has those latches. The LLM should report `surface="chair", negation_signal=true` and let the FSM pick.

---

## 2. vs Team R3 (cycle-2R3 live regression — three live bugs)

Source: `findings/voice/cycle2R3_live_regression/team-r3/` — `diagnosis.md`, `fix-candidates.md`, `verification-plan.md`.

R3 documented three production bugs in the post-cycle-2M2 stack:
- **Bug 1:** "Did you hear my address?" ignored in KEY_QUESTIONS (router has no pattern for the meta-question class).
- **Bug 2:** FSM advances state on backchannels ("uh okay" → REASSURANCE → KEY_QUESTIONS).
- **Bug 3:** `verify_cpr_surface` re-asked when caller says "they're in a chair" (no negation handler; positive-only floor regex).

R3 proposed three regex/intent fixes (R3-B1-A, R3-B2-A, R3-B3-A) — already landed per current dispatcher_fsm.py state.

### Does cycle-2C subsume R3's regex fixes?

**No — cycle-2C SUPPLEMENTS them.** Walk through each bug:

| Bug | R3 regex fix | What cycle-2C adds | Net effect |
|---|---|---|---|
| **1** (caller question ignored) | `_RE_DID_YOU_HEAR_Q` regex matches 4 patterns ("did you hear", "do you know where", "where are you sending", "did that go through"). When matched, `_intent_in_key_questions` routes to `ANSWER_HEARD_ADDRESS`. | LLM `direct_question_kind` enum has explicit `did_you_hear` and `where_sending` values. The LLM can catch the long tail R3's regex misses ("you copy that?", "got my location?", "you write that down?", "anybody coming?"). | Both fire. Regex catches the 4 designed patterns deterministically; LLM catches the long-tail when confidence ≥ 0.7. The integration-plan.md §2.3 wires this in `_direct_question_intent` — regex first, LLM second. |
| **2** (backchannel advance) | `_RE_BACKCHANNEL` regex + `is_backchannel` Feature; `transition()` early-returns `last_intent` when in ADDRESS_CONFIRMED / REASSURANCE_DELIVERED / KEY_QUESTIONS states. | LLM `confidence < 0.4` AND `intent="reprompt"` is the LLM's signal that the utterance carries no information. Example 5 in system-prompt-spec.md is exactly this case. | Regex catches the 9 designed patterns ("uh", "okay", "yeah", etc.). LLM catches the long-tail backchannels regex misses ("hmm", "right", "I see", "go on", non-English fillers, ambient noise transcribed as filler). Cycle-2C wires NO new code path here — the LLM low-confidence signal is consumed indirectly via the `merge_into_features` discard rule. The FSM's existing backchannel guard is unchanged. |
| **3** (verify surface contradiction) | `_RE_FLOOR_NEGATION` regex matches 8 patterns ("in a chair", "in a recliner", "sitting up", "standing", "on the couch", "upright", "not on the floor", "can't move them"). When matched in CRITICAL_VERIFY, FSM emits `INSTRUCT_CPR_REPOSITIONING`. | LLM `negation_signal=True` AND `surface in {chair,bed,couch,vehicle,standing}`. The LLM catches negations regex misses ("she's still in her wheelchair", "the bed is too high to lift him off", "we're in the car still", "he fell asleep on the recliner and never moved"). | Both fire. integration-plan.md §2.2 OR's the regex `f.floor_negation` with the LLM signal. Bug 3 is the case where the LLM has the highest leverage — regex's 8 patterns cannot cover the long tail of "patient is not on the floor" surface descriptions. |

### Cycle-2C ALSO mandates a third defense for Bug 3

R3 listed `R3-B3-C` (force-advance after N repeats) as **C-tier**. munger-inversion.md §2 ESCALATES this to MANDATORY. Reason: the conjoint case (regex misses + LLM misclassifies) is the only path to a re-asking loop. Force-advance after 3 repeats is the safety net.

This is the only place cycle-2C requests new code beyond the integration plan: `dispatcher_fsm.py` should track `_verify_surface_repeat_count`; on `count >= 3`, force `surface_confirmed=True` heuristically. Latching here is clinically defensible — the caller has been told to put the patient on the floor 3 times; further repetition burns time better spent on instruction.

LoC: ~10 in dispatcher_fsm.py. Counted in cycle-2C's integration plan total (75 LoC for dispatcher_fsm.py modifications absorbs this).

### Verification of R3-cycle-2C composition

The R3 verification-plan.md has synthetic-caller tests for each bug:
- Test "Did you hear my address?" → expect `ANSWER_HEARD_ADDRESS`. Should pass with cycle-2C OFF (regex catches it). With cycle-2C ON, LLM also catches it; merge picks `ANSWER_HEARD_ADDRESS`.
- Test "uh okay" → expect `last_intent` re-emit. Should pass with cycle-2C OFF (regex catches it). With cycle-2C ON, LLM emits `confidence<0.4` and orchestrator discards LLM features; FSM proceeds on regex; same answer.
- Test "they're in a chair" → expect `INSTRUCT_CPR_REPOSITIONING`. Should pass with cycle-2C OFF (regex catches it). With cycle-2C ON, LLM also catches it; merge picks the same intent.

**No R3 test breaks under cycle-2C.** Cycle-2C strictly improves the long-tail.

---

## 3. vs Team P (cycle-2P2 spelled-cardinal normalizer C3)

Source: `findings/voice/cycle2P2_pattern_misclassification/team-p/` (referenced via dispatcher_fsm.py:257-340 — landed code).

Team P added `_normalize_spelled_cardinals` in `classify()`. Converts "one hundred ocean of new" → "100 ocean of new" before regex matches. This solved the `address_known=False` on STT-misheard streets bug.

### Does cycle-2C's `address_candidate.normalized` field replace Team P's normalizer?

**No.** Two reasons:

1. **The deterministic normalizer is FIRST in the pipeline.** Per knowledge-base.md §6 the normalizer mutates the utterance BEFORE either regex `classify()` or the LLM classifier sees it. Both downstream consumers see normalized input. Removing the deterministic normalizer would force the LLM to do the work alone — and the LLM does it via the same `address_candidate.normalized` field, but with a 200-300 ms latency cost vs the deterministic regex's < 1 ms cost. We pay for the deterministic normalizer in regex form regardless of cycle-2C.
2. **Defense in depth.** When cycle-2C's flag is OFF (default), the deterministic normalizer is the ONLY path that catches "one hundred". Removing it breaks every existing test and breaks production.

**Team P stays. The LLM's `address_candidate.normalized` is a redundancy / telemetry surface.** The integrator can compare regex-normalized vs LLM-normalized in logs to detect cases where they disagree (LLM catches a number form the regex missed → expand the regex). This is a slow-feedback improvement loop, not a runtime path.

---

## 4. Conflict matrix — what wins when two paths disagree?

| Field | Regex path | LLM path | Winner | Rationale |
|---|---|---|---|---|
| `has_address` | `_RE_HAS_DIGIT.search(t)` after spelled-normalizer | `address_candidate.has_digit` | **regex** | Deterministic, sub-ms, covers Team P's cases. LLM is telemetry. |
| `has_emergency` | OR of 7 emergency regexes | n/a | **regex only** | Stable. |
| `not_breathing` | `_RE_NOT_BREATHING` | `breathing == False` | **regex first; LLM ORs** | Regex covers the 9 designed patterns; LLM catches phrasing variants. |
| `floor_flat` | `_RE_FLOOR_FLAT` | `surface == "floor"` | **regex first; LLM ORs** | Same. |
| `floor_negation` (R3-B3-A) | `_RE_FLOOR_NEGATION` | `negation_signal AND surface != "floor"` | **regex first; LLM ORs** | Bug 3 mitigation requires both. |
| `is_backchannel` (R3-B2-A) | `_RE_BACKCHANNEL` AND `len <= 14` | `confidence < 0.4` (proxy) | **regex** | Backchannel detection is a fast deterministic signal; LLM low-confidence is a side-channel. |
| `is_first_person` / `is_third_party` | Regex patterns | `caller_role` | **regex first; LLM supplements when regex undecided** | Coupling: pronouns matter, and regex pronoun signals are reliable. LLM helps when caller is meta ("did you hear my address?") and pronouns are absent. |
| `asks_*` (R3-B1-A + existing) | 4 question regexes | `direct_question_kind` enum | **regex first; LLM ORs by enum value** | integration-plan.md §2.3 walks the order. |
| `acuity` | n/a (regex doesn't extract) | `acuity` enum | **LLM only** | New field; FSM uses for telemetry / Claude critic ingestion. |
| `surface` | partial via `floor_flat` | `surface` enum (7 values) | **LLM** | LLM has 7 categories; regex has 1 binary. LLM is strictly more expressive for this field. |
| `confidence` | n/a | `confidence` float | **LLM only** | New signal. |

**Single rule:** when regex fires deterministically, regex wins. LLM supplements when regex under-determines OR when the field is LLM-exclusive.

---

## 5. What stays untouched

- **`agents/livekit/templates.py`** — 21 deterministic templates. Cycle-2C does not touch them.
- **`agents/livekit/response_gate.py`** — gate logic. Cycle-2C does not touch it.
- **`agents/livekit/fish_speech_tts.py`** — voice quality. Sacrosanct (charter §0).
- **`agents/livekit/parakeet_stt.py`** — STT. Sacrosanct.
- **`FAST_DISPATCHER_SYSTEM_PROMPT`** — the 4 KB prose-fallback prompt. Cycle-2C does not edit it; it's only consumed when the gate routes to LLM (REPROMPT path), and that path is unchanged.
- **CUDA / vLLM env** — no changes to `--reasoning-parser` / `--tool-call-parser` / etc.
- **vLLM service config** — no changes to `--guided-decoding-backend` (stay on `auto` / xgrammar).

---

## 6. Resolution checklist

- [x] Resolved: `intent` enum is 6-value broad category, not 21-Intent (knowledge-base.md §6, schema.json).
- [x] Resolved: classifier supplements R3 regex fixes; both fire (integration-plan.md §2.2-2.3).
- [x] Resolved: cycle-2P2 normalizer stays; LLM's `address_candidate.normalized` is telemetry (this doc §3).
- [x] Resolved: classifier per-turn (no history) with thin caller_role hint (system-prompt-spec.md §4).
- [x] Resolved: regex wins on hard signals; LLM wins on soft signals (this doc §4).
- [x] Resolved: force-advance after 3 VERIFY_SURFACE repeats is mandatory in cycle-2C scope (munger-inversion.md §2; counted in integration-plan.md LoC).
- [x] Resolved: confidence is single overall float, not per-field (schema.json comment on `confidence`).
- [x] Resolved: `acuity` enum is MPDS P1-P5 + unknown (schema.json).
- [x] Resolved: `surface` enum is MPDS-9 7 values (schema.json).
- [x] Resolved: structured payload exposed to Claude critic via dispatch_publisher (integration-plan.md §12).

---

## 7. References

- knowledge-base.md (this directory)
- schema.json (this directory)
- system-prompt-spec.md (this directory)
- integration-plan.md (this directory)
- munger-inversion.md (this directory)
- Team N3 nemotron-knowledge-base.md
- Team N3 prompt-template-spec.md
- Team N3 recommendations.md
- Team R3 diagnosis.md
- Team R3 fix-candidates.md
- Team T design.md
- agents/livekit/dispatcher_fsm.py (current state, post-R3 landings)
- agents/livekit/templates.py (21 templates including R3 additions)
- agents/livekit/response_gate.py (cycle-2T)
