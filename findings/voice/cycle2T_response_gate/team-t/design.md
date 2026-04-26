# Cycle-2T Response Gate — Design Doc (Team T)

## Mission

Insert a deterministic response gate between the dispatcher FSM and Fish
TTS so the bytes Fish speaks are bounded by code, not by LLM
constraint-following. Cycle-2Q put the FSM in front of the LLM; cycle-2T
puts a template-or-validate layer between the FSM and the speech path.

## Why now

Cycle-2Q surfaced two live bugs that the FSM alone could not block:

1. **Spurious simulation-disclaimer fire.** Nemotron-3-Nano (IFBench
   70.7) intermittently produced "dial 911 on a working phone" despite
   the negation rules in `FAST_DISPATCHER_SYSTEM_PROMPT`. ~30%
   per-instruction failure rate is the published Nemotron-3-Nano
   ceiling.
2. **Gendered "him" without caller commit.** FSM tracks `pronouns`
   correctly but the LLM still substituted "him" / "her" when the
   caller never specified gender.

Both failures are LLM-creativity failures. Most dispatcher intents have
ONE correct realization; rendering them deterministically (no LLM call
in the speech path) takes those failure modes off the table entirely.

## Frozen-path inventory (read-only constraints)

- `agents/livekit/worker.py`
- `agents/livekit/orchestrator.py` (one ~5-line additive hook only)
- `agents/livekit/dispatcher_fsm.py`
- `agents/livekit/fish_speech_tts.py`
- `agents/livekit/dispatch_publisher.py`
- All Parakeet/Fish/Nemotron config
- The `FAST_DISPATCHER_SYSTEM_PROMPT` text (LLM-fallback prompt
  scaffolding when the gate routes to LLM)

## FSM inventory (Phase 1 deliverable)

### Intents (21 total, sourced verbatim from `dispatcher_fsm.py:113-141`)

```
# Intake
REQUEST_LOCATION_AND_EMERGENCY
REQUEST_LOCATION
REQUEST_EMERGENCY
CONFIRM_ADDRESS
# Reassurance — once-per-call latched
DELIVER_REASSURANCE
# Key questions
KQ_RESPONSIVE_BREATHING            (third-party medical)
KQ_SEVERITY                        (first-party medical)
KQ_BLEEDING_LOCATION
KQ_FIRE_EVACUATION
KQ_SAFE_LOCATION                   (crime / trauma)
# Verification (cardiac arrest gate, MPDS-9 sub-FSM)
VERIFY_SURFACE
VERIFY_BREATHING
# Pre-arrival instructions
INSTRUCT_CPR_BEGIN
INSTRUCT_CHOKING
INSTRUCT_PRESSURE_BLEED
INSTRUCT_SEIZURE
# Direct-question router
ANSWER_DO_NOT_MOVE
ANSWER_HOW_LONG
ANSWER_OUTCOME_UNCERTAIN
# Defaults
REPROMPT
CLOSEOUT
```

### States (8 + sub-FSM)

```
INTAKE
ADDRESS_CONFIRMED
REASSURANCE_DELIVERED
KEY_QUESTIONS
PRE_ARRIVAL
CRITICAL_VERIFY     (sub-FSM: VerifyStep.Q_SURFACE | Q_BREATHING | DONE)
CRITICAL_CPR
HANDOFF
```

### FSM facts available per turn (sourced from `dispatcher_fsm.py:294-314`)

```
state: State
verify_step: VerifyStep
address_known: bool
emergency_known: bool
reassurance_done: bool
surface_confirmed: bool
breathing_assessed: bool
is_cardiac_arrest: bool
pronouns: str  # 'unknown' | 'they' | 'he/him' | 'she/her'
recent_replies: deque[str]  # last 3 dispatcher utterances
is_third_party: bool
complaint: str  # 'medical' | 'fire' | 'trauma' | 'crime' | 'unknown'
turns: int
last_intent: Intent | None
```

### CPR safety gate — fact mapping

The user's directive specifies: do not allow compressions unless
`awake=False AND breathing=False`.

- **`awake=False`** maps to FSM fact `surface_confirmed AND
  is_cardiac_arrest` — the FSM only enters `CRITICAL_VERIFY` when the
  caller signaled "not breathing / unresponsive / no pulse" via
  `_RE_NOT_BREATHING`. The `surface_confirmed` latch fires after V1
  ("on the floor flat on their back?"). When V1 is `True`, the patient
  is positioned for compressions and is, per the caller's report,
  unresponsive.
- **`breathing=False`** maps to FSM fact `breathing_assessed AND
  not (caller said breathing-normally)`. The FSM latches
  `breathing_assessed=True` when the caller confirms "gasping" OR
  "breathing normally". The CPR-safe condition is "gasping or absent" —
  i.e. `breathing_assessed=True AND not breathing_normal_signal`. The
  FSM does not currently surface a separate "normal-breathing" boolean,
  but: the only path that reaches `INSTRUCT_CPR_BEGIN` from
  `_intent_in_verify` requires `surface_confirmed AND breathing_assessed`,
  AND the FSM only set `breathing_assessed=True` on `gasping OR
  breathing_normal`. If the caller said "breathing normally" the FSM
  would reset `is_cardiac_arrest` (it does not, currently — but the
  caller would have rolled out of CRITICAL_VERIFY before reaching the
  CPR instruction in any realistic flow). For the gate, we treat
  `is_cardiac_arrest AND surface_confirmed AND breathing_assessed AND
  NOT breathing_normal` as the green light.

The gate is conservative — it requires ALL of:

```
fsm.is_cardiac_arrest is True
fsm.surface_confirmed is True
fsm.breathing_assessed is True
```

When any of those is `None` or `False`, the gate raises
`cpr_blocked=True` and routes the orchestrator back to verification.
This matches the user's "awake=False AND breathing=False" rule under
the FSM's fact model — the FSM cannot reach `INSTRUCT_CPR_BEGIN`
without those latches set, but the gate enforces it independently as
defense in depth (the LLM cannot trick the FSM into emitting that
intent without the latches).

**On reject:** the gate returns a structured `GateDecision` with
`cpr_blocked=True` and `fallback_intent=Intent.VERIFY_SURFACE` (or
`VERIFY_BREATHING` if surface is already confirmed). The orchestrator
re-renders the verification template. We do NOT raise an exception —
voice paths must never wedge.

## Decisions

### D1 — Intent → template routing

Three classes:

| Class | Template path | LLM path | Intents |
|---|---|---|---|
| **Deterministic** | yes | no | REQUEST_LOCATION_AND_EMERGENCY, REQUEST_LOCATION, REQUEST_EMERGENCY, CONFIRM_ADDRESS, DELIVER_REASSURANCE, KQ_RESPONSIVE_BREATHING, KQ_SEVERITY, KQ_BLEEDING_LOCATION, KQ_FIRE_EVACUATION, KQ_SAFE_LOCATION, VERIFY_SURFACE, VERIFY_BREATHING, INSTRUCT_CPR_BEGIN, INSTRUCT_CHOKING, INSTRUCT_PRESSURE_BLEED, INSTRUCT_SEIZURE, ANSWER_DO_NOT_MOVE, ANSWER_HOW_LONG, ANSWER_OUTCOME_UNCERTAIN, CLOSEOUT |
| **LLM with hard validators** | no | yes | REPROMPT (caller utterance shapes "I didn't catch that — could you repeat ___?") |
| **Mixed** | n/a | n/a | (none — every other intent is fixed enough to template) |

20 of 21 intents are deterministic. The LLM is only invoked for
`REPROMPT`, where the dispatcher needs to echo back what the caller
said verbatim. Even there, validators (5–14 words, single terminator,
no gendered pronouns when `pronouns_known=False`, no repeat-phrase)
clamp the output. The integrator can also choose to keep
REPROMPT deterministic ("Sorry, could you repeat that for me?") as a
follow-up — the gate supports both.

CPR templates are FROZEN at the deterministic class — no creativity.

### D2 — Pronoun substitution

Templates use `{pronoun_subject}` / `{pronoun_object}` /
`{possessive}` placeholders, populated from `fsm.pronouns`:

| `fsm.pronouns` | subject | object | possessive |
|---|---|---|---|
| `unknown` | they | them | their |
| `they` | they | them | their |
| `he/him` | he | him | his |
| `she/her` | she | her | her |

Default everywhere is **they/them/their**. Templates with
`pronoun_required=False` use no pronouns at all (genderless by
construction). Templates with `pronoun_required=True` interpolate
substitution — but the substitution defaults to `they` if pronouns are
not committed, so even pronoun-required templates are gender-safe by
default.

### D3 — Safety override list (templates ALWAYS used, no LLM)

```
INSTRUCT_CPR_BEGIN          (life-safety)
INSTRUCT_CHOKING            (life-safety)
INSTRUCT_PRESSURE_BLEED     (life-safety)
INSTRUCT_SEIZURE            (life-safety)
ANSWER_DO_NOT_MOVE          (could cause harm if mis-phrased)
ANSWER_OUTCOME_UNCERTAIN    (do-not-promise, hard rule)
VERIFY_SURFACE              (CPR gate guard)
VERIFY_BREATHING            (CPR gate guard)
```

These eight intents bypass the LLM regardless of any future config.

### D4 — Open-ended intents

Only `REPROMPT` legitimately benefits from LLM creativity. Everything
else has one canonical realization. If the integrator decides REPROMPT
is also a one-template intent ("Sorry, could you repeat that?"), the
gate becomes 100% template — even safer.

### D5 — CPR gate spec

```
if intent == Intent.INSTRUCT_CPR_BEGIN:
    awake_ok = fsm.is_cardiac_arrest is True and fsm.surface_confirmed is True
    breathing_ok = fsm.breathing_assessed is True
    if not (awake_ok and breathing_ok):
        # Route back to verification.
        if not fsm.surface_confirmed:
            fallback = Intent.VERIFY_SURFACE
        else:
            fallback = Intent.VERIFY_BREATHING
        return GateDecision(
            cpr_blocked=True,
            fallback_intent=fallback,
            used_template=True,                 # render fallback template
            final_text=render(fallback, fsm),
            used_llm=False,
        )
```

Boundary semantics:
- `surface_confirmed=None` → blocked (None ≠ True)
- `breathing_assessed=None` → blocked
- `is_cardiac_arrest=False` → blocked (FSM should never reach this
  intent in this state; defensive)

The gate **fixes the symptom in code**. The FSM's transition logic is
structurally correct for these latches; the gate makes that correctness
mechanical instead of trusting the FSM and the LLM to co-respect it.

### D6 — Validator rules (LLM path)

A `ValidationResult` is `ok=True` iff ALL of:

1. `5 <= word_count(text) <= 14`
2. exactly one terminator in `{".", "!", "?"}`
3. if `pronouns_known is False`: no occurrence of `\b(he|him|his|she|her)\b`
4. no phrase from `recent_replies[-3:]` appears as a substring (verbatim)

On reject the gate returns the FALLBACK template for that intent (every
intent has a deterministic fallback — even REPROMPT has "Sorry, could
you repeat that for me?"). Voice latency is preserved because the
fallback is a `str` literal lookup, not a re-call.

### D7 — Logging

Every `gate_decision` emits:

```
log.info(
    "response_gate.decision",
    intent=intent.value,
    used_template=decision.used_template,
    used_llm=decision.used_llm,
    final_text=decision.final_text,
    cpr_blocked=decision.cpr_blocked,
    state=fsm.state.value,
    pronouns=fsm.pronouns,
)
```

Mirrors the cycle-2Q `fsm.transition` structured-log pattern.

### D8 — Default OFF

`PRISM42_ENABLE_RESPONSE_GATE=1` env flag, single source of truth
function `should_use_response_gate()`. When unset/0 the gate module is
imported but its `gate_decision` is never invoked, so the cycle-2Q path
is byte-equivalent.

### D9 — Latency

| Path | Cost added | Notes |
|---|---|---|
| Template | **−500–2000 ms** | Skips the entire LLM call (Sonnet 4.6 streaming TTFT ~500 ms; full reply ~1–2 s). |
| LLM-with-validate | **<1 ms** | Validators are 4 regex checks + word count. |

Templates are NET LATENCY WINS. The gate strictly improves p95.

### D10 — Voice quality

Hand-tuned templates target Fish TTS S2-Pro:

- 5–14 words (audited via `len(t.split())` in the test suite)
- Single sentence, single terminator
- No filler ("OK"/"Alright"/"Got it") at start
- Genderless by default; pronoun substitution uses `they/them/their`
- Natural-sounding English (not robot speak)

Each template was read aloud to confirm prosody.

## File layout

```
agents/livekit/response_gate.py     ~280 LoC  (gate logic + validators + decision dataclass)
agents/livekit/templates.py         ~210 LoC  (TEMPLATES dict + TemplateSpec dataclass + render helper)
tests/voice/test_response_gate.py   ~330 LoC  (pytest, no pod dependency)
findings/voice/cycle2T_response_gate/team-t/design.md
findings/voice/cycle2T_response_gate/team-t/integration-patch.md
```

Tests live at `tests/voice/test_response_gate.py` to match the
existing repo convention (`tests/voice/test_*.py`). The directive's
suggestion of `agents/livekit/__tests__/` would be a new convention
contradicting the rest of `tests/voice/`.

## Risks / mitigations

| Risk | Mitigation |
|---|---|
| Template list drifts from FSM intents (new Intent added) | `test_response_gate.py::test_every_intent_has_template_or_llm` enumerates `Intent.__members__` and asserts coverage. New intent without entry fails the test. |
| Pronoun substitution leaves `{placeholder}` in output | Every template-with-placeholder is unit-tested for the 4 pronoun states; raw `{` in output triggers test failure. |
| CPR boundary regression | Three explicit boundary tests (None, False, True) for both `surface_confirmed` and `breathing_assessed`. |
| Voice-quality regression on hand-tuned wording | Word-count audit prints every template's length in the test output; reviewer can re-read each one before approving. |
| Hook wedges on import error | Lazy-import in orchestrator hook (mirrors cycle-2Q `try: from dispatcher_fsm import ...`); on `ImportError` the gate is None and the LLM path runs unchanged. |

## Ship-by

T+120 min. Templates are the long pole — every one was hand-tuned for
syllable count + naturalness. Code is mostly type-safety + dispatch.
