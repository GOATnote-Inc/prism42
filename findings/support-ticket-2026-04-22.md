---
title: Prism — Anthropic support-ticket draft for multi-agent strip
date: 2026-04-22
status: DRAFT — human-send, do not auto-dispatch
workspace_binding: MATCH (API-key workspace owns all 6 prism-* agents; verified 2026-04-22)
---

# Anthropic Support Ticket Draft — Managed Agents: `callable_agents` silently stripped

**Human-send gate.** This file is a draft. Review, edit as needed, then
paste into the support form. Do not auto-dispatch.

---

## Subject

Managed Agents: `callable_agents` silently stripped on `POST /v1/agents` despite multi-agent research-preview access

## Body

Hello,

I have multi-agent research-preview access on my organization (granted
via the form at `https://claude.com/form/claude-managed-agents`). When
I create a coordinator agent with `callable_agents`, the API returns
200 OK but stores the agent without the `callable_agents` field, and
at session runtime the coordinator reports that no sub-agent callable
tools are exposed. No 400, no 403, no warning header — the field is
silently dropped.

### Evidence

1. **Workspace binding verified MATCH.** Via `beta.agents.list`, the
   `ANTHROPIC_API_KEY` I'm using sees **all 6 of my `prism-*` agents**
   and my **1 environment** in the org's workspace. Independent probes
   in two different minutes confirm this. Request-ids:
   - `req_011CaJg9qBnVqPNkaoBLgjrN` (2026-04-22 10:46 UTC)
   - `req_011CaK9KBKtPYQXMDZxHwzeN` (2026-04-22 ~16:41 UTC)
   - List-probe: `req_011CaK9C1Ntt5NSH7gs9RaHc` (2026-04-22 16:41 UTC)

   The API-key's workspace IS the workspace containing the `prism-*`
   agents. This is not a wrong-workspace mismatch.

2. **Canonical shape from your docs is what I sent.** From
   `platform.claude.com/docs/en/managed-agents/multi-agent`:

   ```python
   orchestrator = client.beta.agents.create(
       name="Engineering Lead",
       model="claude-opus-4-7",
       system="...",
       tools=[{"type": "agent_toolset_20260401"}],
       callable_agents=[
           {"type": "agent", "id": reviewer_agent.id, "version": reviewer_agent.version},
           {"type": "agent", "id": test_writer_agent.id, "version": test_writer_agent.version},
       ],
   )
   ```

3. **Five beta-header combinations tested against raw HTTP** — all
   return 200 OK, all strip `callable_agents`:
   - `managed-agents-2026-04-01` (base)
   - `... + multi-agent-2026-04-01`
   - `... + managed-agents-multi-agent-2026-04-01`
   - `... + multiagent-2026-04-01`
   - `... + research-preview-2026-04-01`

   The response body in every case contains keys
   `[archived_at, created_at, description, id, mcp_servers, metadata,
   model, name, skills, system, tools, type, updated_at, version]` —
   no `callable_agents`. No response header (`X-Feature-Disabled`,
   `Anthropic-Warning`, etc.) hints at why.

4. **SDK surface mismatch (informational, not the bug).** The
   `anthropic` Python SDK v0.96.0 (current on PyPI) and the `main`
   branch on GitHub both lack `callable_agents` as a named kwarg on
   `client.beta.agents.create`. I used `extra_body={"callable_agents":[...]}`
   to send the field; raw-HTTP replay confirms the field IS on the
   wire. The strip happens at the API layer, not in the SDK.

5. **Runtime self-introspection** (session `sesn_011CaJem4cfdpLGVbvYi5A2s`,
   2026-04-22). The coordinator replied verbatim:

   > "My available tool bindings in this session are only: `bash`,
   > `edit`, `read`, `write`, `glob`, `grep`, `web_fetch`, and
   > `web_search`. There is no `defender` (or `attacker`/`synthesizer`/
   > `executor`/`adjudicator`) callable sub-agent tool exposed to me
   > at runtime. ... the `callable_agents` binding you're trying to
   > verify did not fire."

### What I expect

Per docs, my coordinator's stored body should include a `callable_agents`
array, and at session runtime the sub-agent callable shims should
appear in the coordinator's tool list. Neither happens.

### Reproduction (minimal)

```bash
# 1. Create a sub-agent
SUB=$(curl -fsS https://api.anthropic.com/v1/agents \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: managed-agents-2026-04-01" \
  -H "content-type: application/json" \
  -d '{"name":"sub","model":"claude-opus-4-7","system":"sub","tools":[{"type":"agent_toolset_20260401"}]}' \
  | jq -r '.id')

# 2. Create a coordinator with callable_agents pointing at it
curl -fsS https://api.anthropic.com/v1/agents \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: managed-agents-2026-04-01" \
  -H "content-type: application/json" \
  -d "$(jq -cn --arg sid "$SUB" '{
    name:"coord", model:"claude-opus-4-7",
    system:"coord", tools:[{type:"agent_toolset_20260401"}],
    callable_agents:[{type:"agent", id:$sid, version:1}]
  }')" \
  | jq 'keys'
# Expected keys include "callable_agents".
# Actual keys do not include "callable_agents".
```

### Asks

1. **Confirm which workspace on my org has multi-agent research-preview
   enabled.** My org has multiple workspaces; I'd like to verify the
   grant is on the workspace my `ANTHROPIC_API_KEY` operates in (the
   one containing the `prism-*` agents above).
2. If the grant is on a different workspace, let me know the
   workspace name so I can rotate the API key. If the grant is on the
   correct workspace and the strip is a provisioning bug, please
   investigate with the request-ids above.
3. Optional — share the exact beta-header name(s) the SDK will attach
   automatically once my workspace is fully provisioned, so I can
   pre-bake the register path.

Account: `B's Individual Org`. Physician-of-record on clinical-rail
work: Brandon Dent, MD.

Thanks.

---

## Cross-reference (for internal records)

- `CLAUDE.md` §8 — operating contract with the workspace-scoping note
  + the first probe request_id.
- `findings/smoke-delegation-2026-04-22.md` — full negative-result
  writeup with verbatim coordinator quote.
- `findings/smoke-session-2026-04-22.md` — successful single-agent
  session smoke (event channel works; only delegation is gated).
- `agents/manifest.yaml` — the 6 live prism-* IDs + env_id.
