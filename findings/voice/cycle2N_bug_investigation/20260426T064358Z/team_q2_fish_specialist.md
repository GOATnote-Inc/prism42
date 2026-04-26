# Q2 Fish Specialist — reference precedence + caching

UTC timestamp: 20260426T064358Z
Reviewer: Team Q2 (read-only Fish-Speech engine specialist, glasswing-discipline)
Vendored Fish source: `/Users/kiteboard/prism42/vendor/fish-speech/` (HEAD `3dd1f85`, 2026-04-06; clone date 2026-04-25)
Adapter reviewed: `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py`

## Top finding

**The MW reference voice fails because the wire-body never carries it.** The
adapter's mutex at `fish_speech_tts.py:167-171` is correct and matches Fish's
engine semantics — but the worker process inherits
`FISH_SPEECH_REFERENCE_ID=psap` from `EnvironmentFile=` (per Q1's static
review), so `self._opts.reference_id` is the truthy string `"psap"`. That
makes the adapter:

1. Skip inline `references_payload` assembly (line 167-171: `not self._opts.reference_id` is `False` → branch skipped).
2. Send `body["reference_id"] = "psap"` on the wire (line 221-222).
3. Send `body["references"] = []` (line 219; the list was never populated).

Fish's engine then takes the **`reference_id` branch** at
`vendor/fish-speech/fish_speech/inference_engine/__init__.py:51-52`:

```python
ref_id: str | None = req.reference_id
prompt_tokens, prompt_texts = [], []
if ref_id is not None:
    prompt_tokens, prompt_texts = self.load_by_id(ref_id, req.use_memory_cache)
elif req.references:
    prompt_tokens, prompt_texts = self.load_by_hash(...)
```

`load_by_id("psap", "on")` re-loads the on-disk preset
`references/psap/sample.wav + sample.lab` (or returns the cached VQ tokens
from `self.ref_by_id["psap"]` if memory cache is warm), and the
`elif req.references:` branch is **never reached**. The MW WAV at
`/opt/prism42/voice-refs/mw_sample.wav` is not even read by the adapter
(line 173 `open(...)` is inside the gated `if`-block) and never crosses the
wire. Fish has no idea MW exists.

This is identical in shape to the precedence J0 cited (engine
`__init__.py:48-57`): J0's claim is **confirmed** and **operative on this
build** (Fish HEAD 3dd1f85, 2026-04-06).

The real bug is upstream of Fish: the systemd drop-in cannot clear an
EnvironmentFile-set value with `Environment=NAME=` — Q1 has the
remediation. Q2's contribution is verifying that the Fish side's silent
fallback is exactly as J0 cited and that no Fish-side knob (caching,
empty-string handling, recent commits) changes that.

---

## Fish reference precedence — current behavior

### File:line evidence

`vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57`
(verbatim, retrieved 2026-04-26):

```python
ref_id: str | None = req.reference_id
prompt_tokens, prompt_texts = [], []
# Load the reference audio and text based on id or hash
if ref_id is not None:
    prompt_tokens, prompt_texts = self.load_by_id(ref_id, req.use_memory_cache)

elif req.references:
    prompt_tokens, prompt_texts = self.load_by_hash(
        req.references, req.use_memory_cache
    )
```

`vendor/fish-speech/fish_speech/utils/schema.py:81-103` (request schema,
verbatim):

```python
class ServeTTSRequest(BaseModel):
    text: str
    chunk_length: Annotated[int, conint(ge=100, le=1000, strict=True)] = 200
    format: Literal["wav", "pcm", "mp3", "opus"] = "wav"
    latency: Literal["normal", "balanced"] = "normal"
    references: list[ServeReferenceAudio] = []
    reference_id: str | None = None
    seed: int | None = None
    use_memory_cache: Literal["on", "off"] = "off"
    ...
```

**`reference_id` is `str | None = None`.** Pydantic does not coerce empty
string to `None` here (no validator does that). An empty string `""` stays
`""`.

### Behavior trace — three cases

**Case A: both `reference_id="psap"` AND `references=[{...}]` set.**
Engine line 51 evaluates `ref_id is not None` → True (string, not None) →
`load_by_id("psap", ...)` runs. The `elif` at line 54 is never reached.
**`references` is silently dropped.** This is J0's claim, verbatim.

**Case B: `reference_id=""` (empty string) only, `references=[]`.**
Engine line 51: `ref_id is not None` → True (empty string is not None) →
`load_by_id("", "on")` runs. `load_by_id` calls `_validate_id("")` at
`vendor/.../reference_loader.py:67` → regex `^[a-zA-Z0-9\-_ ]+$` requires
**at least one** character (the `+` quantifier). Empty string fails the
regex match → `ValueError("Reference ID contains invalid characters or
is too long...")` → bubbled up via `views.py:146-205` `/v1/tts` route as
HTTP 5xx.

This validation was added by **PR #1207** (merged 2026-03-23, "fix: add
reference ID validation to prevent path traversal"). **Before that PR**,
empty string would have skipped the validate, called
`Path("references") / ""` → `Path("references")` directory, listed all
audio files in the references root, and returned a stitched-together
multi-voice prompt (or no audio if the dir was empty). Either way: empty
string was never the same as None.

**Implication for the adapter contract:** the adapter must **omit the
`reference_id` field entirely** (not send `""`) when it wants the engine
to take the `elif req.references:` branch. The adapter does this
correctly at `fish_speech_tts.py:221-222`:

```python
if self._opts.reference_id:
    body["reference_id"] = self._opts.reference_id
```

Empty string `self._opts.reference_id == ""` is falsy → field is omitted.
ormsgpack pack of a dict-without-key produces no `reference_id` field on
the wire. Pydantic on Fish's side then defaults it to `None` per the
schema. Engine line 51 sees `None`, falls through to `elif`, calls
`load_by_hash`. **This is the path the adapter intends.**

So the adapter's empty-string guard is **correct**. The bug is one level
up: `self._opts.reference_id` is not empty — it's `"psap"`, inherited
from the EnvironmentFile.

**Case C: `reference_id` absent + `references=[{audio, text}]` non-empty.**
Engine line 51: Pydantic-defaulted `req.reference_id is None` → True (None
is None — does NOT enter the `if` since `is not None` is False) — fall
through to `elif req.references:` line 54 → empty-list-falsy check → list
has one entry → True → `load_by_hash([{...}], "on")` runs, encodes via
VQ-GAN (or pulls from `ref_by_hash[sha256(audio)]` cache), returns the
prompt tokens for the inline reference. **MW path, when wired.**

This is what the adapter would have produced if `FISH_SPEECH_REFERENCE_ID`
had actually been cleared in the worker process env.

---

## Recent Fish source changes (2026-04 onward)

Vendored clone HEAD: `3dd1f85` (2026-04-06, "Fix UnboundLocalError for
torchaudio in ReferenceLoader.__init__"). Below is the upstream
`fishaudio/fish-speech` commit history fetched via `gh api` on 2026-04-26
for the window 2026-03-25 → 2026-04-25:

| Date | SHA / PR | Touches reference handling? | Note |
|---|---|---|---|
| 2026-04-25 | #1276 | YES (security harden) | Bounds `ServeReferenceAudio.audio` to 25 MB, list to 16 items; explicit `isinstance(bytes)` discrimination in `load_audio`. **Not yet vendored locally.** Does NOT change precedence; only rejects oversized payloads earlier. |
| 2026-04-25 | #1275 | NO (max_new_tokens cap) | — |
| 2026-04-25 | #1277 | NO (torch.load weights_only=True) | — |
| 2026-04-25 | #1274 | NO (compile guard for B300) | — |
| 2026-04-06 | #1257 | NO (UnboundLocalError fix in __init__) | This is the local HEAD. |
| 2026-03-30 | #1249 | NO (broken import in quantize tool) | — |
| 2026-03-23 | **#1207** | **YES — added `_validate_id` to `load_by_id`** | Path-traversal fix. **Empty string now raises ValueError** at `_validate_id`. Before this PR, empty string would silently traverse to `Path("references")` root. |
| 2026-03-23 | #1203 | NO (wants_json content-type) | — |
| 2026-03-23 | #1148 | NO (torchaudio 2.9 compat) | — |
| 2026-03-23 | #1141 | NO (uvicorn workers fix) | — |
| 2026-03-23 | #1225 | NO (CUDA 12.6→12.9 docker) | — |
| 2026-03-19 | — | NO (webui readme) | — |
| 2026-03-13 | — | NO (torch.compile in-place fix) | — |
| 2026-03-10 | #1167 | indirectly | "S2 beta" — model-checkpoint commit. |

**Net effect on precedence semantics:** the `if reference_id is not None
... elif references` precedence at `inference_engine/__init__.py:48-57`
is **unchanged for the entire 2026-03-25 → 2026-04-26 window.** The only
behavioral change is PR #1207 making empty string an error instead of a
silent root-of-references-dir traversal — which **strengthens** the
adapter's "omit the field when empty" pattern and makes accidental
empty-string sends loud (5xx) instead of silent (wrong voice from
arbitrary preset). The adapter's existing `if self._opts.reference_id:`
guard already does the right thing.

### Open issues touching reference behavior (2026-04 window)

| # | Date | Title | Relevance |
|---|---|---|---|
| #1268 | 2026-04-15 | "Cannot reproduce reported Seed-TTS-Eval results for s2-pro" | Quality issue with reference voices, not a precedence bug |
| #1260 | 2026-04-07 | "How to achieve voice consistency, without cloning" | User confirms: without `reference_id` AND without `references`, S2-Pro produces a different voice each call (no determinism in default voice). Confirms why the deploy looks "psap-stable but wrong voice" — psap is *one* voice because reference_id is locking it. |
| #1053 | 2025-06-23 (closed) | "Reference audio not being applied in /partial API calls" | **Closest precedent.** Different code path (Gradio `/partial` vs HTTP `/v1/tts`), but same family: reference audio silently ignored. Symptom matches the cycle-2N field report. |
| #836 | older | "Fish TTS API Fails to Match Reference Audio Tone and Style" | Quality drift, not silent drop |

No 2026-04 issue specifically reports `Environment=NAME=` failing to clear
an EnvironmentFile value (that's a systemd issue, not a Fish issue). The
silent-drop-when-both-set behavior on `/v1/tts` is undocumented in the
Fish docs (`vendor/fish-speech/docs/en/server.md` does not call out the
mutex), so callers who don't read the engine source easily fall into
this trap.

---

## Fish caching behavior

`use_memory_cache` semantics, exhaustively (verified at
`vendor/fish-speech/fish_speech/inference_engine/reference_loader.py`):

1. **Two caches, both keyed by reference identity, NOT by output text.**
   - `self.ref_by_id: dict` — keyed by reference_id string.
     Stores `(prompt_tokens, prompt_texts)` — the VQ-encoded reference
     prompt only. (`reference_loader.py:29, 76-95`.)
   - `self.ref_by_hash: dict` — keyed by `sha256(audio_bytes).hexdigest()`.
     Stores `(single_prompt_token, ref_text)` per audio entry.
     (`reference_loader.py:30, 99-126`.)
2. **No cache of generated TTS output.** The LLAMA model is invoked on
   every request inside `TTSInferenceEngine.inference()` at
   `inference_engine/__init__.py:65` regardless of cache state. The cache
   only short-circuits the **VQ-encode of the reference** at
   `vq_manager.py:24-53`. The text → semantic-token → audio path runs
   afresh every call, modulo `seed`-based determinism (the adapter pins
   `seed=911` per `fish_speech_tts.py:83`).
3. **No cross-reference contamination.** Cache entries are per-id and
   per-audio-hash. Setting a new `references_payload` with a different
   audio file produces a different sha256 and a fresh cache miss → fresh
   VQ-encode. The bug is NOT "Fish reused the old psap encoded tokens for
   the MW request." The bug is "the MW request never reached Fish — Fish
   saw `reference_id=psap` and obeyed."

**Direct answer to the cycle-2j R1 lookup ("cold VQ-encode pass per new
audio"):** correct, with a corollary the cycle-2j note didn't spell out
— the cold VQ-encode only fires if the request actually carries the new
audio. If the wire body still carries `reference_id`, the inline path is
short-circuited at engine line 51-52 and no encode of the new audio
happens. There is no "fish silently used cache" scenario at the output
level; only "fish never saw the new reference" at the precedence level.

**Test that would have caught this:** a curl against `/v1/tts` from the
worker box with the worker's exact env (sourced from
`/proc/$(pgrep worker.py)/environ`) plus the body the adapter would
construct. The 500-line systemd → adapter → ormsgpack chain hides the
fact that the wire body still has `reference_id="psap"`. A request-side
log of the body keys (not just the values) would surface this in one
log line.

---

## Sources

All citations dated **2026-04-26** unless otherwise noted.

1. `/Users/kiteboard/prism42/vendor/fish-speech/fish_speech/inference_engine/__init__.py:48-57` — engine reference precedence (`reference_id` first, else `references`). Vendored HEAD `3dd1f85` (2026-04-06).
2. `/Users/kiteboard/prism42/vendor/fish-speech/fish_speech/utils/schema.py:60-103` — `ServeReferenceAudio` and `ServeTTSRequest` Pydantic schemas. `reference_id: str | None = None`.
3. `/Users/kiteboard/prism42/vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:54-97` — `_validate_id` regex `^[a-zA-Z0-9\-_ ]+$` and `load_by_id` body. Empty string fails validation (regex requires `+`).
4. `/Users/kiteboard/prism42/vendor/fish-speech/fish_speech/inference_engine/reference_loader.py:99-131` — `load_by_hash`: per-request inline reference path; cache keyed by sha256(audio).
5. `/Users/kiteboard/prism42/vendor/fish-speech/fish_speech/inference_engine/vq_manager.py:24-53` — `encode_reference` cold-encode site (per-new-audio cost).
6. `/Users/kiteboard/prism42/agents/livekit/fish_speech_tts.py:166-193, 219-222` — adapter mutex (correct: `not self._opts.reference_id` gates inline assembly) and body construction (`if self._opts.reference_id: body["reference_id"] = ...`).
7. https://github.com/fishaudio/fish-speech/pull/1207 — "fix: add reference ID validation to prevent path traversal" (merged 2026-03-23). Adds `_validate_id` regex check to `load_by_id` and the delete/update endpoints.
8. https://github.com/fishaudio/fish-speech/pull/1276 — "security: bound audio bytes + harden path/bytes discrimination in reference_loader" (merged 2026-04-25). Caps audio at 25 MB / list at 16 items; explicit `isinstance(bytes)` in `load_audio`. Does not change precedence.
9. https://github.com/fishaudio/fish-speech/issues/1053 — "Reference audio not being applied in /partial API calls" (2025-06-23, closed). Closest precedent for silent-reference-drop family of bugs.
10. https://github.com/fishaudio/fish-speech/issues/1260 — "How to achieve voice consistency, without cloning" (2026-04-07). Confirms S2-Pro has no per-request voice determinism without `reference_id` or `references`.
11. https://github.com/fishaudio/fish-speech/commits/main — Commit history surveyed via `gh api repos/fishaudio/fish-speech/commits` for window 2026-03-25 → 2026-04-25 (retrieved 2026-04-26 06:42 UTC).
12. `/Users/kiteboard/prism42/findings/voice/cycle2j_reference_voice/2026-04-26T014938Z/team_j0_static_audit.md:117-134` — J0's earlier cite of the same precedence point. Confirmed unchanged on 2026-04-26 build.
13. `/Users/kiteboard/prism42/findings/voice/cycle2N_bug_investigation/20260426T064303Z/team_q1_code_review.md` — Q1's static review of the systemd EnvironmentFile vs drop-in semantics. Q2 corroborates Q1's adapter-side claim from the Fish-engine angle.

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)
