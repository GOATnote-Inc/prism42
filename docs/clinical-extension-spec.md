---
title: Prism — Clinical Target Extension
status: Draft for handoff
date: 2026-04-21
scope: Add a second audit target (clinical reasoning) to the existing Prism harness, gated behind T4 completion of the kernel target.
hard_constraint: All work is new work started during the hackathon window (Apr 21–26, 2026). No code, corpus, methodology, or written artifacts may be imported from outside `~/prism/` created today.
---

# Prism — Clinical Target Extension

## 1. Thesis and hackathon framing

Prism's core contract: **"Every finding ships with a runnable proof-of-concept we executed on real infrastructure before reporting."** That contract doesn't depend on what's being audited. This extension demonstrates it by applying the same five-agent harness to a second domain — clinical reasoning — with a different executor backend.

Two domains, one harness, one cinematic methodology beat in the demo video. This targets the **"Keep Thinking" side prize** ("didn't stop at the first idea — landed somewhere nobody saw coming") and the **Impact 30%** rubric (the methodology ports). It also opens the door to the **"Best use of Managed Agents" side prize** — see §4.5.

The hackathon problem-statement fit is **"Build From What You Know"**: an emergency physician noticed the failure modes of GPU kernels (numerical, boundary, race) map structurally onto the failure modes of clinical reasoning (premature closure, context loss under distraction, safety-rail bypass) — and built one harness that audits both.

**This extension does not reduce the GPU primary.** It is gated: no work on clinical target begins until the T4 FA-corpus validation gate passes (≥80% recall on known-fixed bugs, ≤20% false-positive rate). If T4 slips past Friday local time, the clinical extension is cut, Prism ships single-target, and no apology is owed — the gate exists precisely to prevent scope-creep regret.

---

## 2. Benchmarks verified

Claude Code should treat the following as ground truth and re-verify any number before citing on camera.

**HealthBench / HealthBench Hard** is an OpenAI benchmark released May 2025. Full HealthBench is 5,000 multi-turn physician-written conversations scored by rubric. HealthBench Hard is a 1,000-example subset designed to be unsaturated. The top frontier-model score at release time was 32%; HealthBench Hard provides headroom for the next generation of models. Data and reference code are released in OpenAI's `simple-evals` repository. Canonical public baseline numbers: GPT-5 0.46, GPT-5.2 0.42, GPT-5.1 0.40, Grok 3 0.23, Gemini 2.5 Pro 0.19, Claude 3.7 Sonnet 0.02. **Claude Opus 4.7 has no publicly reported HealthBench Hard score as of Apr 21, 2026 — establishing that baseline is the headline empirical contribution of this extension.**

**MedAgentBench** is a Stanford ML Group benchmark published in NEJM AI. 300 clinician-authored tasks across 10 categories, FHIR-compliant environment with 100 de-identified patient profiles and 700,000+ data elements. Claude 3.5 Sonnet v2 leads at 69.67%. Docker image `jyxsu6/medagentbench` exposes a local FHIR server on port 8080.

**Treat MedAgentBench as stretch, not must.** HealthBench Hard baseline alone suffices for the demo. MedAgentBench lands only if the Docker environment comes up clean on first try and baseline runs in under 90 minutes. Otherwise move to post-hackathon retrospective.

---

## 3. ElevenLabs role

Voice is a **demo surface**, not a dependency. Not on the critical path.

ElevenLabs Conversational AI supports custom LLM servers via OpenAI-compatible SSE endpoints at `/v1/chat/completions` or `/v1/responses`, which lets you route an ElevenLabs agent to your own LLM backend. Same adversarial-dialectic harness could power a voice endpoint. Standing it up is ~3–4 hours and only runs if everything else has landed cleanly by Saturday afternoon.

Build the voice demo iff: HealthBench Hard baseline + harness-modified run both landed green, and the 3-minute video is already cut. Otherwise skip. Voice is the bow.

---

## 4. Architecture additions (Managed Agents shape)

**Verified against `platform.claude.com/docs/en/managed-agents/{overview,multi-agent,sessions}` on 2026-04-21.** All deltas below follow the four-primitive model (**Agent / Environment / Session / Events**) and require the beta header `managed-agents-2026-04-01` on every request. Additionally set `task-budgets-2026-03-13` so Claude has visibility into remaining budget across the agentic loop. **Multi-agent coordination is a research-preview feature; account has access confirmed 2026-04-21.** The SDK sets the additional research-preview beta header automatically — verify via request-debug at implementation time.

### 4.1 Map Prism's five roles onto the Managed Agents primitive set

Each of Prism's five dialectic roles becomes one **Agent** (defined once, referenced by ID). A sixth agent — `prism-coordinator` — orchestrates them via the `agent_toolset_20260401` tool and a `callable_agents` declaration.

| Prism role | Agent definition | Tools surfaced | Role in session |
|---|---|---|---|
| `prism-coordinator` | System prompt: "audit one finding end-to-end. Call defender→attacker→synthesizer, then executor twice (baseline, modified), then adjudicator. Return the verdict." | `agent_toolset_20260401`, file ops. `callable_agents`: [defender, attacker, synthesizer, executor, adjudicator]. | Primary thread. |
| `prism-defender` | System prompt: "derive the invariant this artifact must uphold." | None (pure reasoning). | Spawned thread. |
| `prism-attacker` | System prompt: "craft a minimal adversarial perturbation that could violate the invariant." | None (pure reasoning). | Spawned thread. |
| `prism-synthesizer` | System prompt: "package defender + attacker outputs as a runnable eval case." | File ops (write to `/workspace/<case_id>/case.yaml`). | Spawned thread. |
| `prism-executor` | System prompt: "run Opus 4.7 against the supplied case configuration, capture the response verbatim to the supplied scratchpad path." | Bash, file ops, web fetch, custom MCP server (`prism-mcp`) exposing `ssh_exec` for GPU target and `anthropic_messages` for clinical target. | Spawned **twice per finding** — baseline thread + modified thread, each persistent. |
| `prism-adjudicator` | System prompt: "apply the rubric to baseline + modified responses, emit verdict: confirmed_delta / no_delta / regression." | File ops (read `/workspace/<case_id>/{baseline,modified}.json`), rubric-grader MCP. | Spawned thread. |

All threads share **one Environment**: container template with Python 3.14, `simple-evals` cloned into `/opt/simple-evals`, `anthropic` + `openai` SDKs, network egress restricted to `api.anthropic.com`, `api.openai.com`, and the GPU bastion host. Coordinator's `callable_agents` field pins each sub-agent by `{id, version}` — version-pinning is critical for demo reproducibility.

### 4.2 Session topology: one coordinator session per finding, six threads, shared filesystem

**Ship (with multi-agent access):** one Session per finding, created on `prism-coordinator`. Inside that session, the coordinator spawns up to six threads (defender, attacker, synthesizer, executor×2, adjudicator). All threads share the session's container and `/workspace/<case_id>/` directory — the scratchpad contract maps natively onto the shared filesystem. One-level-of-delegation limit does not hurt us: no sub-agent needs to spawn further sub-agents.

**Parallelism.** The coordinator can call callable-agents in parallel inside its thread. Dependency graph:
```
defender ──┐
           ├── synthesizer ── executor(baseline) ──┐
attacker ──┘               └─ executor(modified) ──┴── adjudicator
```
`defender` and `attacker` run in parallel. The two `executor` invocations run in parallel (distinct persistent threads on the same agent). Wall-clock per finding ≈ max(defender, attacker) + synthesizer + max(baseline, modified) + adjudicator ≈ ~8 minutes.

**Cross-finding parallelism.** 30 coordinator sessions spawn client-side in parallel, subject to the 60 creates/min rate limit. The sweep drops from serial (~4h) to ~10min wall-clock.

**Durability demo.** Session state persists through disconnects: kill the client mid-sweep, reattach via `/v1/sessions/:id/stream`, in-flight sessions keep running. This is the §4.5 "Best use of Managed Agents" beat.

### 4.3 Rail selection (per-finding)

The executor's Agent is identical across both targets. The target split happens in the **initial `user.message` event** sent to the coordinator when the session is created:

```json
{
  "target_domain": "gpu" | "clinical",
  "case_id": "KERNEL-BD-037" | "HBH-CLN-012",
  "invariant": "<defender output>",
  "perturbation": "<attacker output>",
  "rubric_ref": "corpus/kernel_bugs.yaml#KERNEL-BD-037" | "corpus/clinical_subset.yaml#HBH-CLN-012"
}
```

The coordinator passes `target_domain` down to the executor threads via their initial user messages. Executor branches on `target_domain`: for `gpu` it calls `prism-mcp.ssh_exec`; for `clinical` it calls `prism-mcp.anthropic_messages` and then the grader MCP. Same agent, same `/workspace` protocol, same `--expect` verification discipline.

### 4.4 What does NOT change

- Five agent prompts: no edits for the clinical extension except adding the rail-selection clause to the executor prompt (`if target_domain == "clinical": …`).
- Scratchpad contract: `/workspace/<case_id>/{invariant.md, perturbation.md, baseline.json, modified.json, verdict.json}`. Same across both targets.
- Disclosure playbook for GPU findings: unchanged.
- Clinical findings get a separate disclosure path documented in `docs/clinical-handling.md` — thumbs-down + direct Anthropic feedback email, not GHSA/CVE. Model-behavior ≠ kernel code.

### 4.5 Branding guardrail

Anthropic's Managed Agents branding guidelines (verified 2026-04-21) prohibit calling derivative products "Claude Code" / "Claude Code Agent." "Prism" is fine. Demo narration and README must avoid "Claude Code Agent" framing when describing the harness. Use "Prism, powered by Opus 4.7 on Claude Managed Agents."

---

## 4.5 Multi-prong prize surface

The hackathon pool is $100K; five surfaces are worth pursuing. Prism can credibly contend for three of them without additional scope, and a fourth with the voice demo:

| Prize | $ | Fit | What we already have | What's missing | Marginal cost |
|---|---|---|---|---|---|
| **1st / 2nd / 3rd** | $50K / $30K / $10K | Headline: GPU primary × clinical extension × demo polish. | All four rubric axes (Impact, Demo, Opus 4.7 Use, Depth). | 3-min video cut + README. | Hours for demo craft. |
| **Best use of Managed Agents** | $5K | §4 is a literal answer to the prompt: multi-agent coordination (research preview), per-finding durable sessions, six-thread fan-out in shared container, MCP tools, hand-off of genuinely long work (full sweep). | Multi-agent is already the core executor topology. | A 20-second demo beat: split-screen showing six thread streams on one session, then disconnect + reconnect demonstrating durability. | Hours; beat is written into T4.8. |
| **"Keep Thinking" Prize** | $5K | The dual-target generalization IS the "didn't stop at the first idea" move. | The extension itself. | One slide or doc (`docs/dual-target-thesis.md`) with the failure-taxonomy crosswalk. | Hours. |
| **Most Creative Opus 4.7 Exploration** | $5K | Voice demo (T4.9) + adversarial-dialectic-as-medium framing. | Harness. | ElevenLabs voice surface that actually hits the 4s RT bar. | 3–4 hours; optional. |

**Interaction effects.** The Managed Agents prize and Keep Thinking prize are stackable with a top-3 placement (past years have awarded side prizes to top-3 teams). Creative is weaker: voice is a demo risk on latency. Don't sacrifice video polish for it.

**What to cut first if time goes sideways:** (1) MedAgentBench → cut. (2) Voice surface → cut. (3) Multi-agent parallel sweep → cut (run serial). (4) Clinical extension → cut (ship GPU-only). In that order. The top-3 podium bid survives cutting #1–#3. The Managed Agents side-prize survives cutting #2–#4. The Keep Thinking prize requires the clinical extension.

---

## 5. Tasks, gates, and verification

Every task has a verification step. The rule: a task is not "done" until its verification returns a machine-checkable success, and that success is printed where a human can see it during demo rehearsal.

### T4.5 — Clinical corpus manifest + Prism Agent definitions

**Gate-blocked by:** T4 pass (kernel harness ≥80% recall, ≤20% FP on FA bug corpus).

**Scope:**
1. Select 30 HealthBench Hard examples. Distribution: 10 emergency/urgent, 5 pediatric, 5 OB/GYN, 5 psych/behavioral, 5 general medicine. File format mirrors `corpus/kernel_bugs.yaml`: per-example `id`, `healthbench_hard_example_id`, `class` (shared taxonomy), `target_axis` (accuracy | completeness | context_awareness | instruction_following | communication), `expected_failure_mode` (physician-written one-liner, new text).
2. Define six Managed Agent Agents via the Managed Agents create-agent endpoint: `prism-defender`, `prism-attacker`, `prism-synthesizer`, `prism-executor`, `prism-adjudicator`, `prism-coordinator`. Create sub-agents first; their `{id, version}` pairs feed the coordinator's `callable_agents` list. Coordinator's tool list includes `{"type": "agent_toolset_20260401"}`. Store all agent IDs and versions in `agents/manifest.yaml`. Define the shared Environment (`prism-standard-env`). All creation requests include the `managed-agents-2026-04-01` and `task-budgets-2026-03-13` beta headers; SDK handles the research-preview beta header for multi-agent.

**Write as:**
- `corpus/clinical_subset.yaml` (v0.1.0, same structure as FA manifest)
- `agents/prism-{defender,attacker,synthesizer,executor,adjudicator,coordinator}.yaml` (source of truth; IDs + versions filled post-create)
- `agents/manifest.yaml` (post-create ID+version lookup)
- `environments/prism-standard-env.yaml`

**Verification step:**
```makefile
verify-clinical-corpus:
    @ruby -ryaml -e '\
      d = YAML.load_file("corpus/clinical_subset.yaml"); \
      raise "expected 30 examples" unless d["examples"].length == 30; \
      axes = d["examples"].map { |e| e["target_axis"] }.uniq; \
      raise "missing axes" unless (axes & %w[accuracy completeness context_awareness instruction_following communication]).length >= 3; \
      puts "clinical corpus: 30 examples, #{axes.length} axes, OK"'

verify-agents-registered:
    @python scripts/verify_agents.py --manifest agents/manifest.yaml
    # must print: "6 agents registered (5 sub + 1 coordinator); callable_agents resolved; 1 environment; beta headers set; OK"
```
Both must print before the next task starts.

### T4.6 — HealthBench Hard ingestion and baseline

**Scope:** Clone `openai/simple-evals` to `~/prism/third_party/simple-evals` (license: Apache 2.0, attribute in `NOTICE`). Write `scripts/healthbench_runner.py` that:
1. Loads the 30 example IDs from `corpus/clinical_subset.yaml`.
2. Calls **Claude Opus 4.7 via Messages API** (baseline is direct API, no Managed Agents — we're measuring the model, not the harness).
3. Grades each response against the HealthBench rubric using `simple-evals`' shipped grader.
4. Writes per-example scores + aggregate to `results/baseline-opus47-{timestamp}.json`.

**Verification step:** Run twice on same seed. Aggregate must be within ±0.02 on rerun — if not, grader is non-deterministic and methodology is broken. Spot-check three results by hand: print question, Opus 4.7 response, rubric items, grader's score.

```makefile
verify-baseline:
    @python scripts/healthbench_runner.py --manifest corpus/clinical_subset.yaml --out results/baseline-1.json --seed 42
    @python scripts/healthbench_runner.py --manifest corpus/clinical_subset.yaml --out results/baseline-2.json --seed 42
    @python scripts/compare_runs.py results/baseline-1.json results/baseline-2.json --tolerance 0.02
    @python scripts/spot_check.py results/baseline-1.json --n 3
```
Must print `baseline reproducible (delta=X.XXX < 0.02), spot-check passed` before proceeding.

**Budget:** 30 × ~$0.50 = ~$15 per baseline run. Two runs = $30. Hard cap $50.

### T4.7 — Harness-driven intervention (Managed Agents)

**Scope:** Run the coordinator-driven dialectic over 30 examples in parallel.

For each finding:
1. **Client** creates a coordinator session via `POST /v1/sessions` with `{agent: prism-coordinator-id, environment_id}`. Session status starts `idle`.
2. **Client** posts an initial `user.message` event with the case config (`target_domain`, `case_id`, `healthbench_hard_example_id`, `expected_failure_mode`, rubric ref).
3. **Coordinator** opens `/workspace/<case_id>/`, then invokes callable-agents in the dependency order described in §4.2. Each invocation spawns a thread; coordinator tracks `session_thread_id` in its turn.
4. **Client** streams the primary session event stream (`/v1/sessions/:id/stream`), listens for `session.thread_created`, `agent.thread_message_sent`, `session.thread_idle` events, and logs per-thread progress. Optionally streams individual threads for demo visibility.
5. **Coordinator** returns final verdict when adjudicator thread completes.
6. **Client** aggregates all 30 session outputs into `results/harness-{timestamp}.json`.

Parallel fan-out: 30 sessions spawned client-side under the 60 creates/min rate limit (batched in two waves of 15, 60s apart, or trickled). Each session ≈ 8 min wall-clock. Total sweep ≈ 10–12 min.

Write `scripts/harness_runner.py` using the `anthropic` Python SDK's `beta.sessions` and `beta.agents` namespaces — SDK auto-sets both beta headers.

**Verification step:** Harness run must produce non-zero `confirmed_delta` count and zero `regression` unless regressions are real findings (in which case surface them). Also verify durability: kill the runner mid-sweep, restart, reattach to in-flight session IDs via `GET /v1/sessions/:id` + re-stream, confirm they're still `running` or transitioned to `idle` on the server side.

```makefile
verify-harness:
    @python scripts/harness_runner.py --manifest corpus/clinical_subset.yaml --baseline results/baseline-1.json --out results/harness.json
    @python scripts/delta_report.py results/baseline-1.json results/harness.json
    @python scripts/verify_session_durability.py --sample 3
    # must print: "harness delta: baseline=0.XXX, modified=0.YYY, confirmed_improvements=N, regressions=M"
    # must print: "session durability: 3/3 sessions survived client kill; reattach OK"
```

**Budget cap:** $100. Managed Agents session-runtime overhead: each coordinator session runs ~8 min with up to 6 concurrent threads. Billing is per-thread runtime, so effective session-hours ≈ 6 × 8 min = 48 thread-min ≈ 0.8 thread-hr per finding × 30 findings = 24 thread-hours × $0.08 = **$1.92 session overhead total**. Token cost still dominates. If at $100 the harness isn't producing a reportable delta, stop — hypothesis didn't land cleanly in the window. Fall back to showing methodology on a single walked-through example.

### T4.8 — Demo cut (clinical beat, 30 seconds; Managed Agents beat, 20 seconds)

**Scope:** Two beats in the 3-minute video.

**Clinical beat (0:30):** Harness running on one HealthBench Hard example end-to-end. Pick the example with the largest confirmed delta. Voiceover: "Same five agents. Same scratchpad. Different target. Defender asserts a clinical invariant. Attacker finds a case where baseline Opus 4.7 violates it. Harness proposes a modification. Modified Opus 4.7 passes the rubric. Delta: +0.XX on this example, +0.YY aggregate across 30."

**Managed Agents beat (0:20):** Two shots.
- Shot 1 (10s): single coordinator session dashboard with six thread streams visible simultaneously — defender, attacker, synthesizer, executor-baseline, executor-modified, adjudicator — all writing to the same `/workspace/<case_id>/` directory. Voiceover: "One session. Six threads. Shared filesystem. Multi-agent coordination doing the orchestration Opus would otherwise have to do in a single context window."
- Shot 2 (10s): runner on laptop A mid-sweep; close laptop A; laptop B reattaches to the same session IDs via `GET /v1/sessions/:id/stream`, threads are still running. Voiceover: "Durable. Survives disconnect. This is what makes it shippable, not a demo."

**Verification:** Watch the cut cold the next morning. Time each beat with a stopwatch. Clinical beat >40s → trim. Managed Agents beat >25s → trim. GPU primary remains the hero.

### T4.9 (optional) — ElevenLabs voice surface

**Gate-blocked by:** T4.8 shipped, video cut reviewed, ≥4 hours remaining before submission.

**Scope:** Stand up an OpenAI-compatible SSE endpoint (`/v1/chat/completions`) that wraps the harness: incoming message → adversarial check → Opus 4.7 → return. Point an ElevenLabs agent at this endpoint via custom-LLM config. Record 20-second clip.

**Verification:** End-to-end latency ≤4s. The adversarial check adds 1–3s. If round-trip exceeds 4s, either cut the adversarial check for the voice demo (narrate that it runs async in the production path) or cut voice entirely.

**Skip signal:** If this eats demo-cut time, cut immediately.

---

## 6. File additions summary

```
~/prism/
├── corpus/
│   └── clinical_subset.yaml            # T4.5, new
├── agents/
│   ├── prism-coordinator.yaml          # T4.5, new (orchestrator; callable_agents pinned)
│   ├── prism-defender.yaml             # T4.5, new
│   ├── prism-attacker.yaml             # T4.5, new
│   ├── prism-synthesizer.yaml          # T4.5, new
│   ├── prism-executor.yaml             # T4.5, new (invoked twice per finding: baseline + modified threads)
│   ├── prism-adjudicator.yaml          # T4.5, new
│   └── manifest.yaml                   # T4.5, new (post-create {id, version} lookup per agent)
├── environments/
│   └── prism-standard-env.yaml         # T4.5, new
├── scripts/
│   ├── healthbench_runner.py           # T4.6, new
│   ├── harness_runner.py               # T4.7, new (Managed Agents SDK)
│   ├── verify_agents.py                # T4.5 verification, new
│   ├── verify_session_durability.py    # T4.7 verification, new
│   ├── compare_runs.py                 # T4.6 verification, new
│   ├── spot_check.py                   # T4.6 verification, new
│   └── delta_report.py                 # T4.7 verification, new
├── third_party/
│   └── simple-evals/                   # T4.6, cloned, Apache 2.0, attributed in NOTICE
├── results/
│   ├── baseline-opus47-*.json          # T4.6 outputs, gitignored
│   └── harness-*.json                  # T4.7 outputs, gitignored
├── docs/
│   ├── clinical-handling.md            # T4.5, new; disclosure posture for model-behavior findings
│   ├── dual-target-thesis.md           # T4.5, new; failure-taxonomy crosswalk (also the Keep-Thinking artifact)
│   └── clinical-extension-spec.md      # this file
└── src/
    └── executor.md                     # T4.6, modified; add clinical branch + managed-agents session creation
```

`results/` gitignored. `findings/private/` untouched by this extension.

---

## 7. Budget envelope

- T4.6 baseline runs: up to $50 (token cost only)
- T4.7 harness runs: up to $100 (tokens + Managed Agents session-hr overhead; overhead is noise at $1.80)
- T4.8 demo cut: no spend
- T4.9 voice surface: ~$10 (ElevenLabs free-tier typically sufficient for 20s cut)

**Total cap for this extension: $160.** Hard stop regardless of progress.

---

## 8. Standing rules

- **Verify every action.** Every task has explicit verification. If a new task doesn't, don't run it.
- **Don't block on external approvals.** Multi-agent research-preview access is an **upgrade path**, not a dependency. Serial sweep with default-on beta is the primary plan.
- **Credentials are leaked the moment they're downloaded.** Anthropic API key via `.env`; never read the file into context.
- **All spend has a cap.** Named above. Hard stop.
- **New work only.** Nothing in `~/prism/` predates Apr 21, 2026 afternoon. This extension respects that.
- **Branding:** never call Prism or any subcomponent "Claude Code" / "Claude Code Agent." Use "Powered by Opus 4.7 on Claude Managed Agents."

---

## 9. The one-liner for the written submission

*"Prism is an Opus 4.7 harness running on Claude Managed Agents multi-agent coordination that audits two targets — GPU kernels and clinical reasoning — with one methodology: every finding ships with a runnable proof-of-concept we executed on real infrastructure before reporting. On the GPU side, we ran against open-source attention kernels on flagship accelerator hardware. On the clinical side, we established the first public HealthBench Hard baseline for Opus 4.7 and a harness-driven delta on 30 physician-weighted scenarios. Each finding is one coordinator session that fans out to six callable-agent threads on a shared container — durable, parallel, resumable after disconnect."*

That sentence leads the submission README.

---

## 10. What Claude Code should not do

- Do not start T4.5 before T4 (kernel corpus validation) passes.
- Do not attempt MedAgentBench until HealthBench Hard is shipping green.
- Do not import methodology, corpus items, or code from any repo outside `~/prism/`.
- Do not edit the GPU primary's agent prompts when adding the clinical backend. Rail selection lives in the `target_domain` initial-event branch on the executor; other four prompts untouched.
- Do not ship a voice demo >4s round-trip. Skip clean.
- Account has multi-agent research-preview access (confirmed 2026-04-21) — use it. Fallback to single-agent session topology only if a specific agent-create or session-create call returns a feature-gating error, in which case reconfigure `prism-coordinator` to invoke sub-agents sequentially via direct Messages API from within its own thread.
- Do not brand anything "Claude Code Agent."

---

## 11. Verification log (update as sources are re-checked)

| Source | URL | Fetched | Relevant facts |
|---|---|---|---|
| Managed Agents overview | `platform.claude.com/docs/en/managed-agents/overview` | 2026-04-21 | 4 primitives (Agent/Environment/Session/Events); beta header `managed-agents-2026-04-01`; rate limits 60 creates/min, 600 reads/min; multi-agent is research preview; built-in tools: Bash/file ops/web/MCP. |
| Managed Agents multi-agent | `platform.claude.com/docs/en/managed-agents/multi-agent` | 2026-04-21 | **Coordinator with `callable_agents` field; tool type `agent_toolset_20260401`; ONE-LEVEL delegation only (callable agents can't nest); threads are persistent — repeat calls to same agent create separate persistent thread each time; all threads share session container + filesystem; event types `session.thread_created`, `session.thread_idle`, `agent.thread_message_sent`, `agent.thread_message_received`; list threads at `/v1/sessions/:id/threads`; stream thread at `/v1/sessions/:id/threads/:thread_id/stream`.** |
| Managed Agents sessions | `platform.claude.com/docs/en/managed-agents/sessions` | 2026-04-21 | Create: `POST /v1/sessions` with `{agent, environment_id}`; pin version via `{type:"agent", id, version}`; MCP auth via `vault_ids`; statuses: idle/running/rescheduling/terminated; archive + delete endpoints; running sessions cannot be deleted — interrupt first. |
| Managed Agents blog (product) | `claude.com/blog/claude-managed-agents` | 2026-04-21 | Pricing $0.08/session-hr + standard token rates; persistent state across disconnects; multi-agent coordination in research preview. |
| Managed Agents engineering post | `anthropic.com/engineering/managed-agents` | 2026-04-21 | "Brain vs hands" decoupling; session API primitives (`getEvents`, `emitEvent`, `getSession`, `wake`); container provisioning is lazy (60% p50 / 90%+ p95 TTFT improvement). |
| Task budgets beta | Anthropic docs | 2026-04-21 | Separate beta header `task-budgets-2026-03-13`; gives Claude visibility into remaining budget across agentic loop. Worth pairing with Managed Agents header on every request. |

Re-verify any fact in §4 before quoting it on camera or in the submission README.
