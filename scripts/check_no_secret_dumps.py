#!/usr/bin/env python3
"""Scan tracked files + recent logs for value-dumping patterns.

Two P0 secret-exposure incidents on 2026-04-27 (operator rotated all
seven keys): assistant ran commands that print env values verbatim
into the conversation transcript. This linter banishes that class of
shell pattern from the repo so it can't recur in:
  - committed shell scripts
  - markdown docs (e.g., runbooks pasted in PRs)
  - findings/ logs
  - CI workflows

Detects:
  - `systemctl show ... --property=Environment`
  - `cat /proc/<pid>/environ`
  - `printenv` (with no arg = full dump)
  - `env` as a bare command on its own line
  - `cat .env` / `cat *.env` / `cat */.env`
  - `grep -E 'KEY=|TOKEN=|SECRET='` (matches the value side)
  - bash heredocs / EOF blocks containing literal secret strings

Allowed shape (the only one that should ever appear):
  awk -F= '/KEY=|TOKEN=|SECRET=/{print $1, "len:", length($2)}' ENV_FILE
                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                 prints NAMES and LENGTHS only,
                                 never the value.

Exit codes:
  0 — no value-dump patterns found
  1 — at least one violation; offending lines printed to stderr

Usage:
  python scripts/check_no_secret_dumps.py
  python scripts/check_no_secret_dumps.py --paths agents/livekit findings/

Banned-pattern table is `BANNED` below. Whitelist literal occurrences
in `WHITELIST_PATHS` only when the pattern appears as documented
counter-example or in this very file.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Banned patterns. Each entry is (regex, human label).
# Patterns must NOT match values themselves; they match the SHAPE of
# commands that print values. Keep this list short and load-bearing.
BANNED: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"systemctl\s+show\b.*--property\s*=\s*Environment\b"),
        "systemctl show --property=Environment dumps every Environment= line verbatim",
    ),
    (
        re.compile(r"\bcat\s+/proc/[^\s]+/environ\b"),
        "cat /proc/<pid>/environ prints null-separated env values verbatim",
    ),
    (
        re.compile(r"^\s*printenv\s*(?:\|.*)?$", re.MULTILINE),
        "bare `printenv` (no arg) prints every env var with values",
    ),
    (
        re.compile(r"^\s*env\s*(?:\|.*)?$", re.MULTILINE),
        "bare `env` on its own line prints every env var with values",
    ),
    (
        re.compile(r"\bcat\s+(?:[^\s]+/)?\.env(?:\b|\s|$)"),
        "cat .env prints the full env file including values",
    ),
    (
        re.compile(r"\bcat\s+[^\s]*\*\.env\b"),
        "cat <glob>.env prints env file values verbatim",
    ),
    (
        # Only flag greps that mention secret-class variable NAMES on
        # the value side. Test fixtures that grep for non-secret keys
        # (e.g. streaming=True) don't match.
        re.compile(
            r"grep[^|]*-[a-zA-Z]*E[a-zA-Z]*\s+['\"][^'\"]*"
            r"(?:KEY|TOKEN|SECRET|PASSWORD|API|CREDENTIAL)[^'\"]*=[^'\"]*['\"]",
            re.IGNORECASE,
        ),
        "grep -E '...KEY=...' on .env prints the matched value — use awk name+length",
    ),
]

# File globs to scan. Production code + ops + CI only — `findings/`
# is forensic-immutable history (past debugging, including pre-rule
# patterns documented as part of incident reports), and we don't
# rewrite history just to satisfy the linter.
SCAN_GLOBS = [
    "agents/**/*.py",
    "agents/**/*.sh",
    "scripts/**/*.py",
    "scripts/**/*.sh",
    "infra/**/*.sh",
    "infra/**/*.py",
    "infra/**/*.yml",
    "infra/**/*.yaml",
    "infra/**/Dockerfile",
    "mvp/**/*.sh",
    "mvp/**/*.ts",
    "mvp/**/*.tsx",
    "tests/**/*.py",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "Makefile",
    "CLAUDE.md",
    "README.md",
    "docs/**/*.md",
]

# Paths that may legitimately contain pattern strings (this file +
# clinical-log incident reports + the contract file, where the rule
# is explained or the incident is described).
WHITELIST_PATHS = {
    "scripts/check_no_secret_dumps.py",
    "findings/clinical-log.jsonl",
    "findings/ops/parallel-session-coord.md",
    "CLAUDE.md",
    "docs/secret-hygiene.md",
}

# Paths to skip entirely
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    ".next",
    "__pycache__",
    "third_party",
    "vendor",
    ".claude/worktrees",
}


def iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for glob in SCAN_GLOBS:
        for p in root.glob(glob):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if str(rel) in WHITELIST_PATHS:
                continue
            out.append(p)
    return sorted(set(out))


def scan(root: Path) -> int:
    violations: list[tuple[Path, int, str, str]] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        for pattern, label in BANNED:
            for m in pattern.finditer(text):
                # 1-based line number
                line_no = text.count("\n", 0, m.start()) + 1
                full_line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
                snippet = full_line.strip()[:160]
                # Per-line allowlist: lines containing
                # `secret-dump-allowed` (typically as a trailing
                # comment) opt out. Use SPARINGLY — only when the
                # output is redirected to a file (chmod 600) and
                # never reaches a terminal/log. Check the FULL line,
                # not the truncated snippet.
                if "secret-dump-allowed" in full_line:
                    continue
                violations.append((path.relative_to(root), line_no, label, snippet))
    if not violations:
        return 0
    print("BANNED VALUE-DUMP PATTERNS FOUND:", file=sys.stderr)
    for rel, line_no, label, snippet in violations:
        print(f"  {rel}:{line_no}  [{label}]", file=sys.stderr)
        print(f"    > {snippet}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Replace with name+length-only patterns, e.g.:",
        file=sys.stderr,
    )
    print(
        "  awk -F= '/KEY=|TOKEN=|SECRET=/{print $1, \"len:\", length($2)}' ENV_FILE",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repo root (default: parent of scripts/)",
    )
    args = ap.parse_args()
    return scan(Path(args.root))


if __name__ == "__main__":
    sys.exit(main())
