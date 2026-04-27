# Future Stack — Research Briefs (2026-04-27)

**Status:** Research only. Nothing in this directory is deployed. None of the
code paths in `mvp/911-console-live/` (the live demo at
`prism42-app.thegoatnote.com/prism42/livekit`) or `mvp/911-console-live/`'s
ElevenLabs fallback (`prism42-console.vercel.app/prism42-v3`) are touched by
the work scoped here. Adoption decisions stay with the user.

## Contents

| Brief | Verdict | Why |
|---|---|---|
| [`rapids-26.04.md`](rapids-26.04.md) | 🟢 Green for healthcraft + openem-corpus (cuVS); 🟡 Yellow for scribegoat2 (cuDF) | cuVS is the highest-leverage win; ~300 LOC for healthcraft integration |
| [`nx-cugraph-26.04.md`](nx-cugraph-26.04.md) | 🔴 Red at current scale | healthcraft entity graph is 3,987 nodes — below the GPU break-even (~10K). No NetworkX call sites in any repo today |
| [`vllm-cuda-13.2.1.md`](vllm-cuda-13.2.1.md) | 🟡 Yellow — sandbox-first mandatory | NVFP4 CUDA-Graph regressions on Blackwell are reported but undocumented; canary in a parallel pod before prod cutover |
| [`cosmos-reason2-2b.md`](cosmos-reason2-2b.md) | 🟡 Yellow — RadSlice yes, prism42 voice no | Cosmos is robotics/physical-AI base; medical fine-tune does NOT exist publicly. Best slot is RadSlice DICOM eval, not voice |
| [`karpathy-autoresearch.md`](karpathy-autoresearch.md) | ⚠️ Attribution correction | `karpathy/autoresearch` optimizes LLM-training `val_bpb`, not RAG. The "nightly RAG optimizer" is Yeyu Huang's derivative. Better-attributed alternative: DSPy GEPA |
| [`stack-diagram.md`](stack-diagram.md) | — | Mermaid version of the user's proposed future-stack diagram, with the Karpathy attribution corrected and pinned versions cited |

## Versions pinned for the future stack (per user)

| Component | Pinned | Rationale |
|---|---|---|
| CUDA | 13.2.1 | B300 SM 10.3 native (CLAUDE.md recent-best-practice §B300) |
| RAPIDS | 26.04 | April 2026 release; cu13 wheels available |
| nx-cugraph | 26.04.00 | April 9, 2026; env-var activation |
| Nemotron Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | Already pinned (`agents/livekit/worker.py:731`) |
| Cosmos-Reason | `nvidia/Cosmos-Reason2-2B` | Vision-language; medical fine-tune is *user's planned work*, not public |
| RAG framework | NVIDIA `GenerativeAIExamples/knowledge_graph_rag` | Reference impl |
| Nightly optimizer | DSPy GEPA (recommended) or `karpathy/autoresearch` (LLM-training pattern, not RAG) | See attribution correction |

## Production guardrail

The deployed surface is canonically:

- **Live (LiveKit path):** `https://prism42-app.thegoatnote.com/prism42/livekit`
- **Fallback (ElevenLabs path):** `https://prism42-console.vercel.app/prism42-v3`

No file under `mvp/911-console-live/`, `agents/livekit/`, `infra/b300/`,
`vendor/`, or any lockfile is modified by this research dir. Any future
adoption work picks up from these briefs and lands in a separate sandbox
pod / branch — never mutating the demo paths in place.
