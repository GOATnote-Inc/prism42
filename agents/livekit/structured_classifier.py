"""structured_classifier — Nemotron PSAP utterance classifier (cycle-2C Phase 1).

SHADOW mode wrapper. Calls the local vLLM endpoint with response_format =
json_schema, parses the 12-field JSON, validates via dataclass field check,
returns a normalized ClassifierResult. The orchestrator runs this as a
fire-and-forget background task AFTER fsm.transition() so the classifier
output is logged + published over the dispatch data-track but NEVER mutates
FSM state. FSM behavior is byte-equivalent to today.

Charter constraints
-------------------
- Default OFF behind PRISM42_ENABLE_SHADOW_CLASSIFIER. When unset / "0",
  should_use_shadow_classifier() returns False and the classifier is never
  invoked. The orchestrator's fire-and-forget block short-circuits.
- 600 ms hard timeout (Munger inversion — failure mode 3). On timeout
  return None; caller treats that as "no classifier signal this turn".
- Schema validation via stdlib only — no jsonschema dep. We dataclass-check
  the 12 required fields + their type/enum constraints. Validation errors
  return None + log classifier.invalid_schema.
- enable_thinking=False is MANDATORY (vLLM #37362 — paired with
  response_format). Already proved correct in cycle-1 N3-R2.
- temperature=0, seed=0 — reproducible greedy decode (Team C
  system-prompt-spec §5).
- max_tokens=192 — Team C system-prompt-spec §5; vLLM #30904 requires >=96.
- Lazy openai import — only happens on first classify_async call.

Spec sources
------------
- findings/voice/cycle2C_structured_classifier/team-c/integration-plan.md §1
- findings/voice/cycle2C_structured_classifier/team-c/schema.json
- findings/voice/cycle2C_structured_classifier/team-c/system-prompt-spec.md
- findings/voice/cycle2C_structured_classifier/team-c/munger-inversion.md
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()


# ---------------------------------------------------------------------
# Env flag — SHADOW mode default OFF.
# ---------------------------------------------------------------------

_ENV_FLAG = "PRISM42_ENABLE_SHADOW_CLASSIFIER"


def should_use_shadow_classifier() -> bool:
    """Single source of truth for the shadow-classifier env-flag gate.

    When False (the default), worker.py skips constructing the classifier
    client and orchestrator.py skips the fire-and-forget call. The
    classifier module is import-safe — it never instantiates the openai
    client at import time.
    """
    return os.environ.get(_ENV_FLAG, "0") == "1"


# ---------------------------------------------------------------------
# Schema constants — copied inline from schema.json so we don't depend
# on the findings tree at runtime. Cross-check by hand on schema bumps.
# ---------------------------------------------------------------------

_INTENT_VALUES = {"intake", "key_question", "verify", "instruct", "answer", "reprompt"}
_ACUITY_VALUES = {"P1", "P2", "P3", "P4", "P5", "unknown"}
_SURFACE_VALUES = {"floor", "chair", "bed", "couch", "vehicle", "standing", "unknown"}
_CALLER_ROLE_VALUES = {"first_party", "third_party", "unknown"}
_COMPLAINT_VALUES = {"medical", "trauma", "fire", "crime", "unknown"}
_DIRECT_QUESTION_VALUES = {
    "none", "do_not_move", "how_long", "outcome", "did_you_hear", "where_sending",
}

_REQUIRED_TOP = (
    "intent", "acuity", "address_candidate", "awake", "breathing", "surface",
    "caller_question", "caller_role", "complaint_category", "negation_signal",
    "direct_question_kind", "confidence",
)
_REQUIRED_ADDRESS = ("raw_text", "normalized", "has_digit")


# ---------------------------------------------------------------------
# Result dataclass — normalized & schema-validated classifier output.
# ---------------------------------------------------------------------


@dataclass
class AddressCandidate:
    raw_text: str | None = None
    normalized: str | None = None
    has_digit: bool = False


@dataclass
class ClassifierResult:
    """Validated, normalized structured-classifier output for one utterance."""

    intent: str  # one of _INTENT_VALUES
    acuity: str  # one of _ACUITY_VALUES
    address_candidate: AddressCandidate = field(default_factory=AddressCandidate)
    awake: bool | None = None
    breathing: bool | None = None
    surface: str = "unknown"
    caller_question: bool = False
    caller_role: str = "unknown"
    complaint_category: str = "unknown"
    negation_signal: bool = False
    direct_question_kind: str = "none"
    confidence: float = 0.0
    # Telemetry — populated by classify_async.
    raw_json: str = ""
    latency_ms: int = 0

    def to_payload(self) -> dict[str, Any]:
        """Render for dispatch_publisher (JSON-safe)."""
        d = asdict(self)
        return d


# ---------------------------------------------------------------------
# System prompt — verbatim from system-prompt-spec.md §3.
# ---------------------------------------------------------------------

SYSTEM_PROMPT = """\
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
"""


# Schema sent to vLLM via response_format. Inline so the worker doesn't read
# the findings tree. Cross-check on schema.json bumps.
_RESPONSE_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_REQUIRED_TOP),
    "properties": {
        "intent": {"type": "string", "enum": sorted(_INTENT_VALUES)},
        "acuity": {"type": "string", "enum": sorted(_ACUITY_VALUES)},
        "address_candidate": {
            "type": "object",
            "additionalProperties": False,
            "required": list(_REQUIRED_ADDRESS),
            "properties": {
                "raw_text": {"type": ["string", "null"], "maxLength": 200},
                "normalized": {"type": ["string", "null"], "maxLength": 200},
                "has_digit": {"type": "boolean"},
            },
        },
        "awake": {"type": ["boolean", "null"]},
        "breathing": {"type": ["boolean", "null"]},
        "surface": {"type": "string", "enum": sorted(_SURFACE_VALUES)},
        "caller_question": {"type": "boolean"},
        "caller_role": {"type": "string", "enum": sorted(_CALLER_ROLE_VALUES)},
        "complaint_category": {"type": "string", "enum": sorted(_COMPLAINT_VALUES)},
        "negation_signal": {"type": "boolean"},
        "direct_question_kind": {"type": "string", "enum": sorted(_DIRECT_QUESTION_VALUES)},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


# ---------------------------------------------------------------------
# Validation — stdlib only, no jsonschema dep.
# ---------------------------------------------------------------------


def _validate_payload(payload: Any) -> ClassifierResult | None:
    """Validate parsed JSON against the schema; return ClassifierResult or None.

    Returns None on any structural / type / enum violation. Caller logs.
    """
    if not isinstance(payload, dict):
        return None
    # Top-level required.
    for k in _REQUIRED_TOP:
        if k not in payload:
            return None
    # Field-by-field type/enum checks.
    intent = payload.get("intent")
    if not isinstance(intent, str) or intent not in _INTENT_VALUES:
        return None
    acuity = payload.get("acuity")
    if not isinstance(acuity, str) or acuity not in _ACUITY_VALUES:
        return None
    addr = payload.get("address_candidate")
    if not isinstance(addr, dict):
        return None
    for k in _REQUIRED_ADDRESS:
        if k not in addr:
            return None
    raw_text = addr.get("raw_text")
    if raw_text is not None and not isinstance(raw_text, str):
        return None
    normalized = addr.get("normalized")
    if normalized is not None and not isinstance(normalized, str):
        return None
    has_digit = addr.get("has_digit")
    if not isinstance(has_digit, bool):
        return None
    awake = payload.get("awake")
    if awake is not None and not isinstance(awake, bool):
        return None
    breathing = payload.get("breathing")
    if breathing is not None and not isinstance(breathing, bool):
        return None
    surface = payload.get("surface")
    if not isinstance(surface, str) or surface not in _SURFACE_VALUES:
        return None
    caller_question = payload.get("caller_question")
    if not isinstance(caller_question, bool):
        return None
    caller_role = payload.get("caller_role")
    if not isinstance(caller_role, str) or caller_role not in _CALLER_ROLE_VALUES:
        return None
    complaint = payload.get("complaint_category")
    if not isinstance(complaint, str) or complaint not in _COMPLAINT_VALUES:
        return None
    negation = payload.get("negation_signal")
    if not isinstance(negation, bool):
        return None
    dqk = payload.get("direct_question_kind")
    if not isinstance(dqk, str) or dqk not in _DIRECT_QUESTION_VALUES:
        return None
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    confidence = float(confidence)
    if confidence < 0.0 or confidence > 1.0:
        return None
    return ClassifierResult(
        intent=intent,
        acuity=acuity,
        address_candidate=AddressCandidate(
            raw_text=raw_text,
            normalized=normalized,
            has_digit=has_digit,
        ),
        awake=awake,
        breathing=breathing,
        surface=surface,
        caller_question=caller_question,
        caller_role=caller_role,
        complaint_category=complaint,
        negation_signal=negation,
        direct_question_kind=dqk,
        confidence=confidence,
    )


# ---------------------------------------------------------------------
# Client builder — lazy openai import. Returns None on any failure so
# orchestrator can short-circuit cleanly.
# ---------------------------------------------------------------------


def build_classifier_client() -> Any | None:
    """Return an openai.AsyncOpenAI client targeting the vLLM endpoint, or None.

    Mirrors the existing OpenAILLM construction in worker.py:695 — same
    base_url default (VLLM_BASE_URL) so the schema FSM is compiled once
    per vLLM session and cached. Outer 2.0 s timeout is the absolute
    ceiling; classify_async enforces a tighter 600 ms budget per call.
    """
    try:
        from openai import AsyncOpenAI  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        log.warning("classifier.openai_import_failed", err=str(e)[:200])
        return None
    try:
        base_url = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8001/v1")
        client = AsyncOpenAI(
            base_url=base_url,
            api_key="EMPTY",
            timeout=2.0,
        )
        return client
    except Exception as e:  # noqa: BLE001
        log.warning("classifier.client_init_failed", err=str(e)[:200])
        return None


# ---------------------------------------------------------------------
# classify_async — the main entry point. Returns ClassifierResult or None.
# Never raises.
# ---------------------------------------------------------------------


async def classify_async(
    client: Any,
    utterance: str,
    *,
    model: str | None = None,
    seed: int = 0,
    timeout_ms: int = 600,
) -> ClassifierResult | None:
    """Send one classifier turn; return ClassifierResult or None.

    None is returned (and logged) on any failure path:
      - Empty / missing utterance.
      - Client missing or vLLM call raises.
      - asyncio timeout (timeout_ms ceiling).
      - JSON parse failure.
      - Schema validation failure.

    The voice path NEVER blocks waiting for this — orchestrator runs the
    coroutine via asyncio.create_task() and consumes the result in a
    callback. Even the timeout itself is a soft observation; on shadow-
    mode this only affects logging, not FSM behavior.
    """
    if not utterance:
        return None
    if client is None:
        return None
    model_name = model or os.environ.get(
        "VLLM_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4",
    )
    t0 = time.monotonic()
    try:
        coro = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": utterance},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "psap_classification",
                    "schema": _RESPONSE_FORMAT_SCHEMA,
                    "strict": True,
                },
            },
            extra_body={
                # MANDATORY pairing with response_format — see vLLM #37362.
                "chat_template_kwargs": {"enable_thinking": False},
            },
            temperature=0.0,
            seed=seed,
            max_tokens=192,
        )
        response = await asyncio.wait_for(coro, timeout=timeout_ms / 1000.0)
    except asyncio.TimeoutError:
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.warning(
            "classifier.timeout",
            timeout_ms=timeout_ms,
            latency_ms=latency_ms,
            utterance=utterance[:120],
        )
        return None
    except Exception as e:  # noqa: BLE001
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.warning(
            "classifier.error",
            err=str(e)[:200],
            latency_ms=latency_ms,
            utterance=utterance[:120],
        )
        return None

    latency_ms = int((time.monotonic() - t0) * 1000)
    try:
        raw = response.choices[0].message.content or ""
    except Exception as e:  # noqa: BLE001
        log.warning("classifier.bad_response_shape", err=str(e)[:200])
        return None
    if not raw:
        log.warning(
            "classifier.empty_content",
            latency_ms=latency_ms,
            utterance=utterance[:120],
        )
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning(
            "classifier.json_parse_error",
            err=str(e)[:200],
            raw_excerpt=raw[:200],
            latency_ms=latency_ms,
        )
        return None
    result = _validate_payload(payload)
    if result is None:
        log.warning(
            "classifier.invalid_schema",
            raw_excerpt=raw[:200],
            latency_ms=latency_ms,
        )
        return None
    result.raw_json = raw
    result.latency_ms = latency_ms
    log.info(
        "classifier.perception",
        intent=result.intent,
        acuity=result.acuity,
        surface=result.surface,
        caller_role=result.caller_role,
        complaint_category=result.complaint_category,
        caller_question=result.caller_question,
        negation_signal=result.negation_signal,
        direct_question_kind=result.direct_question_kind,
        awake=result.awake,
        breathing=result.breathing,
        address_has_digit=result.address_candidate.has_digit,
        confidence=result.confidence,
        latency_ms=latency_ms,
        utterance=utterance[:200],
    )
    return result
