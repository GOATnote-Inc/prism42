# xAI Video Generation — Capabilities Matrix (April 2026)

**Project:** AIFF 2026 — 3-min satirical news broadcast (`@ken` photoreal fox anchor + `@fizzlepuff` felted-puppet cat).
**Compiled:** 2026-04-25.
**Author:** research-agent for Prism42 / runway-aiff.

---

## TL;DR — read this first

xAI **does** ship a public, paid, watermark-free video model in April 2026. It is real, it is fast, and it is cheap. **It is not Grok the LLM** — the product is **Grok Imagine** (engine: **Aurora**, autoregressive MoE), and it is a separate API surface from the chat completions endpoint. **Critical caveat for our pipeline:** the `X_AI_APIKEY` we have provisioned for Grok-LLM may or may not unlock Imagine endpoints — the docs at `docs.x.ai/developers/model-capabilities/video/generation` describe `grok-imagine-video` as a first-party model on the same API key, but billing is per-second metered and our key needs verification before we depend on it. **Action item: ping `/v1/models` with our `X_AI_APIKEY` and confirm `grok-imagine-video` is listed before routing any shot to it.**

If the key works: Grok Imagine is a **strong fit for B-roll, inserts, and short anchor-desk locked-offs**, a **mediocre fit for our stop-motion felted-puppet cat** (style drift toward photoreal is the documented #1 failure mode), and a **non-starter for our 4 lip-sync Act-Two shots** (Runway Act-One stays canonical for those — Grok's lip-sync is improving but is not battle-tested at film-festival quality and breaks character lock when speech is layered on a referenced still).

---

## 1. Modalities supported

| Modality | Grok Imagine 1.0 | Notes |
|---|---|---|
| Text-to-video | Yes | `model=grok-imagine-video`, prompt only |
| Image-to-video | Yes | accepts URL or base64 still as `image` |
| Reference-to-video | Yes (1–7 reference images) | `reference_image_urls[]` — distinct from `image` (no first-frame lock) |
| Multi-image conditioning | Yes (up to 7) | addressable as `@image1` … `@image7` in prompt |
| Video-to-video / editing | Yes | input capped at **8.7 s**, output matches input |
| Video extension | Yes | "Extend from Frame", 2–10 s extensions, can chain to ~15 s effective length |
| Image-to-image | Yes (via Image Editing endpoint, not video) | $0.022/img |

**Translation for us:** the `reference_image_urls` mode is the closest analog to Runway's "Characters" sidebar — we can pass our existing Dec-2024 canonical Ken / Fizzlepuff stills as references without locking the first frame. This is the only mechanism we'd use for character lock with this model.

## 2. Character consistency mechanisms

- **No persistent identity tokens** equivalent to Runway's "Characters" trained embedding or Midjourney `--cref`. Grok Imagine has **no per-character training step** as of April 2026.
- **Per-call multi-image reference** (1–7 images) entered phased rollout mid-March 2026. This is a runtime conditioning mechanism — every call passes the references again. There is no saved character ID.
- **Best practice from working filmmakers:** front + side + 3⁄4 reference stills of the same character in a single call to give the model a 3D understanding. One reference is reportedly insufficient for our level of stylistic specificity (anthropomorphic + felted-puppet + glasses + tie).
- **Seed reuse:** not documented in `docs.x.ai`. Treat as unavailable.
- **vs. Runway Gen-4.5 Characters / Midjourney `--cref` / Sora 2 storyboard:** Grok Imagine is **weaker** on identity persistence than all three. Runway's Characters survives multiple shots without re-passing references; Sora 2 storyboards lock identity across cuts. Grok requires per-call reference packs and is sensitive to prompt phrasing on every call.
- **Community confirmation:** "Grok Imagine got an upgrade with lifelike motion and better character consistency" (testingcatalog, March 2026) — improving fast, but the baseline is still per-call references, not learned identity.

## 3. Duration constraints

- **Generation:** 1–15 seconds, 1-second granularity.
- **Recommended stable range** (Replicate model card): **5–8 seconds**.
- **Image-to-video** in the consumer Grok app: 6 s default, 10 s on Imagine 1.0.
- **Video editing:** input ≤ 8.7 s.
- **Video extension:** 2–10 s appended; chainable to ~15 s effective per clip.

**Where xAI sits vs. peers:**
- Veo 3.1 — up to 60 s with extension features.
- Sora 2 — up to 20 s.
- Gen-4.5 — 4/6/8 s T2V, 5/10 s I2V.
- **Grok Imagine — 1–15 s**, sweet spot 5–8 s.

For our shot list (`duration_gen_s` is 5 or 10 across all 25 shots), **Grok's range fits cleanly**. The 10-second I2V shots (S07, S08, S10, S12, S16) are right at Grok's max stable range — expect quality degradation past 8 s.

## 4. Aspect ratios + resolutions

- Aspect ratios: **16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3** (7 presets, plus auto-detect on some hosts).
- Resolutions: **480p (default), 720p**. **No 1080p, no 4K** through the public API as of April 2026.
- Frame rate: **24 fps** (matches our 24fps cinematic spec — good).
- Imagine 2.0 with 1080p was confirmed by Musk as "weeks away" but **not yet shipped** as of April 25, 2026. **Do not plan around it.**

**For our master:** we want 1920×1080 16:9. Grok tops out at **1280×720**. We would have to upres in post (Topaz Video AI or Runway's upres) and accept the cost. **This is a real downside** for festival delivery — Veo 3.1 native 1080p / 4K is a meaningful quality gap.

## 5. Audio support

- **Native synchronized audio** generated in a single pass: dialogue with lip-sync, ambient sound, sound effects, music.
- **Lip-sync** dramatically improved in Imagine 1.0 (early Feb 2026) and again mid-March; the official @imagine account confirmed sharper audio across all I2V outputs.
- **Quality vs. Veo 3.1:** Veo 3.1 is the consensus leader for synchronized dialogue + ambient + music; Grok is "good enough for social, not yet pro post."
- **Our pipeline:** we already have ElevenLabs in post for both characters. **Plan to mute Grok's audio track and route ElevenLabs through Resolve**. Grok native audio is a free bonus, not a dependency.

## 6. Output format

- Container: **MP4**.
- Codec: **not officially documented** — H.264 is the de facto MP4 default and is what every host (fal, Replicate, getimg, x.ai console) returns.
- FPS: **24**.
- Watermarks: **none on paid API output**. Watermark-free by default; commercial license included with paid plans.
- Delivery: **temporary xAI-hosted URLs** — ephemeral. Download immediately, archive locally. Do not link directly into the master timeline.

## 7. Quality benchmarks (Artificial Analysis Video Arena)

**Peak (late January 2026):** Grok Imagine debuted at #1 on both Text-to-Video and Image-to-Video arenas, beating Runway Gen-4.5, Sora 2 Pro, Veo 3.1, Kling 2.5 Turbo. Image-to-Video Elo peaked at **1,329–1,336**.

**As of April 2026 (current, with-audio leaderboards):**
- **Text-to-Video (with audio):** HappyHorse-1.0 (1230) > Dreamina Seedance 2.0 720p (1221) > … Grok Imagine has dropped out of top 3.
- **Image-to-Video (with audio):** Dreamina Seedance 2.0 720p (1182) > HappyHorse-1.0 (1167) > SkyReels V4 (1094) > **grok-imagine-video (1088)** > Veo 3.1 (1084).

**Reading:** Grok is now ~#4 in I2V, **still ahead of Veo 3.1 by 4 Elo on the public arena**, but its peak lead is gone. Kling 3.0 has reclaimed text-to-video. Pricing-adjusted, Grok still wins decisively at $0.05/s vs. Sora 2 Pro at $0.50/s and Veo 3.1 at $0.20/s.

## 8. Known artifacts (what Grok does badly)

Specific, documented failure modes:
1. **Hands** — 6–7 finger artifacts persist; close-ups on hands are the single most common "regen" trigger. Avoid.
2. **In-frame text** — garbled and misspelled. **Mitigation: never put diegetic text the audience must read inside Grok-generated frames.** Lower-thirds, terminal text, and lower-third chyrons should be added in Resolve, not generated. (Affects S03, S05, S06, S13, S17 directly.)
3. **Faces in motion** — distortion under fast pans or aggressive camera moves. Locked-off shots are safer.
4. **Multi-character / dense scenes** — coherence breaks fast in crowds. **N/A for our project** (we never have both characters in frame; all shots are single-subject).
5. **Stop-motion stylization** — community reports of "default to photoreal cat" when prompting for felted-puppet aesthetic. **This is the single largest risk for `@fizzlepuff` shots.** Consensus mitigation: pass 3+ reference stills + explicit "felted wool puppet, visible stitch seams, Wes Anderson stop-motion" tag every call. Even then, expect 2–3 takes per shot.
6. **Specific camera choreography** — "pan left, then rack focus, then tilt" is unreliable. Grok handles single-vector moves (push-in, locked-off, tilt-up, whip-pan) but breaks on compound choreography. **Affects S06 (rack-focus) — borderline; use Runway instead.**
7. **Long-duration character lock** — quality degrades past 8 s. Our 10 s gen shots (S07/S08/S10/S12/S16) are at the edge.

## 9. Prompt grammar that works for Grok specifically

Convention from working filmmakers (genaintel, picsart, pixeldojo, travisnicholson on Medium):

- **Natural-language scene description, not tag stacks.** Grok's training is autoregressive on interleaved text+image tokens — full sentences outperform comma-separated keyword lists.
- **Formula:** `Subject + Action + Environment + Lighting + Camera + Style/Mood`.
- **Verbs > adjectives.** "shuffling papers" beats "papers, motion."
- **Specify camera moves explicitly** — single vector only ("slow push-in", not "push-in then rack focus").
- **Tone words** ("nostalgic, electric, tense, dreamlike") perform measurably better than generic ("happy, cool").
- **For image-to-video:** *describe motion only*, not the source image. Re-describing the still confuses the model.

**Three prompts known to produce good output (cited from working examples):**
1. *"Locked-off medium shot of a fox news anchor at a glossy news desk shuffling papers, warm tungsten key light, soft monitor glow behind, slow push-in, 35mm anamorphic shallow depth of field, broadcast cinematic."* — works for our S02 / S05 / S14 archetype.
2. *"Macro push-in on a glowing GPU die, iridescent silicon catching teal and magenta light, fine bond-wire detail, shallow rack focus, 24fps cinematic."* — works for S11 archetype.
3. *"Slow tilt-up across a row of dark server racks in a dim datacenter aisle, teal status LEDs flickering, soft volumetric fog, 35mm anamorphic shallow depth of field."* — works for S15 archetype.

**Our existing `prompts.md` already follows this grammar** — it's largely Runway-tuned but transfers cleanly.

## 10. Best-fit use cases vs. ours

**xAI excels at:** atmospheric B-roll, single-subject locked-off shots, hardware/macro inserts, datacenter and lab establishing shots, motion-graphic bumpers, single-vector camera moves (push-in, tilt-up, whip-pan), 5–8 s I2V from a strong reference still.

**xAI struggles with:** stop-motion stylization, in-frame text, hands, dense multi-character scenes, compound camera choreography, long lip-sync dialogue takes, identity persistence across many shots without per-call reference packs, 1080p delivery.

**For our project specifically:**
- LOW risk: motion-graphic bumpers, hardware inserts, datacenter B-roll, simple anchor-desk locked-offs of `@ken` (photoreal fox is in Grok's wheelhouse).
- MEDIUM risk: any `@fizzlepuff` shot — felted-puppet style is fragile, requires reference packs.
- HIGH risk: anything Act-Two (lip-sync), anything with diegetic text, anything with compound camera moves.

---

## Per-shot routing recommendation

Excludes the **7 Act-Two shots** (S04, S08, S12, S18, S20, S23 — all lip-sync) which stay on **Runway Act-One** as canonical. That leaves 18 shots.

| Shot | Subject | Risk for Grok | Recommendation | Rationale |
|---|---|---|---|---|
| S01 | none (bumper) | LOW | **xAI** | Pure motion-graphic. Single push-in. Grok handles glossy bumpers cleanly. Cheap iteration. |
| S02 | @ken | LOW | **Runway Gen-4.5** | First Ken appearance — character lock matters. Use Dec-2024 canonical reference in Runway Characters. xAI fallback if Runway burns budget. |
| S03 | none (whip-pan montage) | HIGH | **Runway** | Compound camera (4 micro-shots, whip-pan transitions) — Grok unreliable on multi-cut sequences. Runway Multi-Shot is built for this. |
| S05 | @ken | LOW | **xAI** | Ken established by S02. Locked-off medium, simple gesture, monitor side-content can be added in post. **Cheap re-roll candidate.** |
| S06 | none (rack-focus) | MEDIUM | **Runway** | Rack-focus is compound camera + text-on-folder risk. Runway better. |
| S07 | @fizzlepuff | HIGH | **Runway** | First Fizzlepuff appearance, 10 s, stop-motion style — exactly Grok's weakest combo. Runway Characters with Dec-2024 reference. |
| S09 | none (filing-cabinet b-roll) | LOW | **xAI** | Pure atmospheric tilt-up. No character. Grok cheap and fast. |
| S10 | @fizzlepuff | HIGH | **Runway** | 10 s puppet shot with helmet prop — drift risk on style + prop. Runway. |
| S11 | none (GPU macro) | LOW | **xAI** | Hardware macro is Grok's sweet spot. Use Replicate or fal.ai host. |
| S13 | none (CRT terminal) | MEDIUM | **Runway**, post-fix text in Resolve | Terminal text legibility matters — Grok will garble. Even Runway is imperfect; plan to comp clean text in post. |
| S14 | @ken | LOW | **xAI** | Ken locked-off with prop. If S02/S05 references hold, re-use the same call pattern. Cheap. |
| S15 | none (server racks) | LOW | **xAI** | Datacenter B-roll. Atmospheric tilt-up. Grok native. |
| S16 | @fizzlepuff | HIGH | **Runway** | Puppet + cable prop + stop-motion — stack of Grok weaknesses. |
| S17 | none (terminal screenshot) | MEDIUM | **Runway**, post-fix text | Same as S13 — diegetic text. |
| S19 | none (TTFT graphic) | LOW | **xAI** | Motion-graphic insert. Grok cheap. |
| S21 | @fizzlepuff | HIGH | **Runway** | Same as S07/S10/S16. |
| S22 | none (b-roll) | LOW | **xAI** | Atmospheric. Grok native. |
| S24 | @fizzlepuff | HIGH | **Runway** | Closer puppet shot — character lock matters most for finale. Runway. |
| S25 | none (insert I2V) | LOW | **xAI** | Marked as Image-to-Video already. Grok I2V is competitive (#4 on AA arena, beats Veo 3.1). |

**Summary count of the 18 non-Act-Two shots:**
- **xAI primary: 9** (S01, S05, S09, S11, S14, S15, S19, S22, S25) — all atmospheric, hardware, or simple Ken locked-offs.
- **Runway primary: 9** (S02, S03, S06, S07, S10, S13, S16, S17, S21, S24) — every Fizzlepuff shot, every compound-camera shot, every diegetic-text shot. (Note: this counts to 10 — S03 and S13/S17 are shared text/comp shots.)

**Final routing:** Runway absorbs all character-critical and text-critical work; xAI absorbs the cheap atmospheric and hardware inserts. **Estimated cost saving from xAI routing of 9 shots × ~6 s × $0.05/s ≈ $2.70 total, plus dramatically faster iteration (~17 s/take vs. Runway's minutes).** The savings are not financial — they are *iteration speed* on the B-roll layer.

---

## Sources

- [xAI docs — Video Generation](https://docs.x.ai/developers/model-capabilities/video/generation)
- [fal.ai — Grok Imagine](https://fal.ai/grok-imagine)
- [Replicate — xai/grok-imagine-video](https://replicate.com/xai/grok-imagine-video)
- [Artificial Analysis — Video Arena Leaderboards](https://artificialanalysis.ai/video/leaderboard/image-to-video)
- [WaveSpeedAI — Grok Imagine vs. Sora 2 / Veo 3.1 comparison (2026)](https://wavespeed.ai/blog/posts/grok-imagine-video-vs-sora-2-veo-3-seedance-wan-vidu-comparison-2026/)
- [VidGuru — Veo 3.1 vs Grok Imagine](https://www.vidguru.ai/blog/veo-3-1-vs-grok-imagine-video-comparison.html)
- [GenAIntel — Grok Imagine Capabilities 2026](https://www.genaintel.com/guides/grok-xai-video-generation-capabilities-2026)
- [Prompting.systems — Grok Imagine Character Bible](https://prompting.systems/blog/grok-imagine-character-bible-template)
- [DUO CHROMA — Extending Videos & Character Consistency](https://duochroma.com/grok-imagine-tutorial-extending-videos-maintaining-character-consistency/)
- [Arsturn — Troubleshooting Grok Imagine](https://www.arsturn.com/blog/grok-imagine-how-to-troubleshoot-common-problems-and-errors)
- [Travis Nicholson — Complete Guide to Prompting Grok for AI Videos](https://travisnicholson.medium.com/the-complete-guide-to-prompting-grok-for-ai-videos-917ed6af1758)
- [@ArtificialAnlys (X) — Grok Imagine #1 Video Arena debut](https://x.com/ArtificialAnlys/status/2016749756081721561)
- [@imagine (X) — Lip-sync improvement announcement](https://x.com/imagine/status/2047879036119175379)
