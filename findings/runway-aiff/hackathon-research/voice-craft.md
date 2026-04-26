# Voice Craft for the prism42 Anthropic Hackathon Cut

**Audience:** Anthropic engineers and "Most Creative Opus 4.7 Exploration" judges who hear voice demos every working hour. Subject is a self-hosted 911 voice-dispatch agent achieving 44 ms TTFT on a B300 pod. Total runtime ~3 min; 108s of VO already rendered using `Brian` (`nPczCjzI2devNBz1zQrb`) + `Charlie` (`IKne3meq5aSn9XLyUdCD`).

---

## Inline Summary (250 words)

The current Brian + Charlie cut is competent but generic — Brian is the single most over-deployed ElevenLabs male voice on TikTok and YouTube tutorials, and Charlie's "British younger" register reads as the default AI-podcast sidekick. Anthropic judges have heard both voices several thousand times. Re-rendering is worth the 13.9k characters out of 1.5M budget.

The strongest move for this audience is a **single-voice, first-person developer-monologue** in the register of an Anthropic engineering blog post — calibrated, specific, anti-hype. Replace Brian with `Harrison Gale` (`fCxG8OHm4STbIsWe4aT9`, American baritone) for documentary segments and keep one short field-call beat with `Patrick International` (`9Ft9sm9dzvprPILZmLJl`) instead of Charlie. Drop the duo gimmick everywhere else.

For the "Most Creative" prize, the strongest bet is a 6-8 second moment near the climax where Opus 4.7's *own text output* — generated live as part of the demo and run through ElevenLabs — narrates the engineering choice in first person ("I picked NVFP4 because the BF16 path was leaving 45% of the tensor core idle"). This makes the model the medium, not the subject. Shippable in 24h via standard Messages API + ElevenLabs TTS; no Anthropic Voice mode access required.

Voice settings shift toward audiobook-pro defaults: stability 0.55-0.65, similarity 0.75, style 0.0-0.10. Music bed: a single sustained drone at -22 dB, no rhythmic newsroom underscore — that genre cue marks the cut as parody-news, which is the wrong frame for Anthropic's house tone. The 44 ms reveal lands in **silence**. Below: voice IDs, settings, dialogue rules, sound design, and the 5-line direction card.

---

## 1. The ElevenLabs voice landscape (April 2026)

The default-voice catalog (`Rachel`, `Adam`, `Antoni`, `Brian`, `Charlie`, `Bill`, `Daniel`, `Liam`, `Will`, `Ethan`) **deprecates Dec 31 2026** and is the set every AI-demo creator pulls from. Using anything from this list reads as "I clicked the first preset."

- **Brian** (`nPczCjzI2devNBz1zQrb`) — saturated; default for crypto-explainer and AI-news YouTube channels.
- **Adam** (`pNInz6obpgDQGcFmaJgB`) — even more saturated. The TikTok narration voice.
- **Antoni** (`ErXwobaYiN019PkySvjV`) — second-tier saturated.
- **Charlie** (`IKne3meq5aSn9XLyUdCD`) — slightly fresher but now default for AI-podcast cold-opens.
- **Rachel** (`21m00Tcm4TlvDq8ikWAM`) — canonical female default; same problem.

**Voices that land well for technical-documentary register and are NOT yet saturated** (pulled from elevenlabs.io/voice-library/documentary-narrator-voices and /narrator-voices):

| Voice | ID | Use case in this cut |
|---|---|---|
| **Harrison Gale** — Smooth, Rich and Deep (American baritone) | `fCxG8OHm4STbIsWe4aT9` | **Primary narrator.** Documentary-grade. Replaces Brian. |
| **Bill — Informative, Clean and Natural** (American) | `lnUnPeUhSI5EcqtFBux7` | Backup primary if Harrison reads too "audiobook." |
| **Patrick International** (deep international male) | `9Ft9sm9dzvprPILZmLJl` | Field-stringer slot if you keep one. Cuts cleaner than Charlie. |
| **David Castlemore — Newsreader** (American) | `XjLkpWUlnhS8i7gGz3lZ` | If you want broadcast register without the parody-news cue. |
| **Nathaniel — Deep, Rich and Mature** (British) | `7S3KNdLDL7aRgBVRQb1z` | Counter-voice for any second-speaker beat. |
| **Jonathan — Sophisticated, Calm Narrator** (British) | `4u5cJuSmHP9d6YRolsOu` | Alternative if you want the "Anthropic-blog-post-spoken-aloud" texture. |
| **Johnny Kid — Serious and Calm Narrator** (British) | `8JVbfL6oEdmuxKn5DK2C` | Bench. Excellent measured delivery. |

**Avoid:** Brian, Adam, Antoni, Rachel, Charlie, Daniel, Liam, Will, Ethan, Sam, Bella, Domi, Elli, Glinda, Mimi, Dorothy — all defaults, all saturated. James, Joseph, Jeremy, Michael, Arnold are fresher but still pull from the default-voice gravity well. The single most differentiating move is leaving the default catalog entirely.

## 2. Voice settings — register by numbers

ElevenLabs documentation and community-pro consensus (humanizeaudio.com narration review, webfuse.com cheat sheet) converges on these settings by register:

- **Documentary authority (Brokaw / Krulwich / Anthropic-blog-aloud):** stability 0.60-0.75, similarity 0.75, style 0.00-0.10. Higher stability removes the small dramatic emphases that read as "performance"; low style keeps it from sounding like a voice actor "doing" a documentary. This is the Harrison Gale primary setting.
- **Hurried field reporter / phone-line stringer:** stability 0.40-0.45, similarity 0.80, style 0.40-0.55. The lower stability is what produces the slightly-uneven cadence that reads as "speaking quickly into a handset." This is the Patrick International setting if you keep the field beat.
- **Introspective developer monologue (first-person, the new option):** stability 0.50-0.55, similarity 0.70, style 0.05-0.15. Lower similarity here lets the prosody breathe; you want the "thinking aloud" cadence where a sentence can shift mid-clause. This is the *new* register for the Opus-4.7 monologue moment.
- **Wry technical commentator:** stability 0.55, similarity 0.75, style 0.20-0.30. Style boost gives the dry-humor lift on the back half of a clause.

Use **Multilingual v2** as the model_id for narrator beats (better prosody, slightly slower). Keep **Turbo v2.5** only for the live-Opus-monologue beat where speed matters and prosody doesn't have to be perfect. The current `eleven_turbo_v2_5` choice in `automation/elevenlabs_vo.py` should change to `eleven_multilingual_v2` for everything except the live beat.

## 3. Single voice vs. duo vs. ensemble

The current Brian + Charlie duo is broadcast-news pastiche. Wrong frame for Anthropic. Anthropic's house tone (read any anthropic.com/research post or the Building Effective Agents essay) is **engineering-blog calm**: first person, specific. No anchor + correspondent. No "back to you, Brian."

**Recommendation: single voice + one cameo.** Harrison Gale narrates everything in first person ("Five days ago, the pipeline was a hosted API. Now it is a B300 pod under my desk."). Patrick International cameos only if a different acoustic delivers information the primary can't.

A 3-voice ensemble telegraphs "I built a podcast" rather than "I built a 911 system." Anthropic judges grade for technical depth + creative voice; the podcast frame works against both.

## 4. Dialogue craft — what wins

Patterns extracted from AIFF 2025 winners (*Total Pixel Space*, *JAILBIRD*, *ONE*, *Distance Between Two Points Of Me*) and AIFF 2024 documentary-style finalists:

- **Short declaratives interleaved with one long sentence per beat.** Not all-short (too staccato, reads as ad copy). Not all-long (loses tension). The pattern: 4-6 short, then one 18-22 word clause that lands the technical claim.
- **First person specific, never first person plural-rhetorical.** "I rebuilt vLLM with native sm_103" lands. "We rebuilt vLLM with native sm_103" reads corporate. "One developer rebuilt..." (current script) reads news-pastiche.
- **Numbers in numerals when read; numbers spelled out when written.** The current script spells "ninety-one percent" and "sixteen-fifty-five" — correct for ElevenLabs (it pronounces digits clumsily). Keep this.
- **No metaphor in technical clauses.** "Latency of a well-rested human" is the kind of line that sounds clever in a writers' room and reads as forced to engineers. Cut or replace with the literal: "44 ms — faster than the 80 ms you can perceive."
- **Name the failure modes explicitly, in order, with the time cost.** This is the Anthropic blog-post move: "Three things broke. macOS shipped no `timeout` binary, which silently broke a session-start hook for two days. An environment file with unquoted multi-line JSON took down a shell. One performance claim about a CUDA toolchain mismatch was retracted under pressure." This is the strongest beat in the current script. Keep it verbatim.

**Words and phrases that hurt with this audience:** "revolutionary," "game-changing," "unleashed," "AI-powered" (used as adjective), "blazing-fast," "next-generation," "redefines," "pioneering," "harnesses the power of," "10x," "magic," "secret sauce." Also avoid "leverage" as a verb. The current script is clean of these — preserve that discipline.

**Words that signal Anthropic-house-tone:** "measured," "specific," "the path that worked," "what broke," "p95," "we re-baselined," "one developer," "the path is one path." Use sparingly.

## 5. The Opus-4.7-as-medium angle (the prize bet)

For "Most Creative Opus 4.7 Exploration," the strongest move is a 6-8 second moment where **Opus 4.7 itself narrates one engineering decision in first person**, generated live during the demo render and piped through ElevenLabs. Concretely:

1. Send Opus 4.7 a prompt like: *"You are Opus 4.7. In ~25 words, first person, dry register, explain to a fellow engineer why NVFP4 was the right format choice for Nemotron-Nano-3 on B300. Cite the specific tensor-core utilization number. No marketing language."*
2. Take the output text and render it through ElevenLabs (Harrison Gale, stability 0.50, style 0.10 — the introspective-developer setting from §2).
3. Insert it at the climax (after the 44 ms reveal, before the closer) with a lower-third caption: "Voice: ElevenLabs. Words: Opus 4.7, generated 2026-04-26, unedited."

This makes the model the *narrator of its own engineering choice* rather than the subject of a documentary about it. Sound design move: 1.5 seconds of silence before the line, which signals the register shift.

**Technical paths considered:**
- **Anthropic Voice mode (Claude Code `/voice`):** rolled out March 2026, ~5% access, uses ElevenLabs under the hood anyway. Not worth requesting access in 24h.
- **Standard Messages API + ElevenLabs:** shippable in <2h. The path. The "unedited" caption is what makes this honest — the words really are Opus's.
- **Voice cloning of Claude's official voice:** there isn't a public canonical Claude voice to clone, and cloning Anthropic's brand voice is a posture problem. Skip.

## 6. Field-stringer review — cut it

The Charlie field-stringer beat is the most over-used dynamic in AI-demo videos as of April 2026. Reads as parody-news pastiche, conflicts with Anthropic-blog tone, adds zero technical information.

**Cut Segment 2 entirely.** Re-allocate the 9 seconds to: (a) the Opus-4.7 monologue (§5), (b) two extra seconds of silence around the 44 ms reveal, (c) one extra shot of actual `nvidia-smi` output. If a second voice is kept for variety, use **Patrick International** for one non-comic beat — no phone-line treatment, no "back to you" button. That button is the worst line in the current script.

## 7. Sound design

- **Music bed:** drop the 95-105 BPM newsroom underscore entirely. That genre cue *is* the parody-news frame. Replace with a single sustained drone (CC0 — try Free Music Archive / freemusicarchive.org's ambient/drone collection or freesound.org tagged `drone cc0`). 40-60 Hz fundamental, no rhythmic content. Sits at -22 dB under VO; -28 dB under silence beats.
- **Ambient layers:** server-room hum at -32 dB throughout (cooling fan + GPU coil whine — record from a real B300 if accessible, otherwise CC0 from freesound.org). Distant siren at -38 dB only during the cold open. *No dispatcher chatter* — too easily reads as fake/synthesized; tip-toes onto regulated-content territory.
- **The 44 ms reveal lands in silence.** Drone ducks to -50 dB (effectively gone) at the cut to "44 ms." Hold silence for 1.0 s on either side of the number. No sting. No stutter cut. Silence is the most under-used effect in AI demos and the highest-confidence move with Anthropic engineers.
- **Stutter-cut moment:** save it for the failure-mode list ("three things broke"). Quick 80 ms hard cut between each failure, hard L-cut audio. This is where the rhythmic energy goes.
- **End card:** single sustained mid-low piano note (around C2, 8 seconds, decaying), then full silence into the 4-second hold of the end card. No stinger.

## 8. Concrete recommendation

**Re-render the entire VO at ~13.9k chars (well under the 1.5M budget).** Specifically:

- Primary narrator: **Harrison Gale** (`fCxG8OHm4STbIsWe4aT9`), `eleven_multilingual_v2`, stability 0.62, similarity 0.75, style 0.08, speaker boost on.
- Opus-4.7 monologue beat (new): **Harrison Gale**, `eleven_multilingual_v2`, stability 0.52, similarity 0.72, style 0.12 (the introspective register).
- Optional second voice (if a non-stringer beat is kept): **Patrick International** (`9Ft9sm9dzvprPILZmLJl`), `eleven_multilingual_v2`, stability 0.50, similarity 0.78, style 0.20.
- Cut Charlie entirely. Cut the "back to you, Brian" button. Cut the field-stringer Segment 2.

Update `automation/elevenlabs_vo.py`:
- Replace `VOICE_IDS` entries.
- Switch `MODEL_ID` to `eleven_multilingual_v2` for narrator lines.
- Add a third speaker key `opus_self` mapped to Harrison Gale with the introspective settings.
- Add a script line for the Opus-4.7 monologue (text generated at render time from `claude-opus-4-7` via Messages API).

## 9. Voice Direction Card (paste into render script)

```
# VOICE DIRECTION CARD — prism42 hackathon cut, 2026-04-25
# Primary: Harrison Gale fCxG8OHm4STbIsWe4aT9 / multilingual_v2 / stab 0.62 sim 0.75 style 0.08 / first-person developer-doc register / no broadcast cadence
# Opus-Self beat: Harrison Gale / stab 0.52 sim 0.72 style 0.12 / words generated live from claude-opus-4-7, lower-third caption "Voice: ElevenLabs. Words: Opus 4.7, unedited."
# Second voice (optional, non-stringer): Patrick International 9Ft9sm9dzvprPILZmLJl / stab 0.50 sim 0.78 style 0.20 / one beat only, no "back to you" button
# Forbidden: Brian, Adam, Antoni, Charlie, Rachel; "revolutionary", "game-changing", "AI-powered", "unleashed", "blazing-fast", "10x", "magic", "back to you"
# Sound bed: CC0 sustained drone -22dB, ducks to -50dB on 44ms reveal (1.0s silence each side), server-hum -32dB throughout, no rhythmic music, no dispatcher chatter
```

---

## Sources

- [ElevenLabs Documentary Narrator Voices](https://elevenlabs.io/voice-library/documentary-narrator-voices)
- [ElevenLabs Narrator Voices](https://elevenlabs.io/voice-library/narrator-voices)
- [ElevenLabs Default Voices doc](https://elevenlabs.io/docs/product/voices/default-voices)
- [ElevenLabs Voice Settings reference](https://elevenlabs.io/docs/api-reference/voices/settings/get)
- [ElevenLabs Cheat Sheet 2026 — webfuse.com](https://www.webfuse.com/elevenlabs-cheat-sheet)
- [Brian voice profile, json2video](https://json2video.com/ai-voices/elevenlabs/voices/nPczCjzI2devNBz1zQrb/)
- [HumanizeAudio narration quality review](https://blog.humanizeaudio.com/elevenlabs-narration-quality-review/)
- [Nerdynav ElevenLabs Review 2026](https://nerdynav.com/elevenlabs-review/)
- [Anthropic — Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- [Anthropic — Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Runway AI Film Festival winners](https://aif.runwayml.com/)
- [TechCrunch — Claude Code voice mode rollout](https://techcrunch.com/2026/03/03/claude-code-rolls-out-a-voice-mode-capability/)
- [The Decoder — Anthropic uses ElevenLabs for speech](https://the-decoder.com/anthropics-claude-uses-elevenlabs-technology-for-speech-features-rather-than-an-in-house-model/)
- [Free Music Archive — Ambient genre (CC0)](https://freemusicarchive.org/genre/Ambient/)
