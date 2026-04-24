# Prism42 LiveKit architecture (decision doc)

**Status:** committed; supersedes the ElevenLabs path for the live
voice runtime once Phase 3a smoke is green. Companion to
`livekit-pivot-investigation.md` (the why) and `deploy-prism42.md`
(the previous ElevenLabs runbook, kept for A/B).

This doc records architectural commitments. It is not exploratory.

---

## 1. Three patterns we adopt, mapped onto Prism42

We ground the architecture in three Anthropic engineering pieces
(fetched 2026-04-23):

- **Agent Teams** — `code.claude.com/docs/en/agent-teams`. Orchestrator
  + specialist teammates with shared task list, direct messaging, and
  scoped context windows. Distinct from subagents (which only report
  back to a parent).
- **Long-running app harness design** —
  `anthropic.com/engineering/harness-design-long-running-apps`.
  Generator/evaluator separation, sprint contracts, structured
  handoff artifacts, context-reset over compaction, evaluator loops,
  cost-aware iteration.
- **Agent Skills** —
  `anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills`.
  `SKILL.md` files with progressive disclosure: name+description in
  system prompt, full body on relevance, references on demand.

### Pattern → component map

| Pattern primitive | Prism42 incarnation |
|---|---|
| Agent Teams: orchestrator | `psap-team-coordinator` running inside the LiveKit voice loop |
| Agent Teams: voice-facing specialists | `intake / triage / dispatch / pdi / handoff` invoked via `@function_tool` (Pattern A) or LiveKit multi-agent handoff (Pattern B, Phase 3b) |
| Agent Teams: parallel evaluators | `safety-monitor / ohca-detector / intent-verifier` invoked concurrently per turn |
| Agent Teams: post-session evaluators | `auditor / qi-reviewer` triggered on session close |
| Harness: generator | The voice-facing specialist that emits the next caller-bound utterance |
| Harness: evaluator | `psap-rubric-live` (per-turn) + `psap-auditor` (per-session) |
| Harness: sprint contract | One per phase: intake / triage / dispatch / pdi / handoff. Codified in `agents/livekit/contracts/<phase>.yaml` |
| Harness: structured handoff artifact | `SessionState.brief` — JSON-shaped phase-summary the orchestrator hands to the next phase agent |
| Harness: context reset | At every phase transition, the new specialist receives the brief + current chief complaint, NOT the full turn history |
| Harness: persistent state | Redis-backed `SessionState` keyed by `session_id` — turns, phase, alerts, grades, brief. SSE-replayed to the dispatcher UI |
| Harness: ephemeral state | LiveKit's per-room `chat_ctx` (audio buffer, partial transcripts) |
| Harness: idempotent retry | Specialist tool calls return deterministic results given the same `(session_id, turn_id)` pair |
| Skills: SKILL.md frontmatter | One `SKILL.md` per voice-facing role + per chief-complaint cluster (e.g., `psap-pdi-cardiac.md`, `psap-pdi-choking-pediatric.md`) |
| Skills: progressive disclosure | Orchestrator system prompt loads only role names + descriptions; full body loads when the orchestrator's tool call references that skill |
| Skills: linked references | GEDP sections (`docs/dispatch-protocol-v0.1.md#§5.1`) loaded on-demand by the specialist that owns the phase |

### Why this matters concretely

Today the coordinator prompt is 6604 chars (verified with the local
sample run on chest-pain utterance). It embeds all 14 role
definitions inline because we couldn't reliably hand off.

After this restructure: orchestrator prompt drops to ~1500 chars
(role names + descriptions + sprint contracts). Each specialist
gets a focused 800–1200 char prompt loaded only when invoked.
Token cost per turn drops by ~3-4× and Opus 4.7 attention to
non-relevant rules (e.g., SP-008 988-redirect during a cardiac
arrest call) goes to zero.

---

## 2. Stack commitments (Phase 3a; what ships first)

| Layer | Choice | Why |
|---|---|---|
| WebRTC + voice runtime | **livekit-agents 1.5.6** (Python) | Native function-tool calling, builtin judge/test framework, semantic turn detection, multi-agent handoff |
| LiveKit server | **Self-hosted on B300 pod** (Docker, port 7880 + 7882/UDP) | Co-located with the agent worker → no cloud hop. Caddy fronts the WSS; UDP direct |
| TLS termination | **Caddy** (auto-TLS via Let's Encrypt) | One-line `livekit.thegoatnote.com { reverse_proxy 127.0.0.1:7880 }` config, auto-renewal, no NGINX cert management |
| DNS | `livekit.thegoatnote.com` A record → B300 pod public IP | Set via GoDaddy API (`infra/b300/setup-dns.sh`); GoDaddy is the registrar + DNS authority for thegoatnote.com |
| STT | **NVIDIA Parakeet** (self-hosted on B300, NeMo) | ~6× faster than accuracy-leader STTs; accuracy already above the practical ceiling for voice agents. Co-located on the pod, zero cloud hop. User decision 2026-04-23. |
| TTS | **Fish Speech S2 Pro** on SGLang (self-hosted on B300) | Beats ElevenLabs on 2 of 3 quality benchmarks; ~100 ms TTFA on H200, faster on B300. SGLang backend gives us kernel-co-design leverage. User decision 2026-04-23. |
| VAD | **Silero** | LiveKit standard; runs locally |
| Turn detection | **LiveKit semantic turn detector** | Transformer-based; reduces false interruptions vs raw VAD |
| Orchestrator LLM | **Anthropic Opus 4.7** (cloud, Phase 3a) | Existing Managed Agents environment; no migration needed for 3a |
| Specialist LLMs | **Anthropic Sonnet 4.6** for parallel oversight (safety/ohca/intent); **Opus 4.7** for voice-facing specialists | Cost-aware iteration: Sonnet 4.6 is 5× cheaper at near-Opus quality for narrow classification tasks |
| Rubric grader | **OpenAI GPT-5.5 → GPT-5.4 → Opus 4.7 shim** (unchanged) | Cross-vendor independence is structurally important; reuse `lib/openai.ts` |
| Session state | **Redis** (B300-local, Docker compose) | Long-running harness primitive — durable across worker restarts and process crashes |
| Frontend | **`@livekit/components-react`** + custom `LiveCallRoom.tsx` | The Orb + transcript components carry over; only the WebRTC layer swaps |
| Token minting | **`livekit-server-sdk`** in a Vercel serverless route | `app/prism42/api/livekit-token/route.ts` — short-lived JWT per session |

### What survives unchanged from the ElevenLabs scaffold

- All 14 `agents/*.yaml` (the source of truth for each role's prompt;
  during the migration we ALSO write `SKILL.md` versions but the
  YAMLs stay as the systemic contract — `prism-ci-safety-expert`
  reads them in CI)
- `lib/types.ts` (`PsapTurn` / `RubricGrade` / `PsapAlert` schemas)
- `lib/coordinator.ts` `TurnSchema` (the Zod gate; runs server-side
  in the Python worker now via Pydantic mirror)
- `lib/openai.ts` (cross-vendor rubric grader; Python port lives at
  `agents/livekit/grader.py`)
- `corpus/red-team/psap-fixtures-v0.1.yaml` (42 scenarios)
- `docs/dispatch-protocol-v0.1.md` (GEDP v0.1)
- `docs/safety-preambles.md` (SP-001-010, with the narrowed SP-001
  from commit `ac10442`)
- `mvp/911-console-live/components/Orb.tsx` (animated voice orb)
- `mvp/911-console-live/components/{Transcript,RubricStrip,AlertsPanel,PhaseTimeline}.tsx`
  (dispatcher panels)

---

## 3. Sprint contracts per phase

Per the harness blog: "Sprint contracts negotiate 'done' before
implementation begins." For a voice agent that means: each phase
has explicit success criteria the specialist must hit before the
orchestrator hands off to the next phase.

Codified at `agents/livekit/contracts/<phase>.yaml`. The
orchestrator reads the contract for the current phase, passes it
to the specialist as part of its tool-call args, and the
specialist's emitted turn must include `contract_satisfied: true`
in the structured JSON.

Example sketch — `agents/livekit/contracts/intake.yaml`:

```yaml
phase: intake
success_criteria:
  - id: address_captured
    description: scene address spoken back verbatim by dispatcher
    verify: address present in session.brief and read-back in any turn.content
  - id: chief_complaint_classified
    description: maps to one of GEDP §5.1-5.21 chief-complaint families
    verify: session.brief.chief_complaint_family is non-null
  - id: callback_number_captured
    description: 10 digits; can defer if caller is on the same line
    verify: session.brief.callback or session.brief.callback_deferred=true
hand_off_to: triage
hand_off_artifact:
  - chief_complaint_family
  - scene_address
  - callback_number
  - caller_state (panicked|coherent|distressed|hostile)
  - language_detected
```

The evaluator (rubric grader) checks contract satisfaction every
turn; if a phase is "done" by the contract, the orchestrator
transitions; if not done after N turns, the orchestrator escalates
(per SP-007 session budget).

---

## 4. Failure modes + recovery (harness pattern)

| Failure | Detection | Recovery |
|---|---|---|
| Anthropic API 5xx on specialist call | Try/except in `@function_tool` body | 1 retry with 250 ms backoff; on second failure fall back to Sonnet 4.6 (cost-aware degradation) |
| Anthropic API rate-limit | 429 response | Queue + backoff up to 2 s; if still failing, emit safe fallback "One moment please" + verify-failed alert |
| LLM returns malformed JSON | Pydantic `model_validate` raises | Lenient parse: extract `content` string field if present (mirrors `tryParseTurn` from `lib/coordinator.ts` ac10442) |
| LLM returns valid JSON but contract not satisfied | `contract_satisfied: false` in turn | Orchestrator stays in current phase; re-invokes specialist with feedback "criterion X still unmet" up to 3 turns; then escalates |
| STT drops a word (low confidence partial) | Parakeet confidence < 0.6 | Specialist asks for repeat ("could you say that again, you broke up") |
| Caller goes silent ≥ 5 s | LiveKit semantic turn detector | Specialist prompts ("are you still there?") |
| WebRTC disconnect mid-call | LiveKit room event | SessionState persisted; reconnect within 30 s resumes from same brief; longer triggers post-session auditor with "incomplete-call" tag |
| Worker process restart | Systemd auto-restart | Redis-backed SessionState survives; in-flight turns are lost, current phase + brief are not |
| Rubric grader (OpenAI) full chain exhausted | `OpenAIGraderUnavailable` | Phase 3b: Opus 4.7 shim with `self_grade_flag` per `agents/psap-rubric-live-shim.yaml` |
| Orchestrator emits explicit-emergency refusal (SP-001) | `action: refuse, sp_reference: SP-001` | Specialist speaks the SP-001 content; orchestrator transitions to `closed` phase; auditor runs |

---

## 5. Observability — what gets logged

Per the harness blog: "Sprint contract negotiations and agreements,
specific bug findings with code locations, iteration counts and
scoring trends, token costs per agent phase."

Every turn writes a `turn_log` JSON line to
`/var/log/prism42/turns/<session_id>.jsonl` on the B300 pod
(structured, append-only, durable):

```json
{
  "ts_ms": 1776990129,
  "session_id": "abc-...",
  "turn_id": "t-abc-3",
  "phase": "triage",
  "specialist": "psap-triage",
  "caller_text": "...",
  "specialist_input_tokens": 1840,
  "specialist_output_tokens": 220,
  "specialist_latency_ms": 690,
  "tts_latency_ms": 110,
  "turn_self_verify": {"all_passed": true, "checks": [...]},
  "rubric_grade": {"weighted": 0.86, "model": "gpt-5-5", "latency_ms": 1850},
  "alerts": []
}
```

Per-session aggregate written at session close to
`/var/log/prism42/sessions/<session_id>.json`:

```json
{
  "session_id": "abc-...",
  "duration_s": 184,
  "phases_visited": ["intake", "triage", "dispatch", "pdi", "handoff"],
  "turns": 14,
  "weighted_score_mean": 0.81,
  "alerts_by_severity": {"medium": 2, "high": 0, "critical": 0},
  "auditor_verdict": "confirmed-green",
  "physician_review_required": false,
  "cost_usd": 0.18
}
```

These get rsynced to the prism42 repo's `findings/public-demo/`
nightly via cron (already gitignored except for the manifest).

The dispatcher UI gets the same data live via LiveKit data channels
(replaces the SSE stream that exists in the ElevenLabs path).

---

## 6. Topology diagram

```
                              caller browser
                                    │
                                    │  LiveKit React SDK
                                    │  WebRTC over wss://livekit.thegoatnote.com
                                    ▼
                            ┌───────────────────┐
                            │   Caddy (auto TLS)│   ← Let's Encrypt
                            │   port 443        │
                            └────────┬──────────┘
                                     │
                                     │  proxy → 127.0.0.1:7880
                                     ▼
                            ┌───────────────────┐
                            │   LiveKit server  │
                            │   :7880 (signal)  │   :7882/UDP for media
                            │   (Docker)        │
                            └────────┬──────────┘
                                     │  agent dispatch
                                     ▼
                B300 GPU pod ┌───────────────────────────────────┐
                             │                                   │
                             │  livekit-agents Python worker     │
                             │  (systemd, auto-restart)          │
                             │                                   │
                             │  AgentSession                     │
                             │  ├─ vad   = silero.VAD            │
                             │  ├─ stt   = ParakeetSTT           │
                             │  │         → http://127.0.0.1:9100│
                             │  ├─ llm   = anthropic.LLM(opus-4-7)│
                             │  │         or vLLM Llama-3-70B    │
                             │  │         (Phase 3b swap)        │
                             │  ├─ tts   = FishSpeechTTS         │
                             │  │         → http://127.0.0.1:9200│
                             │  └─ turn  = livekit.semantic-turn │
                             │                                   │
                             │  Agent (orchestrator):            │
                             │  ├─ psap-team-coordinator         │
                             │  ├─ tools[]:                      │
                             │  │  ├─ run_safety_monitor (Sonnet)│
                             │  │  ├─ run_ohca_detector  (Sonnet)│
                             │  │  ├─ run_intent_verifier(Sonnet)│
                             │  │  ├─ specialist_intake  (Opus)  │
                             │  │  ├─ specialist_triage  (Opus)  │
                             │  │  ├─ specialist_dispatch(Opus)  │
                             │  │  ├─ specialist_pdi     (Opus)  │
                             │  │  └─ specialist_handoff (Opus)  │
                             │  └─ contracts: dict[phase, yaml]  │
                             │                                   │
                             │  ┌───────────────┐                │
                             │  │ Redis :6379   │ ← SessionState │
                             │  │ (Docker)      │   durability   │
                             │  └───────────────┘                │
                             │                                   │
                             │  ┌───────────────┐                │
                             │  │ vLLM :8000    │ ← Phase 3b     │
                             │  │ Llama-3-70B   │   self-host    │
                             │  │ (optional)    │   LLM swap-in  │
                             │  └───────────────┘                │
                             │                                   │
                             └───────────────────────────────────┘

Cloud services (no inbound):
  - Anthropic API     (Opus 4.7 + Sonnet 4.6 — Phase 3a)
  - OpenAI API        (GPT-5.5/5.4 rubric grader)

Everything else runs on the pod. STT (Parakeet) and TTS (Fish Speech
S2 Pro) are self-hosted from day one — "commercial APIs still win on
pure latency and ops maturity; we trade that for full control of the
stack and the ability to co-design kernels end-to-end" (user
decision 2026-04-23).
```

---

## 6.1 Brev firewall reality check (discovered 2026-04-23)

Empirical test from the workstation to pod `31.22.104.100` (prism-mla-
b300-h4h5):

| Port | TCP | UDP |
|---|---|---|
| 22 (SSH) | OPEN | n/a |
| 80 | closed/filtered | — |
| 443 | closed/filtered | — |
| 7880 | closed/filtered | — |
| 7882 | closed/filtered | **OPEN** |

Brev's outer firewall (unreachable via `ufw`) blocks inbound TCP on
arbitrary ports. Their dashboard literally says "This cloud provider
doesn't allow the modifications of ports." UDP/7882 is open — which
is lucky, because that's where WebRTC media lives.

**Implication for the TLS plan:** Caddy terminating TLS on
`livekit.thegoatnote.com:443` on the pod itself DOESN'T work —
:443 is blocked at the Brev edge. Three workable paths:

1. **Phase 3a path (ship-ready today): Brev Shareable URL for WSS
   signaling; direct UDP for media.** User shares port 7880 in the
   Brev dashboard → gets a `https://livekit-bvtyxg31j.brevlab.com`
   URL with a valid `*.brevlab.com` cert. Set
   `NEXT_PUBLIC_LIVEKIT_URL=wss://livekit-bvtyxg31j.brevlab.com`.
   WebRTC media uses UDP/7882 direct to the pod IP — that port we
   verified reachable. Caddy is NOT deployed for Phase 3a.
2. **Phase 3c path: Cloudflare in front of Brev.** `livekit.thegoatnote
   .com` CNAME → Cloudflare → origin = `livekit-bvtyxg31j.brevlab.com`.
   Cloudflare rewrites the Host header + serves a matching cert.
   Gets us the branded domain back. Requires moving DNS for
   `thegoatnote.com` (or at least the `livekit` subdomain) to
   Cloudflare, which is a user decision.
3. **Fallback: LiveKit Cloud.** Only outbound from the pod; no
   firewall fight. User rejected this in the arch doc ("self-host
   from day 1"); listed here for completeness in case Brev's
   constraint sticks.

Phase 3a ships option 1. The setup.sh + Caddyfile + GoDaddy DNS
automation from §7 becomes Phase 3c work.

## 7. DNS plan (deferred to Phase 3c)

`thegoatnote.com` is registered with GoDaddy and uses GoDaddy DNS
(corrected from earlier assumption of Vercel DNS — Vercel only hosts
`prism42-console.vercel.app` content, the apex domain is on GoDaddy).

**Automation:** `infra/b300/setup-dns.sh` calls GoDaddy's REST API to
PUT the A record. Idempotent — re-run safely. Requires the user's
GoDaddy production API key + secret in `.env`:

```bash
GODADDY_API_KEY=...        # https://developer.godaddy.com/keys
GODADDY_API_SECRET=...
```

**Run once at pod provisioning:**

```bash
set -a && source /Users/kiteboard/prism42/.env && set +a
POD_PUBLIC_IP=$(ssh prism42-pod 'curl -s ifconfig.me') \
  bash infra/b300/setup-dns.sh
```

This PUTs `livekit.thegoatnote.com  A  <pod-ip>  TTL 600`. After DNS
propagation (~60-300 s), Caddy on the pod auto-provisions a Let's
Encrypt cert on first request to `https://livekit.thegoatnote.com`.

**Verification:**

```bash
dig +short livekit.thegoatnote.com
# expect: <pod-ip>

curl -sI https://livekit.thegoatnote.com/health
# expect: HTTP/2 200
```

---

## 8. What "ships" in Phase 3a (the next-turn deliverable)

Concrete artifacts landing in this PR:

1. `docs/livekit-architecture.md` (this file) — decisions
2. `agents/livekit/pyproject.toml` — Python deps pinned
3. `agents/livekit/worker.py` — entry point + AgentSession boot
4. `agents/livekit/orchestrator.py` — `PsapOrchestrator(Agent)` with
   contract loading + tool catalog
5. `agents/livekit/specialists.py` — `@function_tool` for
   safety_monitor, ohca_detector, intent_verifier (Sonnet 4.6) +
   intake, triage (Opus 4.7) — 5 of 14, pattern shown
6. `agents/livekit/state.py` — Redis-backed `SessionState` +
   structured handoff brief
7. `agents/livekit/grader.py` — Python port of `lib/openai.ts`
   cross-vendor rubric grader
8. `agents/livekit/contracts/{intake,triage,dispatch,pdi,handoff}.yaml`
   — 5 phase-sprint contracts
9. `infra/b300/Caddyfile` — auto-TLS reverse proxy
10. `infra/b300/livekit.yaml` — single-port-ICE LiveKit server config
11. `infra/b300/docker-compose.yml` — LiveKit server + Redis
12. `infra/b300/setup.sh` — pod bootstrap (apt install caddy, pull
    docker images, install uv + python deps, install systemd unit)
13. `infra/b300/prism42-agent.service` — systemd unit for the worker
14. `mvp/911-console-live/components/LiveCallRoom.tsx` — frontend
15. `mvp/911-console-live/app/prism42/livekit/page.tsx` — new route
16. `mvp/911-console-live/app/prism42/api/livekit-token/route.ts` —
    short-lived JWT mint
17. `.env.example` — new env vars

What's deferred to a follow-on PR:

- Migration of all 14 YAMLs to SKILL.md format with progressive
  disclosure (skills directory restructure)
- LiveKit data-channel bridge to dispatcher panels (Phase 3a uses
  the existing SSE stream; Phase 3b moves to LiveKit channels)
- vLLM Llama-3-70B integration on the B300 pod (Phase 3b)
- Cut-over to remove ElevenLabs path entirely (Phase 3c)
- Multi-agent handoff via Pattern B (LiveKit `Agent` return values
  from tools) — Pattern A first

---

## 9. Decisions that are NOT up for further negotiation

These are committed; revisit only if a specific failure forces it:

1. **LiveKit, not ElevenLabs** for the Phase 3a+ voice runtime.
2. **Self-host LiveKit on the B300 pod** from day 1 (not LiveKit Cloud).
3. **Caddy** for TLS termination (not NGINX, not Traefik).
4. **Fish Speech S2 Pro on SGLang (self-hosted)** for TTS. NOT
   Cartesia, NOT ElevenLabs Flash, NOT OpenAI TTS. The A/B
   comparison table for the evidence wall keeps Cartesia and
   ElevenLabs as cloud-latency benchmarks but the live path serves
   from the pod.
5. **NVIDIA Parakeet via NeMo (self-hosted)** for STT. NOT Deepgram,
   NOT Whisper. Accuracy is above the practical ceiling for voice
   agents; ~6× faster than the accuracy leaders.
6. **Pattern A** (single orchestrator + 14 `@function_tool`
   specialists) for Phase 3a; Pattern B (multi-agent handoff via
   LiveKit `Agent` return) for Phase 3b once Pattern A's tool
   boundaries are stress-tested.
7. **Sonnet 4.6 for parallel oversight** specialists; Opus 4.7
   for voice-facing specialists.
8. **Redis** for session-state durability (not Postgres, not
   in-memory; Phase 3c may reconsider for full audit trail).
9. **JWT-via-Vercel-serverless** for the token mint (the only piece
   of the runtime that stays on Vercel; the rest moves to the B300
   pod).
10. **`/prism42`** stays the primary visitor URL; Phase 3a adds
    `/prism42/livekit` alongside; Phase 3c collapses them so
    `/prism42` IS the LiveKit path.

---

## 10. The promise this architecture is making

If we ship Phase 3a per the artifact list above and connect it to
the B300 pod, prism42 becomes the **architectural showcase** the
project's thesis claims — a 14-specialist clinical voice agent
running native function-tool calling, cross-vendor evaluation, sprint
contracts per phase, durable session state, and self-host on a
Blackwell GPU. None of those primitives is bolted on; each is a
first-class element of the LiveKit + Anthropic + harness pattern
combination.

Sources consulted 2026-04-23:

- [LiveKit Agents (Python)](https://github.com/livekit/agents)
- [LiveKit Agents-JS](https://github.com/livekit/agents-js)
- [LiveKit Agents docs](https://docs.livekit.io/agents/)
- [LiveKit self-hosting](https://docs.livekit.io/home/self-hosting/deployment/)
- [Claude Code: agent teams](https://code.claude.com/docs/en/agent-teams)
- [Anthropic engineering: harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic engineering: equipping agents for the real world with skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Caddy auto-TLS](https://caddyserver.com/docs/automatic-https)
- [Vercel CLI dns](https://vercel.com/docs/cli/dns)
