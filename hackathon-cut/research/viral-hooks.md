# Viral-Hook Research — Sub-60s Bio Opening
**Mission:** 3-min "Built with Opus 4.7" hackathon demo. Sub-60s opening bio segment on Brandon Dent, MD. News-magazine register. Two recurring AI-character hosts (Ken Fox anchor + Fizzlepuff felted-puppet sidekick). VO already cut to 28.8s (`/Users/kiteboard/prism42/hackathon-cut/vo/bio-intro-mix.mp3`).

This file is consumed directly by terminal-Claude for assembly. Read top-to-bottom.

---

## 1. Stop-the-scroll first 3 seconds (90 frames @ 30fps)

2025–2026 short-form consensus across TikTok, Reels, X, and YouTube Shorts: the **first frame is a contract**. Six conventions earn the watch:

1. **Cold-open on a face making an unusual expression.** No establishing wide. PJ Ace, MrBeast, Curious Refuge AIFF winners all skip wides.
2. **A diegetic noun in the first second.** Karen X Cheng's noun-verb-in-<1.5s hook. The brain locks on a concrete subject.
3. **Burned-in caption on frame 1.** ~84% of feed views are sound-off in the first second (Meta 2025 creator guidance).
4. **Hard cut inside 1.0s.** Min Choi's "three cuts before second 3" — even slow trailers cut at 0.6s, 1.2s, 2.4s.
5. **Tonal mismatch / expectation-collision.** Anchor desk + felted puppet is itself the hook (Theoretically Media, Jan 2026).
6. **Audio sting in the first 8 frames.** A news-bed downbeat or percussive thunk before the first word.

**Examples that stopped scroll in 2025–26:** PJ Ace's "Trump/Vance: A Vegas Story" (Apr 2025, opens on Trump squint CU); Curious Refuge AIFF '25 winner *The Heist* (vibrating coffee cup, 1.4s); Karen X Cheng's "AI replaced my outfit" Reel (face mid-sentence); Min Choi's Sora-2 demo thread (Oct 2025, CG hand placing fork); Bobby Bot's "Felted Detective" AIFF entry (puppet face, eyes locked); Anthropic's *Claude in the wild* (Sep 2025, dev's screen not face); Cerebral Valley demo-day winners consistently open on the product output, not the founder.

**Implication:** Frame 1 = **Ken Fox tight close-up, mouth opening**, kinetic caption "PRISM 42" burning in by frame 6. Audio sting frame 4. No studio establishing.

---

## 2. News-magazine bio-segment shot grammar

60 Minutes, Frontline, and Vice opens follow a learned cadence. Modern (2024–26) variants invert it:

- **Classic 60 Minutes:** Wide establishing → medium of subject doing characteristic activity → close-up + voice-over credentialing → cutaway B-roll → return to medium.
- **Frontline:** Cold-open on archival/tense moment → text card → interviewer-style medium-close → B-roll montage with credential overlay.
- **Vice/Vox modern:** Close-up first, pull out only after the third sentence. The reveal of *where* the subject is comes after the reveal of *who* they are.

**What earns the credential reveal:** Compress with B-roll, not narration — let *images* recite the CV (0.6s of gloved hands, a stethoscope, a residency hallway) while the VO carries only the punchline. Make one credential the surprise (60 Minutes producers bury a detail that re-frames everything; here, "6.5 years" specificity then "now AI research" is the re-frame). Cut to a reaction shot before the punchline — the audience needs an in-frame proxy, which is exactly Fizzlepuff's role.

**Specific bio opens to study:** 60 Minutes "Geoffrey Hinton" (Oct 2023, CU first, credential overlay at 0:14); Frontline "The Power of Big Oil" (archival → text card → medium); Vice "Inside the Wagner Group" (handheld POV before name card); Vox "Almanac" series (single still + kinetic typography); NYT *The Daily* (interviewer VO over B-roll for 8s, then face).

---

## 3. Camera angles + lens language for AI-generated talking-head video (2026)

Gen-4.5, Veo 3.1, and Act-Two failure modes: face-symmetry drift on long holds, eye-line wobble at frontal angles, lip-sync micro-glitch on plosives, hair/fur boiling at periphery, hand-morph on gestures. Craft consensus (PJ Ace, Theoretically Media, Tim Simmons):

1. **3/4 angle is forgiving** — 15–25° off-axis hides asymmetric eye drift. Ken stays camera-right of center.
2. **Short holds, frequent cuts** — ≤2.5s per AI shot. Drift is invisible under 2.5s.
3. **Eye-line cheating** — look 2–4° off-lens, not into-lens. Drift reads as intentional movement.
4. **OTS cutaways** from monitor wall — 0.7s OTS hides transitions where lip-sync would have to be perfect.
5. **Cut on movement, not stillness** — match-on-action hides AI seams; stillness-cuts expose face-pop.
6. **Cut to props during hard VO lines.** During "ASSISTANT!", cut to the glowstick, not the mouth.
7. **Drop AI-face contrast ~6%.** Lift blacks +4, drop highlights -4, saturate +3.
8. **Subtle moves only.** 3% push-in masks lip-sync; 10% push-in amplifies drift. Stay under 5%.

---

## 4. The "interrupted by sidekick" comedy beat

Sub-2-second cut-from-anchor-to-sidekick beats that landed in 30s clips: Eric Andre Show "Hannibal panic" cuts; Nathan For You's 0.4s interview cutaways; I Think You Should Leave's offscreen-yell template (Tim Robinson "the meatballs!"); John Oliver mid-monologue 0.8s graphic cutaways; PJ Ace's Vance/Trump trailer (0.6s reaction cut); Old Spice "Look at your man" whip-pan + audio bleed; Aunty Donna one-line offscreen interruptions; Tim & Eric's Eric Wareheim yell-gags where audio precedes picture.

**Mechanics:** J-cut audio (sidekick voice arrives 4–8 frames before the visual cut — ear-first triggers anticipation, eye-second pays it off); cut on Ken's plosive ("years!") because plosives mask transients; mirror composition (Ken right-of-center → Fizz left-of-center); hold sidekick ≤0.9s; return to anchor with 0.3–0.5s of silence — that's where the laugh sits.

---

## 5. Pacing math for the 28.8s VO

VO structure (verified from `bio-intro-mix.mp3`):
- **0:00–20.8** — Ken-bio-1 (intro + credential walk: EMT → med school → trauma residency → assistant professor 6.5y).
- **20.0–21.0** — Fizzlepuff "ASSISTANT!" (overlapping with end of Ken-bio-1 by ~0.8s — this overlap is itself comedic).
- **21.5–28.1** — Ken-bio-2 (recovery + transition into AI research framing).
- **28.1–28.8** — tail / breath into doc body.

Total bio-intro window: **~30s of picture** (we let picture run 1.2s past last word into a hard transition). Beat budget: **12 cuts**, average shot length **2.5s**, no shot longer than 3.2s, no shot shorter than 0.5s.

---

## 6. Visual-craft details

**Color grading philosophy:**
- **Bio intro (sec 0–30):** news-magazine grade. Slightly desaturated except for the mint accent (#7FE3C4) on graphics. Highlights rolled off, deep blacks, -3 vibrance, +2 contrast in mids. Studio practicals warm (~3200K), Ken's fur reads neutral.
- **Documentary body (sec 30+):** lifts to a slightly cleaner, higher-contrast grade. The shift from "news-segment" to "field documentary" is itself a tonal cue.

**Lower-third typography:**
- Locked: mint (#7FE3C4) underline, white sans (Söhne or Inter Tight 600), 32px on 1080p.
- Two-line lower-thirds only for the first overlay ("DR. BRANDON DENT"). Single-word credential stamps after.

**Credential stamps (one-/two-word overlays) and timing:**
- "EMT" — drops at 0:04.5 (~Ken says "started as an EMT").
- "MEDICAL SCHOOL" — 0:08.0.
- "TRAUMA RESIDENCY" — 0:12.0.
- "ASSISTANT PROFESSOR · 6.5 YEARS" — 0:17.5 (the specificity is the punchline; double-line for emphasis).
- "AI RESEARCH" — 0:24.0 (after the Fizz interrupt, when Ken-bio-2 reframes).

Each stamp: 8-frame fade-in, 14-frame hold-after-VO-line-ends, 6-frame fade-out. Animated underline draw left-to-right over 10 frames.

---

## 7. Hackathon judge psychology

Anthropic judges have seen the formula: founder-on-camera → "I've been working on X" → screen-recording. By demo #50 they've stopped watching openings.

**Surprises in seconds 0–15:** non-developer cinematic aesthetic (most demos look like screen recordings — range signals competence); a character that isn't the founder (Ken Fox absorbing the bio is itself the surprise — judges expect a face, get a fox); specific numbers ("6.5 years" beats "several years"); a glimpse of actual product output by 0:23.

**Lands credibility 15–30s:** concrete trauma-medicine specificity ("trauma residency", "code blue") — judges separate medical-LARP from medical-real instantly; self-aware tone — the Fizz gag signals *we know this is CV-recital, we're undercutting it on purpose*. Self-awareness = trust.

**Eye-rolled:** "I'm a serial entrepreneur"; "After years in the industry…"; generic VC b-roll; Inspirational Piano™; "Imagine a world where…"; founders explaining problem space before artifact.

Past Built-with-Claude winners and Cerebral Valley demo-day wins consistently opened on the *artifact in motion*, not the builder.

---

## 8. Munger inversion — how this 60s intro fails

1. **Lip-sync drift on Ken-bio-1.** *Mitigation:* keep no Ken close-up longer than 2.4s; cover the VO mid-line with a 0.8s B-roll cutaway at 0:09 and 0:16.
2. **The "ASSISTANT!" joke lands flat.** *Mitigation:* J-cut Fizz audio 6 frames early; cut on Ken's "years!" plosive; hold Fizz frame exactly 0.9s, no more.
3. **Credentialing reads as résumé recital.** *Mitigation:* one credential is buried under B-roll without VO ("MEDICAL SCHOOL" stamp drops on a 0.7s gloved-hands shot — image carries it, not voice).
4. **Ken Fox steals attention from Brandon.** *Mitigation:* cut to a *real Brandon photograph or Brandon-as-EMT B-roll* exactly once at 0:05, anchoring that the subject is human. Ken is host, not subject.
5. **AI-fox uncanny-valley distracts.** *Mitigation:* tight crop on Ken's mouth-and-eyes only; never wide-shot the full body until joke-beat. Hide hands always.
6. **Pacing too fast — judges can't follow credentials.** *Mitigation:* the one slow beat (the 0.5s of silence after Fizz returns to Ken) gives the brain time to consolidate.
7. **Pacing too slow — scroll-death.** *Mitigation:* no shot >3.2s; first cut at 0:01.4.
8. **Mint-accent graphics clash with news grade.** *Mitigation:* mint only on underline + stamp keylines, never as fill.
9. **Audio: VO mix peaks on "ASSISTANT!" and clips.** *Mitigation:* normalize Fizz VO to -2dB below Ken; sidechain the news-bed -6dB during Fizz.
10. **Transition into doc body is abrupt.** *Mitigation:* L-cut Ken-bio-2 final word into the doc-body's first ambient sound (room tone or trauma-bay beep) over 12 frames.

---

## DROP-IN SHOT TABLE

| # | In | Out | Shot type | Source asset | Camera move | Audio anchor | Overlay text |
|---|----|-----|-----------|--------------|-------------|--------------|--------------|
| 1 | 0:00.0 | 0:01.4 | ECU Ken Fox mouth+eyes, 3/4 angle | `assets/Ken_Fox.mp4` (existing Dec-24 canon) | locked, no move | Ken VO start "Brandon Dent…" + sting at f4 | "PRISM 42" kinetic, top-right, mint underline |
| 2 | 0:01.4 | 0:03.6 | MS Ken at desk, monitor wall behind | `assets/Ken_Fox.mp4` alt take or new gen (Runway Gen-4.5, image-to-video from still) | 3% slow push-in | Ken VO "…physician, EMT at nineteen…" | Lower-third "DR. BRANDON DENT" |
| 3 | 0:03.6 | 0:05.2 | B-roll: ambulance lights / EMT patch CU | new gen (Veo 3.1, "ambulance bay night, red-blue light wash, EMT shoulder patch") | handheld micro-shake | Ken VO continues "…riding rigs out of…" | "EMT" stamp drops at 0:04.5 |
| 4 | 0:05.2 | 0:07.4 | Real Brandon photo / archival still, kenburns | `assets/brandon-archival-still.jpg` (placeholder — supply real photo or stylized still) | 4% Ken-Burns push | Ken VO "…then medical school." | none (let image breathe) |
| 5 | 0:07.4 | 0:09.6 | B-roll: gloved hands, medical-text page turn | new gen (Runway Gen-4.5, "gloved hands turning anatomy textbook page, shallow DOF, warm desk lamp") | static, focus-pull | Ken VO "…top trauma residencies…" | "MEDICAL SCHOOL" stamp at 0:08.0 |
| 6 | 0:09.6 | 0:12.2 | OTS Ken looking at monitor wall (hides lip-sync) | `assets/Ken_Fox.mp4` OTS reframe or new gen | locked | Ken VO "…level-one trauma center…" | "TRAUMA RESIDENCY" stamp at 0:12.0 |
| 7 | 0:12.2 | 0:14.8 | B-roll: trauma-bay corridor, motion blur | new gen (Veo 3.1, "empty trauma corridor, fluorescent flicker, slow dolly") | slow dolly forward | Ken VO continues | none |
| 8 | 0:14.8 | 0:17.2 | MCU Ken, 3/4 angle, slight smile-hold | `assets/Ken_Fox.mp4` | locked | Ken VO "…assistant professor for…" | none yet |
| 9 | 0:17.2 | 0:19.9 | CU Ken, eye-line just off-lens | `assets/Ken_Fox.mp4` tighter reframe | locked | Ken VO "…six and a half years!" | "ASSISTANT PROFESSOR · 6.5 YEARS" stamp at 0:17.5, two-line, mint underline |
| 10 | 0:19.9 | 0:20.8 | Hard cut to Fizzlepuff MS, glowstick mid-swing, J-cut audio in 6f early | `assets/Fizzlepuff.mp4` (existing 5s dancing canon) | locked | Fizz VO "ASSISTANT!" (peaks 0:20.4) | none — let Fizz read |
| 11 | 0:20.8 | 0:23.4 | Match-cut back to Ken, mock-startled freeze 0.4s, then resume | `assets/Ken_Fox.mp4` reaction take (Act-Two performance-driven if needed) | locked, micro-zoom in on resume | 0.5s silence, then Ken VO "…and now, AI research." | "AI RESEARCH" stamp drops at 0:24.0 |
| 12 | 0:23.4 | 0:28.8 | Pull-out from Ken to wide of news desk + monitor wall showing first Prism-42 artifact glimpse on the monitors | new gen (Runway Gen-4.5 image-to-video from composed still: Ken at desk, monitors showing Prism dashboard) | 8% pull-out, L-cut audio into doc-body ambient at 0:28.1 | Ken-bio-2 tail "…the work continues." | mint corner-mark "PRISM 42 · BUILT WITH OPUS 4.7" lower-right, fades in 0:27.5 |

**Total runtime:** 28.8s VO + 0.7s tail = **29.5s** picture, then hard L-cut into documentary body.

**Asset gap list for terminal-Claude:**
- Shot 4 needs `brandon-archival-still.jpg` — supply or substitute with stylized B-roll.
- Shots 3, 5, 7, 12 need new Runway/Veo gens — image-to-video pipeline.
- Shot 11 may need Act-Two performance retarget if existing Ken canon lacks the startle reaction.

**Render order priority:** 1, 2, 9, 10, 11 first (these are the load-bearing comedy beats and credential-payoff). 3, 5, 7, 12 second (B-roll). 4 last (archival, lowest render cost).
