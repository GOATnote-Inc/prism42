# Claude Code Best Practices (for Prism and contributors)

> Neo-learning-kung-fu reference for Claude Code and any contributor (human or
> agent) working on Prism. Distilled from Anthropic's engineering writing on
> agents, context, tools, and multi-agent systems.
>
> Project-specific rules live in `CLAUDE.md` at the repo root. This doc is the
> *general* playbook for how to work with Claude on any agent-shaped task.

## 0. Prime directives

1. **Start simple. Add complexity only when it demonstrably improves outcomes.**
   Optimize a single LLM call with good retrieval and examples before reaching
   for workflows; reach for workflows before reaching for agents; reach for
   agents before reaching for multi-agent.
2. **Three core principles for any agent we ship:**
   (a) maintain simplicity,
   (b) prioritize transparency by showing the agent's planning steps,
   (c) craft the agent-computer interface (ACI) — tool docs and schemas — with
   as much care as any human-facing API.
3. **Treat context as a finite, precious resource.** Every token competes for a
   limited attention budget. Find "the smallest possible set of high-signal
   tokens that maximize the likelihood of the desired outcome."
4. **Evaluation is the steering wheel.** Start with ~20 realistic test cases on
   day one. Iterate prompts, tools, and harness against them. Don't wait for a
   "proper" eval suite.

## 1. When to use what (decision ladder)

- **Single LLM call + retrieval + examples** — default. Most hackathon features start here.
- **Workflow** (prompt chaining, routing, parallelization, orchestrator-workers,
  evaluator-optimizer) — when the task decomposes cleanly and you want
  predictability.
- **Agent** (LLM autonomously using tools in a loop) — when the path can't be
  predicted, the environment provides ground-truth feedback, and you're willing
  to trade cost/latency for flexibility.
- **Multi-agent** — only when the task is (i) high-value, (ii) heavily
  parallelizable, (iii) exceeds a single context window, or (iv) needs distinct
  separations of concern. Multi-agent systems use ~15× chat-level tokens and
  ~4× single-agent tokens — reserve them for breadth-first research, large
  codebase work, or exhaustive tool-interfacing.

Frameworks (Claude Agent SDK, etc.) are fine, but start by calling the API
directly so you actually understand the prompts and responses flowing through.
Incorrect assumptions about framework internals are a top source of bugs.

## 2. Workflow patterns (cheat sheet)

- **Prompt chaining** — decompose into sequential steps; add programmatic
  "gates" between steps. Great for outline → draft, or generate → translate.
- **Routing** — classify input, dispatch to specialized prompt/model. Use Haiku
  for easy/common cases and Sonnet/Opus for hard/unusual ones.
- **Parallelization** — sectioning (split independent subtasks) or voting (run
  the same task N times for confidence). Good for guardrails, multi-aspect
  evals, security review.
- **Orchestrator-workers** — lead LLM dynamically decomposes and delegates. Use
  when subtasks aren't predictable (e.g., multi-file code changes).
- **Evaluator-optimizer** — generator + critic loop. Use when evaluation
  criteria are crisp and iterative refinement helps (translation, complex
  search).

## 3. Context engineering

Context = system prompt + tools + examples + message history + retrieved data +
tool results. All of it competes for the attention budget. "Context rot" is
real — recall degrades as tokens grow.

- **System prompts at the right altitude.** Not brittle if/else walls of rules,
  not vague vibes. Give minimal-but-sufficient instruction organized into clear
  sections (`<background>`, `<instructions>`, `## Tool guidance`,
  `## Output format`). Start minimal with the best model and add only where
  failure modes appear.
- **Few-shot examples > rule lists.** Curate a small, diverse, canonical set of
  examples. Don't dump every edge case into the prompt.
- **Just-in-time retrieval beats front-loading everything.** Keep lightweight
  identifiers (file paths, IDs, URLs) and let the agent pull context on demand
  via tools. This mirrors how humans use file systems. Claude Code does this
  with `glob`/`grep` plus a `CLAUDE.md` hybrid.
- **Compaction** — when approaching context limits, summarize the conversation
  (preserve architectural decisions, unresolved bugs, implementation details;
  drop redundant tool output) and restart with the summary plus the N
  most-recent files.
- **Structured note-taking / agentic memory** — let the agent persist notes to
  a file (`NOTES.md`, `TODO.md`) outside the context window and re-read on
  demand. Huge unlock for long-horizon tasks.
- **Sub-agents for isolation** — spawn a subagent with a fresh context to do
  deep exploration, then have it return a 1–2k-token distilled summary. Detail
  stays out of the lead agent's window.
- **Clear tool-result clutter aggressively.** Old tool outputs deep in history
  are usually safe to drop — the newer state supersedes them.

## 4. Tool / ACI design (this is where most real wins live)

Tools are a contract between a deterministic system and a non-deterministic
agent. Design them *for* agents, not as thin wrappers around existing APIs.

**Choose the right tools:**
- Build a few high-leverage tools that match real workflows. Don't mirror every
  API endpoint.
- Prefer consolidated tools that do a meaningful unit of work: `schedule_event`
  (finds availability + books) beats `list_users` + `list_events` +
  `create_event`. `get_customer_context` beats three separate lookups.
  `search_logs` beats `read_logs`.
- Each tool needs a single, distinct purpose. Overlapping tools confuse agents.

**Namespace tools** to delineate boundaries, e.g., `asana_search`,
`asana_projects_search`, `github_issues_create`. Prefix vs. suffix matters —
test both.

**Return high-signal context:**
- Prefer semantic fields (`name`, `file_type`) over opaque identifiers (`uuid`,
  `mime_type`, `256px_image_url`).
- Resolve UUIDs to human-readable names or 0-indexed IDs when possible — it
  reduces hallucination measurably.
- Expose a `response_format` enum (e.g., `concise` | `detailed`) so the agent
  can control verbosity.
- Experiment with XML vs. JSON vs. Markdown for responses. No one-size-fits-all;
  let eval pick.

**Token efficiency:**
- Default-limit large responses (Claude Code caps tool responses at 25,000
  tokens).
- Support pagination, range selection, filtering, truncation with sensible
  defaults.
- When truncating, tell the agent how to get the rest ("use `offset=...` to
  continue").

**Prompt-engineer your tool descriptions like you're onboarding a junior
engineer:**
- Explicitly state niche terminology, query formats, resource relationships,
  edge cases, example usage.
- Name parameters unambiguously: `user_id` not `user`.
- Enforce strict schemas so malformed calls are rejected with *actionable*
  error messages (not tracebacks) — the error is itself a prompt back to the
  model.
- Poka-yoke: change signatures so mistakes become impossible (e.g., require
  absolute file paths to survive `cd`).

**Evaluate tools iteratively.** Build ~dozens of realistic multi-tool tasks,
run an agentic loop against them, read transcripts, and let Claude Code analyze
transcripts and rewrite tool descriptions. Anthropic's internal tool-testing
agent yielded a **40% reduction in task completion time** just from rewriting
descriptions.

## 5. Prompting agents (patterns that worked on the Research system)

- **Think like your agent.** Replay its trace step-by-step in a console. The
  failure mode is usually obvious once you watch it.
- **Teach the orchestrator how to delegate.** Each subtask handed off must
  specify: objective, output format, tools/sources to use, and explicit task
  boundaries. Vague delegation ("research the semiconductor shortage") produces
  duplicated or misdirected work.
- **Scale effort to query complexity.** Encode rules in the prompt:
  fact-finding → 1 agent, 3–10 tool calls; comparison → 2–4 subagents × 10–15
  calls; complex research → 10+ subagents. Prevents over-investment on simple
  tasks.
- **Start wide, then narrow.** Force agents to open with short, broad queries;
  evaluate results; then drill down.
- **Use extended / interleaved thinking as a controllable scratchpad.** Big
  wins for instruction-following, planning, and post-tool-call reflection.
- **Parallel tool calling.** Spin up 3–5 subagents in parallel; have each
  subagent call 3+ tools in parallel. Cuts research-style task time by up to
  90%.
- **Let Claude improve its own prompts and tools.** Claude 4-class models are
  excellent prompt engineers when given a failure trace.
- **Heuristics > rigid rules.** Codify how a skilled human would approach the
  task (decompose, judge source quality, adapt on new info, know when to go
  deep vs. broad). Pair with explicit guardrails so the agent doesn't spiral.

## 6. Evaluation

- **Start small, start now.** 20 realistic prompts beat 0 comprehensive ones.
  Effects are large early; you'll see signal.
- **LLM-as-judge works when done right.** A single model call with one rubric
  returning a 0.0–1.0 score + pass/fail is more consistent than multi-judge
  ensembles. Judge on: factual accuracy, citation accuracy, completeness,
  source quality, tool efficiency.
- **Human testing catches what automation misses.** Hallucinations on weird
  queries, source-selection bias (e.g., SEO farms over authoritative sources),
  weird emergent UX.
- **End-state eval for state-mutating agents.** Don't grade each turn — grade
  final state. Use checkpoint states for long workflows.
- **Track metrics beyond accuracy:** total runtime, tool-call count, token
  consumption, tool error rate. Redundant tool calls → fix pagination. Param
  errors → fix descriptions.

## 7. Production reliability

- **Agents are stateful; errors compound.** Never assume you can just restart
  from zero. Build resumability — durable session logs, checkpoints, idempotent
  tool calls.
- **Let the model handle errors gracefully.** Passing a clear tool-failure
  message back to Claude and letting it adapt works surprisingly well. Combine
  with deterministic retries for the flaky cases.
- **Observability.** Full production tracing of prompts, tool calls, tool
  results, and decision patterns (respecting user privacy). Non-determinism
  makes logs your only friend.
- **Rainbow deploys.** Agents can be anywhere in a long-running process when
  you ship. Don't kill them — run old and new versions side-by-side and drain.
- **Decouple brain / hands / session** (Managed Agents architecture):
  - **Brain** = Claude + harness (stateless, cattle not pets — if it crashes,
    respawn it).
  - **Hands** = sandboxes and tools accessed via
    `execute(name, input) → string`. Containers are cattle too; if one dies,
    return the error to the model and let it retry.
  - **Session** = durable append-only event log living *outside* the harness,
    queryable via `getEvents()`. Enables recovery, rewinding, and arbitrary
    context transformations per turn.
- **Never put credentials in the sandbox.** Use a vault + proxy pattern (e.g.,
  MCP proxy holds OAuth, repo clones use scoped tokens wired into local git
  remote). A prompt injection should never be one hop from your secrets.
- **Cache-friendly context layout.** Organize context for high prompt-cache hit
  rate — stable preambles first, volatile per-turn data last.

## 8. Coding-agent specifics (applies directly to Prism)

- **A `CLAUDE.md` at repo root is high-leverage.** It's dropped into context up
  front by Claude Code. Keep it tight: repo layout, key commands, coding
  conventions, invariants, how to run tests, anything a new hire would need on
  day one.
- **Prefer verifiable outcomes.** Code is well-suited to agents because tests
  give ground truth. Wire up fast, deterministic tests and let the agent
  iterate against them.
- **Absolute paths in tool signatures.** The SWE-bench lesson: relative paths
  break the moment the agent `cd`s. Make them impossible.
- **Subagents for exploration.** Let a subagent grep/read dozens of files with
  a clean context and return a small summary. Keep the lead agent clean.
- **Store artifacts in the filesystem, not in chat.** Subagents should write
  code/reports/diffs to files and pass back lightweight references — avoids
  the "game of telephone" and reduces token duplication.
- **Prefer search over list.** `search_code(query)` > `list_files()` + read
  each.
- **Synchronous execution is a bottleneck.** Favor async subagent dispatch
  where consistency allows; accept added complexity in coordination/error
  propagation.

## 9. Model selection and Opus 4.7 usage (hackathon scoring angle)

Judges weight "Opus 4.7 use" at 25% and reward creative, non-obvious uses.
Practical guidance:

- **Route by difficulty.** Use smaller/cheaper models (Haiku) for
  classification, pre-filtering, and simple tool-argument construction; Sonnet
  for mainline agent work; Opus 4.7 for the orchestrator and for hard
  reasoning / long-horizon planning. Multi-agent with Opus lead + Sonnet
  subagents is the known-good pattern.
- **Treat Opus 4.7 as a creative medium, not a tool.** The "Most Creative"
  prize explicitly rewards voice, point of view, surprise. Use extended
  thinking, interleaved thinking, and the model's self-improvement ability as
  features, not implementation details.
- **Surface capability.** Show planning traces, let the user see what the
  agent tried and why. Transparency is both a safety property and a demo
  feature.

## 10. Hackathon-specific guardrails

- **Every component must be open source** under an approved license (backend,
  frontend, models, assets). No pre-existing code.
- **Team ≤ 2 members.** All work net-new.
- **Deliverables:** 3-min demo video, open-source repo, 100–200-word written
  summary. Deadline Apr 26, 8:00 PM EST.
- **Judging weights (Stage 1):** Impact 30% / Demo 25% / Opus 4.7 Use 25% /
  Depth & Execution 20%.
- **Managed Agents prize ($5k credits):** for a meaningful long-running task
  hand-off — not a toy, something you'd actually ship. Architect
  brain/hands/session decoupling if you're going for this.

## 11. Default checklist before merging any agent code

- [ ] Does this add genuine capability, or am I adding complexity for its own sake?
- [ ] Is the system prompt at the right altitude (not brittle, not vague)?
- [ ] Does every tool have a distinct purpose, a clear docstring, unambiguous
      params, and an actionable error path?
- [ ] Have I budgeted context? Any long tool outputs paginated/truncated? Any
      stale tool results cleared?
- [ ] Do I have ≥20 realistic eval cases and a way to run them in a loop?
- [ ] Are there checkpoints / resumability so a crash doesn't cost the whole
      session?
- [ ] Is there a trace log I can read when something goes sideways?
- [ ] Are secrets out of the sandbox?
- [ ] Could a subagent handle this with a clean context instead of bloating the
      main one?

---

<!-- GAPS_FILLED_BELOW -->

---

## 12. Claude Code Best Practices — condensed from code.claude.com

*(Fetched 2026-04-21 from `code.claude.com/docs/en/best-practices`.)*

**Context is the fundamental constraint.** Claude Code performance degrades as
the window fills. Everything below is downstream of managing that.

### Verification

- **Give Claude a way to verify its work** — tests, screenshots, expected
  outputs. This is the single highest-leverage thing you can do.
- Provide concrete success criteria: not *"implement email validation"* but
  *"write validateEmail; test cases: user@example.com → true, invalid → false,
  user@.com → false; run the tests."*
- **Address root causes, not symptoms.** Tell Claude to fix the cause, not
  suppress the error.

### Workflow: Explore → Plan → Implement → Commit

- Use **Plan Mode** to separate research from execution. `Ctrl+G` opens the
  plan in your editor for direct edits before Claude proceeds.
- Skip planning for small, scoped changes (typo, rename, single line). Plan
  when: uncertain about approach, multi-file change, unfamiliar code.

### Specific context > vague prompts

- **Scope the task** (file, scenario, testing prefs).
- **Point to sources** (a file, a git history, an example pattern file).
- **Describe the symptom + likely location + what "fixed" looks like.**
- Rich content: `@path` to reference files, paste images/screenshots,
  `cat err.log | claude`, pass URLs (allowlist frequent domains via
  `/permissions`), and explicitly tell Claude to fetch what it needs.

### CLAUDE.md hygiene

- `/init` generates a starter CLAUDE.md. Refine over time.
- **Keep it short.** For every line ask: "Would removing this cause mistakes?"
  If not, cut it. Bloated CLAUDE.md → Claude ignores actual instructions.
- **Include:** bash commands Claude can't guess, house code-style rules
  differing from defaults, test commands, repo etiquette, architectural
  decisions, env quirks, non-obvious gotchas.
- **Exclude:** anything derivable from code, standard language conventions,
  API docs (link instead), file-by-file descriptions, self-evident advice.
- Import other files with `@path/to/file.md` syntax.
- Placement: `~/.claude/CLAUDE.md` (global), `./CLAUDE.md` (team), `./CLAUDE.local.md`
  (personal, gitignored), parent/child dirs (monorepos; children load on demand).
- Emphasis works: "IMPORTANT" / "YOU MUST" increases adherence.
- Check it into git. If Claude repeatedly violates a rule, the file is likely
  too long — prune.

### Permissions & sandboxing

- **Auto mode** (`claude --permission-mode auto`) — classifier model blocks
  risky actions, waves through routine work. Best when you trust the direction
  but don't want to click through every step. In `-p` non-interactive runs, it
  aborts after repeated blocks.
- **Permission allowlists** via `/permissions` — e.g., always-allow
  `npm run lint`, `git commit`.
- **`/sandbox`** — OS-level filesystem + network isolation.

### External tooling

- Install CLI tools (`gh`, `aws`, `gcloud`, `sentry-cli`). They are the most
  context-efficient way for Claude to talk to external services. `gh auth login`
  is table stakes if you use GitHub.
- `claude mcp add` to connect Notion/Figma/DBs via MCP.
- **Hooks are deterministic** where CLAUDE.md is advisory. Use hooks for
  actions that *must* happen every time (formatter after edit, block writes
  to `migrations/`).
- **Skills** give domain knowledge / reusable workflows, loaded on demand —
  don't bloat every conversation. `disable-model-invocation: true` makes a
  Skill user-triggered only (for workflows with side effects).
- **Subagents** in `.claude/agents/*.md` — isolated context + scoped tools
  + specialized role (e.g., security-reviewer). Tell Claude *"use a subagent
  to…"* explicitly.
- **Plugins** via `/plugin` — bundled skills+hooks+subagents+MCP from the
  marketplace.

### Communication patterns

- **Ask codebase questions like a new hire** — "how does logging work",
  "what edge cases does X handle", "why `foo()` instead of `bar()` on line 333".
  No special prompting required.
- **Let Claude interview you** for large features: start with a minimal
  prompt, ask it to use `AskUserQuestion` to dig into implementation, UX,
  edge cases, tradeoffs — then write the spec to SPEC.md. Fresh session
  executes from the spec.

### Session management

- **Course-correct early and often.**
  - `Esc` — stop Claude mid-action (context preserved).
  - `Esc+Esc` or `/rewind` — restore previous conversation/code or summarize
    from a selected message.
  - *"Undo that"* — revert Claude's changes.
  - `/clear` — reset context between unrelated tasks.
- **After two failed corrections, `/clear` and re-prompt.** Cluttered context
  full of failed attempts almost never beats a fresh session with a sharper
  prompt.
- `/compact <instructions>` for manual compaction targeting specific slices.
- `Esc+Esc` → "Summarize from here" condenses part of the conversation while
  keeping earlier context intact.
- `/btw` for quick side questions — answer appears as a dismissible overlay,
  never enters conversation history.
- **Subagents for investigation** — separate context window, returns a
  summary. The most powerful lever for keeping main context clean.
- **Checkpoints** — every action is checkpointed. Tell Claude to try something
  risky; rewind if it doesn't work. Note: checkpoints track only Claude's
  changes, not external processes — not a git replacement.
- `claude --continue` (most recent session) / `claude --resume` (pick).
  `/rename` gives sessions descriptive names. Treat sessions like branches.

### Non-interactive + parallel

- `claude -p "prompt"` for CI/pre-commit/scripting. `--output-format json` or
  `stream-json` for parsing.
- **Parallel sessions** — desktop app (isolated worktrees), Claude Code on
  the web (cloud VMs), or Agent Teams (shared tasks, team lead).
- **Writer/Reviewer pattern** — fresh reviewer context catches what the
  writer missed. Also works for test-writer / implementation-writer.
- **Fan-out** — loop `claude -p "…$file…"` across a file list with
  `--allowedTools` scoped for unattended runs.

### Failure patterns to avoid

- **Kitchen sink session** — unrelated tasks in one context. `/clear`.
- **Correcting over and over** — after two misses, `/clear` + re-prompt.
- **Over-specified CLAUDE.md** — important rules get lost in noise. Prune
  aggressively; convert rules to hooks where possible.
- **Trust-then-verify gap** — plausible-looking code that doesn't work. If
  you can't verify it, don't ship it.
- **Infinite exploration** — unbounded "investigate X" consumes context.
  Scope or delegate to a subagent.

---

## 13. Prompt engineering (Anthropic canon) — condensed

*(Fetched 2026-04-21 from `platform.claude.com/docs/.../prompt-engineering/overview`
and `claude.com/blog/best-practices-for-prompt-engineering`.)*

### Prerequisites

Before you prompt-engineer anything, have:
1. Clear success criteria for the task.
2. Some way to empirically test against them.
3. A first-draft prompt to improve.

Prompt engineering is for improving controllable outcomes. If latency or cost
is the real problem, pick a different model — don't prompt harder.

### Canon techniques (use in this order)

1. **Explicit > inferred.** State desired features, depth, format. Don't
   assume Claude will infer intent.
2. **Verb-first clarity.** Lead with `Write`, `Analyze`, `Generate`,
   `Create`. Skip preambles.
3. **Justify constraints.** Saying *why* (not just *what*) lets the model
   generalize to related decisions.
4. **Examples over description** (few-shot). One well-chosen example beats
   a paragraph of prose. Start with one, add more only if needed.
5. **Let Claude think** (chain-of-thought / extended thinking) before
   committing to an answer — especially on multi-step or reasoning tasks.
6. **Give uncertainty permission.** Explicitly allow *"I don't know"* — it
   reduces hallucinations.
7. **Prefill for format control.** Start the assistant's turn with `{` to
   force JSON, skip preambles, or anchor tone.
8. **Chain prompts for multi-stage problems.** Separate focused prompts beat
   one giant one.
9. **Modern role simplicity.** Skip "you are a world-renowned expert"
   theatre. An explicit perspective request ("analyze focusing on X") works
   better.
10. **Use XML tags / structure only when actually needed.** For modern
    Claude, clear headings and whitespace usually suffice. Reserve XML for
    complex prompts where you need unambiguous sectioning.
11. **Iterate and measure.** Longer / more complex prompts aren't inherently
    better. Test the impact of each addition.

### Tools in the Console

Anthropic's Console ships a **prompt generator**, **templates and variables**,
and **prompt improver** — useful for quickly iterating drafts. Try the
[prompt-eng interactive tutorial](https://github.com/anthropics/prompt-eng-interactive-tutorial)
for hands-on.

---

## 14. Skills — explained + authoring

*(Fetched 2026-04-21 from `claude.com/blog/skills-explained` and
`.../building-agents-with-skills-equipping-agents-for-specialized-work`.)*

### What they are

Skills are **folders containing instructions, scripts, and resources** that
Claude dynamically loads when relevant. Think "training manual" for a
specific domain, loaded on demand — not injected into every conversation.

### vs the alternatives

| Mechanism | When |
|---|---|
| **Prompt** | One-time, in-conversation instruction. |
| **Project** | Persistent *knowledge* for an initiative (the "what"). |
| **Skill** | Persistent *procedural expertise* that triggers by description (the "how"). Loads on demand. |
| **MCP** | Connectivity to external data/tools. Complementary to Skills. |
| **Subagent** | Independent agent with its own context + scoped tools. Use for discrete task delegation; use Skills for shared procedures. |

### Progressive-disclosure architecture

Three tiers loaded as needed:
- **Metadata** (~100 tokens) — `name` + `description` in YAML frontmatter.
  This is *all* Claude sees by default; it must accurately signal when the
  Skill applies.
- **SKILL.md body** (~≤500 tokens is a good target, cap ~5k) — core
  procedure.
- **Bundled assets** — docs, scripts, reference files. Code is
  self-documenting and doesn't need to be in context at all times.

### Canonical layout

```
.claude/skills/<skill-name>/
  SKILL.md             # YAML frontmatter + body
  docs/*.md            # loaded on demand
  scripts/*.py|sh      # self-documenting, executable
```

Minimal SKILL.md:
```markdown
---
name: api-conventions
description: REST API design conventions for our services
---
# API Conventions
- kebab-case URL paths
- camelCase JSON properties
- pagination on all list endpoints
- version in URL (/v1/, /v2/)
```

User-triggered-only (for side-effectful workflows):
```markdown
---
name: fix-issue
description: Fix a GitHub issue
disable-model-invocation: true
---
Fix GitHub issue $ARGUMENTS...
```
Invoke with `/fix-issue 1234`.

### Authoring best practices

- **Name is a signal.** "DCF Model Builder" > "Finance Tool".
- **Description is the trigger.** Agents only see it initially. Concisely
  state *what the skill does* and *when to use it*.
- **Scope tightly.** Over-scoped Skills pollute discovery; split into
  multiple.
- **No org-specific assumptions** baked into a reusable Skill.
- **Bundle self-documenting code** rather than cramming procedure into prose.

### Common failure modes

- Over-scoped (too much unrelated info)
- Poor/ambiguous description → never triggers
- Hard-coded org assumptions → fails elsewhere

---

## 15. Hooks — deterministic automation

*(Fetched 2026-04-21 from `claude.com/blog/how-to-configure-hooks`.)*

**Hooks are shell commands Claude Code runs automatically at lifecycle
events.** Unlike CLAUDE.md (advisory), hooks are deterministic. Use them when
an action *must* happen every time.

### Events

| Event | Fires | Common uses |
|---|---|---|
| `PreToolUse` | Before tool runs | Block dangerous commands, validate paths |
| `PostToolUse` | After tool runs | Auto-format on write/edit |
| `PermissionRequest` | On permission dialog | Auto-approve safe ops |
| `UserPromptSubmit` | When user submits | Inject dynamic context |
| `SessionStart` | Session begins | Load git status, TODO |
| `Stop` | Claude finishes responding | Force continuation / notify |
| `PreCompact` | Before context compaction | Back up transcript |
| `SubagentStop` | Subagent completes | Validate output |

### Configuration locations

- `.claude/settings.json` — project, shareable
- `~/.claude/settings.json` — user, global
- `.claude/settings.local.json` — personal, gitignored

### Exit codes

- `0` — success; stdout parsed as JSON or added to context
- `2` — blocking error; stderr becomes the error message, action prevented
- other — non-blocking; visible in `--verbose`

### Canonical recipes

**Auto-format on write:**
```json
{ "hooks": { "PostToolUse": [{
    "matcher": "Write|Edit",
    "hooks": [{ "type": "command",
                "command": "prettier --write \"$CLAUDE_TOOL_INPUT_FILE_PATH\"" }]
}] } }
```

**Auto-approve safe bash prefix:**
```json
{ "hooks": { "PermissionRequest": [{
    "matcher": "Bash(npm test*)",
    "hooks": [{ "type": "command", "command": "exit 0" }]
}] } }
```

**Inject sprint context into every prompt:**
```json
{ "hooks": { "UserPromptSubmit": [{
    "hooks": [{ "type": "command",
                "command": "cat ./current-sprint-context.md" }]
}] } }
```

**Session-start briefing:**
```json
{ "hooks": { "SessionStart": [{
    "hooks": [{ "type": "command",
                "command": "git status --short && echo --- && cat TODO.md" }]
}] } }
```

Claude will write hooks for you: *"Write a hook that runs eslint after every
file edit"*. Browse configured hooks with `/hooks`.

---

## 16. Claude Managed Agents — the brain/hands/session harness

*(Fetched 2026-04-21 from `platform.claude.com/docs/en/managed-agents/overview`.
Currently in beta; behavior may change.)*

Anthropic offers two paths:

| | Messages API | Claude Managed Agents |
|---|---|---|
| **What** | Raw model access | Pre-built agent harness with managed infra |
| **For** | Custom loops, fine-grained control | Long-running, async work |

Managed Agents handles the agent loop, tool execution, container runtime,
prompt caching, and compaction for you.

### Four core concepts

- **Agent** — model + system prompt + tools + MCP servers + skills. Defined
  once, referenced by ID.
- **Environment** — container template (pre-installed packages, network
  access rules, mounted files).
- **Session** — a running agent instance in an environment, performing one task.
- **Events** — messages exchanged (user turns, tool results, status). Persisted
  server-side; fetchable in full. Streamed back via SSE.

### Lifecycle

1. **Create agent** (once).
2. **Create environment** (container template).
3. **Start session** referencing agent + environment.
4. **Send events, stream responses.** Claude autonomously runs tools.
5. **Steer or interrupt** mid-execution by sending more events.

### Built-in tools

Bash · file ops (read/write/edit/glob/grep) · web search+fetch · MCP servers.

### When to reach for it

- Long-running tasks (minutes to hours, many tool calls)
- You don't want to build a sandbox/loop/tool-execution layer
- You want stateful, persistent FS across interactions
- Good fit for the hackathon's **"Best use of Claude Managed Agents"
  $5k credits prize** — show a meaningful, long-running hand-off you'd
  actually ship.

### Access

- `managed-agents-2026-04-01` beta header required (SDK sets automatically).
- Enabled by default for all API accounts.
- Rate limits: 60 create-ops/min, 600 read-ops/min per org.
- **Research preview** (needs separate access): outcomes, multi-agent,
  memory.
- Branding: can call it "Claude Agent" or "{YourName} Powered by Claude".
  Cannot call it "Claude Code".

---

## 17. Multi-agent systems — decision framework

*(Fetched 2026-04-21 from `claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them`.)*

### When multi-agent wins

1. **Context protection** — isolated contexts prevent pollution from
   irrelevant information.
2. **Parallelization** — independent subtasks run concurrently (research,
   search).
3. **Specialization** — distinct toolsets (15–20+ tools in one agent → selection
   errors), conflicting modes, or domain-specific expertise.

### Anti-patterns

- **Problem-type decomposition fails.** Splitting by role (planner /
  implementer / tester / reviewer) creates coordination overhead and
  hand-off context loss. Use **context-centric decomposition** — group work
  by shared context requirements.
- **The telephone game.** Multi-agent typically burns 3–10× the tokens of a
  single agent (duplicated context, coordination messages, summarization).
- **Premature optimization.** Teams often build elaborate multi-agent
  architectures only to find better single-agent prompting matched it.

### Named patterns

- **Orchestrator + subagents** — hierarchical; lead spawns specialists.
- **Verification subagent** — dedicated agent tests/validates the main
  agent's work. Minimal context transfer required.

### Core principle

Start single-agent. **Add multi-agent complexity only when evidence demands
it.** Recent wins (context compaction, Tool Search Tool) have shifted the
threshold — it's higher than it used to be.

---

## 18. Claude Agent SDK — when raw API isn't enough

*(Fetched 2026-04-21 from `claude.com/blog/building-agents-with-the-claude-agent-sdk`.
Previously called the "Claude Code SDK" — same thing, broader framing.)*

### Philosophy

*"Giving Claude a computer unlocks agents more effective than before."*
Terminal + filesystem + code execution → Claude operates like a human IC.

### What the SDK gives you (vs raw Messages API)

- Baked-in agent loop: **Gather context → Act → Verify → Repeat**
- Automatic context management (compaction, semantic search)
- Simplified tool abstractions
- Subagent spawning + MCP integration
- Visual / rules-based / LLM-as-judge verification hooks

### Primitives (conceptual)

- **Tools** — custom actions
- **File system access** — retrieval + agentic search
- **Bash execution** — general-purpose
- **Code generation** — composable operations
- **Subagents** — parallelization + isolation
- **MCP** — standardized external integrations

### Use SDK when

Building a multi-step autonomous system that needs iteration, context
management, and tool orchestration. Use raw API when you want complete
control over every turn.

---

## 19. MCP — Model Context Protocol

*(Fetched 2026-04-21 from `modelcontextprotocol.io/docs/getting-started/intro`.)*

> *"USB-C for AI applications"* — open-source standard for connecting AI
> apps to external systems.

### Three primitives

- **Resources** — data sources (files, DBs) the model can read
- **Tools** — actions the model can invoke (search, create, calculate)
- **Prompts** — specialized / parameterized prompts the host can surface

### Server vs client

- **Server** exposes resources/tools/prompts from a specific system
  (GitHub, Figma, Postgres, your internal API).
- **Client** is the AI app (Claude Desktop, Claude Code, Cursor, VS Code)
  that consumes servers.

### First-server checklist

1. Pick one high-leverage capability. Don't wrap every endpoint.
2. Write tool descriptions like you're onboarding a junior engineer (see §4).
3. Test via Claude Code: `claude mcp add <name>` then try realistic tasks
   and read transcripts.

Widely supported across Claude, ChatGPT, VS Code, Cursor, and others — build
once, integrate everywhere.

---

## Sources

Primary Anthropic docs fetched 2026-04-21:

- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- [Prompt engineering overview](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview)
- [Best practices for prompt engineering (blog)](https://claude.com/blog/best-practices-for-prompt-engineering)
- [Skills explained](https://claude.com/blog/skills-explained)
- [Building agents with Skills](https://claude.com/blog/building-agents-with-skills-equipping-agents-for-specialized-work)
- [How to configure hooks](https://claude.com/blog/how-to-configure-hooks)
- [Claude Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview)
- [Building multi-agent systems](https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them)
- [Building agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)
- [MCP getting started](https://modelcontextprotocol.io/docs/getting-started/intro)

Original sources (referenced but not fetched in this pass — read directly
for canonical detail): Building Effective Agents, Effective Context
Engineering for AI Agents, How we built our multi-agent research system,
Writing effective tools for AI agents, Scaling Managed Agents — all at
`anthropic.com/engineering`.
