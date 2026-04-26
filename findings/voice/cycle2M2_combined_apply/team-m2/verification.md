# Cycle-2M2 Team M2 — verification

**Date:** 2026-04-26
**Pod:** prism-mla-b300-h4h5
**Method:** 3 probes per Phase 3 of the M2 spec; supplemental classify/transition checks for full FSM-fix coverage

## Probe 1 — synthetic_caller PASS_2R baseline

Command:
```
ssh prism-mla-b300-h4h5 'cd /opt/prism42/agents/livekit && timeout 60 .venv/bin/python synthetic_caller.py 2>&1 | tail -25'
```

Result (last frame and verdict):
```
+35.54s: bytes=1,632,960 speech_frames=232 peak=30343 first_frame=+1.52s

============================================================
RESULT
============================================================
agent_joined            : YES ('agent-AJ_zk84W3m2PmCM')
audio_track_subscribed  : YES
first_audio_frame       : YES (+1.52s)
total_audio_bytes       : 1,632,960
speech_frames           : 232 (frames with peak > 1000)
peak_amplitude          : 30343 (16-bit signed; >5000 = clear speech)
VERDICT: PASS — agent spoke (232 non-silent frames, peak amplitude 30343)
```

| Metric | Spec target | Actual | |
|---|---|---|---|
| agent_joined | YES | YES | PASS |
| audio_track | YES | YES | PASS |
| bytes | 1500-1700 KB | 1632 KB | PASS |
| speech_frames | >=230 | 232 | PASS |
| peak_amplitude | >25000 | 30343 | PASS |
| first_frame | <2.0s | +1.52s | PASS |

**Probe 1: PASS, no regression vs cycle-2R baseline.**

## Probe 2 — Q-fix verification (event counts for synthetic_caller session)

Session: `bad7afbf-df2c-e054-feeb-dd4cd8afa1e0` (RM_smvXKCyth2Kv).

Note on the spec: synthetic_caller does NOT speak any caller utterances — it only listens to the dispatcher greeting. The greeting is served from the cached `greeting.911.played source=cached` path, NOT via Fish TTS. Therefore the spec-anticipated outcome ("expect fsm=0, gate=0, tts=1 (greeting), preempt=0, filler=0") translates to: greeting=1 (cached, not via fishspeech.t0); the load-bearing assertions are `preempt=0` and `filler=0`.

Counts on this session:
```
utt=0  fsm=0  gate_dec=0  gate=0  tts=0  preempt=0  filler=0
greeting.911.played: 1 (cached, source=cached)
greeting.911.dispatched: 1
```

| Metric | Spec target | Actual | |
|---|---|---|---|
| `using preemptive generation` | 0 | 0 | PASS |
| `filler.spoken` | 0 | 0 | PASS |
| greeting played | 1 | 1 (cached) | PASS |
| any error | none | none | PASS |

**Probe 2: PASS.** The Q-fix-1 invariant — `preempt=0` whenever the gate-template path completes — is upheld at session boot. (synthetic_caller doesn't exercise the post-greeting gate-template path; full live-call attestation by the user is the next signal source for the multi-turn cardiac scenario.)

## Probe 3 — P-fix C3 verification (spelled-cardinal normalizer on pod)

```
ssh prism-mla-b300-h4h5 'cd /opt/prism42/agents/livekit && .venv/bin/python -c "
from dispatcher_fsm import _normalize_spelled_cardinals as n, classify
print(\"normalize:\")
print(repr(n(\"one hundred ocean avenue\")))
print(repr(n(\"fifty-two main street\")))
print(repr(n(\"twelve riverside drive\")))
print(repr(n(\"ocean of new\")))
print(\"classify.has_address:\")
print(\"one hundred ocean avenue:\", classify(\"one hundred ocean avenue\").has_address)
print(\"fifty-two main street:\", classify(\"fifty-two main street\").has_address)
print(\"twelve riverside drive:\", classify(\"twelve riverside drive\").has_address)
print(\"ocean of new:\", classify(\"ocean of new\").has_address)
"'
```

Output:
```
normalize:
'100 ocean avenue'
'52 main street'
'12 riverside drive'
'ocean of new'
classify.has_address:
one hundred ocean avenue: True
fifty-two main street: True
twelve riverside drive: True
ocean of new: False
```

| Test | Expected | Actual | |
|---|---|---|---|
| "one hundred ocean avenue" -> matches digit | True | True | PASS |
| "fifty-two main street" -> matches digit | True | True | PASS |
| "twelve riverside drive" -> matches digit | True | True | PASS |
| "ocean of new" -> NO spurious match | False | False | PASS |

**Probe 3: PASS on all 4 spec cases.**

## Supplemental — A1 + A3 in-pod transition checks

In addition to the spec's three probes, ran A1 (cardiac short-circuit gating) and A3 (direct-question router in CRITICAL_VERIFY) on the pod:

```
=== A1 Cardiac short-circuit gating ===
B-01 friend stopped breathing       state=critical_verify    cardiac=True       (positive cue, third-party still latches)
B-05 I cant breathe                  state=intake             cardiac=False      (first-person, no longer mis-routes)  *** USER-ATTESTED FIX ***
B-08 He is not breathing well        state=critical_verify    cardiac=True       (positive cue + third-party from 'he', latches as designed)
B-04 I am not breathing fast enough  state=critical_verify    cardiac=True       (positive cue 'not breathing' fires per Team P spec)
B-06 unresponsive                    state=critical_verify    cardiac=True       (positive cue still fires per Team P spec)

=== A3 Direct-question router in CRITICAL_VERIFY ===
D-01 Should I move him?                       intent=answer_do_not_move
D-02 How long until they get here?            intent=answer_how_long
D-03 Will he be OK?                           intent=answer_outcome_uncertain
```

A1 successfully prevents the user-attested mis-route ("I can't breathe" first-person no longer falls into CRITICAL_VERIFY). B-04 / B-06 still latch because Team P's `positive_arrest_cue` regex (verbatim per directive #1) covers "not breathing" and "unresponsive" — this is consistent with the spec's documented behavior.

A3 routes all three direct-question patterns correctly when in CRITICAL_VERIFY.

## Worker stability post-restart

```
ssh prism-mla-b300-h4h5 'systemctl is-active prism42-worker'
-> active

ssh prism-mla-b300-h4h5 'tail -200 /tmp/prism42-logs/worker.log | grep -E "ERROR|CRITICAL|Traceback"'
-> (no matches)
```

No errors, no crash loops. The brief "exiting forcefully" log line at 17:38:04 was the systemd restart itself (SIGTERM caught by watchfiles); the new worker process came up at 17:38:05 and registered cleanly.

## Summary

| Phase | Status |
|---|---|
| Phase 1 (apply 5 patches locally + commit per-patch) | DONE |
| Phase 2 (scp + worker restart) | DONE — worker active, 14s dark window |
| Phase 3 Probe 1 (synthetic_caller baseline) | PASS |
| Phase 3 Probe 2 (Q-fix invariants) | PASS (`preempt=0`, `filler=0`) |
| Phase 3 Probe 3 (C3 normalizer) | PASS (4/4 spec cases) |
| Phase 3 Supplemental (A1 + A3) | PASS (user-attested fix verified) |

**Net result:** 5 patches applied, deployed, verified. Ready for live-call attestation by user against the canonical 3-turn cardiac scenario.
