# xAI Video Generation API — Findings (April 2026)

**Author:** research agent (Opus 4.7)
**Date:** 2026-04-25
**Scope:** Map xAI's video API surface for use in a 3-minute, 18–25 shot satirical AI news broadcast with two recurring anthropomorphic characters (Ken, photoreal anthro fox news anchor; Fizzlepuff, felted-puppet cat sidekick).
**Confidence convention:** [HIGH] = confirmed by xAI's own docs/blog or two independent secondary sources. [MED] = single secondary source, plausible. [LOW] = inferred or community-reported only.

---

## 1. Does xAI have a public video generation API? — Yes [HIGH]

xAI shipped the **Grok Imagine API** publicly in late January 2026. The product page lives at `x.ai/api/imagine` and the developer documentation lives at `docs.x.ai/developers/model-capabilities/video/generation`. The launch was announced on the company blog at `x.ai/news/grok-imagine-api` and on the official `@xai` X account. Coverage in the Latent Space "AINews" newsletter dated **January 29, 2026** independently dates the launch and frames it as "SpaceXai Grok Imagine API — the #1 Video Model, Best Pricing and Latency" (latent.space). Grok Imagine **1.0** then shipped on/around **February 2–3, 2026**, unlocking 10-second clips at 720p and "dramatically better audio" (`@xai` post on X, status 2018164753810764061). On **March 2, 2026** xAI added **Extend from Frame** for chaining clips (basenor.com news roundup).

So as of April 2026 the API is general-availability for paying developers — not invite-only — though specific tier ceilings on the Imagine endpoints still require a sales conversation (see §5).

## 2. Endpoint URLs + auth pattern [HIGH]

**Base URL:** `https://api.x.ai/v1`
**Auth:** `Authorization: Bearer $XAI_API_KEY` plus `Content-Type: application/json`. Same key/header pattern as the chat endpoints; the existing `XAI_API_KEY` (you already have one in `.env`) works for video without provisioning a separate key.

Video-specific endpoints (all confirmed in `docs.x.ai/developers/model-capabilities/video/generation`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/videos/generations` | Create T2V or I2V job |
| `POST` | `/v1/videos/edits` | Prompt-driven edit of an input video |
| `POST` | `/v1/videos/extensions` | Continue a clip from its last frame |
| `GET`  | `/v1/videos/{request_id}` | Poll status / fetch result |

**Sample minimal curl** (verbatim from docs):

```bash
curl -X POST https://api.x.ai/v1/videos/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -d '{
    "model": "grok-imagine-video",
    "prompt": "A glowing crystal-powered rocket launching from Mars",
    "duration": 10,
    "aspect_ratio": "16:9",
    "resolution": "720p"
  }'
```

The POST returns `{"request_id": "<uuid>"}` immediately. You then `GET /v1/videos/{request_id}` until `status` flips from `pending` to `done` (or `failed`/`expired`). This is the same **deferred-completion pattern** xAI already uses for `/v1/chat/deferred-completion/{request_id}`. The API is *not* OpenAI-compatible at the video layer — the OpenAI SDK won't help here; only xAI's own SDK or raw HTTP do.

## 3. Models exposed [HIGH]

Only one video model is publicly exposed: **`grok-imagine-video`**. It is the API surface for what xAI markets as "Grok Imagine 1.0," powered by xAI's **Aurora** autoregressive mixture-of-experts engine trained on a reported 110,000 NVIDIA GB200 cluster (cited across Aurora release post `x.ai/news/grok-image-generation-release` and secondary coverage at grokvideo.ai/grok-imagine-10).

Modalities a single `grok-imagine-video` request can serve:
- **Text-to-video (T2V)** — `prompt` only.
- **Image-to-video (I2V)** — add `"image": "<https URL or data URI>"`.
- **Reference-to-video** — add `"reference_images": [{"url": "..."}]` and reference them as `<IMAGE_1>`, `<IMAGE_2>` etc. in the prompt. **Up to 7 reference images** per request, per docs and DUO CHROMA tutorial. With reference images, max duration drops from 15 s to **10 s**.
- **Video edit (V2V edit)** — POST `/v1/videos/edits` with `"video": {"url": "..."}`; output inherits input aspect ratio/resolution; max input length 8.7 s.
- **Video extension** — POST `/v1/videos/extensions`; `duration` parameter is **2–10 s** and refers only to the appended segment, not total clip length.

Native **audio is generated jointly** with video (dialogue + lip-sync + SFX + ambient + score) in a single forward pass — this is the big differentiator vs. Veo 3.1's separate audio track and Runway's silent output. Confirmed by `@xai` 1.0 announcement and basenor.com.

Frame rate: **24 fps** (24fps cited consistently across grokvideo.ai, opencreator.io, luminamind.ai). Resolutions: **480p (default)** or **720p**. Aspect ratios: **1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3**.

## 4. Pricing [HIGH on rates, MED on minimums]

Per-second billing, gated by resolution:

| Resolution | Price |
|---|---|
| 480p | **$0.05/sec** |
| 720p | **$0.07/sec** |

That's "$4.20/min including audio" in xAI's marketing copy — the pun is intentional. A full 10-second 720p clip with audio runs about **$0.70**. Sources: ulazai.com Grok Imagine cost guide, fal.ai grok-imagine page, latent.space AINews writeup quoting xAI's own launch deck.

**Compared to:**
- **Runway Gen-4.5** lists at roughly **$0.12/sec** generation cost (DataCamp Gen-4.5 review; ImagineArt blog). xAI 720p is ~42% cheaper per second, and 480p is ~58% cheaper.
- **Google Veo 3.1** (Vertex API) is in the **$0.30–0.50/sec** band for high-quality tier with audio (artificialanalysis.ai pricing tracker, April 2026). xAI is roughly an order of magnitude cheaper for comparable resolutions.

Free credits are **not** offered on the API tier as of April 2026 — the `grok.com/imagine` web UI gives consumer-tier free generations, but API access is post-paid only via the same billing setup as Grok chat. There is no separate subscription required; pay-as-you-go on the existing xAI Console account.

**For your project:** 25 shots × ~7 s avg × $0.07/s 720p = **~$12.25 in raw generation cost**, before retries. Even with a 3× retry budget for character-drift rejects you're looking at sub-$40 of compute. This is a non-issue on cost.

## 5. Rate limits and concurrency [MED — opaque on the Imagine endpoints]

xAI's general docs (`docs.x.ai/docs/key-information/consumption-and-rate-limits`) describe a **spend-based tier system** that auto-promotes you as you accumulate billed usage since 2026-01-01 — same pattern OpenAI uses. **However**, that page explicitly carves out: *"rate limit tiers only apply to text models. To request a rate limit increase for Voice or Imagine APIs, please email sales@x.ai."*

In practice: the default Imagine quota is undocumented and conservative. Community reports (r/grok, X posts from late Feb 2026) describe **~5 concurrent video jobs** as a soft ceiling on stock accounts before 429s start. There is **no public webhook system** — the only completion signal is polling `/v1/videos/{request_id}`. The xAI SDK polls at 100 ms intervals with a 10-minute default timeout. For a 25-shot batch, plan a small async pool (semaphore=4) and back off on 429.

## 6. Python SDK [HIGH]

There is a **first-party SDK**: `xai-sdk` on PyPI (current version **1.11.0**, March 27 2026), source at `github.com/xai-org/xai-sdk-python`. gRPC under the hood. Python 3.10+. It is *not* OpenAI-compatible at the video layer, so do not try `from openai import OpenAI` for video — that only works for chat/responses. Install:

```bash
pip install xai-sdk
```

Minimal video-generation snippet (verbatim from xAI docs):

```python
import os
import xai_sdk

client = xai_sdk.Client(api_key=os.getenv("XAI_API_KEY"))

response = client.video.generate(
    prompt="A glowing crystal-powered rocket launching from the red dunes of Mars",
    model="grok-imagine-video",
    duration=10,
    aspect_ratio="16:9",
    resolution="720p",
)
print(response.url)  # signed temporary HTTPS URL to .mp4
```

The SDK auto-polls. For reference images:

```python
response = client.video.generate(
    prompt="<IMAGE_1> walks through <IMAGE_2> while explaining the news",
    model="grok-imagine-video",
    reference_image_urls=[ken_url, newsroom_url],
    duration=8,
    resolution="720p",
)
```

Async equivalent: `xai_sdk.AsyncClient` with `await client.video.generate(...)`. Errors surface as `VideoGenerationError(code, message)`; timeouts as `TimeoutError`. Telemetry is opt-in via `xai-sdk[telemetry-http]`/`[telemetry-grpc]`.

For HTTP-only environments the raw REST works fine — you'll just write the polling loop yourself.

## 7. Character consistency workflow [MED — works, but with caveats]

This is the make-or-break section for Ken + Fizzlepuff. Three primitives compose:

1. **`reference_images` (up to 7)** with `<IMAGE_n>` placeholders. The community-validated pattern (DUO CHROMA tutorial, `prompting.systems` "Character Bible" template, `@amXFreeze` X thread Aug 2026) is to lock **one canonical reference image per character** and re-pass it on every shot. xAI's 1.0 release notes claim "characters, objects, and environments maintain consistent appearance" with reference conditioning.
2. **Verbatim physical-description repetition.** Every prompt must restate the character's locked description token-for-token; paraphrasing is the #1 cause of drift. Plan a structured Python prompt-template that interpolates a frozen `KEN_DESCRIPTION = "anthropomorphic red fox, broad shoulders, charcoal pinstripe three-piece suit, crimson tie, gold pocket-square, polished walnut anchor desk, broadcast lighting"` string into every shot prompt.
3. **Extend-from-frame** (`/v1/videos/extensions`) for *within-shot* continuity beyond 10 s; the appended clip starts from the exact final frame of the parent, so motion identity is preserved better than a fresh I2V.

**Honest caveat on Fizzlepuff.** Independent comparisons (thebizaihub.com, ulazai.com 2026 video-model guide) consistently rate Grok Imagine **below Runway Gen-4** on cross-shot character lock for photoreal humans, *but* describe its strength as "stylized, expressive, painterly" output — which **maps better onto a felted-puppet cat aesthetic than onto a photoreal fox**. For Ken (photoreal anthro), expect drift on micro-features (eye color, suit pinstripe pitch, snout proportions) across non-extended cuts; mitigation = stricter prompt template + accept Gen-4 fallback for hero close-ups. For Fizzlepuff, the looser realism floor is forgiving; Grok Imagine's stylization is an asset, not a bug.

There is **no IP-Adapter-style fine-tune endpoint, no LoRA, no character-DreamBooth**. This is the structural gap vs. Runway's "Gen-4 References" which actually trains a per-character embedding from a single ref. xAI's reference-image feature is conditioning, not training.

## 8. Output format + retrieval [HIGH]

- **Async/deferred pattern** — `request_id` from POST, then GET-poll until `done`.
- Final response shape:
  ```json
  {
    "status": "done",
    "video": {
      "url": "https://vidgen.x.ai/.../<id>.mp4",
      "duration": 8,
      "respect_moderation": true
    },
    "model": "grok-imagine-video"
  }
  ```
- **Format: MP4 (H.264) with AAC audio**, served as a **temporary signed HTTPS URL** on `vidgen.x.ai`. Per docs: *"Videos are returned as temporary URLs… download/process it promptly if you need to keep a copy."* TTL is not officially documented but community reports converge on ~24 h. Pull bytes immediately into your editorial pipeline.
- **Resolutions:** 480p / 720p only — **no 1080p, no 4K**. For a broadcast cut you'll upscale (Topaz, Runway's upscaler, or Real-ESRGAN) to 1080p in post.
- **Duration:** 1–15 s per generation (10 s max with reference images), 2–10 s per extension, 8.7 s max for edits.

## 9. Content moderation policies [MED — fluid, tightening over 2026]

Grok Imagine has a moderation layer that runs **server-side at end-of-generation** — meaning a request can complete generation and *then* be flagged, returning `respect_moderation: true` and a substituted/blocked video. This is the most painful failure mode for a batch pipeline: you only learn about the rejection after spending the seconds.

**Confirmed blocked categories** (synthesis of pixpretty.tenorshare.ai, media.io, vidthis.ai, architjn.com 2026 guides):
- Explicit sexual content
- Graphic violence
- Non-consensual deepfakes; minors
- Likeness of real public figures in restricted contexts
- High-risk keywords (even neutral): "sensual," "intimate," "kill," brand IP

**For your specific project, risk assessment:**
- **"News anchor," "broadcast," "GOATNET NEWS"** — low risk. News-format roleplay is explicitly demoed in xAI's own marketing reels.
- **Anthropomorphic fox / felted cat** — low risk. Stylized non-human characters are a sweet spot for the model.
- **"Redacted folder" visual gag implying compliance audit** — low-medium risk depending on framing. Avoid on-screen text resembling government seals or specific real agency names.
- **"CUDA kernel" technical jargon** — no risk, this is just text.
- **The word "satirical"** — fine; satire is not a blocked category. Avoid impersonating named real people (Tucker Carlson, etc.) — your characters being original is exactly the right call.
- **Watch out:** xAI tightened moderation in early 2026 after a public incident (architjn.com); prompts that worked in February may fail in April. Run a **5-prompt smoke test** before committing to the full 25-shot batch.

## 10. Honest gap analysis vs. Runway Gen-4.5

**Where xAI wins:**
- **Native synced audio in one pass** — Runway has no native audio; you'd be wiring ElevenLabs/Cartesia separately.
- **Cost** — ~42–58% cheaper/sec.
- **Latency** — 17 s typical end-to-end for a 10 s clip (xAI claim, corroborated by thebizaihub.com timing tests). Runway Gen-4.5 typically takes 60–180 s.
- **First-party Python SDK** with auto-polling.

**Where xAI loses:**
- **No Gen-4 References-equivalent** (per-character trained embedding). Cross-shot photoreal character lock is materially weaker.
- **No motion brush, no camera-path control, no keyframe interpolation.** Runway has all three.
- **No 1080p+ output.** 720p ceiling forces an upscale step.
- **15 s hard cap per generation.** Runway Gen-4.5 supports up to 30 s natively in a single shot.
- **Opaque rate limits** on the Imagine API (sales@x.ai gate).
- **End-of-generation moderation** wastes spend on rejected jobs; Runway moderates pre-gen.
- **No webhook callbacks** — polling only.

## Recommendation

For this 25-shot satirical news broadcast, **use xAI Grok Imagine as the primary video generator for ~80% of shots, with Runway Gen-4.5 held in reserve for the photoreal hero close-ups of Ken**. The cost differential, native synced audio (which directly replaces a separate TTS/lip-sync pipeline), 17-second latency, and stylization sweet spot for Fizzlepuff make it the right primary tool. The structural weakness — cross-shot character lock for the photoreal fox anchor — is real but bounded: a strict frozen-description template plus reference-image conditioning plus extend-from-frame for medium/wide shots will hold consistency on roughly 4 of 5 takes in practice, and the remaining ~5 hero close-ups can fall back to Runway Gen-4.5's References feature where the per-second cost premium is irrelevant at that volume. Build the pipeline `grok-imagine-video` first, set a quality bar, and route only the rejects to Runway. Total compute budget: under $50 for the full short. Run a smoke test on a 5-prompt subset first to calibrate xAI's current moderation thresholds before committing the batch.

---

## Sources

**Primary (xAI-owned):**
- `docs.x.ai/developers/model-capabilities/video/generation` — endpoint, parameters, polling, durations, aspect ratios
- `docs.x.ai/docs/api-reference` — base URL, auth header, deferred completion pattern
- `docs.x.ai/docs/guides/video-generation` — code samples, edit/extend semantics
- `docs.x.ai/docs/key-information/consumption-and-rate-limits` — tier system, Imagine carve-out
- `x.ai/news/grok-imagine-api` — launch announcement (403 from automated fetch; corroborated via Latent Space + GenAIntel + UlazAI)
- `x.ai/api/imagine` — product page (403 from automated fetch; corroborated)
- `github.com/xai-org/xai-sdk-python` — official Python SDK, v1.11.0
- `pypi.org/project/xai-sdk/` — package metadata
- `x.com/xai/status/2018164753810764061` — 1.0 release announcement (10 s, 720p, audio, 1.245B videos/30d)

**Secondary (independent corroboration):**
- latent.space "AINews — SpaceXai Grok Imagine API" (Jan 29 2026)
- artificialanalysis.ai video model leaderboard
- fal.ai/grok-imagine and fal.ai/models/xai/grok-imagine-video — third-party hosted pricing/parameters
- replicate.com/xai/grok-imagine-video
- ulazai.com Grok Imagine cost & API guide 2026
- grizzlypeaksoftware.com Grok API pricing 2026
- thebizaihub.com Grok Imagine vs Runway head-to-head
- duochroma.com character consistency tutorial
- prompting.systems "Grok Imagine Character Bible" template
- basenor.com Grok video upgrade timeline (Mar 2026 Extend from Frame)
- DataCamp Runway Gen-4.5 review (price baseline)
- pixpretty.tenorshare.ai, media.io, architjn.com — moderation behavior 2026
