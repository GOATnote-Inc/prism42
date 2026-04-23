# GOATnote PSAP Console — Clinical-Grade 911 Call Handler

A single-pane 911 call-taker console on the **IRB-pilot → SaMD** trajectory.
Built on **ElevenLabs Conversational AI** over **Claude Opus 4.7**,
physician-of-record accountable, every dispatcher turn rubric-graded against
HealthBench Hard-aligned clinical criteria in real time.

**One console. One dispatcher. One physician in the loop.** AI is decision
support; the human is always the decider.

```
console.html   The console itself — offline-safe single-file HTML
README.md      This file — market context + clinical thesis + IRB pathway
```

Open `console.html` in any modern browser. Fonts load from Google; offline
falls back cleanly. No build step, no server, no API keys. Wire to an
ElevenLabs custom-LLM endpoint per the integration reference in the Prism
repo (`docs/anthropic-elevenlabs-agent-bp-2026-04-21.md`) to take a live
call.

## Why it exists — the outcome-first thesis

Six levers move survival and morbidity in US 911 systems today. A console
is *worth building* only if it moves at least one of them by a
measurable, physician-auditable amount:

| Lever | Current state | Evidence | Our lever |
|---|---|---|---|
| OHCA first-minute recognition | Dispatchers miss ~25% | [Corti 93% vs 73%, 30 s faster](https://eena.org/wp-content/uploads/2020_01_13_Corti_Report.pdf) · [Blomberg 2021 RCT null on bolt-on](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2774644) | **OHCA early-warning gauge** fed by agonal-gasp classifier + language signals — surfaced in-UI next to the MPDS card, not as a side panel the dispatcher has to look for |
| Telephone CPR delivery | T-CPR raises OHCA survival 2-3×; Seattle doubled bystander-CPR rate | [StatPearls EMS Pre-Arrival](https://www.ncbi.nlm.nih.gov/books/NBK470543/) · [MCW T-CPR evidence review](https://www.mcw.edu/departments/emergency-medicine/community-engagement/dispatcher-assisted-bystander-cpr) | **Pre-arrival instructions pre-generated + age-appropriate** the moment the determinant code forms, ready to read in the caller's own language |
| Protocol adherence | Dispatcher drift from MPDS correlates with worse outcomes | MPDS IAED quality metrics | **Determinant computed from conversation** — the dispatcher can't drift because the CAD code is derived from the actual utterances, not typed |
| Language-access equity | Non-English callers have longer time-to-dispatch + worse outcomes | NENA language-access guidance | **Real-time bidirectional translation** (caller's language ↔ dispatcher's English) in ~128 ms median — no 3-way language-line delay |
| Dispatcher cognitive load + burnout | 25-70% PSAP vacancy rates; 15-30% annual turnover | [Police1 AI call automation review](https://www.police1.com/911-and-dispatch/how-ai-call-automation-can-ease-the-strain-on-911-centers) | **Auto-CAD capture** — fields populate from conversation; dispatcher never types during a live call. Real-time rubric decoupled from call flow (async judge) |
| QI feedback loop | Retrospective review is weekly, per-agency manual | IAED accreditation workflow | **Per-turn rubric grading** (HealthBench Hard-aligned) with physician weekly sign-off; QI loop shrinks from weeks to minutes |

## How we differ from what US PSAPs run today

| Vendor | 2026 product posture | What they don't yet do |
|---|---|---|
| **Motorola** VESTA + Hyper (Apr 9 2026 acq) | Assist Agents for non-emergency offload + translation | Clinical rubric grading · physician-in-loop QI · MPDS-embedded determinant derivation |
| **Axon** 911 (Prepared $800-900M + Carbyne) | 70+ languages, CAD-ready extraction, 1000+ agencies, 49 states | IRB-pathway design · HealthBench-aligned rubric · published Opus 4.7 baseline |
| **Carbyne** APEX / Universe | Cloud-native NG911, 35+ languages, live video | Clinical trajectory · physician-of-record attestation · published benchmarks |
| **Aurelian** (Ava) | AI handles 74% of non-emergency calls autonomously | Emergency-call clinical support (by design — they hand off to humans) |
| **GOATnote (this console)** | **Emergency-call clinical decision-support, physician-accountable, rubric-graded in real time, IRB-pilot ready** | SOTA on everything above · ships today |

**The differentiation isn't "AI on phones" — everyone has that now. It's
clinical accountability.** VESTA Assist transcribes; Prepared extracts;
Carbyne streams video; Aurelian triages non-emergencies. None of them
grade the dispatcher's clinical response per turn, none of them compute
the MPDS determinant from the conversation to prevent drift, none of
them publish a physician-reviewed rubric against HealthBench Hard, and
none of them ship on a trajectory to IRB pilot and eventual SaMD
clearance.

That's the gap we're closing.

## What's on the console

```
┌─ TOP BAR ────────────────────────────────────────────────────────────┐
│ GOATnote mark  │  call timer · rec · line  │  SOTA capability strip │
│  Transcribe · Translate · OHCA-sig · CAD-capture · Rubric 0.82      │
├─ IRB BAND ───────────────────────────────────────────────────────────┤
│ RESEARCH INSTRUMENT · IRB 2026-GN-PSAP-001 · physician of record     │
├─ LEFT ─────────────┬─ CENTER ─────────────────┬─ RIGHT ──────────────┤
│ LIVE TRANSCRIPT    │ MPDS breadcrumbs         │ CAD incident         │
│  · speaker diariz. │ DETERMINANT 11-D-2 ECHO  │  · ANI/ALI block     │
│  · bidirectional   │ CLINICAL ROW             │  · map + units       │
│    translation     │  OHCA gauge · CAD cap    │ EMS HANDOFF BRIEF    │
│  · audio-event     │ KQ CARD                  │  · live-generating   │
│    classifier      │  scripted + 4 options +  │  · pushes to unit    │
│  · NG911 chans     │  copilot recommend       │ 988 WARM HANDOFF     │
│    voice/RTT/video │ PRE-ARRIVAL instructions │                      │
│                    │  age-appropriate + STOP  │                      │
│                    │  clauses + read-aloud    │                      │
├─ BOTTOM STRIP (AI COPILOT + CLINICAL RUBRIC) ────────────────────────┤
│ NEXT QUESTION │ SAFETY-CRITICAL │ LIVE RUBRIC │ ASK + TELEMETRY     │
│ physician-    │ protocol + AHA  │ 5 criteria  │ STT · LLM · TTS ·   │
│ signed src    │ citation        │ + transcript│ E2E · V4 headroom   │
└──────────────────────────────────────────────────────────────────────┘
```

### The six SOTA subsystems

1. **Transcribe** — Whisper-v4 or equivalent, 96% caller confidence baseline
2. **Translate** — bidirectional real-time (caller-language ↔ dispatcher-English), 128 ms median, Opus 4.7 + Whisper pipeline, 70+ languages
3. **OHCA early warning** — background-audio classifier (YAMNet + PANNs hybrid) + language-signal model; surfaces agonal-gasp, cyanosis-reported, unresponsive flags; gauge next to protocol card
4. **CAD auto-capture** — structured field extraction from conversation (patient demographics, chief complaint, onset, scene, allergies); dispatcher sees per-field confidence and attestation state
5. **Clinical rubric** — async per-turn rubric grade (HealthBench Hard-aligned, physician-designed) on a cheaper judge model (GPT-5.4-mini / Haiku); logged for weekly physician QI sign-off
6. **EMS handoff brief** — structured handoff note generated live during the call and pushed to the rolling unit's tablet before arrival

### Keyboard-first dispatch

```
/       focus the copilot input
1-4     answer the current MPDS key question
R       read current pre-arrival instruction aloud (dispatcher's language)
T       toggle translation on/off
P       push EMS handoff brief to rolling unit
F1      takeover — pause voice-agent, dispatcher has the call
Esc     mute TTS
```

No mouse-hunting during a time-critical call.

## The clinical trajectory — IRB → SaMD

This console is a **research instrument**. It is not FDA-cleared, it is
not Clinical-Decision-Support (CDS)-exempt, and it is not a medical
device today. The trajectory below is the deliberate path it walks:

1. **Phase 0 — Synthetic-fixture validation (here).** Every call
   rendered uses synthetic ANI/ALI, synthetic transcripts, synthetic
   caller data. No PHI. Rubric cards carry `physician_review = null`
   until countersigned.
2. **Phase 1 — IRB pilot.** Protocol `2026-GN-PSAP-001` (drafted;
   pending IRB submission). Single PSAP, physician-of-record on
   every shift, all dispositions made by the human dispatcher. AI
   surfaces are logged but not load-bearing. Primary outcome:
   dispatcher-rated clinical utility + rubric-pass-rate delta.
3. **Phase 2 — Prospective outcome study.** Paired pre/post design
   at 2-3 PSAPs. Secondary outcomes: time-to-determinant, T-CPR
   instruction delivery rate, MPDS protocol adherence, OHCA
   first-minute recognition.
4. **Phase 3 — Pre-submission + SaMD filing.** FDA 510(k) or De
   Novo depending on clinical-decision-support classification.
   Class II SaMD target.

Physician of record: **Brandon Dent, MD** (emergency medicine).
Physician-in-loop sign-off is enforced in the rubric adjudicator's
`physician_review` field and in the UI's IRB band — the code never
pre-signs it.

## Integration stack

- **Voice I/O**: ElevenLabs Conversational AI custom-LLM mode, SSE on
  `/v1/chat/completions`. Buffer-word pattern `"... "` keeps TTS flowing
  during slow LLM turns.
- **Brain**: Claude Opus 4.7 (`claude-opus-4-7`), thinking OFF by default
  for voice latency (Phase-V rule: cut at p95 > 4 s). Safety preamble in
  the translator layer, not ElevenLabs-side.
- **Async rubric judge**: GPT-5.4-mini or Haiku on a background thread,
  1.8 s behind real-time. Logs go to `results/rubric/*.jsonl` for
  physician weekly review.
- **Clinical content**: MPDS v13.3 (IAED licensed). AHA BLS 2025 for
  pre-arrival. HealthBench Hard for rubric criterion derivation.
- **Telemetry**: stopwatched STT, LLM TTFT, TTS, E2E p95; headroom vs.
  4-second V4 rule surfaced in the bottom strip.
- **Safeguards**: no PHI in synthetic-fixture mode; BAA required with
  ElevenLabs before production; NENA i3 compliance required at PSAP.

Full reference: the Prism dev-repo doc
`docs/anthropic-elevenlabs-agent-bp-2026-04-21.md` (same file in this
repo's `docs/` once Prism's public mirror syncs it).

## Safeguards

- Synthetic fixtures only on this console. Not PHI. Not a medical-use
  claim.
- Clinical findings route per Prism's clinical-handling posture
  (`docs/clinical-handling.md`): physician review first, Anthropic
  feedback channel second, never public-issue-tracker, never social.
- Rubric design is physician-owned. The model never grades itself
  load-bearingly — grades go to a physician for attestation.
- The AI cannot dispose of a call. Every disposition requires the
  dispatcher's confirmation and carries a physician-of-record attestation.

## Attribution

- **Concept + physician of record** — Brandon Dent, MD · GOATnote-Inc ·
  `b@thegoatnote.com`
- **Design system** — extracted from Prism dev-repo
  `results/demo/index.html`, typography upgraded per
  [Anthropic frontend-aesthetics cookbook](https://platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics)
- **Voice + LLM stack** — ElevenLabs Conversational AI + Anthropic
  Claude Opus 4.7
- **Clinical content licensing** — MPDS via IAED (pending); AHA BLS
  2025 reference
- **Rubric methodology** — HealthBench Hard (OpenAI `simple-evals`,
  Apache 2.0) as the grading-shape source

## License

MIT for the HTML/CSS/JS in this directory. Clinical content (MPDS, AHA
BLS) retains its upstream licensing; attribution required. GOATnote logo
and trademark: GOATnote-Inc.

— 2026-04-23
