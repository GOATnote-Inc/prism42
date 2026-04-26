# Anti-Stuck Patterns for the Prism42 Trauma FSM

**Cycle:** 2D9 — anti-stuck question loop
**Date:** 2026-04-26
**Trigger:** Live demo at 14:28 — FSM asked "Where is the bleeding, and how heavy?" three consecutive times after the caller said "his bone is sticking out of his legs, and he's got some blood on his chest." A substantive, dispatcher-grade answer was treated as silence by our state machine.

---

## Executive summary — what the FSM should emit / detect differently

1. **An answer is anything that mentions a body part OR a severity descriptor OR a mechanism word.** Our FSM is treating only enumerated keywords as answers; trained dispatchers accept "bone sticking out / blood on his chest" as a fully usable bleeding-location answer because it carries body-parts (legs, chest) plus mechanism (open fracture, blood). Single-keyword detection is the wrong specification.
2. **The "good enough" threshold is time, not completeness.** AHA T-CPR sets a hard 90-second arrest-recognition ceiling and 150-second first-compression ceiling [AHA T-CPR PMs]. That guidance is generalizable: every additional question costs seconds the patient does not have. The FSM should advance after one answer-shaped utterance OR after a max-question budget, whichever comes first.
3. **Never re-ask in identical wording.** APCO-grade active-listening curricula and the Tracy/Tracy facework research treat repeated questions as a face-threatening act that erodes caller trust ("are they not listening to me?"). At minimum, re-asks must paraphrase, not echo.
4. **Acknowledge-then-advance, not re-ask-on-uncertainty.** The trained move when the caller's answer is partial, off-topic, or panicked is to acknowledge what was said and pivot to the next instruction. "Okay, I hear you — start pressing on the chest wound, hard, with whatever clean cloth you have." This single move replaces our retry loop.
5. **Show the caller's words on screen.** Modern PSAP CAD systems (VESTA NXT, Smart Transcription) display real-time caller transcription to the call-taker. Our voice agent should commit a transcribed turn to UI state the instant ASR finalizes, regardless of whether the FSM has classified it. The user's contract — "when a user speaks they expect to see their words on screen" — is the published industry standard, not an idiosyncratic ask.

---

## Answer-recognition rules

Public dispatcher curricula are explicit that information-gathering is structured around *Where, What, Weapon, When, Who, How* (Virginia DCJS dispatcher standards) — and that the call-taker verifies understanding by **paraphrasing or repeating the caller's words back**, not by re-asking [DCJS Communication]. Acknowledgment is achieved through "Uh huh," "OK," "Alright," "Go ahead" tokens, or by repeating the last word or phrase the caller stated. None of these published rules condition advancement on the dispatcher having heard a specific keyword.

For severe-bleeding triage specifically, the public Stop the Bleed and IAED guidance treats "**life-threatening bleeding**" as a category recognizable by *quantity* ("a large amount of bleeding that is continuous and is enough to pool in clothing or on the ground") OR *location* ("specific location on the body, as clothing can affect the bleeding") [Stop the Bleed; IAED *Stop the Bleed*]. Either signal alone is enough to advance into pre-arrival instruction.

For an FSM, this implies the answer-recognition predicate for the bleeding key question should fire on ANY of:

- **Body-part token:** leg(s), arm(s), chest, neck, head, abdomen, back, hand, foot, groin, hip, thigh, shoulder. (Source: standard anatomic vocabulary used in Stop the Bleed bystander training.)
- **Mechanism / wound-shape token:** sticking out, broken, bone, cut, gash, wound, hole, gunshot, stab, ripped, torn, crushed, mangled, open. ("Stop the Bleed" and IAED both reference these mechanisms when teaching bystander recognition.)
- **Severity / quantity token:** a lot, lots, gushing, pouring, pooling, spurting, soaked, bleeding bad, won't stop, everywhere, all over.
- **Negation/no-bleed token:** "no blood," "not bleeding," "I don't see blood" — these also count as answers and should flow to a different next-step branch.

Our demo failure case ("bone is sticking out of his legs, and he's got some blood on his chest") satisfies **three** of the four predicates simultaneously. Any reasonable answer-recognition rule passes this turn.

---

## Good-enough advance threshold

The dominant published principle is **time-bounded triage, not perfect interrogation**. AHA T-CPR sets the binding numbers [AHA T-CPR PMs; Torres AEDR]:

- Arrest recognition: **<90 seconds** (high-performing agencies target <60 s).
- First T-CPR-directed compression: **<150 seconds**.
- Telecommunicator-recognized OHCA receiving T-CPR: target 75%+.

The Torres time-analysis paper makes the operational principle blunt: "**Compress more, talk less!**" Questions that "do not change response level or provide for scene or responder safety [are] counterproductive." The "Fast Track" mechanism — which lets a dispatcher skip downstream questions once obvious arrest signs are confirmed — is described as "the EMD's best friend" because it eliminates redundant questioning [Torres AEDR].

For trauma/bleeding, no equivalent FDA-grade benchmark exists publicly, but the IAED's "Stop the Bleed" coverage and the Annals/JNTM Joint Position Statement on Prehospital Hemorrhage Control both emphasize that direct pressure should begin as fast as humanly possible, with tourniquet escalation if pressure fails [Annals Joint Position; Springer Stop the Bleed].

For our FSM, "good enough" should be operationalized as the disjunction of:

- **Answer-recognition predicate fired** (any of the four token classes above), OR
- **Question-budget exhausted** (e.g. the same question has been asked once with no answer-shaped reply for N seconds), OR
- **Hard-time-budget exhausted** (e.g. >30 s on a single key question — the recognition-time discipline scaled to a per-question slice of the 90 s budget).

Whichever fires first triggers an acknowledge-then-advance transition, not a re-ask.

---

## Anti-repetition discipline

The published research is unambiguous that **repeated identical questions are a face-threatening act**. Karen Tracy and Sarah Tracy's foundational work *Rudeness at 911: Reconceptualizing Face and Face Attack* analyzes 650 calls and 400+ observational notes and frames repeated, identically-worded calltaker queries as one of the canonical face-attack patterns, eroding caller cooperation and inflating call duration [Tracy & Tracy, *Rudeness at 911*]. A subsequent Tracy paper (*When questioning turns to face threat*) extends the finding: "asking questions and taking down information is one of the most important, yet problematic, parts of a 911 call-taker's job, as citizens often resist answering questions" [Tracy, Semantic Scholar abstract].

The remediation in active-listening curricula is consistent. Virginia DCJS dispatcher communication standards require dispatchers to **paraphrase, mirror, or repeat the last word or phrase** the caller said — explicitly to "demonstrate that you have listened, understood, and are able to repeat and verify the information you heard" [DCJS Communication]. The same standard requires acknowledgment tokens between substantive moves.

APCO Project 33 / ANSI 3.103.2.2015 — the national minimum-training standard for public-safety telecommunicators since 1995 — treats active listening and verification-by-paraphrase as core competencies inside the EMS-dispatcher track [APCO Standards page; APCO P33 *Officer.com*]. The standard does not enumerate a "do not repeat" rule by name in the public abstract, but the entire active-listening pedagogy it codifies — paraphrase, mirror, verify — exists precisely *to remove the need for re-asking*.

Operational rule for our FSM: **if a re-ask is unavoidable, it must paraphrase, not echo**. "Where is the bleeding?" → "Tell me which part of him is bleeding the most." Echo loops are the failure signature of a system that has not committed the caller's previous turn into state.

---

## Acknowledge-then-advance pattern

This is the highest-leverage pattern in the public literature, and it is the move our FSM is missing.

The IAED's *Help! There's Not A Protocol For This!* article shows the canonical acknowledge-then-pivot in action: a dispatcher facing a water-birth call without protocol coverage stated "I don't have any instructions to navigate a water birth," **then remained on the line, monitored, and escalated** rather than re-cycling questions [IAED *No Protocol*]. The principle the article extracts: "Protocols are based on probabilities, and not everything is reasonably probable. For that reason, EMDs need to be familiar with the Protocol's goals and objectives" — i.e. once the goal (e.g. *bleeding control begun*) is achievable from the partial information available, advance.

The redirection-as-directive pattern (Penn-Tay et al., *Calming emotional 911 callers*, *Patient Education and Counseling* 2021) extends this: the trained move with a panicked or off-topic caller is **a patient-focused imperative directive, not another interrogative**. "Okay — put your hand on the wound and press hard" is a redirection that simultaneously acknowledges the caller's distress and converts them from interrogation-target to action-taker.

The dispatcher reassurance phrasing observed in Los Angeles County Dispatch Pre-Arrival Guidelines and in Stratford EMS practice is also instructive: *"Listen carefully. I'll tell you what to do."* and *"Sir, if you can hear me, we are coming as quickly as we can for you, okay?"* [LA County DHS Dispatch Guidelines; Stratford EMS]. Both are imperatives that act as transitions — they signal *I have what I need, now act with me*.

For our FSM, the pattern compiles to:

```
on (answer_recognized OR budget_exhausted):
    emit acknowledgment_token (paraphrase the caller, not echo our own question)
    transition to next_instruction_state
```

Concrete example for our demo failure: caller said "bone is sticking out of his legs, and he's got some blood on his chest." The acknowledge-then-advance utterance is: *"I hear you — bone showing on the leg, blood on the chest. Press hard on the chest wound with a clean cloth. Don't let up. Tell me when you have pressure on it."*

That single utterance mirrors the caller's words (paraphrase), commits to action (imperative directive), and creates the next state-transition trigger ("tell me when…"). It satisfies every published dispatcher pedagogy listed in this document.

---

## Body-part / severity vocabulary (paraphrased, no proprietary)

These are the dispatcher-relevant vocabulary clusters extractable from public sources (Stop the Bleed bystander training, IAED Journal Stop the Bleed coverage, StatPearls EMS Pre-Arrival, Annals Joint Position Statement, Mayo/AHA hands-only/Stop-the-Bleed lay materials). None is proprietary MPDS/ProQA card text.

**Body-part location tokens (extremities, torso, head):**
leg, legs, thigh, knee, calf, shin, ankle, foot; arm, arms, shoulder, elbow, forearm, wrist, hand; chest, abdomen, belly, stomach, side, flank, back, ribs; neck, head, scalp, face, jaw; groin, hip, pelvis.

**Junctional/critical-zone tokens (per the EMS Junctional Hemorrhage StatPearls):**
groin, armpit, neck, shoulder — these signal that direct pressure may be insufficient and that wound-packing escalation is on-protocol.

**Mechanism / wound-shape tokens:**
gunshot, shot, stab, stabbed, cut, slashed, gash, gash, hole, puncture, bone showing, bone sticking out, open fracture, mangled, crushed, ripped, torn, amputated, missing.

**Severity / quantity tokens:**
a lot, lots, gushing, pouring, pumping, spurting, pooling, soaked, soaking through, won't stop, can't stop, everywhere, all over, like a river, getting pale, going white.

**Color / temporal severity tokens:**
bright red (arterial), dark red, black; getting worse, getting faster, slowing down; going limp, going cold.

For our FSM, the answer-recognition predicate need not be exhaustive — it just needs to cover the high-frequency tokens, especially the severity cluster, because severity descriptors generalize across body parts.

---

## Transcription contract for callers

The user's spec — "when a user speaks they expect to see their words on screen" — is **the standard PSAP design contract**, not a novel requirement.

NENA's CAD Knowledge Base entry defines CAD as a system that automates dispatching and record-keeping for the call-taker, with caller information populated into CAD templates in real time [NENA CAD KB]. The location, reporting party, and incident fields are explicitly populated *as the caller speaks*, not after the call.

Modern Next-Generation 9-1-1 call-handling platforms have made this verbatim. Motorola/Vesta's VESTA 9-1-1 and VESTA NXT both ship "Smart Transcription" / "real-time transcription" as a marketed feature, providing call-takers with searchable transcripts and immediate audio access alongside live caller text [Vesta NXT marketing copy via MCA Dispatch; Motorola CAD product page]. The published rationale is "improving oversight, incident analysis, and multi-language communication" — the same affordance our demo UX needs.

For Prism42 specifically, the operational implication is that ASR-finalized turns must be committed to the dispatcher-facing UI as soon as they are recognized, **regardless of whether the FSM has classified them as an answer**. The transcript display is upstream of and decoupled from the answer-classifier. If the ASR confidence is low or the FSM rejects the turn, the right move is to show the words and a paraphrase ack, not to swallow the turn and re-ask.

---

## Sources cited

- [AHA T-CPR Recommendations and Performance Measures](https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures) — fetched 2026-04-26.
- [AHA Telecommunicator CPR Policy Statement, *Circulation*](https://www.ahajournals.org/doi/10.1161/CIR.0000000000000744) — referenced 2026-04-26 (full text gated 403; abstract/measures cited via AHA performance-measures page above).
- [Torres et al., "Beating the Clock to Save Lives," *AEDR Journal*](https://www.aedrjournal.org/beating-the-clock-to-save-lives--a-time-analysis-of-critical-steps-in-dispatcher-directed-cpr-jeremy-torres-nrp-ed-q) — fetched 2026-04-26.
- [Tracy & Tracy, *Rudeness at 911: Reconceptualizing Face and Face Attack* (PDF)](https://www.agence911.org/wp-content/uploads/2017/11/Tracy-Tracy-Rudeness-at-911.pdf) — referenced 2026-04-26 (PDF binary; cited via search-result abstracts and Semantic Scholar companion paper).
- [Tracy, "When questioning turns to face threat: An interactional sensitivity in 911 call-taking" (Semantic Scholar)](https://www.semanticscholar.org/paper/When-questioning-turns-to-face-threat:-An-in-911-Tracy/7abd09ce1d438a192e759ca76c7c48ad693f6c25) — fetched 2026-04-26.
- [Penn-Tay et al., "Calming emotional 911 callers: Using redirection as a patient-focused directive in emergency medical calls," *Patient Education and Counseling*](https://www.sciencedirect.com/science/article/pii/S0271530921000707) — referenced 2026-04-26 (publisher 403; cited via search-result abstract).
- [APCO 3.103.2.2015 Minimum Training Standards for Public Safety Telecommunicators](https://www.apcointl.org/standards/3-103-2-2015-minimum-training-standards-for-public-safety-telecommunicators/) — fetched 2026-04-26.
- [APCO Project 33 Training Program Certification (Officer.com)](https://www.officer.com/command-hq/technology/communications/article/10162081/apcos-2010-project-33-training-program-certification) — fetched 2026-04-26.
- [Virginia DCJS Dispatcher Communication Standards](https://www.dcjs.virginia.gov/law-enforcement/manual/standards-performance-outcomes/dispatchers-effective-march-30-2019/communication) — fetched 2026-04-26.
- [StatPearls: EMS Pre-Arrival Instructions (NCBI Bookshelf NBK470543)](https://www.ncbi.nlm.nih.gov/books/NBK470543/) — fetched 2026-04-26.
- [StatPearls: EMS Junctional Hemorrhage Control (NCBI Bookshelf NBK597371)](https://www.ncbi.nlm.nih.gov/books/NBK597371/) — fetched 2026-04-26.
- [IAED Journal: *Stop the Bleed*](https://www.iaedjournal.org/stop-the-bleed-2) — fetched 2026-04-26.
- [IAED Journal: *Help! There's Not A Protocol For This!*](https://www.iaedjournal.org/help-theres-not-a-protocol-for-this) — fetched 2026-04-26.
- [Stop the Bleed (American College of Surgeons)](https://www.stopthebleed.org/) — fetched 2026-04-26.
- [Annals of Emergency Medicine: Prehospital Hemorrhage Control Joint Position Statement](https://www.annemergmed.com/article/S0196-0644(23)00209-3/fulltext) — fetched 2026-04-26.
- [Springer European J. Trauma & Emergency Surgery: Prehospital Bleeding Control Systematic Review](https://link.springer.com/article/10.1007/s00068-024-02726-1) — fetched 2026-04-26.
- [LA County DHS Dispatch Pre-Arrival Guidelines (PDF)](https://file.lacounty.gov/SDSInter/dhs/1031386_227.1EMSDispatchGuidelines.pdf) — fetched 2026-04-26.
- [Stratford EMS: *Pre-Arrival Instructions: Invasive Call-taking*](https://www.stratfordems.org/2016/04/09/pre-arrival-instructions-invasive-call-taking/) — fetched 2026-04-26.
- [NENA CAD Knowledge Base entry](https://kb.nena.org/wiki/CAD_(Computer-Aided_Dispatch)) — fetched 2026-04-26.
- [Motorola Solutions: Voice & Computer-Aided Dispatch](https://www.motorolasolutions.com/en_xu/products/command-center-software/voice-and-computer-aided-dispatch.html) — fetched 2026-04-26.
- [MCA Dispatch Solutions PSAP & E911 Software (VESTA NXT product copy)](https://callmc.com/voice-solutions/two-way-radios/dispatch-systems/psap-e911-software/) — fetched 2026-04-26.
- [Wikipedia: Computer-aided dispatch](https://en.wikipedia.org/wiki/Computer-aided_dispatch) — fetched 2026-04-26.
