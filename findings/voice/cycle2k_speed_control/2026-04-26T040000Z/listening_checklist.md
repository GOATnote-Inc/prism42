# Cycle-2k listening checklist — 30 audio files

The agent ran a 6×5 bench (6 conditions × 5 phrases = 30 audio files) and computed wpm/sps metrics. The agent CANNOT confirm whether a tag like `[urgent dispatcher pace]` is consumed silently as voice direction OR rendered as audible spoken words. Only the human can.

Walk through the 30 files in this order. For each, mark a verdict per the rubric below. The empirical winner from machine metrics is **T1 [urgent dispatcher pace]**; T5 [911 dispatcher voice] is the alt. Listen to those two condition directories first; if both fail the audible-tag check, the bench result is null.

## Files (relative to this dir)

```
audio/baseline/p1.wav  Nine one one, where is your emergency?
audio/baseline/p2.wav  What's your location?
audio/baseline/p3.wav  Are they breathing?
audio/baseline/p4.wav  Stay with me.
audio/baseline/p5.wav  Help is on the way.

audio/T1/p1.wav  [urgent dispatcher pace] Nine one one, where is your emergency?
audio/T1/p2.wav  [urgent dispatcher pace] What's your location?
audio/T1/p3.wav  [urgent dispatcher pace] Are they breathing?
audio/T1/p4.wav  [urgent dispatcher pace] Stay with me.
audio/T1/p5.wav  [urgent dispatcher pace] Help is on the way.

audio/T2/p1.wav  [fast clear] Nine one one, where is your emergency?
audio/T2/p2.wav  [fast clear] What's your location?
audio/T2/p3.wav  [fast clear] Are they breathing?
audio/T2/p4.wav  [fast clear] Stay with me.
audio/T2/p5.wav  [fast clear] Help is on the way.

audio/T3/p1.wav  [news anchor pace] Nine one one, where is your emergency?
audio/T3/p2.wav  [news anchor pace] What's your location?
audio/T3/p3.wav  [news anchor pace] Are they breathing?
audio/T3/p4.wav  [news anchor pace] Stay with me.
audio/T3/p5.wav  [news anchor pace] Help is on the way.

audio/T4/p1.wav  [brisk professional] Nine one one, where is your emergency?
audio/T4/p2.wav  [brisk professional] What's your location?
audio/T4/p3.wav  [brisk professional] Are they breathing?
audio/T4/p4.wav  [brisk professional] Stay with me.
audio/T4/p5.wav  [brisk professional] Help is on the way.

audio/T5/p1.wav  [911 dispatcher voice] Nine one one, where is your emergency?
audio/T5/p2.wav  [911 dispatcher voice] What's your location?
audio/T5/p3.wav  [911 dispatcher voice] Are they breathing?
audio/T5/p4.wav  [911 dispatcher voice] Stay with me.
audio/T5/p5.wav  [911 dispatcher voice] Help is on the way.
```

## Rubric per file

For each .wav, mark **one** of:

- **PASS** — phrase rendered correctly, tag silent, voice identity stable, pace acceptable.
- **AUDIBLE_TAG** — you hear the bracket tag spoken as words (e.g. literally hears "urgent dispatcher pace"). DEAL-BREAKER.
- **VOICE_DRIFT** — voice character clearly different from the baseline reference (e.g. different speaker / different gender / robotic).
- **GARBLED** — audio is unintelligible / has crackle / is silent.
- **TOO_FAST** — comprehensible but rushed past natural conversational pace.
- **TOO_SLOW** — comprehensible but draggy / unnatural pause.
- **OTHER** — describe in notes.

## Walk-through prompt (for the listener)

Step 1 — Calibrate the ear on baseline (no tag):

| file | rubric verdict | notes |
|---|---|---|
| audio/baseline/p1.wav |  |  |
| audio/baseline/p2.wav |  |  |
| audio/baseline/p3.wav |  |  |
| audio/baseline/p4.wav |  |  |
| audio/baseline/p5.wav |  |  |

K1 measured baseline P1 at 160.7 wpm — perceived as 0.5x by the user during cycle-2j. P3-P5 all >225 wpm — perceived as natural. Confirm.

Step 2 — Listen to **T1 [urgent dispatcher pace]** (empirical winner):

| file | rubric verdict | notes |
|---|---|---|
| audio/T1/p1.wav |  |  |
| audio/T1/p2.wav |  |  |
| audio/T1/p3.wav |  |  |
| audio/T1/p4.wav |  |  |
| audio/T1/p5.wav |  |  |

CRITICAL CHECK on T1/p1: do you hear the literal words "urgent dispatcher pace" before "Nine one one"? If YES, T1 is dead.

Step 3 — Listen to **T5 [911 dispatcher voice]** (empirical alt):

| file | rubric verdict | notes |
|---|---|---|
| audio/T5/p1.wav |  |  |
| audio/T5/p2.wav |  |  |
| audio/T5/p3.wav |  |  |
| audio/T5/p4.wav |  |  |
| audio/T5/p5.wav |  |  |

CRITICAL CHECK on T5/p1: do you hear the literal words "911 dispatcher voice" before "Nine one one"? If YES, T5 is dead.

Step 4 — If T1 and T5 both pass the audible-tag check, listen to T2/T3/T4 for completeness (these are empirically not winners; just verifying no tag gets a free PASS that the wpm metric missed):

| file | rubric verdict | notes |
|---|---|---|
| audio/T2/p1.wav |  |  |
| audio/T2/p2.wav |  |  |
| audio/T2/p3.wav |  |  |
| audio/T2/p4.wav |  |  |
| audio/T2/p5.wav |  |  |
| audio/T3/p1.wav |  |  |
| audio/T3/p2.wav |  |  |
| audio/T3/p3.wav |  |  |
| audio/T3/p4.wav |  |  |
| audio/T3/p5.wav |  |  |
| audio/T4/p1.wav |  |  |
| audio/T4/p2.wav |  |  |
| audio/T4/p3.wav |  |  |
| audio/T4/p4.wav |  |  |
| audio/T4/p5.wav |  |  |

## Decision template

Pick one and write it into `decision.txt`:

- `CYCLE2K_DEPLOYED_T1` — all 5 T1 files PASS, deploy `[urgent dispatcher pace]`.
- `CYCLE2K_DEPLOYED_T5` — all 5 T5 files PASS, T1 had AUDIBLE_TAG or VOICE_DRIFT, deploy `[911 dispatcher voice]`.
- `CYCLE2K_DEPLOYED_TX` — fallback to T2/T3/T4 (only if T1+T5 both fail audible-tag check AND a fallback tag has 5/5 PASS).
- `CYCLE2K_ROLLED_BACK` — every tag has AUDIBLE_TAG / VOICE_DRIFT / GARBLED on at least one file. Restore baseline per rollback in `decision.txt`.

## Deploy command (after picking a winner)

```bash
ssh prism-mla-b300-h4h5
sudo tee /etc/systemd/system/prism42-worker.service.d/70-cycle2k-pacetag.conf <<'EOF'
[Service]
Environment=PRISM42_FISH_PACE_TAG=[urgent dispatcher pace]
EOF
sudo systemctl daemon-reload && sudo systemctl restart prism42-worker
# verify watchdog:
bash /Users/kiteboard/prism42/findings/b300_bench/cycle2_guard/2026-04-25T13-56-50Z/health_check.sh
# (ignore vllm.pid stale fail — HTTP probes are the truth)
```

Replace `[urgent dispatcher pace]` with the tag you picked. The `Environment=` line keeps the brackets and spaces literal — systemd handles the value as-is. The adapter reads `os.environ["PRISM42_FISH_PACE_TAG"]` at request time and prepends `<tag> ` to every utterance.

## Notes for the listener

- Audio is 44.1 kHz mono PCM16 in RIFF WAV containers — every player should handle them.
- Quick-listen sanity: `afplay audio/T1/p1.wav` on macOS, or VLC.
- For comparison: open `audio/baseline/p1.wav` and `audio/T1/p1.wav` side-by-side; same words, T1 should be ~30% shorter.
- The bracket tag is theoretically silent ("voice direction"). Fish S2-Pro README claims 15,000+ unique tag descriptors. Whether these specific 5 tags are in-distribution is a partial-test question.
