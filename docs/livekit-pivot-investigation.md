# LiveKit pivot — investigation (2026-04-23)

**Status:** investigation, not executed. Companion to
`docs/deploy-prism42.md` (current ElevenLabs + Vercel stack) and the
concurrent B300 A/B-grader work on `main`. Decides whether and how
Prism42 should replace ElevenLabs with LiveKit for voice I/O and
migrate the live-agent runtime from Vercel serverless to a B300 GPU
pod.

TL;DR: **LiveKit is the better architectural fit** for Prism42's
stated goals (lowest latency, native tool calling, cross-vendor rubric,
self-verification loops, eventual self-hosted LLM). The pivot is
non-trivial but the existing scaffold does not need to be thrown away
— the Next.js app, session store, Zod schemas, coordinator prompt,
rubric grader, and GEDP protocol content all move across unchanged.
What changes is the **voice runtime**: `<elevenlabs-convai>` /
`@elevenlabs/react` on Vercel serverless → LiveKit Agents (Python)
worker on a B300 pod with a LiveKit React frontend in the existing
Next.js app.

---

## 1. Why LiveKit wins on Prism42's own criteria

| Criterion | ElevenLabs ConvAI (current) | LiveKit Agents |
|---|---|---|
| Latency (STT→LLM→TTS p95) | ~300-500 ms depending on TTS; flash v2.5 TTS 75 ms; extra hop through ElevenLabs cloud | Direct WebRTC; STT+LLM+TTS co-located on the B300 pod; semantic turn detection reduces false interruptions |
| Native tool calling | Must be wired via custom-LLM endpoint (our `/prism42/api/chat/completions` reconstitutes tool calls); no native concept of multi-agent handoff | `@function_tool` decorator; multi-agent handoff via tool return values; exactly matches our 14-agent topology |
| Self-verification / rubrics | Built-in evaluation criteria but shallow; rubric grading is bolted on via async OpenAI call | Built-in test framework with judges (v1.5.6, April 2026); judges are exactly `psap-auditor`'s shape |
| Observability | ElevenLabs Analysis tab + conversation history | Full LiveKit server logs + any OpenTelemetry exporter; we own the pipeline |
| Self-hosted LLM | Custom-LLM endpoint pattern only; model runs wherever our endpoint lives | Agent process + vLLM + LiveKit server all co-located on the B300 pod; zero per-call LLM cost |
| WebRTC control | Opaque (ElevenLabs owns the stack) | LiveKit's OSS server + SDKs; full control over codecs, TURN, data channels |
| BYO components | LLM only | STT (Deepgram / Whisper / Scribe), LLM (Opus / Llama / GPT), TTS (Cartesia / ElevenLabs Flash / OpenAI), VAD (Silero) |
| Video / multimodal | Voice only | Voice + video + screen-share (not a Phase-3 need but future-compatible) |
| Commercial track record | 4M agents, 40M users, 75% Fortune 500 | Used by OpenAI for ChatGPT Voice, Character.AI, Rabbit r1, many enterprise voice products |
| Ease of ship (shallow demo) | Days | 1–2 weeks for equivalent polish |
| Ease of ship (prism42-grade: tool calling, rubrics, self-host) | Weeks (fighting the framework) | 1–2 weeks (framework supports it natively) |

For a shallow "voice chat on a website" demo, ElevenLabs wins. For
Prism42's actual posture (14-agent tool topology, per-turn self-verify
gate, cross-vendor rubric grading, eventual self-hosted LLM, IRB-pilot
trajectory), **LiveKit is the match**.

Sources: [LiveKit Agents GitHub](https://github.com/livekit/agents) ·
[LiveKit docs](https://docs.livekit.io/agents/) ·
[ElevenLabs vs LiveKit comparison blog](https://elevenlabs.io/it/blog/elevenlabs-vs-livekit)
(ElevenLabs' own writeup; their conclusion: pick them for turnkey
simple voice, pick LiveKit for complex workflows + self-host).

---

## 2. Architecture — current vs. proposed

### Current (as of `ac10442`)

```
caller browser
      │  microphone → <elevenlabs-convai widget>  (or @elevenlabs/react)
      ▼
ElevenLabs cloud
      │  STT → LLM-custom (HTTP fetch) → TTS
      ▼
prism42-console.vercel.app
      /prism42/api/chat/completions (Node serverless)
      │  coordinator prompt → Anthropic Opus 4.7 → structured JSON
      │  Zod gate → OpenAI GPT-5.5 rubric (async)
      ▼
session-store (in-memory, per-instance)
      │  SSE fan-out
      ▼
dispatcher UI panels (transcript / rubric / alerts)
```

**Pain points observed in the live run:**
- The floating widget hijacks UX (marketing modal, "engage in
  meaningful conversations")
- Double cloud hop: caller → ElevenLabs → Vercel → Anthropic
- Serverless in-memory session store doesn't persist across instances
- Dashboard GUI preselects LLM; we work around via API (works, but
  fragile)
- Tool calling must be faked inside one coordinator prompt —
  `psap-safety-monitor`, `psap-ohca-detector`, `psap-intent-verifier`
  are documented as separate agents but run as workflow phases inside
  the single Opus call

### Proposed (LiveKit + B300)

```
caller browser
      │  LiveKit React SDK (@livekit/components-react)
      │  WebRTC ↔ Cloud or self-hosted LiveKit server
      ▼
LiveKit server   ← can be LiveKit Cloud (free ≤ 500 hr/mo) OR
                   self-hosted on the B300 pod (Docker, port 7880)
      │  routes room join + audio channels
      ▼
B300 GPU pod (Brev-provisioned H100/B300)
      │
      ├─ livekit-agents Python worker
      │     ├─ STT   → Deepgram nova-3 cloud (or self-hosted whisper)
      │     ├─ VAD   → Silero
      │     ├─ Turn  → LiveKit semantic-turn transformer
      │     ├─ LLM   → Anthropic Opus 4.7 cloud (Phase 3a)
      │     │         OR vLLM Llama-3-70B self-hosted on same pod
      │     │         (Phase 3b — matches the concurrent B300 A/B plan)
      │     ├─ Tools → @function_tool × 14 PSAP agents
      │     │         (handoff via multi-agent pattern)
      │     └─ TTS   → Cartesia Sonic-3 (primary)
      │               OR ElevenLabs Flash v2.5 (BAA path)
      │
      ├─ vLLM server on :8000  (optional; Phase 3b)
      │     serves Llama-3-70B for Opus-parity eval
      │
      └─ evidence writer
            │  publishes PsapTurn + RubricGrade via LiveKit data
            │  channels back to the frontend
            ▼
      frontend dispatcher panels (unchanged — just swap the data
      source from /api/session/:id/stream to livekit dataReceived)
```

### What stays the same

- `mvp/911-console-live/` — Next.js app, the shell, components
- `lib/types.ts` — `PsapTurn` / `RubricGrade` / `PsapAlert` schemas
- `lib/coordinator.ts` — `COORDINATOR_SYSTEM_PROMPT` + `TurnSchema`
  (used by the LiveKit LLM node as the system prompt)
- `lib/openai.ts` — cross-vendor rubric grader
- `agents/*.yaml` — 14 PSAP agent definitions
- `agents/psap-manifest.yaml` — Managed Agents IDs (still a valid
  backup for Phase 3a; the coordinator prompt is what actually
  drives behavior)
- `corpus/red-team/psap-fixtures-v0.1.yaml` — 42 scenarios
- `docs/dispatch-protocol-v0.1.md` — GEDP v0.1
- `docs/safety-preambles.md` — SP-001 through SP-010
- `schemas/psap-turn.schema.json`

### What goes away

- `<elevenlabs-convai>` widget
- `@elevenlabs/react` package
- `components/CallerWidget.tsx` (already deleted) + `CallerExperience.tsx`
  (replaced by LiveKit-based equivalent)
- `app/prism42/api/chat/completions/route.ts` (OpenAI-compat SSE) —
  unless we want to keep a headless HTTP path for smoke tests; can
  sunset post-pivot
- `agents/prism42-elevenlabs.yaml` + `agents/elevenlabs-manifest.yaml`
- `scripts/register_elevenlabs_agent.py`

### What's new

- `agents/livekit/worker.py` — LiveKit Agent worker (Python)
- `agents/livekit/tools.py` — `@function_tool` decorators for
  safety-monitor, ohca-detector, intent-verifier, dispatch-emit, etc.
- `agents/livekit/judges.py` — LiveKit judge implementations wrapping
  the existing rubric + psap-auditor
- `scripts/livekit_worker_service.sh` — runs the worker as a B300
  service (systemd unit or tmux session)
- `mvp/911-console-live/components/LiveCallRoom.tsx` — LiveKit React
  component replacing CallerExperience
- `mvp/911-console-live/app/prism42/api/livekit-token/route.ts` —
  mints short-lived LiveKit room tokens for the browser
- `.env` adds `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
  `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`

---

## 3. Mapping the 14-agent topology onto LiveKit

Two legitimate patterns, pick one:

### Pattern A — Single agent with 14 tools (recommended for Phase 3a)

```python
from livekit.agents import Agent, function_tool

class PSAPAgent(Agent):
    @function_tool
    async def run_safety_monitor(self, turn_text: str) -> dict:
        """Classify the current turn against 8 alert classes."""
        # ... call Opus with psap-safety-monitor YAML system prompt
        return {"alerts": [...]}

    @function_tool
    async def run_ohca_detector(self, transcript: str) -> dict:
        """Compute OHCA probability per GEDP §5.1.1."""
        # ... call Opus with psap-ohca-detector YAML system prompt
        return {"probability": 0.75, "signals": [...]}

    @function_tool
    async def emit_dispatch(self, determinant: str, units: list[str]) -> dict:
        """Lock the CAD + dispatch units."""
        return {"ok": True, "eta_seconds": 340}

    # ... 11 more tools
```

Advantages: simpler deploy, one conversation context, the tools are
just LLM functions. Maps cleanly to the existing coordinator prompt.

### Pattern B — Multi-agent handoff (Phase 3b goal)

```python
class IntakeAgent(Agent): ...
class TriageAgent(Agent): ...
class DispatchAgent(Agent): ...
class PDIAgent(Agent): ...
class HandoffAgent(Agent): ...

# Tools return other agents to hand off the mic:
@function_tool
async def transition_to_triage(self) -> TriageAgent:
    return TriageAgent(chat_ctx=self.chat_ctx)
```

Advantages: native implementation of the phase state machine we
already documented in `docs/agents/topology.md`. Each voice-facing
agent gets its own system prompt, so they can be prompt-engineered
independently without the giant coordinator prompt.

**Recommendation**: ship Pattern A in Phase 3a, migrate to Pattern B
in Phase 3b once the tool boundaries have been stress-tested against
the 42-scenario red team.

---

## 4. Phased migration plan

### Phase 3a — LiveKit POC alongside Vercel (2–3 days)

Don't demolish the Vercel deploy. Add a parallel path:

1. Set up LiveKit Cloud project (free tier). Get `LIVEKIT_URL`,
   `API_KEY`, `API_SECRET`. Add to `.env`.
2. Create `agents/livekit/worker.py` — single-agent Pattern A with 3
   core tools first (`intake_capture`, `safety_check`, `close_call`).
   Use Anthropic Opus 4.7 as the LLM (Managed Agents, matches current
   behavior). Deepgram Nova-3 for STT, Cartesia Sonic-3 for TTS.
3. Write the LiveKit token-mint endpoint at
   `mvp/911-console-live/app/prism42/api/livekit-token/route.ts`.
4. Add `mvp/911-console-live/components/LiveCallRoom.tsx` using
   `@livekit/components-react`.
5. Mount a new route: `/prism42/livekit` — same dispatcher panels,
   swapped caller component. Keep `/prism42` on ElevenLabs for A/B.
6. Run locally: `cd agents/livekit && uv run python worker.py dev`.
7. Smoke-test end-to-end from the browser.

**Deliverable**: two call buttons on the site, one ElevenLabs one
LiveKit. Side-by-side voice-latency comparison.

### Phase 3b — Move to B300 + self-hosted LLM (3–5 days)

1. Provision B300 pod via Brev (the concurrent session has already
   drafted the setup script + vLLM plan — reuse).
2. Install `livekit-agents` + plugins on the pod via `uv`.
3. Swap the worker's LLM backend from Anthropic Opus 4.7 →
   `openai.LLM(base_url="http://localhost:8000/v1", api_key="…")`
   pointing at the pod's vLLM serving Llama-3-70B.
4. Still use Cartesia / Deepgram (cloud) for TTS / STT — those are
   the fastest. Self-host only if a BAA path requires it.
5. Run the LiveKit server on the pod too (Docker image), so the
   entire pipeline is in one rack — eliminates cloud hop latency.
6. Add `/prism42/b300/live` as the pod-backed route. Compare against
   `/prism42/livekit` (cloud LLM) and `/prism42` (ElevenLabs).

**Deliverable**: three modes on one site. Evidence wall at
`/prism42-b300/compare` (the concurrent session's page) extended with
voice-latency + cost-per-call + rubric-delta columns.

### Phase 3c — Cut over (1–2 days)

1. Retire `<elevenlabs-convai>` widget + `@elevenlabs/react` from
   `/prism42` (or keep it as a "cloud only" benchmark row).
2. `/prism42` defaults to `/prism42/livekit` behavior (call LiveKit
   Cloud LLM — reliable uptime).
3. `/prism42/b300` is the "watch the self-host stack" showcase.
4. Delete `scripts/register_elevenlabs_agent.py` + ConvAI agent
   config (or keep them documented as the "week 1 path we shipped").

---

## 5. Concrete package + version pins

Python side (`pyproject.toml` under `agents/livekit/`):

```toml
[project]
name = "prism42-livekit-agent"
requires-python = ">=3.11"
dependencies = [
    "livekit-agents>=1.5.6",
    "livekit-plugins-openai>=0.14",     # for OpenAI + OpenAI-compat endpoints (vLLM)
    "livekit-plugins-anthropic>=0.14",
    "livekit-plugins-deepgram>=0.14",
    "livekit-plugins-cartesia>=0.14",
    "livekit-plugins-silero>=0.14",
    "livekit-plugins-turn-detector>=0.14",
    "pyyaml>=6.0",
    "anthropic>=0.97.0",
]
```

TypeScript side (adds to `mvp/911-console-live/package.json`):

```json
{
  "dependencies": {
    "@livekit/components-react": "^2.9.0",
    "@livekit/components-styles": "^1.2.0",
    "livekit-client": "^2.15.0",
    "livekit-server-sdk": "^2.13.0"
  }
}
```

Services / infra env (append to `.env`):

```bash
# -- LiveKit --
LIVEKIT_URL=wss://<your-project>.livekit.cloud   # or self-hosted wss://
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# -- STT/TTS --
DEEPGRAM_API_KEY=    # STT
CARTESIA_API_KEY=    # TTS
# ELEVENLABS_API_KEY stays (TTS fallback)

# -- Self-hosted LLM (Phase 3b) --
PRISM42_LLM_BASE_URL=http://localhost:8000/v1    # vLLM on the B300 pod
PRISM42_LLM_MODEL=meta-llama/Llama-3-70B-Instruct
```

---

## 6. Cost + latency back-of-envelope

### Cloud LLM path (Phase 3a)

- LiveKit Cloud: free ≤ 500 participant-hours/mo; beyond that $0.004/part-min
- Deepgram Nova-3: $0.0043/min streaming STT
- Cartesia Sonic-3: ~$30/M chars → ~$0.005 per 3-min call
- Anthropic Opus 4.7: ~$0.20 per 3-min call (3× current cost; we get
  Opus-grade not Llama)
- **Total per 3-min call**: ~$0.22 — dominated by the LLM

### Self-hosted LLM path (Phase 3b)

- LiveKit self-host: $0 marginal, just pod CPU
- Deepgram cloud: same ($0.013 per 3 min)
- Cartesia cloud: same ($0.005 per 3 min)
- vLLM Llama-3-70B on B300: $0 per call, amortizes B300 hourly cost.
  Per concurrent session's math: B300 $7.91/hr × 24/7 → 40 concurrent
  calls → **$0.0066/call**
- **Total per 3-min call**: ~$0.024 — 10× cheaper than Opus

### Latency

- Flash v2.5 TTS (current): 75 ms model inference
- Cartesia Sonic-3: ~100 ms
- Deepgram Nova-3 streaming STT: ~200 ms first partial
- LiveKit semantic turn detection: 100–200 ms post-utterance
- Network RTT (caller ↔ LiveKit edge ↔ B300): 40–80 ms each leg
- LLM inference: 400–800 ms for Opus; 200–400 ms for Llama-70B on
  vLLM (B300 decode per concurrent session measurements)
- **End-to-end p95 target**: 1.0–1.3 s per turn, consistent with
  ElevenLabs-class UX

---

## 7. Risks + open questions

### Risk: LiveKit Cloud free tier runs out

500 participant-hours/mo is ~40 calls/day at 3 min each. If prism42
demo traffic exceeds that, either upgrade ($29/mo Pro) or self-host.
Self-host is the Phase 3b default anyway; this risk is ceiling-only.

### Risk: LiveKit server on B300 — DNS + TLS

LiveKit WebRTC requires a trusted TLS cert for the `wss://` URL.
B300 pods are Brev-provisioned with ephemeral IPs. Need either:
- LiveKit Cloud (no self-host)
- Static IP + Let's Encrypt on a subdomain pointed at the pod
- Cloudflare Tunnel from the pod to a public domain

Easiest: use LiveKit Cloud for the demo; the B300 pod connects
OUTBOUND to LiveKit Cloud as a worker (no inbound TLS needed).

### Risk: Pattern A vs Pattern B prompt drift

If the single-agent Pattern A's system prompt diverges from the
14 YAMLs under `agents/`, we lose the per-agent clarity. Mitigation:
`scripts/check_prompt_sync.mjs` (the concurrent session already has
this) verifies the coordinator prompt embeds the YAML role
definitions verbatim.

### Risk: TTS provider drift

ElevenLabs Flash v2.5 sounds different from Cartesia Sonic-3. If
a stakeholder heard the ElevenLabs voice in a demo, switching could
feel regressive. Mitigation: use ElevenLabs Flash *as* the TTS
inside LiveKit — livekit-plugins-elevenlabs supports it. LiveKit is
agnostic; we don't have to drop ElevenLabs entirely.

### Open question: who writes the canonical system prompt?

Today: `lib/coordinator.ts` has it, and ElevenLabs-side prompt is
minimal. Tomorrow: the Python worker needs the same prompt. Two
approaches:
- Duplicate + `check_prompt_sync.mjs` enforces equality
- Single source of truth in `agents/coordinator-prompt.md` that both
  lib/coordinator.ts and agents/livekit/worker.py read at startup

Recommendation: single-source. Aligns with the concurrent session's
"Single-variable A/B discipline: same prompt, different serving
backend" invariant.

### Open question: where does the rubric grader live?

Today: `lib/openai.ts` on Vercel serverless; B300 variant in
`lib/rubric-local.ts` calling vLLM at :8000.

Tomorrow options:
- Keep it on Vercel (LiveKit agent calls the Vercel endpoint)
- Move it to the Python worker (one process, better latency)
- Keep both — use the same endpoint-shape contract either side

Recommendation: Python worker calls `openai.AsyncClient(base_url=
PRISM42_LLM_BASE_URL or openai_public_url)` — the same switch the
concurrent session's `lib/rubric-local.ts` was built for. That way,
the B300 A/B (Llama vs OpenAI rubric) still works under LiveKit.

---

## 8. Next concrete steps (if approved)

In order:

1. **Create the LiveKit Cloud project** (free tier). User does this
   in their LiveKit dashboard; I can't from the sandbox.
2. **Paste `LIVEKIT_URL` + `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET`
   into `/Users/kiteboard/prism42/.env`** — user does this.
3. **Scaffold `agents/livekit/`** — worker.py with Pattern A (3 core
   tools), token-mint endpoint, LiveCallRoom component. Ships behind
   `/prism42/livekit` route so the existing ElevenLabs path at
   `/prism42` is untouched. Verified locally with `uv run python
   worker.py dev`. I can do this.
4. **A/B smoke**: click `/prism42` (ElevenLabs), click `/prism42/
   livekit` (LiveKit Cloud + Opus 4.7 cloud LLM). Compare audibly.
5. **Integrate with B300** (after concurrent session's pod is back
   online): swap LLM `base_url` to the pod's vLLM.
6. **Cut over**: redirect `/prism42` to the LiveKit path, retire the
   ElevenLabs widget.

Budget for Phase 3a (coding only, no B300 yet): 2–3 days.
Budget for Phase 3b (B300 integration): +3–5 days.
Budget for Phase 3c (cut over + retirement): 1–2 days.

---

## 9. Recommendation

**Do the pivot.** Do it in phases; do NOT big-bang it. The 2026-04-23
scaffolding (Vercel + ElevenLabs) was useful prototyping and clarified
exactly which pieces of the architecture are load-bearing — the
coordinator prompt, the Zod gate, the rubric grader, the 14-agent
topology. Those all port to LiveKit cleanly. The voice stack below
the coordinator is the only thing that swaps.

Sources consulted 2026-04-23:

- [livekit/agents GitHub](https://github.com/livekit/agents)
- [livekit/agents-js GitHub](https://github.com/livekit/agents-js)
- [LiveKit Agents docs](https://docs.livekit.io/agents/)
- [LiveKit self-hosting](https://docs.livekit.io/home/self-hosting/deployment/)
- [ElevenLabs vs LiveKit comparison (ElevenLabs' blog)](https://elevenlabs.io/it/blog/elevenlabs-vs-livekit)
- [Hamming AI voice-agent stack comparison](https://hamming.ai/blog/best-voice-agent-stack)
- [p0stman ElevenLabs vs LiveKit vs Custom Build](https://p0stman.com/guides/voice-ai-platforms-elevenlabs-livekit-custom-comparison-2025.html)
- LiveKit Agents latest release 1.5.6 (April 2026) — native MCP
  support, semantic turn detection, builtin test framework with judges
