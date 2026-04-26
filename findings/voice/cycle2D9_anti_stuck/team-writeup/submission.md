# Prism42 — Hackathon Submission

## 100-200 word summary (PRIMARY)

Speak into the microphone at https://prism42-app.thegoatnote.com/prism42/livekit and you reach a 911 voice dispatcher that returns under 1.5 seconds end-to-end and walks an MPDS-9 protocol turn: address verification, complaint-specific reassurance, key questions, T-CPR pre-arrival instructions. The architecture splits roles. A deterministic finite-state machine owns dialogue control and every safety-critical template (CPR compressions, repositioning, breathing-verify) — those ship verbatim. Claude Opus 4.7 owns natural phrasing inside the FSM's intent envelope, with adaptive thinking on a `display=omitted` path so latency stays voice-grade, and a parallel Opus 4.7 critic scoring intent-agreement against a 100-fixture eval. Naive LLM-as-dispatcher drifts, repeats, and hallucinates reassurance; Prism42 supervises with an LLM and dispatches with an FSM. Every life-safety code path is signed off by a practicing emergency physician, with templates traced to NHTSA EMD, AHA T-CPR, and NHS Pathways. 71 of 71 regression tests pass. Self-hosted full-stack on Brev B300 Blackwell Ultra: livekit-agents 1.5.6, Cartesia Sonic-3, Deepgram Nova-3, Opus 4.7. MIT licensed.

Word count: 154 words

## Backup paragraphs

### Why Opus 4.7

Opus 4.7's instruction-literalness is what made the FSM-LLM split actually work. Earlier models would "improve" safety templates; 4.7 leaves them alone. Adaptive thinking with `display=omitted` gave us a reasoning budget without a latency penalty — sub-1.5s p95 over a Cartesia round-trip. The parallel critic call uses 4.7 against itself for cheap intent-agreement scoring.

### Why physician sign-off

Voice agents in life-safety contexts fail in a category demos don't catch: confidently wrong reassurance, skipped cardiac short-circuit, pronoun confusion between caller and patient. Brandon Dent, MD reviewed every code path that touches a clinical decision. The CLAUDE.md §10 rule is literal: no life-safety merge without physician sign-off. Demo polish is downstream of that.

### Why the FSM-LLM split

A naive LLM dispatcher drifts off protocol, repeats itself, and improvises reassurance that buys time the patient doesn't have. An FSM-only dispatcher sounds like a 1990s IVR. The split — FSM owns intent, safety templates, anti-repetition, and pronoun discipline; Opus 4.7 owns phrasing within that envelope — is the thing that made the system both safe and natural-sounding.

## Demo video plan (3 minutes max)

- 0:00–0:15 — Open at https://prism42-app.thegoatnote.com/prism42/livekit. One sentence on the URL: "Public 911 PSAP voice dispatcher, mic in your browser, MIT licensed."
- 0:15–0:35 — Mic on. Open with a routine intake: "There's been a car accident at 1400 Page Mill Road." Show the dispatcher echo the address, get the verification, advance state. Camera on the live transcript and the latched FSM facts panel so judges see the state machine actually latching.
- 0:35–1:10 — Pivot the call into a cardiac scenario: "My friend just collapsed, he's not breathing." Hit the cardiac short-circuit. The dispatcher should drop into T-CPR pre-arrival instructions verbatim — point to those templates as the FSM-owned, never-rephrased path. Show timing under 1.5s.
- 1:10–1:40 — Show the dispatch panel UI: role-labeled turns, the perception sub-panel running the shadow Nemotron classifier alongside Opus 4.7. Brief callout that the LLM proposes phrasing, the FSM dispatches.
- 1:40–2:15 — Cut to the repo: 71/71 regression tests, the FSM module, one safety template file, and the CLAUDE.md §10 physician sign-off rule. Ten seconds on the test suite running green.
- 2:15–2:45 — One slide: stack diagram. Brev B300 Blackwell Ultra, livekit-agents, Cartesia Sonic-3, Deepgram Nova-3, Opus 4.7 with adaptive thinking, parallel Opus 4.7 critic. Cite the published protocol sources (NHTSA EMD, AHA T-CPR, NHS Pathways).
- 2:45–3:00 — Close on identity: practicing emergency physician founder, Build From What You Know. URL on screen.

## Form-field answers (from cerebralvalley.ai submission page)

### Project Name
```
Prism42
```

### Selected Hackathon Problem Statement
```
1. Build From What You Know
```

Rationale: Brandon Dent, MD is a practicing emergency physician.
The MPDS-9 verification discipline encoded in the FSM (surface →
breathing → compressions, never skip a gate) is a workflow he has
used clinically for years. Voice AI in 911 dispatch is exactly the
"thing only you'd know to build" framing the prompt asks for.
(A defensible secondary fit is "Build For What's Next" — voice
agents in life-safety contexts don't yet exist as a category — but
"Build From What You Know" is the stronger lead for the impact
criterion.)

### Project Description (paste from "100-200 word summary" above)

### Public GitHub Repository
```
https://github.com/GOATnote-Inc/prism42
```

### Demo Video
```
[YouTube/Loom URL — record per the 3-minute demo plan above]
```

### Thoughts and feedback on building with Opus 4.7

```
Opus 4.7's instruction-literalness was the unlock. Earlier models
"improved" our safety templates without being asked — they would
soften "Push hard and fast on the center of the chest, twice per
second" into something gentler and lose the cadence cue. 4.7 leaves
the templates alone, which is exactly what a deterministic safety
gate needs.

Adaptive thinking with display=omitted gave us a reasoning budget
without a user-visible latency penalty. End-to-end voice
turn-around stayed under 1.5s p95.

The behavior change worth noting: 4.7 spawns fewer subagents and
uses more direct phrasing than 4.6. For a dispatcher voice path
that wants short, ungilded utterances, that's a feature, not a
regression.

The new tokenizer ran 1.0-1.35× tokens vs 4.6 on our prompts —
budget that into any latency math. We re-measured rather than
backfilling.

One ask: a `style: terse` mode would obviate half the prompting we
do to keep voice replies in the 5-14 word band.
```

### Did you use Claude Managed Agents? If so, how?

```
Yes — during the build, not in the runtime demo path.

Build phase: We used Claude subagents extensively for parallel
research dispatches (5-team OODA on the LiveKit/B300 cutover,
3-agent disclosure-compliance audit before the public-repo flip,
2-agent dispatch-protocol research that informed the FSM template
wording, multi-agent voice perceptual-SOTA work). Subagents shine
for parallelizing slow paths that would otherwise serialize a
solo session.

Runtime path: The live voice dispatcher does NOT use Managed
Agents — we use direct messages.create against Opus 4.7 with
adaptive thinking, plus an off-path Opus 4.7 critic for
intent-agreement scoring on a 100-fixture eval. Managed Agents'
session-durability story is a great fit for longer-horizon work
(our auditor harness uses it elsewhere) but for a sub-1.5s voice
turn the direct API is the right shape.

Tested the multi-agent (callable_agents) path: silently stripped
on our workspace as of 2026-04-22, even with the
managed-agents-2026-04-01 beta header. We have the request_id for
support if needed (req_011CaJg9qBnVqPNkaoBLgjrN).
```

## Submission checklist

- [ ] 3-minute demo video (record per plan above)
- [x] Public GitHub repo: https://github.com/GOATnote-Inc/prism42
- [x] Written summary (PRIMARY above; 154 words)
- [x] Form-field answers (above)
- [ ] Submitted by April 26 8:00 PM EST (deadline)
