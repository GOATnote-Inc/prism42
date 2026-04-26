# Cycle-2P2 STT accuracy findings — Parakeet TDT 0.6B v3 on B300

Author: Team P · Date: 2026-04-26 · Status: research-only, no code changes

## What's deployed right now

- **Model**: `nvidia/parakeet-tdt-0.6b-v3` (verified via `/healthz` on pod and
  `MODEL_NAME` default in `infra/b300/services/parakeet/server.py:57`).
- **Container**: `nvcr.io/nvidia/nemo:25.09` (`infra/b300/services/parakeet/Dockerfile:30`).
- **Decoder mode**: NeMo `model.transcribe()` default — greedy_batch RNN-T/TDT,
  no external LM, no boosting tree, no hotwords (verified `server.py:163,211,305`).
- **Capabilities advertised to LiveKit**: `streaming=True, interim_results=True`
  via WebSocket `/ws` (`parakeet_stt.py:111-125`). The streaming path
  re-transcribes a growing PCM buffer every 160 ms (`server.py:62-64`).
- **Sample rate**: 16 kHz mono PCM16 (`server.py:69`).
- **Lexicon / vocabulary**: BASE only. The model card lists 25 European
  languages and English-only variants but no domain-specific lexicon for
  US dispatch / addresses. No custom vocabulary is wired into our
  `model.transcribe()` call.

## Recent transcripts that bear on the issue

From `/tmp/prism42-logs/worker.log`, the worker's "user_transcript" debug
events for sessions in the last 24 hours that involved address dictation.

| Caller intended | Parakeet final transcript | FSM `address_known` |
|---|---|---:|
| 100 Ocean Avenue | `"Uh one hundred Ocean Avenue."` | True (Avenue suffix) |
| 100 Ocean Avenue | `"One hundred Ocean Avenue."` | True (Avenue) |
| 100 Ocean Avenue | `"One hundred ocean of new."` | **False — "of new" instead of "Avenue"** |
| 100 Ocean Avenue | `"Um one hundred Ocean Avenue."` | True (Avenue) |
| 12 Riverside | `"Twelve Riverside"` | False (no digit, no suffix in regex) |
| 20 Riverside | `"Twenty Riverside Drive"` | True (Drive) |
| 200 (no suffix) | `"Two hundred"` | False (no digit, no suffix) |
| 20 Lake Park Drive | `"Twenty Lake Park Drive."` | True (Drive) |
| 20 Lakeside | `"Twenty Lakeside"` | False |

Take-aways:

1. Parakeet TDT 0.6B v3 emits **spelled-out** cardinal numbers, not digits.
   That alone breaks the FSM's `\d` heuristic for half of US addresses.
2. Mis-hears on the suffix are real and recurrent. "Avenue" -> "of new"
   and "Lakeside" with no suffix word are the failure shapes seen live.
3. **`transcript_delay`** in worker.log holds steady at ~0.95 s for most
   utterances. We are paying full batch latency even with the WebSocket
   path. Phase 3b's preflight events would help here but don't change
   the *content* of the final.

## Custom-vocabulary feasibility

### Option A — NeMo-native phrase boosting (GPU-PB)

NVIDIA documentation (fetched 2026-04-26): NeMo 2.5.0 added GPU-accelerated
phrase boosting (GPU-PB / NGPU-LM) for **CTC, RNN-T, TDT, and AED (Canary)
models** including Parakeet TDT. Not available on the bare `model.transcribe()`
API; must go through the `eval_beamsearch_ngram_transducer` script or the
config knobs in `rnnt_decoding`:

```yaml
rnnt_decoding:
  strategy: "greedy_batch"   # or "malsd_batch" for beam search
  greedy:
    boosting_tree:
      key_phrases_file: "/path/to/phrases.txt"
      # OR key_phrases_list: [...]
      context_score: 1.0          # recommended starting value
      depth_scaling: 2.0          # recommended
  boosting_tree_alpha: 0.5        # tune this weight
```

Source: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/asr_customization/word_boosting.html` (fetched 2026-04-26).

NeMo 25.09 container ships NeMo >= 2.5.0 (`pip show nemo_toolkit` not run on
pod; assumed from container release notes — verify before commit). GPU-PB is
applied at decoding step in shallow fusion mode; **no model retraining needed**.

**Phrases file content for our use case** (proposal):

```
# Address suffixes (capitalized — model emits capitalized output)
Street
Avenue
Boulevard
Drive
Road
Lane
Court
Way
Highway
Parkway
Place
Circle
Terrace

# Common cardinal directions
North
South
East
West

# Apartment markers
Apartment
Suite
Unit
Floor

# 911 call domain
nine one one
emergency
ambulance
paramedics
police
fire department
not breathing
unresponsive
chest compressions
```

NVIDIA docs note: capitalize all key phrases for capitalization-supporting
models like parakeet-tdt-0.6b. We're on `v3` which is the same family.

**Risks**:
- Phrase boost adds ~5-15 ms decode latency per phrase set, depending on
  list size. Acceptable for our budget.
- Over-boosting addresses can pull the model toward false-positive "Avenue"
  on any utterance ending in `-vee-noo` sounds. Tune via `boosting_tree_alpha`.
- Capitalization rule means "ocean" wouldn't match — must be "Ocean" — but
  Parakeet does emit "Ocean Avenue" with caps when it gets the suffix right
  (verified live). The mis-hear case "of new" wouldn't be repaired by
  boosting Ocean / Avenue alone — it needs phonetic-level intervention.

### Option B — Inverse text normalization (ITN) for digits

NeMo includes WFST-based ITN that converts spoken numbers ("one hundred")
to written form ("100"). Blocked behind:

- `nemo_text_processing` package (already in NeMo container).
- WFST FAR files for English (downloadable from NeMo NGC).
- Apply at *post-processing*, not in `transcribe()` itself.

If we apply ITN to the Parakeet output, "One hundred Ocean Avenue" becomes
"100 Ocean Avenue" and the FSM's `_RE_HAS_DIGIT` fires immediately. This is
a one-call fix for the spelled-out-number problem.

Source: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/text_processing/text_processing.html`
(NeMo text processing toolkit; `nemo_text_processing.inverse_text_normalization`).

**Risks**:
- ITN can over-normalize ("one for one trade" -> "1 for 1 trade"). Most
  cases fine for dispatch context.
- Adds ~5-20 ms per utterance.
- Must run on the *server* side (in `parakeet/server.py`) so the FSM sees
  digits in the final transcript.

### Option C — Post-STT correction layer (LLM rewrite)

Run the Parakeet final through a tiny correction pass before the FSM sees
it. Two flavors:

- **Rule-based**: regex map `\bocean of new\b -> Ocean Avenue`,
  `\bof new\b$ -> Avenue`, etc. Fast (<1 ms), no new infra, brittle to
  unseen mis-hears.
- **LLM-based**: pre-FSM correction call (could be Sonnet, Opus, even
  a 1B local model). Slow (>= 50 ms TTFT), but generalizes. Adds a
  failure mode (LLM hallucinates an address that wasn't said) so it must
  be confidence-gated.

For Phase 3a/b on the hackathon timeline, rule-based is cheap and
ship-in-a-day. LLM-based correction only makes sense after we know which
mis-hears recur.

### Option D — Switch to streaming-first model

`nvidia/parakeet-unified-en-0.6b` (April 2026, per
`docs/livekit-kb/12-parakeet-stt-component.md`) is streaming-first with
160 ms claimed minimum latency. Same 0.6B params, Blackwell supported.
Whether it changes the digit-vs-spelled-out behavior is not documented;
likely no improvement on that axis since both models are trained on the
same corpus type.

This is a Phase 3b call (Team R territory), not a P2 fix.

## Confidence-threshold tuning

The plugin sets `ParakeetOptions.confidence_floor=0.0` (`parakeet_stt.py:93`).
The server does emit confidence in the final payload (computed from log-score,
`server.py:142-146`). Two practical uses:

1. **Low-confidence reprompt.** When `confidence < 0.5` AND the FSM is in
   INTAKE, emit a polite "I didn't quite catch that — could you repeat the
   address?" instead of advancing the FSM. This is the dispatcher
   "say-again" loop, NOT a regression — every real PSAP does this.
2. **Confidence-gated cardiac latch.** When `_RE_NOT_BREATHING` matches
   AND `confidence < 0.6`, do NOT auto-jump to CRITICAL_VERIFY; instead
   emit `kq_responsive_breathing` to confirm. Prevents false positives
   on noisy STT.

The current confidence path emits the transcript regardless. Adding a
threshold-based reprompt is a 5-line change in the orchestrator hook
(after `transition()` returns, before applying state).

## Best alternative if Parakeet can't be tuned in time

CLAUDE.md cites Deepgram Nova-3 as the cloud streaming alternative. From
Deepgram docs (fetched 2026-04-26):

- **Nova-3 Multilingual**: supports Multilingual Keyterm Prompting, up
  to 500 tokens (~100 words). Can pass `keyterm` parameter at request
  time to bias toward addresses, dispatch jargon.
- **Latency**: ~150 ms partial-TTFT (per
  `docs/livekit-kb/12-parakeet-stt-component.md` table).
- **Pricing**: paid (we are on $0 self-host today).
- **Existing LiveKit plugin**: `livekit-plugins-deepgram` is what
  `parakeet_stt.py` replaced; the wiring still exists in commits and
  could be re-introduced behind a feature flag.

For the hackathon ship-by, swapping Parakeet -> Deepgram for the address-
intake leg of the call (and using Parakeet for the rest) is feasible but
contradicts the "single demo path" rule in CLAUDE.md §0. Recommendation
is in `fix-candidates.md`.

## What WON'T help

- **Re-recording / re-prompting the caller verbatim.** Parakeet doesn't
  improve from re-tries on the same audio; it improves from different
  audio. If the caller repeats themselves slowly, accuracy may go up,
  but the FSM has no "ask the caller to repeat slowly" intent.
- **Increasing `INTERIM_INTERVAL_MS`** (`server.py:64`). That changes how
  often we *transcribe*, not how *accurate* the final is.
- **Moving to a bigger Parakeet (1.1B).** Same training corpus; gains
  are mostly on long-form dictation, not short-utterance address capture.
  Per the v3 model card, the WER deltas vs 0.6B are sub-percentage on
  short utterances.

## Sources (fetched 2026-04-26)

- `https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3` -- model card,
  documents punctuation/capitalization, 25 European languages, 24-min
  full-attention max audio. Does NOT mention hotword/boost in the bare
  `transcribe()` API.
- `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/asr_customization/word_boosting.html`
  -- GPU-PB (NGPU-LM) for CTC/RNN-T/TDT/AED. Config keys
  `rnnt_decoding.greedy.boosting_tree.key_phrases_file/list/context_score/depth_scaling`,
  `rnnt_decoding.boosting_tree_alpha`. NeMo >= 2.5.0.
- `https://docs.livekit.io/agents/models/stt/plugins/nvidia/` -- LiveKit
  NVIDIA STT plugin params: `language_code`, `model`, `server`,
  `enable_diarization`, `max_speaker_count`. **No** `keywords`, `boost`,
  `hotwords` parameters in the documented surface.
- `https://docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/asr-customizing.html`
  -- Riva-ONLY: `SpeechContext.phrases` with `boost` (recommended 20-100),
  `--decoding_vocab` build-time, ITN classes including `$ADDRESSNUM`,
  `$POSTALCODE`. Riva is a separate deployment from our raw NeMo container.
- `https://developers.deepgram.com/docs/keyterm` -- Nova-3 keyterm
  prompting (fetched via search summary).
- pod `/tmp/prism42-logs/worker.log`, `/healthz` JSON.
