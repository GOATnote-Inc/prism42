---
title: Prism — Skilled Audit via 5 Anthropic Agent Skills (the real flex)
date: 2026-04-22
status: GREEN — 5 role skills uploaded, bound to coordinator v2, end-to-end audit executed
scope: Prism now decomposes the 5-phase dialectic via progressive-disclosure Skills — no multi-agent research preview required.
---

# Prism — Skilled Audit: the real flex

## What this is

Prism's five dialectic roles — **defender, attacker, synthesizer,
executor, adjudicator** — are now packaged as **Anthropic Agent
Skills**, uploaded via the public-beta `/v1/skills` endpoint and
bound to the `prism-coordinator` Managed Agent via
`beta.agents.update(skills=[...])`. At session runtime, Opus 4.7
loads each skill's YAML frontmatter at startup (~100 tokens each) and
pulls in the full SKILL.md body on demand when the current phase
matches the skill's description — exactly the progressive-disclosure
pattern Anthropic's Agent Skills spec is designed for.

**This is a genuine forward step, not a fallback**: Skills are an
**open-standard Anthropic is pushing alongside MCP**; the decomposition
lives in versioned, publishable-to-other-teams artifacts; the code
path works on today's public beta with zero research-preview
dependencies.

## What runs today

### Uploaded skills (2026-04-22T17:32:40Z)

```yaml
defender     skill_01Py4owBxPzpqa4pfmWPrwWs
attacker     skill_01Pq44fSBhTjtEya3U73xEKp
synthesizer  skill_01LRqcgBQW1YGMonZtrHUwjv
executor     skill_01VLF1w5TuAVoT5k83eBMeJ9
adjudicator  skill_01XuLKoXdjBHQ8WtfqDCw88w
```

Source: `skills/prism-<role>/SKILL.md`. Manifest written to
`skills/manifest.yaml` (committed). Upload script:
`scripts/register_skills.py` (double-gated).

### Bound to coordinator v2

```
agent_011CaJboTBvV6agLw9huTWJY  prism-coordinator  v2
  skills: [5 × {type: custom, skill_id: skill_01...}]
```

One `beta.agents.update(agent_id=..., version=1, skills=[...])`
call bumped the coordinator from v1 → v2. `agents/manifest.yaml`
updated.

### Live skilled audit

Session: `sesn_011CaKDGyjn5MfLYXyyBJTVB`
(`https://platform.claude.com/sessions/sesn_011CaKDGyjn5MfLYXyyBJTVB`)

| Metric | Skilled (v2) | Solo mode (v1, for comparison) |
|---|---|---|
| Wall time | **152.61 s** | 97.85 s |
| Events | **81** | 53 |
| `agent.thinking` spans | **6** | 1 |
| `agent.tool_use` events | **15** | 10 |
| `agent.message` turns | **10** | 7 |
| `span.model_request_*` pairs | **16** | 11 |
| User-message prompt size | **~400 chars** | 3,463 chars |
| `SKILLED AUDIT COMPLETE:` marker | ✓ | n/a |

Key delta: the **user message is ~9× smaller** under skilled mode
because the role specs live in Skills, not in the prompt. The
tradeoff is ~55 s more wall time because the model thinks and
invokes more tools (6 thinking spans vs 1) — it's genuinely using the
skills as reusable primitives, not as one-shot instructions.

## Why this is the right architecture

Per Anthropic's *"Scaling Managed Agents: Decoupling the brain from
the hands"* engineering blog, the canonical pattern has:

- **Brain** (Claude + harness) — stateless, replaceable.
- **Hands** (tools / skills / MCP servers) — disposable, composable.
- **Session** (event log) — durable.

Skills are a GA-grade "hand" that carries structured, versioned,
on-demand expertise. Using Skills to package each Prism role:

1. **Forward-compatible.** When multi-agent research-preview
   provisions on this workspace, the 5 Skills stay; the coordinator's
   `skills=[...]` binding stays; only the orchestration loop changes
   (delegation arrows fire on top of the same skill-loaded context).
2. **Reusable.** Other teams auditing GPU or clinical rails can bind
   the same 5 Skill IDs to THEIR coordinator. Open-standard by design.
3. **Reduced prompt bloat.** 3,463 → 400 chars in the first user
   message. Role specs move from ephemeral prompts to versioned
   artifacts.
4. **Progressive disclosure.** The metadata block costs ~500 tokens
   at startup for all 5 skills combined. The full ~2.5 KB body is
   loaded **only when the model decides it's needed** — Anthropic's
   native mechanism for this, not a workaround.
5. **Publishable.** `skills/` is a directory any third party can
   clone, modify, and re-register. Prism ships its dialectic as a
   skill pack.

## Reproduce

```bash
# 1. Upload + bind (one-time, ~$0)
PRISM_SKILLS_COMMIT=1 python scripts/register_skills.py --commit

# 2. Run a skilled audit (~$0.50 per run)
PRISM_SKILLED_AUDIT_COMMIT=1 python scripts/run_skilled_audit.py --commit
```

Artifacts land under `results/audits/<session_id>/transcript.log` and
`summary.json`. The audit-produced case files (invariants / attacks /
synthesizer stand-ins / exec record / verdict) live at
`/workspace/<case_id>/` inside the session container.

## What the skills say

Each `SKILL.md` (under `skills/prism-<role>/`) has:

- **YAML frontmatter**: `name` + `description` that doubles as the
  trigger instruction. The description field is XML-tag-free per
  Anthropic's validation (we hit a 400 the first pass on `<case_id>`
  in a description — fixed before the landed version).
- **Body**: schema the role must write + rail-specific heuristics +
  hard rules + counter-examples. ~2-3 KB each; well under the 5 KB
  soft cap Anthropic recommends for SKILL.md Level-2 instructions.
- **Hard single output**: each role writes exactly one artifact file
  and emits exactly one self-check line. No drift, no extras.

## Fumbles worth recording (for future agent sessions)

1. **First upload 400'd** on "SKILL.md file must be exactly in the
   top-level folder." Fix: pass filename as `prism-<role>/SKILL.md`,
   not `SKILL.md` — the API expects a folder-qualified path even for
   single-file skills.
2. **Second 400** on "SKILL.md description cannot contain XML tags."
   Fix: strip `<case_id>` tokens from the *description* frontmatter
   field. The body can keep angle brackets.
3. **Third 400** on "Skill cannot reuse an existing display_title."
   Fix: clean up the orphan Defender skill from attempt #2. Must
   delete all versions first (`beta.skills.versions.delete(version=,
   skill_id=)` — note kwarg order: `version` is positional-first in
   the SDK typed signature), then `beta.skills.delete(skill_id)`.
4. All three are documented in-script so future runs don't repeat.

## Cross-reference

- `scripts/register_skills.py` — upload + bind (double-gated).
- `scripts/run_skilled_audit.py` — live-session runner (double-gated).
- `skills/prism-<role>/SKILL.md` — the 5 role specs.
- `skills/manifest.yaml` — skill_id mapping.
- `agents/manifest.yaml` — coordinator v2 with bound skills.
- `findings/solo-audit-2026-04-22.md` — prior audit path (solo mode).
  Still works; kept as a lean alternative for cases that don't need
  the skill-loading overhead.
- `findings/smoke-delegation-2026-04-22.md` — the research-preview
  negative result this architecture side-steps.
- `CLAUDE.md` §8 — Managed Agents operating contract; update pending
  (add skills-as-hands section on next §8 edit).
- Canonical docs: `https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview`
  + `https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills`
