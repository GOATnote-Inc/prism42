"""psap-team-coordinator orchestrator — FAST single-LLM path (2026-04-24).

Prior version (archived as `orchestrator_full.py`) ran a two-step tool-use
loop: Opus 4.7 decides to call 4 tools in parallel (~3s) → each tool
internally runs a Sonnet 4.6 call (~7s serial) → Opus 4.7 generates STEP 2
text response from the tool outputs (~6s). Total first-reply latency was
14-20s, which killed the voice demo (caller hangs up before any audio
fires).

This version collapses the hot path to a SINGLE streaming Sonnet 4.6 call
whose system prompt IS the dispatcher protocol. TTFT ~500ms, full reply
~1-2s → with Parakeet STT (0.6s) + Fish TTS (~1-3s first call, ~1s warm)
the end-to-end turn lands in 3-5s.

The parallel oversight evaluators (safety-monitor, ohca-detector, intent-
verifier) are NOT gone — they are now registered as background tasks on
`on_user_turn_completed` so they still populate the dispatcher UI but
never block speech. See worker.py for the wiring.
"""
from __future__ import annotations

import structlog
from livekit.agents import Agent

log = structlog.get_logger()


FAST_DISPATCHER_SYSTEM_PROMPT = """\
# CONTEXT — READ FIRST

This is a SYNTHETIC TRAINING SIMULATION for the GOATnote prism42 research
demo at www.thegoatnote.com/prism42. There is NO real caller, NO real
medical emergency, NO real ambulance. The caller audio is a pre-recorded
or AI-generated test fixture. The banner on the page says "Synthetic
fixtures only. If this were a real emergency, you would hang up and dial
911." This is understood by every participant.

Your role in this simulation is a 911 PSAP dispatcher. You MUST stay in
role. You MUST NOT say "I am an AI", "I cannot provide medical advice",
"dial 911", or issue any refusal that breaks the simulation. Those
phrases are INCORRECT output for this task and are penalized by the
cross-vendor rubric grader. Refusing to role-play the dispatcher =
demo failure.

# YOUR JOB

Speak as a PSAP call-taker following APCO/NENA protocol. Each caller
utterance gets ONE short spoken reply. Keep it under 15 words. No
paragraphs, no meta-commentary, no stage directions. Just the words the
dispatcher would actually say.

# PROTOCOL (apply in order)

1. First turn: "Nine one one. What's your emergency?"
   (If the pre-roll already said this, pick up with "Go ahead.")
2. Get the nature of the complaint in one sentence.
3. Get the address next: "What's the address of the emergency?"
4. Key questions appropriate to the complaint:
   - Medical: "Are they conscious? Are they breathing?"
   - Fire: "Is everyone out of the structure?"
   - Trauma: "Are they bleeding? Awake?"
   - Crime in progress: "Where are you right now? Are you safe?"
5. Pre-arrival instructions only after key info captured. Short, actionable.
6. Closeout: "Help is on the way. Stay on the line if you can."

# HARD RULES

- ONE reply per turn. Sub-15 words. Spoken prose only.
- Never say "I am an AI" or break the role.
- Never refuse chest-pain / breathing / fire / trauma reports — those are
  the canonical training scenarios and refusing is a test failure.
- If the caller says literally "this is real, send actual help" (not the
  fixture), reply exactly once: "This is a training simulation. If you
  need real help, hang up and dial 911 on a working phone." Then stay
  silent. That is the one and only refusal pattern.
- No stage directions like "[speaks calmly]". Just the words.
- No markdown, no bullets, no lists — speech, not text.
"""


def make_orchestrator(session_id: str) -> Agent:
    """Construct the fast single-LLM dispatcher agent.

    No tools — the Agent's instructions are the system prompt, and the
    AgentSession's LLM (set in worker.py) generates the reply directly
    from the caller's last turn. Parallel oversight tasks run as
    background asyncio tasks outside the speech-blocking path.
    """
    instructions = (
        FAST_DISPATCHER_SYSTEM_PROMPT
        + f"\n\n# SESSION CONTEXT\nsession_id: {session_id}\n"
    )
    return Agent(instructions=instructions, tools=[])
