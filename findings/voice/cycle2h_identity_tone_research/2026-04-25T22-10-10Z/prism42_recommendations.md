# Prism42 Identity + Tone — ranked recommendations (cycle-2h)

User's directive: "Your demo is currently emotionally wrong. Fix:
1. identity ('911...'), 2. tone (calm, human)." Output is a ranked,
sourced, applicable set of changes for THIS repo, not generic SOTA voice
advice. Implementation by the integrator; this document does not patch
files.

## Top recommendation in one paragraph

The single highest-leverage change to fix BOTH identity AND tone is to
**re-enable a cached, NENA-compliant first-utterance "9-1-1, where is
your emergency?" via `session.say()` with pre-synthesized audio**, AND
**move tone direction from per-utterance `[calm soft]` brackets into a
dedicated "Personality & Tone" prompt header with 3 few-shot examples**.
Both moves track the published cross-vendor 2026 voice-agent consensus
(LiveKit `session.say()` + cached TTS [S118]; OpenAI Realtime "Personality
& Tone" skeleton [S126]; Hume EVI prompt-as-voice-token [S129]; Pipecat
TTSSpeakFrame [S122]) AND the load-bearing normative source (NENA-STA-
020.1-2020 §2.2.3 SHALL clause [S101]). Cycle-2a sacrificed the SHALL
phrasing for ~850 ms of latency the user did NOT ask us to optimize for;
cycle-2f put per-utterance prosody markup in a place no leading vendor
recommends and where Fish renders the brackets unreliably.

## Ranked recommendations table

| # | Change | Fixes | File:line target | Effort | Risk | Source |
|---|---|---|---|---|---|---|
| 1 | Re-enable first-utterance "9-1-1, where is your emergency?" via cached TTS | identity (primary) + tone (secondary, by setting calm baseline) | `worker.py:781-803` (preroll branch) + new `agents/livekit/preroll_audio.wav` cache | ~30 LOC + offline TTS pre-synth + 1 file | L | [S101][S118][S126] |
| 2 | Add "Personality & Tone" header to FAST_DISPATCHER_SYSTEM_PROMPT replacing per-utterance brackets | tone (primary) | `orchestrator.py:227-254` (prompt header section) | ~25 LOC | L | [S126][S129][S130] |
| 3 | Add 3 few-shot dispatcher-caller examples in the prompt | tone | `orchestrator.py:355` (after ANSWER-THE-QUESTION RULE) | ~30 LOC | L | [S126][S129] |
| 4 | Replace content-blind FILLERS with content-aware acknowledgement turns | tone | `worker.py:75-81` (FILLERS tuple) + `_fire_filler` body | ~20 LOC | M | [S130][S148] |
| 5 | Drop `[calm soft]` per-utterance brackets; set ONE Fish reference-text personality tag at session level | tone (cleanup) | `agents/livekit/fish_speech_tts.py` reference_id template + remove cycle-2f prompt prefix | ~10 LOC | L | [S13][S14][S129] |
| 6 | Add "first response always begins with '9-1-1' if no preroll fired" enforcement to system prompt | identity (defense-in-depth) | `orchestrator.py:255-264` FIRST TURN block | ~10 LOC | L | [S101] |
| 7 | Handle "can you hear me?" / channel-affirmation utterances explicitly | identity + tone | `orchestrator.py:319-355` ANSWER-THE-QUESTION RULE | ~15 LOC | L | [S101][S105] |
| 8 | Disclose AI ONCE in pre-roll for synthetic-training framing | identity (transparency) | `agents/livekit/preroll_audio.wav` text | ~5 LOC | M | [S132] |
| 9 | Add IAED Protocol 41 "asks rather than tells" pattern to early turns | tone | `orchestrator.py:286-313` PROTOCOL section | ~15 LOC | M | [S142] |
| 10 | Cap reply length to "1-2 sentences, max 12 words" per OpenAI Realtime guide | tone | `orchestrator.py:364-370` HARD RULES | already in prompt; tighten enforcement language | L | [S126] |

L = low risk (additive prompt change; existing infra). M = medium
(behavior-changing in user-perceptible way; needs single-pilot before
sweep).

---

## Per-recommendation detail (top 5)

### Rec #1 — Cached "9-1-1, where is your emergency?" preroll

**Rationale.** NENA-STA-020.1-2020 §2.2.3 [S101] is a SHALL clause:
"All 9-1-1 lines at a primary Public Safety Answering Point (PSAP)
SHALL be answered with the phrase '9-1-1' ('Nine One One')." The
demo bypasses this. LiveKit's documented canonical pattern [S118]:
"For fixed phrases like these, you can cache TTS and use pre-
synthesized audio to avoid redundant TTS calls and reduce latency."
This is the engineering answer to the cycle-2a tradeoff — we get the
SHALL phrase AND we don't pay the 850 ms TTS round-trip we cut for.

**Evidence.**
- NENA SHALL clause [S101 §2.2.3].
- LiveKit cache pattern [S118 Agent speech docs].
- Pipecat TTSSpeakFrame canonical [S122 issue body, S125 kwindla
  Twitter].
- 911 industry vacancy on emergency-line voice AI [S110 Ava is
  non-emergency only; S116 CallHyper non-emergency only;
  S117 Prepared 911 non-emergency only] — there's no industry
  competitor, so the bar to clear is the NENA SHALL itself.
- Cross-source dispatcher canon: "9-1-1, what's the address of
  your emergency?" / "9-1-1, where is your emergency?" /
  "9-1-1, what's the emergency?" all NENA-compliant variants
  [S101 §2.2.3 verbatim].
- MPDS protocol: case-entry first question is "Where is the
  emergency?" [S106 search consensus]; location-first is the
  canonical PSAP variant.

**Patch sketch (NOT the patch, do not apply from this doc):**

In `agents/livekit/worker.py` around lines 781-803:

- Replace `log.info("preroll.disabled_for_demo", session_id=session_id)`
  with a call to the existing `session.say(...)` API loaded from
  cached audio file.
- Pre-synthesize `9-1-1, where is your emergency?` once offline (Fish
  S2-Pro at the same `seed=911`, voice preset, T=0.1) into
  `agents/livekit/static/preroll_911_v1.wav`.
- Stream the cached file as the first audio frame on `caller_spoke`
  TimeoutError path. Total time-to-first-audio = filesystem read +
  WebRTC frame dispatch ≈ tens of ms, not the 5-7 s Fish round-trip
  cycle-2a was avoiding.
- Keep the `caller_spoke.is_set()` check that cycle-2a added — if the
  caller jumps in, we still suppress the preroll. The cached preroll
  is interrupted by adaptive interruption (LiveKit 1.5.0+) just like
  any other utterance.

**Measurement.**
- Pilot on one synthetic call. Check t_first_audio is < 200 ms from
  pickup.
- Bench: 10/10 demo turns hear "9-1-1" as the first word of the
  call.
- A/B with audio recording + 3 raters: does the caller now perceive
  "this is a 911 line"? (Shipping criterion: 3/3 say yes within 5 s
  of pickup.)

**Why this is #1.** It addresses the exact user complaint
("identity") and is the only NENA-normative change in the list. The
other items are best-practice; this one is standards-compliance.

---

### Rec #2 — Personality & Tone header in system prompt

**Rationale.** OpenAI Realtime prompting guide [S126] and Hume EVI
[S129] both anchor "warmth" in a dedicated Personality & Tone section
of the system prompt. **The model emits language that the TTS then
renders prosodically** — Hume's verbatim claim: "excited text (e.g.
'Oh wow, that's so interesting!') will make EVI's voice sound
excited"; "warm and nurturing" prompts make the voice "sound soothing."
This is the cross-vendor recommended mechanism. **Per-utterance
`[calm soft]` brackets are off-pattern** — they're a Fish-specific
free-vocabulary text-conditioning that risks rendering literally.

**Evidence.**
- OpenAI Realtime guide [S126]: canonical skeleton has explicit
  "Personality & Tone" section. Verbatim example: "Personality:
  Friendly, calm and approachable expert customer service assistant.
  Tone: Warm, concise, confident, never fawning. Length: 2–3
  sentences per turn."
- Hume EVI prompting [S129]: "warm and nurturing" in prompt produces
  soothing voice without changing base speaker.
- Decagon [S130]: "Warmth builds trust through personal connection,
  while professionalism builds it through confidence."
- Vapi [S127]: "Maintain a calm, empathetic, and professional tone."
- Cycle-2f bracket pattern is structurally outside all four published
  patterns above.

**Patch sketch.** Add after `# CONTEXT — READ FIRST` in
`orchestrator.py:227`:

```
# PERSONALITY & TONE (read every turn)

Voice: a senior PSAP call-taker, mid-pitch female, 12 years of
experience, takes ~30 calls a shift. Calm and steady — not flat. Brief
and direct — not curt. The caller's panic does not become your panic.
Your cadence is slightly slower than the caller's. You lead with
acknowledgement, then the next action.

Tone words to inhabit, not to declare: present, focused, warm-but-not-
saccharine, capable, here.

Tone words to AVOID emitting verbatim: calm down, don't worry,
unfortunately, I'm afraid, I'd love to, I am an AI, dial 911.
```

Then DELETE the `[calm soft]` and `[short pause]` cycle-2f prefix from
LLM-emitted replies. The personality direction here is meant to
shape word choice; the resulting language renders calm via Fish's
existing prosody training, not via inline markup.

**Measurement.**
- 10-turn smoke set: count how many replies contain forbidden phrases
  ("calm down", "don't worry"). Target 0/10.
- 3-rater MOS Likert (1-5) on warmth perception: target ≥ 4.0
  (matches Phase A measurement protocol §A8 [S64][S67]).
- A/B vs cycle-2f current: does shipping THIS prompt (no brackets) +
  cached preroll improve the user's "emotionally wrong" rating? Need
  user demo to determine.

**Why #2 not #1.** The identity fix (Rec 1) is necessary AND
sufficient on its own to address the user's first complaint. The
tone fix (Rec 2-5) is structurally orthogonal but needs Rec 1
shipped first, because without identity the tone won't be heard
correctly anyway.

---

### Rec #3 — 3 few-shot dispatcher-caller examples in the prompt

**Rationale.** Hume EVI [S129] and OpenAI Realtime [S126] both
emphasize few-shot prompting as "one of the most effective ways
to improve response quality" and to "shape the assistant's
character." Our orchestrator has zero examples. Adding 3 short
exemplars (chest pain / not breathing / car accident / fire) of
the kind of dispatcher-caller turn we want the model to mirror is
cheaper and more transferable than markup tweaks.

**Evidence.**
- Hume EVI prompting [S129]: "Use examples to demonstrate how the
  model should respond." Few-shot is "one of the most effective ways
  to improve response quality."
- OpenAI Realtime [S126]: "examples help establish that tone, with
  the model learning to mirror the phrasing, pacing, and emotional
  style used in your samples."

**Patch sketch.** After `# ANSWER-THE-QUESTION RULE` in
`orchestrator.py`, add:

```
# EXAMPLES — the kind of dispatcher we are emulating

Example 1 — chest pain
Caller: "My husband is having chest pain. He's clutching his chest."
Reply: "Okay. What's your address?"

Caller: "847 Maple Drive, apartment 4B."
Reply: "847 Maple, 4B. Help is on the way. Stay on the line with me."

Caller: "He looks pale, is he going to be okay?"
Reply: "We're getting help to you fast. Is he able to talk to you?"

Example 2 — not breathing
Caller: "My son isn't breathing. Please."
Reply: "Where are you right now?"

Caller: "1422 Oak Lane."
Reply: "1422 Oak Lane. Help is on the way. Lay him flat on his back."

Caller: "Okay he's flat."
Reply: "Start chest compressions — center of the chest, hard and fast."

Example 3 — fire
Caller: "There's a fire in my kitchen. The cabinets are burning."
Reply: "Are you out of the building?"

Caller: "I'm in the hallway."
Reply: "Get outside now. What's the address?"

These are the model. Acknowledgement first (1-3 words), then the next
single action. Never two questions in one turn.
```

**Measurement.** Same as Rec 2 + bench check: do new replies look
structurally like the examples? (Eyeball pass; no automated grader.)

---

### Rec #4 — Content-aware acknowledgement vs content-blind fillers

**Rationale.** Phase A §A2 confirms our existing FILLERS tuple is
correct infrastructure. Decagon [S130] and the 911-dispatcher canon
[S148][S130] add a critical refinement: the filler should
ACKNOWLEDGE WHAT THE CALLER JUST SAID, not be a generic stall.

> Decagon: "Briefly acknowledging a missed delivery or a billing
> error before jumping straight to solutions signals to the caller
> that they've been heard." [S130]

The current FILLERS are:
```
"Okay, stay with me.", "Got it, one moment.", "I hear you.",
"Alright, hold on.", "Okay."
```

These are content-blind. A content-aware version inspects the last
caller utterance and produces a 1-3 word acknowledgement:
- "Chest pain — okay."
- "Not breathing — got it."
- "Fire — okay."

**Evidence.**
- Decagon: acknowledgement-before-action [S130].
- Tracy & Whittaker [S36 best_in_class]: "patient-focused directive
  redirection" — the redirection is content-anchored.
- Verbal Judo §1: dignity = the caller hears that you heard them
  [S144].

**Patch sketch.** Modify `_fire_filler` in `worker.py:827` to take
a parameter — the last caller utterance text (already available
via the SSE bus posted at `worker.py:744-749`) — and produce a
content-aware acknowledgement using a tiny rule table or a fast
2-token-budget LLM call. **Keep the existing 5 generic FILLERS as
fallback** if rule-table doesn't match. **Cancellable, interruptible,
fully reverts to filler infrastructure on failure.**

**Risk: M** — content-aware fillers can mis-classify. Mitigation:
fallback to generic FILLERS on any error / ambiguity. The fallback
preserves cycle-2d behavior bit-exact.

**Measurement.** Bench 10 turns:
- 8/10 should match content (reasonable rule-table coverage).
- 2/10 fallback to generic — that's fine.
- 0/10 mis-classify ("chest pain" said by caller → "fire — okay"
  is a hard fail; trip switches back to generic).

---

### Rec #5 — Drop per-utterance brackets, set ONE session-level Fish tag

**Rationale.** Phase A §A1 [S13][S14][S15][S16] established Fish
S2-Pro accepts open-vocabulary `[tag]` markup. **Cycle-2f put the
brackets per-utterance.** The Sesame "voice presence" research [S135]
explicitly identifies "consistent personality" as one of four
mechanisms — varying per-utterance markup works against this. Hume
EVI [S129] and OpenAI Realtime [S126] put tone direction at session
level once, not per-utterance.

For Fish specifically, the right mechanism is the reference-text /
voice-conditioning template fed at session start
(`agents/livekit/fish_speech_tts.py`, the Fish reference text), not
the LLM emit prefix. Setting this once means:

- The LLM's emitted text is clean prose (no bracket noise that
  might leak into the SSE bus or transcript).
- Fish's voice conditioning is set ONCE at session boundary and
  remains stable — best aligns with Sesame's "consistent personality"
  finding.
- We avoid the cycle-2f symptom where brackets are visible in
  bench logs: `[calm soft] Chest pain and breathing trouble`.

**Evidence.**
- Sesame voice-presence framework [S135] — consistency.
- Hume EVI prompting [S129] — personality once at session level.
- OpenAI Realtime [S126] — tone in prompt header.
- Fish docs [S14] — reference-text is the session-level conditioning
  surface.
- Cycle-2f observation: per-utterance brackets read as flat in user's
  laptop+mic test ("emotionally wrong").

**Patch sketch.** In Fish reference-text template (location TBD by
integrator — likely `fish_speech_tts.py:30-50` reference setup
block), add a single conditioning bracket directive:

```
[professional emergency dispatcher voice, calm and steady, mid-pitch
female, slightly slower than conversational pace]
```

In `orchestrator.py`, REMOVE the cycle-2f `[calm soft]` and
`[short pause]` injection from the LLM-emitted prefix. The model
emits clean prose; Fish renders it with the session-level voice
conditioning.

**Risk: L** — straightforward Fish config change. Existing
`seed=911` deterministic mode is preserved. Reverting is trivial
(re-enable cycle-2f prefix).

**Measurement.** 10-turn bench:
- 0/10 turns have visible `[`brackets`]` in LLM-emitted text.
- 3-rater MOS Likert ≥ cycle-2f current state.
- Subjective check: voice consistency across 10 turns of the same
  session feels less "actor-y" / more "person-y."

---

## What we considered and rejected

### Cartesia Sonic-3 / ElevenLabs / Hume engine swap

User-excluded. Phase A established Fish has open-vocabulary prosody
markup at parity with Cartesia/Hume on warmth surface; the gap is
how we use it, not which engine.

### Sample-rate boost above 44.1 kHz

Phase A §A1 ruled this out; Fish DAC outputs at 44.1 kHz; WebRTC
Opus quantization on phone channels makes higher rates inaudible
[Phase A §A1, S - Wikipedia voice-bandwidth consensus].

### Real dispatcher voice cloning (e.g., warm female 911 voice)

Consumer Reports March 2025 [S48 best_in_class]: 5/6 voice cloning
tools have easily-bypassable consent safeguards. Cloning a real
dispatcher is a swatting-vector liability. Single-voice synthetic +
disclosed-as-AI is the safe ship-state.

### Hume-style {emotion confidence} bracket markup on user turns

Hume's user-side bracket markup is decoded from acoustic features
in their proprietary eLLM — not portable to our STT (Parakeet TDT
0.6B v3). Adding it would require a separate emotion classifier
that we don't currently run.

### Disabling the SYNTHETIC TRAINING SIMULATION framing in the prompt

Phase A §A4 [S44][S45][S46]: STAT News April 2026, Nature 2026,
California SB 243 all explicitly counsel against AI voice agents
in real-emergency-line roles. Our framing is the safety rail; the
identity fix is "9-1-1" + the upfront AI disclosure (Rec 8) — not
removing the synthetic-simulation language.

### A second-LLM "tone polisher" pass on outputs

Adds latency, breaks our cycle-2d <2.5 s p95 win, and is dominated
by Rec 2 (prompt header) on perceptual outcome. Reject.

### Adding an IAED Protocol 41 license / training to the team

Out of scope ($99/seat × N callers + 4 hour module + non-trivial
integration). Mentioned as future-work not actionable this cycle.
The "asks rather than tells" verbatim heuristic [S142] is the
extracted pattern we can apply via Rec 9 without licensing.

### Real-time emotion classification on caller audio

Out of scope this cycle. Hume EVI does this internally via eLLM;
Fish doesn't. Adding a separate emotion-classifier path adds a
new failure surface and ms-cost. Defer.

### Mirroring the caller's pace / pitch

Phase A §A3 — explicitly counter-recommended for 911 (HSAJ [S37]
elevated dispatcher pitch escalates officer/caller stress; Tracy &
Whittaker [S36 best_in_class] counter-prosody is the calming
pattern). Mirror is right for B2C; counter is right for EMS triage.

---

## Subjective character anchor — does this hit the user's two needles?

User's exact words: "directionally excellent", "technically strong",
"emotionally wrong". Two specific gaps: identity ("911..."), tone
(calm, human).

- **Identity needle:** Rec 1 + Rec 6 + Rec 7 directly fix the
  reported failure. The agent's first audio will be the cached
  NENA SHALL phrase. The 9-1-1 line is identified before any
  other content.
- **Tone needle:** Rec 2 + Rec 3 + Rec 4 + Rec 5 attack the
  "emotionally wrong" diagnosis from the four published 2026
  vendor playbooks (LiveKit / OpenAI / Hume / Pipecat) and the
  three load-bearing 911-dispatcher canons (NENA / APCO / IAED).

Recs 1+2 alone are likely the minimum viable path. The remaining
recs (3-10) are progressive disclosure improvements to ship after
the user demo confirms 1+2 landed.
