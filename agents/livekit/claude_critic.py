"""claude_critic — Anthropic Opus 4.7 OFF-PATH critic for prism42.

Cycle-2BC, 2026-04-26. Pattern 6 (Critic) ONLY. Hot-path Pattern 2
(Fallback / regenerate) is explicitly DISABLED for this cycle per user
directive — see `regenerate()` stub at the bottom of this module.

What this module does
---------------------
Runs Opus 4.7 in parallel with the FSM/Nemotron path, mirroring the
existing safety-monitor / ohca-detector / intent-verifier triplet
(specialists.py:206-323). The critic READS FSM state, dispatcher reply,
caller utterance — and writes a structured JSON judgment to structlog.
It NEVER speaks (no TTS surface) and NEVER blocks (caller wraps it in
`asyncio.create_task(...)`).

What this module does NOT do
----------------------------
- Does NOT generate caller-facing text.
- Does NOT mutate FSM state.
- Does NOT run on the hot path; the 750ms timeout is intentionally
  longer than the 500ms hot-path budget because off-path can afford it.
- Does NOT use Sonnet 4.6 — this cycle uses Opus 4.7 only.
- Does NOT enable `regenerate()` (kept as a NotImplementedError stub
  to preserve the team-b skeleton's API surface for cycle-2C).

Default OFF
-----------
Behind `PRISM42_ENABLE_CLAUDE_CRITIC=1`. With the flag unset the call
returns immediately without importing the `anthropic` SDK and without
issuing a network request — the lazy-import pattern matches
specialists.py and worker.py.

Per CLAUDE.md §8 (model contract)
---------------------------------
- Model id `claude-opus-4-7`.
- Never set `temperature`, `top_p`, `top_k`, `budget_tokens` —
  Opus 4.7 returns 400 on any of those.
  Source: https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
  (fetched 2026-04-26; "Sampling parameters removed").
- Thinking OFF by default — we omit the `thinking` field entirely
  (Opus 4.7 default is `display: omitted`).
  Source: https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking
  (fetched 2026-04-26).
- `extra_body` is NOT a bypass for the rejected kwargs.

Per CLAUDE.md §0 (hackathon mode)
---------------------------------
- The voice path latency p95 < 1.5s is sacrosanct. The critic does not
  participate in that budget — it runs as a fire-and-forget task whose
  only output is a structlog event consumed by the dashboard.
- On any failure (timeout, 5xx, 429, refusal regex match, missing
  key), the caller is unaffected — the critic just doesn't emit a
  rubric for that turn.

Pricing reference (fetched 2026-04-26 from
https://platform.claude.com/docs/en/about-claude/pricing):

  Opus 4.7   input $5/MTok   output $25/MTok   cache read $0.50/MTok

At ~500 input + ~120 output tokens per call:
  100 calls = ~50k input + ~12k output = $0.25 + $0.30 = ~$0.55
  1k calls/day = ~$5.50/day at 100% sample rate.

Module structure
----------------
- `score(...)` — the off-path critic. Returns `CriticScore`. Never
  raises.
- `regenerate(...)` — STUB. Raises NotImplementedError. Hot-path
  use is disabled this cycle. Cycle-2C may re-enable.
- `should_use_claude_critic()` — env-flag accessor.
- `get_token_usage_snapshot()` — synchronous accumulator read for
  the dashboard / eval harness.
- `reset_token_usage()` — test/eval-only helper to reset the global
  accumulator.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()


# ---------------------------------------------------------------------
# Env-flag accessors. Default OFF.
# ---------------------------------------------------------------------


def should_use_claude_critic() -> bool:
    """Off-path Pattern 6 (Critic). Default OFF.

    Per user directive 2026-04-26: only `score()` is shipped this
    cycle. The hot-path `regenerate()` stub raises rather than running.
    """
    return os.environ.get("PRISM42_ENABLE_CLAUDE_CRITIC", "0") == "1"


def _critic_timeout_ms() -> int:
    """Off-path hard ceiling. Default 750ms — per user 2026-04-26.

    Skeleton's 500ms was a hot-path number; off-path can afford the
    longer budget so Opus 4.7's TTFT (3-7s on short prompts per
    KB 08 §7) doesn't immediately starve the rubric.
    """
    return int(os.environ.get("PRISM42_CLAUDE_CRITIC_TIMEOUT_MS", "750"))


def _critic_model() -> str:
    """Off-path model. Opus 4.7 by default — its instruction-following
    on JSON rubrics is materially better than Sonnet 4.6's. Cycle-2BC
    user directive: critic uses Opus 4.7 only; Sonnet not allowed."""
    return os.environ.get("PRISM42_CLAUDE_CRITIC_MODEL", "claude-opus-4-7")


def _critic_sample_rate() -> float:
    try:
        rate = float(os.environ.get("PRISM42_CLAUDE_CRITIC_SAMPLE_RATE", "1.0"))
    except ValueError:
        rate = 1.0
    return max(0.0, min(1.0, rate))


# ---------------------------------------------------------------------
# Result type.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class CriticScore:
    """Outcome of an off-path critic call.

    Fields
    ------
    suggested_correction:
        Concrete dispatcher reply that would have been better, or None
        if the FSM-emitted reply is acceptable. Critic's correction is
        ADVISORY ONLY — the caller never hears it.
    risk_flag:
        One of {"none", "low", "medium", "high"}. Magnitude of the
        deviation between FSM behavior and what the critic believes
        protocol demands.
    state_mismatch:
        True if the critic believes the FSM is in the wrong state /
        emitted a reply that contradicts latched facts.
    state_mismatch_reason:
        Free-form string (<=200 chars) explaining the mismatch when
        `state_mismatch=True`. Empty when state_mismatch=False.
    confidence:
        0.0-1.0 critic self-reported confidence in its judgment.
    intent:
        The FSM intent that was emitted on this turn — echoed back so
        downstream tooling can join critic output to FSM logs without
        re-querying.
    token_usage:
        `{"input_tokens": int, "output_tokens": int}` or None when the
        call short-circuited.
    failure_mode:
        "" (success), "timeout", "api_5xx", "api_429", "refusal_regex",
        "missing_key", "exception".
    elapsed_ms:
        Wall time of the critic call. Includes timeout (set to
        `_critic_timeout_ms()` on timeout).
    model:
        Model id that was used. Echoes `_critic_model()`.
    """

    suggested_correction: str | None
    risk_flag: str
    state_mismatch: bool
    state_mismatch_reason: str
    confidence: float
    intent: str
    token_usage: dict[str, int] | None
    failure_mode: str
    elapsed_ms: int
    model: str


# ---------------------------------------------------------------------
# Refusal-regex — Anthropic medical refusal patterns to drop.
#
# Mirrors the team-b skeleton's _REFUSAL_RE plus a couple extra phrases
# specifically called out by user directive 2026-04-26.
# ---------------------------------------------------------------------

_REFUSAL_RE = re.compile(
    r"(I am an AI|I'?m an AI|as a (?:large )?language model|"
    r"I cannot (?:provide|offer)|dial 9-?1-?1|"
    r"this is a simulation|real emergency)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# Refusal counter — bumped whenever the critic's response triggers
# the regex above. Exposed for the dashboard via
# `get_token_usage_snapshot()`.
# ---------------------------------------------------------------------


_REFUSAL_COUNT = 0


# ---------------------------------------------------------------------
# Token-usage accumulator. Process-global. Reset at UTC midnight by
# `_record_usage`. Bounded by daily/session caps if/when those are wired
# (this cycle does not enforce caps — eval harness has its own budget).
# ---------------------------------------------------------------------


@dataclass
class _TokenUsage:
    day: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    daily_input: int = 0
    daily_output: int = 0
    daily_calls: int = 0
    refusals: int = 0
    by_session: dict[str, int] = field(default_factory=dict)


_TOKEN_USAGE = _TokenUsage()
_TOKEN_LOCK = asyncio.Lock()


async def _record_usage(
    session_id: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Bump the global token counters under lock. Roll the day on
    UTC-midnight."""
    async with _TOKEN_LOCK:
        today = datetime.now(timezone.utc).date().isoformat()
        if _TOKEN_USAGE.day != today:
            _TOKEN_USAGE.day = today
            _TOKEN_USAGE.daily_input = 0
            _TOKEN_USAGE.daily_output = 0
            _TOKEN_USAGE.daily_calls = 0
            _TOKEN_USAGE.refusals = 0
            _TOKEN_USAGE.by_session.clear()
        _TOKEN_USAGE.daily_input += input_tokens
        _TOKEN_USAGE.daily_output += output_tokens
        _TOKEN_USAGE.daily_calls += 1
        _TOKEN_USAGE.by_session[session_id] = (
            _TOKEN_USAGE.by_session.get(session_id, 0) + input_tokens + output_tokens
        )


def get_token_usage_snapshot() -> dict[str, Any]:
    """Synchronous read for dashboards / eval harness. Not under lock —
    racy, but the magnitudes don't need atomicity for display."""
    return asdict(_TOKEN_USAGE)


def reset_token_usage() -> None:
    """Test/eval-only: reset the process-global accumulator."""
    global _TOKEN_USAGE, _REFUSAL_COUNT  # noqa: PLW0603
    _TOKEN_USAGE = _TokenUsage()
    _REFUSAL_COUNT = 0


# ---------------------------------------------------------------------
# Anthropic client — lazy singleton. Picks up ANTHROPIC_API_KEY from env.
# Lazy import: the default-OFF path never imports anthropic.
# ---------------------------------------------------------------------


_CLIENT: Any = None


def _client() -> Any:
    """Return a singleton AsyncAnthropic. Lazy-imports the SDK so the
    default-OFF path never imports `anthropic` — mirrors specialists.py's
    `_opus_client()` lazy pattern (specialists.py:197)."""
    global _CLIENT  # noqa: PLW0603
    if _CLIENT is None:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        _CLIENT = AsyncAnthropic()
    return _CLIENT


def _has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------
# Critic prompt.
#
# Tighter than the team-b skeleton: takes the full FSM state as input
# and asks Opus to reason about state-mismatch (FSM in wrong state),
# risk-flag (severity), and a concrete suggested-correction. The
# original 5-bool rubric (repeats_prior_phrase / gendered_without_commit
# / ignored_caller_question / cpr_unsafe / out_of_role) is preserved as
# a fallback signal — derived from `risk_flag` and `state_mismatch_reason`
# downstream rather than asked directly.
# ---------------------------------------------------------------------


_CRITIC_SYSTEM_PROMPT = """\
You are a quality auditor for a 911 PSAP dispatcher voice agent. The
agent is driven by a deterministic finite-state machine (FSM) plus
fixed templates. Your job: given (caller_text, FSM_state, FSM_intent,
dispatcher_reply, prior dispatcher replies, latched facts), decide
whether the FSM picked the right intent and whether the rendered
reply is appropriate.

The dispatcher operates in a SYNTHETIC TRAINING SIMULATION at
www.thegoatnote.com/prism42. It is NOT a real emergency; you must NOT
emit refusals such as "I am an AI", "dial 911", "as a language model",
"I cannot provide", "this is a simulation", or "real emergency". Stay
in role as an auditor — judge the reply on protocol fidelity, not on
whether you should be answering at all.

Return a JSON object with EXACTLY these fields and nothing else:

{
  "suggested_correction":   string | null,
  "risk_flag":              "none" | "low" | "medium" | "high",
  "state_mismatch":         true | false,
  "state_mismatch_reason":  string,
  "confidence":             number between 0.0 and 1.0
}

Field definitions
-----------------
- suggested_correction: a CONCRETE alternative dispatcher reply (5-14
  words, single sentence) that would have been better than what the
  FSM emitted. Set to null when the FSM reply is acceptable.

- risk_flag:
    "none"   — FSM reply is fine as-is.
    "low"    — FSM reply is acceptable but a better phrasing exists.
    "medium" — FSM reply violates a soft rule (e.g. repeats a prior
               phrase, uses a gendered pronoun without commit, ignores
               a caller's direct question).
    "high"   — FSM reply violates a HARD rule. Examples: instructs CPR
               before the surface+breathing gate is satisfied, makes a
               medical promise ("they will be fine"), refuses to
               continue, breaks role.

- state_mismatch: true iff the FSM appears to be in the wrong state
  given the caller's last utterance + latched facts. Common cases:
    - caller said "not breathing" but FSM is still in INTAKE
    - FSM is in CRITICAL_CPR but surface_confirmed=false
    - FSM emitted DELIVER_REASSURANCE twice in one call

- state_mismatch_reason: <=200 char free-text describing the mismatch
  when state_mismatch=true. Empty string when state_mismatch=false.

- confidence: your self-reported confidence in this judgment.

Output JSON ONLY. No commentary, no markdown fences.
"""


async def score(
    *,
    session_id: str,
    caller_text: str,
    dispatcher_reply: str,
    prior_dispatcher_replies: list[str],
    intent: str,
    fsm_state: str,
    latched_facts: dict[str, Any],
) -> CriticScore:
    """Off-path async critic. Caller wraps in `asyncio.create_task(...)`.

    Returns a CriticScore — never raises into the caller. On default-OFF
    or any failure, fields are empty/None and `failure_mode` is set.

    The 750ms timeout is enforced by `asyncio.wait_for`. On timeout the
    elapsed_ms in the returned score equals the timeout (not the partial
    network time), and `failure_mode == "timeout"`.
    """
    t0 = time.monotonic()
    model = _critic_model()
    timeout_ms = _critic_timeout_ms()

    # Cheap-fail-fast guards — order matters.
    if not should_use_claude_critic():
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=None,
            failure_mode="",
            elapsed_ms=0,
            model=model,
        )

    if not _has_api_key():
        log.warning("claude_critic.missing_api_key")
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=None,
            failure_mode="missing_key",
            elapsed_ms=0,
            model=model,
        )

    # Sample-rate gate. os.urandom-derived float so PRNG state isn't
    # shared with anything reproducible.
    sample = _critic_sample_rate()
    if sample < 1.0:
        roll = int.from_bytes(os.urandom(8), "big") / (2**64)
        if roll > sample:
            return CriticScore(
                suggested_correction=None,
                risk_flag="none",
                state_mismatch=False,
                state_mismatch_reason="",
                confidence=0.0,
                intent=intent,
                token_usage=None,
                failure_mode="",
                elapsed_ms=0,
                model=model,
            )

    user_msg = json.dumps(
        {
            "caller_text": caller_text,
            "fsm_state": fsm_state,
            "fsm_intent": intent,
            "dispatcher_reply": dispatcher_reply,
            "prior_dispatcher_replies": prior_dispatcher_replies[-3:],
            "latched_facts": latched_facts,
        }
    )

    async def _do_call() -> tuple[Any, str]:
        """Returns (resp, failure_mode). resp may be None on failure."""
        try:
            resp = await _client().messages.create(
                model=model,
                max_tokens=300,
                system=_CRITIC_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:  # noqa: BLE001
            cls = type(e).__name__
            status = getattr(e, "status_code", None)
            if status == 429 or "rate_limit" in cls.lower():
                return None, "api_429"
            if status and 500 <= int(status) < 600:
                return None, "api_5xx"
            log.warning("claude_critic.exception", cls=cls, msg=str(e)[:200])
            return None, "exception"
        return resp, ""

    try:
        resp, failure_mode = await asyncio.wait_for(
            _do_call(),
            timeout=timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.warning(
            "claude_critic.timeout",
            session_id=session_id,
            ms=elapsed_ms,
            timeout_ms=timeout_ms,
        )
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=None,
            failure_mode="timeout",
            elapsed_ms=timeout_ms,
            model=model,
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if failure_mode:
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=None,
            failure_mode=failure_mode,
            elapsed_ms=elapsed_ms,
            model=model,
        )

    usage = {
        "input_tokens": int(getattr(resp.usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(resp.usage, "output_tokens", 0) or 0),
    }
    await _record_usage(session_id, usage["input_tokens"], usage["output_tokens"])

    raw = resp.content[0].text if resp.content else "{}"

    # Refusal regex — drop responses that broke role.
    if _REFUSAL_RE.search(raw):
        global _REFUSAL_COUNT  # noqa: PLW0603
        _REFUSAL_COUNT += 1
        async with _TOKEN_LOCK:
            _TOKEN_USAGE.refusals += 1
        log.warning(
            "claude_critic.refused",
            count=_REFUSAL_COUNT,
            text=raw[:200],
        )
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=usage,
            failure_mode="refusal_regex",
            elapsed_ms=elapsed_ms,
            model=model,
        )

    # Lenient JSON extraction — same shape as specialists.py:247.
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        log.warning("claude_critic.no_json", raw=raw[:200])
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=usage,
            failure_mode="exception",
            elapsed_ms=elapsed_ms,
            model=model,
        )
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        log.warning("claude_critic.json_parse_failed", raw=raw[:200])
        return CriticScore(
            suggested_correction=None,
            risk_flag="none",
            state_mismatch=False,
            state_mismatch_reason="",
            confidence=0.0,
            intent=intent,
            token_usage=usage,
            failure_mode="exception",
            elapsed_ms=elapsed_ms,
            model=model,
        )

    # Coerce / validate the rubric.
    risk_flag = str(parsed.get("risk_flag", "none")).strip().lower()
    if risk_flag not in {"none", "low", "medium", "high"}:
        risk_flag = "none"

    sc = parsed.get("suggested_correction", None)
    if sc is not None and (not isinstance(sc, str) or not sc.strip()):
        sc = None
    elif isinstance(sc, str):
        sc = sc.strip()[:240]  # cap length to keep JSONL bounded

    state_mismatch = bool(parsed.get("state_mismatch", False))
    state_mismatch_reason = str(parsed.get("state_mismatch_reason", ""))[:200]
    if not state_mismatch:
        state_mismatch_reason = ""

    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (ValueError, TypeError):
        confidence = 0.0

    log.info(
        "claude_critic.score",
        session_id=session_id,
        ms=elapsed_ms,
        model=model,
        intent=intent,
        risk_flag=risk_flag,
        state_mismatch=state_mismatch,
        confidence=confidence,
    )

    return CriticScore(
        suggested_correction=sc,
        risk_flag=risk_flag,
        state_mismatch=state_mismatch,
        state_mismatch_reason=state_mismatch_reason,
        confidence=confidence,
        intent=intent,
        token_usage=usage,
        failure_mode="",
        elapsed_ms=elapsed_ms,
        model=model,
    )


# ---------------------------------------------------------------------
# Hot-path stub — DISABLED for cycle-2BC.
#
# The team-b skeleton (findings/voice/cycle2B_brain_layer/team-b/
# skeleton/claude_brain.py) implements `regenerate(...)` as a Pattern 2
# (Fallback) hot-path call to Sonnet 4.6. Per user directive 2026-04-26,
# only the off-path critic ships this cycle. The stub remains so any
# accidental wiring fails loudly rather than silently importing the SDK
# or issuing a network request.
# ---------------------------------------------------------------------


async def regenerate(
    *,
    session_id: str,
    caller_text: str,
    rejected_reply: str,
    prior_dispatcher_reply: str,
    intent: str,
    pronoun_committed: bool,
) -> Any:
    """DISABLED — hot-path use deferred to cycle-2C.

    Per user directive 2026-04-26: Claude is shipped as ASYNC CRITIC
    ONLY this cycle. The hot-path Pattern 2 fallback (regenerate) is
    not approved for this hackathon. Calling this raises so any
    accidental orchestrator wiring fails loud.
    """
    raise NotImplementedError(
        "claude_critic.regenerate is disabled for cycle-2BC. "
        "Use score(...) for off-path critique. Hot-path fallback "
        "deferred to cycle-2C per user directive 2026-04-26."
    )


# ---------------------------------------------------------------------
# Structlog event names — single source of truth for the dashboard.
# ---------------------------------------------------------------------

EVENT_CRITIC_SCORE = "claude_critic.score"
EVENT_CRITIC_TIMEOUT = "claude_critic.timeout"
EVENT_CRITIC_REFUSED = "claude_critic.refused"
EVENT_CRITIC_NO_JSON = "claude_critic.no_json"
EVENT_CRITIC_JSON_PARSE_FAILED = "claude_critic.json_parse_failed"
EVENT_CRITIC_EXCEPTION = "claude_critic.exception"
EVENT_CRITIC_MISSING_API_KEY = "claude_critic.missing_api_key"
