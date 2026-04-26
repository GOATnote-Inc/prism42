# Team J-T — Reference WAV transcripts

**Mission:** Provide exact spoken-text transcripts for the two LibriTTS reference WAVs so Team J-I can pass them to Fish S2-Pro as paired audio+transcript references (mitigates J0 risk R4: silent transcript/audio drift).

**Mode:** Read-only (WAV + transcript files untouched). No copy to pod or repo — that is J-I's job.

**Audit window:** 2026-04-26T021256Z (UTC).

**Source provenance:** LibriTTS-R speaker `2026` (LibriVox reader Mil Nicholson reading Charles Dickens, *The Old Curiosity Shop*, chapter 22756 = Dickens Ch. 20). Confirmed against Project Gutenberg / online-literature.com canonical text — see Sources §.

---

## File 1: 2026_22756_000001_000000.wav (13.530 s)

**Transcript (verbatim, original — RECOMMENDED FOR FISH):**

```
Day after day as he bent his steps homeward, returning from some new effort to procure employment, Kit raised his eyes to the window of the little room he had so much commended to the child, and hoped to see some indication of her presence.
```

**Transcript (normalized variant — for reference only):**

```
Day after day as he bent his steps homeward, returning from some new effort to procure employment, Kit raised his eyes to the window of the little room he had so much commended to the child, and hoped to see some indication of her presence.
```

(File 1: original.txt and normalized.txt are byte-identical — 240 bytes each, no normalization needed; 19th-century prose contained no expandable abbreviations or numerics in this segment.)

**Source:** `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000000.original.txt` (Mar 17 2023 mtime, 240 bytes). Cross-verified against Dickens *Old Curiosity Shop* Ch. 20 canonical text (see Sources §1, §3).

**Cross-check:**
- Audio metadata: 16-bit PCM mono 24 kHz, 324,720 frames → 13.530 s (matches stated 13.53 s exactly).
- WPM: 45 words / 13.530 s = 199.6 wpm. Within plausible 19th-century English narration range (~150-220 wpm for an articulate reader; LibriVox volunteer Mil Nicholson is on the brisker side).
- Played via `afplay`: NOT aurally verified — agent has no audio perception; durations + canonical-text match are the strongest evidence available.
- Tag/artifact scan: no `<unk>`, `[MUSIC]`, `[NOISE]`, `[INAUDIBLE]`, or bracket-tags. Plain English with standard punctuation.
- Match to canonical Dickens: PASS. Phrase "Day after day as he bent his steps homeward" is the verified opening of a paragraph in Ch. 20 (Sources §1, §3).

**Status: USABLE for Fish reference-audio pairing.**

---

## File 2: 2026_22756_000001_000001.wav (14.550 s)

**Transcript (verbatim, original — RECOMMENDED FOR FISH):**

```
His own earnest wish, coupled with the assurance he had received from Quilp, filled him with the belief that she would yet arrive to claim the humble shelter he had offered, and from the death of each day's hope another hope sprung up to live to-morrow.
```

**Transcript (normalized variant — DO NOT USE for Fish):**

```
His own earnest wish, coupled with the assurance he had received from Quilp, filled him with the belief that she would yet arrive to claim the humble shelter he had offered, and from the death of each day's hope another hope sprung up to live to morrow.
```

**Key drift:** original `to-morrow` (hyphenated, archaic Dickensian) vs normalized `to morrow` (space). The audio (a human narrator) will pronounce a single word "tomorrow" — both forms are imperfect, but `to-morrow` matches the canonical 1841 Dickens print text and is the standard LibriTTS "original" label that Fish-style models are trained on. The space-separated `to morrow` would tokenize as TWO words, breaking phoneme-alignment cues for the speaker conditioner.

**Source:** `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000001.original.txt` (Mar 17 2023 mtime, 253 bytes). Cross-verified against Dickens *Old Curiosity Shop* Ch. 20 (Sources §2, §3).

**Cross-check:**
- Audio metadata: 16-bit PCM mono 24 kHz, 349,200 frames → 14.550 s (matches stated 14.55 s exactly).
- WPM: 46 words / 14.550 s = 189.7 wpm. Within plausible English narration range. Slightly slower than File 1, consistent with a longer, more contemplative final clause.
- Played via `afplay`: NOT aurally verified — agent has no audio perception; durations + canonical-text match are the strongest evidence available.
- Tag/artifact scan: no `<unk>`, `[MUSIC]`, `[NOISE]`, `[INAUDIBLE]`, or bracket-tags. Plain English with standard 19th-century punctuation; archaism `to-morrow` preserved.
- Match to canonical Dickens: PASS. Sentence "His own earnest wish, coupled with the assurance he had received from Quilp..." with terminal `to-morrow` is verified verbatim in Ch. 20 (Sources §2, §3). The two utterances 000000 and 000001 are consecutive sentences in the same Dickens paragraph — this is consistent with LibriTTS segmentation.

**Status: USABLE for Fish reference-audio pairing — use original.txt, NOT normalized.txt.**

---

## Recommendation for Fish reference-audio use

**Both files are usable as paired references.** Submit:

| Pair | Audio file | Transcript file (use this one) |
|------|-----------|-------------------------------|
| ref_1 | `2026_22756_000001_000000.wav` | `2026_22756_000001_000000.original.txt` content (verbatim above) |
| ref_2 | `2026_22756_000001_000001.wav` | `2026_22756_000001_000001.original.txt` content (verbatim above) |

**Critical guidance for J-I:**

1. **Use `.original.txt` content, NOT `.normalized.txt`.** For File 2 specifically, `.normalized.txt` mangles `to-morrow` into `to morrow` (two tokens), which is a documented mismatch with the spoken audio. For File 1 the two are byte-identical so no risk, but use `original` for consistency.

2. **Pass the transcript as plain UTF-8 string** — no leading/trailing whitespace, no LibriTTS line-number prefixes, no bracket tags. The text already contains no problematic characters; it is ASCII-clean except for standard apostrophes and hyphens.

3. **Trust the original Dickens punctuation** — em-dashes, hyphens (`to-morrow`), and the comma-heavy clause structure are CORRECT and match the speaker's actual prosody (Mil Nicholson is reading Dickens verbatim, not modernized). Fish S2-Pro's prosody encoder benefits from punctuation that mirrors the audio's pause/intonation pattern; do not strip or modernize.

4. **Aural verification gap:** This agent could not actually hear the WAVs (no audio perception). Recommendation J-I or a human integrator should do a 10-second listen of each WAV before locking the references — verify the spoken last word in File 2 is indeed "tomorrow" (single word) and not some other variant. The text/duration/canonical-source triangulation is strong but not a substitute for one human ear-check at integration time.

5. **Risk R4 (J0 audit) status:** MITIGATED for both pairs given canonical-source verification + duration alignment + clean text. Final residual risk is the aural-verification gap noted in §4 above.

---

## Sources

1. Project Gutenberg, *The Old Curiosity Shop* by Charles Dickens (eBook 700) — `https://www.gutenberg.org/files/700/700-h/700-h.htm`. Retrieved 2026-04-26. (Note: the version of this URL accessible at fetch time covered Chs. 1-6 only; Ch. 20 confirmation came via Source §3 below.)
2. Online-Literature mirror, *The Old Curiosity Shop* Ch. 20 — `https://www.online-literature.com/dickens/curiosity/20/`. Indirectly confirmed via WebSearch result snippets returning both target sentences with `to-morrow` hyphen intact. Retrieved 2026-04-26 (direct fetch returned 403; verbatim text confirmed via search-engine excerpt).
3. WebSearch verification queries 2026-04-26:
   - `"Day after day as he bent his steps homeward" "Old Curiosity Shop" Dickens` → confirmed File 1 text in Ch. 20.
   - `"His own earnest wish, coupled with the assurance he had received from Quilp" "to-morrow"` → confirmed File 2 text including hyphenated `to-morrow` in Ch. 20.
4. LibriVox catalog — *The Old Curiosity Shop* read by Mil Nicholson — `https://librivox.org/the-old-curiosity-shop-by-charles-dickens/` and `https://archive.org/details/curiosity_shop_mn_librivox`. Retrieved 2026-04-26. Confirms LibriVox source recording of Mil Nicholson, consistent with LibriTTS speaker-2026 attribution from Team J1's earlier audit.
5. Local transcript files (read-only):
   - `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000000.original.txt`
   - `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000000.normalized.txt`
   - `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000001.original.txt`
   - `/Users/kiteboard/Downloads/libritts-english/2026/22756/2026_22756_000001_000001.normalized.txt`
6. Local WAV metadata (Python `wave` module, read-only):
   - `2026_22756_000001_000000.wav`: 324,720 frames @ 24 kHz, mono, 16-bit → 13.530 s
   - `2026_22756_000001_000001.wav`: 349,200 frames @ 24 kHz, mono, 16-bit → 14.550 s
7. Team J0 static audit (referenced for R4 framing): `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T014938Z/team_j0_static_audit.md`.

---

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits).
