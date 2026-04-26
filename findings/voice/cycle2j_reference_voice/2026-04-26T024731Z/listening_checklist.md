# Cycle-2j listening checklist

**For human attestation only — agent has no audio perception.**

15 audio files: 5 phrases x 3 conditions. All rendered at 44.1 kHz mono 16-bit PCM by Fish S2 Pro on B300, seed=911, temperature=0.1, top_p=0.7.

Listen to each phrase across all 3 conditions (baseline, wav1, wav2) and rate naturalness, calmness, dispatcher-fit. Then pick the winning condition (or REJECT_BOTH if neither beats baseline on naturalness).

Recommended order: listen P1 across all 3 first (the 911 identity line is the highest-stakes utterance). If a clear winner emerges on P1, use P2-P5 to confirm consistency.

---

## P1 — "Nine one one, where is your emergency?"

- [ ] **baseline**: `audio/baseline/p1.wav` — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav1**:     `audio/wav1/p1.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav2**:     `audio/wav2/p1.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>

Notes: ____

## P2 — "What's your location?"

- [ ] **baseline**: `audio/baseline/p2.wav` — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav1**:     `audio/wav1/p2.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav2**:     `audio/wav2/p2.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>

Notes: ____

## P3 — "Are they breathing?"

- [ ] **baseline**: `audio/baseline/p3.wav` — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav1**:     `audio/wav1/p3.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav2**:     `audio/wav2/p3.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>

Notes: ____

## P4 — "Stay with me."

- [ ] **baseline**: `audio/baseline/p4.wav` — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav1**:     `audio/wav1/p4.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav2**:     `audio/wav2/p4.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>

Notes: ____

## P5 — "Help is on the way."

- [ ] **baseline**: `audio/baseline/p5.wav` — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav1**:     `audio/wav1/p5.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>
- [ ] **wav2**:     `audio/wav2/p5.wav`     — naturalness <H/M/L>, calmness <H/M/L>, dispatcher-fit <Y/N>

Notes: ____

---

## Verdict (fill in after listening)

- [ ] PICK_WAV1 — install `60-cycle2j-refvoice.conf` with WAV1 path
- [ ] PICK_WAV2 — install `60-cycle2j-refvoice.conf` with WAV2 path
- [ ] REJECT_BOTH — keep adapter patched but no env, default to baseline voice (current state)
- [ ] PARTIAL_KEEP_OFF — slight latency win on WAV1/2 but not enough naturalness improvement to justify (current state)

**Current default state if no action: PARTIAL_KEEP_OFF (adapter patched, no env set, no drop-in installed).**

---

## Reference-voice provenance

- **WAV1**: LibriTTS speaker 2026, file `2026_22756_000001_000000.wav`, 13.530 s, 24 kHz mono
  - LibriVox reader Mil Nicholson reading Charles Dickens, *The Old Curiosity Shop*, ch. 20
  - Public domain audiobook recording — no consent issues
- **WAV2**: LibriTTS speaker 2026, file `2026_22756_000001_000001.wav`, 14.550 s, 24 kHz mono
  - Same reader, same chapter, contiguous segment
  - Public domain audiobook recording — no consent issues

Both clips are within Fish's recommended 10-30 s reference window and contain a single speaker (Mil Nicholson) reading prose with natural prosody.
