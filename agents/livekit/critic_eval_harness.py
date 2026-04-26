"""critic_eval_harness — 100-call shadow eval of Claude critic vs FSM.

Cycle-2BC, 2026-04-26. STANDALONE LOCAL-ONLY script. NOT wired into the
production runtime; not installed on the pod. Runs against:

  - the LIVE prism42 DispatcherFSM (agents/livekit/dispatcher_fsm.py),
  - the LIVE deterministic templates (agents/livekit/templates.py),
  - the LIVE Anthropic Opus 4.7 critic (agents/livekit/claude_critic.py)
    via `score(...)` — the off-path Pattern 6 path.

Every fixture caller utterance is fed into a fresh DispatcherFSM, the
FSM picks an intent, the dispatcher reply is rendered via templates,
and the Claude critic is invoked in parallel. Per-call results are
written to a JSONL artifact; aggregate metrics are written to a
human-readable markdown summary.

Double-gate (per CLAUDE.md §5)
------------------------------
The harness only issues live Anthropic calls when BOTH:

  1. `--commit` flag is on the CLI, AND
  2. `PRISM42_CRITIC_COMMIT=1` env var is set.

Without both, the harness runs in DRY-RUN: it executes the FSM path and
records the same per-call rows, but the Claude critic short-circuits
(default-OFF returns CriticScore with empty fields) so no API calls are
made. Useful for harness regression testing without spending budget.

Usage
-----
Dry-run (default):
  python3 critic_eval_harness.py \
      --fixtures agents/livekit/critic_fixtures.jsonl \
      --out-dir findings/voice/cycle2BC_critic_eval/team-b-critic/

Live (double-gated):
  PRISM42_CRITIC_COMMIT=1 PRISM42_ENABLE_CLAUDE_CRITIC=1 \
  python3 critic_eval_harness.py --commit \
      --fixtures agents/livekit/critic_fixtures.jsonl \
      --out-dir findings/voice/cycle2BC_critic_eval/team-b-critic/

Outputs
-------
- <out-dir>/critic-eval-<UTC-date>.jsonl: per-call rows (one line per
  caller utterance).
- <out-dir>/aggregate-metrics.md: human-readable summary.

Cite-on-touch
-------------
- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
  (fetched 2026-04-26).
- Opus 4.7 sampler kwargs rejected:
  https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
  (fetched 2026-04-26).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# agents/livekit/ is not on the default Python path; inject so the
# harness can run without `pip install -e`.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import claude_critic  # noqa: E402
from dispatcher_fsm import DispatcherFSM, Intent  # noqa: E402
from templates import render_template  # noqa: E402

# Pricing per Anthropic 2026-04-26: Opus 4.7 input $5/MTok, output $25/MTok.
OPUS_4_7_INPUT_PER_MTOK = 5.00
OPUS_4_7_OUTPUT_PER_MTOK = 25.00


# ---------------------------------------------------------------------
# Per-call row.
# ---------------------------------------------------------------------


@dataclass
class CallRow:
    """One caller utterance + its FSM/critic judgments. Serialized to JSONL."""

    fixture_id: str
    scenario: str
    turn_index: int  # 0-indexed within the call
    caller_utterance: str
    # FSM output
    fsm_state_before: str
    fsm_state_after: str
    fsm_intent: str
    fsm_reply: str | None  # None when no template (REPROMPT etc.)
    fsm_pronouns: str
    fsm_address_known: bool
    fsm_emergency_known: bool
    fsm_reassurance_done: bool
    fsm_surface_confirmed: bool
    fsm_breathing_assessed: bool
    fsm_is_cardiac_arrest: bool
    fsm_is_third_party: bool
    fsm_complaint: str
    # Critic output
    critic_suggested_correction: str | None
    critic_risk_flag: str
    critic_state_mismatch: bool
    critic_state_mismatch_reason: str
    critic_confidence: float
    critic_failure_mode: str
    critic_elapsed_ms: int
    critic_input_tokens: int
    critic_output_tokens: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# ---------------------------------------------------------------------
# Fixture loader.
# ---------------------------------------------------------------------


@dataclass
class Fixture:
    fixture_id: str
    scenario: str
    turns: list[str] = field(default_factory=list)


def load_fixtures(path: Path) -> list[Fixture]:
    """Load JSONL fixtures. Each line:
    {"id": "cf-001", "scenario": "cardiac",
     "turns": [{"caller": "twelve riverside drive"}, ...]}
    """
    out: list[Fixture] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            turns = [t["caller"] for t in obj.get("turns", [])]
            out.append(
                Fixture(
                    fixture_id=obj["id"],
                    scenario=obj.get("scenario", "unknown"),
                    turns=turns,
                )
            )
    return out


# ---------------------------------------------------------------------
# Per-fixture runner.
# ---------------------------------------------------------------------


def _state_snapshot(fsm: DispatcherFSM) -> dict[str, Any]:
    """Return the FSM's latched-fact view, used as the critic input.

    Mirrors the field set the FSM logs on every transition
    (dispatcher_fsm.py:734-753) including the life-safety telemetry
    (`surface_status`, `cpr_allowed`) added in cycle-2R3 B3-A.
    """
    surface_status = (
        "confirmed"
        if fsm.surface_confirmed
        else "negated"
        if getattr(fsm, "_reposition_emits", 0) > 0
        else "unknown"
    )
    cpr_allowed = bool(
        fsm.surface_confirmed and fsm.breathing_assessed and fsm.is_cardiac_arrest
    )
    return {
        "address_known": fsm.address_known,
        "emergency_known": fsm.emergency_known,
        "reassurance_done": fsm.reassurance_done,
        "surface_confirmed": fsm.surface_confirmed,
        "breathing_assessed": fsm.breathing_assessed,
        "is_cardiac_arrest": fsm.is_cardiac_arrest,
        "is_third_party": fsm.is_third_party,
        "complaint": fsm.complaint,
        "pronouns": fsm.pronouns,
        "verify_step": fsm.verify_step.value,
        "turns": fsm.turns,
        "surface_status": surface_status,
        "cpr_allowed": cpr_allowed,
        "reposition_emits": getattr(fsm, "_reposition_emits", 0),
    }


async def run_fixture(
    fixture: Fixture,
    *,
    session_id: str,
) -> list[CallRow]:
    """Run one fixture (one full call) end-to-end.

    Returns one CallRow per caller turn.
    """
    fsm = DispatcherFSM()
    rows: list[CallRow] = []
    prior_replies: list[str] = []

    for turn_idx, caller_utter in enumerate(fixture.turns):
        state_before = fsm.state.value
        intent: Intent = fsm.transition(caller_utter)
        state_after = fsm.state.value
        reply = render_template(intent.value, fsm.pronouns)
        if reply is not None:
            fsm.record_dispatcher_reply(reply)
            prior_replies.append(reply)

        # Critic call — async + bounded by its own 750ms timeout.
        critic_score = await claude_critic.score(
            session_id=session_id,
            caller_text=caller_utter,
            dispatcher_reply=reply or "",
            prior_dispatcher_replies=prior_replies[:-1],  # exclude current reply
            intent=intent.value,
            fsm_state=state_after,
            latched_facts=_state_snapshot(fsm),
        )

        usage = critic_score.token_usage or {"input_tokens": 0, "output_tokens": 0}
        rows.append(
            CallRow(
                fixture_id=fixture.fixture_id,
                scenario=fixture.scenario,
                turn_index=turn_idx,
                caller_utterance=caller_utter,
                fsm_state_before=state_before,
                fsm_state_after=state_after,
                fsm_intent=intent.value,
                fsm_reply=reply,
                fsm_pronouns=fsm.pronouns,
                fsm_address_known=fsm.address_known,
                fsm_emergency_known=fsm.emergency_known,
                fsm_reassurance_done=fsm.reassurance_done,
                fsm_surface_confirmed=fsm.surface_confirmed,
                fsm_breathing_assessed=fsm.breathing_assessed,
                fsm_is_cardiac_arrest=fsm.is_cardiac_arrest,
                fsm_is_third_party=fsm.is_third_party,
                fsm_complaint=fsm.complaint,
                critic_suggested_correction=critic_score.suggested_correction,
                critic_risk_flag=critic_score.risk_flag,
                critic_state_mismatch=critic_score.state_mismatch,
                critic_state_mismatch_reason=critic_score.state_mismatch_reason,
                critic_confidence=critic_score.confidence,
                critic_failure_mode=critic_score.failure_mode,
                critic_elapsed_ms=critic_score.elapsed_ms,
                critic_input_tokens=usage["input_tokens"],
                critic_output_tokens=usage["output_tokens"],
            )
        )

    return rows


# ---------------------------------------------------------------------
# Aggregator.
# ---------------------------------------------------------------------


def aggregate(rows: list[CallRow]) -> dict[str, Any]:
    """Compute aggregate metrics from per-call rows."""
    total = len(rows)

    # Skip rows where the critic short-circuited (no API call attempted).
    # Default-OFF rows have failure_mode="" but elapsed_ms=0 and no usage.
    actionable = [r for r in rows if r.critic_failure_mode == "" and r.critic_elapsed_ms > 0]
    failures = [r for r in rows if r.critic_failure_mode != ""]

    risk_counts = Counter(r.critic_risk_flag for r in actionable)
    state_mismatch_count = sum(1 for r in actionable if r.critic_state_mismatch)
    state_mismatch_high = sum(
        1 for r in actionable if r.critic_state_mismatch and r.critic_risk_flag == "high"
    )

    suggested_corrections = [
        r.critic_suggested_correction
        for r in actionable
        if r.critic_suggested_correction
    ]
    top_corrections = Counter(suggested_corrections).most_common(10)

    # Mismatch reason taxonomy.
    mismatch_reasons = [
        r.critic_state_mismatch_reason
        for r in actionable
        if r.critic_state_mismatch and r.critic_state_mismatch_reason
    ]

    # Latency stats from actionable calls only.
    latencies = [r.critic_elapsed_ms for r in actionable]
    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p95_idx = max(0, int(0.95 * len(latencies_sorted)) - 1)
        p99_idx = max(0, int(0.99 * len(latencies_sorted)) - 1)
        p95 = latencies_sorted[p95_idx]
        p99 = latencies_sorted[p99_idx]
        avg = statistics.mean(latencies)
    else:
        p50 = p95 = p99 = 0
        avg = 0.0

    # Token / cost stats.
    total_in = sum(r.critic_input_tokens for r in rows)
    total_out = sum(r.critic_output_tokens for r in rows)
    cost_usd = (
        total_in * OPUS_4_7_INPUT_PER_MTOK / 1_000_000
        + total_out * OPUS_4_7_OUTPUT_PER_MTOK / 1_000_000
    )

    # Critic vs FSM "agreement" — defined as risk_flag == "none" AND not state_mismatch.
    agreement = sum(
        1 for r in actionable if r.critic_risk_flag == "none" and not r.critic_state_mismatch
    )
    agreement_rate = (agreement / len(actionable)) if actionable else 0.0

    # Failure-mode breakdown.
    failure_modes = Counter(r.critic_failure_mode for r in failures)

    return {
        "total_rows": total,
        "actionable_rows": len(actionable),
        "failure_rows": len(failures),
        "failure_modes": dict(failure_modes),
        "risk_flag_distribution": dict(risk_counts),
        "state_mismatch_count": state_mismatch_count,
        "state_mismatch_with_high_risk": state_mismatch_high,
        "agreement_rate": agreement_rate,
        "top_suggested_corrections": top_corrections,
        "mismatch_reasons_sample": mismatch_reasons[:20],
        "latency_ms": {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "avg": round(avg, 1),
        },
        "tokens": {"input": total_in, "output": total_out},
        "cost_usd_total": round(cost_usd, 4),
        "cost_usd_per_call": round(cost_usd / total, 6) if total else 0.0,
    }


# ---------------------------------------------------------------------
# Markdown report writer.
# ---------------------------------------------------------------------


def _top3_state_mismatch_examples(rows: list[CallRow]) -> list[CallRow]:
    """Return up to 3 most informative state_mismatch examples — prefer
    risk=high first, then medium, then low; tie-break by earliest appearance."""
    by_risk = {"high": [], "medium": [], "low": [], "none": []}
    for r in rows:
        if r.critic_state_mismatch and r.critic_failure_mode == "":
            by_risk[r.critic_risk_flag].append(r)
    out: list[CallRow] = []
    for risk in ("high", "medium", "low", "none"):
        for r in by_risk[risk]:
            if len(out) >= 3:
                return out
            out.append(r)
    return out


def write_markdown_report(
    out_path: Path,
    *,
    metrics: dict[str, Any],
    fixture_count: int,
    rows: list[CallRow],
    args: argparse.Namespace,
) -> None:
    """Write a human-readable aggregate-metrics.md."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mode = "LIVE" if (args.commit and os.environ.get("PRISM42_CRITIC_COMMIT") == "1") else "DRY-RUN"

    examples = _top3_state_mismatch_examples(rows)

    lines: list[str] = []
    lines.append("# Cycle-2BC critic eval — aggregate metrics")
    lines.append("")
    lines.append(f"- Mode: **{mode}**")
    lines.append(f"- Generated: {now}")
    lines.append(f"- Fixtures: {fixture_count}")
    lines.append(f"- Rows total: {metrics['total_rows']}")
    lines.append(f"- Rows with actionable critic output: {metrics['actionable_rows']}")
    lines.append(f"- Rows where critic failed: {metrics['failure_rows']}")
    if metrics["failure_modes"]:
        lines.append(f"  - Failure modes: {metrics['failure_modes']}")
    lines.append("")
    lines.append("## Critic vs FSM agreement")
    lines.append("")
    pct = metrics["agreement_rate"] * 100
    lines.append(f"- Agreement rate: **{pct:.1f}%**")
    lines.append("  (risk_flag=='none' AND state_mismatch==False)")
    lines.append("")
    lines.append("## Risk-flag distribution (actionable rows only)")
    lines.append("")
    for k in ("none", "low", "medium", "high"):
        n = metrics["risk_flag_distribution"].get(k, 0)
        share = (n / max(1, metrics["actionable_rows"])) * 100
        lines.append(f"- `{k}`: {n} ({share:.1f}%)")
    lines.append("")
    lines.append("## State-mismatch flags")
    lines.append("")
    sm = metrics["state_mismatch_count"]
    sm_high = metrics["state_mismatch_with_high_risk"]
    lines.append(f"- state_mismatch=True: {sm}")
    lines.append(f"- state_mismatch=True AND risk=high: {sm_high}")
    if metrics["mismatch_reasons_sample"]:
        lines.append("")
        lines.append("Mismatch-reason sample (up to 20):")
        for reason in metrics["mismatch_reasons_sample"]:
            lines.append(f"- {reason}")
    lines.append("")
    lines.append("## Top suggested corrections (most common)")
    lines.append("")
    if metrics["top_suggested_corrections"]:
        for text, n in metrics["top_suggested_corrections"]:
            lines.append(f"- ({n}x) {text}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Top-3 state_mismatch examples")
    lines.append("")
    if examples:
        for r in examples:
            lines.append(f"### {r.fixture_id} (turn {r.turn_index}, scenario={r.scenario})")
            lines.append("")
            lines.append(f"- Caller: {r.caller_utterance!r}")
            lines.append(f"- FSM intent: `{r.fsm_intent}` (state {r.fsm_state_before} -> {r.fsm_state_after})")
            lines.append(f"- FSM reply: {r.fsm_reply!r}")
            lines.append(f"- Critic risk: `{r.critic_risk_flag}`")
            lines.append(f"- Critic mismatch reason: {r.critic_state_mismatch_reason!r}")
            if r.critic_suggested_correction:
                lines.append(f"- Critic suggested correction: {r.critic_suggested_correction!r}")
            lines.append("")
    else:
        lines.append("- (no state_mismatch=True rows)")
    lines.append("")
    lines.append("## Latency (critic actionable rows)")
    lines.append("")
    L = metrics["latency_ms"]
    lines.append(f"- p50: {L['p50']} ms")
    lines.append(f"- p95: {L['p95']} ms")
    lines.append(f"- p99: {L['p99']} ms")
    lines.append(f"- avg: {L['avg']} ms")
    lines.append("")
    lines.append("## Cost (Opus 4.7, $5 / $25 per MTok)")
    lines.append("")
    lines.append(f"- Total input tokens: {metrics['tokens']['input']}")
    lines.append(f"- Total output tokens: {metrics['tokens']['output']}")
    lines.append(f"- Total cost: ${metrics['cost_usd_total']:.4f}")
    lines.append(f"- Cost per call: ${metrics['cost_usd_per_call']:.6f}")
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    lines.append("- Pricing: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-04-26)")
    lines.append("- Opus 4.7 sampler kwargs: https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7 (fetched 2026-04-26)")
    lines.append("")
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------
# Entrypoint.
# ---------------------------------------------------------------------


async def _amain(args: argparse.Namespace) -> int:
    fixtures_path = Path(args.fixtures).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not fixtures_path.exists():
        print(f"[harness] fixtures path missing: {fixtures_path}", file=sys.stderr)
        return 2

    # Double-gate enforcement.
    is_live = bool(args.commit) and os.environ.get("PRISM42_CRITIC_COMMIT") == "1"
    print(
        f"[harness] mode={'LIVE' if is_live else 'DRY-RUN'} "
        f"(commit={args.commit}, env={os.environ.get('PRISM42_CRITIC_COMMIT')})",
        file=sys.stderr,
    )
    if is_live:
        # Live run: ensure the critic is enabled.
        if os.environ.get("PRISM42_ENABLE_CLAUDE_CRITIC") != "1":
            os.environ["PRISM42_ENABLE_CLAUDE_CRITIC"] = "1"
            print("[harness] forced PRISM42_ENABLE_CLAUDE_CRITIC=1 for live run", file=sys.stderr)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "[harness] LIVE mode requested but ANTHROPIC_API_KEY missing; aborting",
                file=sys.stderr,
            )
            return 3
    else:
        # Dry-run: ensure critic stays OFF so we never make API calls.
        os.environ["PRISM42_ENABLE_CLAUDE_CRITIC"] = "0"

    fixtures = load_fixtures(fixtures_path)
    print(f"[harness] loaded {len(fixtures)} fixtures from {fixtures_path}", file=sys.stderr)

    if args.limit:
        fixtures = fixtures[: args.limit]
        print(f"[harness] limited to first {len(fixtures)} fixtures", file=sys.stderr)

    # Reset the critic's accumulator so we get clean metrics for THIS run.
    claude_critic.reset_token_usage()

    rows: list[CallRow] = []
    t0 = time.monotonic()

    for i, fx in enumerate(fixtures, start=1):
        session_id = f"eval-{fx.fixture_id}"
        try:
            fx_rows = await run_fixture(fx, session_id=session_id)
        except Exception as e:  # noqa: BLE001
            print(
                f"[harness] fixture {fx.fixture_id} raised: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            continue
        rows.extend(fx_rows)
        if i % 10 == 0 or i == len(fixtures):
            dt = time.monotonic() - t0
            print(
                f"[harness] {i}/{len(fixtures)} fixtures, {len(rows)} rows, {dt:.1f}s elapsed",
                file=sys.stderr,
            )

    # Per-call JSONL.
    today = datetime.now(timezone.utc).date().isoformat()
    jsonl_path = out_dir / f"critic-eval-{today}.jsonl"
    with jsonl_path.open("w") as f:
        for r in rows:
            f.write(r.to_json() + "\n")
    print(f"[harness] wrote {len(rows)} rows to {jsonl_path}", file=sys.stderr)

    # Aggregate.
    metrics = aggregate(rows)
    md_path = out_dir / "aggregate-metrics.md"
    write_markdown_report(
        md_path,
        metrics=metrics,
        fixture_count=len(fixtures),
        rows=rows,
        args=args,
    )
    print(f"[harness] wrote aggregate metrics to {md_path}", file=sys.stderr)

    # Print a one-line summary so CI / pipes can grep.
    print(
        json.dumps(
            {
                "rows": metrics["total_rows"],
                "actionable": metrics["actionable_rows"],
                "agreement_rate": round(metrics["agreement_rate"], 4),
                "state_mismatch": metrics["state_mismatch_count"],
                "risk_dist": metrics["risk_flag_distribution"],
                "p50_ms": metrics["latency_ms"]["p50"],
                "p95_ms": metrics["latency_ms"]["p95"],
                "cost_usd": metrics["cost_usd_total"],
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Critic eval harness — FSM vs Claude Opus 4.7 critic shadow eval."
    )
    parser.add_argument(
        "--fixtures",
        required=True,
        help="Path to the JSONL fixtures file.",
    )
    parser.add_argument(
        "--out-dir",
        default="findings/voice/cycle2BC_critic_eval/team-b-critic/",
        help="Directory to write the JSONL log and aggregate metrics.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="One half of the double-gate. Live calls also need PRISM42_CRITIC_COMMIT=1.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If non-zero, only run the first N fixtures (smoke).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
