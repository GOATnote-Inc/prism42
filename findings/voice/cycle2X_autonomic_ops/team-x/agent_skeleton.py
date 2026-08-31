"""Cycle-2X autonomic-ops coordinator — Anthropic Managed Agent skeleton.

Status
------
SPEC ONLY in cycle-2X. Default OFF. The integrator runs `python agent_skeleton.py
--create` exactly once to register the agent on the workspace; nothing is
auto-invoked. Heartbeat sessions are started by the integrator after review of
the cycle-2X charter + tool-surface.yaml.

What this file does
-------------------
1. Loads the tool surface from tool-surface.yaml in this directory.
2. Registers a single coordinator Managed Agent (`claude.beta.agents.create`)
   with model `claude-opus-4-7`, beta header `managed-agents-2026-04-01`,
   built-in `agent_toolset_20260401`, and the custom tools enumerated in the
   YAML.
3. Optionally writes the registered agent ID to
   `findings/voice/cycle2X_autonomic_ops/team-x/.agent_id` so the integrator
   can start sessions later.

What this file does NOT do
--------------------------
- Does NOT call `client.beta.sessions.create(...)` (no autonomic loop running).
- Does NOT touch the pod (no SSH, no curl, no service control).
- Does NOT invoke any custom tools — it only declares them at agent-create.
- Does NOT depend on `callable_agents`. Per CLAUDE.md §8 and memory note
  `managed_agents_multi_agent_verified.md`, multi-agent is silently stripped
  on this workspace's API key as of 2026-04-22. Upgrade path: see the
  `multi_agent_upgrade` block in tool-surface.yaml.

Usage
-----
Dry-run (default; safe to run anywhere):
    python agent_skeleton.py

Register the agent (requires ANTHROPIC_API_KEY + explicit gate):
    PRISM42_AUTONOMIC_REGISTER=1 python agent_skeleton.py --create

Print the would-be create payload as JSON without calling the API:
    python agent_skeleton.py --print-payload

Citations
---------
- Anthropic Managed Agents overview (fetched 2026-04-26):
  https://platform.claude.com/docs/en/managed-agents/overview
- Tools / `agent_toolset_20260401` (fetched 2026-04-26):
  https://platform.claude.com/docs/en/managed-agents/tools
- Custom tool best practices: same Tools page, "Best practices for custom
  tool definitions".
- Workspace multi-agent strip: CLAUDE.md §8 + memory
  `managed_agents_multi_agent_verified.md`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# YAML is the only third-party import; pyyaml is already in the repo's
# pyproject.toml (used by env loader, scribegoat2 cross-ref). Keep import
# inside main() so a `--print-payload` invocation in a clean shell can show
# the payload schema without requiring yaml installed (we fall back to a
# hand-coded dict in that case — see `_TOOL_SURFACE_FALLBACK` below).

HERE = Path(__file__).parent.resolve()
TOOL_SURFACE_YAML = HERE / "tool-surface.yaml"
AGENT_ID_FILE = HERE / ".agent_id"

# ─────────────────────────────────────────────────────────────────────
# Coordinator system prompt (single agent; no callable_agents)
# ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are the prism42 autonomic-ops coordinator agent. You wrap the prism42
voice stack on the Brev B300 pod (b300-pod). You DO NOT sit on
the voice critical path. You are a sidecar.

Your loop, per heartbeat tick (default 30 s):

1. Call `pod_smi`, `vllm_health`, `livekit_health`, `pod_journalctl` (60 s
   window) in parallel. Synthesize a heartbeat event.
2. Classify state into nominal / warn / degraded / failing per the rules in
   the cycle-2X charter (heartbeat-design.md §4).
3. Emit one `prism42.heartbeat` event via `heartbeat_publish` every tick.
4. On state transition into warn or worse, emit `prism42.alert`.
5. Auto-recovery is OFF unless the matching env-flag is set on the host.
   You learn which flags are armed by calling `bash` with
   `env | grep ^PRISM42_AUTONOMIC_` and caching the result for the session.
6. ONE service may be touched per tick. After any gated_destructive call,
   you enter a 5-tick cooldown during which only passive_read tools are
   allowed.
7. Three consecutive auto-recovery actions on the same service in a 30-min
   window halts your loop — you write `findings/voice/cycle2X_autonomic_ops/
   incidents/halt-<ts>.json` and stop emitting heartbeats. The integrator
   restarts you manually.

Hard rules:
- Never touch /opt/prism42/agents/ or /opt/prism42/voice-refs/. Frozen.
- Never call `service_restart`, `cuda_checkpoint_ctl`, or `restore_invoke`
  without explicit gate flag. The handlers refuse without the flag, but you
  must not waste budget calling them speculatively.
- Never propose changes to worker.py, orchestrator.py, dispatcher_fsm.py,
  fish_speech_tts.py, dispatch_publisher.py, templates.py, or response_gate.py.
- Verify state via `pod_smi` or `vllm_health` immediately before AND after
  every gated_destructive action. Both probes must agree on the expected
  pre/post state.

Provenance: every action you take ends with an `incident_log_write` call
that appends a JSON object describing what you did, what you observed, and
why. This is your durable audit trail.
"""

# ─────────────────────────────────────────────────────────────────────
# Hand-coded fallback if yaml is not importable (lets --print-payload work
# in a minimal shell). Mirrors the YAML's custom_tools list, abbreviated.
# ─────────────────────────────────────────────────────────────────────
_TOOL_SURFACE_FALLBACK: dict[str, Any] = {
    "agent_name": "prism42-autonomic-coordinator",
    "model": "claude-opus-4-7",
    "beta_header": "managed-agents-2026-04-01",
    "builtin_toolset": {
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": True},
        "configs": [
            {"name": "web_search", "enabled": False},
            {"name": "web_fetch", "enabled": True},
        ],
    },
    "custom_tools": [
        {"name": "pod_smi", "permission": "passive_read"},
        {"name": "pod_journalctl", "permission": "passive_read"},
        {"name": "vllm_health", "permission": "passive_read"},
        {"name": "livekit_health", "permission": "passive_read"},
        {"name": "vercel_status", "permission": "passive_read"},
        {"name": "synthetic_caller", "permission": "passive_read"},
        {"name": "heartbeat_publish", "permission": "active_mutate"},
        {"name": "nsys_profile_attach", "permission": "active_mutate"},
        {"name": "nsys_export", "permission": "passive_read"},
        {"name": "gds_op", "permission": "active_mutate"},
        {"name": "cuda_checkpoint_ctl", "permission": "gated_destructive"},
        {"name": "service_restart", "permission": "gated_destructive"},
        {"name": "restore_invoke", "permission": "gated_destructive"},
        {"name": "workload_prior_emit", "permission": "active_mutate"},
        {"name": "incident_log_write", "permission": "active_mutate"},
    ],
}


def _load_tool_surface() -> dict[str, Any]:
    """Load tool-surface.yaml; fall back to the hand-coded dict above."""
    try:
        import yaml  # type: ignore
    except ImportError:
        print(
            "[skeleton] pyyaml not installed; using fallback tool surface "
            "(suitable for --print-payload only).",
            file=sys.stderr,
        )
        return _TOOL_SURFACE_FALLBACK
    if not TOOL_SURFACE_YAML.exists():
        print(f"[skeleton] {TOOL_SURFACE_YAML} not found; using fallback.", file=sys.stderr)
        return _TOOL_SURFACE_FALLBACK
    with TOOL_SURFACE_YAML.open() as f:
        return yaml.safe_load(f)


def _custom_tool_input_schema(tool_name: str) -> dict[str, Any]:
    """Return a minimal-but-real input_schema for each custom tool.

    Custom-tool best practice from
    https://platform.claude.com/docs/en/managed-agents/tools (fetched 2026-04-26):
    "Provide extremely detailed descriptions ... Aim for at least 3-4 sentences
    per tool description."

    Tool descriptions are sourced from tool-surface.yaml; this function
    supplies the input-schema shape.
    """
    schemas: dict[str, dict[str, Any]] = {
        "pod_smi": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Comma-separated --query-gpu fields for nvidia-smi.",
                },
            },
            "required": [],
        },
        "pod_journalctl": {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "enum": ["prism42-worker", "prism42-fish", "prism42-vllm", "caddy", "b300-livekit-1"],
                },
                "lines": {"type": "integer", "default": 50, "maximum": 500},
                "since": {"type": "string", "default": "60 seconds ago"},
            },
            "required": ["unit"],
        },
        "vllm_health": {"type": "object", "properties": {}, "required": []},
        "livekit_health": {"type": "object", "properties": {}, "required": []},
        "vercel_status": {"type": "object", "properties": {}, "required": []},
        "synthetic_caller": {
            "type": "object",
            "properties": {"timeout_s": {"type": "integer", "default": 40, "maximum": 60}},
            "required": [],
        },
        "heartbeat_publish": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
                        "prism42.heartbeat",
                        "prism42.alert",
                        "prism42.action",
                        "prism42.profile_ready",
                        "prism42.elasticity",
                    ],
                },
                "payload": {"type": "object"},
            },
            "required": ["topic", "payload"],
        },
        "nsys_profile_attach": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "duration_s": {"type": "integer", "default": 30, "minimum": 5, "maximum": 120},
                "trace": {"type": "string", "default": "cuda,nvtx,cudnn,cublas"},
            },
            "required": ["pid"],
        },
        "nsys_export": {
            "type": "object",
            "properties": {
                "rep_path": {"type": "string"},
                "format": {"type": "string", "enum": ["jsonl", "sqlite"], "default": "jsonl"},
            },
            "required": ["rep_path"],
        },
        "gds_op": {
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["prefetch_weights", "spill_kv", "stage_checkpoint", "status"],
                },
                "target": {"type": "string"},
            },
            "required": ["subcommand"],
        },
        "cuda_checkpoint_ctl": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["lock", "checkpoint", "restore", "unlock", "get_state"],
                },
                "pid": {"type": "integer"},
                "timeout_ms": {"type": "integer", "default": 5000},
            },
            "required": ["action", "pid"],
        },
        "service_restart": {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "enum": ["prism42-vllm", "prism42-fish", "prism42-worker", "caddy"],
                },
                "reason": {"type": "string"},
            },
            "required": ["unit", "reason"],
        },
        "restore_invoke": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["check", "pod-only", "vercel-only", "full"],
                    "default": "check",
                },
                "confirm_token": {"type": "string"},
            },
            "required": ["confirm_token"],
        },
        "workload_prior_emit": {
            "type": "object",
            "properties": {"prior": {"type": "object"}},
            "required": ["prior"],
        },
        "incident_log_write": {
            "type": "object",
            "properties": {"incident": {"type": "object"}},
            "required": ["incident"],
        },
    }
    return schemas.get(tool_name, {"type": "object", "properties": {}, "required": []})


def _custom_tool_descriptions() -> dict[str, str]:
    """Detailed (3-4 sentence) descriptions per Anthropic's tool-use best
    practices. These are what Claude reads to decide *when* to call each tool.
    """
    return {
        "pod_smi": (
            "Query nvidia-smi over SSH on the b300-pod pod. Returns "
            "parsed JSON of GPU memory, utilization, temperature, and power. "
            "Read-only; never mutates pod state. Call this tool BEFORE every "
            "heartbeat tick, AND immediately before/after any gated action so "
            "you have ground truth for the state pre/post invariant."
        ),
        "pod_journalctl": (
            "Tail the systemd journal for one whitelisted unit on the pod "
            "(prism42-worker, prism42-fish, prism42-vllm, caddy, b300-livekit-1). "
            "Read-only. Use this when classifying state into warn/degraded — "
            "the journal often shows the proximate cause that nvidia-smi alone "
            "cannot reveal (e.g. OOMKilled, registration failures, websocket "
            "errors). Bound 'lines' to 50-200 to keep responses small."
        ),
        "vllm_health": (
            "HTTP probe of vLLM /health and /metrics on :8001. Read-only. "
            "Use this to confirm the LLM is serving requests and to gather "
            "p50/p95 TTFT, decode rate, and KV cache utilization for the "
            "heartbeat payload. Failures here are the strongest single signal "
            "of a degraded voice path."
        ),
        "livekit_health": (
            "HTTP probe of https://prism42.thegoatnote.com (self-host LiveKit) "
            "AND a parallel check of LiveKit Cloud as the fallback path. "
            "Read-only. Use this to confirm the media plane is reachable and "
            "to count active rooms before triggering any action that briefly "
            "affects the voice path (Nsight profiling, cuda-checkpoint, etc.)."
        ),
        "vercel_status": (
            "Run `vercel inspect` for the 911-console-live project. Reads the "
            "current production deployment URL, env-var presence (not values), "
            "and last build status. Use this when diagnosing a frontend-side "
            "report; useful BEFORE recommending a `restore_invoke` so you can "
            "verify the public surface is in the expected state."
        ),
        "synthetic_caller": (
            "Invoke agents/livekit/synthetic_caller.py for a one-shot smoke "
            "turn. Joins the room as a fake browser caller, listens for one "
            "agent reply, records latency at every leg (token mint → room "
            "connect → agent join → first audio frame). Bounded to 35 s. Use "
            "this AFTER any gated_destructive recovery action to confirm the "
            "voice path is end-to-end functional."
        ),
        "heartbeat_publish": (
            "Publish one event to a prism42.* LiveKit data-track topic. "
            "Mutates only the room data plane; never touches the voice path. "
            "Mirrors the additive topic-segmented pattern in "
            "agents/livekit/dispatch_publisher.py. Call this at the end of "
            "every heartbeat tick and at every state transition."
        ),
        "nsys_profile_attach": (
            "Run NVIDIA Nsight Systems against a target PID with the safe "
            "trace set (cuda,nvtx,cudnn,cublas only — never the high-overhead "
            "options like --cuda-trace-all-apis or --cudabacktrace). Output "
            "is a .nsys-rep file under /opt/prism42/scratch/profiles/. Use "
            "this only when (a) a latency anomaly was detected for >5 ticks, "
            "or (b) the user explicitly requested a profile, AND active "
            "LiveKit room count is below 2."
        ),
        "nsys_export": (
            "Export a .nsys-rep file to JSON Lines or SQLite for parsing. "
            "Read-only relative to the source file. Use this immediately "
            "after `nsys_profile_attach` returns, then read the export file "
            "with the built-in `read` tool to extract top-N kernels by total "
            "time, occupancy delta, and memory-vs-compute classification."
        ),
        "gds_op": (
            "Wrapper for cuFile-bound storage operations (the Pillar 2 "
            "agent-orchestrated GPUDirect Storage path). Subcommands: "
            "prefetch_weights, spill_kv, stage_checkpoint, status. Mutates "
            "filesystem and HBM under integrator-owned policy; no NVIDIA "
            "daemon involved. Use prefetch_weights before a planned vLLM "
            "cold-start; use stage_checkpoint to durably save a "
            "cuda-checkpoint snapshot before a high-risk action."
        ),
        "cuda_checkpoint_ctl": (
            "Wrapper around NVIDIA's cuda-checkpoint CLI. Subcommands map "
            "1:1 to --action: lock, checkpoint, restore, unlock, get_state. "
            "GATED: PRISM42_AUTONOMIC_ELASTICITY=1 must be set on the host. "
            "Use this strictly per the elasticity-runbook.md sequence — "
            "never freelance the order of lock/checkpoint/restore/unlock; "
            "always verify with get_state between transitions; abort on any "
            "unexpected state."
        ),
        "service_restart": (
            "Issue `systemctl restart` for one whitelisted service on the pod. "
            "GATED per-unit: PRISM42_AUTONOMIC_AUTORESTART_VLLM=1 (etc). "
            "Single-service-at-a-time discipline (memory note "
            "prism42_b300_voice_durable_findings.md) — never restart two "
            "services from the same tick. After every restart, wait 5 ticks "
            "(150 s cooldown) before any other gated action."
        ),
        "restore_invoke": (
            "BIG RED BUTTON. Invokes findings/voice/cycle2R_livekit_selfhost/"
            "baseline-2026-04-26/restore.sh to roll the demo path back to "
            "LiveKit Cloud. Default mode is `check` (dry-run). Use this only "
            "when (a) the self-host path is unrecoverable AND (b) the user "
            "has supplied a fresh confirm_token AND (c) "
            "PRISM42_AUTONOMIC_RESTORE=1 is set. Expect to use this near-"
            "never; it is the safety net of last resort."
        ),
        "workload_prior_emit": (
            "Write the cuTILE workload-prior JSON to /opt/prism42/scratch/"
            "priors/ so the next vLLM/CUTLASS launch can consume it. The "
            "JSON describes the workload shape (batch=1 PSAP voice, ctx, "
            "dtype, model, phase) so kernel autotuners can pick from the "
            "right corner of their search space. Pillar 5 stub — writes the "
            "JSON only; does not re-tune kernels (that lands in cycle-2Z)."
        ),
        "incident_log_write": (
            "Append a structured incident JSON to "
            "findings/voice/cycle2X_autonomic_ops/incidents/<ts>.json. This "
            "is your durable provenance log. Call this at the end of every "
            "tick that produced a state transition, every gated action, and "
            "every halt. Schema in heartbeat-design.md §3."
        ),
    }


def build_create_payload(surface: dict[str, Any]) -> dict[str, Any]:
    """Build the JSON payload for `client.beta.agents.create(...)`."""
    builtin = surface.get("builtin_toolset", _TOOL_SURFACE_FALLBACK["builtin_toolset"])
    descriptions = _custom_tool_descriptions()

    tools: list[dict[str, Any]] = [
        {
            "type": "agent_toolset_20260401",
            "default_config": builtin.get("default_config", {"enabled": True}),
            "configs": builtin.get("configs", []),
        }
    ]

    for entry in surface.get("custom_tools", []):
        name = entry["name"]
        tools.append(
            {
                "type": "custom",
                "name": name,
                "description": descriptions.get(name, entry.get("description", "")),
                "input_schema": _custom_tool_input_schema(name),
            }
        )

    return {
        "name": surface.get("agent_name", "prism42-autonomic-coordinator"),
        "model": surface.get("model", "claude-opus-4-7"),
        "system": SYSTEM_PROMPT,
        "tools": tools,
    }


def create_agent(payload: dict[str, Any]) -> str:
    """Call client.beta.agents.create. Returns the agent id."""
    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError:
        raise SystemExit(
            "anthropic SDK not installed. `pip install anthropic` and re-run "
            "with PRISM42_AUTONOMIC_REGISTER=1 --create."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY missing. Source the canonical "
            "~/lostbench/.env per memory note "
            "api_keys_canonical_env.md."
        )

    client = Anthropic(default_headers={"anthropic-beta": "managed-agents-2026-04-01"})
    agent = client.beta.agents.create(**payload)  # type: ignore[arg-type]
    agent_id: str = getattr(agent, "id", None) or agent["id"]  # SDK + dict fallback

    AGENT_ID_FILE.write_text(agent_id + "\n")
    print(f"[skeleton] agent registered: {agent_id}")
    print(f"[skeleton] id written to {AGENT_ID_FILE}")
    return agent_id


def main() -> int:
    p = argparse.ArgumentParser(description="prism42 autonomic-ops agent skeleton")
    p.add_argument("--create", action="store_true", help="register the agent on the workspace")
    p.add_argument("--print-payload", action="store_true", help="print the create payload as JSON")
    args = p.parse_args()

    surface = _load_tool_surface()
    payload = build_create_payload(surface)

    if args.print_payload:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    if not args.create:
        print(
            "[skeleton] dry-run. tool count = "
            f"{1 + len(surface.get('custom_tools', []))} "
            f"(1 builtin toolset + {len(surface.get('custom_tools', []))} custom). "
            "Pass --create with PRISM42_AUTONOMIC_REGISTER=1 to register."
        )
        return 0

    if os.environ.get("PRISM42_AUTONOMIC_REGISTER", "0") != "1":
        raise SystemExit(
            "Refusing to call beta.agents.create without "
            "PRISM42_AUTONOMIC_REGISTER=1. Charter §5 (double-gate)."
        )

    create_agent(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
