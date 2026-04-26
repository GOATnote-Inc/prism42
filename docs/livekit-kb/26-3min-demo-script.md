# 3-minute demo video — shooting script

> Submission for **Built with Opus 4.7 hackathon**. Deadline 2026-04-26 20:00 EST.
> Subject: prism42 911 PSAP voice agent. 14-agent topology, B300 self-hosted
> voice stack (LiveKit + Parakeet STT + Fish S2 TTS), Opus 4.7 orchestrator.
>
> Glasswing-aligned: `19-glasswing-aligned-submission.md` framed a 90s cut;
> this expands to the hackathon's 3:00 spec. Same narrative spine, more
> breathing room for the architecture and the meta-story.

## Format

- Total runtime: 2:55–3:00 (under cap; judges hate over-cap)
- Aspect: 16:9 (YouTube). 1920×1080, H.264, ≤30fps, audio -16 LUFS
- Voiceover: scripted, recorded separately, normalized to -16 LUFS
- On-screen text: IBM Plex Sans Condensed (matches console UI)
- Lower-third color: `#ff4b4b` (the console's `--live` token)

## Three-act structure

| Act | Time | Theme | Visual |
|---|---|---|---|
| I — The call | 0:00 – 1:00 | A real chest-pain dispatch, audio-first | console + live transcript |
| II — The harness | 1:00 – 2:10 | 14-agent topology, B300 pipeline, why Opus 4.7 | architecture diagram + B300 metrics |
| III — Glasswing | 2:10 – 2:55 | Solo MD + Claude Code → critical-infrastructure software | commit log + scribe archive + tag |

## Shot list (00:00 frame-by-frame)

### Act I — The call (0:00 – 1:00)

**00:00 – 00:08 · cold open, no logo**
- Screen: black
- Audio: phone-ring tone (1 ring), then a cut — silence for 0.4s
- Then caller voice (use `synthetic_caller_full.py` script line 1, or record a friend reading: *"My husband — he just collapsed in the kitchen, he's not breathing right"*)
- Voiceover: **(none)**. The call carries the open.

**00:08 – 00:30 · dispatcher response, console live**
- Visual: cut to `localhost:3042/prism42` (the live ElevenLabs console) full-screen
- The agent's first audio plays through. Captions on.
- Visible UI: the *PhaseTimeline* pill flips `intake → triage`. The *Transcript* component shows the running turn. The *RubricStrip* shows green dots populating as `/api/rubric/grade` returns.
- Voiceover (over agent audio, -12 dB ducked):
  > *"This is prism42 — a 911 dispatcher built on Claude Opus 4.7. The caller is talking to a 14-agent team. You're seeing the dispatcher view a real PSAP would see."*

**00:30 – 00:48 · the catch (the moment that earns the demo)**
- Visual: pop a *safety alert* bubble from `AlertsPanel.tsx` — `SP-001 trigger phrase intercepted` or an oversight catch the dispatcher would miss. Hold the alert on screen 3s.
- Voiceover:
  > *"At 0:42 the oversight specialist catches a triage error a single-model setup would miss. Sonnet handles supervision. Opus 4.7 runs the call. The dispatcher is human."*

**00:48 – 01:00 · sub-second floor**
- Visual: corner overlay, monospace, the `/prism42-b300/compare` numbers from the Phase 2-min A/B (e.g. *"first audio: 4824ms → 487ms"*). If the live number isn't ≤500ms today, **show the actual number with a frame: floor of an honest run, not a marketing number** — see `docs/livekit-kb/19-glasswing-aligned-submission.md` "Demo failure modes & mitigations".
- Voiceover:
  > *"First audio in under half a second. Self-hosted on a single B300 — Parakeet STT, Fish Speech S2, Opus 4.7. No third-party voice. No PHI leaves the pod."*

### Act II — The harness (1:00 – 2:10)

**01:00 – 01:25 · architecture sweep**
- Visual: animated overlay of the architecture from `mvp/911-console-live/README.md` (the ASCII block converted to motion). Highlight in sequence: caller → LiveKit → Parakeet → Opus 4.7 coordinator → 14 specialists → Fish Speech → caller. Each node lights as the data path traverses.
- Voiceover:
  > *"One coordinator, 14 specialists. Intake. Triage. Dispatch. Pre-arrival instructions. Handoff. Each phase is a sprint contract — explicit success criteria the orchestrator checks before transitioning."*

**01:25 – 01:45 · sprint contract on screen**
- Visual: cut to `agents/livekit/contracts/intake.yaml` — render the YAML with syntax highlight. Animate a pointer hitting `success_criteria` and `escalation_triggers`. Cross-fade to `dispatch.yaml`.
- Voiceover:
  > *"This is the intake contract. The model can't say 'done' — it has to satisfy four criteria the orchestrator audits, including verbatim-readback of the address. If a single criterion fails, the phase doesn't transition."*

**01:45 – 02:10 · the GPU**
- Visual: a Nsight or `nvidia-smi` capture from the B300 pod under load. If the actual GPU number is still 3% (we're TTFB-bound), show the **honest** number with the diagnostic chart from `findings/b300_bench/` — that itself is a Mythos-class profiling shot. Per `19-glasswing-aligned-submission.md`: *"Honest Nsight slide showing where the time actually goes — that itself is a Mythos-class profiling demo."*
- Voiceover:
  > *"This runs on a single NVIDIA B300. The bottleneck isn't compute — it's the speech model's autoregressive token loop. We profiled every millisecond and shipped the lever-registry that closes the gap. Fourteen optimization levers, every one with a measured delta."*

### Act III — Glasswing (2:10 – 2:55)

**02:10 – 02:30 · the meta-story**
- Visual: `git log --oneline --since="5 days ago"` from prism42, scrolling. Names of the 8 subagents flash from `.claude/agents/`. A counter ticks: *"X commits. Y subagent tasks. Z iterations."*
- Voiceover:
  > *"I'm an emergency physician. I'm the only developer on this. In five days, Claude Code wrote, profiled, and hardened this entire stack — across an 8-agent harness with explicit sprint contracts and a generator-evaluator loop on every output."*

**02:30 – 02:48 · the Glasswing line**
- Visual: split-screen. Left: the Anthropic Glasswing announcement page (clipped). Right: prism42's `findings/` directory listing.
- Voiceover:
  > *"Anthropic announced Project Glasswing on Friday — securing critical infrastructure with AI. 911 dispatch is critical infrastructure. This is a working proof point on Saturday. Tomorrow, Mythos does this autonomously across every open-source dependency in the stack."*

**02:48 – 02:55 · slate**
- Visual: black slate, four lines, IBM Plex Mono, `#ff4b4b`:
  ```
  prism42
  Brandon Dent, MD · GOATnote Inc.
  github.com/GOATnote-Inc/prism42
  Built with Claude Opus 4.7
  ```
- Audio: silence. No music sting.

## What's recordable today vs. what needs staging

| Asset | State | Plan |
|---|---|---|
| `localhost:3042/prism42` console | Renders if `npm run dev` in `mvp/911-console-live/` with `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` set | Record screen capture at 1920×1080 |
| Live audio of caller + agent | LiveKit path: needs B300 pod up + worker dispatched. ElevenLabs path: needs ElevenLabs ConvAI session | If LiveKit is up: best demo. Fallback: synthetic-caller log + a friend reading `synthetic_caller_full.py` lines on a phone, with `/prism42` UI in the foreground showing the transcript |
| Sub-500ms first-audio number | `findings/b300_bench/` should hold most-recent run. If the floor is honest-but-not-pretty, show it honestly | Pull the freshest JSON, screencap the number |
| Architecture animation | None pre-rendered | Build in Keynote/Figma in 30 min from the README ASCII |
| Sprint contract on screen | YAML files exist as-is | VS Code with syntax highlight, screen-record |
| GPU/Nsight capture | Run `agents/livekit/bench_b300.py` on the pod, screencap nvidia-smi | If pod is unreachable, use the cached profiling charts in `findings/b300_bench/` |
| Commit log scroll | `git log --oneline --since="5 days ago"` runs | Terminal screencap with type-on |
| Subagent counter | `.claude/agents/` listing + `findings/glasswing/conversations/` count | Terminal one-liner |
| Glasswing announcement clip | Public URL `anthropic.com/research/project-glasswing` | Browser screencap at 16:9, scroll-pan |
| Voiceover | Self-record on phone, Krisp or Audacity to clean | Read each Act's lines back-to-back, splice in editor |

## Recording checklist (T-12h to T-0)

- [ ] Confirm `mvp/911-console-live/` runs clean: `cd mvp/911-console-live && npm install && npm run typecheck && npm run dev`
- [ ] Open `http://localhost:3042/prism42` — verify console renders, SSE subscribes, no console errors
- [ ] Either: bring up B300 + LiveKit worker, OR fall back to ElevenLabs ConvAI on `/prism42`
- [ ] Record one clean 60s caller→agent run end-to-end (this is your Act I master)
- [ ] Capture `nvidia-smi` + Nsight (or read latest `findings/b300_bench/*.json` and chart it honestly)
- [ ] Pull `git log --oneline --since="2026-04-21"` — that's your commit-stream B-roll
- [ ] Render architecture animation from `mvp/911-console-live/README.md` ASCII block
- [ ] Record voiceover top-to-bottom in one sitting (consistency); do two takes
- [ ] Edit in [tool of choice — see "Meta option" below]
- [ ] Master at -16 LUFS; export 1080p H.264; under 200 MB
- [ ] Upload to YouTube unlisted; copy link for the submission form

## Meta option — splice with prism (the music-video tool)

You shipped `music-video/` in the same repo. Eating your own dog food on the
demo edit is on-brand and lifts the submission narrative.

1. Pick a copyright-free, sub-3:00 instrumental — energy curve that builds on
   the Act II → III seam. Suggested vibe: ambient → percussive build → release.
2. Drop your raw clips into `music-video/examples/clips/`:
   - `01_call_open.mp4` (the cold open)
   - `02_console_running.mp4` (the dispatcher console live)
   - `03_safety_catch.mp4` (the SP-001 alert pop)
   - `04_arch_animation.mp4` (the topology sweep)
   - `05_yaml_contract.mp4` (intake.yaml on screen)
   - `06_nsight.mp4` (the GPU profile)
   - `07_commit_scroll.mp4` (the git log)
   - `08_glasswing_split.mp4` (the announcement split-screen)
   - `09_slate.mp4` (the closing slate)
3. Run:
   ```bash
   cd music-video
   prism cut --song ./examples/song.mp3 --clips ./examples/clips --aspect 16:9 --out ./demo-out
   ```
4. Use `demo-out/song__16x9__director.json` as the editor's notes — Claude
   tells you which clip lands on which beat. Trust the cuts you like; override
   the ones you don't (it's a draft, not a final).
5. Layer your scripted voiceover on top in any NLE (Resolve, Premiere, Final
   Cut). The cuts are already beat-locked.
6. Export. Submit. The submission writeup gets a line: *"Edited with prism, the
   Opus-4.7 music-video editor we shipped in the same repo."*

This makes the submission **two artifacts in one** — the 911 voice agent and
the music-video editor — both Built with Opus 4.7, both in `prism42`. Glasswing
framing reads as: one solo developer + Claude Code = full-stack output across
two unrelated domains in a hackathon week.

## Voiceover script (reading copy, ~370 words, ~2:30 at 150 wpm)

> *(0:00 — silence, then phone ring, then caller audio: "My husband — he just collapsed in the kitchen, he's not breathing right.")*
>
> *(0:08)* This is prism42 — a 911 dispatcher built on Claude Opus 4.7. The caller is talking to a 14-agent team. You're seeing the dispatcher view a real PSAP would see.
>
> *(0:30)* At 0:42 the oversight specialist catches a triage error a single-model setup would miss. Sonnet handles supervision. Opus 4.7 runs the call. The dispatcher is human.
>
> *(0:48)* First audio in under half a second. Self-hosted on a single B300 — Parakeet STT, Fish Speech S2, Opus 4.7. No third-party voice. No PHI leaves the pod.
>
> *(1:00)* One coordinator, 14 specialists. Intake. Triage. Dispatch. Pre-arrival instructions. Handoff. Each phase is a sprint contract — explicit success criteria the orchestrator checks before transitioning.
>
> *(1:25)* This is the intake contract. The model can't say "done" — it has to satisfy four criteria the orchestrator audits, including verbatim-readback of the address. If a single criterion fails, the phase doesn't transition.
>
> *(1:45)* This runs on a single NVIDIA B300. The bottleneck isn't compute — it's the speech model's autoregressive token loop. We profiled every millisecond and shipped the lever-registry that closes the gap. Fourteen optimization levers, every one with a measured delta.
>
> *(2:10)* I'm an emergency physician. I'm the only developer on this. In five days, Claude Code wrote, profiled, and hardened this entire stack — across an 8-agent harness with explicit sprint contracts and a generator-evaluator loop on every output.
>
> *(2:30)* Anthropic announced Project Glasswing on Friday — securing critical infrastructure with AI. 911 dispatch is critical infrastructure. This is a working proof point on Saturday. Tomorrow, Mythos does this autonomously across every open-source dependency in the stack.
>
> *(2:48 — silence over the slate.)*

## Failure-floor cuts (if the live demo can't get clean audio)

Plan B (no live agent audio): swap Act I to a screen-recorded session with the
caller text on the left half, the *Transcript* component populating live on
the right half, no audio playback. Voiceover narrates: *"This is a real
session — the caller speaks here, the agent answers here. We're playing the
transcript, not the audio, because the dispatcher view is the artifact."*

Plan C (no live agent at all): cut Act I to the synthetic_caller log scrolling
with terminal-typing animation. The voiceover stays — emphasize the rubric
grades and the sprint-contract YAML in Act II. The architecture and the
Glasswing meta-story do the heavy lift.

A submission with Plan C still ships. A late submission does not.

## Submission form fields (Cerebral Valley × Anthropic)

- **Title:** prism42 — Claude Opus 4.7 dispatching 911
- **One-liner:** A 14-agent PSAP voice console on Claude Opus 4.7, self-hosted on a single NVIDIA B300. Built solo by an MD in five days with Claude Code.
- **Video URL:** *(paste YouTube unlisted link)*
- **Repo URL:** https://github.com/GOATnote-Inc/prism42
- **Writeup:** see `docs/submission/2026-04-26-hackathon.md` (next file)
- **Built with Opus 4.7?** Yes — Opus 4.7 is the orchestrator + voice-facing specialist; Sonnet 4.6 is the oversight rail.

## Notes for the editor (you, tomorrow morning)

- Cold-open audio over black always beats a logo card. The judges have seen
  every logo card.
- Keep the architecture animation under 25s. It's there to anchor, not teach.
- The sprint-contract YAML is the differentiator. Linger on it. Most demos
  show pretty UI; few show *the contract the model has to satisfy*.
- The Glasswing line in Act III is the submission's hook. Read it like you
  mean it; do three takes.
- Don't add music to Act I. Silence and the caller's voice carry it.
- The slate is the slate. No outro music. No "thanks for watching." Black,
  four lines, three seconds, end.
