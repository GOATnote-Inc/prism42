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
| [`tensorrt-llm-on-b300.md`](tensorrt-llm-on-b300.md) | 🟡–🟢 Yellow–Green; sandbox-first | TRT-LLM 1.2.1 wins for Nemotron-Nano-30B-A3B-NVFP4 (NVIDIA cookbook + AutoDeploy). Two-runtime split: TRT-LLM for Nemotron, vLLM for Cosmos |
| [`cosmos-reason2-2b.md`](cosmos-reason2-2b.md) | 🟡 Yellow — RadSlice yes, prism42 voice no | Cosmos is general-purpose physical AI; **vLLM is NVIDIA's official serving path**, not TRT-LLM. Best slot is RadSlice DICOM eval |
| [`karpathy-autoresearch.md`](karpathy-autoresearch.md) | ⚠️ Attribution correction | `karpathy/autoresearch` optimizes LLM-training `val_bpb`, not RAG. Diagram dual-credits "Karpathy autoresearch · DSPy GEPA" — Karpathy named the pattern, DSPy GEPA is the maintained RAG implementation |
| [`medical-fine-tune-plan.md`](medical-fine-tune-plan.md) | 📋 User-led, post-corpus | User's chosen path over BioNeMo or MedGemma: build a curated medical corpus (no Claude outputs), fine-tune Nemotron-Nano. Anthropic AUP-clean. Sketch only — assistant scopes, user owns execution |
| [`b300-bench-plan.md`](b300-bench-plan.md) | 🛠️ OODA + 4 agent teams | Operating plan for the `warm-lavender-narwhal` research pod (1× H200 141 GiB, Nebius/eu-north-1, $4.24/hr). Cost ceiling $50/session, halt-and-report on anomaly. No prod touch |
| [`medical-corpus-skeleton.md`](medical-corpus-skeleton.md) | 📂 Team D delivered | Directory tree + manifest schema + AUP-gate + eval-quarantine + physician-review log shape for the user-led medical fine-tune corpus. Hardware-agnostic; $0 to land |
| [`stack-diagram.md`](stack-diagram.md) | — | Mermaid mirror of the hero diagram with attribution corrections + runtime split notes |
| [`h200-bench-team-a.md`](h200-bench-team-a.md) | 🟢 Team A complete | Nemotron-Nano-30B-A3B BF16 on H200: cold-load 621 s, steady-state 186 ms / 50-tok @ conc=1 (~269 tok/s). NVFP4 attempt blocked on vLLM 0.20.0 FlashInfer MoE backend gap; pivoted to BF16 sibling. Apples-to-apples baseline for future B300 NVFP4 run |
| [`nvidia-voice-stack-architecture.md`](nvidia-voice-stack-architecture.md) | 🟢 Architecture lock | Synthesis of 4 research agents (Riva 2.15, Guardrails 0.21, nx-cugraph for medical KG, CUDA 13.2 reality). Aligns to `NVIDIA-AI-Blueprints/nemotron-voice-agent` reference. p95 < 1.1 s end-to-end achievable on H200 single-GPU. 2-phase plan: ship Riva NIMs today (50 min once `NVIDIA_API_KEY` populated); sequence Guardrails + KG when corpus lands |
| [`voice-5role-design.md`](voice-5role-design.md) | 🟢 Phase 2 design | Time-axis taxonomy keeping 5-role accountability under 1100 ms p95 voice budget. Maps Defender→FSM, Executor→response_gate, Synthesizer→classifier, Adjudicator→claude_critic; only NEW modules are `attacker.py` + `rule_adjudicator.py`. Avoids the orchestrator_full.py 14-20 s trap by keeping 3 roles deterministic, 1 parallel local-LLM, 1 sampled off-path Opus |

## What changed 2026-04-27 (since the first commit)

1. **BioNeMo dropped.** Researched, surfaced as biomolecular (not clinical-encounter); user agreed to drop. See `medical-fine-tune-plan.md` for the path chosen instead.
2. **vLLM brief retired in favor of TRT-LLM brief.** Two-runtime split: TRT-LLM serves Nemotron, vLLM keeps serving Cosmos (NVIDIA's official Cosmos runtime).
3. **Karpathy attribution dual-credited** in the hero diagram caption ("DSPy GEPA · tweaks retrieval, ranking, subgraph logic. Runs nightly.") — Karpathy keeps the headline (pattern lineage), DSPy GEPA cited as implementation.
4. **B300 bench plan added** for the research pod `final-gold-ox`. Four scoped agent teams with explicit outcomes, halt conditions, cost ceilings.

## Versions pinned for the future stack

| Component | Pinned | Rationale |
|---|---|---|
| CUDA | 13.2.1 | B300 SM 10.3 native |
| RAPIDS | 26.04 | April 2026 release; cu13 wheels available |
| nx-cugraph | 26.04.00 | April 9, 2026; env-var activation. RED at current graph scale (3,987 nodes) |
| Nemotron Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | Already pinned (`agents/livekit/worker.py:731`) |
| Nemotron serving | **TensorRT-LLM 1.2.1** (NGC `release:1.2.1`) | NVIDIA cookbook + AutoDeploy. Replaces vLLM 0.20 for this model. |
| Cosmos-Reason | `nvidia/Cosmos-Reason2-2B` | General-purpose physical AI. Medical fine-tune is *user's planned work*, not a public checkpoint |
| Cosmos serving | **vLLM ≥ 0.12** (Qwen3-VL stack) | NVIDIA's official path for this VLM. Not TRT-LLM |
| RAG framework | NVIDIA `GenerativeAIExamples/knowledge_graph_rag` | Reference impl |
| Nightly RAG optimizer | **DSPy GEPA** (Stanford NLP) | Active maintainership, Generic RAG Adapter. The "Karpathy autoresearch" framing names the *pattern*; GEPA is the implementation of record |

## Production guardrail

The deployed surface is canonically:

- **Live (LiveKit path):** `https://prism42-app.thegoatnote.com/prism42/livekit`
- **Fallback (ElevenLabs path):** `https://prism42-console.vercel.app/prism42-v3`

No file under `mvp/911-console-live/`, `agents/livekit/`, `infra/b300/`,
`vendor/`, or any lockfile is modified by this research dir. Any future
adoption work picks up from these briefs and lands in a separate sandbox
pod (`final-gold-ox` is the current research pod) — never mutating the
demo paths in place.
