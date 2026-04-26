# Chrome-Claude Playbook — Runway Gen-4.5 Production Run

**Audience:** Claude for Chrome (Opus 4.7 sidebar) operating on `app.runwayml.com`.
**Authored by:** terminal-Claude (Opus 4.7) on 2026-04-25.
**Project:** AIFF 2026 submission — 3-min satirical news broadcast.
**Sister files (read these for context):**
- `script.md` — full dialogue, voice direction, music plan
- `shot-list.json` — 25 shots, JSON-valid, all metadata
- `prompts.md` — 25 paste-ready Runway prompt cards organized by segment

---

## How to use this playbook

You (Chrome's Claude) cannot read the sister files unless the user pastes them in. Operate in **phases**. The user pastes the relevant section at the start of each phase. Keep `Ask before acting` ON for Phases 1 and 3 (file uploads, sustained dialogue gens). The user may turn it off for Phase 2 (batch B-roll queue) once they've watched 3 shots succeed.

After every phase, output a **status block** in this exact format:

```
PHASE <N> STATUS
- completed: [list of shot IDs]
- failed: [list of shot IDs + one-line failure reason]
- next decision: [what the user must approve before Phase N+1 starts]
```

Do not freelance. If a step doesn't match what's on screen, **stop and report**, don't guess.

---

## Pre-flight (do this once, before Phase 1)

1. Confirm tab is `app.runwayml.com/video-tools/teams/<team-slug>/ai-tools/generate?mode=apps` (the Apps page).
2. Confirm the `∞ Unlimited` badge is visible top-right. If it shows credits instead, **stop** — wrong account or plan lapsed.
3. Confirm the user is on the correct team workspace (the URL slug). If unsure, ask the user to confirm before proceeding.
4. In the left sidebar, confirm these entries are visible: `Apps`, `Custom`, `Chat`, `Recents`, `Workflow`, `Characters`. If `Characters` is missing, the account doesn't have access — stop.

Report `PRE-FLIGHT OK` and wait for Phase 1 instructions.

---

## Phase 1 — Character lock (most important step, do not skip)

**Goal:** create two persistent Character entries (`@ken`, `@fizzlepuff`) with 3–4 reference images each, so all 25 shots can lock identity by `@`-tag.

**User must provide before this phase:**
- Path to existing Dec-2024 fox reference image (will be uploaded via OS file picker — you click the upload button, the user selects the file)
- Path to existing Dec-2024 cat reference image
- Optional: 3 additional angles per character if already generated; otherwise we'll generate them in 1.2

### Step 1.1 — Open Characters

1. Click `Characters` in the left sidebar.
2. Wait for the Characters library to load. If empty, that's expected (first-time use).
3. Click `+ New Character` (or equivalent — top-right of the panel).

### Step 1.2 — Create `@ken`

1. In the new-character dialog, set name: `ken`.
2. Click the upload area for reference images.
3. **Pause and ask the user to select the Dec-2024 fox image** in the OS file picker. Wait for upload to complete (you'll see a thumbnail).
4. If the user has 3 additional angle references on disk, repeat upload for each (front / 3-quarter / profile / neutral expression — Runway's "Consistent Characters" docs say 3–4 refs is the sweet spot).
5. If only the Dec-2024 still is available, **generate additional angles in-app**:
   - Click `Generate angles` (or use the Image-to-Image flow with the Dec-2024 still as reference).
   - Prompt: `anthropomorphic red fox in pinstripe suit, orange tie, three-quarter view, neutral expression, broadcast studio lighting, photoreal cinematic CGI, matching reference identity exactly`
   - Generate 3 variants. Approve the 2–3 that match the Dec-2024 character's face shape and fur color most closely. Reject any that drift.
6. Save the character. Confirm it appears in the Characters library with the name `ken`.

### Step 1.3 — Create `@fizzlepuff`

Repeat 1.2 with these changes:
- Name: `fizzlepuff`
- Reference: Dec-2024 felted-puppet cat still
- Generate-angles prompt: `stop-motion felted puppet cat, knitted texture, dark suit with pink tie, oversized round glasses, three-quarter view, holding stick, wes anderson fantastic mr fox aesthetic, neon backlighting, matching reference identity exactly`

### Step 1.4 — Verify both characters work

1. Open `Apps → Image → Gen-4 Image` (or any text-to-image with reference support).
2. Test prompt: `medium shot of @ken at news desk, reading from teleprompter, broadcast studio, warm tungsten lighting`
3. Generate 1 still. Confirm:
   - The fox is recognizably the Dec-2024 character (face shape, fur tone, suit/tie).
   - The character is anthropomorphic (sitting at desk, hands on monitor) — not a literal fox.
4. Repeat with `@fizzlepuff` test prompt: `medium shot of @fizzlepuff at desk in dim newsroom, holding microphone, satellite-feed glitch overlay, warm fill lighting, stop-motion felted aesthetic`.
5. If either test fails identity lock (looks generic, drifts to photoreal cat instead of felted, etc.), **stop** and report. Do not proceed to Phase 2 with bad character locks — every downstream shot will be wrong.

Report `PHASE 1 STATUS` per the format above. Wait for the user to confirm both character tests look right before Phase 2.

---

## Phase 2 — Batch generation (19 non-Act-Two shots)

**Goal:** queue all Scene Builder, Multi-Shot Video, and Image-to-Video shots from `shot-list.json`. Skip the 6 Act-Two shots — those need driving videos and run in Phase 3.

**User pastes:** the contents of `prompts.md` filtered to non-Act-Two shots, OR the user pastes shots one at a time. Either works.

### Per-shot loop (repeat for each non-Act-Two shot)

1. From the prompt card, read: shot ID, tool, duration, aspect, prompt.
2. Open the named tool from the left sidebar:
   - **Scene Builder** → `Apps → Starter Kits → Film or shorts → Scene Builder`
   - **Multi-Shot Video** → `Apps → Starter Kits → Film or shorts → Multi-Shot Video`
   - **Image-to-Video** → `Apps → Video → Image-to-Video` (Gen-4.5)
3. Paste the full prompt from the card into the prompt field.
4. Set:
   - **Aspect ratio:** `1920×1080` (16:9)
   - **Duration:** value from the card (`duration_gen_s` field — 5 or 10 seconds)
   - **Model:** `Gen-4.5` (NOT Turbo — quality > speed for AIFF)
   - **Seed:** leave default unless the prompt card specifies one (S07 first-cat-appearance specifies a seed for re-runs)
5. If the card lists character references (e.g., `@ken` or `@fizzlepuff`), confirm the corresponding Characters slots are loaded into the prompt — Runway's UI shows pills for each tag.
6. Click `Generate`.
7. Note the task ID or queue position in your status block.
8. Move to the next shot — **do not wait for completion**. Runway queues generations; we'll download in batch in Phase 4.

### Special handling

- **S07 (first cat appearance)** — flagged drift risk. After queuing, immediately watch its generation. If the cat renders photoreal instead of felted, regen with seed lock + add `[NOT photoreal, MUST be stop-motion felted puppet]` at the end of prompt. Do this BEFORE queueing more cat shots so character drift doesn't propagate.
- **S19 (44ms vs 1655ms hero graphic)** — generate the red-gradient backdrop only. Do NOT trust Runway to render the digits. Note this clearly in status. Terminal-Claude will composite the actual `44ms` and `1655ms` text in DaVinci Fusion later.
- **S25 (end card)** — Image-to-Video over a typeset still. Skip for now. Terminal-Claude will provide the typeset still in a later step.

### Halt conditions (stop and report immediately)

- Any shot fails 2 generation attempts in a row with the same prompt.
- Account hits a rate-limit message (Unlimited Explore can still throttle on concurrent count).
- A character pill disappears from the prompt without warning (Runway sometimes drops references).
- The Generate button greys out for >60s.

Report `PHASE 2 STATUS` after every 5 shots queued. Final status when all 19 are queued.

---

## Phase 3 — Act-Two close-ups (6 shots: S04, S08, S12, S18, S20, S23)

**Goal:** lip-sync 6 dialogue close-ups using Act-Two performance capture.

**User must provide before this phase:**
- 6 driving performance videos recorded on phone or webcam — flat front lighting, chest-up framing, head centered with ~30% headroom, mouth visible the entire time, eyes at lens, 24fps if possible. Each video should be the actual line as it should be spoken (so timing matches).

The user reads each line into the camera. Lines come from `script.md` Segments 1, 2, 3, 4, 5, 6 — one Act-Two shot per segment. The shot mapping:

| Shot ID | Segment | Character | Line (excerpt — full line in script.md) |
|---|---|---|---|
| S04 | Cold Open | FOX | "Tonight at six: a one-person hackathon team..." |
| S08 | Compliance Desk | CAT | "Wait — wait. We did WHAT to whose repo?" |
| S12 | Kernel Lab | CAT | "I'm reporting live from sm_103 — and Stuart, the math is GORGEOUS..." |
| S18 | Hardware Hour | FOX | "[B-roll narration over server racks]" |
| S20 | Engineering Breaking News | FOX | "Forty-four. Milliseconds." (composure-break beat) |
| S23 | Closer | FOX | "None of this happens without the brain in the box..." |

### Per-Act-Two-shot loop

1. Open `Apps → Starter Kits → Film or shorts → Performance Capture with Act-Two`.
2. Upload the **target character image** — for each shot, use the canonical front still from the Characters library (`@ken` for fox shots, `@fizzlepuff` for cat shots). You may need to download the Character ref to disk and re-upload here, since Act-Two takes images not Character tags. Ask the user.
3. Upload the **driving performance video** — user selects from disk.
4. Set:
   - `body_control`: medium (allows shoulder/head movement, not full-body)
   - `expression_intensity`: 0.7 (default 1.0 is too cartoony for satire)
5. Click Generate.
6. Wait for completion (Act-Two is slower than image-to-video, expect 3–8 min per shot).
7. Inspect: face identity locked? Lip-sync visibly matches audio? Eyes following lens?
8. If drift on first try, regen once with `expression_intensity` lowered to 0.5.
9. If still drifts, **stop** — terminal-Claude will provide a fallback prompt or revise the script line.

### Special handling

- **S20 (fox composure break)** — flagged for highest drift risk. The "disbelief" beat may distort the face. Plan for 3 takes minimum. The user may want to record 3 different driving performances of the same line with slightly different deliveries, then pick the best Act-Two output.
- **S12 (longest cat dialogue)** — if Act-Two struggles with the felted-puppet face geometry over a 10-second clip, fallback: split into two 5-second segments cut on a whip-pan. The script.md has a natural pause point.

Report `PHASE 3 STATUS` after each Act-Two shot completes.

---

## Phase 4 — Downloads + organization

**Goal:** pull every generated clip at max quality into a structured local folder. Terminal-Claude will assemble in DaVinci.

### Step 4.1 — Download HD masters

1. Open `Recents` from the left sidebar. All Phase 2 + Phase 3 outputs should be listed.
2. For each clip:
   - Click the clip thumbnail.
   - Click the `Download HD` button. If a `4K Upscale` toggle is available (it costs 0 credits on Unlimited, takes 1–2 min wall-clock), enable it for the 6 Act-Two shots and S19 (the hero graphic backdrop). The other 18 are fine at 1080p.
   - Save with the filename: `<shot_id>.mp4` (e.g., `S01.mp4`, `S07.mp4`, etc.).
3. **Save target folder:** ask the user to set the browser's default download folder to `/Users/kiteboard/prism42/findings/runway-aiff/clips/` before starting. Otherwise, the user manually moves files after.

### Step 4.2 — Verify completeness

After all downloads, confirm 25 files present, named `S01.mp4` through `S25.mp4`. Report any missing IDs in the status block.

### Step 4.3 — Tag with Characters in Recents (optional cleanup)

For future re-runs, click the `Tag` button on each character shot in Recents and tag with `aiff-broadcast` so the project filters cleanly later. Skip if time-pressured.

Report `PHASE 4 STATUS` with the file count + any missing IDs.

---

## Phase 5 — Final status handoff

When Phases 1–4 complete, write a single summary to terminal-Claude (the user can paste this into the prism42 terminal session):

```
RUNWAY GEN COMPLETE — handoff to terminal-Claude

- characters: @ken and @fizzlepuff locked, refs at <count> per
- shots downloaded: <count>/25
- failures (if any): <list shot IDs + reason>
- 4K-upscaled: <list shot IDs that got the upscale>
- driving videos used for Act-Two: <list shot IDs + driving video filenames>
- ready for: DaVinci assembly + ElevenLabs VO + Kodak 2383 grade

Next steps for terminal-Claude:
1. Composite hero number "44ms vs 1655ms" in DaVinci Fusion onto S19.
2. Generate typeset end-card still for S25, then user re-runs Image-to-Video on it.
3. Render ElevenLabs VO from script.md (FOX = warm baritone, CAT = nervous tenor).
4. Source CC0 music bed from YouTube Audio Library (news-broadcast feel, ~110 BPM, ducks at 1:50 climax).
5. Assemble timeline, color-grade, upscale master, export H.264 1080p 24fps under 2GB.
6. Submit to aif.runwayml.com/submit under Storytelling/Narrative category before May 18 11:59 PM PT.
```

---

## Appendix A — Recovery patterns

| Failure | Symptom | Fix |
|---|---|---|
| Character drift | Fox renders generic / cat renders photoreal | Regen with seed lock + identity tokens in first 20 prompt tokens. If 2nd attempt fails, escalate to terminal-Claude with screenshot. |
| Garbled text in shot | Any digit/letter rendered by Runway looks wrong | Don't fix in Runway — note for DaVinci compositing. Generate the underlying plate clean. |
| Motion artifacts (flicker, morph) | Subject features warp during the clip | Reduce duration to 5s, regen. If persists, change camera move to locked-off. |
| Lip-sync off in Act-Two | Mouth doesn't match audio timing | Re-record driving video reading the line in cadence; ensure 24fps phone setting. |
| Queue stalled | Generations don't progress for >5min | Refresh page. If stuck, hard-reload tab. Don't re-queue duplicates — Runway will dedupe but it confuses the Recents list. |
| File picker won't open | OS dialog doesn't appear when clicking upload | Browser permissions. Tell user to check Chrome's site settings for app.runwayml.com. |
| `@character` pill drops | Character reference disappears from prompt mid-typing | Retype the `@` and re-select from the autocomplete. Save the prompt as a snippet so you don't lose it. |

## Appendix B — Driving-video recording checklist (for Phase 3)

- iPhone or webcam at chest height, lens at user's eye level
- Soft front-light source (window facing user, OR ring light at 1m). NO hard side lighting — kills Act-Two retargeting.
- Plain background (off-white or solid color). No motion behind user.
- Frame: chest-up, head centered, ~30% headroom above the head
- Look at the lens (not at the screen below it)
- Record at 24fps if possible (iPhone: Settings → Camera → Record Video → 1080p HD at 24 fps)
- Read the line in the cadence intended for the final cut (this sets the timing Act-Two will preserve)
- Each driving video: 5–10 seconds, matching the corresponding shot's `duration_gen_s`

## Appendix C — When to escalate to terminal-Claude

Stop and ping the user (who pings terminal-Claude) immediately if:

- A character can't be locked after 3 prompt iterations.
- A scripted beat needs rewording because Act-Two can't sell it (e.g., a visual gag depends on a facial expression Act-Two won't produce cleanly).
- The Unlimited Explore badge changes to a credit balance mid-session.
- Any shot would require text-rendering that DaVinci compositing can't fix (ask before doing creative substitutions).

Don't escalate for: routine drift on first attempt, slow gen times, queue position, normal regen workflow. Those are expected and you handle them per the recovery patterns.
