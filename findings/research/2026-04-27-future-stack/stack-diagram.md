# Future Stack — North-Star Diagram

**Status:** research / forward-looking. **Not deployed.** The current
production surface is documented in `docs/pipeline-narrative.md`.

This diagram captures the user's proposed future architecture, with two
attribution corrections from the research briefs in this directory:

1. **Cosmos-Reason2-2B** is general-purpose physical AI; the medical
   fine-tune is *user's planned work*, not a public checkpoint.
2. **Karpathy's autoresearch optimizes LLM-training `val_bpb`, not RAG.**
   The recommended nightly RAG optimizer is **DSPy GEPA** (Stanford NLP),
   not a Karpathy artifact.

## Diagram

```mermaid
flowchart TD
    User[User Medical Inquiry]
    --> RAG[NVIDIA Knowledge-Graph RAG<br/>GenerativeAIExamples reference impl]

    RAG --> Graph[nx-cugraph 26.04.00<br/>Medical Knowledge Graph<br/>GPU-resident]

    Graph --> LLM[Nemotron Nano 30B-A3B NVFP4<br/>via TensorRT-LLM 1.2.1<br/>+ Cosmos-Reason2-2B<br/>via vLLM ≥ 0.12]

    LLM --> Five[Five Adversarial Roles<br/>Defender · Attacker · Synthesizer<br/>Executor · Adjudicator]

    Five --> Output[Safe Final Response]

    Optimizer[DSPy GEPA<br/>nightly RAG optimizer<br/>Stanford NLP] -.->|tunes retrieval, ranking, synthesis prompts| RAG

    subgraph B300 ["B300 — all GPU-native"]
        Graph
        LLM
    end

    style B300 fill:#22c55e,stroke:#166534,stroke-width:3px,color:#000
    style Five fill:#eab308,stroke:#854d0e
    style Optimizer fill:#a855f7,stroke:#581c87,color:#fff
```

## Pinned versions (target state)

| Component | Version | Source |
|---|---|---|
| CUDA driver (host) | 13.2.1 | NVIDIA Blackwell Compatibility Guide |
| RAPIDS | 26.04 | rapids.ai |
| nx-cugraph | 26.04.00 (April 9, 2026) | rapidsai/nx-cugraph |
| Nemotron serving | **TensorRT-LLM 1.2.1** (NGC `release:1.2.1`) | github.com/NVIDIA/TensorRT-LLM |
| Cosmos serving | **vLLM ≥ 0.12** (Qwen3-VL stack) | github.com/vllm-project/vllm |
| Nemotron Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | huggingface.co/nvidia |
| Cosmos-Reason | `nvidia/Cosmos-Reason2-2B` (general-purpose; medical fine-tune is user-led work, not public) | huggingface.co/nvidia |
| RAG framework | NVIDIA `GenerativeAIExamples/knowledge_graph_rag` | github.com/NVIDIA/GenerativeAIExamples |
| Nightly optimizer | DSPy GEPA | dspy.ai/api/optimizers/GEPA |

## Caveats per-brief

- **nx-cugraph at 3,987 nodes is below GPU break-even.** Diagram shows the
  intent, but actual healthcraft graph size today does not justify GPU
  acceleration. See `nx-cugraph-26.04.md`.
- **Cosmos-Reason2-2B medical fine-tune does not exist publicly.** Planned
  work, not a checkpoint. See `cosmos-reason2-2b.md`.
- **Two-runtime serving on B300.** TRT-LLM 1.2.1 for Nemotron-Nano
  (NVIDIA cookbook AutoDeploy path); vLLM ≥ 0.12 for Cosmos-Reason2-2B
  (NVIDIA's official Qwen3-VL serving runtime). Sandbox-first
  cutover for the Nemotron migration. See `tensorrt-llm-on-b300.md`
  and `cosmos-reason2-2b.md`.
- **DSPy GEPA + Karpathy autoresearch — dual-credit.** The hero
  diagram caption reads "DSPy GEPA · tweaks retrieval, ranking,
  subgraph logic. Runs nightly." Karpathy's autoresearch named the
  *pattern* (LLM-training reference impl); DSPy GEPA is the
  maintained RAG implementation. See `karpathy-autoresearch.md`.

## What's already deployed (do not confuse with the diagram)

- **Live LiveKit demo:** `https://prism42-app.thegoatnote.com/prism42/livekit`
  — Opus 4.7 LLM + Parakeet STT + Fish TTS on B300, vLLM 0.20 + CUDA 12.9.
- **Fallback ElevenLabs demo:** `https://prism42-console.vercel.app/prism42-v3`
  — Opus 4.7 via Anthropic API, no B300.

The future-stack diagram is the *next* iteration. Both deployed surfaces
remain in service through the transition.
