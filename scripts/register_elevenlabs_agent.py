#!/usr/bin/env python3
"""Register (or update) the prism42 ElevenLabs ConvAI agent.

Companion to scripts/register_psap_agents.py (Anthropic side). Reads
agents/prism42-elevenlabs.yaml and either:

  1. Creates a fresh ElevenLabs agent via POST /v1/convai/agents/create
     — if no agents/elevenlabs-manifest.yaml exists yet, OR --replace.
  2. Updates an existing agent via PATCH /v1/convai/agents/:agent_id
     — if the manifest carries a prior agent_id.

Default behavior: --dry-run. Prints the exact JSON body that would
be POSTed or PATCHed. Makes no network calls; does not import the
HTTP stack.

Real write requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_ELEVENLABS_COMMIT=1 in the environment.

Third gate: ELEVENLABS_API_KEY must be present in the environment
(never read from disk by this script — the user is expected to have
`set -a && source .env && set +a` before invoking; same pattern as
register_psap_agents.py).

On success, writes agents/elevenlabs-manifest.yaml with:
  agent_id: <returned id>
  name:     <agent name>
  last_written_at: ISO timestamp

Usage:

  python scripts/register_elevenlabs_agent.py                          # dry-run
  python scripts/register_elevenlabs_agent.py --commit                 # still dry-run
  PRISM_ELEVENLABS_COMMIT=1 python scripts/register_elevenlabs_agent.py --commit   # real
  PRISM_ELEVENLABS_COMMIT=1 python scripts/register_elevenlabs_agent.py --commit --replace   # force-create
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
AGENT_YAML = AGENTS_DIR / "prism42-elevenlabs.yaml"
MANIFEST = AGENTS_DIR / "elevenlabs-manifest.yaml"

API_BASE = "https://api.elevenlabs.io/v1/convai/agents"


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def _strip_prism(cfg: dict) -> dict:
    body = copy.deepcopy(cfg)
    body.pop("_prism", None)
    return body


def build_body() -> dict:
    """Load the YAML → API body. The top-level shape is already the
    POST/PATCH body shape, so this is mostly validation + strip.
    """
    if not AGENT_YAML.exists():
        raise FileNotFoundError(f"{AGENT_YAML} missing; expected config file")
    cfg = _load_yaml(AGENT_YAML)
    if cfg.get("name") != "prism42":
        raise ValueError(
            f"{AGENT_YAML}: name expected 'prism42', got {cfg.get('name')!r}"
        )
    agent_cfg = cfg.get("agent_config", {})
    prompt = agent_cfg.get("prompt", {})
    if prompt.get("llm") != "custom-llm":
        raise ValueError(
            f"{AGENT_YAML}: agent_config.prompt.llm must be 'custom-llm' for "
            f"Prism42, got {prompt.get('llm')!r}"
        )
    url = prompt.get("custom_llm", {}).get("url", "")
    if not url.startswith("https://"):
        raise ValueError(
            f"{AGENT_YAML}: agent_config.prompt.custom_llm.url must be https, "
            f"got {url!r}"
        )
    return _strip_prism(cfg)


def load_existing_agent_id() -> str | None:
    if not MANIFEST.exists():
        return None
    prev = _load_yaml(MANIFEST) or {}
    return prev.get("agent_id")


def do_dry_run() -> None:
    body = build_body()
    existing_id = load_existing_agent_id()
    mode = "PATCH" if existing_id else "POST"
    endpoint = f"{API_BASE}/{existing_id}" if existing_id else f"{API_BASE}/create"
    print(f"--- {mode} {endpoint} ---")
    print(json.dumps(body, indent=2, default=str))
    print()
    if existing_id:
        print(
            f"Would PATCH existing agent {existing_id} (from "
            f"{MANIFEST.name}). PATCH is additive; dashboard-set "
            f"voice / first_message / etc. are preserved unless "
            f"this YAML overrides them."
        )
    else:
        print(
            "Would POST a new agent. Response agent_id will be "
            f"written to {MANIFEST}."
        )
    print()
    print("To actually write:")
    print(
        "  PRISM_ELEVENLABS_COMMIT=1 python "
        "scripts/register_elevenlabs_agent.py --commit"
    )


def do_commit(replace: bool) -> None:
    """Real ElevenLabs write. Reached only when both gates pass."""
    # Lazy-import so dry-run never touches api.elevenlabs.io.
    import urllib.request  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY missing from environment — this should "
            "have been caught by the gate in main()"
        )

    body = build_body()
    existing_id = None if replace else load_existing_agent_id()

    if existing_id:
        url = f"{API_BASE}/{existing_id}"
        method = "PATCH"
    else:
        url = f"{API_BASE}/create"
        method = "POST"

    print(f"{method} {url}")

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            resp_json = json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} from ElevenLabs: {err_body}", file=sys.stderr)
        raise

    agent_id = resp_json.get("agent_id") or existing_id
    if not agent_id:
        raise RuntimeError(
            f"No agent_id in response — response was: {resp_json!r}"
        )
    print(f"agent_id: {agent_id}")

    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    manifest = {
        "_generated_by": "scripts/register_elevenlabs_agent.py --commit",
        "last_written_at": now_iso,
        "_notes": (
            "ElevenLabs ConvAI agent config for the prism42 PSAP voice "
            "layer. The Custom LLM backend at "
            "https://prism42-console.vercel.app/prism42/api/chat/completions "
            "owns all clinical logic; this agent is the voice I/O."
        ),
        "agent_id": agent_id,
        "name": body.get("name"),
        "mode": method,
    }
    MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=False))
    print(f"Manifest written: {MANIFEST}")
    print()
    print(
        "Paste this into the Vercel prism42-console project's "
        f"NEXT_PUBLIC_ELEVENLABS_AGENT_ID env var:\n  {agent_id}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register/update the prism42 ElevenLabs ConvAI agent."
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually call the API (requires PRISM_ELEVENLABS_COMMIT=1 env).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Ignore existing agent_id in elevenlabs-manifest.yaml; POST a "
        "fresh agent.",
    )
    args = parser.parse_args()

    if not args.commit:
        do_dry_run()
        return 0

    if os.environ.get("PRISM_ELEVENLABS_COMMIT") != "1":
        print(
            "REFUSED: --commit requires PRISM_ELEVENLABS_COMMIT=1 in "
            "environment."
        )
        print(
            "This is the double-gate pattern for scripts that spend "
            "money or call external APIs. See CLAUDE.md §5."
        )
        return 1

    if not os.environ.get("ELEVENLABS_API_KEY"):
        print("REFUSED: ELEVENLABS_API_KEY not in environment.")
        print("Source .env before invoking: `set -a && source .env && set +a`")
        return 1

    print("Gates passed. Writing agent config to ElevenLabs.")
    print()
    do_commit(replace=args.replace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
