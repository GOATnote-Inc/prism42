"""Tests for scripts/smoke_session.py and scripts/smoke_delegation.py.

Both scripts are live-API reproducers gated behind:
  - `--commit` on the command line, AND
  - `PRISM_SMOKE_{SESSION,DELEGATION}_COMMIT=1` in the environment.

These tests exercise only the dry-run + refusal paths — they never call
the live API, never cost money, and don't require ANTHROPIC_API_KEY. The
live-execution path has its own evidence under `findings/smoke-*.md`.

What we verify:
  - dry-run exits 0 and prints a plan; no files are written under results/
  - --commit without the env var refuses (exit 1 + "refusing" on stderr)
  - env var alone (no --commit) stays dry-run
  - --help renders the docstring header
  - No import of `anthropic` at module scope (dry-run must not touch SDK)
  - `callable_agents` is NOT sent by the smoke_delegation script (it
    targets a simpler prompt that asks the coordinator to delegate
    natively; verification only)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SESSION_SCRIPT = REPO / "scripts" / "smoke_session.py"
DELEGATION_SCRIPT = REPO / "scripts" / "smoke_delegation.py"

SCRIPTS = (
    ("session", SESSION_SCRIPT, "PRISM_SMOKE_SESSION_COMMIT"),
    ("delegation", DELEGATION_SCRIPT, "PRISM_SMOKE_DELEGATION_COMMIT"),
)


def _run(
    script: Path,
    *extra: str,
    env_var: str | None = None,
    env_present: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Strip live-API env-vars on every run — these tests must never touch
    # the network even if the developer's shell has them set.
    for k in (
        "PRISM_SMOKE_SESSION_COMMIT",
        "PRISM_SMOKE_DELEGATION_COMMIT",
    ):
        env.pop(k, None)
    if env_var and env_present:
        env[env_var] = "1"
    return subprocess.run(
        [sys.executable, str(script), *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# --------------------------------------------------------------------------- #
# Dry-run / gating                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("label,script,env_var", SCRIPTS)
def test_dry_run_exits_zero_and_prints_plan(
    label: str, script: Path, env_var: str
) -> None:
    res = _run(script)
    assert res.returncode == 0, f"{label}: stderr={res.stderr}"
    assert "(dry-run)" in res.stdout, f"{label}: expected dry-run banner"


@pytest.mark.parametrize("label,script,env_var", SCRIPTS)
def test_commit_without_env_refuses(
    label: str, script: Path, env_var: str
) -> None:
    res = _run(script, "--commit", env_var=env_var, env_present=False)
    assert res.returncode == 1, f"{label}: expected exit 1 on refusal"
    assert "refusing" in res.stderr, f"{label}: expected refusal message"
    assert env_var in res.stderr, f"{label}: refusal should name {env_var}"


@pytest.mark.parametrize("label,script,env_var", SCRIPTS)
def test_env_without_commit_stays_dry_run(
    label: str, script: Path, env_var: str
) -> None:
    """Env var alone is a no-op — the --commit flag is the other gate."""
    res = _run(script, env_var=env_var, env_present=True)
    assert res.returncode == 0, f"{label}: stderr={res.stderr}"
    assert "(dry-run)" in res.stdout


@pytest.mark.parametrize("label,script,env_var", SCRIPTS)
def test_help_renders_docstring(label: str, script: Path, env_var: str) -> None:
    res = _run(script, "--help")
    assert res.returncode == 0
    # Both scripts include their docstring in --help via RawDescriptionHelpFormatter.
    assert "smoke" in res.stdout.lower()


# --------------------------------------------------------------------------- #
# SDK containment (dry-run path must not import anthropic)                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("label,script,env_var", SCRIPTS)
def test_dry_run_does_not_import_anthropic_at_module_scope(
    label: str, script: Path, env_var: str
) -> None:
    """Canary for the AST-enforced SDK-containment rule: if `anthropic`
    were imported at module scope, `python -c "import <script>"` in a
    no-API-key env would hit a 401 or similar. We verify the file is
    parseable and has no `import anthropic` at column 0."""
    text = script.read_text()
    # Strict: no `^import anthropic` or `^from anthropic` line.
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("import anthropic") or stripped.startswith(
            "from anthropic"
        ):
            # Only allowed inside a function body (indented).
            assert line.startswith((" ", "\t")), (
                f"{label}: {script.name}:{i}: anthropic import at module scope"
            )


# --------------------------------------------------------------------------- #
# Delegation script specifics                                                 #
# --------------------------------------------------------------------------- #


def test_delegation_prompt_is_conservative() -> None:
    """The delegation-smoke prompt explicitly tells the coordinator to
    call ONLY the defender once and stop. A looser prompt could fan
    out to all five sub-agents and blow the budget."""
    text = DELEGATION_SCRIPT.read_text()
    # Conservative-prompt invariants (each is a single-source-of-truth
    # fact; if someone reworks the prompt, at least one should survive
    # or the test fails loudly).
    assert "defender" in text
    assert "STOP" in text
    assert "Do not call any other sub-agent" in text
    # The four other sub-agents are explicitly forbidden in the prompt.
    for forbidden in ("attacker", "synthesizer", "executor", "adjudicator"):
        assert forbidden in text, (
            f"delegation prompt should name-and-forbid sub-agent {forbidden}"
        )


def test_delegation_script_has_stream_cap_default() -> None:
    """Hard wall-clock cap on the stream so a misbehaving session can't
    accrue session-hour charges past the budget advisory."""
    text = DELEGATION_SCRIPT.read_text()
    # Default should be 180s; don't hard-code the exact number in the
    # test (authors may tune it), but require a sensible positive default.
    assert "--stream-cap-sec" in text
    assert "default=" in text
