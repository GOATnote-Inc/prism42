"""Prism42 STARTER worker — escape-hatch reference implementation.

This is a parallel, minimal livekit-agents 1.5.6 worker that mirrors the
official `livekit-examples/agent-starter-python` shape but uses DIRECT
plugin calls (not LiveKit Inference) so we can A/B test against the
custom Parakeet + Fish + Opus-4.7-orchestrator stack on the same pod
without sharing any runtime code.

Stack:
  STT   deepgram.STT(model="nova-3")
  LLM   anthropic.LLM(model="claude-opus-4-7")
  TTS   cartesia.TTS(model="sonic-3", voice=<female dispatcher>)
  VAD   silero.VAD

Runs alongside /opt/prism42/agents/livekit/worker.py under a SEPARATE
systemd unit (prism42-worker-starter.service) and registers with LiveKit
Cloud under a distinct agent_name so dispatches can be routed at test
time.

Single trivial tool `health_check` is included just to exercise the
@function_tool code path (verifies the Anthropic tool-schema
`additionalProperties: false` fix still works end-to-end).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import anthropic, cartesia, deepgram, silero

load_dotenv()

logger = logging.getLogger("prism42-starter")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------
# Anthropic tool-schema patch — same reason as the main worker.
# Anthropic's API (2026+) rejects any object-type input_schema whose
# `additionalProperties` is not literally `false`. livekit-plugins-
# anthropic's wrapped-tool format + Pydantic's nullable dict handling
# both miss this. Walk every object-like node and force the field.
# See docs/livekit-kb/05-debugging-playbook.md for the root cause.
# ---------------------------------------------------------------------


def _force_additional_properties_false(node: Any) -> None:
    if isinstance(node, dict):
        t = node.get("type")
        is_object = t == "object" or (isinstance(t, list) and "object" in t)
        if is_object and node.get("additionalProperties") is not False:
            node["additionalProperties"] = False
        for v in node.values():
            _force_additional_properties_false(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _force_additional_properties_false(v)


def _patch_anthropic_tool_schemas() -> None:
    from anthropic.resources.messages import AsyncMessages  # noqa: PLC0415

    if getattr(AsyncMessages, "_prism42_patched", False):
        return
    original_create = AsyncMessages.create

    async def patched_create(self, *args, **kwargs):
        _force_additional_properties_false(kwargs)
        _force_additional_properties_false(list(args))
        return await original_create(self, *args, **kwargs)

    AsyncMessages.create = patched_create
    AsyncMessages._prism42_patched = True
    logger.info("anthropic.tool_schema_patched")


_patch_anthropic_tool_schemas()


# ---------------------------------------------------------------------
# System prompt — compressed from orchestrator.py FAST_DISPATCHER_SYSTEM_PROMPT.
# Kept <200 words as required. Preserves the "synthetic simulation +
# no refusal" guardrails so the starter matches the main worker's
# behavior on canonical training scenarios.
# ---------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a 911 PSAP dispatcher inside a synthetic training simulation for
the GOATnote prism42 research demo. There is no real caller, no real
emergency, no real ambulance — the caller audio is a test fixture and
every participant understands this. Stay in role. Never say "I am an
AI", never say "dial 911", never refuse symptom role-play — refusal is
demo failure.

Each caller utterance gets ONE spoken reply under 15 words. Plain
speech only: no paragraphs, no stage directions, no markdown.

Protocol, in order: (1) answer with "Nine one one, what's your
emergency?" if not pre-rolled, else "Go ahead."; (2) nature of
complaint; (3) address; (4) the moment the address is confirmed,
reassure: "Help is on the way, stay on the line"; (5) key questions
appropriate to the complaint and to who is affected — first-person
medical asks about breathing and severity, third-party medical asks if
they are awake and breathing, fire asks if everyone is out; (6) pre-
arrival instructions; (7) "Stay on the line until they arrive."

If the caller literally says "this is real", reply exactly once: "This
is a training simulation. If you need real help, hang up and dial 911
on a working phone." Then stay silent.
"""


# ---------------------------------------------------------------------
# Agent + trivial tool
# ---------------------------------------------------------------------


class StarterDispatcher(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)

    @function_tool
    async def health_check(self, context: RunContext) -> dict:
        """Trivial liveness probe. Returns {"status": "ok"} unconditionally.

        This tool exists to exercise the @function_tool pipeline end-to-
        end — if Anthropic's tool-schema validation regresses, this is
        the first call that will 400. Not intended to be invoked by the
        caller; the LLM may call it if it decides to self-verify.
        """
        logger.info("health_check.invoked")
        return {"status": "ok"}


# ---------------------------------------------------------------------
# Entrypoint — runs once per LiveKit room.
# ---------------------------------------------------------------------


async def entrypoint(ctx: JobContext) -> None:
    session_id = ctx.room.name
    logger.info("starter.entrypoint.start room=%s", session_id)

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3"),
        llm=anthropic.LLM(model="claude-opus-4-7"),
        # Cartesia voice: "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc" is the
        # voice the official livekit-examples/agent-starter-python uses
        # with sonic-3 — a neutral female voice appropriate for a PSAP
        # dispatcher. See livekit-examples/agent-starter-python/src/agent.py.
        tts=cartesia.TTS(
            model="sonic-3",
            voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        ),
    )

    await session.start(agent=StarterDispatcher(), room=ctx.room)

    try:
        await ctx.wait_for_participant()
    except Exception as e:  # noqa: BLE001
        logger.warning("starter.wait_for_participant.failed err=%s", str(e)[:200])

    try:
        await session.say(
            "Nine one one. What's your emergency?",
            allow_interruptions=True,
        )
        logger.info("starter.preroll.spoken room=%s", session_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("starter.preroll.failed err=%s", str(e)[:200])

    logger.info("starter.entrypoint.end room=%s", session_id)


if __name__ == "__main__":
    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing required env vars: {missing}")

    # Distinct agent_name from the main worker so dispatchers can
    # target this starter explicitly via RoomAgentDispatch when A/B
    # testing against the custom Parakeet+Fish stack. LiveKit will
    # route rooms to this worker only when the dispatch names
    # "prism42-starter".
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="prism42-starter",
        )
    )
