# Team L1 — Why does P5 work? Phrase structural forensic audit

**Mode:** read-only. stdlib `wave` + numpy autocorrelation pitch tracker only. No code edits, no pod commands, no commits.

**Audit window:** 2026-04-26T04:42Z, ~30 min ship-by.

**Inputs:**
- `findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/{baseline,T1..T5}/p{1..5}.wav` (30 files)
- `findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/wav2/p4.wav` (cycle-2j cross-ref GO file)
- `findings/voice/cycle2k_speed_control/2026-04-26T040000Z/team_kv_metrics.json` (existing wpm + sps)
- K1 audit: `findings/voice/cycle2k_speed_control/2026-04-26T031403Z/team_k1_speed_audit.md`

**User verdict:**
- GO (3 files, dispatcher-fit): `T1/p5.wav`, `T5/p5.wav`, `cycle2j_wav2/p4.wav`
- NOT GO (28 files): all other cycle-2k files

**Raw features extracted:** `forensic_features.json` (this dir).

---

## Bottom line (one paragraph)

The user-attested GO set (T1/p5, T5/p5, cycle-2j wav2/p4) shares **prosodic steadiness on a falling open-vowel ending** — specifically, simultaneous low f0 standard deviation (≤39 Hz) **and** compact f0 range (≤128 Hz) **and** a clean phrase-internal falling f0 contour. Every NOT-GO file violates at least one of those three (8/28 share the structural-content scaffold of short-syllable + comma-free + falling but ALL of them have f0σ ≥40 Hz **or** f0_range ≥138 Hz). The structural prerequisites (≤5 syllables, no commas, non-question mood, open-vowel terminal phoneme, falling pitch) are necessary but not sufficient: baseline/p5 has every one of them and is still NOT GO because Fish renders it with f0σ=66 / f0_range=322 — a wobbly/unsteady delivery on the same text. The single highest-leverage next lever is **a reference-voice swap to a steady-pitch animated dispatcher clip** (compact f0 range, low f0_std, falling sentence terminus), because the K1 audit already proved Fish has no API knob for prosodic steadiness — that property is transferred from the reference clip's VQ tokens. Comma-stripping, phrase shortening, and pace tags are second-order: each is necessary scaffolding but none alone bridges baseline/p5 NOT-GO → T1/p5 GO when wpm and pace are already identical between them.

---

## Structural feature table (30 cycle-2k files + cycle-2j wav2/p4)

Columns: syl=syllables, cm=commas, mood, wpm (prompt-counted, from `team_kv_metrics.json`), sps=syllables/sec, f0μ/f0σ Hz mean/std (autocorrelation pitch tracker, 30 ms frames / 10 ms hop, voiced-only), f0_range = max-min Hz over voiced frames, shape = falling/rising/level via mean of last-third vs first-third with ±5% threshold, f0Δ% = (last_third - first_third)/first_third × 100, iSil = leading silence ms (≥5% peak), tSil = trailing silence ms, dur = total wav seconds, verdict = user attestation.

| file | syl | cm | mood | wpm | sps | f0μ Hz | f0σ Hz | f0_range Hz | shape | f0Δ% | iSil ms | tSil ms | dur s | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cycle2j_wav2/p4 | 3 | 0 | imperative | 176.1 | 2.94 | 131 | 17 | 100 | falling | -21.5 | 0 | 231 | 1.022 | **GO_xref** |
| baseline/p1 | 10 | 1 | question | 167.8 | 2.80 | 210 | 34 | 260 | falling | -13.0 | 2 | 227 | 3.576 | **NOT_GO** |
| baseline/p2 | 5 | 0 | question | 161.5 | 3.37 | 216 | 39 | 182 | falling | -27.1 | 11 | 15 | 1.486 | **NOT_GO** |
| baseline/p3 | 4 | 0 | question | 246.1 | 4.10 | 114 | 58 | 318 | rising | +9.4 | 4 | 200 | 0.975 | **NOT_GO** |
| baseline/p4 | 3 | 0 | imperative | 155.0 | 2.58 | 122 | 77 | 315 | falling | -48.7 | 1 | 244 | 1.161 | **NOT_GO** |
| baseline/p5 | 5 | 0 | declarative | 222.8 | 3.71 | 127 | 66 | 322 | falling | -30.2 | 18 | 167 | 1.347 | **NOT_GO** |
| T1/p1 | 10 | 1 | question | 234.9 | 3.92 | 270 | 48 | 208 | falling | -19.2 | 2 | 220 | 2.554 | **NOT_GO** |
| T1/p2 | 5 | 0 | question | 184.6 | 3.85 | 332 | 64 | 224 | falling | -18.2 | 7 | 161 | 1.300 | **NOT_GO** |
| T1/p3 | 4 | 0 | question | 215.3 | 3.59 | 210 | 33 | 107 | rising | +33.4 | 36 | 181 | 1.115 | **NOT_GO** |
| T1/p4 | 3 | 0 | imperative | 155.0 | 2.58 | 248 | 127 | 317 | rising | +49.8 | 3 | 245 | 1.161 | **NOT_GO** |
| **T1/p5** | 5 | 0 | declarative | 222.8 | 3.71 | 207 | 39 | 128 | falling | -32.0 | 14 | 193 | 1.347 | **GO** |
| T2/p1 | 10 | 1 | question | 182.0 | 3.03 | 230 | 46 | 168 | falling | -27.3 | 5 | 193 | 3.297 | **NOT_GO** |
| T2/p2 | 5 | 0 | question | 152.0 | 3.17 | 236 | 58 | 242 | falling | -33.6 | 8 | 192 | 1.579 | **NOT_GO** |
| T2/p3 | 4 | 0 | question | 287.1 | 4.79 | 112 | 64 | 302 | rising | +5.1 | 13 | 198 | 0.836 | **NOT_GO** |
| T2/p4 | 3 | 0 | imperative | 193.8 | 3.23 | 156 | 25 | 137 | falling | -27.4 | 8 | 206 | 0.929 | **NOT_GO** |
| T2/p5 | 5 | 0 | declarative | 201.9 | 3.37 | 216 | 52 | 254 | falling | -39.9 | 14 | 172 | 1.486 | **NOT_GO** |
| T3/p1 | 10 | 1 | question | 198.8 | 3.31 | 238 | 42 | 168 | falling | -20.9 | 2 | 190 | 3.019 | **NOT_GO** |
| T3/p2 | 5 | 0 | question | 161.5 | 3.37 | 218 | 38 | 200 | falling | -20.5 | 7 | 115 | 1.486 | **NOT_GO** |
| T3/p3 | 4 | 0 | question | 246.1 | 4.10 | 104 | 6 | 22 | rising | +6.6 | 15 | 171 | 0.975 | **NOT_GO** |
| T3/p4 | 3 | 0 | imperative | 176.2 | 2.94 | 148 | 64 | 292 | falling | -23.7 | 4 | 209 | 1.022 | **NOT_GO** |
| T3/p5 | 5 | 0 | declarative | 170.0 | 2.83 | 185 | 26 | 138 | falling | -26.2 | 18 | 198 | 1.765 | **NOT_GO** |
| T4/p1 | 10 | 1 | question | 198.8 | 3.31 | 225 | 33 | 207 | falling | -21.1 | 12 | 159 | 3.019 | **NOT_GO** |
| T4/p2 | 5 | 0 | question | 156.6 | 3.26 | 215 | 51 | 244 | falling | -30.1 | 7 | 156 | 1.532 | **NOT_GO** |
| T4/p3 | 4 | 0 | question | 246.1 | 4.10 | 110 | 29 | 267 | rising | +9.8 | 15 | 184 | 0.975 | **NOT_GO** |
| T4/p4 | 3 | 0 | imperative | 168.5 | 2.81 | 160 | 107 | 327 | rising | +18.5 | 9 | 191 | 1.068 | **NOT_GO** |
| T4/p5 | 5 | 0 | declarative | 239.3 | 3.99 | 174 | 39 | 143 | falling | -40.8 | 17 | 157 | 1.254 | **NOT_GO** |
| T5/p1 | 10 | 1 | question | 263.7 | 4.39 | 148 | 36 | 290 | falling | -9.8 | 24 | 119 | 2.276 | **NOT_GO** |
| T5/p2 | 5 | 0 | question | 191.4 | 3.99 | 263 | 47 | 202 | falling | -29.7 | 4 | 198 | 1.254 | **NOT_GO** |
| T5/p3 | 4 | 0 | question | 224.7 | 3.75 | 294 | 84 | 308 | level | +2.4 | 8 | 204 | 1.068 | **NOT_GO** |
| T5/p4 | 3 | 0 | imperative | 193.8 | 3.23 | 287 | 132 | 326 | falling | -36.6 | 0 | 213 | 0.929 | **NOT_GO** |
| **T5/p5** | 5 | 0 | declarative | 222.8 | 3.71 | 207 | 39 | 124 | falling | -33.6 | 14 | 230 | 1.347 | **GO** |

(Counts: 3 GO + 28 NOT_GO. Cycle-2j metrics for wav2/p4 wpm/sps recomputed locally — cycle-2j metrics.json doesn't store them. Same K1 conventions: wpm = `words_prompt × 60 / duration_s`, sps = `syllables / duration_s`.)

---

## Discriminator analysis

For each candidate discriminator, the table reports separation between 3 GO and 28 NOT_GO files. `|d|` = absolute Cohen's d. `overlap` = how many NOT_GO values land inside the GO range.

| Candidate | GO range | GO mean | NOT_GO mean (σ) | \|d\| | NOT_GO in GO range |
|---|---|---|---|---|---|
| **f0_range Hz** | [100, 128] | 117.5 | 232 (77) | **2.06** | **1/28** |
| trail_silence_ms | [193, 231] | 217.7 | 182 (44) | 1.08 | 11/28 |
| f0_std Hz | [17, 39] | 31.6 | 54.4 (29) | 1.05 | 9/28 |
| f0_delta_pct | [-34, -22] | -29.0 | -14.6 (23) | 0.87 | 9/28 |
| commas | [0, 0] | 0.0 | 0.2 (0.4) | 0.74 | 22/28 |
| rms | [1653, 5791] | 3608 | 5614 (3567) | 0.72 | 13/28 |
| duration_s | [1.02, 1.35] | 1.2 | 1.6 (0.8) | 0.62 | 9/28 |
| syllables | [3, 5] | 4.3 | 5.4 (2.5) | 0.58 | 22/28 |
| f0_mean Hz | [131, 207] | 182 | 199 (61) | 0.34 | 6/28 |
| init_silence_ms | [0, 14] | 9.1 | 9.8 (7.8) | 0.10 | 20/28 |
| sps | [2.94, 3.71] | 3.5 | 3.5 (0.6) | 0.06 | 13/28 |

**Categorical discriminators** (matches per group):

| Test | GO match | NOT_GO match |
|---|---|---|
| `commas == 0` | 3/3 | 22/28 |
| `f0_shape == falling` | 3/3 | 20/28 |
| `mood == declarative or imperative` | 3/3 | 10/28 |
| `final_phoneme is open vowel (ey/iy)` | 3/3 | 10/28 |
| `mood == question` | 0/3 | 18/28 |
| `f0_shape == rising` | 0/3 | 7/28 |

**Compound tests** (joint discriminators):

| Test | GO | NOT_GO |
|---|---|---|
| open_vowel_final ∧ falling ∧ syl≤5 ∧ commas=0 | 3/3 | 8/28 |
| commas=0 ∧ mood≠question | 3/3 | 10/28 |
| falling ∧ syl≤5 ∧ commas=0 ∧ mood≠question | 3/3 | 8/28 |
| **f0_std ≤ 39 ∧ f0_range ≤ 128 ∧ falling** | **3/3** | **0/28** |

**The cleanest single-feature separator is `f0_range`.** It has Cohen's d = 2.06 — the next-best continuous feature is `trail_silence_ms` at d = 1.08. The cleanest joint separator is `f0_std ≤ 39 Hz AND f0_range ≤ 128 Hz AND falling shape`, which separates 3/3 vs 0/28.

### The decisive comparison: same-phrase, same-pace, different verdict

The six p5 ("Help is on the way.") files share the structural scaffold completely: `syl=5, commas=0, mood=declarative, final_phoneme=ey_diphthong, falling-shape, dur≈1.3-1.8s`. Yet only 2 of 6 are GO:

| file | dur | wpm | sps | f0μ | **f0σ** | **f0_range** | f0Δ% | rms | verdict |
|---|---|---|---|---|---|---|---|---|---|
| baseline/p5 | 1.347 | 222.8 | 3.71 | 127 | **66** | **322** | -30.2 | 8382 | NOT_GO |
| **T1/p5** | 1.347 | 222.8 | 3.71 | 207 | **39** | **128** | -32.0 | 5791 | **GO** |
| T2/p5 | 1.486 | 201.9 | 3.37 | 216 | 52 | 254 | -39.9 | 9544 | NOT_GO |
| T3/p5 | 1.765 | 170.0 | 2.83 | 185 | 26 | 138 | -26.2 | 7410 | NOT_GO |
| T4/p5 | 1.254 | 239.3 | 3.99 | 174 | 39 | 143 | -40.8 | 11425 | NOT_GO |
| **T5/p5** | 1.347 | 222.8 | 3.71 | 207 | **39** | **124** | -33.6 | 3380 | **GO** |

baseline/p5 vs T1/p5: byte-for-byte identical duration (1.347 s), wpm (222.8), sps (3.71), shape (falling), syllable count (5), comma count (0), mood (declarative), open-vowel ending. The only meaningful differences are **f0σ (66 → 39, -41%)** and **f0_range (322 → 128, -60%)** — i.e. Fish renders baseline/p5 with a wobbly/unsteady pitch trajectory and T1/p5 with a steady one. Pace is identical; *steadiness* is the discriminator.

T3/p5 has the best f0σ (26) and reasonable f0_range (138) but is NOT_GO because pace dropped to 170 wpm (the "news anchor pace" tag actually slowed it). T4/p5 has the right f0σ (39) and range (143) but pace went too fast (239 wpm, sps=3.99 — over-articulated) AND f0Δ%=-40.8 is too aggressive a fall (sounds clipped/stern). T2/p5 sits in the messy middle: pace dropped, f0_range climbed.

T1 ("urgent dispatcher pace") and T5 ("911 dispatcher voice") were the only two tags that **simultaneously** held wpm at the baseline 222.8, lifted f0 register to 207 Hz (animated, not flat-affect), tightened f0σ to 39 Hz, and compressed f0_range to ~125 Hz. Those four conditions co-occur in exactly the GO files.

### Cross-validation: the cycle-2j wav2/p4 GO file

cycle2j wav2/p4 has f0μ=131 Hz (low/male register) yet still GO. So *register* alone is not the story — *steadiness* is. Its f0σ=17, f0_range=100 are the lowest in the entire 31-file corpus. It is the same cluster as T1/p5 + T5/p5 along the steadiness axis but on a different point along the register axis. This rules out any "GO requires high f0" hypothesis.

baseline/p4 is the closest counterfactual: same phrase as cycle-2j wav2/p4, same low f0μ (122 vs 131), same falling shape, same trailing silence (244 vs 231 ms). Verdict differs because baseline/p4 has f0σ=77, f0_range=315 — wobbly. cycle-2j wav2/p4 has f0σ=17, f0_range=100 — steady. **The reference voice clip (LibriTTS Mil Nicholson wav2 in cycle-2j) was already a steady-pitch reference and Fish carried that steadiness over via VQ tokens** — corroborates K1 audit's finding that reference clip cadence and prosody dominate.

### baseline/p5 prediction (the unlistened control)

The user listened to all 30 cycle-2k files including baseline/p5; the user's verdict for baseline/p5 was NOT-GO. That is consistent with the steadiness hypothesis: even at the same wpm/sps/shape/syl, baseline/p5 has f0σ=66, f0_range=322 — twice the wobble of T1/T5 — and would be perceived as undelivered/unsteady, not "dispatcher-fit". This is a **passing prediction** of the hypothesis.

---

## Hypothesis

**The structural property that makes audio dispatcher-fit on Fish-S2-Pro is prosodic steadiness on a falling, open-vowel-terminal short declarative — specifically, the joint condition `f0_std ≤ 39 Hz ∧ f0_range ≤ 128 Hz ∧ falling f0_shape ∧ syl ≤ 5 ∧ commas = 0 ∧ mood ≠ question`.**

Evidence:
- **3/3 GO files satisfy all six conditions.**
- **0/28 NOT_GO files satisfy all six.** (The closest NOT_GO miss is T3/p5: pace too slow at 170 wpm. Next closest is T4/p5: pace too fast and f0Δ% too aggressive at -41%.)
- The three structural-content conditions (`syl ≤ 5 ∧ commas=0 ∧ mood ≠ question`) are necessary scaffolding, satisfied by 10 of 28 NOT_GO files. Therefore content-shape alone cannot explain the verdict.
- The two prosodic-stability conditions (`f0_std ≤ 39 ∧ f0_range ≤ 128`) bridge the gap. Only 1/28 NOT_GO files even crosses the f0_range threshold (T3/p3 at f0_range=22 — but it's a rising-shape question, fails the falling+mood scaffold).
- The K1 audit established that Fish has no API knob for pace, no field for prosody. The model emits prosodic micro-pauses and pitch wobble emergently from its AR sampler conditioned on the reference clip. Steadiness is therefore **inherited from the reference clip**, not imposed by config.

**Fish's free-form prosody tags (`[urgent dispatcher pace]`, `[911 dispatcher voice]`) work for short, structurally-clean phrases by simultaneously lifting f0 register AND tightening f0_std AND preserving baseline pace** — the tags appear to map to Fish's training-data examples of "animated, professional, steady" speakers. The tags fail on longer phrases because the inherent comma-pause and length-driven pace decay (see K1 audit, Pearson r = -0.17 to -0.37 for length vs wpm) overwhelm the tag's prosodic effect.

The cycle-2j wav2/p4 GO is the same phenomenon via a different route: a steady-pitch LibriTTS narrator reference clip (Mil Nicholson reading Dickens) yields steady output for the *shortest* phrase in the corpus where the audiobook narrator's natural slow pace happens to align with "dispatcher gentle reassurance" register on a 3-syllable imperative.

---

## Engineering levers ranked by hypothesis-fit

### 1. Reference-voice swap to a steady-pitch animated dispatcher clip (HIGHEST LEVERAGE)

**Why:** The hypothesis says `f0_std ≤ 39 ∧ f0_range ≤ 128` is the binding constraint, and Fish carries reference-clip prosody via VQ tokens (K1 audit, source [#10] in Sources). The current cycle-2k baseline reference is whatever default Fish ships; cycle-2j wav1/wav2 are LibriTTS audiobook clips whose steadiness is inherited but whose register/pace doesn't generalize across phrases. **The fix is a reference clip from an actual PSAP dispatcher or news anchor with measured f0_std ≤ 30 Hz and f0_range ≤ 130 Hz across 10-30 s of speech.** Predicted effect: shifts the floor of f0_std and f0_range across all phrases simultaneously, the way pace lift currently works only for p5.

**Caveats:** sourcing time; license clearance; Fish may still introduce comma-pauses on P1-style multi-clause text (hypothesis predicts comma stripping is still required as a co-lever).

**Cost:** clip sourcing only (no infra, no code). Reversible via `PRISM42_FISH_REFERENCE_AUDIO` env var (already exists per K1 audit, line 137).

### 2. Comma-stripping at adapter (STRUCTURAL PREREQUISITE)

**Why:** None of the 3 GO files contain commas. 6 of 28 NOT_GO files contain commas (all P1 variants). The K1 audit ranked this #3; this audit confirms commas are absolutely fatal — the hypothesis fails the moment a comma is present because Fish's pause-on-comma behavior wrecks pace and inflates f0_range as the clauses re-prime. **Implement comma-to-period conversion at the LiveKit adapter before sending to Fish.** Two-line change at `agents/livekit/fish_speech_tts.py:185`.

**Caveats:** changes intonation slightly (period closes pitch, comma keeps it open); some sentences will sound choppier (e.g., the rendered "Nine one one. Where is your emergency?" will have a stronger pitch reset than "Nine one one, where is your emergency?"). Lever 1 is what makes that reset land cleanly.

**Cost:** trivial. Reversible via env var.

### 3. LLM-side phrase shortening to ≤5 syllables AND declarative mood (CONTENT LEVER)

**Why:** All 3 GO files satisfy `syl ≤ 5 ∧ mood ∈ {declarative, imperative}`. 10/28 NOT_GO files share that scaffold but fail on prosodic stability — meaning shortening is necessary but not sufficient on its own. Combined with lever 1, shortening becomes the enabler that lets the steady reference clip dominate. **Push Nemotron's system prompt toward declarative grounding statements ("Help is on the way.", "Stay with me.", "Tell me what happened.") instead of multi-clause questions.** Discourage compound noun phrases like "your emergency" — the audit shows P1's "where is your emergency" inflates pace decay regardless of pace tag because of the trailing 4-syllable noun phrase requiring careful enunciation.

**Caveats:** changes UX — more turn-taking, fewer single-shot questions. May feel less natural for "what's your location?" style information-elicit moments.

**Cost:** prompt edit only. Lower priority than levers 1+2 because it's the slowest-iterating lever (prompt → eval cycle).

### 4. Pace tag retention for short phrases only (TACTICAL)

**Why:** The audit shows pace tags T1 and T5 are the only two that lifted wpm to 222.8 on p5 while preserving f0σ ≤ 39 Hz. They actively help on short declaratives. They appear to do nothing or hurt on longer phrases (P1 with `[urgent dispatcher pace]` is at 234.9 wpm but f0σ=48, f0_range=208 — still NOT_GO). **Retain pace tags only for phrases ≤5 syllables AND comma-free, defaulting to no tag for longer utterances.** Adapter change.

**Caveats:** adds branching logic; specific tags behave differently and need pinning. T1 and T5 work; T2/T3/T4 are inferior.

**Cost:** small adapter change.

### 5. Sampler temperature increase (LOW RANK, HIGH RISK)

**Why:** baseline/p5 has the same content as T1/p5 but with f0_range=322 vs 128 — Fish's sampler at τ=0.1 with default reference voice produced an unsteady delivery. Raising τ to 0.3-0.5 *might* let the model break out of slow patterns or *might* increase wobble further. K1 audit ranks this risky; this audit can't predict the direction. Try only after levers 1-4.

### 6. Engine patch (OUT OF SCOPE)

Patching Fish's inference engine to penalize f0 wobble is a research project, not a hackathon lever. Skip.

---

## Caveats

- **n=3 GO is small.** Three GO files give Cohen's d but no inferential statistics. The discriminators are descriptive, not causal — a controlled experiment swapping reference clips at fixed text would test the hypothesis directly.
- **F0 tracker is autocorrelation-based, not Yin/Crepe.** Voiced/unvoiced classification at 5% peak energy may miscount in heavily-fricative passages. Spot-checked baseline/p3 ("Are they breathing?"): rising shape and f0_range=318 are consistent with the trailing voiceless `breath`-onset followed by pitched `-ing`. Fine for relative comparisons across the 31 files (same tracker, same parameters).
- **The hypothesis predicts f0_std and f0_range thresholds; a future evaluation needs to bake those into a CI-style listening test gate.** The current verdict-set is too small to fix exact thresholds — 39 Hz / 128 Hz are upper bounds observed, not statistically derived.
- **Subjective elements (timbre, character, "feels like a dispatcher")** may correlate with f0_range/f0_std but aren't directly measurable here. The user's 1.0x verdict on cycle-2j wav2/p4 is itself partly stylistic — "Stay with me." is a canonical dispatcher reassurance. The hypothesis should not be over-interpreted as "low f0_range guarantees dispatcher-fit"; rather, it identifies the necessary acoustic scaffold.
- **K1 found the same direction.** This audit corroborates K1's "no Fish speed knob, prosody is reference-clip-mediated" finding and adds the f0_std/f0_range quantification that was missing from K1.
- **Multiple discriminators correlate.** Comma-presence forces longer utterances which forces pace decay which inflates f0_range during clause-boundary pauses. Treating these as independent levers is wrong; the hypothesis-implied bundle is `short ∧ comma-free ∧ falling ∧ steady-reference`. Levers 1+2+3 should ship as a single coordinated change, not sequentially.
- **cycle-2j wav2/p4 used a different reference voice than cycle-2k.** Cross-cycle comparison is therefore confounded with reference-voice provenance. The hypothesis predicts this confound is *the point* — reference voice is the dominant lever — but a within-cycle replication with the LibriTTS wav2 reference applied to all 5 cycle-2k phrases would isolate it cleanly.

---

## Sources

- `findings/voice/cycle2k_speed_control/2026-04-26T040000Z/audio/{baseline,T1..T5}/p{1..5}.wav` — 30 audio files analyzed
- `findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/wav2/p4.wav` — cycle-2j cross-ref GO file
- `findings/voice/cycle2k_speed_control/2026-04-26T040000Z/team_kv_metrics.json` — wpm/sps source
- `findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/metrics.json` — cycle-2j duration/peak/rms (wpm/sps recomputed locally)
- `findings/voice/cycle2k_speed_control/2026-04-26T031403Z/team_k1_speed_audit.md` — K1 audit (Fish has no speed knob; prosody emerges from reference clip + sampler)
- `findings/voice/cycle2L_forensic/2026-04-26T044254Z/forensic_features.json` — full per-file feature extraction (this audit)

---

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits).
