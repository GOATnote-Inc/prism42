# Listening checklist — cycle-2M (M1 + M2 references)

User listens before accepting the REJECT_BOTH default decision; perception may diverge from f0-steadiness metrics.

## A/B/C set

| set | path | what it is |
|---|---|---|
| **A** | `findings/voice/cycle2L_forensic/2026-04-26T04-43-16Z/audio/B_psap_fast/p{1..5}.wav` | Production default (psap reference_id, no commafix). 3/5 PASS_loose under cycle-2M tracker. |
| **B** | `findings/voice/cycle2M_steadiness/2026-04-26T051841Z/audio/M1/p{1..5}.wav` | Cycle-2M M1 (LibriTTS wav1; cycle-2j wav1 re-bench). 0/5 PASS_loose. |
| **C** | `findings/voice/cycle2M_steadiness/2026-04-26T051841Z/audio/M2/p{1..5}.wav` | Cycle-2M M2 (NEW LibriTTS file 000013). 1/5 PASS_loose (only p3 "Are they breathing?"). |

## Phrases

| id | text |
|---|---|
| p1 | Nine one one, where is your emergency? |
| p2 | What's your location? |
| p3 | Are they breathing? |
| p4 | Stay with me. |
| p5 | Help is on the way. |

## Per-phrase listening prompt

For each of p1–p5, listen to A then B then C in sequence. Score each on:

- **Steadiness:** does the voice hold a consistent pitch line, or does it wobble/quaver?
- **Pace:** is it dispatcher-fast (≥ 200 wpm) without sounding rushed?
- **Affect:** does it sound like a calm professional under pressure, or like an audiobook narrator, or like a robot?
- **Fit:** would you accept this as a 911 dispatcher's voice on a real call?

Mark each (A, B, C) per phrase as: PSAP_FIT / OK / NOT_FIT.

## Decision matrix after listening

- **A wins on ≥ 3/5 phrases** → confirm REJECT_BOTH; production stays on psap.
- **B wins on ≥ 3/5 phrases** → user override → re-install M1 drop-in; pin reference to wav_M1.
- **C wins on ≥ 3/5 phrases** → user override → re-install M2 drop-in; pin reference to wav_M2.
- **Any tie** → re-bench with steadier reference (out-of-corpus); see `f0_validation.md` for what that requires.

## Re-install drop-in (if user picks B or C)

```bash
ssh b300-pod 'sudo tee /etc/systemd/system/prism42-worker.service.d/90-cycle2M-refaudio.conf > /dev/null <<EOF
[Service]
Environment="PRISM42_FISH_REFERENCE_AUDIO=/opt/prism42/voice-refs/wav_M{1|2}.wav"
Environment="PRISM42_FISH_REFERENCE_TEXT=<verbatim transcript from result.json>"
Environment="FISH_SPEECH_REFERENCE_ID="
EOF
sudo systemctl daemon-reload
sudo systemctl restart prism42-worker
sleep 6
systemctl is-active prism42-worker
journalctl -u prism42-worker --since "1 min ago" | grep reference_voice'
```

(Replace `M{1|2}` and the transcript from `result.json["phases"]["phase_2_mv_wait"]["top_2_candidates"]["M{1|2}"]["transcript"]`.)

## Rollback (60 s)

```bash
ssh b300-pod 'sudo rm -f /etc/systemd/system/prism42-worker.service.d/90-cycle2M-refaudio.conf && sudo systemctl daemon-reload && sudo systemctl restart prism42-worker && systemctl is-active prism42-worker'
```

(Already executed at end of bench — no further action needed unless user re-installs.)

## Caveat

The f0 metric measures *prosodic steadiness*, which the L1 audit attested correlates with the user's earlier GO/NOT_GO ratings on cycle-2k. But:

- The L1 audit used only 30 phrases. Generalization is plausible but not proven.
- Audio quality has many other axes (timbre, breathiness, accent, intelligibility) that f0 does not capture.
- M2's p3 ("Are they breathing?") is the one PASS_loose phrase across all 10 outputs. Listen to it specifically — if it's the standout calm-dispatcher rendering, that's the f0 metric working. If it sounds the same as the others, that's evidence the f0 metric is undertrained.

If user listening contradicts the metric, that's a data point about the metric's reliability — not necessarily a reason to override the metric for the production default.
