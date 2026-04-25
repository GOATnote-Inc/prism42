# Open TTS fallback options — cycle-2 scout

Researched 2026-04-25 (UTC). Read-only reconnaissance of 4 user-specified open-source TTS candidates. Mainline (`TTS_BACKEND=fish` via `agents/livekit/worker.py:408`) is frozen; this file ranks fallbacks for use IF cycle-2d Fish FA patch fails or returns UNSAFE.

Hardware target: Brev B300 pod, sm_103, CUDA 13.0, torch 2.13 nightly, ~190 GB free VRAM, currently co-resident with vLLM 0.20 (Nemotron NVFP4) + Parakeet TDT 0.6B v3 + Fish S2-Pro standalone HTTP service.

## Top recommendation (one line, pre-ranked)

If cycle-2d Fish FA patch fails: **deploy NVIDIA Magpie TTS Multilingual via Riva NIM (`docker run nvcr.io/nim/nvidia/magpie-tts-multilingual:latest`) and switch `worker.py:408` from `FishSpeechTTS` to `livekit.plugins.nvidia.TTS(server="127.0.0.1:50051", use_ssl=False, voice="Magpie-Multilingual.EN-US.Leo")`. Estimated swap-time: 4-8 hours (NIM auth + container pull + TTS plugin path). License: NVIDIA Open Model License (commercial-OK with acceptance). Predicted TTFB: 55-100 ms p50 on B200 published [#2], no B300 number, model card flags one Blackwell limitation [#11].**

## Ranked table

| # | Name | License | Predicted TTFB | Swap-time | Verified-on |
|---|---|---|---|---|---|
| 1 | NVIDIA Magpie TTS Multilingual (Riva NIM) via livekit-plugins-nvidia | NVIDIA Open Model License | 55.1 ms (B200 1-stream, published) [#2] | 4-8 h | B200 sm_100 verified; B300 sm_103 NOT verified; Blackwell limitation flagged [#11] |
| 2 | Kokoro-FastAPI (Kokoro-82M) + livekit-kokoro plugin | Apache 2.0 (model + server) [#7][#8] | ~80 ms (RTX 4090, published) [#9] | 2-4 h | Hopper/Ampere/RTX 40xx verified; Blackwell sm_103 NOT explicitly stated; CUDA 12.8 doc'd |
| 3 | SGLang-Omni Fish S2-Pro (own server) | MIT (server) + Fish Audio Research License (model) [#3][#4] | ~140 ms TTFA / RTF 0.34 (H200, published) [#1] | 8-16 h | H200 verified; B300 sm_103 NOT verified; depends on SGLang 25.11 B300 path |
| 4 | vLLM-Omni Fish S2-Pro | Apache 2.0 (server) + Fish Audio Research License (model) [#5][#6] | None published; assumed similar Fish-class | 6-12 h | sm_100 not explicit; sm_103 not explicit; CUDA 13 binaries shipping |

Tag legend: TTFB = time-to-first-audio-byte at single-stream batch=1.

---

## Per-candidate detail

### #1 — NVIDIA Magpie TTS Multilingual (Riva NIM) via livekit-plugins-nvidia

**Install command**

```bash
# 1. Pull the NIM container (NGC API key required)
docker run -it --rm --name=magpie-tts-multilingual \
  --runtime=nvidia \
  --gpus '"device=0"' \
  --shm-size=8GB \
  -e NGC_API_KEY \
  -e NIM_HTTP_API_PORT=9000 \
  -e NIM_GRPC_API_PORT=50051 \
  -p 9000:9000 \
  -p 50051:50051 \
  nvcr.io/nim/nvidia/magpie-tts-multilingual:latest
# Verbatim from [#10].

# 2. Install LiveKit nvidia plugin in the worker venv
uv add "livekit-agents[nvidia]~=1.4"
# Verbatim from [#13].
```

**Model + license**

- Weights: `nvidia/magpie_tts_multilingual_357m` on HF [#15]; container at `nvcr.io/nim/nvidia/magpie-tts-multilingual:latest` [#10][#11].
- License: **NVIDIA Open Model License Agreement** [#15]. Permissive but NOT BSD/Apache — requires explicit acceptance and downstream-distribution rules. Acceptable for commercial / hosted-demo use after click-through.
- Architecture: 357M params, causal transformer encoder (6L) + decoder (12L), multi-codebook prediction [#15].

**Expected GPU memory**

From NIM Speech support matrix [#11]:
- batch_size=8: **10.87 GB**
- batch_size=32: **31.55 GB**
- batch_size=64: **60.224 GB**

For 1 voice session (batch=1 in our config), expect ~6-10 GB. Co-residency with current 88/275 GB stack: easily fits — replaces Fish's ~20 GB and reduces footprint.

**Minimal smoke command**

```bash
# 1. Health check (run after container start)
curl -X 'GET' 'http://localhost:9000/v1/health/ready'
# Verbatim from [#10].

# 2. Synthesize a test phrase (gRPC client, takes ~10s end-to-end with audio file dump)
python3 -c "
import grpc, riva.client
auth = riva.client.Auth(uri='localhost:50051', use_ssl=False)
tts = riva.client.SpeechSynthesisService(auth)
resp = tts.synthesize('Stay on the line, help is on the way.',
                      voice_name='Magpie-Multilingual.EN-US.Leo',
                      language_code='en-US',
                      sample_rate_hz=16000)
open('/tmp/magpie_smoke.wav','wb').write(resp.audio)
print('OK bytes=', len(resp.audio))
"
# Pattern from [#13][#14] cross-referenced with NVIDIA Riva client docs.

# 3. (Optional, fast) HTTP/REST smoke
curl -X POST http://localhost:9000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Stay on the line, help is on the way.","voice":"Magpie-Multilingual.EN-US.Leo","model":"magpie-tts-multilingual"}' \
  --output /tmp/magpie_smoke.wav
# OpenAI-compatible endpoint pattern; confirm exact path on the running NIM /v1 surface.

# 4. Audio sanity (durable check)
file /tmp/magpie_smoke.wav   # Should report RIFF wav, 16000 Hz
soxi /tmp/magpie_smoke.wav   # Reports sample-rate, duration > 0

# 5. Plugin-level smoke (LiveKit context)
python3 -c "
from livekit.plugins import nvidia
tts = nvidia.TTS(server='127.0.0.1:50051', use_ssl=False,
                 voice='Magpie-Multilingual.EN-US.Leo', language_code='en-US')
print('voices:', tts.list_voices()[:3])
"
```

**LiveKit integration delta**

Surgical edit to `agents/livekit/worker.py` around `worker.py:407-409`:

```python
# Before (worker.py:408):
else:
    _tts = FishSpeechTTS(FishSpeechOptions())
    log.info("tts.backend", backend="fish", model="s2-pro")

# After — add a new branch above the else:
elif _tts_backend == "magpie":
    from livekit.plugins import nvidia  # noqa: PLC0415
    _tts = nvidia.TTS(
        server=os.environ.get("NVIDIA_RIVA_SERVER", "127.0.0.1:50051"),
        use_ssl=False,
        voice=os.environ.get("MAGPIE_VOICE", "Magpie-Multilingual.EN-US.Leo"),
        language_code="en-US",
    )
    log.info("tts.backend", backend="magpie", model="magpie-tts-multilingual-357m")
```

Plugin already exists on PyPI (`livekit-plugins-nvidia`, also in `livekit-agents[nvidia]~=1.4`) [#13][#14]. TTS class signature verbatim from [#13]:

```python
class TTS(*, server: str = 'grpc.nvcf.nvidia.com:443',
          voice: str = 'Magpie-Multilingual.EN-US.Leo',
          function_id: str = '877104f7-e885-42b9-8de8-f6e4c6303969',
          language_code: str = 'en-US',
          use_ssl: bool = True,
          api_key: str | None = None)
# sample_rate=16000, num_channels=1, encoding=LINEAR_PCM
```

No custom plugin shim needed — LiveKit ships it.

**Estimated swap-time: 4-8 hours**
- 30 min: NGC API key + accept NVIDIA Open Model License terms (interactive, gated by user).
- 60-180 min: First-time Magpie NIM container pull (~25-40 GB compressed) over Brev egress.
- 30 min: `worker.py` edit + `uv add livekit-agents[nvidia]` + worker restart.
- 60 min: Smoke test (steps 1-5 above) + 10-turn synthetic-caller bench (`agents/livekit/synthetic_caller.py`).
- 60-90 min: Buffer for unblocked-port debugging or use_ssl/grpc-cred mismatch.
- **Risk multiplier:** if Magpie TTS Multilingual hits the documented "not supported on Blackwell platform" limitation [#11][#16] on B300 sm_103, fall back to **Magpie TTS Flow** or **Magpie TTS Zeroshot** variants (offline / cloning) — but those don't stream and are not 1:1 swaps. Build the safety-net variant fallback into the runbook.

**Predicted TTFB**

Published B200 sm_100 1-stream **first-chunk 55.1 ms** [#2]. H100 sm_90 1-stream **70.0 ms**. **No B300 sm_103 number published as of 2026-04-25** [findings/voice/nvidia-tts-patterns.md]. The B200→H100 gap is ~21% TTFB advantage on the smaller-model Magpie workload that does not saturate either chip — so B300 may be similar to B200, not faster (B300's gains are mostly memory/FP4-throughput). Conservative range for B300: **55-100 ms p50, 100-200 ms p95.** Verified-on B200 sm_100, claimed-unverified-on B300 sm_103.

**Co-residency cost**

**Replaces Fish entirely.** Memory budget post-swap: vLLM ~57 GB + Parakeet ~12 GB + Magpie ~10 GB = **~80 GB / 275 GB used**. Down from current 88 GB (Fish ~20 GB swap to Magpie ~10 GB). MLOPart partitioning (per `findings/voice/coresidency` and `nvidia-tts-patterns.md` P2/P4 patterns) becomes optional — Magpie is small enough to share unpartitioned. If we keep Fish running for A/B comparison during transition: 88 + 10 = 98 GB, still well within 275 GB.

**Sources for this candidate**

[#2] NVIDIA NIM Speech TTS Performance docs (B200 first-chunk 55.1 ms, methodology = 20 iterations × 10 LJSpeech inputs × 3 trials). [#10] NVIDIA NIM TTS deploy doc. [#11] NIM Speech support matrix. [#13] LiveKit nvidia plugin TTS class signature. [#14] LiveKit NVIDIA TTS plugin guide. [#15] HuggingFace nvidia/magpie_tts_multilingual_357m. [#16] Search aggregation flagging "Magpie TTS Multilingual not supported on Blackwell" — third-party claim, not in NVIDIA's canonical [#11], but worth a sanity check on B300 specifically.

---

### #2 — Kokoro-FastAPI (Kokoro-82M) + livekit-kokoro plugin

**Install command**

```bash
# 1. Run Kokoro-FastAPI in Docker (GPU variant) on the B300 pod
docker run --gpus all -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-gpu:latest
# Verbatim from [#7].

# 2. Install the livekit-kokoro plugin shim (community, not first-party LiveKit)
pip install openai httpx
git clone https://github.com/taresh18/livekit-kokoro.git
cp livekit-kokoro/kokoro_plugin.py agents/livekit/
# Verbatim install line from [#9].
```

**Model + license**

- Weights: `hexgrad/Kokoro-82M` on HF [#8]. **82 million parameters** verbatim from [#8].
- License: **Apache 2.0** for both weights and Kokoro-FastAPI server. Verbatim quotes:
  - HF model card: *"With Apache-licensed weights, Kokoro can be deployed anywhere from production environments to personal projects."* [#8]
  - Kokoro-FastAPI repo: *"This project is licensed under the Apache License 2.0"* [#7]
- Architecture: StyleTTS 2 + ISTFTNet (decoder-only, no diffusion) [#8].
- 8 languages, 54 voices in v1.0 [#8].

**Expected GPU memory**

**Total GPU memory during inference (including CUDA kernels and buffers): 2-3 GB.** Search-summary citation, multiple sources [#9][#17]. Tiny — fits trivially alongside vLLM + Parakeet without partitioning. RTF on A100: ~0.03 [#17] — 33× faster than realtime. Should easily run on B300.

**Minimal smoke command**

```bash
# 1. Health check
curl http://localhost:8880/health
# Or: curl http://localhost:8880/v1/models

# 2. Synthesize via OpenAI-compatible endpoint
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Stay on the line, help is on the way.","voice":"af_heart","response_format":"wav"}' \
  --output /tmp/kokoro_smoke.wav
# OpenAI-compatible Speech endpoint verbatim from [#7].

# 3. Audio sanity
file /tmp/kokoro_smoke.wav    # RIFF wav
soxi /tmp/kokoro_smoke.wav    # duration > 0, sample-rate

# 4. Plugin-level smoke (using community livekit-kokoro)
python3 -c "
from kokoro_plugin import KokoroTTS
tts = KokoroTTS(base_url='http://localhost:8880', api_key='NULL', voice='af_heart', speed=1.0)
print('OK')
"
# Verbatim signature from [#9].

# 5. End-to-end short-utterance check
time curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hi.","voice":"af_heart"}' \
  --output /tmp/kokoro_tiny.wav
# Should complete in <500 ms wall-clock for the curl command on a warm server.
```

**LiveKit integration delta**

Edit to `agents/livekit/worker.py` around `worker.py:407-409`:

```python
# Add elif branch:
elif _tts_backend == "kokoro":
    from kokoro_plugin import KokoroTTS  # community plugin, vendored under agents/livekit/  # noqa: PLC0415
    _tts = KokoroTTS(
        base_url=os.environ.get("KOKORO_URL", "http://127.0.0.1:8880"),
        api_key="NULL",
        voice=os.environ.get("KOKORO_VOICE", "af_heart"),
        speed=1.0,
    )
    log.info("tts.backend", backend="kokoro", model="kokoro-82m")
```

The plugin is **community, not first-party LiveKit** [#9]. The license of the plugin shim itself is not stated in the README we fetched [#9] — **assume MIT-or-Apache and verify before commercial deploy**, OR write a 50-line in-house shim using `livekit-plugins-openai` against Kokoro-FastAPI's OpenAI endpoint. Either path is small.

**Estimated swap-time: 2-4 hours**
- 15 min: Docker pull (Kokoro-FastAPI image is small, ~3-5 GB).
- 30 min: Vendor `kokoro_plugin.py` into `agents/livekit/` + license check.
- 30 min: `worker.py` edit + worker restart.
- 60 min: Smoke test + 10-turn synthetic-caller bench.
- 60 min: Buffer for voice-quality A/B (Kokoro has 54 voices; finding the right professional female PSAP voice may need iteration).

**Predicted TTFB**

Published **~80 ms TTFB on RTX 4090** [#9] verbatim: *"~80ms time-to-first-byte (TTFB) on RTX 4090"*. RTX 4090 is sm_89 (Ada Lovelace), not Blackwell. B300 sm_103 has ~6-8× the FP16 compute and ~2× memory bandwidth vs RTX 4090 — Kokoro is 82M params and not compute-bound, so expect **~50-150 ms p50 on B300** (likely closer to 80 ms as the model is so small that the additional compute is unused). Verified-on RTX 4090 / Hopper-class consumer; claimed-unverified-on B300 sm_103.

**Co-residency cost**

**Replaces Fish entirely OR runs alongside.** Kokoro at 2-3 GB is so small it can sit beside Fish during A/B without contention. Memory budget: vLLM ~57 GB + Parakeet ~12 GB + Kokoro ~3 GB = **~72 GB / 275 GB.** This is the safest co-residency profile of all 4 candidates.

**Sources for this candidate**

[#7] github.com/remsky/Kokoro-FastAPI (Docker GPU command, Apache 2.0 license, OpenAI-compatible endpoint). [#8] huggingface.co/hexgrad/Kokoro-82M (weights, Apache 2.0, 82M params, StyleTTS 2 architecture). [#9] github.com/taresh18/livekit-kokoro (community LiveKit plugin shim, ~80 ms TTFB on RTX 4090). [#17] Spheron deploy guide aggregation citing A100 RTF 0.03 and 2-3 GB memory.

---

### #3 — SGLang-Omni Fish S2-Pro (own server)

**Install command**

```bash
# 1. Clone SGLang-Omni and install (B300 pod, CUDA 13.0)
git clone https://github.com/sgl-project/sglang-omni.git
cd sglang-omni
uv pip install -e .
# Pattern; verify against the docs/Get-Started page in the repo (we could not fetch the
# specific install page in research; sglang_omni/models/fishaudio_s2_pro/README.md
# referenced "TTS Model Usage" doc separately) [#1][#3].

# 2. Pull Fish S2-Pro weights (model is fishaudio/s2-pro on HF)
huggingface-cli download fishaudio/s2-pro --local-dir /opt/models/s2-pro

# 3. Start the SGLang-Omni TTS server
python -m sglang_omni.serve --model-path /opt/models/s2-pro \
  --tp 1 --port 9210 --host 0.0.0.0
# Pattern; specific flags TBD per repo docs (couldn't fetch live).
```

**Model + license**

- Server license: **MIT** (sglang-omni repo) [#3] verbatim: *"MIT license"*.
- Model license: **Fish Audio Research License** for `fishaudio/s2-pro` [#4][#18] verbatim: *"This model is licensed under the Fish Audio Research License. Research and non-commercial use is permitted free of charge. Commercial use requires a separate license from Fish Audio — contact business@fish.audio."*
- **License flag for hosted demo:** This is the same model as our current Fish deployment. If our current commercial-use story already covers Fish S2-Pro for the demo, SGLang-Omni reuses that license. If our current Fish deployment is research-mode, this candidate is research-mode too. **Confirm with `findings/voice/fish-fork-analysis/` whether the prism42 deploy has commercial license or research-license posture.** This is a P0 blocker for hosted demo at `www.thegoatnote.com/prism42`.

**Expected GPU memory**

Not published in research [#1][#3]. Fish S2-Pro is **5B parameters (4B Slow AR + 400M Fast AR)** [#4]. Standard footprint should be ~12-20 GB at BF16. Probably comparable to our current Fish ~20 GB measurement.

**Minimal smoke command**

```bash
# 1. Health check
curl http://localhost:9210/health
# (Pattern — exact endpoint TBD per repo docs)

# 2. Synthesize (assuming OpenAI-compatible endpoint)
curl -X POST http://localhost:9210/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"fishaudio/s2-pro","input":"Stay on the line, help is on the way.","voice":"default"}' \
  --output /tmp/sglang_fish_smoke.wav

# 3. Audio sanity
file /tmp/sglang_fish_smoke.wav
soxi /tmp/sglang_fish_smoke.wav

# 4. Latency probe
time curl -X POST http://localhost:9210/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"fishaudio/s2-pro","input":"Hi.","voice":"default"}' \
  --output /tmp/sglang_fish_tiny.wav

# 5. SDK smoke (if SGLang-Omni exposes a Python client)
python3 -c "
import sglang_omni
client = sglang_omni.Client('http://localhost:9210')
audio = client.tts('Hello', voice='default')
print('OK bytes=', len(audio))
"
```

**LiveKit integration delta**

Either:
1. **Reuse the existing FishSpeechTTS** in `agents/livekit/fish_speech_tts.py` (point `FISH_SPEECH_URL` env var at the SGLang-Omni server endpoint). Zero plugin work IF the SGLang-Omni HTTP shape matches our current Fish HTTP shape. Worker edit: just change `FISH_SPEECH_URL` env in `prism42-fish.service`.
2. **Use livekit-plugins-openai TTS** if SGLang-Omni exposes the OpenAI `/v1/audio/speech` endpoint — write a 30-line subclass in `worker.py` to point at the SGLang-Omni URL.

Surgical edit at `worker.py:407-409`:

```python
elif _tts_backend == "sglang_fish":
    # Reuse FishSpeechTTS but point at SGLang-Omni server
    _tts = FishSpeechTTS(FishSpeechOptions(
        base_url=os.environ.get("SGLANG_FISH_URL", "http://127.0.0.1:9210"),
        voice=os.environ.get("SGLANG_FISH_VOICE", "default"),
    ))
    log.info("tts.backend", backend="sglang_fish", model="s2-pro")
```

The FishSpeechTTS shim already exists at `agents/livekit/fish_speech_tts.py`; verify HTTP-API parity between our current Fish service and SGLang-Omni's serve surface before flipping. If they diverge, a 30-50 line OpenAI-compatible adapter is needed.

**Estimated swap-time: 8-16 hours**
- 60 min: Repo clone + dependency install on B300 pod (CUDA 13.0, torch 2.13).
- 60-180 min: Possible build-from-source for SGLang-Omni on sm_103 (we don't have a published Blackwell wheel confirmation [#3]). If pre-built wheels exist, 30 min; if compile-from-source, 2-3 hours.
- 30 min: Pull Fish S2-Pro weights (~10-15 GB).
- 60-180 min: First-run SGLang Mamba/CUDA-graph capture (analogous to our vLLM 14-min boot per `findings/b300_bench/nvidia-research/expert-wiring.md` §B1).
- 60 min: HTTP-API parity check OR OpenAI-compat adapter shim.
- 60 min: 10-turn bench.
- 120 min: Buffer for SGLang-Omni-on-B300-sm_103 unknowns. SGLang 25.11 supports B300/sm_103 broadly per `CLAUDE.md` recent-best-practice notes, but **SGLang-Omni** is a different package and B300 support is not explicitly documented [#3].

**Predicted TTFB**

Published **H200 (sm_90, Hopper) numbers** [#1]:
- *"RTF of 0.34 and 63.3 tok/s on single H200 GPU at single batch size"* [#1] — verbatim from sglang_omni README.
- *"TTFT (~18ms) and Time-to-First-Audio (~140ms)"* [#1].
- A second source: *"SGLang Streaming achieves RTF 0.195, TTFA ~100ms, and 3000+ tokens/s on a single H200"* [#1] — different test-config numbers, probably the same engine measured under different conditions.

H200 → B300 delta is comparable on a model this size — same TTFA range expected. **Predicted: 100-200 ms p50 on B300.** Verified-on H200 sm_90; claimed-unverified-on B300 sm_103.

**Co-residency cost**

Same as current Fish — replaces Fish entirely. Memory budget unchanged from current state (~88 GB / 275 GB). No co-residency upside from the swap.

**Sources for this candidate**

[#1] sgl-project/sglang-omni README (RTF 0.34 H200, TTFA 140 ms). [#3] github.com/sgl-project/sglang-omni (MIT license). [#4] huggingface.co/fishaudio/s2-pro (Fish Audio Research License). [#18] WebSearch confirmation of Fish Audio Research License terms.

---

### #4 — vLLM-Omni Fish S2-Pro

**Install command**

```bash
# 1. Pre-built wheel install (CUDA 13 binaries shipping in v0.19.x [#5])
uv pip install vllm-omni
# Verbatim from [#5]. May need to add 'vllm-omni[demo]' for full deps.

# 2. Pull Fish S2-Pro weights (HF-hosted)
huggingface-cli download fishaudio/s2-pro --local-dir /opt/models/s2-pro

# 3. Start the TTS server
vllm serve fishaudio/s2-pro --omni --port 8091
# Verbatim from [#6].
```

**Model + license**

- Server license: **Apache 2.0** (vllm-omni repo) [#5] verbatim: *"Apache License 2.0, as found in the LICENSE file."*
- Model license: **Fish Audio Research License** [#4][#18] (same as #3 — research-only by default; commercial requires Fish Audio sales contact).
- **Same commercial-license blocker as #3** for hosted-demo posture.

**Expected GPU memory**

Not explicitly documented in vllm-omni docs [#6]. Fish S2-Pro = 5B params at BF16 ≈ 12-20 GB. vllm-omni's GPU-memory-utilization knob (default 0.5 for stages [#6]) means it would default-claim ~138 GB on a 275 GB B300 unless explicitly capped — **MUST set `--gpu-memory-utilization 0.10` to ~28 GB cap** for safe co-residency.

**Minimal smoke command**

```bash
# 1. Health check
curl http://localhost:8091/health
# (Standard vLLM health endpoint)

# 2. Smoke synthesis via OpenAI-compatible endpoint
curl -X POST http://localhost:8091/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"fishaudio/s2-pro","input":"Stay on the line, help is on the way.","voice":"default"}' \
  --output /tmp/vllm_omni_smoke.wav
# Endpoint shape verbatim from [#6]: POST /v1/audio/speech with Content-Type: application/json.

# 3. Audio sanity (verify 44.1 kHz Fish output)
file /tmp/vllm_omni_smoke.wav
soxi /tmp/vllm_omni_smoke.wav   # Should report 44100 Hz per [#6]: "Fish Speech S2 Pro outputs at 44.1 kHz"

# 4. Latency probe
time curl -X POST http://localhost:8091/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"fishaudio/s2-pro","input":"Hi."}' --output /tmp/vllm_omni_tiny.wav

# 5. Voice-clone smoke (vllm-omni supports voice cloning via reference audio per [#5])
# (Endpoint shape TBD; consult vllm-omni docs)
```

**LiveKit integration delta**

vllm-omni exposes the **OpenAI `/v1/audio/speech` endpoint** [#6]. The cleanest LiveKit integration is via livekit-plugins-openai-compatible TTS:

```python
elif _tts_backend == "vllm_omni_fish":
    # vllm-omni exposes OpenAI /v1/audio/speech — use FishSpeechTTS with new URL
    _tts = FishSpeechTTS(FishSpeechOptions(
        base_url=os.environ.get("VLLM_OMNI_URL", "http://127.0.0.1:8091"),
        voice=os.environ.get("VLLM_OMNI_VOICE", "default"),
    ))
    log.info("tts.backend", backend="vllm_omni_fish", model="s2-pro")
```

Same FishSpeechTTS shim as #3 if the HTTP shape matches our current Fish service. If not, write a 30-line OpenAI-compatible TTS adapter.

**Estimated swap-time: 6-12 hours**
- 30 min: `pip install vllm-omni`. Wheel install if Blackwell sm_103 is supported by the prebuilt; otherwise compile-from-source 90-180 min.
- 30 min: Fish S2-Pro weights pull.
- 30 min: First-run server start; vLLM CUDA-graph capture (mitigated by `--cuda-graph-sizes 1 2 4 8` per `findings/b300_bench/nvidia-research/expert-wiring.md` §B1).
- 60 min: HTTP-API verification + adapter shim.
- 60 min: 10-turn bench.
- 120 min: Buffer for **B300 sm_103 not explicitly listed** in vLLM-Omni docs [#19] (only sm_70+ generic compute capability mentioned; no explicit Blackwell ack in the GPU install page we fetched). The base vLLM-Omni release notes do mention CUDA 13 binaries and Blackwell SM120 fixes, but no clean B300 sm_103 confirmation.

**Predicted TTFB**

**No published TTFB numbers for vLLM-Omni Fish S2-Pro on any hardware** [#6][#19]. By analogy to SGLang-Omni's ~140 ms TTFA on H200, expect similar or slightly worse. **Predicted: 150-300 ms p50 on B300, claimed-unverified.** vLLM-Omni's TTS path is newer than SGLang's per [#5][#6] and may have less optimization. Tag: claimed-unverified-on-Blackwell, no published baseline anywhere.

**Co-residency cost**

Replaces Fish entirely. Memory budget similar to current state.

**Sources for this candidate**

[#5] github.com/vllm-project/vllm-omni (Apache 2.0, v0.19.0rc1 with CUDA 13 binaries, B300/sm_103 not explicit). [#6] vllm-omni Speech API doc (Fish S2-Pro serving command, 44.1 kHz output, OpenAI `/v1/audio/speech` endpoint). [#19] vllm-omni Blackwell GPU install doc (sm_70+ compute capability mentioned; Blackwell not explicit on install page).

---

## What does NOT exist as published

Things we searched for and could NOT find:

1. **A first-party `livekit-plugins-nvidia-tts` package separate from STT.** Initial assumption was wrong — `livekit-plugins-nvidia` is a single package that **includes both STT and TTS** [#13][#14]. The TTS class supports Magpie voices and self-hosted Riva NIM endpoints out of the box. Re-confirms the per-`findings/voice/nvidia-tts-patterns.md` claim that "no `livekit-plugins-nvidia-tts` exists" needs an update — the TTS support is in the unified plugin.

2. **B300 sm_103 published TTFB benchmark for any production-grade TTS.** Across all 4 candidates: every published number is on H100 sm_90, H200 sm_90, B200 sm_100, RTX 4090 sm_89, or DGX Spark sm_121. No B300 sm_103 datacenter TTS benchmarks exist as of 2026-04-25. [Confirms `findings/voice/nvidia-tts-patterns.md` closing note.]

3. **Magpie TTS NVIDIA Open Model License — the canonical `support-matrix/tts.html` page does NOT list B300 in its hardware enumeration.** The matrix lists: A30, A100, H100, A2/A10/A16/A40, L4/L40/RTX 40xx, RTX 50xx, "Blackwell RTX 60xx", DGX Spark — but **B200 and B300 datacenter are NOT explicitly enumerated** [#11]. NVIDIA's NIM perf docs DO publish B200 numbers [#2], so Magpie runs on B200; B300 status is a known unknown.

4. **A direct comparison of any two of these four candidates on identical hardware.** Each vendor self-reports on their preferred hardware; cross-vendor head-to-head benchmarks do not exist.

5. **Verified-on-Blackwell-sm_103 release for SGLang-Omni or vLLM-Omni.** Both projects support generic Blackwell, but B300 sm_103 specific call-outs are absent from the GPU install / release-notes pages we fetched [#3][#5][#19].

6. **Whether the LiveKit nvidia plugin's `synthesize_online` method streams TTS audio progressively or returns a single buffer.** Verbatim from [#13] only that `LINEAR_PCM` encoding and `sample_rate=16000` are used; chunk granularity not documented. Empirical test required.

7. **A community-maintained MIT/Apache-licensed commercial-friendly Fish-class TTS server.** Fish S2-Pro itself is research-license-only [#4][#18]. SGLang-Omni and vLLM-Omni servers are MIT/Apache, but the **model weights** they serve carry the Fish Audio Research License. This means **all three Fish-class candidates (#1's Magpie is the exception) are commercial-blocked unless Fish Audio is contacted for a commercial license.**

---

## License-cleanliness summary (for hosted-demo posture)

| Candidate | Server license | Model license | Hosted-demo OK? |
|---|---|---|---|
| #1 Magpie via Riva NIM | NIM container EULA | NVIDIA Open Model License | **Yes** with click-through acceptance. NVIDIA OML permits commercial use with attribution. |
| #2 Kokoro-FastAPI | Apache 2.0 | Apache 2.0 (Kokoro-82M weights) | **Yes — cleanest of the four.** Apache 2.0 end-to-end. |
| #3 SGLang-Omni Fish S2-Pro | MIT (server) | Fish Audio Research License (model) | **No** without Fish Audio commercial license. |
| #4 vLLM-Omni Fish S2-Pro | Apache 2.0 (server) | Fish Audio Research License (model) | **No** without Fish Audio commercial license. |

**This is why the ranking is #1 → #2 → #3 → #4 even though #2's Kokoro has the cleanest license:** the user's stated criterion #1 ("license-clean for hosted demo, commercial-OK") favors #2 in isolation, but criterion #5 ("B300 sm_103 verified vs claimed-unverified") favors #1 (Magpie has more datacenter Blackwell vetting via NIM). #1 is ranked first because **license-clean AND has the most-published-on-Blackwell pedigree** even though #2 has slightly cleaner license. If the demo-posture committee rejects NVIDIA's OML, #2 is the immediate fallback.

---

## Sources

All retrieval dates 2026-04-25 (UTC).

1. **github.com/sgl-project/sglang-omni — fishaudio_s2_pro README.** https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md — RTF 0.34 / 63.3 tok/s H200 single batch; TTFT ~18 ms / TTFA ~140 ms. Second-source aggregation cites RTF 0.195 / TTFA ~100 ms / 3000+ tok/s on H200.

2. **NVIDIA Speech NIM Microservices — TTS NIM Performance.** https://docs.nvidia.com/nim/speech/latest/reference/performances/tts/performance.html — Magpie TTS Multilingual B200 sm_100 1-stream 55.1 ms first-chunk; H100 70.0 ms; B200 64-stream 184.15 ms; methodology = 20 iter × 10 LJSpeech × 3 trials. Last updated 2026-04-20.

3. **github.com/sgl-project/sglang-omni — root README.** https://github.com/sgl-project/sglang-omni — MIT license verbatim.

4. **huggingface.co/fishaudio/s2-pro — model card.** https://huggingface.co/fishaudio/s2-pro — Fish Audio Research License verbatim. 5B params (4B Slow AR + 400M Fast AR). BF16 safetensors.

5. **github.com/vllm-project/vllm-omni — releases.** https://github.com/vllm-project/vllm-omni/releases — Apache 2.0. v0.19.0rc1 (2026-04-04), v0.18.0 (2026-03-28). CUDA 13.0-compatible binaries by default in v0.19.x. Fish Speech S2 Pro online serving + voice cloning released in v0.18.0.

6. **vLLM-Omni docs — Speech API.** https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/speech_api/ — `vllm serve fishaudio/s2-pro --omni --port 8091`. POST /v1/audio/speech endpoint. Fish output 44.1 kHz; Qwen3-TTS output 24 kHz. Output formats: wav, mp3, flac, pcm, aac, opus.

7. **github.com/remsky/Kokoro-FastAPI.** https://github.com/remsky/Kokoro-FastAPI — Apache 2.0 verbatim. Docker GPU command `docker run --gpus all -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-gpu:latest`. OpenAI-compatible /v1/audio/speech endpoint. CUDA 12.8 support documented.

8. **huggingface.co/hexgrad/Kokoro-82M.** https://huggingface.co/hexgrad/Kokoro-82M — Apache 2.0 verbatim. 82M params. StyleTTS 2 + ISTFTNet architecture. 8 languages, 54 voices in v1.0. Training cost ~$1,000.

9. **github.com/taresh18/livekit-kokoro — community LiveKit Kokoro plugin.** https://github.com/taresh18/livekit-kokoro — TTFB ~80 ms on RTX 4090 verbatim. Uses Kokoro-FastAPI as backend. Plugin license not stated in fetched README.

10. **NVIDIA NIM Speech — Deploy and Run TTS Microservice.** https://docs.nvidia.com/nim/speech/latest/tts/deploy-tts-model.html — Docker run command verbatim. Ports 9000 (HTTP) / 50051 (gRPC). Health check `curl http://localhost:9000/v1/health/ready`. NIM container at nvcr.io/nim/nvidia/$CONTAINER_ID:latest.

11. **NVIDIA NIM Speech TTS Support Matrix.** https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/tts.html — Magpie batch-size memory: 8→10.87 GB, 32→31.55 GB, 64→60.224 GB. Hardware enumeration: A30/A100, H100, A2/A10/A16/A40, L4/L40/RTX 40xx, RTX 50xx, "Blackwell RTX 60xx", DGX Spark — **B200/B300 datacenter not explicitly enumerated.**

12. *(reserved)*

13. **LiveKit nvidia plugin API doc.** https://docs.livekit.io/reference/python/v1/livekit/plugins/nvidia/index.html — TTS class signature with server / voice / function_id / language_code / use_ssl / api_key params. sample_rate=16000, num_channels=1, encoding=LINEAR_PCM. Default voice "Magpie-Multilingual.EN-US.Leo".

14. **LiveKit NVIDIA Riva TTS plugin guide.** https://docs.livekit.io/agents/models/tts/plugins/nvidia/ — `uv add "livekit-agents[nvidia]~=1.4"`. Self-host: `server="local-host:50051"` + `use_ssl=False`. Supports list_voices() method.

15. **HuggingFace nvidia/magpie_tts_multilingual_357m.** https://huggingface.co/nvidia/magpie_tts_multilingual_357m — 357M params. Causal transformer 6L encoder + 12L decoder. Multi-codebook prediction. NeMo Framework 25.11 runtime. NVIDIA Open Model License Agreement. Magpie v2602 released 2026-03-03 with Hindi/Japanese.

16. **WebSearch aggregation — "Magpie TTS Multilingual not supported on Blackwell platform"** flagged in third-party summaries; not in canonical NVIDIA support matrix [#11]. Treat as outdated/incorrect, BUT verify on B300 specifically before commit.

17. **Spheron deploy guide for open-source TTS on GPU cloud (2026).** https://www.spheron.network/blog/deploy-open-source-tts-gpu-cloud-2026/ — Kokoro RTF ~0.03 on A100, 2-3 GB GPU memory.

18. **WebSearch — Fish Audio Research License confirmation.** https://huggingface.co/fishaudio/s2-pro/blob/main/LICENSE.md — Fish Audio Research License terms; commercial use requires separate license from Fish Audio (business@fish.audio).

19. **vLLM-Omni GPU installation doc.** https://docs.vllm.ai/projects/vllm-omni/en/latest/getting_started/installation/gpu/ — `uv pip install vllm-omni`. CUDA 13.0 binaries default in v0.19.0. Compute capability 7.0 or higher mentioned (V100/T4/RTX20xx/A100/L4/H100); Blackwell sm_100/sm_103 NOT explicitly enumerated on this install page.

20. **Cross-reference: findings/voice/nvidia-tts-patterns.md (this repo).** Confirmed B200 sm_100 verified data points; B300 sm_103 published-benchmark gap.

21. **Cross-reference: findings/b300_bench/nvidia-research/expert-wiring.md (this repo).** vLLM 14-min CUDA-graph capture mitigation pattern (B1) applies to vLLM-Omni Fish S2-Pro candidate as well — same engine code.
