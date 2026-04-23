---
title: Prism — Dual-Target Thesis
date: 2026-04-21
status: Draft
scope: Why one adversarial-dialectic harness audits both GPU kernels and clinical reasoning — failure-taxonomy crosswalk.
---

## 1. Opening

An emergency physician spends a career watching two things fail: instruments at a scale boundary, and reasoning at a scale boundary. The observation that seeded Prism is that those failures share a structure. The same adversarial-dialectic harness that audits open-source attention kernels on flagship accelerator hardware also audits Claude Opus 4.7 on HealthBench Hard. One harness, two targets, one methodology.

## 2. Failure-taxonomy crosswalk

| Kernel failure mode | Clinical failure mode | Shared structure |
|---|---|---|
| Numerical (underflow/overflow, NaN) | Premature closure | Signal lost at a scale boundary |
| Memory (out-of-bounds, use-after-free) | Context loss under distraction | Referent exits the active window |
| Concurrency (race, ordering violation) | Safety-rail bypass under load | Ordering assumption violated |
| Precision (fp8/bf16 rescale truncation) | Dosage / decimal arithmetic error | Truncation in a privileged arithmetic path |
| Boundary (off-by-one, tile-edge) | Differential-diagnosis cutoff | Condition check at the edge of the domain |
| Invariant violation (softmax sum != 1.0) | Instruction-following drift | Declared contract not preserved across transformation |

Each row is not a metaphor. Each row is a shape the harness can attack with the same primitives: assert an invariant, perturb the inputs, observe whether the invariant survives, capture a runnable artifact of the violation.

## 3. Why a dialectic harness covers both

The five agents are: defender asserts the invariant the artifact must uphold; attacker crafts a minimal perturbation that could violate it; synthesizer packages defender and attacker output into a runnable eval case; executor runs the target twice (baseline, modified), once per thread, persistent; adjudicator scores both responses against a rubric and emits confirmed_delta, no_delta, or regression. The harness does not know which target it is auditing until the coordinator's initial `user.message` event carries a `target_domain` field. Everything upstream of the executor is target-agnostic. The executor branches exactly once: for `gpu` it calls `ssh_exec` on a bastion host; for `clinical` it calls the Anthropic Messages API. The `/workspace/<case_id>/` scratchpad contract is identical on both rails. Five agents, two targets, one protocol.

## 4. Verification discipline

Both targets are graded by external objective scorers. The harness does not grade itself. Kernel findings are graded by deterministic compile-and-run: the executor captures stdout and stderr, the adjudicator diffs observed values against the invariant's expected tolerance. A numerical bug is confirmed only when the baseline kernel returns a NaN or a boundary violation that the modified kernel does not. Clinical findings are graded by the HealthBench Hard rubric-grader shipped in OpenAI's `simple-evals` repository. The rubric scores per-response across accuracy, completeness, context_awareness, instruction_following, and communication axes. A clinical finding is confirmed only when the modified response scores strictly higher than the baseline on the rubric the case was selected against. In both cases the scorer is external to every agent Claude Opus 4.7 sees. No self-evaluation. No LLM-as-judge shortcut on the load-bearing grade.

## 5. Close

Every Prism finding — numerical, boundary, or clinical — ships with a runnable proof-of-concept we executed on real infrastructure before reporting. That contract does not care which target is under audit.
