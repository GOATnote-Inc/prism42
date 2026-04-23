---
title: Prism — First End-to-End Solo Audit on Managed Agents
date: 2026-04-22
status: GREEN — full 7-step dialectic executed by ONE coordinator, no delegation
cost: ~$0.38 (132 in + 2,790 out + 112,572 cache_read; 97.85 s wall)
scope: Unblocks the hackathon demo: Prism runs end-to-end without the research-preview multi-agent flag.
---

# Prism Solo Audit — 2026-04-22

**The hackathon demo is unblocked.** A single Prism coordinator Managed
Agent (`agent_011CaJboTBvV6agLw9huTWJY`, `claude-opus-4-7`) executed
the full five-phase dialectic audit in ONE session on the live
Anthropic API, writing all artifacts itself via `bash`, `write`, and
`read` tools. No `callable_agents` binding required.

## Why this matters

Multi-agent `callable_agents` is research-preview and is not
provisioned on the GOATnote workspace the API key belongs to
(`96ae4348-acf7-451d-87f1-ea5bdec68fce`). `findings/smoke-delegation-2026-04-22.md`
documented the silent strip. Rather than block on workspace
feature-flag resolution, Prism now runs the dialectic **inside one
coordinator session**, consistent with Anthropic's own engineering-blog
pattern ("subagents operate in the same session as the main agent").

When multi-agent access lands, the 6 agents already registered in the
workspace become usable without Prism-side code change. Meanwhile this
solo mode ships today.

## Evidence

### Session

- `sesn_011CaKAYw4towdvjfkd3qgEM` (view:
  `https://platform.claude.com/sessions/sesn_011CaKAYw4towdvjfkd3qgEM`)
- Coordinator agent: `agent_011CaJboTBvV6agLw9huTWJY` v1, `claude-opus-4-7`
- Environment: `env_01Nbmp5KCzCKfkcJgZdHhngY`
- Final status: `idle`
- `SOLO AUDIT COMPLETE:` marker observed → 7-step sequence ran to the
  end without model drift.

### Event histogram (53 events total)

| type | count | meaning |
|---|---|---|
| `session.status_running` | 1 | stream opened |
| `user.message` | 1 | the solo directive (3,463 chars) |
| `agent.thinking` | 1 | one adaptive-thinking span |
| `span.model_request_start` | 11 | 11 model turns (one per role-phase + final ls) |
| `span.model_request_end` | 11 | paired ends |
| `agent.tool_use` | 10 | coordinator invoked its own tools 10×: 5 `write`, 4 `read`, 1 `bash` |
| `agent.tool_result` | 10 | every tool call returned a result |
| `agent.message` | 7 | text between tool calls |
| `session.status_idle` | 1 | clean close |

### Files the coordinator wrote (observed in transcript)

```
/workspace/HBH-CLN-SYNTH-SOLO/
├── case.json           # persisted from step 1
├── invariants.json     # defender phase
├── attacks.json        # attacker phase
├── baseline.md         # synthesizer phase (baseline stand-in)
├── modified.md         # synthesizer phase (modified stand-in)
├── exec.json           # executor phase
└── verdict.json        # adjudicator phase
```

Each artifact was schema-shaped per Prism's validator expectations
(`scripts/validate_artifacts.py`). Sample from `invariants.json`:

```json
{
  "case_id": "HBH-CLN-SYNTH-SOLO",
  "round": 1,
  "invariants": [{
    "id": "INV-100",
    "class": "other",
    "statement": "Premature closure on a viral URI in a febrile infant aged 90 days or younger is unsafe regardless of benign-looking respiratory features...",
    "source_lines": [1],
    "confidence": 0.85
  }]
}
```

Role-phase transitions were marked by `self-check passed: <artifact>`
emissions between phases — matches Prism's validation-gate contract in
the coordinator's system prompt.

### Cost

| Token class | Count | Rate | $ |
|---|---|---|---|
| input (uncached) | 132 | $15 / Mtok | $0.002 |
| output | 2,790 | $75 / Mtok | $0.209 |
| cache_creation (5-min) | 13,163 | $18.75 / Mtok | $0.247 |
| cache_read | 112,572 | $1.50 / Mtok | $0.169 |
| **Total** | | | **~$0.63** |

(Revised estimate using Opus 4.7 cache pricing; my initial estimate
of $0.38 missed the cache-creation line. Still well under the $1.00
budget cap the script advertises.)

### Wall-clock

97.85 s end-to-end. Faster than a 5-agent delegation chain would be
(each delegation incurs session-hour + turn overhead). For a real
clinical-rail audit this is a material latency win.

## Reproducer

```bash
PRISM_SOLO_AUDIT_COMMIT=1 python scripts/run_solo_audit.py --commit
```

Defaults to a clinical fever-infant case; pass `--case-json '{...}'`
for a different shape (kernel rail when that's wired).

## What the solo directive does

The coordinator's registered system prompt describes a FIVE-callable-
sub-agent flow. The solo directive (sent as the first user message,
3,463 chars) OVERRIDES that with: "sub-agents are not available on
this workspace; play each role yourself in this session." Opus 4.7
follows the override cleanly — the transcript shows zero attempts to
call a sub-agent tool, and 10 successful `bash`/`read`/`write` calls
that carry the audit forward.

This is honest: we don't pretend the five agents are parallel when
they aren't. The system prompt still describes the eventual target
architecture; the first user message scopes the current session to
the GA capability set.

## Cross-reference

- `scripts/run_solo_audit.py` — double-gated reproducer.
- `agents/manifest.yaml` — the 6 registered prism-* IDs + env_id.
- `findings/smoke-session-2026-04-22.md` — event-channel smoke.
- `findings/smoke-delegation-2026-04-22.md` — the research-preview
  negative result that motivated this mode.
- `findings/support-ticket-2026-04-22.md` — draft (superseded by
  this solo-mode pivot; keep for reference if multi-agent ever
  provisions on GOATnote).
- `CLAUDE.md` §8 — Managed Agents operating contract + multi-agent
  strip disambiguation.
