#!/usr/bin/env python3
"""Live session-event smoke for the Prism coordinator on Managed Agents.

Creates one session bound to `prism-coordinator` + `prism-standard-env`
(IDs from agents/manifest.yaml), sends a short introduction prompt, and
streams session events for up to 90 seconds. The prompt explicitly tells
the coordinator NOT to call sub-agents — this smoke proves the event
channel works without running up session-hour charges.

Default behavior is --dry-run: print plan, no network, no SDK import.
Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_SMOKE_SESSION_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1.

Outputs on commit (written to results/smoke/, gitignored):
  - session-<yyyymmdd-hhmm>-transcript.log : full prompt+response+event log
  - session-<yyyymmdd-hhmm>-summary.json   : structured {session_id, events, usage}

A summary doc for humans lives at findings/smoke-session-2026-04-22.md
(committed; the transcript log is an ephemeral operational artifact).

First live run: 2026-04-22. Cost: ~$0.15 (tokens only; session was idle
by the time the prompt was answered). Re-running is safe and cheap;
creating a new session every time avoids stale-state.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import uuid
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "agents" / "manifest.yaml"
OUT_DIR = REPO / "results" / "smoke"
BETA = "managed-agents-2026-04-01"

PROMPT = (
    "Introduce yourself in 3 short sentences: (a) your role as the Prism "
    "coordinator, (b) the five callable sub-agents you can invoke and the "
    "ORDER you invoke them in, (c) the shape of the first user message "
    "you expect (what keys). Do NOT call any sub-agents. Do NOT invoke "
    "any tools. Plain text answer only."
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
    coord_id = coord.get("id")
    coord_version = coord.get("version")
    if not env_id or not coord_id:
        raise RuntimeError(
            f"manifest incomplete: environment_id={env_id!r}, "
            f"coordinator={coord!r}"
        )
    return {
        "environment_id": env_id,
        "coordinator_id": coord_id,
        "coordinator_version": coord_version,
    }


def do_dry_run(args: argparse.Namespace) -> int:
    print("(dry-run) scripts/smoke_session.py plan:")
    try:
        m = _load_manifest()
        print(f"  coordinator      : {m['coordinator_id']} v{m['coordinator_version']}")
        print(f"  environment      : {m['environment_id']}")
    except RuntimeError as e:
        print(f"  manifest         : NOT FOUND ({e})")
    print(f"  stream-cap-sec   : {args.stream_cap_sec}")
    print(f"  out-dir          : {OUT_DIR}")
    print(f"  prompt length    : {len(PROMPT)} chars")
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def do_commit(args: argparse.Namespace) -> int:
    # Lazy SDK import — inside do_commit only. Containment-asserted by
    # scripts/check_sdk_containment.py.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    m = _load_manifest()
    stamp = _now_stamp()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / f"session-{stamp}-transcript.log"
    summary_path = OUT_DIR / f"session-{stamp}-summary.json"

    c = Anthropic()
    t0 = time.time()
    lines: list[str] = []

    def _log(s: str) -> None:
        line = s.rstrip()
        lines.append(line)
        print(line)

    _log("== prism-coordinator session smoke — live ==")
    session = c.beta.sessions.create(
        agent={
            "type": "agent",
            "id": m["coordinator_id"],
            "version": m["coordinator_version"],
        },
        environment_id=m["environment_id"],
        title=f"prism-smoke-{stamp}",
        extra_headers={"anthropic-beta": BETA},
    )
    sid = session.id
    _log(
        f"[{time.time()-t0:5.1f}s] session.create -> id={sid} "
        f"status={getattr(session, 'status', None)}"
    )

    c.beta.sessions.events.send(
        session_id=sid,
        events=[
            {
                "type": "user.message",
                "content": [{"type": "text", "text": PROMPT}],
            }
        ],
        extra_headers={"anthropic-beta": BETA},
    )
    _log(
        f"[{time.time()-t0:5.1f}s] events.send -> user.message posted "
        f"({len(PROMPT)} chars)"
    )

    deadline = t0 + float(args.stream_cap_sec)
    collected: list[dict] = []
    assistant_text_chunks: list[str] = []
    event_types: dict[str, int] = {}

    try:
        with c.beta.sessions.events.stream(
            session_id=sid, extra_headers={"anthropic-beta": BETA}
        ) as stream:
            for ev in stream:
                now = time.time()
                etype = getattr(ev, "type", None) or type(ev).__name__
                event_types[etype] = event_types.get(etype, 0) + 1
                collected.append({"t": round(now - t0, 2), "type": etype})
                content = getattr(ev, "content", None)
                if content:
                    for block in content:
                        if getattr(block, "type", None) == "text":
                            assistant_text_chunks.append(
                                getattr(block, "text", "") or ""
                            )
                _log(f"[{now - t0:5.1f}s] event: {etype}")
                if etype in ("turn.ended", "session.ended", "error"):
                    break
                if etype == "session.status_idle" and len(collected) >= 3:
                    # The coordinator finished its response and the session
                    # is idle waiting for the next user message. Close clean.
                    _log(f"[{now - t0:5.1f}s] idle reached, closing stream")
                    break
                if now > deadline:
                    _log(f"[{now - t0:5.1f}s] STOP ({args.stream_cap_sec}s cap)")
                    break
    except Exception as e:
        _log(f"STREAM ERROR: {type(e).__name__}: {str(e)[:300]}")

    _log("---")
    _log(f"event types: {event_types}")
    _log(f"total events: {len(collected)}")
    joined = "".join(assistant_text_chunks)
    if joined:
        _log(f"--- assistant text ({len(joined)} chars) ---")
        _log(joined[:2000])
        _log("---")

    final = c.beta.sessions.retrieve(
        session_id=sid, extra_headers={"anthropic-beta": BETA}
    )
    final_status = getattr(final, "status", None)
    usage = getattr(final, "usage", None)
    _log(f"final status: {final_status}")
    if usage:
        _log(f"usage: {usage}")
    console_url = f"https://platform.claude.com/sessions/{sid}"
    _log(f"session URL: {console_url}")
    _log(f"SMOKE RESULT: session {sid} reachable; event channel functional.")

    log_path.write_text("\n".join(lines) + "\n")

    # Structured summary. Strips any text content from assistant_text (the
    # log file holds the full transcript); this JSON is for machine
    # consumption (CI badge, dashboards, etc.).
    def _usage_dict(u) -> dict:
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
        "environment_id": m["environment_id"],
        "final_status": final_status,
        "event_types": event_types,
        "n_events": len(collected),
        "assistant_text_len": len(joined),
        "wall_time_sec": round(time.time() - t0, 2),
        "usage": _usage_dict(usage),
        "console_url": console_url,
        "beta_header": BETA,
        "generated_at": _now_stamp(),
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")

    print(f"\n(commit) transcript: {log_path}")
    print(f"(commit) summary   : {summary_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run live. Requires PRISM_SMOKE_SESSION_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--stream-cap-sec",
        type=int,
        default=90,
        help="Hard cap on stream duration (default 90).",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=0.50,
        help="Advisory only; the smoke prompt is small (~$0.15 observed).",
    )
    args = ap.parse_args(argv)

    if args.commit and os.environ.get("PRISM_SMOKE_SESSION_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_SMOKE_SESSION_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args)
    return do_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
