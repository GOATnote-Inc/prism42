"""Pytest conftest for the Prism L3 golden-case test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


# Tests that read kernel corpus (absent in prism42)
# as input. Those files are absent from this public tree (held privately
# under coordinated-disclosure discipline); tests skip automatically when
# inputs are missing. When present (e.g. a local checkout with a synthetic
# corpus), the tests run unchanged.
_CORPUS_DEPENDENT_TESTS = {
    ("test_demo_artifacts.py", "test_commit_with_env_writes_four_files"),
    ("test_demo_artifacts.py", "test_json_shape"),
    ("test_demo_artifacts.py", "test_metadata_has_git_sha_and_source_hashes"),
    ("test_demo_artifacts.py", "test_aggregate_line_present"),
    ("test_demo_artifacts.py", "test_no_technique_prose_from_notes"),
    ("test_demo_html.py", "test_no_leaked_notes_prose"),
    ("test_demo_html.py", "test_all_gpu_bug_ids_present"),
    ("test_disclosure_artifacts.py", "test_commit_writes_per_bug_files"),
    ("test_disclosure_artifacts.py", "test_index_shape"),
    ("test_disclosure_artifacts.py", "test_email_placeholders_filled"),
    ("test_disclosure_artifacts.py", "test_per_bug_md_has_frontmatter"),
    ("test_disclosure_artifacts.py", "test_redaction_no_forbidden_fields"),
    ("test_disclosure_artifacts.py", "test_no_technique_prose_from_notes"),
    ("test_disclosure_artifacts.py", "test_routing_routes_all_bugs"),
}


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_validator: test requires scripts/validate_artifacts.py from the L1 agent",
    )


def pytest_collection_modifyitems(config, items) -> None:
    """Skip tests whose inputs are absent from the public tree.

    If both inputs are present (e.g. a synthetic corpus was rebuilt locally),
    no test is skipped — the skipif is strictly conditional on real file
    absence, not a permanent xfail.
    """
    repo_root = Path(__file__).resolve().parent.parent
    kernel_bugs = repo_root / "corpus" / "kernel_bugs.yaml"
    if kernel_bugs.exists():
        return
    skip_marker = pytest.mark.skip(
        reason="corpus inputs absent in public tree; "
        "rebuild synthetic fixtures to re-enable",
    )
    for item in items:
        try:
            file_name = item.path.name
        except AttributeError:
            file_name = Path(item.nodeid.split("::", 1)[0]).name
        if (file_name, item.name) in _CORPUS_DEPENDENT_TESTS:
            item.add_marker(skip_marker)
