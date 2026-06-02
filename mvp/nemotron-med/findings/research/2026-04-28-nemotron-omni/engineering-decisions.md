# Nemotron-3-Nano-Omni — engineering decisions for our medical lane

**Date**: 2026-04-28 (afternoon, after Omni release).
**Status**: synthesis of three parallel research agents (serving / routing / RAG-graph).
**Audience**: future-me + Brandon Dent, MD before pulling the swap trigger.
**Verification posture**: every concrete recommendation traces to a URL the source agents cited; load-bearing claims are flagged "verified" or "uncertain" — the Karpathy / Glasswing / Omni audits taught us that under-claim beats over-claim.

This brief makes three concrete decisions and tells you what to defer.

---

## Decision 1 — vLLM flags for the H100 A/B serve

The starting flag set in `scripts/bench_omni_alongside.sh`:

```
--model nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4
--hf-overrides='{"architectures":["NemotronH_Nano_VL_V2"]}'
--trust-remote-code
--tensor-parallel-size 1
--max-model-len 16384
--max-num-seqs 32
--max-num-batched-tokens 12288
--gpu-memory-utilization 0.80
--kv-cache-dtype fp8
--enable-chunked-prefill
--enable-prefix-caching
```

**Why these specific values** (verified against the [vLLM Nemotron-3-Nano recipe](https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html)):

- `--max-model-len 16384` — HealthBench Hard prompts top out around 4–6K input + 768 output. 16K leaves headroom without paying for 256K KV reservation we don't use.
- `--kv-cache-dtype fp8` — recipe explicitly recommends fp8 KV cache for the FP8/NVFP4 model variants. Cuts the 6 GQA layers' KV footprint 4× vs BF16.
- `--gpu-memory-utilization 0.80` — H100 is 80 GiB, NVFP4 weights are ~21 GB; 0.80 leaves ~64 GB for KV + activations. Bump to 0.85 if profiling shows headroom.
- `--enable-chunked-prefill` — default in vLLM V1 but explicit-on for clarity.
- `--enable-prefix-caching` — vLLM 0.20+ auto-manages Mamba SSM state and conv1d state separately under prefix caching. No separate Mamba-cache flag needed.

**Flags I'm explicitly NOT including yet** (need verification):

- `--mamba-block-size 128` — Agent A cited it but I couldn't verify the flag name in vLLM 0.20 release notes. Will add once confirmed.
- `--async-scheduling` — same. Cited but unverified.

**Watch list (foot-guns from the agents' digging)**:

- NVFP4 + CPU weight offload has crashed on consumer Blackwell ([vLLM #38718](https://github.com/vllm-project/vllm/issues/38718)). H100 is unaffected, but DO NOT use `--cpu-offload-gb`.
- Mamba SSM state corruption at block wrap-around in fp32 ([vLLM #27264](https://github.com/vllm-project/vllm/issues/27264)) — fp8 / auto state dtype is safe.
- vLLM ≥ 0.20.0 explicitly required (NOT `:latest`).

## Decision 2 — ⚠️ SUPERSEDED 2026-04-29 — see [`../2026-04-29-graph-rag-rethink/synthesis.md`](../2026-04-29-graph-rag-rethink/synthesis.md)

> **Reversed.** The user pushed back on this call and was right. The "10K-node threshold" came from a paper whose evaluation was bias-corrected the next month (arXiv:2506.06331). LazyGraphRAG indexing costs 0.1 % of full GraphRAG — no cost barrier at 2 K nodes. Medical multi-hop + provenance + hallucination resistance favor graph-augmented dense retrieval. The new architecture is LazyGraphRAG-shaped, NVIDIA-primitive-aligned, target p50 ~50 ms closed-loop. See the v2 brief.

> Original Decision 2 text preserved below for audit. Decisions 1 (vLLM flags) and 3 (expert routing) still stand.

### Skip graph-RAG at our scale; embrace NV-Embed-v2 + FAISS + 256K context

For the R2 retrieval rewrite, we drop the graph-walk plan and go context-stuffing-first. Three reasons, sourced from Agent C:

1. **At 2K KG nodes, dense retrieval beats graph-walks.** Per the [GraphRAG when-to-use analysis (arXiv 2506.05690)](https://arxiv.org/html/2506.05690v3), graphs earn their keep at 10K+ nodes with rich relational structure, not 2K medical-condition cards.
2. **Omni's 256K context lets us inline the relevant slice.** OpenEM 370 conditions × ~3K tokens = ~1.1M total — too big for one shot. But top-50 condition cards via NV-Embed-v2 = ~50K tokens, well under 256K. The Jamba-Instruct precedent ([LlamaIndex blog](https://www.llamaindex.ai/blog/jamba-instruct-s-256k-context-window-on-llamaindex)) shows long-context models retrieve 100 chunks vs traditional RAG's few.
3. **Mamba2's failure mode is state saturation, not "lost in the middle."** Per the [Stuffed Mamba paper (OpenReview cu2CT2VAvs)](https://openreview.net/forum?id=cu2CT2VAvs) and [ReMamba (arXiv 2408.15496)](https://arxiv.org/html/2408.15496v1): Mamba2 fails to forget when context exceeds capacity and degrades distant info. Mitigation: place high-priority retrieved chunks (red flags + differentials) at the **start AND end** of the context window, not middle.

**v0 → v1 → v2 retrieval upgrade path** (revised from the original R2 plan):

| Version | What ships | Validation |
|---|---|---|
| v0 (now) | `KeywordRetriever` in `mla/retrieval.py` — alias + ICD-10 substring match. Zero deps. | unit-tested only |
| v1 | NV-Embed-v2 + FAISS over OpenEM 370 (~1M tokens corpus). Top-10 condition cards inlined into 32K context. | BLEU/ROUGE on 50-question medical QA holdout |
| v2 | Top-50 inlining (~50K tokens, well under 256K) + image retrieval (BiomedCLIP or NeMo Embed VL) for ECG/chest-X-ray when prompt mentions them. | recall@5 on a held-out OpenEM lookup set |
| v3 (deferred) | Audio retrieval (Korotkoff, dictation). Requires speech-to-text + audio embeddings; uncertain timeline. | — |

**Citation-grounding rail** (replaces the originally-planned "must cite a KG node-id" rail). Per [NeMo Guardrails fact-checking docs](https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/guardrail-catalog/fact-checking.html): for each cited passage in the model's output, verify it has ≥0.8 cosine similarity to the retrieved chunks. Pair with a string-match fallback. The foot-gun is hallucinated cross-card synthesis ("dyspnea + chest pain" appears in 15 cards; the model confidently cites a passage that synthesizes across two but doesn't exist verbatim) — see [Nature npj Digital Medicine on long-context medical RAG hallucination](https://nature.com/articles/s41746-025-01651-w).

## Decision 3 — On 128 experts × top-6 routing: probe before fine-tuning

Agent B's research surfaced a credible action plan that's cheaper than the originally-planned full medical LoRA. Order of operations:

1. **Don't full-LoRA on the dense backbone yet.** With our small medical training set (~10K examples), retraining 128 experts risks catastrophic forgetting on general reasoning.
2. **EASY-EP expert pruning** ([arXiv 2504.06792](https://arxiv.org/html/2504.06792)) on a small calibration set (10–20 medical samples) to identify the top 32–64 experts that consistently activate on clinical content. Reported 2.99× throughput gain at retained accuracy. Production-ready.
3. **Router-only fine-tune** (frozen experts) on MedQA + HealthBench-train (~200 examples). Per the [Med-MoE precedent (arXiv 2404.10237)](https://arxiv.org/html/2404.10237v2). Parameter-efficient; avoids touching expert weights.
4. **Self-consistency voting on judge calls** — top-6 introduces inter-expert noise; sample routing 3× per judge call, majority-vote. Mitigates noise on medical reasoning where consistency matters.
5. **Log routing on 100 sample calls** via vLLM hooks ([RFC #36998](https://github.com/vllm-project/vllm/issues/36998)) for interpretability — which experts fire on "diagnostic reasoning," "drug interaction," "differential diagnosis." Informs future fine-tuning.

**Header-number claim from Agent A, verified against [the Nemotron-3-Nano technical report](https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Nano-Technical-Report.pdf) and the [HF blog](https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence)**: the **3B active params figure already includes the top-6 factor**. Don't multiply by 3 again. (This was a real risk: in some MoE write-ups the active figure is per-expert × top-k.)

## Open questions I won't decide solo

- Whether to actually swap the H200 to Omni or A/B on H100 first. The brief at `brief.md` recommends A/B; this engineering doc agrees. The script `scripts/bench_omni_alongside.sh` is ready to run on user's `--commit + PRISM42_OMNI_AB=1`.
- Whether to invest the ~$50–100 in router-only fine-tuning (decision 3 step 3) before R2's RAG ships, or after. Cheaper to ship RAG first and measure where retrieval recall is hurting; specialize routing only if data justifies it.

## What's NOT in scope of this brief

- B300 / NVFP4-on-Blackwell perf characterization (Agent A correctly flagged that NVFP4 is Hopper-compatible per NVIDIA's blog, contradicting our earlier mental model — our two pods are Hopper, so NVFP4 IS available to us).
- TRT-LLM 1.2.x compat for Omni — uncertain, deferred to separate research.
- NIM container availability for Omni — agents could not confirm; vLLM is the path tonight.

## Sources index (for verification)

vLLM-side:
- vLLM Nemotron-3-Nano recipe: <https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html>
- Hybrid KV cache manager design: <https://docs.vllm.ai/en/latest/design/hybrid_kv_cache_manager/>
- vLLM observation plugin RFC: <https://github.com/vllm-project/vllm/issues/36998>
- vLLM #38718 (NVFP4 + CPU offload crash): <https://github.com/vllm-project/vllm/issues/38718>
- vLLM #27264 (Mamba SSM state corruption): <https://github.com/vllm-project/vllm/issues/27264>

Architecture-side:
- Nemotron-3-Nano technical report: <https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Nano-Technical-Report.pdf>
- HF blog on Omni: <https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence>
- NVIDIA dev blog on Omni: <https://developer.nvidia.com/blog/nvidia-nemotron-3-nano-omni-powers-multimodal-agent-reasoning-in-a-single-efficient-open-model/>
- Mamba2 long-context state saturation: <https://openreview.net/forum?id=cu2CT2VAvs>
- ReMamba (long-sequence degradation): <https://arxiv.org/html/2408.15496v1>

RAG-side:
- GraphRAG when-to-use analysis: <https://arxiv.org/html/2506.05690v3>
- Jamba-Instruct 256K context retrieval: <https://www.llamaindex.ai/blog/jamba-instruct-s-256k-context-window-on-llamaindex>
- Lost in the Middle (TACL 2024): <https://aclanthology.org/2024.tacl-1.9/>
- Long-context medical RAG (Nature npj Digital Medicine): <https://nature.com/articles/s41746-025-01651-w>
- NeMo Guardrails fact-checking: <https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/guardrail-catalog/fact-checking.html>

MoE-side:
- EASY-EP domain-specific expert pruning: <https://arxiv.org/html/2504.06792>
- Med-MoE (clinical MoE precedent): <https://arxiv.org/html/2404.10237v2>
- Domain-Expert-Guided Hybrid MoE for medical AI: <https://arxiv.org/html/2601.17977>
- Expert Choice Routing: <https://arxiv.org/pdf/2202.09368>
