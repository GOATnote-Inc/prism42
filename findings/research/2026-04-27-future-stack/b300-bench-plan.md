# B300 Bench Plan — `final-gold-ox` (OODA + agent teams)

**Date:** 2026-04-27 · **Pod:** `final-gold-ox` (NVIDIA B300,
288 GiB HBM3E, 30 vCPU, 275 GiB RAM, Helsinki / Verda, $7.91/hr) ·
**Status:** Deploying as of session start; SSH-ready signal pending.

This is the operating plan for the freshly-provisioned research B300.
It follows the **Anthropic Claude Code best-practices loop** (Explore
→ Plan → Implement → Commit, with verification rock-solid at every
step) wrapped in a **Boyd OODA cadence** (Observe → Orient → Decide →
Act, looping fast). Source:
https://code.claude.com/docs/en/best-practices.

> *"Investing in making your verification rock-solid is the single
> highest-leverage thing you can do."* — Anthropic best-practices,
> "Give Claude a way to verify its work."

The plan deliberately **does not touch production** — the live demos
(`prism42-app.thegoatnote.com/prism42/livekit` and
`prism42-console.vercel.app/prism42-v3`) run on the existing B300
voice pod, not this research pod. Verda/Helsinki is in a different
region and is research-scope.

## 0. Hard constraints

- **Cost ceiling:** $50 / session, $200 / week. Halt + report at
  spend hit. Current burn: 1× H200 on Hyperstack (price not yet
  visible in Brev UI; estimated ~$3-4/hr based on Hyperstack
  H200 list price). All four teams co-tenant on the same H200, so
  burn is single-pod, not dual-pod. ~13h before hitting $50 ceiling
  at $3.80/hr. Stop pod between sessions if ≥ 12h gap.
- **No production touch.** This pod is research-only. Don't point
  any live demo URL at it. Don't ssh from this pod into any prod
  pod.
- **No Claude outputs in any training corpus** (Anthropic AUP, see
  `medical-fine-tune-plan.md`).
- **Frozen paths still apply** (CLAUDE.md §3): `.env`, `.state/`,
  `docs/clinical-extension-spec.md` are read-only.
- **Verification gate:** every team's outcome is a JSON artifact
  under `findings/private/b300-bench-2026-04-27/<team>/` with
  `nvidia-smi` capture, command log, exit code, and the measured
  metric. No "looks good" verdicts.

## 1. OBSERVE — current state (as of 2026-04-27 ~04:36 PT)

**Verda Helsinki had a multi-SKU provisioning incident this morning**
— 5 pods failed across `verda_B300`, `verda_B200`, `verda_H200x2`.
Brev's own error message: *"retry on a different cloud."* Pivoted
to Hyperstack/Montreal — first attempt at 2× H100 (`amazing-coral-
bee`) also failed. Final landing: **Nebius eu-north-1** (a third
cloud) on a single H200 141 GiB (`warm-lavender-narwhal`). The
parallel session's `prism-mla-h100` (1× H100, Hyperstack/Montreal)
is independent and stays with them for live-demo restoration.

**This changes the measurement matrix.** Hopper is SM 9.0 with FP8-
native tensor cores; B300 is Blackwell Ultra SM 10.3 with **NVFP4-
native** tensor cores. The `Nemotron-Nano-30B-A3B-NVFP4` quantized
model **cannot run with native NVFP4 kernels on Hopper** — measure
the BF16 base variant (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`)
instead. The H200's 141 GB HBM3e is enough that Nemotron-Nano-30B
in BF16 (~60 GB) fits on a *single* GPU with ~80 GB headroom — no
TP=2 needed, the "do I need 2 GPUs" question dissolves.

**Active pods:**

| Pod | Hardware | State | Owner | Use |
|---|---|---|---|---|
| `warm-lavender-narwhal` (`pdlpt96nl`) | 1× **H200 141 GiB HBM3e**, 16 vCPU, 200 GiB RAM, 256 GiB storage, **Nebius eu-north-1**, $4.24/hr | **Running / Built (READY)** | **THIS session** | All 4 bench teams |
| `prism-mla-h100` (`x3rytha2l`) | 1× H100 80 GB, 28 vCPU, 180 GiB RAM | Running / Building | Parallel session | Live-demo restore (Parakeet + Fish + voice). DO NOT touch. |
| `amazing-coral-bee` (`f5ubt2usb`) | 2× H100 (FAILURE) | Failed, $0/hr | — | Slot-blocking; deletable |

**Failed Verda pods (already deleted by parallel session):**
`prism-mla-b300-h4h5`, `final-gold-ox`, `verbal-yellow-hoverfly`,
`sleepy-bronze-puffin`, `comfortable-indigo-asp`.

**Brev CLI:** `brew install brevdev/homebrew-brev/brev` →
`brev login` → `brev shell warm-lavender-narwhal`.

**Other context:**
- Hackathon judges TODAY — live demo path is `prism-mla-h100`
  (parallel session). My pod is `warm-lavender-narwhal`. Don't
  cross the streams.
- Polarity-fix PR #9 is held draft; Wed 04/29 13:00 PT auto-merge
  routine scheduled (`trig_018rMpinFHQQuj4hnxNsJiZC`).
- Future-stack briefs landed on main (`b459157` → `c5902ad` line).

## 2. ORIENT — binding constraints

| Constraint | Impact |
|---|---|
| Judges TODAY → prod cannot regress | Research pod (`warm-lavender-narwhal`) is isolated from the live-demo pod. No DNS, no Caddy, no LiveKit on this pod. |
| Pod in Hyperstack/Montreal (research region) | Cross-region latency to any user-facing endpoint makes it useless for a live A/B anyway. Compute-only. |
| H200 SM 9.0, no NVFP4 | Nemotron-Nano measurement is BF16 (or FP8 if a variant exists) — **not a Blackwell preview**. |
| TRT-LLM AutoDeploy cold-start = 8–25 min | First measurement of one model burns several minutes of compute just on compile. Cache the engine to a persistent volume. |
| Parallel session owns `prism-mla-h100` | Coordination required if future plans need the H100 pod; default is to leave it alone. |
| User explicitly framed: "i will train nemotron" | Fine-tune work is **user-led**. Assistant does not execute training; only scopes. |
| Boris Cherny / Anthropic discipline: small steps, verify every step | No "run the whole bench overnight and check in the morning." 30-min observe loop. |

## 3. DECIDE — agent teams + outcomes

Four teams. Each team is one Claude Code subagent dispatch with
explicit goal, inputs, success criteria, and report shape. Teams
A/B/C run on `warm-lavender-narwhal` (single H200, co-tenanted by
phase); Team D runs locally (doc only).

### Team A — TRT-LLM cold-start measurement (H200 BF16 baseline)

- **Pod:** `warm-lavender-narwhal` (1× H200 141 GiB).
- **Goal:** measure TRT-LLM 1.2.1 AutoDeploy cold-compile time + p50/
  p99 first-token latency for `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
  (**BF16 base variant**, NOT the -NVFP4 quantized variant — Hopper
  has no native NVFP4 kernels). Single-GPU; no TP needed (141 GB
  fits 60 GB weights + KV with comfortable headroom). Optionally
  also test FP8 if a quantized variant is on HF — H200 has FP8
  tensor cores.
- **Inputs:** `nano_v3.yaml` adapted (drop NVFP4-specific flags;
  single-GPU; `attn_backend: flashinfer`), Docker, NGC container
  `nvcr.io/nvidia/tensorrt-llm/release:1.2.1`.
- **Success criteria:**
  - JSON artifact `findings/private/h200-bench-2026-04-27/team-a/
    cold-start.json` with: `compile_seconds`, `p50_ms`, `p99_ms`,
    `tokens_per_second`, `nvidia_smi.txt`, `exit_code: 0`.
  - p50 first-token latency < 200 ms on a 50-token gen at
    concurrency=1 (Hopper BF16 baseline; not directly comparable to
    Blackwell NVFP4).
  - Cost: < $15 (single-GPU H200, ≤ 3h compute).
- **Halt conditions:**
  - AutoDeploy fails on Nemotron-3-Nano hybrid (Mamba-2 + MoE +
    Attention) → fall back to `:1.3.0rc0` (cookbook pin); do **one**
    retry then halt.
  - VRAM OOM at `max_seq_len: 16384` → drop to 8192, one retry,
    halt if still failing.
  - $15 spent → halt.
- **Caveat:** these numbers are NOT a B300 NVFP4 preview. They
  establish an H200 BF16 baseline that's useful in its own right
  (Hopper is the dominant production GPU today) and validate the
  AutoDeploy compile flow on a real single-GPU setup.
- **Report shape:** 200-word summary + the JSON artifact.

### Team B — Cosmos-Reason2-2B latency budget audit (H200)

- **Pod:** `warm-lavender-narwhal` (same H200 as Team A — Cosmos at
  ~10 GB BF16 co-tenants with Nemotron without VRAM pressure).
- **Goal:** measure Cosmos-Reason2-2B (vLLM-served) per-image
  inference latency on H200 SM 9.0, vs prism42's 1.5 s p95 voice-
  end-to-end budget.
- **Inputs:** vLLM ≥ 0.12 with Qwen3-VL multimodal stack, 5
  representative test images (synthetic or RadSlice-public-class).
- **Success criteria:**
  - JSON artifact `findings/private/h200-bench-2026-04-27/team-b/
    cosmos-latency.json` with per-image `p50_ms`, `p99_ms`,
    `image_size_kb`, `model_load_seconds`.
  - Verdict: GREEN if p99 < 500 ms (fits in voice budget), YELLOW
    500–1000 ms, RED > 1000 ms.
  - Cost: < $5 (≤ 1.5h on H200; can co-tenant with Team A's serve).
- **Halt conditions:**
  - vLLM Qwen3-VL recipe fails on H200 SM 9.0 → log, file as blocker, halt.
  - $5 spent → halt.
- **Report shape:** 200-word summary + JSON.

### Team C — MLA kernel Hopper baseline (NOT a B300 preview)

- **Pod:** `warm-lavender-narwhal` (1× H200, same SM 9.0 arch as H100).
- **Goal:** establish an MLA kernel baseline on Hopper SM 9.0. This
  is **a different baseline** than the prior Blackwell-port work —
  SOTA MLA kernels target `sm_100/sm_103`, not `sm_90`. Useful as
  the Hopper-rail reference (the dominant production GPU today) but
  not as a Blackwell-roadmap preview.
- **Inputs:** `mla/` package (`/Users/kiteboard/prism42/mla/`), the
  evolutionary search runners, golden test set, production attention
  kernel implementations for SM 9.0.
- **Success criteria:**
  - JSON artifacts under `findings/private/h200-bench-2026-04-27/
    team-c/` capturing: ref-impl correctness pass on H200, p50/p99
    of the current best Hopper-targeted candidate, BF16/FP8
    numerics within tolerance.
  - Cost: < $15.
- **Halt conditions:**
  - Numeric drift > tolerance vs CPU reference → log delta, halt.
  - $15 spent → halt.
- **Report shape:** 250-word summary + artifacts. Mark explicitly
  "Hopper SM 9.0 baseline — not comparable to Blackwell numbers."

### Team D — Medical-corpus scaffolding (local, doc-only)

- **Goal:** propose a directory structure + sourcing checklist for
  the user-led medical corpus, per `medical-fine-tune-plan.md`.
- **Inputs:** existing OpenEM, GEDP, healthcraft eval corpora as
  reference shapes.
- **Success criteria:**
  - Markdown brief at `findings/research/2026-04-27-future-stack/
    medical-corpus-skeleton.md` with: dir tree, manifest schema,
    license-tracking shape, provenance-hash recipe, eval-set
    quarantine rule.
  - Cost: $0 (no GPU touch).
- **Halt conditions:** none — doc only.
- **Report shape:** the brief itself.

## 4. ACT — execution gating

**Now (before pod is SSH-ready):**

- [x] Land all doc updates (BioNeMo dropped, TRT-LLM brief, Cosmos
      brief updated, dual-credit feedback loop in diagram, this
      plan, the medical-fine-tune sketch).
- [ ] Team D (corpus scaffolding) can begin immediately — local-only.

**When pod is SSH-ready (user pings "ready"):**

- [ ] Team A first (foundational measurement; everything else depends
      on knowing if TRT-LLM AutoDeploy works on the Nemotron hybrid).
- [ ] On Team A green: spawn Team B + Team C in parallel.
- [ ] Spend ceiling: $50/session. Halt-and-report at hit.

**Daily OODA cadence (when running):**

- 30-minute observe ticks: `nvidia-smi`, `df -h`, container status,
  active spend.
- Halt + report at any anomaly (compile stall, OOM, numerics drift,
  cost overrun).
- Verify each step's exit code before claiming "done."

**Tear-down rule:**

- After each session, capture `findings/private/b300-bench-2026-04-
  27/<team>/<timestamp>/` snapshot. Pod can stay up if next session
  is < 12h out; otherwise stop the pod (preserve work via Brev
  storage; pod re-provision is ~3 min).

## 5. Anti-patterns (the things this plan refuses to do)

- ❌ Run all four teams concurrently for 6 hours unattended.
- ❌ Use the research pod for any live demo or production traffic.
- ❌ Train Nemotron on Claude-generated outputs.
- ❌ Measure perf without an `nvidia-smi` capture in the artifact.
- ❌ Claim a TRT-LLM-vs-vLLM win without a paired 24h shadow run.
- ❌ Touch any file under `/Users/kiteboard/prism2/` (parallel
  session's worktree).
- ❌ Skip the verification step on any team's "done" claim.

## 6. References

- https://code.claude.com/docs/en/best-practices — Explore → Plan →
  Implement → Commit; verification-rock-solid principle.
- John Boyd's OODA loop — observe-orient-decide-act, looping fast.
- `findings/research/2026-04-27-future-stack/tensorrt-llm-on-b300.md`
  — runtime brief that this bench plan operationalizes.
- `findings/research/2026-04-27-future-stack/cosmos-reason2-2b.md` —
  Cosmos serving path (vLLM, not TRT-LLM).
- CLAUDE.md §0 (hackathon mode), §3 (frozen paths), §4 (verification
  discipline), §5 (double-gate for live calls), §9 (cost ceilings).
