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

