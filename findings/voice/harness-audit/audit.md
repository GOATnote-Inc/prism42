# Harness audit — synthetic_caller_full.py — 2026-04-25

Read-only audit of `/Users/kiteboard/prism42/agents/livekit/synthetic_caller_full.py`
(271 lines). Goal: complete inventory of measurement biases, hardcoded sleeps,
hardcoded thresholds, race-condition assumptions, audio-thresholds, worker-
behavior coupling, and token/room/session coupling so cycle-2a (and beyond)
metrics are not contaminated.

Cycle-2a anticipator (`findings/voice/cycle-2a-anticipator/contingencies.md`)
already flagged two — both confirmed and merged into the table below as F1 and
F2 (no double-counting). All other findings are net-new from this pass.

## Summary

Total findings: 14
Findings that bias metrics LOWER (look artificially good): 0
Findings that bias metrics HIGHER (look artificially bad): 4 (F1, F8, F9, F11)
Findings that add NOISE / wall-clock floor: 4 (F2, F3, F4, F12)
Findings that are CONTRACT-COUPLING risk (silent break if upstream changes): 6 (F5, F6, F7, F10, F13, F14)

Highest-priority patch: F1 (line 254-256 hard-assertion `preroll_speech < 5 → return 4`) — every cycle-2a turn is currently mis-classified as "TTS broken" even when the voice path is healthy. Without F1, all other measurements are moot.

Recommended cycle-2a-debug action: apply the safe-to-apply patch bundle below (F1 + F2 + F8 + F9 + F11 + F12 fixes), re-run a 1-turn smoke against the live worker, then re-run the 10-turn bench. F3, F4, F5-F7, F10, F13, F14 stay as documented assumptions — flagged for cycle-2b calibration but not patched in this pass.

## Findings table

| # | Type | Line(s) | Description | Bias direction | Patch (safe-now?) |
|---|---|---|---|---|---|
| F1 | hard-assertion | 254-256 | `if preroll_speech < 5: return 4` (TTS-broken verdict) | HIGHER (false-fail on cycle-2a) | gate behind `PRISM42_HARNESS_REQUIRE_PREROLL` env, default off — SAFE |
| F2 | hardcoded sleep | 177 | `await asyncio.sleep(4.0)` STAGE D pre-roll wait | NOISE (+4s wall-clock floor every turn) | env-tunable `PRISM42_HARNESS_PREROLL_WAIT_S`, default 0.5 — SAFE |
| F3 | magic number | 146 | `publish_end_at[0] + 0.3` echo-suppress window | NOISE (drops first 300ms of agent reply if reply starts <300ms after caller-end) | leave as-is, document — needs calibration test |
| F4 | hardcoded sleep | 233 | `await asyncio.sleep(5.0)` post-detect "confirm sustained speech" | NOISE (+5s wall-clock per turn after detection) | env-tunable, default 1.0 — SAFE |
| F5 | timeout | 161 | `wait_for(agent_joined, timeout=15)` | HIGHER on slow worker startup (returns exit 2 on transient delay) | env-tunable, default 30 — SAFE |
| F6 | timeout | 169 | `wait_for(agent_audio_track_subscribed, timeout=15)` | HIGHER on slow worker startup | env-tunable, default 30 — SAFE |
| F7 | timeout | 211 | `reply_deadline = publish_end + 25.0` | HIGHER if LLM TTFT + Fish TTS exceeds 25s (rare but real) | env-tunable, default 30 — SAFE |
| F8 | amplitude threshold | 141 | `if peak > 1000: speech_frames[0] += 1` | HIGHER (can miss quiet TTS or low-volume Fish output) | document; needs measured calibration against Fish output before tuning |
| F9 | amplitude threshold | 215 | `if audio_after_publish_end_amp_max[0] > 1000` (reply detection) | HIGHER (same — quiet reply marks as "no reply") | document; needs measured calibration |
| F10 | race | 134-150 | `_drain` task spawns inside event handler — frames before subscription complete are dropped | NOISE (under-counts preroll on slow networks) | leave as-is, document — needs RTC behavior test |
| F11 | hard-assertion | 251-253 | `if not first_audio_at: return 4` (any audio at all) | HIGHER (false-fail if track subscribes but first frame is delayed) | leave as-is — this is correct logic when `audio_track_subscribed` already fired |
| F12 | hardcoded sleep | 205 | `await asyncio.sleep(0.01)` per 10ms publish chunk | NOISE (publish wall-clock = 1× audio duration; deliberate but documented as 10ms) | leave as-is — this is the actual publish pacing, not measurement |
| F13 | worker coupling | 123 | `if p.identity != "synthetic-caller"` (anyone-but-me = "the agent") | HIGHER if a 3rd participant joins (e.g. another synthetic caller, or web client) | leave as-is — document the assumption |
| F14 | session coupling | 99-104 | `session_id` minted from Vercel `/prism42/api/session/start`; token from `/prism42/api/livekit-token` | UNSTABLE if Vercel routes change shape, hard error masks worker-side bugs | leave as-is — document; the contract is owned by Vercel |

---

## Detailed findings

### F1 — Hard-assertion `preroll_speech < 5 → exit 4` (line 254-256)

**Current behavior.** After STAGE F, if fewer than 5 frames with peak >1000 were captured during the 4-second STAGE D window, the harness prints `VERDICT: pre-roll never spoke (TTS broken)` and exits 4. This was correct cycle-1 logic: `worker.py` always called `session.say(preroll_text)` early; absence of preroll meant TTS was broken.

**Cycle-2a context.** Worker.py:799 now logs `preroll.disabled_for_demo` and intentionally does NOT call `session.say()`. The `preroll_speech < 5` branch fires on every turn regardless of voice-path health, returning exit 4 when the truth is exit 0.

**Bias direction.** HIGHER (artificially bad). Every cycle-2a turn marks as "TTS broken" while the actual reply path may be 100% healthy. `bench_b300.py:215` records the verdict line, then `parse_window` short-circuits — every metric downstream of this assertion is `None` or zero.

**Surgical patch.** Gate behind opt-in env var. Default off so cycle-2a measurements come through; cycle-1 / regression checks can re-enable explicitly:

```python
if preroll_speech < 5 and os.environ.get("PRISM42_HARNESS_REQUIRE_PREROLL"):
    print("VERDICT: pre-roll never spoke (TTS broken)")
    return 4
```

**Safe-to-apply now?** YES. Flips a false-negative to a permissive-by-default check; preserves the original semantics for callers that want it.

---

### F2 — Hardcoded `await asyncio.sleep(4.0)` STAGE D (line 177)

**Current behavior.** After audio track subscribed, sleep 4 seconds before publishing the caller utterance. Comment says "wait for pre-roll".

**Why it exists.** Cycle-1 needed time for `session.say(preroll_text)` to flush so the harness could measure preroll amplitude. Failure mode #4 in `cycle-2a-anticipator/contingencies.md` also notes the 0.5s lower bound: Parakeet STT cold-start may swallow leading audio if the harness publishes immediately.

**Bias direction.** NOISE. Adds a fixed 4s wall-clock floor per turn regardless of preroll presence. The +6s offset noted in cycle-1 is exactly this 4s + ~2s connect/agent-join (line 156-167). User-perceived "publish → first useful audio" looks unchanged because the harness pads in time the user doesn't measure.

**Surgical patch.** Make tunable; default 0.5s (the Parakeet warm-up margin from failure mode #4):

```python
preroll_wait = float(os.environ.get("PRISM42_HARNESS_PREROLL_WAIT_S", "0.5"))
print(f"\n=== STAGE D: wait for pre-roll ({preroll_wait}s) ===")
await asyncio.sleep(preroll_wait)
```

**Safe-to-apply now?** YES. Default 0.5s preserves STT warmup; environments that need 4s can opt back in.

---

### F3 — Echo-suppress window `+ 0.3` seconds (line 146)

**Current behavior.** The drain task only counts post-publish-end audio if `time.time() > publish_end_at[0] + 0.3`. This is to keep the harness's own published audio (loopback echo from LiveKit's track-mux, in-room audio, etc.) from being counted as "agent reply".

**Why it exists.** Without this, the trailing edge of the caller utterance would be detected as "agent replied at 0ms after publish-end" — a false positive.

**Bias direction.** NOISE. If the agent (e.g. with preemptive generation) starts responding *during* the caller utterance and the first reply audio frame lands within 300ms of publish-end, those frames are NOT counted. `reply_first_speech_at` would be later than reality.

**Surgical patch.** None applied this cycle. The 0.3s value is uncalibrated (no comment, no measurement). It should be replaced with measured loopback-echo duration from the LiveKit Cloud media plane. Document as cycle-2b calibration.

**Safe-to-apply now?** NO — needs a measured loopback echo characterization run.

---

### F4 — `await asyncio.sleep(5.0)` "confirm sustained speech" (line 233)

**Current behavior.** After the harness detects a non-zero reply amplitude, it sleeps 5 more seconds "to confirm sustained speech" before disconnecting.

**Why it exists.** Probably to catch spurious single-frame spikes that aren't real speech. But the harness doesn't actually re-validate after the sleep — it just proceeds to print results. The 5s is pure wall-clock burn.

**Bias direction.** NOISE. Adds 5s per successful turn. On a 10-turn bench, that's 50s of extra wall-clock with no measurement output.

**Surgical patch.** Make tunable; default 1.0s (enough to catch the rest of the first reply word; not enough to burn benches):

```python
confirm_wait = float(os.environ.get("PRISM42_HARNESS_REPLY_CONFIRM_S", "1.0"))
if reply_first_speech_at:
    print(f"[stage F] listening {confirm_wait}s more to confirm sustained speech ...")
    await asyncio.sleep(confirm_wait)
```

**Safe-to-apply now?** YES. Cuts bench wall-clock; doesn't change measurement semantics (we still verify `audio_after_publish_end_amp_max[0] > 1000` once, which already happened).

---

### F5 — `wait_for(agent_joined.wait(), timeout=15)` (line 161)

**Current behavior.** If the agent doesn't join the room within 15 seconds of harness connect, exit 2 ("agent never joined").

**Bias direction.** HIGHER on a slow-startup worker (cold container, cold Parakeet/Fish models, cold LLM warmup). 15s is borderline for a fully-cold path: livekit-agents 1.5.6 + Parakeet plugin first-frame init can spike >10s on cold start.

**Surgical patch.** Make tunable; default 30s:

```python
join_timeout = float(os.environ.get("PRISM42_HARNESS_JOIN_TIMEOUT_S", "30"))
await asyncio.wait_for(agent_joined.wait(), timeout=join_timeout)
```

**Safe-to-apply now?** YES. Default 30s only matters on cold-start path; warm worker still joins in ~1-2s.

---

### F6 — `wait_for(agent_audio_track_subscribed.wait(), timeout=15)` (line 169)

**Current behavior.** Same shape as F5 but for the audio track subscription event.

**Bias direction.** HIGHER on slow track-subscribe (LiveKit Cloud SFU subscribe latency under load).

**Surgical patch.** Same env-tunable pattern:

```python
track_timeout = float(os.environ.get("PRISM42_HARNESS_TRACK_TIMEOUT_S", "30"))
await asyncio.wait_for(agent_audio_track_subscribed.wait(), timeout=track_timeout)
```

**Safe-to-apply now?** YES.

---

### F7 — `reply_deadline = publish_end + 25.0` (line 211)

**Current behavior.** If no reply audio detected within 25s after publish-end, the loop exits without setting `reply_first_speech_at` → exit 5.

**Bias direction.** HIGHER if the worker's LLM-TTFT + Fish TTFB occasionally exceeds 25s. The CLAUDE.md target is p95 < 1.5s end-to-end, so 25s is comfortable for healthy operation — but Fish has been observed at >10s tail latency in fish-fork-analysis. A 25s cap classifies legitimately-slow turns as exit 5.

**Surgical patch.** Make tunable; default 30s:

```python
reply_timeout = float(os.environ.get("PRISM42_HARNESS_REPLY_TIMEOUT_S", "30"))
reply_deadline = reply_window_start + reply_timeout
```

**Safe-to-apply now?** YES.

---

### F8 — Amplitude threshold `peak > 1000` for speech-frame counter (line 141)

**Current behavior.** A frame is counted as "speech" if max-abs-sample exceeds 1000 (int16, range ±32768). 1000/32768 = ~3% of full scale.

**Why this number?** No comment. The threshold is shared between preroll detection (F1) and reply detection (F9).

**Bias direction.** HIGHER (artificially bad) if Fish TTS output is quiet — the reply might be real audio at e.g. peak=800, registering as silence. Recently-touched `fish_speech_tts.py` and the fish-fork-analysis suggest Fish output amplitude varies with prompt length and voice config.

**Surgical patch.** None applied — this is a measurement threshold, and changing it without calibration could flip bias direction. Cycle-2b should record max-amplitude over a 1-minute Fish output sample and set the threshold to e.g. 5% of measured peak (probably much lower than 1000).

**Safe-to-apply now?** NO — needs a measured Fish output amplitude sample first. Note in cycle-2a output if reply_speech_amp_max consistently lands in the 500-1500 range (suggests threshold should drop).

---

### F9 — Amplitude threshold `peak > 1000` for reply detection (line 215)

**Current behavior.** Same threshold as F8, applied to `audio_after_publish_end_amp_max` to decide whether a reply was detected.

**Bias direction.** HIGHER for the same reason — quiet reply would be missed.

**Surgical patch.** Same as F8 — needs calibration first.

**Safe-to-apply now?** NO.

**Note:** F8 and F9 share a single magic number; should be a named constant once calibrated.

---

### F10 — `_drain` task spawned in event handler (line 134-150)

**Current behavior.** When `track_subscribed` fires, `asyncio.create_task(_drain())` is spawned. Frames that arrive *before* the create_task is scheduled (RTC events fire in the asyncio loop's event scheduler order) might be missed.

**Bias direction.** NOISE. Under-counts preroll on slow event-loop turns. In practice, livekit-rtc buffers recent frames and replays them to a new AudioStream — but this is implementation-detail-dependent.

**Surgical patch.** None this cycle. Document as a known harness limitation; needs an RTC-behavior test to confirm whether `rtc.AudioStream(track)` replays buffered frames or not.

**Safe-to-apply now?** NO — needs livekit-rtc behavior probe.

---

### F11 — `if not first_audio_at: return 4` (line 251-253)

**Current behavior.** If the drain task never recorded a single audio frame, exit 4.

**Bias direction.** Mild HIGHER risk — but only if `audio_track_subscribed` event fires (line 169 succeeds) yet no frames ever arrive. In current livekit-rtc, this is a real failure mode (track exists but is muted/empty), so the assertion is correct.

**Surgical patch.** None — this is correct logic. `agent_audio_track_subscribed.wait()` already passed, so any "no audio" outcome is genuinely a track-without-frames pathology.

**Safe-to-apply now?** N/A — keep as-is.

**Note:** The assertion ordering matters: F11 (line 251-253) fires BEFORE F1 (line 254-256), so even with F1 patched, "completely silent track" still correctly returns 4.

---

### F12 — `await asyncio.sleep(0.01)` per publish chunk (line 205)

**Current behavior.** The publish loop pushes 10ms audio chunks at 1× wall-clock speed (sleep 10ms after each chunk).

**Why it exists.** This is the actual publish pacing — LiveKit's `AudioSource.capture_frame` expects real-time pacing for proper jitter-buffer behavior. Push-too-fast can cause SFU to drop frames.

**Bias direction.** NOISE in the sense that a 5-second utterance takes 5 seconds to publish. But this is real-time correct, not arbitrary. The 0.01 matches `chunk_samples = TARGET_SR // 100` (10ms at 48kHz).

**Surgical patch.** None — this is the correct pacing. Document as "deliberate, matches chunk_samples".

**Safe-to-apply now?** N/A — keep as-is.

---

### F13 — Identity coupling `if p.identity != "synthetic-caller"` (line 123)

**Current behavior.** Anyone-but-me on `participant_connected` is treated as "the agent". The harness then takes their identity into `agent_identity[0]`.

**Bias direction.** HIGHER if a 3rd participant joins — e.g. another synthetic caller running concurrently, or a web client during a public-demo run. The 3rd identity gets recorded as `agent_identity[0]`, but the agent might also join, just second. The first non-synthetic-caller participant wins.

**Worker coupling.** The harness expects the agent's identity to be ANYTHING but `synthetic-caller`. Worker.py's identity scheme isn't pinned here — if worker.py ever publishes the agent under identity `synthetic-caller-2` or similar, this filter breaks silently.

**Surgical patch.** None — this is the LiveKit Agents 1.5.6 default behavior (agent identities are typically `agent-<uuid>` or similar). Document as an assumption: "harness assumes only one non-`synthetic-caller` participant in the room at any time".

**Safe-to-apply now?** N/A — would need a stricter identity-prefix check (e.g. `p.identity.startswith("agent-")`) but that couples to the worker-publish convention.

---

### F14 — Vercel-routed token mint (line 99-104)

**Current behavior.** The harness POSTs to `${VERCEL_BASE}/prism42/api/session/start` to mint a session, then to `${VERCEL_BASE}/prism42/api/livekit-token` to mint a JWT for that session.

**Bias direction.** UNSTABLE / contract-coupled. If Vercel's API routes change shape (e.g. response field rename `session_id` → `id`), the harness raises `KeyError` and exits with a Python traceback — masking any actual voice-path issue.

**Worker coupling.** This is more upstream-coupling: the harness depends on Vercel's routes being healthy AND on worker.py being able to recognize sessions minted via this path. If worker.py changes its session-recognition logic (e.g. requires a different metadata field), the harness still mints fine but the agent never joins.

**Surgical patch.** None — this is the correct contract surface. Add a try/except wrapping `_http_post` calls so the harness exits with a clear "Vercel route X failed: <body>" message instead of a raw Python KeyError. Defer to cycle-2b.

**Safe-to-apply now?** Could add error handling, but it changes harness output structure (current callers don't expect new error lines). Defer.

---

## Patch bundle

The following diff applies F1, F2, F4, F5, F6, F7 as a single patch. F3, F8, F9, F10, F13, F14 are documented assumptions and stay unchanged. F11, F12 are correct as-is.

Patch file: `/Users/kiteboard/prism42/findings/voice/harness-audit/synthetic_caller_full.py.patch`. Verified via `git apply --check` (exit 0). Apply with:

```
git apply findings/voice/harness-audit/synthetic_caller_full.py.patch
```

Final verified diff:

```diff
--- a/agents/livekit/synthetic_caller_full.py
+++ b/agents/livekit/synthetic_caller_full.py
@@ -157,24 +157,27 @@
     await room.connect(url, jwt)
     print(f"[stage C] connected @ +{time.time() - t0:.2f}s")
 
+    join_timeout = float(os.environ.get("PRISM42_HARNESS_JOIN_TIMEOUT_S", "30"))
     try:
-        await asyncio.wait_for(agent_joined.wait(), timeout=15)
+        await asyncio.wait_for(agent_joined.wait(), timeout=join_timeout)
     except asyncio.TimeoutError:
         print("FAIL: agent never joined")
         await room.disconnect()
         return 2
     print(f"[stage C] AGENT JOINED @ +{time.time() - t0:.2f}s ({agent_identity[0]})")
 
+    track_timeout = float(os.environ.get("PRISM42_HARNESS_TRACK_TIMEOUT_S", "30"))
     try:
-        await asyncio.wait_for(agent_audio_track_subscribed.wait(), timeout=15)
+        await asyncio.wait_for(agent_audio_track_subscribed.wait(), timeout=track_timeout)
     except asyncio.TimeoutError:
         print("FAIL: no agent audio track")
         await room.disconnect()
         return 3
     print(f"[stage C] AUDIO TRACK SUBSCRIBED @ +{time.time() - t0:.2f}s")
 
-    print(f"\n=== STAGE D: wait for pre-roll (4s) ===")
-    await asyncio.sleep(4.0)
+    preroll_wait = float(os.environ.get("PRISM42_HARNESS_PREROLL_WAIT_S", "0.5"))
+    print(f"\n=== STAGE D: wait for pre-roll ({preroll_wait}s) ===")
+    await asyncio.sleep(preroll_wait)
     preroll_speech = speech_frames[0]
     preroll_peak = peak_amplitude[0]
     print(f"[stage D] pre-roll audio: {preroll_speech} non-silent frames, peak {preroll_peak}")
@@ -206,9 +209,10 @@
     publish_end_at[0] = time.time()
     print(f"[stage E] publish ended @ +{time.time() - t0:.2f}s")
 
-    print(f"\n=== STAGE F: wait up to 25s for agent reply ===")
+    reply_timeout = float(os.environ.get("PRISM42_HARNESS_REPLY_TIMEOUT_S", "30"))
+    print(f"\n=== STAGE F: wait up to {reply_timeout}s for agent reply ===")
     reply_window_start = publish_end_at[0]
-    reply_deadline = reply_window_start + 25.0
+    reply_deadline = reply_window_start + reply_timeout
     reply_first_speech_at = None
     while time.time() < reply_deadline:
         await asyncio.sleep(0.5)
@@ -227,10 +231,11 @@
             f"(0 = silence)"
         )
 
-    # Listen 5s more to capture any audio that started.
+    confirm_wait = float(os.environ.get("PRISM42_HARNESS_REPLY_CONFIRM_S", "1.0"))
+    # Listen confirm_wait seconds more to capture any audio that started.
     if reply_first_speech_at:
-        print(f"[stage F] listening 5s more to confirm sustained speech ...")
-        await asyncio.sleep(5.0)
+        print(f"[stage F] listening {confirm_wait}s more to confirm sustained speech ...")
+        await asyncio.sleep(confirm_wait)
 
     await room.disconnect()
 
@@ -251,7 +256,7 @@
     if not first_audio_at:
         print("VERDICT: no audio at all")
         return 4
-    if preroll_speech < 5:
+    if preroll_speech < 5 and os.environ.get("PRISM42_HARNESS_REQUIRE_PREROLL"):
         print("VERDICT: pre-roll never spoke (TTS broken)")
         return 4
     if reply_first_speech_at is None:
```

---

## What we did NOT find / can't audit without running

These items require live-pod runs to confirm; this audit is read-only.

1. **F8/F9 amplitude threshold (1000) calibration.** Need a 1-minute Fish-output amplitude trace from the live pod. Acceptance: the threshold should be ~5% of measured Fish peak. If measured peak is 16384 (50% full-scale), threshold 1000 (3% full-scale) is fine. If peak is 4000, threshold 1000 is missing 25% of frames.

2. **F3 echo-suppress window (300ms) calibration.** Need a measurement of LiveKit Cloud's loopback-echo duration on the `livekit.thegoatnote.com` pod. Could be 100ms or 800ms — we currently assume 300ms with no evidence.

3. **F10 livekit-rtc buffered-frame replay behavior.** Does `rtc.AudioStream(track)` replay buffered frames from before subscription? If yes, F10 is a non-issue. If no, F10 under-counts preroll proportional to event-loop scheduling latency.

4. **Cold-start vs warm-start latency distribution.** The 30s defaults in F5/F6 are guesses based on "30s should cover any reasonable cold start" — would be tighter with a measured cold-start histogram.

5. **F14 Vercel-route response shape stability.** Cannot audit Vercel-side without checking that repo. The `session_id` field name dependency is a real coupling.

6. **Concurrent-caller behavior.** F13's "first non-`synthetic-caller` is the agent" assumption. Two concurrent harness runs in the same room, or a web client visiting `/prism42/livekit` while the harness is running, would mis-identify the agent. This is more a deployment-discipline issue than a measurement bias, but worth flagging.

7. **Whether the worker.py changes between cycles preserve `participant_connected` and `track_subscribed` semantics.** If a future worker.py version uses a delayed track publication (e.g. on-demand TTS track creation), F11 (`if not first_audio_at: return 4`) could fire before the agent is actually broken.

---

## Verification

Verified live during this audit (CWD `/Users/kiteboard/prism42`):

```
$ git apply --check findings/voice/harness-audit/synthetic_caller_full.py.patch
$ echo "EXIT=$?"
EXIT=0
```

The patch applies cleanly to the current working tree of `agents/livekit/synthetic_caller_full.py` (271 lines, modified 2026-04-24 05:30).

---

## What this audit explicitly does NOT change

- Exit codes 0/2/3/4/5 — the contract bench_b300.py reads. F1 changes WHEN exit 4 fires (now opt-in), but doesn't introduce new codes.
- The verdict line strings ("VERDICT: pre-roll never spoke (TTS broken)", "VERDICT: PASS — full turn round-trip works") — bench_b300.py:215 greps for `VERDICT` prefix; we keep that prefix on every print.
- The publish-pacing logic (line 191-205) — that's WebRTC-correct, not measurement bias.
- The Fish synthesis path (line 58-76) — out of scope; this is harness audit, not the TTS audit.
- The token mint contract (line 99-105) — Vercel's, not ours to change.
