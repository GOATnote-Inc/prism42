---
title: Prism42 hackathon submission playbook
date: 2026-04-26
valid_through: 2026-04-29
hackathon: Anthropic "Built with Opus 4.7" — Apr 21-26 2026
rubric: Impact 30 / Demo 25 / Opus 4.7 Use 25 / Depth 20
side_prize_target: Most Creative Opus 4.7 Exploration ($5k)
audience: Brandon Dent, MD — submitting today
companion_docs:
  - demo-curation-2026-04-26.md
  - hipaa-baa-matrix-2026-04-26.md
  - score-maximizer-2026-04-26.md
---

# Submission playbook — read top to bottom, do not skip

Three parallel agent teams (Demo Curator, HIPAA/BAA Auditor, Hackathon Score Maximizer) ran today. Each wrote a full report into this folder. Every blocking claim below has been verified against the live repo or the live web before being promoted here.

---

## STOP — fix these four before recording or submitting

Each is reproducible at the command line. Each must be done.

### 1. The README's published URL is a 404

`README.md:45` and `README.md:49` send judges to `https://www.thegoatnote.com/prism42`.

```
verified: curl -L https://www.thegoatnote.com/prism42  ->  HTTP 404
verified: curl -L https://prism42-console.vercel.app/prism42         -> HTTP 200
verified: curl -L https://prism42-console.vercel.app/prism42/livekit -> HTTP 200
```

Fix in 3 minutes:

```bash
cd ~/prism42
sed -i '' 's#www.thegoatnote.com/prism42#prism42-console.vercel.app/prism42#g' README.md
git add README.md && git commit -m "docs: point published URL to the running deployment for hackathon submission"
```

Then verify with `grep -n thegoatnote.com/prism42 README.md` → should be empty.

### 2. 64 commits are sitting on local main; origin is behind

The judges look at GitHub, not your laptop. Push.

```bash
cd ~/prism42
git status -sb           # confirm clean tree
git push origin main     # publishes 64 commits including today's StopResponse fix
gh run list --limit 5    # confirm CI started; do not submit until green
```

If CI fails, fix or revert before submission. A red main is worse than no demo.

### 3. Do not claim "live multi-agent" in the voice loop

`scripts/register_agents.py` (worktree) explicitly strips `callable_agents` from the coordinator request because Managed Agents multi-agent is a research-preview feature that is not enabled on this workspace. `tests/test_smoke_scripts.py:17` confirms: `callable_agents` is NOT sent by the smoke_delegation script.

What this means: the voice loop runs a single Opus 4.7 agent today. The five-role kernel-correctness dialectic and the agent-team patterns are real in the kernel pipeline (`mla/`), but the voice path does not delegate live across multiple sub-agents.

In the demo and in the submission text, frame agent teams as the kernel-pipeline thing they are, not as something the voice path does at runtime. The Score Maximizer doc (§1.3 and §2) gives the exact wording.

### 4. Pick the right recording in <10 minutes

Open `~/Desktop` in Finder, sort by size descending. The Demo Curator's verdict, verified against the file inventory:

| File | Size | Duration | Verdict |
|---|---:|---:|---|
| Screen Recording 2026-04-25 at 7.07.11 PM.mov | 646 MB | 7:03 | **PRIMARY** — open first |
| Screen Recording 2026-04-25 at 6.53.59 PM.mov | 153 MB | 3:15 | fallback if §5 red flag in primary |
| Screen Recording 2026-04-25 at 6.49.37 PM.mov | 113 MB | 1:39 | fallback if both above fail |
| Screen Recording 2026-04-24 at 1.15.54 PM.mov | 110 GB | ~30 h | DO NOT OPEN — workspace capture, leaks context |
| Screen Recording 2026-04-25 at 7.14.25 PM.mov | 35 GB | 6.6 h | DO NOT OPEN — workspace capture |
| 4-second / 17-second / 25-second clips | various | ≤30 s | b-roll or discard |
| Screen Recording 2026-04-26 at 3.12 AM / 4.01 AM | 2.3 / 3.8 GB | 49 / 38 min | DO NOT OPEN — overnight working sessions |

Apply the 8-anchor scrubbing rubric in `demo-curation-2026-04-26.md` §2. Ship if the primary scores ≥6/8 and anchors A1 (clean intro), A2 (end-to-end caller dialogue), A3 (visible Opus 4.7 reasoning) all hit.

---

## HIPAA / BAA — the framing that lets this demo ship today

The hackathon judges are not lawyers. A hospital CTO who watches your demo IS one. Both audiences need the same thing: an honest "no, today — here is the path".

### Pinned 30-second disclaimer (use verbatim)

Place this in the first 10 seconds of the demo video AND at the top of the submission description AND on `prism42-console.vercel.app/prism42`:

> Prism42 is a capability demonstration. The voice exchanges shown use synthetic, clearly-fictional dialogue. No real PHI is processed. The production deployment path is HIPAA-tractable — see the BAA matrix and 90-day compliance roadmap at `docs/hackathon/hipaa-baa-matrix-2026-04-26.md`. This is not a clinical product, not FDA cleared, and not currently a Business Associate to any covered entity.

### Why Path A (B300 self-hosted) is the structurally stronger HIPAA story

When Phase 3b lands the LLM on the same B300 pod that hosts the agent, the reasoning step never leaves the customer-auditable boundary. Path B (ElevenLabs Conversational AI) bundles SaaS components that no third-party stack can replicate. Auditor §4 has the full argument.

### Day-Zero blocker for production

Brev / NVIDIA's BAA status is unverified. Before any PHI-bearing pilot:

```
2026-04-29   Email NVIDIA BAA team via the BAA matrix's verified URL.
             If "no BAA available", name a fallback compute host.
```

Every other production-stack vendor (Anthropic, LiveKit, Cartesia, Deepgram, Vercel Pro) has a documented BAA path. See `hipaa-baa-matrix-2026-04-26.md` §2 for the per-vendor table.

---

## The 90-second demo script

Full beat-by-beat script with timestamps lives in `score-maximizer-2026-04-26.md` §3. Skeleton:

```
00:00–00:12  Hook: "Real 911 dispatchers can hang up a confused caller in <2 seconds.
                   Can our AI keep one alive long enough for help to arrive?"
00:12–00:25  Disclaimer (the 30-second HIPAA statement above, abbreviated).
00:25–00:40  Trust pipeline: correct -> fast -> safer -> deployed.
                   On-screen: README's four-stage diagram.
00:40–01:30  Live voice exchange (PRIMARY recording's best 50 seconds).
                   On-screen overlay at 01:10–01:20:
                     - session ID 3891e1ac-a739-61c1-3e2a-fd4085d34105
                     - agent identity agent-AJ_8HRTcbiUQao4
                     - Vercel deploy dpl_6NH7gWV472iXLTP1kM9gnTa8QKo8
                   These three IDs reproduce the run. Burning them on screen
                   is what separates this from every other voice-AI hackathon entry.
01:30–01:40  One Opus-4.7-only moment (adaptive thinking budget OR FSM-gated
                   phrasing per cycle-2Q). Pick whichever is on the recording.
01:40–01:50  Close: link to repo + running URL + side-prize tag.
```

If the recording allows a 5-minute cut, use the §6 timing in the Demo Curator doc.

---

## Submission description (paste-ready)

The full 500-word submission text lives in `score-maximizer-2026-04-26.md` §4. Open that file, copy §4 verbatim into the hackathon submission form. Verify before submit:

- [ ] Problem stated in one sentence
- [ ] Three proven things (correct, fast, safer)
- [ ] Built within Apr 21–26 window — confirmed: first commit `f807903` is 2026-04-23
- [ ] HIPAA disclaimer present
- [ ] BAA matrix linked
- [ ] YouTube/video link
- [ ] Public repo: `github.com/GOATnote-Inc/prism42`
- [ ] Running URL: `prism42-console.vercel.app/prism42` (NOT `www.thegoatnote.com/prism42`)
- [ ] Side prize tagged: **Most Creative Opus 4.7 Exploration**
- [ ] Author email: `b@thegoatnote.com` (never a personal address)

---

## Final pre-flight checklist

Run before clicking submit:

- [ ] §1 fixed and pushed
- [ ] §2: `git push` done; `gh run list --limit 3` shows green for the latest commit
- [ ] §3: agent-teams claim is scoped to the kernel pipeline in narration and submission text
- [ ] §4: primary recording chosen, scored ≥6/8 on the rubric, no §5 red flag
- [ ] HIPAA disclaimer present in first 10 s of video AND in submission description
- [ ] BAA matrix doc linked from submission description
- [ ] Recording reviewed for: leaked secret, .env content, real PHI-shaped identifier, real-911-sounding audio, missing simulation disclaimer
- [ ] No emojis anywhere — video, repo README, submission text
- [ ] Demo URL clicks through and loads in <2 s in an incognito window
- [ ] If using `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` to populate the dispatcher panel, that's stated honestly somewhere ("synthetic fixtures only")

---

## Validity & follow-up

This playbook is the source of truth through **2026-04-29**. After submission:

- 2026-04-27 — wait for any judge feedback; do not break the running URL.
- 2026-04-28 — kick off the HIPAA 90-day roadmap (`hipaa-baa-matrix-2026-04-26.md` §5). Item 1: Brev/NVIDIA BAA status email.
- 2026-04-29 — write the post-submission lessons-learned and update this file (status: superseded by `docs/hackathon/POST-MORTEM-2026-04-29.md` if the submission landed).

If the submission slips to an extended deadline, this playbook does not change — the four blocking items above are blocking regardless of clock.

---

## Companion documents (read these for detail)

| File | What's in it | Length |
|---|---|---:|
| `demo-curation-2026-04-26.md` | 8-anchor scrubbing rubric, per-file go/no-go, stitching plan, 2-min and 5-min cutdowns, red-flag abort list | 13 KB |
| `hipaa-baa-matrix-2026-04-26.md` | 30-second disclaimer, per-vendor BAA table for both Path A and Path B, HIPAA Security Rule mapping, 90-day roadmap (start 2026-04-29, end 2026-07-28), CTO talk-track | 32 KB |
| `score-maximizer-2026-04-26.md` | Per-criterion strategy (Impact/Demo/Opus 4.7 Use/Depth), side-prize hit list, 90-second demo script with timestamps, 500-word submission description, pre-submission checklist, two failure modes | 28 KB |

---

## Single highest-leverage action right now

Push main. Without origin/main matching the local tree, judges click into a stale GitHub view of 64 commits behind. Everything else in this playbook is meaningless until that's fixed.

```bash
cd ~/prism42 && git push origin main && gh run list --limit 3
```
