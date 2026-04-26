# Cycle-2I — Verification Plan

**Team:** I
**Mode:** Prove the cycle-2I patches eliminate address-intake interruption
WITHOUT introducing dead-air on intentional end-of-speech pauses.

---

## Phase 0 — Sanity (10 min, before patches)

Goal: confirm the bug reproduces with current cycle-2Q config.

```bash
# On B300 pod
journalctl -u prism42-worker -f --since="1 min ago" | grep -E "(filler|user_state_changed|overlap)"
```

In another shell, hit the live URL `https://prism42-console.vercel.app/prism42/livekit`,
press "Start Call" and slowly dictate:

```
Five zero one two ... <0.8 s pause> ... East River Road ... <0.8 s pause> ... apartment two B
```

**Expect (current bug):**
- 3-4 `filler.spoken` log lines during a single utterance
- Audio interrupts caller mid-word

**If observed:** baseline confirmed. Apply patches. Otherwise: bug is
environment-specific or transient — re-bench with synthetic_caller to
get a deterministic repro.

---

## Phase 1 — Synthetic_caller probe with mid-utterance pause (BLOCKING)

Goal: deterministic regression test that asserts no filler / interruption
fires during a 3-second utterance with a 500 ms mid-pause.

**File:** New script `agents/livekit/tests/probe_address_intake.py`
(integrator can place anywhere; recommendation below for parity with
existing synthetic_caller_full.py)

```python
"""Probe: caller dictates a multi-token address with mid-utterance pause.

Asserts:
  1. Fewer than 1 `filler.spoken` event during the utterance.
  2. Zero `interruption_started` events on the caller side during the
     utterance window.
  3. The `user_state_changed: speaking->listening` events count is <=2
     across the full utterance (one per real silence floor cross, not
     one per breath).

Designed to run against a worker connected to a test LiveKit room. The
audio is synthesized from a WAV via the LiveKit `LocalAudioTrack`, so
no real mic / speaker is needed — fully CI-runnable.
"""
from __future__ import annotations

import asyncio
import json
import time
import wave
from pathlib import Path

import numpy as np
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

# 3-second utterance: "five zero one two" + 500ms silence + "East River Road"
# Synthesized via Fish TTS once and cached as a fixture.
FIXTURE = Path(__file__).parent / "fixtures" / "address_dictation_with_pause.wav"

PROBE_DURATION_S = 3.0
PAUSE_START_S = 1.2
PAUSE_END_S = 1.7  # 500 ms mid-utterance pause

# Tolerated ranges
MAX_FILLERS = 0
MAX_USER_STATE_CYCLES = 1  # speaking->listening transitions

async def probe(room_url: str, api_key: str, api_secret: str) -> dict:
    """Connect, publish the fixture, watch the data channel + logs."""
    token = (
        AccessToken(api_key, api_secret)
        .with_identity("probe-caller")
        .with_grants(VideoGrants(room_join=True, room="probe-intake-test"))
        .to_jwt()
    )
    room = rtc.Room()
    await room.connect(room_url, token)

    # Load fixture
    with wave.open(str(FIXTURE), "rb") as f:
        sr = f.getframerate()
        nchan = f.getnchannels()
        pcm = f.readframes(f.getnframes())

    # Publish as audio track
    source = rtc.AudioSource(sr, nchan)
    track = rtc.LocalAudioTrack.create_audio_track("probe", source)
    await room.local_participant.publish_track(track)

    # Stream the fixture in 20 ms chunks
    samples_per_frame = sr * 20 // 1000
    bytes_per_frame = samples_per_frame * 2 * nchan
    t0 = time.monotonic()
    for i in range(0, len(pcm), bytes_per_frame):
        chunk = pcm[i : i + bytes_per_frame]
        if len(chunk) < bytes_per_frame:
            chunk += b"\x00" * (bytes_per_frame - len(chunk))
        frame = rtc.AudioFrame(
            data=chunk, sample_rate=sr, num_channels=nchan,
            samples_per_channel=samples_per_frame,
        )
        await source.capture_frame(frame)
        await asyncio.sleep(0.020)
    elapsed = time.monotonic() - t0

    # Wait a beat for any trailing filler/say to land in logs
    await asyncio.sleep(2.0)
    await room.disconnect()
    return {"elapsed_s": elapsed}


def assert_logs_clean(journal_lines: list[str], session_id: str) -> tuple[bool, list[str]]:
    """Parse log lines for the assertions."""
    n_filler = sum(1 for L in journal_lines if "filler.spoken" in L and session_id in L)
    n_state = sum(
        1 for L in journal_lines
        if "user_state_changed" in L
        and session_id in L
        and "speaking" in L and "listening" in L
    )
    fails = []
    if n_filler > MAX_FILLERS:
        fails.append(f"FAIL: {n_filler} fillers fired (max={MAX_FILLERS})")
    if n_state > MAX_USER_STATE_CYCLES:
        fails.append(f"FAIL: {n_state} speaking->listening transitions (max={MAX_USER_STATE_CYCLES})")
    return (not fails), fails
```

**Fixture generation (one-time):** synthesize the WAV via a single Fish
or Cartesia call with the exact phoneme sequence above, save it under
`agents/livekit/tests/fixtures/address_dictation_with_pause.wav`. Hash
it (sha256) and pin the hash in CI.

---

## Phase 2 — Live verification (5 min, post-patch, manual)

Same as Phase 0 but with patches applied. Hit the URL, dictate the same
utterance, watch logs.

**Pass criteria:**
- ZERO `filler.spoken` lines during the address utterance
- ONE `user_state_changed: speaking->listening` event at the end
- ONE `overlap.tts_first_audio_after_speech_ms` line with the
  response_gate template firing
- Caller hears the confirmation reply 1.0-1.5 s after they actually
  finished speaking — NOT during pauses

```bash
# Run on B300 pod
journalctl -u prism42-worker -f --since="1 min ago" | \
    grep -E "(filler|user_state_changed|overlap|response_gate.decision|turn_handling.interruption_active)"
```

---

## Phase 3 — Negative control (5 min)

Goal: prove we did NOT introduce dead-air on intentional end-of-speech.

Caller fluently says "five zero one two East River Road" with NO mid
pause and stops. Stopwatch:

**Pass criteria:** dispatcher response begins ≤2.0 s after caller stops
(target ~1.5 s — `min_delay=1.0` + STT finalize ~300 ms + template
render <50 ms + TTS first frame ~100 ms).

If response begins >3.0 s after caller stop → `min_delay` is too
aggressive; integrator can ratchet `PRISM42_ENDPOINT_MIN_DELAY_S` down
to 0.8.

---

## Phase 4 — Latency regression (5 min)

Re-run cycle-2T baseline bench (`scripts/bench_b300.py`) post-patch.

**Pass criteria:** p95 end-to-end ≤1.7 s (cycle-2Q baseline + 200 ms
budget for the raised `min_delay`). If p95 ≥2.0 s, dial `min_delay`
back to 0.8.

---

## Single-command verify

After patches land, the integrator can run:

```bash
PRISM42_PROBE_URL=wss://livekit.thegoatnote.com \
PRISM42_API_KEY=$LIVEKIT_API_KEY \
PRISM42_API_SECRET=$LIVEKIT_API_SECRET \
.venv/bin/python agents/livekit/tests/probe_address_intake.py \
  && echo "VERIFIED: cycle-2I intake interruption fix"
```

Exit 0 == address-intake interruption no longer fires.
Exit 1 + structured log lines from `assert_logs_clean()` == regression.
