#!/usr/bin/env python3
"""Verify a sample of in-flight Managed Agents sessions survive client kill.

Reads a state file (default `results/harness-in-progress.txt`) containing
one session_id per line, samples N of them, then reattaches via
`GET /v1/sessions/:id/stream` and confirms each is still `running` or
transitioned to `idle`. This is the T4.7 durability verification beat
(spec §5 T4.7):

    make verify-harness
    # ...
    python scripts/verify_session_durability.py --sample 3
    # must print: "session durability: 3/3 sessions survived client kill; reattach OK"

Default behavior is --dry-run: prints the sampling plan, does not construct
an Anthropic client, does not hit the API.

Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_DURABILITY_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic SDK is
only imported inside do_commit(); dry-run never touches it.
scripts/check_sdk_containment.py enforces this with AST.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STATE_FILE = REPO / "results" / "harness-in-progress.txt"

MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"

OK_STATUSES = {"running", "idle", "rescheduling"}


def _load_session_ids(state_path: Path) -> list[str]:
    if not state_path.exists():
        return []
    ids: list[str] = []
    for line in state_path.read_text().splitlines():
        sid = line.strip()
        if sid and not sid.startswith("#"):
            ids.append(sid)
    return ids


def do_dry_run(args: argparse.Namespace, state_path: Path) -> int:
    ids = _load_session_ids(state_path)
    rng = random.Random(args.seed)
    n = min(args.sample, len(ids))
    sample = rng.sample(ids, n) if n else []

    print("(dry-run) verify_session_durability.py plan:")
    print(f"  state_file : {state_path}")
    print(f"  state_found: {state_path.exists()}")
    print(f"  sessions   : {len(ids)} in state file")
    print(f"  sample_n   : {args.sample}")
    print(f"  seed       : {args.seed}")
    if sample:
        print("  planned session ids to re-stream:")
        for sid in sample:
            print(f"    - {sid}")
    else:
        print("  (no session ids available to sample)")
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def do_commit(args: argparse.Namespace, state_path: Path) -> int:
    """Re-attach to sampled sessions and confirm they are still progressing."""
    # The Anthropic client is only constructed in this function. It is
    # never imported or instantiated at module scope and never touched
    # from dry-run. scripts/check_sdk_containment.py enforces this.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    ids = _load_session_ids(state_path)
    if not ids:
        print(f"error: no session ids found in {state_path}", file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    n = min(args.sample, len(ids))
    sample = rng.sample(ids, n)

    client = Anthropic()
    survivors = 0
    for sid in sample:
        try:
            session = client.beta.sessions.retrieve(sid, betas=[MANAGED_AGENTS_BETA])
            status = getattr(session, "status", "unknown")
            print(f"  session={sid} status={status}")
            if status in OK_STATUSES:
                # Confirm stream is reachable; consume a single event then exit.
                stream = client.beta.sessions.events.stream(
                    sid, betas=[MANAGED_AGENTS_BETA]
                )
                got_event = False
                with stream as events:
                    for _ev in events:
                        got_event = True
                        break
                if got_event or status == "idle":
                    survivors += 1
                else:
                    print(f"  WARN: session={sid} opened but produced no event")
            else:
                print(f"  WARN: session={sid} in unexpected status={status}")
        except Exception as exc:  # noqa: BLE001 — diagnostic print
            print(f"  ERROR: session={sid} reattach failed: {exc}")

    if survivors == n:
        print(
            f"session durability: {survivors}/{n} sessions survived client kill; reattach OK"
        )
        return 0
    print(
        f"session durability: {survivors}/{n} survived — durability gate FAILED",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--sample",
        type=int,
        required=True,
        help="Number of in-flight sessions to reattach and verify.",
    )
    ap.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help=f"State file with one session_id per line (default: {DEFAULT_STATE_FILE}).",
    )
    ap.add_argument("--seed", type=int, default=42, help="Sampling seed (default 42).")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Actually reattach via the API. Requires PRISM_DURABILITY_COMMIT=1 in env.",
    )
    args = ap.parse_args()

    state_path = Path(args.state_file).resolve()

    if args.commit and os.environ.get("PRISM_DURABILITY_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_DURABILITY_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args, state_path)
    return do_dry_run(args, state_path)


if __name__ == "__main__":
    sys.exit(main())
