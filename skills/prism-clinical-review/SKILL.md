---
name: prism-clinical-review
description: Use this skill ONLY when case.rail == "clinical" AND the current phase is synthesizer (producing a modified-response stand-in) OR the voice fast-path (V1 SSE endpoint) is preparing a realtime reply. Applies a five-line physician-tone safety preamble — red flags / differentials / contraindications / caveats / uncertainty — ahead of the main clinical content. Skips silently on GPU-rail cases. Grades against the HealthBench Hard communication axis per docs/sota-portfolio.md §R4.
---

# Prism — Clinical-Review Skill (R4.1)

You are producing a clinical-rail response that must pass the HealthBench Hard **communication** axis. Your ONE job is to prepend a fixed-shape safety preamble and enforce physician-tone throughout. You do NOT change the medical content, the DDx list, or the dosing — those are owned by `prism-differential-diagnosis` and `prism-dosage-check`.

## When this skill fires

Trigger only when ALL of the following hold:

1. `case.rail == "clinical"` (never on `cuda | cute | nki`).
2. Phase is **synthesizer** (writing `modified.md`) OR the V1 voice fast-path needs a realtime reply.
3. No prior `clinical-review` self-check line has been emitted for this case/turn.

If any condition fails, emit nothing from this skill and let the host agent proceed.

## The five-line preamble (verbatim shape)

Every response begins with exactly these five lines, populated for the case at hand. One line per item; no bullets, no headings, no bolding. The preamble is what the communication-axis rubric looks for.

```
Red flags considered: <1 short clause, specific to this chief complaint>
Top differentials: <3 one-word or two-word items, comma-separated>
Contraindications checked: <drug-class or procedure-class, comma-separated, or "n/a">
Key caveats: <1 short clause naming the most load-bearing assumption>
Uncertainty: <1 clause — what you would need to know to be more confident>
```

Then a blank line, then the main response body produced by the host phase.

Example (fever infant, 58 days old):

```
Red flags considered: bacterial meningitis, SBI under 90 days, parental hypovigilance
Top differentials: UTI, viral URI, bacteremia
Contraindications checked: n/a (diagnostic, not therapeutic)
Key caveats: age-stratified (<=60d) — empiric coverage threshold is lower here
Uncertainty: need CBC with differential, UA, and LP results to risk-stratify

[body follows — owned by differential-diagnosis / executor / etc.]
```

## Physician-tone rules (enforced in the body)

Apply these even if the preamble is the only thing you add:

- **Second-person-neutral**: speak to the clinician reader ("Consider ruling out..."), not the patient.
- **Hedged commit**: "is consistent with" beats "is"; "suggests" beats "means"; never use "definitely" or "just" before a diagnosis.
- **Disposition over reassurance**: close with next-step guidance (labs, imaging, disposition, follow-up), not blanket reassurance.
- **Named pathways when they exist**: cite the specific decision rule by name (Rochester, Step-by-Step, PECARN, HEART, CURB-65, Wells, Centor, NEXUS, Canadian C-spine, etc.) rather than paraphrasing.
- **No first-person**: never "I think..." or "I'd recommend...".

## What you do NOT do

- Do NOT invent drug doses. That is `prism-dosage-check`.
- Do NOT expand the differential. That is `prism-differential-diagnosis`.
- Do NOT claim a citation you did not retrieve via R1 MedlinePlus or R2 PubMed — if no retrieval fired, omit citations entirely.
- Do NOT reference real patient data. Synthetic personas only (see CLAUDE.md §10).
- Do NOT add a self-rating line (e.g. "my confidence: high"). The adjudicator scores, you deliver.

## Grading hook

- **Axis graded**: communication.
- **Ship gate**: paired axis delta >= 0.05 on the 30-example HealthBench Hard subset (see `docs/sota-portfolio.md` §R4).
- **Delta is measured** against the same case run without this skill loaded.

## Hard rules

- Preamble MUST be exactly 5 lines, in the order above. The grader pattern-matches the leading-tokens.
- If a field genuinely does not apply (e.g. contraindications on a pure diagnostic question), write `n/a` with a brief parenthetical reason — never leave the field empty.
- Emit EXACTLY this line after applying the preamble and returning control: `self-check passed: clinical-review`. Nothing else from this skill.

## Counter-examples (do NOT do these)

- Don't merge the five preamble lines into prose — the grader looks for the line shape.
- Don't add "In summary..." closings — the communication axis penalizes filler.
- Don't translate named pathways into plain English ("the well-appearing-infant rule"). Use the name.
- Don't fire on `case.rail == "cuda" | "cute" | "nki"` — kernel rail has no communication axis.
