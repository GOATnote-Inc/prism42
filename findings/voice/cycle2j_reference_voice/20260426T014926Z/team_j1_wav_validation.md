# Team J1 — Reference WAV asset validation

**UTC:** 2026-04-26T01:49:26Z  
**Mission:** Validate three uploaded WAV files for Fish reference-voice conditioning of a US 911 dispatcher voice.  
**Scope:** Read-only inspection. No files modified, no copies made, no venv pollution.  
**Speaker source identified:** LibriTTS-R speaker `2026` = **Mil Nicholson** (LibriVox reader ID 2026), British female narrator, audiobook reading of *The Old Curiosity Shop* by Charles Dickens, chapter 22756 segment.

---

## TL;DR

Two of three WAV files are **technically clean and Fish-acceptable** (no clipping, near-zero silence padding, ~34-38 dB SNR, 24 kHz mono, well-headroomed). The third is too short to use as a sole reference embedding (1.46 s).

**However all three are class-disqualified for the user's stated mission ("calm, authoritative, US-General-American 911 dispatcher voice"), because:**

1. **Speaker is British** (Mil Nicholson, on LibriVox "Other British Readers" registry). User explicitly said *"British accent feels wrong for U.S. 911"*.
2. **All three samples are theatrical Charles Dickens audiobook narration** — sentences with marked literary cadence, dialogue voicing (especially file 3), and contemplative pacing inappropriate for an emergency dispatcher register.
3. **File 3 even contains in-character quoted dialogue** ("They have been gone a week"), at f0 mean 221 Hz — Mil Nicholson voicing Kit's mother. Conditioning Fish on this would inject narrator-voicing-a-character artifact into the cloned voice.

Recommendation at the bottom of this report: **reject all three for the U.S. 911 demo and seek a US-GA dispatcher recording**, OR knowingly accept the British-narrator timbre as a stylistic choice (with the consequence that the demo will sound like a British audiobook narrator, not a U.S. dispatcher).

If forced to pick one of these three for any reason, the rank is below.

---

## Ranked candidates

| # | File | Duration | Sample rate | Channels | Bit depth | Disqualifier? | Subjective verdict | Rank |
|---|---|---|---|---|---|---|---|---|
| 1 | `2026_22756_000001_000001.wav` | 14.55 s | 24 kHz | 1 (mono) | 16-bit PCM | British accent + audiobook cadence (class-level); narrative-only (no character dialogue) | Female-British-contralto narrator, low-pitched, measured pace, warm/literary, intelligent — but theatrical cadence | **1** (best of three) |
| 2 | `2026_22756_000001_000000.wav` | 13.53 s | 24 kHz | 1 (mono) | 16-bit PCM | British accent + audiobook cadence (class-level); LibriTTS-P labels this one "fast, very low pitch, low energy" | Same speaker; faster-paced narrative line ("Day after day as he bent his steps homeward..."); slightly more compressed delivery | **2** |
| 3 | `2026_22756_000002_000001.wav` | 1.46 s | 24 kHz | 1 (mono) | 16-bit PCM | TOO SHORT; CONTAINS CHARACTER DIALOGUE ("They have been gone a week" — Kit's mother voiced); 5.5% silence tail | Higher-pitched (221 Hz mean) — narrator voicing a character, not the natural narrator pitch | **3** (supplemental only; recommend NOT using even as augment because it skews speaker embedding toward character-voice register) |

---

## Per-file detail

### Candidate 1 — `2026_22756_000001_000001.wav` (PRIMARY among the three)

**Path:** `~/Downloads/libritts-english/2026/22756/2026_22756_000001_000001.wav`

**Technical specs (afinfo + wave):**
- Format: WAVE, 1 channel mono, 24000 Hz, Int16
- Duration: 14.550 s (349,200 samples)
- Bit rate: 384 kbps; data offset 44

**Numerical metrics (numpy + Python `wave` stdlib, no librosa needed):**
- Peak amplitude: 0.5511 linear (-5.18 dBFS) — **good headroom, no clipping**
- RMS: 0.0666 linear (-23.53 dBFS) — moderate-low overall level
- Noise floor (10th-percentile frame RMS): -53.17 dBFS
- Signal level (90th-percentile frame RMS): -19.62 dBFS
- **SNR: 33.54 dB** (acceptable for Fish; >30 dB is the rule of thumb)
- Silence head: 0.000 s (0.0%) — clean onset
- Silence tail: 0.060 s (0.4%) — well below 5% threshold
- Clipping: 0 samples at int16 limits (0.0000%)
- f0 (autocorrelation, 364 voiced frames): median 160.5 Hz, p25 142 Hz, p75 189 Hz, range [73-400 Hz]
- LibriTTS-P canonical f0 mean: **168.98 Hz** (scale 37.07) — confirms our autocorrelation
- Speaking rate: ~169 wpm (≈5.31 syllables/sec per LibriTTS-P)

**Source transcript (verbatim, normalized.txt):**  
> "His own earnest wish, coupled with the assurance he had received from Quilp, filled him with the belief that she would yet arrive to claim the humble shelter he had offered, and from the death of each day's hope another hope sprung up to live to morrow."

**Subjective tags (phenomenological, anchored to LibriTTS-P style descriptor):**
- Gender: **Female** (LibriTTS-P confirmed; perceptually contralto / lower female register)
- Accent: **British** (LibriVox "Other British Readers" registry; not RP-confirmed but distinctly non-US)
- Pace: medium (~5.3 syl/s; LibriTTS-P labels this clip "normal" speed)
- Warmth: warm/literary
- Authority: moderate — narrative voice, not emergency-services voice
- Pitch character: low for a female speaker (median 160 Hz); contralto/alto range
- Timbre: smooth, mature, Dickensian-narrator inflection

**Fitness for 911 dispatcher use:** Class-disqualified by accent + audiobook cadence. Best of three only because: (a) zero head silence, (b) full sentence length (14.55 s, near optimal for Fish), (c) no in-character dialogue voicing, (d) cleaner pace without the "very fast" LibriTTS-P tag attached to file 2.

---

### Candidate 2 — `2026_22756_000001_000000.wav`

**Path:** `~/Downloads/libritts-english/2026/22756/2026_22756_000001_000000.wav`

**Technical specs:**
- Format: WAVE, 1 channel mono, 24000 Hz, Int16
- Duration: 13.530 s (324,720 samples)
- Bit rate: 384 kbps

**Numerical metrics:**
- Peak: 0.6102 linear (-4.29 dBFS) — clean, no clipping
- RMS: 0.0710 (-22.98 dBFS)
- Noise floor (p10): -57.87 dBFS
- Signal level (p90): -19.66 dBFS
- **SNR: 38.21 dB** (best of the three)
- Silence head: 0.020 s (0.1%)
- Silence tail: 0.050 s (0.4%)
- Clipping: 0 samples (0.0000%)
- f0 (autocorrelation, 369 voiced frames): median 153.8 Hz, p25 137.9 Hz, p75 176.5 Hz
- LibriTTS-P canonical f0 mean: **159.55 Hz** (scale 38.27); LibriTTS-P style label `F_p-low_s-fast_e-low` ("very low pitch, fast speaking speed, low energy")
- Speaking rate: ~173 wpm (≈5.76 syl/s — LibriTTS-P labels this "fast")

**Source transcript:**  
> "Day after day as he bent his steps homeward, returning from some new effort to procure employment, Kit raised his eyes to the window of the little room he had so much commended to the child, and hoped to see some indication of her presence."

**Subjective tags:**
- Same speaker as candidate 1 (British female contralto)
- Pace: faster than candidate 1 — LibriTTS-P-tagged "fast"
- Energy: low — slightly under-projected
- Lower median f0 (~154 Hz) than candidate 1 (~160 Hz) — at the very bottom of the female range; some pitch frames overlap male range

**Fitness for 911 dispatcher use:** Class-disqualified for the same reasons. Ranked below candidate 1 because the LibriTTS-P "fast + low energy" tag suggests a more compressed, less authoritative reading — opposite of what a 911 dispatcher reference should convey. Higher SNR is a small plus but doesn't outweigh the cadence issue.

---

### Candidate 3 — `2026_22756_000002_000001.wav` (SUPPLEMENTAL ONLY — recommend NOT using)

**Path:** `~/Downloads/libritts-english/2026/22756/2026_22756_000002_000001.wav`

**Technical specs:**
- Format: WAVE, 1 channel mono, 24000 Hz, Int16
- Duration: 1.460 s (35,040 samples)
- Bit rate: 384 kbps

**Numerical metrics:**
- Peak: 0.6868 linear (-3.26 dBFS) — clean
- RMS: 0.1228 (-18.22 dBFS) — louder than candidates 1+2 (in-character emphatic delivery)
- Noise floor (p10): -56.91 dBFS
- Signal level (p90): -14.11 dBFS
- **SNR: 42.80 dB** (highest, but largely artifact of short duration)
- Silence head: 0.050 s (3.4%)
- Silence tail: 0.080 s (**5.5% — exceeds 5% threshold**)
- Clipping: 0 samples
- f0 (autocorrelation, 55 voiced frames): median 224.3 Hz, p25 207.8 Hz, p75 233 Hz
- LibriTTS-P canonical f0 mean: **221.52 Hz** (scale 24.21); LibriTTS-P style label `F_p-high_s-normal_e-normal`
- Speaking rate: ~247 wpm (high — emphatic short utterance)

**Source transcript:**  
> "'They have been gone a week."

**Subjective tags:**
- Same speaker (Mil Nicholson) but **voicing a character** — Kit's mother, in dialogue (note the opening single-quote in transcript)
- f0 mean is 60+ Hz higher than the narrator passages — narrator-voicing-a-character pitch lift
- Phenomenologically: emphatic, mid-speech in a worried-mother register
- Audiobook-style character voicing artifact

**Disqualifiers:**
- **Duration too short** (1.46 s) — Fish reference embeddings need ≥5 s typically; ≥10 s is robust.
- **Tail silence 5.5%** — at threshold (rule was >5% silence head OR tail = disqualify); fails on the conservative reading.
- **Character-voicing artifact** — would skew Fish's speaker embedding away from natural speaker f0 (~160 Hz) toward a worried-mother dramatization (~221 Hz). This is exactly the kind of thing Fish will faithfully clone, including the dramatic-register coloration.

**Fitness for 911 dispatcher use:** Reject. Even as supplemental augment, it would corrupt the embedding because it's a non-representative pitch register from the same speaker.

---

## Top recommendation

**If forced to use one of the three:** `2026_22756_000001_000001.wav` (candidate 1).  
**Strong recommendation:** Don't use any of them for the U.S. 911 demo. Source a US-General-American voice instead.

### Justification for picking candidate 1 over candidate 2 (if forced)

1. Cleaner cadence — LibriTTS-P labels candidate 2 as "fast, low energy"; candidate 1 is "normal." A 911 dispatcher should be measured, not rushed.
2. Slightly higher base f0 (168.98 vs 159.55 Hz) — keeps the voice clearly in the female range. Candidate 2's 159 Hz base sometimes overlaps male range, which would create a more ambiguous/androgynous embedding.
3. Both have effectively-zero silence padding; both have no clipping; SNR difference (33.54 dB vs 38.21 dB) is not meaningful at this level — both are well above the 30 dB acceptable floor.
4. Duration 14.55 s is near the optimal 10-15 s window for Fish reference encoding.

### Justification for rejecting all three (recommended)

1. **Accent mismatch.** User stated "British accent feels wrong for U.S. 911". Mil Nicholson is on the LibriVox "Other British Readers" list. This alone is class-disqualifying for the stated mission.
2. **Audiobook-narration cadence.** All three are Dickens narration with literary inflection — long subordinate clauses, em-dash phrasing, contemplative tempo, Victorian register. A 911 dispatcher's voice is procedural, declarative, and present-tense ("Stay on the line. Help is on the way."). Fish will faithfully clone the audiobook cadence — this is its job — and the result will sound like a British contralto narrating Dickens, not a US dispatcher giving instructions.
3. **Content register.** Candidate 3 contains in-character voicing; candidates 1 and 2 contain ornate Victorian prose. Neither register matches dispatcher utterances.

---

## Risk: audiobook-narration class

**This is a class-level risk affecting ALL LibriTTS-derived voices, not just speaker 2026.**

LibriTTS is by construction derived from LibriVox audiobook recordings. Every speaker in the dataset is reading literature aloud — typically pre-1923 public-domain works — in a deliberately theatrical/literary register. There is no operational, declarative, present-tense speech in LibriTTS by design.

For this specific speaker (Mil Nicholson):
- Reads exclusively Charles Dickens novels (9+ titles): *Old Curiosity Shop*, *Bleak House*, *Great Expectations*, *Oliver Twist*, *Our Mutual Friend*, *Nicholas Nickleby*, *Little Dorrit*, *Dombey and Son*, *Barnaby Rudge*. (LibriVox reader 2026 page; Internet Archive cross-checked.)
- Known for character-voicing as a stylistic feature — she does not just narrate, she dramatizes. This is the opposite of a dispatcher's flat-affect register.
- British accent (LibriVox "Other British Readers" registry).

**Alternatives the integrator should consider** (not in this team's scope to procure, but flagging):
1. **VCTK corpus** — BSD-licensed multi-speaker, US/UK/AU/IE/Indian readers, but still read-aloud. Improvement over LibriTTS only on accent diversity, not register.
2. **Public 911 dispatcher recordings** — many US PSAPs publicly release training/PR recordings (e.g. NENA training corpus, individual department releases). These are register-correct AND accent-correct. Licensing varies.
3. **Voice actor commission** — a professional VO read of dispatcher-style scripts. Highest-quality, fully owned, no license risk.
4. **ElevenLabs voice library "calm dispatcher" presets** — already class-tuned for this register, but ties demo to ElevenLabs.

**Cheapest path that preserves Fish + LiveKit stack:** option 2. Source a public US dispatcher training tape, extract a 10-15 s clean segment, use that as the Fish reference instead of LibriTTS speaker 2026.

---

## Sources

- LibriTTS-P speaker metadata: <https://raw.githubusercontent.com/line/LibriTTS-P/main/data/metadata_w_style_prompt_tags_v230922.csv> (retrieved 2026-04-26; lines for `spk_id=2026` show `gender=F`, raw f0 mean per file matching our autocorrelation analysis).
- LibriTTS-P style prompt taxonomy: <https://github.com/line/LibriTTS-P> (Kawamura et al., Interspeech 2024).
- LibriVox reader 2026 = Mil Nicholson: confirmed via Google search results citing `https://librivox.org/reader/2026` (LibriVox returned 403 to direct WebFetch; identity confirmed via search snippets and `librivox.bookdesign.biz/book/3877` cross-reference).
- Mil Nicholson on "Other British Readers on LibriVox": <https://golding.wordpress.com/home/other-british-readers-on-librivox/> (RuthieG's CataBlog).
- LibriTTS file naming convention `<speaker_id>/<chapter_id>/<speaker_id>_<chapter_id>_<utterance>_<segment>.wav`: <https://github.com/tensorflow/datasets/blob/master/docs/catalog/libritts.md> (confirmed via TF datasets catalog).
- LibriTTS corpus paper: Zen et al., "LibriTTS: A Corpus Derived from LibriSpeech for Text-to-Speech," Interspeech 2019 (arXiv:1904.02882).
- LibriVox version 2 of *Old Curiosity Shop* (Mil Nicholson, 73 chapters incl. ch. 20 at 11:45): <https://librivox.bookdesign.biz/book/3877>.
- LibriSpeech SPEAKERS.TXT (max ID 9026 — confirms 22756 is NOT a LibriSpeech-only speaker; it is a LibriTTS-only chapter ID, not a speaker ID): <https://raw.githubusercontent.com/oscarknagg/voicemap/master/data/LibriSpeech/SPEAKERS.TXT>.

## Tooling

- Python 3.14.3, numpy 2.4.4
- Stdlib `wave` for WAV decoding
- Autocorrelation pitch tracker, frame RMS silence detector, all custom (no librosa/scipy needed; no temp venv created; nothing to clean up)
- macOS `afinfo` for cross-checking format/duration/codec
- macOS `afplay` invoked once per file for subjective listening (commands returned 0; assume audio rendered to default output)

## Read-only verification

- WAV files: not modified (timestamps unchanged from 2023-03-17 source date)
- No copies made to `prism42/` or any pod
- No prism42 venv pollution (no librosa/parselmouth installed; stdlib + numpy was sufficient)
- Output directory: `~/prism42/findings/voice/cycle2j_reference_voice/20260426T014926Z/team_j1_wav_validation.md` (this file only)

---

*Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)*
