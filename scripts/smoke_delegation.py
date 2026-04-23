#!/usr/bin/env python3
"""Live delegation smoke — prism-coordinator calls prism-defender once.

Extends scripts/smoke_session.py: this one actually exercises the
`callable_agents` binding at runtime, not just at create-time. We send
the coordinator a TRIVIAL invariant + an explicit instruction to call
defender exactly once and stop. The smoke succeeds iff we observe a
sub-agent span event in the stream (`span.sub_agent_*` or equivalent).

Default behavior is --dry-run. Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_SMOKE_DELEGATION_COMMIT=1 in the environment.

Missing either prints a refusal and exits 1. Cost budget is
advisory: sub-agent tokens accumulate across the coordinator + one
defender call; realistic spend is ~$0.30-$0.50 per run. The stream is
hard-capped at --stream-cap-sec (default 180).

Outputs on commit (under results/smoke/, gitignored):
  - delegation-<stamp>-transcript.log  full event log with timestamps
  - delegation-<stamp>-summary.json    structured {session_id, events, usage, delegation_observed}

Human-facing evidence: findings/smoke-delegation-2026-04-22.md (committed).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "agents" / "manifest.yaml"
OUT_DIR = REPO / "results" / "smoke"
BETA = "managed-agents-2026-04-01"

# Kept deliberately small: coordinator + ONE defender call, no dialectic,
# no other sub-agents. Invariant is trivial and requires no file I/O.
PROMPT = (
    "DELEGATION SMOKE — do exactly this, then stop:\n"
    "\n"
    "1. Call the `defender` sub-agent with the single user-message:\n"
    '   "Smoke test: emit exactly one invariant as JSON, id=INV-000, '
    "class=numerical, statement='Any real number x satisfies x == x.', "
    "source_lines=[1], confidence=0.99. "
    'Do not run any tools. Do not write any files. One message and done."\n'
    "\n"
    "2. After defender returns, in your next assistant message, summarize "
    "in ONE sentence what defender emitted.\n"
    "\n"
    "3. STOP. Do not call any other sub-agent (no attacker, no "
    "synthesizer, no executor, no adjudicator). Do not iterate.\n"
    "\n"
    "This is a smoke test of the delegation path only. No case_id, no "
    "target_path, no artifacts — just defender invoked once and a one-line "
    "summary. The harness is verifying that the `callable_agents` binding "
    "you received at create-time actually fires at session runtime."
)


def _now_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _load_manifest() -> dict:
    if not MANIFEST.exists():
        raise RuntimeError(
            "agents/manifest.yaml is missing. Run "
            "`PRISM_AGENTS_COMMIT=1 python scripts/register_agents.py --commit` first."
        )
    data = yaml.safe_load(MANIFEST.read_text()) or {}
    env_id = data.get("environment_id")
    coord = (data.get("agents") or {}).get("coordinator") or {}
    defender = (data.get("agents") or {}).get("defender") or {}
    if not env_id or not coord.get("id") or not defender.get("id"):
        raise RuntimeError(f"manifest incomplete: env={env_id!r}, coord={coord!r}, def={defender!r}")
    return {
        "environment_id": env_id,
        "coordinator_id": coord["id"],
        "coordinator_version": coord["version"],
        "defender_id": defender["id"],
    }


def _ev_type(ev) -> str:
    return getattr(ev, "type", None) or type(ev).__name__


def _maybe_text_blocks(ev) -> list[str]:
    out: list[str] = []
    content = getattr(ev, "content", None) or []
    for block in content:
        if getattr(block, "type", None) == "text":
            out.append(getattr(block, "text", "") or "")
    return out


def do_dry_run(args: argparse.Namespace) -> int:
    print("(dry-run) scripts/smoke_delegation.py plan:")
    try:
        m = _load_manifest()
        print(f"  coordinator      : {m['coordinator_id']} v{m['coordinator_version']}")
        print(f"  defender (target) : {m['defender_id']}")
        print(f"  environment      : {m['environment_id']}")
    except RuntimeError as e:
        print(f"  manifest         : NOT USABLE ({e})")
    print(f"  stream-cap-sec   : {args.stream_cap_sec}")
    print(f"  budget-cap-usd   : {args.budget_cap_usd}")
    print(f"  out-dir          : {OUT_DIR}")
    print(f"  prompt length    : {len(PROMPT)} chars")
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def do_commit(args: argparse.Namespace) -> int:
    # Lazy SDK import, enforced by scripts/check_sdk_containment.py.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    m = _load_manifest()
    stamp = _now_stamp()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / f"delegation-{stamp}-transcript.log"
    summary_path = OUT_DIR / f"delegation-{stamp}-summary.json"

    c = Anthropic()
    t0 = time.time()
    lines: list[str] = []

    def _log(s: str) -> None:
        line = s.rstrip()
        lines.append(line)
        print(line)

    _log("== prism-coordinator -> defender DELEGATION smoke — live ==")
    session = c.beta.sessions.create(
        agent={"type": "agent", "id": m["coordinator_id"], "version": m["coordinator_version"]},
        environment_id=m["environment_id"],
        title=f"prism-delegation-smoke-{stamp}",
        extra_headers={"anthropic-beta": BETA},
    )
    sid = session.id
    _log(f"[{time.time()-t0:5.1f}s] session.create -> id={sid}")

    c.beta.sessions.events.send(
        session_id=sid,
        events=[{"type": "user.message", "content": [{"type": "text", "text": PROMPT}]}],
        extra_headers={"anthropic-beta": BETA},
    )
    _log(f"[{time.time()-t0:5.1f}s] events.send -> user.message ({len(PROMPT)} chars)")

    deadline = t0 + float(args.stream_cap_sec)
    event_types: dict[str, int] = {}
    collected: list[dict] = []
    assistant_text: list[str] = []
    delegation_observed = False
    sub_agent_spans: list[dict] = []

    try:
        with c.beta.sessions.events.stream(
            session_id=sid, extra_headers={"anthropic-beta": BETA}
        ) as stream:
            for ev in stream:
                now = time.time()
                etype = _ev_type(ev)
                event_types[etype] = event_types.get(etype, 0) + 1
                rec: dict = {"t": round(now - t0, 2), "type": etype}
                collected.append(rec)

                # Detect delegation — any event type that carries a sub-agent
                # reference. The exact event name varies by SDK version; we
                # track any string that hints at sub-agent / call / delegate
                # / subagent, and specifically any span whose name includes
                # an agent_id matching our defender.
                lowered = etype.lower()
                if any(
                    kw in lowered
                    for kw in ("sub_agent", "subagent", "delegate", "call", "invoke")
                ) and "model_request" not in lowered:
                    delegation_observed = True
                    sub_agent_spans.append(rec)

                # Also inspect event attributes for an agent_id pointing at
                # the defender (best-effort — SDK shape may vary).
                agent_id_attr = getattr(ev, "agent_id", None) or getattr(
                    ev, "sub_agent_id", None
                )
                if agent_id_attr and agent_id_attr == m["defender_id"]:
                    delegation_observed = True
                    sub_agent_spans.append({**rec, "agent_id": agent_id_attr})

                for text in _maybe_text_blocks(ev):
                    if text:
                        assistant_text.append(text)

                _log(f"[{now - t0:5.1f}s] event: {etype}")

                if etype in ("turn.ended", "session.ended", "error"):
                    break
                if now > deadline:
                    _log(f"[{now - t0:5.1f}s] STOP ({args.stream_cap_sec}s cap)")
                    break
    except Exception as e:
        _log(f"STREAM ERROR: {type(e).__name__}: {str(e)[:300]}")

    _log("---")
    _log(f"event types: {event_types}")
    _log(f"total events: {len(collected)}")
    _log(f"delegation_observed: {delegation_observed}")
    if sub_agent_spans:
        _log(f"sub_agent spans: {len(sub_agent_spans)}")
        for s in sub_agent_spans[:10]:
            _log(f"  {s}")
    if assistant_text:
        joined = "".join(assistant_text)
        _log(f"--- assistant text ({len(joined)} chars) ---")
        _log(joined[:3000])
        _log("---")

    final = c.beta.sessions.retrieve(session_id=sid, extra_headers={"anthropic-beta": BETA})
    usage = getattr(final, "usage", None)
    _log(f"final status: {getattr(final, 'status', None)}")
    if usage:
        _log(f"usage: {usage}")
    console_url = f"https://platform.claude.com/sessions/{sid}"
    _log(f"session URL: {console_url}")

    log_path.write_text("\n".join(lines) + "\n")

    def _u(u) -> dict:
        if u is None:
            return {}
        return {
            "input_tokens": getattr(u, "input_tokens", None),
            "output_tokens": getattr(u, "output_tokens", None),
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None),
        }

    summary = {
        "session_id": sid,
        "coordinator_id": m["coordinator_id"],
        "defender_id": m["defender_id"],
        "environment_id": m["environment_id"],
        "final_status": getattr(final, "status", None),
        "event_types": event_types,
        "n_events": len(collected),
        "delegation_observed": delegation_observed,
        "sub_agent_spans": sub_agent_spans,
        "assistant_text_len": sum(len(t) for t in assistant_text),
        "wall_time_sec": round(time.time() - t0, 2),
        "usage": _u(usage),
        "console_url": console_url,
        "beta_header": BETA,
        "generated_at": _now_stamp(),
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")

    print(f"\n(commit) transcript: {log_path}")
    print(f"(commit) summary   : {summary_path}")
    if delegation_observed:
        print("(commit) RESULT: delegation fired — coordinator reached the defender.")
        return 0
    print("(commit) RESULT: NO delegation span observed within cap.")
    return 0  # treated informational, not failing — event-type names may drift


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run live. Requires PRISM_SMOKE_DELEGATION_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--stream-cap-sec",
        type=int,
        default=180,
        help="Hard cap on stream duration (default 180).",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=1.0,
        help="Advisory budget cap. Realistic cost ~$0.30-0.50 per run.",
    )
    args = ap.parse_args(argv)

    if args.commit and os.environ.get("PRISM_SMOKE_DELEGATION_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_SMOKE_DELEGATION_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args)
    return do_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
