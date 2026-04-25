# Glasswing-aligned hackathon submission narrative

> Submission shape for **Built with Opus 4.7 hackathon** (Cerebral
> Valley + Anthropic, deadline 2026-04-26 5pm PT). Frames the prism42
> 911 PSAP voice agent as a Glasswing-playbook proof point: solo dev
> + Claude Code multi-agent harness shipping kernel-level + cyber work
> on critical infrastructure.

## One-paragraph pitch

> "I'm an MD. In 5 days, I shipped a Claude-driven 911 dispatcher on
> a self-hosted NVIDIA B300 — sub-second first-audio, GPU at 60-90%
> under load, 14-agent PSAP topology. While I was at it, my Claude
> Code multi-agent security harness audited the open-source
> dependencies and shipped a [PR | finding] upstream. Project
> Glasswing announced its mission Friday: secure critical
> infrastructure with AI. Here's a working proof point on Saturday.
> Tomorrow Mythos does this autonomously across every OSS project."

## Submission deliverables (in order judges will encounter them)

1. **90-second demo video**
   - Real chest-pain 911 scenario, end-to-end audio
   - Sub-2s first-audio (target ≤ 500ms TTFB)
   - On-screen 14-agent PSAP topology trace
   - One frame showing safety-monitor catching a triage error that
     Sonnet-only would miss → only Opus 4.7 reasoning catches it
   - One frame showing the cyber harness finding card

2. **GitHub repo**: `github.com/GOATnote-Inc/prism42` (already public)

3. **Submission writeup** (single markdown, ~1500 words)
   - The 911 stakes (caller dies if dispatch misroutes)
   - The B300 architecture (LiveKit + Fish + Parakeet + Claude + 14 agents)
   - The before/after benchmark (4824ms → ≤ 500ms; GPU 3% → 60-90%)
   - The Nsight timeline screenshot
   - The cyber harness diagram + the [PR | finding] card
   - The Claude Code conversation log links — actual transcripts
   - The "iteration count vs. capability-unlocked" chart

4. **Reproducibility**: full deployment recipe, every env var documented,
   `make verify-all` passes on a fresh B300 pod

## Glasswing-alignment trace

For each judge-relevant attribute, show how the submission embodies
Glasswing's stated mission:

| Glasswing target | This submission |
|---|---|
| Securing critical infrastructure | 911 PSAP dispatch |
| AI finding & fixing vulnerabilities | Cyber harness on Fish/NeMo/LiveKit |
| Open-source maintainer access | All deps Apache 2.0; we PR upstream |
| Multi-vendor collaboration | LiveKit + NVIDIA + Anthropic + Fish + NeMo |
| Defensive cybersecurity playbook | Defender / attacker / fixer multi-agent |

## Mythos-capability proof points (what makes Cherny's team take note)

- **Agentic coding at scale**: Claude Code wrote N CUDA/Triton/Python
  kernels with M iterations each. Iteration count drops over the 5-day
  window — visible trend line.
- **Multi-agent harness in production**: 8 specialist subagents, real
  sprint contracts, scribe captures everything, generator/evaluator
  loop validated against real outcomes (audio quality, kernel
  correctness).
- **Cybersecurity at scale**: 5 codebases audited in parallel, X
  findings, Y PRs drafted, Z merged.
- **Build-for-future-model**: charts that show Opus 4.7 today doing
  what 4.6 couldn't. Implication: Mythos tomorrow does autonomously
  what we coordinated by hand.

## What the scribe agent captures

Every Claude Code conversation in `findings/glasswing/conversations/`:
- Filename: `<UTC>-<subagent>-<task-slug>.md`
- Content: prompt + tool calls + diffs + final outcome + iteration count
- Aggregated into `findings/glasswing/iteration-trends.json`
- Demo deck pulls from this directory

## Demo failure modes & mitigations

| Risk | Floor mitigation |
|---|---|
| Voice TTFB doesn't drop to < 500ms | Show the diagnosis path + a Triton kernel that landed *some* improvement; honest Nsight before/after |
| Cyber harness finds nothing real | "Soft findings" tier: race conditions, missing rate limits, deserialization risks. Still a writeup. |
| OSS PR not merged in time | Ship the open PR + the conversation log; merging within hackathon window is gravy |
| Live demo fails on stage | Pre-recorded 90s video + live console showing the harness orchestrating in real-time |
| GPU still idle at 0% during demo | Honest Nsight slide showing where the time *actually* goes — that itself is a Mythos-class profiling demo |

## Voice + cyber both fail badly: the meta-recovery

Even if every artifact misses its goal, the **scribe's archive of Claude
Code conversation logs + iteration trends** is by itself a Mythos-aligned
contribution. A solo dev's 5-day archive of Claude Code orchestrating
multi-agent kernel + cyber work, with iteration counts and capability-
unlock timestamps, is the kind of dataset Anthropic would want for
internal "model in six months" calibration.

That's the floor of the floor. Submission is never empty.

## Ship checklist (T-7h to T-0)

- [ ] 90s demo video uploaded
- [ ] Submission writeup committed + linked
- [ ] All 8 subagent role files committed
- [ ] Nsight before/after slide in `findings/glasswing/`
- [ ] Cyber harness findings deck in `findings/glasswing/`
- [ ] PR draft(s) opened in upstream repos (Fish/NeMo/LiveKit if findings warrant)
- [ ] Scribe archive committed under `findings/glasswing/conversations/`
- [ ] `iteration-trends.json` chart generated
- [ ] Cerebral Valley submission form completed
- [ ] User attestation (task #87) — voice works on laptop + mobile
- [ ] `make verify-all` green on fresh checkout

## Resources for the scribe agent

When summarizing what we built, point at:

- `docs/livekit-kb/00-overview.md` — repo orientation
- `docs/livekit-kb/16a-lever-registry.yaml` — the 13+ optimization levers + measured deltas
- `docs/livekit-kb/17-sota-polish-48h.md` — the original 48h cadence (now revised)
- `docs/livekit-kb/18-stack-evaluation.md` — strategic frame
- `tests/voice/slo.yaml` — the durable SLO contract
- `scripts/ralph_loop.sh` — the measure-bottleneck-suggest loop
- `mvp/911-console-live/` — the dispatcher UI

The harness is the artifact. The artifact is the harness. Both are the
submission.
