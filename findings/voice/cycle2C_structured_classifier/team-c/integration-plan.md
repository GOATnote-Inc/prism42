# Integration Plan — landing the structured classifier in `agents/livekit/`

**Author:** Team C-Architect, prism42 cycle-2C.
**Charter:** READ-ONLY — design only. No code edits in this cycle.
**Default-OFF flag:** `PRISM42_ENABLE_STRUCTURED_CLASSIFIER=1`. Unset / `0` → byte-for-byte identical to current behavior.
**Sources:** schema.json + system-prompt-spec.md + knowledge-base.md (this directory). All file:line refs use `agents/livekit/` as the prefix; line numbers are at HEAD as of 2026-04-26.

---

## 0. One-page change summary

| File | Type | LoC delta | Touches FSM logic? |
|---|---|---:|:---:|
| `agents/livekit/structured_classifier.py` | NEW | +220 | no |
| `agents/livekit/dispatcher_fsm.py` | additive (Features fields + merge helper) | +75 | yes (additive only) |
| `agents/livekit/worker.py` | additive (helper for classifier client) | +25 | no |
| `agents/livekit/orchestrator.py` | additive (call classifier before fsm.transition) | +60 | yes (call-site) |
| `tests/voice/test_structured_classifier.py` | NEW | +260 | no |
| `tests/voice/test_structured_classifier_offline.py` | NEW | +180 (mock-only) | no |
| `findings/voice/cycle2C_structured_classifier/team-c/probe-spec.md` | NEW | +120 | no |
| **Total** | | **~940 LoC** | |

Net: ~6 % growth in `agents/livekit/`. All changes are additive; flag-OFF preserves cycle-2T+R3 behavior byte-for-byte.

---

## 1. NEW file: `agents/livekit/structured_classifier.py` (~220 LoC)

Single new module. Encapsulates schema, JSON validation, and the vLLM call. Imported lazily by the orchestrator only when the env flag is set.

### 1.1 Public surface

```python
# agents/livekit/structured_classifier.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class ClassifierResult:
    """Validated, normalized structured-classifier output for one utterance."""
    intent_category: str   # one of: intake|key_question|verify|instruct|answer|reprompt
    acuity: str            # P1|P2|P3|P4|P5|unknown
    address_raw: str | None
    address_normalized: str | None
    address_has_digit: bool
    awake: bool | None
    breathing: bool | None
    surface: str           # floor|chair|bed|couch|vehicle|standing|unknown
    caller_question: bool
    caller_role: str       # first_party|third_party|unknown
    complaint_category: str  # medical|trauma|fire|crime|unknown
    negation_signal: bool
    direct_question_kind: str  # none|do_not_move|how_long|outcome|did_you_hear|where_sending
    confidence: float
    # Telemetry / debug:
    raw_json: str          # the verbatim JSON the model emitted
    latency_ms: int
    schema_valid: bool     # False -> caller falls back to regex
    fallback_reason: str | None  # "" | "json_parse_error" | "schema_invalid" | "low_confidence" | "vllm_error"

def should_use_structured_classifier() -> bool:
    """Single source of truth for the env flag. Mirrors cycle-2T's
    should_use_response_gate() pattern in response_gate.py:380.
    """
    import os
    return os.environ.get("PRISM42_ENABLE_STRUCTURED_CLASSIFIER", "0") == "1"

async def classify_async(
    client: Any,
    utterance: str,
    *,
    fsm_caller_role_hint: str = "unknown",
    last_dispatcher_intent: str = "none",
    seed: int = 0,
    timeout_ms: int = 600,  # hard ceiling; structured classifier is on the voice hot path
) -> ClassifierResult:
    """Send one classifier turn and return a parsed, validated result.

    Failure modes (set fallback_reason and schema_valid=False; never raise):
      - vLLM call raises   -> fallback_reason="vllm_error"
      - JSON parse fails   -> fallback_reason="json_parse_error"
      - schema invalid     -> fallback_reason="schema_invalid"
      - timeout exceeded   -> fallback_reason="vllm_timeout"
      - confidence < threshold -> fallback_reason="low_confidence" (still returns parsed fields)

    The orchestrator MUST inspect schema_valid + fallback_reason and decide
    whether to merge LLM features into the FSM Features (see §4 below).
    """
    ...

def merge_into_features(
    base: "Features",
    classifier: ClassifierResult,
    *,
    confidence_threshold_high: float = 0.7,
    confidence_threshold_min: float = 0.4,
) -> "Features":
    """Return a NEW Features instance combining regex 'base' with LLM 'classifier'.

    Merge rule (knowledge-base.md §6):
      - Regex always WINS on hard signals: has_address, has_emergency,
        not_breathing, floor_flat, gasping, breathing_normal, choking,
        bleeding, seizure, fire, chest_pain, trauma, is_first_person,
        is_third_party, is_backchannel.
      - LLM populates NEW fields (only present after this cycle):
        acuity, surface, caller_role, complaint_category, negation_signal,
        direct_question_kind, classifier_confidence.
      - LLM SUPPLEMENTS the existing tri-state fields (awake / breathing
        SCHEMA values) only when the regex left them at default AND
        confidence >= confidence_threshold_high.
      - When classifier.fallback_reason is set OR confidence <
        confidence_threshold_min, return base unchanged (LLM is ignored
        this turn).
    """
    ...
```

### 1.2 Implementation notes

- **Schema is loaded once at import time** from `findings/voice/cycle2C_structured_classifier/team-c/schema.json`. (Move to `agents/livekit/schemas/psap_classification.schema.json` at integration time so the prod path doesn't depend on the findings tree.)
- **`jsonschema` package required** — already in requirements (used elsewhere). Validation cost: ~0.3 ms/payload at our schema size.
- **Timeout enforcement** uses `asyncio.wait_for(client.chat.completions.create(...), timeout=timeout_ms/1000)`. On timeout, return `ClassifierResult(fallback_reason="vllm_timeout", schema_valid=False, ...)` with all default values. Voice path NEVER blocks waiting for the classifier.
- **No retry inside `classify_async`** — the voice path cannot afford a second 600 ms attempt. If the first call fails, regex carries the turn.
- **Logging:** every call emits one structured log line:
  ```python
  log.info(
      "structured_classifier.result",
      session_id=session_id,
      intent_category=result.intent_category,
      surface=result.surface,
      negation_signal=result.negation_signal,
      direct_question_kind=result.direct_question_kind,
      confidence=result.confidence,
      schema_valid=result.schema_valid,
      fallback_reason=result.fallback_reason or "",
      latency_ms=result.latency_ms,
  )
  ```
  Mirrors cycle-2T's `response_gate.decision` log line for grep-ability.

---

## 2. MODIFIED file: `agents/livekit/dispatcher_fsm.py` (~75 LoC additive)

### 2.1 Extend `Features` dataclass at line 228-254

ADD to the existing dataclass (do NOT modify any current field):

```python
@dataclass
class Features:
    # ... existing fields (line 232-254) ...

    # ----- cycle-2C structured-classifier supplement (additive) ----
    # Populated only when PRISM42_ENABLE_STRUCTURED_CLASSIFIER=1 AND
    # the classifier returned schema_valid=True AND confidence >=
    # confidence_threshold_high. Default values preserve current behavior
    # when LLM features are unavailable.
    llm_acuity: str = "unknown"
    llm_surface: str = "unknown"
    llm_caller_role: str = "unknown"
    llm_complaint_category: str = "unknown"
    llm_negation_signal: bool = False
    llm_direct_question_kind: str = "none"
    llm_confidence: float = 0.0
    llm_schema_valid: bool = False
    # Tri-state mirrors of awake/breathing — only set when LLM > regex,
    # else None. The FSM helpers prefer regex hard-signals; these are
    # used for negation-handling and for the post-hoc Claude critic.
    llm_awake: bool | None = None
    llm_breathing: bool | None = None
```

LoC: +13. Default values match the "no LLM features" state — when flag is OFF, these stay default forever.

### 2.2 Use `llm_negation_signal` in `_intent_in_verify` to fix Bug 3

Currently the cycle-2R3 fix-candidate adds a regex `_RE_FLOOR_NEGATION` (Team R3 §B3-A). The LLM-driven path is STRICTLY MORE GENERAL than the regex (catches "they're sitting up", "in their wheelchair", "the bed is too high" — long-tail of negations). Wire BOTH (regex ORs LLM):

```python
# In _intent_in_verify (currently dispatcher_fsm.py:573-597 + R3-B3-A patch).
# After Team R3 R3-B3-A lands:
def _intent_in_verify(self, f: Features, t0: float) -> Intent:
    q = self._direct_question_intent(f)
    if q is not None:
        return self._record(q, t0)
    # cycle-2R3 + cycle-2C: caller signaled NOT on the floor.
    surface_negation = f.floor_negation or (
        f.llm_schema_valid
        and f.llm_negation_signal
        and f.llm_surface in ("chair", "bed", "couch", "vehicle", "standing")
    )
    if (not self.surface_confirmed) and surface_negation:
        return self._record(Intent.INSTRUCT_CPR_REPOSITIONING, t0)
    # ... rest unchanged ...
```

LoC: +5 inside the helper. Strictly additive guard — when LLM is unavailable, only the regex path matters (Team R3 R3-B3-A behavior preserved).

### 2.3 Use `llm_direct_question_kind` in `_direct_question_intent` to fix Bug 1 long-tail

Currently the cycle-2R3 fix-candidate adds the `_RE_DID_YOU_HEAR_Q` regex (Team R3 §B1-A). LLM-supplemented version (after R3 lands):

```python
# In _direct_question_intent (currently dispatcher_fsm.py:609-616).
def _direct_question_intent(self, f: Features) -> Intent | None:
    if f.asks_do_not_move:
        return Intent.ANSWER_DO_NOT_MOVE
    if f.asks_how_long:
        return Intent.ANSWER_HOW_LONG
    if f.asks_outcome:
        return Intent.ANSWER_OUTCOME_UNCERTAIN
    if f.asks_heard_address:
        return Intent.ANSWER_HEARD_ADDRESS
    # cycle-2C: if regex did not match BUT LLM caught a question, route.
    if f.llm_schema_valid and f.llm_confidence >= 0.7:
        kind = f.llm_direct_question_kind
        if kind == "do_not_move":
            return Intent.ANSWER_DO_NOT_MOVE
        if kind == "how_long":
            return Intent.ANSWER_HOW_LONG
        if kind == "outcome":
            return Intent.ANSWER_OUTCOME_UNCERTAIN
        if kind in ("did_you_hear", "where_sending"):
            return Intent.ANSWER_HEARD_ADDRESS
    return None
```

LoC: +12. The LLM is the LAST line; regex always wins when it fires.

### 2.4 Acuity surfacing in `next_prompt` (no immediate use, telemetry-only)

The FSM does not currently dispatch on acuity. We add `f.llm_acuity` to `state_summary` for the cycle-2T2 dispatcher UI / Claude critic to consume. ~5 LoC pure additive.

---

## 3. MODIFIED file: `agents/livekit/worker.py` (~25 LoC additive)

The classifier needs an OpenAI-compatible client pointed at the same vLLM endpoint as the prose path. Worker already constructs an `OpenAILLM` (worker.py:695-707). The classifier needs the **raw OpenAI Python client** (`openai.AsyncOpenAI`), not the LiveKit-wrapper.

### 3.1 Add helper at end of worker.py module-level (~+25 LoC)

```python
# worker.py — module level, near the OpenAILLM construction (line 695).
_classifier_client_singleton: Any = None

def _get_classifier_client() -> Any:
    """Return a cached AsyncOpenAI client targeting the local vLLM endpoint.

    Lazily constructed on first call; reused for every classifier turn.
    Pointed at the SAME vLLM instance as the prose LLM (worker.py:700)
    so the schema FSM is compiled once per vLLM session and cached.
    """
    global _classifier_client_singleton
    if _classifier_client_singleton is not None:
        return _classifier_client_singleton
    try:
        from openai import AsyncOpenAI  # noqa: PLC0415
    except Exception:
        return None
    base_url = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8001/v1")
    _classifier_client_singleton = AsyncOpenAI(
        base_url=base_url,
        api_key="EMPTY",
        timeout=2.0,  # outer ceiling; classify_async enforces a tighter ms budget
    )
    return _classifier_client_singleton
```

The orchestrator imports this helper. Default-OFF: when the env flag is unset, the helper is never called and the OpenAI client is never instantiated.

LoC: +25. No regression risk — the prose `OpenAILLM` path is unchanged.

---

## 4. MODIFIED file: `agents/livekit/orchestrator.py` (~60 LoC additive)

The hot path is `FsmDispatcherAgent.on_user_turn_completed` at orchestrator.py:324-492. The classifier call is inserted between utterance extraction (line 338) and FSM transition (line 342).

### 4.1 Lazy import + flag check at module head (~+15 LoC)

After the existing `gate_for_fsm` lazy-import block at orchestrator.py:271-285:

```python
# orchestrator.py — module head, after the gate_for_fsm import block.
try:
    from .structured_classifier import (
        classify_async as _structured_classify_async,
        merge_into_features as _merge_classifier_into_features,
        should_use_structured_classifier,
    )
except Exception:
    _structured_classify_async = None  # type: ignore[assignment]
    _merge_classifier_into_features = None  # type: ignore[assignment]

    def should_use_structured_classifier() -> bool:  # type: ignore[no-redef]
        return False
```

Mirrors the cycle-2T import-fallback pattern at orchestrator.py:271-285.

### 4.2 Modify `on_user_turn_completed` (~+45 LoC additive)

CURRENT (orchestrator.py:336-345):
```python
gate_emitted_template = False
try:
    utterance = (getattr(new_message, "text_content", None) or "").strip()
    if not utterance:
        return
    intent = self._fsm.transition(utterance)
```

CYCLE-2C VERSION (additive — current behavior preserved when flag is off):
```python
gate_emitted_template = False
try:
    utterance = (getattr(new_message, "text_content", None) or "").strip()
    if not utterance:
        return

    # cycle-2C: structured classifier runs BEFORE FSM transition. The
    # classifier output is merged into the regex Features by the FSM,
    # but the FSM still calls its own classify() — the LLM is supplemental.
    classifier_result = None
    if (
        should_use_structured_classifier()
        and _structured_classify_async is not None
        and _classifier_client is not None
    ):
        try:
            classifier_result = await _structured_classify_async(
                _classifier_client,
                utterance,
                fsm_caller_role_hint=("first" if not self._fsm.is_third_party else "third"),
                last_dispatcher_intent=(
                    self._fsm.last_intent.value if self._fsm.last_intent else "none"
                ),
                timeout_ms=600,
            )
        except Exception as classifier_err:  # noqa: BLE001
            local_log.warning(
                "structured_classifier.call_failed",
                err=str(classifier_err)[:200],
                session_id=self._session_id,
            )
            classifier_result = None

    intent = self._fsm.transition(utterance, classifier=classifier_result)
```

Two changes:
1. Inserts the classifier call (whole block conditional on flag — short-circuits when OFF).
2. Passes `classifier=classifier_result` to `self._fsm.transition`. This requires extending `transition()` signature to accept an optional `classifier` kwarg.

### 4.3 Extend `DispatcherFSM.transition` to accept `classifier` (~+10 LoC in dispatcher_fsm.py)

```python
# dispatcher_fsm.py:436 (existing transition method).
def transition(
    self,
    utterance: str,
    *,
    classifier: "ClassifierResult | None" = None,
) -> Intent:
    """Compute the next intent. Mutates state. <1 ms on B300.

    cycle-2C: if `classifier` is provided AND schema_valid, the
    LLM-derived fields supplement the regex Features (merge rule in
    structured_classifier.merge_into_features). Otherwise behaves
    identically to today.
    """
    t0 = time.monotonic()
    f = classify(utterance)
    if classifier is not None and classifier.schema_valid:
        # In-place merge — Features is a dataclass, so we just set the
        # llm_* fields. Hard signals already populated by classify();
        # we never overwrite them.
        f.llm_acuity = classifier.acuity
        f.llm_surface = classifier.surface
        f.llm_caller_role = classifier.caller_role
        f.llm_complaint_category = classifier.complaint_category
        f.llm_negation_signal = classifier.negation_signal
        f.llm_direct_question_kind = classifier.direct_question_kind
        f.llm_confidence = classifier.confidence
        f.llm_schema_valid = True
        f.llm_awake = classifier.awake
        f.llm_breathing = classifier.breathing
    self.turns += 1
    # ... rest unchanged ...
```

LoC: +10 in transition (the merge block) plus +1 import for ClassifierResult type alias.

### 4.4 No changes to the response gate path

The cycle-2T response gate at orchestrator.py:372-446 is downstream of `transition()`. It receives the same `Intent` regardless of whether the classifier ran. Templates render the same. Voice path is unchanged.

The classifier improves WHICH intent the FSM picks; it does not change WHAT is spoken (templates are deterministic).

---

## 5. NEW file: `tests/voice/test_structured_classifier_offline.py` (~180 LoC, mock-only)

Pytest, no pod / vLLM dependency. Tests:

1. `test_schema_validates_self()` — load schema.json, run `Draft7Validator.check_schema(schema)`.
2. `test_classify_async_with_mock_returns_clean_result()` — mock `AsyncOpenAI`, return canned JSON for each of the 5 examples in system-prompt-spec.md, assert `ClassifierResult` fields.
3. `test_classify_async_handles_invalid_json()` — mock returns `"not json"`, assert `fallback_reason="json_parse_error"`.
4. `test_classify_async_handles_schema_violation()` — mock returns valid JSON missing required field, assert `fallback_reason="schema_invalid"`.
5. `test_classify_async_handles_timeout()` — mock raises asyncio.TimeoutError, assert `fallback_reason="vllm_timeout"`.
6. `test_merge_into_features_regex_wins_on_hard_signals()` — base Features with `has_address=True`, classifier with `surface="chair"`. Assert `has_address` unchanged AND `llm_surface == "chair"`.
7. `test_merge_into_features_low_confidence_ignores_classifier()` — classifier confidence=0.3, assert merged Features == base Features.
8. `test_merge_into_features_high_confidence_supplements_tri_state()` — classifier confidence=0.9 with `awake=False, breathing=False`, base Features all default. Assert `llm_awake=False, llm_breathing=False`.

All mock-only; runs offline, in CI, in <1 second.

---

## 6. NEW file: `tests/voice/test_structured_classifier.py` (~260 LoC, requires VLLM_BASE_URL)

Pytest with `pytest.mark.skipif(not os.environ.get('VLLM_BASE_URL'), reason='requires live vLLM')`. Pod-only. Tests:

1. `test_live_classifier_example_1_chest_pain` — feed Example 1 utterance, assert `intent_category=="intake"`, `acuity=="P1"`, `complaint_category=="medical"`, `caller_role=="third_party"`.
2. `test_live_classifier_example_2_not_breathing` — feed Example 2, assert `awake=False`, `breathing=False`, `intent_category=="verify"`.
3. `test_live_classifier_example_3_in_a_chair` (Bug 3 case) — assert `surface=="chair"`, `negation_signal==True`.
4. `test_live_classifier_example_4_did_you_hear` (Bug 1 case) — assert `caller_question==True`, `direct_question_kind=="did_you_hear"`.
5. `test_live_classifier_example_5_backchannel` (Bug 2 case) — feed "uh okay", assert `confidence < 0.4` AND `intent_category=="reprompt"`.
6. `test_live_classifier_50_synthetic_utterances` — load `tests/voice/fixtures/synthetic_caller_*.txt`, classify each, assert ≥99 % JSON-valid AND ≥90 % per-field accuracy on hand-labeled gold.
7. `test_live_classifier_latency_p95` — 20 calls, assert p95 < 600 ms (the timeout ceiling). Median target < 300 ms.

Run via `make test-classifier-live` on the pod. Out of CI by default.

---

## 7. NEW file: `findings/voice/cycle2C_structured_classifier/team-c/probe-spec.md` (~120 LoC)

The integration probe — copy/paste shell sequence the integrator runs after deploying the classifier flag-on. Lives in this directory because it ships with the cycle artifact, not in `tests/`.

Sections:
1. Pre-deploy: assert `PRISM42_ENABLE_STRUCTURED_CLASSIFIER=0` in production. Run cycle-2T regression set; baseline pass rate.
2. Deploy: flip flag to `1`. Re-run cycle-2T regression set. Pass rate should be ≥ baseline (any regression is a no-go for cycle-2C).
3. Live probe: 6 dispatched calls (Examples 1-5 + one nominal cardiac scenario). Listen for voice-quality regressions; check `worker.log` for `structured_classifier.result` lines per turn; assert no `structured_classifier.call_failed` lines.
4. p95 latency probe: 60 turns measured end-to-end via dispatcher UI; assert p95 < cycle-2T baseline + 80 ms (the classifier budget).
5. Rollback: `unset PRISM42_ENABLE_STRUCTURED_CLASSIFIER && systemctl restart prism42-worker.service`. Voice path returns to cycle-2T+R3 behavior immediately.

---

## 8. Default-OFF semantics — verified

When `PRISM42_ENABLE_STRUCTURED_CLASSIFIER` is unset OR `0`:

- `should_use_structured_classifier() == False`. → orchestrator's `if should_use...:` block at §4.2 is skipped.
- `classifier_result` stays `None`.
- `self._fsm.transition(utterance, classifier=None)` is called.
- Inside `transition()`, the `if classifier is not None and classifier.schema_valid:` guard fails. None of the `f.llm_*` fields are set; they stay at default (`""`, `False`, `0.0`).
- `_direct_question_intent` and `_intent_in_verify` use the `llm_*` fields ONLY inside `if f.llm_schema_valid:` guards. Guard fails → only regex paths fire.
- The voice path takes the cycle-2T+R3 trajectory exactly as today.

When `PRISM42_ENABLE_STRUCTURED_CLASSIFIER=1`:

- The classifier is invoked once per non-empty utterance.
- On classifier failure (parse, schema, timeout, vllm error): `schema_valid=False`, `f.llm_schema_valid=False`, FSM falls back to regex-only — same as flag-OFF.
- On classifier success: `f.llm_*` fields populated; FSM helpers consume them as supplemental signal.

---

## 9. Backwards-compat with `Features` dataclass

The Features dataclass at dispatcher_fsm.py:228-254 has 21 fields today. We add 10 more (`llm_*`). All have defaults. Anyone constructing a Features manually (no one does — only `classify()` constructs them) gets the defaults.

Tests that snapshot `Features` (none today, but possible in the future) should compare on the regex-derived fields only. We add a comment to the dataclass:

```python
# llm_* fields are supplemental — set ONLY when cycle-2C flag is on AND
# the classifier returned schema_valid=True with confidence >= 0.7. Tests
# snapshotting Features should not assert on these fields unless the
# classifier path is explicitly under test.
```

---

## 10. Interaction with cycle-2T (response gate), cycle-2I (interruption), cycle-2R3 (R3 fixes)

| Cycle | Interaction | Resolution |
|---|---|---|
| **cycle-2T** (response gate) | Gate runs AFTER the FSM picks an intent. The classifier improves WHICH intent the FSM picks; the gate's logic is unchanged. CPR safety gate, validators, fallback templates — all preserved. | No conflict. Composable. |
| **cycle-2I** (interruption fix) | Interruption handling is at LiveKit `TurnHandlingOptions` level (worker.py:759-) — entirely upstream of `on_user_turn_completed`. The classifier adds ~280 ms median to the on_user_turn_completed budget but the gate's StopResponse fires from the same hook so the LLM-prose path is still cancelled correctly. | No conflict. The classifier latency must stay below LiveKit's preemptive-generation deadline (~500 ms typical) — see §11. |
| **cycle-2R3** (R3 bug fixes) | R3-B1-A (`asks_heard_address`), R3-B2-A (`is_backchannel`), R3-B3-A (`floor_negation`) all land BEFORE cycle-2C. The classifier supplements those regex paths; it does NOT replace them. | Composable; cycle-2C makes R3 strictly more general. |
| **cycle-2P2** (spelled-cardinal normalizer) | Runs INSIDE `classify()` at dispatcher_fsm.py:347-351. The LLM also does its own normalization in the `address_candidate.normalized` field. Redundant but harmless — they should agree on common cases. | No conflict. The FSM trusts its own normalizer. The LLM's `address_candidate.normalized` is telemetry. |

---

## 11. Latency budget — does the classifier fit?

Current cycle-2T+R3 hot path budget (orchestrator.py:419 — `gate_template_ms`):
- FSM transition: < 1 ms
- Gate decision + render: < 1 ms
- session.say() invocation: < 1 ms
- StopResponse raise + LiveKit cancel: ~5 ms
- **Total: ~10 ms** when the gate fires a template.

Cycle-2C adds:
- Classifier vLLM call: 200-300 ms median, < 600 ms p95 (timeout ceiling).

The classifier runs SEQUENTIALLY before `fsm.transition`. So end-to-end first-speakable-byte latency goes from ~10 ms to ~300 ms median. **This is acceptable for the voice path** because:

1. LiveKit's preemptive-generation kicks off the LLM-prose path on the partial STT transcript at the BACKCHANNEL detection point (typically ~500 ms before STT-final). When STT-final arrives, our `on_user_turn_completed` fires — by which point the LLM-prose path has been streaming for ~500 ms already.
2. With cycle-2T, we issue `StopResponse()` to cancel the LLM-prose stream as soon as the gate fires a template. The user hears the gate template, NOT the prose stream.
3. The classifier adds 200-300 ms to the gate-fire decision. The LLM-prose path is still cancelled before any tokens reach Fish TTS (TTS audio synthesis itself is buffered behind ~100 ms).
4. Net: the user-perceived TTFT increases by ~250 ms median. This is below LiveKit's `min_delay=500ms` endpointing window — i.e. the caller has not yet heard "silence" for long enough to perceive a regression.

**If p95 of the classifier exceeds 600 ms** (timeout ceiling), the classifier returns `fallback_reason="vllm_timeout"` and the FSM proceeds with regex-only features. The user still gets a reply at the same latency as today. This is the safety net.

**If the median exceeds 400 ms**, we have a regression — flag this in the probe and consider tightening the timeout to 400 ms (the voice path can absorb 400 ms but not 600 ms).

---

## 12. Telemetry surface for the Claude critic (Team B-Critic)

The critic consumes the FSM state JSON post-turn. Cycle-2C adds the following fields to the `dispatch_publisher.publish_turn` payload (orchestrator.py:354-360, dispatch_publisher.py):

```json
{
  "turn_id": "...",
  "fsm_state": "key_questions",
  "fsm_intent": "kq_responsive_breathing",
  "regex_features": { ... existing regex fields ... },
  "classifier": {
    "intent_category": "key_question",
    "acuity": "P1",
    "address_candidate": { "raw_text": null, "normalized": null, "has_digit": false },
    "awake": null, "breathing": null,
    "surface": "unknown",
    "caller_question": false,
    "caller_role": "third_party",
    "complaint_category": "medical",
    "negation_signal": false,
    "direct_question_kind": "none",
    "confidence": 0.91,
    "schema_valid": true,
    "fallback_reason": null,
    "latency_ms": 248
  },
  "merged_features_diff": {
    // diff of llm_* fields the merge actually applied
  }
}
```

This payload feeds:
1. The dispatcher UI (turn pane).
2. The Claude critic (cycle-2BC, parallel work). The critic's job is to flag turns where regex and LLM disagreed on a hard signal — those are training-data signals for prompt revision.

LoC for this addition: ~30 in dispatch_publisher.py, ~15 in orchestrator.py. Counted in Team C's totals as "Team B-Critic surface" — a shared dependency.

---

## 13. Ship sequence (proposed; not a directive)

1. Land Team R3 fixes (R3-B1-A, R3-B2-A, R3-B3-A) — they are already in dispatcher_fsm.py per the line counts shown. Confirm they're flag-on.
2. Land cycle-2C with the env flag DEFAULT-OFF. Run cycle-2T regression with flag-OFF — must be byte-identical to current.
3. Run pod-only `tests/voice/test_structured_classifier.py` — must pass.
4. Flip flag-ON in staging. Run live probe per `probe-spec.md`.
5. Promote to production behind the same flag (default-ON in production after 24h soak, no regression).

---

## 14. Files NOT touched (and why)

- `agents/livekit/templates.py` — templates are deterministic by design (Team T D3, the safety override list). Cycle-2C does not propose new templates. The R3 fix candidates already added `instruct_cpr_repositioning` and `answer_heard_address`; cycle-2C consumes those.
- `agents/livekit/response_gate.py` — gate logic is downstream of FSM. Unchanged.
- `agents/livekit/fish_speech_tts.py`, `parakeet_stt.py` — voice quality is sacrosanct.
- `agents/livekit/dispatch_publisher.py` (heavy modification) — only one additive payload field. Schema-compatible.
- `agents/livekit/install_worker.sh`, `prism42-worker.service` — no env-var injection needed; the worker process inherits PRISM42_ENABLE_STRUCTURED_CLASSIFIER from the unit's EnvironmentFile.

---

## 15. References

- schema.json (this directory)
- system-prompt-spec.md (this directory)
- knowledge-base.md (this directory)
- Team N3 prompt-template-spec.md
- Team T design.md (cycle-2T response gate)
- Team R3 fix-candidates.md (the three live bugs and proposed regex fixes)
- agents/livekit/orchestrator.py:271-285 (lazy-import pattern), :324-492 (on_user_turn_completed)
- agents/livekit/dispatcher_fsm.py:228-254 (Features), :436-490 (transition), :573-597 (_intent_in_verify), :609-616 (_direct_question_intent)
- agents/livekit/worker.py:680-707 (LLM construction site)
- agents/livekit/response_gate.py:380 (`should_use_response_gate` flag pattern)
