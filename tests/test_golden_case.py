"""Golden-case fixture integrity tests.

Every assertion in this file is a cross-reference rule that the Prism L3
verification layer must preserve forever. If one of these fails, the fix
is in the layer under test -- not the fixture.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_DIR = REPO_ROOT / "corpus" / "golden-cases" / "KERNEL-GOLD-001"
CASE_ID = "KERNEL-GOLD-001"

JSON_FILES = ("case.json", "invariants.json", "attacks.json", "exec.json", "verdict.json")


# ---------------------------------------------------------------------------
# loaders / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def artifacts() -> dict:
    out = {}
    for name in JSON_FILES:
        path = CASE_DIR / name
        with path.open("r", encoding="utf-8") as fh:
            out[name] = json.load(fh)
    # report.md front-matter
    report_text = (CASE_DIR / "report.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", report_text, flags=re.S)
    assert m is not None, "report.md must start with a YAML front-matter block"
    out["report.md"] = {
        "front_matter": yaml.safe_load(m.group(1)),
        "body": report_text[m.end():],
        "raw": report_text,
    }
    return out


# ---------------------------------------------------------------------------
# file presence
# ---------------------------------------------------------------------------


def test_all_expected_files_present() -> None:
    expected = set(JSON_FILES) | {"poc.py", "report.md"}
    present = {p.name for p in CASE_DIR.iterdir() if p.is_file()}
    missing = expected - present
    assert not missing, f"missing fixture files: {sorted(missing)}"


# ---------------------------------------------------------------------------
# schema-shape / cross-reference rules
# ---------------------------------------------------------------------------


def test_case_id_matches_across_json_files(artifacts: dict) -> None:
    for name in JSON_FILES:
        assert artifacts[name]["case_id"] == CASE_ID, f"{name} case_id mismatch"


def test_case_id_matches_report_front_matter(artifacts: dict) -> None:
    assert artifacts["report.md"]["front_matter"]["case_id"] == CASE_ID


def test_case_id_matches_regex() -> None:
    assert re.match(r"^[A-Z]{2,}-[A-Z]+-[A-Z0-9]{3,}$", CASE_ID), (
        "golden case id must satisfy the schema case_id pattern "
        "(^[A-Z]{2,}-[A-Z]+-[A-Z0-9]{3,}$)"
    )


def test_invariant_ids_well_formed(artifacts: dict) -> None:
    for inv in artifacts["invariants.json"]["invariants"]:
        assert re.match(r"^INV-\d{3}$", inv["id"]), f"bad invariant id: {inv['id']}"
        assert inv["class"] in {"numerical", "memory", "concurrency", "precision", "other"}
        assert 0.0 <= inv["confidence"] <= 1.0
        assert isinstance(inv["source_lines"], list)
        assert all(isinstance(x, int) for x in inv["source_lines"])


def test_attack_ids_well_formed(artifacts: dict) -> None:
    for atk in artifacts["attacks.json"]["attacks"]:
        assert re.match(r"^ATK-\d{3}$", atk["id"]), f"bad attack id: {atk['id']}"
        assert re.match(r"^INV-\d{3}$", atk["invariant_id"])
        assert 0.0 <= atk["confidence"] <= 1.0


def test_every_attack_references_real_invariant(artifacts: dict) -> None:
    invariant_ids = {inv["id"] for inv in artifacts["invariants.json"]["invariants"]}
    for atk in artifacts["attacks.json"]["attacks"]:
        assert atk["invariant_id"] in invariant_ids, (
            f"attack {atk['id']} references unknown invariant {atk['invariant_id']}"
        )


def test_exec_run_id_matches_verdict_run_id(artifacts: dict) -> None:
    assert artifacts["exec.json"]["run_id"] == artifacts["verdict.json"]["run_id"]


def test_run_id_is_uuid(artifacts: dict) -> None:
    import uuid

    run_id = artifacts["exec.json"]["run_id"]
    # will raise if not a valid uuid
    uuid.UUID(run_id)


def test_verdict_regex(artifacts: dict) -> None:
    verdict = artifacts["exec.json"]["verdict"]
    assert re.match(
        r"^(attack_succeeded|attack_failed|poc_compile_error|execution_timeout|execution_deferred_[a-z_]+)$",
        verdict,
    ), f"exec.verdict {verdict!r} does not match the L1 regex"


def test_rail_enum(artifacts: dict) -> None:
    assert artifacts["exec.json"]["rail"] in {"cuda", "cute", "nki", "clinical"}


def test_verdict_enum(artifacts: dict) -> None:
    assert artifacts["verdict.json"]["verdict"] in {"confirmed", "denied", "inconclusive"}
    assert artifacts["verdict.json"]["severity"] in {
        "critical",
        "high",
        "medium",
        "low",
        "informational",
    }
    assert artifacts["verdict.json"]["embargo_channel"] in {"GHSA", "direct-email", "N/A"}


def test_confirmed_implies_all_cross_checks_true(artifacts: dict) -> None:
    v = artifacts["verdict.json"]
    if v["verdict"] == "confirmed":
        cc = v["cross_checks"]
        assert cc["poc_matches_claim"] is True
        assert cc["citations_valid"] is True
        assert cc["severity_consistent"] is True


def test_attack_succeeded_consistent_with_confirmed(artifacts: dict) -> None:
    exec_verdict = artifacts["exec.json"]["verdict"]
    adj_verdict = artifacts["verdict.json"]["verdict"]
    if adj_verdict == "confirmed":
        # 'denied' on a succeeded attack is the contradictory combo; everything else is fine.
        assert exec_verdict != "attack_failed", (
            "confirmed verdict contradicts an attack_failed execution record"
        )


def test_report_front_matter_has_required_keys(artifacts: dict) -> None:
    fm = artifacts["report.md"]["front_matter"]
    required = {"case_id", "target", "class", "severity_estimate", "invariant_id", "attack_id"}
    missing = required - set(fm.keys())
    assert not missing, f"report.md front-matter missing keys: {sorted(missing)}"


def test_report_front_matter_references_real_ids(artifacts: dict) -> None:
    fm = artifacts["report.md"]["front_matter"]
    invariant_ids = {inv["id"] for inv in artifacts["invariants.json"]["invariants"]}
    attack_ids = {atk["id"] for atk in artifacts["attacks.json"]["attacks"]}
    assert fm["invariant_id"] in invariant_ids, (
        f"report.md invariant_id {fm['invariant_id']!r} not in invariants.json"
    )
    assert fm["attack_id"] in attack_ids, (
        f"report.md attack_id {fm['attack_id']!r} not in attacks.json"
    )


def test_report_severity_matches_verdict(artifacts: dict) -> None:
    fm = artifacts["report.md"]["front_matter"]
    assert fm["severity_estimate"] == artifacts["verdict.json"]["severity"], (
        "report.md severity_estimate must match verdict.json severity"
    )


# ---------------------------------------------------------------------------
# PoC execution
# ---------------------------------------------------------------------------


def test_poc_parses() -> None:
    import ast

    ast.parse((CASE_DIR / "poc.py").read_text(encoding="utf-8"))


def test_poc_exits_nonzero_and_names_invariant(artifacts: dict) -> None:
    """Golden PoC must demonstrate the violation."""
    proc = subprocess.run(
        [sys.executable, str(CASE_DIR / "poc.py")],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(CASE_DIR),
    )
    assert proc.returncode != 0, (
        f"poc.py exited 0 but the golden fixture requires it to demonstrate the violation; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )

    # invariant_id or its class must appear in stderr (per the task spec).
    target_inv = artifacts["report.md"]["front_matter"]["invariant_id"]
    inv_class = next(
        inv["class"]
        for inv in artifacts["invariants.json"]["invariants"]
        if inv["id"] == target_inv
    )
    assert target_inv in proc.stderr or inv_class in proc.stderr, (
        f"poc.py stderr must mention {target_inv!r} or class {inv_class!r}; got {proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# external validator (L1 / parallel agent) -- skipped if not present
# ---------------------------------------------------------------------------


_VALIDATOR = REPO_ROOT / "scripts" / "validate_artifacts.py"


@pytest.mark.requires_validator
@pytest.mark.skipif(
    not _VALIDATOR.exists(),
    reason="scripts/validate_artifacts.py is written by the L1 agent in parallel; not present in this worktree.",
)
def test_validator_accepts_golden_case() -> None:
    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--case-dir", str(CASE_DIR)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"validate_artifacts.py rejected the golden case "
        f"(exit={proc.returncode}); stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
