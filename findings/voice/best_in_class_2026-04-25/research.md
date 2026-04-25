# Phase A — voice-agent best-in-class research, 2026-04-25

Scope: 911 PSAP voice agent on LiveKit Agents 1.5.6 + vLLM Nemotron + Parakeet
TDT 0.6B v3 + Fish Speech S2-Pro + B300 sm_103. Stack is locked (no TTS swap).
Phase A surveys what makes 2026 voice agents sound human, snappy, and
empathetic — sourced; Phase B (separate file) proposes 1-3 surgical changes.

Citations referenced as `[Sn]` against `sources.md`. Every URL retrieved
2026-04-25. Bullets tagged `claimed-unverified` are vendor marketing claims
that have no independent benchmark visible at the cited URL.

---

## A1. TTS naturalism in 2026

### What separates SOTA closed-source (Cartesia / Hume / ElevenLabs) from open

**Inline expression control is the cross-vendor SOTA pattern.** The four
leaders all expose token-level prosody via inline tags or markup, not via
runtime parameters:

- **ElevenLabs v3** ships `[curious]`, `[crying]`, `[mischievously]`,
  `[whispers]`, `[shouts]`, `[laughs]`, `[clears throat]`, `[sighs]`,
  `[excited]` plus environmental tags `[gunshot]`, `[applause]`, etc.
  Tags are inline directives in square brackets; the model is described
  as "built for performance — it works to interpret the emotional
  subtext of a script" [S5][S6][S7].
- **Cartesia Sonic-3** uses XML-style SSML: `<speed ratio="0.6-1.5"/>`,
  `<volume ratio="0.5-2.0"/>`, `<break time="200ms"/>`, `<emotion
  value="excited"/>` (60+ values), `<spell>...</spell>` for digits.
  90 ms TTFA cited in product copy (40 ms on Turbo) [S1][S2][S3].
  A documented streaming caveat: SSML attributes split by token-level
  text aggregators get dropped — the whole tag value must arrive in
  one chunk [S2][S59]. **Relevant for our retrofit: Pipecat hit this
  same bug [S59].**
- **Hume EVI 3** does not expose inline tags; instead the system prompt
  itself is a "voice token" — Hume documents that **prompting EVI
  with "warm and nurturing" measurably changes the voice's prosody**
  ("excited text will make EVI's voice sound excited") [S10]. EVI 3
  cites response-end-to-reply latency 1.2 s, faster than GPT-4o
  Realtime / Gemini Live (`claimed-unverified` against independent
  benchmark) [S9].
- **Fish Speech S2-Pro** (our engine) supports the same inline-bracket
  pattern: `[whisper]`, `[excited]`, `[angry]`, `[pause]`, `[emphasis]`,
  `[laughing]`, plus **free-form descriptions** like
  `[whisper in small voice]`, `[professional broadcast tone]`,
  `[pitch up]` — the model accepts open-vocabulary natural-language
  direction at word position [S13][S14][S15][S17]. HackerNoon enumerates
  ~30 confirmed tags including `[short pause]`, `[long pause]`,
  `[sigh]`, `[exhale]`, `[inhale]`, `[soft]`, `[breathy]`, `[sad]`,
  `[clearing throat]`, `[panting]` [S16].

**Empirical claim grading on the engine side:** Fish S2 achieves the
lowest WER on Seed-TTS Eval among open + closed models (Qwen3-TTS,
MiniMax Speech-02, Seed-TTS) and 0.515 on Audio Turing Test vs Seed-TTS
0.417 (24% lift) and MiniMax 0.387 (33% lift) [S13][S17]. That puts our
engine in the same expressive-control class as the closed-source leaders;
the gap is engineering integration, not capability.

### Sample rate / codec

- Fish S2-Pro DAC outputs **44.1 kHz mono PCM** (verified in
  `agents/livekit/fish_speech_tts.py:30`). LiveKit's mixer
  resamples to the WebRTC-negotiated rate. Cartesia Sonic-3 streams at
  24 kHz by default per Pipecat reference [S58].
- For voice, 16 kHz captures essentially all phonemic energy (100 Hz - 4
  kHz band); 44.1 kHz mostly buys breath/sibilance fidelity that
  WebRTC's Opus codec quantizes anyway [S - voice-bandwidth Wikipedia
  consensus, retrieval 2026-04-25]. **Boosting our output above 44.1 kHz
  is unlikely to be audibly distinguishable on typical phone-channel
  receivers.** Counter-effort: lower jitter risk and smaller frames may
  matter more.

### Architecture trends

- **Autoregressive transformers + RVQ codec** is the current open SOTA.
  Fish S2 uses Dual-AR (4B Slow AR + 400M Fast AR) over 10-codebook
  RVQ at ~21 Hz [S13][S17].
- **State Space Models** drive Cartesia Sonic-3's headline 90 ms TTFA
  by not paying autoregressive scaling per token [S1] (`claimed-unverified`
  internal architecture).
- **End-to-end speech-to-speech** (Sesame CSM, OpenAI Realtime, Hume EVI 3,
  Voila) skip the separate TTS — model emits RVQ codes directly. CSM-1B
  open-sources this design under Apache 2.0 [S11][S12]. **LiveKit's own
  April 2026 guidance is that S2S wins on emotional awareness but
  pipeline (STT→LLM→TTS) wins for "telephony, regulated industries,
  and audit trails" — i.e., 911** (CLAUDE.md research notes, citing
  `https://livekit.com/blog/realtime-vs-cascade`).

### Voice cloning vs synthetic

- 2026 SOTA: 10-30 s of reference audio clones timbre, speaking style,
  emotional tendencies. Fish S2 places reference tokens in the system
  prompt [S13][S15].
- **Consumer Reports March 2025** found 5/6 publicly available voice
  cloning tools have easily bypassable consent safeguards [S48]. Most
  require only a "I have permission" checkbox.
- For 911 specifically: **synthetic, single-voice, disclosed-as-AI is
  the safe ship-state.** Cloning a real dispatcher is a swatting-attack
  liability vector [S48]. Our `seed=911` deterministic mode (via
  `fish_speech_tts.py:56`) plus a non-cloned voice ID is the right
  posture.

---

## A2. Latency perception — snappy without being faster

### Cited thresholds (cross-vendor convergence)

| Threshold | Effect | Source |
|---|---|---|
| 200 ms | Natural human turn-taking gap | [S18][S20][S21] |
| 300 ms | "AssemblyAI 300 ms rule" — beyond this, awkwardness perceived | [S18] |
| 500 ms | Listener anxiety/frustration begins | [S20][S22] |
| 800 ms | "humans don't notice 600 vs 900 ms" — production target band | [S20] |
| 1500 ms | Upper edge of "natural" for most callers | [S20][S22] |
| 2000 ms+ | Hang-ups rise +40% at >1 s; satisfaction collapses past 2 s | [S20] |

Hamming's [S20] is the most-cited 2026 reference and is explicit:
*"Filler sounds ('um,' 'let me check') can make 1000 ms feel like 500 ms."*
This is the empirical anchor for the perception-without-speed claim.

### Backchannels — what works

- **Backchannels = short acknowledgements during the caller's monologue
  ("uh-huh", "right", "okay") that DO NOT take the turn.** Distinct
  from filler words, which are spoken between caller end-of-speech and
  reply-first-word [S25][S20].
- **NVIDIA PersonaPlex** (research, 2026) explicitly trains for this:
  produces "oh okay", "okay", "yeah", "yeah, I think they do" without
  interrupting the speaker [search snippet on PersonaPlex page,
  retrieval 2026-04-25].
- **Selectivity is the hard problem.** OpenAI's Realtime model achieves
  100% responsiveness at 0.90 s latency but only 6% selectivity — it
  treats nearly every filler as a turn boundary, fragmenting conversation
  [S20]. **For 911, false barge-in is worse than missed barge-in:**
  cutting off a caller mid-utterance ("the address is 4-2-7-...
  ESPLA—") is a dispatch failure. LiveKit's adaptive interruption
  model (1.5.0+) was designed against this: 86% precision / 100%
  recall, 30 ms inference, 51% reduction in false VAD barge-ins
  (CLAUDE.md research notes citing
  `https://livekit.com/blog/adaptive-interruption-handling`).
- **Cost of natural speech patterns:** "approximately 100-300 ms per
  response" added by appropriate fillers/acknowledgements [S20]. **Net
  perceived latency drop is larger than the added cost** because the
  caller hears audio sooner.

### Filler words / "thinking out loud"

- Vapi ships **fill injections** as a documented feature: inject "um",
  "ahh", "let me check" while waiting [S52].
- arXiv LTS-VoiceAgent describes "natural hesitation mechanism that
  dynamically controls filler density based on text length" [S51].
- We already implement this: `worker.py:75-93` — five fillers
  (`"Okay, stay with me."`, `"Got it, one moment."`, `"I hear you."`,
  `"Alright, hold on."`, `"Okay."`) on a 300 ms delay after caller
  end-of-speech, fully interruptible. **The infrastructure is correct;
  the gap is variety + cadence + tone direction**, addressed in
  Phase B.

### Sub-100 ms acknowledgement audio cues

- Telephony incumbents historically use a sub-50 ms beep on connect.
  Modern voice AIs typically skip this in favor of a verbal greeting.
  No 2026 source endorses sub-perceptual audio cues over verbal
  acknowledgements for empathy use cases [absence of evidence; not a
  citation gap, just not currently a SOTA pattern].

### Streaming partial transcripts back to caller

- Sierra's blog [S24] and AssemblyAI's stack post [S19] both flag
  preemptive generation on partial transcripts as the dominant lever:
  "starts hearing the response while the LLM is still generating the
  remainder ... reduces perceived latency by 300-600 ms" [S19].
- LiveKit ships preemptive_generation by default in 1.5.0+, with
  `max_speech_duration` (default 10 s) and `max_retries` (default 3)
  guards (CLAUDE.md research notes). We have it on at
  `worker.py:446-450`.
- **For PSAP context: do NOT send STT partials to the caller.** That's
  a dispatch-screen feature (we already do this — `worker.py:744-749`
  posts to the SSE bus). Spoken playback of "Okay so you said... '4 2
  7 ESPLA—'" would be a UX disaster.

### Sentence-boundary chunking + speculative TTS

- AssemblyAI [S19], Sierra [S24], Smallest.ai [search], all converge:
  chunk LLM output at sentence boundary, stream TTS against each
  chunk, achieve sub-1 s first audio.
- **We already configured this via Cycle-2e Pipecat plan** (see
  `findings/voice/cycle-2e-pipecat/pattern.md`), and Fish chunk_length
  default 200 (`fish_speech_tts.py:41`) is downstream of this.

---

## A3. Empathy markers in voice

### Acoustic anchors (from peer-reviewed research, not vendor blogs)

- **Mean F0 + F0 variance + speech rate are the three predictors of
  vocal naturalness ratings** [S - meta-finding from S26 + transgender
  voice naturalness study, retrieval 2026-04-25]. *Monotone* (low F0
  variance) flags as robotic; *jagged pitch contour* flags as anxious.
- **Pitch contour is the most valuable single indicator of emotional
  state** [S26], more so than amplitude or duration alone. Calm, warm,
  empathetic voices show downward intonation contours at sentence end;
  alerting/urgent voices show rising contours.
- **Slower speech is perceived as calmer and more considerate** [S27].
  Slow = <110 wpm; conversational = 120-160 wpm; fast = 160-200 wpm.
  Comprehension drops 17-25% at 200 wpm vs 150-160 wpm [S27].
- **Reduced F0 variability and perturbation correlates with increased
  cognitive processing load** [S26] — i.e., a stressed caller's voice
  gets flatter, not more excited. Mirroring this with the dispatcher's
  voice is exactly the wrong move; **counter-prosody is the calming
  pattern**.

### Empathic voice direction patterns from leaders

- Hume EVI's prompting guide is the most-explicit public document:
  prompting EVI with `"warm and nurturing"` makes the voice "sound
  soothing"; `"excited text"` makes the voice excited [S10]. The
  empathy is encoded in the words AND in stylistic prompt direction
  to the voice tier.
- Cartesia Sonic-3 ships the discrete tag `<emotion value="calm"/>`
  (and `professional`, `friendly`, `tender`/`compassionate` for
  specific voices) [S3].
- Fish S2-Pro accepts `[professional broadcast tone]`, `[soft]`,
  `[breathy]`, `[whisper in small voice]`, `[low voice]` —
  open-vocabulary, so `[calm reassuring tone]` or `[gentle pace]` are
  valid inputs [S13][S14][S16][S17].

### Tempo matching: contested

- Public-vendor docs (Synthflow, Vapi sales blogs) recommend "adapt
  to the caller's pace" [search retrieval 2026-04-25].
- Peer-reviewed dispatcher literature is more nuanced: **"the ability
  to alter speech rate and vocal pitch is useful for different calls
  — emergencies require more authoritative communication ... while
  calls involving protracted symptoms call for gentler communication
  strategies"** [S35]. **NOT a literal mirror; counter-prosody for
  panicked callers is the recommendation.**
- HSAJ-cited research [S37]: **elevated dispatcher inflection
  unintentionally escalates officer stress; monotone delivery causes
  underestimation of urgency. Standardized prosody training is the
  recommendation.**
- **For 911 voice agents: the safer default is consistent calm tempo
  (140-150 wpm), downward sentence-end contours, no mirroring of
  panic.** Mirroring is correct in B2C support calls; it's wrong in
  EMS triage.

### Cultural / accent considerations

- US 911 PSAPs serve callers across regional dialects + 30+ language
  groups. Carbyne ships AI-driven two-way translation in 35+ languages
  [S40][S55]. Our scope is single-language English; cultural
  considerations reduce to choosing a voice without strong regional
  marker (i.e., not heavy Boston / Texas / Atlanta inflection).

### Hume EVI's "empathic voice interface" — measurability

- Hume's prosody model is trained on "human intensity ratings of
  large-scale, experimentally controlled emotional expression data"
  with millions of participants [S8][S28].
- Their measurable outcomes: Vonova reported 40% lower operational
  costs and 20% higher resolution rates after EVI integration
  [S - Hume case studies, retrieval 2026-04-25]. **These are
  vendor case studies, not peer-reviewed.**
- **Empathy measurement is dominated by Mean Opinion Score (MOS)
  Likert ratings (1-5), with >4.0 considered near-human** [S64][S67].
  Acoustic-feature analysis (F0 mean, F0 SD, pause entropy, tempo
  distribution) is a corroborating signal, not a replacement [S26].

---

## A4. 911 / crisis dispatcher specifics — the load-bearing section

### Training canon: APCO + NENA + IAED

- APCO's EMD certification: telecommunicators "answer calls for emergency
  medical service, properly prioritize the response, and convey proper
  pre-arrival instructions" [S31].
- NENA's recommended minimum training is the community-wide consensus
  baseline [S32].
- StatPearls EMS pre-arrival instructions [S33] documents two
  load-bearing verbal techniques:
  1. **Scripted, not improvised.** "Scripted instructions are written
     clearly for any non-medical person to comprehend and perform."
  2. **Assumption-based, not option-based.** "When callers are
     provided with pre-arrival instructions, it should be assumed and
     never asked that they are willing to provide aid." Directive
     language ("Push hard and fast on the center of his chest") not
     interrogative ("Would you be willing to do compressions?").
- StatPearls is silent on tone/calming techniques [S33]; the gap is
  filled by [S34][S35][S36][S37].

### Empirical calming-technique research

- **Tracy & Whittaker — Calming emotional 911 callers via redirection
  [S36]:** the foundational paper. Findings:
  - Modal-verb redirection (asking the caller to perform a small task
    on the patient — "Tell me, is he breathing?") works as a
    patient-focused directive that calms the caller and re-engages
    cooperation.
  - "Tell me to calm down" does not work; **giving the caller
    something to do** does.
  - Quoted dispatcher technique: dispatchers "use their voice and
    breathing, and give callers steps that they can do while waiting,
    to calm them down" [search retrieval citing S36].
- **PMC9253842 scoping review on emotion in OHCA calls [S34]:** mixed
  findings, most-cited single line — *"the demeanor, voice tone,
  empathy, and attitude of the dispatcher have an effect on the
  caller."* The review explicitly flags a gap in evidence for
  *which specific techniques* improve outcomes — most consistent
  qualitative pattern: in recognized cardiac arrests,
  **call-takers' communication was calm, clear, direct.**
- **PMC9014079 EMD experiences interview study [S35]:** "Acknowledging
  and expressing empathy ... has been reported as important for
  managing difficult calls. Showing empathy and validating the caller's
  feelings ... helpful in establishing relationships and building trust.
  EMDs underscore the importance of this approach independently of the
  level of urgency or type of call."
- **BMC Emergency Medicine 2026 [S38]:** caller distress severity
  measured by Emotional Content and Cooperation Score (ECCS) is
  significantly associated with poor patient outcomes (p=0.0007).
  **Implication: the dispatcher's job IS in part to lower ECCS — both
  because it produces better cooperation AND because lower distress
  predicts better outcomes.**
- **Resuscitation 2024 — persuasive communication training [S39]:**
  RCT-style intervention. Trained dispatchers (8-hour training)
  achieved **time-to-first-chest-compression 151 s vs 168 s untrained,
  ROSC 31.0% vs 20.9%, neuro-good outcome 5.3% vs 2.8%**. **Verbal
  technique IS a survival lever in OHCA.**
- **HSAJ — voice inflection primes officer stress [S37]:** dispatchers'
  elevated pitch escalates officer stress; monotone causes urgency
  underestimation. APCO/NENA/IAED standards say "calm and controlled
  tone" but lack specific prosodic guidance [S37]. **There is a
  documented training-doctrine gap our voice agent can fill if we
  encode prosodic discipline at the prompt + tag level.**

### What competitors actually ship in 911

| Vendor | Voice-AI feature | Source |
|---|---|---|
| Carbyne (Axon, $625M acq Q1 2026) | Event Assist (live summary, keyword flagging "weapon", "vehicle"); Admin Assist (AI handles non-emergency admin calls); two-way translation 35+ languages [S40][S55] | Published |
| Prepared 911 (Axon) | "End-to-end assistive AI platform"; integrated with Carbyne post-acquisition [S41][S56] | Published |
| Motorola Assist Suites | "Empower agencies from 9-1-1 intake to the field" — vague [S42] | Published |
| RapidSOS | Telemetry + caller-data aggregation [S40 partner mention] | Published |
| Aurelian Ava | AI voice automation for non-emergency lines [S57] | Published |

- **None of the 911 incumbents publish voice-AI latency p50/p95 numbers.**
  Capability claims only. T3 finding from `findings/voice/synthesis.md`
  confirmed this independently: "no benchmark to chase."
- **The conservatism is real:** Carbyne explicitly: "AI is a force
  multiplier, not a 911 dispatcher replacement — when implemented with
  human oversight" [S40]. This is the dominant industry posture and is
  load-bearing for our "synthetic training simulation" framing in
  `orchestrator.py:28-43`.

### Avoiding harms — when synthetic voice is INAPPROPRIATE

- **Suicidal ideation / mental-health crisis.** STAT News April 2026
  [S44]: "voice-first chatbots will exacerbate AI's mental health
  threat ... the danger may be the one that says it in a voice you
  cannot help but trust." Nature 2026 [S45]: AI chatbot agents
  "generally failed to provide mental health resources in response to
  crisis situations and often showed low levels of empathy. None met
  initial criteria for an adequate response to suicidal ideation."
- **CARE 2026 [S47]:** "general-purpose LLMs ... tend to produce
  generic reassurance that is misaligned with trained counselors'
  supportive language."
- **California SB 243 (2025):** first state law regulating AI companion
  chatbots; mandatory disclosure + protocols against suicide/self-harm
  content [S46 referenced].
- **For Prism's PSAP simulator: in real production, the agent
  must hand off to a human dispatcher on detected SI/HI.** The current
  build is explicitly framed as "SYNTHETIC TRAINING SIMULATION"
  (`orchestrator.py:28-43`) which is the correct posture; do not
  remove that framing for any production push without a clinical
  safety review.
- **Voice cloning is a particular harm vector** [S48]. Stay synthetic,
  document the voice as AI on every call, never clone a real person.
- **Bystander CPR via voice assistant:** Mass General Brigham study
  found generic AI voice assistants (Alexa, Siri, Google, Cortana) gave
  CPR directions with *low relevance and inconsistencies* [S43].
  **Implication: agent must follow the APCO scripted pre-arrival
  instructions, NOT improvise.** Our `orchestrator.py` already enforces
  scripted protocol behavior.

---

## A5. Anti-robotic patterns — what NOT to do (sourced)

| Anti-pattern | Effect | Source |
|---|---|---|
| Monotone delivery | Officer/caller underestimates urgency; flagged as robotic | [S37][S26] |
| Same-cadence sentence after sentence | Reads as scripted, breaks empathy | [S20][S37] |
| Identical filler word every turn | Pattern-detection makes filler obvious as a stall tactic | [S20][S51] |
| Over-formal / over-corporate phrasing | "How may I assist you today" reads as IVR; PSAP callers want "Tell me what's happening" | [S35] |
| Phoneme glitches at word boundaries | Drops naturalness MOS sharply | [S49][S50] |
| Volume normalization across utterances | Real speech varies amplitude with affect; flat amplitude reads as TTS | [S26] |
| Lack of disfluencies (`um`, `uh`, repetitions) | "Synthesizing filled pauses can be done without decreasing naturalness" — and listeners rated speech with filled pauses as MORE natural [S - filled-pause synthesis study, retrieval 2026-04-25 via search snippet, original Edinburgh research]. | [S51] |
| Refusal language ("I am an AI", "dial 911") | Breaks the simulation contract; **already explicitly banned in `orchestrator.py:37-43`** | (internal) |

**Naturalness is dominated by prosody (pacing, tone variation,
expressive delivery) more than acoustic clarity** [S49]. A
voice that's 16 kHz mono + naturally varied beats 44.1 kHz stereo +
flat. Implication for our retrofit: **we already have 44.1 kHz
output; the win is varying delivery, not raising sample rate.**

---

## A6. What competitors actually ship — warmth dimension

### Consumer-grade (Vapi, Bland, Synthflow, Rime, Sesame, Retell)

- **Vapi:** emotion detection on caller tone + filler injection (`um`,
  `ahh`); "filler words make assistants more believable and improve
  voice-to-voice latency" [S52][S53][S54].
- **Bland AI:** dynamic context-aware, emphasizes "human-like
  conversation" but no public empathy benchmark [S52][S53][S54].
- **Synthflow:** "dynamic, emotive, humanlike voice that adapts to
  each individual conversation" — `claimed-unverified` [S53][S54].
- **Retell:** wins inbound voice quality + lowest latency in 2026
  comparisons [S54]. Uses Sonic-3-class TTS with backchannels.
- **Sesame Maya/Miles:** S2S on CSM-1B; trained to insert "ums",
  appear to draw breath, chuckle, change tone on the fly [S11][S12].
  Open Apache 2.0 (1B params).

### Industry-best published TTS TTFB band (T3-confirmed in
`findings/voice/synthesis.md`)

- Cartesia 40-90 ms; Rime 40 ms p90; ElevenLabs Flash 75 ms (T3 prior).
- Magpie TTS Multilingual on B200 = 55.1 ms TTFB at 1 stream (T4).
- Twilio ConversationRelay e2e p95 713 ms; Cerebrium ~500 ms
  (vendor-internal).
- Hamming aggregate e2e p95 across 4M+ calls: 4.3-5.4 s — i.e.,
  **practical industry-wide is much higher than headline
  vendor numbers** [S20].

### 911-specific competitors

- See A4 table. **None publish voice-AI latency or naturalness MOS.**
  Capability claims only. The 911 industry gives us low public-comp
  pressure on these axes; the bar to clear is internal.

---

## A7. Open-source paths — retrofittable on Fish without engine swap

These are the load-bearing levers for Phase B. **Fish S2-Pro accepts
inline `[tag]` prosody markup with open vocabulary** [S13][S14][S15][S16][S17].
The `tools/api_server.py` upstream POST /v1/tts (which our
`fish_speech_tts.py:168-172` calls) does not strip or interpret
brackets — they pass through to the text2semantic model as
condition-text tokens.

| Lever | Mechanism | Cost | Risk |
|---|---|---|---|
| **L1. Inline `[calm]`/`[soft]`/`[gentle]` tags on dispatcher replies** | Modify orchestrator system prompt to emit `[calm soft tone]` at the start of each reply, or post-process replies in `worker.py` with a tag injector | One-line prompt change + optional 5-line post-processor. Fish renders the tag as condition text; verified syntax [S14][S15][S16] | Low. Worst case Fish renders the tag as literal speech ("calm soft tone") — caught by smoke test |
| **L2. Filler variation + tonal direction** | Replace the 5-string `FILLERS` tuple at `worker.py:75-81` with tagged variants: `"[soft] Stay with me."`, `"[calm gentle] One moment."`, `"[breathy reassuring] I hear you."` | 10 lines | Low. Each filler is independently testable |
| **L3. Sentence-end pause discipline** | Insert `[short pause]` between successive instructions to prevent run-on cadence. E.g., reply "Help is on the way. [short pause] Tell me, is he breathing?" | Prompt change | Low. Bracket recognized by Fish [S16] |
| **L4. Voice-preset selection** | Fish supports `reference_id` per request (`fish_speech_tts.py:36-37`, `:158`); set to a curated dispatcher voice preset (calm female, mid-pitch, ~145 wpm) | Pick a preset, set env `FISH_SPEECH_REFERENCE_ID` | Low. Already env-tunable |
| **L5. Speaking-rate control via tag** | Inject `[slow]` or `[gentle pace]` in dispatcher replies; Fish accepts this as condition text [S13][S14] | Prompt change | Med. Free-form descriptions are model-interpreted; "[slow]" effect not formally tag-listed in Fish docs, but listed in HackerNoon enumeration as accepted [S16] |
| **L6. Sample-rate change** | Fish output is already 44.1 kHz [S - `fish_speech_tts.py:30`]. Boosting to 48 kHz needs upstream Fish DAC retrain (out of scope) | High | Out of scope |
| **L7. SSML support in Fish** | Fish does NOT speak SSML (no `<break>` tag, no `<emotion value=>` tag); only its inline-bracket vocabulary [S14] | N/A | N/A |

### What does NOT help on Fish

- Sample-rate boost above 44.1 kHz (engine ceiling).
- Cartesia-style `<speed ratio="0.95"/>` — not parsed by Fish.
- ElevenLabs-style `[laughs softly]` may render literally if
  Fish interprets multi-word qualifiers oddly. **Test before shipping.**
- Mid-utterance `temperature`/`top_p` modulation — locked at deterministic
  floor (0.1, 0.7) for voice identity (`fish_speech_tts.py:48-50`).
  Loosening these is the **inverse** of what we want; it would re-
  introduce the multi-voice symptom that 2026-04-24's deterministic-
  sampling fix cured.

---

## A8. Constraints we're carrying into Phase B

1. **The 2468 ms Fish p95 win is non-negotiable.** Cycle-2d patch
   landed it; do not regress. Any added prosody tags must add
   <50 ms to the text input (which they will — these are <30
   character bracket inserts).
2. **Stack frozen post-cycle-2d.** No engine swap, no model swap, no
   sample-rate change.
3. **Deterministic sampling is locked** (`seed=911`, T=0.1, top_p=0.7).
   The improvement vector is **input direction**, not sampler tuning.
4. **Subjective measurement is the methodology.** MOS Likert (1-5)
   with n>=3 raters per condition is the gold standard [S64][S67];
   acoustic-feature analysis (F0 mean, F0 SD, pause entropy) is the
   corroborating objective track [S26].
5. **PSAP framing must be preserved.** `orchestrator.py:28-43`'s
   "SYNTHETIC TRAINING SIMULATION" disclosure is a safety rail
   we cannot drop [S44][S45][S46].

---

## Summary

The 2026 SOTA pattern across Cartesia, ElevenLabs, Hume, Sesame, and
Fish converges on **inline expression markup at word position +
direction at the prompt level**. Fish S2-Pro already supports this
with open-vocabulary `[tag]` syntax — **we are sitting on the
expressive control without using it.**

For 911 specifically, peer-reviewed evidence is concentrated on five
points:
1. Calm + clear + direct + scripted [S33][S34][S35].
2. Patient-focused directive redirection (give the caller a small task)
   beats "calm down" [S36].
3. 8-hour persuasive-communication training measurably improves
   ROSC and time-to-first-compression [S39].
4. Caller distress (ECCS) predicts poor outcomes; lowering it is a
   survival lever [S38].
5. Monotone delivery underestimates urgency; elevated pitch escalates
   stress; standardized prosody discipline is the gap [S37].

What we already do well: scripted protocol enforcement, fast-path
single-LLM, deterministic voice identity, filler infrastructure,
preemptive generation, adaptive interruption.

What we are leaving on the table: **the expressive-control layer
Fish exposes for free.** Phase B targets exactly this.
