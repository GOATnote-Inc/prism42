# Bio Intro — Ken Fox interviews Brandon Dent, MD

**Format:** News-magazine bio segment (60 Minutes / Frontline register).
**Runtime target:** 25–30 seconds.
**Slot:** Opens the demo. Replaces or precedes the existing v3 documentary cut.
**Visual base:** Existing Dec-2024 Runway Gen-3 + Act-One assets for Ken (anchor at desk) and Fizzlepuff (felted puppet dancing with glowstick). New VO via ElevenLabs.

---

## The shape

Ken narrates Brandon's bio with measured news-anchor authority. At the word "assistant" — which Ken is saying as part of "assistant professor" — Fizzlepuff (audible/visible from another room, dancing with glowstick) yells "ASSISTANT!" misinterpreting it as being summoned. Ken does not break, finishes the sentence. Cuts to documentary continuation.

The joke does the lifting: it establishes (a) Brandon's credentialed depth, (b) the show's house tone (deadpan + chaos), and (c) the running Ken–Fizzlepuff dynamic — all in 25 seconds.

---

## Dialogue

**KEN FOX** (V.O., over Ken at anchor desk):
> We are here with Brandon Dent, MD — contestant in Anthropic's Built with Opus 4.7 hackathon. He has worked emergency departments since starting as an EMT — through medical school, through residency at some of the country's largest and most reputable trauma centers. Then —

**[CUT TO FIZZLEPUFF — adjacent room, dancing with glowstick, neon backlight]**

**FIZZLEPUFF** (off-screen yell, then mouth movement caught on cut):
> ASSISTANT!

**[CUT BACK TO KEN — unbroken, level]**

**KEN FOX** (V.O., continues):
> — assistant professor for six and a half years. About a year ago, he set out to research AI.

**[Documentary continues into v3 master cut]**

---

## Voice direction

- **Ken Fox** — `Harrison Gale` (`fCxG8OHm4STbIsWe4aT9`, American documentary baritone). Stability 0.62, similarity 0.75, style 0.08. Model `eleven_multilingual_v2`. Brokaw cadence.
- **Fizzlepuff** — `Charlie` (`IKne3meq5aSn9XLyUdCD`, the existing canon voice for this character). Stability 0.30, similarity 0.80, style 0.70 — push style HIGH for this single-word yell so it lands as comedic interruption. Model `eleven_turbo_v2_5` (speed > prosody for a yell).

Why Charlie despite the voice-craft research saying "saturated": Fizzlepuff is a *character* with established Dec-2024 audio canon. One word ("ASSISTANT!") doesn't trigger the saturation problem. Continuity wins.

---

## Bio facts (verified per user brief)

- ED experience starting as EMT
- Medical school
- Residency at top-tier trauma centers
- Assistant professor — 6.5 years
- ~1 year ago set out to research AI
- Currently: contestant in Anthropic Built with Opus 4.7 hackathon, building prism42 (911 voice-dispatch agent)

---

## Production plan

1. Render `ken-bio-1.mp3` (Harrison Gale, segment 1, ~14s)
2. Render `fizz-assistant.mp3` (Charlie, ~1s yell)
3. Render `ken-bio-2.mp3` (Harrison Gale, segment 2, ~7s)
4. Locate existing Dec-2024 Ken at-desk video — use as visual base for Ken V.O.
5. Locate existing Dec-2024 Fizzlepuff dancing-with-glowstick video (seed=3282450978 per memory) — use as cutaway
6. Splice via ffmpeg:
   - 0:00–0:14 Ken visual + ken-bio-1 audio
   - 0:14–0:16 Fizzlepuff visual + fizz-assistant audio
   - 0:16–0:23 Ken visual + ken-bio-2 audio
7. Cut to documentary master at t=0:23 (or 0:25 with breath)

If Runway API access lands during production, optional upgrade: regenerate Ken's "talking" performance via Lip-Sync API with the new VO as driving audio. Lip-sync precision on news-magazine register isn't critical (V.O. convention).
