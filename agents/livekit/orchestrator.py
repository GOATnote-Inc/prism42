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

Cycle-2e (2026-04-25) addition: optional Pipecat-style sentence-buffer +
first-segment token cap, gated on PRISM42_CYCLE_2E_BUFFER=1. When OFF
(default) the agent path is byte-for-byte identical to the cycle-2d
baseline. When ON, BufferedDispatcherAgent overrides tts_node() to ship
the first sentence (or token-capped chunk) to TTS as soon as it's
available, so audio can start earlier in the LLM stream.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

import structlog
from livekit import rtc
from livekit.agents import Agent
from livekit.agents.voice.agent import ModelSettings  # type: ignore[attr-defined]

# Cycle-2L: StopResponse is the LiveKit Agents 1.5.x canonical hammer for
# "I already answered this turn deterministically — do NOT run the LLM."
# When raised inside on_user_turn_completed, agent_activity.py:1973 catches
# it and returns from the user-input handler, which also cancels any
# preemptive-generation in flight. Without this, the gate's session.say()
# template AND the LLM-driven reply both fire — caller hears the gate
# template followed by the FAST_DISPATCHER_SYSTEM_PROMPT-driven LLM reply
# (which says "Nine one one, what is the address of your emergency?" on
# every turn because the LLM has no FSM state and re-applies "First turn
# verbatim"). Default-OFF guarded — only raised when the gate's flag is
# enabled AND the gate elected to emit a template successfully.
try:
    from livekit.agents.llm import StopResponse  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    StopResponse = None  # type: ignore[assignment]

log = structlog.get_logger()


# ---------------------------------------------------------------------
# Cycle-2e — Pipecat sentence-buffer constants + helpers.
# ---------------------------------------------------------------------

# Pipecat sentence regex — terminator + optional close-quote/paren + whitespace.
# Verbatim from pipecat_bots/sentence_buffer.py:64.
_SENTENCE_RE = re.compile(r'[.!?]["\'\)]*\s')

# Pipecat InputParams defaults (llama_cpp_buffered_llm.py InputParams).
_FIRST_SEGMENT_MAX_TOKENS = int(os.environ.get("PRISM42_CYCLE_2E_FIRST_TOKENS", "24"))
_SEGMENT_MAX_TOKENS = int(os.environ.get("PRISM42_CYCLE_2E_NEXT_TOKENS", "32"))
_SEGMENT_HARD_MAX_TOKENS = int(os.environ.get("PRISM42_CYCLE_2E_HARD_TOKENS", "96"))

# Metric-honesty: first segment must contain at least this many chars of LLM
# text before we let TTS render it. Rejects ".", "Yes.", and similar pure-
# punctuation flushes that the bench's peak>1000 check might still count as
# the first useful audio frame. Tunable so a flat-fail bench can prove the
# threshold isn't smuggling pollution.
_MIN_FIRST_SEGMENT_CHARS = int(os.environ.get("PRISM42_CYCLE_2E_MIN_CHARS", "8"))


def _approx_tokens(text: str) -> int:
    """Coarse char-to-token count. The cap is a fence, not a guillotine."""
    return max(len(text) // 4, 1)


class _SentenceBuffer:
    """Verbatim port of Pipecat's pipecat_bots/sentence_buffer.py priority
    ladder: sentence > clause > word > everything.

    `extract_complete_sentences()` returns the prefix up through the LAST
    regex match (multi-sentence segments stay together — important for
    prosody). `extract_at_boundary()` is the force-flush fallback.
    """

    def __init__(self) -> None:
        self.text: str = ""
        self.token_count: int = 0

    def add(self, delta: str) -> None:
        self.text += delta
        self.token_count += _approx_tokens(delta)

    def has_content(self) -> bool:
        return bool(self.text and self.text.strip())

    def reset_token_count(self) -> None:
        self.token_count = 0

    def extract_complete_sentences(self) -> str | None:
        """Return prefix through the LAST sentence terminator, or None."""
        matches = list(_SENTENCE_RE.finditer(self.text))
        if not matches:
            return None
        end = matches[-1].end()
        out, self.text = self.text[:end], self.text[end:]
        return out

    def extract_at_boundary(self) -> str | None:
        """Force-flush at sentence > clause > word > everything."""
        sent = self.extract_complete_sentences()
        if sent is not None:
            return sent
        # Clause boundary.
        for ch in (",", ";", "\n"):
            idx = self.text.rfind(ch)
            if idx >= 0:
                end = idx + 1
                # Eat a trailing space if present.
                if end < len(self.text) and self.text[end] == " ":
                    end += 1
                out, self.text = self.text[:end], self.text[end:]
                return out
        # Word boundary.
        idx = self.text.rfind(" ")
        if idx >= 0:
            out, self.text = self.text[:idx + 1], self.text[idx + 1:]
            return out
        # Last resort — flush everything.
        if self.text:
            out, self.text = self.text, ""
            return out
        return None


class BufferedDispatcherAgent(Agent):
    """Sentence-boundary buffered TTS emit + first-segment token cap.

    See findings/voice/cycle-2e-pipecat/pattern.md and
    findings/b300_bench/cycle2e_orchestration/patch_plan.md.

    Override tts_node so the first segment ships on the earliest of:
      - first sentence terminator (.!? + space)
      - approximately FIRST_SEGMENT_MAX_TOKENS

    Subsequent segments use SEGMENT_MAX_TOKENS / SEGMENT_HARD_MAX_TOKENS.
    Metric-honesty check (a) — first segment must contain >= MIN_CHARS
    of LLM-generated text before it's allowed to flush.
    """

    async def tts_node(  # type: ignore[override]
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        local_log = structlog.get_logger()
        buf = _SentenceBuffer()
        # Mutable state captured by closure for _gated().
        is_first = [True]
        cap = [_FIRST_SEGMENT_MAX_TOKENS]
        hard_cap = [_FIRST_SEGMENT_MAX_TOKENS]
        first_segment_chars: list[int] = []
        t_llm_first_delta: list[float] = []
        t_first_segment_published: list[float] = []

        async def _gated() -> AsyncGenerator[str, None]:
            async for delta in text:
                if not delta:
                    # Risk-2 guard: ignore reasoning-content / FlushSentinel
                    # / empty deltas (pattern.md §4 Risk 2).
                    continue
                if not t_llm_first_delta:
                    t_llm_first_delta.append(time.monotonic())
                buf.add(delta)

                # Sentence-boundary path.
                seg = buf.extract_complete_sentences()
                # Token-cap force-flush.
                if seg is None and buf.token_count >= cap[0]:
                    seg = buf.extract_at_boundary()
                # Hard cap.
                if seg is None and buf.token_count >= hard_cap[0]:
                    seg = buf.extract_at_boundary()

                if seg:
                    buf.reset_token_count()
                    if is_first[0]:
                        # Metric-honesty check (a): first segment must contain
                        # at least MIN_CHARS of LLM text. If under, push back
                        # into buffer and keep accumulating.
                        if len(seg) < _MIN_FIRST_SEGMENT_CHARS:
                            buf.text = seg + buf.text
                            buf.token_count += _approx_tokens(seg)
                            continue
                        first_segment_chars.append(len(seg))
                        is_first[0] = False
                        cap[0] = _SEGMENT_MAX_TOKENS
                        hard_cap[0] = _SEGMENT_HARD_MAX_TOKENS
                        t_first_segment_published.append(time.monotonic())
                        # Telemetry: how long did we hold the LLM stream
                        # before publishing the first segment?
                        if t_llm_first_delta:
                            dt_ms = int(
                                (t_first_segment_published[0] - t_llm_first_delta[0]) * 1000
                            )
                            local_log.info(
                                "overlap.first_segment_published_after_llm_ms",
                                ms=dt_ms,
                                chars=first_segment_chars[0],
                                approx_tokens=_approx_tokens(seg),
                                cap_used=_FIRST_SEGMENT_MAX_TOKENS,
                            )
                    yield seg
            # End-of-stream — flush the incomplete tail.
            if buf.has_content():
                tail = buf.text.strip()
                if tail:
                    if is_first[0] and len(tail) < _MIN_FIRST_SEGMENT_CHARS:
                        # Edge case: the entire reply is shorter than the
                        # min-chars threshold (e.g. "OK."). Ship it anyway —
                        # silence is worse. Log so the bench can flag it.
                        local_log.info(
                            "overlap.first_segment_below_threshold",
                            chars=len(tail),
                            min_chars=_MIN_FIRST_SEGMENT_CHARS,
                        )
                    yield tail

        # Delegate to Agent.default.tts_node — already wraps the underlying
        # TTS plugin (livekit.agents.voice.agent.Agent.default).
        async for frame in Agent.default.tts_node(self, _gated(), model_settings):
            yield frame


# ---------------------------------------------------------------------
# Cycle-2Q — DispatcherFSM integration.
#
# Default OFF (PRISM42_ENABLE_FSM=0). When enabled, FsmDispatcherAgent
# wraps BufferedDispatcherAgent so the cycle-2e sentence-buffer + FSM
# per-turn prompt rewrite stack composes cleanly. The FSM owns dialogue
# state (latches, pronouns, anti-repetition); the LLM owns phrasing.
# See findings/voice/cycle2Q_logic_audit/2026-04-26-team3/fsm-design.md.
# ---------------------------------------------------------------------

# Lazy import — keeps the cycle-2P path free of FSM module load when
# the flag is off. Verified import-cost on B300 pod: <5 ms cold.
try:
    from dispatcher_fsm import (  # type: ignore[import-not-found]
        DispatcherFSM,
        Intent,
        fsm_for_session,
        should_use_fsm,
    )
except Exception:  # noqa: BLE001
    DispatcherFSM = None  # type: ignore[assignment]
    Intent = None  # type: ignore[assignment]
    fsm_for_session = None  # type: ignore[assignment]

    def should_use_fsm() -> bool:  # type: ignore[no-redef]
        return False


# Cycle-2T — deterministic response gate between FSM and Fish TTS.
# Default OFF; flag PRISM42_ENABLE_RESPONSE_GATE=1 to enable. When
# disabled the gate module is imported but never invoked, so the
# cycle-2Q FSM-only path is byte-equivalent.
try:
    from response_gate import (  # type: ignore[import-not-found]
        gate_for_fsm,
        should_use_response_gate,
    )
except Exception:  # noqa: BLE001
    gate_for_fsm = None  # type: ignore[assignment]

    def should_use_response_gate() -> bool:  # type: ignore[no-redef]
        return False


# Cycle-2C Phase 1 — shadow Nemotron structured classifier (SHADOW MODE).
# Default OFF; flag PRISM42_ENABLE_SHADOW_CLASSIFIER=1 to enable. When ON
# the classifier runs as a fire-and-forget background task AFTER
# fsm.transition() has already chosen the intent. FSM behavior is byte-
# equivalent regardless of classifier output — Phase 1 only LOGS the
# perception and PUBLISHES it via dispatch_publisher for the UI to render.
# No fusion in this phase.
try:
    from structured_classifier import (  # type: ignore[import-not-found]
        classify_async as _shadow_classify_async,
        should_use_shadow_classifier,
    )
except Exception:  # noqa: BLE001
    _shadow_classify_async = None  # type: ignore[assignment]

    def should_use_shadow_classifier() -> bool:  # type: ignore[no-redef]
        return False


async def _run_shadow_classifier(
    *,
    client: Any,
    utterance: str,
    turn_index: int,
    dispatch_publisher: Any,
    session_id: str,
) -> None:
    """Cycle-2C Phase 1 — fire-and-forget shadow classifier coroutine.

    Runs OUTSIDE the voice hot path. Calls structured_classifier.classify_async
    with a 600 ms hard timeout (Munger inversion). On success, the classifier
    emits a `classifier.perception` log line itself; we then publish a
    `perception` event over the dispatch data-track. On failure (timeout /
    parse / schema), classify_async returns None and logs the reason.

    SHADOW MODE: this coroutine NEVER mutates the FSM. The orchestrator's
    voice path has already chosen its intent before this task is scheduled.
    """
    local_log = structlog.get_logger()
    if _shadow_classify_async is None or client is None:
        return
    try:
        result = await _shadow_classify_async(client, utterance)
    except Exception as e:  # noqa: BLE001
        local_log.warning(
            "classifier.exception",
            err=str(e)[:200],
            session_id=session_id,
            utterance=utterance[:120],
        )
        return
    if result is None:
        # classify_async already logged the specific failure reason
        # (timeout / json_parse_error / invalid_schema / error). No
        # need to double-log; just exit quietly.
        return
    if dispatch_publisher is None:
        return
    try:
        dispatch_publisher.publish_perception(
            turn_index=turn_index,
            classifier_payload=result.to_payload(),
        )
    except Exception as e:  # noqa: BLE001
        local_log.warning(
            "classifier.publish_failed",
            err=str(e)[:200],
            session_id=session_id,
        )


class FsmDispatcherAgent(BufferedDispatcherAgent):
    """BufferedDispatcherAgent + per-turn FSM-driven prompt rewrite.

    Hook: `on_user_turn_completed(turn_ctx, new_message)` fires AFTER
    STT-final and BEFORE the LLM generation kicks off
    (livekit/agents/voice/agent.py:247). We extract the caller's
    utterance, advance the FSM, and call `update_instructions(...)`
    so the LLM sees a one-page, intent-tagged system prompt instead
    of the 4 KB FAST_DISPATCHER_SYSTEM_PROMPT.

    Latency budget: <100 ms / turn (FSM + prompt build + update). On
    B300 the FSM transition is <50 us; the bulk of the budget is
    update_instructions, which is a same-process attribute write.
    """

    def __init__(
        self,
        *,
        instructions: str,
        tools: list[Any],
        session_id: str,
        fsm: Any,
    ) -> None:
        super().__init__(instructions=instructions, tools=tools)
        self._session_id = session_id
        self._fsm = fsm
        # Cycle-2T: deterministic response gate. None when flag off.
        self._response_gate = (
            gate_for_fsm(fsm) if (gate_for_fsm and should_use_response_gate()) else None
        )

    @property
    def fsm(self) -> Any:
        """Expose the FSM for worker.py to record dispatcher utterances
        into the anti-repetition buffer post-LLM."""
        return self._fsm

    async def on_user_turn_completed(  # type: ignore[override]
        self,
        turn_ctx: Any,
        new_message: Any,
    ) -> None:
        local_log = structlog.get_logger()
        t0 = time.monotonic()
        # Cycle-2L: when the gate emits a template, we set this flag so the
        # outer try/except (which exists to keep the FSM from wedging the
        # voice path) does NOT swallow the StopResponse we want LiveKit to
        # see. Without this, raise-StopResponse-then-broad-except yields a
        # 'orchestrator.fsm_turn_failed' log line and the LLM still runs.
        gate_emitted_template = False
        try:
            utterance = (getattr(new_message, "text_content", None) or "").strip()
            if not utterance:
                # Empty turn — nothing to advance. Keep prior instructions.
                return
            intent = self._fsm.transition(utterance)

            # (additive) cycle-2T2 Team T2 fix — publish `turn` event BEFORE
            # the gate-decision branch so template-only turns ALSO emit a
            # turn event. Previously this lived under the LLM-fallthrough
            # path (line ~372), which the gate's `return` at line 365
            # short-circuited 100% of the time once cycle-2T was on. Result:
            # dispatcher-UI transcript pane stayed blank because no `turn`
            # events ever reached the browser. The publish is best-effort
            # and never blocks the voice path. (See findings/voice/
            # cycle2T2_transcript_debug/team-t2/diagnosis.md.)
            try:
                _dp = getattr(self, "_dispatch_publisher", None)
                if _dp is not None:
                    _dp.publish_turn(
                        caller_utterance=utterance,
                        fsm=self._fsm,
                        latency_ms={},  # latency populated by reply event
                    )
            except Exception as e:  # noqa: BLE001
                local_log.warning(
                    "orchestrator.dispatch_publish_failed", err=str(e)[:200]
                )

            # ---- cycle-2C Phase 1 — SHADOW classifier observer ----
            # The FSM has already chosen the intent above. The classifier
            # runs as fire-and-forget so it never blocks speech. Output is
            # logged + relayed to the UI via dispatch_publisher; the FSM
            # is unaware. Phase 1 = observe-only. No fusion.
            # Hoisted so the 5-role dispatches below can reference it even
            # when the shadow-classifier branch is skipped (flag OFF).
            turn_index_for_perception = (
                getattr(_dp, "_turn_index", 0) if _dp is not None else 0
            )
            try:
                _shadow_client = getattr(self, "_shadow_classifier_client", None)
                if (
                    should_use_shadow_classifier()
                    and _shadow_classify_async is not None
                    and _shadow_client is not None
                ):
                    asyncio.create_task(
                        _run_shadow_classifier(
                            client=_shadow_client,
                            utterance=utterance,
                            turn_index=turn_index_for_perception,
                            dispatch_publisher=_dp,
                            session_id=self._session_id,
                        )
                    )
            except Exception as e:  # noqa: BLE001
                local_log.warning(
                    "orchestrator.shadow_classifier_dispatch_failed",
                    err=str(e)[:200],
                )

            # 5-role activation (2026-04-27): Guardrails input rail + Attacker
            # adversarial probe — both fire-and-forget, structlog-only
            # observability. Each wrapper is env-flag-gated default OFF
            # (PRISM42_ENABLE_GUARDRAILS, PRISM42_ENABLE_ATTACKER) — when
            # disabled the dispatch returns None immediately without
            # importing the SDK, hitting the network, or mutating any
            # FSM / chat_ctx state. Output flows ONLY to structlog; the
            # audio path is unaffected.
            # Refs:
            #   findings/research/2026-04-27-future-stack/voice-5role-design.md §1, §3
            #   findings/research/2026-04-27-future-stack/nvidia-voice-stack-architecture.md §1
            try:
                from guardrails_wrapper import check_input as _guardrails_check_input  # noqa: PLC0415
                asyncio.create_task(
                    _guardrails_check_input(
                        utterance,
                        session_id=self._session_id,
                        turn_idx=turn_index_for_perception,
                    )
                )
            except Exception as e:  # noqa: BLE001
                local_log.debug(
                    "orchestrator.guardrails_input_dispatch_failed",
                    err=str(e)[:200],
                )

            try:
                from attacker import probe as _attacker_probe  # noqa: PLC0415
                asyncio.create_task(
                    _attacker_probe(
                        caller_utterance=utterance,
                        dispatcher_reply=getattr(intent, "value", str(intent)),
                        session_id=self._session_id,
                        turn_idx=turn_index_for_perception,
                    )
                )
            except Exception as e:  # noqa: BLE001
                local_log.debug(
                    "orchestrator.attacker_dispatch_failed",
                    err=str(e)[:200],
                )

            # Cycle-2T: deterministic response gate between FSM and TTS.
            # When the gate elects a template, we emit directly to TTS via
            # session.say() and SHORT-CIRCUIT the LLM call — voice path is
            # bounded by code, not LLM constraint-following. When the gate
            # elects the LLM path, we fall through to the cycle-2Q
            # update_instructions branch below.
            if self._response_gate is not None:
                decision = self._response_gate.gate_decision(
                    getattr(intent, "value", str(intent)),
                    caller_utterance=utterance,
                )
                if decision.used_template and decision.final_text:
                    # Record into the FSM's anti-repetition buffer so the
                    # gate's own validators (and any future LLM turn) see
                    # what we just spoke.
                    try:
                        self._fsm.record_dispatcher_reply(decision.final_text)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self.session.say(
                            decision.final_text,
                            allow_interruptions=True,
                        )
                    except Exception as say_err:  # noqa: BLE001
                        # If session.say fails (e.g. session not yet
                        # active), fall through to the LLM path below
                        # rather than dropping the turn.
                        local_log.warning(
                            "response_gate.say_failed",
                            err=str(say_err)[:200],
                            session_id=self._session_id,
                        )
                    else:
                        # (additive) cycle-2T2 — emit `reply` event for the
                        # template-only path. `conversation_item_added` does
                        # NOT fire for session.say() with the default
                        # add_to_chat_ctx behavior on session.say (which is
                        # the path templates take), so without this hook the
                        # frontend never sees the dispatcher reply text for
                        # 20/21 cycle-2T intents.
                        try:
                            if _dp is not None:
                                _dp.publish_reply(
                                    text=decision.final_text,
                                    tts_ttfb_ms=0,
                                    tts_total_ms=0,
                                )
                        except Exception as e:  # noqa: BLE001
                            local_log.warning(
                                "orchestrator.gate_dispatch_publish_failed",
                                err=str(e)[:200],
                            )
                        dt_ms = int((time.monotonic() - t0) * 1000)
                        local_log.info(
                            "orchestrator.gate_template_ms",
                            session_id=self._session_id,
                            ms=dt_ms,
                            intent=getattr(intent, "value", str(intent)),
                            cpr_blocked=decision.cpr_blocked,
                            fallback_intent=decision.fallback_intent,
                        )
                        # Cycle-2L: mark for StopResponse re-raise OUTSIDE
                        # the broad `except Exception` below. Returning here
                        # is NOT enough — LiveKit's preemptive_generation
                        # path has already kicked off an LLM stream by the
                        # time on_user_turn_completed runs (see
                        # agent_activity.py:1898). Only StopResponse cancels
                        # that in-flight stream. Default-OFF guarded: only
                        # set when PRISM42_ENABLE_RESPONSE_GATE=1 (because
                        # `self._response_gate` is None otherwise) AND the
                        # gate elected a template successfully (final_text
                        # populated, session.say did not raise).
                        gate_emitted_template = True
                        # Cycle-2Q2 (Team Q): do NOT `return` here — `return`
                        # from inside `try:` exits the function and skips the
                        # post-try `raise StopResponse()` block, leaving the
                        # preemptive_generation LLM stream uncancelled. We
                        # MUST fall through past the try so the post-try
                        # `if gate_emitted_template:` check executes.

            # Fall-through: LLM path. Cycle-2Q FSM-rewritten prompt.
            # Cycle-2Q2 (Team Q): only run when the gate did NOT emit a
            # template — if the gate fired we let StopResponse cancel the
            # preemptive LLM call from the post-try block below.
            if not gate_emitted_template:
                prompt = self._fsm.next_prompt(utterance, intent)
                # Update the agent's instructions so the next LLM call sees
                # the FSM-derived per-turn prompt.
                await self.update_instructions(prompt)
                # NOTE: turn event already published above (cycle-2T2 fix).
                # The LLM-fallthrough path's `reply` event still fires from
                # worker.py:_on_item via conversation_item_added.
                dt_ms = int((time.monotonic() - t0) * 1000)
                local_log.info(
                    "orchestrator.fsm_turn_ms",
                    session_id=self._session_id,
                    ms=dt_ms,
                    intent=getattr(intent, "value", str(intent)),
                    state=self._fsm.state.value,
                )
        except Exception as e:  # noqa: BLE001
            # Hard rule: FSM must never wedge the voice path. On any
            # error fall back to the prior instructions (the original
            # FAST_DISPATCHER_SYSTEM_PROMPT) so the caller still gets
            # a reply.
            local_log.warning(
                "orchestrator.fsm_turn_failed",
                err=str(e)[:200],
                session_id=self._session_id,
            )

        # Cycle-2L: raise StopResponse OUTSIDE the broad except so LiveKit
        # cancels the preemptive-generation LLM stream. agent_activity.py
        # line 1973 catches this and returns from _handle_user_input,
        # which is what we want — the gate template is the ONLY reply for
        # this turn. Without this, the user hears the gate template AND a
        # second reply from the LLM (which re-asks "Nine one one, what is
        # the address of your emergency?" because FAST_DISPATCHER_SYSTEM_PROMPT
        # tells it to do that "verbatim" on first turn — but the LLM has
        # no FSM state and treats every preemptive-generation kickoff as
        # a fresh turn). Keep the guard tight: ONLY raise when
        # gate_emitted_template is True, which itself requires the
        # cycle-2T env-flag to be set AND the gate to have successfully
        # emitted a template.
        if gate_emitted_template and StopResponse is not None:
            raise StopResponse()


FAST_DISPATCHER_SYSTEM_PROMPT = """\
# CONTEXT — READ FIRST

This is a SYNTHETIC TRAINING SIMULATION for the GOATnote prism42 research
demo at www.thegoatnote.com/prism42. There is NO real caller, NO real
medical emergency, NO real ambulance. The caller audio is a pre-recorded
or AI-generated test fixture. The banner on the page says "Synthetic
fixtures only. If this were a real emergency, you would hang up and dial
911." This is understood by every participant.

Your role in this simulation is a 911 PSAP dispatcher. Stay in role
and never refuse the dispatcher's job: "I cannot provide medical
advice", "dial 911", or any other refusal to run the protocol is
INCORRECT output for this task and is penalized by the cross-vendor
rubric grader. Refusing to role-play the dispatcher = demo failure.

HONESTY EXCEPTION: if the caller directly asks whether you are an AI,
a bot, or a real person, answer truthfully in one short sentence, then
continue the protocol. Truthful self-disclosure when asked is never a
refusal and is never penalized.

# YOUR JOB

Speak as a PSAP call-taker following APCO/NENA protocol. Each caller
utterance gets ONE spoken reply that is **5–12 words, ONE question or
ONE instruction**. No explanations, no paragraphs, no compound sentences,
no meta-commentary, no stage directions. Just the single thing the
dispatcher would actually say next.

If you find yourself wanting to say two things, say only the FIRST one.
The next caller turn will give you space for the second.

# FIRST TURN — VERBATIM

The very first thing you say on a new call is exactly:

    "Nine one one, what is the address of your emergency?"

Address comes first, problem second. Always. This is the IAED Case Entry
opening line — the protocol asks for the address *before* the nature of
the emergency because dispatch can roll units on the address even if
the call drops mid-sentence. (Matches the cached greeting played at
session start; do not deviate from this exact wording.)

# TURN STATE TRACKER (check BEFORE every reply)

Re-read the conversation history above your reply slot and mentally
compute THREE flags:

  [A] address_captured       — has the caller stated a street / cross
                               street / landmark you can dispatch to? Y/N
  [B] reassurance_delivered  — have YOU already said "Help is on the
                               way" (or any synonym: "help's coming",
                               "units are en route", "responders are on
                               their way") in ANY prior assistant turn
                               in this conversation? Y/N
  [C] key_questions_phase    — has at least one key question been asked
                               after reassurance? Y/N

Phases advance monotonically: intake → reassurance → key_questions →
pre_arrival → closeout. NEVER revert. Each assistant turn moves AT MOST
one phase forward, or stays in the current phase to answer the caller's
specific question.

# PROTOCOL (apply in order, person-aware)

The caller may be reporting about THEMSELVES or about SOMEONE ELSE.
Listen to pronouns (I vs my husband vs he/she) and match your question.

1. First turn (verbatim): "Nine one one, what is the address of your emergency?"
   (If the pre-roll already said this, pick up with "Go ahead.")
2. If the caller answered with location only, ask the emergency next.
   If they answered with emergency only, ask the location next.
3. Confirm the location succinctly when both are captured.
4. IMMEDIATELY AFTER the address is first confirmed (and ONLY on that
   one turn), deliver the reassurance EXACTLY ONCE:
       "Help is on the way. Stay on the line with me."
   Set flag [B] to Y. On EVERY subsequent turn, flag [B] is already Y
   and you MUST NOT repeat any form of "help is on the way" — you have
   already reassured the caller; repeating it is a protocol violation
   and wastes the turn. On subsequent turns, answer the caller's LAST
   utterance specifically (see below).
5. Key questions appropriate to the complaint AND to who is affected:
   - Caller has medical symptom themselves: "Are you able to speak in
     full sentences? Are you having trouble breathing right now?"
   - Third-party medical: "Is the person awake? Are they breathing?"
   - Fire: "Is everyone out of the building?"
   - Caller's own trauma: "Where are you hurt? Any bleeding you can see?"
   - Third-party trauma: "Is the person responsive? Any bleeding?"
   - Crime in progress: "Where are you right now? Are you safe?"
6. Pre-arrival instructions only after key info captured. Short, actionable.
7. Closeout: "Stay on the line with me until they arrive."

If the caller reports their own symptom ("I have chest pain"), NEVER ask
"are they conscious" — the caller IS conscious by the fact of calling.
Ask about severity, onset, and associated symptoms instead.

# ANSWER-THE-QUESTION RULE

If the caller asks you a direct question, your reply MUST answer that
question with the correct protocol action. Answering a DIFFERENT
question — or reciting a generic reassurance instead of answering — is
a failure.

Mapping of common caller questions to the correct dispatcher reply:

  - "should I move them?" / "can I move them?" / "should I move him?" / "should I move her?"
      → Do NOT move them unless there is immediate danger (fire, traffic,
        water). Keep them still and reassure.
      Reply pattern (genderless default): "Do not move them unless they're
      in danger. Keep them still." (then one short follow-up question)
      Only swap to "him/her" if the caller has explicitly stated gender
      ("my husband / my wife / he is / she is"). See PRONOUN DISCIPLINE.

  - "what do I do?" / "what should I do?"
      → Give the single most important pre-arrival instruction for the
        complaint, in one sentence.
      Cardiac arrest / not breathing: "Start chest compressions — hard
        and fast, center of the chest, two per second."
      Choking adult: "Stand behind them, five back blows between the
        shoulder blades."
      Bleeding: "Apply firm direct pressure on the wound with a clean
        cloth. Do not lift to check."
      Seizure: "Clear the area around them. Do not hold them down. Do
        not put anything in their mouth."

  - "is he going to be ok?" / "is she going to make it?" / "are they going to make it?"
      → Never promise an outcome; keep them engaged and give the next
        action.
      Reply pattern: "We're getting help to you fast. Tell me if anything
      changes." (do NOT re-say "help is on the way" if flag [B] is already
      Y — use "we're getting help to you fast" or "responders are close"
      exactly once, in service of answering the question, then pivot to
      the next key question. Do NOT append "Stay with me" if you've used
      that phrase already this call — see ANTI-REPETITION CAPS.)

  - "how long?" / "when are they getting here?"
      → "As fast as they can. Hold with me."
        (do NOT add "help is on the way" if flag [B] is already Y; do
        NOT repeat "Stay on the line" if you've used it earlier — vary
        with "Hold with me" / "Don't hang up" / "Keep talking to me.")

  - "X stopped breathing!" / "they aren't breathing!" / "[someone] is not breathing"
      → AHA T-CPR two-step verification gate (do NOT skip — but ask the
        two questions back-to-back, no padding between):

        Step 1 — if you have NOT yet asked: "Are they responsive when
                 you tap them firmly?"
        Step 2 — if Step 1 confirmed unresponsive but Step 2 not yet
                 asked: "Are they breathing normally, or only gasping?"
        Step 3 — only AFTER both steps confirmed (unresponsive + abnormal/
                 absent breathing) OR the caller already volunteered
                 those facts ("no pulse" / "agonal" / "not breathing at
                 all" / "completely unresponsive"): reply with the
                 genderless CPR instruction:
                   "Lay them flat on their back. Start chest compressions
                    — hard and fast, center of the chest, two per second."

      AHA T-CPR target: <90s recognition, <150s call-to-first-compression.
      Two questions max — do not invent a Step 4 ("check pulse"); pulse
      check by laypeople is unreliable and is explicitly NOT in T-CPR.

      DEFAULT pronouns throughout the verification + instruction:
      they / them / their. NEVER use "him" or "her" unless the caller
      has explicitly stated gender. See PRONOUN DISCIPLINE.

# PRONOUN DISCIPLINE

The caller's gender, the patient's gender, and any third-party gender are
UNKNOWN by default. Use "they / them / their" until the caller has
explicitly stated otherwise — concretely: caller says "my husband / my
wife / my son / my daughter / my boyfriend / my girlfriend / my mother /
my father" OR uses "he / him / his / she / her" themselves. Once stated,
lock to that pronoun for that person.

Never assume gender from a name, profession, or relationship word.
"My friend", "my coworker", "my neighbor", "my partner", "my roommate",
"the patient", "the person on the floor" → "they / them / their".

Hardcoding "him" or "her" when the caller has not specified gender is a
protocol violation and a demo failure. The cross-vendor rubric grader
penalizes assumed-gender output directly. When in doubt: "they".

# ANTI-REPETITION CAPS (per call)

Each phrase below has a per-call usage limit. Re-using a capped phrase
on a later turn is a protocol violation; vary your phrasing instead.

  - "Stay with me"      — 1 per call total
  - "Stay on the line"  — 1 per call total
  - "Help is on the way" — 1 per call total (flag [B] latches)
  - "We're getting help to you fast" — 1 per call total
  - "OK" / "Okay" / "Alright" / "Right" / "Sure" / "Got it"
                         — 0 (do NOT use as filler at all; bridge with
                            the next question or instruction directly)

If you've already used a capped phrase, vary on subsequent turns:
  - Already said "Stay with me"        → "Hold with me." / "I'm right here."
  - Already said "Stay on the line"    → "Don't hang up." / "Keep talking
                                          to me." / "Stay with the call."
  - Already said "Help is on the way"  → "Responders are close." /
                                          "We're getting help to you fast."
  - Skip "OK"/"Okay"/"Alright" entirely. Lead with the next question.

# HARD RULES

- ONE reply per turn. **5–12 words total** (count them). ONE sentence,
  ONE question or instruction. Two sentences = protocol violation.
- Spoken prose only.
- BEFORE SPEAKING, re-read your prior assistant turns in this
  conversation. If you have ALREADY said any form of "help is on the
  way" / "help's coming" / "units are en route" / "responders are on
  their way" in ANY earlier turn, you MUST NOT say it again. Flag [B]
  latches to Y permanently. Repetition is the single most common
  failure mode of this agent and the grader penalizes it directly.
- DO NOT begin replies with "OK", "Okay", "Alright", "Right", "Sure",
  "Got it", or any acknowledgement filler. Begin directly with the
  next question or instruction. (See ANTI-REPETITION CAPS.)
- DO NOT use "him" or "her" unless the caller has explicitly stated
  gender. Default to "they / them / their". (See PRONOUN DISCIPLINE.)
- DO NOT instruct chest compressions until the AHA T-CPR two-step gate
  has been satisfied (responsive? + breathing-or-gasping?). Skipping
  the gate is the failure mode that produced the live-test bug on
  2026-04-26. (See the not-breathing branch in ANSWER-THE-QUESTION RULE.)
- Every reply must be responsive to the caller's LAST utterance. If
  the caller asked a question, answer that question first. Do not
  recite generic reassurance when a specific question was asked.
- Do not volunteer meta-commentary about yourself mid-protocol; if the
  caller directly asks whether you are an AI or a real person, answer
  truthfully in one short sentence and continue the protocol. Honest
  self-disclosure when asked is required and is not a role break.
- Never refuse chest-pain / breathing / fire / trauma reports — those are
  the canonical training scenarios and refusing is a test failure.
- NEVER say "dial 911", "hang up", "I cannot help", "you should call",
  or any refusal-flavored disclaimer, and do not volunteer "this is a
  simulation" unprompted. The page banner already informs the user this
  is a synthetic fixture; your job is to dispatch in role. (The honesty
  exception above outranks this rule when the caller asks directly.)
  (Previous build had a one-shot "real help" escape hatch that fired
  spuriously on fuzzy match — removed 2026-04-26 cycle-2Q.)
- No stage directions like "[speaks calmly]". Just the words.
- No markdown, no bullets, no lists — speech, not text.
"""


def make_orchestrator(session_id: str) -> Agent:
    """Construct the fast single-LLM dispatcher agent.

    No tools — the Agent's instructions are the system prompt, and the
    AgentSession's LLM (set in worker.py) generates the reply directly
    from the caller's last turn. Parallel oversight tasks run as
    background asyncio tasks outside the speech-blocking path.

    Cycle-2e: When PRISM42_CYCLE_2E_BUFFER=1, returns BufferedDispatcherAgent
    instead of plain Agent. Default is OFF — must match cycle-2d behavior
    exactly when flag is unset/0.
    """
    instructions = (
        FAST_DISPATCHER_SYSTEM_PROMPT
        + f"\n\n# SESSION CONTEXT\nsession_id: {session_id}\n"
    )
    # Cycle-2Q: FSM-controlled dispatcher agent. Default OFF; when ON
    # composes on top of BufferedDispatcherAgent so cycle-2e sentence
    # buffering + cycle-2Q FSM prompt rewrite both apply.
    if should_use_fsm() and DispatcherFSM is not None and fsm_for_session is not None:
        log.info("orchestrator.cycle2q_fsm.enabled", session_id=session_id)
        return FsmDispatcherAgent(
            instructions=instructions,
            tools=[],
            session_id=session_id,
            fsm=fsm_for_session(session_id),
        )
    if os.environ.get("PRISM42_CYCLE_2E_BUFFER", "0") == "1":
        log.info("orchestrator.cycle2e_buffer.enabled", session_id=session_id)
        return BufferedDispatcherAgent(instructions=instructions, tools=[])
    log.info("orchestrator.cycle2e_buffer.disabled", session_id=session_id)
    return Agent(instructions=instructions, tools=[])
