# Phase B — improvement team scope

Single Glasswing-scopable team applying surgical changes to the existing
Fish + LiveKit + vLLM stack to maximize empathy + naturalism + perceived
snappiness without regressing the 2468 ms Fish p95 win.

**No engine swap. No sample-rate change. No sampler retuning.**
**Deterministic voice identity (`seed=911`) preserved.**
**ElevenLabs fallback path under `/prism42` not touched.**

Companion file: `research.md` — Phase A coverage with citations.

---

## Team identity

- **Name:** `voice-empathy-tags-team`
- **Mission:** Wire Fish S2-Pro's existing inline-tag expressive
  control [research.md A1, A7] into our PSAP voice path. Three
  surgical changes, all env-flag-gated default OFF, all individually
  reversible. Validate via blind A/B MOS + acoustic-feature analysis
  before flipping defaults.
- **Glasswing scope shape:** scoped (3 changes), tasked (file:line
  targets explicit), tested (calibrated subjective + objective
  protocol), looped-team (1 generator + 1 evaluator + 1 listener panel
  coordinator).
- **Ship-by:** 2026-04-26 23:59 PT (within hackathon mode §0 deadline).
- **Failure modes anticipated:**
  - Fish renders `[calm]` as literal speech text — caught by C1 smoke.
  - Tags pass through but produce no audible effect — caught by C2 acoustic
    delta check.
  - Listener panel reports tags make the voice WORSE — fall back to
    default OFF, lose nothing.
  - Bench p95 regresses past 2468 ms — fall back to default OFF.
  - Tags force Fish into a different sampling region that breaks
    `seed=911` byte-identical determinism — caught by C3 SHA check.

---

## Three surgical changes

### Change 1 — `[tag]`-prefixed dispatcher prompt directive

**Goal:** Fish receives every dispatcher reply prefixed with a small
voice-direction tag block. The tag block conditions the text2semantic
model toward calm + soft + reassuring prosody [research.md A1, A3, A7].

**File:line targets:**

- `agents/livekit/orchestrator.py:28` — `FAST_DISPATCHER_SYSTEM_PROMPT`
  - Add a new `# VOICE DIRECTION` section before `# CONTEXT`:
    ```
    # VOICE DIRECTION (rendered by Fish S2-Pro tag interpreter)
    Begin every reply with the literal token sequence:
        [calm soft]
    Do NOT explain it. Do NOT skip it. The token block is silent voice
    direction; it conditions the TTS layer on the reply's prosody.
    Do NOT add other bracket tags inside the reply unless the
    dispatcher protocol explicitly says to.
    ```
- `agents/livekit/worker.py` — add a new env flag near
  `FILLER_DELAY_S` (line 93):
  ```python
  ENABLE_TTS_PROSODY_TAGS: bool = os.environ.get(
      "PRISM42_ENABLE_TTS_PROSODY_TAGS", "0"
  ) == "1"
  ```
- `agents/livekit/orchestrator.py` — gate the prompt section on the
  env flag at the module level so flipping the flag rebuilds the
  prompt cleanly.

**Patch shape:** env-flag-gated (`PRISM42_ENABLE_TTS_PROSODY_TAGS=0` =
default OFF). When OFF, prompt is unchanged from current production.

**Predicted impact (sourced):**
- Fish [S13][S14][S15][S17] documents inline `[tag]` syntax accepts
  free-form direction at word position; `[calm soft]` is a
  model-interpreted instruction comparable to `[whisper in small
  voice]`, `[professional broadcast tone]`. *Predicted MOS lift on
  empathy axis: +0.3 to +0.6 on a 5-point scale*. Cited basis:
  Hume's documented prosodic effect of system-prompt direction
  ("warm and nurturing" → soothing voice) [S10] and WellSaid's finding
  that prosodic variation dominates naturalness ratings [S49].
- *Predicted naturalness MOS effect:* neutral or slight positive.
  Tag is silent (model treats it as condition, not phoneme) — risk is
  rendering as literal speech, mitigated by smoke test.

**Risk:** **Low.** Worst case Fish reads `[calm soft]` aloud; caught
in 5 minutes by smoke listen. Default OFF means production
immediately reverts.

**Apply+bench time:** 30 minutes (10-line prompt change + 1-line env
gate + 5-line worker edit + smoke listen).

---

### Change 2 — Tagged filler variants with tonal direction

**Goal:** The current 5-string filler tuple at `worker.py:75-81` is
flat. Replace with bracketed variants so each filler arrives at Fish
already prosody-directed [research.md A2, A5].

**File:line targets:**

- `agents/livekit/worker.py:75-81` — `FILLERS` tuple. Replacement
  block (only loaded when env flag is on):
  ```python
  FILLERS_PLAIN: tuple[str, ...] = (
      "Okay, stay with me.",
      "Got it, one moment.",
      "I hear you.",
      "Alright, hold on.",
      "Okay.",
  )
  FILLERS_TAGGED: tuple[str, ...] = (
      "[soft] Okay, stay with me.",
      "[calm gentle] Got it. One moment.",
      "[breathy reassuring] I hear you.",
      "[soft warm] Alright. Hold on.",
      "[calm] Okay.",
  )
  FILLERS: tuple[str, ...] = (
      FILLERS_TAGGED if ENABLE_TTS_PROSODY_TAGS else FILLERS_PLAIN
  )
  ```
- The existing `_fire_filler` async function at `worker.py:823` does
  NOT need changes; it consumes whatever `FILLERS` resolves to.
- `last_filler` deduplication at `worker.py:828-830` continues to
  work over the tagged strings unchanged.

**Patch shape:** env-flag-gated (same flag as Change 1). Keeps the
plain tuple as the documented baseline; the tagged tuple is used
only when the flag is set.

**Predicted impact (sourced):**
- Hamming [S20]: "filler sounds can make 1000 ms feel like 500 ms" —
  but only if they sound natural. Tagged fillers should preserve the
  perceptual lift while sounding less like a single canned voice
  loop. *Predicted listener-rated "did the agent sound canned"
  detection rate: -20 to -40%* against current.
- Tag vocabulary chosen from Fish's confirmed-accepted list per
  HackerNoon enumeration [S16] (`[soft]`, `[gentle]`,
  `[breathy]`, `[calm]`, `[reassuring]` is composable per S13's
  free-form rule). The HCI literature [S26][S27] supports softer +
  slower + downward-contour fillers as the empathy-coded variants.

**Risk:** **Low.** Each filler is independently testable. If one
specific tag breaks the audio (e.g., Fish renders `[breathy
reassuring]` as garbled diphone glue), pull just that filler from
the tagged tuple — we still have four good ones.

**Apply+bench time:** 20 minutes (10-line replacement + smoke listen
to all 5 variants).

---

### Change 3 — Sentence-pause discipline in scripted protocol output

**Goal:** Prevent the run-on-monotone anti-pattern [research.md A5,
S37, S26]. Insert `[short pause]` between separable directive
clauses in dispatcher replies. Mirrors APCO scripted-direction
discipline [S33] without changing the protocol words.

**File:line targets:**

- `agents/livekit/orchestrator.py:46-65` — `# YOUR JOB` and
  `# FIRST TURN — VERBATIM` sections. Two specific edits:
  - Section `# YOUR JOB` at `:46`: append a sentence:
    ```
    When your reply has TWO separable parts (acknowledgement + ask),
    place [short pause] between them. Example:
    "[calm] Help is on the way. [short pause] Tell me, is he breathing?"
    Do NOT use [short pause] within a single clause.
    ```
  - Section `# FIRST TURN — VERBATIM` at `:58`: keep verbatim
    text unchanged (`"Nine one one, what is your location and
    emergency?"`) — single clause, no pause needed. Add the
    `[calm]` prefix only if Change 1 is enabled.
- `agents/livekit/worker.py` — no changes needed; tag pass-through
  via Fish is already in place.

**Patch shape:** env-flag-gated (same flag as Changes 1 + 2). When
OFF, prompt produces no `[short pause]` tags.

**Predicted impact (sourced):**
- Run-on cadence is a top-listed anti-robotic pattern [research.md
  A5][S37]. `[short pause]` is on Fish's confirmed tag list [S16].
- *Predicted naturalness MOS effect:* +0.2 to +0.5 on directive-heavy
  utterances ("Help is on the way. Tell me is he breathing?").
  Smaller effect on single-clause replies.
- *Predicted compliance effect (from APCO scripted-direction
  research [S33][S39]):* a slight measured pause after the
  reassurance phrase before the next directive is consistent with
  trained-dispatcher cadence.

**Risk:** **Low-medium.** The model might over-insert `[short
pause]`, breaking utterances into too many fragments and
**lengthening** Fish's render time enough to threaten p95.
Mitigation: bench p95 must be reverified after enabling.

**Apply+bench time:** 25 minutes (5-line prompt edit + smoke listen
+ bench p95 reverify).

---

## Combined patch shape

```bash
# All three changes share one env flag.
PRISM42_ENABLE_TTS_PROSODY_TAGS=1 ./run-worker.sh
# Default OFF — production behavior unchanged.
PRISM42_ENABLE_TTS_PROSODY_TAGS=0 ./run-worker.sh   # or unset
```

Total surface: ~25 lines across two files. All reversible by env flip.

---

## Testing protocol

Two-track validation. Subjective measures cannot be bench-friendly
[research.md A8] but we calibrate them.

### Track A — blind A/B MOS panel (subjective, primary)

- **Stimulus generation:** 12 dispatcher replies drawn from existing
  fixture corpus (`tests/voice/fixtures/` if present, else mint 12
  scripted replies covering: 4 first-turn greetings, 4 reassurance
  + question pairs, 4 pre-arrival CPR instructions). Each
  rendered TWICE through Fish: once with
  `PRISM42_ENABLE_TTS_PROSODY_TAGS=0`, once with `=1`. **24 audio
  files, all from the same Fish weights, same `seed=911`.** Tag
  on/off is the only delta.
- **Listener panel:** 3 raters minimum, 5 ideal. Recommend Brandon
  + 2 unaffiliated. Blinded — file naming randomized; rater
  doesn't know A vs B.
- **Per-utterance ratings (5-point Likert each):**
  1. Naturalness: "How human-sounding does this voice sound?"
     1=robotic, 5=indistinguishable from human.
  2. Empathy: "How much does this voice sound like it cares?"
     1=cold, 5=deeply empathetic.
  3. Calm: "How calm does this voice sound for a 911 dispatcher?"
     1=panicked, 5=perfectly composed.
  4. Snappy: "Did the response feel responsive (not laggy)?"
     1=very laggy, 5=very snappy.
- **Scoring:** Mean ± 95% CI per condition per dimension.
- **Decision rule:** Ship Change i if **the paired-A/B mean
  delta's 95% CI excludes 0 on Empathy OR Calm AND the Naturalness
  CI does not exclude 0 below**. (Mirrors the §4 paired-design
  benchmark discipline from CLAUDE.md.) Apply per change.
- **Inter-rater reliability:** Cronbach α >=0.7 across 3 raters or
  expand panel.
- **Min detectable effect (MDE):** at n=3 raters x 12 utterances =
  36 paired observations, MDE for paired Likert with σ≈0.7 is
  Δ≈0.4 at α=0.05. **A real effect smaller than 0.4 will not be
  detected; this is acceptable because anything less is unlikely
  to be worth shipping.**

### Track B — acoustic feature analysis (objective, corroborating)

- **Tools:** Praat or `parselmouth` Python wrapper for F0 +
  intensity. Free, well-known [S26].
- **Per-condition metrics on the same 24 audio files:**
  1. Mean F0 (Hz). Hypothesis: calm-tagged < plain.
  2. F0 standard deviation. Hypothesis: calm-tagged shows MORE
     downward-contour variation (specifically end-of-sentence
     drops), but lower spike-driven SD.
  3. Mean speaking rate (syllables/sec). Hypothesis: calm-tagged
     slightly slower (140-150 wpm target [S27]).
  4. Pause entropy: distribution of inter-clause silence durations.
     Hypothesis: calm-tagged with `[short pause]` shows distinct
     bimodal distribution; plain shows roughly uniform.
- **Decision support:** acoustic deltas in the predicted direction
  are corroborating signal but NOT the ship decision; subjective
  Track A is dispositive.

### Track C — rails (regression checks, blocker)

- **C1. Tag-rendering smoke (5 min):** play all 5 tagged fillers +
  3 `[calm soft] Help is on the way` test replies. Manual listen.
  PASS if no bracket text rendered as literal phoneme.
- **C2. Determinism check (5 min):** run the same tagged input
  through Fish twice with `seed=911`. Compare SHA256 of output PCM.
  PASS if byte-identical (matches the 2026-04-24 deterministic
  sampling fix `fish_speech_tts.py:43-56`).
- **C3. p95 latency reverify (15 min):** existing
  `bench_b300.py` smoke. PASS if p95 <= 2600 ms (5% headroom over
  the cycle-2d 2468 ms baseline). FAIL forces flag default OFF.
- **C4. Bench utterance set:** confirm the same canonical bench
  utterances ("I have chest pain", etc.) still produce coherent
  speech with tags appended. PASS by listening + transcript-
  alignment if available.

### Track D — verification commands

```bash
# C1 + C2 in one shot — fixed input, two runs
make voice-tag-smoke           # to be added; mints A/B audio + sha
# C3 — bench reverify
make voice-bench               # existing
# Track A — listener panel intake
make voice-mos-panel SET=tags-2026-04-25
```

`make voice-mos-panel` uploads stimuli to a shared review surface (or
emits a local `mos_panel.html` that randomizes A/B and writes ratings
to `findings/voice/best_in_class_2026-04-25/mos_results.csv`).

---

## Failure modes & rollback

| Symptom | Diagnosis | Action |
|---|---|---|
| Fish renders `[calm soft]` literally | Tag passthrough not interpreting | C1 fail; revert prompt addition; investigate Fish tag whitelist |
| All 3 changes show no MOS delta | Listeners can't hear difference | Ship anyway — no harm — OR pull tags as visual clutter not earning their keep |
| Empathy MOS up but Naturalness MOS down | Tags caused glitches or weirdness | Ship Change 1 + 3 only; pull Change 2 (filler set) |
| p95 regresses past 2600 ms | Tags forcing Fish into different sampler region | C3 fail; flag default OFF |
| `seed=911` SHA mismatch with tags on | Tags affect deterministic sampling | C2 fail; flag default OFF; deeper investigation |
| Listener panel disagrees (κ<0.5) | Subjective effect not strong enough to detect | Expand panel to 5; if still disagree, no-op (do not ship from a contested signal) |

**Rollback is one env-var flip.** No code revert needed.

---

## Why this is the right scope

1. **Surgical.** 25 lines, three files, one env flag.
2. **Stack-respecting.** No engine swap. Fish's existing capability
   is the lever.
3. **Sourced.** Each change cites Fish docs [S13][S14][S15][S16][S17]
   for syntax, plus 911-specific dispatcher research [S33][S35][S36][S37][S39]
   for direction.
4. **Measurable.** Track A subjective + Track B objective + Track C
   regression. Decision rule is paired-CI.
5. **Reversible.** Default OFF means production is unchanged until
   the ship decision lands.
6. **Mainline-safe.** Does not touch the ElevenLabs fallback (`/prism42`),
   does not touch the cycle-2d Fish patches, does not touch the
   coordinator/orchestrator beyond two prompt-section edits.
7. **Glasswing-shaped.** One owner, three changes, one ship-by, three
   verify commands, anticipated failure modes enumerated.

---

## What we are intentionally NOT doing

- No tempo-mirroring of the caller (research [S35] argues against
  literal mirroring for emergency calls; counter-prosody is the safer
  default).
- No mid-utterance amplitude modulation (Fish doesn't expose it as
  inline tag; would require sampler retuning).
- No SSML retrofit on Fish (engine doesn't speak SSML [research.md A7]).
- No adding tag interpretation to the worker (`worker.py` should not
  parse / strip / rewrite tags; Fish should see exactly what the
  prompt produced).
- No Cartesia/ElevenLabs/Hume swap (out of hackathon scope; locked).
- No voice-cloning preset of a real dispatcher [S48 — safety].
- No removal of the "SYNTHETIC TRAINING SIMULATION" framing
  [orchestrator.py:28-43; required by safety research S44-S48].
- No mental-health crisis routing changes (out of scope for this
  team; flagged in research.md A4 as a separate workstream needed
  before any production push).
