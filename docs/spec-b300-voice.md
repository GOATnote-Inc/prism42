# Spec — B300-voice: Blackwell Ultra safety augmentations to prism42

**Status:** SPECIFICATION (not implementation). Exit criteria: a build-agent can read this and produce working code without guessing.
**Branch:** `spec/b300-voice`. **Public URL on promote:** `www.thegoatnote.com/prism42-b300` (separate from `/prism42` to preserve the existing demo's continuity claim while the B300 path matures).
**Superset of:** `docs/anthropic-elevenlabs-agent-bp-2026-04-21.md` §5 (decode-latency budget, 2026-04-23).
**Depends on:** GEDP v0.1 (`docs/dispatch-protocol-v0.1.md`), 20-agent topology (`docs/agents/topology.md`), safety preambles SP-001..SP-010 (`docs/safety-preambles.md`), red-team v0.1 (`corpus/red-team/psap-fixtures-v0.1.yaml`), structured-JSON gate (`schemas/psap-turn.schema.json`).
**Author date:** 2026-04-23.

---

## 1. Context

### 1.1 Why a separate spec + URL

The `/prism42` demo ships with a **continuity claim** (`README.md` L47–57): the agents a visitor interacts with are the same ones whose correctness, performance, and clinical-reasoning lift were measured in stages 1–3. That claim is the credibility mechanism. It must survive introducing new hardware.

B300 Blackwell Ultra introduces augmentations that **cannot** run on the current stack (H100 fa3, hosted GPT-5.5 rubric) — they require 288 GB HBM3e, 14 PFLOPS FP4, and sm_103 tensor-memory primitives. Adding them to `/prism42` would either (a) change the demo silently, breaking continuity, or (b) require disclaiming half the scenarios, diluting the evidence stack.

**Resolution**: `/prism42-b300` is a sibling demo that shares corpus, safety preambles, GEDP v0.1, and the 42-scenario red-team fixture, but ships with the B300-only augmentations (§5) enabled. `/prism42` remains the conservative anchor until the B300 augmentations clear the rubric §3 integration gate.

### 1.2 What changes vs what doesn't

- **Changes** (§5): rubric grader moves local and goes sub-second; OHCA classifier becomes continuous on-device audio stream; a second clinical-reasoning model runs concurrently and is reconciled in real-time by the team coordinator.
- **Does not change** (§7): GEDP v0.1, 20-agent topology, 42-scenario red-team fixture, structured-JSON output gate, SP-001..SP-010 preambles, continuity claim at `/prism42`.

### 1.3 What's shippable today vs `pending`

- **Shippable**: rubric grader on local Llama-3-70B NVFP4 (vLLM 0.14.1 + FlashInfer FP4 MoE), Parakeet-RNNT streaming STT, Opus 4.7 + GPT-5.5 hosted-API dialectic.
- **`pending`**: FlashInfer MLA on sm_103 (H4 deferred in `/Users/kiteboard/prism/docs/mla-corpus/HYPOTHESIS_LADDER.md` §H4); on-device second-model cross-vendor if both must be local (memory-gated).

---

## 2. URL and deploy infrastructure

| Attribute | `/prism42` (existing) | `/prism42-b300` (new) |
|:---|:---|:---|
| URL | `www.thegoatnote.com/prism42` | `www.thegoatnote.com/prism42-b300` |
| Hosting | Vercel static front-end + Managed Agents back-end | Same front-end path; B300 pod in back-end |
| LLM back-end | Anthropic Managed Agents (Opus 4.7) | Opus 4.7 + GPT-5.5 dialectic + local Llama-3-70B NVFP4 rubric |
| Voice STT | ElevenLabs Flash (`~75 ms` per source §9 of `anthropic-elevenlabs-agent-bp-2026-04-21.md`) | Parakeet-RNNT streaming on B300 (target `< 50 ms` partial-transcript, `pending` measurement) |
| Voice TTS | ElevenLabs Conversational AI | Same (TTS is not the B300 bottleneck; see §5 rationale) |
| Rubric grader | GPT-5.5 hosted, async, 2–4 s behind real-time (`docs/agents/topology.md` L217) | Local Llama-3-70B NVFP4 on B300, target p50 ≤ 800 ms in-turn |
| OHCA detector | Transcript-triggered LLM classification (post-utterance) | Continuous audio-domain classifier streaming at ~30 ms chunk cadence |
| Continuity claim | Same agents as benchmarked | Superset: same 20 agents + B300-only augmentations, each with its own rubric §2 grid pass before public demo |

**Deploy flow**: Vercel serves `/prism42-b300/*` as a variant of the existing route; the back-end coordinator (existing Managed Agent) receives a `deployment: "b300"` header and routes to the B300 pod for rubric + OHCA classifier invocations. Fall-through to `/prism42` behavior if the B300 pod is unreachable — fail-safe to the benchmarked floor.

---

## 3. B300 hardware + software reference

All numbers cited with fetch-date; unverifiable claims labeled `pending`.

### 3.1 Hardware (B300 SXM6, fetch-date 2026-04-23)

| Attribute | Value | Source |
|:---|:---|:---|
| Compute capability | `10.3` (`sm_103` / `sm_103a`) | Verified empirically on Brev/Verda pod `prism-mla-b300-h4h5`; `torch.cuda.get_device_capability(0) == (10, 3)` |
| HBM3e memory | 270–288 GB per GPU (nvidia-smi on test pod reports 275 040 MiB usable) | [Verda B300 page](https://verda.com/b300) fetch 2026-04-23; empirical `nvidia-smi` |
| Memory bandwidth | 7.7 TB/s | [Verda B300-vs-B200 blog](https://verda.com/blog/nvidia-b300-vs-b200-complete-gpu-comparison-to-date) fetch 2026-04-23 |
| FP4 dense | 14 PFLOPS (55.6 % > B200's 9 PFLOPS) | same source |
| FP8/FP6 | 4.5 PFLOPS | same |
| BF16/FP16 | 2.25 PFLOPS | same |
| TF32 | 1.1 PFLOPS | same |
| FP32 | 0.037 PFLOPS | same |
| NVLink (gen 5) | 1.8 TB/s | same |
| TDP | up to 1100 W (vs B200 1000 W) | same |
| Driver seen on pod | `580.126.09` | empirical |

### 3.2 Software stack (fetch-date 2026-04-23)

| Layer | Version | Status on sm_103 | Source |
|:---|:---|:---|:---|
| CUDA Toolkit | **12.9** first added `compute_103` / `sm_103` / `sm_103a` / `sm_103f` compile targets; **13.0** full support | ✓ nvcc ≥ 12.9 mandatory | [CUDA 13.0 release notes](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/index.html) fetch 2026-04-23 |
| nvcc on Brev/Verda B300 pod (stock) | **12.8** | **✗ `nvcc fatal : Unsupported gpu architecture 'compute_103a'`** — pod setup script must install CUDA ≥ 12.9 | empirical 2026-04-23 |
| PyTorch | 2.11.0+cu130 | ✓ reports `cap (10,3)` correctly; `torch.compile(mode='max-autotune-no-cudagraphs')` produces Triton + cuBLAS kernels on sm_103 | empirical |
| CUTLASS | 4.4.1+ | ✓ `tcgen05.mma` + NVFP4/MXFP4/MXFP6/MXFP8 block-scaled; known SM120 issues in issue #3096 but data-center sm_103 is in better shape | [CUTLASS CHANGELOG](https://raw.githubusercontent.com/NVIDIA/cutlass/main/CHANGELOG.md) fetch 2026-04-23 |
| FlashInfer-python | 0.6.8.post1 (PyPI latest 2026-04-23) | **✗ MLA decode broken on sm_103**: fa3/fa2 compile sm_90 only → runtime `no kernel image`; cutlass compiles with `FLASHINFER_CUDA_ARCH_LIST="10.0"` workaround but runtime `cutlass fmha.initialize failed: Error Internal`. Mainline `main` branch has sm_103 fixes in progress. | empirical + [FlashInfer issue #2723](https://github.com/flashinfer-ai/flashinfer/issues/2723) |
| TensorRT-LLM | **1.1** added B300/GB300; **1.2** DGX Spark beta; DeepSeek V3 chunked prefill on sm_103 ✓, KV cache reuse BF16/FP8 ✓ | ✓ | [TRT-LLM release notes](https://nvidia.github.io/TensorRT-LLM/release-notes.html) fetch 2026-04-23 |
| vLLM | 0.14.1 | ✓ validated by vLLM blog on GB300 for DeepSeek-V3.2 NVFP4+TP2 at 7 360 / 2 816 TGS prefill/decode | [vLLM GB300-DeepSeek blog](https://vllm.ai/blog/gb300-deepseek) fetch 2026-04-23 |
| SGLang | latest | ✓ 1.32× vs vLLM at batch=1 decode, 2.23× at batch=128 via Blackwell CUTLASS schedules | [Joshua8.AI bench](https://joshua8.ai/llm-inference-benchmark/) fetch 2026-04-23 |
| NeMo / Parakeet | Parakeet-TDT 0.6B v3 (HF); Parakeet-RNNT multilingual (streaming) | ✓ on B300 via NeMo direct; **NIM is offline-only** for Parakeet-TDT | [Parakeet TDT HF card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) + [NIM Riva ASR matrix](https://docs.nvidia.com/nim/riva/asr/latest/support-matrix.html) fetch 2026-04-23 |

### 3.3 Required environment and ABI gotchas

1. **CUDA toolkit upgrade**: Brev/Verda B300 image ships nvcc 12.8. Pod setup script must install `cuda-toolkit-12-9` (or 13.0) before any FlashInfer / CUTLASS JIT compile. (Alternatively, pin `FLASHINFER_CUDA_ARCH_LIST="10.0"` to target `compute_100a` which nvcc 12.8 accepts; sm_100a code executes on sm_103 hardware — `pending` verification for runtime correctness beyond the cutlass fmha init failure we already observed.)
2. **FlashInfer arch override**: `export FLASHINFER_CUDA_ARCH_LIST="10.3"` (or `"10.0"` for nvcc 12.8) is required; without it, FlashInfer's `CompilationContext._normalize_cuda_arch(10, 3)` returns `(10, "3a")` which maps to `compute_103a,code=sm_103a`.
3. **`/home/ubuntu` vs `/home/shadeform`**: Brev/Verda pods run as user `shadeform`, not `ubuntu`. Scripts that hard-code `/home/ubuntu/workspace` (including Brev's own documented paths) break. Use `$HOME` or resolve at runtime.
4. **Ninja path**: `pip install ninja` places the binary under `<venv>/bin/ninja`, not `/usr/bin/ninja`. Subprocess-based kernel builds (FlashInfer, Triton) inherit `PATH` from the parent — prepend `"$venv/bin"` before invoking.

---

## 4. Self-verification loop (frontier-lab discipline, mandatory)

This section is referenced by every B300 augmentation in §5. Each augmentation implements **all four layers**:

| Layer | Purpose | Concrete gate |
|:---|:---|:---|
| **L1 — Schema** | Augmentation's structured output parses as the augmentation's JSON Schema 2020-12 | `scripts/validate_b300_artifacts.py --case-dir <dir>` exit 0; extends the existing `scripts/validate_artifacts.py` pattern |
| **L2 — Agreement w/ anchor** | Augmentation's decision agrees with the corresponding anchor system on ≥ 95 % of the 42-scenario red-team fixture (`corpus/red-team/psap-fixtures-v0.1.yaml`) | Anchor = the production `/prism42` path for that decision; disagreement logged to `findings/b300-disagreement.jsonl`; gate: per-scenario `{"agreement": true, "severity_delta": <=1}` |
| **L3 — Rubric score** | Augmentation does not regress `psap-rubric-live` grade vs anchor on the same red-team fixture | Gate: median rubric-grader score ≥ anchor median on all 5 GEDP-aligned criteria (`docs/agents/topology.md` L201–213) |
| **L4 — Latency SLA** | Augmentation meets its stated p50 and p99 on the test pod | Gate: measured p50 ≤ stated p50 × 1.05, p99 ≤ stated p99 × 1.10 on n ≥ 100 trials |

**Exit gate for public promotion to `/prism42-b300`**: all four layers green on all 42 scenarios, with the same rigor as rubric v1.1 §2 grid + §3 integration.

**Verification harness**: `scripts/verify_b300_voice.py` (new) orchestrates L1–L4 against a live B300 pod; exit 0 = promotion-ready; `pending` until implemented.

---

## 5. B300-specific safety augmentations

### 5.1 Sub-second local rubric grader (replaces hosted 2–4 s GPT-5.5)

#### 5.1.1 Behavior change

Today, `psap-rubric-live` grades each dispatcher turn against 5 GEDP-aligned criteria using a hosted model (GPT-5.5 preferred, GPT-5.4 fallback; `docs/agents/topology.md` L201–217). Grades arrive **2–4 s behind real-time**, which means:

- The dispatcher's next utterance is already underway when the grade on the previous turn arrives.
- A rubric failure can only trigger **post-hoc intervention** (safety-monitor escalation for the next turn, or a recorded audit finding for QI review).
- The utterance the caller is currently hearing is never graded before it ships.

On B300, with the grader running locally on Llama-3-70B NVFP4 (see §5.1.3), the latency budget collapses to a **target p50 ≤ 800 ms, p99 ≤ 1 500 ms** per turn.

At 40 tokens/sec natural speech cadence (`anthropic-elevenlabs-agent-bp-2026-04-21.md` §5), a dispatcher utterance of ≥ 40 tokens takes ≥ 1.0 s to speak. **A sub-second rubric grade can arrive before the utterance finishes** — creating a new intervention class:

- **Pre-TTS gating** (in-turn): the rubric grade on the LLM's generated text (before TTS streaming starts) decides whether to emit, defer, or substitute a safe-message. This extends the existing structured-JSON gate (`schemas/psap-turn.schema.json` `self_verify.all_passed`) with a continuous rubric check.
- **Mid-utterance barge-in** (rare): if the rubric grade on the first half of a streaming TTS utterance crosses a critical threshold (e.g., scope-violation or safety-preservation red), the back-end can interrupt TTS and inject a standard correction ("*Let me correct that — ...*"). This is high-risk UX and requires physician sign-off before enabling; spec's default is OFF with a feature flag.

#### 5.1.2 What sub-second rubric reveals that 2–4 s post-hoc does not

- **Per-turn drift**: when the model's confidence in its scope-adherence drifts mid-call (e.g., a chatty caller pulling toward diagnosis), 2–4 s latency masks the drift because by the time the grade lands, the model has already self-corrected. Sub-second grades expose the oscillation.
- **Response-generation-time gate**: the structured-JSON `self_verify.all_passed` check runs on the model's own reflection. A sub-second independent rubric grade is a **second opinion on the same turn** — different failure modes (LLM hallucinates both its output AND its self-verify).
- **Corrective UX latency budget**: if the grade arrives in < 1 s, a dispatcher-in-the-loop can abort/override a suggestion before the caller hears it. Post-hoc grades cannot.

#### 5.1.3 Architecture

```
+--------------------+   dispatcher   +----------------------+
|  Coordinator       |---- turn  --->|  Llama-3-70B NVFP4   |
|  (Managed Agent)   |               |  on B300 (vLLM 0.14.1)|
+--------------------+               +----------------------+
          |                                     |
          | self_verify (structured JSON)       | rubric scores 
          v                                     v  (5 criteria × 
+--------------------+                          | confidence)
|  schemas/          |                          |
|  psap-turn.schema  |<--- augmentation merge --+
+--------------------+
          |
          v
      all_passed && rubric.min_score >= threshold
          |
          +---> TTS stream (if green)
          +---> defer/refuse/escalate (if red)
```

- **Model**: Llama-3-70B NVFP4 (fits in ~36 GB on B300 with 128k ctx KV cache; `pending` exact KV math) OR Qwen2-72B NVFP4. Choice reasoned in §8 as open question; default Llama-3-70B because Open-Weight, widely validated on vLLM GB300 path.
- **Serving**: vLLM 0.14.1 with `VLLM_USE_FLASHINFER_MOE_FP4=1` (reference: vLLM GB300-DeepSeek blog, fetch 2026-04-23). TP1 on single B300 (no tensor-parallel needed at 70B NVFP4).
- **Prompt**: Existing GEDP 5-criteria rubric prompt (`docs/agents/topology.md` L201–213) ported verbatim. No prompt engineering for Llama-specific quirks at spec-time; L2 agreement gate catches drift.
- **Output**: Structured JSON `{"clinical_accuracy":0-5, "scope_adherence":0-5, "safety_preservation":0-5, "clarity":0-5, "protocol_adherence":0-5, "confidence":0-1, "rationale":"..."}`. Schema: `schemas/psap-rubric-local.schema.json` (new, extends existing rubric schema; `pending` creation).
- **Latency budget**: prefill ≤ 200 ms for 2 k token dispatcher-turn context; decode 25–50 output tokens at ~3 ms/token NVFP4 ≈ 75–150 ms; JSON-parse + schema-validate ≤ 20 ms. **Total p50 target: ≤ 800 ms.**

#### 5.1.4 Self-verification (L1–L4 per §4)

- **L1**: new schema `schemas/psap-rubric-local.schema.json`; `scripts/validate_b300_artifacts.py --kind rubric-local` gate.
- **L2**: on every red-team scenario (42 total), the local Llama grader's 5 scores must agree with the hosted GPT-5.5 grader within ±1 (on a 0–5 scale) on ≥ 95 % of turns. Disagreement logged.
- **L3**: median 5-criteria score local ≥ hosted median on the same fixture (the local grader must not be harsher or more lenient by more than 0.2 points median).
- **L4**: p50 ≤ 800 ms, p99 ≤ 1 500 ms measured on n=100 red-team scenarios.

**Open fail-modes** (§8 open questions):
- What if the local grader is systematically more lenient on safety-preservation (it's the hardest axis)? Defense: L3 gate + 42-scenario red-team fixture includes safety-preservation-stress scenarios (category F).
- What if local and hosted disagree on a production call? Both scores logged to `findings/b300-rubric-dual-log.jsonl`; the **hosted score** is load-bearing for deploy gating (sub-second is a speed feature, not a correctness replacement); physician review consulted on divergence > 3 red-team scenarios per week.

---

### 5.2 Continuous on-device OHCA classifier

#### 5.2.1 Behavior change

Today, `psap-ohca-detector` is triggered on each dispatcher turn (post-transcript), runs a hosted-model classification on the transcript text, and returns a binary + reason. Failure modes:

- **Transcript lag**: STT is itself 75–200 ms behind spoken audio; post-transcript classification adds another hosted-LLM hop.
- **Audio-domain information lost**: gasping, agonal respiration, silence after a thud, collapse noise — none of this reaches a text-only classifier.
- **Debounce gap**: first 10–30 s of a call is often the highest-yield OHCA detection window (caller distress, breathing pattern); transcript-only detection misses non-verbal cues.

On B300, the classifier runs **directly on the audio stream** in ~30 ms windows, concurrent with STT.

#### 5.2.2 Architecture (sketch, exact model `pending` selection)

```
 audio stream (16 kHz mono) ----+----> STT (Parakeet-RNNT streaming)
                                |
                                +----> OHCA classifier (this section)
                                            |
                                            v
                                     binary {OHCA_suspected, confidence, modality}
                                            |
                                            +---> emits an event to coordinator if 
                                                  confidence > threshold for N 
                                                  consecutive 30 ms windows
```

- **Model class**: small (<100 M params) audio-event classifier trained on a *continuous gasping / agonal-breathing / collapse-noise* dataset. Candidate architectures (choice is `pending`, §8 open):
  - **AST (Audio Spectrogram Transformer)** pre-trained on AudioSet, fine-tuned on medical-event audio
  - **BEATs / Whisper-encoder embeddings** + small classifier head
  - **Wav2Vec2 + Conformer head** specialized for agonal-respiration detection
- **Serving**: TensorRT-LLM 1.2 or ONNX Runtime CUDA on B300. FP8 or NVFP4 quantized. ≤ 1 GB VRAM. Runs alongside the rubric grader on the same pod.
- **Input window**: 30 ms sliding at 10 ms hop (industry-standard audio event detection cadence). Model input is the log-Mel spectrogram over the last 300 ms (rolling).
- **Output**: `{p_ohca: float, modality: ["gasping","agonal_respiration","silence_then_thud","breathing_pattern_normal"], confidence: float}` per 30 ms frame.
- **Escalation policy**: fire a coordinator event when `p_ohca > 0.8` for ≥ 5 consecutive frames (150 ms), AND `confidence > 0.7`. Coordinator policy (`docs/agents/topology.md` psap-ohca-detector role) decides whether to inject PDI (pre-arrival instructions) prompt and notify psap-team-coordinator.

#### 5.2.3 Latency budget

- Audio frame → Mel spectrogram: ≤ 2 ms (CPU-side, handled by audio ingress)
- Classifier forward: ≤ 5 ms on B300 (NVFP4 + TensorRT-LLM; `pending` empirical)
- Coordinator event emit: ≤ 10 ms (IPC)
- **End-to-end p50 target**: ≤ 30 ms per frame (one frame of debt max)
- **Detection window (5 consecutive frames)**: ≤ 150 ms from onset of detectable signal

#### 5.2.4 False-positive discipline

OHCA false alarms carry two kinds of cost: (a) embarrassment / unnecessary dispatch escalation on a non-emergency, (b) **eroded dispatcher trust in the classifier**, which turns into the detector being ignored when it matters. The spec's default is to **bias for under-alarming**:

- **Gate 1** — per-frame threshold `p_ohca > 0.8` (not 0.5): derived from ROC cut-point on held-out validation audio; `pending` dataset selection (candidates: MIMIC-III respiratory audio, Sonus cardiac-event audio, GOATnote-collected synthetic).
- **Gate 2** — 5-consecutive-frame hysteresis: rejects spurious spikes from cough / speech glottal closure / environmental noise.
- **Gate 3** — cross-check with Parakeet transcript: if the last 1 s of transcript contains "talking", "laughing", or affirmative responses to dispatcher, suppress the event (the patient is not in arrest).
- **Gate 4** — rubric grader confirmation: coordinator passes the raw audio window + transcript to the local Llama rubric grader with the prompt "Is OHCA likely? Respond yes/no + confidence." If the grader disagrees with confidence > 0.9, suppress.
- **Gate 5** — physician-reviewable audit trail: every OHCA event (suppressed or fired) logged to `findings/ohca-events.jsonl` with audio-window hash + all 4 gate values. QI reviews weekly.

Target FPR: **≤ 0.5 false alarms per 1 000 dispatcher-hours** (aggressive; `pending` empirical). Recall should stay ≥ 90 % on held-out AHA-protocol-confirmed OHCA recordings.

#### 5.2.5 Self-verification (L1–L4 per §4)

- **L1**: `schemas/psap-ohca-event.schema.json` (new); validator enforces the 5-gate record.
- **L2**: on held-out OHCA audio fixture (separate from red-team; `pending` curation), binary agreement with physician-labeled ground truth ≥ 95 % recall, ≥ 99 % specificity.
- **L3**: does not degrade psap-rubric-live safety-preservation median score (i.e., the classifier must not trigger *during* a non-emergency turn in a way that corrupts the coordinator's structured output).
- **L4**: p50 ≤ 30 ms per frame; p99 ≤ 60 ms; zero frames dropped over a 60-minute soak.

---

### 5.3 Real-time cross-vendor dialectic (Opus 4.7 + GPT-5.5 concurrent)

#### 5.3.1 Behavior change

Today, the dialectic between Opus 4.7 (primary) and the external rubric grader (GPT-5.5) is **sequential and post-hoc**: Opus generates → structured-JSON gate → GPT-5.5 grades (2–4 s later). The two models never see the same dispatcher turn at the same time.

On B300, both models consume the **same dispatcher-turn context simultaneously**, and the coordinator reconciles in real-time.

#### 5.3.2 Why concurrency (not sequentialism)

Sequential dialectic tests Model B's grade of Model A's output. Real-time concurrent dialectic tests **whether Model B would produce the same output given the same inputs**. The failure modes exposed are disjoint:

- **Sequential catches**: post-hoc rubric violations, scope drift, protocol skips (Model B reads Model A's output and notices what's missing/wrong).
- **Concurrent catches**: Model A's *framing* of the problem (latent biases in prompt interpretation), model-specific hallucination signatures, situations where the two models agree on rubric but would have taken opposite actions.

Concrete example: a caller says "I think my husband had a heart attack." Opus 4.7 may transition to OHCA PDI confidently; GPT-5.5 may ask the verification question ("Is he breathing normally?") before committing. Sequential grading scores both answers as acceptable. **Concurrent** disagreement reveals that the two models chose different risk profiles for the same turn — and the coordinator can surface that to the dispatcher for a real-time decision.

#### 5.3.3 Architecture

```
+-------------------- coordinator (Managed Agent) ---------------+
|                                                                 |
|   dispatcher turn context  ----- fan out --+------> Opus 4.7    |
|                                             |         (primary) |
|                                             +------> GPT-5.5    |
|                                             |         (secondary)|
|                                             +------> local Llama|
|                                                       (rubric)  |
|                                                                 |
|   +---- reconciler <--- {action_A, action_B, rubric_scores} --+ |
|   |                                                             |
|   v                                                             |
|  disagreement?  yes -> log + apply disagree-resolution policy   |
|                  no -> emit action_A with cross-vendor=OK flag  |
+-----------------------------------------------------------------+
```

- **Fan-out**: both hosted APIs receive the same structured system prompt + GEDP preambles + 42-scenario-context. Opus 4.7 is the action producer; GPT-5.5 is a parallel action producer (not a grader) whose output is compared.
- **Reconciler**: a deterministic policy (NOT a third LLM — critical for determinism):
  - If `action_A == action_B` on `{action_type, severity_code, next_question}` → emit `action_A`, record concurrence.
  - If `action_A.severity_code > action_B.severity_code` (Opus more cautious) → emit `action_A` (always favor higher severity), flag "Opus-more-cautious".
  - If `action_A.severity_code < action_B.severity_code` (GPT more cautious) → emit `action_B`, flag "GPT-more-cautious".
  - If `action_type` differs (e.g., dispatch vs verify) → default to **verify** (the question-asking action), flag "cross-vendor-action-type-disagreement", escalate to psap-safety-monitor.
- **Rubric grader** (§5.1) runs on whichever action the reconciler emitted, within the same sub-second budget.

#### 5.3.4 What real-time disagreement reveals vs post-hoc

Post-hoc grading answers: "Was the action correct?" Real-time cross-vendor disagreement answers additionally:

- **"How stable was the correct action?"** — if two frontier models independently chose the same action, the decision is stable; if they diverged, the dispatcher sees a disagreement flag and has evidence-of-controversy before committing.
- **Prompt-robustness**: if Opus consistently picks action X and GPT consistently picks action Y on the same inputs, the divergence is in model priors, not the scenario. This data feeds future prompt engineering (e.g., safety preamble revisions).
- **Consensus-vs-authority tradeoff**: post-hoc dialectic privileges Model B's grade. Real-time dialectic makes **neither model the authority** — the reconciler policy is. This matters for regulator-facing audit: the claim is "two frontier models and a deterministic safety-biased policy", not "one AI model".
- **Model-drift detection**: when an upstream provider deploys a new minor model version (Opus 4.7 → 4.8; GPT-5.5 → 5.6), real-time concurrence rate tracks deployment-induced shift directly. Sequential grading can't distinguish "model A drifted" from "model A and model B both drifted in the same direction."

#### 5.3.5 Cost + latency

- Two concurrent hosted API calls per turn. At Opus 4.7 ~$0.015/1k-token-out and GPT-5.5 ~$0.020/1k-token-out (`pending` exact 2026-04-23 pricing), a 50-token-out dispatcher turn costs ~$0.0018 for Opus + ~$0.0010 for GPT ≈ $0.003/turn total.
- Latency: both calls in parallel; p50 end-to-end = max(Opus p50, GPT p50). Per provider docs, Opus 4.7 p50 ~400 ms, GPT-5.5 p50 ~300 ms for 50-token responses (`pending` empirical). **Real-time concurrency target: p50 ≤ 500 ms per turn-pair.**
- Reconciler: deterministic, ≤ 2 ms.

#### 5.3.6 Self-verification (L1–L4 per §4)

- **L1**: `schemas/cross-vendor-decision.schema.json` — captures both actions, reconciler verdict, rubric scores, flags.
- **L2**: disagreement rate on the 42-scenario red-team fixture ≤ 20 % (baseline; benchmarks will tighten); on scenarios labeled "agreement expected" (Category A — OHCA, severe hemorrhage) disagreement should be ≤ 5 %.
- **L3**: when reconciler fires "verify" action due to cross-vendor action-type disagreement, rubric grade on the resulting utterance must be ≥ median of non-disagreement turns (verification questions are a legitimate dispatcher move, not a regression).
- **L4**: p50 ≤ 500 ms, p99 ≤ 1 200 ms per turn-pair; reconciler latency p99 ≤ 5 ms.

---

## 6. Cost model on B300

### 6.1 Fixed cost (B300 rental)

Rates fetch-date 2026-04-23. Rounded per-hour; monthly = hourly × 720.

| Provider | Config | $/hr (on-demand) | $/hr (spot) | Source |
|:---|:---|---:|---:|:---|
| Brev (NVIDIA) | 1× B300 SXM6 (Verda, Helsinki) | $7.91 | `pending` | empirical (pod `prism-mla-b300-h4h5`) |
| Verda direct | 1× B300 SXM6 | `pending` (not listed on verda.com/b300, which lists B200 only) | `pending` | [verda.com/b300](https://verda.com/b300) fetch 2026-04-23 |
| Shadeform | 1× B300 via partner clouds | ~$5.63/hr (this was March 2026 B200 number; B300 `pending`) | varies | [Shadeform B200 article](https://shadeform.com/resources/articles/nvidia-b200-gpu-price-guide) fetch 2026-04-23 |
| Lambda | `pending` — no B300 listing seen 2026-04-23 | `pending` | `pending` | — |
| AWS p6-b300 | `pending` — not announced as of 2026-04-23 | `pending` | — |
| RunPod | B200 at ~$2.99/hr confirmed earlier; B300 `pending` | `pending` | `pending` | — |

**Working assumption for break-even math**: $7.91/hr Brev, or $6.00/hr blended estimate across emerging spot providers.

### 6.2 Variable cost (per-call decomposition)

Baseline: a 2-minute 911 dispatcher call with ~40 dispatcher turns (~20 caller turns, alternating).

| Component | Per call | Notes |
|:---|---:|:---|
| STT (ElevenLabs Flash) | ~$0.016 | [ElevenLabs pricing](https://elevenlabs.io/conversational-ai) `pending` exact 2026-04-23 number |
| STT (Parakeet on B300, local) | $0 variable; amortized to fixed | drop-in replacement for ElevenLabs STT; only labor-cost is integration |
| TTS (ElevenLabs Conversational AI) | ~$0.040 | unchanged from `/prism42` |
| Opus 4.7 inference (40 turns × ~50 tok) | ~$0.072 | `pending` 2026-04-23 per-token pricing |
| GPT-5.5 concurrent inference (40 × ~50 tok) | ~$0.040 | new cost for B300 augmentation §5.3 |
| Rubric grader (local Llama NVFP4) | $0 variable; amortized | replaces hosted GPT-5.5 grader (~$0.020/call saved) |
| OHCA classifier (local) | $0 variable; amortized | replaces nothing (net-new capability) |
| **Total per call (B300)** | **~$0.168** | `/prism42` comparable ~$0.148 (same STT/TTS/LLM; no §5.3 second model) |
| Incremental vs `/prism42` | **+$0.020/call** | net cost of §5.3 real-time cross-vendor concurrency |

### 6.3 Break-even: owning B300 capacity vs paying per-call

At $7.91/hr fixed, amortizing purely over voice-calls:

- **Break-even point**: $7.91/hr ÷ $0.020 incremental-savings-per-call = **~396 calls/hr** or **6.6 calls/minute** just to justify the incremental cross-vendor cost. Clearly B300 is not justified on §5.3 alone.
- **Full amortization** (including §5.1 local rubric + §5.2 OHCA): saves ~$0.024/call (hosted rubric) + avoids undeterminable cost of missed-OHCA liability. Break-even becomes **~329 calls/hr = 5.5 calls/min**. Still high.

**Correct framing: B300 is NOT justified by cost savings. It is justified by latency + capability + continuity**:

- Sub-second rubric enables pre-TTS gating — a capability category that has no equivalent per-call API price because it doesn't exist as a hosted service.
- Continuous audio-domain OHCA classifier likewise.
- Real-time cross-vendor dialectic requires both calls in parallel; hosted providers don't offer a joint-inference API.

**Recommended deploy pattern**: one B300 pod serves N parallel calls concurrently (quantify N: rubric grader at 50 tok/call, 800 ms/grade, B300 can run ~40 concurrent grades if memory permits). At N = 40 concurrent calls, fixed-cost per call = $7.91/hr ÷ (40 × 60 min/hr ÷ 2 min/call) = $7.91 / 1 200 ≈ $0.0066/call. **Below the § 5.3 incremental cost**, so B300 pays for itself at ≥ ~30 concurrent calls. `pending` empirical verification of N.

### 6.4 Development + integration cost (one-time)

- vLLM 0.14.1 + FlashInfer FP4 MoE setup on B300: ~4 hr engineer time (includes nvcc 12.9 install, FLASHINFER_CUDA_ARCH_LIST, container build).
- Local Llama-3-70B NVFP4 rubric integration: ~2 days engineer + 1 day physician review on 42-scenario fixture.
- OHCA classifier: **6–12 weeks** (dataset curation + model selection + L2 gate + physician sign-off). The long pole.
- Cross-vendor reconciler: ~3 days engineer + 1 day policy review.

---

## 7. What does NOT change

The following must remain identical between `/prism42` and `/prism42-b300`:

- **GEDP v0.1** protocol (`docs/dispatch-protocol-v0.1.md`). Three-character determinant codes, dispatcher authority scope, GEDP citations (AHA BLS 2025, NHTSA, peer review). No new determinants introduced by B300 augmentations.
- **20-agent topology** (`docs/agents/topology.md`). B300 augmentations are implementation changes to existing agents (psap-rubric-live goes local; psap-ohca-detector gains an audio input path), not new agents. No new agent registrations.
- **Structured-JSON output gate** (`schemas/psap-turn.schema.json`). `self_verify.all_passed` remains the primary deploy gate. Rubric + OHCA + cross-vendor results are additive fields on the same envelope, not replacements.
- **Safety preambles SP-001 through SP-010** (`docs/safety-preambles.md`). Identical.
- **42-scenario red-team fixture v0.1** (`corpus/red-team/psap-fixtures-v0.1.yaml`). Identical fixture; `/prism42-b300` must pass all 42 scenarios before public promotion, using the same release-gate criterion.
- **Pipeline narrative** (`docs/pipeline-narrative.md`). Four-stage evidence stack unchanged. `/prism42-b300` plugs into Stage 2 (compute-path optimization) and Stage 3 (clinical-reasoning lift) without rewriting Stage 1 (kernel correctness).
- **Public URL `/prism42`**. Not redirected, not deprecated. `/prism42-b300` is a sibling.
- **Continuity claim** (`README.md` L47–57). `/prism42`'s claim stands as-is. `/prism42-b300` has its own continuity claim: same 20 agents, same preambles, same fixture, enhanced on B300-specific augmentations each of which has its own L1–L4 verification record.
- **Rubric v1.1 discipline** (from `/Users/kiteboard/prism/mla/docs/EVALUATION_RUBRIC.md` v1.1). No "beats X" claims for B300 augmentations without rubric §2 grid + §3 integration. Same hype-free language.

---

## 8. Open questions (decisions not made alone)

Each is flagged as requiring user input before implementation begins. Build-agents must NOT choose defaults for these without explicit approval.

### 8.1 B300 rental provider

- **Option A**: Brev (NVIDIA) / Verda backend. $7.91/hr. **Pro**: empirically validated; auth via `brev login --token` works; persistent volume path `/home/shadeform/workspace` survives reboots on non-pre-release instances. **Con**: Verda pre-release is no-stop/start (only delete); Helsinki-only.
- **Option B**: Lambda, CoreWeave, or another hyperscaler when B300 listings land. `pending` pricing.
- **Option C**: AWS p6-b300 when announced. `pending` availability.
- **Default recommended**: **A (Brev/Verda)** for near-term validation; reassess at beta-ready.

### 8.2 STT primary vendor (for `/prism42-b300`)

- **Option A**: Keep ElevenLabs Flash. **Pro**: unchanged integration; already HIPAA-compliant per ElevenLabs marketing. **Con**: variable per-call cost; external dependency.
- **Option B**: Switch to Parakeet-RNNT streaming on the B300 pod. **Pro**: eliminates STT variable cost; controlled latency budget; can co-locate with rubric grader on same GPU. **Con**: integration engineering; PHI compliance stays with B300 pod operator.
- **Option C**: Both — Parakeet primary, ElevenLabs fallback on pod failure. **Pro**: best of both; fail-safe. **Con**: 2× integration cost.
- **Default recommended**: **C** for production readiness; **A** for demo-only continuity.

### 8.3 Second concurrent LLM (GPT-5.5) — real-time or async?

- **Option A**: Real-time concurrent, per §5.3. **Pro**: exposes cross-vendor action-type disagreement in UX. **Con**: +$0.040/call; requires reconciler policy that both product + legal sign off on.
- **Option B**: Async, graded post-hoc (current `/prism42` behavior for GPT-5.5 as rubric grader). **Pro**: cheap, low-risk. **Con**: loses the real-time disagreement-reveals-model-framing-bias capability (§5.3.4).
- **Option C**: Real-time concurrent, but only on **Category A red-team scenarios** (OHCA, severe hemorrhage) and random 10 % sample of other calls. **Pro**: cost-bounded; exercises the capability on highest-stakes turns. **Con**: sampling discipline adds complexity.
- **Default recommended**: **C** for public beta; promote to A after 90-day disagreement-rate analysis.

### 8.4 On-device OHCA classifier — Phase 1 or Phase 2?

- **Option A**: Phase 1 (ship with `/prism42-b300` launch). **Pro**: maximum capability at launch; differentiates against hosted-only competitors. **Con**: 6–12 weeks of dataset + model + physician-review work; highest-risk path (FP discipline is hard).
- **Option B**: Phase 2 (ship `/prism42-b300` with local rubric + cross-vendor, add OHCA later). **Pro**: faster to launch; decouples risks. **Con**: marketing narrative is weaker (no new audio-domain capability at launch).
- **Default recommended**: **B** — ship Phase 1 as local-rubric + cross-vendor dialectic; queue OHCA classifier as Phase 2 with its own 42-scenario audio-fixture first.

### 8.5 Rubric-grader model choice

- **Option A**: Llama-3-70B NVFP4 (vLLM validated on GB300). **Pro**: open weights; widely reproduced. **Con**: may under-perform on scope-adherence vs hosted GPT-5.5.
- **Option B**: Qwen2-72B NVFP4. **Pro**: reportedly stronger on instruction-following. **Con**: less validated on GB300 stack specifically (`pending`).
- **Option C**: DeepSeek-V3.2 NVFP4 (per vLLM GB300 blog). **Pro**: highest validated throughput on GB300; MoE means 37B active parameters per token. **Con**: may be over-kill for the rubric task; costlier at concurrency.
- **Default recommended**: **A** for consistency with open-source ecosystem; re-benchmark all three on the 42-scenario fixture before locking.

### 8.6 Local vs hosted fallback semantics

- If the B300 pod is unreachable during a production call, `/prism42-b300` back-end falls through to `/prism42` behavior (hosted rubric, no OHCA classifier, sequential dialectic). **Open**: should this be silent or visible to the dispatcher? Options:
  - **Silent fallthrough** — user experience degrades to `/prism42` baseline.
  - **Visible degraded-mode banner** — "Augmented grader unavailable; dispatch mode is baseline." Dispatcher knows quality is lower.
- **Default recommended**: **Visible** — consistent with the continuity claim (users know which mode they're in).

### 8.7 Self-verification harness dispatch

- L1–L4 verification needs an orchestrator. Options: (a) extend existing `scripts/verify_ralph_consistency.py` style linter, (b) new `scripts/verify_b300_voice.py`, (c) GitHub Action that runs nightly on a CI-pinned B300 pod.
- **Default recommended**: (b) `scripts/verify_b300_voice.py` hand-run + (c) nightly CI for regressions. Both flow into `findings/b300-verify-<date>.jsonl`.

### 8.8 Physician sign-off gating

- §5.1.1 "mid-utterance barge-in" is disabled by default pending physician sign-off.
- §5.2 OHCA classifier FPR target (≤ 0.5/1000-hr) requires physician review of held-out dataset.
- §5.3.3 cross-vendor action-type disagreement policy (`default to verify`) requires physician + legal review.
- **Open**: who are the sign-off physicians? Process (single physician vs panel)? Timeline?

---

## 9. Exit criteria

This spec is complete when a build-agent can:

- [ ] Deploy a B300 pod with the software stack in §3.2 installed and pass the sanity probe (nvcc ≥ 12.9; torch cap (10,3); vLLM 0.14.1 serves Llama-3-70B NVFP4).
- [ ] Implement §5.1 local-rubric path and pass L1–L4 self-verification (§4) on all 42 red-team scenarios.
- [ ] Implement §5.2 OHCA classifier (post decision on 8.4) and pass L1–L4.
- [ ] Implement §5.3 cross-vendor reconciler and pass L1–L4.
- [ ] Deploy to `www.thegoatnote.com/prism42-b300` via the Vercel variant path.
- [ ] Ship a single `findings/b300-release-<date>.jsonl` record containing all L1–L4 artifacts, signed off by a physician reviewer.
- [ ] NOT touch `/prism42` production path during any of the above.

---

## 10. Cross-refs (authoritative)

- **prism42 GEDP**: `docs/dispatch-protocol-v0.1.md`
- **prism42 20-agent topology**: `docs/agents/topology.md`
- **prism42 safety preambles**: `docs/safety-preambles.md`
- **prism42 red-team fixture**: `corpus/red-team/psap-fixtures-v0.1.yaml`
- **prism42 structured-JSON gate**: `schemas/psap-turn.schema.json`
- **prism42 pipeline narrative**: `docs/pipeline-narrative.md`
- **prism42 ElevenLabs blueprint (decode-latency budget)**: `docs/anthropic-elevenlabs-agent-bp-2026-04-21.md` §5 (updated 2026-04-23)
- **prism MLA decode measurements (H100, B300 torch-only)**: `<off-tree benchmark corpus>`, `.../CLAIM_002_b300_blackwell_ultra_torch_ceiling.md`
- **prism hypothesis ladder (H4 deferred, H5 supported)**: `/Users/kiteboard/prism/docs/mla-corpus/HYPOTHESIS_LADDER.md`
- **Empirical B300 pod session**: Brev/Verda `prism-mla-b300-h4h5`, 2026-04-23, artifacts at `/Users/kiteboard/prism/mla/results/logs/h5_h4_b300/`

---

## 11. Citations (external, fetch-date 2026-04-23)

1. [Verda B300 product page](https://verda.com/b300) — specs (HBM3e, NVLink, TDP).
2. [Verda B300 vs B200 comparison blog](https://verda.com/blog/nvidia-b300-vs-b200-complete-gpu-comparison-to-date) — TFLOPS table, architectural deltas.
3. [NVIDIA CUDA Toolkit 13.0 release notes](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/index.html) — sm_103 added at 12.9, full support 13.0; deprecates pre-Turing.
4. [CUTLASS 4.4 CHANGELOG](https://raw.githubusercontent.com/NVIDIA/cutlass/main/CHANGELOG.md) — tcgen05.mma, NVFP4/MXFP block-scaled support on SM100/SM103.
5. [CUTLASS SM120 NVFP4 MoE issue #3096](https://github.com/NVIDIA/cutlass/issues/3096) — known desktop-Blackwell gaps; data-center sm_103 status derived by elimination.
6. [FlashInfer SM120 issue #2723](https://github.com/flashinfer-ai/flashinfer/issues/2723) — NVFP4 MoE patches on CUTLASS; sm_103 mainline-only.
7. [NVIDIA TensorRT-LLM release notes](https://nvidia.github.io/TensorRT-LLM/release-notes.html) — 1.1 added B300/GB300, 1.2 DGX Spark beta; MLA chunked prefill on sm_103; FP8 MLA on Hopper+Blackwell.
8. [vLLM GB300 DeepSeek blog](https://vllm.ai/blog/gb300-deepseek) — vLLM 0.14.1 + CUDA 13.0 reference stack; `VLLM_USE_FLASHINFER_MOE_FP4=1`; DeepSeek-V3.2 NVFP4+TP2 at 7 360 / 2 816 TGS.
9. [SGLang vs vLLM Blackwell benchmark — joshua8.ai](https://joshua8.ai/llm-inference-benchmark/) — 1.32× at bs=1 / 2.23× at bs=128 decode via Blackwell CUTLASS schedules.
10. [Parakeet-TDT 0.6B v3 HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) — TDT architecture, RTFx, streaming availability.
11. [NIM Riva ASR support matrix](https://docs.nvidia.com/nim/riva/asr/latest/support-matrix.html) — NIM Parakeet-TDT is offline-only; RNNT multilingual is streaming.
12. [Supermicro MLPerf v6.0 B300 Whisper](https://learn-more.supermicro.com/data-center-stories/supermicro-leads-whisper-benchmark-in-mlperf-v6-nvidia-b300-gpus) — B300 HGX 8× config context.
13. [Spheron B300 Blackwell Ultra guide](https://www.spheron.network/blog/nvidia-b300-blackwell-ultra-guide/) — January 2026 ship date, 14 PFLOPS FP4 context.

**Labeled `pending` (not yet verifiable from current sources)**:
- Exact FlashInfer version that fixes sm_103 MLA decode (0.7.x `pending`; empirical prism session 2026-04-23 confirmed 0.6.8.post1 is broken).
- Exact Opus 4.7 and GPT-5.5 per-token pricing 2026-04-23.
- Exact Verda direct B300 on-demand price (page lists B200 spot $1.71; B300 not yet on public pricing).
- B300 Lambda / AWS p6 / RunPod availability and pricing.
- ElevenLabs Flash STT per-call USD cost 2026-04-23.
- OHCA audio classifier held-out dataset (candidates named in §5.2.2; selection deferred to §8.4).

---

*End of spec. Implementation begins on user approval + §8 decisions.*
