"""Long-running harness primitives for prism42 voice sessions.

Per docs/livekit-architecture.md §4 + the Anthropic harness blog
(anthropic.com/engineering/harness-design-long-running-apps), each
session is a "long-running app instance" that needs:

  - Durable state (survives worker restarts)
  - Structured handoff artifacts (the SessionBrief; the brief is what
    the orchestrator passes to the next-phase specialist instead of
    the full turn history — context reset over compaction)
  - Sprint contract loading per phase
  - Idempotent turn recording (same session_id+turn_id is a no-op)
  - Observability writes (durable JSONL log per session)

Backed by Redis on the B300 pod. Falls back to in-memory dict when
REDIS_URL is unset (local dev / tests).
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import structlog
import yaml
from pydantic import BaseModel, Field

log = structlog.get_logger()

PHASES = Literal["intake", "triage", "dispatch", "pdi", "handoff", "closed"]
ALERT_KINDS = Literal[
    "real-emergency-claim",
    "ohca-signal",
    "contraindicated-instruction",
    "phi-disclosure",
    "caller-distress",
    "intent-ambiguous",
    "verify-failed",
    "latency-breach",
]
ALERT_SEVERITIES = Literal["info", "medium", "high", "critical"]


# ---------------------------------------------------------------------
# Pydantic mirror of mvp/911-console-live/lib/types.ts. Keep in sync.
# ---------------------------------------------------------------------


class SelfVerifyCheck(BaseModel):
    name: str
    passed: bool
    note: str | None = None


class SelfVerify(BaseModel):
    checks: list[SelfVerifyCheck]
    all_passed: bool


class Alert(BaseModel):
    kind: str
    severity: ALERT_SEVERITIES
    detail: str
    source_agent: str


class TurnRecord(BaseModel):
    """Single voice-facing turn. Mirror of PsapTurn (TS)."""

    agent: str
    turn_id: str
    action: Literal["speak", "defer", "refuse", "escalate", "handoff", "end"]
    content: str | None
    rationale: str
    cites: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: Literal["citation", "inference", "uncertain"]
    self_verify: SelfVerify
    contract_satisfied: bool | None = None
    alerts: list[Alert] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)


class RubricGrade(BaseModel):
    turn_id: str
    weighted_score: float = Field(ge=0.0, le=1.0)
    criteria: dict[str, float]
    rationales: dict[str, str]
    cites: list[str]
    model_used: str
    self_grade_flag: bool
    flag_reason: str | None = None
    latency_ms: int


# ---------------------------------------------------------------------
# SessionBrief — the structured handoff artifact between phases.
#
# Per the harness blog: "Communication was handled via files: one agent
# would write a file, another agent would read it." The brief is our
# in-memory equivalent. It survives across phase transitions; the
# specialist sees ONLY the brief + current caller utterance + sprint
# contract — never the full turn history. This is the context-reset
# pattern that prevents both context fill and "context anxiety."
# ---------------------------------------------------------------------


class SessionBrief(BaseModel):
    """What every phase specialist needs to know to do its job.

    Populated incrementally by each phase. Fields are nullable until
    the relevant phase fills them. Sprint contracts assert the
    not-null subset that must hold before a phase can hand off.
    """

    # intake
    chief_complaint_family: str | None = None
    chief_complaint_text: str | None = None
    scene_address: str | None = None
    callback: str | None = None
    callback_deferred: bool = False
    caller_state: Literal[
        "panicked", "coherent", "distressed", "hostile", "unknown"
    ] | None = None
    language_detected: str | None = None
    # triage
    determinant: str | None = None
    response_level: Literal[
        "echo", "delta", "charlie", "bravo", "alpha", "omega"
    ] | None = None
    kq_responses: dict[str, str] = Field(default_factory=dict)
    red_flags: list[str] = Field(default_factory=list)
    # dispatch
    units_assigned: list[str] = Field(default_factory=list)
    eta_seconds: int | None = None
    # pdi
    pdi_protocol_id: str | None = None
    instructions_delivered: list[str] = Field(default_factory=list)
    caller_compliance: Literal["observed", "refused", "unable"] | None = None
    # handoff
    close_mode: (
        Literal[
            "units-arrived",
            "patient-recovered",
            "supervisor-transfer",
            "forced-termination",
        ]
        | None
    ) = None
    post_action_guidance_id: str | None = None
    # rolling oversight signals (populated every turn by parallel evaluators)
    ohca_probability: float = 0.0
    intent_class: str | None = None


class SessionState(BaseModel):
    """Durable state per call. Persisted to Redis (or in-memory map).

    The orchestrator reads + writes via the SessionStore wrapper; the
    specialists never touch this directly — they receive a brief
    snapshot at tool-call time.
    """

    session_id: str
    started_at_ms: int
    last_touched_ms: int
    phase: PHASES = "intake"
    turn_seq: int = 0
    brief: SessionBrief = Field(default_factory=SessionBrief)
    turns: list[TurnRecord] = Field(default_factory=list)
    grades: list[RubricGrade] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    # Closed-call summary, populated by the auditor:
    auditor_verdict: str | None = None


# ---------------------------------------------------------------------
# SessionStore — Redis-backed (production) or dict-backed (dev/tests).
# ---------------------------------------------------------------------


class _MemoryBackend:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._d.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._d[key] = value

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class SessionStore:
    """Wraps Redis (or dict) with PsapTurn-shaped getters/setters.

    Idempotency: `record_turn(turn_id=...)` is a no-op if the same
    `turn_id` is already in `state.turns`. This matters when Anthropic
    streaming retries fire the same finalized JSON twice.
    """

    REDIS_KEY = "prism42:session:{sid}"
    REDIS_TTL = 6 * 3600  # 6 h — well past the longest plausible call

    def __init__(self, backend: Any | None = None) -> None:
        if backend is not None:
            self.backend = backend
        else:
            url = os.environ.get("REDIS_URL")
            if url:
                import redis  # noqa: PLC0415  lazy

                self.backend = redis.Redis.from_url(url, decode_responses=True)
            else:
                log.info("session_store.fallback", reason="REDIS_URL unset")
                self.backend = _MemoryBackend()

    # -- read -----------------------------------------------------------

    def get(self, session_id: str) -> SessionState | None:
        raw = self.backend.get(self.REDIS_KEY.format(sid=session_id))
        if not raw:
            return None
        return SessionState.model_validate_json(raw)

    def require(self, session_id: str) -> SessionState:
        state = self.get(session_id)
        if not state:
            raise KeyError(f"session not found: {session_id}")
        return state

    # -- create --------------------------------------------------------

    def open(self, session_id: str) -> SessionState:
        existing = self.get(session_id)
        if existing:
            return existing
        now = int(time.time() * 1000)
        state = SessionState(
            session_id=session_id,
            started_at_ms=now,
            last_touched_ms=now,
        )
        self._persist(state)
        return state

    # -- mutate --------------------------------------------------------

    def record_turn(
        self, session_id: str, turn: TurnRecord, contract_satisfied: bool | None = None
    ) -> SessionState:
        state = self.require(session_id)
        # idempotent: same turn_id never recorded twice
        for existing in state.turns:
            if existing.turn_id == turn.turn_id:
                log.info(
                    "session_store.turn_dedup",
                    session_id=session_id,
                    turn_id=turn.turn_id,
                )
                return state
        if contract_satisfied is not None:
            turn.contract_satisfied = contract_satisfied
        state.turns.append(turn)
        state.alerts.extend(turn.alerts)
        state.last_touched_ms = int(time.time() * 1000)
        state.turn_seq += 1
        self._persist(state)
        return state

    def record_grade(self, session_id: str, grade: RubricGrade) -> None:
        state = self.require(session_id)
        state.grades.append(grade)
        state.last_touched_ms = int(time.time() * 1000)
        self._persist(state)

    def update_brief(self, session_id: str, **patch: Any) -> SessionBrief:
        state = self.require(session_id)
        for k, v in patch.items():
            if v is None:
                continue
            setattr(state.brief, k, v)
        state.last_touched_ms = int(time.time() * 1000)
        self._persist(state)
        return state.brief

    def transition_phase(self, session_id: str, new_phase: PHASES) -> SessionState:
        state = self.require(session_id)
        old = state.phase
        state.phase = new_phase
        state.last_touched_ms = int(time.time() * 1000)
        log.info(
            "session_store.phase_transition",
            session_id=session_id,
            from_phase=old,
            to_phase=new_phase,
        )
        self._persist(state)
        return state

    def close(self, session_id: str, verdict: str | None = None) -> None:
        state = self.require(session_id)
        state.phase = "closed"
        if verdict:
            state.auditor_verdict = verdict
        state.last_touched_ms = int(time.time() * 1000)
        self._persist(state)

    # -- internals -----------------------------------------------------

    def _persist(self, state: SessionState) -> None:
        key = self.REDIS_KEY.format(sid=state.session_id)
        self.backend.set(key, state.model_dump_json(), ex=self.REDIS_TTL)


# ---------------------------------------------------------------------
# SprintContract loader.
# ---------------------------------------------------------------------


class SprintContract(BaseModel):
    phase: str
    description: str
    max_turns: int
    hand_off_to: str
    hand_off_artifact_keys: list[str]
    success_criteria: list[dict[str, Any]]
    escalation_triggers: list[dict[str, Any]] = Field(default_factory=list)


CONTRACT_DIR = Path(__file__).parent / "contracts"


def load_contract(phase: str) -> SprintContract:
    p = CONTRACT_DIR / f"{phase}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"sprint contract missing: {p}")
    with p.open() as f:
        data = yaml.safe_load(f)
    return SprintContract(**data)


def all_phases() -> Iterable[str]:
    yield from ("intake", "triage", "dispatch", "pdi", "handoff")


# ---------------------------------------------------------------------
# Observability — append a turn_log line per turn.
# ---------------------------------------------------------------------


LOG_DIR = Path(os.environ.get("PRISM42_LOG_DIR", "/var/log/prism42"))


def write_turn_log(line: dict[str, Any]) -> None:
    """JSONL append. Best-effort — failures must never block the hot path."""
    try:
        (LOG_DIR / "turns").mkdir(parents=True, exist_ok=True)
        sid = line.get("session_id", "unknown")
        with (LOG_DIR / "turns" / f"{sid}.jsonl").open("a") as f:
            f.write(json.dumps(line) + "\n")
    except OSError as e:
        log.warning("turn_log.write_failed", err=str(e))


def write_session_summary(line: dict[str, Any]) -> None:
    try:
        (LOG_DIR / "sessions").mkdir(parents=True, exist_ok=True)
        sid = line.get("session_id", "unknown")
        with (LOG_DIR / "sessions" / f"{sid}.json").open("w") as f:
            json.dump(line, f, indent=2)
    except OSError as e:
        log.warning("session_summary.write_failed", err=str(e))


# ---------------------------------------------------------------------
# Singleton SessionStore — used by worker.py + specialists.py.
# Lifts into state.py so specialists.py doesn't need to import from
# worker.py (avoids circular import).
# ---------------------------------------------------------------------


_SINGLETON: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Lazy-init singleton. Called by worker entry + every specialist tool."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = SessionStore()
    return _SINGLETON


def _reset_session_store_for_tests() -> None:
    global _SINGLETON
    _SINGLETON = None
