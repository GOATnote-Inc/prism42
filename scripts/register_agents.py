#!/usr/bin/env python3
"""Register Prism Managed Agents on Anthropic.

Default behavior is --dry-run: load every agents/*.yaml and
environments/*.yaml, strip the Prism-only _prism metadata, resolve
callable_agents symbolic names, and print the JSON request bodies
that would be POSTed. No network calls are made in dry-run mode.

Real registration requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_AGENTS_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic client
is only constructed inside the commit branch; dry-run never imports or
instantiates it, so there is no way for a dry-run invocation to touch
api.anthropic.com.

On successful commit, writes agents/manifest.yaml with role -> {id, version}
entries and the environment_id.
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
ENV_DIR = REPO / "environments"
MANIFEST = AGENTS_DIR / "manifest.yaml"

# Create sub-agents first so their {id, version} are known by the time
# the coordinator is created (its callable_agents references them).
ORDER = [
    "defender",
    "attacker",
    "synthesizer",
    "executor",
    "adjudicator",
    "coordinator",
]


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def _strip_prism(cfg: dict) -> dict:
    body = copy.deepcopy(cfg)
    body.pop("_prism", None)
    return body


def build_agent_bodies() -> dict[str, dict]:
    bodies: dict[str, dict] = {}
    for role in ORDER:
        path = AGENTS_DIR / f"prism-{role}.yaml"
        cfg = _load_yaml(path)
        meta = cfg.get("_prism") or {}
        if meta.get("role") != role:
            raise ValueError(f"{path}: _prism.role expected {role!r}, got {meta.get('role')!r}")
        bodies[role] = _strip_prism(cfg)
    return bodies


def build_env_body() -> dict:
    path = ENV_DIR / "prism-standard-env.yaml"
    return _strip_prism(_load_yaml(path))


def resolve_callable_agents(coord_body: dict, manifest_agents: dict[str, dict]) -> dict:
    """Replace ['defender', 'attacker', ...] with [{type, id, version}, ...]."""
    resolved = []
    for role in coord_body.get("callable_agents", []):
        entry = manifest_agents.get(role)
        if entry is None:
            raise ValueError(f"coordinator references unknown callable_agent {role!r}")
        resolved.append({"type": "agent", "id": entry["id"], "version": entry["version"]})
    body = copy.deepcopy(coord_body)
    body["callable_agents"] = resolved
    return body


def _print_body(label: str, body: dict) -> None:
    print(f"--- {label} ---")
    print(json.dumps(body, indent=2, default=str))
    print()


def do_dry_run() -> None:
    """Print request bodies; no network, no client construction."""
    env_body = build_env_body()
    _print_body("POST /v1/environments  (environment: prism-standard-env)", env_body)

    bodies = build_agent_bodies()
    # Fake manifest so coordinator prints with placeholder IDs. Real run
    # would fill these in after each sub-agent create succeeds.
    fake_manifest = {
        role: {"id": f"agt_<{role}_id_placeholder>", "version": 1}
        for role in ORDER
        if role != "coordinator"
    }
    for role in ORDER:
        body = bodies[role]
        if role == "coordinator":
            body = resolve_callable_agents(body, fake_manifest)
        _print_body(f"POST /v1/agents  (role: {role})", body)


def do_commit() -> None:
    """Real Managed Agents registration. Reached only when both gates pass."""
    # The Anthropic client is only constructed in this function. It is
    # never imported or instantiated at module scope and never touched
    # from dry-run. Tests grep for `Anthropic(` — it must stay here.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    client = Anthropic()

    env_body = build_env_body()
    env = client.beta.environments.create(**env_body)
    print(f"environment created: id={env.id}")

    manifest_agents: dict[str, dict] = {}
    bodies = build_agent_bodies()
    for role in ORDER:
        body = bodies[role]
        # anthropic SDK v0.96.0 typed surface for beta.agents.create does
        # not expose `callable_agents`. Multi-agent is RESEARCH PREVIEW
        # (see CLAUDE.md §8): without the workspace flag, the API
        # silently drops this field — the coordinator is created but its
        # runtime tool surface does NOT include sub-agent shims. Until
        # access lands, we strip `callable_agents` from the coordinator
        # body cleanly (rather than pretending `extra_body` bypasses it,
        # which it does not — verified 2026-04-22). The five sub-agent
        # IDs still land in agents/manifest.yaml so they can be bound
        # without a re-register when multi-agent access clears.
        if role == "coordinator":
            body = resolve_callable_agents(body, manifest_agents)
            body.pop("callable_agents", None)  # strip; awaiting research-preview
        created = client.beta.agents.create(**body)
        manifest_agents[role] = {"id": created.id, "version": created.version}
        print(f"agent created: role={role} id={created.id} version={created.version}")

    manifest_doc = {
        "_generated_by": "scripts/register_agents.py --commit",
        "_registered_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "environment_id": env.id,
        "agents": manifest_agents,
    }
    with MANIFEST.open("w") as f:
        yaml.safe_dump(manifest_doc, f, sort_keys=False)
    print(f"manifest written: {MANIFEST}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true",
                    help="Register for real. Requires PRISM_AGENTS_COMMIT=1 in env.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Default behavior; prints request bodies, no network.")
    args = ap.parse_args()

    if args.commit and args.dry_run:
        print("error: --commit and --dry-run are mutually exclusive", file=sys.stderr)
        return 2

    if args.commit:
        if os.environ.get("PRISM_AGENTS_COMMIT") != "1":
            print("error: --commit requires PRISM_AGENTS_COMMIT=1 in env; refusing", file=sys.stderr)
            return 1
        do_commit()
        return 0

    do_dry_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
