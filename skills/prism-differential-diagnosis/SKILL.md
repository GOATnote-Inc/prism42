---
name: prism-differential-diagnosis
description: Use this skill ONLY when case.rail == "clinical" AND the current phase is defender (enumerating completeness invariants) OR synthesizer (producing the modified-response stand-in for a diagnostic question). Emits a structured differential-diagnosis list with explicit prior-probability estimates, must-not-miss flags, and the key discriminator for each item. Skips silently on GPU-rail cases or on purely therapeutic / disposition questions. Grades against the HealthBench Hard completeness axis per docs/sota-portfolio.md §R4.
---

# Prism — Differential-Diagnosis Skill (R4.2)

You are producing (or evaluating) the structured differential for a clinical-rail case. Your ONE job is to emit a DDx block in a fixed shape. You do NOT write the preamble (that is `prism-clinical-review`) and you do NOT compute drug doses (that is `prism-dosage-check`).

## When this skill fires

Trigger only when ALL of the following hold:

1. `case.rail == "clinical"`.
2. The case stem is **diagnostic** — names a chief complaint, presentation, or abnormal finding and asks what it could be. Skip on pure dosing questions, pure procedural questions, and pure disposition questions.
3. Phase is **defender** (writing completeness invariants) OR **synthesizer** (writing `modified.md`).
4. No prior `differential-diagnosis` self-check line has been emitted for this case/turn.

## The DDx block shape (fixed)

Emit a compact table. 3–5 rows. One line per differential. Exact columns:

```
DDx | prior | must-not-miss | key discriminator
----|-------|---------------|------------------
<dx name> | <low|mod|high> | <yes|no> | <one short clause>
...
```

Rules for the columns:

- **DDx name**: 1–3 words, specific (e.g. "bacterial meningitis" not "infection"; "PE" not "dyspnea cause"). Accept common abbreviations (MI, PE, DKA, AAA).
- **prior**: `low` / `mod` / `high` — your pre-test estimate given the case stem only. This is not the post-test probability; it is the population-prior for someone presenting this way.
- **must-not-miss**: `yes` if missing this diagnosis would be life-threatening or disabling within 24 h; `no` otherwise. The completeness axis specifically rewards flagging these.
- **key discriminator**: one clause naming the single most efficient test or history item that separates this DDx from the others in the row above (e.g. "troponin + ECG ST changes", "blood glucose >250 + anion gap", "D-dimer or CTA").

## Ordering rule

Sort by `must-not-miss` descending first, then by `prior` descending. Reason: the completeness axis is structured to reward clinicians who surface the dangerous diagnosis before the common one. The rubric penalizes the opposite.

## Completeness invariants (defender phase)

When the defender phase fires this skill, emit an `invariants.json`-compatible list where each invariant corresponds to a DDx row. Pattern for the `statement` field:

> "Response must enumerate <dx name> (prior=<lvl>, must-not-miss=<yes|no>) and cite the key discriminator <clause>."

`class` stays `other` per the clinical mapping in `skills/prism-defender/SKILL.md`. Up to 3 invariants per pass (one per must-not-miss DDx + one for the modal-prior DDx).

## Hard rules

- 3–5 rows. Fewer than 3 means the case is not diagnostic (skip); more than 5 means you are listing zebras (cut).
- At least one row MUST have `must-not-miss: yes` unless the case stem is explicitly benign (e.g. "healthy 25-year-old asking about...").
- Use the exact table format above. The completeness-axis grader pattern-matches the pipe-delimited shape.
- Do NOT cite sources in this block — retrieval citations belong in the surrounding prose (via R1/R2) or not at all.
- Do NOT compute doses. If the case requires dosing, hand off to `prism-dosage-check`.
- Emit EXACTLY: `self-check passed: differential-diagnosis`. Nothing else from this skill.

## Grading hook

- **Axis graded**: completeness.
- **Ship gate**: paired axis delta >= 0.05 on the 30-example HealthBench Hard subset.
- **Delta is measured** against the same case without this skill loaded — a defender/synthesizer response that emits prose paragraphs instead of a structured table.

## Counter-examples (do NOT do these)

- Don't order rows by prevalence first. Dangerous-before-common.
- Don't emit prose paragraphs in place of the table; the grader pattern-matches the table.
- Don't list >5 differentials; completeness rewards the high-signal set, not the encyclopedia.
- Don't fire on a question that has no DDx structure (e.g. "what is the mechanism of vancomycin?"). Skip instead.
- Don't duplicate a row that also appears in the `prism-clinical-review` preamble's "top differentials" line — that is a summary; this is the structured version.
