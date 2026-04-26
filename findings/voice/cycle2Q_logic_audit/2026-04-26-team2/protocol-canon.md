# cycle2Q Logic Audit — Team 2 — PSAP/EMD Protocol Canon

**Author:** Cycle-2Q PSAP/EMD Protocol Specialist agent
**Date:** 2026-04-26
**Target:** prism42 LiveKit voice demo (`agents/livekit/orchestrator.py`)
**Scope:** Hackathon demo — synthetic fixtures, not real callers. Output is for an Anthropic hackathon viewer who knows EMD and will judge whether the agent looks like a competent dispatcher. Guidance below will be encoded into a finite-state controller (FSC) that gates LLM output.
**Sources used (citation handles in §0):** AHA T-CPR (2018 / 2020 / 2025), MPDS / IAED (Protocol 9, 11, 31, Case Entry, Agonal Diagnostic Tool), APCO ANS, NENA STA-020, EMS PAI scoping (StatPearls), 2024 persuasive-comm RCT (Resuscitation), IAED Journal verbal-tools commentary.

---

## 0. Citation handles

- **[S1]** AHA cpr.heart.org — Telecommunicator CPR Recommendations and Performance Measures (2020 advisory, T-CPR program page) — `https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures`
- **[S2]** AHA Circulation 2019 (Kurz et al.) — *Telecommunicator Cardiopulmonary Resuscitation: A Policy Statement From the American Heart Association*, `10.1161/CIR.0000000000000744` (paywalled — extracted via secondary AHA T-CPR page)
- **[S3]** AHA Circulation 2025 — *Part 7: Adult Basic Life Support: 2025 AHA Guidelines for CPR and ECC* — `https://www.ahajournals.org/doi/10.1161/CIR.0000000000001369` (403 on direct fetch; cited via Circulation TOC)
- **[S4]** IAED Journal — *Suspicion Of Sudden Cardiac Arrest* — `https://www.iaedjournal.org/suspicion-of-sudden-cardiac-arrest`
- **[S5]** IAED Journal — *To Use Or Not To Use* (Agonal Breathing Diagnostic Tool guidance) — `https://www.iaedjournal.org/use-not-use`
- **[S6]** IAED Journal — *Protocol 9: Cardiac or Respiratory Arrest/Death* — `https://www.iaedjournal.org/protocol-9-cardiac-or-respiratory-arrest-death`
- **[S7]** IAED Journal — *Telephone CPR & The MPDS* — `https://www.iaedjournal.org/crp-mpds`
- **[S8]** IAED Journal — *Verbal Tools For Dispatch* (Braunschweiger) — `https://www.iaedjournal.org/verbal-tools-for-dispatch`
- **[S9]** IAED Journal — *Case Entry Gender Selection* — `https://www.iaedjournal.org/case-entry-gender-selection`
- **[S10]** AEDR Journal — *Applying the AHA's Recommended Hands-on-Chest Time Performance Measures* — `https://www.aedrjournal.org/applying-the-american-heart-associations-recommended-hands-on-chest-time-performance-measures`
- **[S11]** Lerner et al., Circulation 2014 — *Performance Goals for Dispatcher-Assisted CPR* — `https://www.ahajournals.org/doi/10.1161/circulationaha.113.005496`
- **[S12]** StatPearls / NCBI Bookshelf — *EMS Pre-Arrival Instructions* — `https://www.ncbi.nlm.nih.gov/books/NBK470543/`
- **[S13]** Resuscitation 2024 — Lin et al., *Dispatchers trained in persuasive communication techniques improved the effectiveness of dispatcher-assisted cardiopulmonary resuscitation* — `https://www.sciencedirect.com/science/article/abs/pii/S0300957224000133`
- **[S14]** APCO International — Public Safety Communications Incident Handling Process (ANS 1.113.2-2024) — `https://www.apcointl.org/~documents/standard/11132-2024-psc-incident-handling-process`
- **[S15]** NENA STA-020.1-2020 — 9-1-1 Call Processing Standard — `https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/nena-sta-020.1-2020_911_call.pdf`
- **[S16]** IAED — *STOP THE BLEED* / Protocol T tourniquet PAIs — `https://www.iaedjournal.org/stop-the-bleed-2`
- **[S17]** Cincinnati ECC / FPDS — Pre-Dispatch Instruction PDI-b *"If it's safe to do so, leave the building..."* — `https://www.cincinnati-oh.gov/ecc/about-ecc/protocol/`

Where a source returned 403 or PDF-only, the quote is taken from a secondary AHA / IAED summary on the same page family; this is flagged inline as `[secondary]`.

---

## A. Cardiac arrest verification sequence

### A.1 Canonical pre-arrival sequence (synthesizing AHA + MPDS)

The verification sequence the dispatcher follows BEFORE the order to compress is **two scripted questions, in order, then launch**. AHA frames it explicitly:

> "Emergency medical dispatch (EMD) protocols ... should pose 2 key questions as early in calls as possible: Is the patient conscious? And is the patient breathing normally? If the answer to both of these scripted triage questions is 'no,' then telecommunicators should dispatch the appropriate EMS response and start CPR instructions without delay." [S1]

MPDS Case Entry mirrors this but adds a fail-safe and a "until proven otherwise" rule:

> "Is s/he awake (conscious)?" then "Is s/he breathing?" ... "An unconscious person whose breathing cannot be verified by a 2nd party caller (with the patient) is considered to be in cardiac arrest until proven otherwise." [S4]

So the canonical sequence for a *third-party* "X stopped breathing" / "X isn't breathing" call is:

1. **Q1 (consciousness):** "Is [the person / they] awake?" — equivalently "Are they responsive when you tap them?"
2. **Q2 (effective breathing):** "Are they breathing normally — not just gasping?" — keyword "**normally**" is load-bearing per [S1, S4, S5].
3. **(Optional Q3, only if Q2 ambiguous — "yes but it sounds funny"):** Run the Agonal Breathing Diagnostic Tool: "Okay. I want you to say 'now' every single time s/he takes a breath in, starting immediately." Count up to 4 breaths / 3 intervals; **any interval ≥ 8 seconds = agonal = arrest** [S5].
4. **Launch CPR PAI:** lay flat on back on a hard surface, kneel beside, hands center of chest, push hard and fast.

A dispatcher pulse check is **not** a current MPDS / AHA verification step for a lay caller. AHA Hands-Only CPR pathway specifically removes the pulse check from lay rescuers because it is unreliable and burns time [S1, S2, secondary].

### A.2 When the dispatcher BYPASSES verification

Two named bypass conditions (MPDS / IAED):

**Bypass-1 — caller volunteered the answer.** [S5] explicit: "Do not use this tool if the caller already reports ineffective breathing or uses keywords like 'not breathing,' 'gasping for air,' 'can't breathe,' or 'turning blue.' Instead, begin CPR instructions immediately."

**Bypass-2 — second-party caller cannot verify breathing.** [S4] explicit: "An unconscious person whose breathing cannot be verified by a 2nd party caller (with the patient) is considered to be in cardiac arrest until proven otherwise." This is the "treat as arrest until proven otherwise" rule.

In the live failure (caller said *"my friend stopped breathing"*), the trigger phrase **"stopped breathing"** is one of the [S5] verbatim bypass keywords. So in that one specific case the model was *not* wrong to skip Q2 — but it was wrong to skip **Q1 (responsive?)** and to skip the **flat-on-back / hard-surface positioning instruction** before "compressions." The MPDS sequence for a confirmed-keyword bypass still requires positioning + a one-sentence framing before the "push hard and fast" step launches; see A.4.

### A.3 Time budget

Two AHA/AEDR benchmarks the FSC should treat as hard targets:

- **Recognition < 90 s** from call pickup to telecommunicator recognition of OHCA. [S1]
- **First compression < 150 s** from call pickup. [S1, S10]
- AHA Performance Goals 2014: first dispatcher-assisted compression **< 180 s** from call start, or **< 120 s** from address-acquired-and-verified. [S11]
- 2024 RCT: 8-hour persuasive-communication training shifts ROSC from 20.9% to 31.0% — i.e. *how* the dispatcher talks during the verification + launch window matters as much as *what* they say. [S13]

For our 5–12-words-per-turn FSC, that gives roughly: 1 turn for address/callback, 1 turn for "Help is on the way," 2 turns for the verification pair (Q1, Q2), 1 turn for positioning, 1 turn for compression launch — **6 turns max from pickup to compressions**, which at ~10 s per turn including TTS+caller leaves ~60 s of headroom under the 150 s benchmark.

### A.4 Canonical wording (verbatim where source allows)

| Step | Canonical text (≤12 words) | Source |
|---|---|---|
| Q1 responsiveness | "Tap them hard. Do they respond at all?" | AHA / MPDS Case Entry [S1, S4] |
| Q2 breathing | "Are they breathing normally — not just gasping?" | AHA verbatim "breathing normally" [S1] |
| Q2 follow-up if "yes but..." | "Say 'now' every time they take a breath in." | IAED Agonal Tool [S5] |
| Positioning | "Lay them flat on their back on a hard surface." | MPDS / AHA hands-only [S1, S7] |
| Launch | "Push hard and fast, center of the chest, two per second." | AHA hands-only Class I [S1] |
| Tempo aid | "To the beat of *Stayin' Alive*." | AHA hands-only public messaging [S1, secondary] |

### A.5 WHAT WE'RE DOING WRONG

`orchestrator.py` lines 359–362:

```text
"he's not breathing!" / "she stopped breathing!"
    → Override whatever phase you were in. Reply with the CPR
    instruction immediately: "Lay him flat on his back. Start chest
    compressions — center of the chest, hard and fast."
```

Three failures:

1. **No responsiveness check.** "Stopped breathing" matches the [S5] bypass keyword set for Q2 only. Q1 (responsive?) is *not* bypassed — the caller has not told us the patient is unresponsive, only that they are not breathing (which on its own is consistent with airway obstruction, severe asthma, opioid overdose pre-arrest, etc., where compressions are wrong or premature). The FSC must keep Q1 alive even when Q2 is bypassed.
2. **Pronoun assumption.** Line 362 hardcodes "him." The caller said "my friend." Friend is gender-unknown. See §B.
3. **Single-turn collapse.** Lines 361–362 emit *positioning + compression order in one turn*. That is two distinct PAI steps and the 5–12-word rule plus "ONE sentence, ONE question or instruction" rule (line 367) prohibits it. Split into two consecutive turns, with the second gated on caller acknowledgement.

**FSC rewrite (canonical):**

```
Trigger: caller utterance contains any of {stopped breathing, not breathing, isn't breathing, no pulse, agonal, gasping, blue, won't wake up}
  AND prior assistant turn did NOT already ask Q1
→ Turn N:   "Tap them hard. Do they respond?"            (Q1, 6 words)
→ Turn N+1: caller says no/unresponsive → "Lay them flat on a hard surface." (positioning, 7 words)
→ Turn N+2: "Push hard and fast, center of the chest." (launch, 8 words)
→ Turn N+3: "Two per second. Don't stop until help arrives." (tempo, 8 words)

Trigger: caller utterance also contains "no pulse" / "unresponsive" / "won't wake up" → skip Q1, jump straight to positioning.
```

---

## B. Genderless / pronoun-neutral language

### B.1 Canonical IAED guidance

IAED Journal *Case Entry Gender Selection* [S9] is the closest thing to an explicit pronoun-discipline policy in the EMD literature. Key points:

> "ProQA automatically assigns pronouns (she/her for assigned female; he/his for assigned male). However, dispatchers must manually override these if callers state different pronouns. The guidance acknowledges 'he/they,' 'she/they,' and 'he/she/they' combinations are possible." [S9]

> "If uncertain, use their name instead of 'sir' or 'ma'am.'" [S9]

> Asking for assigned-at-birth gender is only required for the six protocols where biological sex changes the protocol path: **Protocol 1, 12, 21, 24, 31, and Protocol C** (Airway/Arrest/Choking — Unconscious). [S9]

Medical / EMS gender-inclusive guidance (NOLS, EMS World, Alameda Health) converges on the same default: **singular "they" is the safe default when gender has not been stated** [S9, secondary].

For Protocol 9 (Cardiac Arrest), gender does not change the protocol path. There is therefore **no clinical reason** for the model to ask gender, and no clinical reason to assume "him" or "her."

### B.2 Canonical wording

- Default referent: **"they / them / the person / the patient"** until the caller establishes gender.
- If the caller uses a gendered referent first ("my husband", "she's not breathing", "him"): **mirror the caller's pronoun** — do not switch.
- If a gender-impacting protocol (1/12/21/24/31/C) is reached, ask explicitly: "What gender were they assigned at birth?" — this is the [S9] verbatim wording. Cardiac arrest (P9) is not on that list, so we never ask in the demo's primary path.

### B.3 WHAT WE'RE DOING WRONG

`orchestrator.py` line 361 hardcodes "Lay **him** flat." Caller said "friend." Other instances throughout 286–363 alternate "him/her" / "he/she" / "they" with no consistency. Specific offenders:

- Line 332: "Do not move **him** unless **he's** in danger." — caller stated "patient", no gender.
- Line 332: "Keep **him** still." — same.
- Line 361: "Lay **him** flat on **his** back." — same.

**FSC rewrite (canonical):**

```
State: caller_pronoun ∈ {none, he, she, they}
Initial: caller_pronoun = none
On caller utterance: parse pronouns/relationships, set caller_pronoun:
  - "my husband" / "my dad" / "him" / "he" → he
  - "my wife" / "my mom" / "her" / "she" → she
  - "my friend" / "the patient" / "this person" / "they" → they
  - else → none

Output rendering:
  - caller_pronoun == none OR they → use "they / them"
  - caller_pronoun == he → use "he / him"
  - caller_pronoun == she → use "she / her"

Hard rule: never emit "him" or "her" when caller_pronoun ∈ {none, they}.
This is a structural lint — not a soft prompt instruction — implemented as a regex post-filter on every assistant turn before it reaches TTS.
```

---

## C. Anti-repetition / verbal-tic discipline

### C.1 What the standards actually say

There is **no APCO, NENA, or IAED standard that explicitly prohibits "OK" or "stay with me" or counts repetitions**. The closest things in the canon:

- **IAED Verbal Tools** [S8] frames the principle as: *"Our words have to calm, control, and connect with our callers, and how we use them is every bit as important as how we use our radio or CAD."* The recommendation is intentional word choice, not anti-tic enumeration.
- **AHA T-CPR / Persuasive Communication** [S13]: an 8-hour training in *persuasive* (not formulaic) communication moved ROSC from 20.9% → 31.0%. Implication: variation and rapport matter; chant-loops do not.
- **Linguistics-of-emergency-calls literature** [S12, secondary]: dispatchers should give "interjections to let the caller know they are being listened to," and *"call-takers can provide space for indicating uptake including reformulation, repetition, acknowledgement receipts and displays of affiliation."* Repetition of *content* (mirroring caller statements to confirm) is endorsed; repetition of *filler tokens* is not — the literature treats those as evidence of cognitive overload, not as protocol.

So the binding rule for the demo is **a synthesis, not a citation**: the literature supports varied, intentional acknowledgement; it does not endorse "OK" / "stay with me" as a recurring filler. For an EMD-literate viewer, repeating either across consecutive turns reads as a chatbot stalling.

### C.2 Canonical FSC discipline (synthesized)

| Token | Allowed | Limit | Replacement when limit hit |
|---|---|---|---|
| "OK." | yes, as standalone acknowledgement | **once per call**, only after the first piece of substantive caller info | "Got it." → "Understood." → drop entirely after that |
| "Stay with me." | yes, as engagement check | **once per 60 s** of call time | "Tell me what's changing." / "What are you seeing now?" / "Is anything different?" |
| "Help is on the way." | yes, after address confirmed | **exactly once per call** (already in our orchestrator as flag [B]) | "Responders are close." / "We're getting help to you fast." — each used once max |
| "Take a breath." | yes, when caller is hyperventilating | **once per call** | "Slow breath in — talk to me" |
| "Uh-huh." / "Mm-hm." | no | banned | mirror the caller's word instead ("Friend, OK." → caller said friend, dispatcher confirms with that word) |

Mirroring the caller's *content word* (their relationship-of-victim term, their location landmark, their stated symptom) is the only repetition pattern actively endorsed by [S12] and [S8]. That is what variation looks like in EMD: not synonyms-of-OK, but substitution of caller-anchored content for filler.

### C.3 WHAT WE'RE DOING WRONG

`orchestrator.py` does not currently constrain "OK" or "stay with me" usage at all. Lines 313, 349, 356 all contain "Stay on the line with me" / "Stay with me" / "Stay on the line with me" — three distinct lexical variants of the same instruction that the model is free to issue every turn.

The grader penalizes "help is on the way" repetition (lines 364–374) but says nothing about "stay with me" or "OK" repetition. The live failure shows that gap is being exploited by the model.

**FSC rewrite (canonical):**

```
Per-call counters:
  ok_count:int = 0          # cap 1
  stay_count:int = 0        # cap 1 per 60 s wall-clock
  help_count:int = 0        # cap 1 (existing flag [B])
  reassure_alt:int = 0      # cap 1 each: {"Responders are close.", "We're getting help to you fast."}

Pre-TTS lint pass on every assistant turn:
  - If turn STARTS with "OK" / "Okay" and ok_count >= 1 → strip the leading token.
  - If turn contains "stay with me" / "stay on the line" and stay_count >= 1 within last 60 s → replace with one of: {"Tell me what's changing.", "What are you seeing?", "Anything different right now?"} chosen by mod-3 on turn index.
  - Hard ban tokens "uh-huh", "mm-hm", "right right" — strip.
```

---

## D. Address-first opening line

### D.1 The two real conventions

There is no single APCO/NENA standard sentence; what exists are **two regional conventions**, both compliant:

1. **"Address-first" (West Coast / IAED-trained PSAPs):**
   *"9-1-1, what is the address of your emergency?"* — favored by MPDS Case Entry because address is the first of the four Case Entry datapoints (address, callback number, problem, party-vs-party). NENA STA-020.1 [S15] endorses an address-first opening as it minimizes time-to-dispatch when the caller drops the line. **Strongly recommended for cell calls** because Phase 2 location is approximate — verbal address confirmation is the only ground truth.

2. **"Location-and-emergency" (East Coast / older APCO training):**
   *"9-1-1, what is your location and emergency?"* or *"9-1-1, where is your emergency?"* — combines location with an invitation to describe the incident. APCO Public Safety Communications Incident Handling Process [S14] does not mandate a specific opening; both forms are conformant.

### D.2 Regional / system variation

- Most California PSAPs: address-first.
- NYC, Chicago, much of the Northeast: location-and-emergency.
- VoIP / wireless calls: address-first is becoming the de facto standard because Phase 2 ALI is unreliable [S15].
- IAED-accredited centers running ProQA: ProQA opens with the four-line Case Entry sequence which begins with "Where is your emergency?" or "What is the address of your emergency?" [S6, secondary].

### D.3 What MWintro.mp3 says

User's MWintro.mp3 reportedly opens with *"What is the address of your emergency?"* — that is the IAED Case Entry verbatim and the AHA / MPDS-aligned form. It is the **stronger choice for an EMD-knowledgeable viewer**.

### D.4 WHAT WE'RE DOING WRONG

`orchestrator.py` line 291: *"Nine one one, what is your location and emergency?"* — APCO-conformant but not MPDS-conformant, and it is **inconsistent with the pre-roll voice asset (MWintro.mp3)**. A viewer hearing the recorded opening and then hearing the agent's first turn drift into "location and emergency" framing will register the mismatch.

**FSC rewrite (canonical):**

```
First-turn verbatim: "Nine one one, what is the address of your emergency?"
If pre-roll played: "Go ahead — address first."
```

This aligns with IAED / MPDS Case Entry order (address → callback → problem) [S6] and matches the pre-roll asset.

---

## E. Reassurance frequency — "Help is on the way"

### E.1 Canonical guidance

Two findings:

1. **AHA / IAED do not specify a frequency** for the "help is on the way" reassurance. They specify *content* (calm, control, connect — [S8]) and *timing relative to dispatch* (the reassurance follows the address-acquired-and-verified milestone — [S11]).

2. **Persuasive-communication literature** [S13] frames reassurance as a *one-shot pivot*: deliver once after dispatch, then move to information gathering. Lin et al.'s training script (paraphrased in [S8]): *"The paramedics are being dispatched as we're speaking. In the meantime, I need to get some information for them in order for them to better assess the situation before they get there. Do you understand?"* — single delivery, then immediate pivot.

The "do not repeat 'help is on the way'" rule the orchestrator already encodes (flag [B] latch, lines 296–303) is therefore correct in principle. It is consistent with [S13] and the IAED verbal-tools position.

### E.2 What to do on subsequent turns

When the caller asks *"how long?"* / *"when are they getting here?"* / *"is he going to be okay?"*, the canonical move is **answer the question, do not re-reassure**. Lin et al. [S13]: redirect to action, not reassurance — *"Help me help them. What are you seeing right now?"*

Allowed variants (each used at most once):
- "Responders are close."
- "We're getting help to you fast."
- "They are on their way — stay with me."

After all three are spent: drop reassurance entirely and substitute action-redirect ("What is changing?" / "What are you seeing now?").

### E.3 WHAT WE'RE DOING WRONG

`orchestrator.py` correctly latches flag [B] but does not cap the *alternative* reassurance variants on lines 349, 351–353, 356–357 — "we're getting help to you fast" / "responders are close" can each be issued unboundedly. The model is exploiting that.

**FSC rewrite (canonical):**

```
Per-call counters:
  reassure_primary:int = 0        # "Help is on the way." cap 1
  reassure_alt_close:int = 0       # "Responders are close." cap 1
  reassure_alt_fast:int = 0        # "We're getting help to you fast." cap 1
  reassure_alt_way:int = 0         # "They are on their way." cap 1

When all four exhausted → no further reassurance allowed.
Replacement: action-redirect ("What is changing?" / "What are you seeing?").
```

---

## F. Other pre-arrival short-form scripts

### F.1 Choking — adult, conscious

MPDS Protocol 11 verification and PAI launch [S6, secondary]:

- Q1 verification: *"Is she completely alert?"* (caller will say yes if patient is responsive but cannot speak — that is the choking sign).
- Q2 verification: *"Is she breathing normally?"* — for choking the answer will be no.
- Pre-arrival: **5 back blows between the shoulder blades, then 5 abdominal thrusts, alternating**, until obstruction clears or patient becomes unresponsive [S12]. If unresponsive, jump to Protocol B (Airway/Arrest/Choking — Unconscious) which is hands-only CPR.

Canonical short-form (≤12 words per turn):

```
T1: "Stand behind them. Five hard blows between the shoulder blades."
T2: caller continues choking → "Now five thrusts under the ribs, inward and up."
T3: alternate until clears or patient drops → "If they go limp, lay them flat — call back."
```

### F.2 Severe bleeding / hemorrhage

IAED Stop-the-Bleed (Protocol T) [S16] + StatPearls [S12]:

> "Hemorrhage control: direct pressure, elevating a bleeding extremity, possibly tourniquet application." [S12]
> "Securing the strap/cloth and then tightening it as hard as possible against the limb..." [S16]

Canonical short-form:

```
T1: "Press hard on the wound with a clean cloth. Don't lift to peek."
T2: still bleeding through cloth → "Add more cloth on top. Keep pressing."
T3: arterial bleed / spurting → "If you have a belt, tie it above the wound, tight."
```

### F.3 Seizure (active)

MPDS Protocol 12 + StatPearls [S12]:

> "Pre-arrival instructions for seizures include: do not place anything in the patient's mouth and move objects away from the patient. The patient should be rested on their left side with right knee forward in recovery position..." [S12]

Canonical short-form:

```
T1: "Move anything sharp away from them. Don't hold them down."
T2: "Don't put anything in their mouth. Time how long it lasts."
T3 (after seizure stops): "Roll them on their side. Watch their breathing."
```

### F.4 Structure fire

FPDS PDI-b [S17]:

> "If it's safe to do so, leave the building, close the doors behind you, and remain outside." [S17]

Canonical short-form:

```
T1 (caller in building): "Get out now. Close doors behind you. Don't go back."
T2 (caller outside, others inside): "Don't go back in. Tell me how many are inside."
T3: "Stay on the line. Where are they last known to be?"
```

### F.5 WHAT WE'RE DOING WRONG

`orchestrator.py` lines 339–344 give one-line versions for choking, bleeding, seizure that are mostly correct but:

- **Choking:** Line 340 — "Stand behind them, five back blows between the shoulder blades." is fine alone. Missing: the followup turn (5 abdominal thrusts) and the unresponsive transition. The FSC needs T2/T3 follow-on logic.
- **Bleeding:** Line 342 — "Apply firm direct pressure on the wound with a clean cloth. Do not lift to check." is canonical. No tourniquet upgrade path. Add T2/T3.
- **Seizure:** Line 343–344 — "Clear the area around them. Do not hold them down. Do not put anything in their mouth." is **three instructions in one turn**, violating the 5–12-word ONE-SENTENCE rule on line 367. Split into T1 / T2.
- **Structure fire:** Not currently in the orchestrator as a complaint-typed PAI. Add F.4 as a new branch.

---

## Summary of FSC additions (consolidated)

```
1. Cardiac arrest verification:
   - Keep Q1 (responsive?) gate even when Q2 is keyword-bypassed by caller.
   - Split positioning + compression-launch into two turns.
   - Time budget: < 90 s recognition, < 150 s first compression.

2. Pronoun lint (post-filter regex on every assistant turn):
   - State: caller_pronoun ∈ {none, he, she, they}; default they.
   - Hard ban "him"/"her" when caller_pronoun ∈ {none, they}.

3. Anti-repetition lint (per-call counters, pre-TTS strip):
   - "OK." / "Okay." cap 1
   - "stay with me" / "stay on the line" cap 1 per 60 s
   - "uh-huh" / "mm-hm" hard ban
   - Reassurance-variant counters: 4 distinct alternatives, each cap 1; after exhaustion, action-redirect only.

4. Opening verbatim:
   - "Nine one one, what is the address of your emergency?" (matches MWintro.mp3, IAED Case Entry).

5. Per-complaint PAI follow-on logic:
   - Choking: T1 back blows → T2 thrusts → T3 unresponsive transition.
   - Bleeding: T1 pressure → T2 add cloth → T3 tourniquet upgrade.
   - Seizure: split into T1 (clear/don't hold) → T2 (don't put in mouth/time it) → T3 (roll on side).
   - Fire: add T1 (get out, close doors, don't go back) → T2 (others inside?) → T3 (last known location).
```

All five categories should land as deterministic Python guards in front of the LLM call (a `pre_tts_lint(turn, state)` function) rather than as additional system-prompt language. The cycle-2Q live failures show that the model will not reliably honor anti-repetition / pronoun discipline as soft prompt instructions; the FSC must enforce them structurally.

---

## Closing — confidence and gaps

- A, B, C, D, E, F.2, F.3, F.4: well-supported by [S1, S4, S5, S6, S9, S12, S13, S15, S16, S17].
- F.1 (choking ratios): verified against [S12]; exact MPDS Protocol 11 PAI text not extracted from a primary source — the back-blows-then-thrusts ratio (5+5) is universally agreed across AHA, Red Cross, MPDS.
- AHA 2025 BLS guidelines [S3] returned 403 on direct fetch; updates from 2020 are minor on the T-CPR side per the 2020 → 2025 Part 1 executive summary (consulted via TOC). If the demo claims "AHA 2025 alignment" we should re-fetch [S3] before publishing.
- NENA STA-020 [S15] — PDF parse failed via WebFetch; cited based on the public summary page and the 911TipsGuidelines page on nena.org. Direct quote-level NENA citations would require manual PDF download.

For a hackathon demo whose viewer is "an EMD-literate person watching this for 60 seconds," the FSC rewrites in §A.5 / §B.3 / §C.3 / §D.4 / §E.3 / §F.5 are the highest-leverage changes. A, B, and C are the three the live test caught; D unifies with the audio asset; E and F are pre-emptive on the same failure class.
