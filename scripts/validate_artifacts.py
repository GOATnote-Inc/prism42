#!/usr/bin/env python3
"""Prism L1 artifact validator.

Validates each artifact in a case directory against its JSON Schema and
enforces cross-reference rules between artifacts. Designed for offline use:
no network calls, no imports beyond the stdlib and ``jsonschema``.

Usage:
    python scripts/validate_artifacts.py --case-dir /workspace/EXAMPLE-CASE-001
    python scripts/validate_artifacts.py --case-dir /workspace/EXAMPLE-CASE-001 \
        --artifact invariants.json

Install requirements (already in prism-standard-env):
    pip install jsonschema

Exits 0 on pass, 1 on any failure. Failures are printed one per line as
``FAIL: <path> - <reason>``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - dependency check
    sys.stderr.write(
        "ERROR: jsonschema is required. Install with: pip install jsonschema\n"
    )
    raise SystemExit(2) from exc


# --------------------------------------------------------------------------- #
# Artifact registry                                                           #
# --------------------------------------------------------------------------- #

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

# Artifact filename -> schema filename. Ordered so --help lists them clearly.
ARTIFACTS: dict[str, str] = {
    "case.json": "case.schema.json",
    "invariants.json": "invariants.schema.json",
    "attacks.json": "attacks.schema.json",
    "exec.json": "exec.schema.json",
    "verdict.json": "verdict.schema.json",
    "report.md": "report.frontmatter.schema.json",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


# --------------------------------------------------------------------------- #
# Loaders                                                                     #
# --------------------------------------------------------------------------- #


def _load_schema(schema_filename: str) -> dict[str, Any]:
    path = SCHEMA_DIR / schema_filename
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_simple_yaml_mapping(text: str) -> dict[str, Any]:
    """Parse the tiny YAML subset we allow in report.md front-matter.

    Supports ``key: value`` lines with string/int/float/bool. This avoids a
    PyYAML dependency and keeps the validator stdlib + jsonschema only.
    """

    out: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"front-matter line missing ':': {raw!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        elif value.lower() in {"true", "false"}:
            value = value.lower() == "true"
        else:
            try:
                if "." in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass  # leave as string
        out[key] = value
    return out


def _load_report_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("report.md is missing a leading YAML front-matter block")
    return _parse_simple_yaml_mapping(match.group(1))


def _load_artifact(path: Path, artifact_name: str) -> Any:
    if artifact_name == "report.md":
        return _load_report_frontmatter(path)
    return _load_json(path)


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


def _schema_errors(data: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    return errors


def _cross_ref_errors(loaded: dict[str, Any]) -> list[str]:
    """Apply cross-artifact rules. Skips rules whose inputs are absent."""

    errs: list[str] = []
    case = loaded.get("case.json")
    invariants = loaded.get("invariants.json")
    attacks = loaded.get("attacks.json")
    exec_ = loaded.get("exec.json")
    verdict = loaded.get("verdict.json")
    report = loaded.get("report.md")

    # Rule 1: case_id consistency across all present files.
    case_ids: dict[str, str] = {}
    for name, doc in (
        ("case.json", case),
        ("invariants.json", invariants),
        ("attacks.json", attacks),
        ("exec.json", exec_),
        ("verdict.json", verdict),
        ("report.md", report),
    ):
        if isinstance(doc, dict) and "case_id" in doc:
            case_ids[name] = doc["case_id"]
    if len(set(case_ids.values())) > 1:
        errs.append(
            "cross-ref: case_id mismatch across artifacts "
            + ", ".join(f"{k}={v}" for k, v in case_ids.items())
        )

    # Rule 2: every attack.invariant_id must exist in invariants.
    if isinstance(invariants, dict) and isinstance(attacks, dict):
        known = {
            inv["id"]
            for inv in invariants.get("invariants", [])
            if isinstance(inv, dict) and "id" in inv
        }
        for atk in attacks.get("attacks", []):
            if not isinstance(atk, dict):
                continue
            ref = atk.get("invariant_id")
            if ref is not None and ref not in known:
                errs.append(
                    f"cross-ref: attacks.{atk.get('id', '?')} references "
                    f"unknown invariant_id {ref!r}"
                )

    # Rule 3: verdict.run_id == exec.run_id.
    if isinstance(exec_, dict) and isinstance(verdict, dict):
        if exec_.get("run_id") != verdict.get("run_id"):
            errs.append(
                "cross-ref: verdict.run_id does not equal exec.run_id "
                f"({verdict.get('run_id')!r} vs {exec_.get('run_id')!r})"
            )

    # Rule 4: confirmed verdict requires all cross_checks true.
    if isinstance(verdict, dict) and verdict.get("verdict") == "confirmed":
        checks = verdict.get("cross_checks") or {}
        if not all(checks.get(k) is True for k in ("poc_matches_claim", "citations_valid", "severity_consistent")):
            errs.append(
                "cross-ref: verdict.verdict=='confirmed' but cross_checks are not all true"
            )

    # Rule 5: exec.verdict=='attack_failed' => verdict.verdict=='denied'.
    if isinstance(exec_, dict) and isinstance(verdict, dict):
        ev = exec_.get("verdict")
        vv = verdict.get("verdict")
        if ev == "attack_failed" and vv != "denied":
            errs.append(
                f"cross-ref: exec.verdict=='attack_failed' requires verdict.verdict=='denied', got {vv!r}"
            )

    # Rule 6: poc_compile_error / execution_* => verdict.verdict=='inconclusive'.
    if isinstance(exec_, dict) and isinstance(verdict, dict):
        ev = exec_.get("verdict", "") or ""
        vv = verdict.get("verdict")
        if (ev == "poc_compile_error" or ev.startswith("execution_")) and vv != "inconclusive":
            errs.append(
                f"cross-ref: exec.verdict=={ev!r} requires verdict.verdict=='inconclusive', got {vv!r}"
            )

    # Rule 7: report front-matter ids must resolve.
    if isinstance(report, dict):
        if isinstance(invariants, dict):
            inv_ids = {
                inv["id"]
                for inv in invariants.get("invariants", [])
                if isinstance(inv, dict) and "id" in inv
            }
            rid = report.get("invariant_id")
            if rid is not None and rid not in inv_ids:
                errs.append(
                    f"cross-ref: report.invariant_id {rid!r} not found in invariants.json"
                )
        if isinstance(attacks, dict):
            atk_ids = {
                atk["id"]
                for atk in attacks.get("attacks", [])
                if isinstance(atk, dict) and "id" in atk
            }
            aid = report.get("attack_id")
            if aid is not None and aid not in atk_ids:
                errs.append(
                    f"cross-ref: report.attack_id {aid!r} not found in attacks.json"
                )

    return errs


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    artifact_list = ", ".join(ARTIFACTS.keys())
    parser = argparse.ArgumentParser(
        prog="validate_artifacts",
        description=(
            "Validate Prism agent artifacts in a case directory against their "
            "JSON Schemas and enforce cross-reference rules.\n\n"
            f"Supported artifacts: {artifact_list}."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--case-dir",
        required=True,
        help="Path to the case directory (e.g. /workspace/EXAMPLE-CASE-001).",
    )
    parser.add_argument(
        "--artifact",
        choices=list(ARTIFACTS.keys()),
        default=None,
        help=(
            "If set, validate only this single artifact (schema only; "
            "cross-reference checks are skipped). Without this flag, every "
            "present artifact is validated and all applicable cross-reference "
            "checks run."
        ),
    )
    return parser


def _emit_failure(path: Path, reason: str) -> None:
    print(f"FAIL: {path} - {reason}")


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    case_dir = Path(args.case_dir)
    if not case_dir.is_dir():
        print(f"FAIL: {case_dir} - case directory does not exist")
        return 1

    selected = [args.artifact] if args.artifact else list(ARTIFACTS.keys())
    loaded: dict[str, Any] = {}
    failures = 0

    for name in selected:
        path = case_dir / name
        if not path.exists():
            if args.artifact:
                _emit_failure(path, "artifact file does not exist")
                failures += 1
            # skip missing files in sweep mode; mid-pipeline is legal.
            continue

        try:
            data = _load_artifact(path, name)
        except (json.JSONDecodeError, ValueError) as exc:
            _emit_failure(path, f"could not parse: {exc}")
            failures += 1
            continue

        schema = _load_schema(ARTIFACTS[name])
        errors = _schema_errors(data, schema)
        if errors:
            for err in errors:
                _emit_failure(path, err)
            failures += len(errors)
            continue

        loaded[name] = data

    if not args.artifact:
        for err in _cross_ref_errors(loaded):
            print(f"FAIL: {case_dir} - {err}")
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
