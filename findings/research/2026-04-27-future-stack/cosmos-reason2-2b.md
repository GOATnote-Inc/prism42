# Cosmos-Reason2-2B Feasibility Brief

**Date:** 2026-04-27 · **Status:** research-only · **Verdict:** 🟡 YELLOW —
RadSlice yes, prism42 voice no, healthcraft maybe.

## 1. What Cosmos-Reason2-2B is

NVIDIA's 2-billion-parameter vision-language model, December 2025 release.
Post-trained on Qwen3-VL-2B-Instruct. Designed for **physical AI and embodied
reasoning** — robotics, planning, spatio-temporal video reasoning.

- **License:** NVIDIA Open Model License (commercially usable).
- **Modalities:** images + video + text in; chain-of-thought text out
  (≤ 4096 tokens recommended).
- **Tasks:** object detection, VQA, spatio-temporal reasoning, task
  planning.
- **Medical/surgical fine-tune status:** **does NOT exist publicly.** The
  user's framing ("Medical Vision") describes *intended* work, not a
  shipped checkpoint. The Cosmos cookbook has SutureBot-style fine-tuning
  examples (via Cosmos-Predict 2.5), but the base model is robotics, not
  medical imaging.

Sources:
- https://huggingface.co/nvidia/Cosmos-Reason2-2B
- https://github.com/nvidia-cosmos/cosmos-reason2
- https://docs.nvidia.com/cosmos/latest/reason2/index.html

## 2. Where it would slot in — three candidate surfaces

### 2a. RadSlice DICOM pipeline (🟢 HIGHEST FIT — ~75% of leverage)

`~/radslice/` is a multimodal radiology VLM benchmark:
- 330 tasks across X-ray, CT, MRI, ultrasound (per `radslice-details.md` and
  CLAUDE.md memory).
- DICOM ingest via `dicom.py` (pydicom + windowing).
- 3-layer grading (L0 deterministic, L2 LLM radiologist judge).
- Documents 11 cross-modal blind spots where reasoning AND vision both fail.

**Why fit:** RadSlice's rubric is already structured for finding-detection
+ diagnostic-accuracy scoring. A medical-finetuned Cosmos variant could be
benchmarked head-to-head against current GPT-5.2 / Opus 4.6 on the rc1.2
forensic-audit subset (29 always-fail tasks, 44 corrected-pass-rate
benchmark).

**Note from memory:** rc1.2 forensic audit found "L0 patterns are
unreliable for pass decisions (75% of L0 passes are judge-false-positives)
. Always invoke judge." Adding a vision model adds a NEW error class
(phantom anatomy, fabricated findings) that the judge must absorb.

### 2b. healthcraft clinical tasks (🟡 MODERATE — ~20%)

`~/healthcraft/`: 195 eval tasks, 24 MCP tools, all
text-based today. No image ingestion. Vision would be NEW surface (e.g.,
new MCP tool `analyzeImage(study_id)` for radiograph review). Possible but
requires task redesign.

### 2c. prism42 voice (🔴 LOWEST — < 5%)

`~/prism42/`: voice path is audio + text only. CLAUDE.md §0
hackathon constraint: "voice path is audio/text only; no caller image
input today." Adding vision is net-new surface, not a drop-in. Latency
budget is 1.5 s p95 end-to-end — adding 200–500 ms vision step
risks the hackathon target.

**Direct engagement with the user's own framing** ("Cosmos doesn't solve
latency + determinism"): correct for prism42 voice. Cosmos is a VLM, not a
latency mitigation. Skip prism42 voice integration.

## 3. Inference path on B300 — vLLM is the official runtime

**NVIDIA's blessed serving path for Cosmos-Reason2-2B is vLLM**, not
TensorRT-LLM. The HF model card lists Transformers as runtime; the
recommended production serve uses vLLM with the Qwen3-VL multimodal
stack (Cosmos-Reason2-2B is post-trained on Qwen3-VL-2B-Instruct).
NIMs wrap vLLM under the hood (verified via `NIM_MODEL_NAME` env-var
plumbing). TRT-LLM has no first-class VLM recipe for this model.

Recommended serve command:

```
vllm serve nvidia/Cosmos-Reason2-2B \
  --allowed-local-media-path "$(pwd)" --max-model-len 16384 \
  --media-io-kwargs '{"video":{"num_frames":-1}}' \
  --reasoning-parser qwen3 --port 8000
```

Pin vLLM ≥ 0.12 for the Qwen3-VL recipe.

Three deployment options on the B300 pod:

1. **Standalone vLLM server** on its own GPU partition (simplest).
2. **Co-tenant with Nemotron** — Nemotron is served via TRT-LLM
   (cookbook AutoDeploy path, see `tensorrt-llm-on-b300.md`); Cosmos
   is served via vLLM. Two runtimes, same B300, different ports.
   This is the future-stack shape.
3. **TRT-LLM for Cosmos** — **do not.** No NVIDIA-blessed recipe;
   vLLM is the current standard for Qwen3-VL-class VLMs.

## 4. Latency + VRAM math on B300

| Component | Format | VRAM | Latency on B300 | Notes |
|---|---|---|---|---|
| Cosmos-Reason2-2B | BF16 | ~10 GB | ~150–300 ms / image (estimate) | NVIDIA has not published B300 numbers |
| Cosmos-Reason2-2B | FP8 | ~6 GB | TBD | Quantized variant available |
| Nemotron-30B NVFP4 | NVFP4 | ~20 GB | < 50 ms TTFT | 3B active per token |
| Parakeet STT | BF16 | ~3 GB | ~200 ms streaming | Already deployed |
| Fish TTS | BF16 | ~2 GB | ~100–200 ms | Already deployed |
| **B300 HBM total** | | **288 GB** | | Plenty of headroom |

**Feasibility:** VRAM-wise all four fit comfortably on a single B300 (~41
GB used out of 288 GB). **Latency-wise** Cosmos's published B300 numbers
do not yet exist — adding 200–500 ms to a 1.5 s pipeline is a real risk
that has to be measured, not assumed.

## 5. Risks

1. **License:** NVIDIA Open Model License — commercial use OK, no GPL
   conflict. ✓
2. **Hallucination on clinical content:** Cosmos is trained on
   robotics/physical-AI; medical imaging is domain-shifted. Phantom
   findings on radiographs are a known VLM failure mode. RadSlice's L2
   judge can absorb this if Cosmos output is treated as a *candidate*, not
   a verdict. Explicit false-positive controls required.
3. **FDA / SaMD:** RadSlice is not a medical device. Any clinical-workflow
   integration of a medical Cosmos variant would trigger FDA SaMD review.
   Out of hackathon scope.
4. **No published medical fine-tune:** the user's stack diagram implies a
   medical Cosmos variant exists; **it does not.** Either (a) fine-tune
   from base on a medical-imaging corpus (100K+ annotated images, weeks of
   training) or (b) wait for NVIDIA / community to release one. Don't ship
   the README claiming Cosmos is a "medical vision" model when the
   public checkpoint is general-purpose physical-AI.

## 6. Recommendation

🟡 **YELLOW — RadSlice PoC only, with attribution corrected.**

**Engage the user's own argument directly:** "Your bottleneck is latency +
determinism, not reasoning capability — Cosmos doesn't solve that." For
**prism42 voice this is correct.** Skip.

For **RadSlice**, the calculus is different: the bottleneck is
*cross-modal blind spots*, not latency, and Cosmos is a candidate vision
backbone. The PoC is cheap (~$300–500 in inference, 3–4 weeks).

**Concrete next steps:**

- **Do:** benchmark base Cosmos-Reason2-2B (or a community medical
  fine-tune if one appears) on RadSlice rc1.2's 44-task corrected-pass-rate
  set, paired against existing GPT-5.2 / Opus 4.6 numbers.
- **Don't:** integrate into prism42 voice or claim "medical vision" until a
  real medical fine-tune exists (publicly released or trained in-house).
- **Stack diagram caveat:** label as "Cosmos-Reason2-2B (general-purpose;
  medical fine-tune is planned work)" — not "Medical Vision."
- **Follow-up trigger:** if the PoC shows ≥ 15 pp absolute lift on
  RadSlice hard set, escalate to Anthropic feedback channel under the
  prism42 disclosure posture and consider a joint validation study.

---

## Sources

- https://huggingface.co/nvidia/Cosmos-Reason2-2B
- https://github.com/nvidia-cosmos/cosmos-reason2
- https://docs.nvidia.com/cosmos/latest/reason2/index.html
- https://github.com/vllm-project/vllm/releases
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
- https://verda.com/blog/nvidia-b200-and-b300-gpu-architecture-and-software-stack
