# Dispatch Patterns: Verbal Structure of Emergency Calls

**Date:** 2026-04-26
**Cycle:** 2D4 dispatch research
**Scope:** Public-domain research on 911 / 999 / NHS-Pathways call structure and the verbal patterns dispatchers use to keep callers oriented and active.
**Out of scope:** Proprietary card-set text from MPDS / ProQA / AMPDS. Those systems are referred to conceptually only; no protocol cards are quoted.

---

## Executive summary — what should the FSM emit differently?

1. **Echo the address back, do not just acknowledge it.** The standard call-taking discipline (and the explicit teaching in public PSAP guidance) is to *repeat* the location to the caller verbatim, then ask them to confirm — "I have you at 1234 Maple Street, apartment 3B. Is that correct?" Acknowledgment without echo ("got your address") is a known failure mode; PSAP training material specifically requires the caller to *say* the address (sometimes twice, especially across an EMS transfer) so the dispatcher can verify what they wrote down ([Sarpy County, NE 911 FAQ](https://www.sarpy.gov/Faq.aspx?QID=293), [Caldwell County NC 911](https://caldwellcountync.org/187/What-to-Expect-When-You-Call-911), [MACC 911 Grant County](https://macc911.org/911-education/emergency-calls/)).
2. **Reassurance must couple to a directive.** "Help is on the way" by itself leaves the caller in the listening role. Trained dispatchers chain reassurance + role-assignment + first task in a single turn: "Help is rolling. I'm staying on the line. Right now I need you to do one thing for me — …". The caller has to be *given a job* immediately or they will ask "what do I do?" — that question is itself a documented failure mode of pure reassurance language ([Resgrid blog on dispatcher communication](https://blog.resgrid.com/what-do-911-dispatchers-do/), [StatPearls EMS Pre-Arrival Instructions](https://www.ncbi.nlm.nih.gov/books/NBK470543/)).
3. **Use the "look, listen, and feel" recognition pattern, not yes/no probes.** A 2023 *Prehospital Emergency Care* qualitative study found 100% (19/19) of cardiac arrests were correctly identified when dispatchers used a "look, listen, feel" structured assessment vs. a much lower rate with open-ended yes/no probes. ([Missel et al. 2023, PMC11259182](https://pmc.ncbi.nlm.nih.gov/articles/PMC11259182/)).
4. **Pre-arrival instructions are issued in the imperative, not the interrogative.** StatPearls' guidance is explicit: dispatchers should **assume** the caller will help and never *ask* permission — offering options ("can you do CPR?") discourages action. The FSM should default to "Put the heel of your hand on the center of their chest" rather than "are you willing to do compressions?" ([StatPearls EMS Pre-Arrival Instructions](https://www.ncbi.nlm.nih.gov/books/NBK470543/)).
5. **AHA T-CPR performance gates are time-bound; the FSM phases must finish on a clock.** AHA goal: cardiac-arrest recognition < 90 seconds, first directed compression < 150 seconds from call receipt. That envelope sets the tempo for every preceding phase — opening, address echo, chief-complaint determination — they all must complete inside ~60-90s combined. ([AHA T-CPR recommendations and performance measures](https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures), [2019 AHA Focused Update on Systems of Care](https://www.ahajournals.org/doi/10.1161/CIR.0000000000000733)).

---

## Universal call structure

The conversation-analysis literature has converged on a 5-phase canonical skeleton, originally formalised by Whalen and Zimmerman (1987) and stable across 30+ years of follow-up research ([Whalen & Zimmerman 1987 *Social Psychology Quarterly*](https://www.scirp.org/reference/referencespapers?referenceid=410409); [Inside the Emergency Service Call-Center: 30 Years of Research review, Tracy & Robles](https://www.academia.edu/124806234/Inside_the_Emergency_Service_Call_Center_Reviewing_Thirty_Years_of_Language_and_Social_Interaction_Research)):

1. **Opening / identification.** "911, what's the address of the emergency?" or in UK 999, "Ambulance, tell me exactly what's happened." The opening utterance is a **summons** that simultaneously identifies the service and pre-allocates the next-turn slot to the caller's request. Notable: the address is asked *first* in US PSAPs because of historical landline-ANI failures and because the address is the only piece of information that is unrecoverable if the line drops.
2. **Request / chief complaint.** Caller delivers the reason for the call. Conversation analysts call this slot the "request" turn. It is the most failure-prone phase because callers in distress often produce dysfluent, self-repaired, narratively-organized speech instead of a clean request. (See "Where Trouble Starts: Communication Breakdown in a Complex Emergency Call," Tandfonline 2024, on the South-Africa axe-attack case where misalignment in the request phase poisoned the rest of the call: [Tandfonline DOI 10.1080/10410236.2024.2346677](https://www.tandfonline.com/doi/full/10.1080/10410236.2024.2346677).)
3. **Interrogative series.** Dispatcher drives a structured question hierarchy. NHS Pathways orders questions by *clinical hierarchy* — life-threatening conditions probed first, then descending acuity ([NHS Digital — NHS Pathways](https://digital.nhs.uk/services/nhs-pathways)). NAEMD/IAED proprietary cards do the same conceptually; APCO Project 33 mandates this be done in plain language without jargon ([APCO ANS 3.103.2.2015 Minimum Training Standards](https://www.apcointl.org/standards/minimum-training-standards-forpublic-safety-telecommunicators/)).
4. **Response / dispatch + pre-arrival instructions.** Resources are sent (often in parallel by a second dispatcher); the call-taker stays on the line and delivers pre-arrival instructions appropriate to the chief complaint. StatPearls categorises pre-arrival instructions into: general safety / medication / responder-access; hemorrhage control; choking; cardiac arrest (compressions); respiratory arrest and drowning; and childbirth ([StatPearls](https://www.ncbi.nlm.nih.gov/books/NBK470543/)).
5. **Closing / handoff.** Dispatcher confirms responder arrival, hands off, and releases the caller. Notably, the closing phase often stays open until the responding unit is *physically with* the patient — not until ETA — so the caller is never left without coaching while help is en route.

The NHTSA *Emergency Medical Dispatch National Standard Curriculum* (originally 1972, the foundation document for US EMD training) baked this structure into call-taking modules ([NHTSA EMD National Standard Curriculum, RoSAP archive](https://rosap.ntl.bts.gov/view/dot/13745); [NHTSA EMS Education Standards 2021](https://coaemsp.org/wp-content/uploads/2025/11/EMS_Education-Standards_2021_FNL1.pdf)).

---

## Address echo discipline

Public PSAP-facing material is unusually specific about *how* to handle the address — because address errors are the single most common preventable cause of late response.

**The discipline (paraphrased from public PSAP "what to expect when you call 911" pages and APCO P33 training):**

- Ask first, before anything else, even if ANI/ALI auto-populates the screen. Auto-location can be stale, wrong, or report the carrier's centroid rather than the caller's actual position.
- After the caller says it, **read it back verbatim** to the caller — including unit / apartment / floor — and request explicit confirmation.
- If the caller is being transferred from PSAP to EMS, the EMS call-taker re-asks the address. The caller is told they will be asked twice "because the medical dispatcher will confirm the information to ensure it has not been lost or distorted during the transfer" ([Sarpy County FAQ](https://www.sarpy.gov/Faq.aspx?QID=293)).
- Confirm whether the caller is *at* the incident location or *somewhere else* reporting on behalf of someone else — these are different dispatch problems ([City of Eugene 9-1-1 Call Scripts](https://www.eugene-or.gov/2892/9-1-1-Call-Scripts)).

**Paraphrased verbal skeleton (synthesized from the public sources, not quoted from any proprietary card):**

> "Okay, I have you at *<address-as-heard>*. Is that correct?"

> "Are you with *<patient>* right now, or are you somewhere else?"

A non-echoing "got your address" violates this standard for two reasons: (a) the caller has no chance to correct a mishearing, and (b) it provides no closure on the address phase, so anxious callers often re-introduce the address mid-CPR-coaching, which derails the instruction stream.

---

## Reassurance + redirect: the "what do I do next" gap

This is the failure pattern the user reported in the demo. Public dispatcher training and academic linguistic research converge on the same fix: **reassurance is glued to a redirect.**

**The pattern, paraphrased:**

> "Help is on the way. I'm going to stay on the line with you. Right now I need you to *<verb-phrase>*."

The first sentence is the safety-assurance ([Resgrid blog](https://blog.resgrid.com/what-do-911-dispatchers-do/)). The second establishes co-presence ("I'm staying with you" / "I'm not going anywhere" / "you're not alone"). The third is the *job assignment* — and it must be a single, concrete, performable verb, not a question. The Tracy & Robles 30-year review (Academia.edu copy linked above) characterizes this as the "sequential glue" that prevents the caller from collapsing into a passive listener role. When the third sentence is missing, callers very predictably ask the question the user observed: "okay, but what do I do?"

**Why "asking" is wrong.** StatPearls is explicit:

> When callers are provided with pre-arrival instructions, it should be assumed and never asked that they are willing to provide aid. Offering options may discourage participation. ([StatPearls](https://www.ncbi.nlm.nih.gov/books/NBK470543/))

So the dispatcher does not say "are you willing to start CPR?" — they say "I want you to put your hand on the center of their chest." The shift from interrogative to imperative is *the* operator move.

**Acknowledge + redirect cadence inside the interrogative series:**

> "Okay, I have your address — now tell me exactly what's happened."

> "Got it. Stay with me. Is he breathing?"

This pattern (acknowledge prior turn → bridge → next question) appears in both NHS Pathways and US EMD curricula. APCO Project 33 explicitly forbids "uh, hold on" / "let me check" / extended silence in the call-taker's turn — silence reads to a panicked caller as abandonment ([APCO P33](https://www.apcointl.org/standards/minimum-training-standards-forpublic-safety-telecommunicators/)).

---

## Cardiac and trauma transition patterns

### Telephone-CPR (T-CPR) cadence — public-domain only

The American Heart Association publishes performance and program-level recommendations publicly; the *exact* card-text used in any given PSAP is typically proprietary (MPDS, Power-Phone, etc.). What is in the public record:

- **Recognition gate.** Two questions, in sequence: "Is the patient conscious?" and "Is the patient breathing normally?" Two NOs → presumed cardiac arrest, dispatch and proceed to T-CPR. ([AHA T-CPR Recommendations](https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures); confirmed in the dispatch-research review at [PMC8760425](https://pmc.ncbi.nlm.nih.gov/articles/PMC8760425/) where the algorithm is described as the "NO-NO-GO" pattern.)
- **Recognition technique.** "Look, listen, and feel" structured assessment, with the dispatcher coaching the caller through positioning the patient and observing chest rise — produced 100% recognition in Missel et al. 2023's qualitative cohort ([PMC11259182](https://pmc.ncbi.nlm.nih.gov/articles/PMC11259182/)).
- **Compression rate.** 100-120 per minute, hands-only, no ventilation for adult bystander CPR (AHA hands-only call-to-action paper, Sayre et al. *Circulation* 2008: [DOI 10.1161/circulationaha.107.189380](https://www.ahajournals.org/doi/10.1161/circulationaha.107.189380); Mayo Clinic public hands-only CPR script: [Mayo Clinic Minute](https://newsnetwork.mayoclinic.org/n7-mcnn/7bcc9724adf7b803/uploads/2019/07/MCM-Script-Learn-hands-only-CPR.pdf)).
- **Time gates.** Recognition < 90 seconds from call receipt; first directed compression < 150 seconds. 75% of OHCAs should be recognized by telecommunicators; T-CPR delivered in 75% of recognized cases ([AHA T-CPR](https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures)).
- **Cadence-keeping technique.** Dispatchers commonly count out loud with the caller (e.g., "one and two and three...") to entrain rate; some use a metronome tone or a song-tempo prompt ("Stayin' Alive" is the canonical public-health teaching). The Medical College of Wisconsin telecommunicator-CPR protocol document (linked in search results, but PDF was not text-extractable in this session) is one published example ([MCW T-CPR Protocols](https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf)).

### The verbal bridge: "help dispatched" → "compressions"

Paraphrased from the public guidance:

> "I have an ambulance on the way. I'm staying with you. Listen carefully — I'm going to tell you exactly what to do. Get them flat on their back on the floor. Tell me when you've done that."

Three operator moves: (a) status report on dispatch, (b) co-presence statement, (c) **immediate first physical action**. Note the action requested is *positioning* — the easiest, lowest-skill thing the caller can do — and it includes a **return-token** ("tell me when you've done that") that gives the caller something to say back, which keeps them oriented and lets the dispatcher pace the next instruction.

### Hemorrhage / trauma transition

The same pattern adapted: "Ambulance is rolling. Stay with me. I need you to press down hard on the wound with whatever clean cloth you have. Press as hard as you can and don't let up. Tell me when you've got pressure on it." Per StatPearls, hemorrhage pre-arrival instructions are direct pressure first, elevation second, tourniquet only if available and trained ([StatPearls](https://www.ncbi.nlm.nih.gov/books/NBK470543/)).

### Direct Patient Care Instructions vs Pre-Arrival Instructions

Public sources do not draw a sharp universal distinction between these terms. In most US EMD programs (including the King County, WA program — one of the longest-running public-record programs), "pre-arrival instructions" is the umbrella term covering everything the dispatcher coaches before the unit physically arrives ([King County EMD program](https://kingcounty.gov/en/dept/dph/health-safety/health-centers-programs-services/emergency-medical-services/emergency-medical-dispatch); [San Diego County EMS S-882 draft](https://www.sandiegocounty.gov/content/dam/sdc/ems/public_comment/DRAFT%20CoSD%20EMS%20S-882%20Emergency%20Medical%20Dispatch%20Programs%20CLEAN%201%203%2024.pdf)). Some training texts distinguish "Direct Patient Care Instructions" (active interventions: CPR, hemorrhage control, Heimlich, childbirth) from "Pre-Arrival Instructions" (preparatory: unlock the door, secure pets, gather meds), but the labels are not standardised across systems. The functional distinction worth modeling in an FSM is **active intervention vs scene preparation** — those are different cadences and different acceptable interruption points.

---

## Failure-mode case studies

### 1. Communication breakdown in a complex emergency call (axe-attack case, South Africa)

Tandfonline 2024 published a single-case linguistic analysis of a triple-homicide call from an upmarket South African golfing estate. Misalignment began in the *opening / request* phase: the caller's framing failed to convey urgency in conventionally recognizable form, and the dispatcher's questions were operating on a different incident model than the caller. Failure cascaded — "an absence of urgency and emotion in his description of the incident, an extended focus on and repair of the incident location, and his dysfluent speech behavior" all contributed to the dispatcher doubting credibility and prolonging the call. ([Where Trouble Starts, Tandfonline DOI 10.1080/10410236.2024.2346677](https://www.tandfonline.com/doi/full/10.1080/10410236.2024.2346677)). **FSM lesson:** when the caller's first turn does not parse cleanly, do not loop on address — pivot fast to the chief-complaint probe and avoid extended location-repair.

### 2. NPR — baby in cardiac arrest, dispatcher untrained in T-CPR

NPR's 2019 reporting documented a case where a dispatcher took a call about a baby in cardiac arrest but had no T-CPR training. The dispatcher could not coach the caller through compressions; the baby died ([NPR 2019 transcript](https://www.npr.org/transcripts/710331622)). The story is widely cited in support of the federal *CPR LifeLinks* initiative, which now publishes a public toolkit for any PSAP wanting to stand up a T-CPR program ([911.gov CPR LifeLinks](https://www.911.gov/projects/cpr-lifelinks/)). **FSM lesson:** the recognition→compressions transition must be a hard-coded path, not optional; the dispatcher (or AI) cannot skip it.

### 3. Potomac River drowning — information dropped in the dispatch transcript

Maryland dispatchers received a call about a teen who had slipped underwater. The caller specified "an inlet off the river" and "in Virginia" — but neither datum was typed into the CAD record, so responders went to the Maryland side. ([Cited in the convey911 PSAP best-practices article](https://www.convey911.com/blog/dispatch-for-911-guide).) **FSM lesson:** narrative context that *modifies* the address (which side of the river, which entrance, which apartment) must be captured and *echoed back to the caller* the same way the address itself is. A bare "got your address" never surfaces the caller's geographic-disambiguator clauses.

### 4. Recognition-phase failures (Missel et al. 2023)

Of 13 failed-recognition cases studied: dispatchers accepted hedged caller language ("kind of" conscious, "eyes are not open", "she's sort of breathing") as ambiguous and routed accordingly, missing the cardiac arrest. The "look, listen, feel" structured assessment, by contrast, recognized 19/19 arrests ([Missel et al., PMC11259182](https://pmc.ncbi.nlm.nih.gov/articles/PMC11259182/)). **FSM lesson:** when a caller hedges, the FSM should escalate to a structured physical-observation prompt, not accept the hedge as a binary answer.

### 5. Discourse-of-distress narrative analysis

The Tracy & Anderson *Discourse and Society* foundational corpus study estimated up to 60% of calls were "lost" or screened out at some point in the dispatcher process — typically due to communication breakdowns or the dispatcher's inability to extract a parseable request ([narrative analysis PDF](https://www.agence911.org/wp-content/uploads/2017/11/911-calls-discourse-of-distress.pdf)). **FSM lesson:** the FSM should treat ambiguity as a routine event, not an exception; explicit graceful-degradation paths (re-ask once, then pivot, then escalate) must exist for every required slot.

---

## Sources cited

All URLs fetched 2026-04-26.

**Primary public guidelines and standards**

- AHA. Telecommunicator CPR Recommendations and Performance Measures. <https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures>
- AHA / Kurz et al. 2019 Focused Update on Systems of Care: Dispatcher-Assisted CPR and Cardiac Arrest Centers. *Circulation*. <https://www.ahajournals.org/doi/10.1161/CIR.0000000000000733>
- AHA / Sayre et al. 2008. Hands-Only (Compression-Only) CPR — A Call to Action. *Circulation*. <https://www.ahajournals.org/doi/10.1161/circulationaha.107.189380>
- AHA. 2020 Guidelines for CPR and Emergency Cardiovascular Care, Part 1 Executive Summary. *Circulation*. <https://www.ahajournals.org/doi/10.1161/CIR.0000000000000918>
- APCO International. ANS 3.103.2.2015 Minimum Training Standards for Public Safety Telecommunicators (Project 33). <https://www.apcointl.org/standards/minimum-training-standards-forpublic-safety-telecommunicators/>
- NHTSA. Emergency Medical Dispatch: National Standard Curriculum (RoSAP archive). <https://rosap.ntl.bts.gov/view/dot/13745>
- NHTSA / CoAEMSP. 2021 National EMS Education Standards. <https://coaemsp.org/wp-content/uploads/2025/11/EMS_Education-Standards_2021_FNL1.pdf>
- NHS Digital. NHS Pathways — service information. <https://digital.nhs.uk/services/nhs-pathways>
- NHS Digital. NHS Pathways Clinical Enquiries Management Process. <https://digital.nhs.uk/services/nhs-pathways/nhs-pathways-service-information/clinical-enquiry-log/nhs-pathways-clinical-enquiries-management-process>
- 911.gov. CPR LifeLinks initiative — federal public toolkit for PSAP T-CPR programs. <https://www.911.gov/projects/cpr-lifelinks/>

**Academic / linguistic-research literature**

- Whalen MR, Zimmerman DH. 1987. Sequential and institutional contexts in calls for help. *Social Psychology Quarterly* 50:172-185. <https://www.scirp.org/reference/referencespapers?referenceid=410409>
- Tracy & Robles. Inside the Emergency Service Call-Center: Reviewing Thirty Years of Language and Social Interaction Research. <https://www.academia.edu/124806234/Inside_the_Emergency_Service_Call_Center_Reviewing_Thirty_Years_of_Language_and_Social_Interaction_Research>
- Perera N, Finn J, Bray J. Can emergency dispatch communication research go deeper? Editorial. *Resuscitation Plus*. <https://pmc.ncbi.nlm.nih.gov/articles/PMC8760425/>
- Missel AL et al. 2023. Barriers to the Initiation of Telecommunicator-CPR During 9-1-1 Out-of-Hospital Cardiac Arrest Calls: A Qualitative Study. *Prehospital Emergency Care* 28(1):118-125. <https://pmc.ncbi.nlm.nih.gov/articles/PMC11259182/>
- Where Trouble Starts: Communication Breakdown in a Complex Emergency Call. *Health Communication*, Tandfonline 2024. <https://www.tandfonline.com/doi/full/10.1080/10410236.2024.2346677>
- Tracy & Anderson. The discourse of distress: A narrative analysis of emergency calls to 911. <https://www.agence911.org/wp-content/uploads/2017/11/911-calls-discourse-of-distress.pdf>
- Clayman SE, Kevoe-Feldman H. 2023. Dispatching First Responders: Language Practices and the Dispatcher's Operational Role in Radio Encounters With Police Officers. *Discourse & Communication*. <https://journals.sagepub.com/doi/10.1177/09579265231164763>

**Reference and clinical-overview material**

- StatPearls / NCBI Bookshelf. EMS Pre-Arrival Instructions. <https://www.ncbi.nlm.nih.gov/books/NBK470543/>
- King County EMD Program (one of the longest-running public-record dispatch programs). <https://kingcounty.gov/en/dept/dph/health-safety/health-centers-programs-services/emergency-medical-services/emergency-medical-dispatch>
- San Diego County draft EMS S-882 Emergency Medical Dispatch Programs. <https://www.sandiegocounty.gov/content/dam/sdc/ems/public_comment/DRAFT%20CoSD%20EMS%20S-882%20Emergency%20Medical%20Dispatch%20Programs%20CLEAN%201%203%2024.pdf>
- Medical College of Wisconsin Telecommunicator-CPR Protocols (PDF; not text-extractable in this session, cited as published example). <https://www.mcw.edu/-/media/MCW/Departments/Emergency-Medicine/EMS/Telecommunicator-CPR-Program-Dispatch-Protocols-In-House.pdf>
- Mayo Clinic Minute Hands-Only CPR script. <https://newsnetwork.mayoclinic.org/n7-mcnn/7bcc9724adf7b803/uploads/2019/07/MCM-Script-Learn-hands-only-CPR.pdf>

**PSAP-facing public guidance ("what to expect when you call 911")**

- Sarpy County, NE 911 FAQ. <https://www.sarpy.gov/Faq.aspx?QID=293>
- Caldwell County, NC. What to Expect When You Call 911. <https://caldwellcountync.org/187/What-to-Expect-When-You-Call-911>
- MACC 911 (Grant County). 911 Education — Emergency Calls. <https://macc911.org/911-education/emergency-calls/>
- City of Eugene, OR. 9-1-1 Call Scripts. <https://www.eugene-or.gov/2892/9-1-1-Call-Scripts>
- Resgrid Blog. What Do 911 Dispatchers Do? <https://blog.resgrid.com/what-do-911-dispatchers-do/>
- Convey911. Dispatch for 911: The Critical Link in Emergency Response. <https://www.convey911.com/blog/dispatch-for-911-guide>

**Press / case-study reporting**

- NPR 2019. A Baby In Cardiac Arrest And An Emergency Dispatcher Who Did Not Know Telephone CPR. <https://www.npr.org/transcripts/710331622>

---

*Word count target 1500-2500; this document is approximately 2,400 words.*
