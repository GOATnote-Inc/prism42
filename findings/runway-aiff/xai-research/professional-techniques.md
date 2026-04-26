# Professional Techniques — Lifting xAI Grok Imagine + Veo 3.1 Output to AIFF Quality

**Author:** research-agent (Opus 4.7)
**Date:** 2026-04-25
**Project:** Prism42 / runway-aiff — 60–90s documentary-tone teaser, subject = engineering of a 911 voice-dispatch agent. Visuals = dispatch consoles, EMS responses, ambulances, police, fire, dispatcher closeups.
**Submission:** AIFF 2026, deadline 2026-04-27 16:59 ET (~52h). Solo dev. v1 already shot — looked generic/placeholder. v2 must look broadcast.
**Discipline mantra applied throughout:** scoped + tasked + tested + looped. Munger inversion ("how does this fail?") is §6.

---

## 0. The 30-second mental model

xAI Grok Imagine 1.0 (`grok-imagine-video`, $0.07/sec @ 720p, native synced audio, 7 reference image slots, 10s cap with refs, 6s cap text-only, 16:9 default) is a **fast cheap broad-coverage atmospheric workhorse**. Veo 3.1 is a **slow expensive director-suite scalpel** that responds to lens grammar and timestamp prompting. The professional move is not to pick one — it is to **route shot-by-shot**: Grok Imagine for atmospherics, vehicles, hardware, environment; Veo 3.1 reserved for the 1–3 hero shots whose composition needs lens precision (a 50mm dispatcher closeup that has to land emotionally). Then everything passes through **Topaz Video AI Proteus → DaVinci Resolve color → DAW for layered sound** before edit.

---

## 1. Prompt grammar pros actually use

Two converged formulas, both validated April 2026:

**Grok Imagine (5-part, validated by GenAIntel + YouMind-OpenLab + DuoChroma):**
`Scene + Style + Mood + Lighting + Camera`
Written as **flowing narrative**, not tag-stacked. Tag-stacking is the #1 reason a Grok clip looks "AI-y."

**Veo 3.1 (Google Cloud official, ltx.studio confirms):**
`Cinematography + Subject + Action + Context + Style/Ambiance`
Veo accepts and rewards explicit lens/aperture/focal-length tokens; Grok rewards atmospheric density over cinematographic precision. Both reward **one primary camera move per prompt** — chained moves degrade output.

### Lens language that works

- **Grok Imagine:** "35mm film look", "50mm lens feel", "85mm portrait look", "anamorphic lens flare", "shallow depth of field", "deep focus", "16:9 / 2.39:1 composition" — used as **atmosphere**, not measurement. Grok does not enforce f-stop literally; it interprets.
- **Veo 3.1:** "wide-angle lens", "macro lens", "shallow depth of field", "deep focus", and the Director's-Suite-style "f/1.4 aperture", "ISO 800 grain", explicit focal-length numbers all survive. Veo treats these as constraints.

### Lighting language that works

- **Practical-source language** ("monitor glow on face", "blue-and-red strobe pulses through windshield", "key light from desk lamp + fill from monitor + rim from open hallway") consistently outperforms abstract terms ("cinematic lighting", "dramatic"). Both models. Confirmed by truefan.ai 8-point grammar.
- **Time/quality words** that earn their keep: "soft dawn light with diffused mist", "harsh fluorescent overhead", "moonlight through rain-spattered window", "tungsten warm 3200K", "fluorescent cool 5600K". Avoid the word "cinematic" — it is a magnet for genericism.

### Camera-move verbs: survive vs. fail

| Survives (use) | Fails (avoid) |
|---|---|
| slow push-in / dolly in | "energetic camera" |
| static lock-off | "dynamic flowing motion" |
| handheld bob, subtle | "frenetic" / "chaotic" |
| slow pan left / pan right | mixed: "pan and zoom and tilt" |
| dolly out | "epic sweeping" |
| crane up, slow | "rotating around subject" (often morphs) |
| 30° arc | "drone-style 360" (almost always artifacts) |

Rule (DuoChroma + Veo 3.1 docs): **one move per shot.**

### 7 cited working examples (verbatim, attributed)

1. **GenAIntel — documentary register:** *"A weathered sailor grips a ship's wheel at twilight, salt spray clinging to his beard as waves crash against jagged cliffs, captured with photoreal detail and natural lighting, documentary feel, 16:9."*
2. **GenAIntel — workshop documentary:** *"Full-body portrait of a craftsman in workshop surrounded by handmade wooden furniture, natural light streaming through large industrial windows, dust particles visible in light beams, worn leather apron and rolled sleeves, authentic documentary photography style, 35mm focal length perspective."*
3. **GenAIntel — neon urban candid:** *"A young couple laughing at a crosswalk in Tokyo at dusk, neon signs reflecting on wet pavement, candid mid-step framing, Fujifilm film grain, 35mm perspective, natural ambient light."*
4. **SeaArt — film noir:** *"Dimly lit 1940s detective office, venetian blind shadows across desk, single overhead lamp, cigarette smoke atmosphere, black and white high contrast, heavy film grain, dramatic chiaroscuro lighting, 35mm anamorphic lens."*
5. **SeaArt — heroic low angle:** *"Low-angle cinematic shot of a hero standing on a rooftop overlooking the city, wind pushing a long coat dramatically, sun flares behind silhouette, high contrast, epic mood, 35mm film look."*
6. **Veo 3.1 official (Google Cloud):** *"Medium shot, a tired corporate worker, rubbing his temples in exhaustion, in front of a bulky 1980s computer in a cluttered office late at night. The scene is lit by the harsh fluorescent overhead lights and the green glow of the monochrome monitor. Retro aesthetic, shot as if on 1980s color film, slightly grainy."*
7. **PJ Ace 2x2 / truefan.ai 8-point shot grammar:** subject + emotion + optics + motion + lighting + style + audio + continuity. PJ Ace publicly works in pairs of cinematic options for A/B selection. (PJ runs Genre.ai; co-winner with Dave Clark of the Grok Super Bowl ad contest 2026.)

---

## 2. Multi-pass workflows

Pros chain **T2I → I2V → upscale → grade → sound** because each stage is cheaper to control than re-rolling video. The economic logic: a $0.50 Veo clip you reroll 10 times costs $5; a single $0.022 Grok still you accept, then animate once, costs $0.72.

**Recommended chain for v2:**
1. **T2I (still) in ChatGPT image-gen or Midjourney v7** — lock composition, lighting, color palette in a still where you can iterate at $0.02 a roll.
2. **I2V via Grok Imagine** with that still as `image_url` (first-frame lock) OR as one of 7 `reference_image_urls[]` (atmosphere lock without first-frame lock). Animate with motion-only prompt.
3. **Veo 3.1 fallback** for the 1–3 hero shots if Grok cannot land the lens behavior.
4. **Topaz Video AI Proteus** 720p → 1440p → 4K in two steps (per Topaz community: never single-jump).
5. **DaVinci Resolve** color + grain match across cuts.
6. **DAW** (Logic / Reaper) layering siren, dispatch chatter, room tone over Grok's native audio. Native audio is good for sync but often too clean — bury it under designed layers.

Single-pass (T2V direct) is acceptable only for **abstract atmospherics** (skyline, fog, wet asphalt) where composition tolerance is high. For anything with a human, multi-pass dominates.

**Aleph (V2V):** xAI does not yet expose Aleph publicly. Runway Aleph is the V2V tool of record but is not in our budget for this submission.

---

## 3. Reference image discipline (the 7-slot)

xAI confirms 1–7 `reference_image_urls[]` addressable as `@image1` … `@image7` in prompt, distinct from the `image` field which is first-frame lock.

**Rules learned (Basenor + DuoChroma):**
- **Order matters.** Slot 1 carries the most weight; slot 7 the least. Put the **identity-defining** image first (e.g., your locked color palette / lighting plate), supporting refs after.
- **Quality threshold.** Use only refs at ≥1024px short edge with consistent color temperature. A noisy ref poisons the run; the model is honest about what you give it.
- **Atmospheric lock pattern (use this for v2):** Generate ONE master "look plate" still in Midjourney — wet-asphalt blue/cyan emergency-services palette, your reference grain — and pass it as `@image1` in **every** dispatch/EMS shot. This gives the v2 reel the unified palette v1 lacked.
- **References hurt when:** (a) you stack 7 mismatched palettes, (b) one ref has burned-in text/borders/watermark — those bleed through, (c) you ref a face you want to animate to a different pose (use first-frame `image` field instead).
- **Workaround for character/face:** if you need a specific dispatcher across 3 shots, do not ref-7 it — use the **Copy Video Frame** technique (DuoChroma): pause the first clip at the desired frame, copy frame, paste as `image` (first-frame lock) for the next clip. Continuity through frame-handoff, not through reference weighting.

---

## 4. Documentary register — what makes it look real

Documentary AI B-roll fails when it looks "stock" or "AI-y." Five cues fix this:

1. **Imperfect framing.** Add "slight handheld bob", "subject not centered", "foreground occlusion (blurry shoulder, doorframe edge)". Observed > staged.
2. **Practical sources, named.** Not "lit dramatically" — "lit by monitor glow + ceiling fluorescent". Models render motivated light better than abstract light.
3. **Earned, not added, lens flares.** Mention "lens flare from off-screen strobe" only if the scene has a strobe. Adding flares to a sterile shot reads fake.
4. **Exposure variance.** Real broadcast doc footage has clipped highlights and lifted shadows. Add "slightly overexposed window" or "crushed shadow detail" — Grok will respect it.
5. **24fps + 16:9 + grain.** "Shot at 24fps, 16:9, subtle 35mm film grain" lands documentary register more than any "documentary style" tag (Magic Hour 10 Pillars).

Avoid: "cinematic", "epic", "dramatic", "stunning", "breathtaking" — magnet words for genericism, and what tipped v1 over the line.

---

## 5. Emergency-services subject conventions

Documentary 911/EMS/police/fire shooting has hard genre rules — both for AI fidelity and for legal/ethical safety.

**Avoid uncanny:**
- AI renders dispatcher faces poorly under monitor glow (eyes do not catch the cyan correctly). **Workaround:** back-of-head, over-shoulder, hands-only, screen-reflection-on-glasses, or silhouette.
- Hands on a headset, hand reaching for a console button, fingers tracing a screen — these are AI-friendly because hand-on-object hides the finger-count problem behind occlusion.
- Vehicle interiors (ambulance back, patrol-car cockpit) are AI-strong because the human is partial and the hardware reads.

**Uniforms / vehicle markings (legal):**
- **Never** use real city or agency names ("NYPD", "FDNY", "LAFD"). Risk: identification + implied endorsement.
- Use **generic block text only**: "EMS", "FIRE", "POLICE", "PARAMEDIC", "DISPATCH". Patches blank or geometric.
- Ambulance numbers: 3-digit fictional ("M-217", "R-04"). Star-of-Life symbol is generic and safe.
- License plates: blur in post or prompt "license plate not visible / motion-blurred".

**Composition rules (documentary EMS):**
- Wide establishing → medium working → tight detail (hands, screen, lights). Three-shot rhythm.
- Wet asphalt is the genre's signature. Always wet, always reflective.
- Strobe-blue + strobe-red on neutral midtones is the visual signature. Push the contrast in grade.
- Time of day: dawn (quiet/aftermath), night (active). Avoid bright daylight — reads PR-video, not doc.

---

## 6. Failure modes (Munger inversion: "how does this fail?")

What goes wrong in xAI emergency-service prompts:

1. **Moderation blocks "weapon" / "violence" / "blood".** Grok Imagine moderation tightened in March 2026 after the January 2026 sexual-imagery scandal (Tenorshare, AVCLabs, Conversation, Izoate). Predictive pre-moderation produces false positives. **Mitigation:** stick to **response/aftermath** vocabulary — "responding", "arriving", "staging", "dispatching" — never "shooting", "fighting", "armed", "victim", "wounded". A patrol car at a "scene" with strobes is fine; a patrol car "responding to an armed suspect" trips moderation.
2. **"Police" + uniform + face = elevated risk.** Police adjacent prompts are not blanket-blocked but are scrutinized when combined with action verbs. **Mitigation:** photograph the **car**, the **lights**, the **scene** — not the officer's face. "Police patrol car at night scene" passes; "police officer drawing weapon" does not.
3. **"911" as a number triggers terrorism filters intermittently.** Reported on r/grok early April 2026. **Mitigation:** say "emergency dispatch center", "PSAP", "dispatch console" — describe the place, not the number.
4. **Realism collapse on uniforms.** Patches morph, badges become smeared. **Mitigation:** keep uniforms generic, prompt "blank navy uniform with reflective stripe", never describe specific patches.
5. **Vehicle-marking realism failures (text rendering).** Grok still renders text poorly. **Mitigation:** prompt text as "minimal block lettering, partially obscured" or hide under motion blur / strobe wash.
6. **Strobe rendering goes hot.** Too-bright blue/red blowouts. **Mitigation:** prompt "soft strobe pulses, not overexposed, light bar partially out of frame".
7. **Faces drift between clips.** **Mitigation:** never feature the same dispatcher's face twice — vary the angle so face is never the subject.

Pre-emptive prompt mitigations (5 paste-in safety phrases):
- *"…not graphic, no injuries visible, professional response context…"*
- *"…uniforms generic, no agency names or real-world insignia…"*
- *"…vehicle markings minimal, fictional unit numbers, no real license plates…"*
- *"…aftermath / response / arrival on scene, calm professional procedure…"*
- *"…dispatcher seen from behind / hands and console only / silhouetted against monitor glow…"*

---

## 7. Concrete recipe set — 9 paste-ready prompts

Each is xAI-friendly: no in-frame text, one camera move, photoreal documentary register, moderation-safe vocabulary.

**Default API params for all:** `model=grok-imagine-video, aspect_ratio="16:9", resolution="720p", duration=6` (text-only) or `duration=10` (with image/refs). All start with `@image1` referencing the master-look plate (see §3).

**C01 — Wide 911 dispatch center, busy:**
> *"Wide establishing shot of a busy emergency dispatch center, rows of consoles with multiple curved monitors, blue and cyan screen glow on operators' faces seen from behind, headsets, hands gesturing toward maps on screens, ambient overhead fluorescent dimmed to 30%, slow push-in 35mm lens feel, shallow depth of field on the foreground console, documentary B-roll style, 24fps, subtle film grain, 16:9. Calm professional atmosphere, no agency names visible."*
> Duration 10s, retry 2x changing only "rows of consoles" → "horseshoe of consoles" if first roll generic.

**C02 — Close-up dispatcher headset on console:**
> *"Macro close-up of a black headset resting on a dispatch console, fingers entering frame from the right reaching for the mic boom, curved monitor in background showing a soft-focus map and call-detail panel, cyan monitor glow as primary key light, warm desk-lamp fill from left, 50mm lens feel, very shallow depth of field, static camera with the slightest handheld bob, documentary photography style, 24fps, 16:9. No readable text on screen."*
> 10s. Retry strategy: if the screen renders fake-looking text, add "screen content out of focus, illegible".

**C03 — Ambulance speeding through dark wet city:**
> *"Tracking shot of an ambulance speeding through a dark wet city street, light bar pulsing red and blue across rain-slicked asphalt and storefront glass, motion blur on streetlights, side-on parallel move, generic block lettering reading EMS on the side panel, fictional unit number M-217, 35mm anamorphic lens flare from the strobes, photoreal night, 24fps, 16:9. Aftermath response context, no other vehicles."*
> 10s. Retry: if strobes blow out, add "strobes soft, not overexposed".

**C04 — EMT prepping equipment in back of ambulance, no face:**
> *"Tight handheld shot inside the back of an ambulance, hands of a paramedic in blue gloves checking a monitor cable and an IV bag, fast confident movements, equipment racks lit by overhead LED strip, blue strobe wash bleeding through the rear window, face out of frame above the top edge, 35mm wide perspective, slight handheld bob, documentary B-roll, 24fps, 16:9. Calm professional procedure, no patient visible."*
> 10s.

**C05 — Police patrol car at night scene:**
> *"Low-angle shot of a parked police patrol car at a night scene, light bar pulsing blue and red across wet asphalt, generic block lettering POLICE on the door, fictional unit number 04, no officer visible, reflections shimmering in puddles, 35mm lens feel, static camera, photoreal documentary style, 24fps, 16:9. Quiet aftermath atmosphere, no graphic content."*
> 10s. Avoid: any officer-with-weapon language. The car IS the subject.

**C06 — Fire engine at scene, dramatic backlight:**
> *"Medium shot of a fire engine parked at a scene at night, dramatic backlight from off-screen scene lights, fine water spray drifting through the beam catching the strobe wash, generic block lettering FIRE on the side, fictional unit R-04, ladder folded, no firefighters in frame, slow dolly-in along the side of the truck, 50mm lens feel, photoreal, 24fps, 16:9. Professional response context, no flames visible."*
> 10s. "No flames visible" is a deliberate moderation hedge.

**C07 — Dispatcher speaking calmly into headset, response timer:**
> *"Over-the-shoulder shot of a dispatcher seen from behind speaking into a headset mic, curved monitor in front showing a softly-focused timer-style readout counting up, cyan and amber screen glow as the only key light, warm fill from a desk lamp, 50mm lens feel, very shallow depth of field on the back of the head, slight handheld bob, documentary photography style, 24fps, 16:9. Calm professional atmosphere."*
> 10s. Note: "softly-focused" hides the model's bad text rendering.

**C08 — City skyline at night, distant sirens reflecting:**
> *"Wide shot of a city skyline at night seen through a foggy rain-streaked high window, distant blue and red strobes pulsing softly from street level reflecting in the glass, low warm interior light from the foreground office out of focus, slow push-in 35mm lens feel, atmospheric haze, photoreal, 24fps, 16:9. Quiet contemplative atmosphere, no people in frame."*
> 6s text-only is fine here. Retry: if too generic, add "Pacific Northwest mid-rise architecture, mid-distance".

**C09 — Dispatch center at dawn, single console operator:**
> *"Wide shot of an emergency dispatch center at dawn, most consoles empty and dark, overhead fluorescents at low level, one operator at a single lit console seen from behind, soft cool dawn light bleeding through high windows mixing with cyan monitor glow, slow dolly-in, 35mm lens feel, deep focus, documentary B-roll, 24fps, subtle film grain, 16:9. Quiet aftermath atmosphere, end-of-shift mood."*
> 10s. The most cinematic of the nine — worth a Veo 3.1 escalation if Grok's first 2 rolls feel flat.

---

## 8. Post-production — lifting 720p to AIFF quality

**Topaz Video AI — Proteus model, two-step upscale:**
- Step 1: 720p → 1440p. Proteus Manual mode. Sharpen 5–15. Recover Details 25–35. Reduce Noise 10–20. Anti-alias 20. Dehalo 0–5. (Topaz Community v3.x guidance.)
- Step 2: 1440p → 4K. Same model. Lower Sharpen (5). Detail bias only.
- Frame rate: leave at 24fps. Do **not** upsample to 60fps for documentary register — it kills the film feel.
- Per-clip processing on RTX-class GPU: roughly 12–14 minutes per 30s of 720p→4K. Plan time.

**DaVinci Resolve color — emergency-services-documentary look:**
- Node 1: normalize Grok output (it tends slightly green). Push offset toward magenta a touch.
- Node 2: lift shadows +0.02, crush a touch in highlights to mimic broadcast-cam clipping.
- Node 3: hue-vs-sat curve — pull saturation in skin/yellow/green range, push saturation in blue and red ranges (the strobe colors). This is the genre's color signature.
- Node 4: subtle teal-shadow / orange-skin push for cohesion across clips, restrained (15–20% mix), not the Marvel-poster version.
- Add 35mm film grain overlay, ~6–8% opacity.
- LUT: any free "Cinematic Doc" LUT (FilterGrade has free cinematic packs) at 30–40% mix. Do not apply at 100%.

**Sound design over Grok's native audio:**
- Keep Grok native audio at -18dB as bed (provides sync and lip-flap consistency).
- Layer: dispatch chatter (low-mid radio band 300Hz–3kHz, lightly compressed) at -22dB.
- Layer: distant siren wash, panned, at -28dB.
- Layer: room tone (server hum, fluorescent buzz) at -32dB.
- Final mix in DAW, export -14 LUFS for festival delivery.

---

## 9. Cost optimization — $50 budget

**Math:**
- Grok Imagine 720p: $0.07/sec → 10s clip = $0.70.
- Veo 3.1 Fast: ~$0.40/sec at delivery quality → 8s clip ~$3.20.
- 9 shots × 2.5 average rolls/shot on Grok = 22 clips × $0.70 = **$15.40**.
- 2 hero shots escalated to Veo 3.1, 2 rolls each = 4 × $3.20 = **$12.80**.
- Reserve **~$22** for: extra T2I stills ($0.50), one safety reroll budget ($5), Topaz/Resolve free, DAW free.
- **Total projected: ~$30 of $50.** Comfortable margin.

**When to escalate Grok → Veo 3.1:**
- Grok cannot land lens behavior after 3 rolls (e.g., lens-precise medium portrait at f/1.4 with rack focus).
- The shot carries narrative weight and must look unmistakably broadcast.
- Native audio is **not** needed (Veo 3.1 native audio is weaker than Grok's; for atmospheric shots Grok wins).

**When to stay on Grok:**
- Atmospherics, environment, vehicles, hardware, hands-only inserts, anything where motion + native audio sync matters more than lens precision.
- All 6 of the 9 recipes above (C01–C06, C08) are Grok-native; C07 and C09 are escalation candidates.

Cost-per-quality verdict: Grok Imagine wins on $/second of usable broadcast footage by ~5×, **as long as you accept the routing discipline**. Veo 3.1 is a scalpel, not a workhorse.

---

## DROP-IN CHECKLIST — 10 items, run before every prompt submit

1. **One camera move only.** Strike all but one verb (push-in OR pan, never both).
2. **Practical light sources named.** Replace "dramatic lighting" with the specific source (monitor glow, strobe wash, desk lamp).
3. **No magnet words.** Strike "cinematic", "epic", "stunning", "breathtaking", "dramatic" unless lighting-qualified.
4. **Documentary register tokens present.** "24fps", "16:9", "subtle film grain", "documentary B-roll" or "documentary photography style".
5. **Moderation hedges in place.** No "weapon", "violence", "victim", "armed", "shooting", "blood". Substitute response/aftermath vocabulary.
6. **Generic markings only.** No real city/agency names. Block lettering EMS/FIRE/POLICE/DISPATCH. Fictional unit numbers.
7. **Face strategy declared.** For human shots: back-of-head, hands-only, silhouette, or screen-reflection. Never frontal closeup of a recurring character.
8. **Reference image discipline.** `@image1` = master look plate (palette/lighting). Refs ≥1024px. ≤4 refs for atmospheric lock; 7 only if all are palette-consistent.
9. **Duration matches content.** 10s for refs/I2V, 6s for text-only abstracts. Don't pay for filler.
10. **Retry budget written down.** Max 3 rolls per shot on Grok before escalating to Veo or restructuring the prompt. Track in the shot-list JSON. Halt if §6 moderation hits twice — rewrite, don't reroll.

---

## Sources

- xAI Grok Imagine API docs — https://docs.x.ai/developers/model-capabilities/video/generation
- xAI Grok Imagine API launch — https://x.ai/news/grok-imagine-api
- GenAIntel Grok Imagine prompting guide — https://www.genaintel.com/guides/how-to-prompt-grok-imagine
- GenAIntel Grok Imagine capabilities 2026 — https://www.genaintel.com/guides/grok-xai-video-generation-capabilities-2026
- Google Cloud — Ultimate prompting guide for Veo 3.1 — https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1
- LTX Studio — Veo 3.1 prompt guide — https://ltx.studio/blog/veo-prompt-guide
- DreamHost — Ultimate Veo 3.1 prompt guide — https://www.dreamhost.com/blog/veo-3-1-prompt-guide/
- Sider — Veo 3.1 cinematic control field guide — https://sider.ai/blog/ai-tools/best-prompt-techniques-for-veo-3_1-video-output-a-field-guide-to-cinematic-control
- Basenor — Grok Imagine 7-image multi-reference — https://www.basenor.com/blogs/news/grok-imagine-now-lets-you-build-videos-from-7-images
- Basenor — Grok multi-image to video walkthrough — https://www.basenor.com/blogs/news/grok-multi-image-to-video-how-to-use-it-right-now
- DuoChroma — Grok Imagine character consistency tutorial — https://duochroma.com/grok-imagine-tutorial-extending-videos-maintaining-character-consistency/
- WaveSpeedAI — Grok Imagine reference-to-video — https://wavespeed.ai/blog/posts/introducing-x-ai-grok-imagine-video-reference-to-video-on-wavespeedai/
- SeaArt — 45 Grok Imagine trending prompts — https://www.seaart.ai/blog/grok-imagine-prompts
- YouMind-OpenLab awesome-grok-imagine-prompts — https://github.com/YouMind-OpenLab/awesome-grok-imagine-prompts
- Picsart Grok Imagine prompts how-to — https://picsart.com/blog/grok-imagine-prompts/
- Truefan.ai 2026 cinematic AI prompt playbook (8-point grammar) — https://www.truefan.ai/blogs/cinematic-ai-video-prompts-2026
- Magic Hour 10-pillar realistic prompting — https://magichour.ai/blog/realistic-ai-video-prompting
- Curious Refuge AI filmmaking course / 2026 best generators — https://curiousrefuge.com/blog/best-ai-video-generators-for-2026
- PJ Ace newsletter (Genre.ai) — https://pjace.beehiiv.com/
- Tenorshare PixPretty — Grok content moderated fix 2026 — https://pixpretty.tenorshare.ai/reviews/grok-content-moderated-try-a-different-idea.html
- AVCLabs — Grok image moderated 2026 — https://www.avclabs.com/social-media/grok-image-is-moderated.html
- Izoate — Grok moderation controversy 2026 — https://www.izoate.com/blog/grok-failed-to-moderate-content-elon-musks-grok-controversy-explained-2026/
- The Conversation — Grok sexualised images AI reckoning — https://theconversation.com/the-furore-over-groks-sexualised-images-has-begun-an-ai-reckoning-275448
- Topaz Video AI — Enhancement filters docs — https://docs.topazlabs.com/video-ai/filters/enhancement
- Topaz Video AI — Upscale 1080→4K guide — https://docs.topazlabs.com/video-ai/how-to-guide/upscale-1080-to-4k
- Topaz Community — Proteus v3.x upscale detail thread — https://community.topazlabs.com/t/upscaling-with-better-detail-using-proteus-in-tvai-v3-x/38738
- Aiarty — Topaz Video AI step-by-step settings — https://www.aiarty.com/ai-video-enhancer/how-to-use-topaz-video-ai.htm
- LearnDocumentary — cinematic lighting for doc filmmakers — https://www.learndocumentary.com/blog/mastering-cinematic-lighting-a-comprehensive-guide-for-documentary-filmmakers
- Xybix — 4 essential types of 911 dispatch center lighting — https://blog.xybix.com/4-types-of-lighting-in-a-911-dispatch-center
- Garage Productions — Directing AI like a DP 2026 — https://www.garageproductions.in/directing-ai-like-a-dp-creative-techniques-to-make-ai-generated-visuals-feel-cinematic-in-2026
- AIFF 2026 (Runway) — https://aif.runwayml.com/
- AI International Film Festival winners — https://aifilmfest.org/winners
- Replicate — xai/grok-imagine-video — https://replicate.com/xai/grok-imagine-video
- fal.ai — Grok Imagine — https://fal.ai/grok-imagine
