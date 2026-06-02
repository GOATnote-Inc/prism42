"""Clinical rail validator tests.

Exercises the ``case.schema.json`` clinical conditional (P1) and the new
``clinical-rubric.schema.json`` document. Mirrors the subprocess + tmp_path
pattern used by ``tests/test_artifact_validation.py`` so the behaviour of
the real CLI is what we observe.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_artifacts.py"
SCHEMA_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import validate_artifacts as va  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


CLINICAL_CASE_ID = "HBH-CLN-SYNTH"
CUDA_CASE_ID = "EXAMPLE-CUDA-001"


def _clinical_case() -> dict[str, Any]:
    """Minimal clinical-rail case.json that satisfies P1 conditional requires."""

    return {
        "case_id": CLINICAL_CASE_ID,
        "target_path": "corpus/golden-cases/HBH-CLN-SYNTH/transcript.md",
        "rail": "clinical",
        "healthbench_hard_example_id": "HBH-EM-001",
        "target_axis": "accuracy",
        "rubric_ref": "corpus/golden-cases/HBH-CLN-SYNTH/rubric.json",
    }


def _cuda_case_with_rail() -> dict[str, Any]:
    """Cuda-rail case with explicit rail field — must NOT require clinical fields."""

    return {
        "case_id": CUDA_CASE_ID,
        "target_domain": "gpu",
        "target_path": "src/kernel/forward.cu",
        "rail": "cuda",
    }


def _cuda_case_no_rail() -> dict[str, Any]:
    """Cuda-style case with no `rail` field (KERNEL-GOLDEN shape)."""

    return {
        "case_id": CUDA_CASE_ID,
        "target_domain": "gpu",
        "target_path": "src/kernel/forward.cu",
        "rail_hint": "cuda",
    }


def _minimal_rubric() -> dict[str, Any]:
    return {
        "rubric_id": "RUB-HBH-CLN-SYNTH-v1",
        "axes": ["accuracy"],
        "criteria": [
            {
                "id": "C1",
                "description": "Identifies the correct differential.",
                "weight": 1.0,
            }
        ],
    }


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _write(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc))


def _run(args: list[str]) -> tuple[int, str]:
    """Invoke the validator in-process; returns (rc, combined-stdout)."""

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = va.run(args)
    return rc, buf.getvalue()


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
    )


def _load_schema(name: str) -> dict[str, Any]:
    with (SCHEMA_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# TestClinicalRequiredFields                                                  #
# --------------------------------------------------------------------------- #


class TestClinicalRequiredFields:
    """When rail=='clinical', the three clinical fields are all required."""

    @pytest.mark.parametrize(
        "field",
        ["healthbench_hard_example_id", "target_axis", "rubric_ref"],
    )
    def test_missing_clinical_field_fails(self, tmp_path: Path, field: str) -> None:
        doc = _clinical_case()
        del doc[field]
        _write(tmp_path / "case.json", doc)
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 1, out
        assert field in out, f"expected {field!r} in validator output, got: {out!r}"


# --------------------------------------------------------------------------- #
# TestClinicalConditional                                                     #
# --------------------------------------------------------------------------- #


class TestClinicalConditional:
    """Regression guards around the `if rail==clinical` branch."""

    def test_cuda_rail_not_forced_to_include_clinical_fields(
        self, tmp_path: Path
    ) -> None:
        """rail=='cuda' must pass without target_axis/rubric_ref/HBH id."""

        _write(tmp_path / "case.json", _cuda_case_with_rail())
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 0, out

    def test_missing_rail_defaults_to_non_clinical_path(
        self, tmp_path: Path
    ) -> None:
        """No `rail` at all (KERNEL-GOLDEN shape) must still validate."""

        _write(tmp_path / "case.json", _cuda_case_no_rail())
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 0, out

    def test_clinical_rail_plus_all_three_required_fields_validates(
        self, tmp_path: Path
    ) -> None:
        """Positive control: clinical rail with all three fields set passes."""

        _write(tmp_path / "case.json", _clinical_case())
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 0, out


# --------------------------------------------------------------------------- #
# TestTargetAxisEnum                                                          #
# --------------------------------------------------------------------------- #


class TestTargetAxisEnum:
    """target_axis must be one of the five HealthBench rubric axes."""

    @pytest.mark.parametrize(
        "axis",
        [
            "accuracy",
            "completeness",
            "context_awareness",
            "instruction_following",
            "communication",
        ],
    )
    def test_valid_axis_passes(self, tmp_path: Path, axis: str) -> None:
        doc = _clinical_case()
        doc["target_axis"] = axis
        _write(tmp_path / "case.json", doc)
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 0, out

    def test_target_axis_bogus_fails(self, tmp_path: Path) -> None:
        doc = _clinical_case()
        doc["target_axis"] = "foo"
        _write(tmp_path / "case.json", doc)
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 1, out
        # jsonschema enum error surfaces either "enum" or the field path.
        assert "target_axis" in out or "enum" in out, out


# --------------------------------------------------------------------------- #
# TestHealthBenchExampleIdPattern                                             #
# --------------------------------------------------------------------------- #


class TestHealthBenchExampleIdPattern:
    """healthbench_hard_example_id must match HBH-<TOKEN>-<digits>."""

    def _with_id(self, hbh_id: str) -> dict[str, Any]:
        doc = _clinical_case()
        doc["healthbench_hard_example_id"] = hbh_id
        return doc

    def test_valid_pattern_passes(self, tmp_path: Path) -> None:
        _write(tmp_path / "case.json", self._with_id("HBH-EM-001"))
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 0, out

    def test_too_few_digits_fails(self, tmp_path: Path) -> None:
        _write(tmp_path / "case.json", self._with_id("HBH-EM-01"))
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 1, out
        assert "healthbench_hard_example_id" in out or "pattern" in out, out

    def test_wrong_prefix_fails(self, tmp_path: Path) -> None:
        _write(tmp_path / "case.json", self._with_id("HBE-EM-001"))
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 1, out
        assert "healthbench_hard_example_id" in out or "pattern" in out, out

    def test_lowercase_fails(self, tmp_path: Path) -> None:
        _write(tmp_path / "case.json", self._with_id("hbh-em-001"))
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 1, out
        assert "healthbench_hard_example_id" in out or "pattern" in out, out


# --------------------------------------------------------------------------- #
# TestClinicalRubricSchema                                                    #
# --------------------------------------------------------------------------- #


class TestClinicalRubricSchema:
    """Structural tests for schemas/clinical-rubric.schema.json via jsonschema."""

    @pytest.fixture(scope="class")
    def schema(self) -> dict[str, Any]:
        return _load_schema("clinical-rubric.schema.json")

    @pytest.fixture(scope="class")
    def validator(self, schema: dict[str, Any]) -> Draft202012Validator:
        # Will raise if the schema itself is malformed.
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def test_minimal_valid_rubric(self, validator: Draft202012Validator) -> None:
        errors = list(validator.iter_errors(_minimal_rubric()))
        assert errors == [], [e.message for e in errors]

    def test_missing_axes_fails(self, validator: Draft202012Validator) -> None:
        doc = _minimal_rubric()
        del doc["axes"]
        errors = list(validator.iter_errors(doc))
        assert errors, "expected schema error on missing 'axes'"
        assert any("axes" in e.message for e in errors), [e.message for e in errors]

    def test_bad_weight_type_fails(self, validator: Draft202012Validator) -> None:
        doc = _minimal_rubric()
        doc["criteria"][0]["weight"] = "heavy"
        errors = list(validator.iter_errors(doc))
        assert errors, "expected schema error on string weight"
        # jsonschema reports the type error on the weight path.
        assert any(
            "weight" in list(map(str, e.absolute_path))
            or "number" in e.message
            for e in errors
        ), [e.message for e in errors]

    def test_criteria_missing_id_fails(
        self, validator: Draft202012Validator
    ) -> None:
        doc = _minimal_rubric()
        del doc["criteria"][0]["id"]
        errors = list(validator.iter_errors(doc))
        assert errors, "expected schema error on missing criterion id"
        assert any("id" in e.message for e in errors), [e.message for e in errors]


# --------------------------------------------------------------------------- #
# TestClinicalRubricRef                                                       #
# --------------------------------------------------------------------------- #


class TestClinicalRubricRef:
    """rubric_ref has minLength 1 (non-empty) per case.schema.json."""

    def test_rubric_ref_empty_string_fails(self, tmp_path: Path) -> None:
        doc = _clinical_case()
        doc["rubric_ref"] = ""
        _write(tmp_path / "case.json", doc)
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 1, out
        assert "rubric_ref" in out or "minLength" in out or "too short" in out, out

    def test_rubric_ref_normal_path_validates(self, tmp_path: Path) -> None:
        doc = _clinical_case()
        doc["rubric_ref"] = "corpus/golden-cases/X/rubric.json"
        _write(tmp_path / "case.json", doc)
        rc, out = _run(["--case-dir", str(tmp_path), "--artifact", "case.json"])
        assert rc == 0, out


# --------------------------------------------------------------------------- #
# Optional integration test: guarded on HBH-CLN-SYNTH presence                #
# --------------------------------------------------------------------------- #


_HBH_CLN_SYNTH = REPO_ROOT / "corpus" / "golden-cases" / "HBH-CLN-SYNTH"


@pytest.mark.skipif(
    not _HBH_CLN_SYNTH.exists(),
    reason="P3 fixture not yet merged into this worktree",
)
def test_hbh_cln_synth_validates_if_present() -> None:
    proc = _run_cli(["--case-dir", str(_HBH_CLN_SYNTH)])
    assert proc.returncode == 0, (
        f"validate_artifacts.py rejected HBH-CLN-SYNTH "
        f"(exit={proc.returncode}); stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
