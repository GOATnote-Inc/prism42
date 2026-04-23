"""Tests for the Prism L1 artifact validator.

Exercises each schema with a minimal valid document plus targeted mutations,
and every cross-reference rule in both directions.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_artifacts.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import validate_artifacts as va  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


CASE_ID = "EXAMPLE-CASE-001"
RUN_ID = str(uuid.UUID(int=0xDEADBEEFCAFEBABE0123456789ABCDEF))


def _case() -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "target_domain": "gpu",
        "target_path": "src/example_module/forward.cu",
        "rail_hint": "cuda",
    }


def _invariants() -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "round": 0,
        "invariants": [
            {
                "id": "INV-001",
                "class": "numerical",
                "statement": "softmax output sums to 1 within 1e-6",
                "source_lines": [42, 43],
                "confidence": 0.9,
            }
        ],
    }


def _attacks() -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "round": 0,
        "attacks": [
            {
                "id": "ATK-001",
                "invariant_id": "INV-001",
                "input_pattern": "rows of all -inf",
                "expected_violation": "softmax produces NaN row",
                "confidence": 0.8,
            }
        ],
    }


def _exec_doc(verdict: str = "attack_succeeded") -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "run_id": RUN_ID,
        "rail": "cuda",
        "compile": {"duration_sec": 3.1, "exit": 0, "stderr": ""},
        "run": {"duration_sec": 0.4, "exit": 0, "stdout": "NaN", "stderr": ""},
        "verdict": verdict,
    }


def _verdict_doc(v: str = "confirmed") -> dict[str, Any]:
    if v == "confirmed":
        checks = {"poc_matches_claim": True, "citations_valid": True, "severity_consistent": True}
    else:
        checks = {"poc_matches_claim": False, "citations_valid": True, "severity_consistent": True}
    return {
        "case_id": CASE_ID,
        "run_id": RUN_ID,
        "verdict": v,
        "severity": "high",
        "cross_checks": checks,
        "disclosure_target": "upstream-maintainer@example.com",
        "embargo_channel": "GHSA" if v == "confirmed" else "N/A",
    }


def _report_text() -> str:
    return (
        "---\n"
        f"case_id: {CASE_ID}\n"
        "target: src/kernel/forward.cu\n"
        "class: numerical\n"
        "severity_estimate: high\n"
        "invariant_id: INV-001\n"
        "attack_id: ATK-001\n"
        "---\n\n# Report body\n"
    )


@pytest.fixture
def case_dir(tmp_path: Path) -> Path:
    """Populates a tmp case dir with a minimal, fully-valid set of artifacts."""

    (tmp_path / "case.json").write_text(json.dumps(_case()))
    (tmp_path / "invariants.json").write_text(json.dumps(_invariants()))
    (tmp_path / "attacks.json").write_text(json.dumps(_attacks()))
    (tmp_path / "exec.json").write_text(json.dumps(_exec_doc()))
    (tmp_path / "verdict.json").write_text(json.dumps(_verdict_doc()))
    (tmp_path / "report.md").write_text(_report_text())
    return tmp_path


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
    )


def _run(args: list[str]) -> tuple[int, str]:
    """Invoke the validator in-process; returns (rc, combined-stdout)."""

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = va.run(args)
    return rc, buf.getvalue()


def _write(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc))


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_all_valid_artifacts_pass(case_dir: Path) -> None:
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 0, out
    assert "FAIL" not in out


@pytest.mark.parametrize(
    "artifact",
    ["case.json", "invariants.json", "attacks.json", "exec.json", "verdict.json", "report.md"],
)
def test_single_artifact_passes(case_dir: Path, artifact: str) -> None:
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", artifact])
    assert rc == 0, out


def test_partial_case_dir_passes_in_sweep_mode(tmp_path: Path) -> None:
    """Mid-pipeline (only case.json present) must not fail."""

    _write(tmp_path / "case.json", _case())
    rc, out = _run(["--case-dir", str(tmp_path)])
    assert rc == 0, out


def test_cli_help_lists_artifacts() -> None:
    result = _run_cli(["--help"])
    assert result.returncode == 0
    stdout = result.stdout
    for name in ["case.json", "invariants.json", "attacks.json", "exec.json", "verdict.json", "report.md"]:
        assert name in stdout


# --------------------------------------------------------------------------- #
# Schema-level mutations                                                      #
# --------------------------------------------------------------------------- #


def test_case_missing_required_field_fails(case_dir: Path) -> None:
    doc = _case()
    del doc["target_path"]
    _write(case_dir / "case.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "case.json"])
    assert rc == 1
    assert "target_path" in out


def test_case_bad_id_pattern_fails(case_dir: Path) -> None:
    doc = _case()
    doc["case_id"] = "fa-bug-7"
    _write(case_dir / "case.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "case.json"])
    assert rc == 1
    assert "case_id" in out


def test_case_bad_target_domain_enum_fails(case_dir: Path) -> None:
    doc = _case()
    doc["target_domain"] = "biomedical"
    _write(case_dir / "case.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "case.json"])
    assert rc == 1
    assert "target_domain" in out


def test_invariants_missing_confidence_fails(case_dir: Path) -> None:
    doc = _invariants()
    del doc["invariants"][0]["confidence"]
    _write(case_dir / "invariants.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "invariants.json"])
    assert rc == 1
    assert "confidence" in out


def test_invariants_confidence_out_of_range_fails(case_dir: Path) -> None:
    doc = _invariants()
    doc["invariants"][0]["confidence"] = 1.5
    _write(case_dir / "invariants.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "invariants.json"])
    assert rc == 1
    assert "confidence" in out


def test_invariants_bad_class_fails(case_dir: Path) -> None:
    doc = _invariants()
    doc["invariants"][0]["class"] = "quantum"
    _write(case_dir / "invariants.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "invariants.json"])
    assert rc == 1
    assert "class" in out


def test_invariants_empty_array_fails(case_dir: Path) -> None:
    doc = _invariants()
    doc["invariants"] = []
    _write(case_dir / "invariants.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "invariants.json"])
    assert rc == 1


def test_attacks_bad_invariant_id_pattern_fails(case_dir: Path) -> None:
    doc = _attacks()
    doc["attacks"][0]["invariant_id"] = "INV-1"
    _write(case_dir / "attacks.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "attacks.json"])
    assert rc == 1
    assert "invariant_id" in out


def test_exec_bad_rail_fails(case_dir: Path) -> None:
    doc = _exec_doc()
    doc["rail"] = "rocm"
    _write(case_dir / "exec.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "exec.json"])
    assert rc == 1
    assert "rail" in out


def test_exec_bad_run_id_uuid_fails(case_dir: Path) -> None:
    doc = _exec_doc()
    doc["run_id"] = "not-a-uuid"
    _write(case_dir / "exec.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "exec.json"])
    assert rc == 1
    assert "run_id" in out


def test_exec_bad_verdict_pattern_fails(case_dir: Path) -> None:
    doc = _exec_doc()
    doc["verdict"] = "maybe_ok"
    _write(case_dir / "exec.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "exec.json"])
    assert rc == 1
    assert "verdict" in out


def test_exec_execution_deferred_pattern_accepted(case_dir: Path) -> None:
    doc = _exec_doc(verdict="execution_deferred_no_gpu")
    _write(case_dir / "exec.json", doc)
    rc, _ = _run(["--case-dir", str(case_dir), "--artifact", "exec.json"])
    assert rc == 0


def test_verdict_bad_enum_fails(case_dir: Path) -> None:
    doc = _verdict_doc()
    doc["verdict"] = "maybe"
    _write(case_dir / "verdict.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "verdict.json"])
    assert rc == 1
    assert "verdict" in out


def test_verdict_missing_cross_checks_fails(case_dir: Path) -> None:
    doc = _verdict_doc()
    del doc["cross_checks"]
    _write(case_dir / "verdict.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "verdict.json"])
    assert rc == 1
    assert "cross_checks" in out


def test_report_missing_frontmatter_fails(case_dir: Path) -> None:
    (case_dir / "report.md").write_text("# just prose\n")
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "report.md"])
    assert rc == 1
    assert "front-matter" in out


def test_report_missing_required_field_fails(case_dir: Path) -> None:
    text = _report_text().replace("attack_id: ATK-001\n", "")
    (case_dir / "report.md").write_text(text)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "report.md"])
    assert rc == 1
    assert "attack_id" in out


# --------------------------------------------------------------------------- #
# Cross-reference mutations                                                   #
# --------------------------------------------------------------------------- #


def test_xref_case_id_mismatch_fails(case_dir: Path) -> None:
    doc = _invariants()
    doc["case_id"] = "EXAMPLE-CASE-999"
    _write(case_dir / "invariants.json", doc)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "case_id mismatch" in out


def test_xref_attack_references_unknown_invariant_fails(case_dir: Path) -> None:
    doc = _attacks()
    doc["attacks"][0]["invariant_id"] = "INV-999"
    _write(case_dir / "attacks.json", doc)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "unknown invariant_id" in out


def test_xref_run_id_mismatch_fails(case_dir: Path) -> None:
    doc = _verdict_doc()
    doc["run_id"] = str(uuid.UUID(int=1))
    _write(case_dir / "verdict.json", doc)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "run_id" in out


def test_xref_confirmed_requires_all_cross_checks_true_fails(case_dir: Path) -> None:
    doc = _verdict_doc("confirmed")
    doc["cross_checks"]["citations_valid"] = False
    _write(case_dir / "verdict.json", doc)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "cross_checks are not all true" in out


def test_xref_attack_failed_requires_denied_fails(case_dir: Path) -> None:
    _write(case_dir / "exec.json", _exec_doc(verdict="attack_failed"))
    # Leave verdict.verdict as 'confirmed' (invalid combination).
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "attack_failed" in out and "denied" in out


def test_xref_attack_failed_plus_denied_passes(case_dir: Path) -> None:
    _write(case_dir / "exec.json", _exec_doc(verdict="attack_failed"))
    v = _verdict_doc("denied")
    v["embargo_channel"] = "N/A"
    _write(case_dir / "verdict.json", v)
    # Report front-matter still references ATK-001 / INV-001 which exist.
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 0, out


def test_xref_execution_timeout_requires_inconclusive_fails(case_dir: Path) -> None:
    _write(case_dir / "exec.json", _exec_doc(verdict="execution_timeout"))
    # verdict is still 'confirmed' => should fail rule 6.
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "execution_timeout" in out and "inconclusive" in out


def test_xref_poc_compile_error_with_inconclusive_passes(case_dir: Path) -> None:
    _write(case_dir / "exec.json", _exec_doc(verdict="poc_compile_error"))
    v = _verdict_doc("inconclusive")
    v["embargo_channel"] = "N/A"
    _write(case_dir / "verdict.json", v)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 0, out


def test_xref_report_invariant_id_unknown_fails(case_dir: Path) -> None:
    text = _report_text().replace("invariant_id: INV-001", "invariant_id: INV-777")
    (case_dir / "report.md").write_text(text)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "report.invariant_id" in out


def test_xref_report_attack_id_unknown_fails(case_dir: Path) -> None:
    text = _report_text().replace("attack_id: ATK-001", "attack_id: ATK-777")
    (case_dir / "report.md").write_text(text)
    rc, out = _run(["--case-dir", str(case_dir)])
    assert rc == 1
    assert "report.attack_id" in out


# --------------------------------------------------------------------------- #
# CLI-level behaviour                                                         #
# --------------------------------------------------------------------------- #


def test_missing_case_dir_fails(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    rc, out = _run(["--case-dir", str(missing)])
    assert rc == 1
    assert "does not exist" in out


def test_single_artifact_missing_fails(tmp_path: Path) -> None:
    # Dir exists but the specific file does not.
    rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "invariants.json"])
    assert rc == 1
    assert "does not exist" in out


def test_single_artifact_skips_cross_refs(case_dir: Path) -> None:
    """With --artifact, cross-ref rules must not run even if they'd fail."""

    doc = _verdict_doc("confirmed")
    doc["cross_checks"]["poc_matches_claim"] = False  # would fail rule 4
    _write(case_dir / "verdict.json", doc)
    # Schema itself still passes, so exit 0 proves we skipped cross-refs.
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "verdict.json"])
    assert rc == 0, out


def test_clinical_rail_without_compile_passes(case_dir: Path) -> None:
    doc = _exec_doc()
    doc["rail"] = "clinical"
    del doc["compile"]
    _write(case_dir / "exec.json", doc)
    rc, out = _run(["--case-dir", str(case_dir), "--artifact", "exec.json"])
    assert rc == 0, out


def test_copy_fixture_is_independent(case_dir: Path) -> None:
    """Regression: fixture builder must produce independent docs per test."""

    a = _invariants()
    b = _invariants()
    a["invariants"][0]["id"] = "INV-002"
    assert b["invariants"][0]["id"] == "INV-001"
    _ = copy.deepcopy(a)
