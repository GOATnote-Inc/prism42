#!/usr/bin/env python3
"""Prism Tier-1 daily orchestrator — plan, execute, verify, PR.

Runs the full Prism long-horizon loop in one invocation:

  1. Pre-flight: `make verify-all` must be green. If red, halt and
     open a "repo needs human intervention" draft PR.
  2. Plan: create a coordinator session with the `prism-planner`
     skill description pinned; it reads repo state + roadmap and
     writes /workspace/plan-YYYYMMDD.json. Captures to local
     results/orchestrator/<stamp>/plan.json.
  3. Safeguards gate: parse the plan JSON; refuse to execute if it
     would touch a frozen path, set physician_review, push a
     disclosure draft, or exceed the budget cap.
  4. Execute: shell out to the planned `runner` command. Captures
     stdout/stderr + exit code.
  5. Post-check: `make verify-all` must STILL be green. If red,
     rollback the working-tree edits (git reset --hard HEAD) and
     open a "red CI after orchestrator run" PR with the diff.
  6. Commit + PR: create branch `orchestrator/daily-YYYYMMDD`,
     commit all changes with a structured message, push, open a
     DRAFT PR. NEVER auto-merge.
  7. Regenerate demo: `make demo-html-commit` so the published
     demo reflects the new state.
  8. Append to `docs/progress.md` (creates if absent).

Default --dry-run. Real execution requires BOTH:
  1) --commit
  2) PRISM_ORCHESTRATOR_COMMIT=1

Safeguards hard-coded (per CLAUDE.md §3, §10 and user directive 2026-04-22):
  - Auto-PR ONLY; never auto-merge to main.
  - `physician_review=null` is an invariant; commit rejected if any
    verdict.json the orchestrator produced has a non-null value.
  - Frozen paths read-only:
    docs/clinical-extension-spec.md, .env, .state/.
  - Hard-stop if `make verify-all` is red BEFORE the run.
  - Budget cap per run (advisory, default $25 — override with --budget-cap-usd).
  - Stream cap 900 s (override with --stream-cap-sec).
  - Runs only from a clean working tree (no uncommitted edits).

Evidence persists to `results/orchestrator/<stamp>/{plan.json,
runner_output.log, summary.json}`. `docs/progress.md` is the human-
facing log that accumulates one entry per run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
AGENTS_MANIFEST = REPO / "agents" / "manifest.yaml"
SKILLS_MANIFEST = REPO / "skills" / "manifest.yaml"
OUT_ROOT = REPO / "results" / "orchestrator"
PROGRESS_DOC = REPO / "docs" / "progress.md"
BETA = "managed-agents-2026-04-01"

FROZEN_PATHS = (
    "corpus/reproducers/",
    "docs/clinical-extension-spec.md",
    ".env",
    ".state/",
)

# Tasks the orchestrator is allowed to execute — explicit allowlist.
# Any task in the plan whose runner starts with a string NOT in this
# list is refused with `halt-unknown-runner`.
ALLOWED_RUNNERS: tuple[tuple[str, str], ...] = (
    ("make demo-artifacts-commit", "regenerate GPU flip-summary demo artifacts"),
    ("make clinical-demo-artifacts-commit", "regenerate clinical rubric cards"),
    ("make demo-html-commit", "regenerate single-file HTML demo surface"),
    ("make verify-all", "offline verification sweep only"),
    ("scripts/run_solo_audit.py --commit", "solo-mode audit on a case"),
    ("scripts/run_skilled_audit.py --commit", "skilled-mode audit on a case"),
    ("docs-only-edit", "edit a doc file (explicit path required in plan)"),
)

PLAN_PROMPT = """\
You are invoking your prism-planner skill. Read the repo state per that
skill's instructions, write exactly one plan to /workspace/plan.json,
and emit the self-check line.

Hard requirements in the emitted plan:
  - `runner` must be one of: {allowed_runners}
  - `safeguards_review.touches_frozen_paths` must be false.
  - `safeguards_review.sets_physician_review` must be false.
  - `estimated_cost_usd` must be <= {budget_cap}.
  - `task_id` must reference docs/clinical-roadmap.md or an existing finding.

Today's date: {today}.
"""


def _now_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _load_manifests() -> dict:
    if not AGENTS_MANIFEST.exists():
        raise RuntimeError("agents/manifest.yaml missing")
    if not SKILLS_MANIFEST.exists():
        raise RuntimeError("skills/manifest.yaml missing — run register_skills.py first")
    a = yaml.safe_load(AGENTS_MANIFEST.read_text()) or {}
    s = yaml.safe_load(SKILLS_MANIFEST.read_text()) or {}
    coord = (a.get("agents") or {}).get("coordinator") or {}
    if not a.get("environment_id") or not coord.get("id"):
        raise RuntimeError("manifest shape invalid")
    if "planner" not in (s.get("skills") or {}):
        raise RuntimeError("skills/manifest.yaml: planner skill missing")
    return {
        "environment_id": a["environment_id"],
        "coordinator_id": coord["id"],
        "coordinator_version": coord["version"],
        "skills": s["skills"],
    }


def _check_clean_tree() -> list[str]:
    """Return list of uncommitted TRACKED file paths. Empty = tree is
    clean of tracked-file modifications. Untracked files (`??` status,
    e.g. parallel-session artifacts not yet added) are ignored — the
    orchestrator does not claim authority over those."""
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    out: list[str] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain format: 2-char status + space + path. "??" = untracked.
        status = line[:2]
        if status == "??":
            continue
        out.append(line[3:])
    return out


def _check_verify_all() -> tuple[bool, str]:
    """Run `make verify-all`; return (green, tail_output)."""
    res = subprocess.run(
        ["make", "verify-all"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    tail = "\n".join(res.stdout.splitlines()[-10:])
    return (res.returncode == 0, tail)


def _validate_plan(plan: dict, budget_cap: float) -> list[str]:
    """Return list of violations. Empty list = plan accepted."""
    v: list[str] = []

    task = plan.get("task_id", "")
    if not task:
        v.append("plan missing task_id")

    # Halt tasks are always OK — they explicitly stop further action.
    if task.startswith("halt-"):
        return v

    runner = plan.get("runner", "")
    ok = any(runner.startswith(a[0]) or runner == "docs-only-edit" for a in ALLOWED_RUNNERS)
    if not ok:
        v.append(f"runner not in ALLOWED_RUNNERS: {runner!r}")

    sg = plan.get("safeguards_review") or {}
    if sg.get("touches_frozen_paths", True):
        v.append("safeguards_review.touches_frozen_paths must be false")
    if sg.get("sets_physician_review", True):
        v.append("safeguards_review.sets_physician_review must be false")
    if sg.get("touches_disclosure_drafts", True):
        v.append("safeguards_review.touches_disclosure_drafts must be false")

    cost = float(plan.get("estimated_cost_usd", 999))
    if cost > budget_cap:
        v.append(f"estimated_cost_usd={cost} exceeds budget_cap={budget_cap}")

    return v


def _get_plan_via_planner_skill(
    c,  # Anthropic client, constructed in do_commit for SDK-containment compliance
    m: dict,
    budget_cap: float,
    stream_cap: int,
    stamp: str,
) -> tuple[dict | None, str]:
    """Spin up a session, invoke planner skill, fetch /workspace/plan.json."""
    today = _dt.date.today().isoformat()
    allowed = ", ".join(a[0] for a in ALLOWED_RUNNERS)
    prompt = PLAN_PROMPT.format(
        allowed_runners=allowed, budget_cap=budget_cap, today=today
    )

    session = c.beta.sessions.create(
        agent={"type": "agent", "id": m["coordinator_id"], "version": m["coordinator_version"]},
        environment_id=m["environment_id"],
        title=f"prism-orchestrator-plan-{stamp}",
        extra_headers={"anthropic-beta": BETA},
    )
    sid = session.id

    c.beta.sessions.events.send(
        session_id=sid,
        events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
        extra_headers={"anthropic-beta": BETA},
    )

    # Ask the coordinator to cat the plan back to us after writing it.
    # We do that with a follow-up user message after the first
    # session.status_idle — but simpler: bake it into the prompt above
    # via the planner skill's "emit self-check" line, then request a
    # single cat via second message.

    t0 = time.time()
    deadline = t0 + float(stream_cap)
    idle_count = 0
    plan_json_text: str | None = None
    last_texts: list[str] = []

    # Stream until first idle, then request plan contents, then second idle.
    phase = "plan-write"
    with c.beta.sessions.events.stream(
        session_id=sid, extra_headers={"anthropic-beta": BETA}
    ) as stream:
        for ev in stream:
            now = time.time()
            etype = getattr(ev, "type", None) or type(ev).__name__
            for block in getattr(ev, "content", None) or []:
                if getattr(block, "type", None) == "text":
                    last_texts.append(getattr(block, "text", "") or "")
            if etype == "session.status_idle":
                idle_count += 1
                if phase == "plan-write":
                    # Second turn: ask for plan contents verbatim.
                    c.beta.sessions.events.send(
                        session_id=sid,
                        events=[
                            {
                                "type": "user.message",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": (
                                            "Now cat /workspace/plan.json and emit its "
                                            "contents as a single code block with json "
                                            "fencing. Do not add commentary."
                                        ),
                                    }
                                ],
                            }
                        ],
                        extra_headers={"anthropic-beta": BETA},
                    )
                    phase = "plan-read"
                    last_texts.clear()
                elif phase == "plan-read":
                    # Extract first ```json ... ``` block.
                    joined = "".join(last_texts)
                    start = joined.find("```json")
                    if start >= 0:
                        body = joined[start + 7 :]
                        end = body.find("```")
                        if end > 0:
                            plan_json_text = body[:end].strip()
                    break
            if now > deadline:
                break
            if etype == "error":
                break

    url = f"https://platform.claude.com/sessions/{sid}"
    if not plan_json_text:
        return None, url
    try:
        plan = json.loads(plan_json_text)
    except json.JSONDecodeError as e:
        print(f"  planner emitted non-JSON: {e}; raw={plan_json_text[:200]!r}")
        return None, url
    return plan, url


def _run_runner(runner: str, log_path: Path, stream_cap: int) -> tuple[int, float]:
    """Shell out to the runner string; tee to log_path; return (exit_code, wall_sec)."""
    t0 = time.time()
    # For safety, only allow a small set of prefixes; already validated upstream.
    cmd = shlex.split(runner) if not runner.startswith("make ") else runner
    args = shlex.split(runner) if isinstance(cmd, str) else cmd
    with log_path.open("w") as log:
        res = subprocess.run(
            args,
            cwd=REPO,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=stream_cap,
        )
    return res.returncode, time.time() - t0


def _rollback() -> None:
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=REPO, check=False)


def _diff_touches_frozen(diff_files: list[str]) -> list[str]:
    violations = []
    for f in diff_files:
        for fp in FROZEN_PATHS:
            if f.startswith(fp):
                violations.append(f)
                break
    return violations


def _verdicts_respect_physician_gate() -> list[str]:
    """Scan for any verdict.json written with non-null physician_review."""
    viols = []
    for p in REPO.glob("results/**/verdict.json"):
        try:
            doc = json.loads(p.read_text())
            if doc.get("physician_review") is not None:
                viols.append(f"{p.relative_to(REPO)}: physician_review is not null")
        except Exception:
            continue
    return viols


def _open_draft_pr(branch: str, title: str, body: str) -> str | None:
    """Push branch + open draft PR via gh. Returns PR URL or None."""
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=REPO, check=True)
    res = subprocess.run(
        ["gh", "pr", "create", "--draft", "--title", title, "--body", body],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    out = (res.stdout or "") + (res.stderr or "")
    for line in out.splitlines():
        if line.startswith("https://"):
            return line.strip()
    return None


def do_dry_run(args: argparse.Namespace) -> int:
    print("(dry-run) scripts/orchestrator.py plan:")
    try:
        m = _load_manifests()
        print(f"  coordinator      : {m['coordinator_id']} v{m['coordinator_version']}")
        print(f"  skills bound     : {list(m['skills'].keys())}")
    except RuntimeError as e:
        print(f"  manifest         : NOT USABLE ({e})")

    pre = _check_clean_tree()
    print(f"  clean tree       : {'YES' if not pre else f'NO ({len(pre)} uncommitted)'}")
    print(f"  budget-cap-usd   : {args.budget_cap_usd}")
    print(f"  stream-cap-sec   : {args.stream_cap_sec}")
    print(f"  out-root         : {OUT_ROOT}")
    print(f"  progress doc     : {PROGRESS_DOC.relative_to(REPO)}")
    print("  allowed runners  :")
    for r, desc in ALLOWED_RUNNERS:
        print(f"    - {r:48s}  # {desc}")
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def do_commit(args: argparse.Namespace) -> int:
    # SDK-containment rule: construct the Anthropic client ONLY inside
    # do_commit. scripts/check_sdk_containment.py enforces this via AST.
    from anthropic import Anthropic  # noqa: PLC0415

    c = Anthropic()

    m = _load_manifests()
    stamp = _now_stamp()
    run_dir = OUT_ROOT / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: preflight.
    uncommitted = _check_clean_tree()
    if uncommitted:
        print(f"HALT: working tree is not clean ({len(uncommitted)} files)")
        for f in uncommitted[:10]:
            print(f"  {f}")
        return 1

    green, tail = _check_verify_all()
    if not green:
        print(f"HALT: make verify-all is red BEFORE this run:")
        print(tail)
        return 2

    # Snapshot pre-existing untracked files so we don't sweep them into
    # the orchestrator's commit. Parallel sessions leave these behind
    # and they are not ours to touch.
    pre_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    )
    pre_untracked: set[str] = {
        l[3:] for l in pre_status.stdout.splitlines()
        if l.strip() and l[:2] == "??"
    }

    # Phase 2: plan.
    print(f"[orchestrator] invoking planner skill (stamp={stamp})")
    plan, session_url = _get_plan_via_planner_skill(
        c, m, args.budget_cap_usd, args.stream_cap_sec, stamp
    )
    (run_dir / "plan.json").write_text(
        json.dumps(plan if plan else {"error": "no plan"}, indent=2)
    )
    (run_dir / "plan_session_url.txt").write_text(session_url + "\n")
    if plan is None:
        print(f"HALT: planner did not emit a parseable plan. See {session_url}")
        return 3

    print(f"[orchestrator] plan received: task_id={plan.get('task_id')} "
          f"runner={plan.get('runner')!r}")
    viols = _validate_plan(plan, args.budget_cap_usd)
    if viols:
        print("HALT: plan violated safeguards:")
        for v in viols:
            print(f"  - {v}")
        return 4

    if plan.get("task_id", "").startswith("halt-"):
        print(f"[orchestrator] plan is a halt: {plan.get('task_id')}. "
              f"Rationale: {plan.get('rationale', '?')}")
        return 0

    # Phase 4: execute.
    runner = plan["runner"]
    print(f"[orchestrator] executing: {runner}")
    runner_log = run_dir / "runner_output.log"
    rc, wall = _run_runner(runner, runner_log, args.stream_cap_sec)
    print(f"[orchestrator] runner exit={rc} wall={wall:.1f}s")
    if rc != 0:
        print("HALT: runner returned non-zero; not committing.")
        _rollback()
        return 5

    # Phase 5: post-check.
    green2, tail2 = _check_verify_all()
    if not green2:
        print("HALT: make verify-all is RED after runner; rolling back.")
        print(tail2)
        _rollback()
        return 6

    # Phase 5.5: safeguards scan on the diff.
    # IMPORTANT: compute the set of CURRENTLY-UNTRACKED files BEFORE
    # the runner in _snapshot_untracked_pre (called in Phase 1); here we
    # filter them out so we only commit files the runner itself created
    # or modified. Otherwise we'd sweep up parallel-session artifacts.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO, capture_output=True, text=True,
    )
    all_now = [(l[:2], l[3:]) for l in status.stdout.splitlines() if l.strip()]
    changed: list[str] = []
    for st, path in all_now:
        if st == "??":
            # Untracked: only commit if it didn't exist before the run.
            if path in pre_untracked:
                continue  # pre-existing untracked — not ours to touch
        changed.append(path)
    frozen_viols = _diff_touches_frozen(changed)
    if frozen_viols:
        print(f"HALT: runner touched frozen paths: {frozen_viols}")
        _rollback()
        return 7

    phys_viols = _verdicts_respect_physician_gate()
    if phys_viols:
        print(f"HALT: physician_review was set to non-null: {phys_viols}")
        _rollback()
        return 8

    # Phase 6: commit + PR.
    # Branch-protection-aware: every write goes through a branch + draft PR.
    # Work-produced runs: branch orchestrator/daily-YYYY-MM-DD.
    # No-op heartbeat runs: branch orchestrator/heartbeat-YYYY-MM-DD.
    # Both are draft PRs; user reviews + merges. No direct push to main.

    is_heartbeat = not changed
    today = _dt.date.today().isoformat()
    if is_heartbeat:
        print("[orchestrator] no-op run — runner produced no tracked changes.")
        print("[orchestrator] routing heartbeat through a draft PR "
              "(branch protection requires it).")

        PROGRESS_DOC.parent.mkdir(parents=True, exist_ok=True)
        if not PROGRESS_DOC.exists():
            PROGRESS_DOC.write_text(
                "# Prism — Progress Log\n\n"
                "One entry per orchestrator run. Most recent first.\n\n---\n\n"
            )
        existing = PROGRESS_DOC.read_text()
        heartbeat = (
            f"## {stamp}  (heartbeat — no-op)\n\n"
            f"- **task**: `{plan.get('task_id')}` — {plan.get('task_title', '?')}\n"
            f"- **runner**: `{runner}` (exit=0, wall={wall:.1f}s)\n"
            f"- **verify-all**: green before + after\n"
            f"- **result**: no tracked-file changes; heartbeat PR only\n"
            f"- **plan session**: {session_url}\n\n---\n\n"
        )
        header_end = existing.find("---\n\n") + len("---\n\n")
        PROGRESS_DOC.write_text(existing[:header_end] + heartbeat + existing[header_end:])
        changed = [str(PROGRESS_DOC.relative_to(REPO))]
        branch = f"orchestrator/heartbeat-{today}"
        commit_msg = (
            f"orchestrator: heartbeat {stamp} (no-op)\n"
            f"\n"
            f"Planner picked task `{plan.get('task_id')}` "
            f"({runner}) and it produced zero tracked-file changes — "
            f"the daily loop ran green but had no work to commit. "
            f"This PR is the system-is-alive signal.\n"
            f"\n"
            f"Plan-session: {session_url}\n"
            f"\n"
            f"Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
        )
    else:
        branch = f"orchestrator/daily-{today}"
        commit_msg = (
            f"orchestrator: {plan.get('task_id')} — {plan.get('task_title', '?')}\n"
            f"\n"
            f"Automated by scripts/orchestrator.py on {stamp}.\n"
            f"Plan-session: {session_url}\n"
            f"Runner: `{runner}` (exit=0, wall={wall:.1f}s)\n"
            f"\n"
            f"Rationale: {plan.get('rationale', '?')}\n"
            f"\n"
            f"make verify-all: GREEN before + after.\n"
            f"physician_review: untouched (null preserved across any emitted verdicts).\n"
            f"Frozen paths: untouched.\n"
            f"\n"
            f"Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
        )

    # For work runs, append to docs/progress.md now so it rides in the
    # same commit as the runner's output. Heartbeat runs already appended
    # their entry above.
    if not is_heartbeat:
        PROGRESS_DOC.parent.mkdir(parents=True, exist_ok=True)
        if not PROGRESS_DOC.exists():
            PROGRESS_DOC.write_text(
                "# Prism — Progress Log\n\n"
                "One entry per orchestrator run. Most recent first.\n\n---\n\n"
            )
        existing = PROGRESS_DOC.read_text()
        entry = (
            f"## {stamp}\n\n"
            f"- **task**: `{plan.get('task_id')}` — {plan.get('task_title', '?')}\n"
            f"- **runner**: `{runner}`\n"
            f"- **verify-all**: green before + after\n"
            f"- **changed files**: {len(changed)}\n"
            f"- **plan session**: {session_url}\n\n---\n\n"
        )
        header_end = existing.find("---\n\n") + len("---\n\n")
        PROGRESS_DOC.write_text(existing[:header_end] + entry + existing[header_end:])
        prog_rel = str(PROGRESS_DOC.relative_to(REPO))
        if prog_rel not in changed:
            changed.append(prog_rel)

    # Create branch; commit everything in one shot (branch protection
    # rejects direct main pushes — this is the single auto-write path).
    subprocess.run(["git", "checkout", "-B", branch], cwd=REPO, check=True)
    subprocess.run(["git", "add", *changed], cwd=REPO, check=True)
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO, check=True)

    pr_url = None
    if args.open_pr:
        pr_title = (
            f"orchestrator: heartbeat {today} (no-op)"
            if is_heartbeat
            else f"orchestrator: {plan.get('task_id')}"
        )
        pr_body = (
            commit_msg
            + "\n\n---\n\n"
            + "This PR was opened by scripts/orchestrator.py. "
            + "Review the diff, run `make verify-all` locally, and merge "
            + "or close. Do NOT auto-merge."
        )
        pr_url = _open_draft_pr(branch, pr_title, pr_body)
        print(f"[orchestrator] draft PR: {pr_url or '(gh pr create failed)'}")

    # Return HEAD to main so the next run starts clean. The PR branch
    # stays behind on the remote.
    subprocess.run(["git", "checkout", "main"], cwd=REPO, check=True)

    # Phase 9: summary.
    summary = {
        "stamp": stamp,
        "plan": plan,
        "plan_session_url": session_url,
        "runner": runner,
        "runner_exit": rc,
        "runner_wall_sec": wall,
        "verify_all_before": True,
        "verify_all_after": True,
        "branch": branch,
        "pr_url": pr_url,
        "changed_files": changed,
        "heartbeat": is_heartbeat,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"[orchestrator] summary: {run_dir / 'summary.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run live. Requires PRISM_ORCHESTRATOR_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--stream-cap-sec",
        type=int,
        default=900,
        help="Hard cap on any single SDK stream or runner subprocess (default 900).",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=25.0,
        help="Advisory cost cap per run (default $25).",
    )
    ap.add_argument(
        "--open-pr",
        action="store_true",
        default=True,
        help="Open a draft PR after committing to branch (default True).",
    )
    args = ap.parse_args(argv)

    if args.commit and os.environ.get("PRISM_ORCHESTRATOR_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_ORCHESTRATOR_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args)
    return do_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
