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
  spend hit. ($7.91/hr × 6h ≈ $48; one full session ≈ ceiling.)
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

## 1. OBSERVE — current state (as of 2026-04-27 ~04:00 PT)

- **Pod:** `final-gold-ox` deploying on Verda/Helsinki.
  $7.91/hr. 288 GiB HBM3E. 30 vCPU. 275 GiB RAM. ETA ≤ 2m30s per
  Brev UI.
- **Brev CLI:** install path is `brew install brevdev/homebrew-
  brev/brev` then `brev login` then `brev shell chemical-black-
  lungfish` — per the Verda console.
- **Other Claude session active in `prism2/`** running a 4-agent
  compliance audit. Treat that worktree as not-ours; do not modify
  files under `/Users/kiteboard/prism2/` from this session.
- **Hackathon judges today.** Live demo path is on a different pod
  and is NOT this one.
- **Polarity-fix PR #9** is held draft; Wed 04/29 13:00 PT auto-
  merge routine is scheduled (`trig_018rMpinFHQQuj4hnxNsJiZC`).
- **Future-stack briefs landed** on main (`b459157` + `ee94339` +
  this commit's hero update).

## 2. ORIENT — binding constraints

| Constraint | Impact |
|---|---|
| Judges TODAY → prod cannot regress | Research pod must stay isolated. No DNS, no Caddy, no LiveKit on this pod. |
| Pod in Helsinki (research region) | Cross-region latency to US-based prod gateway makes it useless for a live A/B anyway. Treat as compute-only. |
| $7.91/hr | One unattended overnight = $190. Halt-and-report > drift. |
| TRT-LLM AutoDeploy cold-start = 8–25 min | First measurement of one model burns ~$3 just on compile. Plan reuse of warm engine cache. |
| User explicitly framed: "i will train nemotron" | Fine-tune work is **user-led**. Assistant does not execute training; only scopes. |
| Boris Cherny / Anthropic discipline: small steps, verify every step | No "run the whole bench overnight and check in the morning." 30-min observe loop. |

## 3. DECIDE — agent teams + outcomes

Four teams. Each team is one Claude Code subagent dispatch with
explicit goal, inputs, success criteria, and report shape. Teams
A/B/C run on the B300 (compute); Team D runs locally (doc only).

### Team A — TRT-LLM cold-start measurement (foundational)

- **Goal:** measure TRT-LLM 1.2.1 AutoDeploy cold-compile time + p50/
  p99 first-token latency for `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-
  NVFP4` on B300 SM 10.3.
- **Inputs:** `infra/b300/nano_v3.yaml` (copy from NVIDIA cookbook),
  fresh pod, Docker, NGC container `nvcr.io/nvidia/tensorrt-llm/
  release:1.2.1`.
- **Success criteria:**
  - JSON artifact `findings/private/b300-bench-2026-04-27/team-a/
    cold-start.json` with: `compile_seconds`, `p50_ms`, `p99_ms`,
    `tokens_per_second`, `nvidia_smi.txt`, `exit_code: 0`.
  - p50 first-token latency < 100 ms on a 50-token gen at concurrency=1.
  - Cost: < $15 (≤ 2h compute).
- **Halt conditions:**
  - AutoDeploy fails on Nemotron-3-Nano hybrid → fall back to
    `:1.3.0rc0` (cookbook pin); do **one** retry then halt.
  - NVFP4 CUDA-Graph error at batch>1 → log, switch to `--disable-
    cuda-graph`, re-run; do **one** retry then halt.
  - $15 spent → halt.
- **Report shape:** 200-word summary + the JSON artifact. No prose
  embellishment.

### Team B — Cosmos-Reason2-2B latency budget audit

- **Goal:** measure Cosmos-Reason2-2B (vLLM-served) per-image
  inference latency on B300 SM 10.3, vs prism42's 1.5 s p95 voice-
  end-to-end budget.
- **Inputs:** vLLM ≥ 0.12 with Qwen3-VL multimodal stack, 5
  representative test images (synthetic or RadSlice-public-class).
- **Success criteria:**
  - JSON artifact `findings/private/b300-bench-2026-04-27/team-b/
    cosmos-latency.json` with per-image `p50_ms`, `p99_ms`,
    `image_size_kb`, `model_load_seconds`.
  - Verdict: GREEN if p99 < 500 ms (fits in voice budget), YELLOW
    500–1000 ms, RED > 1000 ms.
  - Cost: < $10.
- **Halt conditions:**
  - vLLM Qwen3-VL recipe fails on B300 SM 10.3 → log, file as
    blocker, halt.
  - $10 spent → halt.
- **Report shape:** 200-word summary + JSON.

### Team C — MLA kernel re-baseline on fresh B300

- **Goal:** re-establish post-cycle-2D MLA kernel benches on a clean
  B300 (the prior pod is wedged per the parallel session).
- **Inputs:** `mla/` package (`/Users/kiteboard/prism42/mla/`), the
  evolutionary search runners, golden test set.
- **Success criteria:**
  - JSON artifacts under `findings/private/b300-bench-2026-04-27/
    team-c/` capturing: ref-impl correctness pass, p50/p99 of the
    current best candidate, NVFP4 numerics within tolerance.
  - Cost: < $20.
- **Halt conditions:**
  - Numeric drift > tolerance vs prior baseline → log delta, halt.
  - $20 spent → halt.
- **Report shape:** 250-word summary + artifacts. Match the existing
  `findings/voice/cycle2*/baseline-*/` shape so it slots into the
  audit trail.

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
