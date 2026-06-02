"""Tests for scripts/sample_clinical_subset.py (T4.5b).

Covers:
  - Classification priority (peds > obgyn > psych > emergency > general)
  - Keyword + age-prefix matching
  - Axis derivation from rubric tags
  - Stratified sampling is deterministic under seed
  - Error path when a stratum is short
  - Generated corpus/clinical_subset.yaml structural invariants
    (strata counts match spec, every example carries the fields the
    HealthBench runner reads)

Tests that need the real 1000-example corpus are skipped if it is
missing. Tests that exercise the classifier / axis logic work against
synthetic examples and always run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from sample_clinical_subset import (  # noqa: E402
    CLASS_KEYWORDS,
    STRATA_COUNTS,
    classify,
    derive_target_axis,
    expected_failure_mode,
    render_manifest,
    stratify,
)

SOURCE = Path("/Users/kiteboard/healthbench_frozen/healthbench_hard_canonical_1000.jsonl")
MANIFEST = REPO / "corpus" / "clinical_subset.yaml"
SOURCE_AVAILABLE = SOURCE.exists()
MANIFEST_AVAILABLE = MANIFEST.exists()


def _msg(content: str) -> list[dict]:
    return [{"role": "user", "content": content}]


# --------------------------------------------------------------
# Classifier — priority + keyword coverage
# --------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("A 4-year-old presents to the emergency department.", "pediatrics"),
        ("Pregnant patient at 32 weeks with preterm labor in the ED.", "obgyn"),
        ("Patient with bipolar disorder in the ED after overdose.", "psychiatry"),
        ("Adult with chest pain, acute MI on ECG.", "emergency"),
        ("What is the standard-of-care follow-up for hypertension?", "general"),
    ],
)
def test_priority_ordering(content: str, expected: str) -> None:
    assert classify(_msg(content)) == expected


def test_age_prefix_promotes_to_pediatrics() -> None:
    assert classify(_msg("A 6-year-old with fever.")) == "pediatrics"
    assert classify(_msg("A 3 year old with cough.")) == "pediatrics"
    # Adult ages do not promote.
    assert classify(_msg("A 46-year-old with headache.")) == "general"


def test_generic_falls_to_general() -> None:
    assert classify(_msg("Please summarize the pharmacokinetics of metformin.")) == "general"


def test_class_keywords_has_general_fallthrough() -> None:
    # Invariant: the LAST entry in CLASS_KEYWORDS must be ('general', ())
    # so classify() always returns.
    assert CLASS_KEYWORDS[-1] == ("general", ())


# --------------------------------------------------------------
# Axis derivation
# --------------------------------------------------------------


def test_axis_picks_highest_weight() -> None:
    rubrics = [
        {"criterion": "a", "points": 4, "tags": ["axis:accuracy"]},
        {"criterion": "b", "points": 10, "tags": ["axis:completeness"]},
        {"criterion": "c", "points": 3, "tags": ["axis:accuracy"]},
    ]
    assert derive_target_axis(rubrics) == "completeness"


def test_axis_ignores_negative_points() -> None:
    rubrics = [
        {"criterion": "a", "points": -5, "tags": ["axis:communication"]},
        {"criterion": "b", "points": 1, "tags": ["axis:accuracy"]},
    ]
    assert derive_target_axis(rubrics) == "accuracy"


def test_axis_ties_break_alphabetically() -> None:
    rubrics = [
        {"criterion": "a", "points": 5, "tags": ["axis:completeness"]},
        {"criterion": "b", "points": 5, "tags": ["axis:accuracy"]},
    ]
    assert derive_target_axis(rubrics) == "accuracy"


def test_axis_defaults_when_untagged() -> None:
    rubrics = [{"criterion": "a", "points": 1, "tags": []}]
    assert derive_target_axis(rubrics) == "accuracy"


# --------------------------------------------------------------
# Expected-failure-mode templates
# --------------------------------------------------------------


def test_expected_failure_mode_pending_review_flag() -> None:
    msg = expected_failure_mode("emergency", "accuracy")
    assert "[PENDING-REVIEW]" in msg
    assert "dose" in msg.lower() or "rate" in msg.lower() or "threshold" in msg.lower()


def test_expected_failure_mode_unknown_pair_is_deterministic() -> None:
    msg = expected_failure_mode("nonexistent", "axis")
    assert "[PENDING-REVIEW]" in msg
    assert "nonexistent" in msg
    assert "axis" in msg


# --------------------------------------------------------------
# Stratified sampling — seed determinism, short-stratum error
# --------------------------------------------------------------


def _synthetic_example(prompt_id: str, content: str, rubric_points: int = 1) -> dict:
    return {
        "prompt_id": prompt_id,
        "prompt": _msg(content),
        "rubrics": [
            {"criterion": "c", "points": rubric_points, "tags": ["axis:accuracy"]}
        ],
    }


def test_stratify_same_seed_same_pick() -> None:
    pool = [
        _synthetic_example(f"peds-{i:02d}", "A 5-year-old with fever") for i in range(10)
    ] + [
        _synthetic_example(f"gen-{i:02d}", "Pharmacokinetics question") for i in range(10)
    ]
    counts = {"pediatrics": 2, "general": 2}
    a = stratify(pool, counts, seed=7)
    b = stratify(pool, counts, seed=7)
    assert [ex["prompt_id"] for _, ex in a] == [ex["prompt_id"] for _, ex in b]


def test_stratify_different_seed_different_pick() -> None:
    pool = [
        _synthetic_example(f"gen-{i:02d}", "General medicine question")
        for i in range(20)
    ]
    counts = {"general": 5}
    a = [ex["prompt_id"] for _, ex in stratify(pool, counts, seed=1)]
    b = [ex["prompt_id"] for _, ex in stratify(pool, counts, seed=99)]
    # Not guaranteed different, but extremely likely for 20-choose-5.
    assert a != b


def test_stratify_raises_when_stratum_too_small() -> None:
    pool = [_synthetic_example(f"peds-{i}", "A 5-year-old with fever") for i in range(2)]
    with pytest.raises(RuntimeError, match="Not enough examples"):
        stratify(pool, {"pediatrics": 5}, seed=42)


# --------------------------------------------------------------
# Full-corpus manifest — real source + landed YAML file
# --------------------------------------------------------------


@pytest.mark.skipif(not MANIFEST_AVAILABLE, reason="corpus/clinical_subset.yaml not generated")
def test_manifest_satisfies_spec() -> None:
    m = yaml.safe_load(MANIFEST.read_text())
    assert m["version"] == "0.1.0"
    assert m["total"] == 30
    assert m["seed"] == 42
    assert m["strata_counts"] == STRATA_COUNTS

    # Distribution matches exactly.
    from collections import Counter

    actual = Counter(e["class"] for e in m["examples"])
    for cls, n in STRATA_COUNTS.items():
        assert actual[cls] == n, f"class {cls}: expected {n}, got {actual[cls]}"

    # Spec §5 T4.5 verify gate: at least 3 distinct target_axis values.
    axes = {e["target_axis"] for e in m["examples"]}
    assert len(axes) >= 3

    # Every example carries fields the runner + grader consume.
    for ex in m["examples"]:
        assert ex["id"].startswith("HBH-CLN-")
        assert isinstance(ex["healthbench_hard_example_id"], str)
        assert ex["class"] in STRATA_COUNTS
        assert ex["target_axis"] in {
            "accuracy", "completeness", "context_awareness",
            "instruction_following", "communication",
        }
        assert "[PENDING-REVIEW]" in ex["expected_failure_mode"]
        assert isinstance(ex["messages"], list) and ex["messages"]
        assert isinstance(ex["rubrics"], list) and ex["rubrics"]
        for r in ex["rubrics"]:
            assert "criterion" in r
            assert "points" in r
            assert "tags" in r


@pytest.mark.skipif(not SOURCE_AVAILABLE, reason="HealthBench frozen corpus not present")
def test_render_manifest_round_trip_seed() -> None:
    """Generating from source twice with seed=42 yields identical manifests."""
    from sample_clinical_subset import load_corpus

    examples = load_corpus(SOURCE)
    picked1 = stratify(examples, STRATA_COUNTS, seed=42)
    picked2 = stratify(examples, STRATA_COUNTS, seed=42)
    m1 = render_manifest(picked1, SOURCE, seed=42)
    m2 = render_manifest(picked2, SOURCE, seed=42)
    assert m1 == m2
