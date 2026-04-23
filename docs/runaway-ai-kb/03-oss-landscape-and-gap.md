---
title: Open-source AI-control landscape and the Prism-shaped gap
date: 2026-04-22
scope: Every relevant open-source project grouped by category, with what it covers and what it does not. The gap analysis at the end is the Prism-positioning-relevant payoff.
---

# OSS landscape and the Prism-shaped gap

## 1. AI-control and safety-eval frameworks

| Project | URL | Stars | Role |
|---|---|---:|---|
| Inspect AI (UK AISI) | https://github.com/UKGovernmentBEIS/inspect_ai | 1,939 | De-facto industry eval harness — solvers, scorers, tools, sandboxes, web UI |
| ControlArena (UK AISI + Redwood) | https://github.com/UKGovernmentBEIS/control-arena | 183 | Inspect-hosted AI-control protocol experiments |
| redwood-control-arena | https://github.com/redwoodresearch/redwood-control-arena | — | Redwood fork with additional settings + protocols |
| METR task-standard | https://github.com/METR/task-standard | 179 | Autonomy-eval task format — frozen 2025-02 |
| METR public-tasks | https://github.com/METR/public-tasks | 120 | 31 example tasks + 186 summaries |
| METR RE-Bench | https://github.com/METR/RE-Bench | 136 | ML research-engineering tasks |
| METR Vivaria | https://github.com/METR/vivaria | 136 | Self-hostable agent-elicitation runner |
| Anthropic evals | https://github.com/anthropics/evals | 369 | Stale (2024) |
| OpenAI Evals | https://github.com/openai/evals | 18,256 | Broadly used; static benchmark harness |
| Stanford HELM | https://github.com/stanford-crfm/helm | 2,758 | Leaderboard-oriented |
| MLCommons AILuminate + modelbench | https://github.com/mlcommons/ailuminate | 76 | Curated harm benchmark (CBRNE, hate, etc.) |
| NVIDIA garak | https://github.com/NVIDIA/garak | 7,613 | Scanner for known vulnerabilities (jailbreaks, leaks, encoding attacks) |
| Petri (Anthropic) | https://www.anthropic.com/research/petri-open-source-auditing | — | Parallel Exploration Tool for Risky Interactions — 111+ seed scenarios, v2 2026 |
| Bloom (safety-research) | https://github.com/safety-research/bloom | — | Automated behavioral evaluation |
| Anthropic attribution-graphs frontend | https://github.com/anthropics/attribution-graphs-frontend | — | Interp visualization |

**What this category covers well.** Pre-deployment evaluation — running a fixed benchmark or red-team probe against a model snapshot. Inspect AI provides the harness primitives (solvers, scorers, tools, sandboxes, Docker); ControlArena builds on Inspect with ~16 settings (Bash, AgentDojo, IAC, SHADE-Arena, vLLM, BigCodeBench, Data Poisoning), policies (honest / attacking / trusted / untrusted), micro-protocols (defer-to-trusted), and suspicion-score monitors. METR owns capability-elicitation benchmarking and time-horizon measurement. Petri is an auditor-agent framework — it runs 111+ scenarios and scores target model behavior along multiple safety dimensions.

**What it does not cover.** Nothing in this category is a *runtime* — none wraps a live deployed agent. Inspect AI has no built-in live-traffic surveillance, resource-consumption budgeting, or circuit-breaking. ControlArena is research infrastructure, not a production gate.

## 2. Agent observability / tracing

| Project | URL | Stars |
|---|---|---:|
| Langfuse | https://github.com/langfuse/langfuse | 25,630 |
| Arize Phoenix | https://github.com/Arize-ai/phoenix | 9,388 |
| traceloop OpenLLMetry | https://github.com/traceloop/openllmetry | 7,030 |
| Helicone | https://github.com/Helicone/helicone | 5,538 |
| Langtrace | https://github.com/Scale3-Labs/langtrace | 1,192 |
| W&B Weave | https://github.com/wandb/weave | 1,088 |
| LangSmith SDK | https://github.com/langchain-ai/langsmith-sdk | 859 |

**Signals captured.** All capture token counts, latency, cost, tool calls, and trace DAGs. Langfuse and Phoenix have agent-trajectory instrumentation; Helicone proxies and has rate-limit / usage-cap features; Phoenix has LLM-as-judge evals at runtime.

**What is not covered.** None is purpose-built for runaway-agent detection. No loop-detection, no policy enforcement, no behavioral circuit breaker. Helicone rate-limits are budget caps, not behavioral. Phoenix focuses on observability and evaluation, not real-time containment. The commercial equivalent with behavioral pattern detection is Galileo Signals; no OSS parallel as of April 2026.

## 3. LLM guardrails

| Project | URL | Stars | Scope |
|---|---|---:|---|
| NVIDIA NeMo Guardrails | https://github.com/NVIDIA-NeMo/Guardrails | 6,028 | Colang rails (input, dialog, retrieval, execution, output) |
| Guardrails AI | https://github.com/guardrails-ai/guardrails | 6,716 | Per-response validators (Validator Hub) |
| Protect AI llm-guard | https://github.com/protectai/llm-guard | 2,855 | 15 input + 20 output scanners |
| Lakera Guard (SaaS) | https://lakera.ai | — | Proprietary |
| LangChain safety chains | part of langchain | — | Legacy moderation |

**What they cover.** Per-request firewalls: prompt-injection classifiers, PII anonymization, toxicity filters, output schema validation. NeMo has execution rails for tool I/O.

**Gap.** These are single-request validators. A long-running agent that iterates 400 turns toward a subverted goal will pass every individual rail. Cross-turn reasoning-drift, tool-call goal-consistency, and resource-exhaustion circuit-breakers are not in scope for this category.

## 4. Red-team frameworks

| Project | URL | Stars |
|---|---|---:|
| Microsoft PyRIT | https://github.com/microsoft/PyRIT | 3,739 |
| NVIDIA garak | https://github.com/NVIDIA/garak | 7,613 |
| HarmBench (CAIS) | https://github.com/centerforaisafety/HarmBench | 931 |

Offensive / evaluator tools for model-level assessment. PyRIT is programmable multi-turn adversarial orchestration; garak is a probe scanner; HarmBench is a framework of 18 attacks × 33 target defenses (effectively frozen at v1.0 Feb 2024).

**Gap.** None produces a persistent runtime policy for a deployed agent. PyRIT's "multi-turn" red-teams the model; it does not watch a running production agent.

## 5. Formal AI-control research code

| Project | URL | Stars |
|---|---|---:|
| Redwood apps-monitor-control-eval | https://github.com/redwoodresearch/apps-monitor-control-eval | 1 |
| Redwood subversion-strategy-eval | https://github.com/redwoodresearch/subversion-strategy-eval | 10 |
| Redwood basharena_public | https://github.com/redwoodresearch/basharena_public | 10 |
| Redwood Measurement-Tampering | https://github.com/redwoodresearch/Measurement-Tampering | 8 |
| Redwood Text-Steganography-Benchmark | https://github.com/redwoodresearch/Text-Steganography-Benchmark | 25 |
| brucewlee/mini-control-arena | https://github.com/brucewlee/mini-control-arena | 15 |

The formal untrusted-monitoring experiments Redwood published in the control-evaluation line are scattered across small repos — research artifacts, not libraries. No maintained, production-grade library for running Trusted / Untrusted / Defer-to-Trusted protocols against live Claude or GPT traffic. ControlArena is the closest, but remains an Inspect-based experiment harness.

## 6. Sandbagging / deception detection

| Project | URL | Stars |
|---|---|---:|
| Apollo deception-detection | https://github.com/ApolloResearch/deception-detection | 40 |
| Apollo insider-trading | https://github.com/ApolloResearch/insider-trading | 58 |
| AISI sandbagging_auditing_games | https://github.com/AI-Safety-Institute/sandbagging_auditing_games | 5 |
| Redwood bench-af / bench-af-2 | https://github.com/redwoodresearch/bench-af-2 | 5 |

**Coverage.** Apollo's `deception-detection` trains linear probes on activations — **white-box only**, Llama in the public release; not applicable to Claude API. `insider-trading` is the GPT-4-strategic-deception corpus (prompts + completions, not a detector). AISI's `sandbagging_auditing_games` ships five model organisms (Cedar, Oak password-locked Llama-3.3-70B variants + benign baselines) for auditors to practice against. Redwood `bench-af-2` = alignment-faking model organisms + detectors + environments.

**Gap.** Every detector in this category is white-box probe-based or a testbed. No black-box sandbagging/deception detector usable as a drop-in runtime check against a closed API.

## 7. Capability-elicitation / dangerous-capability evals

| Project | URL | Stars |
|---|---|---:|
| METR public-tasks (ARA, R&D uplift) | https://github.com/METR/public-tasks | 120 |
| METR RE-Bench | https://github.com/METR/RE-Bench | 136 |
| Cybench | https://github.com/andyzorigin/cybench | 235 |
| WMDP (CAIS) | https://github.com/centerforaisafety/wmdp | 166 |
| BioLP-bench | https://github.com/baceolus/BioLP-bench | 6 |

Pre-deployment capability measurement. METR public-tasks explicitly includes autonomous replication, self-improvement, worm-development tasks framed as dangerous-capability elicitation. Cybench = 40 CTFs with subtask scoring (offensive cyber). WMDP = 3,668 MCQs over bio/cyber/chem hazardous knowledge plus RMU unlearning code. None is a runtime surveillance tool for deployed agents.

## 8. Where Prism sits — the unclaimed territory

Synthesizing the above: the OSS stack is mature at both ends (pre-deployment evals; per-request firewalls) and **hollow in the middle** — behavioral runtime control of live agent pipelines.

Six distinct gaps are unclaimed as of April 2026. Prism occupies a specific slice of this space.

### Gap A — Runtime AI-control SDK against closed APIs

ControlArena's protocols (Trusted / Untrusted / Defer-to-Trusted / Defer-to-Resample / Editing) exist only as Inspect research code. No library lets a developer wrap `client.messages.create(...)` and get a Trusted/Untrusted protocol in production — cheap-model monitor, suspicion score, action-layer gate. This is the single largest gap, and it is exactly Claude-API-shaped.

**Prism's relationship to gap A.** Prism implements a version of this for a narrow domain — GPU kernel auditing and HealthBench-Hard clinical reasoning. The attacker is the untrusted policy; the adjudicator is the monitor; the synthesizer is the trusted editor; the executor is the action layer; the defender supplies invariants the attacker tries to break. This is not a generic SDK yet; the protocol wiring is domain-specific. A future direction — post-hackathon — is to extract the protocol plumbing into a reusable library. For now, Prism is a proof that the protocol can be made real for a production target.

### Gap B — Cross-turn behavioral circuit-breakers

Guardrails catch bad single responses. Nobody catches a 200-turn agent slowly drifting from its stated goal, fabricating tool outputs, or silently escalating privilege. Signals worth monitoring include goal-consistency scoring (plan vs action), tool-argument distribution drift, "I'll just quickly..." escalation patterns, self-reference / meta-cognition spikes, and chain-of-thought / action divergence.

**Prism's relationship to gap B.** Not currently in scope; relevant if Prism lifts the double-gate for autonomous long-running sessions.

### Gap C — Black-box sandbagging / deception detection

Apollo and AISI both need white-box access or run in pre-deployment game settings. A PRISM-grade platform could ship ensemble behavioral detectors (paraphrase-invariance tests, consistency probes across framings, capability-floor canaries injected into real traffic) that work against any closed API.

**Prism's relationship to gap C.** Prism does not itself detect sandbagging in a third-party model; it is itself running Opus 4.7 in an adversarial role. Relevant to Prism as a *risk to be aware of*: the attacker agent could in principle sandbag (produce a weak counterexample while capable of producing a strong one). Today this is mitigated by (a) adjudicator external-rubric grading — a sandbagged attacker produces weak findings that fail adjudication — and (b) the fact that Opus-4.7 sandbagging on "try to break this invariant" tasks has no observed training-gradient incentive. Prism's existing discipline happens to shield against this failure mode, but not by design.

### Gap D — Resource / tool-abuse circuit breakers with economic framing

Helicone has rate limits; nobody has a per-agent budget that combines token spend, tool-call variety and rate, filesystem write volume, net-egress bytes, and credential scope into one composite runaway score that trips a policy action.

**Prism's relationship to gap D.** Budget ceilings in `CLAUDE.md` §9 are a business-logic form of this; Prism does not ship a runtime enforcer. Out of scope for current Prism.

### Gap E — Incident forensics and replay

Observability platforms trace the happy path. When an agent exfiltrates a secret or melts a cloud bill, timeline reconstruction, counterfactual replay with an alternative monitor, and diff against the baseline-policy version are all missing OSS-side.

**Prism's relationship to gap E.** Findings ship with an executed PoC log; (deterministic PoC validator, private) is a replay mechanism for one specific artifact class. Not a general forensics platform.

### Gap F — Managed-Agents-native control plane

Anthropic launched Managed Agents in beta April 2026. The beta ships with dashboards for sessions, costs, and credentials, but no behavioral control layer on top. Sandbagging canaries injected per session, Defer-to-Trusted wrappers on risky tools, per-thread runaway scores, and protocol audit logs would all be natural extensions.

**Prism's relationship to gap F.** Prism is Managed-Agents-native by construction — the `agents/*.yaml` + `scripts/register_agents.py` flow plus the pipeline-invariants check constitute a minimal control plane for the specific Managed Agents that Prism uses. This is narrower than a generic control plane; Prism is not selling itself as one.

## 9. What Prism is uniquely contributing

Pulling the six gaps together, the distinct contribution Prism makes to the OSS landscape is:

**An end-to-end demonstration that an adversarial multi-agent dialectic can be run against a production target (GPU kernels, HealthBench-Hard reasoning) with external-rubric grading on every load-bearing decision and an executed artifact per finding.** This is novel because:

1. The domain (GPU kernel semantic correctness, clinical-reasoning rubric deltas) is a real target, not a benchmark. Nobody has shipped LLM-driven kernel auditing with real-hardware PoC validation.
2. The discipline (no LLM-as-judge on load-bearing decisions; deterministic or third-party grading) is a stronger pattern than what the AI-control protocol literature specifies. The trust model makes no claim stronger than "the executor ran this and it did X" or "simple-evals scored this at Y."
3. The explicit mapping onto Redwood-family protocols makes Prism interpretable inside the AI-control research community, which gives it an upgrade path: protocols published after Prism lands can be dropped in as dialectic variants.

What Prism is not trying to be: a generic runtime AI-control SDK (gap A in the abstract), a cross-turn behavioral circuit-breaker (gap B), a black-box sandbagging detector (gap C), a resource-abuse monitor (gap D), a forensics platform (gap E), or a generic Managed Agents control plane (gap F). Those remain open for the field.

## 10. References

All URLs in this file are reproduced in `sources.md` with short annotations. The gap-analysis framing draws on competitive-landscape coverage from LangWatch 2026, Galileo 2026, Arize 2026, and the public announcements around Claude Managed Agents — also in `sources.md`.
