#!/usr/bin/env python3
"""Assert the Anthropic SDK is imported and constructed only inside do_commit().

Both scripts/register_agents.py and scripts/harness_runner.py gate real
network access behind --commit + PRISM_*_COMMIT=1. The hard structural
guarantee backing that gate is: the `anthropic` SDK must never be
imported at module scope, and `Anthropic(...)` must never be called
outside the do_commit() function body. This script enforces that with
AST, not regex — comments and strings can't fool it.

Exits 0 on pass, 1 on any violation, printing the offending location.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS = [
    REPO / "scripts" / "register_agents.py",
    REPO / "scripts" / "harness_runner.py",
    REPO / "scripts" / "healthbench_runner.py",
    REPO / "scripts" / "medqa_runner.py",
    REPO / "scripts" / "pubmedqa_runner.py",
    REPO / "scripts" / "mmlu_medical_runner.py",
    REPO / "scripts" / "verify_session_durability.py",
    REPO / "scripts" / "smoke_session.py",
    REPO / "scripts" / "smoke_delegation.py",
    REPO / "scripts" / "run_solo_audit.py",
    REPO / "scripts" / "register_skills.py",
    REPO / "scripts" / "run_skilled_audit.py",
    REPO / "scripts" / "orchestrator.py",
    REPO / "scripts" / "generate_clinical_demo_artifacts.py",
    # Pure-compute generators added 2026-04-22 — none currently import
    # anthropic, but listing them catches a future regression introduced
    # by a contributor who adds SDK use without reading the double-gate
    # policy. Per security sweep low-finding #3.
    REPO / "scripts" / "generate_demo_artifacts.py",
    REPO / "scripts" / "generate_disclosure_artifacts.py",
    REPO / "scripts" / "generate_demo_html.py",
    # T4.7b harness sweep (2026-04-23): new driver that loops 30-example
    # subset through the coordinator and grades the modified responses.
    # Budgeted live spend — containment is mandatory.
    REPO / "scripts" / "harness_sweep.py",
    # Phase M MLA oracle runner. Does not currently import anthropic (MLA
    # oracle runs are pure kernel audits); listing here guards against a
    # future regression where a contributor wires the oracle to call Claude.
    REPO / "scripts" / "mla_oracle_runner.py",
]


def _in_do_commit(stack: list[ast.AST]) -> bool:
    return any(
        isinstance(node, ast.FunctionDef) and node.name == "do_commit"
        for node in stack
    )


def _check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    violations: list[str] = []

    def walk(node: ast.AST, stack: list[ast.AST]) -> None:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("anthropic"):
            if not _in_do_commit(stack):
                violations.append(
                    f"{path}:{node.lineno}: `from anthropic ...` at module scope"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("anthropic") and not _in_do_commit(stack):
                    violations.append(
                        f"{path}:{node.lineno}: `import anthropic` at module scope"
                    )
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "Anthropic" and not _in_do_commit(stack):
                violations.append(
                    f"{path}:{node.lineno}: `Anthropic(...)` call outside do_commit"
                )
        for child in ast.iter_child_nodes(node):
            walk(child, stack + [node])

    walk(tree, [])
    return violations


def main() -> int:
    all_violations: list[str] = []
    for path in TARGETS:
        viols = _check_file(path)
        if viols:
            all_violations.extend(viols)
        else:
            print(f"  ok: {path.relative_to(REPO)}")
    if all_violations:
        print("  FAIL: SDK containment violations:")
        for v in all_violations:
            print(f"    {v}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
