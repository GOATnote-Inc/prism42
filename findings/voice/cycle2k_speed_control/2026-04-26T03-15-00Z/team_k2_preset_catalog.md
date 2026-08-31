# Team K2 — Fish preset voice catalog

Read-only investigation. No code edits, no pod commands, no commits.
All retrieval dates 2026-04-25 / 2026-04-26.

## TL;DR (one paragraph)

Self-hosted Fish-Speech ships **zero preset voices**. The
`reference_id` parameter on a self-hosted server is a pure on-disk
lookup of `references/<id>/` — the engine literally reads
`Path("references") / id` and concatenates audio + `.lab` transcript
files inside that directory
([reference_loader.py:62-97][1]). It is **not** a cloud catalog
lookup. Any cloud Fish-Audio voice slug (e.g.
`fish.audio/m/c2623f0c...`) will return "no audio files found" on a
self-hosted pod unless we first download the audio and hand-install
it under `references/<slug>/`. Worse, the cloud Voice Library is
**personal-use only on the free tier** — pulling a community voice
to a self-hosted production server requires a paid Fish-Audio plan
to unlock commercial-use rights for that voice. Production already
has one preset wired and live: `psap` (a macOS `say -v Samantha`
recording, see `setup_psap_reference.sh`). It is the *only* preset
available on the pod today. K1's speed-knob path is the durable
fix; reference-voice swaps cannot fix the slow-cadence symptom.

## Self-hosted vs cloud

Our deployment is self-hosted at `:9200`. The `reference_id` path
on a self-hosted Fish-Speech server resolves to: **on-disk lookup,
no cloud delegation**. Specifically:

- `TTSInferenceEngine.inference()` at
  `~/prism42/vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-52`
  branches on `req.reference_id` and calls
  `self.load_by_id(ref_id, req.use_memory_cache)`.
- `ReferenceLoader.load_by_id()` at
  `~/prism42/vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:62-97`
  builds `ref_folder = Path("references") / id`, calls
  `ref_folder.mkdir(parents=True, exist_ok=True)` (note: silently
  creates an empty dir if absent), and lists audio files via
  `list_files(ref_folder, AUDIO_EXTENSIONS, recursive=True)`. If
  the dir is empty (no audio + `.lab` pair), `prompt_tokens` and
  `prompt_texts` come back as empty lists. Generation then
  proceeds with NO conditioning — silently falling back to the
  base model's distribution.
- ID validation regex at
  `~/prism42/vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:20`:
  `^[a-zA-Z0-9\-_ ]+$`, max 255 chars. A Fish-cloud 32-char hex
  slug passes the regex (alphanumeric only) but the on-disk dir
  doesn't exist — silent no-op + silent `mkdir` of an empty dir.
- The schema-comment hint at
  `~/prism42/vendor/fish-speech/fish_speech/utils/schema.py:91-93`:
  `# For example, if you want use https://fish.audio/m/7f92f8afb8ec43bf81429cc1c9199cb1/` /
  `# Just pass 7f92f8afb8ec43bf81429cc1c9199cb1` is misleading
  for self-hosted users. It only works against `api.fish.audio`
  (the cloud) where Fish maintains the voice corpus. The self-
  hosted server uses the same field name with **completely
  different semantics**.

There is **no built-in catalog of preset voices** in the Fish-
Speech open-source distribution. The Fish-Audio docs confirm:
*"Create a `references/` directory in the project root … Place
files in each subdirectory"*
([Fish Audio self-hosting docs][2], retrieval 2026-04-25). The
folder ships empty.

## Known presets

### What's actually on the pod's `references/` dir today

Inferred from `~/prism42/infra/b300/services/fish-speech/setup_psap_reference.sh`
(verified-by-source):

| preset_id | voice character | cadence | license | source | hosted at |
|---|---|---|---|---|---|
| `psap` | Female, US English (macOS `say -v Samantha`), 12.14 s reference, "Nine one one, what is the address of your emergency. …" | Audiobook-baseline (no inline `[tag]` directives in the reference clip → cadence drifts toward Fish's audiobook prior at RTF ~1.96) | macOS Apple system voice → Apple Software License Agreement; commercial PSAP-product use needs Apple legal review. The `say` voice is bundled with macOS for end-user TTS, not for redistribution as a cloned reference voice. **Open license risk.** | `setup_psap_reference.sh` step 1 (laptop-side `say` + `ffmpeg`); installed at `/opt/prism42/infra/b300/services/fish-speech/references/psap/{ref.wav,ref.lab}` | self-hosted on B300 pod (cannot verify directly without SSH; flagged for K3) |

That is the **complete current catalog on the self-hosted pod**.
There is no second preset, no third preset.
`tools/server/views.py` exposes `GET /v1/references/list`
which returns the directory listing — Team K3 (or any operator
with pod access) can call that endpoint to enumerate the actual
on-disk state.

### What ships in the `vendor/fish-speech/` tree

Verified by `find ~/prism42/vendor/fish-speech -name "*.lab"`
and `find … -type d -name "references"`: **zero results**. The
upstream repo ships **no sample voices, no preset voices, no demo
voices**.

### What Fish-Audio cloud has (for reference, NOT self-hosted-usable as-is)

The cloud catalog is searchable at `https://fish.audio/voice-library/`.
URL pattern for an individual voice page: `fish.audio/m/<32-char-hex>/`
(also addressable as `fish.audio/app/m/<32-char-hex>/`). Tag
taxonomy on cards (claimed-by-website, retrieval 2026-04-25):
Pitch (Deep / Low / Medium / High / Soft / Bright / Warm / Dark /
Raspy / Smooth / Breathy / Husky), Energy (Energetic / Calm /
Relaxed / Fast / Slow / Measured / Dynamic), Emotion (Sexy /
Friendly / Professional / Serious / Cheerful / Enthusiastic /
Confident / Authoritative / Gentle / Empathetic / Playful /
Dramatic / Intimate / Mysterious / Sad / Angry), Delivery (Clear /
Crisp / Neutral Tone / Expressive / Monotone / Animated /
Storytelling), Demographics (Gender, Age).

| cloud_slug (`reference_id` on cloud only) | voice character | cadence tag | license | source |
|---|---|---|---|---|
| `c2623f0c075b4492ac367989aee1576f` (Paula) | Female, English (general American implied, not explicitly tagged), middle-aged, "professional and clear" | Conversational, Professional, Confident, Clear, Friendly | Cloud Voice Library entry. Free for personal use; **commercial requires paid Fish-Audio plan** ($5.50/mo+ tier per [Fish-Audio pricing][3]). | claimed-by-website [Paula voice page][4] |
| `b347db033a6549378b48d00acb0d06cd` (Selene) | Female, English (general American implied), middle-aged, "meditative" | Soft, Calm, Gentle, Intimate, Breathy, ASMR — **too breathy for dispatch** | same as Paula | claimed-by-website [Selene voice page][5] |
| `b545c585f631496c914815291da4e893` (Friendly Women) | Female, young, English | Bright, Energetic, Professional, Clear — **likely too high-energy for distressed-caller dispatch** | same as Paula | claimed-by-website (Voice Library card surfaced by Discovery search 2026-04-25) |
| Sarah / Adrian / Brian / Ethan / Dolly | Various character voices used as Fish-Audio site demo placeholders | Variable; tagged to Documentary / Curious / Narration / Educational / Sexy-Smooth respectively | same as above (paid for commercial) | claimed-by-website [Voice Library landing page][6] |

**License impact for self-hosted production**: even if K3 ports a
cloud slug to the pod by downloading the audio sample and dropping
it at `references/<slug>/`, the **voice itself is licensed by
Fish-Audio's commercial-rights paywall**. Free-tier downloads
carry "personal use only" terms ([Fish-Audio pricing][3], retrieval
2026-04-26). Using a Voice Library asset as the production voice
on `www.thegoatnote.com/prism42` without a paid Fish-Audio
subscription violates Fish's TOS. This is a separate license
concern from the FARL on the model weights themselves.

## Top 3 candidates for US-911-dispatcher use

Filtered by: US General American, calm, authoritative,
conversational pace (not audiobook), commercial-use feasible on a
self-hosted pod.

### 1. Stay on the current `psap` preset (in-place) — **DO NOT pivot**

Rationale: It already exists on the pod, it's already wired
(`FISH_SPEECH_REFERENCE_ID=psap` in the worker env per
`setup_psap_reference.sh:47`), and the user's reported speed
problem is **not** the reference voice. K1's audit is investigating
the speed-knob symptom (`temperature 0.1`, `top_p 0.7`,
`chunk_length 200`, `seed 911`, frame_buffer 200 ms). Per the
current adapter at
`~/prism42/agents/livekit/fish_speech_tts.py:60-73`,
all four sampling/streaming knobs are at the schema floor —
voice-cloning input timbre cannot rescue tokenizer-level pacing if
those knobs aren't right. A voice swap would just exchange one
audiobook-prior voice for another.

How to enable: already enabled. No action needed. The pod restart
sequence is `setup_psap_reference.sh` step 4-5.

### 2. Generate a *new* `psap-fast` preset from a faster reference clip — **viable if K1 confirms reference-clip cadence influences output cadence**

Rationale: Fish's reference-conditioning learns timbre, prosody,
*and* pacing from the reference. The current `psap` reference is a
synthesized macOS `say` clip that itself runs slow ("audiobook
narrator" cadence). If we re-record at conversational dispatcher
speed (e.g. `say -v Samantha -r 230` for 230 wpm vs `say`'s ~175
wpm default), the cloned voice should inherit that cadence.
Verified-by-source: K1's research probe (referenced in the durable
findings memo at `<owner-memory>/prism42_b300_voice_durable_findings.md`,
finding #1) confirms determinism with `seed=911`, so the influence
of reference-clip cadence is testable in isolation.

How to enable (for K3 / integrator):

```
say -v Samantha -r 230 -o /tmp/psap_fast.aiff \
  "Nine one one, what is the address of your emergency. Stay on the line with me, help is on the way. Are you able to speak in full sentences right now. Help is coming."
ffmpeg -y -i /tmp/psap_fast.aiff -ar 44100 -ac 1 -sample_fmt s16 /tmp/psap_fast.wav
scp /tmp/psap_fast.wav b300-pod:/tmp/psap_fast.wav
ssh b300-pod 'sudo mkdir -p /opt/prism42/infra/b300/services/fish-speech/references/psap-fast && \
  sudo cp /tmp/psap_fast.wav /opt/prism42/infra/b300/services/fish-speech/references/psap-fast/ref.wav && \
  echo "Nine one one, what is the address of your emergency. Stay on the line with me, help is on the way. Are you able to speak in full sentences right now. Help is coming." | \
    sudo tee /opt/prism42/infra/b300/services/fish-speech/references/psap-fast/ref.lab >/dev/null'
# then in worker .env: FISH_SPEECH_REFERENCE_ID=psap-fast
# (existing .env value `psap` is what gets replaced; mutex-OK since
# `references` inline path requires id empty per
# vendor/.../inference_engine/__init__.py:48-57)
sudo systemctl restart prism42-worker
```

License: Apple voice → same posture as #1 (acceptable for hackathon
demo per HACKATHON MODE §0; needs legal review before public PSAP
launch).

**Caveat**: Whether reference-clip cadence in fact dominates over
`temperature` / `top_p` / `chunk_length` is **unverified** in this
repo. K1's speed-knob audit is the primary path; this is a
fallback only. If the speed problem persists with both knobs and
fast-clip set, the bottleneck is elsewhere (Fish RTF 1.96 → 0.7
patch in cycle-2d-fish-patches addresses *generation throughput*
not *speech tempo*).

### 3. Generate a `dispatch-female-us` preset from a consented internal voice or a CC-0 dataset clip — **the durable-license option, off the hackathon critical path**

Rationale: Both #1 and #2 use Apple's `say` voice, which is
fine for a hackathon demo but has no clear redistribution license
for production PSAP deployment. The clean-license alternatives
are: (a) a recorded clip from a consented colleague (PSAP-domain
script, 12-30 s, 44.1 kHz mono PCM, consent doc beside it per
J0 Risk R8), or (b) a CC-0 / public-domain dispatcher-style clip
from LibriTTS (which K1 already evaluated negatively in cycle2j —
audiobook prior leaks through), VCTK (cleaner than LibriTTS but
still narration-prior), or LJ Speech (single speaker, audiobook).

How to enable: same shell pattern as #2 above, with the new audio
asset placed at `references/dispatch-female-us/ref.wav` plus
`ref.lab`. Set `FISH_SPEECH_REFERENCE_ID=dispatch-female-us` in
the worker `.env`, restart.

**Caveat**: still subject to the audiobook-prior risk K1 is
investigating. None of the three options bypass it without the
sampling-knob fix.

## What ISN'T available

Things that would have been useful but do not exist:

- **No Fish-shipped preset library on self-hosted.** The vendor
  tree contains zero `.lab` files, zero `references/` subdirs,
  zero `samples/`, `presets/`, or `voices/` directories. Verified
  by exhaustive find. The cloud Voice Library is a separate
  product, not bundled.
- **No cross-environment ID portability.** A `reference_id` from
  the Fish-Audio cloud (e.g. `c2623f0c075b4492ac367989aee1576f`)
  does NOT resolve on the self-hosted server. The schema comment
  at `vendor/.../utils/schema.py:91-93` is a footgun for self-
  hosted users.
- **No "dispatcher / first-responder" tagged category** in the
  cloud Voice Library taxonomy. Closest analogs are "Professional"
  + "Calm" + "Authoritative" — Paula matches three of these but
  her tag set ("Educational / Conversational / Friendly")
  optimizes for educational-content voiceover, not for crisis
  intake.
- **No commercial-use-clean shipped voices.** Every cloud Voice
  Library entry inherits the Fish-Audio paid-tier
  commercial-rights paywall. There is no MIT-licensed or CC-0
  Fish reference library equivalent to the SD3 stock-image
  marketplace concept.
- **No way to query Fish for cadence/pace metadata.** The Voice
  Library tags include "Energetic / Calm / Slow / Fast /
  Measured / Dynamic" but there is no published WPM number per
  voice and no audio-sample-download path that doesn't go
  through the paid Advanced Playground UI.

## Recommendation

**Stay on K1's speed-knob investigation. Reference-voice swaps
will not fix the slow-cadence symptom.**

Detail: the user's listening pass found cycle-2j's reference voice
"didn't fix the speed problem — Fish is rendering slow at 0.5-0.75x
for most phrases." That symptom signature is consistent with the
sampling stack at the schema floor (current adapter:
`temperature=0.1`, `top_p=0.7`, `repetition_penalty=1.1`,
`chunk_length=200`, `seed=911`,
`~/prism42/agents/livekit/fish_speech_tts.py:60-73`)
producing low-entropy decoding that gravitates to the audiobook
prior in Fish's training distribution. Adding a different reference
voice exchanges one audiobook-prior voice for another; the prior
is the bottleneck. The minimum-viable K1 experiment is raising
`temperature` toward 0.5-0.7 and/or relaxing `top_p` toward 0.9
while keeping `seed` locked, watching for cadence shift in the
listening pass, and only then layering on `[professional broadcast
tone]` or similar inline `[tag]` directives at the prompt level
(durable findings memo §3, "Fish S2-Pro supports inline [tag]
prosody control"). If after K1's knob sweep the cadence is still
off, then a re-recorded reference clip at higher WPM (option 2
above) becomes the next intervention. Do NOT pivot to a Fish
cloud Voice Library asset — that path adds licensing exposure for
zero technical benefit on this symptom.

## Sources

[1]: `~/prism42/vendor/fish-speech/fish_speech/inference_engine/reference_loader.py` lines 20-97 (regex + load_by_id) — verified-by-source 2026-04-26.
[2]: `https://docs.fish.audio/developer-guide/self-hosting/running-inference` — claimed-by-website, retrieval 2026-04-25.
[3]: `https://fish.audio/plan/` — claimed-by-website, retrieval 2026-04-26.
[4]: `https://fish.audio/m/c2623f0c075b4492ac367989aee1576f/` (Paula) — claimed-by-website, retrieval 2026-04-26.
[5]: `https://fish.audio/m/b347db033a6549378b48d00acb0d06cd/` (Selene) — claimed-by-website, retrieval 2026-04-26.
[6]: `https://fish.audio/voice-library/` — claimed-by-website, retrieval 2026-04-25.

Additional verified-by-source citations:

- `~/prism42/vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57` — reference precedence (id wins over inline; silent drop of inline when both set). Retrieval 2026-04-26.
- `~/prism42/vendor/fish-speech/fish_speech/utils/schema.py:60-103` — `ServeReferenceAudio` and `ServeTTSRequest` Pydantic schemas, including the misleading `reference_id` cloud-URL comment. Retrieval 2026-04-26.
- `~/prism42/vendor/fish-speech/tools/server/views.py:208-211` — `/v1/references/{add,list,delete,update}` admin routes (proves on-disk-only model). Retrieval 2026-04-26.
- `~/prism42/vendor/fish-speech/docs/en/server.md:54-62` — upstream documentation that `--reference_id` selects "a saved reference voice" (i.e. server-side preset on disk). Retrieval 2026-04-26.
- `~/prism42/vendor/fish-speech/README.md:46` — Fish Audio Research License (FARL) on weights and code. Retrieval 2026-04-26.
- `~/prism42/infra/b300/services/fish-speech/setup_psap_reference.sh:15-51` — defines the only preset currently installed on the pod (`psap`, macOS `say -v Samantha`). Retrieval 2026-04-26.
- `~/prism42/agents/livekit/fish_speech_tts.py:28-29, 37, 60-73, 184-207` — adapter env wiring (`FISH_SPEECH_REFERENCE_ID`), default sampling knobs, body construction. Retrieval 2026-04-26.
- `~/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T014938Z/team_j0_static_audit.md` lines 18-100 — prior J0 audit confirming the two reference paths and their semantics. Retrieval 2026-04-26.
- `<owner-memory>/prism42_b300_voice_durable_findings.md` finding #3 — Fish S2-Pro inline `[tag]` prosody-control discovery (alternative to reference-voice swap). Retrieval 2026-04-26.

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)
