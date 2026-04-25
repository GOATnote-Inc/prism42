# Stack evaluation — Mythos-shaped artifacts on B300 (Glasswing-aligned)

> Strategic synthesis after Anthropic announced **Project Glasswing +
> Claude Mythos Preview** on 2026-04-24 (mid-hackathon). Updated brief
> from Boris Cherny's contestant Zoom: *"build for future model
> capability, mythos on the horizon"* — meaning Mythos itself, the
> unreleased frontier model, is the capability ceiling we should
> aim our submission *toward*.
>
> This document supersedes prior framings. The submission has **two
> parallel Mythos-shaped artifacts**, both shipped via a Claude Code
> multi-agent harness.

## Mythos Preview, decoded

- Announced 2026-04-24 alongside Project Glasswing — a $100M+ industry
  alliance (AWS, Apple, Broadcom, Cisco, CrowdStrike, Google, JPMorgan,
  Linux Foundation, Microsoft, **NVIDIA**, Palo Alto Networks).
- Mission: *secure critical software infrastructure with AI*.
- Mythos benchmark headline: SWE-bench Verified 93.9% (vs Opus 4.6 80.8%),
  Terminal-Bench 2.0 82.0%, **CyberGym 83.1%**, BrowseComp 86.9% with 4.9×
  fewer tokens.
- Mythos found a 27-year-old OpenBSD vuln, a 16-year-old FFmpeg vuln, a
  Linux-kernel privilege-escalation chain — autonomously, no human
  steering.
- Pricing post-preview: $25 / $125 per million input/output tokens.
- Available on Claude API, AWS Bedrock, Google Vertex AI, Microsoft Foundry.

**Implication for the hackathon**: submissions that demonstrate
Glasswing-shaped capability (agentic coding + cybersecurity + critical
infrastructure) on Opus 4.7 today are the literal "build for the model
in six months" pitch.

## Why Cherny's brief lands here

The brief in your contestant Zoom — *"build for future model capability,
mythos on the horizon"* — combined with the Glasswing announcement, says:

1. **The model six months from now is Mythos.** Submissions should
   anticipate that capability ceiling.
2. **The capability ceiling is agentic coding + cybersecurity at scale**
   (per the benchmark numbers + Glasswing framing).
3. **The route to that capability is Claude Code multi-agent harnesses**
   (Anthropic's Apr-8 product, the architecture Mythos was trained to
   exploit).
4. **The use case is critical infrastructure** (Glasswing's stated target).

A 911 PSAP voice agent on B300 *is* critical infrastructure. The submission
shape that resonates: solo-dev shipping kernel-level voice work +
Glasswing-style security audits on the same critical-infra codebase, all
via Claude Code multi-agent harness.

## The two artifacts

### Artifact 1 — B300 purrs (the voice mastery)

What today's voice-AI industry doesn't have: a fully self-hosted
Claude-driven 911 dispatcher hitting < 2s first-audio on B300.
Industry baseline 2026: 200ms first-audio. Cartesia leads at 40ms TTFA.
Our Fish: 4824ms. Gap: 24×.

**Goal**: 4824ms → ≤ 500ms TTFB (10× floor) or ≤ 200ms (24× ceiling). GPU
utilization 0% → 60-90% during synthesis (currently 3% peak). Solo dev
shipping kernel-level systems work via Claude Code multi-agent harness.

**Mythos shape**: agentic coding of low-level systems code that today
takes an NVIDIA team a week. Tomorrow Mythos does it across thousands of
OSS projects.

### Artifact 2 — Glasswing on our own dependencies (the cyber mastery)

Run a Claude Code multi-agent security harness — `defender` / `attacker` /
`fixer` — across the open-source dependencies of our own critical
infrastructure: Fish Speech, NVIDIA NeMo (Parakeet), LiveKit Agents,
livekit-plugins-anthropic, livekit-plugins-elevenlabs.

**Goal**: at least one real vulnerability (or hardening opportunity) found
+ a fix branch + a PR upstream. The PR is the receipt.

**Mythos shape**: directly executes Glasswing's playbook — find + fix
critical-infra vulns autonomously. We're using Opus 4.7, not Mythos, but
the workflow + harness is the proof point.

## Decision tree (route stays data-driven)

Phase 1 for each artifact runs in parallel. Each routes its star
deliverable based on what's measured:

```
Voice harness Phase 1 — Nsight + cProfile during one Fish synth turn:
├── Bottleneck = SGLang server config (CUDA graphs OFF, paged-KV OFF)
│       → Star: SGLang config fix + ONE Triton kernel for the next
│         largest hot path. Probability ≈ 70%.
├── Bottleneck = KV cache (eager allocation)
│       → Star: paged-KV cache rewrite. Probability ≈ 50%.
├── Bottleneck = autoregressive sequential dependency
│       → Star: speculative decoding via small draft model. Probability ≈ 30%.
├── Bottleneck = HTTP/Python overhead
│       → Star: Triton + zero-copy audio path. Probability ≈ 60%.
└── Bottleneck = Fish architecture irreducible
        → Pivot: Qwen3-TTS Blackwell-bug fix PR upstream. Probability ≈ 30%.

Cyber harness Phase 1 — multi-agent runs in parallel on:
├── prism42 codebase (PSAP critical infrastructure)
├── Fish Speech (TTS dependency, Apache 2.0)
├── NeMo / Parakeet (STT dependency, Apache 2.0)
├── livekit-agents (telephony framework, Apache 2.0)
└── livekit-plugins-anthropic (Claude bridge)

Findings tier:
├── A: real exploitable vuln in OSS dep → PR upstream (mythos hit)
├── B: real vuln in our own code → fix + writeup
├── C: soft findings (deser risks, race conditions, missing rate limits)
└── D: nothing → meta-finding "AI security audits at this scale need calibration"
```

All four cyber tiers produce a submittable artifact.

## Phase plan — hard time-boxes

| Phase | Window | Voice work | Cyber work | Auth needed |
|---|---|---|---|---|
| 0 | T-44h → T-43h (1h) | Revise this doc, scaffold subagent role files | Same | none |
| 1 | T-43h → T-39h (4h) | Nsight diagnosis, identify primary bottleneck | Multi-agent run on prism42 + Fish + NeMo + livekit | nsys install on pod |
| 2 | T-39h → T-19h (20h) | Star kernel artifact (data-routed) | PR drafts; upstream the strongest finding | per-step pod auth |
| 3 | T-19h → T-7h (12h) | Demo recording, Nsight before/after slide | Writeup + PR submission | minimal |
| 4 | T-7h → T-0 (7h) | Submit + rest | Submit + rest | none |

## Probability ladder

- **Floor (90%)**: Voice TTFB → ≤ 500ms via SGLang config. Multi-agent
  harness diagram. Working 911 demo. **At least one cyber soft finding**
  with writeup.
- **Median (50%)**: Floor + one Triton kernel for next-largest hot path
  + one own-codebase real fix.
- **Ceiling (15%)**: Floor + paged-KV or speculative-decoding rewrite
  landing 24× speedup + one OSS soft finding written up cleanly.
- **Moonshot (5%)**: Ceiling + merged PR upstream in Fish/NeMo/LiveKit
  with Claude Code conversation log linked from the commit message.

## Subagent harness — the meta-artifact

Eight Claude Code subagents (`.claude/agents/*.md`):

**Voice (4)**:
- `kernel-author` — writes Triton/CUDA/SGLang-config code
- `profiler` — runs Nsight + cProfile, reports before/after deltas
- `validator` — correctness + voice-quality regression tests
- `integrator` — LiveKit plugin glue + bench harness extension

**Cyber (3)**:
- `defender` — proactively audits code for vulnerabilities (output: finding-cards)
- `attacker` — drafts exploits / PoCs for findings (educational, attestation-only)
- `fixer` — writes patches + opens PR drafts

**Shared (1)**:
- `scribe` — captures every Claude Code conversation, builds the
  submission deck, produces the `iteration-count vs. capability-unlocked`
  chart that proves Cherny's "model in six months" thesis in graph form

Anthropic's Apr-8 Managed Agents multi-agent product is what the judges
just shipped. A working 8-subagent harness running cyber audits + kernel
work in parallel is the canonical demo of their own unreleased-tier
product.

## Where things land

- **This doc**: `docs/livekit-kb/18-stack-evaluation.md` (here) — strategic frame.
- **Submission narrative skeleton**: `docs/livekit-kb/19-glasswing-aligned-submission.md` — what the demo shows + writeup template.
- **Subagent role files**: `.claude/agents/*.md` — 8 files.
- **Lever registry update**: `docs/livekit-kb/16a-lever-registry.yaml` — adds Mythos-aligned artifacts as levers 14-21.
- **Memory pointer**: `~/.claude/projects/-Users-kiteboard/memory/project_goatnote_911_console.md` — append the Glasswing reframe.

## Sources

- [Project Glasswing announcement (Anthropic, 2026-04-24)](https://www.anthropic.com/news/project-glasswing) — the announcement is the brief.
- [Boris Cherny on Lightcone Podcast](https://x.com/ycombinator/status/2026787362693591205) — "build for the model six months from now"
- [Claude Mythos Preview system card](https://www.anthropic.com/research) — capability + safety properties
- [Inworld voice latency benchmarks 2026](https://inworld.ai/resources/best-voice-ai-tts-apis-for-real-time-voice-agents-2026-benchmarks) — industry baseline 200ms first-audio
- [Anthropic Managed Agents (Apr 8 2026)](https://www.anthropic.com/engineering/managed-agents) — multi-agent harness pattern
- [Anthropic harness design (Mar 24 2026)](https://www.anthropic.com/engineering/harness-design-long-running-apps) — generator/evaluator/sprint-contract pattern
