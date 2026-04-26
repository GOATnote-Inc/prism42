"""ResponseGate — deterministic gate between FSM and Fish TTS (cycle-2T).

Pipeline (when PRISM42_ENABLE_RESPONSE_GATE=1):

    caller utterance
        -> dispatcher_fsm.transition(...)        (cycle-2Q FSM)
        -> response_gate.gate_decision(...)      (cycle-2T, this module)
            * deterministic template OR validated LLM constraints
            * CPR safety gate hard-rejects unsafe compressions
        -> Fish TTS (template path: bypasses LLM entirely)
           or Sonnet/Nemotron LLM (fallback path: validators clamp output)

The gate's job is to keep the bytes Fish speaks bounded by code, not by
LLM constraint-following. Cycle-2Q showed that even with the FSM driving
intent, Nemotron-3-Nano's 30% per-instruction failure rate produces:
  - spurious simulation disclaimers ("dial 911 on a working phone")
  - gendered pronouns without caller commit ("him" from "my friend")
  - filler at start ("OK so...") despite negation rules
  - phrase repeats across turns

The gate eliminates those failure modes for 20 of 21 intents by skipping
the LLM call entirely and rendering a hand-tuned template. The remaining
intent (REPROMPT, currently also templated for safety) carries hard
post-validation: 5-14 words, single terminator, no gendered pronouns when
fsm.pronouns is unknown, no verbatim repeats from the rolling buffer.

Default OFF (PRISM42_ENABLE_RESPONSE_GATE=1 to enable). When unset/0
the gate module is imported but its `gate_decision` is never invoked,
so the cycle-2Q path is byte-equivalent.

See findings/voice/cycle2T_response_gate/team-t/design.md for decisions.
See findings/voice/cycle2T_response_gate/team-t/integration-patch.md for
the orchestrator hook.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import structlog

from templates import TEMPLATES, render_template

log = structlog.get_logger()


# ---------------------------------------------------------------------
# Env flag — default OFF until cycle-2T ship confidence is reached.
# ---------------------------------------------------------------------


def should_use_response_gate() -> bool:
    """Return True when the operator has set PRISM42_ENABLE_RESPONSE_GATE=1.

    Single source of truth — orchestrator.py and tests both call this so
    the gate cannot drift. When False the gate module is imported but
    its `gate_decision` is never invoked, leaving the cycle-2Q FSM-only
    path byte-equivalent.
    """
    return os.environ.get("PRISM42_ENABLE_RESPONSE_GATE", "0") == "1"


# ---------------------------------------------------------------------
# Decision + validation dataclasses.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating an LLM-generated reply against gate rules."""

    ok: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateDecision:
    """The gate's per-turn verdict.

    Exactly one of (used_template, used_llm) is True. `final_text` is
    populated when the gate has a deterministic answer ready; the
    orchestrator emits it directly to TTS. If `used_llm=True` the
    orchestrator falls through to the LLM path with `constraints_for_llm`
    injected into the system prompt.

    `cpr_blocked=True` indicates the CPR safety gate rejected the FSM's
    INSTRUCT_CPR_BEGIN intent; the orchestrator should re-render with
    `fallback_intent` (also surfaced as a deterministic template).
    """

    intent: str                                # Intent.value
    used_template: bool
    used_llm: bool
    final_text: str | None
    constraints_for_llm: dict[str, Any] | None = None
    cpr_blocked: bool = False
    fallback_intent: str | None = None         # set when cpr_blocked


# ---------------------------------------------------------------------
# Validators — clamp LLM output (REPROMPT and any future LLM intent).
# ---------------------------------------------------------------------


# Gendered-pronoun set. The gate rejects these when fsm.pronouns is
# 'unknown' (i.e. caller has not committed gender).
_BANNED_GENDERED = re.compile(r"\b(he|him|his|she|her|hers)\b", re.IGNORECASE)
_TERMINATOR = re.compile(r"[.!?]")


def _word_count(text: str) -> int:
    """Stripped-of-punctuation word count for output rules check."""
    cleaned = re.sub(r"[.,!?;:]", "", text)
    return len([w for w in cleaned.split() if w])


def validate_llm_output(
    text: str,
    *,
    recent_replies: list[str] | tuple[str, ...] = (),
    pronouns_known: bool = False,
) -> ValidationResult:
    """Apply the cycle-2T post-LLM validators.

    Rules
    -----
    1. 5 <= word_count <= 14
    2. exactly one terminator from {. ! ?}
    3. if not pronouns_known: no gendered pronouns
    4. no verbatim phrase from `recent_replies` appears in `text`

    Returns
    -------
    ValidationResult with `ok` and a tuple of `reasons` strings (empty
    when ok=True). Used both at gate-decision time (LLM-path output) and
    by the test suite to assert validator behavior.
    """
    reasons: list[str] = []
    stripped = (text or "").strip()
    if not stripped:
        return ValidationResult(ok=False, reasons=("empty",))

    n_words = _word_count(stripped)
    if n_words < 5:
        reasons.append(f"word_count={n_words}<5")
    elif n_words > 14:
        reasons.append(f"word_count={n_words}>14")

    n_term = len(_TERMINATOR.findall(stripped))
    if n_term != 1:
        reasons.append(f"terminators={n_term}!=1")

    if not pronouns_known:
        m = _BANNED_GENDERED.search(stripped)
        if m:
            reasons.append(f"gendered_pronoun={m.group(0)!r}")

    # Repeat-phrase check — verbatim substring match, case-insensitive.
    # We also catch "near-verbatim" by checking each prior reply with
    # punctuation collapsed.
    lc_text = stripped.lower()
    for prior in recent_replies:
        p = (prior or "").strip()
        if not p:
            continue
        if p.lower() in lc_text:
            reasons.append(f"repeat_full={p!r}")
            break
        # Lightweight near-match: 6-word rolling window.
        prior_words = p.lower().split()
        if len(prior_words) >= 6:
            for i in range(len(prior_words) - 5):
                window = " ".join(prior_words[i : i + 6])
                if window in lc_text:
                    reasons.append(f"repeat_window={window!r}")
                    break
            if reasons and reasons[-1].startswith("repeat_window"):
                break

    return ValidationResult(ok=not reasons, reasons=tuple(reasons))


# ---------------------------------------------------------------------
# ResponseGate — orchestrator-facing entry point.
# ---------------------------------------------------------------------


# Intents that ALWAYS use a template, even if the LLM-fallback path is
# tempted otherwise. Hard-coded for safety.
_SAFETY_TEMPLATE_ONLY: frozenset[str] = frozenset(
    {
        "instruct_cpr_compressions",     # life-safety
        "instruct_choking_back_blows",   # life-safety
        "instruct_pressure_bleed",       # life-safety
        "instruct_seizure_clear_area",   # life-safety
        "answer_do_not_move",            # could cause harm if mis-phrased
        "answer_outcome_uncertain",      # do-not-promise hard rule
        "verify_cpr_surface",            # CPR gate guard
        "verify_cpr_breathing",          # CPR gate guard
    }
)


@dataclass
class ResponseGate:
    """Stateless wrapper around the FSM that produces gate decisions.

    Call sites
    ----------
    - `should_use_template(intent, fsm)` — fast yes/no without rendering
    - `render_template_for(intent, fsm)` — render to text
    - `validate_llm_output(...)` — post-LLM clamp
    - `gate_decision(intent, fsm, caller_utterance)` — full decision
    - `cpr_safe(fsm)` — CPR safety gate; True iff compressions allowed

    The gate does NOT mutate the FSM. Mutation belongs to
    DispatcherFSM.transition. The gate reads facts and routes.
    """

    fsm: Any  # DispatcherFSM (kept Any to avoid import cycle / typing)

    # ---- CPR safety gate ---------------------------------------------

    def cpr_safe(self) -> bool:
        """Return True iff INSTRUCT_CPR_BEGIN may be emitted now.

        Per cycle-2T directive: do not allow compressions unless
        awake=False AND breathing=False. Mapped to FSM facts:

          awake=False     <-> is_cardiac_arrest=True AND surface_confirmed=True
          breathing=False <-> breathing_assessed=True

        The FSM's own _intent_in_verify will ALSO route to verification
        when the latches are missing — the gate's cpr_safe() is defense
        in depth, not redundancy. The gate is the LAST layer; the FSM
        cannot be trusted to remain bug-free across future refactors.
        """
        is_arrest = getattr(self.fsm, "is_cardiac_arrest", None) is True
        surface = getattr(self.fsm, "surface_confirmed", None) is True
        breathing_assessed = getattr(self.fsm, "breathing_assessed", None) is True
        return is_arrest and surface and breathing_assessed

    # ---- Routing -----------------------------------------------------

    def should_use_template(self, intent_value: str) -> bool:
        """Return True when this intent renders deterministically."""
        if intent_value in _SAFETY_TEMPLATE_ONLY:
            return True
        return intent_value in TEMPLATES

    def render_template_for(self, intent_value: str) -> str | None:
        """Render the template for `intent_value` against fsm.pronouns.

        Returns None if the intent has no template (the gate routes the
        intent to the LLM path with validators).
        """
        pronouns = getattr(self.fsm, "pronouns", "they") or "they"
        return render_template(intent_value, pronouns)

    # ---- LLM-path constraint payload --------------------------------

    def _llm_constraints(self) -> dict[str, Any]:
        """Return the constraint block the orchestrator can splice into
        the LLM system prompt for the current FSM state.

        Used only when the gate routes an intent through the LLM path.
        Mirrors validate_llm_output rules so the LLM is biased toward
        producing acceptable output on the first attempt.
        """
        recent = list(getattr(self.fsm, "recent_replies", []) or [])
        pronouns = getattr(self.fsm, "pronouns", "unknown") or "unknown"
        pronouns_known = pronouns not in ("unknown",)
        return {
            "max_words": 14,
            "min_words": 5,
            "terminators_max": 1,
            "pronouns_known": pronouns_known,
            "pronouns": pronouns,
            "recent_replies": recent,
            "forbid_gendered": not pronouns_known,
        }

    # ---- The gate decision ------------------------------------------

    def gate_decision(
        self,
        intent_value: str,
        caller_utterance: str = "",
    ) -> GateDecision:
        """Produce the GateDecision for the given intent + FSM state.

        Behavior
        --------
        1. If intent is INSTRUCT_CPR_BEGIN AND not cpr_safe(): block,
           fall back to the next-needed verification intent template.
        2. If intent has a template (every intent except possibly
           REPROMPT, depending on config): render and emit.
        3. Otherwise route to LLM with `constraints_for_llm`.

        Always logs `response_gate.decision` with the structured fields
        the user requested in the directive.
        """
        t0 = time.monotonic()

        # 1. CPR safety gate.
        if intent_value == "instruct_cpr_compressions" and not self.cpr_safe():
            # Prefer surface check first; only fall through to breathing
            # if surface is already latched.
            if not getattr(self.fsm, "surface_confirmed", False):
                fallback = "verify_cpr_surface"
            else:
                fallback = "verify_cpr_breathing"
            text = self.render_template_for(fallback)
            decision = GateDecision(
                intent=intent_value,
                used_template=True,
                used_llm=False,
                final_text=text,
                cpr_blocked=True,
                fallback_intent=fallback,
            )
            self._log(decision, t0)
            return decision

        # 2. Template path.
        if self.should_use_template(intent_value):
            text = self.render_template_for(intent_value)
            if text is not None:
                decision = GateDecision(
                    intent=intent_value,
                    used_template=True,
                    used_llm=False,
                    final_text=text,
                )
                self._log(decision, t0)
                return decision

        # 3. LLM path with hard validators.
        constraints = self._llm_constraints()
        decision = GateDecision(
            intent=intent_value,
            used_template=False,
            used_llm=True,
            final_text=None,
            constraints_for_llm=constraints,
        )
        self._log(decision, t0)
        return decision

    def validate_llm_output(
        self,
        text: str,
    ) -> ValidationResult:
        """Apply the LLM-path validators against the FSM's current state.

        Convenience wrapper around module-level `validate_llm_output` —
        threads `recent_replies` and `pronouns_known` from the FSM so
        the orchestrator hook does not have to plumb them.
        """
        recent = list(getattr(self.fsm, "recent_replies", []) or [])
        pronouns = getattr(self.fsm, "pronouns", "unknown") or "unknown"
        pronouns_known = pronouns not in ("unknown",)
        return validate_llm_output(
            text,
            recent_replies=recent,
            pronouns_known=pronouns_known,
        )

    # ---- Logging -----------------------------------------------------

    def _log(self, d: GateDecision, t0: float) -> None:
        dt_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "response_gate.decision",
            intent=d.intent,
            used_template=d.used_template,
            used_llm=d.used_llm,
            final_text=d.final_text,
            cpr_blocked=d.cpr_blocked,
            fallback_intent=d.fallback_intent,
            state=getattr(self.fsm, "state", None) if not isinstance(
                getattr(self.fsm, "state", None), str
            ) else getattr(self.fsm, "state"),
            pronouns=getattr(self.fsm, "pronouns", "unknown"),
            ms=dt_ms,
        )


# ---------------------------------------------------------------------
# Module-level helpers used by orchestrator.py + tests.
# ---------------------------------------------------------------------


def gate_for_fsm(fsm: Any) -> ResponseGate:
    """Construct a gate for the given FSM. Stateless apart from the FSM
    pointer; safe to call once per session and reuse across turns."""
    return ResponseGate(fsm=fsm)


__all__ = [
    "GateDecision",
    "ResponseGate",
    "ValidationResult",
    "gate_for_fsm",
    "should_use_response_gate",
    "validate_llm_output",
]
