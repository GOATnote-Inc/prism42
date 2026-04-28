"""Ralph-loop self-verification — checks the hypothesis ladder, decisions log,
rubric, and tests stay coherent.

Runs on every push via CI (see make verify-all extension) and on-demand.
Exit 0 if coherent; nonzero + structured stderr if not.

Charter §4 says "every action ends with a verification step whose exit code
proves the claim." This is that verification step for the Ralph loop itself
— it proves the claim "the ladder, log, rubric, and test suite are
consistent at this commit."

Checks performed:
  1. Every `answered (*)` row in HYPOTHESIS_LADDER.md has a matching
     `phase: "reflect"` row in ralph_decisions.jsonl with the same
     hypothesis ID.
  2. Every `phase: "reflect"` in ralph_decisions has a corresponding
     ladder row with that ID.
  3. Every `verdict` in ralph reflect rows is one of the allowed enum
     values.
  4. ralph_decisions.jsonl parses as strict JSONL (one valid JSON object
     per non-blank line).
  5. EVALUATION_RUBRIC.md's latest version pin must appear in at least
     one ralph_decisions row (enforces that a rubric bump requires a
     grounding session).
  6. HYPOTHESIS_LADDER.md row IDs are unique (no duplicate H{N} sections).

Exit code = number of failed checks.

Self-improving property: every new hypothesis closure adds a reflect row
and an answered ladder entry; this script rejects diverged PRs structurally
rather than depending on humans remembering each time.

Usage:
    python mla/scripts/verify_ralph_consistency.py
    python mla/scripts/verify_ralph_consistency.py --verbose
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


VALID_VERDICTS = {
    "supported",
    "partially-supported",
    "falsified",
    "partially-falsified",
    "premise-falsified",
    "inconclusive",
}


def _load_ralph_decisions(path: Path) -> list[dict]:
    rows: list[dict] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError as e:
            raise SystemExit(f"[FAIL] ralph_decisions.jsonl line {i} is not valid JSON: {e}")
    return rows


def _extract_ladder_rows(ladder_text: str) -> list[dict]:
    """Parse HYPOTHESIS_LADDER.md rows. Returns list of {id, header, status, body}."""
    rows = []
    pattern = re.compile(r"^### (H[\d.]+)\s*—\s*(.*?)$", re.MULTILINE)
    matches = list(pattern.finditer(ladder_text))
    for i, m in enumerate(matches):
        hid = m.group(1)
        header = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(ladder_text)
        body = ladder_text[body_start:body_end]
        status_match = re.search(r"\*\*Status:\*\*\s*`([^`]+)`", body)
        status = status_match.group(1).strip() if status_match else None
        inline_falsified = bool(re.search(
            r"(FALSIFIED|premise.falsified|partially.falsified|SUPPORTED)",
            header, re.IGNORECASE,
        ))
        rows.append({
            "id": hid,
            "header": header,
            "body": body,
            "status": status,
            "inline_falsified": inline_falsified,
        })
    return rows


def _check_unique_ids(ladder_rows: list[dict]) -> list[str]:
    seen = {}
    dupes = []
    for r in ladder_rows:
        if r["id"] in seen:
            dupes.append(
                f"duplicate H id {r['id']!r} (headers: {seen[r['id']]!r} AND {r['header']!r})"
            )
        else:
            seen[r["id"]] = r["header"]
    return dupes


def _check_answered_has_reflect(ladder_rows: list[dict], ralph_rows: list[dict]) -> list[str]:
    reflected_ids = {
        r["hypothesis"] for r in ralph_rows
        if r.get("phase") == "reflect" and r.get("hypothesis")
    }
    errors = []
    for row in ladder_rows:
        is_answered = (row["status"] and "answered" in row["status"]) or row["inline_falsified"]
        if is_answered and row["id"] not in reflected_ids:
            errors.append(
                f"ladder row {row['id']} is answered/falsified but ralph_decisions "
                f"has no phase=reflect row for it"
            )
    return errors


def _check_reflect_has_ladder_entry(ladder_rows: list[dict], ralph_rows: list[dict]) -> list[str]:
    ladder_ids = {r["id"] for r in ladder_rows}
    errors = []
    for r in ralph_rows:
        if r.get("phase") == "reflect" and r.get("hypothesis"):
            if r["hypothesis"] not in ladder_ids:
                errors.append(
                    f"ralph reflect row cites hypothesis {r['hypothesis']!r} "
                    f"but no matching ladder row"
                )
    return errors


def _check_verdict_enum(ralph_rows: list[dict]) -> list[str]:
    errors = []
    for r in ralph_rows:
        if r.get("phase") == "reflect" and "verdict" in r:
            if r["verdict"] not in VALID_VERDICTS:
                errors.append(
                    f"ralph reflect row has invalid verdict {r['verdict']!r}; "
                    f"allowed: {sorted(VALID_VERDICTS)}"
                )
    return errors


def _check_rubric_version_grounded(rubric_path: Path, ralph_rows: list[dict]) -> list[str]:
    text = rubric_path.read_text()
    # Match: `- **v1.1 (any desc):**` or `version **v1.0** (prose)`
    all_versions = re.findall(r"\*\*v(\d+\.\d+)\s", text)
    if not all_versions:
        all_versions = re.findall(r"version \*\*v(\d+\.\d+)", text)
    if not all_versions:
        return ["could not parse rubric version from EVALUATION_RUBRIC.md"]
    latest = max(all_versions, key=lambda v: tuple(int(x) for x in v.split(".")))
    cited = {r.get("rubric") for r in ralph_rows if r.get("rubric")}
    errors = []
    for v in cited:
        if v and not re.fullmatch(r"v\d+\.\d+", v):
            errors.append(f"ralph row cites malformed rubric version {v!r}")
    if f"v{latest}" not in cited:
        errors.append(
            f"rubric latest version v{latest} not cited by any ralph_decisions "
            f"row — rubric bump without grounding session?"
        )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parent.parent.parent
    ladder_path = root / "docs" / "mla-corpus" / "HYPOTHESIS_LADDER.md"
    ralph_path = root / "mla" / "results" / "logs" / "ralph_decisions.jsonl"
    rubric_path = root / "mla" / "docs" / "EVALUATION_RUBRIC.md"

    for p in (ladder_path, ralph_path, rubric_path):
        if not p.exists():
            print(f"[FAIL] missing required file: {p}", file=sys.stderr)
            return 1

    ladder_rows = _extract_ladder_rows(ladder_path.read_text())
    ralph_rows = _load_ralph_decisions(ralph_path)

    failures = []
    failures += _check_unique_ids(ladder_rows)
    failures += _check_answered_has_reflect(ladder_rows, ralph_rows)
    failures += _check_reflect_has_ladder_entry(ladder_rows, ralph_rows)
    failures += _check_verdict_enum(ralph_rows)
    failures += _check_rubric_version_grounded(rubric_path, ralph_rows)

    if args.verbose:
        print(f"[info] ladder rows: {len(ladder_rows)}")
        print(f"[info] ralph rows: {len(ralph_rows)}")
        reflects = [r for r in ralph_rows if r.get("phase") == "reflect"]
        print(f"[info] reflect rows: {len(reflects)}")
        for r in reflects:
            print(f"       {str(r.get('hypothesis','?')):<8s} "
                  f"{str(r.get('verdict','?')):<24s} {r.get('ts','?')}")

    if not failures:
        print(f"[OK] ralph consistency: {len(ladder_rows)} ladder rows, "
              f"{len(ralph_rows)} ralph_decisions rows, all coherent.")
        return 0

    print(f"[FAIL] {len(failures)} consistency check(s) failed:", file=sys.stderr)
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
