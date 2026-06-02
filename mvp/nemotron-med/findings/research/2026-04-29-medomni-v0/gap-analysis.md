# MedOmni v0 — gap analysis (self-critical review)

**Date**: 2026-04-29 (afternoon).
**Purpose**: user explicitly asked "what is the v0 build missing. what needs to be added to plan for it to succeed tasks. think of far superior to MedGemma and other instruct best in class." This is an honest review of what `architecture-v2.md` lacks for that ambition level.

The v2 plan is a coherent architecture but it is **not** sufficient to deliver "far superior to MedGemma." Below are 10 missing pieces ranked by how much each one moves the needle.

## 1. The autoresearcher loop is named but not architected (HIGH priority)

The user's directive includes "autoresearcher and nx-cugraph on NVIDIA's best hardware." Yesterday's reversal back to graph-RAG covered the nx-cugraph half; the **autoresearcher** half hasn't been designed.

What's missing: a nightly loop that:

1. Samples the prior day's failed/recused queries from production telemetry
2. Re-runs them with mutated retrieval params (top-k, hop count, persona-mask filter, rerank weights)
3. Grades each variation against the rubric (using the sovereign judge)
4. Keeps the variations that improve, discards the rest
5. Commits the new params with a provenance trail (which queries justified the change)
6. CI-gates the deploy so a regression auto-rolls-back

This is the [DSPy GEPA pattern (Stanford NLP, Agrawal et al. 2025)](https://arxiv.org/html/2506.05690v3) applied to *our* pipeline params, not just prompts. Karpathy named the meta-pattern; GEPA is the maintained library; we run our specific version.

**v0.5 add**: `scripts/autoresearch_loop.py` — runs nightly on the orchestrator pod (RunPod H100), produces a daily PR with proposed param changes + rubric-delta evidence. Human reviews and merges.

## 2. Speed + accuracy targets are absent (HIGH)

The v2 plan has an acceptance threshold (rubric ≥0.80 across N=3 trials) but no quantified **speed** or **accuracy-vs-baseline** targets. "Far superior to MedGemma" is not measurable without numbers.

What's missing:

| Axis | Target for v0 (vs MedGemma 27B published) |
|---|---|
| HealthBench Hard | beat current Opus 4.7 baseline `0.196 ± 0.068`; target `0.30 ± 0.05` (relative +50%) |
| MedQA (USMLE-style) | beat MedGemma 27B's published number by ≥3 pp |
| MedAgentBench | beat published GPT-5 numbers by ≥5 pp |
| MMLU-Medical-6 | match or exceed MedGemma |
| Persona-drift FKGL violations | <2% on patient/family outputs |
| Citation-grounding failures | <5% (each cited passage must have ≥0.8 cosine to a retrieved node) |
| Latency p50 physician text-only | <500 ms (Mamba-bound at 8K context) |
| Latency p50 nurse-with-graph | <800 ms (adds graph walk + rerank) |
| Latency p50 family persona | <1.5 s (adds FKGL rail + retry) |
| Throughput on H200 NVFP4 batch=1 | >50 tok/s decode |
| Cold-start (full stack: rails + serve + retrieval) | <5 min |

**v0 add**: `findings/research/2026-04-29-medomni-v0/perf-targets.md` documenting these targets + the bench harness that measures them.

## 3. Multi-modal medical use cases are unaddressed (HIGH)

Omni supports text+image+video+audio natively. The v2 plan is text-only. **This is leaving the moat on the table.** MedGemma 4B/27B is image+text only. Audio + video are decisive Omni-only territory.

What's missing — five high-value multi-modal medical use cases:

| Modality | Use case | Why it matters |
|---|---|---|
| Image: ECG | "interpret this 12-lead, given chest pain in a 58-yo with new AF" | EM bread-and-butter; OE doesn't do images at all |
| Image: chest X-ray | "PA + lateral, dyspnea + fever, sat 89% RA" | Radiology prelim; EM physician adjunct |
| Image: dermatology | "this rash, fever, and sore throat in a 6-yo" | Pediatric EM |
| Audio: heart/lung sounds | "this S3 gallop in a 72-yo" | Bedside clinical training |
| Video: gait/seizure | "this gait pattern after fall" | Neurology adjunct |

**v0.5 add**: One multi-modal test fixture per modality, in the same HealthBench-Hard rubric format as `CLN-DEMO-TAMOXIFEN-MIRENA`. Each fixture exercises retrieval + persona-output + Omni's modality-specific encoder. Shipping one (ECG) in v0 demonstrates the architecture handles it.

## 4. Reproducibility plumbing exists in spirit, not in code (HIGH)

The v2 plan inherits the prism42 norm of "every claim → session ID → shell command." Good. But the actual artifact that carries this — a per-layer hash manifest — doesn't exist yet.

What's missing:

```
reproducibility/
  manifest-2026-04-29.yaml          # this run's pinned everything
  past-manifests/                   # rolling window
make reproduce SESSION=<id>         # single command rebuild
make freeze-snapshot                # captures current state into a manifest
make freeze-verify-all              # diffs every layer's hash vs the pinned
```

Each layer in the manifest:

```yaml
runtime:
  driver: "580.126.09"
  cuda: "13.2"
  nvidia_container_toolkit: "1.17.x"
container_digests:
  vllm: "sha256:abc..."
  triton_server: "sha256:def..."
  llama_guard: "sha256:..."
models:
  omni_nvfp4: { id: "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4", revision: "<sha>" }
  nv_embed_v2: { id: "nvidia/NV-Embed-v2", revision: "<sha>" }
  llama_guard_3: { id: "meta-llama/Llama-Guard-3-8B", revision: "<sha>" }
corpus:
  openem: { sha: "<commit-sha>", file_count: 370 }
  pubmed_oa_snapshot: "2026-04-29"
graph_artifacts:
  lazygraph_v1: { manifest_sha: "<sha>", node_count: 2034, edge_count: 11823, leiden_resolution: 0.5 }
eval:
  rubric_version: "CLN-DEMO-TAMOXIFEN-MIRENA-v1"
  judge_model: "Llama-3.1-Nemotron-70B-Reward-HF"
  judge_revision: "<sha>"
  scoring_math_version: "openai/simple-evals@ee3b0318"
sampling:
  seed: 42
  temperature: 0.0  # for reproducibility
  max_tokens: 1024
```

**v0 add**: `scripts/freeze_snapshot.py` and `scripts/freeze_verify_all.py` + the manifest schema.

## 5. Closed-loop testing is partial (MEDIUM-HIGH)

Today's testing flow: I author scripts → user authorizes → I SSH-run → read artifacts → grade. The loop runs but it's manual and depends on me staying in the conversation.

What's missing:

- A `make ci-medomni` target that runs end-to-end on the deployed pods, regardless of Claude/me being present.
- Triggered on every commit to the architecture branch (or on a cron from the orchestrator pod).
- Halts on rubric drop, FKGL violation, citation-grounding failure rate >5%, or latency p99 regression.
- Posts a one-line summary to a single file the user can `cat` to see CI state.

**v0 add**: `Makefile` target `ci-medomni` and the orchestrator-side cron job (described in §6).

## 6. The orchestrator role is named but not implemented (MEDIUM)

v2 says "Claude Code (headless) or OpenClaw direct on RunPod H100." That's a hand-wave. What does it actually do?

What's missing:

- A small Python/Bash service running on the RunPod H100 that:
  - Polls the H200 + voice-H100 GPU/container state every 60s
  - Maintains the LazyGraphRAG index freshness (rebuilds when corpus SHA changes)
  - Runs the nightly autoresearch loop (§1)
  - Triggers `ci-medomni` on every architecture-branch commit
  - Posts a one-line state summary to `/tmp/medomni-orchestrator-state.txt` over SSH
- This is not Claude Code interactive; it's a daemon.

**v0.5 add**: `scripts/orchestrator/medomni_supervisor.py` + systemd/tmux launcher.

## 7. The "audit-trail product" claimed in v1 strategy is not built (MEDIUM)

The strategic-positioning section of v2 calls out reproducibility + audit-trail as a wedge. But the user-facing surface for that wedge — what a hospital sees when it audits a query — doesn't exist.

What's missing — for every patient-facing query:

- A "session card" at `results/medomni-sessions/<session-id>.json`:
  - patient query (PHI-redacted)
  - persona used
  - retrieval hits (node IDs + scores)
  - reranked subgraph
  - generated response
  - citations with cosine confidence
  - rails passed/failed (FKGL, jargon-blacklist, Llama-Guard-3, citation-grounding)
  - judge verdict (rubric items met)
  - manifest sha (link to reproducibility/manifest-<date>.yaml)
- A read-only viewer (`scripts/session_inspector.py session-id`) that any reviewer can use.

**v0 add**: session-card schema + write path; `session_inspector.py` viewer.

## 8. Cost-per-query observability is missing (MEDIUM)

Critical for the EM-residency / academic-hospital pilot pitch. Hospitals will ask "how much does this cost per query at scale?"

What's missing:

- Per-session token-count log (input + output, per persona)
- GPU-second log (idle vs active during the session)
- Daily aggregate: ($ for compute) / (number of queries served) / (rubric mean) → unit economics
- This is also what surfaces the "I'm being charged $100/day on RunPod" question structurally — a daily invoice equivalent.

**v0 add**: `scripts/cost_per_query.py` + a daily aggregate that lands in `results/economics/`.

## 9. The first-100-users plan is absent (MEDIUM)

For "more users" (per the user's frame) to be real, MedOmni needs an early-pilot path. The v2 plan says "EM residency + academic hospital pilot" but doesn't say how to get the first 5 users to first 100.

What's missing:

- Recruitment plan: which residency program, which contact, what's the v0 demo
- IRB / data-use shape: what data does the hospital give (none, in pilot — model is read-only knowledge-base, no PHI flows in)
- Onboarding: how does a nurse open it on shift? (Web app on the hospital wifi? iPad kiosk in the break room? Slack/Teams plugin?)
- Feedback loop: how does a resident flag a wrong answer that the autoresearcher uses as training signal

**v1 add**: a 1-page pilot-deployment spec. Not architecture; product. But it's the gating constraint on every architecture choice — single-tenant vs multi-tenant, auth model, etc.

## 10. Persona drift and clinical-jargon detection is FKGL-only (LOW-MEDIUM)

v2's persona-output rail uses Flesch-Kincaid Grade Level + a forbidden-jargon blacklist. That catches readability drift but not other failure modes:

- Empathy regression: "your father has likely died" is grade-3 readable but tonally wrong
- Cultural mismatch: assumes the listener speaks English at native fluency
- Decision-paternalism: "you must" / "you should" in patient-facing answers
- False reassurance: "this is probably nothing" in a context that warrants escalation
- Premature closure: gives a single-diagnosis answer when DDx is required

What's missing — five additional rail types:

1. Empathy-classifier rail (small Llama-Guard-3-8B variant or fine-tuned)
2. Cultural-fluency rail (multilingual / English-second-language detection)
3. Decision-register rail (patient-facing must use SDM, not directive)
4. False-reassurance rail (escalation thresholds — anything matching red-flag patterns must surface them)
5. DDx-presence rail (if symptom-cluster suggests >1 condition, response must list ≥3 differentials)

**v0.5 add**: rail catalog + per-rail unit tests.

---

## Priority ranking and v0 scope

If we ship v0 in 7 days from today (2026-04-29 → 2026-05-06), the must-haves are:

- §1 autoresearcher (architected even if not yet running)
- §2 speed + accuracy targets (numerical, written down)
- §4 reproducibility manifest (skeleton + one captured snapshot)
- §5 closed-loop CI (`make ci-medomni`, runs end-to-end)
- §7 session card (write path + inspector)
- §10 persona-drift rail catalog (designed; one rail implemented)

Defer to v0.5 (week 2):

- §3 multi-modal use cases (one fixture, ECG)
- §6 orchestrator daemon (one-shot manual replacement OK for v0)
- §8 cost-per-query (basic logging only)

Defer to v1 (week 3-4):

- §9 first-100-users plan (product side, not architecture)
- §3 remaining multi-modal use cases (chest X-ray, dermatology, audio)

This is the actual v0 punch list. The v2 architecture document is the *target state*; this gap analysis is the *delta to ship by 2026-05-06*.

## Next concrete steps (immediately)

1. Create `findings/research/2026-04-29-medomni-v0/perf-targets.md` with the §2 numbers.
2. Create `reproducibility/manifest-template.yaml` with the §4 schema.
3. Create `scripts/freeze_snapshot.py` and `scripts/freeze_verify_all.py` with the §4 logic.
4. Add a `Makefile` target `ci-medomni` that wires the closed-loop.
5. Wait for the three parallel agents (Omni capability brief / beat-MedGemma / reproducibility patterns) to land, then incorporate their substance.
