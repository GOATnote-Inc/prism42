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
    # Cycle-2D5-B: complaint-specific reassurance variants. Fuse
    # reassurance + first key question into a single turn so the caller
    # is never left in the listening role with no task. Per public PSAP
    # research (StatPearls NBK470543, AHA T-CPR, NHS Pathways): "help is
    # on the way" must couple to a directive, not stand alone.
    DELIVER_REASSURANCE_TRAUMA = "deliver_reassurance_trauma"
    DELIVER_REASSURANCE_MEDICAL = "deliver_reassurance_medical"
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
    # Cycle-2R3 (B3-A): caller indicated patient not on floor — direct
    # caller to reposition before CPR can begin. Physician-reviewed by
    # Brandon Dent, MD 2026-04-26 per CLAUDE.md §10.
    INSTRUCT_CPR_REPOSITIONING = "instruct_cpr_repositioning"
    INSTRUCT_CHOKING = "instruct_choking_back_blows"
    INSTRUCT_PRESSURE_BLEED = "instruct_pressure_bleed"
    INSTRUCT_SEIZURE = "instruct_seizure_clear_area"
    # Caller asked us a direct question.
    ANSWER_DO_NOT_MOVE = "answer_do_not_move"
    ANSWER_HOW_LONG = "answer_how_long"
    ANSWER_OUTCOME_UNCERTAIN = "answer_outcome_uncertain"
    # Cycle-2R3 (B1-A): caller asks if we heard their address.
    ANSWER_HEARD_ADDRESS = "answer_heard_address"
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
# Cycle-2D5-A: address-echo capture. Greedier than _RE_STREET — captures
# digit-or-cardinal prefix + name + street suffix as a single span so the
# echo template can read back the full address ("100 ocean avenue", not
# "100 ocean" or "ocean avenue"). Only used for the echo string; address
# detection still uses _RE_STREET / _RE_HAS_DIGIT for has_address.
# Cycle-2D7: bumped the optional-middle-word allowance from 1 to 3 so
# 4+-word addresses ("two hundred oceanfront avenue", "1234 east main
# boulevard", "twelve north shore drive") capture intact. Without this,
# "Two hundred oceanfront avenue" echoed as "hundred oceanfront avenue".
_RE_ADDRESS_ECHO = re.compile(
    r"\b\d+(?:\s+[a-z]+){1,3}\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|"
    r"dr|drive|ct|court|way|hwy|highway|pkwy|parkway)\b"
    r"|\b[a-z]+(?:\s+[a-z]+){1,3}\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|"
    r"dr|drive|ct|court|way|hwy|highway|pkwy|parkway)\b",
    re.IGNORECASE,
)
_RE_NOT_BREATHING = re.compile(
    r"\b(?:stopped breathing|not breathing|no(?:t)? breath(?:ing)?|"
    r"isn't breathing|can'?t breathe|no pulse|no heartbeat|"
    r"unresponsive|won'?t wake up|won'?t respond|not responding|"
    # Cycle-2D3: caller phrases like "I don't think he's breathing",
    # "I don't think she's breathing at all anymore", "doesn't seem
    # like he's breathing" — the literal-adjacency "not breathing"
    # rule misses these natural-language variants.
    r"don'?t think (?:he|she|they|the patient)(?:'?s| is| are)? breath\w*|"
    r"doesn'?t (?:seem|look|sound) (?:like )?(?:he|she|they)(?:'?s| is)? breath\w*|"
    r"breathing at all)\b",
    re.IGNORECASE,
)
_RE_FLOOR_FLAT = re.compile(
    r"\b(?:on the (?:floor|ground)|laying down|lying flat|flat on (?:his|her|their) back|"
    r"on (?:his|her|their) back|on the back)\b",
    re.IGNORECASE,
)
# Cycle-2R3 (B3-A): caller indicates patient NOT on the floor / not flat —
# a chair, bed, couch, vehicle, sitting, standing, upright, slumped, etc.
# Drives the INSTRUCT_CPR_REPOSITIONING intent. Physician-reviewed
# 2026-04-26 by Brandon Dent, MD per CLAUDE.md §10.
_RE_FLOOR_NEGATION = re.compile(
    r"\b(?:in (?:a |the )?(?:chair|recliner|car seat|bed|couch|sofa|wheelchair)|"
    # Cycle-2D6: "sit up" / "to sit" / "wants to sit" — caller's screenshot
    # said "made him feel better to sit up" which the prior 'sitting up'-only
    # pattern missed. Catches the shorter verb form too.
    r"sitting (?:up|on|in)|to sit (?:up|on|down)|sit(?:s|ting)? up|"
    r"seated|standing|upright|slumped|"
    r"on the (?:couch|sofa|bed)|in (?:his|her|their) (?:chair|bed)|"
    r"not (?:on the floor|flat|laying down)|"
    r"can'?t (?:move|get) (?:him|her|them))\b",
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
# Cycle-2D2 (Team RCA B2-B): bare-no surface negation. Caller answers
# "No" / "Nope" / "Negative" / "Nah" / "Uh-uh" to a VERIFY_SURFACE
# question. The bare-no signal alone (without a positive surface
# keyword like "chair" or "bed") does not match _RE_FLOOR_NEGATION
# but is a strong intent-driven floor-negation cue. The negative
# lookahead ensures "No, he's breathing" / "No, he's responsive" do
# NOT trigger reposition (they're answering a different question).
_RE_BARE_NO_SURFACE = re.compile(
    r"^\s*(?:no+|nope|negative|nah|uh[- ]?uh)\b"
    r"(?!.*\b(?:breath|pulse|responsive|responding|awake|conscious|alert|"
    r"gasping|moving|alive|talking|crying)\b)",
    re.IGNORECASE,
)

# Cycle-2R3 (Team R3 B1-A): caller asking whether dispatcher heard the address
# or where help is being sent. Routes to ANSWER_HEARD_ADDRESS template.
_RE_DID_YOU_HEAR_Q = re.compile(
    r"\bdid (?:you|ya) (?:hear|get|catch)\b|"
    r"\bdo you (?:know|have) (?:where|the address|my address)\b|"
    r"\bwhere are you sending\b|\bdid (?:you|that) go through\b",
    re.IGNORECASE,
)
# Cycle-2R3 (Team R3 B2-A): backchannel detector — short acknowledgements
# like "uh okay", "yeah", "got it" that should NOT advance FSM state.
_RE_BACKCHANNEL = re.compile(
    r"^\s*(?:uh+|um+|ah+|oh+|ok(?:ay)?|alright|right|yeah|yep|yes|"
    r"got it|sure|mm+hmm+|hmm+)[.,!?\s]*$",
    re.IGNORECASE,
)


@dataclass
class Features:
    """Structured features extracted from one caller utterance."""

    has_address: bool = False
    # Cycle-2D5-A: captured address span (un-normalized; preserves the
    # caller's spoken cardinals like "twelve" so the echo reads back what
    # the caller said, not "12"). None when the utterance has no clean
    # street-suffix or numeric-prefix span.
    address_text: str | None = None
    has_emergency: bool = False
    is_first_person: bool = False
    is_third_party: bool = False
    not_breathing: bool = False
    floor_flat: bool = False
    # Cycle-2R3 (B3-A): caller signaled patient NOT on the floor —
    # drives INSTRUCT_CPR_REPOSITIONING. Mutually-exclusive with floor_flat;
    # both can't be true on the same utterance.
    floor_negation: bool = False
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
    # Cycle-2R3 (B1-A): caller asking if dispatcher heard the address.
    asks_heard_address: bool = False
    # Cycle-2R3 (B2-A): backchannel utterance — should not advance state.
    is_backchannel: bool = False
    pronoun_he: bool = False
    pronoun_she: bool = False


# Cycle-2P2 (Team P C3): spelled-cardinal -> digit normalizer.
# Maps spoken-form cardinals (zero..nine, ten..nineteen, twenty..ninety,
# hundred, thousand) to digit form so the address-classification regex
# (_RE_HAS_DIGIT) catches "one hundred ocean of new" -> "100 ocean of new"
# even when Parakeet mis-hears the suffix. Hard-coded; no NLP library.
# Pre-FSM only: the UI / transcript pane keeps the raw utterance.
_SPELLED_DIGIT_UNITS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_SPELLED_DIGIT_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
# Compiled once. Match order matters — try multi-word forms before
# single-word forms so "one hundred" beats "one" alone.
_SPELLED_NUMBER_PATTERNS: list[tuple[re.Pattern[str], int | str]] = []


def _build_spelled_number_patterns() -> list[tuple[re.Pattern[str], int | str]]:
    """Build (pattern, value-or-template) pairs once at import time."""
    pats: list[tuple[re.Pattern[str], int | str]] = []
    # Pattern: "<tens>-<unit>" or "<tens> <unit>" -> tens+unit (52, 21, ...)
    for tens_word, tens_val in _SPELLED_DIGIT_TENS.items():
        for unit_word, unit_val in _SPELLED_DIGIT_UNITS.items():
            if unit_val == 0 or unit_val >= 10:
                continue
            combo = f"{tens_word}[\\s-]+{unit_word}"
            pats.append(
                (re.compile(rf"\b{combo}\b", re.IGNORECASE), tens_val + unit_val)
            )
    # Pattern: "<unit> hundred [and <rest>]" -> 100..999. Without the
    # optional rest we just emit the hundreds value (e.g. "one hundred"
    # -> 100). With the rest we recurse via a placeholder; keep it simple
    # and only support the no-tail form, which covers the canonical
    # "one hundred ocean ave" smoking-gun case.
    for unit_word, unit_val in _SPELLED_DIGIT_UNITS.items():
        if unit_val == 0 or unit_val >= 10:
            continue
        pats.append(
            (re.compile(rf"\b{unit_word}\s+hundred\b", re.IGNORECASE),
             unit_val * 100)
        )
    # "<unit> thousand" -> 1000..9000.
    for unit_word, unit_val in _SPELLED_DIGIT_UNITS.items():
        if unit_val == 0 or unit_val >= 10:
            continue
        pats.append(
            (re.compile(rf"\b{unit_word}\s+thousand\b", re.IGNORECASE),
             unit_val * 1000)
        )
    # Standalone tens (twenty, thirty, ...).
    for tens_word, tens_val in _SPELLED_DIGIT_TENS.items():
        pats.append((re.compile(rf"\b{tens_word}\b", re.IGNORECASE), tens_val))
    # Standalone units 1..19. Skip "zero" -> "0" because addresses rarely
    # start with a literal zero and "zero" appears in non-numeric contexts.
    for unit_word, unit_val in _SPELLED_DIGIT_UNITS.items():
        if unit_val == 0:
            continue
        pats.append((re.compile(rf"\b{unit_word}\b", re.IGNORECASE), unit_val))
    return pats


_SPELLED_NUMBER_PATTERNS = _build_spelled_number_patterns()


def _normalize_spelled_cardinals(text: str) -> str:
    """Convert spelled-out cardinals to digits. Idempotent on already-numeric input.

    Best-effort and conservative: applies patterns in longest-match-first
    order. Does NOT solve full English number parsing (no "one hundred and
    twenty-three"). Solves the smoking-gun cases: "one hundred ocean
    avenue", "twelve riverside drive", "fifty-two main street",
    "twenty lakeside".
    """
    if not text:
        return text
    out = text
    for pat, val in _SPELLED_NUMBER_PATTERNS:
        out = pat.sub(str(val), out)
    return out


def classify(utterance: str) -> Features:
    """Extract features. Conservative: ambiguous -> all-False."""
    if not utterance:
        return Features()
    # Cycle-2P2 (Team P C3): normalize spelled cardinals BEFORE regex
    # matching so "one hundred ocean of new" registers a digit and
    # latches address_known on turn 1 even when STT mis-hears the
    # street suffix. UI / transcript still sees the original utterance.
    t = _normalize_spelled_cardinals(utterance.strip())
    # Cycle-2D5-A: capture address span from the ORIGINAL utterance so the
    # echo preserves cardinal-words ("twelve riverside drive", not
    # "12 riverside drive"). Only set when the regex finds a clean span;
    # digit-only matches (no street suffix) leave address_text=None and
    # the gate falls back to the no-echo template.
    addr_match = _RE_ADDRESS_ECHO.search(utterance.strip())
    address_text = addr_match.group(0).strip() if addr_match else None
    # Cycle-2D8: strip STT disfluencies ("uh", "um", "er", "like", "ah")
    # from the captured address span so the echo doesn't read back
    # "200 uh river drive". STT often drops these into the middle of
    # multi-word addresses when the caller hesitates. Case-insensitive
    # word-boundary match; collapse runs of whitespace afterwards.
    if address_text:
        address_text = re.sub(
            r"\b(?:uh+|um+|er+|ah+|like|y'?know)\b",
            "",
            address_text,
            flags=re.IGNORECASE,
        )
        address_text = re.sub(r"\s+", " ", address_text).strip()
        if not address_text:
            address_text = None
    return Features(
        has_address=bool(_RE_STREET.search(t)) or bool(_RE_HAS_DIGIT.search(t)),
        address_text=address_text,
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
        # Cycle-2R3 (B3-A): caller signaled patient NOT on the floor.
        floor_negation=bool(_RE_FLOOR_NEGATION.search(t)),
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
        # Cycle-2R3 (B1-A): caller asks if we heard their address.
        asks_heard_address=bool(_RE_DID_YOU_HEAR_Q.search(t)),
        # Cycle-2R3 (B2-A): backchannel — short, content-free utterance.
        # The <=14-char guard rejects long utterances that happen to
        # start with a backchannel filler (e.g. "Yeah, my friend stopped
        # breathing" should still latch cardiac).
        is_backchannel=bool(_RE_BACKCHANNEL.match(t)) and len(t) <= 14,
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
    # Cycle-2D5-A: captured address text — latched once on first capture
    # so the confirm_address template can echo it back to the caller.
    # None until the caller speaks an address with a clean street-suffix
    # or numeric-prefix span (digit-only fallback leaves this None).
    address_text: str | None = None
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
    # Cycle-2R3 (B3-A): count of consecutive INSTRUCT_CPR_REPOSITIONING
    # emits — used to latch surface_confirmed heuristically after 2
    # repositions if caller still hasn't moved patient to the floor.
    _reposition_emits: int = 0
    # Cycle-2D6: count of consecutive VERIFY_SURFACE emits without any
    # floor-signal (neither floor_flat nor floor_negation) from the
    # caller. After N emits the FSM latches surface_confirmed
    # heuristically and advances to breathing — otherwise the FSM
    # loops on "Are they on the floor, flat on their back?" forever
    # when the caller cannot or will not directly answer.
    _verify_surface_emits: int = 0
    # Cycle-2D9: count of consecutive same-KQ emits (KQ_BLEEDING_LOCATION,
    # KQ_RESPONSIVE_BREATHING, KQ_SEVERITY, KQ_FIRE_EVACUATION,
    # KQ_SAFE_LOCATION). When the caller's answer is partial or off-topic
    # and the FSM has no per-KQ answer detector, repeating the same
    # question 3+ times is worse than advancing with imperfect info
    # (PSAP discipline + AHA T-CPR <150s gate). After 2 emits, advance
    # to PRE_ARRIVAL.
    _kq_emits: int = 0
    # Cycle-2D10: same anti-repeat shape for pre-arrival instructions.
    # After 2 emits of the same INSTRUCT_*, the instruction has been
    # delivered. Stay-on-the-line (CLOSEOUT) takes over so the caller
    # gets continuous coaching instead of identical re-emits.
    _instruction_emits: int = 0

    # ---- main API -----------------------------------------------------

    def transition(self, utterance: str) -> Intent:
        """Compute the next intent. Mutates state. <1 ms on B300."""
        t0 = time.monotonic()
        f = classify(utterance)
        self.turns += 1

        # Cycle-2R3 (B2-A): backchannel guard — caller is acknowledging,
        # not committing a substantive new turn. Re-emit last_intent
        # rather than advancing state. Only applies after caller has
        # entered the call (post-INTAKE) — backchannels in INTAKE could
        # be the address itself misheard, so preserve current behavior
        # there.
        if f.is_backchannel and self.state in (
            State.ADDRESS_CONFIRMED,
            State.REASSURANCE_DELIVERED,
            State.KEY_QUESTIONS,
        ):
            return self._record(self.last_intent or Intent.REPROMPT, t0)

        # Cycle-2D2 (Team RCA fix 2B): intent-aware bare-no surface
        # negation. If FSM just asked VERIFY_SURFACE and caller's reply
        # opens with "No" / "Nope" / "Nah" AND the utterance does NOT
        # mention breathing / pulse / responsiveness (i.e. they're
        # answering THIS question, not a different one), treat as
        # floor_negation regardless of whether _RE_FLOOR_NEGATION
        # matched. Covers "No, he's on the street" / "Nope." / "No he
        # is not on his back" — patterns the substantive-keyword regex
        # cannot infer surface-negation from.
        if (
            self.last_intent == Intent.VERIFY_SURFACE
            and self.state == State.CRITICAL_VERIFY
            and not self.surface_confirmed
            and _RE_BARE_NO_SURFACE.match(utterance)
            and not f.floor_flat
        ):
            f.floor_negation = True

        # Cycle-2D3: breathing-verify "no" / "not at all" handler.
        # Caller has been asked "Are they breathing normally, or only
        # gasping?" If they answer with "not breathing at all" / "no" /
        # "negative" / "nothing" → the answer to MPDS-9 V2 is "absent"
        # which IS a confirmed cardiac arrest indicator. Latch
        # breathing_assessed=True and let the next intent advance to
        # INSTRUCT_CPR_BEGIN. Without this, the FSM repeats VERIFY_BREATHING
        # because not_breathing alone never set breathing_assessed
        # (the gap was: breathing_assessed only fired on positive cues
        # gasping/breathing_normal).
        if (
            self.last_intent == Intent.VERIFY_BREATHING
            and self.state == State.CRITICAL_VERIFY
            and not self.breathing_assessed
            and (
                f.not_breathing
                or f.gasping
                or f.breathing_normal
                or _RE_BARE_NO_SURFACE.match(utterance)  # "no" / "nothing" — same regex shape
            )
        ):
            self.breathing_assessed = True
            log.info("fsm.breathing_assessed_mid_verify",
                     not_breathing=f.not_breathing,
                     gasping=f.gasping,
                     breathing_normal=f.breathing_normal)

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
        # Cycle-2D5-A: latch the address echo string on first clean capture.
        # Once latched, subsequent address-shaped utterances do NOT overwrite.
        if f.address_text and not self.address_text:
            self.address_text = f.address_text
        if f.has_emergency:
            self.emergency_known = True
            # Cycle-2D2 (Team RCA fix 1A): trauma is sticky once latched.
            # Subsequent turns that introduce a medical cue (e.g. "not
            # breathing") on a known-trauma victim represent dual-rail
            # (traumatic arrest) — preserve the cardiac short-circuit AND
            # the trauma context so future KQ branching can re-engage
            # hemorrhage / safe-location flows. Without this latch the
            # FSM silently flipped trauma → medical on the cardiac jump
            # and lost the mechanism-of-injury context entirely.
            if f.fire:
                self.complaint = "fire"
            elif f.trauma:
                self.complaint = "trauma"
            elif self.complaint != "trauma":
                # Only flip to 'medical' if not already on a trauma rail.
                self.complaint = "medical"

        # ----- CRITICAL OVERRIDE: caller signals cardiac arrest -----
        # Whenever the FSM hears "not breathing" / "no pulse" / etc., we
        # jump into the verification mini-FSM unless we are already in
        # CPR coaching. This honors the MPDS-9 "verify before instruct"
        # gate — we never skip straight to compressions.
        # Cycle-2P2 (Team P A1): defense-in-depth gate. Positive arrest
        # cues ("stopped breathing", "no pulse", "unresponsive") trigger
        # unconditionally. Ambiguous cues ("not responding") require
        # third-party context — first-person "I'm not responding" / "my
        # phone won't respond" no longer mis-routes to CPR-verify.
        # Cycle-2D8: extend the inline positive-arrest regex with the
        # natural-language patterns that cycle-2D3 added to
        # _RE_NOT_BREATHING. Without this, "I don't think he's breathing
        # anymore" is detected as a feature flag (f.not_breathing=True)
        # but does NOT trigger the cardiac short-circuit, so the FSM
        # stays in trauma key-questions instead of jumping to
        # CRITICAL_VERIFY. The new patterns are anchored to a third-
        # person subject so they remain "positive" cues (no first-person
        # ambiguity that motivated the original ambiguous/positive split).
        # Cycle-2D10: also catch sudden-collapse cues. Caller said
        # "they had chest pain earlier today...the next thing I know,
        # they fell down" — classic cardiac event presentation. Sudden
        # collapse + chest pain is a positive arrest cue per AHA T-CPR
        # NO-NO-GO algorithm (recognition < 90s; fewer questions, faster).
        positive_arrest_cue = bool(
            re.search(
                r"\b(?:stopped breathing|not breathing|"
                r"isn'?t breathing|no pulse|no heartbeat|"
                r"unresponsive|won'?t wake up|just gasping|"
                r"don'?t think (?:he|she|they|the patient)"
                r"(?:'?s| is| are)? breath\w*|"
                r"doesn'?t (?:seem|look|sound) (?:like )?"
                r"(?:he|she|they)(?:'?s| is)? breath\w*|"
                r"breathing at all|"
                # Cycle-2D10: sudden collapse cues (3rd-person only;
                # 1st-person fainting is NOT an arrest indicator).
                # Cycle-2D11: extended subject set to catch "my friend
                # passed out", "my husband collapsed", etc. Caller's
                # reported relation is the canonical 3rd-person subject
                # in 911 calls; previous regex required pronoun.
                # Up-to-2-word filler between subject and verb so
                # "my friend just passed out" / "my mom suddenly fainted"
                # also match.
                r"(?:he|she|they|the patient|my \w+) "
                r"(?:\w+\s+){0,2}"
                r"(?:fell|collapsed|passed out|fainted|"
                r"went (?:down|out|unconscious)|dropped)|"
                r"unconscious)\b",
                utterance, re.IGNORECASE,
            )
        )
        ambiguous_arrest_cue = bool(
            re.search(
                r"\b(?:not responding|won'?t respond|no(?:t)? breath)\b",
                utterance, re.IGNORECASE,
            )
        )
        should_jump_to_verify = positive_arrest_cue or (
            ambiguous_arrest_cue and self.is_third_party
        )
        if should_jump_to_verify and self.state not in (State.CRITICAL_VERIFY,
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
        # Cycle-2D5-B: complaint-specific reassurance variants. Reassurance
        # alone leaves the caller in the listening role ("ok, but what do
        # I do?"). Public PSAP research (StatPearls NBK470543, AHA T-CPR)
        # requires reassurance + co-presence + first directive in a
        # single turn. We pick the variant by complaint so the fused
        # template asks the right next question. Cardiac short-circuit
        # bypasses this path entirely (jumps to CRITICAL_VERIFY at line
        # ~610), so DELIVER_REASSURANCE_CARDIAC is unreachable and not
        # added here. Fire/crime/unknown fall back to the legacy
        # standalone DELIVER_REASSURANCE.
        if self.complaint == "trauma":
            intent = Intent.DELIVER_REASSURANCE_TRAUMA
        elif self.complaint == "medical":
            intent = Intent.DELIVER_REASSURANCE_MEDICAL
        else:
            intent = Intent.DELIVER_REASSURANCE
        self.reassurance_done = True
        self.state = State.REASSURANCE_DELIVERED
        return self._record(intent, t0)

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
        # Cycle-2D9 anti-stuck: if we've emitted the same KQ twice in a row
        # without progress, advance to PRE_ARRIVAL. The caller has either
        # given a partial / off-topic answer or is panicking; either way
        # repeating the same question is worse than instructing them on
        # the next physical action with the info we have.
        if self._kq_emits >= 2:
            self.state = State.PRE_ARRIVAL
            log.info("fsm.kq_loop_force_advance",
                     last_intent=getattr(self.last_intent, "value", None),
                     kq_emits=self._kq_emits)
            self._kq_emits = 0
            return self._intent_in_pre_arrival(f, t0)

        # Pick the appropriate KQ for this complaint.
        if self.complaint == "fire":
            self.state = State.PRE_ARRIVAL
            return self._record(Intent.KQ_FIRE_EVACUATION, t0)
        if self.complaint == "trauma":
            kq = Intent.KQ_BLEEDING_LOCATION
        elif self.is_third_party:
            kq = Intent.KQ_RESPONSIVE_BREATHING
        else:
            kq = Intent.KQ_SEVERITY

        # Increment counter when we are about to re-emit the SAME KQ.
        if self.last_intent == kq:
            self._kq_emits += 1
        else:
            self._kq_emits = 1
        return self._record(kq, t0)

    def _intent_in_pre_arrival(self, f: Features, t0: float) -> Intent:
        q = self._direct_question_intent(f)
        if q is not None:
            return self._record(q, t0)
        # Cycle-2D10: anti-repeat for instructions. After 2 emits of the
        # same INSTRUCT_*, route to CLOSEOUT ("Stay on the line until
        # they get there.") so the caller gets continuous coaching
        # rather than identical re-emits. PSAP "compress more, talk
        # less" principle (Torres, AEDR Journal): once instruction is
        # delivered, talking less > talking same.
        if self._instruction_emits >= 2 and self.last_intent in (
            Intent.INSTRUCT_PRESSURE_BLEED,
            Intent.INSTRUCT_CHOKING,
            Intent.INSTRUCT_SEIZURE,
        ):
            log.info("fsm.pre_arrival_loop_to_closeout",
                     last_intent=getattr(self.last_intent, "value", None),
                     instruction_emits=self._instruction_emits)
            return self._record(Intent.CLOSEOUT, t0)

        # Pick the appropriate instruction.
        if f.choking:
            instr = Intent.INSTRUCT_CHOKING
        elif f.bleeding:
            instr = Intent.INSTRUCT_PRESSURE_BLEED
        elif f.seizure:
            instr = Intent.INSTRUCT_SEIZURE
        elif self.complaint == "trauma":
            # Cycle-2D9: when force-advanced from KQ-loop without a
            # current-turn feature, default to direct pressure for the
            # trauma rail (StatPearls + AHA hands-only).
            instr = Intent.INSTRUCT_PRESSURE_BLEED
        else:
            return self._record(Intent.CLOSEOUT, t0)

        # Cycle-2D10: increment instruction counter when re-emitting.
        if self.last_intent == instr:
            self._instruction_emits += 1
        else:
            self._instruction_emits = 1
        return self._record(instr, t0)

    def _intent_in_verify(self, f: Features, t0: float) -> Intent:
        """MPDS-9 sub-FSM: verify before instructing CPR.

        Rules:
        - V1 surface: skip if caller already said floor/flat/back.
        - V2 breathing-vs-gasping: skip if caller already said not
          breathing or gasping (both confirm cardiac arrest).
        - Both confirmed -> jump to CRITICAL_CPR with INSTRUCT_CPR_BEGIN.
        """
        # Cycle-2P2 (Team P A3): direct caller questions ("Should I move
        # him?", "How long until they get here?") take priority over
        # re-emitting the verify question. Mirrors _intent_in_cpr.
        q = self._direct_question_intent(f)
        if q is not None:
            return self._record(q, t0)
        # Cycle-2R3 (B3-A): caller's positive surface confirmation
        # mid-verify also latches surface_confirmed. (E.g. caller says
        # "yes, on the floor" or "okay he's on his back now" after the
        # reposition instruction.)
        if (not self.surface_confirmed) and f.floor_flat:
            self.surface_confirmed = True
            log.info("fsm.surface_confirmed_mid_verify")
        # Cycle-2R3 (B3-A) life-safety: caller signaled patient NOT on
        # the floor (chair / sitting / bed / etc). Direct caller to
        # reposition BEFORE re-asking the surface verification — the
        # patient has to be flat on a hard surface for compressions to
        # work (MPDS-9). If the negation persists across two emits,
        # surface_confirmed latches True heuristically (caller is doing
        # what they can; every second matters).
        if (not self.surface_confirmed) and f.floor_negation:
            self._reposition_emits = getattr(self, "_reposition_emits", 0) + 1
            if self._reposition_emits >= 3:
                # Caller has heard the reposition instruction twice and
                # still signals not-on-floor. Latch surface_confirmed
                # heuristically and proceed to breathing-verify so we
                # don't loop forever. Logged so the metric surfaces.
                self.surface_confirmed = True
                log.info("fsm.surface_latch_heuristic",
                         reposition_emits=self._reposition_emits)
            else:
                return self._record(Intent.INSTRUCT_CPR_REPOSITIONING, t0)
        if not self.surface_confirmed:
            # Cycle-2D6: bound the VERIFY_SURFACE re-emit loop. When the
            # caller cannot or will not answer the surface question
            # (silent, panicking, off-topic), looping the same question
            # is worse than advancing — every second matters in cardiac
            # arrest. After 3 emits with no floor signal in either
            # direction, latch surface_confirmed heuristically and
            # proceed to breathing-verify. Counter only increments when
            # caller's utterance had NO floor information; floor_flat
            # already latches True above, floor_negation routes to
            # REPOSITION (separate counter).
            self._verify_surface_emits = getattr(
                self, "_verify_surface_emits", 0
            ) + 1
            if self._verify_surface_emits >= 3:
                self.surface_confirmed = True
                log.info("fsm.surface_latch_after_verify_loop",
                         verify_surface_emits=self._verify_surface_emits)
            else:
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
        # Cycle-2D12: anti-repeat for CPR coaching. After 2 verbatim
        # emits of "Push hard and fast on the center of the chest,
        # twice per second," alternate with CLOSEOUT ("Stay on the
        # line until they get there.") so the caller gets variation.
        # CPR continues — the FSM keeps coming back to compressions —
        # but words don't drone verbatim. Reset counter on alternation
        # so the pattern is PUSH PUSH STAY PUSH PUSH STAY...
        if (self._instruction_emits >= 2
                and self.last_intent == Intent.INSTRUCT_CPR_BEGIN):
            log.info("fsm.cpr_loop_alternate_closeout",
                     instruction_emits=self._instruction_emits)
            self._instruction_emits = 0
            return self._record(Intent.CLOSEOUT, t0)
        if self.last_intent == Intent.INSTRUCT_CPR_BEGIN:
            self._instruction_emits += 1
        else:
            self._instruction_emits = 1
        return self._record(Intent.INSTRUCT_CPR_BEGIN, t0)

    # ---- direct-question router ---------------------------------------

    def _direct_question_intent(self, f: Features) -> Intent | None:
        # Cycle-2R3 (B1-A): caller asking "did you hear my address?" or
        # "where are you sending them?" preempts ALL other intents — caller
        # trust is on the line. Goes first in the priority order.
        if f.asks_heard_address:
            return Intent.ANSWER_HEARD_ADDRESS
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
        # Cycle-2R3 (B3-A) life-safety telemetry: surface_status reflects
        # the FSM's view of whether the patient is on a hard surface
        # (compressions can begin). cpr_allowed is the safety gate result —
        # MUST be False unless caller volunteered both unresponsive AND
        # not-breathing (the AHA T-CPR two-question gate; CLAUDE.md §10
        # life-safety per Brandon Dent, MD 2026-04-26).
        surface_status = (
            "confirmed" if self.surface_confirmed
            else "negated" if self._reposition_emits > 0
            else "unknown"
        )
        cpr_allowed = bool(self.surface_confirmed and self.breathing_assessed
                           and self.is_cardiac_arrest)
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
            surface_status=surface_status,
            cpr_allowed=cpr_allowed,
            reposition_emits=self._reposition_emits,
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
        Intent.INSTRUCT_CPR_REPOSITIONING:
            "Direct the caller to move the patient flat on the floor, on "
            "their back. Compressions cannot start on a chair or bed.",
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
        Intent.ANSWER_HEARD_ADDRESS:
            "Reassure the caller: yes, you have their address and units "
            "are on the way.",
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
