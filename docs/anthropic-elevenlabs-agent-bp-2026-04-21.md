---
title: Anthropic + ElevenLabs Agent Build Reference
date: 2026-04-21
fetch_date: 2026-04-21
status: Reference (snapshot)
scope: Last-30-day best-practices snapshot for Claude Opus 4.7 + ElevenLabs voice-agent builds. Every factual claim carries a URL at bottom. Re-verify before quoting in submission.
---

# Anthropic + ElevenLabs Agent Build Reference (Snapshot 2026-04-21)

Companion to `docs/sota-portfolio.md` §3 (Phase V) and §10 (Opus 4.7 operational constraints). All claims dated to fetch-date 2026-04-21. Primary sources preferred over third-party blogs.

## 1. Anthropic — agent-building essentials

### 1.1 Claude Managed Agents (beta, public)

- Beta header: `anthropic-beta: managed-agents-2026-04-01`. Still beta, not GA. SDK sets it automatically. [1]
- Core Managed Agents endpoints are **public beta** (enabled by default for all API accounts). Three features remain **research preview** behind a separate access form: `outcomes`, `multi-agent`, and `memory`. [1]
- Rate limits: 60 req/min create; 600 req/min read/stream (per org). [1]
- Pricing: $0.08 per session-hour in addition to token costs. [1]
- Core concepts: Agent (model + system prompt + tools + MCP + skills), Environment (container template), Session (running agent instance), Events (user turns, tool results). [1]

### 1.2 `callable_agents` + `agent_toolset_20260401`

Verified against the Multiagent sessions page [2]:

- Delegation depth is **1 level**, verbatim: "Only one level of delegation is supported: the coordinator can call other agents, but those agents cannot call agents of their own."
- Shared filesystem, verbatim: "All agents share the same container and filesystem, but each agent runs in its own session **thread**, a context-isolated event stream with its own conversation history."
- Threads are **persistent**: a coordinator can re-call an earlier subagent and that thread retains prior turns.
- Declaration: `callable_agents: [{type: "agent", id: ..., version: ...}, ...]` at agent-create time. `agent_toolset_20260401` enables the prebuilt agent toolset (bash, file ops, web search, etc.).
- Routing subagent tool-use events: subagent-originated events carry a `session_thread_id`; echo it on the reply so the platform routes responses to the waiting thread.
- Multiagent = research preview; requires an additional beta header beyond `managed-agents-2026-04-01`.

### 1.3 Opus 4.7 constraints (Messages API)

All verified against the official "What's new in Claude Opus 4.7" page [3]:

- Model ID: `claude-opus-4-7`. 1M context, 128k max output.
- Rejected parameters (HTTP 400): `temperature`, `top_p`, `top_k` at any non-default value.
- `budget_tokens` removed: `thinking: {type: enabled, budget_tokens: N}` returns 400. Only `thinking: {type: adaptive}` accepted. Adaptive thinking is OFF by default.
- Thinking content omitted by default; opt back in with `"display": "summarized"`.
- Effort levels: `low | medium | high | xhigh | max`. `xhigh` is new in 4.7, sits between `high` and `max`, recommended starting point for coding/agentic work. Messages API only — Managed Agents handles effort automatically.
- Task budgets (beta): beta header `task-budgets-2026-03-13`. Advisory (not hard cap) token budget across the full agentic loop. Minimum 20k tokens. `output_config={"effort": "xhigh", "task_budget": {"type": "tokens", "total": N}}`.
- Tokenizer change: ~1.0x–1.35x as many tokens as 4.6; bump `max_tokens` headroom.
- Behavior: more literal instruction following, fewer tool calls by default, fewer subagents spawned by default, less "validation-forward" tone.

### 1.4 Agent Skills spec (canonical shape)

Verified against the Anthropic Agent Skills overview [4]:

Folder layout:
```
my-skill/
├── SKILL.md          (required)
├── REFERENCE.md      (optional additional instructions)
├── scripts/          (optional executable code)
└── <resources>       (templates, schemas, examples)
```

- Required YAML frontmatter: exactly two fields — `name` and `description`.
- `name`: lowercase letters/numbers/hyphens; max 64 chars; cannot contain "anthropic" or "claude".
- `description`: max 1024 chars, non-empty. Drives activation — must state both what the skill does and when Claude should use it.
- Three-level progressive disclosure: L1 metadata always loaded (~100 tok/skill), L2 SKILL.md body loaded on trigger (<5k tok), L3 bundled files loaded on demand via bash (effectively unlimited).
- Tool-use interaction: skills run in Claude's code-execution VM; Claude reads SKILL.md via bash, then reads any referenced file via bash. Scripts execute via bash and only output (not source) hits context.
- API prerequisites: three beta headers — `code-execution-2025-08-25`, `skills-2025-10-02`, `files-api-2025-04-14`.
- Skills are NOT covered by Zero Data Retention.

### 1.5 Hooks (Agent SDK)

From the canonical Agent SDK hooks page [5]:

- Python + TS shared events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PermissionRequest`, `Notification`.
- TypeScript-only events: `SessionStart`, `SessionEnd`, `Setup`, `TeammateIdle`, `TaskCompleted`, `ConfigChange`, `WorktreeCreate`, `WorktreeRemove`.
- Applicability: Agent SDK (both `@anthropic-ai/claude-agent-sdk` and `claude_agent_sdk`) — not Managed Agents. Managed Agents exposes analogous control via events and tool-confirmation responses, not hooks.
- Priority: `deny > ask > allow`. Multiple hooks execute in array order; any deny blocks regardless of others.
- Async mode: return `{async: true}` (TS) or `{"async_": True}` (Py) for side-effect hooks that don't block agent progression.
- `SessionStart` / `SessionEnd` are TS-only as SDK callbacks; in Python they exist only as shell-command hooks via `settings.json`.

### 1.6 The "verify its work" principle — canonical source

Verified verbatim from Claude Code best practices [6], under the heading "Give Claude a way to verify its work":

> "Include tests, screenshots, or expected outputs so Claude can check itself. This is the single highest-leverage thing you can do."
>
> "Claude performs dramatically better when it can verify its own work, like run tests, compare screenshots, and validate outputs."

The "trust-then-verify gap" failure pattern: "Claude produces a plausible-looking implementation that doesn't handle edge cases. Fix: Always provide verification (tests, scripts, screenshots). If you can't verify it, don't ship it." [6]

### 1.7 Healthcare-specific April 2026 posture

- "Claude for Healthcare" launched at JPMorgan Healthcare Conference 2026 — HIPAA-ready workflow software for health systems/payers, with new skills: FHIR data exchange, prior-auth review templates, clinical trial protocol drafting, bioinformatics. [7]
- Webinar 2026-04-23 — "Claude Code for Healthcare: How Physicians Build with AI" [8] — live demos, auditability + compliance + output-traceability discussion.
- Safety posture summary: human-in-the-loop required for safety-critical content; workflow-first (not chatbot); emphasis on role-based oversight and clearly-defined HITL gates. No GA "healthcare agent skill" SDK as of fetch-date; healthcare skill bundle appears gated to select partners.

---

## 2. ElevenLabs — Conversational AI build recipe

### 2.1 Platform overview

- Custom LLM docs: `/docs/eleven-agents/customization/llm/custom-llm` [9].
- Agents can be pointed at either ElevenLabs-hosted LLMs (default) or a custom OpenAI-compatible endpoint with your own credentials. Dashboard config drives model choice; local dev via tunneling (ngrok).
- Fallback LLM chain: Default / Custom / Disabled [10]. "Disabled" is discouraged for production.

### 2.2 SSE + endpoint shapes

Verified against custom-LLM docs [9]:

Two OpenAI-compatible endpoints accepted (either works):
1. Chat Completions: `POST /v1/chat/completions`
2. Responses API: `POST /v1/responses`

SSE requirements (both): `Content-Type: text/event-stream`. Stream must end with `data: [DONE]\n\n`.

- Chat Completions chunk format: `data: {json}\n\n`
- Responses API chunk format: `event: {type}\ndata: {json}\n\n`, with required types `response.output_text.delta` (streaming text) and `response.completed` (completion).
- Request fields accepted: `messages`, `model`, `stream`, optional `temperature`/`max_tokens`, and `tools` (OpenAI function-calling format) when system tools are configured.

### 2.3 Latency expectations

Primary source is thin on end-to-end p95 numbers; what's verified:

- Flash v2.5 TTS: ~75ms model inference for short inputs (representative benchmark, not a p95). [11]
- Network round-trip: 20-200ms typical (geographic). [11]
- Audio player buffer: 500ms common. [11]
- End-to-end p95 target: conversational-AI research threshold is <300ms for "natural-feeling" and <1s before feeling robotic. ElevenLabs markets "sub-second latency" for conversational AI [12]. An explicit p95 number for the full voice-round-trip is NOT documented on a primary page — unverified, needs follow-up.
- Buffer words strategy: documented for slow custom LLMs — return initial content ending in `"... "` (ellipsis + space) to keep TTS flowing while the LLM continues generating. [9]

### 2.4 Tool-calling direction

Verified [9]: direction is **ElevenLabs → Custom LLM** (server-side). System tools arrive in the request's `tools` array in OpenAI function-calling format. The custom LLM must emit function calls; ElevenLabs interprets returned function calls for built-in actions (`end_call`, `language_detection`, `transfer_to_agent`, etc.). April 2026 changelog adds per-workflow-node `tool_ids` and `knowledge_base` override scoping. [13]

### 2.5 Voice presets for clinical tone

- HIPAA/HDS certified, SOC2, GDPR, zero-retention mode, VPC deployment, E2E encryption. [14]
- 10,000+ preset voices. The vendor does not explicitly discourage voice cloning for healthcare; that restraint is a product decision. **Recommended approach for Prism**: use a preset voice (no cloning) — safer for BAA scope, no PHI-adjacent biometric concerns, matches the repo's healthcare-compliance posture even if not strictly required by the vendor.
- BAA availability: not explicitly named on the healthcare page; HIPAA certification is stated, BAA should be confirmed via sales. Marked **unverified — needs follow-up** before production PHI.

### 2.6 April 2026 product updates

From the 2026-04-07 changelog [13]:

- `conversation`- vs `agent`-scoped evaluation criteria in multi-agent workflows.
- Per-node `tool_ids` and `knowledge_base` overrides.
- `visited_agents[]` array on conversation retrieval.
- Multimodal message input: `sendMultimodalMessage` hook and `MultimodalMessageInput` export.
- New LLM providers: `gemini-3.1-pro-preview`, `qwen35-35b-a3b`, `qwen35-397b-a17b`.
- File input: images/PDFs can be attached in chat when agent LLM is multimodal.
- Voice recording quality enum: `studio`, `good`, `ok`, `poor`, `bad` on `get voice` response.

---

## 3. Integration pattern — Opus 4.7 behind ElevenLabs (Prism-specific)

### 3.1 Recommended endpoint shape

Use `POST /v1/chat/completions` (simpler than `/v1/responses`, widely-tested). Minimal shape: accept `{messages, model, stream, tools?}`; return SSE chunks `data: {openai-chunk-json}\n\n`; terminate with `data: [DONE]\n\n`. Host on any server Prism runs; expose via HTTPS (tunneling with ngrok for dev).

### 3.2 Streaming Opus 4.7 tokens through SSE

Use the Anthropic Python SDK `client.messages.stream(model="claude-opus-4-7", ...)` and translate each `content_block_delta` text event into one OpenAI chat completion chunk (`{"choices":[{"delta":{"content":"..."}}]}`). Opus 4.7 pitfalls: do not pass `temperature`/`top_p`/`top_k` (400); do not pass `thinking.budget_tokens` (400); if reasoning visible is desired set `thinking={"type":"adaptive","display":"summarized"}`, otherwise leave thinking off for fastest first-token. At voice latency budgets, thinking-off default is the right call.

### 3.3 Where safety preamble + retrieval hooks live

- Safety preamble: inject as the `system` field on every Anthropic call. Do NOT rely on an ElevenLabs-side system prompt alone — that gets forwarded but gives less control over non-negotiable clinical guardrails. Put the preamble in the translator layer (before the Opus call) so it's enforced server-side every turn.
- Retrieval: run before the Opus call in the translator. Pre-call augmentation: take `messages[-1].content`, retrieve, inject results as an additional `system` block or prepend to the user message. Keeping retrieval outside Skills avoids the code-execution-container activation cost and lets you use arbitrary vector stores.
- Post-processing: light text normalization only (strip markdown asterisks before TTS, expand medical abbreviations). No expensive post-processing — it burns the first-token-to-audio budget.

### 3.4 "Verify its work" for live voice turns

Apply the principle from [6] as async infrastructure, not live blocking:

1. **Async rubric grading**: after each turn, fire a background judge call (cheaper model, e.g. GPT-5.4-mini or Haiku) grading the response against a clinical rubric. Log failures for offline review; don't block TTS on this.
2. **Stopwatch telemetry**: timestamp STT-end, LLM-first-token, LLM-last-token, TTS-start, TTS-end. Log per-turn p95s; alert on regressions.
3. **Transcript replay harness**: replay recorded ElevenLabs conversation audio through the custom LLM offline; diff responses when changing preamble/retrieval. Load-bearing dev loop.
4. **Safety preamble regression test**: small fixture set of known-risky prompts that must refuse/disclaim. Run nightly in CI.

### 3.5 Pitfalls (last 30 days)

- Buffer-word gotcha: if streaming has gaps >400ms, the conversation feels broken. Docs-recommended fix: end a partial chunk with `"... "` [9]. Opus 4.7 adaptive thinking can stall first-token — consider thinking-off for voice.
- Tokenizer change: Opus 4.7 uses ~1.0-1.35x more tokens than 4.6 [3]. Bump `max_tokens` headroom in the translator.
- MCP tool scoping in April 2026: per-node `tool_ids` override means tool-inheritance defaults may not match older agent configs — re-verify subagent tool exposure after any workflow edit. [13]
- Multimodal message additions (Apr 2026): if file_input is enabled, the LLM must be multimodal-capable. Opus 4.7 is, but the router needs to pass image parts through. Test before submission.
- Voice cloning + healthcare: vendor permits it; for Prism's posture, stick with presets.

---

## 4. Citations (fetch-date 2026-04-21)

1. [Claude Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview) — beta header `managed-agents-2026-04-01`, rate limits, pricing, research-preview flags.
2. [Claude Managed Agents Multiagent sessions](https://platform.claude.com/docs/en/managed-agents/multi-agent) — `callable_agents` shape, 1-level delegation rule, shared container/filesystem, thread routing via `session_thread_id`.
3. [What's new in Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7) — model ID, rejected params, adaptive-thinking-only, `xhigh` effort, `task-budgets-2026-03-13` beta header, tokenizer change.
4. [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) — SKILL.md layout, frontmatter fields, progressive disclosure, required beta headers.
5. [Agent SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks) — hook event table, Python/TS parity, deny > ask > allow priority, async mode.
6. [Claude Code best practices](https://code.claude.com/docs/en/best-practices) — canonical source for "Give Claude a way to verify its work" verbatim.
7. [JPM26: Anthropic launches Claude for Healthcare](https://www.fiercehealthcare.com/ai-and-machine-learning/jpm26-anthropic-launches-claude-healthcare-targeting-health-systems-payers) — healthcare stack context (secondary source; primary landing at claude.com/solutions/healthcare).
8. [Claude Code for Healthcare webinar](https://www.anthropic.com/webinars/claude-code-in-healthcare-how-physicians-are-building-with-claude) — 2026-04-23 physician-build session.
9. [ElevenLabs Custom LLM integration](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm) — `/v1/chat/completions` + `/v1/responses` shapes, SSE format, `data: [DONE]` terminator, tool-calling direction, buffer words.
10. [ElevenLabs LLM models](https://elevenlabs.io/docs/eleven-agents/customization/llm) — backup LLM config.
11. [ElevenLabs latency concepts](https://elevenlabs.io/docs/eleven-api/concepts/latency) — 75ms Flash inference, 20-200ms network, 500ms player buffer.
12. [ElevenLabs healthcare page](https://elevenlabs.io/agents/conversational-ai-healthcare) — HIPAA/HDS certified, sub-second latency claim, deterministic workflow gating.
13. [ElevenLabs changelog 2026-04-07](https://elevenlabs.io/docs/changelog/2026/4/7) — April 2026 agent features (multimodal, workflow scoping, `visited_agents`, new LLM providers).
14. [ElevenLabs Conversational AI landing](https://elevenlabs.io/conversational-ai) — compliance marketing (HIPAA, SOC2, GDPR, VPC).

**Explicitly unverified / follow-up:**
- ElevenLabs p95 voice round-trip target (no primary-source number; rely on empirical stopwatch telemetry).
- BAA availability for ElevenLabs healthcare deployment (HIPAA certification stated; BAA not explicitly documented — confirm via sales before production PHI).
