# L1 hypothesis empirical check — cycle-2M

**Hypothesis under test (Team L1, cycle-2L):**

> If a reference clip has steady f0 (f0_std ≤ 30, f0_range ≤ 130, falling shape), Fish-S2-Pro's VQ-token inheritance carries that steadiness into the synthesized output, lifting the output above the GO bar.

**Result: PARTIAL — antecedent never satisfied; mechanism appears consistent with data but prediction not testable here.**

## Reference vs output, side-by-side

Reference f0 from M-V (M-V tracker; same family of autocorrelation as L1 / this run, but different voicing gate).
Output f0 from this run (`aggregate_metrics.py`; calibrated to 1.00× on T1/p5 GO anchor).

| condition | reference f0_std | reference f0_range (p5-p95) | output f0_std mean | output f0_range mean | output PASS_loose count |
|---|---|---|---|---|---|
| M1 (`..._000001_000000.wav`, dur 13.53 s) | 50.9 | 132.2 | **49.0** | **352.7** (max-min) | 0/5 |
| M2 (`..._000013_000000.wav`, dur 10.95 s) | 51.2 | 139.8 | **46.8** | **288.4** (max-min) | 1/5 |

**Pattern: output f0_std ≈ reference f0_std** (M1: 50.9 → 49.0; M2: 51.2 → 46.8). The ratio is ~0.95–1.00. Fish does not magnify or attenuate the reference's steadiness; it inherits it ~1:1 — consistent with L1's stated mechanism (VQ tokens carry prosodic features). Output f0_range is ~2.5–3× higher than reference's p5-p95 range, but that's expected: outputs are short 1–3 s utterances where a single-frame outlier can dominate max-min, while references are 10–14 s narrations where p5-p95 dominates. A like-for-like comparison (output max-min vs reference max-min) shows reference 263–308 Hz vs output mean 288–353 Hz — output is 1.0–1.3× the reference, again consistent with ~1:1 inheritance plus normal noise.

## Why the hypothesis cannot be cleanly accepted or rejected

L1's hypothesis predicts: **steady reference → steady output passes GO bar**. The contrapositive is testable: **unsteady reference → unsteady output**, which IS what we see. But the affirmative prediction requires a steady reference (f0_std ≤ 30), which neither M1 nor M2 provides:

- M-V's audit (this dir, `team_mv_validation.md` §"Caveats" item 1): "NO file in the 6 [LibriTTS Mil Nicholson candidates] meets L1's strict f0_std ≤ 30 Hz GO criterion, even on the loose ≤ 39 Hz bound. The candidates run 51–69 Hz f0_std, well above."
- The candidate pool (LibriTTS Mil Nicholson speaker_id 2026) is too wobbly for the hypothesis's pre-condition. Selecting the best-of-this-pool gives references at 51 Hz, which Fish then inherits at 47–49 Hz, still failing the 39 Hz loose bound and the 30 Hz strict bound by a wide margin.

What the data DO confirm:

1. **Inheritance is real.** Reference steadiness predicts output steadiness with ratio ≈ 1.0. So the mechanism L1 posited (VQ-token transfer of prosodic features) is consistent.
2. **No multiplicative magic.** Fish does not "smooth" an unsteady reference. If you want output steadiness, you must supply reference steadiness.
3. **The selection ceiling is hit.** Within the LibriTTS pool M-V audited, the 1st-ranked candidate's output (M1) is no better than the 3rd-ranked candidate's output (M2 has 1 PASS to M1's 0, but that's likely tracker noise on a single phrase). Picking finer-grained between candidates with reference f0_std clustered at 51 ± 9 Hz is below the noise floor.

## What would falsify L1 cleanly

Either:

- **Find a real-world reference at f0_std ≤ 30.** Bench it. If the output also lands at f0_std ≤ 30 and passes ≥ 4/5, hypothesis CONFIRMED. If output stays high despite low-f0_std reference, hypothesis FALSIFIED (mechanism is not VQ-token-mediated).
- **Find a reference whose f0_std ≪ output's f0_std.** This would refute the ~1:1 inheritance ratio observed here.

Neither test was possible in this run because both candidates failed the antecedent.

## What this run DOES rule out

- **The LibriTTS Mil Nicholson speaker_id 2026 corpus** is exhausted on the steadiness axis. M-V audited 6 files, ranked them, picked top-2; bench shows the top-2 outputs are strictly worse than the existing psap-fast default. Trying more files from this corpus is not the lever.
- **More reference variation** within the audiobook-narration genre is unlikely to clear the 30/39 Hz threshold. Audiobook narrators inherently use prosodic variation as a craft tool — that's the opposite of dispatcher steadiness.

## Production implication

Production currently uses `FISH_SPEECH_REFERENCE_ID=psap` (set in `.env`). The cycle-2L `B_psap_fast` outputs measured 3/5 PASS_loose under this same tracker. Both M-candidates would regress production from 3/5 to 0–1/5. **Reverting drop-in (done) and keeping psap reference is the strictly-better default until a steadier reference is sourced.**

## Sources

- L1 audit: `findings/voice/cycle2L_forensic/2026-04-26T044254Z/team_l1_phrase_audit.md` (GO criterion + anchor file)
- M-V validation: `findings/voice/cycle2M_steadiness/2026-04-26T051841Z/team_mv_validation.md` (top-2 ranking + caveats)
- L1 anchor file: `findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/wav2/p4.wav` (cycle-2j wav2/p4, the GO_xref anchor at f0_std=17 / f0_range=100 by L1's tracker)
- This run's f0 tracker calibration: 1.00× on T1/p5 (39 vs L1 39); 1.00× on T1/p5 range (127.7 vs L1 128); diverges (~2.85×) on cycle-2j wav2/p4 likely due to F0_MIN floor on low-male register. Calibration is sound for the dispatcher-register outputs that dominate this run.
