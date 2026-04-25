# vendor/fish-speech — Prism42 inspection snapshot

## What this is

Source-only clone of `github.com/fishaudio/fish-speech` for read-only
analysis of the inference path. Goal: locate the Fish-Speech S2-Pro
TTFB / RTF bottleneck on our B300 pod (RTF 2.07 measured; SOTA target
< 0.4).

## Pinned SHA

```
3dd1f85c402ee6f0a17c2971d3b0dd8d881ca139
2026-04-06 12:09:59 -0400
"Fix UnboundLocalError for torchaudio in ReferenceLoader.__init__ (#1257)"
```

This is HEAD of `main` as of clone time (2026-04-25). No tag exists for
S2-Pro release; pyproject reports `version = "2.0.0"`.

## License — CRITICAL CAVEAT

The brief stated this repo is BSD-3. **It is NOT.** The file `LICENSE`
is the **Fish Audio Research License Agreement** ("FARL"), last updated
2026-03-07. Key clauses for our use case:

- Section II grants free use only for **Research** or **Non-Commercial**
  purpose.
- Section III: *"Any use of the Fish Audio Materials or Derivative
  Works for a Commercial Purpose requires a separate written license
  agreement from Fish Audio."*
- Commercial Purpose includes (verbatim from §V definitions): *"creating,
  modifying, or distributing Your product or service, including via a
  hosted service or application programming interface."*

Implication for the public Prism42 / GOATnote 911 console:

- The current usage (LiveKit voice agent serving the public PSAP demo)
  reads as **Commercial Purpose** under §V because it is a hosted
  product surface. We may need a Fish Audio commercial license OR to
  swap to a permissively-licensed model before any commercial framing.
- The "research / non-commercial" hackathon framing (April 2026 sprint)
  is defensible under §II for now, but the FARL is a permanent risk
  surface that the integrator should address with counsel before public
  GA.
- Any code we contribute upstream to fishaudio/fish-speech is feedback
  under §IV(v) — perpetual royalty-free license to Fish Audio. That is
  fine for our optimizations; we get attribution and Fish gets the
  patch. No compensation flows either way.

## What was inspected

- `tools/api_server.py` — Kui/uvicorn HTTP entry, 145 LOC
- `tools/server/views.py` — `/v1/tts` route, lines 146-205
- `tools/server/api_utils.py` — argparse defaults, MsgPack codec
- `tools/server/inference.py` — `inference_wrapper` adapter, 45 LOC
- `tools/server/model_manager.py` — model loader + warm-up, 93 LOC
- `fish_speech/inference_engine/__init__.py` — `TTSInferenceEngine`,
  the segment-by-segment yield orchestrator, 192 LOC
- `fish_speech/inference_engine/vq_manager.py` — DAC `from_indices`
  call, 53 LOC
- `fish_speech/models/text2semantic/inference.py` — `generate_long`,
  `generate`, `decode_n_tokens`, AR sampler. 966 LOC, focus on
  lines 96-238 (token loop) and 523-733 (batch loop)
- `fish_speech/models/text2semantic/llama.py` — DualAR model + KVCache
  + Attention with SDPA wiring, 1038 LOC
- `fish_speech/models/dac/modded_dac.py` — DAC vocoder + RVQ, 1045 LOC
- `fish_speech/configs/modded_dac_vq.yaml` — DAC architecture config
- `fish_speech/utils/schema.py` — `ServeTTSRequest` Pydantic schema

## What was NOT modified

This vendor tree is read-only. No Python imports from prism42 worker
code reach this directory. Nothing was installed; the runtime on the
B300 pod uses its own fish-speech checkout.

## Integrator decision needed

Two valid paths, document the choice when committing:

1. **Commit this snapshot.** Pro: deterministic SHA pin, easy to grep
   from the analysis report, future regressions diff-able. Con: 15 MB
   added to repo. Add `vendor/fish-speech/` to `.gitignore` for ALL
   subdirs except this README to ride this fence.
2. **gitignore entire `vendor/`.** Pro: keeps repo small. Con: future
   readers of `findings/voice/fish-fork-analysis/profile.md` must
   re-clone to verify file:line references; SHA pin lives only in this
   README file (which is also gitignored, so effectively in commit
   message only).

Recommendation: option 1, with the entire vendored tree committed once
and the SHA pin acting as the integrity marker. The repo grows by 15 MB
once and never again unless we re-pin.
