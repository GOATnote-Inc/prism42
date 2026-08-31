# LiveKit Knowledge Base — prism42 voice-agent operations

> Entry point for anyone (human or agent) debugging the prism42 voice
> runtime. Written 2026-04-24 after a multi-hour incident where the
> Anthropic Messages API rejected tool schemas generated from
> `@function_tool` signatures. Five parallel research agents converged
> on the same root cause; their deliverables live alongside this file.

## What's in here

| File | Owner | Summary |
|---|---|---|
| [`02-agents-sdk-anatomy.md`](./02-agents-sdk-anatomy.md) | Agent A | End-to-end call graph from `@function_tool` → strict schema walker → anthropic plugin → HTTP body. Exact file:line refs for the bug at `_strict.py:59-60` + five ordered fixes. |
| [`03-tool-schema-gotchas.md`](./03-tool-schema-gotchas.md) | Agent B | Community incidence + PR history. PR #5259 (livekit/agents, 2026-03-28) is the official fix, shipped in `livekit-plugins-anthropic 1.5.2` (2026-04-08). Related caps (20/24/16 strict tools). |
| [`04-deployment-patterns.md`](./04-deployment-patterns.md) | Agent D | 2026 production playbook: three-plane topology, SFU-won media, preemptive generation, tool-calling vendor matrix, failure modes + mitigations. 23 footnoted citations. |
| [`05-debugging-playbook.md`](./05-debugging-playbook.md) | Agent E | Live diagnosis recipes: `ANTHROPIC_LOG=debug`, offline body synthesis, httpx event-hook instrumentation, captured body excerpt with the exact key path Anthropic rejects. |
| [`07-repo-audit.md`](./07-repo-audit.md) | Agent C | Inventory of every `@function_tool` in our tree. Exactly ONE offending parameter across 8 tools. Risk + blast radius per fix. |
| [`07-proposed-code-fixes.diff`](./07-proposed-code-fixes.diff) | Agent C | Unified diffs for Strategy A (narrow Pydantic model) / Strategy B (drop param, read from SessionStore) / Strategy C (retire monkey-patch). |

## The incident in one paragraph

`dict[str, Any] | None` on the `last_specialist_turn` parameter of
`run_safety_monitor` in `specialists.py:98` caused Pydantic v2 to emit
`type: ["object", "null"], additionalProperties: true` in the derived
JSON schema. The livekit-agents strict-schema walker at `_strict.py:
59-60` only sets `additionalProperties: false` when the key is MISSING
— it left the explicit `true` alone. Anthropic Messages API (under
strict-mode tools, GA 2026) rejects any `type: object` schema whose
`additionalProperties` is not `false`. Result: `HTTP 400
tools.0.custom: additionalProperties: true is not supported`.

A monkey-patch in `worker.py` tried to fix this at `AsyncMessages.create`
kwargs-level, but its guard `node.get("type") == "object"` only matched
the string form; Pydantic emits the nullable-dict type as a LIST
(`["object", "null"]`), so the guard missed every nullable dict.

## The fix landed (2026-04-24)

Applied in three layers:

1. **Strategy B** — dropped `last_specialist_turn` from `run_safety_monitor`;
   the tool now reads the last turn from SessionStore internally.
   SessionStore was already source of truth — the parameter was
   redundant.
2. **Monkey-patch guard fix** — `worker.py`'s `_force_additional_properties_false`
   now matches both `type == "object"` AND `type: [..., "object", ...]`
   (list form). Defense-in-depth against future nullable-dict hints.
3. **(Deferred)** Upgrade `livekit-plugins-anthropic` to `>= 1.5.6` to
   pick up PR #5259 (strict-schema walker fix) + PR #5324 (oneOf→anyOf).
   Not yet applied — the local fixes above are sufficient for Phase A.

## Current runtime (2026-04-24)

- **Media plane**: LiveKit Cloud, project `ai therapy` → URL `wss://ai-therapy-v3svfd9o.livekit.cloud`, region Germany 2. Free tier: 5,000 participant-min/mo, 100 concurrent, 50 GB downstream.
- **Compute plane**: Python agent worker on Brev B300 pod `b300-pod`, at `/opt/prism42/agents/livekit/`. Outbound-WSS only — no inbound ports required (this is why we pivoted off self-hosted LiveKit server).
- **STT**: Parakeet TDT 0.6B v3 on pod `127.0.0.1:9100` (NeMo).
- **TTS**: Fish Speech S2-Pro on pod `127.0.0.1:9200` (custom FastAPI wrapping `tools/api_server.py`).
- **LLM**: Anthropic Opus 4.7 (orchestrator + voice-facing specialists), Sonnet 4.6 (parallel safety/ohca/intent evaluators).
- **Rubric**: OpenAI GPT-5.5 → GPT-5.4 → Opus shim (async, fail-quiet).
- **Session store**: Redis container on pod `127.0.0.1:6379`.
- **Cloudflare TURN key** `rapid-thunder-5758`: ready in `.env` for Phase B self-host return.
- **Dispatcher UI**: Next.js on Vercel at `https://prism42-console.vercel.app/prism42/livekit`.

## Verification

`bash scripts/verify_voice.sh` — 8-check harness. Phase A is done when
checks 1-4 PASS automatically + user-attestation checks 5-8 pass.

## Known gotchas to watch after Phase A

- **Strict-mode caps**: 20 strict tools per request / 24 optional params
  per tool / 16 anyOf per param. Our orchestrator has 8 tools — safe.
- **`oneOf` from Pydantic discriminated unions** → rejected under strict.
  Use `anyOf` instead (plugin 1.5.6 rewrites automatically).
- **`$schema` from MCP tools** → Anthropic-side handled, Gemini-side
  still open (issue #4334).
- **Brev firewall**: inbound UDP/7882 blocked at edge. Self-hosted
  LiveKit server on this pod will NEVER work without TURN. Cloudflare
  TURN is our Phase B path; key already minted.

## How to extend this KB

- If you patch the runtime, append a one-line entry to the "The fix
  landed" section above with a date + what changed.
- If you discover a new failure class, add a new numbered doc
  (e.g. `08-fishspeech-oom.md`) and link it in the table at top.
- Keep `04-deployment-patterns.md` updated when LiveKit or vendor
  docs change a cited number (latency, cap, default).

## Memory pointer

The user's auto-memory at `<owner-memory>/`
holds a pointer to this KB so future sessions find it without
re-discovering. See `livekit-kb-pointer.md` entry in `MEMORY.md`.
