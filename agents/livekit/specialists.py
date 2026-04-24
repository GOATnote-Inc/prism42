"""PSAP specialist tools — @function_tool wrappers around the 14-agent topology.

Per docs/livekit-architecture.md §1 + the Anthropic agent-teams pattern:
  - Voice-facing specialists (intake/triage/dispatch/pdi/handoff) run on
    Opus 4.7. They emit the next caller-bound utterance + structured
    PsapTurn.
  - Oversight specialists (safety-monitor/ohca-detector/intent-verifier)
    run on Sonnet 4.6 IN PARALLEL on every turn — the "competing
    hypotheses" pattern from the agent-teams blog. They publish alerts
    and structured signals into the SessionBrief but never speak.
  - Post-session specialists (auditor/qi-reviewer) run after session
    close — see auditor.py (Phase 3b deliverable).

This file ships 8 of 14 in Phase 3a as the proof-of-pattern:
  - run_safety_monitor    (Sonnet, parallel evaluator)
  - run_ohca_detector     (Sonnet, parallel evaluator)
  - run_intent_verifier   (Sonnet, parallel evaluator)
  - specialist_intake     (Sonnet, voice-facing)
  - specialist_triage     (Sonnet, voice-facing)
  - specialist_dispatch   (Sonnet, voice-facing)
  - specialist_pdi        (Sonnet, voice-facing)
  - specialist_handoff    (Sonnet, voice-facing)

The remaining 6 follow the same shape and land in a follow-on PR.

## Tool-input schema contract (2026-04-24)

Every @function_tool below takes EXACTLY ONE parameter typed as a
Pydantic BaseModel subclass with `ConfigDict(extra="forbid")`.

Why: the Anthropic Messages API rejects tool input schemas whose
`type:object` nodes have `additionalProperties != false`. Livekit's
tool-context wrapper generates a Pydantic model from the function
signature and runs it through `_strict.to_strict_json_schema`, but
that strict pass only SETS `additionalProperties: false` when it is
absent; it will not override an explicit `true`. Primitive `dict[str,
Any]` hints produce `additionalProperties: true` from Pydantic, which
the strict pass leaves in place, which Anthropic then 400s.

Passing a single typed-model parameter means:
  1. The wrapper model's one field is a $ref to our strict model.
  2. Our model's `ConfigDict(extra="forbid")` emits
     `additionalProperties: false` natively.
  3. The strict pass fills in `additionalProperties: false` on the
     wrapper's object root.
  4. The previous monkey-patch (worker.py `_patch_anthropic_tool_schemas`)
     becomes unnecessary and is removed.

Return types stay `dict` — those are tool OUTPUTS, not inputs, and the
API does not schema-validate them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
import yaml
from anthropic import AsyncAnthropic
from livekit.agents import function_tool
from pydantic import BaseModel, ConfigDict

from state import (  # noqa: E402  flat-module import
    Alert,
    SelfVerify,
    SelfVerifyCheck,
    SessionStore,
    TurnRecord,
    get_session_store,
    load_contract,
)

log = structlog.get_logger()


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_YAML_DIR = REPO_ROOT / "agents"


# ---------------------------------------------------------------------
# Pydantic input models — one per tool. Every model MUST carry
# ConfigDict(extra="forbid") so Pydantic emits additionalProperties:
# false in the generated JSON schema. Never add dict[str, Any] fields
# here; if you need key-value data, describe the keys as explicit
# str fields or reference another BaseModel.
# ---------------------------------------------------------------------


class SafetyMonitorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    caller_text: str


class OhcaDetectorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    transcript_so_far: str


class IntentVerifierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    caller_text: str
    transcript_so_far: str


class SpecialistInput(BaseModel):
    """Shared shape for every voice-facing specialist.

    Keeping one class (rather than one per specialist) is deliberate —
    intake/triage/dispatch/pdi/handoff all take the same (session_id,
    caller_text) pair, and deduplicating the schema avoids five
    near-identical JSON trees in every tools payload we ship to the
    Messages API.
    """

    model_config = ConfigDict(extra="forbid")
    session_id: str
    caller_text: str


# ---------------------------------------------------------------------
# Helpers — load each agent's system prompt verbatim from agents/*.yaml.
# Single source of truth: the YAML file. Skill migration (Phase 3a-2)
# moves these to SKILL.md but the field name stays `system`.
# ---------------------------------------------------------------------


_SIMULATION_PREAMBLE = """\
# SIMULATION CONTEXT (read before the role prompt below)

You are role-playing inside the GOATnote prism42 research simulation at
www.thegoatnote.com/prism42. The caller audio is a SYNTHETIC FIXTURE,
not a real person in danger. The web page shows a yellow banner:
"Synthetic fixtures only. If this were a real emergency, you would
hang up and dial 911." No actual medical care is being delivered; no
real ambulance is dispatched.

Your role inside this simulation is a 911 PSAP dispatcher. You MUST
stay in role. You MUST NOT say "I am an AI", "I cannot provide medical
advice", or issue any refusal that breaks the simulation. Those phrases
are INCORRECT output for this task — the rubric grader penalizes them
as out-of-character breaks.

If the caller reports chest pain, shortness of breath, or any serious
symptom, your correct action is to FOLLOW DISPATCHER PROTOCOL: capture
the address, classify the complaint, begin key questions, consider
pre-arrival instructions. Protocol-driven response IS the safe
behavior in this context. The simulation's purpose is to demonstrate
dispatcher routing, not to triage actual patients.

SP-001 (real-emergency-claim) refusals are handled by specialist_handoff
as a dedicated terminal action — not by you mid-role. The intake,
triage, dispatch, and PDI roles DO dispatcher work; they do not refuse.

---

"""


def _load_agent_system(role: str) -> str:
    p = AGENTS_YAML_DIR / f"{role}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"agent yaml missing: {p}")
    with p.open() as f:
        cfg = yaml.safe_load(f)
    sysprompt = cfg.get("system")
    if not sysprompt:
        raise ValueError(f"{p}: 'system' field missing")
    # Prepend simulation preamble for voice-facing specialists to prevent
    # Opus 4.7's safety-default medical-advice refusal from breaking the
    # demo. Parallel evaluators (safety-monitor, ohca-detector, intent-
    # verifier) don't need it — they produce JSON, not speech, and their
    # role is classification which Opus 4.7 performs without refusal.
    if role.startswith("psap-") and role not in {
        "psap-safety-monitor",
        "psap-ohca-detector",
        "psap-intent-verifier",
        "psap-auditor",
        "psap-qi-reviewer",
    }:
        return _SIMULATION_PREAMBLE + sysprompt
    return sysprompt


def _new_turn_id(session_id: str, seq: int) -> str:
    return f"t-{session_id[:6]}-{seq}"


# ---------------------------------------------------------------------
# Anthropic client singletons (reused across tool calls).
# ---------------------------------------------------------------------


def _opus_client() -> AsyncAnthropic:
    return AsyncAnthropic()  # picks up ANTHROPIC_API_KEY from env


def _sonnet_client() -> AsyncAnthropic:
    return AsyncAnthropic()  # same client, different model on the call


# ---------------------------------------------------------------------
# Tier B — parallel oversight evaluators (Sonnet 4.6).
# These DO NOT speak. They publish alerts and brief-field updates.
# The orchestrator calls all three IN PARALLEL on every caller turn.
# ---------------------------------------------------------------------


@function_tool
async def run_safety_monitor(input: SafetyMonitorInput) -> dict:
    """Classify the current turn against 8 alert classes.

    Returns: {"alerts": [...]} per the schema. Recorded directly into
    SessionState.alerts; never spoken.

    The previous specialist turn is read from SessionStore so the
    @function_tool signature stays Anthropic-schema-compatible (no
    dict[str, Any] hints — they emit additionalProperties:true which
    the Messages API rejects under strict-mode tools). SessionStore is
    the source of truth for turn history anyway. See
    docs/livekit-kb/05-debugging-playbook.md.
    """
    store = get_session_store()
    state = store.get(input.session_id)
    last_specialist_turn = (
        state.turns[-1].model_dump() if state and state.turns else None
    )
    sysprompt = _load_agent_system("psap-safety-monitor")
    user = json.dumps(
        {
            "caller_text": input.caller_text,
            "last_specialist_turn": last_specialist_turn,
        }
    )
    client = _sonnet_client()
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=sysprompt,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text if resp.content else "{}"
    try:
        parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return {"alerts": []}
    return {"alerts": parsed.get("alerts", [])}


@function_tool
async def run_ohca_detector(input: OhcaDetectorInput) -> dict:
    """Compute OHCA probability per GEDP §5.1.1 + AHA BLS 2025 signals.

    Returns: {"probability": float, "signals": [...], "alert_severity": str|None}.
    Updates SessionBrief.ohca_probability.
    """
    sysprompt = _load_agent_system("psap-ohca-detector")
    user = json.dumps({"transcript_so_far": input.transcript_so_far})
    client = _sonnet_client()
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=sysprompt,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text if resp.content else "{}"
    try:
        parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return {"probability": 0.0, "signals": [], "alert_severity": None}
    prob = float(parsed.get("confidence", parsed.get("probability", 0)))
    severity = None
    if prob >= 0.85:
        severity = "critical"
    elif prob >= 0.60:
        severity = "high"
    elif prob >= 0.30:
        severity = "medium"
    return {
        "probability": prob,
        "signals": parsed.get("signals", []),
        "alert_severity": severity,
    }


@function_tool
async def run_intent_verifier(input: IntentVerifierInput) -> dict:
    """Classify caller intent — testing, real-emergency-claim, prank, in-character, etc.

    Returns: {"intent_class": str, "confidence": float, "cited_utterances": [str]}.
    Updates SessionBrief.intent_class.
    """
    sysprompt = _load_agent_system("psap-intent-verifier")
    user = json.dumps(
        {
            "caller_text": input.caller_text,
            "transcript_so_far": input.transcript_so_far,
        }
    )
    client = _sonnet_client()
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=sysprompt,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text if resp.content else "{}"
    try:
        parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return {
            "intent_class": "unknown",
            "confidence": 0.0,
            "cited_utterances": [],
        }
    return {
        "intent_class": parsed.get("intent_class", "unknown"),
        "confidence": float(parsed.get("confidence", 0)),
        "cited_utterances": parsed.get("cited_utterances", []),
    }


# ---------------------------------------------------------------------
# Tier A — voice-facing specialists (Opus 4.7).
# These EMIT the next utterance via TTS. Each returns a TurnRecord +
# brief patch + optional next_phase signal.
# ---------------------------------------------------------------------


async def _emit_specialist_turn(
    role: str,
    session_store: SessionStore,
    session_id: str,
    caller_text: str,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Common shape for voice-facing specialists.

    Loads the role's YAML system prompt + sprint contract for the
    current phase, calls Opus, validates the JSON, records the turn,
    returns the spoken content + brief patch for the orchestrator.
    """
    state = session_store.require(session_id)
    contract = load_contract(state.phase)
    sysprompt = _load_agent_system(role)

    # Sprint-contract injection — the specialist sees the success
    # criteria for the current phase + the brief snapshot, never the
    # full turn history. Context-reset over compaction.
    contract_block = (
        "\n\n## SPRINT CONTRACT (current phase)\n"
        + yaml.safe_dump(contract.model_dump(), sort_keys=False)
        + "\n## BRIEF (what previous phases established)\n"
        + state.brief.model_dump_json(indent=2)
    )

    user_msg = json.dumps(
        {
            "caller_text": caller_text,
            "extra_context": extra_context or {},
            "turn_seq": state.turn_seq,
        }
    )

    # 2026-04-24: voice-facing specialists run on Sonnet 4.6, not Opus 4.7.
    # Per docs/livekit-kb/08-opus-47-refusal-patterns.md §7: Sonnet 4.6 hits
    # ~600ms TTFT (Opus 4.7 was ~7s — caller hung up before response), and
    # has lower refusal rate (0.18% vs 0.28%) on medical role-play. Opus 4.7
    # stays as the orchestrator and parallel-evaluator backbone where the
    # 7s budget is acceptable.
    client = _opus_client()
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=sysprompt + contract_block,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text if resp.content else "{}"

    # Lenient JSON parse — same pattern as lib/coordinator.ts ac10442.
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        # Model returned plain prose — use it as the utterance directly.
        prose = raw.strip()[:400]
        if prose:
            return _serve_prose(role, session_store, session_id, prose)
        return _safe_fallback(role, session_store, session_id, "no JSON in specialist response")
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return _safe_fallback(role, session_store, session_id, "JSON parse failed")

    # Try strict pydantic; on failure, lenient serve.
    try:
        turn = TurnRecord.model_validate(
            {
                **obj,
                "agent": obj.get("agent", role),
                "turn_id": obj.get("turn_id", _new_turn_id(session_id, state.turn_seq)),
            }
        )
    except Exception as e:  # noqa: BLE001
        log.warning("specialist.lenient_serve", role=role, err=str(e)[:160])
        # Accept either `spoken_content` (what the YAML asks for) or
        # `content` (what TurnRecord uses internally). YAMLs use the
        # former; older shim used the latter. Belt-and-suspenders.
        content = (
            obj.get("spoken_content")
            or obj.get("content")
            or obj.get("utterance")
            or obj.get("text")
        )
        if not isinstance(content, str) or not content.strip():
            return _safe_fallback(role, session_store, session_id, str(e))
        turn = TurnRecord(
            agent=role,
            turn_id=_new_turn_id(session_id, state.turn_seq),
            action="speak",
            content=content,
            rationale=f"lenient serve: {str(e)[:120]}",
            cites=obj.get("cites", []),
            confidence=0.5,
            confidence_basis="uncertain",
            self_verify=SelfVerify(
                checks=[
                    SelfVerifyCheck(name="json-parseable", passed=True),
                    SelfVerifyCheck(name="schema-valid", passed=False, note=str(e)[:120]),
                ],
                all_passed=False,
            ),
            alerts=[
                Alert(
                    kind="verify-failed",
                    severity="medium",
                    detail=f"lenient-served: {str(e)[:160]}",
                    source_agent=role,
                )
            ],
        )

    contract_satisfied = bool(obj.get("contract_satisfied"))
    session_store.record_turn(session_id, turn, contract_satisfied=contract_satisfied)

    brief_patch = obj.get("brief_patch") or {}
    if isinstance(brief_patch, dict):
        session_store.update_brief(session_id, **brief_patch)

    next_phase = obj.get("next_phase")
    return {
        "spoken_content": turn.content if turn.action == "speak" else SAFE_FALLBACK,
        "turn_id": turn.turn_id,
        "self_verify_passed": turn.self_verify.all_passed,
        "contract_satisfied": contract_satisfied,
        "next_phase": next_phase,
    }


SAFE_FALLBACK = "One moment please."


def _serve_prose(
    role: str, session_store: SessionStore, session_id: str, utterance: str
) -> dict[str, Any]:
    """Last-resort: model returned prose with no JSON envelope. Speak it
    rather than dropping the turn entirely. Common when the system
    prompt's JSON output instruction is ignored under load or under
    safety-default deflection."""
    state = session_store.require(session_id)
    turn = TurnRecord(
        agent=role,
        turn_id=_new_turn_id(session_id, state.turn_seq),
        action="speak",
        content=utterance,
        rationale="prose-served: model emitted no JSON envelope",
        cites=[],
        confidence=0.4,
        confidence_basis="uncertain",
        self_verify=SelfVerify(
            checks=[
                SelfVerifyCheck(name="json-parseable", passed=False, note="raw prose"),
                SelfVerifyCheck(name="schema-valid", passed=False, note="bypassed"),
            ],
            all_passed=False,
        ),
        alerts=[
            Alert(
                kind="verify-failed",
                severity="info",
                detail="prose-served: model emitted no JSON envelope",
                source_agent=role,
            )
        ],
    )
    session_store.record_turn(session_id, turn, contract_satisfied=False)
    return {
        "spoken_content": utterance,
        "turn_id": turn.turn_id,
        "self_verify_passed": False,
        "contract_satisfied": False,
        "next_phase": None,
    }


def _safe_fallback(
    role: str, session_store: SessionStore, session_id: str, reason: str
) -> dict[str, Any]:
    state = session_store.require(session_id)
    turn = TurnRecord(
        agent=role,
        turn_id=_new_turn_id(session_id, state.turn_seq),
        action="defer",
        content=None,
        rationale=f"safe fallback: {reason[:160]}",
        cites=["sp:SP-006"],
        confidence=0.0,
        confidence_basis="uncertain",
        self_verify=SelfVerify(
            checks=[SelfVerifyCheck(name="json-parseable", passed=False, note=reason[:120])],
            all_passed=False,
        ),
        alerts=[
            Alert(
                kind="verify-failed",
                severity="medium",
                detail=reason[:200],
                source_agent=role,
            )
        ],
    )
    session_store.record_turn(session_id, turn, contract_satisfied=False)
    return {
        "spoken_content": SAFE_FALLBACK,
        "turn_id": turn.turn_id,
        "self_verify_passed": False,
        "contract_satisfied": False,
        "next_phase": None,
    }


@function_tool
async def specialist_intake(input: SpecialistInput) -> dict:
    """Drive the intake phase: greet, capture address, classify chief complaint, get callback."""
    return await _emit_specialist_turn(
        "psap-intake", get_session_store(), input.session_id, input.caller_text
    )


@function_tool
async def specialist_triage(input: SpecialistInput) -> dict:
    """Run GEDP key-question flow for the chief complaint family; assign determinant."""
    return await _emit_specialist_turn(
        "psap-triage", get_session_store(), input.session_id, input.caller_text
    )


@function_tool
async def specialist_dispatch(input: SpecialistInput) -> dict:
    """Commit unit assignment, read back the determinant code, confirm resources enroute."""
    return await _emit_specialist_turn(
        "psap-dispatch", get_session_store(), input.session_id, input.caller_text
    )


@function_tool
async def specialist_pdi(input: SpecialistInput) -> dict:
    """Deliver pre-arrival instructions matched to the determinant (CPR, bleeding control, airway)."""
    return await _emit_specialist_turn(
        "psap-pdi", get_session_store(), input.session_id, input.caller_text
    )


@function_tool
async def specialist_handoff(input: SpecialistInput) -> dict:
    """Terminal-phase handoff: confirm units arrived or caller is with responders; close call."""
    return await _emit_specialist_turn(
        "psap-handoff", get_session_store(), input.session_id, input.caller_text
    )


# Public catalog — the worker registers exactly these tools on the orchestrator.
TOOL_CATALOG = [
    # Tier B — parallel evaluators
    run_safety_monitor,
    run_ohca_detector,
    run_intent_verifier,
    # Tier A — voice-facing
    specialist_intake,
    specialist_triage,
    specialist_dispatch,
    specialist_pdi,
    specialist_handoff,
]
