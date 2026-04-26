# F0 validation — cycle-2N MW reference

## Tracker

`team_mv_analyze.py` from `cycle2M_steadiness/2026-04-26T051841Z/`:
autocorrelation pitch tracker w/ subharmonic-preference octave correction
+ 5-frame median snap. 30 ms window, 10 ms hop, F0 range 70–400 Hz.

## L1 GO criterion (anchor)

- **strict**: `f0_std ≤ 30 Hz AND f0_range ≤ 130 Hz`
- **loose**: `f0_std ≤ 39 Hz AND f0_range ≤ 128 Hz`
- M-V tracker reports ~63% higher than L1's per cycle-2M notes.
  M-V f0_std=50 ≈ L1 f0_std=30. M-V f0_std=39 ≈ L1 f0_std=24.

## MW reference window sweep (M-V tracker)

| Window  | dur s | f0_mean | f0_std | f0_range | f0_p5p95 | voiced% | rms    | peak   |
|---------|------:|--------:|-------:|---------:|---------:|--------:|-------:|-------:|
| 35..50  | 15.0  | 173.1   | **38.3** | 296.5  | 108.2    | 33.8    | 0.0850 | 0.607  |
| 40..52  | 12.0  | 175.0   | 39.9   | 296.5    | 109.7    | 37.1    | 0.0914 | 0.738  |
| 40..55  | 15.0  | 175.7   | 41.7   | 296.5    | 126.9    | 37.9    | 0.0921 | 0.738  |
| 30..45  | 15.0  | 173.5   | 43.2   | 263.8    | 121.5    | 34.2    | 0.0873 | 0.653  |
| 55..70  | 15.0  | 171.4   | 45.4   | 274.2    | 151.6    | 36.8    | 0.0837 | 0.775  |
| 5..20   | 15.0  | 174.3   | 51.9   | 284.9    | 153.3    | 43.1    | 0.0913 | 0.744  |

35-50s selected — steadiest 15s window in the 72s recording.

Validity gate: PASS (f0_std=38.3 ≤ 50 (M-V loose), 0 clipping samples,
duration in 10–30s window, transcript clean from Parakeet).

## MW outputs (5 PSAP phrases, M-V tracker)

| phrase | dur s | f0_mean | f0_std | f0_range | voiced% | peak   | pass_loose | pass_strict |
|--------|------:|--------:|-------:|---------:|--------:|-------:|-----------:|------------:|
| p1     | 3.16  | 158.7   | 29.6   | 146.3    | 65.2    | 0.8547 |    NO (range 146>128) | NO |
| p2     | 1.21  | 154.8   | 31.7   | **123.8**| 46.6    | 0.8547 |    YES     | NO (std 31.7>30) |
| p3     | 0.93  | 152.4   | 33.1   | 256.1    | 73.3    | 0.8547 |    NO      | NO |
| p4     | 1.02  | 169.4   | 44.2   | 277.0    | 60.0    | 0.8547 |    NO      | NO |
| p5     | 1.21  | 192.9   | 39.9   | 208.2    | 56.8    | 0.8547 |    NO      | NO |

PASS_loose: **1/5** (only p2 — narrow phrase "What's your location?")
PASS_strict: 0/5

Aggregate: mean f0_std=35.7, mean f0_range=202.3, mean f0_mean=165.6.

## psap-fast outputs (cycle-2L re-measured under M-V tracker)

| phrase | dur s | f0_mean | f0_std | f0_range | voiced% | pass_loose | pass_strict |
|--------|------:|--------:|-------:|---------:|--------:|-----------:|------------:|
| p1     | 2.00  | 166.2   | 33.0   | 227.2    | 82.7    |    NO      | NO |
| p2     | 0.98  | 169.9   | 27.0   | 135.5    | 72.6    |    NO (range 135.5>128) | NO (range 135.5>130) |
| p3     | 0.70  | 179.0   | **12.8**| 49.4    | 92.5    |    YES     | YES |
| p4     | 0.70  | 165.4   | 38.4   | 148.3    | 76.1    |    NO      | NO |
| p5     | 0.98  | 167.1   | 31.7   | 103.8    | 74.7    |    YES     | NO (std 31.7>30) |

PASS_loose: **2/5** (p3, p5)
PASS_strict: 1/5 (p3 only — anchor)

Aggregate: mean f0_std=28.6, mean f0_range=132.8, mean f0_mean=169.5.

## Direct comparison

```
metric              MW         psap-fast    delta
mean f0_std         35.7       28.6         +7.1 (worse)
mean f0_range       202.3      132.8        +69.5 (worse)
PASS_loose          1/5        2/5          -1
PASS_strict         0/5        1/5          -1
```

MW does not improve on psap-fast on any aggregate steadiness metric.

## L1 1:1 inheritance hypothesis check

```
ref.f0_std = 38.3
output.mean.f0_std = 35.7
ratio = 0.93
hypothesis_status = PARTIAL_INHERITANCE
```

The reference IS communicating prosody to the output, but at a 0.93 multiplier
(not a strict 1:1). Floor-effect: a 38.3 Hz reference cannot yield <38.3*0.93=35.6 Hz
output, far above the 30 Hz strict gate.

To reliably pass 4/5 PASS_loose, the reference needs f0_std around 30 Hz
(M-V tracker) — well below the 38.3 the MW sample offers.
