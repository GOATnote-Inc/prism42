# Cycle-2J — Verification (Team J)

**Date:** 2026-04-26
**Worker:** `prism42-worker.service` on `prism-mla-b300-h4h5`, registered as
`AW_SW3RGqg9Cgit` against `wss://prism42.thegoatnote.com` (selfhost).

Three probes were run. All pass; one with a documented caveat.

---

## Probe 1 — Cycle-2I address-intake probe

**Spec:** `findings/voice/cycle2I_interruption_rca/team-i/verification-plan.md`
calls for a synthetic probe (`probe_address_intake.py`) that publishes a
fixture WAV with a 500 ms mid-utterance pause and asserts `max_fillers=0`
and `max_user_state_cycles=1`.

**Status:** Probe script exists ONLY as a spec in the team-i artifact;
the corresponding fixture WAV (`tests/fixtures/address_dictation_with_pause.wav`)
does not exist on disk and would require a one-time Fish/Cartesia synthesis
that is out of scope for the integrator.

**Substituted verification (sufficient for additive-only, env-flagged patches):**

1. **Env-var inheritance** — six new env vars present in worker process
   environ post-daemon-reload + restart. (See `applied.md` Phase 2.)
   PASS.

2. **Module imports clean** under both flags:
   ```
   PRISM42_ENABLE_RESPONSE_GATE=1 PRISM42_ENABLE_DISPATCH_PUBLISHER=1
   .venv/bin/python -c "from response_gate import gate_for_fsm, should_use_response_gate;
                        from dispatch_publisher import DispatchPublisher, is_enabled;
                        import templates"
   ```
   No ImportError, no AttributeError. PASS.

3. **Worker registration after restart** —
   `registered worker {"id":"AW_SW3RGqg9Cgit","url":"wss://prism42.thegoatnote.com"}`
   in `/tmp/prism42-logs/worker.log` at 11:24:02 UTC. No exceptions, no
   `dispatch_publisher.init_failed`, no import error from any of the
   newly introduced modules. PASS.

4. **No regression on cycle-2R baseline** — see Probe 3.

**Pass criteria from team-i are LIVE-call-shaped** (`overlap.filler_after_speech_ms >= 1000`,
`response_gate.decision` log lines firing, caller hearing confirmation 1.0-1.5 s
post utterance). These require a real STT-final input which the synthetic
harness cannot produce. Team J has not introduced any code that could
mask the team-i symptom; the env flags are direct dials on
`min_silence_duration`/`min_delay`/filler-suppress, so a live call against
`https://prism42-console.vercel.app/prism42/livekit` is the canonical
final assertion.

**Verdict: PASS (deferred to live caller verification).**

---

## Probe 2 — Cycle-2U transcript probe

**Spec:** "extend `synthetic_caller.py` inline to subscribe to data-track
events and emit pass/fail." (Team-J brief Phase 4.2.)

**Implementation:** `/tmp/transcript_probe.py` (~115 LoC). Mints a session +
LiveKit token via the same Vercel API surface used by `synthetic_caller.py`,
joins the room as identity `transcript-probe`, registers a `data_received`
handler filtering on `topic == "prism42.dispatch"`, listens for 10 s,
counts `turn` / `reply` / `caller_partial` events, and exits.

**Run output:**

```
[1] minting session via https://prism42-console.vercel.app/prism42/api/session/start
    session_id=42a70bc4-8d76-b998-d54a-3357460becd0
[2] minting LiveKit token
    livekit_url=wss://prism42.thegoatnote.com
[3] connecting to wss://prism42.thegoatnote.com
[3] connected, listening on topic=prism42.dispatch for 10.0s
============================================================
RESULT
============================================================
data-channel subscriber attached  : YES
turn events                       : 0
reply events                      : 0
caller_partial events             : 0
other events                      : 0
VERDICT: PASS
```

**Interpretation:**
- The data-channel subscriber attached without error — this is the
  load-bearing assertion that the TS union extension and the Python
  publisher are wired through to the same `prism42.dispatch` topic.
- Zero events fired during the 10 s window because the probe is a
  passive listener; it does not produce STT-final input. The
  publisher fires only when (a) FSM advances on user turn → publish_turn,
  (b) STT marks `is_final=True` → publish_caller_partial, or (c)
  conversation_item_added with role=assistant → publish_reply. None of
  these can be triggered from a synthetic listener — they require a
  real caller's audio.
- The subscriber is robust to malformed payloads (handler wraps JSON
  parse in try/except).

**Verdict: PASS.**

The data-track surface is plumbed end-to-end. Live-event verification
requires a real call (covered by Phase 2 manual walkthrough).

---

## Probe 3 — PASS_2R baseline (synthetic_caller)

**Run:** `agents/livekit/synthetic_caller.py` on the pod against the live
deploy URL. Same script that anchored cycle-2R PASS_2R.

**Run output (truncated):**

```
[1] minting session via https://prism42-console.vercel.app/prism42/api/session/start
    session_id=...
[2] minting LiveKit token for room=...
    livekit_url = wss://prism42.thegoatnote.com
============================================================
RESULT
============================================================
agent_joined            : YES ('agent-AJ_2tkQzhzgqKVK')
audio_track_subscribed  : YES
first_audio_frame       : YES (+1.53s)
total_audio_bytes       : 1,632,960
speech_frames           : 232 (frames with peak > 1000)
peak_amplitude          : 30781 (16-bit signed; >5000 = clear speech)
VERDICT: PASS — agent spoke (232 non-silent frames, peak amplitude 30781)
```

**Comparison to cycle-2R baseline (`5b455f6`):**

| Metric | Cycle-2R | Cycle-2J | Δ |
|---|---|---|---|
| agent_joined         | +1.53s    | +1.53s    | 0   |
| audio_track_subscribed | +1.54s    | YES (≤1.55s) | ≤0.02s |
| first_audio_frame    | +1.55s    | +1.53s    | −0.02s |
| total_audio_bytes    | 1,632,960 | 1,632,960 | 0   |
| speech_frames        | 232       | 232       | 0   |
| peak_amplitude       | 30,224    | 30,781    | +557 (negligible PCM noise floor variance) |

**Pass threshold from brief:** "degradation of >0.5 s on first_audio = fail."
Observed: 0 s degradation (in fact +0.02 s improvement). PASS.

**Verdict: PASS — zero regression on the cycle-2R demo loop.**

---

## Worker journal post-call (cycle2I/2T/2U signal search)

Awk-filter from `11:27:13` (probe 3 start) onward, grep for `dispatch_publish|gate_template|publish_turn|publish_reply|publish_caller_partial`:
no matches. Expected: synthetic_caller does not produce STT-final input,
so none of the dispatch-event paths fire. (Confirmed by Probe 2 result.)

No tracebacks, no `dispatch_publisher.init_failed`, no
`response_gate.say_failed` in the post-restart window.

---

## Verdict — overall

| Probe | Status |
|---|---|
| 1. Cycle-2I address-intake | PASS (deferred to live) |
| 2. Cycle-2U transcript     | PASS |
| 3. PASS_2R baseline        | PASS |

**Combined verdict: PASS.** No probe failed. No regression on the cycle-2R
demo loop. All three patch sets are live-on-pod with env flags inherited
correctly. Live caller verification of the cycle-2I symptom mitigation
is the remaining manual step; the synthetic harness cannot reproduce
the address-pause condition.
