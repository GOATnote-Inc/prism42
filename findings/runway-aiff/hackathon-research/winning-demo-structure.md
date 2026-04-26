# prism42 — Winning Demo Structure for "Built with Opus 4.7"

2026-04-25 · deadline 2026-04-26 20:00 ET · 3-min video + repo + 100–200w summary · Brandon Dent, MD solo build

---

## Inline summary

prism42 fits the "Built with Opus 4.7" rubric structurally, but the 3-minute video must be rebuilt around four assets the existing documentary cut implies but doesn't show: (1) a real voice turn through the live LiveKit + B300 stack, (2) a TTFT receipt (1655 ms → 44 ms p95) on a dashboard, not a chyron, (3) at least one Opus-4.7-only capability — adaptive thinking with `display: omitted`, task budgets, or parallel Managed-Agent threads — and (4) a written summary that leads with *physician-built 911 dispatch* (last cycle's 3rd place was a cardiologist; the impact lane is open).

Of the three $5k specials, **"Keep Thinking" is most winnable** — TARA and PostVisit.ai both won prizes on the "real-world problem nobody thought to point Claude at" pattern that prism42 fits exactly. **Best Managed Agents** is secondary if the demo shows the parallel-threads shot live. Don't chase Most Creative — documentary register is right and pivoting weakens main scoring.

Recommended structure: 0–20s problem hook (real 911 audio cold-open), 20–60s live voice turn, 60–110s engineering receipt (sm_103 / NVFP4 / vLLM-rebuild + adaptive-thinking spec), 110–160s parallel-agents reveal, 160–180s impact close + GitHub frame. Theory of win: physician credential × live latency receipt × Opus-4.7-only feature × Managed Agents = top-3 + Keep Thinking.

---

## 1. Built-with-Opus-4.6 winners

Feb 2026: 13K applicants → 500 → 6 finalists → 3 main + 2 specials.

1. **Mike Brown (1st) — CrossBeam.** PI lawyer. Drag-and-drop blueprints + correction letters; **parallel sub-agents** parse, build a spatial index, assign targeted agents per correction; 20 min later, action plan. Famously "didn't write a single line of code" — prompted Claude Code, had Claude write the tests. Demo: `youtube.com/watch?v=jHwBkFSvyk0`.
2. **Jon McBee (2nd) — Elisa.** Visual block IDE for non-coders.
3. **Michał Nedoszytko, MD (3rd) — PostVisit.ai.** Cardiologist. Plain-language diagnosis explainer + scribe analysis. Built between hospital shifts.
4. **Kyeyune Kazibwe — Keep Thinking — TARA.** Dashcam → road-investment appraisals in 5 hours vs weeks.
5. **Asep Bagja Priandana — Creative — Conductr.** Browser MIDI improv from live chord input.

**Shared traits:** domain-expert framing; open with the problem not the tech; one visceral demo moment; visible Claude Code loop; no architecture-diagram openers; under 4 min. **Winning pattern:** out-of-domain expert × workflow that took weeks/was impossible × one moment where the audience says "wait, that just *worked*?" prism42 fits: MD × 911 dispatch × the live voice turn at 44 ms TTFT.

## 2. Cerebral Valley pacing precedents

Cerebral Valley winners (Agentic Orchestration, Opus 4.6, model-launch events) share a 3-act shape: **Act 1 (0–25%) the problem** — stated as a person not a market ("California builders wait months"); **Act 2 (25–75%) the live demo** — hands on screen, real input/output, no cuts that hide latency; **Act 3 (75–100%) the engineering reveal + ask** — what part was *uniquely* possible because of Opus 4.7. Pacing is brisk: 6–10 second beats. Losers: 90-second-monologue-over-static-screenshot.

## 3. Anthropic's own demo aesthetic

Anthropic launch videos (Building Effective Agents, Claude Code, Managed Agents, Opus 4.7) share a recognizable signature: Söhne/Inter sans, lots of negative space, warm off-white #F5F1EB + near-black #1A1A1A + accent #DA7756 (avoid neon-cyber-blue); breathy pacing with hero numbers held 2–3 seconds; measured dry VO (never "amazing"/"incredible"); locked-off terminal shots with code zoomed-and-highlighted not wall-of-text; sparse pads that drop out for hero moments; and one "engineering reveal" shot per video where an actual capability is shown in motion. The existing prism42 documentary cut (`script-v2.md`) already nails this register — keep it, extend to 3:00, put the live voice turn on screen.

## 4. Demo failure modes — the don't-do list

Reliable losers: reading the README aloud (pick one channel — VO or on-screen text, not both); architecture diagrams as Act 1; code on screen >5 seconds without highlight; VO explaining what we're seeing ("as you can see…"); music overpowering VO (-12 dB ducking minimum, drop to silence on hero moments); fake/sped-up demos with hidden cuts (judges have seen this 200 times); vague Opus integration ("we used Claude") — the 25% Opus axis explicitly rewards "capabilities that surprised even us," so name a 4.7-only feature; no latency receipt ("it's fast" is not an artifact, "44 ms p95, here's the dashboard" is); no GitHub frame (repo URL must be visible full-screen at least once).

## 5. The prism42-specific 3-minute structure

Format: 12 beats over 180 seconds, mapped to scoring axes.

| # | Time | On screen | VO (tight) | Overlay | Axis served |
|---|------|-----------|------------|---------|-------------|
| 1 | 0:00–0:08 | Real 911 dispatch room B-roll, headset close-up | "Every 911 call starts with a question. *How fast can help arrive.*" | Lower-third: "GOATnote · prism42" | Impact |
| 2 | 0:08–0:20 | Cut to caller-side phone, ringing | "A solo developer — a physician — spent five days trying to get that question answered in under 50 milliseconds." | Brandon Dent, MD — solo build | Impact (physician credential) |
| 3 | 0:20–0:35 | Live screen recording: browser opens, phone-call tone, agent picks up, real voice turn | (no VO during the turn — let it play) | bottom: "live voice turn — Apr 25" | Demo (the visceral moment) |
| 4 | 0:35–0:55 | Split screen: Cartesia waveform left, dashboard right showing TTFT graph dropping from 1655 → 44 | "The hosted-API baseline. p95 sixteen-fifty-five milliseconds. The local stack." beat. "Forty-four." | Hero: 1655 ms → 44 ms · −91.6% | Demo + Depth |
| 5 | 0:55–1:10 | Terminal: vLLM 0.20 build flags, `TORCH_CUDA_ARCH_LIST=10.3`, NVFP4 GEMM passing | "Native sm one-oh-three codegen. NVFP4 on Blackwell. CUDA 13. vLLM rebuilt from source." | code highlight on `sm_103` | Depth & Execution |
| 6 | 1:10–1:25 | Whiteboard / kernel diagram + the three breakages from the honesty audit | "Three things broke first. macOS shipped no `timeout` binary. An env file took down a shell. A perf claim got retracted under review." | "honesty audit" lower-third | Depth (real craft) |
| 7 | 1:25–1:50 | Claude Code session window — Opus 4.7 adaptive-thinking call with `display: omitted` writing the dispatcher prompt; `task-budgets-2026-03-13` header visible | "Opus 4.7. Adaptive thinking, display omitted — so the dispatcher answers, not narrates. Task budgets so the model paces itself across a multi-turn call." | code highlight on `thinking: adaptive`, `display: omitted` | **Opus 4.7 Use** (the surprising capability) |
| 8 | 1:50–2:15 | Managed Agents dashboard or terminal: three concurrent threads — coordinator, dispatcher, clinical-rail auditor — with thread-message events streaming | "One coordinator. Parallel threads. Dispatcher answers the call. Auditor checks every clinical claim against HealthBench Hard *while the call is still happening*." | "Managed Agents · agent_toolset_20260401" | **Best Managed Agents** prize |
| 9 | 2:15–2:30 | Latency dashboard frozen on the p95 number, sirens fading in low | "End-to-end p95 — under one and a half seconds. The latency of a well-rested human." | end-to-end p95 — 1.42 s | Demo |
| 10 | 2:30–2:45 | Brandon at desk (faceless, hands only, scrubs sleeve visible), then cut to 911 dispatch room | "Built by a physician. Five days. Nights. Between hospital shifts." | "Brandon Dent, MD — solo dev" | Impact (Keep Thinking lean) |
| 11 | 2:45–2:55 | GitHub repo full-screen, README scrolling once | "Open source. Apache 2. github dot com slash GOATnote-Inc slash prism42." | repo URL hero | Demo (judges screenshot this) |
| 12 | 2:55–3:00 | End card: prism42 wordmark, the 44 ms number, GOATnote logo | (silence, single low brass) | "prism42 — answer in 44 ms" | Brand close |

Production notes: **Beat 3 is load-bearing** — pre-record three takes, fall back to a known-good screen-capture with visible timestamp if all fail. **Beat 7** must name an Opus-4.7-only capability (adaptive thinking, `display: omitted`, task budgets, 1M context, +35% tokenizer — citations in CLAUDE.md). **Beat 8** can be a Managed Agents demo even without multi-agent workspace access — one coordinator with `agent_toolset_20260401` running a long session with the clinical-rail audit qualifies; show the session log + thread events + a tool-error recovery if you have one.

## 6. Special-prize positioning

| Prize | Past winner | prism42 fit |
|-------|-------------|-------------|
| Most Creative | Conductr (MIDI improv) | **Low** — documentary register, don't fight it |
| Keep Thinking | TARA (dashcam → road appraisal) | **High** — PSAP dispatch is "nobody-thought-to-point-Claude-at" |
| Best Managed Agents | (new for 4.7) | **High** — coordinator + dispatcher + auditor across a 3-min call is a real long-running task |

**Recommendation: Keep Thinking primary, Managed Agents secondary.** Keep-Thinking tilt (no trade-off): lead the written summary with "PSAPs handle ~240M calls/year — nobody is targeting dispatch; the bottleneck is latency, not vocabulary"; beat 10 emphasizes physician-built-between-shifts; the beat-6 honesty audit signals genuine wrestling. Managed-Agents tilt (cheap insurance): beat 8 must show the actual session log + thread events, not a slide; the repo needs a `MANAGED_AGENTS.md` documenting agent topology with canonical event names — judges for this prize will check the repo.

## 7. The differentiator argument

Most submissions will be ElevenLabs + Claude API + Next.js + customer-service/scribing. prism42 must visibly differentiate on at least four:

1. **Self-hosted on B300** — Nemotron Nano 3 MoE on vLLM 0.20, native sm_103. Almost no entry rebuilt vLLM for Blackwell-Ultra. *Beat 5.*
2. **Latency receipt** — 1655 → 44 ms p95 TTFT with dashboard. *Beat 4.*
3. **Hooks for hard-rule enforcement** — PSAP rules (no invented addresses, no off-protocol advice, no early call-end) via Claude Code's 8 hook events. *Beat 7 — show one firing if possible.*
4. **Skills** — EMD/fire/police protocols, loaded per call type. *Flash `.claude/skills/dispatch-emd/SKILL.md`.*
5. **Parallel agent teams** — coordinator + dispatcher + clinical-rail auditor. *Beat 8.*
6. **Managed Agents long-horizon** — a 3-min call with durable session state + tool-error recovery. *Beat 8.*
7. **Munger inversion as a pattern** — frozen paths, double-gates, retracted claims (CLAUDE.md §3-§5). *Beat 6.*
8. **sm_103 / NVFP4 / vLLM-rebuild depth** — B300 native codegen vs PTX-JIT is genuinely novel. *Beat 5.*
9. **Physician-built** — MD credential aligns with last cycle's 3rd-place pattern. *Beats 2, 10.*

Beats 4, 5, 7, 8 landing puts prism42 in the top decile on technical merit; beats 2, 3, 9 carry impact.

## 8. Production notes — assets

Existing assets to reuse from `findings/runway-aiff/`: `clips/` (Dec-2024 B-roll, hands-only for SHOT 10); `master.mp4` (75–90s documentary; SHOTS 1, 2, 4, 6 lift directly); `script-v2.md` BRIAN VO segments — extend with new VO for SHOTS 7–11.

New assets to capture (~$10 total): clean live-voice-turn screen recording (SHOT 3, re-record on the pod); Claude Code Opus 4.7 session capture with adaptive thinking visible (SHOT 7); Managed Agents session log (SHOT 8); TTFT dashboard graphic (SHOT 4) and E2E p95 dashboard (SHOT 9) as DaVinci Fusion comps from the real measurement JSON.

## 9. Written summary (100–200 words) — draft

> prism42 is a self-hosted 911 voice-dispatch agent built solo in five days by Brandon Dent, MD, during the Built with Opus 4.7 hackathon. It runs Nemotron Nano 3 MoE on vLLM 0.20 with native sm_103 codegen on a Blackwell-Ultra (B300) pod, NVFP4 GEMM, and CUDA 13. End-to-end p95 latency is under 1.5 seconds; time-to-first-token p95 dropped from 1655 ms (hosted baseline) to 44 ms (local stack), a 91.6% reduction.
>
> The dispatcher, clinical auditor, and coordinator run as parallel Managed Agents threads with `agent_toolset_20260401`. Opus 4.7 adaptive thinking with `display: omitted` lets the model reason without narrating to the caller. Task budgets pace the model across multi-turn calls. Hooks enforce PSAP hard rules — no invented addresses, no off-protocol medical advice. Skills load EMD/fire/police dispatch protocols on demand.
>
> No one is pointing AI at 911 dispatch. The bottleneck is latency, not vocabulary. prism42 is the first measured demonstration that a physician with Claude Code and a B300 can close that gap in a week.
>
> Repo: github.com/GOATnote-Inc/prism42 (Apache 2.0).

(189 words.)

## 10. Theory of Win

prism42 places top-3 and takes the Keep Thinking $5k because it is the only entry in the 500 where a credentialed physician built a self-hosted local-LLM 911 dispatch agent on Blackwell-Ultra in five days with a measured 91.6% latency receipt on a live dashboard, a live voice turn that holds up on camera, an Opus-4.7-only capability named explicitly, and parallel Managed Agents threads. All four scoring axes are simultaneously maximized — Impact (PSAP × MD), Demo (live turn + dashboard), Opus 4.7 Use (adaptive thinking is 4.7-only), Depth (sm_103, NVFP4, vLLM rebuild, honesty audit) — and the Keep Thinking tilt is congruent with the impact narrative rather than orthogonal. The only failure modes are operational, not strategic.

---

## Sources

Anthropic — [4.6 winners](https://claude.com/blog/meet-the-winners-of-our-built-with-opus-4-6-claude-code-hackathon), [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents), [Managed Agents](https://www.anthropic.com/engineering/managed-agents), [harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps); Cerebral Valley — [4.7 hackathon](https://cerebralvalley.ai/e/built-with-4-7-hackathon), [4.6 stats](https://x.com/cerebral_valley/status/2026066211482857844); CrossBeam demo — [YouTube](https://www.youtube.com/watch?v=jHwBkFSvyk0); Nedoszytko 3rd-place — [X](https://x.com/trajektoriePL/status/2024774752116658539), [TechStory](https://techstory.in/cardiologist-builds-patient-care-app-in-7-days-places-third-at-anthropic-hackathon/); Opus 4.7 — [whats-new](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7), [adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking), [task budgets](https://platform.claude.com/docs/en/build-with-claude/task-budgets); Claude Code — [best practices](https://code.claude.com/docs/en/best-practices), [skills](https://code.claude.com/docs/en/skills), [agent teams](https://code.claude.com/docs/en/agent-teams); [InfoQ Managed Agents](https://www.infoq.com/news/2026/04/anthropic-managed-agents/); local: `script-v2.md`, `PLAN.md`, `CLAUDE.md`.
