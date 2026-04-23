"""Tests for scripts/check_pipeline_invariants.py.

Each check has a happy-path assertion against the live repo and a
mutation test that rewires the module-level paths at a tmp copy and
asserts the check catches the drift.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_pipeline_invariants as cpi  # noqa: E402


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_all_checks_pass_on_current_repo() -> None:
    """Baseline: the checker must be green on the committed repo state."""

    for name, fn in cpi.CHECKS:
        results = fn()
        if len(results) == 1 and results[0].startswith("skip:"):
            continue
        assert results == [], f"check {name} failed on clean repo: {results}"


def test_main_returns_zero_on_current_repo(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cpi.main()
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "FAIL" not in out


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def cloned_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copies agents/ and environments/ into tmp_path and points the checker at it.

    If a live `agents/manifest.yaml` exists in the source repo (written by
    a successful `scripts/register_agents.py --commit`), it is NOT copied
    so that manifest-absence tests keep their semantics. Tests that want
    a manifest present can write one into `cpi.MANIFEST_FILE` themselves
    (see `test_manifest_roles_happy_when_full`).
    """

    dst_agents = tmp_path / "agents"
    dst_envs = tmp_path / "environments"
    dst_schemas = tmp_path / "schemas"
    shutil.copytree(
        REPO_ROOT / "agents",
        dst_agents,
        ignore=shutil.ignore_patterns("manifest.yaml"),
    )
    shutil.copytree(REPO_ROOT / "environments", dst_envs)
    shutil.copytree(REPO_ROOT / "schemas", dst_schemas)

    monkeypatch.setattr(cpi, "REPO", tmp_path)
    monkeypatch.setattr(cpi, "AGENTS_DIR", dst_agents)
    monkeypatch.setattr(cpi, "ENV_FILE", dst_envs / "prism-standard-env.yaml")
    monkeypatch.setattr(cpi, "MANIFEST_FILE", dst_agents / "manifest.yaml")
    monkeypatch.setattr(cpi, "SCHEMAS_DIR", dst_schemas)
    return tmp_path


def _write_yaml(path: Path, doc: Any) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


# --------------------------------------------------------------------------- #
# (a) agent_model_pins                                                        #
# --------------------------------------------------------------------------- #


def test_agent_model_pins_happy(cloned_repo: Path) -> None:
    assert cpi.check_agent_model_pins() == []


def test_agent_model_pins_catches_older_opus(cloned_repo: Path) -> None:
    path = cloned_repo / "agents" / "prism-defender.yaml"
    doc = _read_yaml(path)
    doc["model"] = "claude-opus-4-6"
    _write_yaml(path, doc)
    violations = cpi.check_agent_model_pins()
    assert len(violations) == 1
    assert "prism-defender.yaml" in violations[0]
    assert "claude-opus-4-6" in violations[0]


def test_agent_model_pins_catches_haiku(cloned_repo: Path) -> None:
    path = cloned_repo / "agents" / "prism-attacker.yaml"
    doc = _read_yaml(path)
    doc["model"] = "claude-haiku-4-5"
    _write_yaml(path, doc)
    violations = cpi.check_agent_model_pins()
    assert any("claude-haiku-4-5" in v for v in violations)


# --------------------------------------------------------------------------- #
# (b) agent_role_matches_filename                                             #
# --------------------------------------------------------------------------- #


def test_agent_role_matches_filename_happy(cloned_repo: Path) -> None:
    assert cpi.check_agent_role_matches_filename() == []


def test_agent_role_matches_filename_catches_swapped_roles(cloned_repo: Path) -> None:
    defender = cloned_repo / "agents" / "prism-defender.yaml"
    attacker = cloned_repo / "agents" / "prism-attacker.yaml"
    d_doc = _read_yaml(defender)
    a_doc = _read_yaml(attacker)
    d_doc["_prism"]["role"] = "attacker"
    a_doc["_prism"]["role"] = "defender"
    _write_yaml(defender, d_doc)
    _write_yaml(attacker, a_doc)
    violations = cpi.check_agent_role_matches_filename()
    assert len(violations) == 2
    joined = " ".join(violations)
    assert "prism-defender.yaml" in joined and "prism-attacker.yaml" in joined


# --------------------------------------------------------------------------- #
# (c) env_egress_allowlist                                                    #
# --------------------------------------------------------------------------- #


def test_env_egress_allowlist_happy(cloned_repo: Path) -> None:
    assert cpi.check_env_egress_allowlist() == []


def test_env_egress_allowlist_catches_rogue_domain(cloned_repo: Path) -> None:
    doc = _read_yaml(cpi.ENV_FILE)
    # Current API shape (SDK v0.96.0 BetaLimitedNetworkParams):
    doc["config"]["networking"]["allowed_hosts"].append("api.badguy.com")
    _write_yaml(cpi.ENV_FILE, doc)
    violations = cpi.check_env_egress_allowlist()
    assert len(violations) == 1
    assert "api.badguy.com" in violations[0]


def test_env_egress_allowlist_rejects_unrestricted_networking(cloned_repo: Path) -> None:
    """Prism requires an explicit allowlist — `type: unrestricted` is a violation."""
    doc = _read_yaml(cpi.ENV_FILE)
    doc["config"]["networking"] = {"type": "unrestricted"}
    _write_yaml(cpi.ENV_FILE, doc)
    violations = cpi.check_env_egress_allowlist()
    assert len(violations) == 1
    assert "unrestricted" in violations[0]


# --------------------------------------------------------------------------- #
# (d) env_mounts_no_secrets                                                   #
# --------------------------------------------------------------------------- #


def test_env_mounts_no_secrets_happy(cloned_repo: Path) -> None:
    assert cpi.check_env_mounts_no_secrets() == []


# Mount-secret invariants are checked against `_prism.aspirational_mounts`
# in the current API shape (mounts are not yet exposed at the API level;
# see environments/prism-standard-env.yaml). When the API gains mounts,
# these tests will also need to cover the top-level `mounts:` path.


def _set_aspirational_mounts(doc: dict, mounts: list[dict]) -> None:
    doc.setdefault("_prism", {})["aspirational_mounts"] = mounts


def _append_aspirational_mount(doc: dict, mount: dict) -> None:
    doc.setdefault("_prism", {}).setdefault("aspirational_mounts", []).append(mount)


def test_env_mounts_no_secrets_catches_dotenv_mount(cloned_repo: Path) -> None:
    doc = _read_yaml(cpi.ENV_FILE)
    _append_aspirational_mount(
        doc, {"source": ".env", "target": "/mnt/prism/.env", "mode": "ro"}
    )
    _write_yaml(cpi.ENV_FILE, doc)
    violations = cpi.check_env_mounts_no_secrets()
    assert len(violations) == 1
    assert ".env" in violations[0]


def test_env_mounts_no_secrets_catches_dotenv_prod_mount(cloned_repo: Path) -> None:
    doc = _read_yaml(cpi.ENV_FILE)
    _append_aspirational_mount(
        doc, {"source": ".env.prod", "target": "/mnt/prism/env", "mode": "ro"}
    )
    _write_yaml(cpi.ENV_FILE, doc)
    violations = cpi.check_env_mounts_no_secrets()
    assert len(violations) == 1
    assert ".env.prod" in violations[0]


def test_env_mounts_no_secrets_catches_secret_word(cloned_repo: Path) -> None:
    doc = _read_yaml(cpi.ENV_FILE)
    _append_aspirational_mount(
        doc, {"source": "config/SECRETS.json", "target": "/x", "mode": "ro"}
    )
    _write_yaml(cpi.ENV_FILE, doc)
    violations = cpi.check_env_mounts_no_secrets()
    assert any("SECRETS" in v for v in violations)


def test_env_mounts_no_secrets_catches_apikey_variants(cloned_repo: Path) -> None:
    for src in ("config/api_key.txt", "config/apikey.json", "config/my-credentials.yml"):
        doc = _read_yaml(cpi.ENV_FILE)
        _set_aspirational_mounts(doc, [{"source": src, "target": "/x", "mode": "ro"}])
        _write_yaml(cpi.ENV_FILE, doc)
        violations = cpi.check_env_mounts_no_secrets()
        assert violations, f"expected violation for source={src!r}"


def test_env_mounts_no_secrets_allows_state_dir(cloned_repo: Path) -> None:
    """`.state/...` paths are explicitly allowed (runpod metadata)."""

    doc = _read_yaml(cpi.ENV_FILE)
    _set_aspirational_mounts(
        doc, [{"source": ".state/runpod-current.json", "target": "/x", "mode": "ro"}]
    )
    _write_yaml(cpi.ENV_FILE, doc)
    assert cpi.check_env_mounts_no_secrets() == []


# --------------------------------------------------------------------------- #
# (e) manifest_roles                                                          #
# --------------------------------------------------------------------------- #


def _full_manifest() -> dict[str, Any]:
    return {
        "environment_id": "env_abc123",
        "agents": {
            role: {"id": f"agent_{role}_001", "version": "0.1.0"}
            for role in cpi.EXPECTED_ROLES
        },
    }


def test_manifest_roles_skips_when_absent(cloned_repo: Path) -> None:
    results = cpi.check_manifest_roles()
    assert results == ["skip: no manifest yet (register_agents.py --commit has not run)"]


def test_manifest_roles_happy_when_full(cloned_repo: Path) -> None:
    _write_yaml(cpi.MANIFEST_FILE, _full_manifest())
    assert cpi.check_manifest_roles() == []


def test_manifest_roles_catches_missing_attacker(cloned_repo: Path) -> None:
    manifest = _full_manifest()
    del manifest["agents"]["attacker"]
    _write_yaml(cpi.MANIFEST_FILE, manifest)
    violations = cpi.check_manifest_roles()
    assert len(violations) == 1
    assert "attacker" in violations[0]
    assert "missing roles" in violations[0]


def test_manifest_roles_catches_missing_id(cloned_repo: Path) -> None:
    manifest = _full_manifest()
    del manifest["agents"]["defender"]["id"]
    _write_yaml(cpi.MANIFEST_FILE, manifest)
    violations = cpi.check_manifest_roles()
    assert any("agents.defender.id" in v for v in violations)


def test_manifest_roles_catches_missing_version(cloned_repo: Path) -> None:
    manifest = _full_manifest()
    manifest["agents"]["coordinator"]["version"] = ""
    _write_yaml(cpi.MANIFEST_FILE, manifest)
    violations = cpi.check_manifest_roles()
    assert any("agents.coordinator.version" in v for v in violations)


def test_manifest_roles_catches_missing_environment_id(cloned_repo: Path) -> None:
    manifest = _full_manifest()
    manifest["environment_id"] = ""
    _write_yaml(cpi.MANIFEST_FILE, manifest)
    violations = cpi.check_manifest_roles()
    assert any("environment_id" in v for v in violations)


# --------------------------------------------------------------------------- #
# (f) schemas_compile                                                         #
# --------------------------------------------------------------------------- #


def test_schemas_compile_happy(cloned_repo: Path) -> None:
    assert cpi.check_schemas_compile() == []


def test_schemas_compile_catches_bad_schema(cloned_repo: Path) -> None:
    bad = cloned_repo / "schemas" / "broken.schema.json"
    # `type` must be a string (or array of strings); a dict is invalid.
    bad.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": {"not": "a type"},
            }
        )
    )
    violations = cpi.check_schemas_compile()
    assert len(violations) == 1
    assert "broken.schema.json" in violations[0]


def test_schemas_compile_catches_invalid_json(cloned_repo: Path) -> None:
    bad = cloned_repo / "schemas" / "malformed.schema.json"
    bad.write_text("{not json")
    violations = cpi.check_schemas_compile()
    assert any("malformed.schema.json" in v and "invalid JSON" in v for v in violations)


# --------------------------------------------------------------------------- #
# main() aggregation                                                          #
# --------------------------------------------------------------------------- #


def test_main_nonzero_on_any_failure(
    cloned_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = cloned_repo / "agents" / "prism-defender.yaml"
    doc = _read_yaml(path)
    doc["model"] = "claude-opus-4-6"
    _write_yaml(path, doc)
    rc = cpi.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL: agent_model_pins" in out
