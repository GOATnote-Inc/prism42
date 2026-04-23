# mvp/911-console-live — Prism42 live PSAP console

A Next.js 15 app that wires the 14-agent PSAP stack to ElevenLabs
Conversational AI for public voice-call demonstrations at
`www.thegoatnote.com/prism42`.

This is the **live** sibling of `mvp/911-console/` (the static
single-file HTML demo). Both share the same GEDP v0.1 protocol
anchors and the same HealthBench-aligned rubric shape.

## What this app is

- **Next.js 15 app router**, TypeScript, React 19, Node runtime
  serverless functions.
- **OpenAI-compatible `/api/chat/completions`** that ElevenLabs
  Conversational AI calls in custom-LLM mode. Per
  [ElevenLabs' integration docs](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm)
  + the repo's blueprint at
  `docs/anthropic-elevenlabs-agent-bp-2026-04-21.md`.
- **Cross-vendor rubric grader** at `/api/rubric/grade` running
  `gpt-5-5` primary → `gpt-5-4` fallback → (Phase 2b)
  `claude-opus-4-7` shim. Prevents self-grading bias.
- **Dispatcher SSE stream** at `/api/session/:id/stream` feeding the
  `/prism42` console.

## Architecture

```
┌─ caller ─────────┐      ┌─ ElevenLabs Conversational AI ──┐
│  phone / widget  │ ───▶ │  STT · turn-taking · TTS        │
└──────────────────┘      └────────────┬────────────────────┘
                                       │ POST /v1/chat/completions
                                       ▼
             ┌──────────── mvp/911-console-live ──────────┐
             │                                            │
             │  /api/chat/completions    (OpenAI-compat)  │
             │    │                                       │
             │    ▼                                       │
             │  lib/coordinator.ts  (14-agent role        │
             │    │   prompt, structured-JSON schema)     │
             │    ▼                                       │
             │  lib/anthropic.ts    (claude-opus-4-7,     │
             │    │   Managed Agents or direct stream)    │
             │    ▼                                       │
             │  lib/session-store.ts   (records PsapTurn, │
             │    │   fans out to UI SSE subscribers)     │
             │    ▼                                       │
             │  /api/rubric/grade   (OpenAI GPT-5.5)      │
             │                                            │
             └────────────┬───────────────────────────────┘
                          │ /api/session/:id/stream
                          ▼
             ┌────────── /prism42 (dispatcher) ───────────┐
             │  transcript · alerts · rubric · phase      │
             └────────────────────────────────────────────┘
```

## File map

```
.
├── app/
│   ├── layout.tsx                      — root HTML + simulation banner
│   ├── globals.css                     — GOATnote dark console palette
│   ├── page.tsx                        — redirect to /prism42
│   └── prism42/
│       ├── page.tsx                    — dispatcher console shell
│       ├── safety/page.tsx             — SP-001-010 + IRB trajectory
│       ├── evidence/page.tsx           — 4-layer evidence dashboard
│       └── api/
│           ├── chat/completions/route.ts   — ElevenLabs custom-LLM SSE
│           ├── rubric/grade/route.ts       — cross-vendor rubric grader
│           └── session/
│               ├── start/route.ts          — mint a new session id
│               ├── [id]/stream/route.ts    — UI SSE subscription
│               └── [id]/end/route.ts       — close session, trigger auditor
├── components/
│   ├── DispatcherShell.tsx  — top-level layout + SSE subscriber
│   ├── PhaseTimeline.tsx    — phase pill strip
│   ├── Transcript.tsx       — live turn list
│   ├── RubricStrip.tsx      — per-turn rubric grades
│   └── AlertsPanel.tsx      — oversight-agent alerts
└── lib/
    ├── anthropic.ts         — SDK wrapper + beta headers
    ├── openai.ts            — rubric grader (GPT-5.5 → GPT-5.4)
    ├── coordinator.ts       — 14-agent system prompt + Zod schema
    ├── session-store.ts     — in-memory session registry + pub/sub
    ├── sse.ts               — SSE writer + OpenAI chunk helper
    └── types.ts             — TS projection of psap-turn schema
```

## Local dev

```bash
cd mvp/911-console-live
cp .env.example .env.local
# Edit .env.local with your ANTHROPIC_API_KEY + OPENAI_API_KEY

npm install
npm run typecheck
npm run dev
# App listens on http://localhost:3042/prism42
```

Smoke-test the chat endpoint without ElevenLabs (every route lives
under `/prism42/` — no `basePath`, the prefix is in the file tree):

```bash
curl -N -X POST http://localhost:3042/prism42/api/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"prism42-coordinator",
    "messages":[
      {"role":"user","content":"my husband just collapsed in the kitchen"}
    ],
    "stream":true,
    "user":"manual-test-session"
  }'
```

## Wiring ElevenLabs (Phase 2b)

1. Create an ElevenLabs Conversational AI agent at
   `elevenlabs.io/app/conversational-ai`.
2. LLM provider → **Custom LLM**.
3. Endpoint URL → `https://www.thegoatnote.com/prism42/api/chat/completions`.
4. Safety preamble → leave empty (we enforce server-side; see
   `lib/coordinator.ts` `COORDINATOR_SYSTEM_PROMPT`).
5. Voice → ElevenLabs preset (no cloning; matches the repo's
   healthcare-compliance posture).
6. Publish the agent on a widget URL or a hosted phone number.

The UI at `/prism42` auto-subscribes to the SSE stream — embed the
ElevenLabs widget on the same page and the dispatcher view updates
live as a visitor speaks to the agent.

## Deployment — Vercel

The `next.config.ts` basePath is set to `/prism42` so this app
mounts cleanly behind the `www.thegoatnote.com/prism42` edge-routing
rule. Env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`PRISM42_COORDINATOR_AGENT_ID`) are configured in the Vercel project
dashboard — never committed.

```bash
vercel link --cwd mvp/911-console-live
vercel env pull .env.local
vercel dev
# or
vercel deploy --prebuilt
```

## Phase 2a → 2b roadmap

Phase 2a (this commit) ships the scaffold:
- [x] OpenAI-compat custom-LLM endpoint
- [x] Coordinator system prompt (14 roles inline)
- [x] Structured-JSON Zod gate + safe fallback
- [x] In-memory session store + SSE fan-out
- [x] Dispatcher console + safety + evidence pages
- [x] Cross-vendor rubric grader (OpenAI primary + fallback)

Phase 2b will add:
- [ ] Opus 4.7 shim fallback (invokes psap-rubric-live-shim via
      Managed Agents on OpenAI grader chain exhaustion)
- [ ] Upstash Redis session store (replaces in-memory for
      multi-instance Vercel scale)
- [ ] ElevenLabs widget embedded in `/prism42`
- [ ] Cloudflare Turnstile + per-IP rate limits
- [ ] Post-session auditor trigger (psap-auditor + psap-qi-reviewer)
- [ ] Live evidence dashboard (reads findings/public-demo/*/verdict.json)
- [ ] Progressive JSON streaming (extract `content` field early to
      reduce perceived voice latency)

## Safety posture

Every voice-facing turn must pass a structured-JSON self-verify gate
before being streamed to ElevenLabs TTS. If the gate fails, the
caller hears `"One moment please."` — never a malformed or
unverified instruction. See `/prism42/safety` for the full SP-001
through SP-010 posture and the IRB trajectory.

Clinical direction: **Brandon Dent, MD** (emergency medicine) as
clinical director of GOATnote Inc. No physician-of-record liability;
the repo's public-facing attribution is "developed under direction of."

## License

MIT (see repo-root `LICENSE`). Contains no MPDS / IAED-licensed
content. Clinical protocol ground truth is GEDP v0.1 at
`docs/dispatch-protocol-v0.1.md` (MIT, GOATnote Inc.).
