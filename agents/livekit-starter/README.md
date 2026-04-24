# Prism42 LiveKit STARTER worker

Escape-hatch reference implementation. Mirrors `livekit-examples/agent-starter-python` (direct plugin variant) so we have a known-good cloud-vendor path to A/B against the custom Parakeet+Fish+Opus-4.7-orchestrator stack at `/opt/prism42/agents/livekit/`.

## Stack
- STT: Deepgram Nova-3
- LLM: Anthropic Claude Opus 4.7
- TTS: Cartesia Sonic-3 (voice `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`)
- VAD: Silero
- One trivial `health_check` tool

## Required env
```
LIVEKIT_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET
ANTHROPIC_API_KEY
DEEPGRAM_API_KEY
CARTESIA_API_KEY
```

## On the pod

```bash
cd /opt/prism42/agents/livekit-starter
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install \
  'livekit-agents>=1.5.6,<2' \
  'livekit-plugins-anthropic>=1.5.6' \
  'livekit-plugins-deepgram>=1.5.6' \
  'livekit-plugins-cartesia>=1.5.6' \
  'livekit-plugins-silero>=1.5.6' \
  python-dotenv
# Populate .env (NOT checked in)
sudo cp prism42-worker-starter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now prism42-worker-starter
```

## Agent name
Registers with LiveKit Cloud as `agent_name="prism42-starter"` — distinct from the main worker's auto-generated `AW_*` id. Route dispatches to this worker with `RoomAgentDispatch(agent_name="prism42-starter", ...)`.

## Logs
`/tmp/prism42-logs/worker-starter.log` (same directory as the main worker, different filename).
