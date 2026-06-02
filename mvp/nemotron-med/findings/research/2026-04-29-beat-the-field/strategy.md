# MedOmni — beating the field, not parity

**Date**: 2026-04-29.
**Frame** (per user): "be far superior to MedGemma and other instruct best-in-class. Don't compete by differentiating away — compete by being faster, more accurate, more reproducible."
**Source**: parallel research agent comparison matrix + decisive-win analysis.

## 1. The actual competitive bar — Claude 3.5 Sonnet, not MedGemma

| Model | Best published MedQA | Multi-modal | Long context | MedAgentBench |
|---|---|---|---|---|
| MedGemma 27B (text) | 87.7 % | no | 128 K | not tested |
| MedGemma 1.5 4B (image+text) | 64.4 % | image only | 128 K | not tested |
| OpenBioLLM-70B | ~85 % | no | 8 K | not tested |
| Med42-v2-70B | 79.1 % | no | 8 K | not tested |
| Med-PaLM-2 | 86.5 % | no | 32 K | not tested |
| Claude 3.5 Sonnet | ~92 % | image+text | 200 K | **69.67 %** (SOTA) |
| GPT-4 | 88 % | image+text | 128 K | ~70 % |
| **Nemotron-3-Nano-Omni** (target) | **measure** | **all four** | **256 K** | **measure** |

MedGemma is not a credible competitor for full-stack clinical workflow — it's 4 B image+text only, no agentic loop, no audio, no video. The real field bar is **Claude 3.5 Sonnet + GPT-4**.

## 2. Three decisive-win dimensions (where MedOmni can be **far superior**, not match)

### Dimension 1 — Multi-modal medical reasoning (longitudinal images + audio + video)

**Why it's a moat**: Omni is the only open model with native text + image + video + audio. MedGemma 1.5 is image+text only. No open competitor handles ECG audio, heart sounds, or dictation.

**Targets**:
- **Longitudinal CXR reasoning** (new benchmark to curate): MedGemma ~66 % macro-acc → MedOmni target **78–82 %**.
- **Pathology + clinical integration** (slide + labs): MedGemma 47 % F1 → MedOmni target **58–62 %**.
- **ECG classification + interpretation** (no current open SOTA): MedGemma 0 % → MedOmni target **75–80 %**.

**Build path**: Omni base + medical fine-tune on (MIMIC-CXR longitudinal pairs + PathomQA + 12-lead ECG dataset). Persona-LoRA for radiologist / pathologist / cardiologist registers.

### Dimension 2 — Long-context medical reasoning (256 K + Mamba)

**Why it's a moat**: Hybrid Mamba2-Transformer + 256 K context is unique among medical LLMs. Mamba's linear scaling at long context is exactly what multi-encounter EHR review needs; transformer-only models hit quadratic walls.

**Targets**:
- **ICU readmission prediction from full EHR** (MIMIC-IV 10–40 K-token cases): Claude 3.5 baseline ~71 % AUROC → MedOmni target **78–82 %**.
- **Multi-paper systematic review reasoning** (5 full-text PubMed papers + meta-analysis question): current SOTA ~65 % accuracy → MedOmni target **75–78 %**.

**Build path**: Omni 256 K + GraphRAG over MIMIC-IV multi-note chains + persona-LoRA "Critical Care Specialist." Reproducibility rail: citable note-span for every clinical claim.

### Dimension 3 — Agentic medical workflow (MedAgentBench)

**Why it's the strongest decisive-win bet**: MedAgentBench is public, deterministic, leaderboarded. Claude 3.5 Sonnet is at 69.67 %. Omni's RL-trained tool calling + persona-LoRA + GraphRAG-backed EHR lookup can plausibly hit 75–80 %.

**Targets**:
- **MedAgentBench full 300-task suite**: Claude 3.5 Sonnet 69.67 % → MedOmni target **76–80 %**.
- **Single-specialty subset (e.g., medication ordering)**: MedOmni target **>80 %**.

**Build path**: Omni base + MedAgentBench training-split fine-tune + persona-LoRA × 5 (ED physician, hospitalist, scheduler, pharmacist, radiologist). NeMo Agent Toolkit integration. Every EMR action logged with justification chain for med-legal audit (this is the reproducibility moat OE doesn't have).

## 3. Honest 6–12 week verdict (per the research agent)

**Can MedOmni be "far superior" in 6–12 weeks?** Yes, on these three dimensions — *if* specific conditions hold.

| Dimension | Probability of decisive win in 12 weeks | Risk |
|---|---|---|
| 1 — Multi-modal medical | 70 % | Dataset licensing (MIMIC images, PathomQA) |
| 2 — Long-context medical | 60 % | Need to confirm Omni's context efficiency vs Claude 3.5; new benchmark to construct |
| 3 — Agentic medical (MedAgentBench) | **80 %** | Tool-calling baseline strength; persona-LoRA effect size |

**Recommendation**: commit to **Dimension 3 as the guaranteed v0 win**. Most concrete, most defensible, most relevant to the user base (clinicians need reliable agentic EMR access, not just better trivia scores). Dimensions 1 and 2 are upside.

## 4. The "stand on shoulders" plan (don't reinvent)

OSS giants we leverage, with the conversion-to-reproducible pattern:

| Stand on | Convert to MedOmni |
|---|---|
| OpenAI `simple-evals` (HealthBench rubric) | pinned at SHA `ee3b0318`; primitives copied verbatim with attribution |
| NVIDIA NeMo Retriever blueprint | adapted for medical-specific embedders + persona-tagged graph |
| MedAgentBench (Stanford) | training-split fine-tune; eval on test-split with reproducibility manifest |
| Microsoft LazyGraphRAG | indexing pattern; medical-graph-specific Leiden communities |
| Karpathy autoresearch | meta-pattern; our specific autoresearch on retrieval params + persona prompts |
| DSPy GEPA | maintained library for prompt evolution; we run our pipeline through it |
| HuggingFace Transformers + datasets | model loading, eval harness; pin revision SHAs |
| vLLM | inference engine; pin container digest |

## 5. The conversion discipline — every output must be reproducible / fastest / most accurate

For every component:
- **Reproducible**: pinned digests + seed + manifest at every layer (see `2026-04-29-reproducibility/design.md`).
- **Fastest**: measure latency p50/p99 on every release; regression-gate in CI.
- **Most accurate**: rubric-graded against the canonical fixtures (tamoxifen + future cases); regression-gate in CI.

If any release misses any of the three, it doesn't ship.

## 6. Sources

- MedGemma technical report: <https://arxiv.org/html/2507.05201v4>
- MedGemma 1.5 model card: <https://developers.google.com/health-ai-developer-foundations/medgemma/model-card>
- MedAgentBench (NEJM AI): <https://ai.nejm.org/doi/full/10.1056/AIdbp2500144>
- Med-PaLM-2 (Nature Medicine): <https://www.nature.com/articles/s41591-024-03423-7>
- OpenBioLLM-70B: <https://huggingface.co/aaditya/Llama3-OpenBioLLM-70B>
- Med42-v2: <https://arxiv.org/html/2408.06142>
- Apollo: <https://arxiv.org/html/2403.03640>
- MedASR (Google): <https://research.google/blog/next-generation-medical-image-interpretation-with-medgemma-1-5-and-medical-speech-to-text-with-medasr/>
- Nemotron-3 family: <https://research.nvidia.com/labs/nemotron/Nemotron-3/>
- LV-Eval 256K (long-context): <https://openreview.net/forum?id=WQwy1rW60F>
