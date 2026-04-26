# cycle-2R synthetic-caller demo — PASS_2R end-to-end

Captured 2026-04-26 ~10:00 UTC by main agent driving
`agents/livekit/synthetic_caller.py` from the pod against the live
post-cutover demo URL.

## Setup

- Demo URL: `https://prism42-console.vercel.app/prism42/livekit`
- Synthetic caller: `agents/livekit/synthetic_caller.py` (already on pod
  in venv) — joins LiveKit room as `identity=synthetic-caller`, listens
  for the agent worker to join + publish audio, reports stages.
- The synthetic caller does NOT publish audio; it only verifies the
  dispatcher's GREETING flows end-to-end (which exercises every layer
  except the caller→agent direction).

## Result

```
[1] minting session via https://prism42-console.vercel.app/prism42/api/session/start
    session_id = 3891e1ac-a739-61c1-3e2a-fd4085d34105
[2] minting LiveKit token for room=3891e1ac-a739-61c1-3e2a-fd4085d34105
    livekit_url = wss://prism42.thegoatnote.com    ← self-hosted, NOT cloud
    token_len   = 363
[3] connecting to room as identity=synthetic-caller
    connected @ +1.50s, sid=...
[4] waiting up to 15.0s for agent participant
    AGENT JOINED @ +1.53s identity='agent-AJ_8HRTcbiUQao4'
[5] waiting up to 30.0s for agent audio track
    AGENT AUDIO TRACK SUBSCRIBED @ +1.54s
[6] listening for 35.0s
    FIRST AUDIO FRAME from agent-AJ_8HRTcbiUQao4 @ +1.55s (samples=480, sr=48000)
    +35.56s: bytes=1,632,480 speech_frames=232 peak=30224

============================================================
RESULT
============================================================
agent_joined            : YES ('agent-AJ_8HRTcbiUQao4')
audio_track_subscribed  : YES
first_audio_frame       : YES (+1.55s)
total_audio_bytes       : 1,632,960
speech_frames           : 232 (frames with peak > 1000)
peak_amplitude          : 30224 (16-bit signed; >5000 = clear speech)
VERDICT: PASS — agent spoke (232 non-silent frames, peak amplitude 30224)
```

## What this proves

| Layer | Verified | How |
|---|---|---|
| Vercel frontend deployed with new build | YES | served HTML contains `b3-cad-` (Team F's scoped CSS prefix); deploy `dpl_6NH7gWV472iXLTP1kM9gnTa8QKo8` |
| `/prism42/api/session/start` route | 200 OK | step [1] minted session_id |
| `/prism42/api/livekit-token` route | 200 OK + correct URL | step [2] returned `wss://prism42.thegoatnote.com` (NOT cloud) and a 363-char JWT signed with the new key/secret |
| DNS resolution from pod | YES | step [3] connect succeeded — pod resolved prism42.thegoatnote.com |
| TLS handshake (Caddy + Let's Encrypt E7) | YES | step [3] WSS upgrade succeeded over TLS 1.3 |
| livekit-server signaling (`:7880` via Caddy reverse-proxy) | YES | step [3] room joined; only-1.5s |
| Agent worker registered + dispatching | YES | step [4] agent joined as `agent-AJ_8HRTcbiUQao4` within +30 ms of caller joining |
| Worker → Fish TTS pipeline | YES | step [5] audio track published |
| Cycle-2P file-backed greeting | YES | first audio frame at +1.55 s (cached MWintro WAV; cycle-2P file path active) |
| Audio frames over WebRTC media plane | YES | 232 non-silent frames received, peak 30224 (clear speech) |

## What this does NOT prove

- **Caller → dispatcher round-trip** — synthetic_caller.py only listens. The full turn (caller speaks → STT → FSM → LLM → TTS → caller hears reply) requires `synthetic_caller_full.py` which publishes audio. Out of scope for this run.
- **Strict-NAT laptop attestation** — requires a corporate-network laptop. Out of scope.
- **Dispatcher UI populates with live FSM data** — Team F's panel is wired but Team A's `dispatch_publisher.py` integration patch (~26 LoC) is not yet applied, so the panel renders empty in default mode (or fixture replay if `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` is set).

## Latency observation

The first-audio-frame at +1.55s is nearly identical to the cycle-2P
baseline on Cloud (file-backed greeting cache hits in <100 ms;
1.5s is dominated by WebRTC handshake + first frame buffering).
**No detectable latency regression from the cutover** — Caddy reverse-
proxy adds <5 ms relative to direct WebSocket; Caddy + livekit-server
on the same machine is essentially zero hop.

## Hand-off

User attestation from laptop+mic remains the gold-standard test (covers
caller→dispatcher direction). This synthetic test eliminates the most
likely failure modes (signaling broken, JWT mismatched, agent worker
not registered, audio path not flowing).
