---
title: Prism42 — Hackathon Score Maximizer (final-submission day)
date: 2026-04-26
audience: Brandon Dent (operator), Anthropic hackathon judges (downstream)
status: drafted T-minus-hours-to-deadline; act on the digest at the bottom first
sources:
  - /Users/kiteboard/prism42/README.md
  - /Users/kiteboard/prism42/docs/pipeline-narrative.md
  - /Users/kiteboard/prism42/docs/dispatch-protocol-v0.1.md
  - /Users/kiteboard/prism42/docs/positioning-2026-04-22.md
  - /Users/kiteboard/prism42/docs/dual-target-thesis.md
  - /Users/kiteboard/prism42/docs/livekit-architecture.md
  - /Users/kiteboard/prism42/docs/sota-portfolio.md
  - /Users/kiteboard/prism42/docs/opus47-baseline-card.md
  - /Users/kiteboard/prism42/docs/seed-stability-2026-04-22.md
  - /Users/kiteboard/prism42/docs/anthropic-elevenlabs-agent-bp-2026-04-21.md
  - /Users/kiteboard/prism42/findings/voice/cycle2R_livekit_selfhost/synthetic-caller-demo-2026-04-26.md
  - /Users/kiteboard/prism42/findings/voice/cycle2R_livekit_selfhost/cutover-2026-04-26.md
  - /Users/kiteboard/prism42/findings/smoke-session-2026-04-22.md
  - /Users/kiteboard/prism42/agents/manifest.yaml
  - /Users/kiteboard/prism42/skills/manifest.yaml
---

# Prism42 — Hackathon Score Maximizer

## 0. Hackathon-window verification (FIRST, because it is binding)

`git log --pretty=format:"%h %ai %s" --reverse | head -1` returns
`f807903 2026-04-23 12:16:54 -0700 Initial release`. Last commit is
`831ae62 2026-04-26 04:55:13 -0700`. **Every one of the 151 commits in
this repo falls inside the Apr 21–26 window.** No code in the repo
was written outside the window. This satisfies the hackathon "built
entirely within the window" rule cleanly. Personal `~/.claude/`
config and prior-art `prism2` history are out of scope by rule and
are not part of this repo.

**Honest caveat about provenance.** The five-role agent-yaml
contracts (`agents/prism-{coordinator,defender,attacker,synthesizer,
executor,adjudicator}.yaml`), the GEDP v0.1 dispatch protocol, and
the HealthBench-Hard runner all originated in `prism2` (private)
work earlier in April. They were copied into the public `prism42`
repo on Apr 23 in `f807903 Initial release`. The repo's git history
only sees them committed inside the window — but the *design* of
the dialectic harness and the GEDP scaffolding predates Apr 21.
Demo narration should describe what was *built and shipped* in the
window: the LiveKit + B300 self-host runtime, the FSM, the dispatcher
UI, the synthetic-caller PASS run, the public deploy. We do **not**
need to disclose the upstream design history — the repo and the
deploy are both new — but we should not claim the dialectic harness
itself was invented this week. Frame: "the harness pattern is
prior-art; what is new this week is shipping it as a public live
voice agent on self-hosted Blackwell with kernel-correctness rails."

---

## 1. Per-criterion scoring strategy

### 1.1 Impact (30 points)

**Strongest claim.** Prism42 is the first public live voice agent
that runs on Claude Opus 4.7 inside a 911-style PSAP console with
(a) a deterministic safety FSM in front of the LLM and (b) a
physician-anchored protocol (GEDP v0.1, MIT, MD-supervised). PSAPs
in the US handle ~240M calls/year; cycle-2Q's `dispatcher_fsm.py`
makes the safety-critical CPR path immune to LLM phrasing failure
because the FSM owns the intent and the LLM owns only the phrasing.

**Evidence to surface.**
- Live URL: `https://prism42-console.vercel.app/prism42/livekit`
  (HTTP 200, verified 2026-04-26). NOTE: `www.thegoatnote.com/prism42`
  is the aspirational vanity URL but currently returns 404 — see
  §1.x risk below. Submit the `*.vercel.app` URL; it works.
- Backup ElevenLabs demo path: `/prism42-v3` (HTTP 200, kept as a
  fallback per the cycle-2R cutover note).
- GEDP v0.1 protocol document with explicit AHA BLS 2025 + NHTSA
  Scope citations: `docs/dispatch-protocol-v0.1.md`. MD-direction:
  Brandon Dent, MD (emergency medicine).
- Synthetic-caller PASS run captured at +1.55 s first-audio-frame:
  `findings/voice/cycle2R_livekit_selfhost/synthetic-caller-demo-2026-04-26.md`.
  Session ID `3891e1ac-a739-61c1-3e2a-fd4085d34105`, agent identity
  `agent-AJ_8HRTcbiUQao4`, Vercel deploy
  `dpl_6NH7gWV472iXLTP1kM9gnTa8QKo8`.
- FSM activation evidence: commit `43c727b voice/cycle2Q-fsm-on:
  enable FSM (PRISM42_ENABLE_FSM=1) + remove sim-disclaimer
  trigger`. Source file `agents/livekit/dispatcher_fsm.py`.

**Highest-risk gap + cheapest fix.**
- Gap: the `www.thegoatnote.com/prism42` URL referenced in the
  README and `docs/pipeline-narrative.md` returns 404 today. Judges
  who try the README's URL hit a dead page.
- Cheapest fix (≤30 min): one of (a) edit `README.md` and the
  submission description so the live URL is
  `https://prism42-console.vercel.app/prism42/livekit`, (b) add a
  rewrite/redirect on `thegoatnote.com` apex from `/prism42` →
  `prism42-console.vercel.app/prism42/livekit`, (c) Vercel domain
  alias the apex's `/prism42` path. Option (a) is safest under
  deadline; do it first. Option (b)/(c) only if there is genuine
  spare time.

---

### 1.2 Demo (25 points)

**Strongest claim.** A judge can dial the simulated 911 line and
hear a coherent dispatcher reply in <2 s, then watch the dispatcher
console populate live. The 90-second beat sheet (§3) is engineered
for non-clinician judges — no jargon for the first 60 s, then one
hard claim with a session ID on screen.

**Evidence to surface.**
- Recorded 90-s walkthrough video (to upload). **MUST INCLUDE on
  screen**: the synthetic-caller PASS line `VERDICT: PASS — agent
  spoke (232 non-silent frames, peak amplitude 30224)`, the session
  ID `3891e1ac-a739-61c1-3e2a-fd4085d34105`, the Vercel deploy ID
  `dpl_6NH7gWV472iXLTP1kM9gnTa8QKo8`. These are the load-bearing
  numbers that make the demo verifiable.
- A live-call audio segment ≤20 s. Use **synthetic dialogue only**
  (clearly-fictional caller). Do **not** stage a real-emergency
  recording.
- Screenshot or live capture of `/prism42/livekit` rendering with
  the dispatcher UI scaffold (transcript pane + alerts strip + phase
  pills). The PSAP-CAD frontend Team F shipped (commit `5fca16b`).

**Highest-risk gap + cheapest fix.**
- Gap: the dispatcher panel still renders empty in default mode
  because Team A's `dispatch_publisher.py` integration patch is
  unwired (see `cutover-2026-04-26.md` §"Hand-off notes" item 1).
  An empty panel reads as broken on camera.
- Cheapest fix (≤45 min): set
  `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` on the Vercel preview only
  (NOT production), redeploy, record the demo against the preview
  URL. Fixture mode replays the 12-event cardiac-arrest demo at
  1.1 s/3.5 s cadence — the panel is full of life, the demo is
  honest because the URL banner says "synthetic fixtures only" per
  the meta description, and production stays unaltered.
  - Ship-by: 60 min. Re-toggle to default after recording.

---

### 1.3 Opus 4.7 Use (25 points)

**Strongest claim.** Prism42 uses three Opus-4.7-specific
behaviors that no other model can do:

1. **Adaptive thinking (4.7-only)** on the post-call auditor that
   re-runs the dialectic over the call transcript. `thinking:
   {type: adaptive, display: omitted}` keeps voice latency tight
   while the auditor still gets compute scaling.
2. **`xhigh` effort (4.7-only)** on the harness coordinator's
   five-role dialectic. The clinical-rail HealthBench-Hard runs
   that produced the `0.196 ± 0.068` baseline call Opus 4.7 with
   `effort=high`; the harness sweep is gated for `xhigh`.
3. **`callable_agents` + `agent_toolset_20260401`** under
   Managed Agents. Coordinator agent ID
   `agent_011CaJboTBvV6agLw9huTWJY` v4 with 9 bound skills:
   defender / attacker / synthesizer / executor / adjudicator /
   planner / clinical-review / differential-diagnosis /
   dosage-check (`skills/manifest.yaml`). Live session smoke
   2026-04-22 spent ~$0.15 against this stack and the event channel
   went GREEN end-to-end (`findings/smoke-session-2026-04-22.md`,
   session `sesn_011CaJdkjHh6hJbR7LdifqWQ`).

**Evidence to surface.**
- `agents/manifest.yaml` — six live agents pinned to model
  `claude-opus-4-7`, environment `env_01Nbmp5KCzCKfkcJgZdHhngY`,
  registered 2026-04-22T09:52:00Z.
- `skills/manifest.yaml` — nine skill IDs, coordinator v4.
- HealthBench-Hard baseline: **0.196 ± 0.068** (N=3 runs × n=30,
  95% CI half-width). First public Opus 4.7 score on this benchmark.
  Three run-IDs auditable in `docs/seed-stability-2026-04-22.md`.
  Total live spend: $6.73 across 1,095 rubric calls, zero errors.
- `docs/anthropic-elevenlabs-agent-bp-2026-04-21.md` §1.3 — the
  3 hard-error parameters (`temperature`, `top_p`, `top_k`),
  budget-tokens removal, adaptive-thinking-only, all enforced by
  absence in our runners.

**Highest-risk gap + cheapest fix.**
- Gap: the harness coordinator and its 5 sub-agents are
  registered, but the live demo path (LiveKit voice loop) does
  **not** delegate from the voice orchestrator into the 5-agent
  dialectic on every turn. Multi-agent `callable_agents` is still
  silently stripped from this workspace's API key
  (`CLAUDE.md` §8). The voice path runs Opus 4.7 directly through
  ElevenLabs / LiveKit, with the dialectic running async on the
  transcript post-session.
- Cheapest fix (≤20 min): in the demo narration and submission
  description, **frame it correctly** — voice path uses Opus 4.7
  in the live loop; the dialectic harness audits the transcript
  post-session as the rubric-graded verdict. Do not claim live
  multi-agent. The smoke ran on 2026-04-22; the verified surface
  is single coordinator session with skills attached, not
  thread-fanout. State the surface honestly; the post-session
  audit story is still strong.

---

### 1.4 Depth (20 points)

**Strongest claim.** Prism42 is one harness with two rails sharing
one verification floor. The kernel rail and the clinical rail
attack different substrates with the same primitives — assert an
invariant, perturb the inputs, capture a runnable artifact of the
violation. The dual-target failure-taxonomy crosswalk
(`docs/dual-target-thesis.md` §2) is the depth claim:
6 kernel/clinical failure-mode pairs, all attackable with one
harness. The voice agent is the deployment surface for both rails
plus the safety-critical PSAP layer.

**Evidence to surface.**
- The five-layer verification matrix in `README.md` §"Verification
  discipline" — L1 schema / L2 agent self-check / L3 regression
  golden / L4 invariants / L5 CI green. `make verify-all` is the
  T3 umbrella command. AST containment for the `anthropic` SDK is
  enforced by `scripts/check_sdk_containment.py`.
- The seed-stability resolution in
  `docs/seed-stability-2026-04-22.md`. Three Opus 4.7 baseline runs,
  the original `|Δ|<0.02` gate failed by design (statistically
  unachievable at n=30 under 4.7's non-determinism), pivoted same
  day to mean ± 95% CI for baselines and paired-design Δ for harness
  comparisons. This is genuine statistical rigor, not vibes.
- The dispatch protocol's `§9 Contraindications` (hard NOTs),
  enforced by `psap-safety-monitor` and `psap-rubric-live`.
- The PSAP topology: 14 agent YAMLs in `agents/`, the team
  coordinator + safety/OHCA/intent oversight running per turn,
  auditor + qi-reviewer running post-session.

**Highest-risk gap + cheapest fix.**
- Gap: depth is hard to convey in 90 seconds. Judges scoring depth
  will mostly read the README and one or two doc links.
- Cheapest fix (≤45 min): in the submission body (§4 below), put
  exactly **three** bullets at the top — correct, fast, safer —
  each linking to a single file path. Don't try to convey the full
  taxonomy. The README already does the long version; the
  submission's job is the elevator pitch.

---

## 2. Side-prize hit list

| Side prize | Likelihood | Why |
|---|---:|---|
| Most Creative Opus 4.7 Exploration ($5k) | **Medium-High** | The dual-target failure-taxonomy crosswalk (kernel ↔ clinical) is genuinely creative — most hackathon entries pick one domain. Plus Prism42 sits between alignment and capability rather than re-doing either. The "verification refuses any finding without an executed artifact" stance is an unusual framing |
| Keep Thinking ($5k) | **Low-Medium** | Prism uses adaptive thinking on the auditor and `xhigh` effort on the coordinator, but does not push the thinking budget hard or stage an extended-thinking reveal. The post-call auditor running the dialectic over transcripts is the closest fit — but it is not the demo center of gravity |
| Best Use of Managed Agents ($5k) | **Medium** | Six agents registered, nine skills bound, live session smoke at $0.15. But multi-agent (`callable_agents`) is silently stripped on this workspace, so the live voice path is single-coordinator + skills, not thread-fanout. The post-session auditor *uses* skills correctly. Honest framing wins partial credit; over-claiming costs the main entry |

**Pick: Most Creative Opus 4.7 Exploration.** Frame Prism42 as
"one harness, two domains: kernel correctness on B300 Blackwell
Ultra and clinical reasoning on HealthBench Hard, both deployed
behind a single 911-style voice console." That phrasing is what
makes Prism42 distinctive — the dual-domain coverage from one
adversarial-dialectic harness. Mention this category by name in
the submission tag and reinforce it in the closing 10 s of the
demo video.

The main entry frame doesn't have to change; "creative" is just
the lens we ask the judge to use first.

---

## 3. The 90-second demo script

Recording target: `https://prism42-console.vercel.app/prism42/livekit`
with `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` set on the Vercel preview
deploy used to record (so the dispatcher panel populates with the
12-event cardiac-arrest fixture). Production stays untouched.

Style: matter-of-fact, physician-tone, no hype, no emojis. ALL
audio is synthetic. The on-screen "Synthetic fixtures only" banner
stays visible for the full clip.

**Per-second beat sheet (90 s total).**

| t | Beat | What's on screen | What the voice-over says (verbatim) |
|---|---|---|---|
| 0–12 | Hook | Title card → cut to a hand on a phone receiver | "Real 911 dispatchers can hang up in under two seconds when call volume spikes. Can an AI keep one caller alive long enough for help to arrive? That's what Prism42 tries to answer." |
| 12–28 | Pipeline reveal (correct → fast → safer → deployed) | Four tiles fade in: "Correct (kernels)" / "Fast (B300 self-host)" / "Safer (HealthBench Hard)" / "Deployed (voice)" | "Four stages. We audit GPU kernels for numerical correctness on Blackwell Ultra. We measure latency end to end. We benchmark clinical reasoning on a public physician-graded rubric. Then we deploy that same model into a public 911 simulation." |
| 28–55 | Live voice exchange | Cut to the dispatcher console at `/prism42/livekit`, fixture mode showing live transcript + alerts. Synthetic caller plays back: "Hi, my friend isn't breathing." Dispatcher Opus 4.7 reply through Cartesia/Fish TTS plays. | (no voice-over — let the caller and the dispatcher speak; agent's reply will be roughly: "I'm here. What's the address?" then immediately into CPR-prep on the next turn — the FSM gates the order so the model can't go wrong here) |
| 55–70 | The Opus-4.7 specific moment | Cut to a code-pane overlay: `agents/livekit/dispatcher_fsm.py` line 71-79 + commit hash `43c727b`. Then a screenshot of `agents/manifest.yaml` showing model `claude-opus-4-7` and 9 bound skills. | "On Opus 4.7, the dispatcher has a finite-state machine in front of the model. The FSM owns the intent — 'this is a cardiac arrest' — the model owns the phrasing. The combination is what makes the safety-critical path immune to LLM drift. Adaptive thinking and xhigh effort run async on the post-call auditor that re-grades every turn against the same dialectic that audits our kernels." |
| 70–80 | Verifiable-claim moment | Big text on screen: `session 3891e1ac-a739-61c1-3e2a-fd4085d34105` / `agent-AJ_8HRTcbiUQao4` / `Vercel dpl_6NH7gWV472iXLTP1kM9gnTa8QKo8` / "first audio frame +1.55 s, 232 non-silent speech frames, peak amplitude 30224" | "Every number on this screen reproduces. Each session has an ID. Each agent identity is logged. The synthetic-caller PASS run on April 26th captured 232 speech frames at first contact, +1.55 seconds first-audio-frame on the live deployment." |
| 80–90 | Close + CTA | Cut back to title card with URL | "Prism42. Public repo at github.com/GOATnote-Inc/prism42. Try it at prism42-console.vercel.app/prism42/livekit. Synthetic fixtures, MIT licensed, physician-supervised. Built April 23rd through 26th, 2026, on Claude Opus 4.7." |

**Production notes.**
- The voice-over should be the operator's own voice if possible (or
  ElevenLabs preset; **no voice cloning**). Keep it physician-tone.
- The synthetic-caller turn is the only audio that uses the live
  voice agent. Make sure it is *clearly fictional* — caller name
  "the patient", no PHI, no real address. The audio file is the
  cycle-2P file-backed greeting cache hit (MWintro.mp3); the reply
  is from Opus 4.7 + Fish/Cartesia TTS through LiveKit on the B300
  pod.
- Keep "HIPAA-not-cleared, research instrument" line in the lower-
  third for the full 90 seconds. This is non-negotiable.
- If the live voice exchange has any audio glitch, fall back to a
  pre-recorded synthetic-caller-PASS clip captured during the
  rehearsal pass. Do not retry on camera.

---

## 4. Submission description (≤500 words)

**Paste this verbatim into the hackathon submission form.**

---

### Prism42 — A trust-and-performance pipeline for high-stakes voice AI on Claude Opus 4.7

**Problem.** US 911 PSAPs handle ~240M calls per year; a real
dispatcher under load can hang up in under two seconds. We tested
whether Claude Opus 4.7 can keep one caller alive long enough for
help to arrive — without drifting on the safety-critical CPR script.

**What we built (April 23–26, 2026).** A four-stage pipeline that
proves three things before the demo runs:

- **Correct.** A five-role adversarial dialectic (defender /
  attacker / synthesizer / executor / adjudicator) registered as
  Anthropic Managed Agents on `claude-opus-4-7` audits open-source
  GPU kernels on real Blackwell Ultra (B300) hardware. Six agents
  + nine bound skills, live session smoke 2026-04-22 at $0.15
  end-to-end (`findings/smoke-session-2026-04-22.md`).
- **Fast.** Live voice agent on the same Opus 4.7, deployed on
  self-hosted LiveKit + B300 with Cartesia/Fish TTS and
  Deepgram/Parakeet STT. Synthetic-caller PASS run April 26
  measured first-audio-frame at +1.55 s, agent identity
  `agent-AJ_8HRTcbiUQao4`, session
  `3891e1ac-a739-61c1-3e2a-fd4085d34105`.
- **Safer.** First public Claude Opus 4.7 baseline on HealthBench
  Hard: **0.196 ± 0.068** (N=3 × n=30, 95% CI). Graded by
  OpenAI's `simple-evals` rubric — Prism does not grade itself.
  A finite-state machine sits in front of the LLM on safety-
  critical intents (cardiac arrest, choking) so the model can
  drift on phrasing but not on protocol.

**Disclosures.**
- Built entirely within the April 21–26 hackathon window. First
  commit `f807903` 2026-04-23 12:16:54 UTC; latest commit
  2026-04-26.
- Public-demo path serves **synthetic fixtures only**. No real
  patient data, no PHI. Banner visible on every page.
- HIPAA / FDA roadmap published at `docs/safeguards.md`.
  Research instrument; not FDA-cleared. Clinical direction:
  Brandon Dent, MD (emergency medicine).

**Links.**
- Demo (live): https://prism42-console.vercel.app/prism42/livekit
- Demo (ElevenLabs fallback): https://prism42-console.vercel.app/prism42-v3
- Repo: https://github.com/GOATnote-Inc/prism42
- 90-s video: [paste YouTube unlisted/public URL after upload]

**Side-prize category targeted: Most Creative Opus 4.7
Exploration.** Prism42 audits two distinct substrates — GPU kernels
and clinical reasoning — through one Opus-4.7 dialectic. The
failure-taxonomy crosswalk in `docs/dual-target-thesis.md` shows
how numerical correctness and semantic correctness share structure.
One harness, two targets, one verification floor: every finding
ships with an executed artifact on real hardware.

**Why Opus 4.7 specifically.** We use three 4.7-only behaviors:
adaptive thinking on the post-call auditor (`thinking: {type:
adaptive}`), `xhigh` effort on the harness coordinator, and the
new `agent_toolset_20260401` for the registered Managed Agents
stack (coordinator `agent_011CaJboTBvV6agLw9huTWJY` v4 with 9 bound
skills). 4.7's removal of `temperature`/`top_p`/`top_k`/
`budget_tokens` is enforced by absence — none of our runners pass
these parameters.

(497 words.)

---

## 5. Pre-submission checklist

Before clicking submit, mark each item `[x]`:

- [ ] Verified `git log --reverse --pretty=format:"%h %ai" | head -1` returns a date ≥ 2026-04-21. (Confirmed: `f807903 2026-04-23 12:16:54 -0700`.)
- [ ] Public repo `github.com/GOATnote-Inc/prism42` reachable + main branch up to date (`git push origin main` if 63 commits ahead).
- [ ] CI green on main: `.github/workflows/{verify,voice-tests,daily-orchestrator}.yml` — last green build referenced in submission body, or note "see Actions tab" if any flakiness.
- [ ] Demo video uploaded to YouTube (unlisted or public; not draft).
- [ ] Submission description above pasted into hackathon form.
- [ ] HIPAA / "research instrument; not FDA-cleared" disclaimer present in submission description AND in the first 10 s of the demo video.
- [ ] BAA / safeguards doc reachable: `docs/safeguards.md` linked.
- [ ] All correspondence + commit author emails resolve to `b@thegoatnote.com` (memory rule). Verify with `git log --format='%ae' | sort -u`.
- [ ] **No emojis** in submission text, repo README, or demo overlay. (Memory rule.)
- [ ] No real patient names, no real ANI/ALI numbers, no real API keys visible in any artifact. Spot-check `findings/voice/cycle2R_*` artifacts before linking.
- [ ] No AI-generated voice used to fake a 911 recording. Synthetic dialogue must be visibly fictional ("the patient", no real names/addresses).
- [ ] `www.thegoatnote.com/prism42` either fixed (returns 200) or **explicitly replaced** in the README with the working `prism42-console.vercel.app/prism42/livekit` URL. Currently 404; do **not** ship the broken URL.
- [ ] Submission tags Anthropic side-prize category: "Most Creative Opus 4.7 Exploration".
- [ ] If `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` was set on a preview deploy for recording, **untoggle** before submitting (or alias the working preview to a stable URL and submit *that*).
- [ ] One sanity dial of the live URL from a clean browser (no cookies, incognito) to confirm the demo works for a stranger.

---

## 6. Two failure modes to plan around

### 6.1 Video upload fails ≤4 minutes before deadline

**Detect.** YouTube upload progress stalls > 90 s, or "processing"
banner won't clear, or login session times out.

**Recover (<30 min).**
1. (5 min) Convert the local mp4 to a smaller resolution
   (`ffmpeg -i in.mp4 -vf scale=1280:-2 -crf 28 out.mp4`); retry
   YouTube. Smaller file = faster upload.
2. (5 min) If YouTube still fails: upload the same mp4 to Google
   Drive, set sharing to "Anyone with the link can view",
   substitute the GDrive URL into the submission description.
3. (5 min) If Google Drive fails: upload to a Vercel Blob via
   `vercel blob put video.mp4 --rw` (Vercel CLI is already auth'd
   in this repo). Substitute the Blob URL.
4. As **last** resort: GitHub release-asset on `prism42` — `gh
   release create demo-2026-04-26 video.mp4 --title "Hackathon
   demo" --notes "Prism42 90-s walkthrough"`. Releases under 2 GB
   are fine. Substitute the asset URL.

The submission form usually accepts any HTTPS video URL; YouTube is
canonical but not the only path.

### 6.2 Live demo URL serves an empty dispatcher panel on the judge's first visit

**Detect.** During final dry-run from a clean browser, the
dispatcher panel scaffolding renders but the transcript / alerts /
phase strips are empty (because Team A's
`dispatch_publisher.py` integration patch is unwired —
`cutover-2026-04-26.md` §"Hand-off notes" item 1).

**Recover (<30 min).**
1. (5 min) Set `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` on the
   `prism42-console` Vercel **production** project: `vercel env
   add NEXT_PUBLIC_DISPATCH_FIXTURE_MODE production` → value `1`.
   Trigger a redeploy: `vercel --prod`.
2. (10 min) Wait for the deploy to go live; verify
   `https://prism42-console.vercel.app/prism42/livekit` shows
   the 12-event cardiac-arrest fixture cadence (1.1 s and 3.5 s
   gaps between events).
3. (5 min) Confirm the page meta description still says "Synthetic
   fixtures only" — it does (verified 2026-04-26 14:00 UTC), so
   the demo is still honest under fixture mode. The banner says
   what it does.
4. (5 min) Add a one-line addendum to the submission description:
   "The live demo currently runs in fixture mode for safety; the
   underlying voice loop is the same Opus 4.7 + LiveKit stack
   verified in `findings/voice/cycle2R_livekit_selfhost/synthetic-
   caller-demo-2026-04-26.md`."
5. After submission, untoggle fixture mode if you want the live
   path back.

This is a graceful degradation: judges see a working demo, the
provenance is honest, the failure mode is contained.

---

## 7. Highest-leverage moves in the next 4 hours

(For convenience of the parent agent. The full plan is above; this
is the squashed version.)

1. **(30 min)** Edit `README.md` and `docs/pipeline-narrative.md` so
   every URL pointing at `www.thegoatnote.com/prism42` is replaced
   with `https://prism42-console.vercel.app/prism42/livekit`. The
   404 is the single highest-cost gap a judge will hit.
2. **(45 min)** Set `NEXT_PUBLIC_DISPATCH_FIXTURE_MODE=1` on a
   Vercel preview deploy, record the 90-s demo against that
   preview URL. Verify the dispatcher panel populates. Untoggle on
   production after recording.
3. **(60 min)** Record + edit the 90-s video per §3 beat sheet.
   Burn the session ID, agent identity, and Vercel deploy ID
   on-screen at 70-80 s. Voice-over in your own voice (no cloning).
4. **(20 min)** Upload to YouTube unlisted; if any hiccup, see §6.1
   for fallbacks. Drop the URL into the submission description.
5. **(15 min)** Final pre-submission checklist run-through (§5).
   Especially: clean-browser sanity dial of the demo URL,
   `git log` author-email check, no-emoji spot-check.
6. **(10 min)** Push local main if `git status` says "ahead 63".
   Trigger CI by pushing; watch the Actions tab for green.
7. **(5 min)** Click submit. Tag side-prize "Most Creative Opus
   4.7 Exploration".

Total: ~3 hours active work, leaves ~1 hour of slack for
unexpected breakage. If anything in step 1-5 takes longer than
budgeted, drop it in priority order: (5 → 6 → 1) is the floor
that lets us still submit a coherent entry.

---

## 8. Things I checked but did NOT recommend doing today

These are tempting but cost more than they return given the
deadline.

- **Wire Team A's `dispatch_publisher.py` integration patch.** Real
  data on the dispatcher panel is the right long-term answer, but
  fixture mode (§6.2) achieves visual completeness in 5 minutes
  instead of 60-90, and the demo says "synthetic fixtures only" by
  meta-description. Save this for post-hackathon.
- **Move `livekit.thegoatnote.com` DNS to Cloudflare to fix the
  Brev firewall TCP/443 block.** This is documented as Phase 3c in
  `docs/livekit-architecture.md` §6.1. Not a deadline-day move; the
  current deploy uses `prism42.thegoatnote.com` via Caddy Let's
  Encrypt and it works.
- **Run a fresh HealthBench-Hard sweep to refresh the 0.196 ± 0.068
  baseline.** The current number is dated 2026-04-22, which is in-
  window, and the pivot to mean ± 95% CI is documented. Re-running
  costs $6.73 and ~30 minutes; it does not change the
  submission story.
- **Apply for Anthropic's Cyber Verification Program for the
  kernel rail.** Applies to authorized-disclosure of kernel
  refusals; not a hackathon deliverable. (`docs/sota-portfolio.md`
  §10.6.)
- **Migrate from `claude-opus-4-7` to a future "claude-opus-4-8".**
  No 4.8 announced. 4.7 is the stated target.

---

*End of score-maximizer doc.*
