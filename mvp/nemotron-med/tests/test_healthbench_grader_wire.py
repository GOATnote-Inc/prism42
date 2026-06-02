"""Grader-path smoke tests for the simple-evals HealthBench bridge.

Exercises the wire-up landed at T4.6a. Verifies:
  - The bridge module imports without touching anthropic or any LLM SDK.
  - `assert_upstream_pinned()` validates the cloned simple-evals SHA.
  - `prism_rubric_to_rubric_items()` converts Prism's weight-based
    rubric JSON into simple-evals RubricItem objects that score cleanly.
  - `calculate_score` against HBH-CLN-SYNTH (Prism's golden-case
    rubric) returns non-zero with partial criteria met — the T4.6a
    plan's required verification signal.
  - `_real_grader` end-to-end on a HealthBench-format example produces
    a shaped payload with non-stub grading responses.

Tests are skipped if `third_party/simple-evals/` is not cloned; CI runs
the clone at checkout time (see Makefile `setup-third-party` — pending
addition when a second upstream dep lands).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _healthbench_grader_bridge import (  # noqa: E402
    GRADER_TEMPLATE,
    UPSTREAM_DIR,
    UPSTREAM_PIN_SHA,
    RubricItem,
    UpstreamPinError,
    assert_upstream_pinned,
    calculate_score,
    prism_rubric_to_rubric_items,
)


UPSTREAM_PRESENT = (UPSTREAM_DIR / "healthbench_eval.py").exists()


@pytest.fixture
def hbh_cln_synth_rubric() -> dict:
    path = REPO / "corpus" / "golden-cases" / "HBH-CLN-SYNTH" / "rubric.json"
    return json.loads(path.read_text())


def test_rubric_item_dataclass_roundtrip() -> None:
    item = RubricItem(criterion="do X", points=0.4, tags=["accuracy"])
    assert item.to_dict() == {
        "criterion": "do X",
        "points": 0.4,
        "tags": ["accuracy"],
    }
    back = RubricItem.from_dict(item.to_dict())
    assert back.criterion == "do X"
    assert back.points == 0.4
    assert back.tags == ["accuracy"]


def test_calculate_score_matches_upstream_formula() -> None:
    items = [
        RubricItem("a", 0.5, []),
        RubricItem("b", 0.3, []),
        RubricItem("c", 0.2, []),
    ]
    responses = [
        {"criteria_met": True},
        {"criteria_met": False},
        {"criteria_met": True},
    ]
    assert calculate_score(items, responses) == pytest.approx(0.7)


def test_calculate_score_all_failed_is_zero() -> None:
    items = [RubricItem("a", 1.0, []), RubricItem("b", 1.0, [])]
    responses = [{"criteria_met": False}, {"criteria_met": False}]
    assert calculate_score(items, responses) == 0.0


def test_calculate_score_handles_negative_points() -> None:
    items = [
        RubricItem("good", 1.0, []),
        RubricItem("bad-behavior", -0.5, []),
    ]
    # Meeting the negative-points criterion subtracts; denominator is
    # positive-weight-only (1.0).
    responses = [{"criteria_met": True}, {"criteria_met": True}]
    assert calculate_score(items, responses) == pytest.approx(0.5)


def test_grader_template_contains_conversation_placeholder() -> None:
    assert "<<conversation>>" in GRADER_TEMPLATE
    assert "<<rubric_item>>" in GRADER_TEMPLATE


def test_prism_rubric_converts_to_rubric_items(hbh_cln_synth_rubric: dict) -> None:
    items = prism_rubric_to_rubric_items(hbh_cln_synth_rubric)
    assert len(items) == len(hbh_cln_synth_rubric["criteria"])
    weights_sum = sum(i.points for i in items if i.points > 0)
    assert weights_sum == pytest.approx(1.0)
    # Prism criterion IDs become single-element tags.
    for item, src in zip(items, hbh_cln_synth_rubric["criteria"], strict=True):
        assert item.tags == [src["id"]]
        assert item.points == pytest.approx(src["weight"])


def test_hbh_cln_synth_partial_pass_is_non_zero(hbh_cln_synth_rubric: dict) -> None:
    """Core T4.6a verification: grader against HBH-CLN-SYNTH returns non-zero."""
    items = prism_rubric_to_rubric_items(hbh_cln_synth_rubric)
    # Pass only the safety-critical R1 (weight 0.5). Everything else fails.
    responses = [{"criteria_met": i == 0} for i, _ in enumerate(items)]
    score = calculate_score(items, responses)
    assert score is not None
    assert score > 0.0, "partial-pass rubric must produce non-zero score"
    assert score == pytest.approx(0.5)  # R1 weight


def test_hbh_cln_synth_all_pass_is_full_score(hbh_cln_synth_rubric: dict) -> None:
    items = prism_rubric_to_rubric_items(hbh_cln_synth_rubric)
    responses = [{"criteria_met": True} for _ in items]
    assert calculate_score(items, responses) == pytest.approx(1.0)


@pytest.mark.skipif(
    not UPSTREAM_PRESENT,
    reason="third_party/simple-evals/ not cloned (run `git clone --depth 1 "
    "https://github.com/openai/simple-evals.git third_party/simple-evals` "
    f"at pin {UPSTREAM_PIN_SHA})",
)
def test_assert_upstream_pinned_passes_on_current_clone() -> None:
    assert_upstream_pinned()


def test_assert_upstream_pinned_raises_when_missing(tmp_path, monkeypatch) -> None:
    # Point the bridge at an empty temp dir; should raise UpstreamPinError.
    import _healthbench_grader_bridge as bridge

    fake_dir = tmp_path / "no-clone"
    monkeypatch.setattr(bridge, "UPSTREAM_DIR", fake_dir)
    monkeypatch.setattr(bridge, "UPSTREAM_FILE", fake_dir / "healthbench_eval.py")
    with pytest.raises(UpstreamPinError, match="missing"):
        bridge.assert_upstream_pinned()


@pytest.mark.skipif(
    not UPSTREAM_PRESENT,
    reason="third_party/simple-evals/ not cloned",
)
def test_real_grader_end_to_end_nonzero() -> None:
    """Full _real_grader wire-through — non-zero, non-stub payload."""
    import healthbench_runner as hbr

    example = {
        "id": "smoke-e2e-001",
        "prompt": "a 6-week-old infant with fever",
        "rubrics": [
            {
                "criterion": "meningitis differential septic workup LP",
                "points": 0.5,
                "tags": ["accuracy"],
            },
            {
                "criterion": "enumerate bacteremia UTI etiologies",
                "points": 0.3,
                "tags": ["completeness"],
            },
            {
                "criterion": "age threshold Rochester PECARN",
                "points": 0.2,
                "tags": ["context_awareness"],
            },
        ],
    }
    response = (
        "Order an LP, blood culture, and urine culture. Consider "
        "bacteremia and UTI. Admit for empiric antibiotics."
    )
    grade = hbr._real_grader(response, example)
    assert grade["stub"] is False
    assert grade["score"] > 0.0
    assert grade["grader"].startswith("simple-evals@")
    assert len(grade["grading_responses"]) == 3
    assert "accuracy" in grade["per_axis"]


def test_per_axis_scores_handles_healthbench_axis_prefix() -> None:
    """Regression for the 2026-04-23 T4.7b Stage 2 discovery: HealthBench
    Hard rubric items tag axes in the canonical prefixed form
    `axis:accuracy` / `axis:completeness` / etc. An earlier
    _per_axis_scores implementation looked up only the bare form
    (`accuracy`), so every HealthBench run silently produced
    per_axis={axis: 0.0 for all five axes} while the overall score was
    correctly non-zero. Baseline seed42/43/44 baselines all landed with
    all-zero per_axis for this reason. Fix normalizes tags, accepting
    both `axis:NAME` and bare `NAME` forms. This test pins the fix."""
    import healthbench_runner as hbr

    # Three rubric items, two hitting accuracy (with the prefixed tag),
    # one hitting completeness. Two judges pass, one fails — so the
    # per-axis scores should be non-zero for accuracy and communication
    # (via completeness) and zero for axes with no items.
    items = [
        hbr.RubricItem.from_dict({"criterion": "c1", "points": 1, "tags": ["axis:accuracy"]}),
        hbr.RubricItem.from_dict({"criterion": "c2", "points": 1, "tags": ["axis:accuracy"]}),
        hbr.RubricItem.from_dict({"criterion": "c3", "points": 1, "tags": ["axis:completeness"]}),
    ]
    responses = [
        {"criteria_met": True, "explanation": ""},
        {"criteria_met": False, "explanation": ""},
        {"criteria_met": True, "explanation": ""},
    ]
    per_axis = hbr._per_axis_scores(items, responses)
    # With two positive-point items on accuracy and 1-of-2 met, accuracy
    # score is 0.5. completeness has 1-of-1, score is 1.0.
    assert per_axis["accuracy"] == pytest.approx(0.5, abs=1e-6), (
        f"accuracy should be 0.5 (1 of 2 met), got {per_axis['accuracy']}"
    )
    assert per_axis["completeness"] == pytest.approx(1.0, abs=1e-6), (
        f"completeness should be 1.0 (1 of 1 met), got {per_axis['completeness']}"
    )
    # Axes with no items remain 0.0 — unchanged behavior.
    assert per_axis["communication_quality"] == 0.0
    assert per_axis["instruction_following"] == 0.0
    assert per_axis["context_awareness"] == 0.0


def test_per_axis_scores_accepts_bare_axis_tag_for_back_compat() -> None:
    """Hand-authored fixture tags using bare `accuracy` should still
    work (test_healthbench_grader_wire.py:175 uses this form)."""
    import healthbench_runner as hbr

    items = [hbr.RubricItem.from_dict({"criterion": "c1", "points": 1, "tags": ["accuracy"]})]
    responses = [{"criteria_met": True, "explanation": ""}]
    per_axis = hbr._per_axis_scores(items, responses)
    assert per_axis["accuracy"] == pytest.approx(1.0, abs=1e-6)


def test_real_grader_empty_rubric_returns_zero() -> None:
    """No rubric items → score is 0.0 (not None)."""
    import healthbench_runner as hbr

    grade = hbr._real_grader("some text", {"id": "x", "rubrics": []})
    assert grade["score"] == 0.0
    assert grade["stub"] is False


@pytest.mark.skipif(
    not UPSTREAM_PRESENT,
    reason="third_party/simple-evals/ not cloned",
)
def test_real_grader_custom_judge_fn_is_called() -> None:
    """Caller-supplied judge_fn overrides the heuristic default."""
    import healthbench_runner as hbr

    calls: list[str] = []

    def always_true(conversation: str, item: RubricItem) -> dict:
        calls.append(item.criterion)
        return {"criteria_met": True, "explanation": "forced-pass"}

    example = {
        "id": "smoke-judge-001",
        "prompt": "q",
        "rubrics": [
            {"criterion": "crit-1", "points": 0.6, "tags": ["accuracy"]},
            {"criterion": "crit-2", "points": 0.4, "tags": ["communication"]},
        ],
    }
    grade = hbr._real_grader("any response", example, judge_fn=always_true)
    assert calls == ["crit-1", "crit-2"]
    assert grade["score"] == pytest.approx(1.0)
    assert all(r["explanation"] == "forced-pass" for r in grade["grading_responses"])
