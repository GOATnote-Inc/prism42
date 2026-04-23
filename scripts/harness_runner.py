#!/usr/bin/env python3
"""Run one Prism audit end-to-end via the Managed Agents coordinator.

Reads agents/manifest.yaml to locate the registered coordinator agent
and the shared environment, creates a session, sends the initial case
event, and streams the resulting primary + thread events to
runs/<run_id>/events.jsonl while also printing a condensed summary.

Default behavior is --dry-run: loads the manifest and the case, prints
the session-create request body and the initial event body that would
be sent, and exits. No network, no client construction.

Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_HARNESS_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic client is
only imported and instantiated inside the commit branch; dry-run never
touches the SDK. Tests grep for `Anthropic(` — it must stay inside
do_commit().
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO / "agents"
MANIFEST = AGENTS_DIR / "manifest.yaml"
RUNS_DIR = REPO / "runs"

MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"


def _load_manifest() -> dict:
    if not MANIFEST.exists():
        raise FileNotFoundError(
            f"{MANIFEST} not found. Run scripts/register_agents.py --commit first."
        )
    with MANIFEST.open() as f:
        return yaml.safe_load(f)


def _fake_manifest() -> dict:
    """Placeholder manifest so dry-run works before registration."""
    return {
        "environment_id": "env_<placeholder>",
        "agents": {
            role: {"id": f"agt_<{role}_placeholder>", "version": 1}
            for role in (
                "coordinator",
                "defender",
                "attacker",
                "synthesizer",
                "executor",
                "adjudicator",
            )
        },
    }


def _load_case(case_path: Path) -> dict:
    with case_path.open() as f:
        return json.load(f)


def _build_session_request(manifest: dict, case: dict, run_id: str) -> dict:
    coord = manifest["agents"]["coordinator"]
    return {
        "agent": {"type": "agent", "id": coord["id"], "version": coord["version"]},
        "environment_id": manifest["environment_id"],
        "title": f"prism-{case['target_domain']}-{case['case_id']}-{run_id[:8]}",
        "metadata": {
            "run_id": run_id,
            "target_domain": case["target_domain"],
            "case_id": case["case_id"],
        },
    }


def _build_initial_event(case: dict) -> dict:
    return {
        "type": "user_message",
        "content": [
            {
                "type": "text",
                "text": json.dumps(case, indent=2, sort_keys=True),
            }
        ],
    }


def _print_body(label: str, body: dict) -> None:
    print(f"--- {label} ---")
    print(json.dumps(body, indent=2, default=str))
    print()


def do_dry_run(case_path: Path) -> None:
    """Print request bodies; no network, no client construction."""
    manifest = _load_manifest() if MANIFEST.exists() else _fake_manifest()
    if not MANIFEST.exists():
        print(f"(dry-run) {MANIFEST} missing — using placeholder IDs")
        print()
    case = _load_case(case_path)
    run_id = str(uuid.uuid4())

    session_req = _build_session_request(manifest, case, run_id)
    _print_body("POST /v1/sessions  (create coordinator session)", session_req)

    event = _build_initial_event(case)
    _print_body("POST /v1/sessions/{id}/events  (initial user_message)", event)

    print(f"(dry-run) run_id={run_id}")
    print(f"(dry-run) would stream events into runs/{run_id}/events.jsonl")


def do_commit(case_path: Path) -> None:
    """Real session create + event stream. Reached only when both gates pass."""
    # The Anthropic client is only constructed in this function. It is
    # never imported or instantiated at module scope and never touched
    # from dry-run. Tests grep for `Anthropic(` — it must stay here.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    client = Anthropic()

    manifest = _load_manifest()
    case = _load_case(case_path)
    run_id = str(uuid.uuid4())

    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"

    session_req = _build_session_request(manifest, case, run_id)
    session = client.beta.sessions.create(betas=[MANAGED_AGENTS_BETA], **session_req)
    print(f"session created: id={session.id} run_id={run_id}")

    initial_event = _build_initial_event(case)
    client.beta.sessions.events.send(
        session.id,
        events=[initial_event],
        betas=[MANAGED_AGENTS_BETA],
    )
    print(f"initial event sent to session {session.id}")

    with events_path.open("w") as f:
        stream = client.beta.sessions.events.stream(
            session.id,
            betas=[MANAGED_AGENTS_BETA],
        )
        with stream as events:
            for ev in events:
                payload = ev.model_dump() if hasattr(ev, "model_dump") else dict(ev)
                f.write(json.dumps(payload, default=str) + "\n")
                f.flush()
                ev_type = payload.get("type", "?")
                thread = payload.get("thread_id") or "primary"
                print(f"  event: {ev_type} thread={thread}")

    print(f"run complete: events -> {events_path}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--case",
        required=True,
        help="Path to the case JSON (target_domain, case_id, target_path, ...).",
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run for real. Requires PRISM_HARNESS_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Default behavior; prints request bodies, no network.",
    )
    args = ap.parse_args()

    if args.commit and args.dry_run:
        print("error: --commit and --dry-run are mutually exclusive", file=sys.stderr)
        return 2

    if args.commit and os.environ.get("PRISM_HARNESS_COMMIT") != "1":
        print(
            "error: --commit requires PRISM_HARNESS_COMMIT=1 in env; refusing",
            file=sys.stderr,
        )
        return 1

    case_path = Path(args.case).resolve()
    if not case_path.exists():
        print(f"error: case file not found: {case_path}", file=sys.stderr)
        return 1

    if args.commit:
        do_commit(case_path)
        return 0

    do_dry_run(case_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
