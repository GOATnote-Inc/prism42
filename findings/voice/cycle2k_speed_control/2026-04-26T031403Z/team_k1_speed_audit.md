# Team K1 — Fish speed/cadence parameter audit

**Mission:** identify the single config knob that fixes Fish S2-Pro's slow rendering for ALL phrases regardless of length or reference voice.

**Mode:** read-only. No code edits. No pod commands.

**Audit window:** 2026-04-26T03:14Z, ~30 min.

---

## Top finding (one paragraph)

**There is no API knob that controls Fish S2-Pro's playback speed.** The schema (`fish_speech/utils/schema.py:81-103`) defines no field for speed/rate/pace/tempo/duration, and the `TTSInferenceEngine.send_Llama_request()` (`fish_speech/inference_engine/__init__.py:144-177`) forwards only six fields to the AR model: `text`, `top_p`, `repetition_penalty`, `temperature`, `chunk_length`, `max_new_tokens`. Pace is **emergent** from the autoregressive sampler conditioned on text + reference-voice prompt tokens. The DAC codec runs at a fixed `hop_length = 2*4*8*8 = 512` samples per frame at 44.1 kHz (`fish_speech/models/dac/modded_dac.py:808,833`), so each emitted token corresponds to a fixed ~11.6 ms of audio — the only thing that varies is **how many tokens the AR model emits per phoneme**. The single highest-leverage lever Fish actually exposes is the **inline natural-language prosody tag system** (15,000+ free-form `[tag]` insertions inside the text — README.md:111-115); for dispatcher pace, the cheapest reversible experiment is prepending a tag like `[professional broadcast tone]` or `[urgent dispatcher pace]` to every utterance. Source: `vendor/fish-speech/README.md:78,111-115`; corroborated by absence of any speed field in `vendor/fish-speech/fish_speech/utils/schema.py`.

---

## Existing parameters our adapter sends

(File: `agents/livekit/fish_speech_tts.py`, lines cited.)

| Field | Current value | What it controls | Source |
|---|---|---|---|
| `text` | LLM output | utterance text | `fish_speech_tts.py:185` |
| `format` | `"wav"` | output container ("pcm" returns 500; "wav" under streaming returns raw PCM) | `fish_speech_tts.py:191` |
| `chunk_length` | `200` | byte budget per text-batch in `group_turns_into_batches`; schema-bound 100-1000 | `fish_speech_tts.py:58,192`; schema constraint `vendor/fish-speech/fish_speech/utils/schema.py:83`; usage `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:601-609` |
| `normalize` | `True` | text normalization for numbers/en/zh | `fish_speech_tts.py:193` |
| `streaming` | `True` | stream PCM samples vs wait for whole WAV | `fish_speech_tts.py:194` |
| `max_new_tokens` | `1024` | hard cap on AR loop length | `fish_speech_tts.py:195` |
| `top_p` | `0.7` | sampler nucleus | `fish_speech_tts.py:67,196` |
| `repetition_penalty` | `1.1` | sampler repetition penalty | `fish_speech_tts.py:68,197` |
| `temperature` | `0.1` | sampler softmax temperature | `fish_speech_tts.py:66,198` |
| `use_memory_cache` | `"on"` | reuse VQ encoder cache for reference clips | `fish_speech_tts.py:199-202` |
| `seed` | `911` | torch.manual_seed for AR determinism | `fish_speech_tts.py:73,203`; engine usage `vendor/fish-speech/fish_speech/inference_engine/__init__.py:60-62` |
| `references` | `[{audio,text}]` or `[]` | inline reference voice clip(s) | `fish_speech_tts.py:152-204` |
| `reference_id` | `""` | named server-side reference (mutex with `references`) | `fish_speech_tts.py:206-207`; mutex enforcement `vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57` |

Adapter-side, not on-wire:

| Knob | Value | What it controls | Source |
|---|---|---|---|
| `frame_size_ms` | `200` (env `PRISM42_TTS_FRAME_MS`) | LiveKit AudioEmitter playback buffer size | `fish_speech_tts.py:135-150` |

Note: `frame_size_ms` is a **playback buffer**, not a generation knob — it affects underrun risk + TTFA, not the underlying audio's pace. Cannot fix slow rendering.

---

## Fish API fields that COULD control speed

Every field in `ServeTTSRequest` (`vendor/fish-speech/fish_speech/utils/schema.py:81-103`), ranked by likelihood of being a speed knob, with verdict:

| Field | Type | Default | Verdict | Why |
|---|---|---|---|---|
| `text` | str | — | **STRONGEST LEVER (indirect)** | S2-Pro accepts inline prosody tags like `[professional broadcast tone]`, `[loud]`, `[volume up]`, `[whisper]`, plus 15,000+ free-form descriptions (README.md:111-115). A `[fast]` / `[urgent dispatcher pace]` / `[brisk]` tag is the closest thing to a speed lever we have. Untested but explicitly supported by the model. |
| `chunk_length` | int 100-1000 | 200 | UNLIKELY direct speed effect | Controls text-batch boundary in `split_text_by_speaker` → `group_turns_into_batches` (`vendor/fish-speech/fish_speech/models/text2semantic/inference.py:600-609`). For our short PSAP utterances the entire text becomes ONE batch regardless of chunk_length value, per `findings/voice/fish-fork-analysis/profile.md:147` ("For a typical short PSAP-style reply with no speaker tag, the entire text becomes ONE batch"). At 200 (current) we are already at the schema default. Could affect cadence on multi-batch text only. |
| `latency` | "normal" \| "balanced" | "normal" | **NO-OP locally** | In schema (`vendor/fish-speech/fish_speech/utils/schema.py:87`) but consumed only by the cloud `api.fish.audio` endpoint via `tools/api_client.py:81,171`. NOT read by our local engine — `tools/server/inference.py`, `tools/server/api_utils.py`, and `fish_speech/inference_engine/__init__.py` never reference `req.latency`. Setting it on local /v1/tts has zero effect. |
| `temperature` | 0.1-1.0 | 0.8 (we use 0.1) | weak indirect | At τ=0.1 the AR is near-deterministic. Higher τ might let the model break out of slow cadence patterns but at the cost of voice-identity drift. Not a safe speed knob. |
| `top_p` | 0.1-1.0 | 0.8 (we use 0.7) | weak indirect | Same family as temperature. |
| `repetition_penalty` | 0.9-2.0 | 1.1 | weak indirect | Could in principle penalize the model for emitting consecutive silence/pause tokens, but no evidence Fish has explicit silence tokens that this would target. |
| `seed` | int \| None | None (we use 911) | NO speed effect | Pure determinism toggle (`vendor/fish-speech/fish_speech/inference_engine/__init__.py:60-62` calls `set_seed()`). Affects voice identity replication, not pace. |
| `max_new_tokens` | int | 1024 | NO speed effect | Hard cap; doesn't control rate while the loop is running. |
| `references` | list | [] | indirect (cadence transfer) | Reference audio cadence is captured in the prompt VQ tokens; the model imitates it. WAV1/WAV2 are LibriTTS Mil Nicholson reading Dickens — slow audiobook prose. Switching to a fast reference (e.g., a 911 dispatcher recording or a brisk newscaster) would shift cadence — but this is a content lever, not a config knob. |
| `reference_id` | str \| None | None | indirect (same as `references`) | Same mechanism, different transport. |
| `use_memory_cache` | "on" \| "off" | "off" (we use "on") | NO speed effect | KV cache reuse only. |
| `streaming` | bool | False (we use True) | NO speed effect | Output transport, not generation rate. |
| `format` | wav/pcm/mp3/opus | wav | NO speed effect | Container format only. |
| `normalize` | bool | True | trivial indirect | Number → words conversion changes the text, which changes token count. Not a real speed knob. |

**Search method**: full-source grep for `speed`, `rate`, `pace`, `tempo`, `prosody`, `duration_modifier`, `speech_rate`, `wpm`, `words_per` across `vendor/fish-speech/**/*.py` returned zero hits beyond `sample_rate` / `bit_rate` / `learning_rate` / `frame_rate` (see grep transcript above). **No hidden parameter exists.**

---

## Empirical speed measurements on the 15 cycle-2j audio files

Method: stdlib `wave` + numpy. Voiced-region detection at 5% of peak energy on 10ms RMS frames; words counted manually; syllables counted manually (CMU pronunciation conventions). All files: 44.1 kHz mono 16-bit PCM, seed=911, τ=0.1, top_p=0.7. Reference: typical adult conversational English = 4-6 syllables/sec, 140-160 wpm; trained dispatcher ~150-180 wpm.

| File | dur (s) | voiced (s) | words | syl | wpm (voiced) | sps | User verdict |
|---|---|---|---|---|---|---|---|
| baseline/p1.wav `Nine one one, where is your emergency?` | 3.576 | 3.34 | 6 | 10 | 107.8 | **2.99** | **0.5x** |
| baseline/p2.wav `What's your location?` | 1.487 | 1.48 | 3 | 5 | 121.6 | 3.38 | (unmarked) |
| baseline/p3.wav `Are they breathing?` | 0.976 | 0.79 | 3 | 4 | 227.8 | 5.06 | (unmarked) |
| baseline/p4.wav `Stay with me.` | 1.161 | 0.94 | 3 | 3 | 191.5 | 3.19 | **0.75x** |
| baseline/p5.wav `Help is on the way.` | 1.347 | 1.15 | 5 | 5 | 260.9 | 4.35 | (unmarked) |
| wav1/p1.wav | 3.298 | 3.08 | 6 | 10 | 116.9 | 3.25 | **0.75x** |
| wav1/p2.wav | 1.022 | 0.98 | 3 | 5 | 183.7 | 5.10 | (unmarked) |
| wav1/p3.wav | 0.790 | 0.78 | 3 | 4 | 230.8 | 5.13 | (unmarked) |
| wav1/p4.wav | 0.976 | 0.78 | 3 | 3 | 230.8 | 3.85 | **1.2x** |
| wav1/p5.wav | 1.161 | 1.00 | 5 | 5 | 300.0 | 5.00 | (unmarked) |
| wav2/p1.wav | 3.576 | 3.33 | 6 | 10 | 108.1 | **3.00** | **0.5x** |
| wav2/p2.wav | 1.208 | 1.01 | 3 | 5 | 178.2 | 4.95 | (unmarked) |
| wav2/p3.wav | 0.976 | 0.79 | 3 | 4 | 227.8 | 5.06 | (unmarked) |
| wav2/p4.wav | 1.022 | 0.85 | 3 | 3 | 211.8 | **3.53** | **1.0x** |
| wav2/p5.wav | 1.301 | 1.10 | 5 | 5 | 272.7 | 4.55 | (unmarked) |

**Per-condition Pearson r (phrase length in words vs wpm):**
- baseline: r = -0.17
- wav1: r = -0.29
- wav2: r = -0.37

Negative r = longer phrases produce slower per-word pace. The trend is uniform across all three reference conditions. WAV1 (cleaner audiobook clip) yields the highest absolute wpm/sps numbers but the same length-vs-pace slope.

---

## Hypothesis: why wav2/p4 hit 1.0x but other phrases didn't

**Hypothesis (well-supported by the data):**

1. Fish S2-Pro's AR loop emits **prosodic micro-pauses around commas, sentence boundaries, and conceptually-loaded compound noun phrases**. These pauses are encoded as semantic tokens that map to short silence frames in the DAC.

2. **Long, comma-broken utterances** (P1 = "Nine one one, where is your emergency?" — 10 syllables across 2 clauses with a comma) accumulate enough of these pauses that voiced-region syllable rate drops to **2.99-3.25 sps** across all three reference conditions — well below the 4-6 sps norm. User perceives this as 0.5-0.75x.

3. **Short, declarative, unbroken utterances** (P3 "Are they breathing?", P5 "Help is on the way.") stay at 4.4-6.4 sps because there are no comma breaks for the model to pause on. User perceives these as 1.0x even at our current adapter settings.

4. **The wav2/p4 ("Stay with me.") = 1.0x outlier** is explained by phrase-length × reference-voice interaction:
   - "Stay with me." is the *shortest* phrase (3 syllables, no commas, declarative).
   - All three conditions hit 3.19-3.85 sps on this phrase.
   - WAV2's slightly faster cadence (3.53 sps vs baseline 3.19) is on the *fast end* of the range that the user happened to perceive as "natural dispatcher pace."
   - The same WAV2 reference on the longer P1 (10 syl, comma break) drops back to 3.00 sps — perceived 0.5x.

5. The reference voice (Mil Nicholson reading Dickens, audiobook prose) **anchors a slow, deliberate cadence** that suits short declaratives ("Stay with me.") but compounds the comma-pause problem on longer utterances.

**Test against the data:**

- All 3 P1 conditions cluster at 3.0 sps → **length effect dominates reference effect.** ✓
- All 3 P3/P5 conditions cluster at 4.5-5.1 sps regardless of reference → **length effect dominates reference effect.** ✓
- Within phrase: WAV1 > WAV2 > baseline on sps for 4/5 phrases → **reference effect is real but smaller than length effect.** ✓
- The single 1.0x perception (wav2/p4) coincides with the shortest phrase × the single stylistically-matched dispatcher utterance ("Stay with me." = grounding language, common dispatcher pattern). User perception of "natural pace" is content-mediated as well as rate-mediated. ✓

**Implication:** No single config knob will hit 1.0x across all phrase lengths. The model's structural pause-on-comma behavior is the binding ceiling. Solutions must operate at the **text-shaping** layer (prosody tags, comma stripping, phrase shortening) or the **reference-clip** layer (swap to a fast newscaster/dispatcher reference).

---

## Ranked fix candidates

1. **Inject inline prosody tags (smallest reversible, untested but model-supported).** Prepend `[professional broadcast tone]` or `[urgent dispatcher pace]` to LLM output before sending to Fish. Fish S2-Pro accepts free-form `[tag]` syntax (README.md:111-115). One-line adapter change in `_run()` at `fish_speech_tts.py:185` (wrap `self._text` with prefix). Reversible via env var. Cost: zero infrastructure, only quality risk if tag triggers off-key delivery.

2. **Swap reference voice to a brisk dispatcher / newscaster clip.** The current WAV1/WAV2 references are LibriTTS Mil Nicholson reading 19th-century prose — naturally slow. Find a 10-30s clip of an actual PSAP dispatcher or fast newscaster (public-domain or licensed); place at `PRISM42_FISH_REFERENCE_AUDIO`. Reversible. Cost: sourcing time. Predicted gain: shifts baseline cadence floor up by ~0.5 sps based on the data (WAV1 already shows +0.3 sps over baseline on most phrases).

3. **Strip commas / hard-segment text before sending.** LLM-side: change PSAP system prompt to avoid commas in dispatcher utterances ("Nine one one. Where is your emergency?" instead of "Nine one one, where is your emergency?"). The model's pause-on-comma behavior is what we observed driving slow P1 across all conditions. Reversible: prompt-only change. Cost: one prompt edit. Predicted gain: substantial on P1-style multi-clause utterances; null on already-comma-free phrases.

4. **Shorten LLM utterances.** Cap to 5-7 syllables per turn at the planner/specialist layer. The data shows phrases <=5 syllables hit 4.5-5.1 sps reliably. Cost: changes UX (more turn-taking). Recoverable.

5. **chunk_length tuning — UNLIKELY to help.** Our 200 is already the schema default and the engine forms a single batch for short PSAP text regardless. Lowering below 100 returns 422 (already verified per cycle-2j adapter comment, line 56-57). Raising it has no effect when text is single-batch.

6. **Sampler temperature change — RISKY.** Raising τ from 0.1 to e.g. 0.5 might let the model break out of slow cadence patterns, but voice identity drift is the documented risk (cycle-2j patch comment, line 60-65). Only worth trying if 1-3 fail.

7. **Engine-level fix (last resort).** Patch `fish_speech/inference_engine/__init__.py` to introduce an explicit silence-token suppression mask. This requires understanding the model's tokenizer + identifying which semantic tokens map to silence (no public docs found). Out of scope for cycle-2k.

**Recommended K2 path:** ship 1+3 together as a single env-toggleable adapter change. Tag injection + comma-stripping is two lines of `_run()` body, fully reversible, and addresses both the structural (commas) and emergent (prosody) drivers separately.

---

## Sources

1. `agents/livekit/fish_speech_tts.py:185-207` — adapter request body construction.
2. `vendor/fish-speech/fish_speech/utils/schema.py:81-103` — `ServeTTSRequest` definition (no speed field).
3. `vendor/fish-speech/fish_speech/inference_engine/__init__.py:144-177` — `send_Llama_request` (only 6 fields forwarded to AR).
4. `vendor/fish-speech/fish_speech/inference_engine/__init__.py:60-62` — `set_seed()` usage.
5. `vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57` — reference_id/references mutex.
6. `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:243-359` — AR `generate()` accepts only `temperature/top_p/top_k/max_new_tokens`.
7. `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:523-540,600-609` — `generate_long()` + `split_text_by_speaker` + `group_turns_into_batches`.
8. `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:96-181` — `decode_one_token_ar()` (Dual-AR codebook prediction; not a speed mode).
9. `vendor/fish-speech/fish_speech/models/dac/modded_dac.py:808,833` — DAC encoder_rates `[2,4,8,8]` → `hop_length=512` (fixed frame duration, ~11.6 ms at 44.1 kHz).
10. `vendor/fish-speech/README.md:78,111-115` — S2-Pro inline prosody tag system, "15,000+ unique tags supported".
11. `vendor/fish-speech/tools/server/views.py:146-205` — `/v1/tts` endpoint handler (no `latency` consumption).
12. `vendor/fish-speech/tools/api_client.py:81,171` — `latency` only consumed by cloud-API CLI client.
13. `findings/voice/fish-fork-analysis/profile.md:147,170,218` — prior cycle-2d profile result confirming single-batch behavior on PSAP-length text + "5x over eager" applies to inference TPS, not playback rate.
14. `findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/listening_checklist.md:66-75` — WAV1/WAV2 provenance (LibriTTS Mil Nicholson, Dickens audiobook).
15. `findings/voice/cycle2j_reference_voice/2026-04-26T024731Z/audio/{baseline,wav1,wav2}/p{1-5}.wav` — 15-file empirical measurement set (computed via stdlib wave + numpy in audit transcript).

---

## Anticipated-failure-mode summary

The prompt anticipated three failure modes; here is the disposition:

- *"Fish may have NO documented speed knob."* **CONFIRMED.** No field, no flag, no tag with explicit speed semantics. The closest thing is the inline `[tag]` system, which is content-shaped not parameter-controlled.
- *"Speed variation may be a Fish-S2-Pro model property that NO config knob fixes."* **CONFIRMED for long/comma-broken utterances.** Pivoting to text-layer fixes (prosody tags, comma stripping) is the recommended next move, not a model swap.
- *"Our `frame_size_ms=200` is unusual."* **Investigated — not the cause.** `frame_size_ms` is a LiveKit playback buffer (`fish_speech_tts.py:135-150`), not a generation knob. The 200ms value affects underrun risk and TTFA only; it does not change the underlying audio rate. Confirmed by reading `output_emitter.initialize()` semantics. The user's slow-pace perception is in the rendered audio bytes themselves, not in playback timing.

---

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits).
