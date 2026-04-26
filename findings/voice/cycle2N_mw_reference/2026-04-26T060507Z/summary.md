# Cycle-2N — MW reference voice bench

**Decision:** REJECT_MW. Keep cycle-2L psap-fast as best lever.

## Result table

```
                    cycle-2L psap-fast   cycle-2M M2     MW (this cycle)
real synth success  5/5                  5/5             5/5
TTFB ms p50         2.68                 5–6             1
TTFB ms p95         43.31                5–6             1
total ms p50        1013.79              1156–1211       1167
output f0_std mean  28.6                 46.8            35.7
output f0_range mean 132.8               288.4           202.3
PASS_loose count    2/5                  1/5             1/5
PASS_strict count   1/5                  0/5             0/5
median wpm          258.2                176.1           176.1
audio peak (band)   not measured         not measured    0.8547 (constant)
verdict                                                  REJECT_MW
flag final state    psap default still active; MW staged at /opt/prism42/voice-refs/mw_sample.wav, no drop-in installed
```

(All output f0 numbers measured under the same M-V autocorrelation tracker
from `cycle2M_steadiness/2026-04-26T051841Z/team_mv_analyze.py`; psap-fast
re-measured here for apples-to-apples — cycle-2L's `result.json` did not
publish per-output f0 values.)

## L1 1:1 inheritance hypothesis check

- reference f0_std (M-V tracker, 35–50s window): **38.3 Hz**
- output mean f0_std across 5 phrases: **35.7 Hz**
- ratio: **0.93** — output is ~93% as variable as reference

The output IS slightly steadier than the reference (VQ-token compression
smooths ~7% of f0 variance), but the absolute floor is set by reference
steadiness. To pass 4/5 PASS_loose (≤39), the reference itself needs to
sit comfortably below 39 — call it ≤30 to leave headroom. The MW sample's
steadiest 15s window is 38.3, which is right at the loose-gate edge.

L1's hypothesis is **partially supported**: there IS inheritance, but
the multiplier (~0.93) is not aggressive enough to let a 38 Hz reference
yield <30 Hz outputs.

## What changed vs cycle-2M

- Reference quality: MW is steadier than LibriTTS pool (38.3 vs 50.9–51.2).
- Outputs: MW (35.7) is steadier than M2 (46.8) — confirms reference matters.
- But MW (35.7) is still worse than psap-fast (28.6) — Samantha-via-`say` at
  230 wpm produces a more uniform prosody than a live dispatcher recording,
  even when the dispatcher is steady by absolute terms.

## Production state

- `prism42-worker` active, drop-ins 10/20/50/70 only.
- `FISH_SPEECH_REFERENCE_ID=psap` (from `.env`) — production still uses default
  psap, NOT psap-fast. Per memory notes, drop-in 80-cycle2L-refid.conf was never
  installed; psap-fast lives only as a candidate WAV at
  `/opt/prism42/infra/b300/services/fish-speech/references/psap-fast/ref.wav`.
- MW WAV at `/opt/prism42/voice-refs/mw_sample.wav`, md5 a46b1bf0b20b85a30126ba59ad06b160.
  Inert data — no env var or drop-in references it post-bench.
- Watchdog GREEN before AND after bench. No code edits, no systemd changes.

## Next-move surface

1. **User A/B/C listen** (see `listening_checklist.md`) — the f0 metric
   may not perfectly align with perceived "professional dispatcher tone."
   If MW sounds more authoritative despite higher f0 variance, that's a
   listener-vs-metric tiebreak that the f0 gate cannot resolve.
2. **Sub-15s narrower trim**: the steadiest 12s window is 40-52 (f0_std=39.9
   M-V). Try 8s windows next.
3. **Acknowledge ceiling**: psap-fast is the binding lever on Fish-S2-Pro for
   the PSAP corpus until a reference recording emerges with f0_std ≤30 (M-V tracker).
4. **Tracker audit**: M-V tracker reports ~63% higher than L1's tracker per
   notes. If L1 tracker were used directly, MW outputs (35.7 M-V → ~21.9 L1)
   would clear the strict gate. Worth replicating L1's exact pitch tracker
   to validate gate calibration.
