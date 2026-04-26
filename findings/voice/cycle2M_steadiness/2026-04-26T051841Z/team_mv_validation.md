# Team M-V — 6-WAV f0-steadiness ranking

**Mode:** read-only. stdlib `wave` + numpy + scipy.io.wavfile.read. Lightweight autocorrelation pitch tracker with subharmonic-preference octave correction + 5-frame median snap. No librosa. No file modifications.

**Window:** 2026-04-26T05:18Z, 20-minute ship-by.

**Inputs (6 LibriTTS WAVs, speaker 2026 = Mil Nicholson per Team J1):**
- `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000000.wav` (cycle-2j wav1; previously tested as ref)
- `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000001.wav` (cycle-2j wav2; speaker character produced cycle-2j wav2/p4 GO output)
- `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000003_000000.wav` (NEW)
- `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000006_000001.wav` (NEW)
- `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000010_000000.wav` (NEW)
- `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000013_000000.wav` (NEW)

**Per-file raw features:** `team_mv_features.json` (this dir). **Tracker source:** `team_mv_analyze.py`.

---

## L1 GO anchor recap

Per `findings/voice/cycle2L_forensic/2026-04-26T044254Z/team_l1_phrase_audit.md`, Team L1 identified the GO discriminator as the conjunction:

- `f0_std ≤ 30 Hz` (strict; 39 Hz looser bound, |d|=1.05)
- `f0_range ≤ 130 Hz` (the dominant discriminator, |d|=2.06)

Anchor: `cycle-2j wav2/p4.wav` (3-syllable imperative "Stay with me", 1.022 s) — the cross-ref GO file — was measured at **f0_std=17, f0_range=100, f0_mean=131** by L1. The TOP candidates **should approximate this profile in the REFERENCE clip itself** so that Fish's VQ-token inheritance carries steadiness through to the synthesized output.

**Critical caveat — tracker calibration cross-check.** Re-running the same anchor file (`cycle-2j/wav2/p4.wav`) through THIS tracker yields f0_std=27.7, f0_range=117.2 — both ~50% higher than L1's reported values. The discrepancy is a tracker-implementation difference (window size, voicing gate, octave-correction rules), not a real signal. **Absolute thresholds (30/39/130) are calibrated for L1's tracker.** This audit's ranking and relative comparisons are reliable; absolute pass/fail vs L1's thresholds requires re-anchoring against L1's tracker if used as a hard gate.

Tracker config: 30 ms window, 10 ms hop, F0 search 70-400 Hz, voicing gate at 1% of peak frame RMS plus AC-peak threshold 0.30, subharmonic-preference octave correction, 5-frame median octave-jump snap.

---

## Per-file features

| # | file | duration s | sample_rate | bit_depth | peak | RMS | f0_mean Hz | f0_std Hz | f0_range Hz (max-min) | f0_range Hz (p5-p95) | silence_head ms | silence_total % | transcript |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `..._000001_000000.wav` | 13.530 | 24000 | 16 | 0.610 | 0.071 | 175.6 | **50.9** | 291.2 | 132.2 | 41.3 | 59.3 | yes |
| 2 | `..._000001_000001.wav` | 14.552 | 24000 | 16 | 0.551 | 0.067 | 186.0 | 53.9 | 308.1 | 173.4 | 50.8 | 60.7 | yes |
| 3 | `..._000003_000000.wav` |  4.781 | 24000 | 16 | 0.511 | 0.058 | 172.1 | 62.7 | 290.8 | 206.1 | 73.1 | 54.7 | yes |
| 4 | `..._000006_000001.wav` |  5.461 | 24000 | 16 | 0.593 | 0.065 | 192.0 | 68.8 | 286.9 | 211.6 | 58.3 | 63.4 | yes |
| 5 | `..._000010_000000.wav` |  4.218 | 24000 | 16 | 0.373 | 0.051 | 282.2 | 64.7 | 263.1 | 220.3 | 33.8 | 63.6 | yes |
| 6 | `..._000013_000000.wav` | 10.949 | 24000 | 16 | 0.529 | 0.056 | 170.8 | **51.2** | 289.4 | 139.8 | 38.1 | 63.5 | yes |

All clean: 0 disqualifying clipping events, all transcripts present (`.original.txt` and `.normalized.txt`), all sample rates ≥16 kHz (all 24 kHz mono 16-bit), no file fails any veto.

---

## Ranking (primary f0_std asc; secondary f0_range asc; tertiary duration desc)

| rank | file | f0_std | f0_range (max-min) | f0_range (p5-p95) | duration | comment |
|---|---|---|---|---|---|---|
| **1** | `2026_22756_000001_000000.wav` | **50.9** | 291.2 | **132.2** | 13.53 s | cycle-2j wav1; previously tested ref |
| **2** | `2026_22756_000013_000000.wav` | **51.2** | 289.4 | 139.8 | 10.95 s | NEW; closest second by f0_std |
| 3 | `2026_22756_000001_000001.wav` | 53.9 | 308.1 | 173.4 | 14.55 s | cycle-2j wav2; gave the GO p4 output |
| 4 | `2026_22756_000003_000000.wav` | 62.7 | 290.8 | 206.1 | 4.78 s | NEW; short |
| 5 | `2026_22756_000010_000000.wav` | 64.7 | 263.1 | 220.3 | 4.24 s | NEW; "I am afraid they have…" — possibly elevated emotional register, f0_mean=282 |
| 6 | `2026_22756_000006_000001.wav` | 68.8 | 286.9 | 211.6 | 5.46 s | NEW; worst f0_std |

**Two ranking signals diverge.** When ranked by `max-min` f0_range, file 5 (`..._000010_000000.wav`) ranks best (263 Hz vs 287-308 for others). When ranked by `p5-p95` f0_range, file 1 ranks best (132 vs 140-220 for others). The `p5-p95` form is the L1-comparable measure (L1 used min/max over voiced frames but with a different voicing gate; the p5/p95 percentiles are the robust analog that throws out single-frame outliers). **The primary ranking holds either way: files 1 and 13 are the top 2.**

---

## Top 2 for Team M-E to bench

### Candidate A — `2026_22756_000001_000000.wav`

- Path: `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000000.wav`
- f0 profile: f0_std=50.9, f0_range (max-min)=291, f0_range (p5-p95)=132, f0_mean=176, duration=13.53 s, sr=24 kHz, mono, 16-bit
- Transcript (`.original.txt`, verbatim): *"Day after day as he bent his steps homeward, returning from some new effort to procure employment, Kit raised his eyes to the window of the little room he had so much commended to the child, and hoped to see some indication of her presence."*
- **Predicted Fish-reference fit: MODERATE.** Best of the 6 by f0_std AND by p5-p95 range. But this is the SAME file already tested as cycle-2j wav1 ref — the user's existing prior on this clip is the prior on this candidate.

### Candidate B — `2026_22756_000013_000000.wav` (NEW)

- Path: `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000013_000000.wav`
- f0 profile: f0_std=51.2, f0_range (max-min)=289, f0_range (p5-p95)=140, f0_mean=171, duration=10.95 s, sr=24 kHz, mono, 16-bit
- Transcript (`.original.txt`, verbatim): *"Kit scratched his head mournfully, in reluctant admission that it did not, and clambering up to the old nail took down the cage and set himself to clean it and to feed the bird."*
- **Predicted Fish-reference fit: MODERATE.** Functionally tied with Candidate A on f0_std (Δ=0.3 Hz, well inside tracker noise). Slightly higher p5-p95 range (140 vs 132) but within 6%. Duration 10.95 s sits in the upper half of Fish's recommended 10-30 s window. Anticipated failure mode (chapter 13 = late-book narrative tension) **did not** materialize — this clip is calmer-toned narration ("Kit scratched his head mournfully"), descriptive prose with no dialogue, no high-affect punctuation.

**Recommendation:** bench BOTH on Team M-E. If only one slot is available, pick **Candidate B (`..._000013_000000.wav`)** since Candidate A is the already-tested cycle-2j wav1 (re-bench yields no new information) and Candidate B is essentially tied on every prosodic feature while being NEW corpus.

---

## Disqualifiers — none

All 6 files pass all veto checks:
- 0 clipping samples (sample-level peak below digital full-scale on every file)
- silence_total ≤ 64% on all (within bounds for narration with natural pauses)
- sample_rate = 24 kHz on all (above 16 kHz floor)
- both `.original.txt` and `.normalized.txt` transcripts present and non-empty for all 6
- single speaker (Mil Nicholson, per Team J1's earlier audit; same speaker_id 2026 across all 6 by file naming)
- all 16-bit PCM mono

---

## Caveats

1. **NO file in the 6 meets L1's strict `f0_std ≤ 30 Hz` GO criterion**, even on the loose `≤39 Hz` bound. The candidates run 51-69 Hz f0_std, well above. f0_range exceeds the 130 Hz bound on every file by max-min measure (263-308 Hz), and on 4 of 6 by the p5-p95 measure (139-220 Hz). The L1 anchor (`cycle-2j wav2/p4`) was a 1-second imperative — the LibriTTS clips here are 4-15 second multi-sentence passages with prosodic variation that no narration clip can avoid. **L1's thresholds are calibrated for the synthesized OUTPUT (Fish's render), not the reference clip itself.** L1's framing ("the TOP candidates should approximate this profile in the REFERENCE clip") is aspirational; in practice, ranking the available LibriTTS pool by these features is the operative mechanism, and that ranking IS produced here.

2. **Speaker-2026 accent issue (per Team J1) is unresolved by these 4 new candidates.** All 6 are Mil Nicholson, British female narrator. Speaker character is fixed across the 6 files; only emotional and prosodic content varies between segments. If the user has de-prioritized the accent disqualifier in favor of the steadiness lever (per the L1 reframe to f0_std/f0_range as the GO discriminator), then the top-2 selection above is the optimal lever-pull from this candidate pool. If accent is still load-bearing, the 4 new candidates do not help — a different speaker is required.

3. **Tracker calibration delta vs L1.** This tracker reports f0_std ~63% higher than L1's tracker on the cycle-2j anchor (27.7 vs 17). The relative ranking and the disqualifier checks are sound regardless. The absolute number "f0_std=51" on Candidate A, multiplied by the calibration ratio (~17/27.7 ≈ 0.61), would project to ~31 Hz under L1's tracker — i.e. right at the strict 30 Hz boundary. **This is a soft signal that the top-2 candidates may pass L1's strict gate when measured by L1's tracker.** Team M-E should re-measure with the L1 tracker (`cycle2L_forensic/2026-04-26T04-43-16Z/aggregate_metrics.py` references the same numpy autocorrelation method but with different gates) before declaring strict-GO compliance.

4. **Failure-mode pre-registration was correct on speaker character (all 6 are same Mil Nicholson) and partially correct on emotional content** — file 5 (`..._000010_000000.wav`, "I am afraid they have, and that's the truth, she said") shows the highest f0_mean of all 6 (282 Hz vs 170-192 for the rest), indicating elevated speaking register on this dialogue line, which propagated into worse f0_std (5th-worst of 6). Chapter 13 was anticipated to have accumulated narrative tension — instead its segment is calm descriptive prose and ranks 2nd best. Anticipated structural priors are partially predictive but content > position.

---

## Sources cited

- Team J1 audit (speaker identification, accent disqualifier) — referenced in user prompt
- Team J-T transcript findings (`.original.txt` preferred for Dickensian word forms) — followed; both `.original.txt` and `.normalized.txt` extracted, `.original.txt` reported as the verbatim transcript
- Team L1 GO criterion: `findings/voice/cycle2L_forensic/2026-04-26T044254Z/team_l1_phrase_audit.md` (read in this audit; thresholds and anchor values quoted directly from the discriminator analysis table)
- L1 forensic features file: `findings/voice/cycle2L_forensic/2026-04-26T044254Z/forensic_features.json` (anchor row `cycle2j_wav2/p4` cross-checked: f0_mean=131.1, f0_std=17.1, f0_range=100.2)

---

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits)
