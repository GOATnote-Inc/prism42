---
title: Prism — Agent-Handoff Dispatch Prompts (H-phase)
date: 2026-04-21
scope: Dispatch-ready subagent prompts for the post-hackathon H-phase.
---

# Prism — Agent-Handoff Dispatch Prompts

Six dispatch-ready subagent prompts, one per H-phase epic from
`docs/clinical-roadmap.md` §7. Each H-file is self-contained: a future
session can copy the body into an Agent-tool invocation and the agent runs
with full context, frozen paths, inputs, outputs, verification command,
commit rule, and budget.

## How to dispatch

1. **Open the target H-file** (e.g. `H1.md`) and re-read the `Blocked by` block first.
2. **Confirm blockers have cleared** by checking the parent tasks — e.g. D3 landed, T4.7c landed, disclosure embargo lifted. Do not dispatch if any blocker is still open.
3. **Copy the body into an Agent-tool invocation** with `isolation: "worktree"` where the H-file touches disjoint files (all six do, by construction). The H-file's "Spec cross-reference" block lists the docs the subagent must read first.
4. **Follow the verification command on return** — the agent's commit is only accepted if the verification command in the H-file exits 0, and `make verify-all` still exits 0.

## Index

| ID | Description | Status | Blockers |
|---|---|---|---|
| H1 | MedAgentBench extension (agentic clinical-rail corpus, FHIR verifier, 3-trial reproducibility) | pending | D3, T4.7c |
| H2 | Third-rail proposal (three candidates: legal, bioinformatics kernels, formal verification) | pending | D3 |
| H3 | Preprint: adversarial-dialectic auditing across two targets (arXiv draft, figures from `results/`) | pending | T4.7c, H1 |
| H4 | Public harness skeleton release (`prism-skel` — schemas + patterns, no private corpus) | pending | D3, disclosure embargo lift |
| H5 | Model-behavior disclosure workflow automation (packet prep for Anthropic feedback channel; human-gated send) | pending | P5, T4.7c |
| H6 | Physician cohort scale-up (30 to 300 HealthBench Hard examples with κ ≥0.6 adjudication overlay) | pending | D3, budget |

## Cross-reference

- `CLAUDE.md` §7 — Subagent dispatch protocol (the seven-field contract these files mirror).
- `docs/clinical-roadmap.md` §7 — H-phase normative spec (size estimates and budgets quoted in these files originate here).
- `docs/clinical-roadmap.md` §9 — Agent-handoff protocol template these files implement.
