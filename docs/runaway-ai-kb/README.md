---
title: Prism runaway-AI knowledge base
date: 2026-04-22
audience: Prism maintainer + future sessions + judges reading the repo cold
scope: Technical reference on runaway-AI concepts, the Claude API control surface, and where Prism sits in the open-source landscape. Complements — does not replace — `safeguards.md` (clinical rail) and `disclosure-playbook.md` (kernel rail).
---

# Runaway-AI knowledge base

## Why this file exists

Prism is a five-agent Opus-4.7 dialectic that, by design, runs one agent (`attacker`) whose job is to produce counterexamples that break invariants, passes them to another agent (`synthesizer`) whose job is to write executable code, hands them to a third (`executor`) that runs that code on a real H100 or Trainium instance over SSM. The architecture is useful precisely because it is adversarial, and it is risky for the same reason. The question this KB answers: **what does the field know about running adversarial AI pipelines without losing containment, and which Claude API primitives implement the answer.**

Three distinct audiences are served:

1. A future Claude session resumes Prism work, needs to orient quickly on why the architecture is what it is, and which API features it depends on.
2. A maintainer adding a new rail, a new tool, or raising the autonomy ceiling (e.g. lifting the double-gate, adding a non-coordinator Managed Agent) needs to know which operational signals and mitigations apply.
3. A judge or reviewer reading the repo cold wants one place that cites the AI-control literature Prism's design is drawn from, without the design document repeating the citations.

## The three insights that apply directly to Prism

### Insight 1 — Prism's five-agent dialectic is an implementation of Redwood's AI Control protocol

Greenblatt, Shlegeris, Sachan, Roger 2023 (*AI Control: Improving Safety Despite Intentional Subversion*, arXiv:2312.06942) define a protocol family — Trusted Monitoring, Defer-to-Trusted, Trusted Editing, Defer-to-Resample — for running an untrusted-but-capable model under oversight of a trusted-but-weaker model plus a small human audit budget. Prism's roles map onto this protocol almost one-to-one:

| Redwood AI Control role | Prism agent | Notes |
|---|---|---|
| Untrusted policy (generates actions) | `attacker` | Generates adversarial inputs and candidate counterexamples |
| Trusted monitor (scores suspicion) | `adjudicator` | External-rubric-graded scoring; no self-grading |
| Trusted editor (rewrites suspicious outputs) | `synthesizer` | Packages the attacker's informal claim into a compilable PoC |
| Action layer (effects the world) | `executor` | Runs on real H100 / Trainium via SSM |
| Trusted weak model (asserts invariants) | `defender` | Derives kernel invariants / clinical reasoning invariants |
| Coordinator | `coordinator` | Enforces protocol ordering; owns shared `/workspace` |

The consequence is that the AI-control literature is directly predictive of which protocol variants Prism could add (Defer-to-Resample = resample the attacker's output when suspicion is high; Editing = let synthesizer modify attacker output before execution), and where the known attacks on these protocols (Mallen et al. 2025, adaptive attacks on trusted monitors; Wen et al. 2025, TraceGuard collusion resistance) should be stressed.

See `04-prism-architecture-mapping.md` for the full mapping, including where Prism's discipline (PoC-validator gate, external rubric grader, no self-grading) is a stronger pattern than what the protocols themselves specify.

### Insight 2 — the Claude API already provides the control levers Prism needs; the gap is orchestration, not primitives

The Messages API's `stop_reason` enum, the thinking-budget and signed-thinking-block mechanics, `tool_choice` and `allowed_callers` on tool definitions, streaming deltas for mid-generation inspection, prompt-cached constitutional constraints, Batch API for pre-deployment redteam, and Managed Agents session interruption collectively cover every layer from "refuse before emission" to "kill a long-running agent mid-thought." Prism's existing double-gate (`--commit` flag plus `PRISM_*_COMMIT=1` env var, AST-verified SDK containment) is a clean external-shell; what remains available is richer in-flight monitoring of a single session — streaming token-rate thresholds, tool-call validation gates before execution, refusal-on-stop-reason escalation.

See `02-claude-api-control-levers.md` for the full list, with PRISM-shape code patterns (not importable; illustrative) for each.

### Insight 3 — the OSS gap Prism sits inside is real and is concretely Managed-Agents-shaped

The open-source world has thoroughly covered (a) pre-deployment capability and safety benchmarks (Inspect AI, METR task-standard, HarmBench, WMDP, Cybench), (b) academic control experiments (ControlArena, Redwood subversion-strategy-eval), (c) per-request firewalls (NeMo Guardrails, Guardrails AI, llm-guard, Lakera Guard), and (d) general LLM observability (Langfuse, Arize Phoenix, OpenLLMetry). **What is missing** is a runtime AI-control SDK that lives on top of a closed API, wraps `client.messages.create(...)` with a cheap-model monitor, emits suspicion scores, and gates action-layer effects. ControlArena is Inspect-harness research code, not a library; the Redwood untrusted-monitoring experiments are scattered across <10-star repos. Prism's execution-artifact-per-finding discipline is a distinct contribution to this gap.

See `03-oss-landscape-and-gap.md` for the full competitive survey.

## Reading order

For a new session, read in this order:

1. This file (you are here).
2. `01-taxonomy-and-signals.md` — concepts and operational detection signals. Reference material; skim on first pass.
3. `04-prism-architecture-mapping.md` — the unique synthesis. The most Prism-specific file.
4. `02-claude-api-control-levers.md` — what the API gives you. Reference; consult when adding features.
5. `03-oss-landscape-and-gap.md` — where Prism sits vs existing projects. Consult when positioning or disclaiming scope.
6. `sources.md` — every citation, annotated. Look up specific papers from here.

## What this KB is not

- It is not a threat model for any specific Prism deployment. That lives in `SECURITY.md` and `docs/disclosure-playbook.md`.
- It is not the clinical-rail safeguards document. That is `docs/safeguards.md`.
- It is not operational runbook material. Cost ceilings, commit discipline, verification layers belong in `CLAUDE.md`.
- It does not propose new code paths. Where a pattern maps onto Prism, the mapping cites paths like `agents/prism-attacker.yaml` or `scripts/harness_runner.py` by name; it does not write them.

## Maintenance

This KB is a reference, not a roadmap. Update it when a new paper meaningfully changes a mapping (Insight 1, the taxonomy tables) or when Claude adds a new API primitive that Prism could use (Insight 2). Do not update it for every incremental system card release — `sources.md` has a "generational markers" section for those.

Last research sweep: 2026-04-22.
