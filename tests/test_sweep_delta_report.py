"""Tests for scripts/sweep_delta_report.py — markdown delta renderer.

Pure-compute. Builds fixture sweep directories in tmp_path and checks
that the rendered markdown surfaces the key sections:
  - overall aggregate score
  - R4 ship-gate table with per-axis paired Δ and decision
  - per-example rows
  - recused examples callout when any score is None
  - graceful degradation when paired_delta is absent or malformed
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "sweep_delta_report.py"

if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def _write_sweep(
    tmp: Path,
    aggregate_extras: dict | None = None,
    per_example: list[dict] | None = None,
) -> Path:
    """Build a minimal fixture sweep dir; return the path."""
    sweep = tmp / "harness-sweep-TEST"
    sweep.mkdir(parents=True, exist_ok=True)
    agg = {
        "run_id": "TEST-RUN",
        "stamp": "20260423-TEST",
        "coordinator_id": "agent_TEST",
        "coordinator_version": 4,
        "judge_model": "claude-opus-4-7",
        "total_cost_usd": 8.1234,
        "aggregate": {
            "n": 3,
            "n_scored": 3,
            "n_recused": 0,
            "score": 0.35,
            "per_axis": {
                "accuracy": 0.40,
                "completeness": 0.30,
                "context_awareness": 0.25,
                "instruction_following": 0.40,
                "communication_quality": 0.35,
            },
        },
    }
    if aggregate_extras:
        agg.update(aggregate_extras)
    (sweep / "aggregate.json").write_text(json.dumps(agg, indent=2))
    (sweep / "per_example.json").write_text(json.dumps(per_example or [], indent=2))
    return sweep


def test_renders_aggregate_section(tmp_path: Path) -> None:
    import sweep_delta_report as sdr

    sweep = _write_sweep(tmp_path)
    aggregate, per_example = sdr._load_sweep(sweep)
    out = sdr.build_report(aggregate, per_example, sweep)
    assert "## Sweep aggregate" in out
    assert "overall score" in out
    assert "| accuracy | 0.4000 |" in out or "| accuracy | 0.4 |" in out


def test_renders_paired_delta_ship_gate_table(tmp_path: Path) -> None:
    import sweep_delta_report as sdr

    paired = {
        "baseline_artifact": "results/baseline-opus47-seed42.json",
        "n_matched": 3,
        "missing_in_baseline": [],
        "overall_delta": {
            "n": 3, "mean": 0.08, "sd": 0.05, "sem": 0.029,
            "t_crit_975": 4.303, "ci95_half": 0.124,
            "ci95_low": -0.044, "ci95_high": 0.204, "excludes_zero": False,
        },
        "per_axis_delta": {
            "accuracy": {
                "n": 3, "mean": 0.12, "sd": 0.03, "sem": 0.017,
                "t_crit_975": 4.303, "ci95_half": 0.074,
                "ci95_low": 0.046, "ci95_high": 0.194, "excludes_zero": True,
            },
            "completeness": {
                "n": 3, "mean": 0.02, "sd": 0.05, "sem": 0.029,
                "t_crit_975": 4.303, "ci95_half": 0.124,
                "ci95_low": -0.104, "ci95_high": 0.144, "excludes_zero": False,
            },
            "communication_quality": {
                "n": 3, "mean": 0.08, "sd": 0.02, "sem": 0.011,
                "t_crit_975": 4.303, "ci95_half": 0.049,
                "ci95_low": 0.031, "ci95_high": 0.129, "excludes_zero": True,
            },
        },
    }
    sweep = _write_sweep(tmp_path, aggregate_extras={"paired_delta": paired})
    aggregate, per_example = sdr._load_sweep(sweep)
    out = sdr.build_report(aggregate, per_example, sweep)

    # Ship-gate table header + all three R4 skill rows.
    assert "## R4 ship-gate" in out
    assert "| `clinical-review` | communication" in out
    assert "| `differential-diagnosis` | completeness" in out
    assert "| `dosage-check` | accuracy" in out
    # accuracy axis (dosage-check) has mean 0.12 AND CI excludes 0 → SHIP.
    assert "SHIP" in out
    # completeness (differential-diagnosis) has mean 0.02 → below 0.05 threshold.
    # communication (clinical-review) has mean 0.08 AND CI excludes 0 → SHIP.


def test_ship_decision_thresholds() -> None:
    """Direct unit test on _ship_decision — the R4 ship-gate logic."""
    import sweep_delta_report as sdr

    # SHIP: Δ>=0.05 AND CI excludes 0.
    ship = {"mean": 0.08, "excludes_zero": True}
    assert "SHIP" in sdr._ship_decision(ship)

    # Signal but Δ below threshold.
    small = {"mean": 0.02, "excludes_zero": True}
    assert "below 0.05 threshold" in sdr._ship_decision(small)

    # Directional only — CI includes zero.
    dir_only = {"mean": 0.10, "excludes_zero": False}
    assert "directional only" in sdr._ship_decision(dir_only)

    # No lift.
    nolift = {"mean": -0.01, "excludes_zero": False}
    assert "no lift" in sdr._ship_decision(nolift)

    # n<2 guard — excludes_zero is None on single-sample deltas.
    too_few = {"mean": 0.5, "excludes_zero": None}
    assert "n<2" in sdr._ship_decision(too_few)


def test_renders_recused_callout(tmp_path: Path) -> None:
    import sweep_delta_report as sdr

    per_example = [
        {"case_id": "OK-001", "score": 0.5, "input_tokens": 100, "output_tokens": 50,
         "modified_len": 800, "session_cost_usd": 0.01, "final_marker": True},
        {"case_id": "FAIL-002", "score": None, "input_tokens": 100, "output_tokens": 50,
         "modified_len": 0, "session_cost_usd": 0.01, "final_marker": False,
         "transcript_path": "results/harness-sweep-TEST/transcripts/FAIL-002.log"},
    ]
    sweep = _write_sweep(tmp_path, per_example=per_example)
    aggregate, pex = sdr._load_sweep(sweep)
    out = sdr.build_report(aggregate, pex, sweep)
    assert "| `OK-001` |" in out
    assert "| `FAIL-002` |" in out
    assert "### Recused examples" in out
    assert "FAIL-002" in out
    assert "no fenced block extracted" in out


def test_paired_delta_error_degrades_gracefully(tmp_path: Path) -> None:
    import sweep_delta_report as sdr

    bad_paired = {"error": "baseline unreadable: [Errno 2] No such file or directory: 'missing.json'"}
    sweep = _write_sweep(tmp_path, aggregate_extras={"paired_delta": bad_paired})
    aggregate, pex = sdr._load_sweep(sweep)
    out = sdr.build_report(aggregate, pex, sweep)
    assert "paired delta unavailable" in out


def test_missing_paired_delta_renders_without_ship_gate(tmp_path: Path) -> None:
    import sweep_delta_report as sdr

    sweep = _write_sweep(tmp_path)  # no paired_delta
    aggregate, pex = sdr._load_sweep(sweep)
    out = sdr.build_report(aggregate, pex, sweep)
    assert "## R4 ship-gate" not in out
    assert "## Sweep aggregate" in out


def test_cli_exits_zero_and_writes_markdown(tmp_path: Path) -> None:
    sweep = _write_sweep(tmp_path)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(sweep)],
        capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    out_md = sweep / "delta-report.md"
    assert out_md.exists()
    body = out_md.read_text()
    assert body.startswith("# Prism — T4.7b harness sweep delta report")


def test_cli_errors_on_missing_dir() -> None:
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "/tmp/definitely-does-not-exist-xyz-12345"],
        capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 1
    assert "not a directory" in res.stderr
