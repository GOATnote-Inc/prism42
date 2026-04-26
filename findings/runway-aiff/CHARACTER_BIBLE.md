# Character Bible — GOATnote Nightly

Single source of truth for character identity. Any prompt to any video tool
references THIS file's descriptions verbatim. Do not paraphrase per-shot —
inconsistency kills the video.

---

## KEN — Anchor

**Type:** Photoreal anthropomorphic red fox.
**Core identity tokens (must appear in every Ken prompt):**
> "anthropomorphic red fox, photoreal cinematic CGI, pinstripe charcoal-grey suit, white dress shirt, burnt-orange necktie, well-groomed russet fur, cream-coloured chest fur, intelligent amber eyes, refined posture"

**Setting tokens:**
> "GOATnote Nightly news desk, dark walnut surface, three monitors behind, warm tungsten key + soft fill, broadcast studio, 35mm anamorphic, shallow depth of field"

**Acting:** Tom Brokaw / Lester Holt energy. Composed. Plays it straight. Eyebrow does the work the voice refuses to. Composure breaks for exactly half a second on the 44ms reveal — that's the only crack.

**Voice (ElevenLabs):** Bill (deep newscaster) or Brian (American narrator). Stability 55, similarity 75, style 15. 60–70 wpm. No upspeak. Brokaw cadence — clauses land.

**Existing canon:** Runway Gen-3 Alpha + Act-One generations from Dec 2024 (filename pattern `talkie-recording-21873xxxxx.mp4`). Driving-video performance capture proven. ID-locked across multiple session.

**Reference image filename:** `automation/refs/ken.png` (canonical front 3/4) + optional `ken-side.png`, `ken-front.png`, `ken-3q.png`.

---

## FIZZLEPUFF — Remote Correspondent (Puppet Bureau)

**Type:** Stop-motion felted/knitted puppet cat.
**Core identity tokens (must appear in every Fizzlepuff prompt):**
> "stop-motion felted puppet cat, hand-knitted texture in russet and dusty-rose, oversized round black-frame glasses, slightly-too-large dark suit, hot-pink necktie, exaggerated eyebrows, occasional glowstick prop, Wes Anderson Fantastic Mr. Fox aesthetic, Laika studios fidelity"

**Setting tokens:**
> "Puppet Bureau remote feed, neon teal + magenta backlight, warm fill from camera-left, slight stop-motion handheld bob, satellite-feed scanline overlay, lower-third chyron 'LIVE — PUPPET BUREAU'"

**Acting:** Wacky. Anxious. Modern Gen-Z slang sprinkled into technical accuracy. Calls Ken "Brian" consistently — it's the running joke. Energy: hype-person of Brandon Dent's solo dev work, but the hype keeps short-circuiting into unprompted technical correctness. Believable Stage 3 caffeine.

**Slang vocabulary** (sprinkle, don't drown — 1–2 per segment):
- "no cap" · "lowkey" · "deadass" · "it's giving" · "based" · "fr fr" · "slay" ·
  "absolutely cooked" · "Brian, this is sending me" · "the math is mathing" ·
  "it's actually so over for hosted APIs" · "we are SO back"

**Voice (ElevenLabs):** Adam pitched +2 semitones, or Charlie at stability 35, similarity 80, style 60. 110–130 wpm with sharp accelerations on technical terms. Breath audible. Pitch ticks up half a step when a number is correct and he knows it. Run through mild AM-radio EQ + 3% packet-loss artifact for the satellite feed.

**Existing canon:** Runway Gen-3 Alpha image-to-video, seed `3282450978`, "dancing in a circle singing 'nothing is foreign' and waving glowsticks", 720p (1280x768), 5s. Multiple variants exist — we have the look locked.

**Reference image filename:** `automation/refs/fizzlepuff.png` (canonical front, glasses + glowstick) + optional `fizzlepuff-side.png`, `fizzlepuff-3q.png`, `fizzlepuff-helmet.png` (kernel-lab variant).

---

## BRANDON DENT, MD — The Subject (off-camera)

**On-screen presence:** **NONE.** Never shown. Never named on camera by Ken (legal/identity-protection bound). Lower-third graphics may show "Brandon Dent, MD · solo dev · repo42" exactly once in the closer. Otherwise referenced only as "the developer" / "the engineer" / "the dev" / "him."

**Fizzlepuff's framing:** hypes him as "the dev" / "repo42 chef" / "the solo guy" / "absolute lone wolf." Never says full name on air.

**Identity protection rationale:** real medical professional, real GOATnote founder, real prism42 author. The video is satire; he is not a public-character target.

---

## SETTING — GOATnote Nightly (fictional)

**Bumper:** "GOATnote Nightly" lower-third + sting. Network ident: dark studio backdrop, neon red + chrome ribbon spinning. NOT "GOATNET NEWS" — corrected to "GOATnote Nightly" matching the actual brand.

**Lower-thirds always say:** "GOATnote Nightly" not "BREAKING NEWS" generic.

**Color palette (locked across all shots):** charcoal + burnt-orange + neon teal + warm tungsten. Felted-puppet shots add hot-pink + magenta backlight. Maintain in DaVinci Kodak 2383 LUT pass.

---

## VENDORS UNNAMED

The compliance-audit beat references "a vendor we are legally encouraged not to name." That phrasing is verbatim in the script. **Never put a real vendor name on screen.** Folder labels in the redacted-folder visual: `VENDOR-█████`, `IP-█████`, `PROJECT-████`. Black redaction bars. Audio joke does the work.

---

## END CARD (S25)

> "GOATnote Nightly — built with Claude Code, Opus 4.7, agent teams, hooks, skills, and one cat."

Typeset still (terminal-Claude generates), 4-second hold, fade. The "one cat" lands as the punchline.
