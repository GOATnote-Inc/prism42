# GOATNET NEWS — Runway AIFF 2026 Prompt Cards

3-minute satirical AI-news broadcast. 25 shots across 6 segments. Two locked characters (`@ken`, `@fizzlepuff`) plus B-roll inserts.

## Global production notes (apply to every shot)

- 16:9 aspect, 24fps cinematic.
- Character shots paste the `@ken` or `@fizzlepuff` token into Scene Builder / Act-Two with the Characters slot already populated.
- One camera move per shot. Locked-off is the default.
- Every cat shot gets a satellite-glitch overlay + `LIVE — PUPPET BUREAU` chyron in DaVinci. The Runway gen does not render the overlay.
- Never let a real vendor name appear on screen — black-bar redact in prompt and verify on review.
- Cut-down lengths in DaVinci; gen at 5s default, 10s only when motion needs to breathe (flagged per shot).

---

## Segment 1 — Cold Open (0:00–0:20)

### S01 — Bumper graphic (0:00–0:03, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Establishing shot of a glossy cable-news bumper graphic spinning into frame, neon red and chrome network ident reading 'GOATNET NEWS', dark studio backdrop with volumetric haze, slow push-in, broadcast lens deep focus, 24fps cinematic
**Drift modes:** Text rendering jitter on 'GOATNET'. Mitigation: accept as broadcast-grain texture; if illegible, comp the wordmark in DaVinci.
**Acceptance:** Logo legible for at least 1.5s, chrome flare hits on cut frame.

### S02 — Fox at desk, papers (0:03–0:08, gen 5s)
**Tool:** Scene Builder
**Refs:** `@ken`
**Prompt:**
> Locked-off medium shot of @ken at the news desk shuffling a stack of papers, photoreal anthropomorphic red fox in pinstripe suit and orange tie, broadcast studio with monitors glowing behind, warm tungsten key light with softbox fill, broadcast lens deep focus, 24fps cinematic
**Drift modes:** Fur tone shifts grey, tie pinks. Mitigation: re-prompt 'rust-orange fur, vivid orange tie'.
**Acceptance:** Pinstripe visible, orange tie reads, suit cut matches reference.

### S03 — Teaser montage (0:08–0:14, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none (b-roll)
**Prompt:**
> Multi-shot teaser montage: redacted manila folder with black blur boxes, then GPU die macro with iridescent sheen, then a whiteboard scribbled with attention-math equations, then a glowing server rack at night, fast whip-pan transitions, high-contrast broadcast graphics, 35mm anamorphic shallow depth of field, 24fps
**Drift modes:** Vendor name leaks past redaction. Mitigation: regen with explicit 'black bar redaction over all visible text'.
**Acceptance:** Four readable beats in 6 seconds, no legible vendor strings anywhere.

### S04 — Fox teaser line (0:14–0:20, gen 5s) **[Act-Two #1]**
**Tool:** Act-Two
**Refs:** `@ken` + 4-second voice take
**Prompt:**
> Close-up of @ken delivering the cold-open teaser line direct to camera, photoreal anthropomorphic red fox, slight knowing smirk, broadcast studio bokeh behind, warm tungsten key, slow push-in, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Tie color, mouth shape distortion at sibilants. Mitigation: 2 takes minimum.
**Acceptance:** Lip-sync within 1 frame of voice track, smirk reads at cut.

---

## Segment 2 — Compliance Desk (0:20–0:50)

### S05 — Fox introduces audit (0:20–0:26, gen 5s)
**Tool:** Scene Builder
**Refs:** `@ken`
**Prompt:**
> Medium shot of @ken at the news desk gesturing toward a side monitor that shows a redacted document with black censor bars, broadcast studio, warm tungsten key, broadcast lens deep focus, 24fps cinematic
**Drift modes:** Side-monitor content reads as garbled text. Mitigation: accept silhouette; comp clean redacted page in DaVinci if needed.
**Acceptance:** Gesture lands toward monitor, monitor shows redaction silhouette.

### S06 — Redacted folders insert (0:26–0:31, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Macro insert of three manila filing folders fanned on a desk, each labeled with black redaction bars over the title, a stamp reading 'AUDITED' in red ink hitting the top folder, rack-focus from foreground stamp to background folders, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Vendor name leak under bars. Mitigation: regen with 'all text fully blacked out, only AUDITED stamp legible'.
**Acceptance:** AUDITED stamp legible, no other text legible.

### S07 — Cat first appearance (0:31–0:38, gen 10s) **[FIRST CAT]**
**Tool:** Scene Builder
**Refs:** `@fizzlepuff`
**Prompt:**
> Locked-off medium shot of @fizzlepuff standing in a cluttered field bureau, stop-motion felted-puppet aesthetic, pink tie and oversized round glasses, dark suit, holding a redacted folder up to camera, neon magenta backlight with warm tungsten fill, faint scanline overlay, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** HIGH — model defaults to photoreal cat. Mitigation: explicit 'felted wool puppet, visible stitch seams, Wes Anderson stop-motion'. 3 takes minimum.
**Acceptance:** Felt texture clearly visible, glasses round and oversized, satellite-glitch comp lands cleanly in post.

### S08 — Cat reads disclosure (0:38–0:45, gen 10s) **[Act-Two #2]**
**Tool:** Act-Two
**Refs:** `@fizzlepuff` + 6-second voice take
**Prompt:**
> Close-up of @fizzlepuff speaking nervously into a chunky retro microphone, stop-motion felted-puppet cat, oversized round glasses catching neon magenta backlight, pink tie slightly crooked, filing cabinets blurred behind, warm fill, slow push-in, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** Act-Two smooths to 24fps real motion, killing the puppet feel. Mitigation: post-production frame-decimation pass to fake stop-motion judder; accept smooth gen.
**Acceptance:** Lip-sync clean, judder reads after post pass.

### S09 — Filing cabinets b-roll (0:45–0:50, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Slow tilt-up across a row of beige filing cabinets, drawers slightly ajar with redacted folders spilling out, dust motes floating in shafts of warm tungsten, faint terminal-green glow from a CRT in the background, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Minimal. Mitigation: none required.
**Acceptance:** Tilt covers cabinet height, dust motes visible.

---

## Segment 3 — Kernel Lab (0:50–1:20)

### S10 — Cat in helmet at whiteboard (0:50–0:57, gen 10s)
**Tool:** Scene Builder
**Refs:** `@fizzlepuff`
**Prompt:**
> Medium shot of @fizzlepuff wearing an oversized yellow construction helmet, stop-motion felted-puppet cat with pink tie, standing in front of a cluttered whiteboard covered in attention-math equations and 'sm_103' stickers, high-key fluorescent lab lighting with neon magenta rim, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** Helmet defaults photoreal white hardhat, math becomes pure scribble. Mitigation: 'felted yellow construction helmet'; require 'sm_103' to read.
**Acceptance:** Helmet covers ears comically, 'sm_103' legible somewhere on whiteboard.

### S11 — GPU die macro (0:57–1:04, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Macro push-in on a Blackwell-class GPU die, iridescent silicon catching teal and magenta light, fine bond-wire detail, shallow rack focus traveling from heatspreader edge into the die surface, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Vendor logo printed on heatspreader. Mitigation: regen with 'unbranded heatspreader'.
**Acceptance:** Die surface fills frame at end of push, no vendor mark visible.

### S12 — Cat anxiety monologue (1:04–1:12, gen 10s) **[Act-Two #3 — HIGHEST RISK]**
**Tool:** Act-Two
**Refs:** `@fizzlepuff` + 7-second voice take
**Prompt:**
> Anxiety-spiral close-up of @fizzlepuff delivering an escalating monologue about attention backends, stop-motion felted-puppet cat, eyes widening behind oversized round glasses, pink tie askew, whiteboard equations blurred behind, neon magenta backlight, slow push-in, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** HIGHEST IN FILM — stop-motion fidelity must hold across longest dialogue gen. Mitigation: 3+ takes; if all fail, split monologue across two 5s gens cut on a whip-pan.
**Acceptance:** Felt texture intact at end of 7s cut, eyes widen at the climactic word.

### S13 — NVFP4 crash insert (1:12–1:17, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Locked-off insert of a CRT-style terminal screen, green-on-black text scrolling a Python stack trace ending in 'NVFP4 GEMM: CUDA error', screen flickers once, faint chromatic aberration at edges, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Model invents real vendor names in stack trace. Mitigation: regen with 'all module paths read goatnet/*'.
**Acceptance:** 'NVFP4 GEMM' and 'CUDA error' legible.

---

## Segment 4 — Hardware Hour (1:20–1:50)

### S14 — Fox holds rack prop (1:20–1:26, gen 5s)
**Tool:** Scene Builder
**Refs:** `@ken`
**Prompt:**
> Locked-off medium shot of @ken at the news desk holding up a small server-rack model like a prop, photoreal anthropomorphic red fox in pinstripe suit and orange tie, monitors behind glowing teal, warm tungsten key, broadcast lens deep focus, 24fps cinematic
**Drift modes:** Prop renders as toy car or random box. Mitigation: 'small black 1U server unit prop with teal LEDs'.
**Acceptance:** Rack-shaped prop in fox's paw, fox face still anchored to reference.

### S15 — Datacenter aisle (1:26–1:33, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Slow tilt-up across a row of glowing dark server racks in a dim datacenter aisle, teal status LEDs flickering, soft volumetric fog at floor level, ambient hum implied, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Vendor logos render on chassis. Mitigation: regen with 'unmarked black chassis'.
**Acceptance:** Aisle perspective reads, no vendor logos visible.

### S16 — Cat chews ethernet cable (1:33–1:40, gen 5s)
**Tool:** Scene Builder
**Refs:** `@fizzlepuff`
**Prompt:**
> Locked-off medium shot of @fizzlepuff casually chewing on a thick yellow ethernet cable like a noodle, stop-motion felted-puppet cat, eyes innocent behind oversized round glasses, pink tie slightly drool-stained, server-rack glow behind, neon magenta rim and warm fill, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** Cat goes photoreal, cable becomes literal noodle. Mitigation: 'yellow CAT6 ethernet cable, RJ45 connector visible'.
**Acceptance:** Felt texture holds, RJ45 connector readable, comedy beat lands.

### S17 — macOS timeout bug (1:40–1:46, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Macro push-in on a laptop terminal showing a bash prompt, the command 'timeout 30 ./run.sh' returning 'command not found', soft glow of OLED screen, dust motes in foreground bokeh, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Terminal text garbles. Mitigation: comp the terminal in DaVinci over a clean OLED-glow plate if needed.
**Acceptance:** 'command not found' legible on screen.

### S18 — Fox transition line (1:46–1:50, gen 5s) **[Act-Two #4]**
**Tool:** Act-Two
**Refs:** `@ken` + 3-second voice take
**Prompt:**
> Locked-off close-up of @ken delivering a deadpan transition line, photoreal anthropomorphic red fox, single eyebrow lift, monitors glowing teal behind, warm tungsten key, broadcast lens deep focus, 24fps cinematic
**Drift modes:** Eyebrow gesture overplayed. Mitigation: voice direction — keep delivery dry, single eyebrow only.
**Acceptance:** Subtle eyebrow lift on punchline beat.

---

## Segment 5 — Engineering Breaking News (1:50–2:30)

### S19 — Big number reveal (1:50–1:57, gen 5s) **[HERO GRAPHIC]**
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Push-in on a giant broadcast graphic dominating the frame: '44ms' in massive white sans-serif against a deep red gradient, smaller subtitle '1655ms baseline' crossed out in white, 91.6% reduction badge in corner, broadcast motion-graphic polish, slow push-in, 24fps cinematic
**Drift modes:** Digit garbling — Runway will likely render '44ms' as '44m5' or similar. Mitigation: PRIMARY — comp the graphic in DaVinci over a clean red-gradient plate generated by Runway. Secondary — 5+ regen attempts.
**Acceptance:** '44ms', '1655ms', '91.6%' all exactly correct on screen.

### S20 — Fox composure break (1:57–2:05, gen 10s) **[Act-Two #5 — CLIMAX]**
**Tool:** Act-Two
**Refs:** `@ken` + 7-second voice take with quarter-second hesitation
**Prompt:**
> Slow push-in close-up of @ken briefly losing composure, photoreal anthropomorphic red fox, mouth opens slightly in disbelief, paw rises halfway to ear-piece, eyes flick off-camera then back, monitors flashing red behind, warm tungsten key with red practical bounce, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Fox face distorts at the disbelief moment, paw geometry breaks. Mitigation: 3 takes minimum, prefer take where eye-flick lands cleanly even if paw is imperfect.
**Acceptance:** Composure break reads as a beat (not a glitch), eye-flick visible, lip-sync intact.

### S21 — Cat confetti reaction (2:05–2:14, gen 10s)
**Tool:** Scene Builder
**Refs:** `@fizzlepuff`
**Prompt:**
> Locked-off medium shot of @fizzlepuff celebrating, stop-motion felted-puppet cat throwing tiny paper confetti into the air, pink tie flying, oversized round glasses askew, whiteboard with attention math behind, neon magenta backlight, warm fill, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** Confetti renders as snow/sparks. Mitigation: 'small felt scraps of paper confetti'.
**Acceptance:** Felt confetti reads as confetti, tie motion sells joy.

### S22 — .env JSON bug (2:14–2:22, gen 5s)
**Tool:** Multi-Shot Video
**Refs:** none
**Prompt:**
> Rack-focus from a coffee mug in foreground to a laptop screen showing a JSON parse error highlighted in red, terminal pane below with green success text scrolling 'all systems nominal', warm desk lamp glow, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Two motion ideas competing. Mitigation: keep prompt singular — one rack-focus.
**Acceptance:** Foreground mug → background screen rack reads cleanly, error text legible.

---

## Segment 6 — Closer (2:30–3:00)

### S23 — Fox sign-off (2:30–2:38, gen 10s) **[Act-Two #6]**
**Tool:** Act-Two
**Refs:** `@ken` + 7-second voice take
**Prompt:**
> Slow push-in medium shot of @ken delivering the sign-off direct to camera, photoreal anthropomorphic red fox in pinstripe suit and orange tie, studio lights dimming as the shot progresses, key tungsten softens to amber, monitors fade to black behind, 35mm anamorphic shallow depth of field, 24fps cinematic
**Drift modes:** Lighting holds steady, killing the emotional beat. Mitigation: dial dimming as a luminance keyframe in DaVinci.
**Acceptance:** Lighting darker at end than start (Runway or post), delivery lands sincere.

### S24 — Cat button wave (2:38–2:46, gen 5s)
**Tool:** Scene Builder
**Refs:** `@fizzlepuff`
**Prompt:**
> Locked-off medium shot of @fizzlepuff giving a small slow wave to camera, stop-motion felted-puppet cat, pink tie now neat, oversized round glasses catching one final magenta highlight, whiteboard fading to black behind, neon backlight cooling, 35mm anamorphic shallow depth of field, 24fps stop-motion cadence
**Drift modes:** Wave is too fast or too many cycles. Mitigation: trim to first 3 seconds in DaVinci, ramp speed if needed.
**Acceptance:** One slow wave, sweet tone.

### S25 — End card (2:46–3:00, gen 10s)
**Tool:** Image-to-Video
**Refs:** still card built in Affinity/Photoshop
**Prompt:**
> Locked-off end-card composition: dark studio backdrop, centered title card 'GOATNET NEWS — A 5-DAY HACKATHON BROADCAST', credit lines reading 'Made with Runway Gen-4.5 + Act-Two / Voice ElevenLabs Turbo / Edit DaVinci Resolve / Bugs found and fixed live', subtle film-grain overlay, slow 0.5x parallax on title, 24fps cinematic
**Drift modes:** Runway text rendering at this density is unreliable. Mitigation: build the still in Affinity/Photoshop, feed to Image-to-Video for grain + parallax animation only.
**Acceptance:** All credit lines legible (because they were typeset, not generated), gentle parallax reads.
