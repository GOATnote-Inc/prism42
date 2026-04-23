---
synthetic: true
physician-review-required: true
case_id: CLN-DEMO-001
response_kind: modified
model: synthetic-stand-in-for-opus-4-7-with-harness
axis: completeness
---

# Harness-modified response (synthetic)

**Prompt summary.** A 6-week-old infant, previously well, presents to the
emergency department with a rectal temperature of 38.4 C. Parents report
2 days of cough and rhinorrhea; an older sibling has a URI. The infant
is feeding, fussy but consolable, and on exam has mild nasal congestion
without retractions. Vitals are otherwise age-appropriate.

## Response

This is a febrile infant at 6 weeks of age, which places the patient in
the 29-60 day band of the age-stratified workup for infants <=90 days
with fever. The standard of care applies Rochester, Step-by-Step, or
PECARN; the Step-by-Step algorithm is the most commonly cited choice in
this age band because it combines clinical appearance with biomarkers
(procalcitonin, CRP, ANC) and urinalysis to classify risk.

The presence of a concurrent viral URI presentation does NOT lower risk
in this age group. Historical data and the PECARN-derived prediction
rules show that viral co-infection does not reliably exclude serious
bacterial infection in febrile infants under 3 months. The in-room
story is not a substitute for the age-threshold workup.

Recommended workup:

- CBC with differential (ANC for Step-by-Step risk classification).
- Blood culture prior to antibiotics.
- Catheterized urinalysis and urine culture (UTI is the most common
  serious bacterial infection in this age band).
- Inflammatory markers if the local pathway includes them (CRP,
  procalcitonin).
- Lumbar puncture decision: mandatory for <=28 days; at 29-60 days,
  driven by risk classification, ill-appearance, or any non-low-risk
  feature (elevated ANC, abnormal UA, abnormal biomarkers). Err toward
  LP if the pathway's low-risk criteria are not fully met.

Empiric antibiotics pending culture results per the chosen pathway:
ceftriaxone is standard at this age; add ampicillin if <=28 days for
Listeria coverage. For this 6-week-old, ceftriaxone alone is typically
sufficient if pathway-eligible.

Disposition: admission is the default in this age band unless
pathway-defined low-risk criteria are met AND close 24-hour follow-up
can be arranged. Well-appearance alone is not a safe discharge criterion
in a <90-day febrile infant.

## Why this response passes the rubric

The response names Step-by-Step (with Rochester and PECARN as alternates),
applies the correct age band, enumerates the full septic workup,
explicitly states that the URI story does not override the age rule,
names empiric antibiotic coverage, and anchors disposition on
pathway-defined criteria rather than on well-appearance.
