"""DispatcherFSM — finite-state controller in front of the LLM (cycle-2Q).

Background
----------
The cycle-2d/2e/2P live demo runs a single streaming Sonnet-4.6 (cloud) or
Nemotron-3-Nano (vLLM 0.20 :8001 on B300) call whose system prompt
(`FAST_DISPATCHER_SYSTEM_PROMPT` in orchestrator.py) IS the dispatcher
protocol. The 4 cycle-2Q failure modes — stuck reassurance ("Stay with
me" repeats), filler repetition ("OK"), unverified CPR instruction
("my friend stopped breathing" -> "start chest compressions"), and
hardcoded gendered pronouns — are all consequences of asking the model
to do BOTH dialogue management AND phrasing in one prompt. When the
model is light (3 B Nemotron Nano) it loses the protocol scaffolding
under conversational pressure.

This module implements the user's proposal: put a deterministic FSM in
front of the LLM. The FSM owns dialogue management. The LLM owns
phrasing. The two communicate through a small per-turn intent-tag
plus a structured context dict.

Design references
-----------------
- Pipecat Flows pattern: predefined nodes -> transitions -> per-state
  role_messages / task_messages drive a per-turn system prompt.
  https://github.com/pipecat-ai/pipecat-flows
- LiveKit Agents 1.5.x hooks: Agent.on_user_turn_completed(turn_ctx,
  new_message) and Agent.update_instructions(text). We hook here.
  voice/agent.py:247 + voice/agent.py:156.
- MPDS Protocol 9 (cardiac arrest, IAED ProQA) — verify before
  instructing. The verification mini-FSM below mirrors the canonical
  "is patient on a hard surface? are they breathing or only gasping
  (agonal)?" pre-CPR gate. See team2/protocol-canon.md when shipped;
  the 2-question gate is a conservative subset of the canonical
  set.
- 2024-2025 literature: state-machine-based dialogue control with LLM
  phrasing (Wang et al. MDPI Information 15(9):580, 2024; Liu et al.
  arXiv:2502.14145, 2025) confirms the pattern is research-validated
  for full-duplex / voice agents.

Charter constraints honored
---------------------------
- Default OFF. Env-flag PRISM42_ENABLE_FSM gates entry. When 0 (the
  default) `should_use_fsm()` returns False and the orchestrator path
  is byte-identical to cycle-2P.
- No third-party deps. Pure stdlib + structlog (already a project dep).
- No async I/O on the hot path; transition + prompt build run in <1 ms
  on the B300 pod. Total FSM-induced overhead per turn budget < 100 ms,
  measured by orchestrator.fsm_turn_ms log line.
- Frozen paths (vendor/fish-speech, FishSpeechTTS, file-backed greeting
  PRISM42_GREETING_AUDIO_FILE) are NOT touched by this module.
"""
from __future__ import annotations

import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Iterable

import structlog

log = structlog.get_logger()


# ---------------------------------------------------------------------
# Env flag — default OFF until cycle-2Q ship confidence is reached.
# ---------------------------------------------------------------------

def should_use_fsm() -> bool:
    """Return True when the operator has set PRISM42_ENABLE_FSM=1.

    Single source of truth — orchestrator.py + worker.py both call this
    so the gate cannot drift. When False the FSM module is imported but
    its `transition` / `next_prompt` are never invoked, leaving the
    cycle-2P system-prompt-only path byte-equivalent.
    """
    return os.environ.get("PRISM42_ENABLE_FSM", "0") == "1"


# ---------------------------------------------------------------------
# State enumeration. Eight states, monotonic forward except for the
# CRITICAL_OVERRIDE branch which can fire from any phase past intake.
# ---------------------------------------------------------------------


class State(str, Enum):
    INTAKE = "intake"                          # need address + nature
    ADDRESS_CONFIRMED = "address_confirmed"    # have both, must reassure
    REASSURANCE_DELIVERED = "reassurance_delivered"  # latched
    KEY_QUESTIONS = "key_questions"            # complaint-specific Q1/Q2/Q3
    PRE_ARRIVAL = "pre_arrival"                # CPR / choking / bleeding / seizure
    CRITICAL_VERIFY = "critical_verify"        # MPDS-9 sub-FSM gate before CPR
    CRITICAL_CPR = "critical_cpr"              # actively coaching compressions
    HANDOFF = "handoff"                        # units arrived / closeout


# Verification sub-state lives inside CRITICAL_VERIFY.
class VerifyStep(str, Enum):
    Q_SURFACE = "q_surface"        # "on the floor flat on their back?"
    Q_BREATHING = "q_breathing"    # "breathing normally, or only gasping?"
    DONE = "done"                  # both confirmed -> jump to CRITICAL_CPR


# ---------------------------------------------------------------------
# Intent tags — the contract between FSM and LLM. The LLM receives
# the tag plus a short caller utterance and returns a 5-12 word
# realization in natural English.
# ---------------------------------------------------------------------


class Intent(str, Enum):
    # Intake
    REQUEST_LOCATION_AND_EMERGENCY = "request_location_and_emergency"
    REQUEST_LOCATION = "request_location"
    REQUEST_EMERGENCY = "request_emergency"
    CONFIRM_ADDRESS = "confirm_address"
    # Reassurance — fires AT MOST ONCE per call (latched).
    DELIVER_REASSURANCE = "deliver_reassurance"
    # Key questions — phrased to the complaint and to who is affected.
    KQ_RESPONSIVE_BREATHING = "kq_responsive_breathing"  # third-party medical
    KQ_SEVERITY = "kq_severity"                          # first-party medical
    KQ_BLEEDING_LOCATION = "kq_bleeding_location"
    KQ_FIRE_EVACUATION = "kq_fire_evacuation"
    KQ_SAFE_LOCATION = "kq_safe_location"                # crime / trauma
    # Verification (cardiac arrest gate)
    VERIFY_SURFACE = "verify_cpr_surface"
    VERIFY_BREATHING = "verify_cpr_breathing"
    # Pre-arrival instructions
    INSTRUCT_CPR_BEGIN = "instruct_cpr_compressions"
    INSTRUCT_CHOKING = "instruct_choking_back_blows"
    INSTRUCT_PRESSURE_BLEED = "instruct_pressure_bleed"
    INSTRUCT_SEIZURE = "instruct_seizure_clear_area"
    # Caller asked us a direct question.
    ANSWER_DO_NOT_MOVE = "answer_do_not_move"
    ANSWER_HOW_LONG = "answer_how_long"
    ANSWER_OUTCOME_UNCERTAIN = "answer_outcome_uncertain"
    # Defaults / fallback
    REPROMPT = "reprompt_caller"
    CLOSEOUT = "closeout"


# ---------------------------------------------------------------------
# Input classification — caller utterance -> structured features.
#
# Lightweight regex-based extractor. The point is to feed the
# transition table; the LLM still does the natural-language work.
# Anything ambiguous defaults conservatively (no overcommit to a state).
# ---------------------------------------------------------------------


_RE_HAS_DIGIT = re.compile(r"\d")
_RE_STREET = re.compile(
    r"\b\d+\s+\w+|\b\w+\s+(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|"
    r"dr|drive|ct|court|way|hwy|highway|pkwy|parkway)\b",
    re.IGNORECASE,
)
_RE_NOT_BREATHING = re.compile(
    r"\b(?:stopped breathing|not breathing|no(?:t)? breath(?:ing)?|"
    r"isn't breathing|can'?t breathe|no pulse|no heartbeat|"
    r"unresponsive|won'?t wake up|won'?t respond|not responding)\b",
    re.IGNORECASE,
)
_RE_FLOOR_FLAT = re.compile(
    r"\b(?:on the (?:floor|ground)|laying down|lying flat|flat on (?:his|her|their) back|"
    r"on (?:his|her|their) back|on the back)\b",
    re.IGNORECASE,
)
_RE_GASPING = re.compile(
    r"\b(?:gasp(?:ing)?|agonal|just gasping|barely breathing)\b",
    re.IGNORECASE,
)
_RE_BREATHING_NORMAL = re.compile(
    r"\bbreathing (?:normally|fine|okay|ok)\b|\bbreath(?:ing)? regular(?:ly)?\b",
    re.IGNORECASE,
)
_RE_CHOKING = re.compile(r"\bchok(?:ing|ed)\b|\bcan'?t breathe\b", re.IGNORECASE)
_RE_BLEEDING = re.compile(r"\bbleed(?:ing)?\b|\bblood\b", re.IGNORECASE)
_RE_SEIZURE = re.compile(r"\bseiz(?:ure|ing)\b|\bconvuls", re.IGNORECASE)
_RE_FIRE = re.compile(r"\bfire|burning|smoke\b", re.IGNORECASE)
_RE_CHEST_PAIN = re.compile(r"\bchest pain|heart attack\b", re.IGNORECASE)
_RE_TRAUMA = re.compile(r"\b(?:hit|stabbed|shot|fell|fall|crash|accident)\b", re.IGNORECASE)
# Pronoun discipline.
_RE_HE = re.compile(r"\b(?:my husband|my son|my dad|my father|my brother|"
                    r"my boyfriend|he is|he's|he was|him\b|his\b)\b", re.IGNORECASE)
_RE_SHE = re.compile(r"\b(?:my wife|my daughter|my mom|my mother|my sister|"
                     r"my girlfriend|she is|she's|she was|her\b)\b", re.IGNORECASE)
# Caller is referring to themselves vs a third party.
_RE_FIRST_PERSON = re.compile(r"\b(?:i (?:have|am|feel|can'?t|got)|my chest|my arm)\b",
                              re.IGNORECASE)
_RE_THIRD_PARTY = re.compile(
    r"\b(?:my friend|my (?:husband|wife|son|daughter|mom|mother|dad|father|"
    r"sister|brother|boyfriend|girlfriend)|"
    r"(?:he|she|they) (?:is|are|was|were|stopped|fell|isn'?t)|"
    r"someone|a person|the patient)\b",
    re.IGNORECASE,
)
_RE_DO_NOT_MOVE_Q = re.compile(
    r"\bshould i move|can i move|do i move|move (?:him|her|them)\b", re.IGNORECASE,
)
_RE_HOW_LONG_Q = re.compile(
    r"\bhow long|when (?:are|will|is)|how soon|coming\??\s*$", re.IGNORECASE,
)
_RE_OUTCOME_Q = re.compile(
    r"\b(?:going to (?:be (?:ok|okay|alright)|make it|die)|will (?:he|she|they) (?:be|live|die))\b",
    re.IGNORECASE,
)


@dataclass
class Features:
    """Structured features extracted from one caller utterance."""

    has_address: bool = False
    has_emergency: bool = False
    is_first_person: bool = False
    is_third_party: bool = False
    not_breathing: bool = False
    floor_flat: bool = False
    gasping: bool = False
    breathing_normal: bool = False
    choking: bool = False
    bleeding: bool = False
    seizure: bool = False
    fire: bool = False
    chest_pain: bool = False
    trauma: bool = False
    asks_do_not_move: bool = False
    asks_how_long: bool = False
    asks_outcome: bool = False
    pronoun_he: bool = False
    pronoun_she: bool = False


def classify(utterance: str) -> Features:
    """Extract features. Conservative: ambiguous -> all-False."""
    if not utterance:
        return Features()
    t = utterance.strip()
    return Features(
        has_address=bool(_RE_STREET.search(t)) or bool(_RE_HAS_DIGIT.search(t)),
        has_emergency=bool(
            _RE_NOT_BREATHING.search(t)
            or _RE_CHOKING.search(t)
            or _RE_BLEEDING.search(t)
            or _RE_SEIZURE.search(t)
            or _RE_FIRE.search(t)
            or _RE_CHEST_PAIN.search(t)
            or _RE_TRAUMA.search(t)
        ),
        is_first_person=bool(_RE_FIRST_PERSON.search(t)),
        is_third_party=bool(_RE_THIRD_PARTY.search(t)),
        not_breathing=bool(_RE_NOT_BREATHING.search(t)),
        floor_flat=bool(_RE_FLOOR_FLAT.search(t)),
        gasping=bool(_RE_GASPING.search(t)),
        breathing_normal=bool(_RE_BREATHING_NORMAL.search(t)),
        choking=bool(_RE_CHOKING.search(t)),
        bleeding=bool(_RE_BLEEDING.search(t)),
        seizure=bool(_RE_SEIZURE.search(t)),
        fire=bool(_RE_FIRE.search(t)),
        chest_pain=bool(_RE_CHEST_PAIN.search(t)),
        trauma=bool(_RE_TRAUMA.search(t)),
        asks_do_not_move=bool(_RE_DO_NOT_MOVE_Q.search(t)),
        asks_how_long=bool(_RE_HOW_LONG_Q.search(t)),
        asks_outcome=bool(_RE_OUTCOME_Q.search(t)),
        pronoun_he=bool(_RE_HE.search(t)),
        pronoun_she=bool(_RE_SHE.search(t)),
    )


# ---------------------------------------------------------------------
# DispatcherFSM — the controller.
# ---------------------------------------------------------------------


@dataclass
class DispatcherFSM:
    """Finite-state controller for the 911 PSAP voice path.

    Lifecycle
    ---------
    Constructed once per call, immediately after `make_orchestrator()`.
    `transition(utterance)` is invoked on every `on_user_turn_completed`
    BEFORE the LLM generation kicks off. It mutates internal state and
    returns the next `Intent`. `next_prompt(utterance)` then returns the
    full per-turn system prompt for the LLM.

    Anti-repetition + pronoun discipline live entirely in this object —
    the LLM never sees stale memory across turns except via the rolling
    buffer fields injected into the prompt.
    """

    # State.
    state: State = State.INTAKE
    verify_step: VerifyStep = VerifyStep.Q_SURFACE
    # Latches.
    address_known: bool = False
    emergency_known: bool = False
    reassurance_done: bool = False
    surface_confirmed: bool = False
    breathing_assessed: bool = False
    is_cardiac_arrest: bool = False
    # Pronouns. 'unknown' until caller commits.
    pronouns: str = "unknown"  # 'unknown' | 'they' | 'he/him' | 'she/her'
    # Anti-repetition rolling buffer (last 3 dispatcher utterances).
    recent_replies: deque[str] = field(default_factory=lambda: deque(maxlen=3))
    # Caller-perspective: first-party medical vs third-party.
    is_third_party: bool = False
    # Categorical complaint for KEY_QUESTIONS phase.
    complaint: str = "unknown"  # 'medical' | 'fire' | 'trauma' | 'crime' | 'unknown'
    # Telemetry.
    turns: int = 0
    last_intent: Intent | None = None

    # ---- main API -----------------------------------------------------

    def transition(self, utterance: str) -> Intent:
        """Compute the next intent. Mutates state. <1 ms on B300."""
        t0 = time.monotonic()
        f = classify(utterance)
        self.turns += 1

        # Pronoun commit (only on explicit signal).
        if self.pronouns == "unknown":
            if f.pronoun_he and not f.pronoun_she:
                self.pronouns = "he/him"
            elif f.pronoun_she and not f.pronoun_he:
                self.pronouns = "she/her"
            elif f.is_third_party:
                self.pronouns = "they"
        # Caller perspective (latches once committed; first-person beats
        # third-party in case both fire on the same turn).
        if f.is_first_person:
            self.is_third_party = False
        elif f.is_third_party and not self.is_third_party:
            self.is_third_party = True

        # Latch address + emergency observations.
        if f.has_address:
            self.address_known = True
        if f.has_emergency:
            self.emergency_known = True
            if f.fire:
                self.complaint = "fire"
            elif f.trauma:
                self.complaint = "trauma"
            else:
                self.complaint = "medical"

        # ----- CRITICAL OVERRIDE: caller signals cardiac arrest -----
        # Whenever the FSM hears "not breathing" / "no pulse" / etc., we
        # jump into the verification mini-FSM unless we are already in
        # CPR coaching. This honors the MPDS-9 "verify before instruct"
        # gate — we never skip straight to compressions.
        if f.not_breathing and self.state not in (State.CRITICAL_VERIFY,
                                                   State.CRITICAL_CPR):
            self.is_cardiac_arrest = True
            self.state = State.CRITICAL_VERIFY
            # Pre-fill latches from anything the caller already volunteered.
            if f.floor_flat:
                self.surface_confirmed = True
            if f.gasping or f.breathing_normal:
                # V2 ("breathing normally vs only gasping") is only
                # answered when the caller specifies the *quality* of
                # the respiration. Plain "not breathing" is what triggers
                # the verify branch in the first place — it does NOT
                # disambiguate gasping vs absent, and per MPDS-9 we still
                # need to confirm because callers often miss agonal
                # gasps. Pre-fill ONLY on gasping/normal signals.
                self.breathing_assessed = True
            return self._intent_in_verify(f, t0)

        # ----- Normal phase machine -----
        if self.state == State.INTAKE:
            return self._intent_in_intake(f, t0)
        if self.state == State.ADDRESS_CONFIRMED:
            return self._intent_in_address_confirmed(f, t0)
        if self.state == State.REASSURANCE_DELIVERED:
            return self._intent_in_after_reassurance(f, t0)
        if self.state == State.KEY_QUESTIONS:
            return self._intent_in_key_questions(f, t0)
        if self.state == State.PRE_ARRIVAL:
            return self._intent_in_pre_arrival(f, t0)
        if self.state == State.CRITICAL_VERIFY:
            return self._intent_in_verify(f, t0)
        if self.state == State.CRITICAL_CPR:
            return self._intent_in_cpr(f, t0)
        # HANDOFF
        return self._record(Intent.CLOSEOUT, t0)

    def record_dispatcher_reply(self, text: str) -> None:
        """Append the LLM's realized utterance to the rolling buffer.

        Called from the post-LLM hook (e.g. on conversation_item_added
        for role=='assistant'). Anti-repetition uses this buffer.
        """
        if text:
            self.recent_replies.append(text.strip())

    # ---- per-state helpers --------------------------------------------

    def _intent_in_intake(self, f: Features, t0: float) -> Intent:
        if self.address_known and self.emergency_known:
            self.state = State.ADDRESS_CONFIRMED
            return self._record(Intent.CONFIRM_ADDRESS, t0)
        if self.address_known and not self.emergency_known:
            return self._record(Intent.REQUEST_EMERGENCY, t0)
        if self.emergency_known and not self.address_known:
            return self._record(Intent.REQUEST_LOCATION, t0)
        # Neither — re-prompt the canonical opener.
        return self._record(Intent.REQUEST_LOCATION_AND_EMERGENCY, t0)

    def _intent_in_address_confirmed(self, f: Features, t0: float) -> Intent:
        # Special-case: caller asks a direct question right after
        # confirmation. Answer-the-question rule beats reassurance.
        q = self._direct_question_intent(f)
        if q is not None:
            # Don't latch reassurance yet — caller's question takes priority.
            return self._record(q, t0)
        # Deliver reassurance EXACTLY ONCE, then latch.
        self.reassurance_done = True
        self.state = State.REASSURANCE_DELIVERED
        return self._record(Intent.DELIVER_REASSURANCE, t0)

    def _intent_in_after_reassurance(self, f: Features, t0: float) -> Intent:
        # If caller asked a question, answer it; do NOT re-emit reassurance.
        q = self._direct_question_intent(f)
        if q is not None:
            return self._record(q, t0)
        # Otherwise advance to KEY_QUESTIONS.
        self.state = State.KEY_QUESTIONS
        return self._intent_in_key_questions(f, t0)

    def _intent_in_key_questions(self, f: Features, t0: float) -> Intent:
        q = self._direct_question_intent(f)
        if q is not None:
            return self._record(q, t0)
        if self.complaint == "fire":
            self.state = State.PRE_ARRIVAL
            return self._record(Intent.KQ_FIRE_EVACUATION, t0)
        if self.complaint == "trauma":
            return self._record(Intent.KQ_BLEEDING_LOCATION, t0)
        # Medical default. Branch on first-vs-third-party.
        if self.is_third_party:
            return self._record(Intent.KQ_RESPONSIVE_BREATHING, t0)
        return self._record(Intent.KQ_SEVERITY, t0)

    def _intent_in_pre_arrival(self, f: Features, t0: float) -> Intent:
        q = self._direct_question_intent(f)
        if q is not None:
            return self._record(q, t0)
        if f.choking:
            return self._record(Intent.INSTRUCT_CHOKING, t0)
        if f.bleeding:
            return self._record(Intent.INSTRUCT_PRESSURE_BLEED, t0)
        if f.seizure:
            return self._record(Intent.INSTRUCT_SEIZURE, t0)
        return self._record(Intent.CLOSEOUT, t0)

    def _intent_in_verify(self, f: Features, t0: float) -> Intent:
        """MPDS-9 sub-FSM: verify before instructing CPR.

        Rules:
        - V1 surface: skip if caller already said floor/flat/back.
        - V2 breathing-vs-gasping: skip if caller already said not
          breathing or gasping (both confirm cardiac arrest).
        - Both confirmed -> jump to CRITICAL_CPR with INSTRUCT_CPR_BEGIN.
        """
        if not self.surface_confirmed:
            self.verify_step = VerifyStep.Q_SURFACE
            return self._record(Intent.VERIFY_SURFACE, t0)
        if not self.breathing_assessed:
            self.verify_step = VerifyStep.Q_BREATHING
            return self._record(Intent.VERIFY_BREATHING, t0)
        # Both confirmed.
        self.state = State.CRITICAL_CPR
        self.verify_step = VerifyStep.DONE
        return self._record(Intent.INSTRUCT_CPR_BEGIN, t0)

    def _intent_in_cpr(self, f: Features, t0: float) -> Intent:
        # Inside active CPR coaching, keep encouraging compressions
        # unless the caller explicitly asks a question.
        q = self._direct_question_intent(f)
        if q is not None:
            return self._record(q, t0)
        return self._record(Intent.INSTRUCT_CPR_BEGIN, t0)

    # ---- direct-question router ---------------------------------------

    def _direct_question_intent(self, f: Features) -> Intent | None:
        if f.asks_do_not_move:
            return Intent.ANSWER_DO_NOT_MOVE
        if f.asks_how_long:
            return Intent.ANSWER_HOW_LONG
        if f.asks_outcome:
            return Intent.ANSWER_OUTCOME_UNCERTAIN
        return None

    # ---- record + telemetry -------------------------------------------

    def _record(self, intent: Intent, t0: float) -> Intent:
        self.last_intent = intent
        dt_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "fsm.transition",
            state=self.state.value,
            intent=intent.value,
            verify_step=self.verify_step.value if self.state == State.CRITICAL_VERIFY else None,
            pronouns=self.pronouns,
            address_known=self.address_known,
            emergency_known=self.emergency_known,
            reassurance_done=self.reassurance_done,
            surface_confirmed=self.surface_confirmed,
            breathing_assessed=self.breathing_assessed,
            cardiac=self.is_cardiac_arrest,
            complaint=self.complaint,
            third_party=self.is_third_party,
            turns=self.turns,
            ms=dt_ms,
        )
        return intent

    # ---- LLM prompt assembly ------------------------------------------

    # Compact intent guidance — the LLM gets ONE of these phrases per
    # turn. The tone, length, and pronoun discipline are enforced by
    # the surrounding shell prompt below, NOT by this table.
    # ClassVar so the dataclass machinery does not treat it as an
    # instance field (and trip the mutable-default guard).
    _INTENT_GUIDANCE: ClassVar[dict[Intent, str]] = {
        Intent.REQUEST_LOCATION_AND_EMERGENCY:
            "Ask for the caller's location AND the nature of the emergency, "
            "in one short sentence.",
        Intent.REQUEST_LOCATION:
            "Ask only for the caller's address or cross street.",
        Intent.REQUEST_EMERGENCY:
            "Ask only what the emergency is.",
        Intent.CONFIRM_ADDRESS:
            "Briefly confirm the address back to the caller.",
        Intent.DELIVER_REASSURANCE:
            "Tell the caller help is on the way and to stay on the line. "
            "Say this exactly ONCE per call.",
        Intent.KQ_RESPONSIVE_BREATHING:
            "Ask whether the patient is awake/responsive and breathing. "
            "Use {PRONOUNS}.",
        Intent.KQ_SEVERITY:
            "Ask how severe the symptom is — can the caller speak in full "
            "sentences, on a scale of 1-10, etc.",
        Intent.KQ_BLEEDING_LOCATION:
            "Ask where the bleeding is and how heavy it is.",
        Intent.KQ_FIRE_EVACUATION:
            "Ask whether everyone is out of the building.",
        Intent.KQ_SAFE_LOCATION:
            "Ask whether the caller is in a safe location right now.",
        Intent.VERIFY_SURFACE:
            "Ask: is the patient on the floor, flat on {POSSESSIVE} back? "
            "Do NOT instruct compressions yet.",
        Intent.VERIFY_BREATHING:
            "Ask: is {PRONOUN_SUBJECT} breathing normally, or only gasping? "
            "Do NOT instruct compressions yet.",
        Intent.INSTRUCT_CPR_BEGIN:
            "Instruct the caller to start chest compressions — center of "
            "the chest, hard and fast, two per second.",
        Intent.INSTRUCT_CHOKING:
            "Instruct: stand behind {PRONOUN_OBJECT}, five back blows "
            "between the shoulder blades.",
        Intent.INSTRUCT_PRESSURE_BLEED:
            "Instruct: apply firm direct pressure on the wound with a "
            "clean cloth. Do not lift to check.",
        Intent.INSTRUCT_SEIZURE:
            "Instruct: clear the area around {PRONOUN_OBJECT}. Do not "
            "hold {PRONOUN_OBJECT} down. Do not put anything in "
            "{POSSESSIVE} mouth.",
        Intent.ANSWER_DO_NOT_MOVE:
            "Answer the caller: do NOT move {PRONOUN_OBJECT} unless "
            "{PRONOUN_SUBJECT} is in danger. Keep {PRONOUN_OBJECT} still.",
        Intent.ANSWER_HOW_LONG:
            "Answer: as fast as they can. Tell the caller to stay on "
            "the line.",
        Intent.ANSWER_OUTCOME_UNCERTAIN:
            "Do NOT promise an outcome. Tell the caller responders are "
            "close and to tell you if anything changes.",
        Intent.REPROMPT:
            "Ask the caller to repeat what they just said.",
        Intent.CLOSEOUT:
            "Tell the caller to stay on the line until units arrive.",
    }

    def _pronoun_block(self) -> dict[str, str]:
        """Render pronoun substitutions for the intent guidance template."""
        if self.pronouns == "he/him":
            return {"PRONOUNS": "he/him", "PRONOUN_SUBJECT": "he",
                    "PRONOUN_OBJECT": "him", "POSSESSIVE": "his"}
        if self.pronouns == "she/her":
            return {"PRONOUNS": "she/her", "PRONOUN_SUBJECT": "she",
                    "PRONOUN_OBJECT": "her", "POSSESSIVE": "her"}
        # Default — unknown OR explicitly 'they'. Singular they.
        return {"PRONOUNS": "they/them", "PRONOUN_SUBJECT": "they",
                "PRONOUN_OBJECT": "them", "POSSESSIVE": "their"}

    def next_prompt(self, utterance: str, intent: Intent) -> str:
        """Build the per-turn system prompt for the LLM.

        The prompt is intentionally short (~one screen). The FSM state
        is not described to the model — only the single intent it must
        realize, the recent-utterance buffer, the pronouns, and the
        non-negotiable phrasing rules.
        """
        sub = self._pronoun_block()
        guidance = self._INTENT_GUIDANCE[intent]
        for k, v in sub.items():
            guidance = guidance.replace("{" + k + "}", v)

        recent = list(self.recent_replies)
        recent_block = (
            "\n".join(f"  - {r!r}" for r in recent) if recent else "  (none yet)"
        )

        latched_lines = []
        if self.reassurance_done:
            latched_lines.append(
                "  - Reassurance ALREADY DELIVERED. Do NOT say 'help is on "
                "the way' / 'help's coming' / 'units are en route' again."
            )
        if self.is_cardiac_arrest and self.state == State.CRITICAL_VERIFY:
            latched_lines.append(
                "  - Cardiac-arrest verification in progress. Do NOT instruct "
                "chest compressions yet — finish verification first."
            )
        latched = "\n".join(latched_lines) if latched_lines else "  (none)"

        # Single-page prompt. Five sections only: role, intent, caller
        # turn, hard rules, anti-repetition. No protocol scaffolding —
        # the FSM owns protocol; the LLM owns phrasing.
        return f"""\
# ROLE

You are a 911 PSAP dispatcher in a synthetic training simulation. Stay in
role. Never break character. Never say "I am an AI" or "dial 911."

# CURRENT INTENT (what to say next)

{guidance}

# CALLER JUST SAID

{utterance!r}

# PRONOUNS FOR THIS PATIENT

Use {sub['PRONOUNS']}. Subject: {sub['PRONOUN_SUBJECT']}. Object:
{sub['PRONOUN_OBJECT']}. Possessive: {sub['POSSESSIVE']}.
If the caller has not stated a gender, default to singular they/them.

# LATCHED FACTS (do not violate)

{latched}

# ANTI-REPETITION

You have already said the following in this call. Do NOT reuse any of
these phrases verbatim or near-verbatim:
{recent_block}

# OUTPUT RULES

- One sentence. 5-12 words. ONE question or ONE instruction.
- Spoken prose only. No markdown, no bullets, no stage directions.
- Realize the CURRENT INTENT in natural English. Do not mix multiple
  intents into one reply.
"""


# ---------------------------------------------------------------------
# Module-level helpers used by orchestrator.py + worker.py.
# ---------------------------------------------------------------------


def fsm_for_session(session_id: str) -> DispatcherFSM:
    """Construct a fresh FSM. Sessions are not shared across calls."""
    log.info("fsm.session_init", session_id=session_id)
    return DispatcherFSM()


def render_recent_buffer(buf: Iterable[str]) -> str:
    """Public helper for tests — render the recent-utterance buffer in
    the same format the prompt would inject."""
    items = list(buf)
    if not items:
        return "  (none yet)"
    return "\n".join(f"  - {r!r}" for r in items)
