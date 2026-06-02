"""rule_adjudicator — every-turn, sub-1-ms structured audit for prism42.

Per voice-5role-design.md §1 (time position **d**: post-hoc audit, off-path):
the Adjudicator role has TWO paths.

1. `claude_critic.py` runs Opus 4.7 sampled at ~5% (`PRISM42_ADJUDICATOR_SAMPLE_RATE`).
2. **This module** runs every turn as pure-Python rule logic (≤1 ms),
   asserting the structural invariants of the 5-role pattern: did Defender
   fire? did Executor template? did Synthesizer's perception arrive in time?
   did Attacker produce a probe? and does the resulting verdict make sense
   for the classified intent?

Wiring
------
Called from `orchestrator.py` after each turn completes (after
`session.say` or `StopResponse` settles). Takes a structured snapshot of
which roles fired and emits `adjudicator.rule` via structlog. The output
is **advisory only** — never blocks audio, never modifies LLM context,
never written to chat_ctx.

Default OFF
-----------
Behind `PRISM42_ENABLE_RULE_ADJUDICATOR=1`. With the flag unset the
function returns None and emits nothing — preserves byte-equivalence
with current behavior.

Output schema (structlog event "adjudicator.rule")
--------------------------------------------------
```
{
  "session_id":             str,
  "turn_idx":               int,
  "intent":                 str,    # FSM-classified intent
  "defender_fired":         bool,   # FSM transition fired
  "executor_template":      bool,   # response_gate returned a template (vs LLM passthrough)
  "synthesizer_perception": bool,   # classifier returned in time with structured perception
  "attacker_probe":         bool,   # Attacker produced a finding for this turn
  "elapsed_ms":             float,  # rule-adjudicator's own runtime (target < 1)
  "verdict":                str,    # "ok" | "missing_safety_role" | "all_roles_fired" | "deterministic_template" | "llm_passthrough"
}
```

Failure modes addressed (voice-5role-design.md §5)
--------------------------------------------------
- This module CANNOT block audio: it has no IO and runs after the turn.
- This module CANNOT flag-everything-and-block: its only output is a
  structlog event; it is read by dashboards / eval harnesses, never by
  the audio path.
"""
from __future__ import annotations

import os
import time
from typing import Any

import structlog

log = structlog.get_logger("prism42.adjudicator")

# Intents we treat as "smalltalk" — non-safety-critical filler turns where
# missing FSM/template fire is OK (the LLM may handle them directly).
_SMALLTALK_INTENTS: frozenset[str] = frozenset(
    {"smalltalk", "unknown", "", "filler", "ack", "noop"}
)


def should_use_rule_adjudicator() -> bool:
    """Env-flag accessor — `PRISM42_ENABLE_RULE_ADJUDICATOR=1` to enable."""
    return os.environ.get("PRISM42_ENABLE_RULE_ADJUDICATOR", "0") == "1"


def _verdict(
    *,
    intent: str,
    defender_fired: bool,
    executor_template: bool,
    synthesizer_perception: bool,
) -> str:
    """Compute the rule verdict from the role-fire pattern."""
    is_safety_critical = intent.lower() not in _SMALLTALK_INTENTS
    safety_fired = defender_fired or executor_template

    if is_safety_critical and not safety_fired:
        return "missing_safety_role"
    if defender_fired and executor_template and synthesizer_perception:
        return "all_roles_fired"
    if executor_template:
        return "deterministic_template"
    if defender_fired:
        return "ok"
    return "llm_passthrough"


def adjudicate(
    *,
    session_id: str,
    turn_idx: int,
    intent: str,
    defender_fired: bool,
    executor_template: bool,
    synthesizer_perception: bool,
    attacker_probe: bool,
) -> dict[str, Any] | None:
    """Run the rule-based adjudicator on a completed turn.

    Pure Python, no IO, sub-1-ms target. Returns the verdict dict on
    success, or None when disabled. Never raises.
    """
    if not should_use_rule_adjudicator():
        return None

    start = time.monotonic()
    verdict = _verdict(
        intent=intent,
        defender_fired=defender_fired,
        executor_template=executor_template,
        synthesizer_perception=synthesizer_perception,
    )
    elapsed_ms = (time.monotonic() - start) * 1000.0

    event: dict[str, Any] = {
        "session_id": session_id,
        "turn_idx": turn_idx,
        "intent": intent,
        "defender_fired": defender_fired,
        "executor_template": executor_template,
        "synthesizer_perception": synthesizer_perception,
        "attacker_probe": attacker_probe,
        "elapsed_ms": elapsed_ms,
        "verdict": verdict,
    }
    log.info("adjudicator.rule", **event)
    return event
