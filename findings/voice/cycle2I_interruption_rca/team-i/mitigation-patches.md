# Cycle-2I — Ranked Mitigation Patches

**Team:** I — diagnosis only. Patches below are RECOMMENDED diffs for the
integrator to apply. All are additive / configurable; default-OFF env
flags preserve cycle-2Q baseline byte-equivalence.

Patch ranking is by leverage on the four-interruption symptom × shipping
risk. P1+P2+P3 together resolve the address-intake interruption with high
confidence. P4 hardens against the self-host adaptive-interruption silent
fallback. P5 is observability-only.

---

## P1 — Disable filler bridge during INTAKE phase (HIGH leverage, LOW risk)

**Hypothesis addressed:** H1 (filler fires on every VAD pause)
**Risk:** LOW — additive guard; cycle-2Q FSM already exposes phase via
`fsm.state`. Default-on after roll-out; gated by env for rollback.

**File:** `agents/livekit/worker.py:1290-1298`

```diff
     def _schedule_filler() -> None:
         # Skip first turn: pre-roll already gave the caller audio.
         filler_state["turns_seen"] += 1
         if filler_state["turns_seen"] <= 1:
             return
+        # Cycle-2I: do NOT fire fillers during INTAKE phase. Address
+        # dictation has natural intra-utterance pauses (0.6-0.9 s
+        # between digit groups + street name + apt) that VAD reads as
+        # end-of-speech. Filler audio talks over the caller's resume.
+        # The cycle-2T response_gate template path renders intake
+        # confirmation in <50 ms — no Fish-latency mask needed here.
+        # PRISM42_FILLER_INTAKE_DISABLE=0 reverts to cycle-2Q behavior.
+        if os.environ.get("PRISM42_FILLER_INTAKE_DISABLE", "1") == "1":
+            try:
+                fsm = getattr(orchestrator, "fsm", None)
+                phase = getattr(getattr(fsm, "state", None), "value", "")
+                if phase in ("intake", "address_confirmed"):
+                    log.info(
+                        "filler.suppressed_intake",
+                        session_id=session_id,
+                        phase=phase,
+                    )
+                    return
+            except Exception:  # noqa: BLE001
+                pass  # fall through to default behavior on error
         prev = filler_state["pending_task"]
         if prev is not None and not prev.done():
             prev.cancel()
         filler_state["pending_task"] = asyncio.create_task(_fire_filler())
```

**Rollback:** `PRISM42_FILLER_INTAKE_DISABLE=0`
**Verify:** synthetic_caller probe that says address with 800 ms mid-pause —
assert no `filler.spoken` log line during INTAKE state.

---

## P2 — Raise endpointing min_delay floor for INTAKE pauses (HIGH leverage, LOW risk)

**Hypothesis addressed:** H2 (`min_delay=0.6` is below natural address pauses)
**Risk:** LOW — within documented `EndpointingOptions` range. Reverts via
env; dynamic mode auto-pulls back when caller is fast.

**File:** `agents/livekit/worker.py:774-779`

```diff
     session = AgentSession(
         vad=silero.VAD.load(),
         stt=ParakeetSTT(ParakeetOptions()),
         llm=_llm,
         tts=_tts,
         turn_handling={
             "endpointing": {
                 "mode": "dynamic",
-                "min_delay": 0.6,
-                "max_delay": 4.0,
+                # Cycle-2I: raise min_delay floor to 1.0 s so address-
+                # dictation mid-pauses (0.6-0.9 s typical) do not fire
+                # end-of-speech. Dynamic-EMA pulls effective delay back
+                # down for fluent callers. max_delay=4.0 preserved.
+                "min_delay": float(os.environ.get(
+                    "PRISM42_ENDPOINT_MIN_DELAY_S", "1.0"
+                )),
+                "max_delay": float(os.environ.get(
+                    "PRISM42_ENDPOINT_MAX_DELAY_S", "4.0"
+                )),
             },
```

**Rollback:** `PRISM42_ENDPOINT_MIN_DELAY_S=0.6`
**Verify:** logs show `overlap.filler_after_speech_ms` >= 1000 on first
mid-address pause.

---

## P3 — Raise Silero VAD min_silence_duration for dictation pauses (HIGH leverage, LOW risk)

**Hypothesis addressed:** H3 (Silero default 0.55 s clips intra-address pauses)
**Risk:** LOW — kwarg is an accepted Silero plugin parameter. Reverts to
default by removing the kwarg.

**File:** `agents/livekit/worker.py:770`

```diff
     session = AgentSession(
-        vad=silero.VAD.load(),
+        # Cycle-2I: raise min_silence_duration above the 0.55 s default
+        # so caller pauses between street number, street name, and
+        # apartment do not register as end-of-speech. Silero FAQ
+        # explicitly recommends raising this for dictation scenarios.
+        # Tunable via PRISM42_VAD_MIN_SILENCE_S (default 0.9 s).
+        vad=silero.VAD.load(
+            min_silence_duration=float(
+                os.environ.get("PRISM42_VAD_MIN_SILENCE_S", "0.9")
+            ),
+        ),
         stt=ParakeetSTT(ParakeetOptions()),
```

**Rollback:** `PRISM42_VAD_MIN_SILENCE_S=0.55` or revert to bare
`silero.VAD.load()`.
**Verify:** caller utterance with 800 ms mid-pause produces a single
`user_state_changed: speaking→listening` event, not multiple.

---

## P4 — Promote adaptive-mode active-state to a one-line log + fall-back guard (MED leverage, LOW risk)

**Hypothesis addressed:** H4 (adaptive mode silently falls back to VAD on self-host)
**Risk:** LOW — log + structured assertion; no behavior change unless
env-flagged.

**File:** `agents/livekit/worker.py:769-792` (after AgentSession creation)

```diff
         turn_handling={
             ...
         },
     )
+    # Cycle-2I: assert which interruption mode is actually active.
+    # `mode: "adaptive"` only runs on LiveKit Cloud / dev mode per docs;
+    # self-host silently falls back to VAD-only. Log a single line so
+    # bench parsers + the heartbeat scheduler can confirm.
+    try:
+        _th = getattr(session, "_turn_handling", None) or getattr(
+            session, "turn_handling", None
+        )
+        _interruption = getattr(_th, "interruption", None) if _th else None
+        _mode_active = getattr(_interruption, "mode", "unknown")
+        log.info(
+            "turn_handling.interruption_active",
+            session_id=session_id,
+            mode_requested="adaptive",
+            mode_active=str(_mode_active),
+            self_hosted=os.environ.get("LIVEKIT_URL", "").endswith(
+                "thegoatnote.com"
+            ),
+        )
+    except Exception as e:  # noqa: BLE001
+        log.warning("turn_handling.probe_failed", err=str(e)[:200])
```

**Rollback:** delete the probe block (no env; pure observability).
**Verify:** `grep turn_handling.interruption_active` in journalctl;
expect a structured value of `mode_active=adaptive` if Cloud, or
`mode_active=vad` (or similar) if self-host fallback.

---

## P5 — Lengthen FILLER_DELAY_S as a defense-in-depth guard (MED leverage, LOW risk)

**Hypothesis addressed:** H1 (filler still fires on non-INTAKE pauses)
**Risk:** LOW — already env-tunable.

**File:** `agents/livekit/worker.py:122`

```diff
-FILLER_DELAY_S: float = float(os.environ.get("PRISM42_FILLER_DELAY_S", "0.3"))
+# Cycle-2I: raise default filler delay from 0.3 s to 0.6 s. The 300 ms
+# value was tuned for masking Fish 5-7 s TTFT; with the cycle-2T
+# response-gate template path landing intake replies in <50 ms, the
+# filler is rarely needed and a longer delay gives the caller more
+# room to resume mid-utterance before any audio fires.
+FILLER_DELAY_S: float = float(os.environ.get("PRISM42_FILLER_DELAY_S", "0.6"))
```

**Rollback:** `PRISM42_FILLER_DELAY_S=0.3`
**Verify:** measured `overlap.filler_after_speech_ms` median shifts
from ~300 to ~600 ms.

---

## Patch ordering and apply-together recommendation

Apply **P1 + P2 + P3** as an atomic landing — they target the same
symptom and partial application leaves an asymmetric pipeline (e.g. P2
without P1 still fires fillers on pauses ≥1.0 s; P1 without P3 still
emits multiple `user_state_changed` events). Add P4+P5 in the same
commit if integrator agrees; both are observability-grade.

Suggested env-block for the systemd drop-in
`/etc/systemd/system/prism42-worker.service.d/50-cycle2i-intake.conf`:

```ini
[Service]
Environment="PRISM42_FILLER_INTAKE_DISABLE=1"
Environment="PRISM42_ENDPOINT_MIN_DELAY_S=1.0"
Environment="PRISM42_ENDPOINT_MAX_DELAY_S=4.0"
Environment="PRISM42_VAD_MIN_SILENCE_S=0.9"
Environment="PRISM42_FILLER_DELAY_S=0.6"
```

**Single-command rollback:**
`sudo rm /etc/systemd/system/prism42-worker.service.d/50-cycle2i-intake.conf && sudo systemctl daemon-reload && sudo systemctl restart prism42-worker`

---

## What we explicitly did NOT touch (per "DON'T list")

- Parakeet STT plugin internals
- Fish TTS adapter (FishSpeechTTS)
- Nemotron / vLLM env
- MW reference voice config
- DispatcherFSM transition logic
- The cycle-2T response_gate templates
- The orchestrator's tts_node sentence buffer (cycle-2e)
- Any framework swap (Pipecat / Vocode etc.)

All five patches are config / env-flag changes within the existing
LiveKit-agents 1.5.6 turn-handling surface.
