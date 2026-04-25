# Cycle-2h — Identity + Tone deep research, 2026-04-25

Scope: orthogonal coverage to `findings/voice/best_in_class_2026-04-25/research.md`
(Phase A). That document is the engineering side: TTS naturalism, latency
perception, empathy markers, 911 industry comp, anti-robotic patterns,
retrofit levers. This document goes adjacent: where do real human dispatchers
+ real production voice agents put their FIRST utterance, how do voice
engineers in 2026 talk about the warmth gap, and what governs the boundary
between "calm + brief" and "robotic + flat" inside a system prompt.

User feedback that triggered this cycle (laptop+mic, 2026-04-25 evening):

> "Can you hear me?" → app responded "What's your location?"
> The app failed to identify itself as a 911 call center.
> Your writeup is directionally excellent.
> Your system is technically strong.
> Your demo is currently emotionally wrong.
> Fix: 1. identity ("911..."), 2. tone (calm, human)

Two specific failures: identity (the agent never said "9-1-1") and tone (the
agent felt cold despite cycle-2f's `[calm soft]` brackets in every reply).
Citations referenced as `[Sn]` against `sources.md`. Every URL retrieved
2026-04-25.

---

## Axis A — Identity / greeting patterns: industry canon vs prism42

### A1. The NENA-STA-020.1-2020 SHALL clause

The single most-load-bearing source we found, full text retrieved
2026-04-25 from the NENA standards CDN [S101]:

> §2.2.3 Standard Answering Protocol – 9-1-1 Lines:
> "All 9-1-1 lines at a primary Public Safety Answering Point (PSAP)
>  SHALL be answered with the phrase '9-1-1' ('Nine One One')."

This is a normative SHALL clause (RFC-2119 binding) [S101 §Document
Terminology]. Local options MAY add:

> "Agencies may elect to precede '9-1-1' with their agency name.
>  Additional information or questions may be added, as in:
>  '9-1-1, what is the emergency?', or '9-1-1 what is the address of the
>  emergency?', '9-1-1 what is the location and type of emergency?'
>  Other information, such as the operator identification number or
>  that the line is recorded may also be added."

Three findings load-bear on prism42:

1. **The agency name is OPTIONAL on emergency lines and DISCOURAGED
   in the 2006 56-005 predecessor document** that NENA-STA-020.1-2020
   merges, per the search-result excerpt of 56-005 §"It is recommended
   that the agency not be identified when answering emergency lines to
   avoid confusing the caller and delaying response to alternate
   [non-emergency] services" [S102]. NENA-STA-020.1-2020 softens this
   to a MAY because some agencies prefer to identify, but the original
   discouragement reasoning still stands and is the canonical reason
   real PSAP first lines tend toward "9-1-1, where is your emergency?"
   without an agency name. **Implication for prism42: the demo should
   open with "9-1-1," not "GOATnote 9-1-1," not "Prism 9-1-1," not the
   AI's name.**
2. **Three published wordings are equally normative**:
   - "9-1-1, what is the emergency?"
   - "9-1-1, what is the address of the emergency?"
   - "9-1-1, what is the location and type of emergency?"
   The MPDS (Medical Priority Dispatch System) Case Entry first
   question is "Where is the emergency?" [S106 search consensus].
   **Location-first is the dominant local PSAP variant** because
   "dispatch can roll units on the address even if the call drops
   mid-sentence" — a reasoning the prism42 system prompt at
   `agents/livekit/orchestrator.py:255-264` already encodes correctly.
3. **The SHALL is on PHRASING, not on whether the agent goes first.**
   NENA does not require the dispatcher to speak before the caller. In
   real PSAP operation the dispatcher answers IMMEDIATELY (the SHALL
   in §2.2.1: 90% of calls answered within 15 s, 95% within 20 s).
   For voice-AI, this translates to: the agent should speak first
   because that's what callers expect from a 911 line, but if the
   caller speaks first, the agent's FIRST RESPONSE must still begin
   with "9-1-1" (or contain explicit identification) — the SHALL is
   on the verbal contract, not the timing.

### A2. Special-call handling — the silent caller, the "can you hear me" caller

NENA-STA-020.1-2020 §§2.2.7-2.2.8 explicitly addresses the case the user
hit on the laptop demo (the agent didn't know it was a 911 line, so when
the caller said "can you hear me," it answered with a location question
— wrong sequence) [S101]:

- §2.2.7.3 Non-Responsive Calls: "All non-responsive calls MUST be
  interrogated with a TTY/TDD to determine if the caller is attempting
  to report an emergency using a special communications device."
  Five seconds minimum wait before initiating silent procedure
  [S101 §2.2.7.3].
- §2.2.8 Indicated Emergency: any background-noise or partial-utterance
  signal triggers re-contact attempts.
- "Four-Second Rule" (AEDR Journal empirical study) [S105]:
  dispatchers should wait 4 s after each prompt before progressing.
  Verbatim "If this is an emergency press one" / "If you need police
  press 1, fire press 2, ambulance press 3" are the established
  silent-procedure prompts [S105].
- For voice-impaired callers the script is keypad-driven: "press 1
  for police", "4 for yes / 5 for no" [S104, Massachusetts Silent
  Call Procedure].

**Why this matters for prism42's "can you hear me" failure:**

The user said "can you hear me?" on the demo. The orchestrator received
this, interpreted it as a partial caller utterance (because no preroll
fired), and emitted "What's your location?" because that's the
APCO-aligned address-first cell of `FAST_DISPATCHER_SYSTEM_PROMPT`
(`orchestrator.py:288`).

In a real PSAP, "can you hear me?" from a caller is not treated as a
silent-call event (the caller is speaking) and is not treated as a
location-collection prompt. The trained-dispatcher response is one of:

- **"Yes, this is 9-1-1, what's your emergency?"** — affirms the
  channel, identifies, then prompts.
- **"You're through to 9-1-1 — go ahead."** — affirmative-then-cede.

Both confirm the audio channel AND identify the line, in 4-7 syllables.
This is the single missing pattern in our orchestrator prompt and is
the surgical fix point for the user's reported failure.

### A3. 988 Suicide and Crisis Lifeline — what the counselor's first line looks like

[S107] (988 Lifeline What to Expect) and [S108] (988 FAQ training):

- IVR pre-roll is automated: select language / Veterans line / local
  contact center.
- Live counselor's first turn: **"a counselor will say hello and
  introduce themselves"** [S107, §What to Expect / Connected to a
  counselor]. Then: **"your skilled counselor will ask you if you
  are safe."**

**Two-step opening pattern** (not a single line):
1. "Hi, I'm [name], I'm a counselor at [center]." — establish
   identity, name, role.
2. "Are you safe right now?" — establish acuity.

Crisis Text Line training (volunteer manual visible via [S109]):
counselors are trained to "introduce themselves, reflect on what
you've said, and invite you to share at your own pace" — also
two-step (identity + invitation).

**Implication for prism42 cross-domain validation:** even non-911
crisis-services explicitly identify the line on turn 1. The "speak
first, identify second" pattern is universal across PSAP + crisis
voice systems. A system that opens with "What's your location?"
without "9-1-1" identification is reading as a customer-service IVR
to the caller, not a 911 line.

### A4. Aurelian Ava (production 911 voice AI) — what's actually shipped

Ava is the closest production-deployed AI voice agent to prism42's
demo target. Searched, fetched, summarized:

- **Deployments confirmed 2026:** Volusia County FL, Snohomish County
  WA (220k+ calls), MACC 911 (Wisconsin) [S110][S111][S112], Akron
  OH (1300+ calls, 400+ transferred to dispatcher) [S113].
- **Scope:** non-emergency lines ONLY. Ava is "a voice-first virtual
  agent that answers non-emergency lines, verifies location, gathers
  caller details, and produces CAD-ready summaries for dispatchers"
  [S110]. **NOT 911 emergency line** — that distinction matters.
- **Public-facing exact greeting text: not published.** The Volusia
  press release [S114] describes capability without quoting Ava's
  opening words. The MACC case study [S115] only contains
  third-party characterizations: "talks and acts like a real
  person". Aurelian's own product page [S110] does not publish a
  sample dialog.
- **What we can infer:** Ava is non-emergency, so her open is closer
  to NENA's §2.2.4 non-emergency answering protocol — "Agency name,
  may I help you" pattern — not the §2.2.3 "9-1-1" SHALL clause.
- **CallHyper [S116] and Prepared 911 [S117]** likewise ship
  non-emergency-only AI voice agents and don't publish their
  greeting text.

**Insight: the production 911 industry has effectively NO published
SOTA on emergency-line first-utterance for an AI voice.** The bar to
clear is internal. (This matches our Phase A finding: "no benchmark
to chase" — confirmed orthogonally.) Prism42 is operating in a public
research surface and can set its own standard, anchored to NENA-STA-020.1.

### A5. Open-source reference implementations — the canonical "speak first" pattern

Cross-source convergence on two production voice frameworks:

- **LiveKit Agents 1.5.6** (our framework) [S118][S119]:
  - Documented canonical: `session.say(text)` for fixed greetings
    + `session.generate_reply(instructions=...)` for dynamic.
  - Telephony quickstart [S120]: "Call the `generate_reply` method
    of your AgentSession to greet the caller after picking up. You
    should also remove the initial greeting or place it behind an
    if statement to ensure the agent waits for the user to speak
    first when placing an outbound call." (For inbound calls — our
    case — the greeting should fire.)
  - **Performance note (canonical doc, [S118]):** "For fixed phrases
    like these, you can cache TTS and use pre-synthesized audio
    to avoid redundant TTS calls and reduce latency." This is the
    direct engineering answer to prism42's preroll-disabled-for-
    latency tradeoff: cache the greeting audio once, replay it as
    a static frame.
  - Multi-agent canonical pattern is `on_enter`: "the agent will
    generate a reply according to its instructions" via
    `self.session.generate_reply(...)` in `on_enter()` [S118
    code excerpt verbatim].
- **Pipecat (our cycle-2e port lineage)** [S121][S122]:
  - Canonical first-greeting pattern is
    `await task.queue_frames([TTSSpeakFrame(FIRST_SPEECH_TEXT)])` —
    a dedicated frame type whose entire purpose is "speak this
    string at the next pipeline tick" [S122 GitHub issue body
    quoted].
  - Pipecat's TTSSpeakFrame is "ordered" not "system": it queues in
    sequence with caller transcript frames and gets cancelled by
    a subsequent EndFrame (Issue #1787 [S123]). Important: it does
    not bypass the LLM context; the LLM sees that the agent said
    the greeting [S124 Issue #3459].
  - kwindla (Pipecat creator) on Twitter, dated 2026-06-30 (after
    our cutoff but referenced retroactively): "it's fairly common
    to have a voice agent say a specific phrase when you start a
    function call or other task that will take some time to return.
    In Pipecat you typically do this by pushing a TTSSpeakFrame."
    [S125].

**Cross-framework convergence: production voice frameworks treat the
first greeting as a CACHED OR PRE-DETERMINED string fired before any
LLM token is produced.** This is the universal pattern. Prism42's
cycle-2a cut violates it.

### A6. The emerging "voice-agent-warmth playbook" (engineer-side)

What 2026 voice-engineer content converges on:

| Lever | Source | Verbatim recommendation |
|---|---|---|
| Cache greeting | LiveKit docs [S118], engineer threads | "use pre-synthesized audio" |
| Speak first on inbound | LiveKit telephony [S120], Pipecat examples | greeting fires before transcription |
| Identify the line / role / brand | OpenAI Realtime guide [S126], Vapi guide [S127], every healthcare voice example [S128] | system-prompt skeleton always has "Role & Objective" |
| Tone in prompt header, not in markup | Hume EVI prompting [S129], OpenAI Realtime [S126], Decagon [S130] | "Personality & Tone: warm, concise, confident, never fawning" |
| Tone declaration FIRST, not per-utterance | Hume [S129] — "warm and nurturing in the prompt" not "[warm]" inline; OpenAI Realtime [S126] | base voice direction at session level |
| 1-2 sentence reply ceiling | OpenAI Realtime [S126] "2-3 sentences per turn"; Vapi [S127] "Keep responses brief" | declared length cap |
| Mid-utterance fillers | Sesame CSM design [S131]; Vapi filler injection [S127] | natural-sounding |
| Speak the same sentence the same way | Hume EVI [S129] "few-shot prompting" pattern | examples shape voice consistency |
| Disclose AI on call | NTIA / govtech survey [S132]: "37% would lose confidence in companies hiding AI" | upfront disclosure |

Five recurring 2026 settings that everyone agrees on:

1. **Cache the greeting.** No LLM round-trip on first audio.
2. **Declare tone in the prompt's "Personality & Tone" section, NOT
   per-utterance brackets.**
3. **Cap reply length explicitly** ("2-3 sentences" or word count).
4. **Show the model 2-3 examples** of correct tone via few-shot.
5. **Use the model's natural prosody, not stage directions in
   brackets.**

**This last point is critical to the cycle-2f issue.** OpenAI's Realtime
guide explicitly says the tone instruction shapes the voice:
"Friendly, calm and approachable" in the prompt makes the model emit
text that the TTS renders as friendly, calm and approachable [S126].
Hume EVI explicitly says "warm and nurturing" in the prompt makes the
voice sound soothing — and even more directly, "excited text (e.g. 'Oh
wow, that's so interesting!') will make EVI's voice sound excited"
[S129]. **The lever is the WORD CHOICE the model emits, modulated by
prompt direction. Inline `[calm soft]` brackets are a Fish-only
mechanism that may render literally on prosody-aware engines and
are a less general tool than emitting language that's already calm.**

---

## Axis B — Human-vs-robotic tone in 2026 voice agents

Phase A covered Cartesia / ElevenLabs / Hume / Sesame / Fish prosody
markup primitives [S1-S17 in `best_in_class`]. This axis covers what
each method actually exposes for "warmth" and which mechanism
generalizes onto Fish without an engine swap.

### B1. Cartesia Sonic-3 — what calm sounds like, exactly

[S133] full emotion-tag enumeration (verified 2026-04-25):

> Primary emotions (best results): `neutral`, `angry`, `excited`,
> `content`, `sad`, `scared`
> Extended (60+): includes `calm`, `peaceful`, `serene`, `sympathetic`,
> `affectionate`, `grateful`, `trust`, `compassionate` is NOT in the
> public list (closest is `sympathetic` + `affectionate`).

Calm-context tag mapping for emergency dispatch (Cartesia's published
docs, [S133]):
- `<emotion value="calm"/>` — directly named.
- `<emotion value="content"/>` — primary tier (best results).
- `<emotion value="sympathetic"/>` — for compassion register.
- Cartesia documents: **"Emotion tags work best when consistent with
  transcript"**; mismatched (calm + panic-inducing words) may not
  produce desired result [S133].

Speed control: `<speed ratio="0.6-1.5"/>`. Volume: `<volume ratio="0.5-2.0"/>`.

**Port to Fish:** Cartesia's XML-style markup is NOT parsed by Fish
S2-Pro. The Fish equivalent is the inline-bracket vocabulary
`[calm]`, `[soft]`, `[gentle pace]` documented in
`best_in_class/research.md` §A1. **These are not equivalent in
fidelity** — Cartesia has discrete trained tokens for 60+ emotions;
Fish has a free-vocabulary text-conditioning that may render the
literal word "[calm]" if the model interprets it ambiguously. The
Phase A finding (Fish renders open-vocabulary description text
[S13][S14][S15]) is the pre-existing constraint.

### B2. Hume EVI 3 — the "prompt-as-voice-token" pattern

Hume's prompting guide, retrieved via redirected URL [S129]:

> "Use examples to demonstrate how the model should respond. A sample
>  interaction shows: User: 'I just can't stop thinking about what
>  happened. {very anxious, quite sad, quite distressed}'
>  Assistant: 'Oh dear, I hear you. Sounds tough, like you're feeling
>  some anxiety and maybe ruminating...'"

Two patterns of note:
1. **{emotion confidence} markup is on USER turns**, not assistant
   turns. EVI's model receives user emotion as bracket-suffixed
   side-channel, then generates language that responds to that
   emotion. **It's an INPUT representation, not an output direction.**
2. **Prompted with "warm and nurturing"**, the voice "sounds soothing,
   but will not change the base speaker." [S129]. Voice change
   happens through generated language's prosody, not via direction
   tokens.

**Direct implication for prism42:** the `[calm soft]` bracket cycle-2f
inserts is structurally OUTSIDE both Cartesia and Hume canonical
patterns. Cartesia uses `<emotion value="calm"/>` (XML, parsed). Hume
uses the prompt's adjective directives ("warm and nurturing"). Fish
uses inline bracket text — but **Fish renders bracket text by
free-vocabulary conditioning**, which is the most fragile of the three.

The single best Fish mechanism for tone control is **the bracket at
SESSION LEVEL, not utterance level**. Set `[professional dispatcher
voice, calm and steady]` ONCE in the reference-text template, and the
LLM emits clean language that Fish renders with the conditioned voice.
Per-utterance `[calm soft]` brackets risk being rendered literally OR
ignored, depending on how the bracket-token sits in the LLM's emit
sequence.

### B3. Sesame CSM-1B — "voice presence" decomposed

Sesame's published research blog [S135] decomposes "voice presence"
into four components:

> "1. Emotional intelligence: reading and responding to emotional
>     contexts
>  2. Conversational dynamics: natural timing, pauses, interruptions
>     and emphasis
>  3. Contextual awareness: adjusting tone and style to match the
>     situation
>  4. Consistent personality: maintaining a coherent, reliable and
>     appropriate presence"

Engineering takeaways:

- **(1) is what the LLM emits**, not what the TTS does. We can do this.
- **(2) is timing infrastructure** — already addressed in cycle-2d
  (preemptive_generation, adaptive interruption, dynamic endpointing).
- **(3) requires the system prompt to redirect tone based on caller
  state.** Our orchestrator already does this in part (CPR override
  in `orchestrator.py:359-362` shifts to instruction mode). Could
  be stronger: explicit "if caller distressed, soften; if caller
  numb, more directive" branching in the prompt.
- **(4) is the WORST place to put `[calm soft]` brackets** because
  inline brackets per-utterance VARY personality across turns, working
  against consistency. **The discipline is one personality tag, set
  once, never repeated.**

Sesame's most-quoted observation [S135]:

> "Without these qualities, emotional flatness becomes more than just
>  disappointing — it becomes exhausting."

The user's "emotionally wrong" is exactly this. The cure is presence,
not bracket markup.

### B4. ElevenLabs v3 inline tags

[S6][S7] in best_in_class. Important contrast for prism42: ElevenLabs
v3 ships `[whispers]`, `[shouts]`, `[laughs]`, `[sighs]`, plus
descriptive `[crying]`, `[mischievously]`, `[excited]` etc. **NOT in
the public list:** `[calm]`, `[gentle]`, `[soft]` — those are not
ElevenLabs v3 tags. The closest tag for empathic delivery is `[whispers]`
or none at all (rely on text content). **Inline bracket markup is
NOT a transferable abstraction across engines.** Our cycle-2f
`[calm soft]` is Fish-specific.

### B5. OpenAI Realtime — the prompt skeleton

[S126], retrieved 2026-04-25:

> Section structure (canonical):
> Role & Objective — who you are and what 'success' means
> Personality & Tone — the voice and style to maintain
> Context — retrieved context, relevant info
> Reference Pronunciations — phonetic guides for tricky words
> Tools — names, usage rules, and preambles
> Instructions / Rules — do's, don'ts, and approach
> Conversation Flow — states, goals, and transitions
> Safety & Escalation — fallback and handoff logic

Personality & Tone example (verbatim):
> "Personality: Friendly, calm and approachable expert customer service
>  assistant. Tone: Warm, concise, confident, never fawning.
>  Length: 2–3 sentences per turn."

**This is the most-prescriptive published 2026 prompt skeleton.** Our
orchestrator's `FAST_DISPATCHER_SYSTEM_PROMPT` has all sections
implicitly but does not separate **Personality & Tone** as a
dedicated header. Cycle-2f added `[calm soft]` per-utterance because
the prompt does not have a "Personality & Tone" header where the
direction "calm, steady, present" could live ONCE.

### B6. Vapi prompting guide [S127]

Vapi's idiomatic Personality + Tone fragment:

> "Maintain a calm, empathetic, and professional tone."
> "Act as Iva, a sales agent who is a human being and has real feelings."
> "Tone: conversational, spartan, use less corporate jargon"

Cadence:
> "Ask one question at a time, but combine related questions where
>  appropriate."
> "Keep responses brief."

What NOT to say:
> "Never say the word 'function' nor 'tools' nor the name of the
>  Available functions."
> "Never say 'ending the call'."

These are domain-specific (Vapi is a B2B platform). The transferable
pattern is the explicit **NEVER list** at prompt level.

### B7. Decagon's "voice persona" framing [S130]

> "Warmth builds trust through personal connection, while
>  professionalism builds it through confidence."
> Avoid "stiff, overly formal phrasing or, even worse, performative
>  enthusiasm" and use "brief spoken transitions ('Give me a second
>  while I pull that up')."
> "Briefly acknowledging a missed delivery or a billing error before
>  jumping straight to solutions signals to the caller that they've
>  been heard."

The acknowledgement pattern matters for 911: before instructions, a
3-syllable acknowledgement of what was reported.

### B8. Zowie's architectural fix [S134]

Zowie identifies four levers, the third of which is directly relevant:

> "Smart Filler Insertions: When the agent recognizes it needs time
>  ... it inserts a natural, conversational bridge."

We already do this (`worker.py:75-93`). Zowie's observation that
filler injection is one of the four critical levers for "robotic"
removal is a confirming citation for our existing infrastructure;
the gap is variety + tone, not whether the lever exists.

---

## Axis C — How voice engineers talk about this problem (2026)

What converges across engineer-authored 2026 content:

### C1. The "first 200ms is everything" claim

Every 2026 guide hits this [S118][S136][S137][S138]: the first audio
the caller hears within 200ms of pickup is what determines the entire
call's feel. This is mechanically true (our preroll cut introduced a
silence gap) and perceptually true (engineer-side: "first sentence
sets the tone for the entire conversation").

### C2. The "say less" rule

OpenAI Realtime [S126], Vapi [S127], Decagon [S130], the AssemblyAI
2026 voice stack [S139], all converge: 1-2 sentences max per turn.
The reason is voice-agent specific — long replies in voice = perceived
robotic monologue. **2-3 sentences is the published cap.** Our
orchestrator says 5-12 words, which is more aggressive than industry
norm but right for PSAP triage [S33 EMS Pre-Arrival].

### C3. The "tone in the system prompt header" rule

OpenAI Realtime [S126], Hume EVI [S129], Vapi [S127], all converge:
tone is declared ONCE at session start, in the system prompt's
opening. NOT modulated per-turn. Cycle-2f's per-utterance `[calm
soft]` brackets are off-pattern.

### C4. The "cache the greeting" rule

LiveKit [S118], Pipecat [S122], industry consensus: greeting is
pre-synthesized audio served from cache. **The latency tradeoff that
drove our cycle-2a preroll cut is not industry-standard.** Industry
ships pre-cached greeting + then streams response.

### C5. The "model your voice on someone real" rule

Hume EVI [S129] few-shot prompting; OpenAI Realtime [S126]: "examples
help establish that tone, with the model learning to mirror the
phrasing, pacing, and emotional style used in your samples." This
is the pattern we are not yet using in the orchestrator's prompt
— there are no example dispatcher-caller exchanges shown. Adding
3-5 verbatim "this is the kind of dispatcher we are emulating"
exchanges would do more for tone than any bracket markup.

### C6. The "barge-in is non-negotiable" rule

LiveKit's adaptive interruption [S140], every 2026 voice-agent guide
[S136][S137][S141]: barge-in is the make-or-break of voice agents.
We already have this (cycle-2d).

### C7. The "tone matters more than latency below 1500ms" pattern

Decagon's central claim [S130]: "no amount of infrastructure precision
compensates for a voice agent that fumbles conversation flow, sounds
robotic, or simply feels wrong for your brand."

Hamming's cited 2026 figure [S20]: "humans don't notice 600 vs 900 ms"
but DO notice flat affect in any reply duration. Below 1500 ms p95
(which we are at — 2468 ms is over, but cycle-2d landed an
improvement), the warmth lever has greater perceptual weight than
the latency lever.

---

## Axis D — Crisis-line and PSAP dispatcher training (the human baseline)

This is the section the user's "calm, human" comment most directly
maps to.

### D1. APCO + NENA + IAED canon

- APCO EMD program [S31 in best_in_class] — telecommunicators
  "answer calls for emergency medical service, properly prioritize
  the response, and convey proper pre-arrival instructions."
- NENA-STA-020.1-2020 [S101] — already covered in §A1.
- StatPearls EMS Pre-Arrival [S33 in best_in_class] — "scripted, not
  improvised"; "assumption-based, not option-based" (directive language
  only).
- IAED Protocol 41: Caller in Crisis [S142][S143]:
  - Mental States Menu identifies 22 distinct caller mental states.
  - Emotional Control Tool guides dispatcher language.
  - Verbatim from [S142]: **"In contrast to other protocols,
    Protocol 41 asks rather than tells."**
  - Verbatim: **"'Intending' is used instead of 'threatening.'"**
  - Specific de-escalation phrasing is paywalled ($99 training).
  - Required 8-hour module-based training.

The **"asks rather than tells"** insight is the single most-load-
bearing IAED finding for our PSAP voice agent. Our orchestrator
prompt is heavily directive ("Tell me, is he breathing?", "Start chest
compressions"). For early-call rapport, the IAED pattern is the
opposite: ASK. **"Are you with him right now?" beats "Tell me where
he is."** This is the de-escalation track our orchestrator misses on
turns 1-3.

### D2. Tracy & Whittaker (foundational paper) — full quote

[S36 in best_in_class], retrieved fresh:

> "Dispatchers use their voice and breathing, and give callers steps
>  that they can do while waiting, to calm them down."
> "'Tell me to calm down' does not work; giving the caller something
>  to do does."
> "Modal-verb redirection ... works as a patient-focused directive
>  that calms the caller and re-engages cooperation."

The recipe extracted from Tracy & Whittaker:

1. Voice modulation by the dispatcher (their voice, pacing, breathing).
2. Specific, doable task assigned to the caller.
3. NEVER "calm down" as a directive.

This is mechanically NOT what our cycle-2f does. `[calm soft]` is a
TTS-side directive to the dispatcher's voice. **The Tracy & Whittaker
finding is that the voice IS calm, AND the caller is given a small
task to anchor.** Our orchestrator does step 2 (asks "Is he
breathing?"). Step 1 — the voice modulation — is the gap.

### D3. Verbal Judo — George Thompson's 5 Universal Truths

[S144], retrieved 2026-04-25:

> "1. All people want to be treated with dignity and respect.
>  2. All people want to be asked rather than being told to do something.
>  3. All people want to know why they are being asked.
>  4. All people want to be given options rather than threats.
>  5. All people want a second chance when they make a mistake."

For prism42, Truths 1-2 are load-bearing:

- **Dignity** — opening with "9-1-1, what's your emergency?" affirms
  dignity (it's the standard, not lessened, not condescending). Our
  current opening (when preroll fires) "Nine one one, what is your
  location and emergency?" is dignity-affirming. Without preroll,
  the agent's first reply lands directly into a question with no
  identification — which can feel interrogation-like.
- **Asked rather than told** — confirms IAED Protocol 41 pattern.
  "Tell me your location" is told. "Where are you right now?" is
  asked. Soft change, real perceptual difference.

### D4. Hostage negotiation cadence research [S145]

Mediate.com Quick Tip on Hostage Negotiator Tone (paywalled retrieval
failed; cross-confirmed via Police1 [S146] and Psychology Today
[S147]):

> "Negotiators are trained to speak slowly and calmly, as people's
>  speech patterns tend to mirror the tone of the dominant
>  conversation, so this provides a model of slow, calm, clear
>  communication from the outset."
> "After interviewing numerous hostage takers, frequently the
>  hostage takers could not recall the specific things the
>  negotiator said to them, but what they did remember was the
>  tone of voice of the negotiator — it was one of concern for
>  them as a victim and in need of help." [S145 paraphrase via S147]

Engineering anchor: the negotiator's CADENCE primes the caller's
cadence. For voice-AI, this means: agent speaks slow → caller
slows → caller becomes coherent. We approximate this by output
length (5-12 words) which creates short utterances. We do NOT
approximate it by speaking-rate control. **Fish doesn't expose
duration_per_word; the closest control is `[slow]` or
`[gentle pace]` brackets** [S16 best_in_class].

### D5. What dispatchers explicitly DO NOT say (consolidated)

Cross-source consensus [S148][S149][S150]:

- **NOT "calm down"** (escalates emotion).
- **NOT "don't worry"** (encourages worry).
- **NOT "no" / strong negatives** (gasoline on fire).
- **NOT what NOT to do** ("don't move him") without the do-version
  follow-up.
- **NOT "I am an AI"** in a roleplay context (breaks contract).
- **NOT "dial 911"** (we ARE 911).
- **NOT corporate-IVR phrasing** ("How may I assist you today").
- **NOT performative enthusiasm** ("I'd love to help!" on a 911 line).

What dispatchers DO say (cross-source) [S148][S149][S151]:

- **"I understand you're upset. It is okay. I am here to help."**
  [S148, Kovacorp].
- **"Police/EMS will be there soon. They will be able to take care of
  you and the emergency."** [S148].
- **"Listen carefully. I'll tell you what to do."** [S151, AHA T-CPR].
- **"Stay with me."** (acknowledged in trauma-informed care literature
  but not bound to a specific 911 source — closest cite is general
  trauma-informed framing).
- **Acknowledgement before instruction** [S130 Decagon]: "I hear you"
  / "Got it" / "Okay" before pivoting to the next directive.

### D6. Hesitancy markers / acknowledgement turns

The pattern across crisis-line and emergency-dispatch literature:
**a 1-3 word acknowledgement turn LEADS the response, not trails it.**

Examples (from cited sources):
- "Okay." [pause] → next directive.
- "Got it." [pause] → next directive.
- "I hear you." [pause] → next directive.

This places the acknowledgement at the FRONT of the dispatcher's
turn — the caller hears empathy first, then the action item. Our
existing FILLERS tuple (`worker.py:75-81`) is structurally a
free-floating filler between caller-end and reply-start, which fills
the same perceptual slot — but is heard as filler, not as
acknowledgement of the *content* of what the caller just said.

**Differential fix:** filler injection is content-blind ("Okay, stay
with me"). Acknowledgement is content-aware ("That's chest pain — okay").
For low-effort improvement, the latter beats the former on warmth.

---

## Cross-axis synthesis

The orthogonal coverage across A-D points to one master finding:

> The 911-PSAP-dispatcher-voice domain has had a normative SHALL clause
> on first-utterance phrasing ("9-1-1") since at least 2006, well before
> AI voice agents existed. Production AI voice in this domain (Aurelian,
> Carbyne, Prepared 911) operates on the non-emergency line where the
> SHALL doesn't apply — so they leave the SHALL clause unaddressed in
> their public materials. Prism42, framed as a SYNTHETIC TRAINING
> SIMULATION of PSAP work, is operating where the SHALL clause DOES apply.
> The cycle-2a preroll cut violated it. The cycle-2f bracket markup
> didn't restore it. Restoring it is the surgical fix.

The user's "emotionally wrong" diagnosis splits into two technically
distinct problems:

1. **Identity gap** = absence of "9-1-1" on turn 1.
2. **Tone gap** = mechanism error: per-utterance `[calm soft]` brackets
   are an inferior generalization of session-level personality
   declaration. The right move is a Personality & Tone header in the
   prompt + few-shot examples + acknowledgement-before-instruction
   discipline + (optionally) a single session-level Fish reference-text
   bracket.

Both fixes are 1-day surgery. Neither requires engine swap. Both align
with cross-vendor 2026 voice-engineer consensus AND with NENA / APCO /
IAED canon.
