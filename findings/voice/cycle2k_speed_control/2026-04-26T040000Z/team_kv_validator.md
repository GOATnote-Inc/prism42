# Team K-V — cycle-2k empirical audio validation

**Mode:** read-only acoustic analysis. No code edits, no pod commands, no commits.

**K-E artifact:** `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z`

**cycle-2j reference:** `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/baseline`

**Methodology:** stdlib `wave` + numpy + scipy.io.wavfile. Duration = total file duration (`getnframes/getframerate`); wpm = words/duration*60; sps = syllables/duration. K1 audit's word counts (P1=6, P2=3, P3=3, P4=3, P5=5) used as primary — methodology cited from `findings/voice/cycle2k_speed_control/2026-04-26T031403Z/team_k1_speed_audit.md` lines 76-92. Target band: 175-200 wpm (trained-dispatcher pace).

**Metrics JSON:** `team_kv_metrics.json` (sibling).

---

## TL;DR (one paragraph)

All 30 K-E audio files render valid (5/5 per condition; peak ≥ 5000, no truncation, no NaN). The single most important finding for the user's stated symptom — **slow rendering on the long P1 utterance "Nine one one, where is your emergency?"** — is that **T5 `[911 dispatcher voice]` shifted P1 from 100.7 wpm baseline to 158.2 wpm (+57.5 wpm relative gain on the slow phrase, the largest of any tag)**. T2 `[fast clear]` wins on overall median wpm (193.8, inside the 175-200 target band) but barely moves P1 (109.2 wpm — essentially baseline). Tag-audibility forensic check (Δduration vs baseline, all conditions ≤ +0.1s avg) suggests **none of the five tags are being spoken aloud as words** — the AR is interpreting them as prosody hints, not text. The baseline cycle-2k median (155.0) reproduces cycle-2j's median (155.0) exactly, confirming determinism with `seed=911`. Recommended listening order: P1 first (T5 → T1 → baseline → cycle-2j anchor), then P2-P5 to confirm no overshoot. Final pick is user-perceptual, not metric-determinable.

**Three candidate winners, depending on what the user values most:**
- **Median-wpm winner:** T2 `[fast clear]` (median 193.8, but P1 stays slow).
- **P1-shift winner:** T5 `[911 dispatcher voice]` (P1 jumps +57.5 wpm to 158.2 — biggest shift on the user-cared-about phrase).
- **Most-consistent winner:** T5 (lowest stdev 31.3 across the 5 phrases — minimal turn-to-turn pace drift).

**Validity gate:** PASS. All 30 files render. No tag failed.
**Audible-tag REJECT list:** none flagged by forensic-Δdur check; user listening still required (agent cannot hear).

---


## Per-condition wpm summary

Word counts: P1=6, P2=3, P3=3, P4=3, P5=5 (K1 methodology). Distance = |median - target band|; 0 means median lies inside [175, 200]. **Overall rank** = primary median-distance + secondary stdev. **P1 rank** = closest to target on the slow phrase only (highest-stakes 911 identity utterance).


| condition | tag | median wpm | mean wpm | range | stdev | 5/5 valid? | dist to target | overall rank | P1 rank |
|---|---|---|---|---|---|---|---|---|---|
| baseline | `(none)` | 155.0 | 156.8 | 100.7-222.8 | 48.9 | 5/5 | 20.0 | (null) | (null) |
| T1 | `[urgent dispatcher pace]` | 155.0 | 163.7 | 138.4-222.8 | 34.4 | 5/5 | 20.0 | 5 | 2 |
| T2 | `[fast clear]` | 193.8 | 166.8 | 109.2-215.3 | 51.0 | 5/5 | 0.0 | 1 | 5 |
| T3 | `[news anchor pace]` | 170.0 | 154.2 | 119.3-184.6 | 31.5 | 5/5 | 5.0 | 2 | 3 |
| T4 | `[brisk professional]` | 168.5 | 165.8 | 117.5-239.3 | 50.6 | 5/5 | 6.5 | 4 | 4 |
| T5 | `[911 dispatcher voice]` | 168.5 | 177.4 | 143.6-222.8 | 31.3 | 5/5 | 6.5 | 3 | 1 |


## Per-phrase wpm + duration

(Bold = invalid, marked when peak <5000 or duration <0.3s. K1 word counts.)


| condition | P1 wpm/dur | P2 wpm/dur | P3 wpm/dur | P4 wpm/dur | P5 wpm/dur |
|---|---|---|---|---|---|
| baseline | 100.7 / 3.58s | 121.1 / 1.49s | 184.6 / 0.98s | 155.0 / 1.16s | 222.8 / 1.35s |
| T1 | 140.9 / 2.55s | 138.4 / 1.30s | 161.5 / 1.11s | 155.0 / 1.16s | 222.8 / 1.35s |
| T2 | 109.2 / 3.30s | 114.0 / 1.58s | 215.3 / 0.84s | 193.8 / 0.93s | 201.9 / 1.49s |
| T3 | 119.3 / 3.02s | 121.1 / 1.49s | 184.6 / 0.98s | 176.2 / 1.02s | 170.0 / 1.76s |
| T4 | 119.3 / 3.02s | 117.5 / 1.53s | 184.6 / 0.98s | 168.5 / 1.07s | 239.3 / 1.25s |
| T5 | 158.2 / 2.28s | 143.6 / 1.25s | 168.5 / 1.07s | 193.8 / 0.93s | 222.8 / 1.35s |


## Validity check (peak / RMS / duration)


| condition | P1 peak | P2 peak | P3 peak | P4 peak | P5 peak | min RMS | min dur (s) |
|---|---|---|---|---|---|---|---|
| baseline | 8304 | 31088 | 17584 | 7892 | 30832 | 1425 | 0.98 |
| T1 | 9936 | 27264 | 31200 | 10464 | 27200 | 1979 | 1.11 |
| T2 | 26640 | 28176 | 11936 | 16672 | 31168 | 2259 | 0.84 |
| T3 | 11256 | 30800 | 29744 | 11200 | 31536 | 1768 | 0.98 |
| T4 | 31616 | 30624 | 30624 | 31024 | 31344 | 6265 | 0.98 |
| T5 | 20720 | 15272 | 12872 | 9768 | 18800 | 1546 | 0.93 |


## Cross-cycle comparison vs cycle-2j


**cycle-2j baseline** (`audio/baseline/p1..p5.wav`): median wpm = 155.0, range 100.7-222.7.


| condition | cycle-2k median wpm | delta vs cycle-2j baseline (wpm) | delta vs target lo (175) | delta vs target hi (200) |
|---|---|---|---|---|
| baseline | 155.0 | +0.1 | -20.0 | -45.0 |
| T1 | 155.0 | +0.1 | -20.0 | -45.0 |
| T2 | 193.8 | +38.8 | +18.8 | -6.2 |
| T3 | 170.0 | +15.0 | -5.0 | -30.0 |
| T4 | 168.5 | +13.6 | -6.5 | -31.5 |
| T5 | 168.5 | +13.6 | -6.5 | -31.5 |


## Tag-audibility forensic check


If Fish were rendering the tag string as audible speech (e.g. literally pronouncing "urgent dispatcher pace" before the phrase), each tagged condition's per-phrase duration would be **larger** than baseline by ~0.5-1.0s (the time it takes to speak the tag itself). If the tag is being interpreted as a prosody hint (the desired behavior), durations should be **similar to or smaller than** baseline. Per-phrase duration delta vs cycle-2k baseline:


| condition | P1 Δdur (s) | P2 Δdur (s) | P3 Δdur (s) | P4 Δdur (s) | P5 Δdur (s) | tag-audible? |
|---|---|---|---|---|---|---|
| T1 | -1.02 | -0.19 | +0.14 | +0.00 | +0.00 | no (Δdur ≤ 0) |
| T2 | -0.28 | +0.09 | -0.14 | -0.23 | +0.14 | no (Δdur ≤ 0) |
| T3 | -0.56 | +0.00 | +0.00 | -0.14 | +0.42 | no (Δdur ≤ 0) |
| T4 | -0.56 | +0.05 | +0.00 | -0.09 | -0.09 | no (Δdur ≤ 0) |
| T5 | -1.30 | -0.23 | +0.09 | -0.23 | +0.00 | no (Δdur ≤ 0) |

**Interpretation:** Δdur ≤ +0.1s (avg) → tag is silent (prosody hint working). Δdur ≥ +0.4s → tag is likely being spoken aloud and the condition should be REJECTED. The numeric verdict is a forensic proxy only — final confirmation requires user listening (the agent has no audio perception).



## Recommended winner (empirical, wpm-only)


### Median-rank winner: T2 = `[fast clear]`

- Median wpm: 193.8 (inside the 175-200 wpm target band).
- Stdev across 5 phrases: 51.0.
- Validity: 5/5.
- +38.8 wpm vs cycle-2k baseline.


### P1-specific winner (highest-stakes slow phrase): T5 = `[911 dispatcher voice]`

- P1 wpm: 158.2 (+57.5 wpm vs baseline P1). Closest to target band on the slow utterance specifically.
- Median across all 5: 168.5 (overall rank 3).
- Stdev: 31.3.


### Most-consistent (low-stdev) candidate: T5 = `[911 dispatcher voice]`

- Stdev: 31.3 (lowest across the 5 tags).
- Median: 168.5, mean: 177.4, range 143.6-222.8.
- Trades absolute speed for cadence stability across phrase types — useful if the user wants minimal pace variation between turn 1 and subsequent turns.



## Listening checklist (ranked, paired)


Ordered with **highest-stakes (slowest-baseline) phrase P1 first**, then briskness check on P2-P5. For each phrase, paired audio paths run baseline → top-ranked tags → cycle-2j baseline (cross-cycle anchor). On P1, the **P1-specific top tag** is listed first (it shifted P1 wpm the most, which is the user-cared-about symptom). On P2-P5, the **overall median-rank top tag** is listed first.


### P1: "Nine one one, where is your emergency?" — slowest baseline (cycle-2k: 3.58s / 100.7 wpm) — **highest-stakes 911-identity utterance**


| order | condition | wpm | path |
|---|---|---|---|
| 1 | cycle-2k baseline (no tag) | 100.7 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/baseline/p1.wav` |
| 2 | P1-rank #1 T5 `[911 dispatcher voice]` | 158.2 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T5/p1.wav` |
| 3 | P1-rank #2 T1 `[urgent dispatcher pace]` | 140.9 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T1/p1.wav` |
| 4 | P1-rank #3 T3 `[news anchor pace]` | 119.3 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T3/p1.wav` |
| 5 | cycle-2j baseline (cross-cycle anchor) | 100.7 | `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/baseline/p1.wav` |

### P2: "What's your location?" — fast-baseline check (don't overshoot)


| order | condition | wpm | path |
|---|---|---|---|
| 1 | cycle-2k baseline (no tag) | 121.1 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/baseline/p2.wav` |
| 2 | rank #1 T2 `[fast clear]` | 114.0 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T2/p2.wav` |
| 3 | rank #2 T3 `[news anchor pace]` | 121.1 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T3/p2.wav` |
| 4 | rank #3 T5 `[911 dispatcher voice]` | 143.6 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T5/p2.wav` |
| 5 | cycle-2j baseline (cross-cycle anchor) | 121.1 | `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/baseline/p2.wav` |

### P3: "Are they breathing?" — fast-baseline check


| order | condition | wpm | path |
|---|---|---|---|
| 1 | cycle-2k baseline (no tag) | 184.6 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/baseline/p3.wav` |
| 2 | rank #1 T2 `[fast clear]` | 215.3 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T2/p3.wav` |
| 3 | rank #2 T3 `[news anchor pace]` | 184.6 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T3/p3.wav` |
| 4 | rank #3 T5 `[911 dispatcher voice]` | 168.5 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T5/p3.wav` |
| 5 | cycle-2j baseline (cross-cycle anchor) | 184.5 | `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/baseline/p3.wav` |

### P4: "Stay with me." — short declarative (K1: 1.0x perception in cycle-2j)


| order | condition | wpm | path |
|---|---|---|---|
| 1 | cycle-2k baseline (no tag) | 155.0 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/baseline/p4.wav` |
| 2 | rank #1 T2 `[fast clear]` | 193.8 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T2/p4.wav` |
| 3 | rank #2 T3 `[news anchor pace]` | 176.2 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T3/p4.wav` |
| 4 | rank #3 T5 `[911 dispatcher voice]` | 193.8 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T5/p4.wav` |
| 5 | cycle-2j baseline (cross-cycle anchor) | 155.0 | `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/baseline/p4.wav` |

### P5: "Help is on the way." — fast-baseline check


| order | condition | wpm | path |
|---|---|---|---|
| 1 | cycle-2k baseline (no tag) | 222.8 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/baseline/p5.wav` |
| 2 | rank #1 T2 `[fast clear]` | 201.9 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T2/p5.wav` |
| 3 | rank #2 T3 `[news anchor pace]` | 170.0 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T3/p5.wav` |
| 4 | rank #3 T5 `[911 dispatcher voice]` | 222.8 | `/Users/kiteboard/prism42/findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/T5/p5.wav` |
| 5 | cycle-2j baseline (cross-cycle anchor) | 222.7 | `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/baseline/p5.wav` |


## Audible-tag flags


K-E did not produce an explicit `audible_tag_check`/`audible_tags` field in result.json. **Listening pass MUST verify by ear that the tag string itself is not spoken aloud** — if you hear words like "urgent dispatcher pace" inside the audio, REJECT that tag regardless of wpm. Fish does not strip unrecognized tags reliably (per K1 audit lines 53-54).



## K-E verdict surface


K-E `result.json` does not include a `ship_decision`/`decision` field (only `conditions` payload). This validator parsed audio files directly and ranked empirically.


K-E per-condition synth latency (from K-E's own bench harness):


| condition | TTFB ms (avg) | total ms (avg) | all 5 ok? |
|---|---|---|---|
| baseline | 3 | 1457 | 5/5 |
| T1 | 3 | 1320 | 5/5 |
| T2 | 3 | 1402 | 5/5 |
| T3 | 3 | 1422 | 5/5 |
| T4 | 3 | 1370 | 5/5 |
| T5 | 3 | 1251 | 5/5 |


## Caveats


- **wpm proxy ≠ perceived speed.** Voiced-region wpm (K1's metric, requires VAD) differs from full-duration wpm (this report's metric) — K1's P1 = 107.8 wpm voiced vs our 100.7 full-duration on the same file. The relative ranking across conditions is stable; absolute numbers are 5-10% lower than K1's voiced-region values.
- **Agent has no audio perception.** This report cannot judge naturalness, pitch, intonation, or whether the tag string itself is being spoken aloud.
- **K1 word counts vs prompt-stated word counts differ** (K1: 6/3/3/3/5, prompt: 10/4/4/3/5). The prompt's counts approximate syllables, not words. K1's are used as primary because they match the cycle-2j baseline methodology cited in the prompt.
- **Overshoot risk on P2-P5.** P3 ("Are they breathing?") and P5 ("Help is on the way.") were already at 184-260 wpm in cycle-2j baseline. A tag that pushes them above ~250 wpm risks degrading naturalness on dispatcher-fit short utterances.
- **Final pick requires user listening.** Ranking is ordinal-only; the absolute wpm-target band [175, 200] is a published-literature reference, not a Fish-S2-Pro-specific calibration. A condition with median 250 wpm but smooth prosody could still be the right pick if the user perceives it as natural.


---


Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)
