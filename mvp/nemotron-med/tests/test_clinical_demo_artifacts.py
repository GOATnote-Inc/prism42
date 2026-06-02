"""Tests for scripts/generate_clinical_demo_artifacts.py.

Subprocess pattern mirrors tests/test_demo_artifacts.py. Invariants:
  - dry-run writes nothing; exit 0.
  - --commit without PRISM_CLINICAL_DEMO_COMMIT=1 refuses (exit 1).
  - env var alone stays dry-run (exit 0, no writes).
  - both gates write 2 rubric-card.md + methodology.md + INDEX.md +
    metadata.json (5 files) plus 2 CLN-DEMO-* subdirs.
  - every rubric-card.md carries synthetic + physician-review-required
    markers.
  - rubric-card weight rows sum to 1.0.
  - modified weighted total beats baseline (positive delta) for every
    case.
  - INDEX.md has one row per case with non-empty axis + delta.
  - metadata.json carries git_sha + source_file_sha256 dict + run_id.
  - "PHI" only appears in negated form in any output file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_clinical_demo_artifacts.py"
CORPUS = REPO_ROOT / "corpus" / "clinical-demo"

SYNTHETIC_MARKER = "synthetic: true"
PHYSICIAN_REVIEW_MARKER = "physician-review-required: true"
CASES = ("CLN-DEMO-001", "CLN-DEMO-002")


def _run(
    out_dir: Path,
    *,
    commit: bool = False,
    env_var: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_var:
        env["PRISM_CLINICAL_DEMO_COMMIT"] = "1"
    elif "PRISM_CLINICAL_DEMO_COMMIT" in env:
        del env["PRISM_CLINICAL_DEMO_COMMIT"]
    args = [
        sys.executable,
        str(SCRIPT),
        "--corpus-dir",
        str(CORPUS),
        "--out-dir",
        str(out_dir),
    ]
    if commit:
        args.append("--commit")
    return subprocess.run(args, capture_output=True, text=True, env=env)


def _children(p: Path) -> list[str]:
    if not p.exists():
        return []
    return sorted(x.name for x in p.iterdir())


# --------------------------------------------------------------------------- #
# Gating                                                                      #
# --------------------------------------------------------------------------- #


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    res = _run(out)
    assert res.returncode == 0, res.stderr
    assert "(dry-run)" in res.stdout
    assert _children(out) == []


def test_commit_without_env_refuses(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    res = _run(out, commit=True, env_var=False)
    assert res.returncode == 1
    assert "refusing" in res.stderr
    assert "PRISM_CLINICAL_DEMO_COMMIT=1" in res.stderr
    assert _children(out) == []


def test_env_without_commit_stays_dry_run(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    res = _run(out, commit=False, env_var=True)
    assert res.returncode == 0
    assert "(dry-run)" in res.stdout
    assert _children(out) == []


# --------------------------------------------------------------------------- #
# File production                                                             #
# --------------------------------------------------------------------------- #


def test_commit_writes_expected_files(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    res = _run(out, commit=True, env_var=True)
    assert res.returncode == 0, res.stderr
    names = _children(out)
    assert "methodology.md" in names
    assert "metadata.json" in names
    assert "INDEX.md" in names
    for case_id in CASES:
        assert case_id in names, f"missing case subdir {case_id}"
        card = out / case_id / "rubric-card.md"
        assert card.is_file(), f"missing {card}"


def test_rubric_cards_have_both_markers(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    for case_id in CASES:
        text = (out / case_id / "rubric-card.md").read_text()
        assert SYNTHETIC_MARKER in text, (
            f"{case_id}/rubric-card.md missing '{SYNTHETIC_MARKER}'"
        )
        assert PHYSICIAN_REVIEW_MARKER in text, (
            f"{case_id}/rubric-card.md missing '{PHYSICIAN_REVIEW_MARKER}'"
        )


def test_rubric_card_weights_sum_to_one(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    for case_id in CASES:
        text = (out / case_id / "rubric-card.md").read_text()
        rows = [
            ln for ln in text.splitlines()
            if re.match(r"^\| R\d+ \|", ln)
        ]
        assert rows, f"{case_id}: no rubric rows found in card"
        weights = []
        for row in rows:
            cells = [c.strip() for c in row.split("|")[1:-1]]
            weights.append(float(cells[1]))
        total = sum(weights)
        assert abs(total - 1.0) < 1e-9, (
            f"{case_id}: rubric card weight sum is {total}, not 1.0"
        )


def test_delta_sign_is_positive(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    for case_id in CASES:
        text = (out / case_id / "rubric-card.md").read_text()
        m = re.search(
            r"Delta \(modified - baseline\):\s+\*\*([+-]?\d*\.\d+)\*\*",
            text,
        )
        assert m, f"{case_id}: could not find delta line"
        delta = float(m.group(1))
        assert delta > 0, (
            f"{case_id}: modified must beat baseline; delta={delta}"
        )


def test_index_has_both_cases(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    text = (out / "INDEX.md").read_text()
    rows = [ln for ln in text.splitlines() if ln.startswith("| CLN-DEMO-")]
    assert len(rows) == len(CASES), (
        f"expected {len(CASES)} rows in INDEX.md, got {len(rows)}"
    )
    for row in rows:
        cells = [c.strip() for c in row.split("|")[1:-1]]
        # Columns: case, axis, baseline, modified, delta, synthetic, review.
        assert len(cells) == 7, f"unexpected row shape: {row!r}"
        for i, col in enumerate(cells):
            assert col, f"empty cell {i} in row: {row!r}"


def test_index_has_both_markers(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    text = (out / "INDEX.md").read_text()
    assert SYNTHETIC_MARKER in text
    assert PHYSICIAN_REVIEW_MARKER in text


def test_metadata_shape(tmp_path: Path) -> None:
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    meta = json.loads((out / "metadata.json").read_text())
    assert "generated_at" in meta
    assert "run_id" in meta
    assert "git_sha" in meta
    assert "source_file_sha256" in meta
    assert meta["n_cases"] == len(CASES)
    for case_id in CASES:
        for fname in ("case.json", "rubric.json", "grading.json",
                      "baseline.md", "modified.md"):
            key = f"{case_id}/{fname}"
            assert key in meta["source_file_sha256"], (
                f"metadata.source_file_sha256 missing {key!r}"
            )
            assert len(meta["source_file_sha256"][key]) == 64


# --------------------------------------------------------------------------- #
# Redaction / labeling contract                                                #
# --------------------------------------------------------------------------- #


def test_no_phi_language_in_outputs(tmp_path: Path) -> None:
    """PHI should only appear in negated form ('not PHI', 'no PHI')."""
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    negated = re.compile(r"\b(no|not|never|without|negated)\s+PHI\b",
                         re.IGNORECASE)
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text()
        for match in re.finditer(r"\bPHI\b", text):
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 5)
            snippet = text[start:end]
            assert negated.search(snippet), (
                f"{path.name}: unflagged PHI mention: {snippet!r}"
            )


def test_no_gpu_rail_forbidden_fields_in_clinical_outputs(
    tmp_path: Path,
) -> None:
    """Clinical-rail outputs must not leak GPU-rail redaction-denied keys."""
    out = tmp_path / "clinical-demo"
    _run(out, commit=True, env_var=True)
    forbidden = ("repro_shape", "revert_method", "pre_fix:", "post_fix:")
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text()
        for f in forbidden:
            assert f not in text, (
                f"{path.name}: forbidden GPU-rail substring {f!r} in "
                f"clinical-demo output"
            )
