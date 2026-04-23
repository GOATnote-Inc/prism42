---
title: Prism — Live Managed Agents Session Smoke
date: 2026-04-22
status: GREEN — end-to-end event channel verified on Claude Opus 4.7
cost: ~$0.15 (8,424 input + 251 output tokens; no session-hour accumulation)
scope: First live session against a Prism-registered coordinator agent.
---

# Prism Session Smoke — 2026-04-22

First live multi-agent Managed Agents session against the Prism
coordinator, executed 2026-04-22 ~03:17 UTC from this machine against
the Anthropic workspace `B's Individual Org`.

## Verdict

**GREEN.** Session created, event channel streamed cleanly, coordinator
responded coherently from its own system prompt. No code path between
the Python SDK and the Managed Agents runtime is broken for our 6-agent
registration.

## Artifacts

| Artifact | Path | Committed |
|---|---|---|
| Reproducer script | `scripts/smoke_session.py` | yes |
| Transcript log    | `results/smoke/session-<stamp>-transcript.log` | no (gitignored; `results/` is operational) |
| Structured summary | `results/smoke/session-<stamp>-summary.json` | no (same) |
| Console URL       | `https://platform.claude.com/sessions/sesn_011CaJdkjHh6hJbR7LdifqWQ` | link only |

To reproduce locally (requires `ANTHROPIC_API_KEY` in `.env` and the
6 agents + env already registered via `scripts/register_agents.py --commit`):

```bash
PRISM_SMOKE_SESSION_COMMIT=1 python scripts/smoke_session.py --commit
```

## What was exercised

1. `beta.sessions.create` — bound the coordinator agent
   (`agent_011CaJboTBvV6agLw9huTWJY` v1) to the environment
   (`env_01Nbmp5KCzCKfkcJgZdHhngY`). Returned status `idle`, 0.4 s.
2. `beta.sessions.events.send` — posted one `user.message` event with
   a 303-char text prompt. 0.6 s round-trip.
3. `beta.sessions.events.stream` — received six SSE events across 8.3 s:
   `session.status_running → user.message → span.model_request_start →
   agent.message → span.model_request_end → session.status_idle`. The
   `agent.message` event carried the coordinator's text response.
4. `beta.sessions.retrieve` — final status `idle`; usage reported
   `input_tokens=6, output_tokens=251, cache_creation.5m=8418`.

## Prompt

Coordinator was asked to describe itself without invoking sub-agents —
this proved the event channel works without spending session-hour
charges on delegation:

> Introduce yourself in 3 short sentences: (a) your role as the Prism
> coordinator, (b) the five callable sub-agents you can invoke and the
> ORDER you invoke them in, (c) the shape of the first user message
> you expect (what keys). Do NOT call any sub-agents. Do NOT invoke
> any tools. Plain text answer only.

## Response (verbatim, from the session)

> I'm the Prism coordinator: I audit one target (a GPU kernel file or a
> clinical-reasoning scenario) end-to-end by orchestrating sub-agents in
> a fixed order, persisting artifacts under `/workspace/<case_id>/`, and
> never fabricating findings.
>
> I invoke five callable sub-agents in this order: (1) defender,
> (2) attacker (with up to 3 dialectic rounds alternating
> defender↔attacker until invariants stabilize), (3) synthesizer,
> (4) executor, (5) adjudicator.
>
> The first user message I expect is a JSON object with keys:
> `target_domain` ("gpu" or "clinical"), `case_id`, `target_path`
> (or a case manifest path for clinical), and optional rail hints.

The response quotes the coordinator's own system prompt
(`agents/prism-coordinator.yaml`) accurately — including the
delegation order, the dialectic-round detail (up to 3 alternations),
and the four expected input keys. This confirms the system prompt
loaded into the live agent unchanged.

## Cost

| Metric | Value |
|---|---|
| Input tokens | 6 |
| Output tokens | 251 |
| Cache creation (5m) | 8,418 |
| Observed cost | **~$0.15** |
| Session-hour accrual | ~0 (session reached `idle` in 8.3 s; tokens-only) |

Budget cap in the script: `$0.50`. Re-runs are safe and cheap.

## Not exercised (follow-up)

- **Delegation**: the prompt explicitly forbade sub-agent calls. The
  coordinator's `callable_agents` attachments were validated at
  create-time (`extra_body={"callable_agents": [...]}`, see
  `agents/manifest.yaml._notes`) but no defender/attacker/… session
  actually ran here. A delegation smoke would cost ~$0.30–0.50 and
  is the natural next increment.
- **Mounts**: `corpus/` files are NOT mounted into the session
  container (the API does not yet support host mounts; see
  `environments/prism-standard-env.yaml._prism.aspirational_mounts`).
  A realistic audit run therefore requires the coordinator to fetch
  content via a tool call or pre-mount — deferred until the API
  surfaces mount support or Prism uses `resources` to supply inputs.

## Cross-reference

- `agents/manifest.yaml` — the 6 live agent IDs + environment ID.
- `CLAUDE.md` §8 — Managed Agents operating contract.
- `docs/clinical-pivot-2026-04-21.md` §5 — verification plan (this smoke is the first "L1 schema" evidence that the session channel is up).
- `docs/safeguards.md` — physician-facing 60-second review; compatible with this smoke (no clinical content posted).
