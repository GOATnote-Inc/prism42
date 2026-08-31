# Cycle-2a (drop preroll) — failure mode anticipator

## Top likelihood: #1 (synthetic harness asserts preroll exists). Single biggest unknown: whether livekit's `_update_agent_state("listening")` is sufficient to satisfy LiveKit Cloud's "agent is live" signaling for the `/prism42/livekit` web client without ever calling `session.say()`.

---

## #1 — Synthetic harness asserts non-empty preroll, fails with exit 4 on every turn
Symptom: All 10 bench runs return `exit_code=4 / VERDICT: pre-roll never spoke (TTS broken)`. Acceptance criterion "10/10 real assistant replies" fails 0/10 — but the failure looks like a TTS regression, not the expected "preroll dropped" success. Bench p95 numbers will be `None` for every hop because `parse_window` short-circuits on `verdict_line=TTS broken`.
Root cause: `synthetic_caller_full.py:254-256` hard-asserts `preroll_speech < 5 → return 4`. This was correct cycle-1 logic but is exactly inverted for cycle-2a.
Surgical workaround: invert the assertion — drop the `preroll_speech < 5` check entirely (or gate it on `os.environ.get("PRISM42_PREROLL_DROPPED")`); keep `reply_first_speech_at is None → return 5` as the only failure check.
Source: `~/prism42/agents/livekit/synthetic_caller_full.py:254-256`

## #2 — STAGE D 4-second hardcoded sleep becomes pure wasted floor on every turn
Symptom: `t_reply_e2e_ms` measured from publish-end is fine, but wall-clock per turn still shows ~+6s before caller publishes (4s STAGE D sleep + ~2s connect/agent-join). User-perceived "publish→first useful assistant audio" looks unchanged because the harness pads in dead time the user is not measuring; "improves materially" gate fails on the wrong metric.
Root cause: `synthetic_caller_full.py:177 await asyncio.sleep(4.0)` is the hardcoded "wait for pre-roll" window — synchronous, regardless of whether preroll exists. This is the +6s offset cycle-1 mentioned.
Surgical workaround: gate the sleep on preroll-expected env var: `await asyncio.sleep(0.5 if os.environ.get("PRISM42_PREROLL_DROPPED") else 4.0)`. 0.5s gives Parakeet warm-up margin (failure mode #4) without burning 3.5s of harness wallclock.
Source: `~/prism42/agents/livekit/synthetic_caller_full.py:176-180`

## #3 — Filler skip-first-turn gate (`turns_seen <= 1`) silently swallows the first reply's filler bridge
Symptom: First turn after preroll-drop has no filler audio. Caller publishes utterance → silence for the full Fish TTS window (~5-7s) → reply audio. User-perceived TTFA on turn 1 is much worse than turns 2-10. p95 across the bench is dominated by turn 1.
Root cause: `worker.py:825-828, 868-871` — `filler_state["turns_seen"] <= 1` skip was specifically because "pre-roll already gave the caller audio". With no preroll, that comment is now wrong; the skip leaves turn 1 with no bridge.
Surgical workaround: change `if filler_state["turns_seen"] <= 1: return` to `if filler_state["turns_seen"] < 1: return` (i.e. fire on first user turn too) — or gate on the same `PRISM42_PREROLL_DROPPED` env. NOTE: user said one-line worker.py change only; recommend leaving worker.py alone and accepting that turn 1 has no filler this cycle, then fixing in cycle-2b. Document the asymmetry in the bench report.
Source: `~/prism42/agents/livekit/worker.py:825-828, 868-871`

## #4 — Parakeet STT cold-start swallows first ~500-1000ms of caller audio on turn 1 (silent test pass risk)
Symptom: Turn 1 shows `t_stt_ms` higher than turns 2-10 (first finalized transcript is delayed; first chars are missing). Reply may be on-topic enough to look "non-empty" but actually responds to a truncated utterance ("chest pain shortness breath" → "pain shortness breath"). Glasswing's tested-loop (proper assertion on transcript content) catches this; an exit-code-only check does not.
Root cause: `session.say(preroll_text)` historically forced the audio output pipeline to warm up before the caller spoke. Without it, the first frames hit a cold STT path; livekit-agents 1.5.6's NVIDIA Parakeet plugin defers stream creation until the first inbound frame. Combined with VAD's start-of-speech threshold, the leading consonants of the very first utterance can be dropped.
Surgical workaround: keep the STAGE D 0.5s pre-publish sleep (failure mode #2) — it gives the STT pipeline time to warm without speaking. Do NOT drop STAGE D to 0s.
Source: AgentSession state transition at `~/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/agent_session.py:799-800` (state goes "listening" only at end of `start()`, after `_forward_audio_task` is wired)

## #5 — `/prism42/livekit` web client connection appears to hang ("connecting forever") because no agent-spoken cue
Symptom: Synthetic 10/10 passes, but a real browser smoke (or the public demo) shows a spinner/blank state for the full Fish TTFB window because the web UI was relying on `participant_connected` + first audio frame to flip from "connecting…" to "live". Without preroll, the first audio frame is the actual reply — 5-7s after the user starts talking, which feels broken.
Root cause: `worker.py:778 ctx.wait_for_participant()` returns as soon as the caller participant joins; the LiveKit room state is "agent has joined" the moment `session.start()` returns and the agent participant is published — no audio required. The web UI's "ready" signal is a frontend choice, not a server-side requirement. But if the existing UI keys off `track_subscribed → first non-silent frame`, that's now multi-second-delayed.
Surgical workaround: out-of-scope (frontend change) — but watch `worker.log` for `participant_connected` arriving before any preroll-spoken event. If a real-browser smoke shows hang, the fastest server-side fix is `await session.say("", allow_interruptions=True)` — empty string forces the TTS pipe + audio track publication without any audible greeting (UI's "first frame" ready-signal fires on the silent-frame).
Source: `~/prism42/agents/livekit/worker.py:778-806`; LiveKit Agents 1.5.6 `RoomIO.start()` publishes the agent participant before any `say()` call

---

## Defensive grep watchlist (for the cycle-2a executor to monitor in worker.log during their bench)

- `preroll.spoken` — should NOT appear in cycle-2a (if it does, the line wasn't actually dropped). Indicates the change didn't land.
- `preroll.skipped_caller_spoke_first` / `preroll.skipped_caller_spoke_race` — should NOT appear (if dropped fully, the skip-paths shouldn't fire either). If these appear, drop was partial.
- `preroll.failed` — should NOT appear; if it does, the dropped code is still being hit and erroring.
- `filler.spoken` count per session — expect 0 on turn 1 (failure mode #3), 1 on turns 2-10. If turn-1 has `filler.spoken`, the worker.py one-line change broke the skip-first-turn gate.
- `overlap.early_llm_trigger` — should fire on every turn including turn 1 (preemptive gen does NOT depend on preroll). If turn 1 is missing this log, failure mode #4 is biting (cold STT swallowed the early chars).
- `participant_connected` followed by >2s gap before first `tts.first_byte` — failure mode #5 indicator (real-browser hang risk).
- `received user transcript` with `transcript_delay >0.8` on turn 1 specifically — failure mode #4 indicator (Parakeet cold-start). Compare turn-1 transcript_delay against turns 2-10 median.
- `VERDICT: pre-roll never spoke (TTS broken)` in synthetic_caller stdout — failure mode #1. If 10/10 turns print this verdict, fix the harness assertion before re-running.

## Sources consulted
- `~/prism42/agents/livekit/worker.py:670-820` (preroll emit + filler bridge)
- `~/prism42/agents/livekit/synthetic_caller_full.py` end-to-end (assertion + STAGE D sleep)
- `~/prism42/agents/livekit/bench_b300.py:1-120, 240-310` (10-turn loop is N fresh sessions, not one session with N turns)
- `~/prism42/agents/livekit/.venv/lib/python3.14/site-packages/livekit/agents/voice/agent_session.py:594-810` (AgentSession.start does NOT require first say() to enter listening)
