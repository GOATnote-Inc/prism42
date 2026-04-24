# prism42 LiveKit agent worker

Self-hosted voice-agent runtime for `prism42`. Replaces the
ElevenLabs ConvAI + Vercel-serverless path. Deploys on a single
B300 GPU pod alongside Caddy (auto-TLS) and a self-hosted LiveKit
server.

See `docs/livekit-architecture.md` for the architectural decisions
(why LiveKit, why Cartesia, why agent-teams pattern, etc.).

## Modules

```
agents/livekit/
├── pyproject.toml           — pinned deps (livekit-agents 1.5.6)
├── README.md                — this file
├── worker.py                — entry: AgentSession + room dispatch
├── orchestrator.py          — psap-team-coordinator (always-on)
├── specialists.py           — @function_tool × 14 PSAP roles
├── state.py                 — Redis-backed SessionState + brief
├── grader.py                — cross-vendor rubric (Python port)
├── prompts.py               — load + render prompt skeletons
├── contracts/               — sprint contracts per phase
│   ├── intake.yaml
│   ├── triage.yaml
│   ├── dispatch.yaml
│   ├── pdi.yaml
│   └── handoff.yaml
└── tests/
    └── test_smoke.py        — minimal POC test
```

## Local dev

```bash
cd agents/livekit
uv sync                               # install deps from pyproject.toml
cp ../../.env .env                    # repo .env carries the keys
uv run python worker.py dev           # console-mode, hot reload
```

In dev mode the worker connects to the LiveKit Cloud free tier OR
your local self-hosted LiveKit (configured by `LIVEKIT_URL`).
Phase 3a defaults to self-hosted on the B300 pod.

## Production (B300 pod)

Provisioned by `infra/b300/setup.sh`. Runs as a systemd unit
`prism42-agent.service` on the pod. Logs to `/var/log/prism42/`.
Auto-restart on crash; Redis-backed state survives restarts.

## Verifying

```bash
uv run python -m pytest tests/        # smoke
uv run python worker.py console       # console mode (text input)
```

## Stack

| Layer | Choice |
|---|---|
| Framework | livekit-agents 1.5.6 (Python) |
| WebRTC | LiveKit (self-host, port 7880 + 7882/UDP) |
| TLS | Caddy (auto-TLS via Let's Encrypt) |
| STT | Deepgram Nova-3 |
| TTS | Cartesia Sonic-3 |
| VAD | Silero |
| Turn detection | LiveKit semantic-turn (transformer) |
| Orchestrator LLM | Anthropic Opus 4.7 |
| Specialist LLM (oversight) | Anthropic Sonnet 4.6 |
| Specialist LLM (voice-facing) | Anthropic Opus 4.7 |
| Rubric grader | OpenAI GPT-5.5 → GPT-5.4 → Opus 4.7 shim |
| Session state | Redis (B300-local, Docker) |
