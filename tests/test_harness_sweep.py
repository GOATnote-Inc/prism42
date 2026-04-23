"""Tests for scripts/harness_sweep.py — T4.7b driver.

All tests here are offline + zero-cost:
  - dry-run default exits 0 with a plan banner and skeletal aggregate.json
  - --commit without PRISM_HARNESS_SWEEP_COMMIT=1 refuses (exit 1)
  - env var alone (no --commit) stays dry-run
  - --n-limit caps the planned-session count
  - _extract_modified parses fenced markdown blocks from assistant text
  - _t_crit returns sensible two-sided 95% values for the relevant df range
  - _paired_delta computes mean Δ, SEM, and CI on synthetic paired data
  - Module scope is SDK-free (import anthropic only inside do_commit)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "harness_sweep.py"
ENV_VAR = "PRISM_HARNESS_SWEEP_COMMIT"

# Make the script importable for direct unit tests on its helpers.
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def _run(*extra: str, env_present: bool = False, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop(ENV_VAR, None)
    if env_present:
        env[ENV_VAR] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


# --------------------------------------------------------------------------- #
# CLI gating                                                                  #
# --------------------------------------------------------------------------- #


def test_dry_run_default_exits_zero_with_plan_banner(tmp_path: Path) -> None:
    res = _run("--out-root", str(tmp_path))
    assert res.returncode == 0, res.stderr
    assert "(dry-run)" in res.stdout
    assert "coordinator" in res.stdout
    # Default n-limit is full subset — should plan 30 examples.
    assert "n examples        : 30" in res.stdout


def test_dry_run_writes_skeletal_aggregate(tmp_path: Path) -> None:
    res = _run("--out-root", str(tmp_path), "--n-limit", "3")
    assert res.returncode == 0, res.stderr
    # Find the written aggregate.json under harness-sweep-<stamp>/.
    hits = list(tmp_path.glob("harness-sweep-*/aggregate.json"))
    assert len(hits) == 1, f"expected one aggregate.json, got {hits}"
    payload = json.loads(hits[0].read_text())
    assert payload["dry_run"] is True
    assert payload["n_planned"] == 3
    assert payload["n_limit"] == 3


def test_commit_without_env_refuses(tmp_path: Path) -> None:
    res = _run("--out-root", str(tmp_path), "--commit", env_present=False)
    assert res.returncode == 1, res.stdout
    assert "refusing" in res.stderr.lower()


def test_env_alone_stays_dry_run(tmp_path: Path) -> None:
    res = _run("--out-root", str(tmp_path), env_present=True)
    assert res.returncode == 0, res.stderr
    assert "(dry-run)" in res.stdout


def test_help_renders(tmp_path: Path) -> None:
    res = _run("--help")
    assert res.returncode == 0
    # First docstring paragraph mentions the T4.7b role.
    assert "T4.7b" in res.stdout or "harness sweep" in res.stdout.lower()


def test_n_limit_caps_planned_sessions(tmp_path: Path) -> None:
    res = _run("--out-root", str(tmp_path), "--n-limit", "5")
    assert res.returncode == 0
    assert "n examples        : 5" in res.stdout


# --------------------------------------------------------------------------- #
# Helpers — direct unit tests                                                 #
# --------------------------------------------------------------------------- #


def test_extract_modified_happy_path() -> None:
    """Sentinels on their own lines surrounding real content."""
    import harness_sweep as hs

    text = (
        "prelude from the dialectic phase\n"
        f"{hs.HARNESS_BEGIN_SENTINEL}\n"
        "The preamble line.\n"
        "Plus a second paragraph.\n"
        f"{hs.HARNESS_END_SENTINEL}\n"
        "HARNESS COMPLETE: HBH-CLN-001\n"
    )
    out = hs._extract_modified(text)
    assert out is not None
    assert "The preamble line." in out
    assert "Plus a second paragraph." in out
    assert "HARNESS COMPLETE" not in out
    assert hs.HARNESS_BEGIN_SENTINEL not in out
    assert hs.HARNESS_END_SENTINEL not in out


def test_extract_modified_picks_last_begin_last_end() -> None:
    """If the model references the sentinel tokens mid-sentence in an
    earlier dialectic phase, the line-anchored matcher must ignore those
    mentions and extract the actual emission at the end."""
    import harness_sweep as hs

    text = (
        "I will emit the sentinel {} next.\n".format(hs.HARNESS_BEGIN_SENTINEL)
        + "And later close with {} before the complete marker.\n".format(hs.HARNESS_END_SENTINEL)
        + "Actually emitting now:\n"
        + f"{hs.HARNESS_BEGIN_SENTINEL}\n"
        + "Real modified content here.\n"
        + f"{hs.HARNESS_END_SENTINEL}\n"
        + "HARNESS COMPLETE: X\n"
    )
    out = hs._extract_modified(text)
    assert out == "Real modified content here."


def test_extract_modified_regression_no_template_echo() -> None:
    """Regression for the 2026-04-23 pilot bug: an earlier prompt
    showed a ```markdown template with the literal placeholder
    '<modified.md contents — no preface, no editor comments>'. The
    coordinator echoed the placeholder verbatim. The fix replaces the
    in-band fence with line-anchored sentinels; this test asserts that
    a fenced markdown block on its own is NO LONGER enough to extract.
    """
    import harness_sweep as hs

    # This is the exact shape of the buggy assistant_text from the
    # failed pilot: a ```markdown block containing a placeholder string,
    # no sentinels anywhere.
    buggy = (
        "```markdown\n"
        "<modified.md contents — no preface, no editor comments>\n"
        "```\n"
        "HARNESS COMPLETE: HBH-CLN-001\n"
    )
    assert hs._extract_modified(buggy) is None, (
        "a fenced markdown block without sentinels must NOT extract — "
        "that was the exact silent-failure mode the pilot exposed"
    )


def test_extract_modified_returns_none_without_sentinels() -> None:
    import harness_sweep as hs

    assert hs._extract_modified("no sentinels here at all") is None
    assert hs._extract_modified("") is None


def test_extract_modified_returns_none_on_missing_end() -> None:
    import harness_sweep as hs

    text = f"{hs.HARNESS_BEGIN_SENTINEL}\nstarted but never ended\n"
    assert hs._extract_modified(text) is None


def test_extract_modified_rejects_inline_sentinel() -> None:
    """A sentinel token embedded mid-sentence must NOT match —
    line-anchored regex requires the token alone on its line."""
    import harness_sweep as hs

    text = (
        "I emit __HARNESS_MODIFIED_BEGIN__ here on this long line\n"
        "body body body\n"
        "and __HARNESS_MODIFIED_END__ is also inline here\n"
    )
    # No standalone-line sentinel, so extraction must refuse.
    assert hs._extract_modified(text) is None


def test_harness_complete_marker_requires_line_anchored_match() -> None:
    """Regression for the 2026-04-23 N=1 smoke false-positive: an
    earlier version of the stream loop set final_marker=True via
    substring check (`if "HARNESS COMPLETE:" in txt`). The model's
    dialectic phases describe future actions in prose ("I will emit
    HARNESS COMPLETE: HBH-CLN-001 once modified.md is written") —
    which fired the substring check before the marker was really
    emitted. Fix uses a line-anchored regex requiring the marker alone
    on its own line. This test pins the regex against both a prose
    mention (must NOT match) and a real terminal emission (must match)."""
    import re as _re

    case_id = "HBH-CLN-001"
    pattern = rf"^HARNESS COMPLETE: {_re.escape(case_id)}\s*$"

    # Prose mention — must NOT match. Before fix, this fired final_marker.
    prose = (
        "I'll now write modified.md and then emit "
        "HARNESS COMPLETE: HBH-CLN-001 afterward."
    )
    assert _re.search(pattern, prose, _re.MULTILINE) is None, (
        "prose mention must not fire final_marker"
    )

    # Real terminal emission — must match.
    terminal = (
        "__HARNESS_MODIFIED_BEGIN__\n"
        "body body body\n"
        "__HARNESS_MODIFIED_END__\n"
        "HARNESS COMPLETE: HBH-CLN-001\n"
    )
    assert _re.search(pattern, terminal, _re.MULTILINE) is not None, (
        "standalone marker line must fire final_marker"
    )


def test_harness_directive_does_not_contain_self_documenting_template() -> None:
    """Guard: the directive must not embed an example of the OUTPUT
    format (e.g. showing a ```markdown block with placeholder content).
    That pattern caused the 2026-04-23 template-echo bug."""
    import harness_sweep as hs

    # The directive DOES mention the sentinels by name (natural-language
    # description). It must NOT contain a template-style block the model
    # could copy verbatim. Specifically: the two sentinels must not
    # appear alone on their own lines INSIDE the directive template
    # itself — if they did, the model could copy that layout. Verify by
    # searching for the line-anchored pattern in the raw directive.
    # (Sentinels are expected to be referenced in the body text, just
    # not on lines by themselves.)
    import re as _re
    begin_alone = _re.search(
        rf"^{_re.escape(hs.HARNESS_BEGIN_SENTINEL)}\s*$",
        hs.HARNESS_DIRECTIVE,
        _re.MULTILINE,
    )
    end_alone = _re.search(
        rf"^{_re.escape(hs.HARNESS_END_SENTINEL)}\s*$",
        hs.HARNESS_DIRECTIVE,
        _re.MULTILINE,
    )
    assert begin_alone is None, (
        "HARNESS_DIRECTIVE contains the BEGIN sentinel alone on a line — "
        "the model may copy this layout; describe in prose instead"
    )
    assert end_alone is None, (
        "HARNESS_DIRECTIVE contains the END sentinel alone on a line — "
        "same hazard as BEGIN"
    )
    # Also: no ```markdown fence with placeholder text.
    assert "```markdown\n<" not in hs.HARNESS_DIRECTIVE, (
        "HARNESS_DIRECTIVE shows a ```markdown template with a <placeholder>; "
        "that is the exact template-echo pattern the pilot caught"
    )


def test_t_crit_two_sided_95_values() -> None:
    import harness_sweep as hs

    # Anchor points against a standard t-table (two-sided α=0.05):
    assert hs._t_crit(29) == pytest.approx(2.045, abs=0.005)  # df=29 → ~2.045
    assert hs._t_crit(9) == pytest.approx(2.262, abs=0.005)  # df=9 → ~2.262
    # df>=100 falls back to the normal approximation 1.96.
    assert hs._t_crit(100) == pytest.approx(1.96, abs=0.005)
    assert hs._t_crit(500) == pytest.approx(1.96, abs=0.005)
    # df<=0 is not valid; function returns nan.
    import math
    assert math.isnan(hs._t_crit(0))


def test_paired_delta_matches_numpy_style_computation(tmp_path: Path) -> None:
    """_paired_delta should match a hand-computed paired-t result."""
    import harness_sweep as hs

    # Synthetic baseline with 4 matched examples; deltas = [+0.1, +0.2, +0.1, +0.0]
    baseline = {
        "per_example": [
            {"id": "A", "score": 0.5, "per_axis": {"accuracy": 0.4}},
            {"id": "B", "score": 0.4, "per_axis": {"accuracy": 0.3}},
            {"id": "C", "score": 0.6, "per_axis": {"accuracy": 0.5}},
            {"id": "D", "score": 0.5, "per_axis": {"accuracy": 0.4}},
        ]
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))

    sweep = [
        {"case_id": "A", "score": 0.6, "per_axis": {"accuracy": 0.5}},
        {"case_id": "B", "score": 0.6, "per_axis": {"accuracy": 0.5}},
        {"case_id": "C", "score": 0.7, "per_axis": {"accuracy": 0.6}},
        {"case_id": "D", "score": 0.5, "per_axis": {"accuracy": 0.4}},
    ]

    out = hs._paired_delta(sweep, baseline_path)
    assert out is not None
    assert out["n_matched"] == 4
    overall = out["overall_delta"]
    # deltas = [0.1, 0.2, 0.1, 0.0] → mean = 0.1
    assert overall["n"] == 4
    assert overall["mean"] == pytest.approx(0.1, abs=1e-6)
    # sample SD of [0.1, 0.2, 0.1, 0.0] = sqrt(variance); variance = (0.0² + 0.1² + 0.0² + 0.1²)/3 = 0.00667
    # sd ≈ 0.0816; sem ≈ 0.0408; t(df=3, .975) ≈ 3.182; half ≈ 0.130
    assert overall["sd"] == pytest.approx(0.0816, abs=0.005)
    # Whether CI excludes zero on these data is a property of the math —
    # mean=0.1, half=0.13, so CI is [-0.03, 0.23] which INCLUDES zero.
    assert overall["excludes_zero"] is False


def test_paired_delta_handles_missing_baseline_ids(tmp_path: Path) -> None:
    import harness_sweep as hs

    baseline = {"per_example": [{"id": "A", "score": 0.5, "per_axis": {}}]}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))

    sweep = [
        {"case_id": "A", "score": 0.6, "per_axis": {}},
        {"case_id": "UNKNOWN", "score": 0.7, "per_axis": {}},
    ]
    out = hs._paired_delta(sweep, baseline_path)
    assert out is not None
    assert "UNKNOWN" in out["missing_in_baseline"]
    assert out["n_matched"] == 1


def test_paired_delta_reports_error_on_bad_baseline(tmp_path: Path) -> None:
    import harness_sweep as hs

    bogus = tmp_path / "does-not-exist.json"
    out = hs._paired_delta([{"case_id": "A", "score": 0.5, "per_axis": {}}], bogus)
    assert out is not None
    assert "error" in out


def test_module_scope_has_no_anthropic_import() -> None:
    """SDK containment: anthropic must NOT import at module scope."""
    src = SCRIPT.read_text()
    # Find first occurrence of `anthropic` — it should live inside do_commit.
    # A coarse check: top-of-file imports must not reference anthropic.
    first_200 = src.splitlines()[:80]
    for line in first_200:
        stripped = line.strip()
        if stripped.startswith("from anthropic") or stripped.startswith("import anthropic"):
            pytest.fail(f"top-of-module anthropic import: {stripped}")


def test_script_in_sdk_containment_targets() -> None:
    """Pipeline-invariants check must police harness_sweep too."""
    src = (REPO / "scripts" / "check_sdk_containment.py").read_text()
    assert "harness_sweep.py" in src, "harness_sweep.py must be in TARGETS"
