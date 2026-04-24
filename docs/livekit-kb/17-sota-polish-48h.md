# Perceptual-SOTA polish — 48h spec

> Frames the 24h tie-ElevenLabs → 48h chase-SOTA window as a **perceptual**
> engineering problem, not a waveform-quality problem. The waveform gap
> (Fish vs. ElevenLabs) is a model-training problem that 24h of harness
> work cannot close. What closes in 48h: **time-to-first-audio, dead-air
> kills, pipeline overlap, interruptibility**. A demo that does those four
> things feels SOTA even when the raw voice is a tier below ElevenLabs.
>
> Source prompt: user's GPT-5 reframe, 2026-04-24.
> Complements: KB 16 (10 levers), 16a (registry), tests/voice/ (guardrails).

## What "perceptual SOTA" means, measured

| Signal | Target | Guard (tests/voice/slo.yaml) |
|---|---|---|
| First audio (user speech-end → TTS first frame) | < 2.0 s | `t_reply_e2e_ms.p50 < 2500ms` |
| Filler utterance ("Yeah,", "Got it,") appears | 300–600 ms after VAD endpoint | log assertion in `test_no_repetition.py` |
| Interrupt latency (user barge-in → agent stops) | < 300 ms | LiveKit adaptive interruption, 216 ms median |
| Dead air between agent phrases | < 500 ms | `per_hop` breakdown in ralph.jsonl |
| Tokens stream into audio (not sentence-batched) | LLM first-token → TTS first-audio < 400 ms | `t_llm_ttft_ms` + `t_tts_ttfb_ms` delta |

**Non-goal**: matching ElevenLabs voice timbre or prosody. Fish S2-Pro +
PSAP reference already does "911 dispatcher" well. Stop training, start
overlapping.

## 48h execution — 12 × 4h blocks

### Day 1 — tie ElevenLabs (hours 0–24)

**Block 1–2 (0–8h): land the overlap levers.**
Drives ralph_loop.sh every 4h and actions the top-priority `ready` lever.

1. #1 Cartesia TTS swap (blocker: CARTESIA_API_KEY) — lifts t_tts_ttfb
   from 9.9s → ~90ms on its own, which is the single biggest lever in
   the registry.
2. #2 Parakeet streaming prod swap (blocker: user kill pid 60210) —
   lever #11 and #12 depend on the interim-transcript events emitted
   by this.
3. #13 LLM-token → TTS stream — the one overlap lever that has no
   blocker today. Wire `llm.stream()` output directly into `tts.push()`
   instead of buffering-by-sentence.

**Block 3 (8–12h): filler-utterance bridge (lever #11).**
The 300-600 ms perceptual window after VAD endpoint. Short phatics
("Yeah,", "Got it,", "Okay,") spoken by Fish from a pre-rendered cache
so TTS TTFB is ~0. Controlled by a pattern: fire only when
`t_tts_ttfb_ms > 800ms` predicted for the real reply. Guard:
`help_is_on_the_way_max_per_call: 1` in slo.yaml — fillers must not
recycle the emergency-phrase pool.

**Block 4 (12–16h): LLM on STT partials (lever #12).**
livekit-agents 1.5.6 gates preemptive generation on
`PREFLIGHT_TRANSCRIPT` events. After lever #2 ships, emit those from
Parakeet interims so LLM starts 400-700 ms before the user stops
talking. Monitor: `worker.log` shows `llm.request` timestamped
before `stt.final`.

**Block 5 (16–20h): bench run + gap report.**
`scripts/ralph_loop.sh --iter 6 --bench-n 5` → 30 samples,
60 min wall. Compare `p50` against ElevenLabs's subjective ~1.2s floor
(KB 09). Stop-work condition: if p50 ≤ 2.0s, proceed to Day 2. If not,
re-run the block-1-4 checklist — one of the overlap levers didn't land.

**Block 6 (20–24h): attestation round-trip.**
User runs the voice path end-to-end on laptop + mobile (task #87).
The tie-ElevenLabs verdict is subjective, not synthetic. Log the
verdict in `/tmp/prism42-ralph/attestation.jsonl`.

### Day 2 — chase SOTA (hours 24–48)

**Block 7 (24–28h): interruption polish.**
LiveKit 1.5.0 adaptive interruption — 216 ms median, 86% precision,
100% recall at 500 ms overlap. Default is on; verify via
synthetic-caller barge-in mid-reply. Target: user interrupts at word 2
of reply, agent stops within 300 ms.

**Block 8 (28–32h): backchannel handling.**
Distinct from interruption: when user says "mhm"/"okay" while agent
talks, agent must NOT stop. LiveKit's adaptive model handles this; test
with: 5 backchannels during 10s agent reply → zero false stops.

**Block 9 (32–36h): Fish partial-DAC decode (lever #8) — if unblocked.**
CUDA nvrtc sm_103 incompatibility is the blocker. If Team F surfaces
a workaround, land it; otherwise skip — a cloud-TTS swap (Cartesia)
has already closed this gap in aggregate.

**Block 10 (36–40h): tool-call latency audit.**
Any `llm.tool()` adds 1–3s per round-trip. Minimize tool surface to
what a dispatcher actually needs (location lookup, protocol match).
Cache tool results per session (LiveKit `userdata` dict).

**Block 11 (40–44h): 30-run bench + latency distribution.**
`ralph_loop.sh --iter 10 --bench-n 3` over the day = enough samples
for p99 claims. Plot p50/p95/p99 over 48h in a single chart. This is
the artifact for the demo.

**Block 12 (44–48h): demo script + handoff.**
Write a 3-call demo script that hits: (a) emergency that triggers
protocol lookup, (b) caller who interrupts, (c) non-English speaker.
Record all three. ship a `demo-48h.mp4` to the repo's `mvp/911-console-live/findings/`
bucket (gitignored; upload link via separate channel).

## Ralph loop cadence

`scripts/ralph_loop.sh` runs **every 4h** during the 48h window
(block boundary). Each run appends one row to
`/tmp/prism42-ralph/ralph.jsonl`. The row answers:

- What's p50/p95 right now?
- What's the current bottleneck hop?
- What's the next `ready` lever in the registry?

**Guardrails (halt-on-regression):**

- If `p50_now > p50_last * 1.3` → pause the loop, surface to user.
  This is the ralph-coverage-cycle rule (see
  `memory/coverage-cycle.md`) — concurrent writes to worker.py can
  compound bad states silently.
- If the bench fails 2 iterations in a row → pause. Likely a pod-side
  service went down; surface the service name from
  `systemctl is-active prism42-worker prism42-fish prism42-parakeet`.

## Integration with auto-memory

After every block, update the MEMORY.md pointer
`project_goatnote_911_console.md` with:

- Current p50/p95 from ralph.jsonl (last row).
- Which lever was just applied (#id from 16a registry).
- What blocker is now active, if any.

Keep the memory terse — the ralph.jsonl + registry are the durable
state; memory is the compass.

## Non-goals (explicit)

- **Training Fish on more data.** 48h insufficient to move the needle;
  the reference-voice lock (lever #7) is where we stop on voice quality.
- **Multi-language TTS.** Cartesia + Fish both speak English. Non-EN
  callers route to a human operator in the current design.
- **On-device inference.** Everything stays on the B300 pod or in
  cloud-TTS (Cartesia). Laptop only speaks WebRTC to LiveKit.
- **Replacing LiveKit or the agent framework.** Any such rewrite is a
  48h-budget-blower.

## When to stop

The 48h window ends. The ralph.jsonl + 30-sample bench + attestation
log + demo video are the deliverables. Past 48h, the remaining gap
to "indistinguishable-from-human" is a model-quality problem, not an
engineering problem, and belongs on a different roadmap.
