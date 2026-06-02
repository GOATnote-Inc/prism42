# Nemotron-3-Nano-Omni — research brief (2026-04-28)

**Status**: research-only — no container swap performed at the time of this brief.
**Author**: Claude Code agent team (3 parallel Explore agents) at Brandon Dent, MD's request.
**Disposition**: SWAP DEFERRED — see §6.

## 1. What was released today

NVIDIA released `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-{BF16,FP8,NVFP4}` on 2026-04-28 as part of NVIDIA's GTC 2026 Nemotron-3 expansion.

- **Architecture**: Hybrid Mamba2-Transformer Mixture-of-Experts. 30 B total params, **3 B active per forward pass**. 128 experts, top-6 routing. 23 Mamba layers + 23 MoE layers + 6 grouped-query-attention layers.
- **Modalities**: text + image + video + audio (unified token processing). The "Omni" name means modality breadth, not parameter scale.
- **Context length**: 256 K tokens (262,144) deployable.
- **Quantizations released today**: BF16 (~62 GB), FP8 (~33 GB), **NVFP4 (~21 GB) — Hopper-compatible per NVIDIA's own technical blog**, contradicting our earlier mental model that NVFP4 was Blackwell-only.
- **License**: NVIDIA Nemotron Open Model Agreement (commercial use OK).
- **Knowledge cutoff**: 2025-06-25.

Sources:
- <https://huggingface.co/nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16>
- <https://huggingface.co/nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4>
- <https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence>
- <https://developer.nvidia.com/blog/nvidia-nemotron-3-nano-omni-powers-multimodal-agent-reasoning-in-a-single-efficient-open-model/>
- <https://blogs.nvidia.com/blog/nemotron-3-nano-omni-multimodal-ai-agents/>

## 2. Relationship to the currently-running model

The H200 at `warm-lavender-narwhal` is currently serving `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` (text-only, 30 B-A3B). Omni is the **vision/audio augmentation of the same backbone** — same active param count, same MoE shape, plus added vision/audio encoders.

- Per NVIDIA's framing: Omni and the prior text+image Nano "**coexist**." Not a strict replacement.
- For text-only inference, the underlying reasoning stack is the same family.
- For multi-modal inference, Omni adds capabilities the existing model does not have at all.

## 3. Headline benchmark numbers (NVIDIA-published)

| Task | Benchmark | Omni score |
|---|---|---|
| Document OCR | OCRBenchV2-En | 65.8 |
| Long documents | MMLongBench-Doc | 57.5 |
| Video understanding | Video-MME | 72.2 |
| Voice interaction | VoiceBench | 89.4 |
| ASR (lower=better) | HF Open ASR | 5.95 |
| GUI / screenshots | ScreenSpot-Pro | 57.8 |
| Spatial grounding | CVBench2D | 83.95 % |
| Computer use | OSWorld | 47.4 % |

Efficiency: NVIDIA cites 9.2× higher system throughput vs comparable open omni models for video reasoning, 7.4× for multi-document.

Source: <https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence>

## 4. Medical benchmark numbers — the honest gap

**NVIDIA published zero medical benchmark scores for Omni.** No HealthBench, no MedQA, no MMLU-Medical, no PubMedQA, no MedAgentBench. No medical-specialized variant (`Nemotron-Omni-Med-*` does not exist as of release).

This is the load-bearing finding for whether to swap. The published benchmarks are document/video/audio understanding tasks — not clinical reasoning.

This lane's measured baseline on `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` (HealthBench Hard, N=2, 30 examples): **`0.059 ± 0.323`**, side-by-side with Opus 4.7's published `0.196 ± 0.068` (CIs overlap). We have no Omni number to compare. A swap without first re-running the bench means we'd lose the apples-to-apples comparison we just paid for.

## 5. Serving on H200 (operational notes)

If/when we swap:

- **vLLM v0.20.0+** is required (NOT `:latest`; pinning matters).
- HF override flag: `--hf-overrides='{"architectures":["NemotronH_Nano_VL_V2"]}'`
- Audio support requires `pip install vllm[audio]` in the container — non-trivial vs the current dead-simple text-only setup.
- Cold-start: 12–18 min on H200 for a 30 B-class multimodal model.
- VRAM at NVFP4: ~21 GB weights + KV cache (manageable on 141 GiB H200 even with KV at 32 K context).
- Backout: `docker stop vllm-nemotron-omni && docker start vllm-nemotron`. The previous container is preserved unless we `docker rm` it, so the rollback path is one command. HF cache may be partially evicted under disk pressure (250 GB pod disk; both checkpoints together fit comfortably, so no real pressure).

The exact swap script is at [`scripts/swap_to_omni_h200.sh`](../../../scripts/swap_to_omni_h200.sh). Double-gated (`PRISM42_OMNI_SWAP=1` + `--commit`); refuses to run unless both signals are present.

## 6. Disposition: swap deferred

**Recommendation**: do not swap the H200 container yet. Three reasons, ranked.

1. **No medical numbers**. Swapping replaces a model we have a measured 30-example HealthBench Hard reading on with one we don't. The honest move is to first re-run the same sweep against Omni (text-only, same 30 examples, same judge endpoint) and **then** decide based on the delta.
2. **Multi-modal complexity is unused by R1**. The R1 sweep is text-only — HealthBench Hard, MedQA, MMLU-Medical, PubMedQA. The vision/audio capabilities Omni adds aren't load-bearing here. They become relevant for R2 (which would benefit) and R3 (medical fine-tune; Omni's broader perception adds surface area but also complexity).
3. **Knowledge cutoff is 2025-06**. For 2026 clinical guideline questions (e.g., 2026 ACLS, 2026 sepsis), Omni has the same lag the prior Nemotron has. Swapping doesn't fix that.

**Recommended next step**: run a paired-sweep against Omni — same 30-example clinical subset, same Triton-judge endpoint architecture (Omni judging Omni preserves the same-family-bias caveat already in our CARD), N=2 trials, same wall-clock budget as the R1 sweep. Then read the delta.

If the user wants the swap NOW regardless of the above, the script in §5 is ready. The destructive step (`docker stop vllm-nemotron`) is gated to require both `PRISM42_OMNI_SWAP=1` and `--commit`.

## 7. What this brief is NOT

- Not an authoritative claim about Omni's medical capability — NVIDIA hasn't published that data.
- Not a deployment recommendation against using Omni for multi-modal medical workflows (radiology, dermatology, dictation) — those are exactly the tasks Omni is designed for and where it's likely the right tool.
- Not an end of the line — when NVIDIA or third parties publish medical benchmark numbers, this brief should be updated and the disposition re-evaluated.
