"""Tests for scripts/orchestrator.py.

Offline-only. Tests the double-gate, the ALLOWED_RUNNERS allowlist,
the plan-validation logic, and the frozen-path / physician-review
safeguards. Does NOT invoke the live Anthropic API (the live live-run
evidence is in findings/ + results/orchestrator/ on disk).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "orchestrator.py"

sys.path.insert(0, str(REPO / "scripts"))
import orchestrator as orch  # noqa: E402


# --------------------------------------------------------------------------- #
# Double-gate                                                                 #
# --------------------------------------------------------------------------- #


def _run_cli(*extra: str, env_present: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PRISM_ORCHESTRATOR_COMMIT", None)
    if env_present:
        env["PRISM_ORCHESTRATOR_COMMIT"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_dry_run_exits_zero_and_prints_plan() -> None:
    res = _run_cli()
    assert res.returncode == 0, res.stderr
    assert "(dry-run)" in res.stdout
    assert "allowed runners" in res.stdout
    # Dry-run must NOT contact the network / SDK.
    assert "no network activity" in res.stdout


def test_commit_without_env_refuses() -> None:
    res = _run_cli("--commit", env_present=False)
    assert res.returncode == 1
    assert "refusing" in res.stderr
    assert "PRISM_ORCHESTRATOR_COMMIT=1" in res.stderr


def test_env_without_commit_stays_dry_run() -> None:
    res = _run_cli(env_present=True)
    assert res.returncode == 0
    assert "(dry-run)" in res.stdout


def test_help_renders() -> None:
    res = _run_cli("--help")
    assert res.returncode == 0
    assert "orchestrator" in res.stdout.lower()


# --------------------------------------------------------------------------- #
# Plan validation                                                             #
# --------------------------------------------------------------------------- #


def _valid_plan() -> dict:
    return {
        "plan_date": "2026-04-22",
        "day_in_week": "Day 1",
        "task_id": "T-maintenance",
        "task_title": "Regenerate demo artifacts",
        "rail": "infra",
        "runner": "make demo-html-commit",
        "expected_artifacts": ["results/demo/index.html"],
        "estimated_minutes": 5,
        "estimated_cost_usd": 0.0,
        "safeguards_review": {
            "touches_frozen_paths": False,
            "touches_disclosure_drafts": False,
            "sets_physician_review": False,
            "requires_human_in_loop": False,
        },
        "rationale": "Demo freshness per planner heuristic.",
        "fallback_if_blocked": "halt-demo",
        "cancel_criteria": "demo already regenerated in last hour",
    }


def test_validate_plan_happy() -> None:
    assert orch._validate_plan(_valid_plan(), budget_cap=25.0) == []


def test_validate_plan_rejects_unknown_runner() -> None:
    plan = _valid_plan()
    plan["runner"] = "rm -rf /"
    viols = orch._validate_plan(plan, 25.0)
    assert any("runner not in ALLOWED_RUNNERS" in v for v in viols)


def test_validate_plan_rejects_frozen_path() -> None:
    plan = _valid_plan()
    plan["safeguards_review"]["touches_frozen_paths"] = True
    viols = orch._validate_plan(plan, 25.0)
    assert any("touches_frozen_paths" in v for v in viols)


def test_validate_plan_rejects_physician_review_change() -> None:
    plan = _valid_plan()
    plan["safeguards_review"]["sets_physician_review"] = True
    viols = orch._validate_plan(plan, 25.0)
    assert any("sets_physician_review" in v for v in viols)


def test_validate_plan_rejects_disclosure_draft_touch() -> None:
    plan = _valid_plan()
    plan["safeguards_review"]["touches_disclosure_drafts"] = True
    viols = orch._validate_plan(plan, 25.0)
    assert any("touches_disclosure_drafts" in v for v in viols)


def test_validate_plan_rejects_overbudget() -> None:
    plan = _valid_plan()
    plan["estimated_cost_usd"] = 100.0
    viols = orch._validate_plan(plan, 25.0)
    assert any("exceeds budget_cap" in v for v in viols)


def test_validate_plan_accepts_halt_tasks() -> None:
    """Halt tasks explicitly stop further action — always accepted."""
    for task_id in ("halt-frozen-path", "halt-needs-new-code",
                    "halt-scope-too-large", "halt-ambiguous"):
        plan = _valid_plan()
        plan["task_id"] = task_id
        # halt tasks may legitimately omit runner / trigger a non-allowlisted runner
        plan["runner"] = ""
        assert orch._validate_plan(plan, 25.0) == [], f"halt task {task_id} should be accepted"


def test_validate_plan_missing_task_id() -> None:
    plan = _valid_plan()
    plan["task_id"] = ""
    viols = orch._validate_plan(plan, 25.0)
    assert any("missing task_id" in v for v in viols)


# --------------------------------------------------------------------------- #
# Safeguard helpers                                                           #
# --------------------------------------------------------------------------- #


def test_frozen_path_detection() -> None:
    diff = [
        "scripts/run_solo_audit.py",                   # allowed
        "corpus/reproducers/EXAMPLE-BUG.py",            # FROZEN
        "docs/clinical-extension-spec.md",             # FROZEN
        ".env",                                         # FROZEN
        "corpus/example-bugs.yaml",                     # allowed (not in frozen list)
    ]
    viols = orch._diff_touches_frozen(diff)
    assert "corpus/reproducers/EXAMPLE-BUG.py" in viols
    assert "docs/clinical-extension-spec.md" in viols
    assert ".env" in viols
    assert "scripts/run_solo_audit.py" not in viols
    assert "corpus/example-bugs.yaml" not in viols


def test_allowed_runners_are_nonempty() -> None:
    """Regression: the allowlist must be populated."""
    assert len(orch.ALLOWED_RUNNERS) >= 5
    for runner, desc in orch.ALLOWED_RUNNERS:
        assert runner
        assert desc


# --------------------------------------------------------------------------- #
# SDK containment — the do_commit path must be the only anthropic import      #
# --------------------------------------------------------------------------- #


def test_sdk_import_only_inside_do_commit() -> None:
    """The `from anthropic import ...` must NOT be at module scope. The
    live SDK import only happens inside do_commit()."""
    text = SCRIPT.read_text()
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("from anthropic", "import anthropic")):
            # must be indented (inside a function)
            assert line.startswith((" ", "\t")), (
                f"{SCRIPT.name}:{i}: anthropic import at module scope"
            )


# --------------------------------------------------------------------------- #
# CI workflow presence                                                         #
# --------------------------------------------------------------------------- #


def test_daily_orchestrator_workflow_exists() -> None:
    wf = REPO / ".github" / "workflows" / "daily-orchestrator.yml"
    assert wf.exists(), "daily-orchestrator.yml is the GitHub-Actions cron"
    text = wf.read_text()
    # Critical invariants of the workflow
    assert "cron:" in text
    assert "PRISM_ORCHESTRATOR_COMMIT" in text
    assert "ANTHROPIC_API_KEY" in text
    assert "permissions:" in text
    assert "contents: write" in text
    assert "pull-requests: write" in text
    assert "workflow_dispatch" in text
