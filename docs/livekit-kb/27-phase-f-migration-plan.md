---
title: Phase F Migration Plan — NeMo 25.11 + Nemotron Speech + Fish torch.compile
date: 2026-04-24
status: research-complete; pre-execution
scope: B300 pod STT layer swap (Parakeet TDT v3 → Nemotron Speech 0.6B) +
       NeMo container bump (25.09 → 25.11) + Fish torch.compile re-attempt
depends-on: Phase D acceptance gate (vLLM serving, strict gate per doc 25)
---

# 27 — Phase F Migration Plan

> Research-only doc. No pod state changes until Phase D strict gate passes.
> Every claim is cited; unknowns are labeled.

---

## Topic 1 — NeMo Container 25.11 Release Notes

### What changed vs 25.09

| Item | 25.09 | 25.11 |
|---|---|---|
| CUDA | 12.9.1 | 13.0.1 (framework) / 13.0.2.006 (PyTorch container) |
| PyTorch | 2.8.0a0+5228986c39.nv25.6 | 2.9.0a0 (NeMo frame) / 2.10.0a0 (PyTorch container) |
| Python | Not pinned in public docs | 3.12 (PyTorch container baseline) |
| Container tag | nvcr.io/nvidia/nemo:25.09 | nvcr.io/nvidia/nemo:25.11 (→ :25.11.01) |

ASR-specific additions confirmed in 25.11 release notes:
- **FeatureBuffer support added to Cache-Aware streaming pipeline** — the new
  class that allows NeMo's PipelineBuilder to accumulate audio feature chunks
  before passing to the cache-aware encoder, enabling lower-overhead chunk
  ingestion from external audio streams like our WebSocket server.
- **Per-Stream Phrase Boosting in ASR Decoding (Transducers)** — runtime-
  configurable hot-word boosting per WebSocket session without server restart.
  Irrelevant to Nemotron Speech swap but useful for future dispatcher
  domain vocabulary work.
- **torchaudio removed; audio transforms moved inside NeMo** — dependency
  reduction. No user-visible API change for the `ASRModel.from_pretrained` +
  `transcribe()` path. Requires re-pinning the container's torchaudio dep if
  any downstream code imports it directly (our server.py does not).
- **NeMo 2.0 LLM/VLM deprecated** in 25.11, replaced by NeMo Megatron-Bridge
  and NeMo AutoModel. ASR collection (`nemo.collections.asr`) is unaffected;
  deprecation is LLM-only.

### Breaking changes for Parakeet TDT 0.6B v3 users

One: `torch.load` defaults to `weights_only=True` as of PyTorch 2.6 (backfilled
in 25.11 container). Parakeet TDT v3 checkpoints may require:

```bash
TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 python ...
```

Set this in the systemd EnvironmentFile before bumping the container. If not
set and the checkpoint has non-tensor objects, `ASRModel.from_pretrained` will
raise a `UnpicklingError` on first load. The rollback is instant: revert the
env var.

Two: if the existing server.py imports `torchaudio` anywhere (it does not),
that import breaks on 25.11. Current server.py is clean.

No breaking changes to the `nemo_asr.models.ASRModel.from_pretrained()` or
`model.transcribe()` API surface between 25.09 and 25.11.

### sm_103 / Blackwell status in 25.11

The 25.11 container ships CUDA 13.0.1 (driver 570.x, which includes sm_103a-
aware ptxas). The known Triton PTXAS sm_103a regression (described in doc 20)
**is fixed at the container level** — the system ptxas at /usr/local/cuda/bin/ptxas
in the 25.11 container understands sm_103a. Bundled Triton in the container is
Triton 3.6+ (aligned with PyTorch 2.9/2.10); the regression existed in Triton
3.4.x bundled with stable torch 2.8. See "Fix paths" in Topic 3 below.

Sources:
- NeMo Software Component Versions: docs.nvidia.com/nemo-framework/user-guide/latest/softwarecomponentversions.html (fetched 2026-04-24)
- NeMo Framework Changelog 25.11: docs.nvidia.com/nemo-framework/user-guide/latest/changelog.html (fetched 2026-04-24)
- PyTorch Container 25.11 release notes: docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-25-11.html (fetched 2026-04-24)

---

## Topic 2 — `nvidia/nemotron-speech-streaming-en-0.6b` Model Card

### Architecture

FastConformer-CacheAware-RNNT:
- 24-layer FastConformer encoder with self-attention cache + convolution cache
  per layer (cache-aware means each frame is encoded exactly once; no prefix
  re-encoding on every chunk)
- RNNT decoder (same transducer family as our current Parakeet TDT; different
  from Parakeet CTC)
- 8x downsampling via depth-wise separable convolution subsampling (vs 4x on
  most non-cache-aware Conformers — fewer encoder tokens/sec, lower VRAM
  pressure per stream)
- 600M parameters — same count as Parakeet TDT 0.6B v3

Updated March 12, 2026: newer checkpoint trained on 530k hours (vs January
2026 original). January 2026 checkpoint preserved on
`nemotron-speech-streaming-jan2026` branch. Use `main` (March 2026) unless WER
regression is observed.

Sources: huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b (fetched 2026-04-24);
huggingface.co/blog/nvidia/nemotron-speech-asr-scaling-voice-agents (fetched 2026-04-24)

### License

NVIDIA Open Model License Agreement (NVIDIA Open Model License, not Apache 2.0).
Same license class as Parakeet TDT 0.6B v3. Commercial and non-commercial use
permitted. No regression vs current setup.
Source: nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/

### Compatible with raw NeMo (not Riva-only)?

Yes. Model card confirms NeMo 25.11 direct path:

```python
import nemo.collections.asr as nemo_asr
model = nemo_asr.models.ASRModel.from_pretrained(
    "nvidia/nemotron-speech-streaming-en-0.6b"
)
```

Cache-aware streaming inference uses:
```python
from nemo.collections.asr.inference.factory.pipeline_builder import PipelineBuilder
from omegaconf import OmegaConf

cfg = OmegaConf.load('cache_aware_rnnt.yaml')
pipeline = PipelineBuilder.build_pipeline(cfg)
output = pipeline.run(audios)
```

Or the NeMo example script at:
`NeMo/examples/asr/asr_cache_aware_streaming/speech_to_text_cache_aware_streaming_infer.py`

The FeatureBuffer addition in 25.11 (see Topic 1) makes the PipelineBuilder
compatible with streaming chunk ingestion without buffering full utterances.

### Does our existing server.py `/ws` need changes?

Yes — significant internal changes, same external WebSocket contract. Details
in Topic 5.

### Sample rate + audio format

- 16 kHz mono, standard ASR format confirmed by NVIDIA blog.
- WAV container for file-based inference; raw PCM16 works for the
  cache-aware streaming path (same as our current server.py receives).
- No transcoding layer needed.

Source: huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b model card (fetched 2026-04-24)

### Token-level timing / event API

The model card and NVIDIA blog do NOT document a `partial`/`preflight`/`final`
event protocol at the NeMo level. NeMo's cache-aware RNNT emits text per
chunk; it is our server.py that must:
1. Emit each chunk result as `{"type":"partial","text":"...","ms":...}`.
2. Apply our existing stable-prefix heuristic (text == last_text) to emit
   `{"type":"preflight",...}`.
3. Emit `{"type":"final",...}` on client flush.

The protocol seen by livekit-agents (parakeet_stt.py) does not change. The
internal transcription method changes from `model.transcribe([pcm_buffer])` on
every interim to `pipeline.ingest_chunk(chunk)` → `pipeline.get_partial()` per
chunk. Emitting PREFLIGHT is preserved in our server.py layer. LiveKit lever
#12 remains operative.

### Memory footprint vs Parakeet TDT v3

Both are 600M-parameter models. Expected VRAM at inference:
- Parakeet TDT 0.6B v3: ~9 GB (measured, B300 bench doc 09)
- Nemotron Speech 0.6B: ~9 GB expected [unverified — parameter count is
  identical; cache tensors add ~0.3-1 GB per concurrent stream depending on
  chunk size and left-context config; for 1 stream at 160ms chunks, estimate
  ~0.5 GB additional cache overhead = ~9.5 GB total]

Benchmark on first boot is required. No published B300-specific number.

Source: huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b; huggingface.co/blog/nvidia/nemotron-speech-asr-scaling-voice-agents

---

## Topic 3 — Fish torch.compile with CUDA 13 nvcc: Updated Status

### Prior situation (from doc 20, 2026-04-25)

- Stable PyTorch 2.9.1+cu130 shipped with Triton that bundled an sm_103a-
  unaware ptxas. `torch.compile(mode="default", fullgraph=True)` on Fish's
  autoregressive decoder failed with `PTXASError: Internal Triton PTX codegen
  error`.
- `.venv-nightly` (torch 2.13.dev20260424+cu130 + Triton 3.7.0+git88b227e)
  was confirmed sm_103a-aware and is already on the pod.

### What changes when Phase D uses .venv-nightly for vLLM?

Phase D's recipe (doc 25, Phase C addendum) builds vLLM inside `.venv-nightly`,
which already has Triton 3.7 with sm_103a support. Once vLLM is running on
`.venv-nightly`, we know the full torch+Triton stack on the pod is nightly-based.

Fish's own `tools/api_server.py` runs in a separate venv (the fish-speech
project venv). Fish's `--compile` flag invokes `torch.compile` through Fish's
own Python environment. **If Fish's venv still pins torch 2.8 stable, the
PTXAS error recurs even after vLLM runs fine in .venv-nightly.**

### The safe re-attempt path

Option A (recommended): Launch a second Fish instance inside `.venv-nightly`
with `--compile`:

```bash
# Fish S2-Pro on port 9201, compile-enabled, .venv-nightly torch
/opt/prism42/infra/b300/services/fish-speech/.venv-nightly/bin/python \
  tools/api_server.py \
  --listen 127.0.0.1:9201 \
  --device cuda \
  --compile \
  --checkpoint-path checkpoints/s2-pro
```

Acceptance gate: RTF < 1.0 (audio_duration_ms > synthesis_wall_ms). If RTF
stays >= 1.0, fall back: kill 9201, prism42-fish.service stays on 9200.

Option B (defensive guard already drafted in doc 20, Option B): Apply the
`_can_safely_compile()` patch upstream to fish-speech. The guard auto-disables
`--compile` on B300 + torch < 2.11, prints an actionable warning, and falls
back to eager. This prevents the 500-on-every-request crash mode if `--compile`
is added to the production unit before confirming .venv-nightly is in the PATH.

**Recommended order**: Apply Option B guard first (12 lines, zero risk), then
test Option A.

### Why CUDA 13 nvcc specifically matters for Phase F

The NeMo 25.11 container bundles CUDA 13.0.1, which includes a ptxas binary
that recognizes sm_103a. If Phase F uses the NeMo 25.11 container for the
Parakeet/Nemotron service (rather than pip-installing nemo into .venv-nightly),
the container's ptxas is authoritative. No further torch.compile-specific
workaround is needed inside that container for NeMo's own inference.

For Fish: Fish is NOT inside the NeMo container. It runs as a separate
systemd service. The `.venv-nightly` Triton (3.7, sm_103a-aware) is the
required torch stack for Fish `--compile` to work.

Source: Doc 20 (2026-04-25); PyTorch Release 25.11 notes (CUDA 13.0.2.006);
NeMo Software Component Versions (CUDA 13.0.1 in 25.11 container).

---

## Topic 4 — Co-Residency Budget After vLLM Lands

### Current baseline (doc 23 §3)

```
Parakeet TDT 0.6B v3      ~9.0 GB
Fish S2-Pro               ~8.0 GB
CUDA context overhead     ~1.5 GB (2 processes × ~0.75 GB)
Total pre-vLLM            ~18.5 GB
B300 HBM3E total           275 GB
Free                       ~256 GB
```

### After Phase D (vLLM + Nemotron Nano 3 MoE NVFP4)

```
vLLM (NVFP4 weights + KV cache + CUDA context)   ~47-51 GB (at gpu_mem_util=0.20)
Parakeet TDT 0.6B v3                              ~9.0 GB
Fish S2-Pro (eager)                               ~8.0 GB
Fish S2-Pro (compile, second instance at 9201)    ~8.0 GB (weights shared in HBM;
                                                   second instance adds ~0.5 GB
                                                   compile graph buffers) [unverified]
CUDA context overhead (4 processes)               ~3.0 GB
TOTAL (worst case, 4 processes)                   ~69-73 GB
B300 remaining (of 275 GB)                        ~202-206 GB free
```

### After Phase F (swap Parakeet → Nemotron Speech)

Nemotron Speech 0.6B estimated at ~9.5 GB (same parameter count as Parakeet
TDT v3, ~0.5 GB added for per-stream encoder cache at 1 concurrent session).
Net change: **+0.5 GB** vs Parakeet at rest. No material co-residency impact.

**Can both Parakeet TDT v3 and Nemotron Speech run simultaneously?**

Yes, with ~18.5 GB for both plus ~3 GB context = ~21.5 GB combined. Well within
budget. However there is no operational reason to co-host both permanently.
Suggested pattern: run Nemotron Speech at 9100 (swapping in-place), keep
Parakeet TDT v3 at 9102 as a warm standby for A/B benchmarking, then terminate
9102 after acceptance gate passes.

```
Post-Phase-F GPU budget summary:
  vLLM Nemotron Nano 3 NVFP4           ~51 GB (gpu_mem_util=0.20 ceiling)
  Nemotron Speech 0.6B (port 9100)      ~9.5 GB
  Fish S2-Pro compile (port 9201)       ~8.5 GB
  CUDA context (3 active processes)     ~2.5 GB
  TOTAL                                 ~71.5 GB
  Free of 275 GB                        ~203 GB  (74% idle)
```

If vLLM is bumped to `--gpu-memory-utilization 0.30` (82.5 GB) for longer
context or higher concurrency, total rises to ~102 GB, still leaving 63% of
HBM3E free.

---

## Topic 5 — server.py Changes for Nemotron Speech Streaming

### What changes

The external WebSocket contract (`/ws` protocol: binary PCM16 in, JSON events
out) is preserved unchanged. parakeet_stt.py and livekit-agents do not change.

Internal transcription path changes from:

```python
# CURRENT: re-transcribe growing buffer every INTERIM_INTERVAL_MS
model.transcribe([pcm_buffer], batch_size=1, verbose=False)
```

To (cache-aware path):

```python
# PHASE F: ingest chunk once, get partial per chunk
pipeline.ingest_chunk(new_chunk_pcm)        # processes only new audio
partial_text = pipeline.get_partial()        # returns current hypothesis
```

### Exact diff (conceptual — validate against NeMo 25.11 PipelineBuilder API)

**Step 1: New env var and model load**

```python
# In server.py, top-level constants:
MODEL_NAME = os.environ.get("MODEL", "nvidia/nemotron-speech-streaming-en-0.6b")
CACHE_AWARE = os.environ.get("NEMOTRON_CACHE_AWARE", "1") == "1"
```

**Step 2: Model load path — add PipelineBuilder branch**

```python
def _load_model():
    global _MODEL, _PIPELINE
    import nemo.collections.asr as nemo_asr

    if CACHE_AWARE:
        from nemo.collections.asr.inference.factory.pipeline_builder import PipelineBuilder
        from omegaconf import OmegaConf
        cfg = OmegaConf.load(
            os.environ.get("CACHE_AWARE_CFG", "/opt/prism42/infra/b300/services/parakeet/cache_aware_rnnt.yaml")
        )
        _PIPELINE = PipelineBuilder.build_pipeline(cfg)
        print(f"[nemotron] cache-aware pipeline loaded", flush=True)
    else:
        _MODEL = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
        _MODEL.eval()
        if torch.cuda.is_available():
            _MODEL = _MODEL.to("cuda")
```

**Step 3: /ws endpoint — replace transcribe_buf with chunk-ingest path**

```python
# CURRENT transcribe_buf (in ws_stream):
async def transcribe_buf(final: bool) -> dict | None:
    ...
    hyps = model.transcribe([pcm], batch_size=1, verbose=False)
    text, conf = _extract_text_score(hyps)
    ...

# PHASE F transcribe_buf:
async def transcribe_buf(final: bool) -> dict | None:
    nonlocal last_text
    if not CACHE_AWARE:
        # Original path preserved for MODEL_NAME=parakeet-tdt-0.6b-v3
        ...
        return payload

    # Cache-aware path: pipeline already has accumulated state
    # For interim: get current partial hypothesis from pipeline
    # For final: flush pipeline, get last hypothesis, reset state
    async with _MODEL_LOCK:
        if final:
            text = _PIPELINE.flush()   # flush and reset per-utterance cache
        else:
            text = _PIPELINE.get_partial()
    conf = 0.9  # RNNT doesn't expose per-token confidence in partial path
    ...
```

NOTE: `_PIPELINE.ingest_chunk()`, `_PIPELINE.get_partial()`, and
`_PIPELINE.flush()` are the expected API surface based on the NeMo 25.11
FeatureBuffer + PipelineBuilder design. **The exact method names must be
verified against the NeMo 25.11 source** at
`NeMo/nemo/collections/asr/inference/factory/pipeline_builder.py` before
writing the final diff. The conceptual shape (ingest per chunk, get partial,
flush on utterance end) is confirmed by the model card and blog post.

**Step 4: Binary frame handler in ws_stream — add chunk ingest call**

```python
if "bytes" in msg and msg["bytes"] is not None:
    data = msg["bytes"]
    if utterance_t0 is None:
        utterance_t0 = time.monotonic()
    pcm_bytes.extend(data)
    bytes_since_interim += len(data)

    if CACHE_AWARE:
        # Ingest this chunk into the pipeline's feature buffer immediately
        new_pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        async with _MODEL_LOCK:
            _PIPELINE.ingest_chunk(new_pcm)

    if bytes_since_interim >= INTERIM_INTERVAL_BYTES:
        bytes_since_interim = 0
        payload = await transcribe_buf(final=False)
        if payload is not None:
            await ws.send_json(payload)
    continue
```

**Step 5: Config YAML for PipelineBuilder**

A `cache_aware_rnnt.yaml` must be authored and placed at
`/opt/prism42/infra/b300/services/parakeet/cache_aware_rnnt.yaml`.
The minimum config (based on model card's `att_context_size` parameter):

```yaml
model_path: nvidia/nemotron-speech-streaming-en-0.6b
device: cuda
chunk_size: 160   # ms; matches our INTERIM_INTERVAL_MS
att_context_size: [70, 1]  # [left_frames, right_frames] at 80ms/frame → 160ms latency
batch_size: 1
```

**Step 6: Rolling buffer / max_buffer_s**

The cache-aware pipeline maintains its own encoder state; our `pcm_bytes`
rolling buffer is still used for the warmup transcribe at startup and the
`PREFLIGHT` heuristic (compare current partial to last partial). Keep the
buffer; do not refactor it out until the PipelineBuilder API is confirmed.

### JSON event contract — no change

```
{"type":"partial","text":"...","ms":123}   ← unchanged
{"type":"preflight","text":"...","ms":234} ← unchanged (our server.py layer)
{"type":"final","text":"...","ms":456,"confidence":0.92} ← unchanged
```

---

## Topic 6 — Migration Risk Ranking

Ordered by risk × reward (highest risk × highest reward first):

### Rank 1 — HIGH risk, HIGH reward: NeMo API compatibility (`PipelineBuilder`)

The cache-aware streaming Python API (`PipelineBuilder.build_pipeline`,
`ingest_chunk`, `get_partial`, `flush`) is documented only at the example-
script level. Exact method signatures have not been verified against the
25.11 source. If the API differs from our server.py assumptions, the WS
endpoint silently returns empty text or crashes on first audio chunk.

**Mitigation**: Before writing server.py edits, run a 10-line probe:

```bash
docker run --rm --gpus all nvcr.io/nvidia/nemo:25.11 \
  python -c "
from nemo.collections.asr.inference.factory.pipeline_builder import PipelineBuilder
import inspect
print(inspect.signature(PipelineBuilder.build_pipeline))
p = PipelineBuilder.build_pipeline(cfg)
print(dir(p))
"
```

If `ingest_chunk`/`get_partial`/`flush` are absent, inspect the actual method
names and update the diff before any live edit to server.py.

Wall-clock: 20 min (container pull + probe). Blocks all other Phase F work.

### Rank 2 — HIGH risk, HIGH reward: Fish `--compile` RTF regression unknown

We know `.venv-nightly` Triton 3.7 is sm_103a-safe (doc 20). We do NOT know
Fish S2-Pro's RTF under `torch.compile` on B300 with nightly torch. The only
measured number is RTF 2.04 in eager mode. The target is RTF <= 1.0. If the
compiled RTF is still > 1.0 (possible if Fish's decode loop is memory-bandwidth-
bound rather than compute-bound, which torch.compile does not help), this sub-
step delivers nothing.

**Mitigation**: Run the bench on the second Fish instance (port 9201) before
migrating the primary:

```bash
python - <<'EOF'
import requests, time, wave, struct
audio = b'\x00\x00' * 22050  # 1 s silence PCM16
t0 = time.time()
r = requests.post("http://127.0.0.1:9201/v1/tts", json={"text": "fire at the corner of 5th and main"})
print(f"RTF: {(time.time()-t0):.3f} / {len(audio)/32000:.3f}")
EOF
```

Wall-clock: 30 min (second Fish startup + 5 warmup inferences + 10 measured).

### Rank 3 — MEDIUM risk, HIGH reward: NeMo container vs .venv-nightly venv split

Phase D (vLLM) runs inside `.venv-nightly`. Phase F (Nemotron Speech) can run
either inside the NeMo 25.11 Docker container OR as a pip-installed nemo_toolkit
inside `.venv-nightly`. The container path is cleaner (NVIDIA-tested) but adds
Docker dependency to the Parakeet service. The pip-install path is simpler
operationally but risks subtle nemo_toolkit version conflicts with the vLLM
install inside `.venv-nightly`.

**Mitigation**: Use Docker for the NeMo 25.11 service (isolated), expose the
same :9100 port via container `-p 9100:9100`. No venv conflict possible.

```bash
docker run -d --gpus '"device=0"' \
  -p 9100:9100 \
  -e MODEL=nvidia/nemotron-speech-streaming-en-0.6b \
  -e NEMOTRON_CACHE_AWARE=1 \
  -v /opt/prism42/infra/b300/services/parakeet:/app \
  nvcr.io/nvidia/nemo:25.11 \
  python /app/server.py
```

Wall-clock: 30 min first container pull + model download.

### Rank 4 — MEDIUM risk, LOW reward: `torch.load weights_only` break

PyTorch 2.9 (in NeMo 25.11) defaults `torch.load` to `weights_only=True`.
If Parakeet TDT v3 or Nemotron Speech checkpoints include non-tensor objects
(optimizers, config dicts), `from_pretrained` raises `UnpicklingError`.

**Mitigation**: Set `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` in the service
EnvironmentFile before first boot on 25.11. Verify on boot logs before declaring
success.

Wall-clock: 2 min to set, 5 min to verify.

### Rank 5 — LOW risk, MEDIUM reward: B300 Nemotron Speech latency vs H100

NVIDIA's published 24 ms median is for H100. B300 is faster per-SM than H100
on FP8/BF16, but the cache-aware RNNT is likely memory-bandwidth-bound for the
encoder pass (600M params, 8x subsampling). B300 has 8 TB/s vs H100 4 TB/s —
latency should be at most equal to H100 (24 ms) and possibly 15-20 ms. But
this is unverified; we might land at 40-60 ms rather than 24 ms if the
bottleneck is in the RNNT decoder sequential steps rather than the encoder.

**Mitigation**: bench first, claim second. Do not cite 24 ms as a B300 number
until measured.

---

## Migration Recipe

### Phase F sub-steps in execution order

```
F0  API probe (20 min)   — verify PipelineBuilder signatures in NeMo 25.11 container
F1  Container pull (30 min) — pull nvcr.io/nvidia/nemo:25.11 (~20 GB image)
F2  Model download (10 min) — cache nemotron-speech-streaming-en-0.6b via HF CLI
F3  Config YAML (15 min) — author cache_aware_rnnt.yaml + test offline
F4  server.py diff (45 min) — implement cache-aware path behind NEMOTRON_CACHE_AWARE flag
F5  Stage on 9102 (30 min) — run new server on :9102 alongside existing :9100
F6  WS bench (20 min)    — fire 20 utterances at :9102; verify partial/preflight/final events
F7  Latency gate (10 min) — confirm t_stt_ms p50 < 50 ms on :9102
F8  Cutover (5 min)      — redirect worker to :9102; kill :9100; rename :9102 → :9100
F9  Fish compile (45 min) — launch second Fish on :9201 with .venv-nightly + --compile; bench RTF
F10 Fish cutover (5 min)  — if RTF < 1.0: swap primary to :9201; else: document result, close sub-step
```

Total estimated wall-clock: **3.5-4.5 hours** (serial execution of all sub-steps).
Parallel: F0 can overlap with F1; F3 can be authored while F1/F2 run. Realistic
compressed timeline: **2.5-3 hours** if prep work (F0-F3) is done while vLLM
bench runs in Phase D.

### Commands

```bash
# F0 — API probe
docker run --rm --gpus '"device=0"' nvcr.io/nvidia/nemo:25.11 python3 -c "
from nemo.collections.asr.inference.factory.pipeline_builder import PipelineBuilder
import inspect
print('build_pipeline:', inspect.signature(PipelineBuilder.build_pipeline))
# create a test pipeline with known good model
"

# F1 — container pull
docker pull nvcr.io/nvidia/nemo:25.11

# F2 — model download
huggingface-cli download nvidia/nemotron-speech-streaming-en-0.6b \
  --local-dir /opt/prism42/.cache/hf/nemotron-speech-streaming-en-0.6b

# F5 — stage on :9102
docker run -d --name prism42-nemotron-test \
  --gpus '"device=0"' \
  --network host \
  -e MODEL=nvidia/nemotron-speech-streaming-en-0.6b \
  -e PORT=9102 \
  -e NEMOTRON_CACHE_AWARE=1 \
  -e TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
  -v /opt/prism42/infra/b300/services/parakeet:/app \
  -v /opt/prism42/.cache/hf:/root/.cache/huggingface \
  nvcr.io/nvidia/nemo:25.11 \
  python /app/server.py

# F6 — WS bench (Python one-liner)
python3 /opt/prism42/scripts/ws_stt_bench.py \
  --url ws://127.0.0.1:9102/ws \
  --audio /opt/prism42/tests/fixtures/audio/test_16k.wav \
  --n 20 --expect-events partial,preflight,final

# F7 — latency gate check
grep '"type":"final"' /tmp/nemotron-bench.jsonl | \
  python3 -c "import sys,json,statistics; ms=[json.loads(l)['ms'] for l in sys.stdin]; \
  print(f'p50={statistics.median(ms):.0f}ms p95={sorted(ms)[int(len(ms)*0.95)]:.0f}ms')"
# GATE: p50 < 50 ms

# F8 — cutover
sudo systemctl stop prism42-parakeet
docker rename prism42-nemotron-test prism42-nemotron
# update /etc/systemd/system/prism42-parakeet.service ExecStart
# to use new docker run on :9100 with Nemotron Speech

# F9 — Fish compile bench
VENV=/opt/prism42/infra/b300/services/fish-speech/.venv-nightly
$VENV/bin/python tools/api_server.py \
  --listen 127.0.0.1:9201 --device cuda --compile \
  --checkpoint-path checkpoints/s2-pro &
sleep 60  # wait for compile warmup
python3 /opt/prism42/scripts/fish_rtf_bench.py \
  --url http://127.0.0.1:9201 --n 10 --text "fire at the corner of 5th and main"
# GATE: RTF p50 < 1.0
```

### Acceptance gate per sub-step

| Sub-step | Gate | Command |
|---|---|---|
| F0 | `PipelineBuilder.build_pipeline` signature visible, `ingest_chunk`/`get_partial`/`flush` confirmed | Docker probe exits 0 |
| F1 | Image present locally | `docker images \| grep nemo:25.11` |
| F2 | Model dir has `model_config.yaml` + safetensors | `ls /opt/prism42/.cache/hf/nemotron-speech-streaming-en-0.6b/*.safetensors` |
| F3 | `cache_aware_rnnt.yaml` parses; OmegaConf loads without error | `python -c "from omegaconf import OmegaConf; OmegaConf.load('cache_aware_rnnt.yaml')"` |
| F4 | `bash -n server.py` passes; no syntax error | `bash -n server.py && echo OK` |
| F5 | Container up, `/healthz` returns `{"status":"ok","streaming":true}` on :9102 | `curl -s http://127.0.0.1:9102/healthz \| python -m json.tool` |
| F6 | 20/20 WS sessions emit at least one partial, one final; no error events | ws_stt_bench.py exits 0 |
| F7 | t_stt_ms p50 < 50 ms | grep+statistics check above |
| F8 | `/ws` on :9100 routes to Nemotron container; prism42-worker logs no errors for 5 consecutive utterances | `journalctl -u prism42-worker -n 50 \| grep -c error` → 0 |
| F9 | Fish RTF p50 < 1.0 (audio_duration / synthesis_wall > 1.0) | fish_rtf_bench.py output |
| F10 | Primary Fish on :9200 is compile-mode instance; old eager :9200 stopped | `ss -tlnp \| grep 9200`; RTF re-confirmed on warm instance |

### Rollback recipe per sub-step

| Sub-step | Rollback |
|---|---|
| F5/F6/F7 (test fails on :9102) | `docker stop prism42-nemotron-test && docker rm prism42-nemotron-test` — :9100 unaffected |
| F8 (cutover fails) | `sudo systemctl restart prism42-parakeet` (original server.py + Parakeet TDT v3 model) |
| F9/F10 (Fish compile worse) | `kill $(lsof -ti:9201)` — primary Fish on :9200 untouched |
| Container compatibility fail | `NEMOTRON_CACHE_AWARE=0 MODEL=nvidia/parakeet-tdt-0.6b-v3` in EnvironmentFile, restart |

---

## Phase F Feasibility Assessment

### Is Phase F achievable in <= 6 hours?

**Honest answer: yes, if Phase D is already clean and the PipelineBuilder API
probe succeeds. No, if the API probe fails (adds 2-4 hours of NeMo source
spelunking) or Fish compile still fails on .venv-nightly (sub-step closes
as no-win, not a blocker).**

Sub-step breakdown:
- Prep (F0-F3): 1-1.5 hours (can overlap with Phase D bench time)
- Execution (F4-F8, Nemotron swap): 2-2.5 hours
- Fish compile (F9-F10): 1 hour if it works, 15 min to close as no-win if RTF >= 1.0
- Total: 4-5 hours best case, 6-8 hours if API probe discovers method name differences

If the API probe (F0) reveals that `PipelineBuilder` works exactly as documented,
Phase F is a 4-hour effort. If it reveals a different API shape (plausible —
the 25.11 FeatureBuffer addition is new), it becomes a 6-8 hour effort with NeMo
source reading.

**Recommendation**: Run F0 (the API probe, 20 min) the moment Phase D's vLLM
serve goes up, in a spare terminal. If F0 passes, Phase F is greenlit as a
4-hour same-day effort after Phase E acceptance. If F0 fails, Phase F becomes
a multi-day item requiring NeMo source study.

The Fish compile sub-step (F9-F10) is independent of Nemotron and can run in
parallel with F5-F7.

---

## Sources

- nvidia/nemotron-speech-streaming-en-0.6b model card: https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b (fetched 2026-04-24)
- NVIDIA blog — Scaling Real-Time Voice Agents with Cache-Aware Streaming ASR: https://huggingface.co/blog/nvidia/nemotron-speech-asr-scaling-voice-agents (fetched 2026-04-24)
- NeMo Software Component Versions (25.09/25.11 CUDA/PyTorch table): https://docs.nvidia.com/nemo-framework/user-guide/latest/softwarecomponentversions.html (fetched 2026-04-24)
- NeMo Framework Changelog (25.11 ASR additions): https://docs.nvidia.com/nemo-framework/user-guide/latest/changelog.html (fetched 2026-04-24)
- PyTorch Container 25.11 release notes (CUDA 13.0.2.006, PyTorch 2.10.0a0, Python 3.12): https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-25-11.html (fetched 2026-04-24)
- Blackwell B300 vs B200 architecture: docs.nvidia.com/cuda/blackwell-compatibility-guide/; verda.com/blog/nvidia-b200-and-b300-gpu-architecture-and-software-stack
- torch.compile Triton PTXAS sm_103a discovery: docs/livekit-kb/20-blackwell-b300-torch-compile-discovery.md (2026-04-25)
- vLLM co-residency + VRAM budget: docs/livekit-kb/23-vllm-020-nvfp4-b300-deployment.md §3
- Purr plan Phase F framing: docs/livekit-kb/25-b300-purr-migration-plan.md §Phase F
- NVIDIA Open Model License: nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
- NeMo cache-aware streaming example: github.com/NVIDIA-NeMo/NeMo/tree/main/examples/asr/asr_cache_aware_streaming
