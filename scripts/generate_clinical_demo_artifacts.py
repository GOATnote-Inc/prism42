#!/usr/bin/env python3
"""Generate the physician-facing clinical-rail demo artifact set from
synthetic fixtures under corpus/clinical-demo/.

Outputs (under --out-dir, default results/clinical-demo/):
  - CLN-DEMO-<id>/rubric-card.md : per-case human-readable rubric card
  - methodology.md               : clinical-rail mechanism note
  - metadata.json                : {generated_at, git_sha, source_file_sha256, run_id}
  - INDEX.md                     : table listing every case with its delta

Every output file carries `synthetic: true` and `physician-review-required:
true` markers. The word "PHI" appears only in negated form (e.g., "no PHI").

Default behavior is --dry-run: load fixtures, print the plan, write
nothing, exit 0. Real writes require BOTH:
  1) --commit on the command line, AND
  2) PRISM_CLINICAL_DEMO_COMMIT=1 in the environment.

Missing either one prints a refusal to stderr and exits 1. This script
never imports `anthropic` (pure compute, no network).

Callable API:
    run_clinical_demo(corpus_dir, out_dir, run_id) -> dict[str, Path]
returns a mapping of short-name -> absolute Path for the emitted files.
Intended to be called from a Managed Agents coordinator without the
subprocess shell detour.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

SYNTHETIC_MARKER = "synthetic: true"
PHYSICIAN_REVIEW_MARKER = "physician-review-required: true"


def _load_json(path: Path) -> dict:
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object at top level")
    return data


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
        + "Z"
    )


def _discover_cases(corpus_dir: Path) -> list[Path]:
    """Return CLN-DEMO-* case subdirs under corpus_dir, sorted by name."""
    if not corpus_dir.exists():
        return []
    return sorted(
        p for p in corpus_dir.iterdir()
        if p.is_dir() and p.name.startswith("CLN-DEMO-")
    )


def _load_case_bundle(case_dir: Path) -> dict[str, Any]:
    """Load the five fixture files for one case and validate basic invariants."""
    case = _load_json(case_dir / "case.json")
    rubric = _load_json(case_dir / "rubric.json")
    grading = _load_json(case_dir / "grading.json")

    weight_sum = sum(float(c["weight"]) for c in rubric["criteria"])
    if abs(weight_sum - 1.0) > 1e-9:
        raise AssertionError(
            f"{case_dir.name}: rubric weights sum to {weight_sum}, not 1.0"
        )

    scores = grading["scores"]
    weights = grading["weights"]
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
    if (
        abs(claimed_baseline - wt_baseline) > 1e-6
        or abs(claimed_modified - wt_modified) > 1e-6
        or abs(claimed_delta - delta) > 1e-6
    ):
        raise AssertionError(
            f"{case_dir.name}: weighted_total/delta in grading.json "
            f"disagrees with recomputed values "
            f"(baseline {wt_baseline:.4f}, modified {wt_modified:.4f}, "
            f"delta {delta:.4f})"
        )

    if grading.get("physician_review") is not None:
        raise AssertionError(
            f"{case_dir.name}: physician_review must be null until countersigned; "
            f"got {grading['physician_review']!r}"
        )

    baseline_md = (case_dir / "baseline.md").read_text()
    modified_md = (case_dir / "modified.md").read_text()
    for kind, text in (("baseline", baseline_md), ("modified", modified_md)):
        if SYNTHETIC_MARKER not in text:
            raise AssertionError(
                f"{case_dir.name}/{kind}.md: missing '{SYNTHETIC_MARKER}' marker"
            )
        if PHYSICIAN_REVIEW_MARKER not in text:
            raise AssertionError(
                f"{case_dir.name}/{kind}.md: missing "
                f"'{PHYSICIAN_REVIEW_MARKER}' marker"
            )

    return {
        "case": case,
        "rubric": rubric,
        "grading": grading,
        "weighted": {
            "baseline": wt_baseline,
            "modified": wt_modified,
            "delta": delta,
        },
    }


def _render_rubric_card(bundle: dict[str, Any]) -> str:
    case = bundle["case"]
    rubric = bundle["rubric"]
    grading = bundle["grading"]
    wt = bundle["weighted"]

    scores = grading["scores"]
    weights = grading["weights"]

    lines: list[str] = []
    lines.append("---")
    lines.append(SYNTHETIC_MARKER)
    lines.append(PHYSICIAN_REVIEW_MARKER)
    lines.append(f"case_id: {case['case_id']}")
    lines.append(f"rubric_id: {rubric['rubric_id']}")
    lines.append(f"target_axis: {case['target_axis']}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Rubric card — {case['case_id']} (synthetic)")
    lines.append("")
    lines.append(
        "> **Synthetic fixture.** Not patient data, not PHI, not for clinical "
        "use. Requires physician review before any disclosure channel."
    )
    lines.append("")
    lines.append("## Case")
    lines.append("")
    lines.append(f"**HealthBench Hard example id:** `{case['healthbench_hard_example_id']}`  ")
    lines.append(f"**Target axis:** `{case['target_axis']}`  ")
    lines.append(f"**Class:** `{case.get('class', 'other')}`  ")
    lines.append(f"**Severity estimate:** `{case.get('severity_estimate', 'medium')}`")
    lines.append("")
    lines.append(f"{case.get('target_path', '').strip()}")
    lines.append("")

    lines.append("## Rubric (weights sum to 1.0)")
    lines.append("")
    lines.append("| ID | Weight | Baseline | Modified | Delta | Description |")
    lines.append("|---|---|---|---|---|---|")
    for crit in rubric["criteria"]:
        cid = crit["id"]
        w = float(weights[cid])
        b = float(scores["baseline"][cid])
        m = float(scores["modified"][cid])
        d = m - b
        desc = crit["description"].replace("|", "\\|")
        lines.append(f"| {cid} | {w:.2f} | {b:.2f} | {m:.2f} | {d:+.2f} | {desc} |")
    lines.append("")

    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- Baseline weighted total: **{wt['baseline']:.2f}**")
    lines.append(f"- Modified weighted total: **{wt['modified']:.2f}**")
    lines.append(f"- Delta (modified - baseline): **{wt['delta']:+.2f}**")
    lines.append("")

    lines.append("## Physician sign-off")
    lines.append("")
    lines.append(
        "This card MUST be countersigned by a board-certified physician "
        "before it is shared outside the repository. The `physician_review` "
        "field in `grading.json` is `null`; code never pre-signs it."
    )
    lines.append("")
    lines.append("- physician_review: **null** (unsigned)")
    lines.append(
        "- disclosure channel (post-sign-off): Anthropic model-feedback "
        "channel under the posture in `docs/clinical-handling.md`."
    )
    lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(
        "Baseline and modified transcripts in this bundle are hand-authored "
        "synthetic stand-ins that illustrate the kind of delta the harness "
        "is designed to surface. When `scripts/harness_runner.py` runs for "
        "real (T4.7b, gated behind `--commit` + `PRISM_HARNESS_COMMIT=1`), "
        "the synthetic transcripts are replaced by live Claude Opus 4.7 "
        "responses. The rubric and case shape stay the same."
    )
    lines.append("")
    return "\n".join(lines)


def _render_methodology() -> str:
    return """---
synthetic: true
physician-review-required: true
---

# Prism — Clinical rail methodology

This note describes how Prism produces a rubric-graded delta on the
clinical rail. It is the companion to the GPU-rail flip summary in
`results/demo/`.

> Every artifact under `results/clinical-demo/` is synthetic. Not
> patient data, not PHI, not for clinical use.

## Five-agent managed dialectic

A single coordinator session delegates to five callable agents (one
level of delegation, shared filesystem):

- defender — asserts clinical-rubric criteria from the case descriptor.
- attacker — generates adversarial prompt variants that stress the axis
  under audit (e.g., anchoring bait, representativeness shortcuts).
- synthesizer — packages the rubric into a runnable grading harness
  against the baseline and the modified transcript.
- executor — invokes the grader (`simple-evals`-equivalent rubric
  scorer) against both transcripts.
- adjudicator — produces a verdict, but never pre-signs the
  physician-review field.

The model is Claude Opus 4.7. The beta header is
`managed-agents-2026-04-01`.

## Five rubric axes

HealthBench Hard scores along five axes: accuracy, completeness,
context_awareness, instruction_following, communication. Every
clinical-demo case selects a subset of axes and lists its criteria with
weights that sum to 1.0. The safety-critical criterion carries the
dominant weight so that an otherwise well-written response that misses
the named decision rule does not pass.

## Synthetic-fixture discipline

The clinical-demo bundle is entirely synthetic. The baseline and
modified transcripts are hand-authored to stress the target axis, not
sampled from a model. This is intentional: the demo is about
**mechanism** (how the harness surfaces a rubric delta), not about
**claim** (that Opus 4.7 beats some baseline on this case). Live runs
happen under `PRISM_HARNESS_COMMIT=1` only, after physician sign-off on
the rubric.

## Physician-in-the-loop gate

Nothing in this directory is cleared for any disclosure channel without
a board-certified physician countersigning the `physician_review` field
in `grading.json`. Code never pre-signs it. The disclosure target is
the Anthropic model-feedback channel under the posture described in
`docs/clinical-handling.md` — never a preprint server, never social
media, never a public issue tracker.

## Benchmark discipline

No clinical technique ships without a measured delta on a Phase B
scorer: HealthBench Hard (rubric, primary), MedQA + MMLU-Medical-6
(null-result controls, `|delta| <= 0.01`), PubMedQA (RAG validator,
lift >= 10pp). The synthetic demo here does not substitute for those
runs; it illustrates the rubric shape that real runs will grade.
"""


def _render_index(bundles: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append(SYNTHETIC_MARKER)
    lines.append(PHYSICIAN_REVIEW_MARKER)
    lines.append("---")
    lines.append("")
    lines.append("# Prism — Clinical demo index")
    lines.append("")
    lines.append(
        f"{len(bundles)} synthetic ED-reasoning cases. Each row is a "
        "rubric-graded delta between a baseline response and a "
        "harness-modified response. No patient data, no PHI. Every card "
        "requires physician review before any disclosure."
    )
    lines.append("")
    lines.append(
        "| Case | Axis | Baseline | Modified | Delta | Synthetic | "
        "Physician review |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for b in bundles:
        case_id = b["case"]["case_id"]
        axis = b["case"]["target_axis"]
        wt = b["weighted"]
        lines.append(
            f"| {case_id} | {axis} | {wt['baseline']:.2f} | "
            f"{wt['modified']:.2f} | {wt['delta']:+.2f} | yes | required |"
        )
    lines.append("")
    lines.append("## What each card contains")
    lines.append("")
    lines.append(
        "- Case summary (target axis, class, severity estimate)."
    )
    lines.append(
        "- Per-criterion rubric table with weight, baseline score, "
        "modified score, delta."
    )
    lines.append("- Aggregate weighted totals + delta.")
    lines.append(
        "- Physician sign-off field (unsigned; `physician_review: null`)."
    )
    lines.append(
        "- Provenance statement naming the synthetic nature of the "
        "transcripts."
    )
    lines.append("")
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def run_clinical_demo(
    corpus_dir: Path,
    out_dir: Path,
    run_id: str,
) -> dict[str, Path]:
    """Write the clinical-demo artifact set and return their paths.

    Loads every CLN-DEMO-* bundle under ``corpus_dir``, renders a rubric
    card per case, writes methodology + metadata + INDEX at the top
    level of ``out_dir``, and returns a mapping of short-name to Path.

    Raises ``AssertionError`` if any bundle fails its structural
    invariants (rubric weights must sum to 1.0; claimed weighted totals
    must match recomputed values; physician_review must be null;
    baseline/modified markdown must carry synthetic + physician-review
    markers).
    """
    case_dirs = _discover_cases(corpus_dir)
    if not case_dirs:
        raise AssertionError(f"no CLN-DEMO-* cases found under {corpus_dir}")

    bundles = [_load_case_bundle(d) for d in case_dirs]

    for bundle in bundles:
        if bundle["weighted"]["delta"] <= 0:
            cid = bundle["case"]["case_id"]
            raise AssertionError(
                f"{cid}: delta must be positive (modified should pass, "
                f"baseline should fail); got {bundle['weighted']['delta']}"
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    source_sha: dict[str, str] = {}

    for case_dir, bundle in zip(case_dirs, bundles):
        case_id = bundle["case"]["case_id"]
        card_dir = out_dir / case_id
        card_dir.mkdir(parents=True, exist_ok=True)
        card_path = card_dir / "rubric-card.md"
        _write(card_path, _render_rubric_card(bundle))
        paths[f"rubric_card_{case_id}"] = card_path

        for fname in ("case.json", "rubric.json", "grading.json",
                      "baseline.md", "modified.md"):
            fpath = case_dir / fname
            source_sha[f"{case_id}/{fname}"] = _sha256_file(fpath)

    methodology_path = out_dir / "methodology.md"
    _write(methodology_path, _render_methodology())
    paths["methodology_md"] = methodology_path

    index_path = out_dir / "INDEX.md"
    _write(index_path, _render_index(bundles))
    paths["index_md"] = index_path

    metadata_path = out_dir / "metadata.json"
    _write_json(
        metadata_path,
        {
            "generated_at": _now_iso(),
            "run_id": run_id,
            "git_sha": _git_sha(),
            "n_cases": len(bundles),
            "source_file_sha256": source_sha,
        },
    )
    paths["metadata_json"] = metadata_path

    return paths


def do_dry_run(args: argparse.Namespace, run_id: str) -> int:
    corpus_dir = Path(args.corpus_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    case_dirs = _discover_cases(corpus_dir)
    n_cases = len(case_dirs)

    print("(dry-run) generate_clinical_demo_artifacts.py plan:")
    print(f"  corpus_dir       : {corpus_dir}")
    print(f"  out_dir          : {out_dir}")
    print(f"  run_id           : {run_id}")
    print(f"  discovered cases : {n_cases}")
    for d in case_dirs:
        print(f"    - {d.name}")
    print(f"  would write      : {n_cases} x CLN-DEMO-*/rubric-card.md,")
    print(f"                     methodology.md, INDEX.md, metadata.json")
    print("(dry-run) no files written; no network activity")
    return 0


def do_commit(args: argparse.Namespace, run_id: str) -> int:
    corpus_dir = Path(args.corpus_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    paths = run_clinical_demo(corpus_dir, out_dir, run_id)
    print(f"(commit) run_id={run_id}")
    for name, path in paths.items():
        print(f"(commit) wrote {name}: {path}")
    print(
        f"(commit) clinical-demo artifacts written to: {out_dir} "
        f"(synthetic; physician-review-required)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--corpus-dir",
        default=str(REPO / "corpus" / "clinical-demo"),
        help="Directory containing CLN-DEMO-* case subdirs (read-only).",
    )
    ap.add_argument(
        "--out-dir",
        default=str(REPO / "results" / "clinical-demo"),
        help="Output directory (gitignored via results/).",
    )
    ap.add_argument(
        "--seed", type=int, default=42, help="Unused; kept for uniformity."
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Write files. Requires PRISM_CLINICAL_DEMO_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--run-id",
        default=None,
        help="Optional UUID for this run; generated if absent.",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=0.0,
        help="Kept for uniformity; this script makes no paid calls.",
    )
    args = ap.parse_args(argv)

    run_id = args.run_id or str(uuid.uuid4())

    if args.commit and os.environ.get("PRISM_CLINICAL_DEMO_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and "
            "PRISM_CLINICAL_DEMO_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args, run_id)
    return do_dry_run(args, run_id)


if __name__ == "__main__":
    sys.exit(main())
