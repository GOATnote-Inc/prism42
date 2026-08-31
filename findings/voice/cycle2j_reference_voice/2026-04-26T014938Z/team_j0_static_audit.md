# Team J0 - Fish reference-audio static audit

Read-only static audit. No mutations applied. All citations resolve to local
vendored Fish source at `~/prism42/vendor/fish-speech/` (cloned
from `github.com/fishaudio/fish-speech`) and to the live adapter at
`~/prism42/agents/livekit/fish_speech_tts.py`. Retrieval date
on all upstream-doc claims: 2026-04-25.

Auditor scope: only the LiveKit adapter contract with the running upstream
`tools/api_server.py`. Engine internals (LLAMA, VQ-GAN, DAC) and vendor
forking are explicitly out of scope.

---

## Verdict

**Fish S2-Pro supports reference audio: YES, via two complementary fields on
the same `/v1/tts` request body.**

1. `reference_id: str` - addresses a server-side preset previously registered
   via `POST /v1/references/add`. One id per request. The adapter already
   exposes this as `FishSpeechOptions.reference_id` and the env override
   `FISH_SPEECH_REFERENCE_ID`.
   `verified-by-source` - schema field at `vendor/fish-speech/fish_speech/utils/schema.py:93`;
   adapter wire passthrough at `agents/livekit/fish_speech_tts.py:157-158`.

2. `references: list[ServeReferenceAudio]` - per-request inline references,
   each carrying `audio: bytes` and `text: str` (the transcript of the audio
   clip). Multiple entries supported - the engine encodes them in order and
   concatenates the resulting prompt-token sequences. The adapter currently
   sends a hardcoded empty list and exposes NO knob to populate it.
   `verified-by-source` - schema at `vendor/fish-speech/fish_speech/utils/schema.py:60-89`;
   server route at `vendor/fish-speech/tools/server/views.py:146-147`;
   engine fan-out at `vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57`;
   adapter omission at `agents/livekit/fish_speech_tts.py:155`.

The adapter's existing `reference_id` path is functional today (line 157-158
conditionally adds the field when set). The gap that Cycle 2j is opening is
the `references` (inline audio+transcript) path, which the adapter pins to
`[]` unconditionally at line 155 with no env or constructor surface to
override it.

---

## Evidence

### Fish HTTP/WS request shape (file:line in `agents/livekit/fish_speech_tts.py`)

`verified-by-source`

- Endpoint: `POST {FISH_SPEECH_URL}/v1/tts`. URL constructed at line 169.
  Base URL defaults to `http://127.0.0.1:9200` (line 28); env override
  `FISH_SPEECH_URL`.
- Wire codec: `ormsgpack.packb(body)` at line 170, `Content-Type:
  application/msgpack` at line 171. The Fish upstream server's
  `format_response` and Body-decoding stack accept ormsgpack as the native
  body codec (matches the upstream `tools/api_client.py` reference client).
- Method: streaming HTTP via `httpx.AsyncClient.stream("POST", ...)` at
  line 167. Response is consumed via `resp.aiter_bytes()` at line 186. This
  is one-shot synthesize, not WebSocket - the adapter declares
  `streaming=False` at line 69 to advertise that to livekit-agents while
  still using HTTP-streaming to receive PCM frames.
- Body field set: `text`, `format="wav"`, `chunk_length`, `normalize`,
  `streaming=True`, `max_new_tokens`, `top_p`, `repetition_penalty`,
  `temperature`, `use_memory_cache="on"`, `seed`, `references=[]`. The
  conditional block at line 157-158 adds `reference_id` only when
  `self._opts.reference_id` is truthy. (`agents/livekit/fish_speech_tts.py:135-158`.)

### Fish upstream API for reference audio

`verified-by-source` against the local vendored clone at
`vendor/fish-speech/`. URL of upstream:
`https://github.com/fishaudio/fish-speech` (retrieval date 2026-04-25).

Request schema (Pydantic `BaseModel`):

```
class ServeReferenceAudio(BaseModel):
    audio: bytes          # raw bytes; base64 strings >255 chars auto-decoded
    text: str             # transcript of the audio clip

class ServeTTSRequest(BaseModel):
    text: str
    chunk_length: int = 200            # ge=100, le=1000
    format: Literal["wav","pcm","mp3","opus"] = "wav"
    latency: Literal["normal","balanced"] = "normal"
    references: list[ServeReferenceAudio] = []
    reference_id: str | None = None
    seed: int | None = None
    use_memory_cache: Literal["on","off"] = "off"
    normalize: bool = True
    streaming: bool = False
    max_new_tokens: int = 1024
    top_p: float = 0.8                 # ge=0.1, le=1.0
    repetition_penalty: float = 1.1    # ge=0.9, le=2.0
    temperature: float = 0.8           # ge=0.1, le=1.0
```

(`vendor/fish-speech/fish_speech/utils/schema.py:60-107`.)

Server route handler:

```
@routes.http.post("/v1/tts")
async def tts(req: Annotated[ServeTTSRequest, Body(exclusive=True)]):
    ...
    if req.streaming:
        return StreamResponse(iterable=inference_async(req, engine), ...)
    else:
        fake_audios = next(inference(req, engine))
        ...
```

(`vendor/fish-speech/tools/server/views.py:146-197`.)

Engine fan-out for references (the precedence and concat behavior):

```
ref_id: str | None = req.reference_id
prompt_tokens, prompt_texts = [], []
if ref_id is not None:
    prompt_tokens, prompt_texts = self.load_by_id(ref_id, req.use_memory_cache)
elif req.references:
    prompt_tokens, prompt_texts = self.load_by_hash(
        req.references, req.use_memory_cache
    )
```

(`vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57`.)

Reference-id is checked first; only if `reference_id is None` does the engine
fall back to inline `references`. **Sending both is silently degenerate -
the inline list is ignored.** This is a contract worth enforcing in the
adapter.

Multi-reference encoding (proves N>1 is supported):

```
def load_by_hash(self, references, use_cache):
    audio_hashes = [sha256(ref.audio).hexdigest() for ref in references]
    prompt_tokens, prompt_texts = [], []
    for i, ref in enumerate(references):
        if use_cache == "off" or audio_hashes[i] not in self.ref_by_hash:
            prompt_tokens.append(self.encode_reference(
                reference_audio=ref.audio, enable_reference_audio=True))
            prompt_texts.append(ref.text)
            self.ref_by_hash[audio_hashes[i]] = (prompt_tokens[-1], ref.text)
        else:
            cached_token, cached_text = self.ref_by_hash[audio_hashes[i]]
            prompt_tokens.append(cached_token)
            prompt_texts.append(cached_text)
    return prompt_tokens, prompt_texts
```

(`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:99-131`.)

Server-side preset registration (the path that backs `reference_id`):

- `POST /v1/references/add` body: `id: str`, `audio: UploadFile`, `text: str`.
  `id` regex `^[a-zA-Z0-9\-_ ]+$`, max length 255.
  (`vendor/fish-speech/tools/server/views.py:208-211`,
  `vendor/fish-speech/fish_speech/utils/schema.py:110-113`.)
- `GET /v1/references/list` returns `reference_ids: list[str]`.
- `DELETE /v1/references/delete` body `reference_id: str`.
- `POST /v1/references/update` body `old_reference_id`, `new_reference_id`.
- Server reads presets from on-disk dir `references/<id>/`.
  (`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:69-95`.)

### Number of reference samples supported

`verified-by-source` - `references` is `list[ServeReferenceAudio] = []` with
no upper bound declared in the Pydantic field (no `max_length`).
(`vendor/fish-speech/fish_speech/utils/schema.py:89`.)

The engine processes them in a `for i, ref in enumerate(references):` loop
(`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:109`)
and concatenates the resulting `prompt_tokens` lists - so any N is
mechanically accepted, but practical N is bounded by the LLAMA prompt
context (S2-Pro context length not auto-discoverable from this source tree;
treat N>3 as an empirical risk, not a hard limit). For `reference_id` the
engine path `load_by_id` returns a single `(tokens, text)` pair from a single
on-disk dir, so id-mode is one preset per request.

`unverified` - whether per-speaker `<|speaker:i|>` tokens (mentioned at
`vendor/fish-speech/docs/en/index.md:148`) interleave automatically with
multi-reference inline `references` lists, or only with multi-speaker presets
registered as a single id.

### Recommended duration

`verified-by-source` - upstream README:

> "Fish Audio S2 supports accurate voice cloning using a short reference
> sample (typically 10-30 seconds). The model captures timbre, speaking
> style, and emotional tendencies, producing realistic and consistent
> cloned voices without additional fine-tuning."

(`vendor/fish-speech/docs/en/index.md:154-156`, retrieval date 2026-04-25.)

The cycle-2h `best_in_class` research file already records this:
`findings/voice/best_in_class_2026-04-25/research.md:92-93` ("10-30 s of
reference audio clones timbre, speaking style, emotional tendencies").

`unverified` - Fish does not publish a strict minimum or maximum in the
vendored docs. Assume 10-30 s as the working window; under 5 s and over
60 s are out of distribution.

### Quality / latency tradeoffs documented

`claimed-by-source` (engine behavior, not benchmarked numbers):

- **Cold-vs-warm reference encoding.** Each new reference clip is encoded
  via VQ-GAN before LLAMA inference begins
  (`vendor/fish-speech/fish_speech/inference_engine/vq_manager.py:24-33`).
  This adds a one-time encode cost per unique audio. The
  `use_memory_cache: "on"` flag makes subsequent calls with the same audio
  hash reuse the encoded prompt tokens
  (`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:121-126`)
  and the adapter already sets `use_memory_cache="on"` at line 153.
  Implication: first-call TTFB grows by the VQ-encode cost; warm-call TTFB
  is roughly unchanged from no-reference. The exact cold-call delta is
  empirical, not in the source.
- **Caching is keyed by sha256(audio bytes).** Bit-identical audio hits
  cache; re-encoded WAV with different headers does not. Plan to ship one
  canonical .wav per voice and never resave.
- **Reference-id path also has its own preset cache** - `self.ref_by_id`
  (`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:84-95`).
  After first warmup, repeated calls with the same `reference_id` do not
  re-encode.
- **Reference tokens consume LLAMA context.** Inline `references` increase
  the prompt-token count proportional to reference duration (10-30 s of
  audio -> tens to hundreds of VQ tokens, depending on chunk_length).
  Longer references push the LLAMA inference closer to its context limit
  and mildly slow per-token decode.
- **Order matters.** `load_by_hash` preserves insertion order; the LLAMA
  prompt is `prompt_texts[0] + prompt_tokens[0] + ... + req.text`. If you
  ship multiple references, the first is the most "primary" voice.

`unverified` - quantitative latency numbers (cold-encode ms, warm-cache
ms, RTF impact). Cycle-2h research said B300 PyTorch RTF is ~1.96
without references; reference-conditioned RTF is not currently measured
in this repo.

### What the adapter does today

`verified-by-source` - `agents/livekit/fish_speech_tts.py`:

| Line | Behavior |
|---|---|
| 29 | Reads `FISH_SPEECH_REFERENCE_ID` env into `DEFAULT_REFERENCE_ID`. |
| 37 | `reference_id: str = DEFAULT_REFERENCE_ID` on `FishSpeechOptions`. |
| 155 | `"references": []` - hardcoded empty list, no constructor or env override. |
| 157-158 | If `self._opts.reference_id` truthy, body gets `reference_id: <id>`. |

The id path is wired and works; the inline-audio path is the gap. There is
also no validation that callers do not set both `reference_id` AND
`references` simultaneously - the engine silently drops `references` in
that case.

---

## Minimal patch plan

**File:** `agents/livekit/fish_speech_tts.py`

**Goal:** thread per-request inline reference audio through to the wire
body, env-flag-gated, default-disabled, fully backwards-compatible. Keep
the existing `reference_id` path untouched.

**Patch sites:** 3 small adds in 3 contiguous regions of one file.

### Site 1 - module constants (after line 29)

Add two env reads and a tiny resolver. ~6 LOC.

```
DEFAULT_REFERENCE_AUDIO_PATH = os.environ.get("PRISM42_FISH_REFERENCE_AUDIO", "")
DEFAULT_REFERENCE_TEXT       = os.environ.get("PRISM42_FISH_REFERENCE_TEXT", "")
```

(Two-knob design: audio bytes come from a path on disk; transcript comes
from a separate env. Avoids embedding a long transcript in an env value.
If `PRISM42_FISH_REFERENCE_TEXT` is unset but the audio path has a sibling
`.txt` file, fall back to that - one extra LOC.)

### Site 2 - `FishSpeechOptions` dataclass (after current line 56)

Add two optional fields. ~2 LOC.

```
reference_audio_path: str = DEFAULT_REFERENCE_AUDIO_PATH
reference_audio_text: str = DEFAULT_REFERENCE_TEXT
```

### Site 3 - body construction (replace line 155, extend conditional at 157-158)

Build the `references` list lazily, only when path is set. ~10-12 LOC.

```
references_payload: list[dict] = []
if self._opts.reference_audio_path and not self._opts.reference_id:
    # Mutual exclusion: engine ignores `references` when `reference_id`
    # is non-None (inference_engine/__init__.py:48-57). Prefer the
    # cheaper id path when both are available.
    try:
        with open(self._opts.reference_audio_path, "rb") as f:
            audio_bytes = f.read()
        ref_text = self._opts.reference_audio_text or ""
        if audio_bytes and ref_text:
            references_payload.append({
                "audio": audio_bytes,
                "text": ref_text,
            })
    except OSError as e:
        log.warning("fishspeech.reference_load_failed",
                    path=self._opts.reference_audio_path, err=str(e)[:200])
body = {
    "text": self._text,
    ...
    "references": references_payload,    # was: []
}
if self._opts.reference_id:
    body["reference_id"] = self._opts.reference_id
```

(Total inline-audio block: ~12 LOC; keeps the `reference_id` branch
untouched. ormsgpack handles `bytes` natively, so no base64 encoding step
is needed - the `vendor/.../schema.py:64-75` decode path is for callers
that DO send base64 strings, not a requirement.)

### Total LOC estimate

~20 LOC including comments, plus one-line wire change at body
construction. No new imports. No dependency changes.

### Backwards compatibility

- Adapter behavior with `PRISM42_FISH_REFERENCE_AUDIO` unset: identical to
  today. `references_payload` is `[]`, body shape unchanged.
- Adapter behavior with `FISH_SPEECH_REFERENCE_ID` set (existing
  production knob): unchanged - the id path still wins, and the patch
  explicitly skips inline reference assembly when an id is set, matching
  the engine's silent drop semantics.
- Adapter behavior with both envs set: id wins, audio is loaded but not
  sent. Logged once at warning level so operators notice.

### What the patch deliberately does NOT do

- Does NOT support multiple inline references in this iteration. One
  audio + one transcript covers the dispatcher-voice use case. Multi-ref
  can land later with `PRISM42_FISH_REFERENCE_AUDIO_<n>` indexing if
  warranted.
- Does NOT auto-register the audio as a server-side preset via
  `/v1/references/add`. That is a different deployment workflow (warmup
  script), not adapter-runtime work.
- Does NOT validate sample rate or duration of the supplied .wav. Fish
  ingests via `torchaudio.load` and resamples internally
  (`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:133-141`).
  Bad input (corrupt file, wrong codec) surfaces as a 5xx from the server.
- Does NOT cache audio bytes in the adapter. Each request reads the file
  fresh from disk. Fish's own `use_memory_cache="on"` already caches by
  sha256 of the bytes (`reference_loader.py:121-126`), so repeated reads
  of the same file get one VQ-encode + N free hits.

---

## Risk register

| Risk | Detection | Mitigation |
|---|---|---|
| **R1. First-call latency spike from cold VQ-encode of new reference.** Inline `references` requires a VQ-GAN encode pass before LLAMA decode begins; the cold-cache delta is not currently measured on B300. | The existing `fishspeech.t_first_byte` log (line 191-195) will jump on the first call after deploy with a new reference. Ship a 1-utterance warmup at agent boot. | Server-side `use_memory_cache="on"` (already set at line 153) caches by sha256(audio). Warmup script issues one synth call at agent boot. Subsequent calls hit cache. |
| **R2. Voice drift if reference is too short, too long, or out-of-distribution.** Fish's docs recommend 10-30 s; outside this the model may produce wrong timbre or revert to a base voice. | Listen test required after every reference-asset change. Add a synthetic-caller golden trajectory pinned to one expected voice profile. | Pin exactly one canonical .wav per deploy. Document its duration, sample rate, and source. Treat reference asset like a model-version pin. |
| **R3. Mutex with `reference_id` is enforced server-side, not adapter-side.** The engine silently ignores `references` when `reference_id` is set (engine line 48-57). | The patch skips inline assembly when id is set and logs at warning. Without that guard, an operator who sets both envs will be confused why the audio file appears to do nothing. | Patch (Site 3) explicitly enforces mutual exclusion in the adapter and logs both-set as a warning. |
| **R4. Reference text/audio mismatch produces drift, not error.** Fish does not validate that the transcript matches the audio. Submitting wrong text degrades quality silently. | Manual listen test. No automated detection. | Document in the agent README: transcript must match audio verbatim, including punctuation. Single source of truth: a canonical `references/<voice>/audio.wav` + `references/<voice>/text.txt` pair, both checked into git or fetched from a deploy artifact. |
| **R5. ormsgpack `bytes` payload increases request size.** A 30 s 24 kHz mono 16-bit WAV is ~1.4 MB; sending that on every TTS call adds bandwidth + serialization cost. | `total_bytes` log at line 233 is response-side; add one `request_body_bytes` log if needed. Network is loopback (B300 pod) so latency cost is minimal but not zero. | Prefer the `reference_id` path in production (one-time `/v1/references/add` at boot, then ids on every request). Inline `references` is the right knob for development and listen-tests; production should land on the id path once the voice is final. |
| **R6. File I/O on every synth call.** Site 3 reads the .wav from disk per request. On a busy worker this is a syscall hit per turn. | Bench: ~1.4 MB sequential read on a B300 pod's local FS is sub-ms. Acceptable. | Optional: load once at adapter `__init__` into a `bytes` field; trade off LRU-cache vs hot-reload-on-edit. Defer until measured. |
| **R7. Mid-call config edits not picked up.** Env vars are read at module import (line 28-29) and frozen on the dataclass. Changing the env mid-flight does not change behavior until the agent restarts. | Same model as `FISH_SPEECH_URL` and `FISH_SPEECH_REFERENCE_ID` today. Documented behavior. | None needed - this matches the existing adapter contract. |
| **R8. Reference asset becomes a privacy / consent surface.** A real human voice clip is now in the deployment artifact. PSAP / clinical context: any voice that resembles a real dispatcher may need that dispatcher's written consent + retention policy. | Code review checkpoint. Not a software detection. | Pre-commit: never check in a real human-voice .wav. Use synthetic / royalty-free / consented-staff voice. Document provenance + consent in `findings/voice/cycle2j_reference_voice/<dir>/asset_consent.md` (or equivalent) before any deploy. |

---

## Sources

All upstream-doc retrievals dated **2026-04-25**.

1. `agents/livekit/fish_speech_tts.py` (lines 28-29, 36-37, 56, 69, 135-158,
   167-172, 233) - the live LiveKit Fish adapter.
2. `vendor/fish-speech/fish_speech/utils/schema.py` (lines 60-107) -
   `ServeReferenceAudio` and `ServeTTSRequest` Pydantic schemas.
3. `vendor/fish-speech/tools/server/views.py` (lines 146-205, 208-211,
   289-290, 318-319) - `/v1/tts` route and `/v1/references/*` admin
   routes.
4. `vendor/fish-speech/fish_speech/inference_engine/__init__.py` (lines
   40-66) - reference precedence (`reference_id` first, else `references`).
5. `vendor/fish-speech/fish_speech/inference_engine/reference_loader.py`
   (lines 67-131, 133-141, 162) - `load_by_id`, `load_by_hash`,
   `load_audio` (torchaudio loader, accepts bytes or path).
6. `vendor/fish-speech/fish_speech/inference_engine/vq_manager.py` (lines
   24-33) - `encode_reference` (cold-encode cost site).
7. `vendor/fish-speech/docs/en/server.md` (lines 30-62) - documented
   `/v1/tts` endpoint, `--reference_id` CLI flag, S2-Pro selected by
   server-start-time checkpoint.
8. `vendor/fish-speech/docs/en/index.md` (lines 144-157) - "10-30 seconds"
   reference duration recommendation, multi-speaker `<|speaker:i|>` token
   note, voice-cloning capability claim.
9. Upstream repo URL: `https://github.com/fishaudio/fish-speech`
   (retrieval date 2026-04-25; vendored at
   `~/prism42/vendor/fish-speech/`).
10. `findings/voice/best_in_class_2026-04-25/research.md` (lines 92-93,
    461) - cycle-2h prior note on reference-id voice-preset L4 mitigation;
    confirmed `reference_id` path is already env-tunable, the inline
    `references` audio path is the gap this audit closes.

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)
