"""claude_brain — Anthropic Claude as a parallel/secondary brain layer.

SKELETON ONLY. Lives under findings/voice/cycle2B_brain_layer/team-b/skeleton/.
NOT wired into agents/livekit/. Intended as a cycle-2B research artifact —
review, cost-validate, then move to agents/livekit/claude_brain.py in a
separate ship.

Patterns implemented (per pattern-catalog.md):
  - Pattern 2 (Fallback). Sync, hot-path bounded, 500ms timeout. Fired only
    when the existing FSM/response-gate validators reject Nemotron output.
    Drives `regenerate(...)`.
  - Pattern 6 (Critic). Async, off-hot-path. 100%-default sample rate.
    Drives `score(...)`.

Default OFF on both flags (PRISM42_ENABLE_CLAUDE_BRAIN=0,
PRISM42_ENABLE_CLAUDE_CRITIC=0). Either flag alone activates only its
branch. Neither flag affects existing response_gate template path.

Per CLAUDE.md §8 (model contract):
  - Model id `claude-opus-4-7` for the critic.
  - Model id `claude-sonnet-4-6` for the hot-path fallback (Opus 4.7 TTFT
    is incompatible with the 500ms hot-path budget).
  - Never set `temperature`, `top_p`, `top_k`, or `budget_tokens` on
    `messages.create(...)` — Opus 4.7 returns 400.
  - `extra_body` is NOT a bypass for those kwargs.
  - Thinking OFF by default (we omit the `thinking` field entirely).
  - No `callable_agents` (silently stripped on this workspace).

Per CLAUDE.md §0 (hackathon mode):
  - Voice path latency p95 < 1.5s is sacrosanct. The hot-path fallback's
    500ms budget is an absolute ceiling, not a target.
  - On any failure (timeout, 5xx, 429, refusal regex match, missing key),
    the caller must hear the original Nemotron output. The fallback never
    silences the worker.

Pricing reference (fetched 2026-04-26 from
https://platform.claude.com/docs/en/about-claude/pricing):

  Opus 4.7   input $5/MTok   output $25/MTok   cache read $0.50/MTok
  Sonnet 4.6 input $3/MTok   output $15/MTok   cache read $0.30/MTok

Telemetry: every call emits structlog events with the canonical names
declared at module bottom (`EVENT_*`). Token counts are accumulated into
a process-global `_TOKEN_USAGE` dict and exposed via
`get_token_usage_snapshot()` for the dispatcher_publisher to surface in
the dashboard.
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
# Env-flag accessors. Every flag default-OFF. Single source of truth.
# ---------------------------------------------------------------------


def should_use_claude_brain() -> bool:
    """Hot-path Pattern 2 (Fallback). Default OFF."""
    return os.environ.get("PRISM42_ENABLE_CLAUDE_BRAIN", "0") == "1"


def should_use_claude_critic() -> bool:
    """Off-path Pattern 6 (Critic). Default OFF."""
    return os.environ.get("PRISM42_ENABLE_CLAUDE_CRITIC", "0") == "1"


def _brain_timeout_ms() -> int:
    """Hot-path hard ceiling. Default 500ms — do not raise without a
    coordinated update to CLAUDE.md §0 latency budget."""
    return int(os.environ.get("PRISM42_CLAUDE_BRAIN_TIMEOUT_MS", "500"))


def _brain_model() -> str:
    """Hot-path model. Sonnet 4.6 is the only model with a published TTFT
    that fits under 500ms. Opus 4.7 measures 3-7s on short prompts; reject
    explicitly to prevent footguns (operator overriding to opus on hot
    path destroys the latency budget)."""
    m = os.environ.get("PRISM42_CLAUDE_BRAIN_MODEL", "claude-sonnet-4-6")
    if m.startswith("claude-opus"):
        log.warning(
            "claude_brain.opus_on_hot_path_rejected",
            model=m,
            fallback="claude-sonnet-4-6",
        )
        return "claude-sonnet-4-6"
    return m


def _critic_model() -> str:
    """Off-path model. Opus 4.7 default — its instruction-following on
    JSON rubrics is materially better than Sonnet 4.6's. The cost delta
    (Opus $5/$25 vs Sonnet $3/$15) is acceptable for a 100-tok-out
    critic."""
    return os.environ.get("PRISM42_CLAUDE_CRITIC_MODEL", "claude-opus-4-7")


def _critic_sample_rate() -> float:
    """Off-path sample rate. Default 1.0 (every turn). Drop to e.g. 0.1
    to cut cost 10x in beta-test surge."""
    try:
        rate = float(os.environ.get("PRISM42_CLAUDE_CRITIC_SAMPLE_RATE", "1.0"))
    except ValueError:
        rate = 1.0
    return max(0.0, min(1.0, rate))


def _daily_token_cap() -> int:
    return int(os.environ.get("PRISM42_CLAUDE_BRAIN_DAILY_TOKEN_CAP", "5000000"))


def _session_token_cap() -> int:
    return int(os.environ.get("PRISM42_CLAUDE_BRAIN_PER_SESSION_TOKEN_CAP", "100000"))


def _inflight_max() -> int:
    return int(os.environ.get("PRISM42_CLAUDE_BRAIN_INFLIGHT_MAX", "8"))


# ---------------------------------------------------------------------
# Result types.
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class BrainResult:
    """Outcome of a hot-path fallback call.

    `final_text` is the rewrite to ship to TTS — None on any failure
    (the orchestrator must then ship the original Nemotron output).

    `token_usage` is `{"input_tokens": int, "output_tokens": int}` or
    None on hard failure.

    `failure_mode` is one of:
      "" (success), "timeout", "api_5xx", "api_429", "refusal_regex",
      "missing_key", "budget_exhausted", "concurrency_full",
      "validator_rejected_rewrite", "exception".
    """

    final_text: str | None
    token_usage: dict[str, int] | None
    failure_mode: str
    elapsed_ms: int
    model: str


@dataclass(frozen=True)
class CriticScore:
    """Outcome of an off-path critic call.

    `rubric` is the 5-bool + confidence dict per recommendation.md:
      repeats_prior_phrase, gendered_without_commit, ignored_caller_question,
      cpr_unsafe, out_of_role, confidence (0..1)

    Critic never fails the voice path — on any error returns
    rubric={} and failure_mode set."""

    intent: str
    rubric: dict[str, Any]
    token_usage: dict[str, int] | None
    failure_mode: str
    elapsed_ms: int
    model: str


# ---------------------------------------------------------------------
# Refusal-regex — Anthropic medical refusal patterns to drop.
# Cycle-2B finding: Sonnet 4.6 refusal rate ~0.18% on this exact role,
# Opus 4.7 ~0.28% (KB 08 §7). At 0.18% you expect 1-2 refusals per 1k
# turns. Drop them and ship the Nemotron output instead — the response_gate
# templates already cover the "what should the dispatcher say" corpus.
# ---------------------------------------------------------------------

_REFUSAL_RE = re.compile(
    r"(I am an AI|I'm an AI|as a (?:large )?language model|"
    r"I cannot (?:provide|offer)|dial 9-?1-?1|"
    r"this is a simulation|real emergency)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# Token-usage accumulator. Process-global. Reset at UTC midnight by
# get_token_usage_snapshot(). Bounded by daily/session caps.
# ---------------------------------------------------------------------


@dataclass
class _TokenUsage:
    day: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    daily_input: int = 0
    daily_output: int = 0
    daily_calls: int = 0
    by_session: dict[str, int] = field(default_factory=dict)


_TOKEN_USAGE = _TokenUsage()
_TOKEN_LOCK = asyncio.Lock()


async def _record_usage(
    session_id: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Bump the global token counters under lock. Roll the day on
    UTC-midnight. Caller is the only place this should be called from."""
    async with _TOKEN_LOCK:
        today = datetime.now(timezone.utc).date().isoformat()
        if _TOKEN_USAGE.day != today:
            _TOKEN_USAGE.day = today
            _TOKEN_USAGE.daily_input = 0
            _TOKEN_USAGE.daily_output = 0
            _TOKEN_USAGE.daily_calls = 0
            _TOKEN_USAGE.by_session.clear()
        _TOKEN_USAGE.daily_input += input_tokens
        _TOKEN_USAGE.daily_output += output_tokens
        _TOKEN_USAGE.daily_calls += 1
        _TOKEN_USAGE.by_session[session_id] = (
            _TOKEN_USAGE.by_session.get(session_id, 0) + input_tokens + output_tokens
        )


async def _budget_exhausted(session_id: str) -> str:
    """Return failure_mode if any cap exceeded, else empty string."""
    async with _TOKEN_LOCK:
        if (_TOKEN_USAGE.daily_input + _TOKEN_USAGE.daily_output) >= _daily_token_cap():
            return "budget_exhausted"
        if _TOKEN_USAGE.by_session.get(session_id, 0) >= _session_token_cap():
            return "budget_exhausted"
    return ""


def get_token_usage_snapshot() -> dict[str, Any]:
    """Synchronous read for dispatch_publisher / dashboard. Not under
    lock — racy but the magnitudes don't need atomicity for display."""
    return asdict(_TOKEN_USAGE)


# ---------------------------------------------------------------------
# Concurrency cap. Bounded asyncio semaphore — protects against a Claude
# latency spike spawning unbounded tasks.
# ---------------------------------------------------------------------

_INFLIGHT_SEM: asyncio.Semaphore | None = None


def _inflight() -> asyncio.Semaphore:
    global _INFLIGHT_SEM
    if _INFLIGHT_SEM is None:
        _INFLIGHT_SEM = asyncio.Semaphore(_inflight_max())
    return _INFLIGHT_SEM


# ---------------------------------------------------------------------
# Anthropic client — lazy singleton. Picks up ANTHROPIC_API_KEY from env.
# Lazy import: do NOT import `anthropic` at module load time, so the
# default-OFF path stays SDK-free per CLAUDE.md §5 SDK-containment rule.
# ---------------------------------------------------------------------

_CLIENT: Any = None


def _client() -> Any:
    """Return a singleton AsyncAnthropic. Lazy-imports the SDK so the
    default-OFF path never imports anthropic — this matches the existing
    pattern in worker.py:546."""
    global _CLIENT
    if _CLIENT is None:
        # Import inside function so default-OFF callers don't pull in
        # the SDK. Mirrors specialists.py's `_opus_client()` pattern.
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        _CLIENT = AsyncAnthropic()
    return _CLIENT


def _has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------
# Hot-path Pattern 2 — Fallback regenerate.
# ---------------------------------------------------------------------


_REGEN_SYSTEM_PROMPT = """\
You are a 911 PSAP dispatcher. Re-render the dispatcher's reply so it
satisfies these rules:

  - 5 to 12 words total.
  - Exactly ONE sentence (one terminator: . ! or ?).
  - No gendered pronouns (he/him/his/she/her/hers) unless the caller has
    explicitly committed gender. If the rejected reply contains a banned
    pronoun, replace with they/them/their.
  - No phrase repeats from the prior dispatcher turn (provided below).
  - No filler at start (no "OK", "Okay", "Alright", "Right", "Sure",
    "Got it"). Lead with the next question or instruction.
  - Stay in role. Never say "I am an AI", "dial 911", "I cannot", or any
    out-of-character disclaimer.

Respond with ONLY the corrected dispatcher utterance. No preamble, no
explanation, no JSON wrapping.
"""


async def regenerate(
    *,
    session_id: str,
    caller_text: str,
    rejected_reply: str,
    prior_dispatcher_reply: str,
    intent: str,
    pronoun_committed: bool,
) -> BrainResult:
    """Hot-path fallback. Returns a BrainResult; final_text=None on any
    failure. Hard 500ms timeout. NEVER raises into the caller."""
    t0 = time.monotonic()
    model = _brain_model()

    # Cheap-fail-fast guards — order matters.
    if not should_use_claude_brain():
        return BrainResult(None, None, "", 0, model)
    if not _has_api_key():
        log.warning("claude_brain.missing_api_key")
        return BrainResult(None, None, "missing_key", 0, model)

    fail = await _budget_exhausted(session_id)
    if fail:
        log.warning(
            "claude_brain.budget_exhausted",
            session_id=session_id,
            usage=get_token_usage_snapshot(),
        )
        return BrainResult(None, None, fail, 0, model)

    sem = _inflight()
    if sem.locked() and sem._value == 0:  # type: ignore[attr-defined]  # noqa: SLF001
        log.warning("claude_brain.concurrency_full", session_id=session_id)
        return BrainResult(None, None, "concurrency_full", 0, model)

    user_msg = json.dumps(
        {
            "caller_text": caller_text,
            "rejected_reply": rejected_reply,
            "prior_dispatcher_reply": prior_dispatcher_reply,
            "intent": intent,
            "pronoun_committed": pronoun_committed,
        }
    )

    timeout_ms = _brain_timeout_ms()

    async def _do_call() -> tuple[str | None, dict[str, int] | None, str]:
        async with sem:
            try:
                # NOTE: NO temperature/top_p/top_k/budget_tokens kwargs —
                # Opus 4.7 returns 400 on those (CLAUDE.md §8). Sonnet 4.6
                # accepts them but we keep the call shape identical to
                # the Opus-4.7 contract so future model swaps are noop.
                resp = await _client().messages.create(
                    model=model,
                    max_tokens=80,  # 5-12 words ≤ ~30 tokens; 80 is generous headroom
                    system=_REGEN_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
            except Exception as e:  # noqa: BLE001
                cls = type(e).__name__
                # Anthropic SDK raises rate_limit_error / api_status_error
                # — bucket those by the HTTP status if present.
                status = getattr(e, "status_code", None)
                if status == 429 or "rate_limit" in cls.lower():
                    return None, None, "api_429"
                if status and 500 <= int(status) < 600:
                    return None, None, "api_5xx"
                log.warning("claude_brain.exception", cls=cls, msg=str(e)[:200])
                return None, None, "exception"

            # Token-usage extraction. AsyncAnthropic's Message.usage is a
            # pydantic-ish object; dict() coerces.
            usage = {
                "input_tokens": int(getattr(resp.usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(resp.usage, "output_tokens", 0) or 0),
            }
            text = (resp.content[0].text if resp.content else "").strip()

            # Reject refusals — drop the rewrite, the worker will ship the
            # original Nemotron output.
            if _REFUSAL_RE.search(text):
                log.warning("claude_brain.refusal_regex", text=text[:200])
                return None, usage, "refusal_regex"

            # Lightweight word-cap clamp — must be 5-14 words (gate slack).
            words = [w for w in re.sub(r"[.,!?;:]", "", text).split() if w]
            if not (5 <= len(words) <= 14):
                log.warning(
                    "claude_brain.validator_rejected_rewrite",
                    words=len(words),
                    text=text[:200],
                )
                return None, usage, "validator_rejected_rewrite"

            return text, usage, ""

    try:
        text, usage, failure_mode = await asyncio.wait_for(
            _do_call(),
            timeout=timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.warning(
            "claude_brain.timeout",
            session_id=session_id,
            ms=elapsed_ms,
            timeout_ms=timeout_ms,
        )
        return BrainResult(None, None, "timeout", elapsed_ms, model)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if usage is not None:
        await _record_usage(
            session_id,
            usage["input_tokens"],
            usage["output_tokens"],
        )
    log.info(
        "claude_brain.regenerate",
        session_id=session_id,
        ms=elapsed_ms,
        model=model,
        failure_mode=failure_mode,
        used_text=bool(text),
    )
    return BrainResult(text, usage, failure_mode, elapsed_ms, model)


# ---------------------------------------------------------------------
# Off-path Pattern 6 — Critic score.
# ---------------------------------------------------------------------


_CRITIC_SYSTEM_PROMPT = """\
You are a quality auditor for a 911 PSAP dispatcher voice agent. Given:

  - the caller's last utterance
  - the dispatcher's reply
  - the prior dispatcher reply (for repeat detection)
  - the FSM intent that produced the reply

…return a JSON object with EXACTLY these fields and nothing else:

{
  "repeats_prior_phrase":  true|false,
  "gendered_without_commit": true|false,
  "ignored_caller_question": true|false,
  "cpr_unsafe":              true|false,
  "out_of_role":             true|false,
  "confidence":              0.0-1.0
}

Definitions:
  - repeats_prior_phrase: dispatcher reply repeats a >=4-word phrase from
    the prior dispatcher reply (verbatim or trivial paraphrase).
  - gendered_without_commit: dispatcher reply uses he/him/his/she/her/hers
    when the caller has not committed gender for that person.
  - ignored_caller_question: caller asked a direct question and the
    dispatcher reply did not answer it (recited generic reassurance
    instead).
  - cpr_unsafe: reply instructs chest compressions before the AHA T-CPR
    two-step gate has been satisfied (responsive? + breathing?).
  - out_of_role: reply contains "I am an AI", "dial 911", "I cannot",
    "this is a simulation", or any out-of-character disclaimer.

Output JSON ONLY. No commentary.
"""


async def score(
    *,
    session_id: str,
    caller_text: str,
    dispatcher_reply: str,
    prior_dispatcher_reply: str,
    intent: str,
) -> CriticScore:
    """Off-path async critic. Caller wraps in `asyncio.create_task(...)`.
    Returns a CriticScore — never raises into the caller."""
    t0 = time.monotonic()
    model = _critic_model()

    if not should_use_claude_critic():
        return CriticScore(intent, {}, None, "", 0, model)
    if not _has_api_key():
        return CriticScore(intent, {}, None, "missing_key", 0, model)

    # Sample-rate gate. Use os.urandom-derived float for the dice roll
    # so PRNG state isn't shared with anything reproducible.
    sample = _critic_sample_rate()
    if sample < 1.0:
        # Bytes -> 0..1 float.
        roll = int.from_bytes(os.urandom(8), "big") / (2**64)
        if roll > sample:
            return CriticScore(intent, {}, None, "", 0, model)

    fail = await _budget_exhausted(session_id)
    if fail:
        return CriticScore(intent, {}, None, fail, 0, model)

    sem = _inflight()

    user_msg = json.dumps(
        {
            "caller_text": caller_text,
            "dispatcher_reply": dispatcher_reply,
            "prior_dispatcher_reply": prior_dispatcher_reply,
            "intent": intent,
        }
    )

    async with sem:
        try:
            resp = await _client().messages.create(
                model=model,
                max_tokens=200,
                system=_CRITIC_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:  # noqa: BLE001
            cls = type(e).__name__
            status = getattr(e, "status_code", None)
            if status == 429:
                fm = "api_429"
            elif status and 500 <= int(status) < 600:
                fm = "api_5xx"
            else:
                fm = "exception"
            log.warning("claude_critic.exception", cls=cls, fm=fm, msg=str(e)[:200])
            return CriticScore(
                intent, {}, None, fm, int((time.monotonic() - t0) * 1000), model
            )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    usage = {
        "input_tokens": int(getattr(resp.usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(resp.usage, "output_tokens", 0) or 0),
    }
    await _record_usage(session_id, usage["input_tokens"], usage["output_tokens"])

    # Lenient JSON extraction — same pattern as specialists.py:247.
    raw = resp.content[0].text if resp.content else "{}"
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        log.warning("claude_critic.no_json", raw=raw[:200])
        return CriticScore(intent, {}, usage, "exception", elapsed_ms, model)
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        log.warning("claude_critic.json_parse_failed", raw=raw[:200])
        return CriticScore(intent, {}, usage, "exception", elapsed_ms, model)

    # Coerce / validate the rubric — only keep known fields.
    rubric = {
        "repeats_prior_phrase": bool(parsed.get("repeats_prior_phrase", False)),
        "gendered_without_commit": bool(parsed.get("gendered_without_commit", False)),
        "ignored_caller_question": bool(parsed.get("ignored_caller_question", False)),
        "cpr_unsafe": bool(parsed.get("cpr_unsafe", False)),
        "out_of_role": bool(parsed.get("out_of_role", False)),
        "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 0.0)))),
    }

    log.info(
        "claude_critic.score",
        session_id=session_id,
        ms=elapsed_ms,
        model=model,
        rubric=rubric,
    )
    return CriticScore(intent, rubric, usage, "", elapsed_ms, model)


# ---------------------------------------------------------------------
# Structlog event names — single source of truth for the dashboard.
# ---------------------------------------------------------------------

EVENT_REGENERATE = "claude_brain.regenerate"
EVENT_TIMEOUT = "claude_brain.timeout"
EVENT_REFUSAL = "claude_brain.refusal_regex"
EVENT_BUDGET = "claude_brain.budget_exhausted"
EVENT_CONCURRENCY = "claude_brain.concurrency_full"
EVENT_CRITIC_SCORE = "claude_critic.score"
EVENT_CRITIC_DROPPED = "claude_critic.dropped"
