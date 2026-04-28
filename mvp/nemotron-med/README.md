# prism42-nemotron-med

**Sovereign NVIDIA medical-LLM stack on Brev Hopper GPUs. Private. Air-gapped from the prism42 production surface.**

> **Hackathon visibility**: this work is mirrored at `mvp/nemotron-med/` on branch
> `nemotron-med-hackathon` of the public `prism42` repo, exposed for judging via
> [PR #11](https://github.com/GOATnote-Inc/prism42/pull/11). Production surface
> `prism42-console.vercel.app/prism42-v3` is unchanged. PR is intentionally
> not merged to main; production deploys remain on the user's promoted commit.

A demonstration that GOATnote can serve, judge, evaluate, and (round 3) fine-tune a frontier NVIDIA-stack medical LLM end-to-end on its own GPUs — with zero cloud LLM API keys in any code path.

## What's running

| Layer | Component | Status |
|---|---|---|
| Inference | vLLM 0.x serving NVIDIA Nemotron on H200 (TRT-LLM is the post-hackathon polish path; vLLM is the judging-tonight path) | **R1 live** |
| Base model | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` — NVIDIA's latest Nemotron-3 MoE family (3B active params, BF16 on Hopper; sister to the Blackwell-only NVFP4 variant on the B300 prod pod) | **R1 live** |
| Judge | Same Nemotron-3-Nano endpoint (same-family bias documented in CARD as a limitation; Reward-model judge on H100 is the R2 sovereign-judge polish) | **R1 live** |
| RAG | NV-Embed-v2 + nx-cugraph over OpenEM-expanded medical KG | R2 scaffold |
| Guardrails | NeMo Guardrails 0.21+ Colang 2.0 + Llama-Guard-3-8B, all local | R2 scaffold |
| Specialization | NeMo Framework PEFT LoRA → `Nemotron-3-Nano-30B-Med` | R3 (post-judging) |

## What ships in this commit

- `scripts/sovereign_bench.py` — drop-in sovereign replacement for the Opus-4.7 path. Posts to OpenAI-compatible local endpoints; 401 / 403 / 404 halt loudly per the judge-401-silent-zero rule.
- `mla/judges/triton.py` — sovereign chat-rubric judge with localhost-only enforcement, JSON-parse retry, audit log.
- `mla/judges/reward.py` — sovereign Reward-model judge via FastAPI shim (R1 spare, R2 primary).
- `scripts/serve_trtllm_h200.sh` + `scripts/serve_judge_h100.sh` — NIM-first deploy scripts for the post-hackathon polish path.
- `scripts/preflight.sh` — six refuses-to-proceed gates: HF token, serve, judge, GPU, no prod-URL leak, public prism42 freeze intact.
- `scripts/run_demo.sh` — orchestrator: preflight → 1-example smoke → READ-the-JSON gate → N-trial paired sweep.
- `corpus/clinical_subset.yaml` — 30-example stratified HealthBench Hard pin (seed=42), the same subset the public prism42 Opus 4.7 baseline (`0.196 ± 0.068`, N=3) was scored on.

## Quickstart (replication on the existing pods)

```bash
# 1. open the laptop-side ssh tunnel to the running H200 vllm-nemotron
ssh -fN -L 8000:127.0.0.1:8000 warm-lavender-narwhal
curl -s http://127.0.0.1:8000/v1/models | jq -r .data[0].id
# → nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16

# 2. clone the simple-evals upstream pin (one-time)
git clone --depth 1 https://github.com/openai/simple-evals.git third_party/simple-evals
git -C third_party/simple-evals fetch --depth 1 origin ee3b0318d8d1d9d72755a4120879be65f7c07e9e
git -C third_party/simple-evals checkout ee3b0318d8d1d9d72755a4120879be65f7c07e9e

# 3. run the sovereign sweep (N=2 trials × 30 examples ≈ 100 min)
.venv/bin/python scripts/sovereign_bench.py \
  --manifest corpus/clinical_subset.yaml \
  --serve-url http://127.0.0.1:8000/v1 \
  --serve-model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --judge-url  http://127.0.0.1:8000/v1 \
  --judge-model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --n 30 --trials 2 --max-tokens 768 \
  --out results/r1-pilot/healthbench-hard-n30.json
```

A score card lands at `results/r1-pilot-<date>/CARD.md` with paired-design CI vs the published Opus 4.7 baseline.

## Hardware

- `prism-mla-h100` — Hyperstack H100 80 GiB, montreal-canada-2, ID `x3rytha2l`. Idle tonight; reserved for R2 sovereign judge / R3 PEFT LoRA.
- `warm-lavender-narwhal` — Nebius H200 141 GiB, eu-north1, ID `pdlpt96nl`. Hot — the running vllm-nemotron container is what every benchmark in this repo speaks to.

Both Hopper (compute_cap 9.0). NVFP4 is Blackwell-only (B300 prod pod) and is **not** used here. BF16 is the format on H200; fp8 is the planned R1.5 polish for higher throughput.

The voice-freeze H100 in the public-repo `findings/voice/freeze-cert*.md` is **distinct hardware** — same SKU, different pod, different region, different role. This repo never ssh's into it.

## Sovereignty by construction

`grep -rE "(OPENAI_API_KEY|ANTHROPIC_API_KEY)" --include="*.py" mla/judges/ scripts/sovereign_bench.py` returns zero matches. The pre-commit hook blocks any future addition outside the legacy paths flagged for refactor (see `.pre-commit-config.yaml`).

A runtime check confirms the import path doesn't transitively pull either SDK:

```python
import sovereign_bench
assert "anthropic" not in sys.modules and "openai" not in sys.modules
```

## Isolation contract

See [`CLAUDE.md`](./CLAUDE.md) §1 — the eight non-negotiable do-not-touch zones absorbed from the audit of the public surface. Every commit is hash-checked against the public repo's HEAD + worktree-diff to verify the freeze still holds. `make freeze-baseline` captures the baseline; `make freeze-verify` diffs.

Provenance: derived from `github.com/GOATnote-Inc/prism42` HEAD `e02e62dd` on 2026-04-28 via squash-import (no git history). Only the medical-LLM eval harness was lifted; voice / LiveKit / Vercel / ElevenLabs / B300 surfaces stayed in the public repo per its own freeze posture.

## What this is NOT

- Not a fork of public prism42 (no shared history, no shared deployment surface).
- Not running on the production B300 pod.
- Not pinning to the prod `Nemotron-3-Nano-30B-A3B-NVFP4` weights (NVFP4 is Blackwell-only; BF16 is the Hopper sister).
- Not using any cloud LLM API key. The only credentials in this repo's `.env.example` are HF read-only token + NGC registry token.

## Citation & Acknowledgements

Every framework, paper, and person below shaped this work. License URLs and identifiers given where they exist; warm thanks given where the contribution is more diffuse than a license can capture. If something is uncited and should be, that omission is unintentional — please open an issue on [PR #11](https://github.com/GOATnote-Inc/prism42/pull/11).

### How to cite this work

```bibtex
@misc{prism42-nemotron-med-2026,
  author       = {Dent, Brandon and {prism42 contributors}},
  title        = {{prism42-nemotron-med}: a sovereign {NVIDIA} medical-{LLM} stack on {Brev} {Hopper} {GPUs}},
  year         = {2026},
  month        = apr,
  howpublished = {GitHub PR},
  url          = {https://github.com/GOATnote-Inc/prism42/pull/11}
}
```

Machine-readable form: [`CITATION.cff`](./CITATION.cff).

### People

- **Brandon Dent, MD** — author and physician-in-loop. Owns the OpenEM corpus design, the GEDP harness, and every clinical fixture under `corpus/clinical-demo/`.
- **Prithvi Rajasekaran (Anthropic)** — the generator-evaluator separation lever from ["Harness design for long-running apps"](https://www.anthropic.com/engineering/harness-design-long-running-apps) (2026-03-24, per public prism42's `CLAUDE.md` §10 attribution). The sovereign judge architecture in `mla/judges/triton.py` and `mla/judges/reward.py` realizes that separation.
- **Anthropic** — Claude Opus 4.7, the published baseline this lane benchmarks against (HealthBench Hard `0.196 ± 0.068`, public `prism42` baseline 2026-04-22). [Claude Code](https://code.claude.com), the harness this codebase was built with — its skills, hooks, [agent teams](https://code.claude.com/docs/en/agent-teams), and [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview) primitives shaped `mla/judges/`, `scripts/preflight.sh`, and the verify-then-claim discipline throughout. The "Glasswing"-shaped agent-team playbook the user formalized at `prism42/.claude/skills/glasswing-discipline/` draws on Anthropic engineering writing — the [long-running-apps harness post](https://www.anthropic.com/engineering/harness-design-long-running-apps), the [Managed Agents engineering post](https://www.anthropic.com/engineering/managed-agents), and the published work of Anthropic's safety, safeguards-engineering, and red-team groups. The isolation contract (`CLAUDE.md` §1) and the cloud-LLM-key-leak pre-commit hooks (`scripts/hooks/no_cloud_llm_keys.sh`) are precautionary postures downstream of theirs.
- **OpenAI `simple-evals` authors** — the HealthBench Hard rubric grader logic. `scripts/_healthbench_grader_bridge.py` is a stdlib-only copy of three primitives with verbatim attribution comments and the upstream pinned at SHA `ee3b0318` so drift is caught at import. MIT, © 2024 OpenAI.
- **NVIDIA Nemotron, NeMo, and RAPIDS teams** — the model weights, the inference and training runtimes, and the graph-acceleration stack that everything serves on.
- **vLLM team (UC Berkeley Sky Lab)** — PagedAttention serving made this run in BF16 on a single H200 with KV headroom to spare. Kwon et al., *Efficient Memory Management for Large Language Model Serving with PagedAttention*, SOSP 2023, [arXiv:2309.06180](https://arxiv.org/abs/2309.06180).
- **NetworkX maintainers** (Aric Hagberg, Dan Schult, Pieter Swart) — the graph library underneath the medical KG. *Exploring Network Structure, Dynamics, and Function using NetworkX*, SciPy 2008.
- **Brev / Hyperstack / Nebius engineers** — Hopper GPU access on demand. Without these substrates, "sovereign on our own NVIDIA hardware" would have stayed a slide.

### Components & upstream work

Grouped by role; license + canonical URL given for each. Where a paper exists and the citation is verified, it is included; where it is not, the URL is the citation.

#### Models
- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` — primary serve (this run). NVIDIA Open Model License. <https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16>
- `nvidia/Llama-3.1-Nemotron-70B-Instruct-HF` and `…-Reward-HF` — R1.5 / R2 scaffold targets. NVIDIA + Llama 3.1 Community License.
- `meta-llama/Llama-Guard-3-8B` — R2 sovereign guardrails backend. Llama 3.1 Community License.
- `nvidia/NV-Embed-v2` — R2 retrieval embedding. NVIDIA Open Model License.
- Foundational: Llama-3 (Dubey et al. 2024, [arXiv:2407.21783](https://arxiv.org/abs/2407.21783)); LoRA (Hu et al. 2021, [arXiv:2106.09685](https://arxiv.org/abs/2106.09685)); Transformer (Vaswani et al. 2017, [arXiv:1706.03762](https://arxiv.org/abs/1706.03762)).

#### Inference & serving
- **vLLM** — Apache-2.0. <https://github.com/vllm-project/vllm>
- **TensorRT-LLM** — Apache-2.0. NVIDIA. <https://github.com/NVIDIA/TensorRT-LLM>
- **Triton Inference Server** — BSD-3-Clause. NVIDIA. <https://github.com/triton-inference-server/server>
- **NVIDIA NIM** — proprietary platform; Apache-2.0 components inside. <https://build.nvidia.com>
- **NeMo Framework** — Apache-2.0. NVIDIA. <https://github.com/NVIDIA/NeMo>
- **NeMo Curator** — Apache-2.0. NVIDIA. <https://github.com/NVIDIA/NeMo-Curator>
- **NeMo Guardrails** (Colang 2.0) — Apache-2.0. NVIDIA. <https://github.com/NVIDIA/NeMo-Guardrails>
- **TensorRT Model Optimizer (`modelopt`)** — Apache-2.0. NVIDIA. <https://github.com/NVIDIA/TensorRT-Model-Optimizer>

#### Evaluation
- **`openai/simple-evals` @ `ee3b0318…`** — MIT, © 2024 OpenAI. Verbatim primitives copied with attribution into `scripts/_healthbench_grader_bridge.py`. <https://github.com/openai/simple-evals>
- **HealthBench Hard** — `Tonic/Health-Bench-Eval-OSS-2025-07` on Hugging Face (Apache-2.0 via simple-evals). Pinned in `corpus/pins/healthbench-hard-1000.yaml`. <https://huggingface.co/datasets/Tonic/Health-Bench-Eval-OSS-2025-07>
- **MedQA** — Jin et al., *What Disease does this Patient Have? A Large-scale Open Domain Question Answering Dataset from Medical Exams*, [arXiv:2009.13081](https://arxiv.org/abs/2009.13081). <https://github.com/jind11/MedQA>
- **PubMedQA** — Jin et al., EMNLP 2019. <https://pubmedqa.github.io>
- **MedAgentBench** — [arXiv:2501.14654](https://arxiv.org/abs/2501.14654). <https://github.com/stanfordmlgroup/MedAgentBench>

#### Graph & retrieval
- **NetworkX** — BSD-3-Clause. Hagberg, Schult, Swart, SciPy 2008. <https://networkx.org>
- **nx-cugraph / cuGraph (RAPIDS)** — Apache-2.0. NVIDIA. <https://github.com/rapidsai/cugraph>
- **FAISS** — MIT. Johnson, Douze, Jégou, *Billion-Scale Similarity Search with GPUs*, IEEE Transactions on Big Data, 2019. <https://github.com/facebookresearch/faiss>
- **sentence-transformers** — Apache-2.0. Reimers & Gurevych, *Sentence-BERT*, EMNLP 2019. <https://github.com/UKPLab/sentence-transformers>

#### Medical corpus
- **OpenEM corpus** (370 conditions) — by GOATnote, the org behind this work. Apache-2.0 / CC-BY tier1 (PubMed OA, WHO, CDC). Physician reviewers credited per condition file's `reviewed_by:` frontmatter. <https://github.com/GOATnote-Inc/openem-corpus>

#### Tooling (quietly load-bearing)
- **httpx** (BSD-3-Clause), **PyYAML** (MIT), **pytest** (MIT), **Ruff** (MIT, Astral), **detect-secrets** (Apache-2.0, Yelp), **pre-commit** (MIT). Without these the sovereign path would not be testable from a laptop in a coffee shop.

### Note on Karpathy / DSPy / GEPA

The public `prism42` repo's architecture diagram (`assets/prism42-medical-rag.png`, root `README.md`) names a "Karpathy autoresearch" RAG loop. Per the public-repo brief at `findings/research/2026-04-27-future-stack/karpathy-autoresearch.md`, that framing is an attribution correction in flight: Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) (2026-03) is an agent-driven nightly experiment loop for **ML training**, not RAG. The maintained RAG-native counterpart is [GEPA](https://github.com/gepa-ai/gepa) ("Reflective Prompt Evolution," Agrawal et al. 2025), which integrates with [DSPy](https://github.com/stanfordnlp/dspy) at Stanford NLP. Karpathy named the pattern; GEPA + DSPy are the maintained implementations. `mvp/nemotron-med` does not directly use either — its R2 retrieval scaffold is a `KeywordRetriever` plus an NV-Embed-v2 + FAISS stub (`mla/retrieval.py`) — so the credit lives in the public root `README` next to the diagram, not here.

#### Compute
- **Brev** — Hopper GPU access on demand, Hyperstack and Nebius substrates. <https://www.brev.dev>
- **NVIDIA H200 / H100** — the silicon that purred during the sweep.

### What this work does not vendor

This repo redistributes no model weights, no HealthBench Hard data, and no `simple-evals` source code. Models pull from Hugging Face under their own licenses at runtime. `simple-evals` is fetched at the pinned SHA on first run (`third_party/simple-evals/`, gitignored). The corpus pin is a manifest, not the data. License notices accompanying the verbatim primitives in `scripts/_healthbench_grader_bridge.py` are kept intact.
