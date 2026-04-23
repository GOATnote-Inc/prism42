#!/usr/bin/env python3
"""Register Prism PSAP Managed Agents on Anthropic.

Companion to scripts/register_agents.py (which registers the 6 existing
benchmarked agents: coordinator + defender/attacker/synthesizer/executor
/adjudicator). This script registers the 14 new PSAP-stack agents that
handle live 911 call simulations at www.thegoatnote.com/prism42.

Agents registered by this script (14 total):

  Tier A — voice-facing (5): psap-intake, psap-triage, psap-dispatch,
                             psap-pdi, psap-handoff
  Tier B — oversight (4)   : psap-safety-monitor, psap-ohca-detector,
                             psap-intent-verifier, psap-rubric-live-shim
                             (the emergency fallback; the hot path runs
                             as a runtime OpenAI chat-completion call
                             outside this registration)
  Tier C — post-session (2): psap-auditor, psap-qi-reviewer
  Tier D — orchestration (3): psap-team-coordinator, prism-ci-safety-expert,
                              prism-release-gate

Agents NOT registered by this script:

  psap-rubric-live (the OpenAI-hot-path grader; runs outside Anthropic
  Managed Agents by design — cross-vendor independence requirement).
  See agents/psap-rubric-live.yaml for the runtime-invoked contract.

Default behavior: --dry-run. Prints every request body that would be
POSTed; makes no network calls; does not import the anthropic SDK.

Real registration requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_PSAP_AGENTS_COMMIT=1 in the environment.

Missing either → refusal + exit 1. The anthropic SDK is only imported
inside do_commit() so dry-run is guaranteed-offline. The AST containment
check in scripts/check_sdk_containment.py verifies this.

On successful commit, writes agents/psap-manifest.yaml with role →
{id, version} entries; reuses the environment from agents/manifest.yaml.

Usage:

  python scripts/register_psap_agents.py                          # dry-run
  python scripts/register_psap_agents.py --commit                 # still dry-run
  PRISM_PSAP_AGENTS_COMMIT=1 python scripts/register_psap_agents.py --commit   # real
  PRISM_PSAP_AGENTS_COMMIT=1 python scripts/register_psap_agents.py --commit --replace   # archive + re-register
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO / "agents"
PSAP_MANIFEST = AGENTS_DIR / "psap-manifest.yaml"
BASE_MANIFEST = AGENTS_DIR / "manifest.yaml"

# Order: Tier A first (voice-facing), then Tier B (oversight), then Tier C
# (post-session), then Tier D (orchestration + governance). Within a tier,
# alphabetical. psap-rubric-live is intentionally excluded (runs via OpenAI
# runtime, not Managed Agents); only its shim is registered.
PSAP_ROLES = [
    # Tier A
    "psap-intake",
    "psap-triage",
    "psap-dispatch",
    "psap-pdi",
    "psap-handoff",
    # Tier B
    "psap-safety-monitor",
    "psap-ohca-detector",
    "psap-intent-verifier",
    "psap-rubric-live-shim",      # circuit-breaker fallback for OpenAI hot path
    # Tier C
    "psap-auditor",
    "psap-qi-reviewer",
    # Tier D
    "psap-team-coordinator",
    "prism-ci-safety-expert",
    "prism-release-gate",
]

# Agents that exist in agents/ but are intentionally NOT registered by this
# script. Documented here so a future reader can see the intent.
NOT_REGISTERED = {
    "psap-rubric-live": (
        "runs as runtime OpenAI chat-completion call (GPT-5.5 primary, "
        "GPT-5.4 fallback); the Anthropic-hosted shim above is the "
        "emergency-only circuit-breaker"
    ),
}


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def _strip_prism(cfg: dict) -> dict:
    """Strip the _prism metadata block + any fields the Anthropic API
    will reject (e.g., custom fallback_chain documentation).
    """
    body = copy.deepcopy(cfg)
    body.pop("_prism", None)
    body.pop("fallback_chain", None)  # documentation-only; not an API field
    return body


def build_psap_bodies() -> dict[str, dict]:
    """Load + validate + strip every PSAP agent YAML."""
    bodies: dict[str, dict] = {}
    for role in PSAP_ROLES:
        path = AGENTS_DIR / f"{role}.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing; expected one YAML per role in PSAP_ROLES"
            )
        cfg = _load_yaml(path)
        meta = cfg.get("_prism") or {}
        # Validate the _prism.role matches the filename.
        if meta.get("role") != role:
            raise ValueError(
                f"{path}: _prism.role expected {role!r}, got {meta.get('role')!r}"
            )
        # Validate name field matches role.
        if cfg.get("name") != role:
            raise ValueError(
                f"{path}: name expected {role!r}, got {cfg.get('name')!r}"
            )
        # Validate model is claude-opus-4-7 (everything in this batch is
        # Anthropic-hosted; the OpenAI hot path for rubric-live is NOT in
        # this script).
        if cfg.get("model") != "claude-opus-4-7":
            raise ValueError(
                f"{path}: model expected 'claude-opus-4-7', got {cfg.get('model')!r}. "
                f"Non-Anthropic models (e.g., gpt-5-5) must not be registered via "
                f"this script; they run as runtime calls outside Managed Agents."
            )
        bodies[role] = _strip_prism(cfg)
    return bodies


def load_base_environment_id() -> str:
    """Reuse the environment the existing 6 agents already run in."""
    if not BASE_MANIFEST.exists():
        raise FileNotFoundError(
            f"{BASE_MANIFEST} missing; run scripts/register_agents.py first "
            f"to establish the base environment."
        )
    manifest = _load_yaml(BASE_MANIFEST)
    env_id = manifest.get("environment_id")
    if not env_id:
        raise ValueError(
            f"{BASE_MANIFEST} has no environment_id; inspect manually."
        )
    return env_id


def _print_body(label: str, body: dict) -> None:
    print(f"--- {label} ---")
    print(json.dumps(body, indent=2, default=str))
    print()


def do_dry_run() -> None:
    """Print request bodies; no network, no client construction."""
    env_id = load_base_environment_id()
    print(f"Using existing environment_id: {env_id}")
    print()

    bodies = build_psap_bodies()
    for role in PSAP_ROLES:
        body = bodies[role]
        _print_body(f"POST /v1/agents  (role: {role})", body)
    print(
        f"(Environment binding {env_id} happens at session-creation time, "
        f"not agent-creation time — the SDK's beta.agents.create does not "
        f"accept environment_id as a kwarg.)"
    )

    # Document the intentionally-skipped agent.
    print("--- INTENTIONALLY NOT REGISTERED ---")
    for role, reason in NOT_REGISTERED.items():
        print(f"  {role}: {reason}")
    print()

    print(f"Dry-run complete. {len(PSAP_ROLES)} agents would be registered.")
    print("To actually register:")
    print("  PRISM_PSAP_AGENTS_COMMIT=1 python scripts/register_psap_agents.py --commit")


def do_commit(replace: bool) -> None:
    """Real Managed Agents registration. Reached only when both gates pass.

    The anthropic SDK is lazy-imported here so dry-run never touches
    api.anthropic.com. The AST guard in scripts/check_sdk_containment.py
    verifies this at CI.
    """
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    client = Anthropic()
    env_id = load_base_environment_id()
    bodies = build_psap_bodies()

    # Idempotent-extend: load existing psap-manifest if present.
    existing: dict = {}
    if PSAP_MANIFEST.exists() and not replace:
        prev = _load_yaml(PSAP_MANIFEST) or {}
        existing = prev.get("agents", {})
        print(f"Found existing psap-manifest with {len(existing)} agents.")

    registered: dict[str, dict] = {}
    for role in PSAP_ROLES:
        body = bodies[role]
        # Environment is bound at session-creation time, not at agent
        # creation. The Anthropic 0.97.0 SDK's beta.agents.create()
        # accepted kwargs are: model, name, description, mcp_servers,
        # metadata, skills, system, tools, betas. `environment_id` is
        # NOT one of them — verified 2026-04-23 via inspect.signature.
        # We keep env_id in the manifest only for downstream session-
        # binding (the live app passes vault_ids / environment_id at
        # session creation).

        if role in existing and not replace:
            entry = existing[role]
            print(f"[skip] {role}: already registered as {entry['id']} v{entry['version']}")
            registered[role] = entry
            continue

        resp = client.beta.agents.create(**body)
        agent_id = resp.id
        version = getattr(resp, "version", 1)
        print(f"[create] {role}: id={agent_id} version={version}")
        registered[role] = {"id": agent_id, "version": version}

    # Write manifest.
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    manifest = {
        "_generated_by": "scripts/register_psap_agents.py --commit",
        "_registered_at": now_iso,
        "_notes": (
            "Registers the 14-agent PSAP stack plus 2 governance agents. "
            "psap-rubric-live (the GPT-5.5 hot path) is intentionally NOT "
            "here — it runs as a runtime OpenAI chat-completion call "
            "outside Managed Agents for cross-vendor independence. The "
            "psap-rubric-live-shim is the Anthropic-hosted circuit-breaker "
            "fallback that fires when both OpenAI models are unavailable "
            "(expected < 0.5% of sessions)."
        ),
        "environment_id": env_id,
        "agents": registered,
        "not_registered": NOT_REGISTERED,
    }
    PSAP_MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=False))
    print()
    print(f"Manifest written: {PSAP_MANIFEST}")
    print(f"  {len(registered)} agents registered.")
    print(f"  {len(NOT_REGISTERED)} agents intentionally not registered.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register Prism PSAP Managed Agents on Anthropic."
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually register (requires PRISM_PSAP_AGENTS_COMMIT=1 env too).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Ignore existing psap-manifest.yaml; re-register everything.",
    )
    args = parser.parse_args()

    if not args.commit:
        do_dry_run()
        return 0

    # Second gate: env var must be set.
    if os.environ.get("PRISM_PSAP_AGENTS_COMMIT") != "1":
        print("REFUSED: --commit requires PRISM_PSAP_AGENTS_COMMIT=1 in environment.")
        print("This is the double-gate pattern for scripts that spend money or call")
        print("external LLM APIs. See CLAUDE.md §5.")
        return 1

    # Third gate: ANTHROPIC_API_KEY must be present (but we do not read its value).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("REFUSED: ANTHROPIC_API_KEY not in environment.")
        print("Source .env before invoking: `set -a && source .env && set +a`")
        return 1

    print("Gates passed. Registering PSAP agents against Anthropic Managed Agents.")
    print()
    do_commit(replace=args.replace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
