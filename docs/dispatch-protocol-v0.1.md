<!--
GEDP v0.1 — GOATnote Emergency Dispatch Protocol

Developed under direction of Brandon Dent, MD (emergency medicine).
Author: GOATnote Inc. MIT-licensed.

Grounded in:
- American Heart Association Emergency Cardiovascular Care Guidelines 2025
  (AHA BLS 2025), cited with attribution.
- National Highway Traffic Safety Administration National EMS Scope of
  Practice Model (NHTSA Scope) — public domain.
- Peer-reviewed EMS literature (cited per complaint).
- Publicly published US PSAP dispatcher materials (cited per complaint).

Not grounded in:
- MPDS / IAED-licensed content (NOT used). Any MPDS comparison is for
  cross-reference only; determinant codes and scripts below are GEDP's
  own, designed to be determinant-neutral and re-mappable.

Version 0.1 status: framework complete. Five chief complaints land in
full clinical detail in this commit (cardiac arrest adult — fully fleshed;
choking pediatric, severe external hemorrhage, stroke signs, breathing
difficulty — structured skeletons with key-question and PDI anchors).
Remaining 16 chief-complaint families land incrementally per Phase 2 of
the prism42 release plan.
-->

---
title: GEDP v0.1 — GOATnote Emergency Dispatch Protocol
version: 0.1.0
author: "GOATnote Inc."
clinical_direction: "Brandon Dent, MD (emergency medicine)"
license: MIT
grounding:
  - aha-bls-2025
  - nhtsa-scope-of-practice-model-2021
  - peer-reviewed-ems-literature-per-cite
  - public-us-psap-materials-per-cite
not_grounded_in:
  - mpds-iaed-licensed
date: 2026-04-23
---

# GOATnote Emergency Dispatch Protocol (GEDP) v0.1

## §1 Scope — what GEDP is and is not

GEDP is a dispatcher-facing decision-support protocol for a simulated
911 call-taker stack. It is:

- **Our own protocol**, MIT-licensed, developed under direction of a
  board-certified emergency physician, grounded in public clinical
  evidence (AHA BLS 2025, NHTSA Scope) and publicly published US PSAP
  dispatch materials.
- **Scoped to dispatch authority**, not ED physician authority. GEDP
  does not diagnose. GEDP does not prescribe. GEDP surfaces a chief
  complaint, a severity classification, a dispatch level, and — where
  the evidence supports it — a pre-arrival instruction (PDI) script.
- **Research-phase**. Not FDA-cleared. Used in a simulation; clinical
  deployment requires IRB + physician-in-loop per the prism42 clinical
  trajectory.
- **Cross-mappable** to MPDS determinants where a user or operator
  references them, but does not reproduce MPDS script verbatim.

GEDP is NOT:

- A replacement for MPDS / IAED accreditation in accredited PSAPs.
- A replacement for physician medical direction.
- Clinical advice for any real patient.
- A warranty of clinical accuracy for any particular case.

## §2 Dispatcher authority + scope boundaries

GEDP dispatchers operate within the following scope (after NHTSA Scope
§2.3 "Emergency Medical Dispatcher" role):

**In scope**:
- Address confirmation + demographic capture.
- Chief complaint classification to a chief-complaint family.
- Key-question flow to determine complaint severity.
- Determinant-code assignment per the GEDP taxonomy (§4).
- Dispatch-level assignment (§4).
- CAD entry (synthetic, in the simulation).
- Pre-arrival instruction delivery from the GEDP PDI library (§6).
- Warm handoff to arriving EMS / other services.

**Out of scope (dispatcher MUST refuse per SP-004)**:
- Medication prescription, including OTC dose guidance.
- Definitive diagnosis of any condition.
- Interpretation of ECG, laboratory, imaging.
- Medical advice outside the dispatcher-appropriate PDI scripts.
- Physical examination instructions beyond observational description.

## §3 Phase state machine

Every call passes through up to five phases. Non-linear transitions
are explicitly allowed for life-over-paperwork cases.

```
  intake → triage → dispatch → (pdi?) → handoff
```

- **Intake** (target < 30 s): address confirmed, chief complaint
  family identified, caller state classified. Exit to triage.
- **Triage** (target 30-90 s): key-question flow for the identified
  family, determinant code assigned, severity classified. Exit to
  dispatch.
- **Dispatch** (target 10-30 s): CAD record finalized, units assigned,
  ETAs estimated. Exit to PDI or handoff.
- **PDI** (target per PDI script): pre-arrival instructions delivered,
  caller confirmation at each step. Exit to handoff when instructions
  complete OR patient state changes OR units arrive.
- **Handoff** (target < 30 s): transfer to arriving team OR close call
  with post-action guidance.

**Non-linear exceptions**:

- **intake → pdi direct** when the caller reports active cardiac arrest
  AND address is captured. Life-over-paperwork: CPR prep begins before
  triage completes. (GEDP §5.1 — adult cardiac arrest.)
- **triage → intake** if address becomes uncertain mid-KQ.
- **pdi → handoff** on patient recovery, patient deterioration (to
  arriving team), or units arrival.
- **any phase → end** on real-emergency claim (SP-001), kill switch,
  or session-budget-exceeded.

## §4 Determinant code taxonomy

GEDP uses three-character determinant codes. Format: `<complaint>-<severity>-<mod>`.

Severity levels (after AHA BLS 2025 acuity model):

| Level | Label | Dispatch | Example |
|---|---|---|---|
| `O` | OMEGA | Referred / advice | Minor laceration, no active bleeding |
| `A` | ALPHA | BLS non-urgent | Stable fall, no obvious injury |
| `B` | BRAVO | BLS urgent | Non-critical trauma, alert patient |
| `C` | CHARLIE | ALS urgent | Moderate symptoms, stable vitals |
| `D` | DELTA | ALS emergent | Unstable vitals, severe presentation |
| `E` | ECHO | Max response | Arrest, near-arrest, mass-casualty |

Complaint prefix is numeric (see §5). Modifier suffix captures
critical state (e.g., `-NA` for "not alert", `-PG` for "pregnancy",
`-PD` for "pediatric"). Example: `1-E-NA` = adult cardiac arrest,
ECHO, not alert (canonical OHCA).

## §5 Chief complaint families — the 21 classes

Each family has a GEDP numeric prefix. Intake classifies to family;
triage refines to determinant.

| # | Family | Section |
|---|---|---|
| 1 | Cardiac arrest | §5.1 — full detail |
| 2 | Breathing difficulty | §5.2 — skeleton |
| 3 | Chest pain | §5.3 — pending Phase 2 |
| 4 | Unconscious / fainting | §5.4 — pending Phase 2 |
| 5 | Choking | §5.5 — skeleton |
| 6 | Stroke signs | §5.6 — skeleton |
| 7 | Seizure | §5.7 — pending Phase 2 |
| 8 | Severe bleeding | §5.8 — skeleton |
| 9 | Trauma | §5.9 — pending Phase 2 |
| 10 | Allergic reaction | §5.10 — pending Phase 2 |
| 11 | Diabetic emergency | §5.11 — pending Phase 2 |
| 12 | Overdose / poisoning | §5.12 — pending Phase 2 |
| 13 | Pregnancy / childbirth | §5.13 — pending Phase 2 |
| 14 | Pediatric distress | §5.14 — pending Phase 2 |
| 15 | Mental health crisis | §5.15 — pending Phase 2 |
| 16 | Heat / cold exposure | §5.16 — pending Phase 2 |
| 17 | Drowning / near-drowning | §5.17 — pending Phase 2 |
| 18 | Burn / electrical | §5.18 — pending Phase 2 |
| 19 | Animal bite | §5.19 — pending Phase 2 |
| 20 | Obstetric-gynecologic other | §5.20 — pending Phase 2 |
| 21 | Unknown / generalized distress | §5.21 — pending Phase 2 |

---

### §5.1 Cardiac arrest — adult

**Triggering intake cues**: "not breathing", "not responding", "turning
blue", "collapsed and won't wake up", "agonal breathing" (or lay
descriptions "gasping", "fish-out-of-water breaths"), reported
unresponsive with absent or abnormal breathing.

**Non-linear intake → pdi**: if the caller reports active arrest AND
address is captured, bypass triage and begin CPR prep immediately.
Triage KQs can happen alongside the first chest compressions.

#### §5.1.1 Key questions (KQs)

KQ1 — "Is the patient awake and breathing normally?"
- Answer "yes, both" → likely misclassification; re-classify to
  chief-complaint family via intake.
- Answer "not awake, not breathing normally" → proceed to KQ2.
- Answer "awake but breathing is bad" → reclassify to breathing
  difficulty (§5.2) OR chest pain (§5.3) per follow-up.
- Answer "not awake, breathing is abnormal" (agonal, gasping) →
  treat as arrest; proceed to PDI-1A.

KQ2 — "How old is the patient?" (age-stratified PDI selection)
- Adult (≥ 8 y or post-pubertal) → standard adult PDI-1A.
- Child (1-8 y) → pediatric PDI-1C.
- Infant (< 1 y) → infant PDI-1I.
- Unknown → assume adult, flag for reassessment during PDI.

KQ3 — "Where is the patient right now — on the floor, on a couch,
in a bed?"
- Floor (flat, firm surface) → proceed directly.
- Couch / bed / soft surface → "Please move them to the floor on
  their back, quickly. I'll wait." Resume when confirmed.
- In water, in a vehicle, at height → escalate to psap-safety-monitor;
  special-case handling in §5.1.5.

KQ4 — "Is there an automated external defibrillator — an AED —
nearby, like in a building or office?"
- Yes → "Send someone to get it while we start CPR. Don't wait for it."
- No / unknown → "That's fine. We'll start CPR now."

#### §5.1.2 Determinant assignment

All confirmed adult cardiac arrest → **`1-E-NA`** (ECHO, not alert).
Dispatch: maximum response. ALS + BLS + supervisor + AED-equipped
unit if available; fire for lift assistance if reported at height or
in confined space.

#### §5.1.3 Pre-arrival instructions — PDI-1A (adult)

After AHA BLS 2025 adult chain of survival. Delivered one step at a
time, waiting for caller confirmation at each.

Step 1 — Confirm position.
> "Is the patient on their back on a firm surface like the floor?"
Wait for "yes" before proceeding.

Step 2 — Find hand position.
> "Kneel beside them. Put the heel of one hand in the center of their
> chest, right between the nipples, on the breastbone. Put your other
> hand on top of the first, and lock your fingers together."
Wait for "OK" or "I have it."

Step 3 — Start compressions with rate + depth cues.
> "You're going to push down hard and fast, about two inches deep, at
> a steady rhythm. I'll count with you. Push — one, two, three, four,
> five, six, seven, eight..."
Count aloud at 110 compressions per minute, matching the AHA BLS 2025
rate of 100-120/min. Continue counting aloud for the first 30
compressions.

Step 4 — Sustain.
> "That's great. Keep going at this rhythm. Don't stop unless I tell
> you to, or the patient wakes up, or EMS takes over."

Step 5 — AED arrival (if applicable).
> "Is the AED here? — Turn it on. Follow the spoken instructions.
> Stick the pads on the patient's bare chest — one on the upper right
> chest, one on the lower left side. Don't touch the patient while the
> AED checks the rhythm. If it tells you to push a button to deliver
> a shock, press it. Then resume compressions immediately."

Step 6 — Ventilation decision.
> If the caller asks about rescue breaths: "If you're trained and
> willing, give 2 breaths after every 30 compressions. If you're not
> trained or not willing, just keep doing compressions — that's the
> most important thing."
> Do NOT require rescue breaths; per AHA 2025 compression-only CPR is
> acceptable and better than no CPR.

Step 7 — Coaching / sustainment.
Every ~60 seconds of compressions, offer:
> "You're doing great. Keep the rhythm. Push hard, push fast. Let the
> chest come all the way back up between pushes. EMS is [estimated
> time] away."

Step 8 — Unit arrival.
> "When EMS arrives, step back and let them take over. Tell them how
> long you've been doing CPR, and whether the AED delivered a shock."

#### §5.1.4 Contraindications + safety rules

- **Never** instruct CPR on a patient who is breathing normally + has a
  pulse. Reclassify.
- **Never** pause compressions for pulse check unless AED is delivering
  a shock or EMS has taken over.
- **Never** suggest rescue breaths are required. Compression-only is
  acceptable (AHA BLS 2025 §5.1).
- **Do not** instruct the caller to check for a pulse; pulse check is
  unreliable for lay rescuers (AHA BLS 2025 §3.2).
- If patient starts breathing normally / moving / making sounds: stop
  compressions, place them on their side if possible, monitor.
- If the caller cannot continue compressions due to exhaustion,
  injury, or fatigue: "If there's another person there, switch with
  them. Otherwise, do the best you can — some compressions are better
  than no compressions."

#### §5.1.5 Special cases

- **Patient in water**: dispatch water rescue; do not instruct
  compressions in water. Once out of water + on firm surface, resume
  standard PDI.
- **Patient in vehicle, at height, in confined space**: dispatch fire
  + rescue for extrication. Standard PDI applies once extricated.
- **Trauma arrest**: do compressions anyway (AHA BLS 2025 notes
  benefit unclear but harm low); flag for psap-safety-monitor so the
  auditor captures it.
- **Suspected hypothermic arrest**: compressions are appropriate;
  recovery can occur with prolonged resuscitation.
- **Do-not-resuscitate (DNR) orders**: if caller reports a documented
  DNR, escalate to psap-safety-monitor; do not coach CPR; provide
  comfort guidance + direct to EMS for verification on arrival.

#### §5.1.6 Pediatric variants

- **Child (1-8 y)**: PDI-1C. Compression depth: about 2 inches or
  one-third chest depth. Compression rate: same 100-120/min. Use
  heel of one hand (not two) for smaller children. 30:2
  compressions-to-ventilations if trained; compression-only acceptable
  per AHA BLS 2025 §6.1.
- **Infant (< 1 y)**: PDI-1I. Two-finger compressions in center of
  chest, just below nipple line. Depth: about 1.5 inches or one-third
  chest depth. Rate: 100-120/min.

Details: separate PDI-1C and PDI-1I scripts, Phase 2.

#### §5.1.7 Citations for this section

- AHA BLS 2025 §3 (adult BLS algorithm), §5.1 (compression-only
  acceptability), §6.1 (pediatric BLS).
- NHTSA Scope §4.2 (EMD pre-arrival instructions).
- Seattle / King County Public Health "Dispatcher-Directed CPR"
  training materials (publicly available).
- Stecker et al., "Public Health Burden of Sudden Cardiac Death",
  Circulation: Arrhythmia and Electrophysiology 2014 (for OHCA
  burden context).
- Wang-Keighley, "Emergency Medical Services in the United States",
  Cambridge UP 2016, Ch 12 (dispatch discipline).

---

### §5.2 Breathing difficulty — skeleton

**Triggering intake cues**: "can't breathe", "short of breath",
"wheezing", "coughing and can't catch air", "chest feels tight", known
history of asthma / COPD with acute worsening.

#### §5.2.1 Key questions

KQ1 — "Is the patient awake and talking?"
- Talking in full sentences → likely mild-moderate severity.
- Talking in short phrases → moderate.
- Cannot talk / only single words → severe; may progress to arrest.
- Not awake → reclassify to cardiac arrest family §5.1.

KQ2 — "Do they have known asthma, COPD, emphysema, or a breathing
problem they see a doctor for?"

KQ3 — "Is there something they could have breathed in — smoke, fumes,
allergic reaction to something new?"

KQ4 — "Are their lips or face turning blue or gray?"

#### §5.2.2 Determinant assignment

- `2-D-NA` — severe distress + not alert → ECHO response, prep PDI-1A
  if progresses to arrest.
- `2-D` — severe distress, awake → ALS emergent.
- `2-C` — moderate distress, history of reactive airway → ALS urgent.
- `2-B` — mild distress, no red flags → BLS urgent.
- `2-A` — stable with known cause, wanting transport → BLS non-urgent.

#### §5.2.3 PDI — PDI-2

If patient has a rescue inhaler: "If they have their rescue inhaler —
usually a blue one — hand it to them and let them use it as the label
describes."

If allergic reaction suspected: see §5.10.

Calm-voice coaching until EMS arrives: slow breaths, seated upright
position, loosen tight clothing at the neck.

Pending Phase 2: full PDI-2 script + 2-D-NA → PDI-1A bridge.

#### §5.2.4 Citations

- AHA BLS 2025 §7 (respiratory emergencies).
- NHTSA Scope §3.8 (ventilation and oxygenation).
- Phase 2 to extend.

---

### §5.5 Choking — pediatric (skeleton, age-stratified)

**Triggering cues**: "my baby is choking", "she can't breathe, she was
eating", reports of object stuck, inability to speak or cry, cyanosis.

#### §5.5.1 Key questions

KQ1 — "How old is the patient?" (age-stratified response)
- Infant (< 1 y) → PDI-5I (back blows + chest thrusts alternating).
- Child (1-8 y) → PDI-5C (chest thrusts, Heimlich for older children).
- Adult → PDI-5A.

KQ2 — "Can they cough, breathe, or make any sound?"
- Yes, forceful cough → partial obstruction; encourage coughing; do
  NOT intervene unless worsens.
- No / weak / silent → complete obstruction; PDI.
- Going limp / losing consciousness → reclassify to cardiac arrest
  §5.1 + begin CPR.

KQ3 — "What did they choke on?" (informational only; do not delay PDI
for this).

#### §5.5.2 Determinant assignment

- `5-D-PD` — complete obstruction, pediatric → ECHO response + PDI-5C/I.
- `5-C-PD` — partial obstruction, pediatric, persistent → ALS urgent.
- `5-D` — complete obstruction, adult → ECHO response + PDI-5A.
- `5-A` — cleared obstruction, self-resolved, requesting evaluation →
  BLS non-urgent.

#### §5.5.3 PDI — PDI-5C (child 1-8 y)

Age-appropriate chest thrusts, NOT infant back-blows. Explicit
contraindication: do not instruct blind finger sweeps in any age.

Step 1: "Stand behind the child. Make a fist with one hand, place the
thumb side against the middle of the child's belly, just above the
navel."
Step 2: "Place your other hand over your fist and give quick, upward
thrusts."
Step 3: "Continue until the object is expelled or the child becomes
unresponsive. If they go limp, lower them carefully to the ground and
begin CPR (§5.1)."

Explicit NOT: no blind finger sweep; only remove visible objects.

#### §5.5.4 PDI-5I (infant < 1 y)

Five back-blows alternating with five chest thrusts. Infant-specific.

#### §5.5.5 PDI-5A (adult)

Standard abdominal thrusts (Heimlich) until obstruction clears or
patient becomes unresponsive (reclassify to §5.1).

#### §5.5.6 Citations

- AHA BLS 2025 §6.3 (pediatric choking), §3.4 (adult foreign-body
  airway obstruction).
- American Red Cross "Pediatric First Aid" 2024 update.
- Phase 2 to extend scripts.

---

### §5.6 Stroke signs — skeleton

**Triggering cues**: "face drooping on one side", "can't move an arm",
"slurring words", "sudden severe headache", "sudden confusion",
"sudden vision change".

#### §5.6.1 BE-FAST assessment (AHA/ASA Stroke 2022+)

- **B**alance — sudden loss of balance or coordination.
- **E**yes — sudden double vision, vision loss.
- **F**ace — ask the caller to look at the patient's face; does one
  side droop when they smile?
- **A**rms — ask the caller to have the patient raise both arms; does
  one drift down?
- **S**peech — is their speech slurred or strange?
- **T**ime — when did the symptoms start?

Any positive BE-FAST element + sudden onset → suspected stroke.

#### §5.6.2 Determinant assignment

- `6-D` — any BE-FAST positive + sudden onset → ALS emergent; alert
  receiving stroke center.
- `6-E-NA` — BE-FAST + decreased level of consciousness → ECHO;
  consider large vessel occlusion.

#### §5.6.3 PDI — PDI-6

- Keep patient calm, head elevated slightly.
- Nothing by mouth (risk of aspiration).
- Do NOT give aspirin (contraindicated in hemorrhagic stroke; cannot
  distinguish ischemic vs hemorrhagic at dispatch).
- Note exact time symptoms started (critical for tPA eligibility).

#### §5.6.4 Citations

- AHA/ASA Stroke Guidelines 2022.
- NHTSA Scope §5.3 (stroke pre-hospital care).

---

### §5.8 Severe external hemorrhage — skeleton

**Triggering cues**: "bleeding a lot", "won't stop bleeding", arterial
spurting described, soaked clothing reported, trauma with bleeding.

#### §5.8.1 Key questions

KQ1 — Location: arm/leg vs torso vs head/neck.
KQ2 — Character: spurting (arterial) vs steady flow (venous) vs
oozing (capillary).
KQ3 — Volume estimate: cup, pint, pool.
KQ4 — Consciousness / mental status of patient.

#### §5.8.2 Determinant assignment

- `8-D` — severe bleeding, unstable mental status → ALS emergent.
- `8-C` — severe bleeding, alert → ALS urgent.
- `8-B` — moderate bleeding, controllable with pressure → BLS urgent.

#### §5.8.3 PDI — PDI-8

Direct pressure primary intervention. Tourniquet secondary for limb
arterial bleeds if direct pressure fails. Stop the Bleed Campaign
2024 guidance.

Explicit NOT: no "move the patient" if spinal injury possible; no
removing impaled objects.

#### §5.8.4 Citations

- Stop the Bleed Campaign (American College of Surgeons) 2024.
- AHA BLS 2025 §9 (trauma-associated arrest).
- NHTSA Scope §7.1 (hemorrhage control).

---

## §6 Pre-arrival instruction library (PDI-*)

Each PDI script is labeled `PDI-<complaint>[<age-mod>]`. Adult PDIs
have no age-mod suffix; pediatric PDIs have `C` (child), `I`
(infant), or `N` (neonate). Scripts are referenced by this ID in
agent cites.

| PDI ID | Complaint | Status |
|---|---|---|
| PDI-1A | Adult cardiac arrest CPR | Complete (§5.1.3) |
| PDI-1C | Child CPR | Skeleton (§5.1.6); Phase 2 complete |
| PDI-1I | Infant CPR | Skeleton (§5.1.6); Phase 2 complete |
| PDI-2 | Breathing difficulty | Skeleton (§5.2.3); Phase 2 complete |
| PDI-5A | Adult choking | Skeleton (§5.5.5); Phase 2 complete |
| PDI-5C | Child choking | Skeleton (§5.5.3) |
| PDI-5I | Infant choking | Skeleton (§5.5.4); Phase 2 complete |
| PDI-6 | Stroke — no intervention, positioning only | Skeleton (§5.6.3) |
| PDI-8 | Severe bleeding | Skeleton (§5.8.3); Phase 2 complete |

Phase 2 completion adds PDI-3 through PDI-21 + full child/infant
variants for the remaining complaints.

## §7 Licensing + citation + contribution

- **License**: MIT. Attribution required in derivative work:
  `"GOATnote Emergency Dispatch Protocol v0.1, GOATnote Inc. /
  Brandon Dent, MD (clinical direction); MIT"`.
- **Citations**: every clinical claim in GEDP cites a specific
  primary source (AHA / NHTSA / peer-reviewed / PSAP-public). Every
  citation is dated at the fetch-date of the citing commit. If a
  primary source updates, GEDP updates in a bumped version with a
  diff-summary changelog.
- **Contribution**: a pull request that modifies GEDP clinical
  content is blocked by CI unless the physician-direction field is
  re-signed by Brandon Dent MD (or successor named in a bumped
  version). Non-clinical edits (typos, cross-refs, structural) do
  not need re-sign.

## §8 Age stratification

GEDP treats age as a first-class axis, not an afterthought. Every
complaint family has explicit adult / child / infant / neonate
variants where the clinical evidence differentiates. Age is obtained
in intake or triage KQ1 or KQ2; unknown-age cases are flagged for
reassessment during PDI.

Age brackets:

- Neonate: 0 - 28 days.
- Infant: 29 days - 12 months.
- Child: 1 year - 8 years (some sources use puberty or 12 years).
- Adolescent: 9 years - 18 years (mostly adult-pattern PDIs apply).
- Adult: 18+ years.
- Older adult: 65+ years (flagged for additional considerations;
  most PDIs unchanged but triage priors differ).

## §9 Contraindications and hard NOTs

A short list of hard prohibitions, enforced by `psap-safety-monitor`
and audited by `psap-auditor`. Violation = immediate intervention.

- **Never** dose any medication.
- **Never** instruct blind finger sweeps in any age for choking.
- **Never** instruct chest compressions on a responsive patient with
  a pulse.
- **Never** instruct the caller to remove an impaled object.
- **Never** instruct the caller to move a patient with suspected
  spinal injury except to preserve airway.
- **Never** give age-inappropriate compression depth, rate, or
  technique.
- **Never** use MPDS script verbatim (license scope).
- **Never** provide diagnostic or prognostic claims ("you're having
  a heart attack"); use observational framing ("the symptoms you're
  describing can happen with several serious conditions").
- **Never** proceed under a self-verify-failed turn record.

Every `NEVER` above maps to at least one GEDP-anchored check in
`psap-safety-monitor` and one rubric criterion in `psap-rubric-live`.

## §10 Versioning policy

GEDP v0.1 is the initial public release of the protocol as part of
prism42's public demo. Versioning:

- **Major** (v1.0, v2.0): new chief-complaint families added; base
  methodology revision.
- **Minor** (v0.2, v0.3): per-complaint revisions; new PDI scripts;
  contraindication updates.
- **Patch** (v0.1.1): typos; citation date bumps; structural edits
  that do not change clinical content.

Clinical-content changes (minor + major) require physician-direction
re-sign (§7). Patches may proceed without re-sign.

Every version carries a changelog block in this doc's front-matter
region identifying what changed relative to the prior version and
the clinical rationale (cited).

---

*End of GEDP v0.1. Phase 2 extensions to §5.3–5.21 and full
child/infant PDI variants queued; see
`docs/agents/topology.md §7` for release sequencing.*
