---
title: Prism42 hackathon demo curation — viewing rubric
date: 2026-04-26
audience: Brandon (self) — pick the submission video in <10 min
context: Anthropic "Built with Opus 4.7" hackathon, Apr 21-26 2026. Judging Impact 30 / Demo 25 / Opus 4.7 Use 25 / Depth 20.
thesis: prove Prism42 is a "trust-and-performance pipeline for high-stakes voice AI" (README L3-L5). Show correctness + speed + clinical lift + the 911 deployment in one continuous take.
---

# How to use this file

Open Finder. Sort `~/Desktop/Screen Recording 2026-04-25 at *.mov` by size descending. Open the 7:03 file (646 MB) in QuickTime first. Use the rubric in §2 against it. If it scores >= 6/8 anchors with no red flags from §5, that is the submission. Otherwise drop down the §3 ranking.

Do NOT open the 110 GB or 35 GB files. They are workspace captures, not demos.

---

## 1. Viewing order

Primary: **Screen Recording 2026-04-25 at 7.07.11 PM.mov** (646 MB, 7:03, modified 19:14). Length is consistent with a full "intro -> live call -> trust pipeline -> outro" demo. Open this first, full-screen QuickTime, scrub at 2x.

Fallback ranking (open only if primary fails §5):

1. 7.07.11 PM (7:03) — full demo candidate
2. 6.53.59 PM (3:15) — mid-length, likely a single rail (B300 or ElevenLabs) shown end-to-end
3. 6.49.37 PM (1:39) — short demo, fits the 90-180 s hackathon target if it has a clean intro
4. 6.51.14 PM (40 s) — too short to satisfy Demo 25 alone, but b-roll candidate
5. 6.49.05 PM (25 s) — b-roll only
6. 6.53.39 PM (17 s), 6.53.14 PM (3 s), 6.49.35 PM (2 s) — discard

Discard outright (not demos): 1.15.54 PM.mov (110 GB, 30h workspace capture), 7.14.25 PM.mov (35 GB, 6.6h overnight), 3.12.05 AM.mov (49 min), 4.01.52 AM.mov (38 min). These are coding sessions, not pitch material.

---

## 2. Scrubbing checklist (run while watching)

For each candidate, score 1 point per anchor. Target >= 6/8 on the primary file before you commit to it.

Eight anchors, in priority order:

```
[ ] A1. Self-contained intro within first 15 s. No "let me restart", no
        visible terminal hunt for a file. The viewer learns "this is a
        911/PSAP voice agent on Opus 4.7" inside 15 s.

[ ] A2. End-to-end caller dialogue. Caller speaks (audible voice or
        on-screen transcript) -> agent responds in voice -> agent
        produces a dispatch action (determinant code, unit assignment,
        or a structured handoff). Stage 4 of the pipeline
        (pipeline-narrative.md L158-196). If only intake fires and
        nothing routes, this anchor is missed.

[ ] A3. Visible Opus 4.7 reasoning. ANY of: a thinking block, a
        tool/agent-call name in a side panel, an agent-team handoff
        (coordinator -> defender -> ...), or a session ID overlay.
        The judges score "Opus 4.7 Use 25" against this. Without a
        visible 4.7-specific surface, that quartile is forfeit.

[ ] A4. Safety rail visibly firing. The cycle-2Q FSM intercepts an
        unsafe phrasing, OR the safety preamble is visible in the
        translator, OR the OHCA-detector triggers, OR the
        intent-verifier blocks a deflection. (CLAUDE memory:
        cycle-2Q FSM blocks "my friend stopped breathing" -> CPR.)
        This anchors the "trust" half of the trust-and-performance
        thesis (README L3).

[ ] A5. Latency numbers on screen. p95 end-to-end < 1.5 s target
        (CLAUDE.md §0). TTFT, RTF, or a per-leg breakdown
        (STT / LLM TTFT / TTS / WebRTC RTT). Even one number anchors
        the "performance" half. Stage 2 of the pipeline
        (pipeline-narrative.md L86-118).

[ ] A6. Trust pipeline visible. ANY of: README four-stage diagram on
        screen, the pipeline-narrative ascii diagram (L27-46), a
        verdict.json view, the dispatcher console showing post-call
        rubric grading, or a make verify-all green screen.

[ ] A7. Audio quality clean. No crackle, no two restarts of the same
        sentence, no obvious mic-clip. If the video has reusable
        audio you can VO over, that's a bonus.

[ ] A8. Both paths shown OR one shown + one referenced. B300/LiveKit
        path AND ElevenLabs path. The README treats LiveKit as the
        new build, ElevenLabs as the fallback (CLAUDE.md §0). Even a
        2-second cut between two browser tabs satisfies this. If only
        one is shown and the other isn't even named, anchor missed.
```

Scoring guidance:
- 7 or 8/8: ship it.
- 6/8: ship if A1, A2, and A3 are all hit. (Self-contained intro + live call + visible 4.7.)
- 5/8 with A1+A2+A3: ship with stitched b-roll for the missing anchors (see §4).
- <5: drop to fallback file.

---

## 3. Per-file go/no-go classification

| File | Class | Why |
|---|---|---|
| 1.15.54 PM.mov (110 GB, ~30h) | discard | workspace capture, not a demo |
| 6.49.05 PM.mov (23 MB, 25 s) | b-roll | too short for primary; possible intro/outro insert |
| 6.49.35 PM.mov (0.7 MB, 2 s) | discard | false start |
| 6.49.37 PM.mov (113 MB, 1:39) | candidate | fits 90-180 s hackathon target if A1/A2/A3 hit |
| 6.51.14 PM.mov (81 MB, 40 s) | b-roll | possible single-anchor capture (one rail), insert clip |
| 6.53.14 PM.mov (2.7 MB, 3 s) | discard | false start |
| 6.53.39 PM.mov (10 MB, 17 s) | b-roll | possible single moment (e.g., FSM firing); insert clip |
| 6.53.59 PM.mov (153 MB, 3:15) | candidate | mid-length; likely one rail end-to-end |
| 7.07.11 PM.mov (646 MB, 7:03) | primary | length matches full pipeline-narrative demo |
| 7.14.25 PM.mov (35 GB, 6.6h) | discard | overnight session |
| 3.12.05 AM.mov (2.3 GB, 49 min) | discard | working session |
| 4.01.52 AM.mov (3.8 GB, 38 min) | discard | working session |

Rule: never submit anything in the discard column. Even slowed down 4x they reveal too much workspace context (env files, internal paths, scratch terminals).

---

## 4. Stitching plan

Assume primary 7.07.11 PM (7:03) is the master. Hackathon target is 90-180 s. You will cut it down.

Cut-point heuristics (mark these as you scrub):

- **0:00-0:15 — intro window.** If A1 missed (e.g., starts with terminal hunt), replace this segment with a static title card or with the cleanest 10 s from 6.49.37 PM (1:39) that names the project.
- **First slow stretch (likely 1:30-3:00).** If a configuration step or a "let me copy this URL" appears, hard-cut around it. Typical cut: skip 02:30-03:45 if it is re-explanation or a waiting-on-deploy moment.
- **Second slow stretch (likely 4:30-5:30).** If demo enters a Q&A-style aside or a tab switch, cut to the dispatcher console close-up directly.
- **Outro 6:30-7:03.** Likely already terse; keep the verdict/post-call screen at minimum.

Splice candidates from shorter files (b-roll):

- **A4 missing (no FSM rail visible)?** Splice 6.53.39 PM (17 s) over the audio of the live call. Caption: "FSM blocks unsafe phrasing — see CLAUDE memory cycle-2Q."
- **A5 missing (no latency number)?** Splice 6.51.14 PM (40 s) — even one chart frame is enough. Caption with the actual number, not a generic "fast."
- **A8 missing (only one rail)?** Use 6.49.05 PM (25 s) or 6.49.37 PM (1:39) to show the second rail's URL bar and a single voice turn.

Editing constraints:
- Cuts on silence, never mid-word.
- No music. The audio of the actual voice agent IS the demo.
- One title card max at the head; one verdict-card screenshot at the tail.
- Keep cursor tracking minimal — long mouse-hunt sequences read as "demo not ready."

---

## 5. Submission-day red flags (abort-and-re-record)

Hard stops. If any one of these appears in the candidate, do not submit it.

```
[ ] Visible API key in any terminal/editor/browser pane (Anthropic,
    OpenAI, Cartesia, Deepgram, LiveKit, Brev, Vercel, ElevenLabs).
    Includes partial keys, sk-... prefixes, ANTHROPIC_API_KEY=...
    in a .env file open in a text editor.
[ ] .env file contents on screen even briefly. CLAUDE memory hard rule:
    never read .env. Same for the demo.
[ ] HIPAA-shaped identifier that looks real. A fake name is fine
    ("John Doe, 54"). A real DOB + real address + real chief complaint
    that maps to a person is a stop. Synthetic by construction
    (pipeline-narrative.md L195: "Phase 0 synthetic-fixture
    validation; all PSAP demo fixtures are synthetic. No PHI, no real
    ANI/ALI, no patient data.").
[ ] Voice that sounds like a real 911 recording. The hackathon is
    fine with synthetic caller voices. A clip that sounds harvested
    from an actual 911 call is a publicity and licensing problem.
[ ] Real cell number, real address, real PSAP CAD ID, real ANI/ALI
    metadata anywhere on screen.
[ ] Any GOATnote private repo URL (prism2, stealth-tic). Public-only:
    prism42, lostbench, scribegoat2, openem-corpus, healthcraft,
    radslice, safeshift.
[ ] Any embargoed kernel finding. The repo is intentionally clean
    of this (kernel-research-posture.md), but verify the screen
    matches.
[ ] Disclaimer modal NOT visible at session start in the public-demo
    capture. pipeline-narrative.md L218 requires "simulation only;
    if real, call 9-1-1." every session.
[ ] "Research instrument. Not FDA cleared." footer NOT visible
    (pipeline-narrative.md L227).
[ ] Any frame showing a competitor's name or logo (Motorola, Axon,
    Carbyne, Aurelian, Prepared) used in a way that reads as
    benchmarking-against-them rather than positioning. The pitch is
    "different from incumbents" (pipeline-narrative.md L231-244),
    not "beats incumbents." Watch the framing.
```

If any flag fires: re-record the affected segment only. Use 6.49.37 PM (1:39) as the template for length/scope of the re-take.

---

## 6. Cutdown plans

### 2-minute cut (target 110-120 s)

Use this if Anthropic asks for the short form.

```
00:00-00:08  Title card. "Prism42 — trust-and-performance pipeline
             for high-stakes voice AI. Built on Claude Opus 4.7."
             (README L3-L5 verbatim.)
00:08-00:25  Stage 1+2 montage. README four-stage diagram on screen,
             VO names "find correctness failures, optimize compute
             path, prove clinical lift, deploy the agent stack."
             Pull from 7.07.11 PM at the diagram-reveal moment.
00:25-01:25  Live 911 call. Caller speaks -> agent triages -> agent
             dispatches. Anchor A2. From 7.07.11 PM. ~60 s of the
             cleanest contiguous call segment. Voice audio kept;
             no VO over caller turns.
01:25-01:45  Trust rail close-up. Either the FSM blocking unsafe
             phrasing (anchor A4) or the post-call verdict.json
             render (anchor A6). Caption shows latency number
             (anchor A5).
01:45-02:00  Outro. Public URL www.thegoatnote.com/prism42.
             "Continuity claim: the agents you talked to are the
             same ones audited in stages 1-3." (README L47-53.)
```

### 5-minute cut (target 280-300 s)

Use this if Anthropic allows the long form OR if the 7.07.11 PM file naturally lands at this length.

```
00:00-00:15  Title card + thesis. Same as 2-min.
00:15-00:50  Stage 1 — kernel correctness. Show MLA dialectic. The
             5-role pattern (defender / attacker / synthesizer /
             executor / adjudicator) named on screen. Cite
             "executed PoC on real GPU hardware."
00:50-01:25  Stage 2 — compute path. Show one latency chart. Name
             p95 < 1.5 s target (CLAUDE.md §0) and the actual
             measured number. Reference clean-process measurement
             rubric (README L27-31).
01:25-02:00  Stage 3 — clinical lift. Show HealthBench Hard baseline
             0.196 +/- 0.068 (README L34, pipeline-narrative.md
             L140-141). "First public Opus 4.7 HealthBench Hard
             number."
02:00-03:30  Stage 4 — deploy the agent stack. The 90-second live
             call. Show BOTH the LiveKit/B300 path AND the
             ElevenLabs path (anchor A8). At least 60 s of caller
             dialogue with audible turns.
03:30-04:15  Trust rail showcase. Safety rail firing (A4),
             post-call verdict (A6), session ID overlay (A3).
             "Every public call produces a structured verdict
             from the same dialectic that audits the kernels"
             (README L52-53).
04:15-05:00  Outro. Public URL. Continuity claim. Credits frame
             with "Built with Claude Opus 4.7" and the GOATnote
             physician-of-record line (pipeline-narrative.md L196).
```

If you only have time to ship one cut: ship the 2-minute. Anthropic's hackathon spec language is "make a video showing your project" — short, anchored, and clean beats long-and-drifty every time.

---

## 7. Decision tree (the 5-line summary)

```
1. Open 7.07.11 PM.mov in QuickTime, 2x scrub.
2. Run the §2 checklist. >=6/8 with A1+A2+A3 hit -> primary confirmed.
3. Run the §5 red-flag list. Any one fires -> re-record affected segment only.
4. Cut to 2-min plan in §6. Splice b-roll from §4 only if anchors A4/A5/A8 missed.
5. Export H.264, upload, submit.
```

If step 2 fails: drop to 6.53.59 PM (3:15) and re-run from step 2. If that fails too: 6.49.37 PM (1:39).

Time budget: 5 min scrub primary + 2 min red-flag pass + 3 min cutdown = 10 min to submission-ready.
