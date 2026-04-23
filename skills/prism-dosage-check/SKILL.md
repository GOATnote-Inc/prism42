---
name: prism-dosage-check
description: Use this skill ONLY when case.rail == "clinical" AND the case stem names a specific drug + patient parameter (weight, age, CrCl, hepatic state, pregnancy) AND an explicit dose calculation is requested or implied. Cross-references the proposed dose against weight-based / age-based / renal-adjusted ranges, flags contraindications, and emits a structured dose record. Skips silently on GPU-rail cases, on pure diagnostic questions, and on cases without a numeric dosing ask. Grades against the HealthBench Hard accuracy axis per docs/sota-portfolio.md §R4.
---

# Prism — Dosage-Check Skill (R4.3)

You are producing (or auditing) a drug-dose recommendation on the clinical rail. Your ONE job is to emit a structured dose record and flag contraindications. You do NOT add preamble (that is `prism-clinical-review`) and you do NOT produce the differential (that is `prism-differential-diagnosis`).

## When this skill fires

Trigger only when ALL of the following hold:

1. `case.rail == "clinical"`.
2. The case stem names a specific drug (by generic name, brand, or class) AND at least one patient parameter: weight, age, creatinine clearance or eGFR, hepatic function, pregnancy status, dialysis status.
3. A dose calculation or adjustment is requested or strongly implied (e.g. "dose vancomycin", "is 400 mg ciprofloxacin appropriate here?", "renal-adjust enoxaparin").
4. No prior `dosage-check` self-check line has been emitted for this case/turn.

If the case only mentions a drug in passing (e.g. "patient is on warfarin") without a dosing ask, skip.

## The dose record shape (fixed)

```
drug: <generic name>
indication: <1 short clause — what is being treated>
patient params:
  - weight: <kg or "not given">
  - age: <years or "not given">
  - CrCl/eGFR: <value or "not given">
  - hepatic: <normal|impaired|not given>
  - pregnancy: <yes|no|not given>
proposed dose: <value unit route frequency> (e.g. "25 mg/kg IV q8h")
reference range: <canonical range for this indication + weight class>
adjustment applied: <none | renal <factor> | hepatic <factor> | weight-based <factor>>
contraindications checked: <drug-class interaction | comorbidity | pregnancy class | "none identified">
verdict: <within-range | above-range | below-range | contraindicated | inadequate-info>
discriminator: <one clause — the single parameter that could flip this verdict>
```

## Calculation rules

- **Weight-based dosing**: if the drug has a standard mg/kg range, compute both the proposed total dose and the reference-range total dose in mg. Flag if the proposed dose is >20 % outside the range.
- **Renal adjustment**: when CrCl or eGFR is given and the drug has a published adjustment threshold, compute the adjusted range and compare.
- **Contraindications**: check at least (a) drug-class interactions with any other drug named in the case, (b) comorbidity contraindications (e.g. NSAIDs in CKD, metformin in eGFR <30), (c) pregnancy category when pregnancy is mentioned.
- **Inadequate info**: if the calculation requires a parameter the stem does not provide AND the parameter cannot be assumed from context (e.g. no weight for a pediatric weight-based dose), set `verdict: inadequate-info` and name the missing parameter in `discriminator`.
- **No retrieval, no citations**: this skill uses recall only. If a fact would need a citation, state the recall range and mark `discriminator` with the parameter whose true value could invalidate it.

## Hard rules

- **Never** invent a dose for a drug you do not recall. Emit `verdict: inadequate-info` and name what you would need.
- **Never** emit only the proposed dose without the reference range. The accuracy-axis grader compares the two.
- **Always** populate `contraindications checked` — use `"none identified"` rather than omitting the field.
- **Flag weight-based pediatric doses explicitly**: if `age < 12` and the drug is weight-based, the verdict MUST show the per-kg calculation even if the final total matches an adult reference.
- **Renal dose adjustments**: use the drug's labeled threshold, not a generic CrCl cutoff.
- Emit EXACTLY: `self-check passed: dosage-check`. Nothing else from this skill.

## Grading hook

- **Axis graded**: accuracy (primary); communication (secondary — the structured record maps onto communication-axis "shows the work" patterns).
- **Ship gate**: paired accuracy-axis delta >= 0.05 on the 30-example HealthBench Hard subset.
- **Delta is measured** against the same case without this skill — a free-text "give 25 mg/kg" answer.

## Counter-examples (do NOT do these)

- Don't emit a dose without a reference range — the grader pattern-matches the paired value.
- Don't paraphrase a CrCl threshold ("low renal function"). Cite the numeric label threshold or mark `inadequate-info`.
- Don't skip the pregnancy field for women of childbearing age; use `"not given"` explicitly so the rubric sees the field.
- Don't merge with the `prism-clinical-review` preamble. The dose record is a separate block.
- Don't fire on pure diagnostic or dispositional questions. Skip.
