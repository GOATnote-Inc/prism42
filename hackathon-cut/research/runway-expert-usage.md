# Runway 2026 — Expert Usage Map for the Bio Intro

**Author:** research-agent (Opus 4.7)
**Date:** 2026-04-25
**Scope:** How working filmmakers leverage Runway's April-2026 API surface, and the
concrete drop-in pipeline for our 28.8s `bio-intro-mix.mp3` lift.
**Authority:** Cross-checked between `docs.dev.runwayml.com`, the locally installed
`runwayml==4.12.0` Stainless-generated Python SDK (which is the canonical OpenAPI
shape), `runwayml.com/changelog`, `help.runwayml.com`, `runwayml.com/news`, plus
filmmaker tutorials from Curious Refuge and the Runway Academy.

---

## 1. Runway feature timeline (Jan-Apr 2026)

| Date | Launch | Surface | Notes |
|---|---|---|---|
| 2026-01-21 | **Gen-4.5 image-to-video** | API + web | First-frame still + text prompt → motion. Ratios `1280:720`, `720:1280`, `1104:832`, `960:960`, `832:1104`, `1584:672`. Allowed `duration` **5 or 10 s**. Hosted at `/v1/image_to_video` (`model="gen4.5"`). |
| 2026-02-10 | **Gen-4.5 text-to-video** | API + web | T2V at `/v1/text_to_video`. Ratios `1280:720` / `720:1280` only on T2V. Duration is a free integer (allowed values surface as 4/6/8/10 in practice). |
| 2026-02-20 | **Third-party models** | Web only | Kling 3.0, Sora 2 Pro, GPT-Image-1.5 inside Runway. **Not on the API yet.** |
| 2026-02-27 | **Nano Banana 2** | Web | Image gen/edit — useful for ref-image prep but no API exposure. |
| 2026-03-09 | **Runway Characters / GWM-1** | API + web | Real-time WebRTC avatar API at `/v1/avatar_videos` (async) and a real-time `/v1/realtime_sessions` flow (the `gwm1_avatars` model). Audio-driven lip-sync, single reference image, **5-min session ceiling**, presets include `cat-character`, `game-character`, `influencer`, `cooking-teacher`. |
| 2026-04-07 | **Seedance 2.0** | API + web | T2V/I2V/V2V with audio-conditioned input. Adds `seedance2` model literal to T2V, I2V, and V2V endpoints. **Outside the US on web; API is global.** |

**Pre-2026 features still load-bearing in Apr-2026 expert work:** Gen-4 References
(image conditioning with up to 3 refs labelled `image_1..image_3`, exposed on
`gen4_image` at `/v1/text_to_image`), Aleph (`gen4_aleph` at `/v1/video_to_video`,
launched Jul-2025), Act-Two (`act_two` at `/v1/character_performance`, the lip+body
performance-transfer model), Veo 3.1 / Veo 3.1 Fast (added Oct-2025 to T2V + I2V),
gen3a_turbo (legacy I2V — now mostly unused except for cheap-and-quick).

[Sources: [API Changelog](https://docs.dev.runwayml.com/api-details/api_changelog/), [Product Changelog](https://runwayml.com/changelog), [Introducing Characters](https://runwayml.com/news/introducing-runway-characters), [Models guide](https://docs.dev.runwayml.com/guides/models/).]

---

## 2. Per-model deep specs (April 2026)

These are **verbatim from the local `runwayml==4.12.0` SDK type stubs** (Stainless
auto-generated from the OpenAPI spec — the source of truth). Pricing from the
official [pricing page](https://docs.dev.runwayml.com/guides/pricing/), credit
conversion **$0.01/credit**.

### `gen4.5` — house workhorse
- **Modalities:** T2V (`text_to_video`) + I2V (`image_to_video`).
- **Ratios T2V:** `1280:720`, `720:1280` only.
- **Ratios I2V:** `1280:720`, `720:1280`, `1104:832`, `960:960`, `832:1104`, `1584:672`.
- **Duration I2V:** `5` or `10` s. **Duration T2V:** integer (4/6/8/10 in practice — SDK accepts arbitrary int but the server enforces).
- **Audio:** **Yes** (set `audio: true` on T2V; native synced audio from Feb-2026 update).
- **References:** Pre-frame conditioning only via `prompt_image` URL/array. For multi-ref character lock, route through `gen4_image` first.
- **Price:** **12 cr/sec → $0.12/sec**. 6 s = $0.72. 10 s = $1.20.
- **Strength:** Best general-purpose photoreal motion in the API. Solid character lock when seeded from a `gen4_image` reference still.
- **Weakness:** Hands, in-frame text, multi-character coherence, compound camera moves.
- **Pro pick when:** Clean single-subject hero shot, locked-off or single-vector camera, 5-10 s, audio optional. Default for "shot the storyboard called for."

### `act_two` — performance transfer (NOT audio-only)
- **Endpoint:** `POST /v1/character_performance`.
- **Inputs:** `character` (image **or** video — must show a recognizable face, kept in frame), `reference` (a **video** of a human performing what you want the character to do, **3-30 s**). **No `audio` parameter — driving signal is video.**
- **Modes:** `body_control: bool`, `expression_intensity: 1-5`, `seed`.
- **Ratios:** `1280:720`, `720:1280`, `960:960`, `1104:832`, `832:1104`, `1584:672`.
- **Output res:** Up to 4K (per `acttwo.cv` marketing; SDK ratio caps at 1584x672 → upscale in post for >720p).
- **Audio:** Lip-sync **derived from the human reference's mouth motion + the audio on that reference**. To put new VO on a character, you film yourself speaking the new VO, then drive the character with that take.
- **Price:** **5 cr/sec → $0.05/sec** of output. 30 s = $1.50.
- **Strength:** Cheapest lip-sync path on the API; works on stylized characters per Runway's own docs ("photorealistic human, cartoon character, fantasy creature, or abstract art").
- **Weakness:** Needs a clean human-face driving reference. Pure-puppet geometry (Fizzlepuff) and snouted anthropomorphs (Ken Fox) sometimes lock to the human jawline rather than the character's. Mitigation: keep `expression_intensity ≤ 3`, reference framing chest-up centered, even diffuse light.
- **Pro pick when:** You have a human "performance reference" you can shoot in 30 seconds on a phone. Default for "make my puppet say this line."

### `gen4_aleph` — V2V edit, the hidden weapon
- **Endpoint:** `POST /v1/video_to_video` (`model="gen4_aleph"`).
- **Inputs:** `video_uri` (HTTPS), `prompt_text` (≤1000 UTF-16 chars), optional `references` (up to 1, image only), `seed`, `content_moderation`.
- **Output:** **Capped at 5 s** regardless of input length. Resolution **inherits from input** — `ratio` is documented as deprecated/ignored. Ratios you can request: `1280:720`, `720:1280`, `1104:832`, `960:960`, `832:1104`, `1584:672`, `848:480`, `640:480`.
- **Audio:** No native audio output (V2V passthrough — input audio is dropped; mux yours back in post).
- **Price:** **15 cr/sec → $0.15/sec**. 5 s = $0.75.
- **Strength:** Style/lighting transfer, object swap, set extension, color match across cuts, weather/time-of-day shift, cleaning a plate. The Curious Refuge "9 ways" tutorial enumerates these as the canonical use-cases. **Aleph is for *editing what's there*, not animating mouths.**
- **Weakness:** **Aleph is NOT a lip-sync model** — every working filmmaker treatment in Apr-2026 confirms it edits style/lighting/objects, not phoneme-aligned mouth motion. The 5-s output cap kills it for full-shot lip-sync anyway.
- **Pro pick when:** "Make these three Ken cuts color-match," or "relight Fizzlepuff's room to warm tungsten," or "remove the on-desk coffee mug from frame 60-120."

### `veo3.1` — Google Veo, accessed via Runway
- **Endpoint:** `text_to_video` and `image_to_video`. Model literal `veo3.1`.
- **Ratios:** `1280:720`, `720:1280`, `1080:1920`, `1920:1080` (this is the **only Runway model with native 1080p**).
- **Duration:** `4`, `6`, `8` s (literal-typed in SDK).
- **First+last frame keyframes:** I2V supports `position: "first"` and `position: "last"` simultaneously — true two-keyframe interpolation.
- **Audio:** Native synced. Pricing toggles: **40 cr/sec with audio = $0.40/sec**, **20 cr/sec no-audio = $0.20/sec**. 8 s with audio = $3.20.
- **Strength:** Highest fidelity in the API for cinematic 1080p, best dialogue+ambient sync at full-shot length, two-keyframe lock.
- **Weakness:** 4× the cost of gen4.5. Hard 8-s ceiling. No reference-image API path on Veo via Runway as of April 2026 (refs route through `gen4_image` and you key-frame into Veo).
- **Pro pick when:** Hero shot. Single most important 4-8 s of the cut. Festival deliverable.

### `veo3.1_fast` — same model, half the price
- Same params as `veo3.1`. **15 cr/sec with audio = $0.15/sec**, **10 cr/sec no-audio = $0.10/sec**.
- 8 s with audio = **$1.20**. ~3.6× cheaper than `veo3.1`.
- Pro filmmakers (Min Choi's Aleph showcase, Curious Refuge live courses) increasingly default to **`veo3.1_fast` for ideation + B-roll**, and reserve `veo3.1` only for the one or two hero frames.

### `veo3` — legacy
- T2V/I2V, **`duration` must be `8` only**, ratios same as 3.1. **40 cr/sec = $0.40/sec → $3.20 per 8-s clip.** Use 3.1 unless a specific aesthetic forces it.

### `gen3a_turbo` — legacy
- I2V only. Durations `5` or `10` s. Ratios `768:1280` / `1280:768`. **5 cr/sec = $0.05/sec.**
- Strength: 24 fps, fast, dirt cheap.
- Weakness: Visibly older; no audio; lower fidelity.
- Pro pick when: Throwaway preview, A/B test of a prompt, or you need a 1280:768 ratio that exactly matches our existing Dec-2024 canon (`Ken_Fox.mp4` is 1280×768) and you don't want to crop.

### `gwm1_avatars` — real-time avatar (the audio-driven lip-sync path)
- **Endpoint async:** `POST /v1/avatar_videos`. **Endpoint realtime:** `POST /v1/realtime_sessions` (WebRTC).
- **Inputs:** `avatar` (preset id from {`game-character`, `music-superstar`, `cat-character`, `cooking-teacher`, `tennis-coach`, `influencer`, `human-resource`, `fashion-designer`, `game-character-man`} **or** `{type: "custom", avatar_id: <id from /v1/avatars>}`), `speech` (`{type: "audio", audio: <https url>}` **or** `{type: "text", text, voice}`).
- **Audio:** **Audio-driven by design.** This is the "feed an MP3, get an animated mouth" path.
- **Price:** **2 credits upfront, then 2 credits per 6 s = $0.02 base + ~$0.0033/sec.** Effectively negligible compared to other models.
- **Session cap:** 5 minutes per realtime session.
- **Strength:** The **only audio-only lip-sync** in the Runway API. Single ref image creates a talking head with no driving video required. Stylized characters supported per docs.
- **Weakness:** Avatar aesthetic is "talking head," not full-bodied performance. Fixed framing. Backgrounds are inherited from the reference image — no environmental motion. The `cat-character` preset is a real animated cat, **not Fizzlepuff**.
- **Pro pick when:** You have raw VO and just need a mouth synced. Our exact use case for the Ken VO leg of the bio intro.

[Sources: [Pricing](https://docs.dev.runwayml.com/guides/pricing/), [Tiers](https://docs.dev.runwayml.com/usage/tiers/), [Models](https://docs.dev.runwayml.com/guides/models/), [Characters concepts](https://docs.dev.runwayml.com/characters/concepts/), local `runwayml==4.12.0` SDK type stubs.]

---

## 3. The Lip-Sync API path

Runway has **three** API-callable lip-sync paths, each with a different cost
and quality envelope:

1. **`act_two` (video-driven)** — film a 3-30 s human reference saying the line, drive the character. Best perceived quality; cheapest at $0.05/sec. Works on stylized characters. **Driving-video requirements:** chest-up framing, recognizable face stays in frame, even diffuse light, no hard backlight, head rotations <30° from camera, mouth fully visible at all times. For a fox/puppet retarget, also: keep your *human reference's* head proportions roughly centered (Act-Two retargets jaw-to-jaw, so your jawline IS the puppet's jawline for that take).
2. **`gwm1_avatars` (audio-driven, async)** — POST audio + reference image, get a video with synced mouth. **No driving video needed.** Best for our Ken-VO leg. ~$0.02 base + per-second.
3. **`gen4.5` I2V with `audio: true`** — generate fresh motion from a still keyframe, with new audio, and let the model lip-sync as part of the generation. Quality is mid-tier; works when the line is short.

Aleph is **not** a lip-sync path. The web app's "Lip Sync" tool ([help.runwayml.com Creating with Lip Sync](https://help.runwayml.com/hc/en-us/articles/31941427186323-Creating-with-Lip-Sync)) is a separate web-only feature that wraps `act_two`'s underlying capability with a more constrained UI; the API exposes the same capability through `/v1/character_performance` and `/v1/avatar_videos`.

[Sources: SDK `character_performance.py`, [Multi-Character Dialogues](https://help.runwayml.com/hc/en-us/articles/41748090660499-Creating-Multi-Character-Dialogues-with-Act-Two), [acttwo.cv](https://acttwo.cv/).]

---

## 4. The "Characters" workflow programmatically

The web "Characters" library is exposed in the API via two routes:

- **Persistent custom avatars** (real-time/live talking-head): `/v1/avatars` to create + retrieve, then reference by `avatar_id` in `/v1/avatar_videos` or `/v1/realtime_sessions`. **Confirmed in the SDK** (`runwayml.resources.avatars`).
- **One-shot character lock for stills**: `/v1/text_to_image` with `model="gen4_image"` and up to **3** reference images labelled `image_1`/`image_2`/`image_3`, then route the result into `/v1/image_to_video`.

There is **no API for the Multi-Shot Video / Scene Builder web feature** as of April 2026 — those are stitched workflows in the web app. The closest API-side equivalent is `/v1/workflows` + `/v1/workflow_invocations` (visible in the SDK), which lets you save and re-run a parameterized chain.

**Cleanest API recipe for "use Ken_Fox.mp4 as canon, regenerate Ken speaking new lines":**

1. Extract a clean keyframe of Ken from `Ken_Fox.mp4` (ffmpeg, frame around t=2s where his face is centered and well-lit) → `ken_canon.png`.
2. Upload `ken_canon.png` to a public HTTPS host (S3, Cloudflare R2 signed-URL with TTL > 1h, or just a tunnel from `~/prism42/hackathon-cut/assets/`).
3. POST `/v1/text_to_image` with `model="gen4_image"`, `reference_images=[{uri: ken_canon_url, tag: "image_1"}]`, `prompt_text="@image_1 fox news anchor at desk, broadcast lighting, framed centered chest-up, eyes to camera"` → poll → get `keyframe_url`.
4. Choose lip-sync route:
   - **Option A (quality, $0.05/s):** `/v1/character_performance` with `character={type: "image", uri: keyframe_url}`, `reference={type: "video", uri: human_take_url}`, `model="act_two"`.
   - **Option B (no human take, $0.02 + cheap):** `/v1/avatar_videos` with `avatar={type: "custom", avatar_id: <ken_avatar_id>}` (create the avatar from the keyframe first via `/v1/avatars`), `speech={type: "audio", audio: ken_bio_mix_url}`.

[Sources: SDK `avatar_videos.py`, `avatars.py`, `text_to_image.py`; [Gen-4 Image References](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References).]

---

## 5. Aleph V2V — when it's the move

**It is not the move for lip-sync.** The 5-second output cap and the model's
documented use-cases (relight, object swap, weather, color, set extension,
clothing replace, light activation, time-of-day, graffiti removal — all from the
Curious Refuge "9 Ways" tutorial) make Aleph the **finishing layer**, not the
animation layer.

**Where Aleph IS the move on the bio intro:**
- **Color/lighting unity pass:** ingest the spliced bio-intro 28.8-s cut chopped into 5-s segments, run each through Aleph with `prompt_text="warm tungsten broadcast key, soft monitor glow, 35mm filmic color, slight halation"`, re-stitch. ~6 segments × 5 s × $0.15 = **$4.50** for unified color across Ken + Fizzlepuff intercut.
- **Set polish on Fizzlepuff cutaway:** re-render the puppet room with a richer neon backlight (`prompt_text="add magenta+teal neon backlight, glowstick light spill on near wall, atmospheric haze"`).
- **Camera reframe:** Aleph can convert wide → medium-tight on Ken without re-generating the performance — preserves Dec-2024 canon while letting you tighten the cut.

[Sources: [Curious Refuge 9 Ways](https://curiousrefuge.com/blog/9-ways-to-use-runway-aleph), [Aleph help](https://help.runwayml.com/hc/en-us/articles/43176400374419-Creating-with-Aleph), [Replicate model card](https://replicate.com/runwayml/gen4-aleph).]

---

## 6. Veo 3.1 vs Gen-4.5 vs Act-Two for our specific shots

| Shot | Best route | Why |
|---|---|---|
| **Ken at desk, ~26 s of dialogue** | Split: **`act_two` × 2** (one 14-s segment + one 7-s segment) using `Ken_Fox.mp4` itself as the `character` (video mode preserves environment + native motion) and your phone-shot human reference as `reference`. Fall-back: `gwm1_avatars` if no time to film a human take. | Act-Two with `character.type="video"` is *exactly* the case Runway designed for: a canon character clip that should now perform a new line. Cheap ($0.05/sec → ~$1.30 total), lip-sync is the model's primary purpose, and your existing 12-s `Ken_Fox.mp4` IS the character ref. |
| **Fizzlepuff in adjacent room dancing + yelling 1 word** | **Reuse Dec-2024 `Fizzlepuff.mp4` directly + ffmpeg-mux the new "ASSISTANT!" yell.** If the mouth doesn't match enough: `act_two` on the puppet image with a 3-s human-reference video shouting "ASSISTANT!" (`expression_intensity: 4-5`, `body_control: false`). | The puppet aesthetic forgives lip-sync imprecision; one-word yells are exactly the case where ffmpeg + audio sweetening beats a regen. Only use `act_two` if the cut feels "off." |
| **B-roll inserts (EMT/medical/dispatch)** | **`veo3.1_fast` T2V** at 1920:1080, audio off. 8-s clips at $0.80 each. | Native 1080p, fast, atmospheric. Avoid medical-procedure prompts that trip moderation; use "EMT silhouette in red and blue light" framings. |

---

## 7. API code recipes (paste-and-go)

Auth pattern: Stainless SDK reads `RUNWAYML_API_SECRET` from env, sends
`Authorization: Bearer <secret>` and `X-Runway-Version: 2024-11-06` automatically
([versioning docs](https://docs.dev.runwayml.com/api-details/versioning/)). Tasks
are **deferred**: SDK methods return a `NewTaskCreatedResponse` immediately, then
poll `/v1/tasks/{id}` until `status == "SUCCEEDED"` and `output[0]` is the
signed URL. The SDK provides `task.wait_for_task_output()` which auto-polls.

```python
# requirements: runwayml>=4.12.0, httpx
import os, time, httpx
from runwayml import RunwayML, TaskFailedError
client = RunwayML(api_key=os.environ["RUNWAYML_API_SECRET"])
```

### Recipe A — Audio-driven lip-sync of Ken (gwm1_avatars, async)
```python
# Step 1: register the Ken avatar from a clean keyframe
ken_avatar = client.avatars.create(
    name="ken-fox-canon",
    image_uri="https://YOUR_HOST/ken_canon.png",
    voice={"type": "preset", "preset_id": "drew"},  # closest-to-Harrison-Gale preset
)
# Step 2: render with our existing bio-intro mix
task = client.avatar_videos.create(
    avatar={"type": "custom", "avatar_id": ken_avatar.id},
    model="gwm1_avatars",
    speech={"type": "audio", "audio": "https://YOUR_HOST/bio-intro-mix.mp3"},
)
out = task.wait_for_task_output(timeout=600)  # blocks until SUCCEEDED
url = out.output[0]
# Wall-clock: ~60-120s. Cost: $0.02 + (29s/6 * $0.02) ≈ $0.12.
```

### Recipe B — Performance transfer via Act-Two (video-driven)
```python
task = client.character_performance.create(
    model="act_two",
    character={"type": "video", "uri": "https://YOUR_HOST/Ken_Fox.mp4"},  # canon
    reference={"type": "video", "uri": "https://YOUR_HOST/me_saying_line.mp4"},
    body_control=False,            # head/face only — Ken stays at desk
    expression_intensity=3,
    ratio="1280:720",
    seed=42,
)
out = task.wait_for_task_output(timeout=900)
# Wall-clock: 3-6 min. Cost: 14s * $0.05 = $0.70 per segment.
```

### Recipe C — Aleph color/lighting unity pass
```python
task = client.video_to_video.create(
    model="gen4_aleph",
    video_uri="https://YOUR_HOST/bio_segment_01.mp4",  # max 5s usable
    prompt_text=("Warm tungsten broadcast key light, soft cool monitor "
                 "spill from screen-left, 35mm filmic color, slight halation, "
                 "preserve all motion and framing exactly."),
    seed=7,
)
out = task.wait_for_task_output(timeout=600)
# Wall-clock: 90-180s. Cost: 5s * $0.15 = $0.75 per segment.
```

### Recipe D — Veo 3.1 Fast hero shot (anonymous-EMT silhouette B-roll)
```python
task = client.text_to_video.create(
    model="veo3.1_fast",
    prompt_text=("Silhouette of a paramedic in EMS uniform standing in a "
                 "dim ambulance bay, red and blue rotator lights wash across "
                 "the wall behind, slow push-in, 35mm anamorphic, shallow "
                 "depth of field, cinematic. No identifiable face."),
    ratio="1920:1080",
    duration=8,
    audio=False,  # we score in post
)
out = task.wait_for_task_output(timeout=600)
# Wall-clock: 90-180s. Cost: 8s * $0.10 = $0.80.
```

---

## 8. Cost optimization on $343 remaining budget (bio intro ≤$50)

| Line item | Model | Calls × duration | Unit cost | Subtotal |
|---|---|---|---|---|
| Ken keyframe (canon still) | `gen4_image` 720p | 1 × 1 frame | $0.05 | **$0.05** |
| Ken bio leg, audio-driven lip-sync (primary) | `gwm1_avatars` | 1 × 29 s | $0.02 + $0.0033/s | **$0.12** |
| Ken bio leg, performance-transfer fallback | `act_two` × 2 | 14 s + 7 s | $0.05/s | **$1.05** |
| Fizzlepuff "ASSISTANT!" lip-sync (only if ffmpeg-mux fails) | `act_two` | 1 × 3 s | $0.05/s | **$0.15** |
| Color-unity Aleph pass × 6 segments | `gen4_aleph` | 6 × 5 s | $0.15/s | **$4.50** |
| Anonymous EMT silhouette hero | `veo3.1_fast` | 1 × 8 s | $0.10/s | **$0.80** |
| Optional dispatch-room B-roll | `veo3.1_fast` | 1 × 8 s | $0.10/s | **$0.80** |
| Optional 1080p Ken hero re-roll | `veo3.1` | 1 × 8 s, audio | $0.40/s | **$3.20** |
| **Subtotal — committed path** | | | | **~$7.50** |
| **Retry budget @ 2× on lip-sync, 1.5× on Aleph** | | | | **+$5** |
| **Grand total bio intro** | | | | **~$12-15** |

This leaves **$25-35 of slack inside the bio-intro $50 ceiling** and ~$300 in
the wider $343 budget for the rest of the demo. Aggressive savings come from
choosing **`gwm1_avatars` + `veo3.1_fast`** over Act-Two + Veo-3.1.

---

## 9. Expert workflows from working filmmakers (2025-2026)

- **Curious Refuge / Tyler Smith** ([9 Ways to Use Runway Aleph](https://curiousrefuge.com/blog/9-ways-to-use-runway-aleph)): Aleph for relight, object swap, time-of-day, weather, set polish, *not* for lip-sync. Pipeline: Midjourney/Nano Banana 2 for stills → `gen4_image` for character lock → `gen4.5` or `veo3.1` for motion → Aleph for finishing → DaVinci for grade.
- **PJ Ace** (interviewed by Curious Refuge, [@PJaccetturo](https://x.com/PJaccetturo)): Veo + Aleph stack for ad spots. Shoots talent on real cameras when possible, uses Aleph to reframe and re-light. Cuts everything in Premiere.
- **Min Choi** ([@minchoi](https://x.com/minchoi)): Public Aleph showcases since Aug-2025; uses Aleph chained with `gen4.5` for short-form viral spots. Treats Aleph as the "VFX layer."
- **Karen X Cheng**: Brand ad work using Runway References + Veo for hero spots; ComfyUI for stylized stills. Heavy editorial in Premiere.
- **Theoretically Media (Tim Simmons)**: YouTube tutorials emphasizing reference-pack workflows on `gen4_image` + `gen4.5` chain. Treats `veo3.1_fast` as the cheap-ideation tier.
- **Bobby Bot**: Character-driven shorts using Act-One/Act-Two; films himself on a phone as the human reference for puppet/animal characters.
- **Iván Verde Albizua / Runway Academy**: Multi-character Act-Two dialogue scenes — same human ref, two character outputs, intercut in Resolve.
- **Common pipeline shape:** Runway as the **animation engine**; Midjourney/Nano-Banana as the **still-image atelier**; ComfyUI for **fine-tune / specific aesthetics**; DaVinci Resolve or Premiere for **grade + sound + delivery**. Almost no working filmmaker uses Runway end-to-end; the cuts and the grade live in a real NLE.

---

## 10. Munger inversion — how this plan fails

| Failure mode | Mitigation |
|---|---|
| **Tier-1 rate limit (1 concurrent task / 50 daily gens per model)** | Serial async. Don't fan out — submit, poll, submit next. Daily 50-gen ceiling is plenty for a 25-shot demo if no >5× retry waste. |
| **Content moderation rejects "EMT"/"medical" prompts** | Use atmosphere words, not procedure words. "Paramedic silhouette in ambulance bay" passes; "EMT inserting IV" gets flagged. Set `content_moderation.public_figure_threshold: "auto"` (default). |
| **Act-Two retargets jawline to your human reference, not the fox** | Frame the human reference chest-up, centered, head proportions matching the character. Keep `expression_intensity ≤ 3`. If still wrong: route to `gwm1_avatars` instead. |
| **Lip-Sync visibly wrong on Fizzlepuff puppet** | Don't generate it. The bio joke is one word ("ASSISTANT!") on a 2-s cutaway — ffmpeg-mux the existing canon clip with the new ElevenLabs yell. Lip-sync precision irrelevant on a 1-frame entry. |
| **Signed-URL TTL expires before download** | Always download immediately on `SUCCEEDED`. Persist locally to `clips/`. The existing `runway_api_batch.py` already does this — reuse the `download_url_to()` helper. |
| **Async polling deadlocks (task stuck in `PROCESSING`)** | Hard timeout per task: `wait_for_task_output(timeout=900)` for video, `timeout=600` for image. On timeout: cancel via `client.tasks.delete(id)` and resubmit with new seed. |
| **Aleph 5-s cap silently truncates a 12-s input** | Pre-slice the input to ≤5-s segments before submit. Re-stitch in ffmpeg afterward. The first 5 s of input is what gets processed; everything after is dropped. |
| **`veo3.1` audio output mismatches our ElevenLabs VO** | Submit Veo with `audio: false` (-50% cost) and mux ElevenLabs in post. Only enable Veo audio when generating ambient SFX you don't already have. |

---

## DROP-IN PIPELINE — execute in this order

Each step is an immediate API call. Pre-condition: `RUNWAYML_API_SECRET` set;
`Ken_Fox.mp4`, `Fizzlepuff.mp4`, `bio-intro-mix.mp3` already on a public HTTPS
host (S3 / Cloudflare R2 / `python -m http.server` + ngrok tunnel). All Python
snippets assume `client = RunwayML(api_key=os.environ["RUNWAYML_API_SECRET"])`.

### Step 1 — Extract Ken canon keyframe (local, no API)
```bash
ffmpeg -y -ss 2.0 -i assets/Ken_Fox.mp4 -frames:v 1 -q:v 2 assets/ken_canon.png
```
Cost $0. Wall ~1s.

### Step 2 — Lock Ken canon as a Gen-4 reference still
```python
task = client.text_to_image.create(
    model="gen4_image",
    prompt_text=("@image_1 anthropomorphic red fox news anchor at glossy "
                 "broadcast desk, charcoal pinstripe three-piece suit, "
                 "crimson tie, soft tungsten key, slight monitor cyan rim, "
                 "framed centered chest-up, eyes to camera, 1280x720"),
    reference_images=[{"uri": "https://HOST/ken_canon.png", "tag": "image_1"}],
    ratio="1920:1080",
)
keyframe_url = task.wait_for_task_output(timeout=300).output[0]
```
Output: `keyframe_url` (1080p PNG). Cost **$0.08**. Wall ~30s.

### Step 3 — Register Ken as a custom GWM-1 avatar
```python
ken_avatar = client.avatars.create(
    name="ken-fox-canon",
    image_uri=keyframe_url,
    voice={"type": "preset", "preset_id": "drew"},
)
```
Output: `ken_avatar.id`. Cost **$0** (creation is free). Wall ~5s.

### Step 4 — Audio-driven lip-sync of full bio VO (primary path)
```python
task = client.avatar_videos.create(
    avatar={"type": "custom", "avatar_id": ken_avatar.id},
    model="gwm1_avatars",
    speech={"type": "audio", "audio": "https://HOST/bio-intro-mix.mp3"},
)
ken_lipsync_url = task.wait_for_task_output(timeout=600).output[0]
```
Output: lip-synced Ken speaking the full 28.8 s. Cost **$0.12**. Wall ~2min.

### Step 5 — Color-unity Aleph pass on the spliced cut (optional finisher)
```bash
# pre-slice to <=5s segments
ffmpeg -y -i bio_intro_master.mp4 -c copy -f segment -segment_time 5 \
       -reset_timestamps 1 final/seg_%02d.mp4
```
```python
unified = []
for i, seg_url in enumerate(public_seg_urls):  # 6 segments
    t = client.video_to_video.create(
        model="gen4_aleph",
        video_uri=seg_url,
        prompt_text=("Warm tungsten broadcast key, soft cyan monitor spill, "
                     "35mm filmic color, slight halation, preserve all "
                     "motion and framing exactly. Documentary news register."),
        seed=7,
    )
    unified.append(t.wait_for_task_output(timeout=600).output[0])
```
Output: 6 color-matched 5-s segments → re-stitch in ffmpeg. Cost **$4.50**. Wall ~12 min.

### Step 6 — Anonymous EMT silhouette B-roll (optional hero insert)
```python
task = client.text_to_video.create(
    model="veo3.1_fast",
    prompt_text=("Silhouette of a paramedic in EMS uniform standing in a "
                 "dim ambulance bay, red and blue rotator lights washing "
                 "the wall behind, slow push-in, 35mm anamorphic shallow DOF, "
                 "cinematic, no identifiable face, no on-screen text."),
    ratio="1920:1080",
    duration=8,
    audio=False,
)
emt_url = task.wait_for_task_output(timeout=600).output[0]
```
Output: 8-s 1080p silhouette plate. Cost **$0.80**. Wall ~3 min.

### Step 7 — Final mux (local ffmpeg, no API)
```bash
# replace Step 4's video audio with the canonical ElevenLabs mix
ffmpeg -y -i ken_lipsync.mp4 -i vo/bio-intro-mix.mp3 -map 0:v -map 1:a \
       -c:v copy -c:a aac -shortest final/bio_ken_lipsync.mp4
# splice with Fizzlepuff cutaway (existing canon)
ffmpeg -y -f concat -safe 0 -i final/concat.txt -c copy final/bio_intro.mp4
```
Cost **$0**. Wall ~1 min.

### Step 8 — Stop. Inspect. Cut into the demo.

**Total committed pipeline cost: ~$5.50.** Worst-case with all retries + Veo 3.1
1080p hero re-roll: **~$15.** Sub-half of the $50 ceiling.

---

**End of file.**

[Sources: [docs.dev.runwayml.com](https://docs.dev.runwayml.com/), [API pricing](https://docs.dev.runwayml.com/guides/pricing/), [Tiers](https://docs.dev.runwayml.com/usage/tiers/), [Models](https://docs.dev.runwayml.com/guides/models/), [Characters concepts](https://docs.dev.runwayml.com/characters/concepts/), [Versioning](https://docs.dev.runwayml.com/api-details/versioning/), [Changelog](https://docs.dev.runwayml.com/api-details/api_changelog/), [Product changelog](https://runwayml.com/changelog), [Introducing Characters](https://runwayml.com/news/introducing-runway-characters), [Creating with Aleph](https://help.runwayml.com/hc/en-us/articles/43176400374419-Creating-with-Aleph), [Creating with Act-Two](https://help.runwayml.com/hc/en-us/articles/42311337895827-Creating-with-Act-Two), [Multi-Character Dialogues](https://help.runwayml.com/hc/en-us/articles/41748090660499-Creating-Multi-Character-Dialogues-with-Act-Two), [Gen-4 Image References](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References), [Curious Refuge — 9 Ways](https://curiousrefuge.com/blog/9-ways-to-use-runway-aleph), [Replicate gen4-aleph](https://replicate.com/runwayml/gen4-aleph), [acttwo.cv](https://acttwo.cv/), local `runwayml==4.12.0` Python SDK type stubs.]
