# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# CLAUDE.md — Prism agent operating charter

Any agent (Claude session, Managed Agent, or subagent) working in this repo reads this first. It is the operating contract. The normative specs (`docs/clinical-extension-spec.md`, `docs/clinical-roadmap.md`, `docs/sota-portfolio.md`) are the *what*; this file is the *how*.

## 1. Mission

Prism is an Opus-4.7 managed-agent auditor of numerical correctness in GPU inference kernels and clinical reasoning (HealthBench Hard rubric). **Every finding ships with an executed artifact — a compiled GPU PoC run on real H100/Trainium, or a rubric-graded model-behavior delta.** There are no speculative findings.

## 2. Two rails, one harness

| Rail | Target | Scorer | Artifact |
|---|---|---|---|
| kernel | CUDA / cute / NKI kernels | PoC exits with `VIOLATION: ...` | executed PoC log on H100/Trainium |
| clinical | HealthBench Hard examples | `simple-evals` rubric grader | baseline `results/*.json` (mean ± 95% CI, N≥3) + paired harness delta |

The five agents (coordinator / defender / attacker / synthesizer / executor / adjudicator) are rail-agnostic. The executor thread branches on `case.rail`.

## 3. Frozen paths — NEVER modify

These belong to a parallel session or are normative contracts. Touching them triggers cross-session conflicts.

```
docs/clinical-extension-spec.md
.env
.state/
```

If a task appears to require editing any of these, STOP and ask the user. The roadmap + spec are designed so agent-sized tasks never need to touch frozen paths.

## 4. Verification discipline (the hard rule)

**Every action ends with a verification step whose exit code proves the claim.** Not "I think it works"; the shell command with exit 0.

| Layer | Command | Proves |
|---|---|---|
| L1 schema | `python scripts/validate_artifacts.py --case-dir <dir>` | artifacts match JSON Schema 2020-12 |
| L2 agent self-check | per-agent output schema validation | agent emitted a parseable, schema-aligned verdict |
| L3 regression | `make validate-golden` | `KERNEL-GOLDEN` and `HBH-CLN-SYNTH` still pass |
| L4 invariants | `scripts/pipeline_invariants.py` | agent pins, role/filename, egress, mounts, manifest, schemas |
| L5 CI | `.github/workflows/verify.yml` | offline green on every push |
| T3 umbrella | `make verify-all` | all above in one call |

**No commit ships without `make verify-all` green.** No branch pushes without CI green on the prior push.

### Benchmark discipline (Phase B, clinical rail)

**No technique ships without a measured delta on a Phase B scorer.** (`docs/sota-portfolio.md` §0, §1.) Primary scorer HealthBench Hard (rubric); null-result controls MedQA and MMLU-Medical-6 (exact-match MCQ, `|delta| <= 0.01`); RAG validator PubMedQA (lift >= 10pp before R1/R2 ship).

**Baseline and harness-delta gates (revised 2026-04-22 after T4.6c/d).** The original `|agg_run1 - agg_run2| < 0.02` absolute gate is statistically unachievable for a non-deterministic model at realistic subset sizes (see `docs/seed-stability-2026-04-22.md` for the variance math). It is replaced by:

1. **Baseline:** HealthBench Hard aggregate reported as mean of N ≥ 3 independent runs ± 95% CI half-width on the declared subset. Every per-run aggregate is retained under `results/`.
2. **Harness delta (T4.7+):** paired comparison against baseline on the same subset, same day. Per example: `score_with_harness - score_without_harness`. Gate: paired mean Δ's 95% CI excludes 0 (two-sided, α=0.05). Minimum detectable effect reported alongside every published delta.

Rationale: paired design cancels per-example sampler variance; both arms see the same Opus 4.7 noise. An absolute-|Δ| gate on two independent baseline runs fights the variance instead of cancelling it.

**Landed baseline (T4.6d, 2026-04-22):** Opus 4.7 HealthBench Hard = **0.196 ± 0.068** (mean of N=3 independent runs, 95% CI half-width) on the declared 30-example subset. This is the first public Opus-4.7 HealthBench Hard number. Harness deltas ship only after a paired re-run against this baseline on the same subset, same day.

The Opus 4.7 baseline card (`docs/opus47-baseline-card.md`) holds every quoted medical benchmark number. Every row is a direct quote from a cited source with a fetch-date. No interpolation, no backfill from related models. If the card says `pending`, the number is not yet knowable.

## 5. Double-gate for live API / compute

Any script that spends money or calls an external LLM is gated by TWO independent signals. Both must be set; either alone is a no-op (stays in dry-run).

```
python scripts/<runner>.py --commit --<other-args>
PRISM_<COMPONENT>_COMMIT=1 python scripts/<runner>.py --commit ...
```

Current gated scripts (12, AST-verified by `scripts/check_sdk_containment.py`):

- **Agent surface:** `register_agents.py`, `register_skills.py`
- **Audit runners:** `harness_runner.py`, `run_solo_audit.py`, `run_skilled_audit.py`, `orchestrator.py`
- **Benchmark runners:** `healthbench_runner.py`, `medqa_runner.py`, `mmlu_medical_runner.py`, `pubmedqa_runner.py`
- **Smokes:** `smoke_session.py`, `smoke_delegation.py`, `verify_session_durability.py`

All default to dry-run. All lazy-import the SDK *inside* `do_commit()` so dry-run paths cannot accidentally import `anthropic`. AST containment is part of `make verify-t3`. If you add a gated script, extend `check_sdk_containment.py`'s TARGETS.

## 6. Commit + push discipline

- **One commit per task**, message template `T-{id}: {subject}` (e.g. `T3 P6: tests/test_clinical_case.py — clinical rail validator tests`).
- **Co-author footer required**: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- **Never `git add -A` / `git add .`** in this repo. Always stage by name. (`.state/` has live edits from parallel sessions.)
- **Never push without explicit user ask** (or the directive being the active mode, e.g. during /loop or explicit "Go" execution).
- **Never amend a pushed commit.** New commit on top.
- **Never `--no-verify`.** If a hook fails, fix the cause.

Repository is public (`GOATnote-Inc/prism42`). MIT-licensed. See `docs/kernel-research-posture.md` for the research / disclosure separation.

## 7. Subagent dispatch protocol

Every subagent invocation (see `docs/clinical-roadmap.md` §9) includes:

1. **Task ID** (e.g. `P3`, `T4.6b`, `H1`).
2. **Spec cross-ref** — roadmap section + spec section the agent must read first.
3. **Frozen paths** — restated in-prompt (agent cannot be assumed to read this file).
4. **Inputs + outputs** — exact paths the agent may read / may write.
5. **Verification command** — exact shell invocation whose exit 0 proves done.
6. **Commit rule** — one commit, message template, no push, co-author footer.
7. **Budget** — token/$ ceiling; halt on hit.

Prefer `isolation: "worktree"` for parallel dispatch when file writes are disjoint — the runtime fast-forward-merges the agent's branch back to `main` on clean completion. If two worktrees touch overlapping files, serialize.

## 8. Managed Agents specifics

- Base Managed Agents (agents, environments, sessions, events, skills,
  deployments) is **GA** — `managed-agents-2026-04-01` beta header, re-
  verified against docs 2026-04-22.
- Model ID **`claude-opus-4-7`**. 4.7 rejects `temperature`, `top_p`,
  `top_k`, `budget_tokens`, and does not expose a `seed` kwarg on
  `messages.create`. Thinking OFF by default. Determinism is lost vs
  4.6; baselines report mean ± 95% CI across N ≥ 3 runs and harness
  deltas gate via paired comparison — see §4 *Benchmark discipline*.
- Session cost ~$0.08 / session-hr plus token usage.
- **Multi-agent (callable_agents) status on this API key's workspace:
  silently stripped.** Docs describe it as research preview
  (`platform.claude.com/docs/en/managed-agents/overview`: "Certain
  features (outcomes, multiagent, and memory) are in research preview.
  Request access at `https://claude.com/form/claude-managed-agents`.").
  Tested 2026-04-22 from this repo against the API key in `.env`:
  `POST /v1/agents` returns 200 OK with `callable_agents` absent from
  the stored body, regardless of which beta-header combination is sent.
  Five headers tested (base only, +`multi-agent-2026-04-01`,
  +`managed-agents-multi-agent-2026-04-01`, +`multiagent-2026-04-01`,
  +`research-preview-2026-04-01`): all 200 OK, all strip. No response
  header indicates the strip; no `X-Feature-Disabled` or warning.
- Python SDK typed surface (v0.96.0 AND GitHub `main` branch) does not
  expose `callable_agents` as a named kwarg. `extra_body` is NOT a
  bypass — verified by raw-HTTP probe. When the workspace gets
  multi-agent feature enabled AND the SDK regenerates from the
  updated OpenAPI spec, the canonical Python form becomes:
  `client.beta.agents.create(..., callable_agents=[{"type":"agent","id":...,"version":...}, ...])`.
- **Key disambiguation**: API keys are workspace-scoped; console views
  are workspace-scoped. Console screenshots showing one set of agents
  may not match API-key `beta.agents.list` — they may be viewing
  different workspaces under the same org. If the user says
  "multi-agent access is granted" but API still strips, verify it was
  granted on the workspace the `ANTHROPIC_API_KEY` belongs to, not
  another workspace under the same org. The live probe's request_id
  for support escalation: `req_011CaJg9qBnVqPNkaoBLgjrN`
  (2026-04-22 10:46 UTC).
- Delegation event names on the session stream (canonical, per docs):
  `session.thread_created`, `session.thread_idle`,
  `agent.thread_message_sent`, `agent.thread_message_received`.
  (Do NOT look for `span.sub_agent_*` — not real event names.)
- Prism fallback for current workspace state: run the whole audit with
  one coordinator Managed Agent using `agent_toolset_20260401`; defender/
  attacker/synthesizer/executor/adjudicator become workflow phases
  within that single agent's session. When multi-agent access lands,
  the 5 sub-agents already registered become callable without Prism-
  side code change.

### `ant` CLI — sidecar, not replacement (added 2026-04-22)

Anthropic ships an official CLI, `ant` (v1.0.0), whose `beta:agents`, `beta:environments`, `beta:sessions`, `beta:skills`, `beta:deployments` subcommands consume the **exact YAML shape** Prism's `agents/*.yaml` and `environments/*.yaml` files already use — after `_prism:` metadata is stripped. See `https://platform.claude.com/docs/en/api/sdks/cli`. Install: `brew install anthropics/tap/ant` + `xattr -d com.apple.quarantine "$(brew --prefix)/bin/ant"` on macOS.

**Policy**: `ant` is a **read-only sidecar** for exploration + smoke tests. Production agent registration stays under `scripts/register_agents.py`, which owns: `_prism:` metadata strip, symbolic `callable_agents` → id resolution, `agents/manifest.yaml` emission, double-gate contract (`--commit` + `PRISM_AGENTS_COMMIT=1`), AST-verified SDK containment, and the pipeline-invariants check. `ant` does none of these. Makefile exposes `make ant-check` + `make ant-smoke` for installation-check and read-only list probes; neither creates, updates, or deletes workspace state. `make verify-all` never depends on `ant` being installed.

### Credential vaults — deferred (status as of 2026-04-22)

Anthropic's Managed Agents surface gained **credential vaults** this week (platform.claude.com → Managed Agents → Credential vaults; docs at `https://platform.claude.com/docs/en/managed-agents/vaults`). Vaults are session-bound MCP auth stores (MCP-OAuth auto-refresh + static-bearer), workspace-scoped, with write-only secret fields and up to 20 credentials per vault. Binding is `POST /v1/sessions { ..., vault_ids: [...] }`.

**Prism does not currently use vaults** because Prism's six agents call `agent_toolset_20260401` (bash, file ops, web) directly — **no MCP servers in the current design**. Vaults become relevant when:

- **R2 PubMed retrieval tool** (`docs/sota-portfolio.md` §6) wires an MCP server for NCBI / Entrez — vault holds the API token.
- **H5 disclosure-packet automation** (`docs/clinical-roadmap.md` §7) wires an MCP server for the Anthropic feedback channel intake.

Both are post-hackathon. Do **not** add vault scaffolding speculatively; wire it only when the first MCP server actually lands. When you do, the binding rule is: `vault_ids` is per-session (not per-agent, not per-environment).

## 9. Cost + budget ceilings

- T3 scaffolding (no live calls): `$0`.
- T4.6 baselines (2 runs × 30 examples × Opus 4.7): ~$30.
- T4.7 harness sweep (30 coordinator sessions): ~$100 + ~$2 session-hr.
- SOTA additions (R1-R6 + V1-V4): +$120.
- **Total hackathon cap: $280.** Agent halts at budget hit; user resumes explicitly.

## 10. Clinical findings are not CVEs

Model-behavior observations (harness beats Opus 4.7 baseline on a HealthBench Hard example) route through the disclosure posture in `docs/clinical-handling.md`: physician review (Brandon Dent, MD sign-off), Anthropic feedback channel primary, research venue secondary, never social. Appended to gitignored `findings/clinical-log.jsonl`.

---

## Recent best-practice synthesis (fetched 2026-04-23)

This section is append-only research notes. It does not supersede §1-§10; it cites what the Anthropic / NVIDIA / LiveKit / vLLM ecosystems said between Feb and April 2026 so the operating charter above stays anchored to the current reality. Every factual claim links to the URL it came from. Bullets tagged `[empirical, unverified]` are things we observed on the pod but could not find a public citation for.

### Claude Code on this repo (2026)

- **CLAUDE.md is loaded every session — keep it short, pruned, human-readable.** Anthropic's explicit test: *"For each line, ask: Would removing this cause Claude to make mistakes? If not, cut it."* Bloated CLAUDE.md causes Claude to ignore the actual rules. Long reference material belongs in skills (loaded on demand), not here. Source: `https://code.claude.com/docs/en/best-practices` (Best Practices, section "Write an effective CLAUDE.md").
- **Verification is the single highest-leverage thing you can do.** Anthropic's phrasing: *"Include tests, screenshots, or expected outputs so Claude can check itself. This is the single highest-leverage thing you can do."* This validates §4 of this file. Source: `https://code.claude.com/docs/en/best-practices` ("Give Claude a way to verify its work").
- **Plan Mode → Normal Mode split for ambiguous work.** Four-phase workflow (Explore → Plan → Implement → Commit); skip planning only when the diff is describable in one sentence. Useful for P3/H-series tasks where spec-cross-ref reading is expensive. Source: `https://code.claude.com/docs/en/best-practices` ("Explore first, then plan, then code").
- **Auto mode has a 17% false-negative rate on "overeager" classifier decisions.** Anthropic engineering blog (Mar 25, 2026): *"Testing revealed a 17% false-negative rate on real overeager actions."* Classifier is a Sonnet-4.6-backed transcript reviewer; 3 consecutive denials or 20 total → process terminates. Means auto mode is safer than YOLO, not safe enough to drop the double-gate in §5. Source: `https://www.anthropic.com/engineering/claude-code-auto-mode`.
- **Skills > commands, and both now unify.** Skills spec: `.claude/skills/<name>/SKILL.md` with frontmatter (`name`, `description`, `disable-model-invocation`, `allowed-tools`, `model`, `effort`, `paths`, `context: fork`). Descriptions are truncated at 1,536 chars in the skill listing — front-load the key use case. Auto-compaction re-attaches the most recent invocation of each skill up to 5,000 tokens, combined 25,000-token budget. Source: `https://code.claude.com/docs/en/skills`.
- **Agent Teams stays experimental and gated.** Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` + Claude Code ≥ v2.1.32. Key limitations: no nested teams, one team per session, permissions set at spawn, lead cannot be reassigned, split panes require tmux or iTerm2. Policy for prism42: use subagents (`.claude/agents/`) for solo work; reserve agent teams for parallel research (`research-preview` hackathon pattern). Source: `https://code.claude.com/docs/en/agent-teams`.

### Claude Opus 4.7 kwargs + patterns

- **`temperature`, `top_p`, `top_k` return 400** on Opus 4.7 Messages API when set to any non-default value. Migration guidance: omit entirely and rely on prompting. Source: `https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7` ("Sampling parameters removed").
- **`thinking: {type: "enabled", budget_tokens: N}` returns 400**; the only supported thinking mode is `thinking: {type: "adaptive"}`. Adaptive thinking auto-enables interleaved thinking between tool calls. Default is **thinking OFF** on 4.7 — requests with no `thinking` field run without thinking. Source: `https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking` ("Supported models" and "How adaptive thinking works").
- **Thinking `display` defaults to `"omitted"` on 4.7**, silent change from 4.6 which defaulted to `"summarized"`. Anthropic flags the consequence directly for voice: *"If your product streams reasoning to users, the new default will appear as a long pause before output begins. Set `display: summarized` to restore visible progress during thinking."* For Prism's 911-dispatcher voice path, keep `display: omitted` — no user-facing reasoning — and accept faster time-to-first-text-token. Source: same page, "Controlling thinking display" section.
- **Task budgets** (`task-budgets-2026-03-13` beta header) are available on 4.7 only, minimum 20,000 tokens. They are advisory, not a hard cap — Claude sees a server-injected countdown and paces itself. `max_tokens` remains the hard per-request ceiling. Setting `remaining` client-side while resending full history under-reports the budget; prefer one-shot setting on the initial request. Source: `https://platform.claude.com/docs/en/build-with-claude/task-budgets`.
- **Tokenizer change: 1x-1.35x tokens compared to Opus 4.6.** Anthropic: *"This new tokenizer may use roughly 1x to 1.35x as many tokens when processing text compared to previous models (up to ~35% more)."* Re-measure budgets after any 4.6→4.7 migration; `/v1/messages/count_tokens` returns different values. 1M context at standard pricing, no long-context premium. Source: same whats-new page, "Updated token counting".
- **Behavior changes that matter for Prism prompts.** Opus 4.7 is more literal (fewer silent generalizations), calibrates response length to task complexity, defaults to fewer tool calls, spawns fewer subagents by default, and uses a more direct/less warm tone. Anthropic explicitly advises: remove scaffolding you added to 4.6 prompts that forced interim status messages, and re-baseline prompts that included "double-check before returning" language — 4.7 already does this. Source: same page, "Behavior changes".

### B300 / Blackwell Ultra specifics for our stack

- **Compute capability is sm_103, not sm_100.** The verda.com analysis and PyTorch Triton error messages both show B300 reports `sm_103a` while B200 is `sm_100`. SM 12.0 (GeForce Blackwell) is **not** a superset of sm_100 — cross-arch kernels fail. Set `TORCH_CUDA_ARCH_LIST` to include both `10.0` (fallback for B200 wheels) and `10.3` if you build from source on a B300 pod. Source: `https://verda.com/blog/nvidia-b200-and-b300-gpu-architecture-and-software-stack` and `https://docs.nvidia.com/cuda/blackwell-compatibility-guide/`.
- **B300 vs B200 headline delta.** +55.6% dense FP4 perf (14 vs 9.0 PFLOPS), +55.6% HBM (288 GB HBM3E vs 180 GB), 8 TB/s vs 7.7 TB/s bandwidth, 1,100 W vs 1,000 W TDP. B300 essentially removes FP64 (1.25 TF vs 37 TF) — irrelevant for inference, catastrophic for any FP64-heavy eval. Source: `https://verda.com/blog/nvidia-b200-and-b300-gpu-architecture-and-software-stack`.
- **vLLM v0.20.0 has B300/GB300 (SM 10.3) support with allreduce fusion enabled by default** and "tuned all-reduce communicators." Use this as the minimum vLLM pin when serving on B300. Source: `https://github.com/vllm-project/vllm/releases` (v0.20.0 notes).
- **SGLang 25.11 adds GB300/B300 support.** Container ships PyTorch 2.10.0a0, FlashInfer 0.5.0, Flash-Attention 2.7.4.post1, CUDA 13.0.2.006. Flash-Attention in the container is **FA2, not FA4** — the SGLang container does not bundle FA4 as of 25.11. Source: `https://docs.nvidia.com/deeplearning/frameworks/sglang-release-notes/rel-25-11.html`.
- **FlashAttention-4 is sm_100-only and written in CuTeDSL (Python), not CUDA C++.** Tri Dao (blog post): 1605 TFLOPs/s BF16 on B200 (71% util), 1.3× faster than cuDNN 9.13, 2.7× faster than Triton. The kernel uses `tcgen05.mma.cta_group::1` (5th-gen tensor cores) and 256 KB TMEM per SM. No B300-specific numbers published as of April 2026 — assume FA4 runs on B300 via PTX JIT but has not been re-tuned. Sources: `https://tridao.me/blog/2026/flash4/` and `https://modal.com/blog/reverse-engineer-flash-attention-4`.
- **FA3 is blocked on Blackwell.** The Dao-AILab error message is explicit: *"FA3 is only supported on devices with compute capability >= 8 excluding 8.6 and 8.9 and Blackwell archs (>=10)."* Our measured 43.25 µs p50 B300 torch.compile vs 22.53 µs p50 H100 FA3 is consistent with this — FA3 simply cannot run on B300; FA4 is the only kernel-path that closes the gap on Blackwell. Source: `https://github.com/Dao-AILab/flash-attention/issues/1853`.
- **Minimum CUDA version is 12.8 for B200; B300 requires CUDA 13.** vLLM docs confirm "NVIDIA Blackwell GPUs (B200, GB200) require a minimum of CUDA 12.8" and "For (G)B300, CUDA 13 is recommended." For our Brev pod, verify `nvidia-smi` shows CUDA 13.0+ before running any FA4 or NVFP4 path. Source: `https://docs.vllm.ai/en/stable/getting_started/installation/gpu/` (via search summary).
- **NVFP4 is the Blackwell-native 4-bit format.** SGLang 25.11 calls this out: *"NVIDIA innovative 4-bit floating point NVFP4 format on Blackwell GPUs...better training and inference performance with lower memory utilization."* vLLM's gpt-oss post on Blackwell uses NVFP4 for MoE paths. For Parakeet STT + Fish TTS on SGLang, stay on BF16/FP8 until we have a measured win from NVFP4 on those specific models. Sources: SGLang 25.11 release notes; `https://blog.vllm.ai/2026/02/01/gpt-oss-optimizations.html`.
- **Environment variables we actually tweak.** `TORCH_CUDA_ARCH_LIST=10.0` (or `10.0;10.3` on B300), `FLASHINFER_CUDA_ARCH_LIST=10.0`, `TRITON_CODEGEN_ARCH=100`, `triton==3.6.0` — `[empirical, unverified]` from the parallel session's findings. Public vLLM docs show `torch_cuda_arch_list="9.0 10.0+PTX"` as the canonical pattern for arm64 Grace-Blackwell builds; extrapolate. Source (partial): `https://docs.vllm.ai/en/stable/getting_started/installation/gpu/`.

### LiveKit agent patterns for voice-first products

- **Semantic turn detector is the default; VAD-only is the fallback.** LiveKit ships a Qwen2.5-0.5B-Instruct-based multilingual turn detector, CPU inference at 50-160 ms per turn, <500 MB RAM. 14 languages. Self-hostable; LiveKit Cloud deploys it globally. Install: `uv add "livekit-agents[turn-detector]~=1.4"`. Source: `https://docs.livekit.io/agents/logic/turns/turn-detector/`.
- **Adaptive interruption handling, released 1.5.0 (2026-03-19), is the default.** CNN + audio-encoder model that distinguishes real barge-in from backchannel. LiveKit claim: *"86% precision and 100% recall (at 500 ms overlap speech)... Rejects 51% of false VAD-based barge-ins... Median audio duration needed: 216 ms. Inference completes in 30 ms or less."* Revert to `interruption={"mode": "vad"}` if this misbehaves on your domain. For PSAP (dispatcher) use we want the adaptive model — EMS callers interrupt for real reasons; we do not want to talk over them. Source: `https://livekit.com/blog/adaptive-interruption-handling`.
- **Dynamic endpointing replaced fixed silence thresholds in 1.5.0.** `TurnHandlingOptions(mode="dynamic", min_delay=0.5, max_delay=3.0)` adapts the delay using an exponential moving average of pause statistics per session. For 911 calls where callers hesitate, keep the default 500-3000 ms window rather than collapsing to 500 ms. Source: `https://livekit.com/blog/understand-and-improve-agent-latency` + `https://docs.livekit.io/agents/logic/turns/turn-detector/`.
- **Preemptive generation is on by default in 1.5.0+.** LLM and TTS begin inference on partial STT transcripts so total pipeline latency approaches `max(VAD, STT, LLM, TTS)` rather than their sum. LiveKit's cited range: 400-800 ms streaming vs 1000-2000 ms+ blocking. `PreemptiveGenerationOptions` in 1.5.4 adds `max_speech_duration` (default 10 s) and `max_retries` (default 3) guards for long utterances. Source: `https://livekit.com/blog/sequential-pipeline-architecture-voice-agents`.
- **Pipeline (STT→LLM→TTS) vs Realtime (S2S) — LiveKit's own April 2026 guidance.** Pipeline wins for "telephony deployments, regulated industries, and scenarios requiring detailed audit trails and compliance controls." Realtime wins for "consumer applications prioritizing emotional awareness and natural prosody." 911 dispatcher is telephony + regulated + audit-heavy → pipeline is correct. Source: `https://livekit.com/blog/realtime-vs-cascade`.
- **Our STT/TTS choices are on the current plugin list.** NVIDIA Riva/Parakeet plugin (`livekit-agents[nvidia]~=1.4`) supports `parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer` with optional speaker diarization. Default endpoint is cloud (`grpc.nvcf.nvidia.com:443`); self-host points at a local Riva NIM. Fish Audio plugin (`livekit-plugins-fishaudio`) defaults to model `s1` — verify Prism is pinning `S2` / S2 Pro explicitly in the agent config; otherwise we're getting the older `s1` backend. Latency mode: "normal" ~500 ms, "balanced" ~300 ms (default). Sources: `https://docs.livekit.io/agents/models/stt/plugins/nvidia/` and `https://docs.livekit.io/reference/python/livekit/plugins/fishaudio/index.html`.
- **WebRTC > WebSockets for voice.** LiveKit's March 2026 position piece argues Opus over WebRTC beats raw WebSockets for jitter tolerance, packet loss, and adaptive bitrate. For our Brev pod, the :7880 WSS (signaling) + :7882 UDP (media) split is the right shape; the :7882 UDP path is what makes barge-in work under Cloudflare's edge latency. Source: `https://livekit.com/blog/why-webrtc-beats-websockets-for-voice-ai-agents`.

### Cross-cutting discipline reminders (specific to this harness)

- **Verification-every-turn is not negotiable (§4).** The Anthropic best-practices post promotes the same pattern: *"Invest in making your verification rock-solid."* Map: our L1-L5 + T3 umbrella matrix is the "verification rock" Anthropic is describing. If a skill or subagent bypasses `make verify-all`, that skill is broken, not the verify chain.
- **Generator-evaluator separation is the sanctioned pattern for harness design.** Anthropic Labs (Prithvi Rajasekaran, 2026-03-24): *"Separating the agent doing the work from the agent judging it proves to be a strong lever."* Prism's 5-role split (defender/attacker/synthesizer/executor/adjudicator) is this pattern applied to numerical-correctness audits. When the workspace gets `callable_agents` access and we turn on true multi-agent, keep adjudicator as a distinct thread — do not let the executor grade itself. Source: `https://www.anthropic.com/engineering/harness-design-long-running-apps`.
- **Session durability lives outside the context window.** Managed Agents engineering post: *"the session provides this same benefit, serving as a context object that lives outside Claude's context window."* Our Redis-backed SessionState is the local analog; treat it as the source of truth for anything that must survive a thread reset. Brain (coordinator) is replaceable; hands (tool runs) are replaceable; the session log is the only thing we cannot recreate. Source: `https://www.anthropic.com/engineering/managed-agents`.
- **Cross-vendor rubric independence (GPT-5.5 → GPT-5.4 → Opus shim).** The clinical rail's paired-delta gate in §4 only cancels variance if both arms see identical judge noise. When a judge fails, the eval must halt — not silently fall back. See `feedback_eval_preflight_judge_key.md` for the 401-poisons-reward incident that originated this rule. Applies to every GEDP v0.1 adjudication trace shipped from `mvp/911-console-live/`.

### Sources consulted

- `https://code.claude.com/docs/en/best-practices`
- `https://code.claude.com/docs/en/skills`
- `https://code.claude.com/docs/en/agent-teams`
- `https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7`
- `https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking`
- `https://platform.claude.com/docs/en/build-with-claude/task-budgets`
- `https://www.anthropic.com/engineering/harness-design-long-running-apps`
- `https://www.anthropic.com/engineering/managed-agents`
- `https://www.anthropic.com/engineering/claude-code-auto-mode`
- `https://tridao.me/blog/2026/flash4/`
- `https://modal.com/blog/reverse-engineer-flash-attention-4`
- `https://github.com/Dao-AILab/flash-attention/issues/1853`
- `https://docs.nvidia.com/deeplearning/frameworks/sglang-release-notes/rel-25-11.html`
- `https://docs.nvidia.com/cuda/blackwell-compatibility-guide/`
- `https://verda.com/blog/nvidia-b200-and-b300-gpu-architecture-and-software-stack`
- `https://docs.vllm.ai/en/stable/getting_started/installation/gpu/`
- `https://github.com/vllm-project/vllm/releases`
- `https://vllm.ai/blog/blackwell-inferencemax`
- `https://vllm.ai/blog/dsr1-gb200-part1`
- `https://blog.vllm.ai/2026/02/01/gpt-oss-optimizations.html`
- `https://docs.livekit.io/agents/logic/turns/turn-detector/`
- `https://docs.livekit.io/agents/models/stt/plugins/nvidia/`
- `https://docs.livekit.io/reference/python/livekit/plugins/fishaudio/index.html`
- `https://livekit.com/blog/adaptive-interruption-handling`
- `https://livekit.com/blog/understand-and-improve-agent-latency`
- `https://livekit.com/blog/realtime-vs-cascade`
- `https://livekit.com/blog/sequential-pipeline-architecture-voice-agents`
- `https://livekit.com/blog/why-webrtc-beats-websockets-for-voice-ai-agents`
- `https://github.com/livekit/agents/releases`
- `https://community.livekit.io/t/released-livekit-agents-1-5-1/649`

