# PLAN — AIFF 2026 Submission

**Date written:** 2026-04-25 ~07:00 PT
**Submission deadline:** **2026-04-27 16:59:59 ET (verified)** — ~48h from write
**Anthropic hackathon deadline:** 2026-04-26 20:00 ET — ~37h from write
**Budget ceiling:** $350 (cook-authorized)
**Subject:** Brandon Dent, MD — solo dev of repo42 — identity-protected on screen
**Characters:** Ken (sharp fox anchor) + Fizzlepuff (felted cat hype-friend, modern slang)

---

## The reality (synthesized from 4 research agents)

### 1. Deadline contradicts brief

User-stated "May 18" appears nowhere in Runway materials. `aif.runwayml.com/submission` and `/terms` both say Apr 27 4:59:59 PM ET. **The 25-shot 3-min broadcast in `script.md` is not shippable in 48h on a solo dev that also has a hackathon to ship in 37h.**

### 2. Hackathon has primacy

Anthropic hackathon = revenue/research/recruitment value. AIFF = portfolio. If cycles bind, hackathon wins.

### 3. xAI video API verified working

The xAI API key grants access to `grok-imagine-video` (Aurora). Endpoint pattern via `xai-sdk` v1.11.0: `client.video.generate(prompt, model="grok-imagine-video", image_url=..., reference_image_urls=[...], aspect_ratio="16:9", resolution="720p", duration=...)`. Pricing **$0.07/sec at 720p** with native synced audio. 1080p not available until Imagine 2.0.

### 4. Routing intelligence (consolidated from Agents 2 + 4)

- xAI is BAD at stop-motion (drifts photoreal) → all Fizzlepuff shots go to Runway, NOT xAI
- xAI is good at photoreal atmospheric / hardware / locked-off Ken shots
- Runway is the only proven character-lock for our recurring characters
- Both fail at in-frame text → composite "44ms vs 1655ms" + chyrons in DaVinci
- Dec-2024 Gen-3 + Act-One assets are the GROUND TRUTH — new gens that look subtly worse than them ruin the cut

### 5. Munger red lines (top 5)

1. Wrong deadline → cut to 60-90s teaser using mostly existing assets (THIS IS US)
2. Hackathon-blocked → abandon AIFF this cycle
3. Vendor-identifiable in compliance segment → cut Segment 2 entirely
4. Brandon's identity leaked on screen → regen the offending frame
5. New gens look worse than Dec-2024 canon → stop generating, recut existing footage

---

## SCOPED PLAN — 60–90s "Field Report Teaser"

Reframe the 3-min broadcast as a **60-90 second field report teaser** that establishes character, lands the 44ms reveal, and ends. No compliance segment (red line C). No hardware deep-dive. No closer monologue. Just: cold open → hardware tease → 44ms reveal → button.

### Beats (4 segments, ~75s total)

| Time | Segment | Source | Cost |
|---|---|---|---|
| 0:00–0:15 | Cold open: GOATnote Nightly bumper + Ken at desk | Existing Dec-2024 Ken Act-One asset (recut) + composited bumper in DaVinci | $0 |
| 0:15–0:30 | Fizzlepuff field report from puppet bureau | Existing Dec-2024 Fizzlepuff Gen-3 asset (`seed=3282450978`, recut + new VO) | $0 |
| 0:30–0:55 | Hardware Hour B-roll: server racks, B300, kernel whiteboard | xAI Imagine T2V × 4 atmospheric shots, 6s each, 720p | ~$1.70 |
| 0:55–1:10 | The 44ms reveal: locked-off Ken + composited hero number | xAI Imagine I2V from Dec-2024 Ken keyframe + DaVinci motion graphic for "1655ms→44ms" | ~$0.50 |
| 1:10–1:20 | Button: Fizzlepuff one-line + end card | Existing Fizzlepuff asset + typeset still + xAI I2V slow zoom | ~$0.50 |

### New generations (xAI Imagine — ~$3 total compute)

**B-roll only — no character refs needed (which xAI handles weakly anyway):**
- B01: Macro push-in on Blackwell GPU die, iridescent silicon (S11 from shot-list)
- B02: Slow tilt-up across glowing dark server racks (S15)
- B03: Whiteboard close-up with attention math + "sm_103" stickers (S11 variant)
- B04: Red-gradient backdrop plate for the 44ms hero number (S19)
- B05: End-card slow zoom over typeset still (S25)

5 generations × ~6s × $0.07/s = **$2.10**.

### VO (ElevenLabs — ~$5)

Two voices, ~1100 words across the 75s of script-cut dialogue:
- KEN: ElevenLabs Brian (American narrator), stability 55, similarity 75, style 15
- FIZZLEPUFF: Charlie pitched +2, stability 35, similarity 80, style 60

Use existing `script.md` Segments 1 + 2 + 4 + 5 + 6 trimmed. Cut Segments 2 (compliance) + 3 (kernel deep-dive) entirely.

### Music + post (DaVinci Resolve free — $0)

- CC0 music bed: YouTube Audio Library "newsroom" feel, ducks under VO
- Lower-thirds + chyrons + 44ms hero number: Fusion comp, never trust gen text
- Color grade: Kodak 2383 LUT for cinematic-news look
- Master export: H.264 1080p 24fps (upscale xAI 720p output via Runway upscale or Topaz if needed)

### Total estimated spend

| Category | $ |
|---|---|
| xAI Imagine (5 gens) | ~$3 |
| ElevenLabs VO | ~$5 |
| Runway upscale (if needed) | ~$5 |
| Buffer for retries / regens | ~$30 |
| **Total** | **~$45** |

Well under $350 cook-authorization. The cheap path is the right path because it preserves the Dec-2024 canon.

---

## Timeline (next 48 hours)

| When | What | Owner |
|---|---|---|
| Sat 07:30 | Verify Dec-2024 assets accessible (download from Runway Recents) | User |
| Sat 08:00 | xAI smoke test (1 gen, ~$0.50) — confirm video endpoint works | terminal-Claude |
| Sat 08:30–10:30 | Generate 5 B-roll shots in parallel via xAI | terminal-Claude |
| Sat 10:30–14:00 | **HACKATHON FOCUS** — voice agent ship | User + voice-agent terminal |
| Sat 14:00–18:00 | More hackathon, leave AIFF idle | User |
| Sun 18:00–22:00 (Sat night → Sun) | Hackathon final ship by Sun 20:00 ET | User |
| Sun 22:00–Mon 02:00 | AIFF: VO render, DaVinci assembly, motion graphics, color grade | User + terminal-Claude |
| Mon 02:00–08:00 | Sleep | User |
| Mon 08:00–14:00 | Final cut, codec validation, test-upload to AIFF form | User |
| Mon 16:00 ET | Submit. Deadline 16:59 ET. | User |

The plan respects D-4/D-5: hackathon first, AIFF after, sleep non-negotiable.

---

## STOP / GO decision tree (your call)

**OPTION A — GO (small, cheap, this plan).** Ship a 60-90s teaser using mostly existing Dec-2024 assets + ~$45 in new gens + composite. Risk: AIFF judges may notice it's heavily reused footage. Upside: actually ships.

**OPTION B — ABANDON AIFF this cycle.** Push the full 3-min broadcast to a 2027 venue or the prism42 portfolio site. Reason: hackathon has primacy, 48h is genuinely too tight, the script as written is not 60-second material. Voice agent ships clean Apr 26.

**OPTION C — HYBRID GO.** Generate the 5 new B-roll shots + VO TODAY (Sat) so they're ready, but ONLY assemble + submit if hackathon ships clean by Sun 20:00 ET. If hackathon slips, abandon AIFF without sunk cost > ~$50.

**My recommendation: OPTION C.** Lowest opportunity cost; preserves both ship paths; ~$50 max sunk if AIFF gets cut.

---

## Acceptance criteria (red lines from Munger)

If any of these trip → STOP and reassess:
1. xAI smoke test fails (key tier-gated for video)
2. Hackathon voice agent slips past Sun 20:00 ET → cut AIFF
3. Vendor-identifiable footage discovered → cut Segment 2 (already cut in this scope)
4. Identity leak (Brandon's path/handle/photo) on any frame → regen
5. New gens noticeably worse than Dec-2024 canon → stop generating, recut existing
6. Spend ledger crosses $300 → halt, leaving $50 for upload retries

---

## Pre-flight TODOs (need user input or action)

1. **Confirm OPTION A / B / C above.** This is the load-bearing decision.
2. **Download Dec-2024 Ken + Fizzlepuff assets from Runway Recents** to `findings/runway-aiff/refs/` so terminal-Claude can use them for editing AND as ref images for the 1 Ken close-up via xAI I2V. Suggested set: 1 Ken Act-One talkie clip, 1 Ken still, 1 Fizzlepuff "dancing in a circle" clip (seed=3282450978), 1 Fizzlepuff still.
3. **Confirm music bed source preference** (YouTube Audio Library "Newsroom" vs Pixabay vs Suno-generated) — affects whether AIFF "all rights" requirement is satisfied without lawyer review.
