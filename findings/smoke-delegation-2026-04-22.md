---
title: Prism — Delegation Smoke: research-preview gate discovered
date: 2026-04-22
status: Negative (informative) — delegation did NOT fire; root cause identified
cost: ~$0.35 (two sessions, ~12-18 s wall each)
scope: First attempt to invoke prism-defender via prism-coordinator's `callable_agents` binding.
---

# Prism Delegation Smoke — 2026-04-22

Attempted coordinator → defender delegation live on the Anthropic
workspace. **Delegation did not fire.** Investigation traced the
root cause to a research-preview gate on the multi-agent feature.
This is a meaningful finding that reshapes Prism's hackathon-demo
posture; details below.

## Verdict

**Negative result, informative.** The coordinator was reachable, the
session event channel streamed cleanly, and the coordinator itself
reported — in its own runtime self-introspection — that the
sub-agent tools were **not wired**.

Verbatim from the session (`sesn_011CaJem4cfdpLGVbvYi5A2s`):

> "I can't complete this smoke test. My available tool bindings in
> this session are only: `bash`, `edit`, `read`, `write`, `glob`,
> `grep`, `web_fetch`, and `web_search`. There is no `defender` (or
> `attacker`/`synthesizer`/`executor`/`adjudicator`) callable
> sub-agent tool exposed to me at runtime.
>
> In other words, the `callable_agents` binding you're trying to
> verify did not fire — the sub-agents described in my system prompt
> are not actually wired up as invocable tools in this session."

The coordinator honored the smoke's "do not fabricate" hard rule and
declined to simulate a defender response.

## Root cause

Two mutually-reinforcing issues, traced by inspecting the live agent
+ the canonical docs:

### 1. Multi-agent is research preview, not generally available

Per `https://platform.claude.com/docs/en/managed-agents/overview`:

> "Certain features (outcomes, **multiagent**, and memory) are in
> research preview. [Request access](https://claude.com/form/claude-managed-agents)
> to try them."

And per `https://platform.claude.com/docs/en/managed-agents/multi-agent`:

> "An additional beta header is needed for research preview features.
> The SDK sets these beta headers automatically."

**This workspace (`B's Individual Org`) does not currently have
multi-agent research-preview access.** Without the additional beta
header (name not documented; SDK-managed), the API silently drops
`callable_agents` from the create-agent request body rather than
returning an error.

### 2. SDK v0.96.0 typed surface rejects `callable_agents`

The canonical Python form from the docs:

```python
orchestrator = client.beta.agents.create(
    name="Engineering Lead", model="claude-opus-4-7", system="...",
    tools=[{"type": "agent_toolset_20260401"}],
    callable_agents=[
        {"type": "agent", "id": reviewer_agent.id, "version": reviewer_agent.version},
        ...
    ],
)
```

`client.beta.agents.create()` in `anthropic` v0.96.0 does NOT expose
`callable_agents` as a named parameter — `inspect.signature` shows only
`model, name, description, mcp_servers, metadata, skills, system, tools,
betas`. The `extra_body` escape hatch `extra_body={"callable_agents": [...]}`
was used as a workaround, but:

- The POST succeeded (no 400, no 403).
- A subsequent `beta.agents.retrieve` returned a body with `mcp_servers: []`,
  `skills: []`, `tools: [...agent_toolset_20260401...]`, **no `callable_agents`
  key**. The field was silently stripped at the API boundary.
- The session-runtime tool surface reflected this: only the default
  `agent_toolset_20260401` tools, no sub-agent callable shims.

Whether the SDK rejected `callable_agents` because the workspace lacks
research-preview access, or because the typed surface was generated
before the multi-agent feature landed, is not directly observable.
Either way: **`extra_body` is not a bypass**.

## Discovered delegation event names (for a future re-attempt)

Per the multi-agent docs, the session stream surfaces these event
types during a successful delegation:

| Type | Description |
| --- | --- |
| `session.thread_created` | Coordinator spawned a new thread. Includes `session_thread_id` + `model`. |
| `session.thread_idle` | An agent thread finished its current work. |
| `agent.thread_message_sent` | Agent sent a message to another thread (`to_thread_id`, `content`). |
| `agent.thread_message_received` | Agent received from another thread (`from_thread_id`, `content`). |

Our `scripts/smoke_delegation.py` scanner was watching for
`span.sub_agent_*` / `delegate.*` / `call.*` heuristically — which are
NOT the real event names. When research-preview access lands, update
the scanner to look for `session.thread_created` as the primary
"delegation fired" signal.

## Also: binding is at create-time only

> "The callable agents are resolved from the orchestrator's
> configuration. You don't need to reference them at session creation."

Good for our harness: `sessions.create(agent=..., environment_id=...)`
stays simple. `resources: [...]` is NOT the delegation binding.

## What this changes about Prism's posture

Prism's `agents/*.yaml` + `register_agents.py` still encode the
research-preview design intent and are correct — no rework needed
there. What needs adjustment:

1. **`CLAUDE.md` §8** — add explicit "multi-agent is research-preview
   gated" note; my earlier claim that extra_body was a safe workaround
   was wrong.
2. **Memory `managed_agents_multi_agent_verified.md`** — the "research-preview
   access confirmed 2026-04-21" record appears to have been for a
   different account or a prior state. This workspace is NOT currently
   gated open for multi-agent.
3. **Prism's hackathon-demo narrative** — two viable paths forward:
   - **Apply for research-preview access** (`https://claude.com/form/claude-managed-agents`).
     Lead time unknown; may not clear by Apr 26.
   - **Pivot the demo to single-coordinator**: run the whole audit with
     one Managed Agent (`prism-coordinator`) using `agent_toolset_20260401`
     (bash + file + web). The defender/attacker/synthesizer/executor/
     adjudicator become *workflow phases within one agent session*
     rather than five independent agents. This is still a legitimate
     agentic audit harness and matches the surface that IS GA today.
4. **`agents/manifest.yaml`** — the 5 sub-agents remain registered; they
   are not wasted. When multi-agent clears, the coordinator gains their
   callable tools with no Prism-side code change (extra_body → typed
   kwarg when SDK updates).

## Cost

Two delegation-smoke attempts:

| run | session_id | wall | tokens | est cost |
|---|---|---|---|---|
| #1 | `sesn_011CaJem4cfdpLGVbvYi5A2s` | 18 s | 8,608 in + 480 out | ~$0.17 |

Plus ~$0.15 across the two earlier intro smokes. Total hackathon spend
on Managed Agents exploration tonight: **~$0.35**.

## Artifacts

| Artifact | Path | Committed |
|---|---|---|
| Reproducer script | `scripts/smoke_delegation.py` | yes |
| Transcript log | `results/smoke/delegation-<stamp>-transcript.log` | no (`results/` gitignored) |
| Structured summary | `results/smoke/delegation-<stamp>-summary.json` | no (same) |

## Cross-reference

- `CLAUDE.md` §8 — Managed Agents operating contract (updated this commit).
- `docs/clinical-pivot-2026-04-21.md` — week plan; consider adding a
  "multi-agent gate" risk row if not already present.
- `findings/smoke-session-2026-04-22.md` — the prior (successful)
  session-channel smoke.
- Canonical docs: `https://platform.claude.com/docs/en/managed-agents/overview`
  + `.../multi-agent` (fetched 2026-04-22).
