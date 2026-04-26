"""Deterministic dispatcher templates — cycle-2T response gate.

Every Intent enum value (defined in dispatcher_fsm.py) has either:
  - a fixed template (the dispatcher-line text Fish TTS speaks),
  - or no template, meaning the LLM path is invoked with hard
    post-validation (currently only REPROMPT).

Hand-tuning rules every template obeys:
  1. 5 <= word_count <= 14 (audited by tests/voice/test_response_gate.py)
  2. one sentence, one terminator from {. ! ?}
  3. one question OR one instruction (not both)
  4. genderless by default — pronouns interpolate to they/them/their
     when the caller has not committed gender
  5. no filler at start ("OK", "Alright", "Got it", "Sure")
  6. natural English when read aloud by Fish S2-Pro

Source: findings/voice/cycle2T_response_gate/team-t/design.md §D2-D4.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Lazy-import-friendly: dispatcher_fsm imports this module ONLY via
# its consumer (response_gate.py); we do not import dispatcher_fsm here
# to avoid a circular load. The Intent enum's `.value` strings are the
# only contract the templates depend on.


# ---------------------------------------------------------------------
# Pronoun substitution table.
#
# `fsm.pronouns` is one of: 'unknown' | 'they' | 'he/him' | 'she/her'.
# Anything other than 'he/him' / 'she/her' renders as singular they.
# ---------------------------------------------------------------------

_PRONOUN_TABLE: dict[str, dict[str, str]] = {
    "he/him": {
        "pronoun_subject": "he",
        "pronoun_object": "him",
        "possessive": "his",
    },
    "she/her": {
        "pronoun_subject": "she",
        "pronoun_object": "her",
        "possessive": "her",
    },
    # Default — singular they for unknown / 'they' / anything else.
    "they": {
        "pronoun_subject": "they",
        "pronoun_object": "them",
        "possessive": "their",
    },
}


def pronoun_substitutions(pronouns: str) -> dict[str, str]:
    """Return the substitution map for the FSM's pronoun-state string.

    Defaults to singular-they when `pronouns` is 'unknown' or any
    unrecognized value. The gate calls this once per render.
    """
    return _PRONOUN_TABLE.get(pronouns, _PRONOUN_TABLE["they"])


# ---------------------------------------------------------------------
# TemplateSpec.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateSpec:
    """A single deterministic dispatcher utterance.

    Fields
    ------
    text:
        The English line, with optional `{pronoun_subject}` /
        `{pronoun_object}` / `{possessive}` placeholders. Word count
        AFTER substitution must be in [5, 14].
    pronoun_required:
        True if the line carries pronoun references. False = the line
        is genderless by construction (the safest case).
    state_filters:
        Optional FSM states under which this template applies. None =
        applies in every state. Currently unused — the gate routes by
        intent, and intents are 1:1 with state-conjunction in the FSM
        already. Reserved for future fine-grain branching.
    notes:
        Free-form developer notes; not user-facing.
    """

    text: str
    pronoun_required: bool = False
    state_filters: tuple[str, ...] | None = None
    notes: str = ""


# ---------------------------------------------------------------------
# Template table — ALL 21 intents.
#
# Keys are the Intent.value strings (NOT the enum members) so this
# module does not need to import dispatcher_fsm at load time.
# response_gate.py performs the lookup with `intent.value`.
# ---------------------------------------------------------------------

TEMPLATES: dict[str, TemplateSpec] = {
    # ----- Intake (4 intents) ---------------------------------------
    "request_location_and_emergency": TemplateSpec(
        # 11 words — IAED Case Entry canonical opener.
        text="Nine one one, what is the address of your emergency?",
        notes="Verbatim PSAP opener; matches greeting cache + system prompt.",
    ),
    "request_location": TemplateSpec(
        # 8 words.
        text="What is the address of the emergency?",
        notes="Caller stated emergency without an address.",
    ),
    "request_emergency": TemplateSpec(
        # 7 words.
        text="What is happening at that location?",
        notes="Caller stated address without an emergency.",
    ),
    "confirm_address": TemplateSpec(
        # Cycle-2D5-A: 9 audited words. Default form acknowledges without
        # echo. The gate's render_template_for() rewrites "your address"
        # to "you at <captured-address>" when fsm.address_text is set,
        # which extends the runtime word count by 1-4 words (still ≤14).
        # PSAP discipline (Sarpy County, Caldwell County, NHTSA EMD,
        # NAEMD): read the address back verbatim so the caller can
        # correct STT mishears.
        text="I have your address, help is on the way.",
        notes=(
            "Cycle-2D5-A: gate substitutes 'your address' -> "
            "'you at {fsm.address_text}' when address_text is non-empty."
        ),
    ),

    # ----- Reassurance (3 intents, latched once per call) -------------
    "deliver_reassurance": TemplateSpec(
        # 11 words. Single sentence — canonical PSAP reassurance.
        # Fallback variant for fire/crime/unknown complaints. Trauma and
        # medical use the fused variants below.
        text="Help is on the way and I am staying with you.",
        notes="Fallback once-per-call reassurance. FSM latches reassurance_done=True.",
    ),
    # Cycle-2D5-B: complaint-specific reassurance variants. Each fuses
    # reassurance + co-presence + first directive question into a single
    # turn so the caller is never left in the listening role with no task.
    # Source: cycle2D4_dispatch_research/team-research/dispatch-patterns.md.
    "deliver_reassurance_trauma": TemplateSpec(
        # 12 words. Reassurance + co-presence + KQ_BLEEDING_LOCATION fused.
        # Single terminator (the question mark); commas pace the clauses.
        text="Help is on the way, stay with me, where is the bleeding?",
        notes="Trauma rail. Fuses reassurance with bleeding-location KQ.",
    ),
    "deliver_reassurance_medical": TemplateSpec(
        # 13 words. Reassurance + co-presence + verbal task. Generic
        # because medical KQ branches first-vs-third-party — keep the
        # specific KQ (responsive_breathing or severity) for the next turn.
        text="Help is on the way, stay with me, tell me what is happening.",
        notes="Medical rail. Verbal task ('tell me') keeps caller active.",
    ),

    # ----- Key questions (5 intents) --------------------------------
    "kq_responsive_breathing": TemplateSpec(
        # 7 words. Genderless — uses "the patient" not pronouns to
        # avoid singular-they verb-agreement awkwardness ("Is they...").
        text="Is the patient awake and breathing now?",
        notes="Third-party medical. 'awake and breathing' covers both checks.",
    ),
    "kq_severity": TemplateSpec(
        # 9 words. First-party medical — caller is the patient.
        text="Can you speak in full sentences right now?",
        notes="First-person medical proxy for severity. No pronouns.",
    ),
    "kq_bleeding_location": TemplateSpec(
        # 8 words. Genderless.
        text="Where is the bleeding, and how heavy?",
        notes="Trauma key question.",
    ),
    "kq_fire_evacuation": TemplateSpec(
        # 8 words.
        text="Is everyone out of the building right now?",
        notes="Fire-complaint key question.",
    ),
    "kq_safe_location": TemplateSpec(
        # 7 words.
        text="Are you in a safe place now?",
        notes="Crime / trauma — caller safety check.",
    ),

    # ----- Verification — CPR gate (2 intents) -----------------------
    "verify_cpr_surface": TemplateSpec(
        # 10 words. Genderless (uses 'they' singular).
        text="Are they on the floor, flat on their back?",
        pronoun_required=True,
        notes="MPDS-9 V1: position. Defaults to they/their — pronoun-safe.",
    ),
    "verify_cpr_breathing": TemplateSpec(
        # 8 words. Genderless default.
        text="Are they breathing normally, or only gasping?",
        pronoun_required=True,
        notes="MPDS-9 V2: breathing quality. 'gasping' is the agonal cue.",
    ),

    # ----- Pre-arrival instructions (4 intents) ---------------------
    "instruct_cpr_compressions": TemplateSpec(
        # 13 words. Hard-and-fast canonical T-CPR phrasing.
        text="Push hard and fast on the center of the chest, twice per second.",
        notes="ONLY emitted when CPR safety gate (cycle-2T) green-lights.",
    ),
    # Cycle-2R3 (B3-A) — physician-reviewed text, Brandon Dent, MD 2026-04-26.
    # Caller said patient is in chair / sitting / bed / etc.; we cannot
    # begin compressions on a non-flat surface. Direct caller to reposition.
    "instruct_cpr_repositioning": TemplateSpec(
        # 9 words. Physician-revised wording (less alarm, clear instruction).
        text="Move them flat on the floor, on their back.",
        notes="MPDS-9: caller indicated patient not on floor — reposition before CPR. "
              "Life-safety; physician-reviewed (Brandon Dent, MD per CLAUDE.md §10).",
    ),
    "instruct_choking_back_blows": TemplateSpec(
        # 11 words. Genderless ("them" placeholder).
        text="Stand behind {pronoun_object} and give five firm back blows.",
        pronoun_required=True,
        notes="Choking pre-arrival — adult back-blows.",
    ),
    "instruct_pressure_bleed": TemplateSpec(
        # 11 words.
        text="Press hard on the wound with a clean cloth now.",
        notes="Bleeding pre-arrival. No pronouns needed.",
    ),
    "instruct_seizure_clear_area": TemplateSpec(
        # 9 words. Single instruction. Genderless plural.
        text="Clear the area around {pronoun_object} and do not restrain.",
        pronoun_required=True,
        notes="Seizure pre-arrival. 'Do not restrain' is the headline rule.",
    ),

    # ----- Direct-question router (3 intents) ------------------------
    "answer_do_not_move": TemplateSpec(
        # 10 words. Genderless plural.
        text="Do not move them unless they are in danger.",
        pronoun_required=True,
        notes="ANSWER-the-question rule: 'should I move them?'",
    ),
    "answer_how_long": TemplateSpec(
        # 11 words. Single sentence — answer + retain.
        text="As fast as they can, so please stay on the line.",
        notes="ANSWER 'how long?'. 'they' here is responders, not patient.",
    ),
    "answer_outcome_uncertain": TemplateSpec(
        # 11 words. Single sentence. Hard rule: never promise outcome.
        text="Responders are close, so tell me if anything changes.",
        notes="ANSWER 'will they make it?'. NEVER promise.",
    ),
    # Cycle-2R3 (B1-A): caller asking "did you hear my address?" /
    # "where are you sending them?" — re-confirm the address was captured
    # and units are en route. Only fires when address_known is already
    # True (FSM never routes here in INTAKE).
    # Cycle-2D14: when the caller asks "did you hear my address?", echo
    # the captured address back instead of the generic acknowledgment.
    # Same render-path substitution as confirm_address — the gate
    # rewrites "your address" -> "you at <fsm.address_text>" when
    # address_text is non-empty. Matches PSAP discipline (read back
    # verbatim) under all address-confirm intents, not just the first.
    "answer_heard_address": TemplateSpec(
        # 11 words. Single sentence. Reassures caller dispatch is real.
        text="Yes, I have your address and units are on the way.",
        notes="ANSWER 'did you hear my address?' — reassures caller their address was captured.",
    ),

    # ----- Defaults / fallback (2 intents) ---------------------------
    # REPROMPT can also be a fixed template — we do that here for
    # maximum determinism. The integrator may swap to the LLM path if
    # the deterministic line proves insufficient.
    "reprompt_caller": TemplateSpec(
        # 7 words. Polite, brief.
        text="Sorry, could you repeat that for me?",
        notes="Caller utterance unintelligible / classifier blank.",
    ),
    # Cycle-2D15 LIFE-SAFETY: physician-reviewed by Brandon Dent, MD on
    # 2026-04-26 per CLAUDE.md §10. Triggers when caller signals patient
    # resumed breathing mid-CPR. Imperative + monitoring + co-presence.
    "stop_cpr_breathing_resumed": TemplateSpec(
        # 11 words. Single terminator.
        text="Stop compressions and watch their breathing — stay on the line.",
        notes=(
            "Cycle-2D15 LIFE-SAFETY: stop CPR when patient resumed breathing. "
            "Physician-reviewed (Brandon Dent, MD 2026-04-26)."
        ),
    ),
    "closeout": TemplateSpec(
        # 9 words.
        text="Stay on the line until they get there.",
        notes="HANDOFF state. 'they' = responders.",
    ),
}


# ---------------------------------------------------------------------
# Render helper.
# ---------------------------------------------------------------------


def render_template(intent_value: str, pronouns: str) -> str | None:
    """Return the rendered template text, or None if no template exists.

    `intent_value` is the `.value` string of the Intent enum (not the
    enum member, to avoid forcing dispatcher_fsm import at template-table
    load time). `pronouns` is the FSM's `pronouns` attribute.

    Returns None for intents that have no template (gate routes those
    to the LLM path with validators).
    """
    spec = TEMPLATES.get(intent_value)
    if spec is None:
        return None
    text = spec.text
    if "{" in text:
        sub = pronoun_substitutions(pronouns)
        for k, v in sub.items():
            text = text.replace("{" + k + "}", v)
    return text


# ---------------------------------------------------------------------
# Self-audit (importable).
# ---------------------------------------------------------------------


def audit_word_counts() -> dict[str, int]:
    """Return {intent_value: word_count} after they/them substitution.

    Used by tests/voice/test_response_gate.py to assert every template
    is in [5, 14] words. Importable so other tooling can reuse the
    audit.
    """
    out: dict[str, int] = {}
    for intent_value, spec in TEMPLATES.items():
        rendered = spec.text
        if "{" in rendered:
            sub = _PRONOUN_TABLE["they"]
            for k, v in sub.items():
                rendered = rendered.replace("{" + k + "}", v)
        # Strip terminators for clean word count.
        words = [w for w in rendered.replace(",", "").replace(".", "").
                 replace("?", "").replace("!", "").split() if w]
        out[intent_value] = len(words)
    return out


# Re-exported names — kept short, gate does `from templates import *`-friendly.
__all__ = [
    "TEMPLATES",
    "TemplateSpec",
    "audit_word_counts",
    "pronoun_substitutions",
    "render_template",
]
