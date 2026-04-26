---
title: NVIDIA Riva / Nemotron Speech ASR — migration brief for Glasswing voice stack
date: 2026-04-24
status: research-only; no action applied
scope: B300 pod STT layer — compare Riva NIM + Nemotron Speech against current
       Parakeet TDT 0.6B v3 via NeMo 25.09 + custom server.py at :9100
---

# 22 — NVIDIA Riva / Nemotron Speech ASR

## 1. Riva vs raw NeMo — what Riva actually adds

Riva (now branded NVIDIA Speech NIM) is not a thin wrapper. It is a
production serving layer that ships the same NeMo model weights but
re-packages them with:

- **TensorRT export** — the model graph is compiled to TRT at container
  startup, yielding the latency floor the raw NeMo `.transcribe()` call
  cannot reach (NeMo runs PyTorch; no TRT by default).
- **Triton Inference Server** inside the container — handles batching,
  concurrency, and GPU stream management. Our `_MODEL_LOCK` asyncio
  mutex in `server.py` is a one-request-at-a-time serializer;
  Triton schedules concurrent requests across CUDA streams.
- **gRPC server at :50051 + REST/WebSocket health at :9000** — replaces
  our FastAPI server entirely.
- **Integrated pipeline components** — Silero VAD, CTC-based neural VAD,
  n-gram beam search decoder, inverse text normalization, punctuation/
  capitalization. These run as Triton sub-pipelines.
- **Sortformer speaker diarization** — a separate model loaded alongside
  the ASR model. Adds speaker labels to each final transcript in
  real time. Supported only on Parakeet-CTC and Conformer-CTC in
  streaming mode; NOT on TDT models.
- **TensorRT-accelerated streaming** — each audio chunk is encoded once
  through the TRT-compiled graph; the Riva server manages the
  per-connection state that our server.py manages manually.

Sources: NVIDIA Riva User Guide "ASR Overview"
(docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/asr-overview.html,
fetched 2026-04-24); NVIDIA Speech NIM overview
(docs.nvidia.com/nim/speech/latest/, fetched 2026-04-24).

## 2. Nemotron Speech ASR — distinct from Parakeet

Nemotron Speech is a **family** of models, not a single model. The
collection (huggingface.co/collections/nvidia/nemotron-speech) currently
has 12 items. The primary streaming member is:

**`nvidia/nemotron-speech-streaming-en-0.6b`** (January 2026)
- Architecture: **FastConformer-CacheAware-RNNT** (24 encoder layers,
  RNNT decoder, 600M parameters, 8x subsampling via depth-wise
  separable convolution)
- License: NVIDIA Open Model License Agreement (NOT Apache 2.0)
- NeMo runtime requirement: 25.11 or higher; Riva 2.25.0 or higher

Parakeet TDT 0.6B v3 (our current model) uses a **TDT** (Token-and-
Duration Transducer) decoder and standard (non-cache-aware) attention
(`att_context_style: regular`). It was designed for high-accuracy
offline/batch transcription. Nemotron Speech was designed from scratch
for low-latency streaming.

**Key distinction:** Nemotron Speech processes each audio frame exactly
once by maintaining per-layer encoder caches (self-attention + conv).
Parakeet TDT and our current server.py re-encode the growing prefix
buffer on every interim transcription pass (we measured ~19 ms per
re-transcribe on B300 for a 1.5 s buffer — cheap enough to ship, but
grows linearly with utterance length).

Nemotron Speech architecture citation: NVIDIA HuggingFace blog "Scaling
Real-Time Voice Agents with Cache-Aware Streaming ASR"
(huggingface.co/blog/nvidia/nemotron-speech-asr-scaling-voice-agents,
January 2026); HF model card nvidia/nemotron-speech-streaming-en-0.6b
(fetched 2026-04-24).

**Published latency (Nemotron Speech, H100, cache-aware mode):**
- Median time-to-final-transcription: **24 ms** (independent of
  utterance length, confirmed by Daily voice pipeline validation)
- At 127 concurrent clients: stable **182 ms** median delay with
  linear timestamp synchronization (Modal validation)
- B200 (DGX): 2x concurrency improvement vs H100 at 160 ms and 320 ms
  chunk modes
- B300-specific numbers: not yet published as of April 2026. B300 is
  faster per-SM than B200 for FP8/BF16; expect B300 >= B200 on throughput
  but no independent measurement is available

NVIDIA's "24 ms" and "sub-100 ms" claims are for Nemotron Speech
cache-aware mode. Parakeet TDT (batch) is not cited in those claims.

## 3. Riva NIM container — deployment on B300

**Container image:** `nvcr.io/nim/nvidia/$CONTAINER_ID:latest`
where CONTAINER_ID is e.g. `parakeet-1-1b-ctc-en-us`.

**Exact docker run (from NVIDIA tutorials, fetched 2026-04-24):**
```bash
docker run -it --rm --name=$CONTAINER_ID \
  --runtime=nvidia \
  --gpus '"device=0"' \
  --shm-size=8GB \
  -e NGC_API_KEY \
  -e NIM_HTTP_API_PORT=9000 \
  -e NIM_GRPC_API_PORT=50051 \
  -p 9000:9000 \
  -p 50051:50051 \
  -e NIM_TAGS_SELECTOR \
  nvcr.io/nim/nvidia/$CONTAINER_ID:latest
```

Add `--ulimit nofile=2048:2048` for Parakeet 1.1B to avoid "too many
open files" errors. First run downloads model weights + runs TensorRT
compilation — up to **30 minutes** before the container accepts requests.

**Ports:** gRPC on :50051, HTTP/WebSocket on :9000. Port 50051 is Riva's
hardcoded default and is unambiguously free on a fresh B300 pod (our
Parakeet server uses :9100).

**GPU memory:** 16+ GB VRAM recommended to avoid OOM on model load.
Our B300 pod has 288 GB HBM3E — memory is not a constraint for any
single-model Riva NIM.

**Sortformer diarization memory cost:** Sortformer is a separate model
loaded alongside the ASR model when `asr_accessory_model=diarizer` is
set in pipeline config. Approximate additional VRAM: ~2-4 GB (not
officially documented; estimated from model parameter count). On a B300
with 288 GB this is negligible.

**NGC API key:** Free Developer Program license allows self-hosting on up
to 16 GPUs for R&D. Production use requires NVIDIA AI Enterprise (NVAIE)
license (90-day free trial available). Free NGC Developer key suffices for
our pod under the 16-GPU cap.

**Blackwell / B300 support status:**
- Riva now uses TensorRT 10.13 with Blackwell GPU architecture support
  (confirmed in recent release notes, fetched 2026-04-24)
- Parakeet **1.1B RNNT Multilingual** is explicitly listed as supported
  on Blackwell and DGX Spark
- Parakeet **TDT 0.6B v3** (our current model): NOT listed as supported
  in Riva NIM on Blackwell in available documentation. The v2 (English-
  only) and v3 (multilingual) are listed under the Parakeet 0.6B TDT NIM
  container but Blackwell support is not confirmed for TDT in that
  container
- Nemotron Speech streaming 0.6B HF card lists V100, A100, A6000, DGX
  Spark, and "Ampere, Blackwell, Hopper, Volta architectures" as
  compatible — but requires NeMo 25.11+

Sources: Support Matrix docs.nvidia.com/nim/riva/asr/latest/support-matrix.html;
speech NIM support matrix docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html
(fetched 2026-04-24).

## 4. livekit-plugins-nvidia

**Install:** `livekit-agents[nvidia]~=1.4` (also works with 1.5.x)

**Import:**
```python
from livekit.plugins import nvidia
stt = nvidia.STT(
    model="parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer",
    server="grpc.nvcf.nvidia.com:443",   # cloud default
    # For self-hosted B300 Riva NIM:
    # server="localhost:50051",
    # use_ssl=False,
    api_key=...,                          # not needed for self-hosted
    enable_diarization=False,
    language_code="en-US",
)
```

**Self-hosted Riva endpoint:** Set `server="localhost:50051"` and
`use_ssl=False`. The plugin talks gRPC to whatever Riva NIM is at that
address. No code change beyond the constructor call is needed.

Source: LiveKit NVIDIA Riva STT plugin docs
(docs.livekit.io/agents/models/stt/plugins/nvidia/, fetched 2026-04-24);
Python API reference docs.livekit.io/reference/python/v1/livekit/plugins/nvidia/index.html
(fetched 2026-04-24).

**Default model in livekit-plugins-nvidia:**
`parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer` — this is the
Parakeet **1.1B** RNNT model with Silero VAD + Sortformer diarization
pre-wired. It is **not** our TDT-0.6B-v3. Pointing it at a local Riva
NIM serving a different model requires matching the `model` parameter to
the NIM's deployed model name.

The plugin advertises `streaming=True, interim_results=True` —
`capabilities.streaming` and `capabilities.interim_results` are both True,
meaning livekit-agents will use the `stream()` path, not `StreamAdapter`.

## 5. Riva streaming protocol — interim/final/PREFLIGHT

Riva's gRPC streaming protocol (`StreamingRecognizeResponse`) uses an
`is_final` boolean field:
- `is_final=False` → interim result (may change); also carries a
  `stability` float [0.0-1.0] indicating how stable the hypothesis is
- `is_final=True` → final result for that utterance segment; no further
  hypotheses returned for that audio

Riva emits interim results continuously while audio streams, then emits
a final when it detects end-of-utterance (VAD-triggered). This maps to
livekit-agents `SpeechEventType.INTERIM_TRANSCRIPT` (for is_final=False)
and `FINAL_TRANSCRIPT` (is_final=True).

**PREFLIGHT_TRANSCRIPT support:** livekit-plugins-nvidia does NOT
document emitting `SpeechEventType.PREFLIGHT_TRANSCRIPT`. Our custom
`parakeet_stt.py` emits PREFLIGHT on stable-prefix detection
(when the partial text is identical to the last partial — the "preflight"
heuristic in `server.py:ws_stream`). Riva's `stability` field is
conceptually equivalent but the LiveKit plugin does not map it to
PREFLIGHT. Loss of PREFLIGHT means lever #12 (LLM trigger on STT partial)
fires later than it would with our current plugin once lever #2 (streaming
/ws) is deployed.

Source: NVIDIA Riva gRPC proto docs
(docs.nvidia.com/deeplearning/riva/user-guide/docs/reference/protos/protos.html,
fetched 2026-04-24).

## 6. Latency on Blackwell — what is published

| Setup | Platform | Median final transcript | Notes |
|---|---|---|---|
| Nemotron Speech, cache-aware, 160 ms chunk | H100 | 24 ms | NVIDIA blog, Jan 2026 |
| Nemotron Speech, 127 concurrent clients | Modal (unspecified GPU) | 182 ms | Modal validation |
| Nemotron Speech | NVIDIA L40 | 90 ms | NVIDIA blog |
| Nemotron Speech | Cloud APIs | 200+ ms | NVIDIA blog |
| Nemotron Speech, B200 | DGX B200 | 2x concurrency vs H100 | latency not published |
| B300 (any model) | B300 | not published | B300 faster per-SM than B200 |
| Parakeet-unified-en-0.6b, 160 ms chunk | claimed (any NVIDIA GPU) | 160 ms minimum | HF card, April 2026 |
| **Our Parakeet-TDT-0.6B-v3, batch** | B300 | **614 ms median** | bench_b300.py N=10 |

The 24 ms figure is specific to Nemotron Speech cache-aware streaming and
is not portable to Parakeet TDT. The B300 is architecturally faster than
the B200 (55.6% more FP4 TFLOPS, 8 TB/s vs 7.7 TB/s bandwidth) — on a
600M-parameter model the bottleneck is typically memory bandwidth, so B300
latency should be at most marginally better than B200, possibly identical
at the chunk-size floor.

## 7. Current setup vs Riva NIM — delta and trade-offs

Our current server.py/parakeet_stt.py with Parakeet TDT 0.6B v3:

**Latency:** 614 ms median (batch path, lever #2 not yet prod-deployed).
With lever #2 (WebSocket /ws + streaming partials), our server.py already
emits partials at 160 ms intervals with prefix-stable PREFLIGHT events.
Expected t_stt_ms: ~160-200 ms once lever #2 lands.

**What we lose by moving to Riva NIM:**
1. `PREFLIGHT_TRANSCRIPT` events — livekit-plugins-nvidia does not emit
   them. Lever #12 (preemptive LLM gen on partial) degrades.
2. Custom `PRISM42_PARAKEET_STREAMING` env flag — trivially replaceable
   with a `STT_BACKEND` env var analogous to `TTS_BACKEND`.
3. Parakeet TDT 0.6B v3 model specifically — Riva's default is Parakeet
   1.1B RNNT Multilingual. TDT-v3 is not confirmed as a Riva-supported
   model on Blackwell. Moving to Riva means moving to Parakeet 1.1B RNNT
   or Nemotron Speech, with a WER regression possible.
4. `/healthz`, custom word-alignment output — minor; easily rewritten to
   Riva's HTTP :9000 health endpoint.
5. The 30-minute TRT compilation at first container start is a cold-start
   penalty that our plain NeMo server avoids.

**What we gain:**
- TensorRT inference: potentially 2-3x throughput, possibly 30-50% lower
  per-call latency vs PyTorch NeMo on the same model
- Triton batching: concurrent call handling without our `_MODEL_LOCK`
  serializer (relevant if call volume scales)
- Riva-managed VAD pipeline: Silero + Sortformer built in
- Direct support from livekit-plugins-nvidia, eliminating custom glue

## 8. Migration bottlenecks

**NGC API key:** Free Developer Program key suffices for up to 16 GPUs.
No enterprise license needed for our single-pod deployment. Key
provisioned at build.nvidia.com — takes minutes, no approval gate.

**License:** Riva NIM is under NVIDIA AI Enterprise EULA for production
deployment, Free Developer Program for R&D. Nemotron Speech 0.6B model
weights are under the NVIDIA Open Model License Agreement — NOT Apache 2.0.
Parakeet TDT 0.6B v3 is also under NVIDIA Open Model License. No license
regression on the model side.

**Port conflict:** Riva NIM runs gRPC on :50051. Our Parakeet server runs
on :9100. No conflict. The only change needed is livekit-plugins-nvidia
`server="localhost:50051"` instead of our custom `parakeet_stt.py`.

**Audio codec:** LiveKit emits audio as 16kHz Opus from the WebRTC media
plane. Riva NIM accepts: WAV, OPUS, FLAC (mono, 16-bit). Opus at 8K,
16K, 24K, 48K sampling rates are supported. 16kHz Opus from LiveKit is
directly compatible — no transcoding layer needed.

**Sortformer diarization:** Separate model co-loaded in the NIM container.
Only supported with Parakeet-CTC and Conformer-CTC ASR models in streaming
mode. If we use Parakeet 1.1B RNNT Multilingual (the default in
livekit-plugins-nvidia), the model name indicates Sortformer is bundled.
Memory cost on B300 (288 GB) is negligible.

**Parakeet TDT 0.6B v3 not confirmed on Riva/Blackwell:** If we want to
stay on TDT-v3, raw NeMo is the only supported path. Riva's Blackwell-
confirmed model is Parakeet 1.1B RNNT Multilingual.

**TRT cold-start:** 30 minutes per container restart. Our NeMo server cold-
starts in ~60-90 seconds. Mitigated by keeping the Riva container always-
on.

**PREFLIGHT gap:** The primary latency lever (#12 — LLM trigger on
partial) requires PREFLIGHT_TRANSCRIPT events. Riva emits interim
results via is_final=False with a `stability` field, but livekit-
plugins-nvidia does not map that stability to PREFLIGHT. To get
PREFLIGHT from Riva we would need a thin proxy/shim that converts
high-stability Riva interim results to SpeechEventType.PREFLIGHT_TRANSCRIPT.
This is the binding technical blocker for a clean Riva migration.

## 9. Migration options ranked by ROI

### Option (a) — Stay on raw NeMo + finish streaming /ws prod swap (lever #2)

**Rationale:** server.py already has a fully-implemented WebSocket /ws
endpoint emitting partial → preflight → final events. parakeet_stt.py
already has the `ParakeetSpeechStream` client wired. The only remaining
work is the prod swap: kill pid 60210 (old batch server) and relaunch
with the new server.py. Expected delta: -400 ms off t_stt_ms, plus lever
#12 (LLM on PREFLIGHT) fires properly once /ws is prod.

**Cost:** ~1 hour of eng time. No new infrastructure. No license change.
No PREFLIGHT gap. PRISM42_PARAKEET_STREAMING env flag already wired.

**Latency floor:** ~160-200 ms t_stt_ms (160 ms is Nemotron-class chunk
latency, not TDT architecture latency — our re-transcription at 160 ms
intervals on a 1.5 s buffer takes ~19 ms per pass on B300). Combined with
lever #12, effective caller-perceived TTFT approaches Sonnet-4.6 TTFT.

### Option (b) — Migrate to Riva NIM (Parakeet 1.1B RNNT Multilingual)

**Rationale:** Drops custom server.py, uses livekit-plugins-nvidia, gets
TRT acceleration and Triton batching. True plug-in with the LiveKit plugin
ecosystem.

**Blockers:**
- Lose PREFLIGHT_TRANSCRIPT without a shim (~4h to write and validate)
- Parakeet TDT 0.6B v3 not supported; must accept Parakeet 1.1B RNNT
  (different WER profile, needs fresh bench)
- 30-min TRT cold-start per container restart (tolerable for always-on)
- NGC API key provisioning (30 min, no approval gate)
- First model download + TRT compile: ~30 min (one-time per pod)

**Expected latency post-migration:** Not benchmarked on B300 with Riva.
The Riva Parakeet RNNT at TRT precision should be in the 100-200 ms range
for streaming finals. The 24 ms Nemotron figure does not apply here.

**Net ROI vs (a):** Questionable. We get TRT acceleration and drop custom
infra, but give up PREFLIGHT (lever #12) unless we write the shim. Model
changes from TDT-v3 to RNNT-1.1B — likely better WER (1.1B vs 0.6B) but
larger memory footprint (still trivial on B300).

### Option (c) — Nemotron Speech ASR (cache-aware FastConformer-RNNT)

**Rationale:** Architecturally superior for streaming. Cache-aware design
is the right architecture for 24 ms median latency. HF model card confirms
Blackwell compatibility. WER competitive with or better than Parakeet CTC
1.1B.

**Blockers:**
- Requires NeMo 25.11+. Our container is NeMo 25.09 (lever #9 landed
  nemo:25.09). A container bump is needed.
- livekit-plugins-nvidia defaults to Parakeet 1.1B; for Nemotron Speech
  via Riva we would need Riva 2.25.0+ with Nemotron Speech model loaded —
  no public NIM container ID for Nemotron Speech confirmed in available
  documentation as of April 2026.
- No published B300 latency. Architecture suggests it will match or beat
  H100 numbers (24 ms), but needs measurement.
- PREFLIGHT gap: same as option (b) unless NeMo direct path is used
  (NeMo 25.11 direct in server.py, model changed to nemotron-speech).
- NVIDIA Open Model License — same constraint as Parakeet; non-issue.

**Direct NeMo path for (c):** Load nemotron-speech-streaming-en-0.6b in
our server.py (swap MODEL_NAME env var), use NeMo 25.11 container,
implement cache-aware streaming via `speech_to_text_cache_aware_streaming_infer.py`.
This is essentially lever #2 completion + model upgrade: retains our
PREFLIGHT semantics, avoids the Riva migration complexity.

**ROI:** Highest ceiling (24 ms architecture-floor latency), highest
implementation complexity, most unknowns on B300.

---

## Recommendation

**Short term: (a) first.** Finish the lever #2 prod swap. That alone
delivers -400 ms and unlocks PREFLIGHT (lever #12) with zero new
infrastructure risk. Estimated prod impact: t_stt_ms 614 → ~200 ms,
enabling LLM preemptive generation to fire on stable partials.

**Medium term: (c) direct NeMo path.** After lever #2 lands and is
measured, evaluate a NeMo container bump to 25.11 + swap MODEL_NAME to
`nvidia/nemotron-speech-streaming-en-0.6b`. This keeps our PREFLIGHT
semantics, gets the cache-aware architecture (24 ms floor on H100/B200),
and avoids the Riva migration complexity. Bench on B300 before committing.

**Skip (b) unless PREFLIGHT is not required.** Riva NIM is the right
answer if: (1) the PREFLIGHT shim is written, (2) the Parakeet 1.1B RNNT
model is benchmarked and WER is acceptable, and (3) the TRT cold-start
is managed by always-on container policy. Do not migrate to Riva to get
the 24 ms number — that number is Nemotron Speech, not Parakeet RNNT.

---

## Sources

- NVIDIA Riva ASR Overview: docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/asr-overview.html
- NVIDIA Speech NIM Microservices: docs.nvidia.com/nim/speech/latest/
- NVIDIA NIM Riva ASR Getting Started: docs.nvidia.com/nim/riva/asr/latest/getting-started.html
- NVIDIA NIM Riva ASR Support Matrix: docs.nvidia.com/nim/riva/asr/latest/support-matrix.html
- NVIDIA ASR NIM Support Matrix (Speech NIM): docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html
- NVIDIA NIM Riva ASR Release Notes: docs.nvidia.com/nim/riva/asr/latest/release-notes.html
- Nemotron Speech HF blog (Jan 2026): huggingface.co/blog/nvidia/nemotron-speech-asr-scaling-voice-agents
- Nemotron Speech model card: huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
- LiveKit NVIDIA STT plugin: docs.livekit.io/agents/models/stt/plugins/nvidia/
- LiveKit Python API ref: docs.livekit.io/reference/python/v1/livekit/plugins/nvidia/index.html
- Riva gRPC proto: docs.nvidia.com/deeplearning/riva/user-guide/docs/reference/protos/protos.html
- NVIDIA Speech NIM tutorial (docker run): docs.nvidia.com/nim/speech/latest/get-started/tutorials/asr.html
- NVIDIA NIM free tier: costbench.com/software/llm-api-providers/nvidia-nim/free-plan/
- Parakeet TDT 0.6B v3 HF card: huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Parakeet unified 0.6B HF card: huggingface.co/nvidia/parakeet-unified-en-0.6b
- Our Parakeet bench: docs/livekit-kb/09-b300-voice-bench.md
- Our server.py: infra/b300/services/parakeet/server.py
- Our parakeet_stt.py: agents/livekit/parakeet_stt.py
- Lever registry: docs/livekit-kb/16a-lever-registry.yaml (lever #2, #12)
