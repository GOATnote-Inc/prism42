#!/usr/bin/env python3
"""Assert Prism pipeline-level invariants that silent drift could break.

`check_sdk_containment.py` pins *where* the Anthropic SDK may appear.
This script pins the rest: every agent is pinned to the benchmark model,
role labels match filenames, the environment's egress allow-list has not
grown unexpected domains, no mount exposes secrets, the committed
manifest (if any) covers all six roles, and every JSON Schema actually
compiles as draft 2020-12.

Each check is a standalone function returning a list of violation
strings. `main()` runs them all, prints one "ok" or "FAIL" line per
check (with details on FAIL), and exits 1 if any check failed.

Exits 0 on pass, 1 on any failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, SchemaError

REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO / "agents"
ENV_FILE = REPO / "environments" / "prism-standard-env.yaml"
MANIFEST_FILE = AGENTS_DIR / "manifest.yaml"
SCHEMAS_DIR = REPO / "schemas"

PINNED_MODEL = "claude-opus-4-7"
KNOWN_EGRESS = {
    "api.anthropic.com",
    "api.openai.com",
    "rest.runpod.io",
    "cloud.lambdalabs.com",
    # Phase M: Google Cloud TPU rail (gcp_tpu_exec.sh → gcloud → TPU VM).
    # Added 2026-04-22.
    "compute.googleapis.com",
    "tpu.googleapis.com",
    "storage.googleapis.com",
    "oauth2.googleapis.com",
}
EXPECTED_ROLES = {
    "coordinator",
    "defender",
    "attacker",
    "synthesizer",
    "executor",
    "adjudicator",
}

# Case-insensitive fragments that must not appear in a mount source path.
_SECRET_PAT = re.compile(
    r"(^|/)\.env(\.|$|/)|secret|credential|api[_-]?key",
    re.IGNORECASE,
)


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("prism-*.yaml"))


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


# --------------------------------------------------------------------------- #
# Checks                                                                      #
# --------------------------------------------------------------------------- #


def check_agent_model_pins() -> list[str]:
    """Every agent YAML must pin `model: claude-opus-4-7`."""

    violations: list[str] = []
    for path in _agent_files():
        cfg = _load_yaml(path)
        model = cfg.get("model")
        if model != PINNED_MODEL:
            violations.append(
                f"{path.relative_to(REPO)}: model={model!r} (expected {PINNED_MODEL!r})"
            )
    return violations


def check_agent_role_matches_filename() -> list[str]:
    """`prism-<role>.yaml` must have `_prism.role == <role>`."""

    violations: list[str] = []
    for path in _agent_files():
        expected = path.stem.removeprefix("prism-")
        cfg = _load_yaml(path)
        role = (cfg.get("_prism") or {}).get("role")
        if role != expected:
            violations.append(
                f"{path.relative_to(REPO)}: _prism.role={role!r} (expected {expected!r})"
            )
    return violations


def check_env_egress_allowlist() -> list[str]:
    """environments/prism-standard-env.yaml config.networking.allowed_hosts must be a subset of KNOWN_EGRESS.

    Reads the live API body location (`config.networking.allowed_hosts`,
    aligned with anthropic SDK v0.96.0 BetaLimitedNetworkParams). The
    older top-level `network.egress_allow` path is still accepted as a
    fallback for any historical YAML in flight during the shape
    migration.
    """

    violations: list[str] = []
    if not ENV_FILE.exists():
        return [f"{ENV_FILE.relative_to(REPO)}: missing"]
    cfg = _load_yaml(ENV_FILE)
    networking = (cfg.get("config") or {}).get("networking") or {}
    egress: list = []
    if networking.get("type") == "limited":
        egress = networking.get("allowed_hosts") or []
    elif networking.get("type") == "unrestricted":
        violations.append(
            f"{ENV_FILE.relative_to(REPO)}: config.networking.type == 'unrestricted' "
            "— Prism requires an explicit allowlist"
        )
        return violations
    else:
        # Fallback: legacy top-level shape. Kept for migration windows.
        egress = ((cfg.get("network") or {}).get("egress_allow")) or []
    if not isinstance(egress, list):
        return [f"{ENV_FILE.relative_to(REPO)}: networking allowed_hosts must be a list"]
    extras = sorted(set(egress) - KNOWN_EGRESS)
    if extras:
        violations.append(
            f"{ENV_FILE.relative_to(REPO)}: unknown egress domain(s) {extras!r} "
            f"(known-safe set is {sorted(KNOWN_EGRESS)!r})"
        )
    return violations


def check_env_mounts_no_secrets() -> list[str]:
    """No mount source may look like a secret/credential path.

    The API as of SDK v0.96.0 does not expose host-file mounts; Prism
    documents its design-intent mounts under `_prism.aspirational_mounts`
    so the invariant still applies when the feature lands.
    """

    violations: list[str] = []
    if not ENV_FILE.exists():
        return [f"{ENV_FILE.relative_to(REPO)}: missing"]
    cfg = _load_yaml(ENV_FILE)
    # Prefer the API-shape location when it materializes; fall back to the
    # aspirational bucket under `_prism` otherwise. Legacy top-level
    # `mounts` is also accepted for migration windows.
    mounts = (
        cfg.get("mounts")
        or ((cfg.get("_prism") or {}).get("aspirational_mounts"))
        or []
    )
    for entry in mounts:
        src = (entry or {}).get("source", "")
        if not isinstance(src, str):
            violations.append(f"{ENV_FILE.relative_to(REPO)}: non-string mount source {src!r}")
            continue
        # Allow `.state/...` (runpod pod metadata, not a secret).
        if src.startswith(".state/") or src == ".state":
            continue
        if _SECRET_PAT.search(src):
            violations.append(
                f"{ENV_FILE.relative_to(REPO)}: mount source {src!r} looks like a secret path"
            )
    return violations


def check_manifest_roles() -> list[str]:
    """If agents/manifest.yaml exists, it must cover all 6 roles with id+version, plus environment_id."""

    if not MANIFEST_FILE.exists():
        return ["skip: no manifest yet (register_agents.py --commit has not run)"]
    cfg = _load_yaml(MANIFEST_FILE)
    violations: list[str] = []

    env_id = cfg.get("environment_id")
    if not isinstance(env_id, str) or not env_id.strip():
        violations.append(
            f"{MANIFEST_FILE.relative_to(REPO)}: environment_id must be a non-empty string"
        )

    agents_block = cfg.get("agents") or {}
    if not isinstance(agents_block, dict):
        violations.append(
            f"{MANIFEST_FILE.relative_to(REPO)}: agents block must be a mapping"
        )
        return violations

    present = set(agents_block.keys())
    missing = sorted(EXPECTED_ROLES - present)
    extra = sorted(present - EXPECTED_ROLES)
    if missing:
        violations.append(
            f"{MANIFEST_FILE.relative_to(REPO)}: missing roles {missing!r}"
        )
    if extra:
        violations.append(
            f"{MANIFEST_FILE.relative_to(REPO)}: unexpected roles {extra!r}"
        )
    for role in sorted(EXPECTED_ROLES & present):
        entry = agents_block.get(role) or {}
        if not isinstance(entry, dict):
            violations.append(
                f"{MANIFEST_FILE.relative_to(REPO)}: agents.{role} must be a mapping"
            )
            continue
        id_val = entry.get("id")
        if not isinstance(id_val, str) or not id_val.strip():
            violations.append(
                f"{MANIFEST_FILE.relative_to(REPO)}: agents.{role}.id must be a non-empty string"
            )
        # `version` is accepted as either a non-negative int (anthropic SDK
        # returns `created.version: int`) or a non-empty string (semver
        # form used by the test fixture). Both identify a version slot.
        version_val = entry.get("version")
        version_ok = (
            (isinstance(version_val, int) and version_val >= 0)
            or (isinstance(version_val, str) and version_val.strip() != "")
        )
        if not version_ok:
            violations.append(
                f"{MANIFEST_FILE.relative_to(REPO)}: agents.{role}.version must be int or non-empty string"
            )
    return violations


def check_schemas_compile() -> list[str]:
    """Every schemas/*.json must compile as draft 2020-12."""

    violations: list[str] = []
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            schema = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            violations.append(f"{path.relative_to(REPO)}: invalid JSON ({exc})")
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            violations.append(
                f"{path.relative_to(REPO)}: schema does not compile ({exc.message})"
            )
    return violations


CHECKS = [
    ("agent_model_pins", check_agent_model_pins),
    ("agent_role_matches_filename", check_agent_role_matches_filename),
    ("env_egress_allowlist", check_env_egress_allowlist),
    ("env_mounts_no_secrets", check_env_mounts_no_secrets),
    ("manifest_roles", check_manifest_roles),
    ("schemas_compile", check_schemas_compile),
]


def main() -> int:
    rc = 0
    for name, fn in CHECKS:
        results = fn()
        # A single-element "skip: ..." list is an informative pass.
        if len(results) == 1 and results[0].startswith("skip:"):
            print(f"  ok: {name} ({results[0]})")
            continue
        if not results:
            print(f"  ok: {name}")
            continue
        rc = 1
        print(f"  FAIL: {name}:")
        for v in results:
            print(f"    {v}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
