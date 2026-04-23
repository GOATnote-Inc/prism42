"""Schema + structural tests for corpus/clinical-demo/CLN-DEMO-* bundles.

These fixtures are synthetic ED-reasoning cases that feed
``scripts/generate_clinical_demo_artifacts.py``. The generator enforces
the same invariants at runtime, but we want a fast schema-level signal
that fires before the generator is invoked.

Invariants tested:
  - case.json is schema-valid against schemas/case.schema.json
  - rubric.json is schema-valid against schemas/clinical-rubric.schema.json
  - rubric criterion weights sum to 1.0
  - baseline.md and modified.md both start with synthetic +
    physician-review-required frontmatter
  - grading.json's physician_review field is null (code never pre-signs)
  - grading.json's weighted_total/delta match recomputed values from
    scores + weights
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus" / "clinical-demo"
SCHEMA_DIR = REPO_ROOT / "schemas"

SYNTHETIC_MARKER = "synthetic: true"
PHYSICIAN_REVIEW_MARKER = "physician-review-required: true"

CASES = ("CLN-DEMO-001", "CLN-DEMO-002")


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _schema(name: str) -> dict:
    return _load_json(SCHEMA_DIR / name)


# --------------------------------------------------------------------------- #
# case.json                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_id", CASES)
def test_case_json_schema_valid(case_id: str) -> None:
    case = _load_json(CORPUS_DIR / case_id / "case.json")
    Draft202012Validator(_schema("case.schema.json")).validate(case)
    assert case["case_id"] == case_id
    assert case["rail"] == "clinical"
    assert case["healthbench_hard_example_id"].startswith("HBH-CLNDEMO-")
    assert case["target_axis"] in {
        "accuracy",
        "completeness",
        "context_awareness",
        "instruction_following",
        "communication",
    }


# --------------------------------------------------------------------------- #
# rubric.json                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_id", CASES)
def test_rubric_json_schema_valid(case_id: str) -> None:
    rubric = _load_json(CORPUS_DIR / case_id / "rubric.json")
    Draft202012Validator(_schema("clinical-rubric.schema.json")).validate(rubric)
    assert rubric["rubric_id"].startswith("rubric-HBH-CLNDEMO-")
    assert len(rubric["criteria"]) >= 3


@pytest.mark.parametrize("case_id", CASES)
def test_rubric_weights_sum_to_one(case_id: str) -> None:
    rubric = _load_json(CORPUS_DIR / case_id / "rubric.json")
    total = sum(float(c["weight"]) for c in rubric["criteria"])
    assert abs(total - 1.0) < 1e-9, f"{case_id}: weights sum to {total}"


# --------------------------------------------------------------------------- #
# baseline.md / modified.md frontmatter                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_id", CASES)
@pytest.mark.parametrize("kind", ["baseline", "modified"])
def test_markdown_has_synthetic_frontmatter(case_id: str, kind: str) -> None:
    text = (CORPUS_DIR / case_id / f"{kind}.md").read_text()
    assert text.startswith("---\n"), (
        f"{case_id}/{kind}.md: missing YAML frontmatter opener"
    )
    second = text.find("\n---\n", 4)
    assert second > 0, f"{case_id}/{kind}.md: missing frontmatter closer"
    frontmatter = text[4:second]
    assert SYNTHETIC_MARKER in frontmatter, (
        f"{case_id}/{kind}.md: missing '{SYNTHETIC_MARKER}' in frontmatter"
    )
    assert PHYSICIAN_REVIEW_MARKER in frontmatter, (
        f"{case_id}/{kind}.md: missing '{PHYSICIAN_REVIEW_MARKER}' in frontmatter"
    )


# --------------------------------------------------------------------------- #
# grading.json                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_id", CASES)
def test_grading_physician_review_is_null(case_id: str) -> None:
    grading = _load_json(CORPUS_DIR / case_id / "grading.json")
    assert "physician_review" in grading, (
        f"{case_id}: grading.json missing physician_review field"
    )
    assert grading["physician_review"] is None, (
        f"{case_id}: physician_review must be null until countersigned; "
        f"got {grading['physician_review']!r}"
    )
    assert grading.get("physician_review_required") is True


@pytest.mark.parametrize("case_id", CASES)
def test_grading_totals_match_weighted_scores(case_id: str) -> None:
    grading = _load_json(CORPUS_DIR / case_id / "grading.json")
    weights = grading["weights"]
    scores = grading["scores"]

    wt_baseline = sum(
        float(scores["baseline"][cid]) * float(weights[cid]) for cid in weights
    )
    wt_modified = sum(
        float(scores["modified"][cid]) * float(weights[cid]) for cid in weights
    )
    delta = wt_modified - wt_baseline

    claimed_baseline = float(grading["weighted_total"]["baseline"])
    claimed_modified = float(grading["weighted_total"]["modified"])
    claimed_delta = float(grading["delta"])

    assert abs(claimed_baseline - wt_baseline) < 1e-6, (
        f"{case_id}: baseline weighted_total {claimed_baseline} != "
        f"recomputed {wt_baseline}"
    )
    assert abs(claimed_modified - wt_modified) < 1e-6, (
        f"{case_id}: modified weighted_total {claimed_modified} != "
        f"recomputed {wt_modified}"
    )
    assert abs(claimed_delta - delta) < 1e-6, (
        f"{case_id}: delta {claimed_delta} != recomputed {delta}"
    )
    assert delta > 0, (
        f"{case_id}: modified should beat baseline (positive delta); "
        f"got {delta}"
    )


# --------------------------------------------------------------------------- #
# Cross-case consistency                                                       #
# --------------------------------------------------------------------------- #


def test_rubric_references_point_at_sibling_rubric() -> None:
    for case_id in CASES:
        case = _load_json(CORPUS_DIR / case_id / "case.json")
        ref = case["rubric_ref"]
        assert ref == f"corpus/clinical-demo/{case_id}/rubric.json", (
            f"{case_id}: rubric_ref should point at sibling rubric.json; "
            f"got {ref!r}"
        )


def test_case_and_rubric_ids_agree() -> None:
    for case_id in CASES:
        case = _load_json(CORPUS_DIR / case_id / "case.json")
        rubric = _load_json(CORPUS_DIR / case_id / "rubric.json")
        hbh_id = case["healthbench_hard_example_id"]
        expected_rubric_id = f"rubric-{hbh_id}"
        assert rubric["rubric_id"] == expected_rubric_id, (
            f"{case_id}: rubric_id {rubric['rubric_id']!r} does not match "
            f"expected {expected_rubric_id!r}"
        )
