# Cycle-2g repo-applicability audit — 2026-04-25T21:02:27Z

Read-only scope. No code changes, no pod commands, no commits. Every claim is
tied to repo file:line. Confidence labels: VERIFIED (read in code/log) vs
CLAIMED (asserted in research doc but not yet verified in code).

Mission: confirm/refute six focus areas against current canonical sources
(`agents/livekit/worker.py`, `orchestrator.py`, `fish_speech_tts.py`,
`parakeet_stt.py`, `synthetic_caller_full.py`) plus the cycle-2d-n30 baseline
log slice.

---

## Six focus areas — confirm / refute

### 1. Pre-roll mismatch — REFUTED in current state (was real, fixed)

**Worker greeting string** (the literal text the worker would have said via
`session.say()` before cycle-2a): "Nine one one. What's your emergency?" —
referenced in **comment only**, not in any active `session.say()` call.
Evidence: `agents/livekit/worker.py:663` ("…to speak the 'Nine one one.
What's your emergency?' greeting"). The actual `session.say(...)` for that
greeting was removed at `worker.py:799-803` (cycle-2a edit, current
canonical SHA `42c8d2e8b5...`).

**Orchestrator first-turn string** (active LLM-driven first reply):
"Nine one one, what is your location and emergency?" — quoted **twice** in
the live system prompt:
- `agents/livekit/orchestrator.py:306` ("FIRST TURN — VERBATIM" block).
- `agents/livekit/orchestrator.py:338` ("PROTOCOL" step 1).

**Currently active (what the caller actually hears).** The orchestrator
form, *only*. After cycle-2a the worker logs `preroll.disabled_for_demo`
and never plays a greeting before the first LLM reply — confirmed in 10/10
calls of the cycle-2d-n30 baseline log
(`findings/b300_bench/cycle2d_n30/2026-04-25T18-58-49Z/logs/worker.log`,
search `preroll.disabled_for_demo`, every call hits this branch). There is
**no living "What's your emergency?" string** — the apparent mismatch is a
historical artifact.

**Live failure mode under cycle-2a.** Caller hears nothing at all between
ringback and the first LLM token (`first_audio_after_speech_ms` p50 =
3504 ms / p95 = 4005 ms in the n=30 baseline). Hearing 3.5 s of dead air
after dialing 911 is its own perceived-latency problem — distinct from the
historic two-versions issue, but more harmful for demo than the original
mismatch was.

**Safest patch (1-2 lines).** Two viable framings; both are 1-line edits:

- **Option A — drop the orchestrator's mention of pre-roll.** Remove the
  parenthetical "If the pre-roll already said this, pick up with 'Go
  ahead.'" at `orchestrator.py:339`. After cycle-2a there is no pre-roll;
  the parenthetical is now dead instruction the LLM can still latch onto
  and emit "Go ahead." as the first turn — mismatched against the
  protocol-correct verbatim above it on line 338.
- **Option B — restore a non-blocking pre-roll that matches the
  orchestrator literally.** Re-enable the `session.say()` at
  `worker.py:803` with a string identical to `orchestrator.py:306`
  ("Nine one one, what is your location and emergency?"). Keeps the
  caller-spoke gate at `worker.py:783-803`, restores audible
  acknowledgement inside ~200 ms, and removes the dead-air problem the
  baseline n=30 documents. Risk: re-introduces the +850 ms median pad
  the cycle-1 forensic flagged on 4/10 turns — but only on first turn,
  which is currently 3.5 s of silence anyway.

Recommend Option A for cycle-2g (one-line, zero pod risk). Option B is
cycle-2h material — needs a clean filler-vs-preroll arbitration design and
its own A/B bench, not a 60-min slot before demo.

### 2. Fish streaming limitation — CONFIRMED

**Adapter declaration.** `agents/livekit/fish_speech_tts.py:69` —
`capabilities=tts.TTSCapabilities(streaming=False)`. Comment at lines 62-67
documents the rationale verbatim: "we implement chunked-stream
synthesize() only, not the framework's stream() method… claiming
streaming=True without implementing stream() raises NotImplementedError
mid-call and the agent emits no audio." So the `streaming=False` flag is
a deliberate self-protective choice, not an oversight.

**Methods implemented.** `synthesize()` only (`fish_speech_tts.py:75-87`).
No `stream()` method on `FishSpeechTTS`. ChunkedStream subclass
`_FishSpeechStream._run()` (lines 108-246) iterates `resp.aiter_bytes()`
from the upstream HTTP server and pushes raw PCM into the
`AudioEmitter` — chunked at the HTTP-response level, not at the
LiveKit-stream-API level.

**Upstream Fish server behavior (CONFIRMED via the adapter's body
shape).** The request at `fish_speech_tts.py:135-156` posts `streaming:
True, format: "wav"` to `/v1/tts` and reads back chunks via
`aiter_bytes()`. So the upstream server *does* stream PCM chunks —
**but at full-utterance generation rate, not per-token**. Evidence from
`findings/b300_bench/cycle2d_n30/2026-04-25T18-58-49Z/logs/worker.log`
`fishspeech.done` lines:

```
chunk_count=6  max_chunk_gap_ms=2002  rtf=0.84  audio_duration_ms=2647
chunk_count=7  max_chunk_gap_ms=2248  rtf=0.79  audio_duration_ms=3111
chunk_count=2  max_chunk_gap_ms=2451  rtf=5.26  audio_duration_ms=511
```

`max_chunk_gap_ms` of 1.5-2.5 s with `frame_buffer_ms=200` means the
upstream emits ~6-7 large blobs per utterance, gap-limited by Fish's
internal generation pace, **not** a true low-latency phoneme/clause stream.
This is consistent with Fish's `chunk_length=200` semantic-token chunking
(`fish_speech_tts.py:41`) — the server emits one PCM blob per
semantic-token chunk, generation-paced.

**True WebSocket realtime adapter — scope (DO NOT IMPLEMENT).** Would
require:
- Upstream Fish service: re-base on the upstream WebSocket route (not
  HTTP `/v1/tts`). Upstream `tools/api_server.py` does have a streaming
  WebSocket per Fish docs, but the *generation latency profile is the
  same* — the bottleneck is text→semantic→DAC, not transport.
- LiveKit adapter: implement `stream()` returning a custom
  `tts.SynthesizeStream` subclass (file: `fish_speech_tts.py`, +~80
  LOC), flip `capabilities=streaming=True, interim=True`, and add a
  `_run()` that pumps text deltas frame-by-frame.
- Risk: `chunk_length=100` (the schema floor) shrinks the chunk gap
  but **kills voice quality** — Fish DAC needs ≥200 semantic tokens for
  prosody. We tried `chunk_length=50` previously; upstream returns 422.
- **Conclusion: a "true streaming" Fish adapter would not change the
  generation-rate floor; cycle-2d already locks the only knob available
  (`chunk_length=200`) to the schema default.** This is a Fish-the-model
  limit, not a Fish-the-adapter limit.

### 3. Partial STT / preflight — CONFIRMED

**Parakeet emits partials and preflights.** `parakeet_stt.py:283-318` —
the WebSocket reader emits `INTERIM_TRANSCRIPT` for `{"type":"partial"}`
and `PREFLIGHT_TRANSCRIPT` for `{"type":"preflight"}`. Capabilities flag
at `parakeet_stt.py:122-124` advertises `streaming=True, interim_results=
True` when `PRISM42_PARAKEET_STREAMING=1` (default true via env).

**Worker handling.** `worker.py:706-766` subscribes to
`user_input_transcribed` and reads `is_preflight` flag at
`worker.py:712-715`. **Current behavior: TELEMETRY ONLY.** The handler
logs `overlap.early_llm_trigger` once per turn at lines 732-739 with the
`is_preflight` flag, then sets `cur["early_llm_logged"] = True`. There is
**no second-generation kick** — the comment at `worker.py:719-725` is
explicit: "This does NOT trigger a second generation — livekit-agents
1.5.6 already fires preemptive gen on PREFLIGHT_TRANSCRIPT under the
hood."

So the chain is: Parakeet emits PREFLIGHT_TRANSCRIPT → livekit-agents
internally calls `on_preemptive_generation()` → the reply LLM starts
streaming on the partial. Verified by the assertion path at
`worker.py:643-657` (`overlap.llm_first_token_after_speech_ms` with
`is_preempt=True` if `t_stt_end is None` when `speech_created` fires).

**Cycle-2e BufferedDispatcherAgent vs preflight handling — DIFFERENT
HOOK POINTS (CONFIRMED).** BufferedDispatcherAgent
(`orchestrator.py:128-224`) overrides `tts_node()` and operates on the
**LLM-output text-delta stream**. Preflight operates on the
**STT-input transcript stream**. They are orthogonal — preflight kicks
the LLM earlier, BufferedDispatcherAgent ships LLM output to TTS at
sentence boundary instead of full-utterance. The cycle-2e
FAIL_2E_CHUNKED_MASK referenced in the user's directive was about this
LLM-output side; preflight is upstream of that and unaffected by 2e
status.

**Minimal safe path to actionability (DO NOT IMPLEMENT).** Two single-knob
moves, both env-flagged:
- **Lower `EARLY_LLM_CHARS`.** `worker.py:103` defaults to 12; the bench
  log shows the early-LLM trigger fires reliably even at 12. Lowering to
  6-8 would assert the trigger sooner but not actually accelerate
  generation (livekit-agents already triggered on PREFLIGHT_TRANSCRIPT
  before the assertion fires). Telemetry-only change. **Low impact.**
- **Tune Parakeet's preflight stability threshold (server-side).** The
  client/adapter has no knob — Parakeet emits whatever its `/ws` server
  decides is "stable prefix." Tightening on the server (post-hackathon)
  would emit preflights earlier. Pod-side change, out of repo scope for
  cycle-2g.

Verdict: preflight is **already actionable** — not a missing capability,
just a fully-wired one whose ceiling is upstream of the worker. No
worker-side patch will accelerate it.

### 4. TTFMA metric chain — PARTIALLY CONFIRMED (3 of 5 legs measured, 2 missing)

The five legs the user asks about, with file:line evidence:

| Leg | Status | Evidence |
|---|---|---|
| VAD end | MEASURED | `worker.py:701-702` — `t_user_speech_end = time.monotonic()` on `user_state_changed` speaking→listening. Backup at `worker.py:756-764` uses `transcript_delay`. |
| Stable partial | NOT explicitly captured as a separate t-stamp | `is_preflight` flag is logged at `worker.py:732-739` but no `t_stt_preflight` timestamp is recorded into the timing bucket. The `overlap.early_llm_trigger` log line carries the flag but not a wall-clock delta. |
| First LLM clause / first useful clause | NOT MEASURED at clause boundary | `worker.py:621-658` records `t_llm_first_token` from `speech_created` event (proxy: when the agent starts synthesizing — already past the LLM-side first token). No clause-boundary timestamp. BufferedDispatcherAgent (`orchestrator.py:191-204`) DOES emit `overlap.first_segment_published_after_llm_ms` but only when cycle-2e is ON (env-flag default OFF). |
| TTS first byte | MEASURED | `fish_speech_tts.py:189-195` — `t_first_byte = time.monotonic()` and log `fishspeech.t_first_byte`. Cross-confirmed at `worker.py:523-541` via `TTSMetrics.ttfb` → `tts_ms`. |
| Playback first sample (caller-side) | NOT MEASURED on the agent side | `synthetic_caller_full.py:137, 193-204, 287-288, 365-367` measures `first_useful_audio_at` and `last_useful_audio_at` — but this is the **synthetic caller's egress probe**, not a live-call playback timestamp. For a real human caller no playback-arrival marker exists. |

**Currently published per-turn metrics:** `stt_ms, llm_ms, tts_ms, tool_ms,
total_ms` over the `b3-latency` data channel
(`worker.py:917-955` / contract docstring). `total_ms` is computed as
`t_turn_done - t_stt_end` (`worker.py:288-289`), which **excludes the VAD-
to-STT-end leg** — a known lossy total.

**Missing hooks (file:line, log event name, payload shape — DO NOT
IMPLEMENT).** Three additions would close the chain:

1. **`t_stt_preflight` → `overlap.preflight_after_speech_ms`.** Add at
   `worker.py:712-739`: when `is_preflight` flips True for the first time
   in this turn, store `cur["t_stt_preflight"] = time.monotonic()` and
   emit `log.info("overlap.preflight_after_speech_ms", session_id, ms,
   text_len)`. Payload: `{ms: int, text_len: int, session_id: str}`.
2. **`t_llm_first_clause` → `overlap.first_clause_after_speech_ms`.**
   Either flip cycle-2e ON (the existing
   `overlap.first_segment_published_after_llm_ms` is exactly this metric
   — `orchestrator.py:198-204`) OR add a non-buffering observer at
   `orchestrator.py` that watches the LLM stream for sentence terminator
   and emits a no-op log line. Payload: `{ms: int, chars: int,
   approx_tokens: int}`.
3. **`t_playback_first_sample` (caller-side proxy).** No clean
   agent-side hook — the `b3-latency` data channel publishes
   `tts_ms = TTFB` already, and the audio path between TTS first byte
   and WebRTC first frame is in livekit-agents' internals.
   `synthetic_caller_full.py` is the only place this is observable; it
   already does. For human calls, `tts_ms` is the practical proxy.

**Net.** TTFMA (VAD-end → first useful audio) is observable via two
existing chains: (a) `overlap.tts_first_audio_after_speech_ms` at
`worker.py:533-541` for the bench, and (b) `total_ms` for live calls. The
two hooks above (preflight, first-clause) would add resolution but are
**non-blocking instrumentation** — not on the demo's critical path.

### 5. Backend selector — CONFIRMED present, multiple branches dead at runtime

**Selector locations.**
- LLM: `worker.py:329` — `os.environ.get("LLM_BACKEND", "anthropic").lower()`. Branches: `vllm-local` (line 330) | else Anthropic (line 361). Default: `anthropic`.
- TTS: `worker.py:378` — `os.environ.get("TTS_BACKEND", "fish").lower()`. Branches: `cartesia` (line 379) | `deepgram_aura` (line 391) | `elevenlabs` (line 399) | else Fish (line 407). Default: `fish`.

**Plugin imports.** All three non-default TTS branches use lazy imports
inside the `if` block (per `worker.py:376-377` comment "Each import lives
inside its branch so a missing plugin only breaks that backend, not
Fish"). Specifically:

- `worker.py:380` — `from livekit.plugins import cartesia`
- `worker.py:392` — `from livekit.agents import inference` (Deepgram via inference plugin)
- `worker.py:400` — `from livekit.plugins import elevenlabs`

**Dependency status (CONFIRMED).** `agents/livekit/pyproject.toml:13-15`
declares `livekit-agents[anthropic,openai,silero,turn-detector]>=1.5.6`.
The `cartesia`, `elevenlabs`, and `nvidia` (Riva) extras are **NOT in
the declared deps**. The branches will `ImportError` at runtime if their
env flags are flipped without first reinstalling with the relevant
extras.

**Env vars required** if a branch were activated:
- Cartesia: `CARTESIA_API_KEY` + optional `CARTESIA_VOICE_ID` (`worker.py:384`).
- Deepgram (via inference): `DEEPGRAM_API_KEY` (implicit via livekit
  inference) + `DEEPGRAM_VOICE` (`worker.py:395`).
- ElevenLabs: `ELEVENLABS_API_KEY` + `ELEVEN_VOICE_ID` (`worker.py:403`).
- Riva / NVIDIA: **not branched in the worker.** No `nvidia` plugin
  branch in the TTS selector. STT side uses our local Parakeet adapter
  (custom subclass of `livekit.agents.stt.STT`), not the NVIDIA plugin.

**User directive.** The hackathon CLAUDE.md §0 originally framed
Cartesia/Deepgram as the "new build" (line "Cartesia Sonic-3 TTS,
Deepgram Nova-3 STT") but the explicit voice directive in this audit's
brief excludes Cartesia/ElevenLabs swaps for cycle-2g. **Note logged;
recommend NO swap.** The branches are scaffolding for a post-demo
A/B, not a hot path.

### 6. Playback buffer — CONFIRMED 200 ms default; underrun-equivalent symptom present

**Default in code.** `fish_speech_tts.py:126` —
`_frame_ms = int(os.environ.get("PRISM42_TTS_FRAME_MS", "200"))`.
Comment at lines 118-126 documents the rationale: 40 ms = lowest
latency but most underrun-prone (Fish RTF ~1.96 on B300 stable
PyTorch). 200 ms gives the receiver enough audio to ride out a
generation hiccup. **Matches project memory's canonical default.**

**Underrun-equivalent in baseline log.** `findings/b300_bench/cycle2d_n30/
2026-04-25T18-58-49Z/logs/worker.log` `fishspeech.done` lines show
`max_chunk_gap_ms` of **1500-2500 ms** on most calls (sample evidence:
`max_chunk_gap_ms=2002 / 2248 / 2115 / 2451 / 1594` over 5
consecutive utterances). With `frame_buffer_ms=200`, that's a 7.5×
to 12× ratio of generation gap to playback buffer. The gap is a
**generation-side** stall (Fish's text→semantic→DAC pipeline pausing
between semantic-token chunks), not a transport-side underrun, but the
user-perceived effect is the same: audio in chunks with audible silence
gaps inside one utterance.

The literal log strings `underrun`, `buffer_empty`, `playback_stall` do
NOT appear in `worker.log` for cycle-2d-n30. The `max_chunk_gap_ms`
metric is the only proxy, and it's elevated.

**Safe sweep scope (DO NOT IMPLEMENT).** `PRISM42_TTS_FRAME_MS` is the
single env knob. A 120/160/200 ms three-point sweep:
- Sweep harness: a single env-flag flip per run at the
  `prism42-fish.service` systemd level (or `prism42-worker.service`
  for the LiveKit side, since the consumer is the worker). The knob
  is read at `_FishSpeechStream._run()` start (line 126) per
  utterance, so a service restart picks it up but a hot-reload does
  not.
- Bench: re-run cycle-2d-n30 (`bench_b300.py` n=30) at each frame
  size, compare `first_audio_after_speech_ms` p50/p95 +
  `max_chunk_gap_ms` distribution.
- Risk: 120 ms exposes the underrun condition the comment at lines
  118-126 specifically warns about; 160 ms is the only meaningfully
  novel point. **Likely outcome: no win, possibly a regression.** The
  generation-side gap dominates; playback-buffer tuning addresses the
  wrong layer.
- **Verdict: low-impact change, defer or reject.** The headline
  generation gap (1.5-2.5 s) cannot be papered over by buffer tuning
  in the 40-200 ms band. This sweep is a 3-hour distraction.

---

## Top 5 repo-applicable changes (ranked)

Scoring rubric: H=3, M=2, L=1. Higher = better in each column. Aggregate
is sum (max 12).

| # | Change | Impact | Risk (lower=better, scored as 4-risk) | Rollback ease | Demo relevance | Aggregate |
|---|---|---|---|---|---|---|
| 1 | Drop dead "If pre-roll already said this" parenthetical at orchestrator.py:339. Single-line edit; eliminates the only living "Go ahead." failure mode the historic mismatch could surface. | M(2) | H(3) | H(3) | M(2) | **10** |
| 2 | Add a 200 ms `tts_first_token` filler kicker on first turn so the caller hears something inside ~250 ms of dialing instead of 3.5 s of dead air. Re-enable the `session.say()` at worker.py:803 with the orchestrator's exact verbatim string + the `caller_spoke` gate already at lines 686-708. | H(3) | M(2) | M(2) | H(3) | **10** |
| 3 | Add `t_stt_preflight` + `overlap.preflight_after_speech_ms` log line at worker.py:712-739 (one new timestamp, one new log.info). Closes the TTFMA chain leg #2 with no behavioral change. Pure observability. | M(2) | H(3) | H(3) | M(2) | **10** |
| 4 | Flip `PRISM42_CYCLE_2E_BUFFER=1` for the demo run (env flag at the worker service level). Activates BufferedDispatcherAgent's sentence-boundary first-clause flush, which directly attacks `first_audio_after_speech_ms`. Code is already in tree at orchestrator.py:128-224, dormant. Has its own `MIN_FIRST_SEGMENT_CHARS=8` metric-honesty floor (line 61). | H(3) | L(1) | H(3) | H(3) | **10** |
| 5 | Lower `EARLY_LLM_CHARS` from 12 to 8 (env flag `PRISM42_EARLY_LLM_CHARS=8`) at worker.py:103. Telemetry-only — does not actually accelerate generation (preempt-gen already fires upstream of this) but makes the assertion line fire on shorter partials, improving observability for cycle-2g sweeps. | L(1) | H(3) | H(3) | L(1) | **8** |

Notes:
- #4 has higher demo relevance than its risk score implies BUT carries
  the largest behavior change of any item here. Cycle-2e was previously
  deployed and rolled back as FAIL_2E_CHUNKED_MASK — the metric-honesty
  floor at `_MIN_FIRST_SEGMENT_CHARS=8` (`orchestrator.py:61`) was the
  fix. Risk is "did the floor fix actually land in the tree?" → YES,
  verified at orchestrator.py:61 with telemetry at 215-218 for
  below-threshold cases. Still rated risk-L because a fresh n=30 bench
  is needed to confirm warm-state non-regression.
- #2 (re-enable preroll) needs careful framing — the cycle-2a edit
  intentionally disabled preroll because it was blocking
  `speech_created` from firing, paying a +850 ms median pad. The proper
  Option B requires a non-blocking `session.say()` (allow_interruptions=
  True) and a strict caller_spoke gate; the current gate at
  worker.py:686-708 already supports this, but the previous test
  showed it still cost time. Rated risk-M.

---

## Do now / defer / reject

| Change | Verdict | Reason |
|---|---|---|
| #1: drop dead "If pre-roll already said this" at orchestrator.py:339 | DO NOW (cycle-2g) | One-line edit, zero pod risk, removes a residual LLM ambiguity in the canonical first-turn protocol. Trivial to roll back (single-line revert). |
| #3: add `overlap.preflight_after_speech_ms` log line at worker.py | DO NOW (cycle-2g) | Pure-observability addition. Closes a TTFMA-chain gap and makes future cycle-2h sweeps measurable. ~5 LOC. No behavior change. |
| #4: flip `PRISM42_CYCLE_2E_BUFFER=1` for the demo run | DO NOW (cycle-2g, with bench gate) | Highest expected impact on `first_audio_after_speech_ms`. Code is in tree, dormant, with metric-honesty floor. **Gate**: must run a fresh n=30 bench BEFORE demo and verify (a) p95 first_useful_audio improves and (b) no FAIL_2E-class regression. If bench fails, flip the flag back. |
| #2: re-enable bounded pre-roll at worker.py:803 | DEFER (cycle-2h) | Genuine UX win (3.5 s dead-air → audible greeting in ~200 ms) but cycle-1 already paid +850 ms median pad on this path. Needs a clean filler-vs-preroll arbitration design and its own A/B bench. Not a 60-min slot before demo. |
| #5: lower `EARLY_LLM_CHARS` from 12 to 8 | DEFER | Cosmetic — does not accelerate the LLM. Wait until cycle-2h instrumentation sweep. |
| Fish "true streaming" WebSocket adapter rewrite | REJECT | Generation-rate bottleneck is the model, not the adapter. `chunk_length=200` is already the schema floor for prosody-acceptable output; lowering hits 422. Rebuild costs ~80 LOC + days of validation for zero expected p50 win. |
| `PRISM42_TTS_FRAME_MS` 120/160/200 sweep | REJECT | Generation-side gap is 1.5-2.5 s; playback-buffer tuning in the 40-200 ms band cannot help. 120 ms exposes the underrun the comment specifically warns against. ~3-hour cost for ~zero expected win. |
| Cartesia / ElevenLabs / Riva swap | REJECT | User explicitly excluded. Branches exist but deps not declared in pyproject.toml (worker.py:380, 400 lazy-import; pyproject.toml:13-15 misses the extras). Risks regressing cycle-2d's 2.4× e2e win for an unbounded UX delta. |

---

## Sources

1. `agents/livekit/worker.py:103` — `EARLY_LLM_CHARS` env default 12.
2. `agents/livekit/worker.py:236-298` — turn timing bucket schema, finalize logic.
3. `agents/livekit/worker.py:329-360` — LLM_BACKEND selector.
4. `agents/livekit/worker.py:378-409` — TTS_BACKEND selector.
5. `agents/livekit/worker.py:411-451` — TurnHandlingOptions + preemptive_generation config.
6. `agents/livekit/worker.py:458-470` — `overlap.config` startup assertion (incl. `cycle_2e_buffer_enabled`).
7. `agents/livekit/worker.py:475-552` — `metrics_collected` handler (STT/LLM/TTS metrics ingestion).
8. `agents/livekit/worker.py:533-541` — `overlap.tts_first_audio_after_speech_ms` log event.
9. `agents/livekit/worker.py:621-658` — `speech_created` handler + `overlap.llm_first_token_after_speech_ms`.
10. `agents/livekit/worker.py:663-668` — comment quoting historic worker greeting "Nine one one. What's your emergency?".
11. `agents/livekit/worker.py:686-766` — caller_spoke gate + `user_input_transcribed` handler with `is_preflight` flag.
12. `agents/livekit/worker.py:732-739` — `overlap.early_llm_trigger` (telemetry-only, comment lines 719-725).
13. `agents/livekit/worker.py:783-803` — preroll `wait_for_participant` + cycle-2a `preroll.disabled_for_demo` log.
14. `agents/livekit/worker.py:820-893` — filler scheduler (`_fire_filler` + `_schedule_filler`).
15. `agents/livekit/orchestrator.py:21-26` — module-level cycle-2e gating description.
16. `agents/livekit/orchestrator.py:49-66` — Pipecat `_SENTENCE_RE` + token-cap defaults.
17. `agents/livekit/orchestrator.py:128-224` — `BufferedDispatcherAgent` body.
18. `agents/livekit/orchestrator.py:191-204` — `overlap.first_segment_published_after_llm_ms` log line.
19. `agents/livekit/orchestrator.py:215-218` — below-threshold tail flush log.
20. `agents/livekit/orchestrator.py:259, 291` — `FAST_DISPATCHER_SYSTEM_PROMPT` first-turn verbatim (two quotes inside the template).
21. `agents/livekit/orchestrator.py:306, 338-339` — first-turn verbatim + dead "If the pre-roll already said this, pick up with 'Go ahead.'" parenthetical.
22. `agents/livekit/orchestrator.py:390-410` — `make_orchestrator()` cycle-2e branch.
23. `agents/livekit/fish_speech_tts.py:24-31` — module-level imports, `DEFAULT_URL`, sample rates.
24. `agents/livekit/fish_speech_tts.py:34-56` — `FishSpeechOptions` dataclass with `chunk_length=200, seed=911, temperature=0.1`.
25. `agents/livekit/fish_speech_tts.py:62-72` — adapter capabilities `streaming=False`.
26. `agents/livekit/fish_speech_tts.py:75-87` — `synthesize()` method (no `stream()`).
27. `agents/livekit/fish_speech_tts.py:108-225` — `_FishSpeechStream._run()` chunked stream body.
28. `agents/livekit/fish_speech_tts.py:118-126` — `PRISM42_TTS_FRAME_MS=200` default + comment.
29. `agents/livekit/fish_speech_tts.py:135-156` — POST body shape (`format: "wav", streaming: True, chunk_length: 200`).
30. `agents/livekit/fish_speech_tts.py:189-225` — chunk pump loop, `t_first_byte` / `t_first_push` / `max_gap_ms` instrumentation.
31. `agents/livekit/parakeet_stt.py:25-30` — protocol comment listing `partial`, `preflight`, `final` events.
32. `agents/livekit/parakeet_stt.py:106-108` — `streaming` flag default + `PRISM42_PARAKEET_STREAMING` env.
33. `agents/livekit/parakeet_stt.py:111-131` — `STTCapabilities(streaming, interim_results)`.
34. `agents/livekit/parakeet_stt.py:202-318` — `ParakeetSpeechStream`, WebSocket reader, `INTERIM_TRANSCRIPT` / `PREFLIGHT_TRANSCRIPT` / `FINAL_TRANSCRIPT` emission.
35. `agents/livekit/synthetic_caller_full.py:137, 193-204, 287-288, 365-367` — `first_useful_audio_at` / `last_useful_audio_at` synthetic-caller probes.
36. `agents/livekit/pyproject.toml:13-15` — `livekit-agents[anthropic,openai,silero,turn-detector]>=1.5.6` (no cartesia / elevenlabs / nvidia extras).
37. `findings/b300_bench/cycle2d_n30/2026-04-25T18-58-49Z/result.json` — cycle-2d-n30 baseline JSON: warm-state Fish full-render p50/p95 = 2205/2822 ms; first_audio_after_speech p50/p95 = 3504/4005 ms; first_useful_audio_after_speech p50/p95 = 3053/3804 ms.
38. `findings/b300_bench/cycle2d_n30/2026-04-25T18-58-49Z/logs/worker.log` — `fishspeech.done` lines showing `max_chunk_gap_ms` 1594-2451 ms with `frame_buffer_ms=200`; `preroll.disabled_for_demo` on every call (no `session.say` greeting plays).
39. `findings/voice/cycle-2e-pipecat/pattern.md` — design doc for BufferedDispatcherAgent (referenced from `orchestrator.py:131`); not re-read in this audit.
40. `findings/voice/cycle-2e-pipecat/worker-target-locations.md` — companion patch-plan doc (referenced from `orchestrator.py:132`); not re-read in this audit.
