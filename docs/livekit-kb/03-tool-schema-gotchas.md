# 03 — LiveKit + Anthropic tool-schema gotchas

Ops brief, compiled 2026-04-23. Scope: the exact 400 error

```
tools.0.custom: For 'object' type, 'additionalProperties: true' is not supported.
Please set 'additionalProperties' to false.
```

## 1. Incidence

The **exact** wording varies by Anthropic API revision, but the same
root failure is tracked across the livekit ecosystem in a small cluster
of threads:

| # | URL | Role |
| --- | --- | --- |
| livekit/agents **#5162** | https://github.com/livekit/agents/issues/5162 | Canonical feature request: "Support strict tool use for the Anthropic provider". Opened 2026-03-19, closed 2026-03-28. |
| livekit/agents **PR #5259** | https://github.com/livekit/agents/pull/5259 | The fix. `feat(anthropic): support strict tool use schema`. Merged 2026-03-28, commit `eb7bd4c112f1fce788f9ba56be965230ed5e1798`. |
| livekit/agents **PR #5324** | https://github.com/livekit/agents/pull/5324 | Follow-up: converts Pydantic `oneOf` to `anyOf` in strict schema. Merged 2026-04-03, commit `d81975a906c9e07dfe2e76e20b1c782743975ea8`. |
| livekit/agents **#4334** | https://github.com/livekit/agents/issues/4334 | Adjacent: Gemini rejects `$schema` / `additionalProperties` from MCP-sourced `RawFunctionTool`. Still **open** for Google provider; fix for Anthropic path implicit in #5259. |
| livekit/agents **PR #4732** | https://github.com/livekit/agents/pull/4732 | Pydantic upgrade started emitting `additionalProperties: true` by default (see https://github.com/pydantic/pydantic/pull/11392) — this is the upstream regression that made the Anthropic breakage visible. |
| BerriAI/litellm **#24121** | https://github.com/BerriAI/litellm/issues/24121 | Same error class at the proxy layer: `tools.0.custom.input_schema.type: Input should be 'object'`. Confirms it is not LiveKit-specific — any caller forwarding unsanitized Pydantic / MCP schemas to Anthropic trips it. |
| vercel/ai **#12020** | https://github.com/vercel/ai/issues/12020 | Vercel AI SDK v6 + Zod variant: `tools.0.custom.input_schema.type: Field required`. Same taxonomy. |
| anthropics/claude-code **#41827** | https://github.com/anthropics/claude-code/issues/41827 | `strict: true` from MCP tools not forwarded to the Anthropic API. Confirms Anthropic wants the `strict` flag explicit. |

I did **not** find a GitHub issue whose body literally contains
`additionalProperties: true is not supported`. That wording is the
Anthropic API error response; its appearance in bug reports is
paraphrased as `400`, `invalid_request_error`, or
`tools.0.custom.input_schema.*`. Do not let that fool you — #5162 and
PR #5259 are the authoritative thread.

No Stack Overflow or Reddit hits with that exact string in the last 90
days. The problem is young (Pydantic 2.10 + Anthropic strict-mode went
GA roughly concurrently in March 2026) and has so far lived on GitHub
and Discord.

## 2. Root-cause consensus

Two concurrent upstream changes collided:

1. **Pydantic ≥ 2.10** (`pydantic/pydantic#11392`) started emitting
   `additionalProperties: true` at the root of generated JSON schemas,
   matching the JSON-Schema default.
2. **Anthropic's Messages API tools endpoint**, with the `strict`
   tool-use feature now GA, **rejects** `additionalProperties: true`
   on `object` schemas. The API wants either `additionalProperties:
   false` (required for `strict: true`) or the key omitted entirely
   (for lax tools).

The livekit-plugins-anthropic ≤ 1.5.1 path ran tool schemas through
`build_legacy_openai_schema()` which did neither — it just forwarded
whatever Pydantic produced. So the moment a user's pinned
`pydantic>=2.10` took effect, every tool call 400'd. Maintainer
`@theomonnom` closed #5162 as completed by merging #5259.

## 3. Known fixes, newest first

### Code fixes merged to livekit/agents main

| Commit | Date | What |
| --- | --- | --- |
| `eb7bd4c` (PR #5259) | 2026-03-28 | Wire `_strict.py` (existing OpenAI infra) into the Anthropic provider. Calls `build_strict_openai_schema()`, which sets `additionalProperties: false` and promotes every field to `required`. Adds constructor param `_strict_tool_schema: bool = True` on `AnthropicLLM` for opt-out. |
| `d81975a` (PR #5324) | 2026-04-03 | Strict schema now converts Pydantic `oneOf` → `anyOf` (Anthropic / OpenAI strict reject `oneOf`). Bite you hit right after upgrading. |
| `477f820` (PR #5137) | 2026-03-18 | Strips empty `{}` entries from `anyOf`/`oneOf` in strict schema. |
| `016da5e` (PR #5082) | 2026-03-12 | Omits `required` when a tool has no parameters. |
| `80fe65e` (PR #5080) | 2026-03-11 | Includes `null` in enum arrays for nullable enums. |

### PyPI release map

| livekit-plugins-anthropic | PyPI upload | Contains PR #5259? |
| --- | --- | --- |
| 1.5.1 | 2026-03-23 | **NO** — breaks |
| **1.5.2** | **2026-04-08** | **YES — first good version** |
| 1.5.3 | 2026-04-15 | yes |
| 1.5.4 | 2026-04-16 | yes |
| 1.5.5 | 2026-04-20 | yes |
| **1.5.6** | **2026-04-22** | yes, latest; also includes #5324 oneOf→anyOf |

The monorepo pins `livekit-plugins-anthropic` to the same version as
`livekit-agents`, and `pyproject.toml` declares
`dependencies = ["livekit-agents>=1.5.6", "anthropic>=0.41", "httpx"]`
at HEAD — so pinning just the plugin works cleanly.

### Workarounds (for anyone stuck < 1.5.2)

Nothing posted publicly on Discord, Slack, Reddit, or X with the exact
error. The only practical workarounds:

1. Monkey-patch `build_legacy_openai_schema` to overwrite
   `additionalProperties: true` → `false` before send. Brittle.
2. Downgrade `pydantic<2.10`. Also brittle; conflicts with other
   deps.
3. Pre-sanitize every tool schema by hand (strip `$schema`, force
   `additionalProperties: false`).

Upgrading to 1.5.6 is strictly easier than any of these.

## 4. Anthropic strict-mode documentation

Yes, live at:

- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
  (canonical page; `docs.anthropic.com/en/docs/...` 301-redirects here
  since the `platform.claude.com` migration)

Key rules the docs now enforce (verified 2026-04-23):

- `strict: true` on a tool **requires** `additionalProperties: false`
  on every `object` in the schema.
- Max **20** strict tools per request.
- Max **24** optional parameters across all strict schemas in a
  request (anything not in `required` counts).
- Max **16** parameters using `anyOf` or union types (e.g.
  `"type": ["string", "null"]`) — these compile exponentially.
- Non-strict tools do **not** count against these limits.
- `oneOf`, `$ref`, `patternProperties`, `if/then/else`, `not` are
  rejected under strict mode.

The docs do not promise a clean error for the `additionalProperties:
true` case specifically; the 400 you see is literal validator output.

## 5. Related gotchas that will bite us next

Ordered by likelihood after fixing the `additionalProperties` 400:

1. **`oneOf` → 400.** Pydantic `Annotated[A | B, Field(discriminator=...)]`
   emits `oneOf`. Anthropic strict mode rejects it. Fixed by PR #5324,
   shipped in 1.5.6.
2. **`$schema` key → 400.** MCP-sourced tools include
   `"$schema": "http://json-schema.org/draft-07/schema#"` at the root.
   Handled for Anthropic via `_strict.py` sanitization, but the
   Gemini/Google provider still trips (#4334 open) — matters if we
   ever fall back to Gemini on this stack.
3. **20-strict-tool cap.** If we attach every 911 console tool with
   `strict=True` we will hit the cap. Mitigate by opting out non-
   critical tools via `AnthropicLLM(_strict_tool_schema=False, ...)`
   or by marking tools individually.
4. **24-optional-param cap.** 4 tools × 6 optionals = breach. Keep
   tool signatures flat.
5. **16 union-param cap.** Avoid `str | None` / enum-or-null; use
   `required` + sentinel values.
6. **`claude-code` #41827.** If we plumb MCP tools in, `strict: true`
   is not forwarded end-to-end — Anthropic-side bug, not ours, but
   worth tracking.
7. **Pydantic `additionalProperties: true` default** (pydantic/pydantic#11392).
   Any hand-rolled tool schema we build via `.model_json_schema()`
   outside the livekit strict path will reproduce the original bug.
   Always route through `_strict.py` or set
   `additionalProperties=False` manually.

## Recommendation

**UPGRADE `livekit-plugins-anthropic` to 1.5.6** (released
2026-04-22). 1.5.2 is the minimum-viable fix; 1.5.6 also includes
PR #5324 (`oneOf` → `anyOf`) and four other strict-schema hardening
commits you will need within days.

```bash
pip install --upgrade 'livekit-agents>=1.5.6' 'livekit-plugins-anthropic>=1.5.6'
```

If the environment has `pydantic<2.10` pinned for unrelated reasons
you may appear to "fix" the issue without upgrading — do not rely on
that. Anthropic's strict-mode validation will tighten further; the
plugin upgrade is the durable answer.

If we must ship on < 1.5.6 for some reason, the floor is 1.5.2
(commit `38f1d6960b` / PR #5391 release) and you accept the `oneOf`
trap.
