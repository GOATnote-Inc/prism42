# Cycle-2L lever test — psap-fast preset and comma-to-period adapter

**UTC:** 2026-04-26T04-43-16Z  
**Method:** Direct-to-Fish HTTP synth bench (bypasses worker.py / LiveKit room flow). 4 conditions × 5 phrases = 20 audio files. Same seed (911), same chunk_length (200), same temp (0.1).

## Results

```
metric                           A baseline             B psap fast            C psap commafix        D psap fast commafix  
real synth success               5/5                    5/5                    5/5                    5/5                   
TTFB p50 (ms)                    2.93                   2.68                   2.68                   2.77                  
TTFB p95 (ms)                    3.62                   43.31                  3.59                   3.30                  
TTFB max (ms)                    3.78                   53.30                  3.81                   3.32                  
total render p50 (ms)            1131.0                 1013.8                 1138.5                 1014.7                
audio duration p50 (s)           1.161                  0.976                  1.161                  0.976                 
median wpm across 5              184.5                  258.2                  184.5                  258.2                 
P1 wpm (slowest phrase)          161.5                  210.3                  164.4                  210.3                 
P5 wpm (the user's good)         248.4                  307.5                  248.4                  307.5                 
audio peak band (s)              0.84-2.60              0.70-2.00              0.84-2.56              0.70-2.00             

phrase                           A_baseline             B_psap_fast            C_psap_commafix        D_psap_fast_commafix  
P1 'Nine one one, where i        161.5                  210.3                  164.4                  210.3                 
P2 "What's your location?        155.0                  184.5                  155.0                  184.5                 
P3 'Are they breathing?'         215.2                  258.2                  215.2                  258.2                 
P4 'Stay with me.'               184.5                  258.2                  184.5                  258.2                 
P5 'Help is on the way.'         248.4                  307.5                  248.4                  307.5                 
```

## Decision

**PICK_B (P1 wpm=210.3 vs A=161.5, lift=48.8)**

## Lever attribution (median wpm vs baseline A)

- **Lever A (psap-fast preset alone, B-A):** +73.7 wpm
- **Lever B (comma-to-period alone, C-A):** +0.0 wpm
- **A+B combined (D-A):** +73.7 wpm

## Lever attribution on P1 (the slowest comma-bearing phrase, vs baseline A)

- **Lever A (psap-fast preset alone):** +48.8 wpm
- **Lever B (comma-to-period alone):** +2.9 wpm
- **A+B combined:** +48.8 wpm

## Rollback (60–90s)

1. (No drop-ins were applied to worker — bench was direct-to-Fish HTTP.)
2. (If drop-ins were ever added) sudo rm /etc/systemd/system/prism42-worker.service.d/{80-cycle2L-refid,81-cycle2L-comma}.conf
3. sudo systemctl daemon-reload && sudo systemctl restart prism42-worker
4. sudo cp /opt/prism42/agents/livekit/fish_speech_tts.py.pre-cycle2L /opt/prism42/agents/livekit/fish_speech_tts.py
5. sudo systemctl restart prism42-worker (only needed if Lever B was activated via env-var)
6. Verify: curl -sf http://localhost:9200/v1/health && systemctl is-active prism42-worker

## Files

- `result.json` — 4-condition aggregate
- `metrics.json` — per-phrase raw metrics
- `metrics_{A,B,C,D}.json` — per-condition raw
- `audio/{A_baseline,B_psap_fast,C_psap_commafix,D_psap_fast_commafix}/p{1..5}.wav` — 20 audio files
- `psap_fast_reference.wav` — the new preset audio
- `setup_psap_fast_reference.sh` — idempotent regen script
- `patch.applied.diff` — adapter diff (Lever B)
- `logs/{worker,fish}.log` — service logs at bench time