---
title: Claude API — control levers for adversarial-agent pipelines
date: 2026-04-22
scope: Every Messages-API, thinking, tool-use, Managed-Agents, Batch, MCP, files, and caching feature that is load-bearing for Prism's adversarial dialectic. PRISM-shape pseudocode; not importable — see `scripts/harness_runner.py` for the canonical path.
---

# Claude API control levers

## 1. The Messages API — first line

### `stop_reason` is a five-valued safety signal

Every Messages response returns `stop_reason`. The values carry distinct control semantics:

| Value | Meaning | Prism response |
|---|---|---|
| `end_turn` | Model finished normally | Proceed |
| `max_tokens` | Hit `max_tokens` cap | Inspect output, decide retry vs abort. In a PoC-generation step, treat as partial evidence only. |
| `stop_sequence` | Hit a caller-supplied stop sequence | Expected when the dialectic uses `[END_REASONING]`-style structural markers |
| `tool_use` | Model requested a tool | Validate against whitelist and schema **before** execution |
| `refusal` | Server-side safety classifier intervened | Do not retry unchanged. Log. For Prism: if a `defender` or `attacker` invocation refuses, a legitimate prompt has hit a classifier — inspect the prompt, not the classifier. |
| `pause_turn` | Server-tool iteration limit (default 10) | Continue by echoing `response.content` back as next message |
| `model_context_window_exceeded` | Hit the model's own context limit | Summarize/truncate input or abort |

*Source: Claude API, Handling Stop Reasons — https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons*

**For Prism specifically**: the `adjudicator` agent in particular has a clean control signal if it hits `refusal` on an adversarial input — the adjudicator itself is the canonical "trusted monitor," so classifier refusals on adjudicator prompts should escalate as a potential monitor-collusion indicator, not be silently routed around.

### `stop_sequences` as a structural boundary

`stop_sequences` (up to 4 per request) truncate generation at specific literal strings. Useful for structural enforcement inside the dialectic — e.g., the attacker agent emits `[END_ATTACK_PROPOSAL]` and the harness halts immediately, removing any tail that a drifting model might try to append. This is **cheap structural containment** and composes well with tool-use validation.

### Streaming for mid-generation inspection

SSE streaming surfaces `content_block_delta`, `content_block_start`, and `message_delta` events before the response completes. Two Prism-relevant uses:

1. **Mid-stream token-rate cap.** If the attacker agent produces more than N output tokens at a rate the harness did not budget for, the stream can be closed before the model finishes. This is independent from `max_tokens` (which is a hard upper bound but still allows single-step runaway up to that bound).

2. **Early `stop_reason` observation.** `message_delta` events expose the final `stop_reason` before `message_stop`. Prism's harness can branch on refusal / stop_sequence at the earliest possible point.

*Pattern (illustrative only — not for import; Prism's production path is `scripts/harness_runner.py`):*

```python
with client.messages.stream(
    model="claude-opus-4-7",
    max_tokens=4096,
    messages=[...],
) as stream:
    output_tokens = 0
    for event in stream:
        if event.type == "content_block_delta" and event.delta.type == "text_delta":
            output_tokens += len(event.delta.text.split())
            if output_tokens > threshold:
                # caller-side runaway cap
                raise RuntimeError("stream exceeded token budget")
        elif event.type == "message_delta":
            if event.delta.stop_reason == "refusal":
                # classifier intervened — escalate, do not retry
                return None
```

## 2. Extended thinking — auditable internal reasoning (with caveats)

### Thinking-block mechanics on Opus 4.7

Opus 4.7 thinking differs from 4.5/4.6 in ways Prism must respect:

- Opus 4.7 rejects `temperature`, `top_p`, `top_k`, and `budget_tokens`. Thinking is OFF by default; when on, it is *adaptive* rather than budget-controlled.
- Thinking blocks on 4.7 are cryptographically signed (signed-thinking is a platform-level feature). Prism can log the full signed blocks for post-hoc audit.
- Anthropic redacts thinking in responses when content violates specific internal policies (redacted thinking block). Prism should treat redaction as a signal, not an error.
- CoT faithfulness is low (Anthropic 2025: Claude 3.7 mentioned hints ~25% of the time). Thinking-block monitoring is **a useful but non-authoritative** signal. It composes well with behavioral monitoring (SHADE-Arena-style paired tasks) but should not be sole-source.

*Source: Extended Thinking — https://platform.claude.com/docs/en/build-with-claude/extended-thinking*

### For Prism specifically

The `attacker` agent is the one whose thinking is most diagnostic — it is the agent most likely to surface adversarial reasoning in CoT (by construction, it is supposed to be reasoning about how to break the defender's invariant). Capturing attacker thinking blocks is high-value audit data. For the `adjudicator`, thinking is load-bearing in a different way: the adjudicator's thinking is the audit trail for why a finding was confirmed or denied. Persist both.

## 3. Tool use — the largest attack surface

### `tool_choice` is the first knob

Four values: `"auto"` (model decides), `"none"` (disable all tools), `"any"` (must use a tool), `{"type": "tool", "name": "X"}` (force specific tool). Prism uses `"auto"` for most phases but should force specific tools for narrow-contract subagent calls.

### `strict: true` on tool schemas

Guarantees the model's tool input matches the declared JSON Schema exactly. Removes a class of schema-drift bugs. Cost: slightly more rigid behavior; the model may refuse to call a tool if it can't produce schema-compliant input. Net: worth it for every Prism tool.

### `allowed_callers` — capability containment

New-ish platform feature that restricts which server-side tools can invoke which other tools. Example: a destructive-filesystem tool can declare `"allowed_callers": ["code_execution_20260120"]` so it is reachable only from inside the code-execution sandbox, not by arbitrary model-initiated calls. This is the programmatic form of the principle-of-least-privilege. Prism's executor-on-SSM pattern should use `allowed_callers` whenever the tool wraps a side-effectful AWS or container action.

### Server-side tools (Anthropic-hosted)

- `web_search`, `web_fetch_20251103`, `code_execution_20260120`, `computer_20251124` (beta) run on Anthropic's infrastructure. Prism does not trust these for load-bearing kernel execution (wrong hardware) but they are useful for the defender's doc-lookup step.

### Client-side tools — where Prism does its real work

Prism's `executor` is a client-side tool. The pattern is: the model emits `stop_reason: "tool_use"`; the harness validates the tool call against:

1. Whitelist (is this tool allowed in this phase?)
2. Schema (does the input pass `strict:true` equivalent even on the caller side?)
3. Policy (e.g., no SSM SendCommand with `--document-name AWS-RunShellScript` containing a regex-blocked payload)
4. Rate/quota (per-session tool-call ceiling)
5. Sandbox invariants (if this tool is `run_poc`, the input script must be within `corpus/reproducers/` and must not import `socket`, `requests`, or `urllib`)

Only then does the harness execute the tool and feed the result back.

### Computer use — the highest-risk tool

`computer_20251124` (beta header `computer-use-2025-11-24`) lets Claude drive an X11 desktop. Prism does not use it and should not. If a future Prism rail does, the hard rules from Anthropic's docs apply:

- Dedicated VM / container with minimal privileges
- Never provide login credentials
- Allowlist egress domains
- Human confirmation for real-world consequences (financial, consent-based)
- Opt into prompt-injection classifiers (default on)

*Source: Tool Use, Computer Use — https://platform.claude.com/docs/en/agents-and-tools/tool-use/, https://platform.claude.com/docs/en/build-with-claude/computer-use*

## 4. Managed Agents — the Prism baseline

### Baseline vs multi-agent feature

Base Managed Agents is GA on the beta header `managed-agents-2026-04-01`. The multi-agent (`callable_agents`) feature is research-preview; **on Prism's current workspace it is silently stripped** from responses (verified 2026-04-22, `CLAUDE.md` §8). Request-id for support escalation: `req_011CaJg9qBnVqPNkaoBLgjrN`.

Operational consequence: Prism's five callable-agent architecture is **aspirational until that flag flips.** Current fallback: one coordinator Managed Agent using `agent_toolset_20260401`; defender/attacker/synthesizer/executor/adjudicator become workflow phases inside that single session. When multi-agent lands, `agents/manifest.yaml` and `scripts/register_agents.py` already have the symbolic `callable_agents` wiring — no harness-code change.

### Session events — the canonical stream

Real event names per docs:

- `session.thread_created`, `session.thread_idle`
- `agent.thread_message_sent`, `agent.thread_message_received`

Not real: `span.sub_agent_*`. Any code or doc referring to those is hallucinated.

### Session interrupt

`client.beta.agent_sessions.interrupt(session_id)` terminates a session mid-execution. Prism's PRISM-rate-limiter pattern (see `CLAUDE.md` §9 budget ceilings) can call this when token-burn-rate or session-duration exceeds a threshold.

### Agent pinning discipline

`CLAUDE.md` invariants (`scripts/pipeline_invariants.py`) enforce that agent IDs, role/filename alignment, egress rules, and mounts are pinned at registration time. This is Prism's answer to "the agent you tested is the agent you deployed."

*Source: Claude Managed Agents — https://platform.claude.com/docs/en/managed-agents/overview*

## 5. Prompt caching — constitutional persistence

`cache_control: {"type": "ephemeral"}` provides 5-min TTL caching; `{"type": "ephemeral", "ttl": "1h"}` extends to 1-hour at 2x storage cost. Cache reads cost 90% less than re-transmission.

**Minimum cacheable length (as of Apr 2026):** Opus 4.5/4.6/4.7 and Haiku 4.5: 4096 tokens; Sonnet 4.6: 2048 tokens; older: 1024 tokens.

For Prism: every agent has a stable, role-specific system prompt (see `agents/prism-*.yaml`). Those should be cached aggressively. The cache hit rate on system prompts is a direct observability signal — a drop in hit rate means something upstream changed the system prompt unexpectedly, which is an integrity signal worth alerting on.

Cache invalidation caveats:

- Any change in non-tool-result user content invalidates the cache for everything after it
- Tool definitions are included in the cache; changing tools invalidates
- Thinking blocks are cached automatically

*Source: Prompt Caching — https://platform.claude.com/docs/en/build-with-claude/prompt-caching*

## 6. Batch API — offline pre-deployment redteam

`POST /v1/messages/batches` — asynchronous, 50% cost reduction, most batches finish within 1 hour. For Prism:

- Pre-register-agents redteam: run every agent's system prompt against a held-out adversarial-prompt set before registering the agent to the workspace. Block registration if any prompt elicits `stop_reason: refusal` on a benign input or non-refusal on a known-harmful input.
- Corpus sweep: re-evaluate all `corpus/reproducers/` against a new model revision without paying full streaming cost.

*Source: Batch Processing — https://platform.claude.com/docs/en/build-with-claude/batch-processing*

## 7. MCP — ring-fenced tool providers

Prism does not currently use MCP servers (`CLAUDE.md` §8 *Credential vaults — deferred*). When it does — R2 PubMed retrieval for the clinical rail, H5 disclosure-packet automation — the relevant levers:

- **Stdio vs remote MCP.** Stdio servers run in subprocess; remote servers are HTTP. Remote adds network-isolation concerns. Prism should prefer stdio for anything that doesn't strictly need remote.
- **Tool namespacing.** MCP tools show up as `serverName.toolName` — the outer name is enforced, making a namespace-whitelist trivial.
- **Credential vaults.** Managed Agents vaults are session-bound, MCP-OAuth auto-refresh or static-bearer, write-only secret fields, up to 20 credentials per vault. Binding is `POST /v1/sessions { vault_ids: [...] }`. Do not pre-scaffold vaults — wire only when first MCP server actually lands.
- **Lifecycle.** MCP server starts with session, cleaned up on session end. Session-interrupt kills both.

*Source: MCP Connector — https://platform.claude.com/docs/en/agents-and-tools/mcp-connector; Vaults — https://platform.claude.com/docs/en/managed-agents/vaults*

## 8. Files API — immutable audit trail

`POST /v1/files` returns a `file_id` that can be referenced in multiple subsequent messages without re-upload. Files are de-duplicated server-side. For Prism: the natural fit is uploading a finished `findings/*.json` + executed PoC log as a pair of immutable file references inside the adjudicator's confirmation message — making the adjudicator's verdict unambiguously tied to the specific artifact. This is especially relevant if a finding ever goes into formal disclosure, where chain-of-custody matters.

## 9. Rate limiting — defense in depth

Organization-level rate limits (per-model tokens/minute, concurrent requests) are the last-mile backstop. Prism's application-level rate limiter should be stricter than the organization limit, with per-session and per-agent dimensions. The budget ceilings in `CLAUDE.md` §9 implement this at the business-logic layer.

Anthropic-supported escalation path: Admin API (`/v1/organizations/{org_id}/*`) for workspace spend caps and per-model rate limits; contact Anthropic support for custom organization-level policy.

## 10. Summary — the Prism control stack

| Layer | Mechanism | Failure mode caught |
|---|---|---|
| L0 constitutional | System prompt + cached | Baseline role drift |
| L1 structural | `stop_sequences` | Format-drift runaway |
| L2 budget | `max_tokens` + stream token-count | Per-turn runaway |
| L3 refusal | `stop_reason: refusal` + server classifiers | Known-harmful request |
| L4 tool-use gate | `tool_choice` + `strict` + caller-side whitelist + schema + policy + rate | Arbitrary tool abuse |
| L5 sandbox | `allowed_callers` + code_execution + MCP stdio | Side-effectful tool escape |
| L6 double-gate | `--commit` flag + `PRISM_*_COMMIT=1` env | Accidental billing / side-effect |
| L7 session interrupt | `client.beta.agent_sessions.interrupt` | Long-running runaway |
| L8 rate limit | Application-level + organization-level | Token-burn runaway |
| L9 audit | Files API + signed thinking + `findings/` logs | Forensic reconstruction |

Prism's current implementation covers L0-L6 robustly. L7 (session-interrupt) and L8 (application-level rate limiter) are the two layers that deserve attention if Prism lifts the double-gate or runs longer autonomous sessions post-hackathon.
