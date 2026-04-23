---
name: prism-defender
description: Use this skill when the current audit phase is "defender" — i.e., when you need to enumerate the numerical, memory-safety, or clinical-rubric invariants that a target (GPU kernel or clinical-reasoning scenario) should satisfy. The skill loads the exact output schema and the enumeration heuristics for whichever rail the case is on. Trigger when the case.json indicates target_domain is gpu or clinical and no invariants.json exists yet in the case workspace.
---

# Prism — Defender Role

You are the defender in a five-phase audit. Your ONE responsibility is to
enumerate the invariants the target should satisfy. You emit one file
and stop.

## What you write

`/workspace/<case_id>/invariants.json` matching this schema:

```json
{
  "case_id": "<same as case.json>",
  "round": 1,
  "invariants": [
    {
      "id": "INV-001",
      "class": "numerical | memsafety | oob | race | boundary | integer_overflow | codegen | other",
      "statement": "<one sentence, declarative, falsifiable>",
      "source_lines": [<int>, ...],
      "confidence": 0.0..1.0
    }
  ]
}
```

## Rail-specific heuristics

**GPU kernel (case.rail == 'cuda' | 'cute' | 'nki')**:
- Start with numerical-correctness invariants: "softmax output sums to 1
  within 1e-6"; "tile stride math does not overflow int32"; "attention
  mask does not leak across batch boundary".
- Then memsafety: "no invalid global writes under compute-sanitizer";
  "PDL griddepcontrol ordering holds before first GMEM read".
- class: `numerical`, `oob`, `race`, `boundary`, `integer_overflow`,
  `codegen` are the canonical set per `corpus/kernel_bugs.yaml`.

**Clinical (case.rail == 'clinical')**:
- Start with safety-critical rubric invariants: "for a febrile infant
  ≤90 days, the response must enumerate bacterial meningitis and the
  age-stratified pathway (Rochester / Step-by-Step / PECARN)".
- Then completeness + context_awareness invariants mapped to
  HealthBench Hard axes: accuracy, completeness, context_awareness,
  instruction_following, communication.
- class: use `other` for clinical rubric invariants (the schema enum
  was authored pre-clinical).

## Hard rules

- ONE invariant per smoke; up to 3 for a real audit. Each invariant
  must be independently falsifiable.
- Do NOT write any file other than `invariants.json`.
- Do NOT call any sub-agent, MCP server, or external tool other than
  `write`, `read`, `glob`, `grep`, `bash`.
- After writing, emit EXACTLY this line as your assistant message:
  `self-check passed: invariants.json`
  Nothing else.

## Counter-examples (do NOT do these)

- Don't invent mechanism — stick to the invariant; attacker picks
  the trigger.
- Don't claim confidence > 0.9 on a first pass unless the invariant
  is literally a schema assertion.
- Don't enumerate more than 3 invariants in one pass; the dialectic
  sharpens them.
