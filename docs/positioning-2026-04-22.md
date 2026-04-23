---
title: Prism — category positioning (submission-ready)
date: 2026-04-22
scope: 150-200 word summary, one judge-facing paragraph, three differentiators. No code, no implementation detail.
---

## 150-200 word summary

Prism is a verification layer for safety-critical AI systems — the category between "it ran" and "it is verifiably correct under adversarial input." One harness, two rails. The GPU rail audits the attention and matmul kernels that run production LLM inference — open-source implementations on flagship accelerator hardware — surfacing silent-NaN and memory-safety failures that propagate through model outputs undetected. The clinical rail audits reasoning in emergency-medicine decision surfaces, surfacing premature closure, instruction drift, and context-poisoning failures that propagate through patient care undetected. Both rails run the same five-agent Opus 4.7 dialectic: defender asserts an invariant, attacker crafts a counterexample, synthesizer packages a reproducer, executor runs it on real infrastructure, adjudicator grades against an external rubric. Every Prism finding ships with its executed proof — a compiled PoC run on a real H100 or Trainium, or a rubric-graded clinical delta against HealthBench Hard. No speculative reports. No LLM-self-grading on the load-bearing decision. Numerical correctness and semantic correctness are the same failure taxonomy in two substrates, and they admit the same solution.

## One paragraph judges should realize

"AI safety" has been conflated with two separate problems — alignment (does the model want the right thing) and benchmark capability (does the model score well on average). Neither answers the load-bearing question for deployment into patient care, infrastructure, or government: *does this produce verifiably correct output under adversarial input, and can you point to the executed artifact that proves it?* Prism makes that question answerable by refusing to accept any finding that does not ship with its execution. Glasswing covers web authz and C/C++ binary analysis — the highest-value attack surfaces of the pre-AI internet. The highest-value attack surfaces of AI systems are the compute substrate and the reasoning substrate. Prism audits both with a single harness.

## Three differentiators vs. typical hackathon projects

- **Every finding ships with an artifact executed on real hardware before submission.** A compiled PoC run on a rented H100 or Trainium instance, or a rubric-graded clinical delta against HealthBench Hard — never a speculative demo, never "here is what it would do if we ran it." This is the direct counter-pattern to the AI-slop backlash that made Stenberg ban AI-generated curl security reports and led the Linux kernel security team to push back on LLM-generated CNA requests.

- **Dual-domain coverage from a single harness.** The failure-taxonomy crosswalk in `docs/dual-target-thesis.md` holds that numerical correctness and semantic correctness share structure across two substrates — signal lost at a scale boundary, referent exits the active window, ordering assumption violated, declared invariant not preserved across transformation. One adversarial dialectic grades both. No second harness is required for the clinical rail; the executor branches exactly once on `case.rail`.

- **External objective grading on every load-bearing decision; never LLM-as-judge.** Kernel findings are scored by deterministic compile-and-run with expected-vs-observed tolerance. Clinical findings are scored by OpenAI's `simple-evals` rubric grader on HealthBench Hard. Self-grading is the silent-failure mode of most LLM evaluation; refusing to self-grade is the correctness floor.
