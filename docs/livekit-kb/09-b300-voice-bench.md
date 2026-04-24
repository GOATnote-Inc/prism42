---
title: B300 self-hosted voice-pipeline latency bench
date: 2026-04-24
status: first measured result (N=10)
scope: Pod-internal per-hop latency for the prism42 LiveKit voice runtime,
       measured against the LiveKit preemptive-streaming budget published
       in `04-deployment-patterns.md`.
---

# B300 self-hosted voice-pipeline bench — N=10

## Setup

`agents/livekit/bench_b300.py` invokes `synthetic_caller_full.py` ten
times back-to-back against the live `prism42-worker.service`, sleeping
15 s between runs and pre-flighting Fish Speech's `/v1/health` (wait up
to 30 s). For every turn it correlates the subprocess stdout with the
worker's structured log at `/tmp/prism42-logs/worker.log`, scopes parsing
to the region *after* that turn's final `user_transcript` line, and
extracts:

- `t_stt_ms` — LiveKit STT `transcript_delay` (utterance-end → transcript),
  Parakeet TDT 0.6B v3 self-hosted on :9100.
- `t_fish_ttfb_ms` — `fishspeech.t_first_byte.ms_since_post` (TTS TTFB).
- `t_fish_total_ms` — `fishspeech.done.total_ms` (TTS full synthesis).
- `t_reply_e2e_ms` — synthetic caller's `reply_latency_after_pubend`
  (publish-end → first audible reply frame, `peak > 1000`).
- `t_llm_proxy_ms` — derived: `t_reply_e2e - t_stt - t_fish_ttfb`.
  Approximates LLM + orchestrator. Team β is wiring a direct `llm_ms`
  log line; until that ships the proxy is the best signal.

**Hardware.** NVIDIA B300 SXM6 AC (sm_103), CUDA 13, single GPU.

**Software.** `livekit-agents 1.5.6`, `livekit-plugins-anthropic 1.5.6`,
Parakeet TDT 0.6B v3, Fish Speech S2-Pro, Opus 4.7 (`claude-opus-4-7`),
adaptive thinking on, display omitted. Session path: Vercel session-mint
→ LiveKit Cloud (Germany-2) media plane → pod worker.

**Run.** `2026-04-24T20:47:10Z`, N=10, same utterance
`"I have chest pain and shortness of breath."`, worker warmed.

## Results (N=10)

| hop                | mean    | median  | p95     | p99     | min     | max     |
|--------------------|---------|---------|---------|---------|---------|---------|
| t_stt_ms           |   606.5 |   614.2 |   627.7 |   627.9 |   555.6 |   628.0 |
| t_fish_ttfb_ms     |     3.6 |     4.0 |     4.5 |     4.9 |     2.0 |     5.0 |
| t_fish_total_ms    |  8625.4 |  6885.5 | 13747.6 | 13827.9 |  6373.0 | 13848.0 |
| t_reply_e2e_ms     | 10467.0 |  9020.0 | 15800.5 | 15984.1 |  8010.0 | 16030.0 |
| t_llm_proxy_ms     |  9856.9 |  8456.4 | 15177.7 | 15367.3 |  7389.7 | 15414.7 |

All ten runs yielded valid STT + Fish-reply measurements. The caller's
verdict line `"pre-roll never spoke (TTS broken)"` is an artifact of the
4 s pre-roll window colliding with `preroll.skipped_caller_spoke_first`
when the bench publishes immediately after connect; reply-audio and
reply-latency measurements remain valid.

## Comparison to the 2026 preemptive-streaming budget

`04-deployment-patterns.md` §preemptive-generation quotes LiveKit's own
claim: **400-800 ms streaming vs 1000-2000 ms+ blocking** for the
STT → LLM → TTS path when 1.5+ preemptive generation is enabled. Our
pod-internal numbers on the same stack:

| budget component                           | LiveKit playbook | B300 measured (median) | verdict             |
|--------------------------------------------|------------------|------------------------|---------------------|
| STT finalization                           | 50-150 ms        | 614 ms                 | over budget 4-12x   |
| LLM to first output (proxy)                | ~600 ms (Opus)   | 8456 ms                | over budget ~14x    |
| TTS time-to-first-byte                     | 100-400 ms       | 4 ms                   | **under budget 25-100x** |
| End-to-end reply (caller-perceived, P50)   | 610-1400 ms      | 9020 ms                | over budget 6-15x   |

## Where B300 wins

1. **Fish S2-Pro TTFB = 3-5 ms.** Two orders of magnitude under LiveKit's
   100-400 ms TTS TTFB band, ~50x faster than Cartesia Sonic-2's ~90 ms.
   The caller experience is gated by everything *before* Fish's POST,
   not by Fish.
2. **Parakeet TDT 0.6B v3 STT at 606 ms median, sub-1 s p99.** Includes
   the LiveKit VAD tail. Cloud STT in the same region typically lands
   400-900 ms with higher long-tail variance under load.
3. **No vendor coupling on STT/TTS.** Pod is insensitive to Deepgram /
   Cartesia / ElevenLabs outages and rate limits. For emergency
   dispatch, this is the argument that matters.

## Where B300 does not win (yet)

1. **LLM + orchestrator dominates ~80% of E2E.** `t_llm_proxy_ms` median
   8.5 s, p99 15.4 s. Opus 4.7 with adaptive thinking + the
   orchestrator's multi-specialist tool round-trip (see `worker.py`
   INTERRUPTION_TIMEOUT = 30 s: "~7-12 s for the first turn"). Until we
   land streaming token-forward from Opus to Fish or swap to a smaller
   LLM on the critical path, nothing on the TTS/STT side will
   materially move `t_reply_e2e_ms`.
2. **Fish total synthesis 6.4-13.8 s.** TTFB is 4 ms but Fish keeps
   emitting bytes for the full reply. LiveKit forwards as Fish pushes,
   so the caller hears audio long before Fish is done — but the full
   reply is not in flight until this elapses. Proportional to reply
   length; shrinks once Team α's streaming-to-Fish patch lands
   (orchestrator currently buffers the entire LLM reply before posting).
3. **STT at ~614 ms is slower than Deepgram streaming (200-400 ms).**
   Driven by the LiveKit VAD endpoint delay (500 ms default). Tighter
   VAD or partial-transcript streaming (Parakeet supports it; the
   plugin runs finalize-only) gets us under 400 ms.

## Reproducibility

```bash
# On the Brev pod (prism-mla-b300-h4h5), agents/livekit directory on pod.
brev exec prism-mla-b300-h4h5 'cd /opt/prism42/agents/livekit && \
    .venv/bin/python bench_b300.py --n 10 --sleep-s 15'
```

Output writes to `/opt/prism42/agents/livekit/findings/b300_bench/<UTC>.json`
(pod-local, gitignored). The bench is idempotent — no state survives across
runs except the worker log, which the bench reads by file-offset window.

## Limits of this bench

1. **Caller-side latency is NOT measured.** Everything here is pod-internal.
   Real callers add the browser mic → LiveKit Cloud Germany-2 → pod
   WebRTC leg (typically 20-80 ms p50 for a US caller).
2. **Same utterance for all runs.** Fish prompt-level caching may
   slightly under-measure worst-case TTS total synthesis.
3. **Proxy LLM latency only.** `t_llm_proxy_ms` folds in RTP propagation,
   Fish queueing before first-byte, preroll/filler-TTS scheduling, and
   LiveKit internal buffering. Team β's `llm_ms` will replace this.
4. **No barge-in / interrupt testing.** All 10 runs are clean single-turn
   publish-and-wait.
5. **Single-GPU contention.** Fish, the LLM client, and future local
   model serving all share the one B300. Earlier runs (20:35:00Z) that
   exited with `httpx.ConnectError: Connection refused` show Fish
   crashing under concurrent reply-TTS + caller-synth load. The 15 s
   between-run sleep avoids this but is not a production regime.

## One-line summary for a demo slide

On the B300 self-hosted voice stack, Fish TTS first byte is **4 ms median**
and Parakeet STT is **614 ms median**; the orchestrator-LLM hop, not the
voice plane, is the remaining bottleneck at **8.5 s median**, giving
**9 s median / 16 s p99** end-to-end reply latency over N=10.

## Raw data

Full summary JSON on pod: `/opt/prism42/agents/livekit/findings/b300_bench/20260424T204710Z.json`
(also mirrored to the caller agent's findings dir, gitignored).
