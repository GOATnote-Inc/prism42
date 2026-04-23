---
title: Prism — Long-Horizon Architecture Proposal
subtitle: From episodic bursts to an autonomous agent workforce
date: 2026-04-22
status: PROPOSAL — awaiting user scope decision before implementation
scope: Synthesize Karpathy's AutoResearch, Ralph loop, OpenClaw/NemoClaw/SwarmClaw, Garry Tan's GBrain, and Claude Code Routines into a Prism-specific architecture.
---

# Prism — Long-Horizon Architecture

The user's framing: "demo is a mere reflection of current state. What we
have so far is merely one team of agents working for short bursts instead
of long horizons." Correct. Everything shipped to date (T5b — T5c Skills)
is **episodic**: run a smoke, commit, stop. What we need for real value
is a **continuously-running workforce** where scheduled routines pursue
the roadmap goals autonomously, with an orchestrator ensuring each
contributes to the greater objective.

This doc surveys the 4 canonical patterns (searched 2026-04-22) and
proposes a concrete Prism-specific architecture built on Anthropic's
native **Claude Code Routines** primitive (April 2026 release). It
does NOT auto-implement — that requires a go/no-go decision on
recurring spend, on-by-default push-to-main, and physician-review
gates the automation must respect.

---

## The 4 patterns we're synthesizing

### 1. Karpathy's AutoResearch (2026-03-07)

- [Repo](https://github.com/karpathy/autoresearch). 21k+ GitHub stars.
- **Loop shape**: 630-line Python. Agent reads its own code, hypothesizes
  a change (learning rate, arch depth), runs experiment, evaluates.
  Keeps only changes that beat the current best.
- **Key invariant**: fixed compute budget per iteration (e.g. 5 min GPU).
- **Evidence it works**: 700 autonomous changes on depth-12 model in
  2 days → 20 transferable improvements → 11% efficiency gain on
  "Time to GPT-2" leaderboard.
- **Pattern name**: *hypothesis-keep loop.*

### 2. Ralph Loop (Geoffrey Huntley et al., Jan 2026)

- [Repo](https://github.com/snarktank/ralph). "Everything is a Ralph loop."
- **Loop shape**: `while(true)` that feeds the same prompt to an AI coding
  agent (Amp or Claude Code) until all PRD items are complete.
- **State persistence**: git history + `progress.txt` + `prd.json` —
  agent sees its prior work each iteration.
- **HITL vs AFK balance**: 10% human-in-the-loop for architecture
  decisions, 90% AFK for the mechanical work.
- **Pattern name**: *PRD-until-done iteration.*

### 3. OpenClaw / NemoClaw / SwarmClaw (Nov 2025 → Apr 2026)

- OpenClaw = personal AI assistant, locally hosted, messaging UI.
- NemoClaw = NVIDIA enterprise stack with sandboxing, egress control,
  minimal-privilege access — "security layer for autonomous agents."
- SwarmClaw = multi-agent runtime. Orchestrators + subagents +
  heartbeats + orchestrator-wake-cycles + schedules + durable memory +
  reflection memory + human-context learning.
- **Pattern name**: *platform with security-first autonomy.*

### 4. Garry Tan's GBrain / GStack (2026-03-12 / 2026-04-09)

- [gstack](https://github.com/gtan/gstack) — 13 Claude Code skills + cron jobs.
- GBrain = personal knowledge repo (10k+ Markdown files) + pgvector +
  skill-triggered agents. Open-source, MIT.
- **Key idiom** (Tan's own framing): "when an agent is fired up, it
  doesn't just jump into writing code; instead, it steps back, asks
  what the user is trying to do, and then creates an implementation
  plan."
- Workflow stages: brainstorm → git worktrees → write plan → subagent-
  driven dev → TDD → code review → finish/branch.
- **Pattern name**: *plan-first + skills + cron.*

### 5. Anthropic's native primitive: Claude Code Routines (2026-04-14)

- [Docs](https://code.claude.com/docs/en/scheduled-tasks).
- **Three trigger types**: schedule (hourly/daily/weekly or cron), API
  call (per-routine bearer-token HTTP endpoint), GitHub webhook.
- **Scheduling minimum**: 1 hour (for sub-hour polling, use `/loop`
  inside an existing session).
- **Plan limits**: Pro 5 runs/day, Max 15, Team/Enterprise 25.
- **Runs in cloud**, not the user's laptop. Same terminal workflow.

---

## Prism's current state — why it's episodic

Everything tonight is single-shot:

- `make verify-all` — offline check, one run.
- `scripts/run_solo_audit.py --commit` — one session, one audit, done.
- `scripts/run_skilled_audit.py --commit` — one session with bound skills.
- `scripts/register_{agents,skills}.py --commit` — one-time bootstrap.

None of these run on their own. None of them read `docs/clinical-roadmap.md`
and pick the next task. None of them update `results/demo/index.html`
without a human invoking `make demo-html-commit`. None of them notice
that a pushed commit turned CI red.

That is the shape the user is objecting to. Correct objection.

---

## Proposal: Prism Long-Horizon Mode — 3 tiers

Minimum viable variant first; escalate tier-by-tier with user sign-off
at each level.

### Tier 0 (exists today, committed): Episodic runners

- 6 agents + 1 environment registered.
- 5 skills bound to coordinator v2.
- Solo + skilled audit scripts.
- Demo artifact generators.

**Action**: none. This is the base layer.

### Tier 1 (proposed): Daily autonomy — MVP

**One** Claude Code Routine, scheduled 1 am PT daily:

- Reads `docs/clinical-roadmap.md`, `CLAUDE.md` §4 (verification
  discipline), and `findings/*.md` (what's already been done).
- Invokes `prism-coordinator` with a **new** bound skill
  `prism-planner` (SKILL.md to be authored): "identify one roadmap
  item achievable in <1 hour, emit it as `/workspace/next_task.json`."
- If the task is one Prism already supports (run an audit, regenerate
  demo, run benchmark), the routine continues and invokes the right
  Prism runner via `scripts/<runner>.py --commit`.
- Regenerates `results/demo/index.html` with the new state.
- Opens a **draft PR** against `main` with the day's changes. Does
  NOT auto-merge. Brandon reviews + merges on morning coffee.
- Hard safeguards:
  - **Daily spend cap**: $20. Halts at cap with a status comment.
  - **Hard-stop on**: red `make verify-all`, uncommitted parallel-
    session edits, `physician_review=null` on any verdict that
    says `confirmed`.
  - **Frozen paths** (CLAUDE.md §3) read-only as always.
  - **Co-author footer** `Claude Opus 4.7` on every commit.

**What Tier 1 gets us**: a daily heartbeat. The repo visibly advances
every morning. The submission demo reflects today's state, not
yesterday's.

**Risk**: ~$20/day = ~$140/week. Hackathon budget cap is $280 total
(per CLAUDE.md §9) — Tier 1 alone doesn't fit.  Scope gate: either
reduce daily cap to $5-8 (lower ambition per run, more reliable) or
expand the hackathon budget for the long-horizon experiment.

### Tier 2 (proposed): Hourly workers (q1h min per Routines API)

Add one more routine: **hourly worker**. Picks small self-contained
tasks (<5 min each), e.g.:

- Regenerate demo artifacts after a corpus edit.
- Run `make verify-all` on a schedule, file an issue if red.
- Re-render `results/demo/index.html` after a skills update.
- Audit a new clinical-demo fixture.

Delegates via the 5 skills. Writes `findings/hourly-<stamp>.md` log.

**Budget**: ~$3/hour × 24 = ~$72/day on top of Tier 1 = **too much**.
Do NOT run hourly until hackathon ends. Gated to scheduled windows
(e.g. 8 am – 8 pm PT only = 12 runs × $3 ≈ $36/day).

### Tier 3 (proposed): Orchestrator-of-orchestrators

The **1 am PT daily** routine becomes the orchestrator. Delegates to
parallel sessions (new Managed Agents sessions) per task. Each task-
session has a budget cap, a wall-clock cap, and a finish-condition.
Orchestrator tracks status in `findings/orchestrator-<date>.md`.

Patterns baked in:

- **Ralph loop**: if a task's `make verify-all` fails, re-delegate
  with the error as context. Max 3 retries per task.
- **AutoResearch keep-if-better**: if a proposed change doesn't beat
  the current baseline on the phase-B scorer (HealthBench Hard
  aggregate), revert. Only keep changes that improve the measured
  delta.
- **GBrain plan-first**: every task-session begins with `prism-planner`
  emitting a written plan; executor only acts after plan is persisted.

**Budget**: Tier 3 is the expensive one. Defer until:
(a) Tier 1 runs smoothly for 3+ days without incident, (b) budget
envelope expanded, (c) explicit Brandon sign-off.

---

## What to build first (if we get the go-ahead)

**MVP is Tier 1 + a small demo auto-updater**. Concrete deliverables,
~4-6 hours of work:

1. `skills/prism-planner/SKILL.md` — "read roadmap + state, emit
   next_task.json." Same upload path as the other 5 skills
   (~15 min). Bound to the coordinator (same agents.update call).
2. `scripts/orchestrator.py` — Ralph-loop wrapper (double-gated,
   `--commit` + `PRISM_ORCHESTRATOR_COMMIT=1`). ~150 lines.
3. `scripts/demo_auto_update.py` — runs every `make *-commit`
   target, regenerates HTML, commits if there's a change. ~80 lines.
4. `.github/workflows/daily-heartbeat.yml` — GitHub Action that
   invokes the orchestrator's API endpoint on a cron. Alternative
   to Claude Code Routines if cron granularity needed.
5. `findings/long-horizon-runbook.md` — when to trust, when to
   revoke, how to rollback a bad autonomous commit.
6. **Integration tests** for the orchestrator: feed it a synthetic
   "stale state" (missing results/demo/), verify it self-heals.

---

## Explicit non-decisions — need user direction

1. **Recurring spend**. $20/day Tier 1 ceiling vs $5/day vs pause
   entirely. Current hackathon total cap is $280 (CLAUDE.md §9);
   Tier 1 at $20/day consumes that in 14 days.
2. **Auto-PR vs auto-merge-to-main**. Default recommendation: draft
   PR only, never auto-merge. User merges manually after 60-second
   review. Adopts Ralph's "HITL/AFK split" where human owns the
   architecture decisions + merge authority.
3. **Clinical-rail autonomy**. Clinical findings MUST stay
   physician-gated (CLAUDE.md §10). Orchestrator can propose a
   finding but cannot route it to disclosure. The physician-review
   field stays `null` until Brandon signs it. Proposed: orchestrator
   opens a PR; physician reviews the PR; merge is the signature.
4. **Routines plan tier**. Requires Max or Team plan for >5 runs/day.
   Current plan unknown. If Pro: Tier 1 is feasible (1 run/day under
   the 5/day cap), Tier 2 + 3 not.
5. **Which tier to start with**. My recommendation: **Tier 1 MVP
   only, for 3 days**. Measure reliability + actual spend. Escalate
   to Tier 2 or Tier 3 only if Tier 1 is provably green.

---

## Why this is the right pivot now

Three independent reasons:

1. **Judges will see it.** The hackathon demo video benefits from
   "wake up tomorrow and the repo has advanced" energy. Solo audit
   + skilled audit are impressive; a live orchestrator that did a
   thing overnight is *un-ignorable*.
2. **It matches Prism's stated thesis.** CLAUDE.md §1: "no
   speculative findings." Long-horizon autonomy forces the
   discipline — every proposed change must pass the PoC-validator
   gate before merge. The Ralph loop + AutoResearch keep-if-better
   constraints are exactly that gate applied continuously.
3. **The primitives are all public-beta or better.** Claude Code
   Routines shipped Apr 14. Agent Skills are GA. The 6 Prism agents
   are registered. We are not waiting on research-preview for any
   piece of this architecture.

---

## Cross-reference

- Karpathy AutoResearch: https://github.com/karpathy/autoresearch
- Ralph loop: https://github.com/snarktank/ralph
- OpenClaw: https://github.com/openclaw/openclaw
- NVIDIA NemoClaw: https://www.nvidia.com/en-us/ai/nemoclaw/
- SwarmClaw: https://github.com/swarmclawai/swarmclaw
- Garry Tan gstack: https://github.com/gtan/gstack (check current URL)
- Garry Tan GBrain: open-sourced 2026-04-09
- Claude Code Routines: https://code.claude.com/docs/en/scheduled-tasks
- Anthropic "Scaling Managed Agents: Decoupling the brain from the
  hands": https://www.anthropic.com/engineering/managed-agents
- Prism's existing skills surface (the building blocks):
  `findings/skills-audit-2026-04-22.md`, `skills/manifest.yaml`.

---

## Request

Brandon: give me explicit go/no-go on:

1. Build Tier 1 MVP (daily 1 am routine, draft-PR-only, $5/day cap)?
2. Budget envelope for the long-horizon experiment (current remaining
   hackathon budget or expanded)?
3. Routines plan tier available (Pro / Max / Team)?
4. Physician-review posture for auto-generated clinical findings
   (keep PR-gated, as recommended)?

I will not schedule any recurring spend without explicit yes on all 4.
