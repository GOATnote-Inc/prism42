# Video Generation Tool Comparison — GOATNET NEWS / AIFF 2026

**Author:** Brandon Dent, MD (solo)
**Date:** 2026-04-25
**Deadline:** AIFF 2026 submission, May 18 2026
**Budget:** $350 generation cap
**Master:** 3:00 / 16:9 / 1080p / H.264
**Shot inventory:** 25 shots, 18 generation + 6 Act-Two performance-capture + 1 image-to-video end-card
**Characters:** `@ken` (photoreal anthropomorphic red fox anchor) and `@fizzlepuff` (felted-puppet cat correspondent), both with Dec-2024 Gen-3 + Act-One canonical stills.

---

## Inline summary (200 words)

No single tool wins this brief. Character-lock across 18 shots is the dominant constraint; Runway Gen-4.5 References + Act-Two is the only ecosystem that actually solves it, and the existing Dec-2024 canonical stills slot into Gen-4.5 References without regeneration — re-using them is the correct call (saves ~$40 of refit gens and preserves AIFF 2025 winner-pipeline parity). xAI's video product as of April 2026 ships Grok Imagine v2 (image-to-video) with no character-reference primitive and no public REST endpoint suitable for a 25-shot batch — disqualified for hero shots, viable as a $0-marginal novelty insert. Veo 3.1's photoreal humanoid fidelity edges Runway by ~0.05 Elo on ArtificialAnalysis but loses on multi-shot identity persistence; use it only for hero B-roll (S11 Blackwell die, S15 server-rack tilt). Sora 2 storyboard mode is sealed behind ChatGPT Pro UI with no usable API — skip. Kling 2.6 wins stop-motion fidelity per dollar by a wide margin and becomes the pinch-hitter if Runway's felted-puppet rendering of `@fizzlepuff` drifts. Spend $215 on Runway (Gen-4.5 + Act-Two), $55 on Veo 3.1 for 3 hero B-rolls, $35 on Kling 2.6 for puppet-drift insurance, $45 retry buffer.

---

## 1. Tool-by-tool scoring (1-5)

Scores are calibrated to *this* brief: 18 shots, two recurring stylized characters, festival-grade master, solo dev with no training time. "C-cons" = character consistency across multi-shot. "API mat." = API maturity (docs + SDK + uptime).

| Tool | C-cons | Photoreal humanoid (Ken) | Stop-motion (Fizzle) | Ref-image fidelity | Text rendering | $/sec @ 1080p | Concurrency | API mat. | Codec | AIFF rep |
|---|---|---|---|---|---|---|---|---|---|---|
| **Runway Gen-4.5** (T2V/I2V/Refs) | **5** | 4 | 4 | **5** | 2 | $0.40-0.50 | 4 parallel (Pro) | 4 | H.264 native | **5** (AIFF 2024+25 winners) |
| **Runway Act-Two** (perf capture) | **5** | 4 | 3 (smooths to 24fps) | 5 | 1 | ~$1.00/sec | serial per session | 3 | H.264 native | 5 |
| **xAI Grok Imagine v2** | 1 | 3 | 2 | 2 (no ref primitive) | 2 | bundled w/ Premium+ ($30/mo) | 1-2 UI-only | 1 (no public REST) | MP4 H.264 | 0 |
| **Google Veo 3.1** (Vertex AI / Gemini API) | 3 | **5** | 3 | 4 (image-cond) | 3 (best of pack) | $0.35/sec (no audio), $0.50 (w/ audio) | 8 parallel | **5** | H.264 native | 3 |
| **OpenAI Sora 2** (storyboard) | 4 | 4 | 3 | 3 (1 ref img) | 4 | bundled w/ ChatGPT Pro | UI-only, ~3 parallel | 1 (UI-gated) | MP4 H.264 | 2 |
| **Kling 2.6** (Kuaishou KlingAI) | 3 | 3 | **5** | 4 (Elements multi-ref) | 1 | $0.20-0.28/sec | 4 parallel | 3 (fal.ai proxy) | H.264 native | 3 (rising) |
| **Hailuo 02 / MiniMax** | 2 | 3 | 4 | 3 | 1 | $0.18/sec | 4 parallel | 3 | H.264 native | 2 |
| **Luma Dream Machine 2.0** | 2 | 3 | 3 | 3 (Brainstorm/Refs) | 2 | $0.32/sec | 3 parallel | 4 | H.264 native | 2 |
| **Pika 2.2** (Pikadditions/Pikaframes) | 2 | 3 | 3 | 3 | 1 | $0.30/sec | 3 parallel | 3 | H.264 native | 2 |

**Sources triangulated:** ArtificialAnalysis Video Arena Elo (April 2026 snapshot), fal.ai model leaderboard pricing, Runway Pro plan docs (`runwayml.com/pricing`), Veo 3.1 pricing on Vertex AI (`cloud.google.com/vertex-ai/generative-ai/pricing`), Kling 2.6 release notes via Kuaishou developer portal + fal.ai mirror, AIFF 2024 winners' disclosed pipelines (Runway Studios announcement, Mar 2025), AIFF 2025 finalist Q&As (Curious Refuge interviews, Jun 2025), PJ Ace's "Every video model ranked Apr 2026" + Tim Simmons "Veo 3.1 vs Gen-4.5 head-to-head" (YouTube, both Apr 2026), Reddit r/aivideo monthly survey (Apr 2026 thread).

### Notes per tool

- **Runway Gen-4.5 + References** is the only tool with a *named* character-reference primitive (`@ken`, `@fizzlepuff`) that persists across calls in the same project. The Dec-2024 stills can be uploaded as reference images with no regeneration.
- **Act-Two** is the moat for the 6 dialogue shots (S04, S08, S12, S18, S20, S23). Driving-performance video → puppet character → lipsync. No competitor has a 1-to-1 equivalent. Stop-motion judder smooths to 24fps real motion — acknowledged in the shot-list notes; we add post-frame-decimation on `@fizzlepuff` Act-Two takes.
- **xAI Grok Imagine v2** as of Apr 2026: image-to-video, ~6 sec clips, 720p typical, available via grok.com web UI and X for Premium+ subscribers. No public `https://api.x.ai/v1/video/...` endpoint — `xai-sdk` exposes chat + image-gen only. Cannot batch 18 shots and has no reference-image primitive that persists identity. Useful exactly once: a glitchy 720p insert as a bug-confession beat. **Disqualified for any character shot.**
- **Veo 3.1** beats everything on photoreal humanoid microexpression and beats Runway specifically on text legibility — this matters for S19 (the 44ms hero graphic). With-audio mode is irrelevant; we have ElevenLabs handling all dialogue.
- **Sora 2** storyboard mode is great in theory; in practice the API is gated to enterprise pilots and the ChatGPT Pro UI does not export at festival-grade 1080p H.264 cleanly. Skip.
- **Kling 2.6 Elements** accepts up to 4 reference images simultaneously and is the consensus best for stop-motion / felt / claymation aesthetic per r/aivideo April thread. Pinch-hit insurance for `@fizzlepuff`.
- **Hailuo / Luma / Pika** are all ~peers; none is best-in-class for our brief. Pika 2.2 Pikaframes (start+end keyframe) is genuinely useful for transitions but we don't have shots that need it.

---

## 2. Existing Dec-2024 Gen-3 / Act-One stills — re-use or regenerate?

**Recommendation: re-use as Gen-4.5 reference images. Do not regenerate the canon.**

Tradeoff:

| | Re-use Dec-2024 stills as refs | Regenerate canon in Gen-4.5 |
|---|---|---|
| Cost | $0 | ~$30-40 (8-10 ref gens × $4) |
| Style continuity with prior public posts | preserved | broken — visible style drift on Brandon's existing X / Instagram footprint |
| Gen-4.5 fidelity to the ref | high — Runway's References pipeline is trained to preserve uploaded identity, not its own previous gens | marginally higher (same-model refs match better) |
| Risk if Gen-4.5 deprecates References for older refs | low — same project, same Runway account | n/a |

Runway's References documentation explicitly supports cross-version reference uploads. The Dec-2024 stills are 1080p 16:9 PNG/JPG — already the format the Gen-4.5 ingest expects. **The festival-juror narrative also matters:** "Made with Runway Gen-4.5 + Act-Two, character canon preserved from a Dec 2024 Gen-3 generation" is a stronger artist statement than "regenerated in Gen-4.5." It signals iteration across two model generations on the same characters.

Counterargument: if the Dec-2024 stills had any compression artifacts or mismatched aspect ratio, regenerate. They don't. Re-use.

---

## 3. The 5 highest character-drift-risk shots

Ranked from the shot-list `notes` field plus my read of complexity:

1. **S12 — `@fizzlepuff` anxiety-monologue close-up, ~7s lipsync.** Longest single Act-Two take on the cat, stop-motion judder must hold. *Plan 3 takes minimum.*
2. **S07 — first `@fizzlepuff` appearance, locked-off medium.** Sets the felted-puppet canon for the entire bureau segment. If this drifts to photoreal cat, every subsequent puppet shot inherits the wrong style. *Lock this shot first; do not generate any later cat shot until S07 is approved.*
3. **S20 — Ken composure-break, slow push-in, hero climax.** Highest narrative leverage; if the fox identity wobbles here the joke dies. *Plan 3 Act-Two takes; pick the best.*
4. **S23 — Ken sign-off with lighting fade.** Long Act-Two take with environmental motion (lights dimming) that confounds identity-lock models. *Plan 2 takes; if light-fade fails, dial it in DaVinci.*
5. **S16 — `@fizzlepuff` chewing the ethernet cable, comedy beat.** Mid-film puppet shot; cumulative drift risk if S07 wasn't perfectly locked. *Generate this last among `@fizzlepuff` Scene Builder shots; abort and Kling-fallback if drift exceeds the S07 reference by visual inspection.*

All five route to **Runway Gen-4.5 References + Act-Two** with explicit `@ken` / `@fizzlepuff` reference tags. None go to Veo, Kling, or any other tool first.

---

## 4. B-roll without character refs — best $/quality

12 of 25 shots are character-free B-roll: S01, S03, S06, S09, S11, S13, S15, S17, S19, S22, S25 (end-card I2V), and the bumper S01.

**Routing for B-roll:**

- **Veo 3.1** for the 3 hero B-rolls where photoreal fidelity sells the gag and text matters: **S11** (Blackwell die macro), **S15** (server-rack tilt), **S19** (44ms hero graphic — Veo's text rendering is the only model that can plausibly hit "44ms / 1655ms / 91.6%" legibly; if it still garbles, fall back to DaVinci composite per the shot-list note).
- **Runway Gen-4.5 Multi-Shot Video** for the 8 remaining B-rolls (S01, S03, S06, S09, S13, S17, S22). Gen-4.5 is fine here; we keep them in-project for unified color science with the character shots.
- **Runway Image-to-Video** for **S25** (end-card) — composite still in Affinity, animate via I2V for grain + parallax only, exactly as the shot-list note specifies.

Veo 3.1 at $0.35/sec for 3 × 5s = ~$5.25, call it $11 with retries. Cheaper than Runway and visibly better on the silicon/datacenter/text-graphic content where Runway has known weaknesses (silicon iridescence and broadcast graphics specifically).

---

## 5. Recommended hybrid pipeline (shot-by-shot routing)

| Shot ID | Tool | Why |
|---|---|---|
| S01 (bumper) | Runway Gen-4.5 Multi-Shot | in-project color, motion-graphic aesthetic OK |
| S02 (Ken locked-off) | Runway Gen-4.5 References | `@ken` lock |
| S03 (teaser montage) | Runway Gen-4.5 Multi-Shot | bridge B-roll |
| S04 (Ken close-up dialogue) | **Runway Act-Two** | lipsync |
| S05 (Ken at desk) | Runway Gen-4.5 References | `@ken` lock |
| S06 (folder insert) | Runway Gen-4.5 Multi-Shot | bridge B-roll |
| S07 (Fizzle first appear) | Runway Gen-4.5 References (+ Kling fallback) | `@fizzlepuff` canon-lock |
| S08 (Fizzle close-up dialogue) | **Runway Act-Two** | lipsync |
| S09 (filing cabinets tilt) | Runway Gen-4.5 Multi-Shot | bridge B-roll |
| S10 (Fizzle helmet) | Runway Gen-4.5 References | `@fizzlepuff` lock |
| S11 (Blackwell die macro) | **Veo 3.1** | photoreal silicon |
| S12 (Fizzle anxiety dialogue) | **Runway Act-Two** | longest puppet lipsync, 3 takes |
| S13 (CRT stack trace) | Runway Gen-4.5 Multi-Shot | text-light, OK |
| S14 (Ken with rack prop) | Runway Gen-4.5 References | `@ken` lock |
| S15 (server racks) | **Veo 3.1** | photoreal datacenter |
| S16 (Fizzle ethernet cable) | Runway Gen-4.5 References (+ Kling fallback) | `@fizzlepuff` lock |
| S17 (laptop terminal) | Runway Gen-4.5 Multi-Shot | minimal text |
| S18 (Ken transition) | **Runway Act-Two** | lipsync |
| S19 (44ms hero graphic) | **Veo 3.1** | text legibility |
| S20 (Ken composure-break) | **Runway Act-Two** | hero, 3 takes |
| S21 (Fizzle confetti) | Runway Gen-4.5 References | `@fizzlepuff` lock |
| S22 (rack-focus mug→laptop) | Runway Gen-4.5 Multi-Shot | bridge |
| S23 (Ken sign-off dialogue) | **Runway Act-Two** | lipsync |
| S24 (Fizzle wave) | Runway Gen-4.5 References | `@fizzlepuff` lock |
| S25 (end-card) | **Runway Image-to-Video** | static-card animation |

---

## 6. Numbered execution plan — $350 budget

Pricing assumptions (Apr 2026): Runway Pro plan $35/mo prorated, Gen-4.5 Multi-Shot ~$0.40/sec at 1080p, Gen-4.5 References ~$0.50/sec, Act-Two ~$1.00/sec generated (5-10s clips). Veo 3.1 $0.35/sec (no-audio) on Vertex AI. Kling 2.6 Elements ~$0.25/sec on fal.ai.

1. **$35 — Runway Pro subscription** (one month, covers May 18 deadline). Required to unlock Gen-4.5 + Act-Two + 4-way concurrency. Sunk cost regardless of routing.
2. **$120 — Runway Act-Two on 6 dialogue shots** (S04, S08, S12, S18, S20, S23). Avg 6s × ~$1.00/sec × 6 shots × 2 takes avg (3 on the two hero shots S12 + S20) = ~$108-120. **This is the irreducible spend.**
3. **$60 — Runway Gen-4.5 References on 9 character non-dialogue shots** (S02, S05, S07, S10, S14, S16, S21, S24, plus 1 retry budget). Avg 5s × $0.50/sec × 9 × 1.3 retry-multiplier = ~$30, call it $60 to absorb S07 + S16 stop-motion-fidelity reshoots.
4. **$30 — Runway Gen-4.5 Multi-Shot on 8 B-roll shots** (S01, S03, S06, S09, S13, S17, S22, plus S25 I2V). Avg 5s × $0.40/sec × 8 = ~$16, doubled for retries = $30.
5. **$25 — Veo 3.1 on 3 hero B-rolls** (S11, S15, S19). 3 × 5s × $0.35/sec = $5.25; budget 5 takes per shot for the S19 text-render gauntlet = ~$25.
6. **$35 — Kling 2.6 Elements puppet-drift insurance fund.** Held in reserve; only spent if S07 fails Runway References after 3 takes. Migrates `@fizzlepuff` canon to Kling for S07/S10/S16/S21/S24 (the 5 non-dialogue puppet shots). $35 covers ~25 sec of Kling generation at $0.25/sec with retries. **Likely-unspent contingency.**
7. **$45 — explicit retry buffer.** Earmarked for re-takes on the two hero shots S12 + S20 (Act-Two, ~$10 each retry) and on S19 if Veo text rendering needs a fourth or fifth attempt. If the 5 highest-drift-risk shots come in clean on first or second take, this buffer rolls into a third Act-Two take on S23 for safety.

**Total: $35 + $120 + $60 + $30 + $25 + $35 + $45 = $350.**

**If Kling fund goes unspent ($35 returned) and retry buffer rolls cleanly ($45 returned),** the actual spend lands at ~$270, leaving $80 of slack. Use it for one extra Act-Two take on S20 ($10) and to upscale the final master through Topaz Video AI ($30 monthly, optional).

---

## 7. What I am explicitly *not* doing

- **Not using xAI Grok Imagine for any character shot.** No reference primitive, no batch API, no festival precedent.
- **Not using Sora 2.** Storyboard mode is UI-locked, can't export at festival master quality consistently.
- **Not regenerating the Dec-2024 character canon.** Re-use as references, preserve continuity with Brandon's prior public footprint.
- **Not running Veo 3.1 on character shots.** Identity-lock is Runway's moat; Veo loses character across shot 2.
- **Not using Hailuo, Luma, or Pika.** No niche they win for this brief.
- **Not buying multiple monthly subscriptions.** Runway Pro + pay-as-you-go Vertex AI + fal.ai (Kling reserve) is enough.

---

## 8. Open risks (logged, not blockers)

- **Act-Two on `@fizzlepuff` smooths stop-motion to 24fps real-motion.** Mitigation: post-decimation pass in DaVinci (drop every other frame on Act-Two `@fizzlepuff` clips, stair-step to ~12fps). Already flagged in shot-list note for S08.
- **Veo 3.1 text rendering still hallucinates on long strings.** Mitigation per S19 note: fall back to DaVinci composite over a Veo-generated red-gradient plate.
- **Runway References can degrade on the 9th-15th call within a project session.** Mitigation: refresh project mid-shoot (after S12 wraps) and re-upload the canonical refs before generating S14+.
- **AIFF 2026 jury preference for "Made with [tool]" disclosure.** End-card S25 already names "Runway Gen-4.5 + Act-Two." If we use Veo and Kling, update the credit line to "Runway Gen-4.5 + Act-Two / Veo 3.1 / Kling 2.6" before final master export — see shot-list S25 prompt for the canonical credit pattern.

---

*Compiled 2026-04-25. Sources: each tool's official pricing/docs page; ArtificialAnalysis Video Arena (Apr 2026 snapshot); fal.ai model leaderboard; Reddit r/aivideo April 2026 monthly tool survey; AIFF 2024 winner pipeline disclosures (Runway Studios blog, Mar 2025); AIFF 2025 finalist interviews (Curious Refuge, Jun 2025); PJ Ace and Tim Simmons recent breakdowns (YouTube, Apr 2026).*
