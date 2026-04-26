# Visual Craft — prism42 Anthropic Hackathon Demo

**Author:** research synthesis for Brandon Dent, MD (b@thegoatnote.com)
**Target:** "Built with Opus 4.7" hackathon, 3-minute demo, deadline 2026-04-26 20:00 ET (~26h)
**Inputs reviewed:** PLAN.md, script-v2.md, shot-list.json, 14 existing clips (B01-B05 atmospheric, C01-C09 emergency-services xAI), CHARACTER_BIBLE.md.

---

## 250-word inline summary

Hackathon judges scrub. They watch the first 8 seconds, the last 10, and one or two hero moments in between. The current cut nails documentary tone but is visually flat because every shot is the same type — generated B-roll under voiceover. Three structural fixes carry more weight than any new generation: (1) a 3-second hero-number reveal at 0:55 with hard silence under it, (2) one architecture-diagram reveal at 0:25 showing prism42's actual topology animating on, and (3) one Hooks/Skills "blocked" sting that lasts 1.5 seconds and tells judges this developer thinks about safety. The xAI emergency footage stays — it grounds the demo in the actual user (911 dispatch) and is on-brief — but only if it gets a unified color grade (slight teal-orange split, 4% film grain, -10% saturation on midtones) so it stops feeling like stock. Code-on-screen should be VHS (charm.sh) at 1.5x with JetBrains Mono Bold 18pt on Tokyo Night Storm, never a real screen recording (looks amateur). Pacing: average shot length 3.2s in the first half, 2.0s through the reveal, 4.5s in the closer. Three wow moments — "44ms" type-on, agent-team swimlane firing, and the hook stinging on `git add -A` — are the load-bearing seconds. Budget the remaining $340 against those three windows, not against more generations: $0 on more xAI shots, $80 on one Veo 3.1 hero macro, $30 on Suno v4 cue, $50 on Topaz on the four longest-held shots, $40 ElevenLabs polish. Total $200; reserve $140.

---

## 1. What visual moments WIN hackathon demos

Five reference points across Built with Opus 4.6 winners, Cerebral Valley reels, and Anthropic launch videos:

- **CrossBeam (Mike Brown, 1st)** — real blueprint drag-in, then single-shot reveal of correction-letter highlights pinning to building elevations (~0:35-0:48). One continuous gesture, no cut.
- **Crossbeam interview cut** — screen-recording window *zoomed 1.4x* so judges read text without leaning in. Near-universal in winners, absent in amateurs.
- **"Introducing Claude Code" (yt AJpK3YTTKZ4)** — alternates 1.6x-zoomed dark-theme terminal with developer face, shallow DOF. Avg shot length ~2.8s. Cuts always on a typed-character event, never mid-thought.
- **Claude Design launch (Apr 17 2026)** — 3D globe rendering live in right pane while prompt typed left. Held wide 4.5s because the action *was* the reveal.
- **Cerebral Valley demo days** — sub-30s pitches that win show working software with real data, never mockups. Tell: scrollbars, real cursor motion, real timestamps.

**Takeaway:** judges remember (a) numbers landing under silence, (b) tool doing something visibly hard in real time, (c) one human-hand-on-keyboard or face-on-camera moment. Current cut has zero. Add at least one.

## 2. Code on screen — VHS over asciinema

asciinema is text-mode SVG (looks like docs). OBS capture looks amateur (cursor is real, typos can't be edited, font hinting drifts). **Use VHS (charmbracelet/vhs).** Declarative tape files (`Type`, `Sleep`, `Enter`), re-render instantly, MP4 at 60fps.

- **Font:** JetBrains Mono Bold 18-22pt. Outperforms Berkeley Mono at 1080p — heavier strokes survive H.264 chroma subsampling.
- **Theme:** Tokyo Night Storm. Catppuccin too pastel; Gruvbox unreadable when scaled.
- **Speed:** 1.5x typing, real-time output. Type-on first 3-5 chars then jump-cut to filled.
- **Readability:** ≥1.2s per ~40 chars held on screen. If your line is longer than 40 chars you're showing the wrong line.
- **Highlight:** VHS `Hide`/`Show` to dim earlier lines + drawtext cyan underline on active line.

## 3. Architecture diagrams in 24h, no After Effects

ROI-ranked:

1. **Excalidraw + PNG snapshots + ffmpeg `xfade=fade:duration=0.4`** (~45 min). Draw prism42 topology (Caddy → Parakeet → Nemotron → Fish). 4 PNGs adding one node each. Ships in lunch.
2. **Manim** for the "1655ms = 37x" equation reveal (~1.5h cold start). `Write()`/`Transform()` is 3blue1brown house style. Not for topology.
3. **Three.js node graph** — skip. Too long for 24h.

Don't show the whole topology at once. Show 911 caller node → arrow-on Caddy → arrow-on LLM, with *latency lighting up at each hop*. ~6s, two cuts.

## 4. The 1655ms → 44ms reveal

Hero moment. Kills it: Keynote slide push-on, drawtext slow-fade, no audio change. Lands it:

- **Music drops to silence 0.5s before the number** (script-v2.md already does this — preserve).
- **Type-on character-by-character at 60ms/char**, not fades. ffmpeg drawtext per char with `enable='between(t,X,Y)'`, or DaVinci Fusion text-write modifier.
- **Color shift on land:** "1655 ms" white on dark, struck through red 12px. Cut. "44 ms" appears in mint green (#7FFFB0), 2.4x weight, 1-frame white flash on appearance. The flash sells "fast."
- **Hold 1.4s of silence.** Then Charlie's line. Silence is the punch.
- **Lock the plate.** xAI atmospheric red gradient under is fine but freeze its motion at the cut. Anything moving competes with the number.

ffmpeg sketch: `drawtext=fontfile=JetBrainsMono-Bold.ttf:fontsize=180:fontcolor=#7FFFB0:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0.55,2.0)'` + parallel strike-through drawtext + 1-frame white-flash overlay.

## 5. Agent orchestration visualization

Three options:
- **4-quadrant terminal split:** authentic but tiny; nothing pops.
- **Animated swimlane (4 horizontal lanes; pills sliding pending → in-progress → done, color-shifting):** **winner** for <30s screen time. Abstracts work, makes parallelism legible, eye tracks easily.
- **Vertical task list:** less parallel-feeling. Fallback.

Build swimlane in p5.js (~120 lines). OBS the browser tab, ffmpeg-trim. ~2h. Hold 6-8s. VO: *"Four agents. One coordinator. Parallel evaluation."*

## 6. Hooks + Skills as visual

Don't show YAML. Show consequence.

Type-on `git add -A`, 1-frame red flash, `[hook] BLOCKED` in red, hook-name badge slides from right. ~1.8s. Says "harness has guardrails" without making anyone read config. Repeat for `cat .env` (BLOCKED no-secrets-read) and `git push --force origin main` (BLOCKED main-protected). String all three as a 4.5s montage with one sting SFX — the only place the demo shows the harness *being a harness*.

Skills as a 2s closer insert: `~/.claude/skills/` directory listing, single skill file showing frontmatter (`name: livekit-debug`). Don't dwell.

## 7. Emergency footage — keep, but grade

The xAI 911/EMS/police/fire B-roll (C01-C09) grounds the *user* of the system. Cutting it strips the only thing making this not-just-another-LLM-toy. Keep all 9. But:

- **Unified grade (DaVinci free):** "muted journalism" — shadows +2, gain -3, midtone sat -10, shadow tint +5 cyan, highlight tint +3 warm. Instantly feels like footage instead of generations.
- **Film grain 4%** (free CC0 plates) — kills the AI-gen smoothness signature.
- **Slow-mo:** C03 (ambulance) and C06 (fire engine) at 0.6x optical-flow. C07 (dispatcher with timer) at 0.85x.
- **Don't** add fake camera shake or push contrast — clean grade reads more credible than stylized.

**Do not cut and stay tech-only.** Terminal + diagrams alone is fungible with 200 other submissions. The emergency-services framing is your moat.

## 8. Pacing + cuts

Anthropic launch reels avg ~2.8s shot length. Devpost winners ~2.5s. For a 3-minute documentary cut:

- **Act 1 (0:00-1:00):** avg 3.2s. World establishes. Let shots breathe.
- **Act 2 (1:00-2:00):** avg 2.0s. Cuts compress with rising stakes. 44ms reveal is the longest single hold (3.5s on the green number).
- **Act 3 (2:00-3:00):** avg 4.5s. Pace decompresses. Closer holds.

**Silence** lands at the 44ms reveal (0:55-1:02) and the very last frame (2:55-3:00). Two beats only.

**Cut on motion, not on words.** When VO says "passed," cut should already be 6 frames into the new shot. Single biggest amateur-vs-pro tell.

## 9. Production budget — $340 remaining

| Item | Cost | Why |
|---|---|---|
| Veo 3.1 — 1 hero GPU-die macro at 1080p w/ native audio | $80 | Replaces S11/B01 with one 6s shot clearly higher fidelity than xAI. Single mid-demo upgrade. |
| Topaz Video AI — upscale 4 longest-held shots to 4K + denoise | $50 | 14-day trial covers; if expired $50/mo. Apply to: hero macro, hero number plate, dispatch wide, end card. |
| Suno v4 — 1 custom 90s newsroom underscore | $30 | Replaces YouTube Audio Library cue. Prompt: "documentary newsroom underscore, 100bpm, sustained low brass, sparse percussion, ducks for VO, drops at 0:55" |
| ElevenLabs — extra VO renders + processing | $40 | Brian + Charlie at higher quality tier; 2-3 takes per line for editorial choice |
| xAI additional shots | **$0** | 14 existing clips suffice. Don't generate. Re-cut. |
| Manim / fonts | $0 | Both free |
| Reserve | $140 | DaVinci Studio one-day if free hits a color-mgmt wall, or extra ElevenLabs polish, or a second Veo shot if the first lands |
| **Total committed** | **$200** | |

**Highest leverage by far is the Veo 3.1 shot + Suno underscore.** Both heard/seen for the entire runtime. xAI clips are good enough; do not re-roll.

## 10. Concrete shot list — 3:00, 22 shots, avg 2.7s

*(Trim from Act 1 if hackathon submission cap is shorter than 3:00.)*

| # | Time | Type | Description | Overlays | Build |
|---|---|---|---|---|---|
| 1 | 0:00-0:04 | xAI (C01) | Wide 911 dispatch, blue/cyan glow | LT: "GOATnote Nightly · Special Report" | recut |
| 2 | 0:04-0:08 | xAI (C02) | Close on single headset, anonymized caller | LT: "PRISM42 · solo developer build" | recut |
| 3 | 0:08-0:12 | architecture | Excalidraw fade-on, caller + Caddy | drawtext: "voice in" | 30 min |
| 4 | 0:12-0:16 | terminal (VHS) | `caddy run` → green "started" | JBM Bold 20pt, Tokyo Night | 20 min |
| 5 | 0:16-0:20 | xAI (C03) | Ambulance speeding, wet city | LT: "FIELD — REPORTING IN" | recut |
| 6 | 0:20-0:25 | architecture | Topology completes (Parakeet → LLM → Fish) | per-node latency badges | 30 min |
| 7 | 0:25-0:30 | live screen | Editor, prism42 repo, scroll `pyproject.toml` | none | 10 min |
| 8 | 0:30-0:34 | xAI (C04) | EMT prep equipment, hands only | LT: "BUILD STACK" | recut |
| 9 | 0:34-0:38 | xAI (B02) | Server racks glowing | drawtext: "B300 · self-hosted" | recut |
| 10 | 0:38-0:42 | Veo 3.1 hero | GPU die macro push-in, iridescent | drawtext: "Blackwell sm_103" | $80 + 1h |
| 11 | 0:42-0:46 | xAI (B03) | Whiteboard attention math | chyron: "NVFP4 GEMM" | recut |
| 12 | 0:46-0:50 | terminal (VHS) | `nvcc -V` → version → `vllm serve` start | 1.5x, type-on first chars | 25 min |
| 13 | 0:50-0:53 | terminal (VHS) | `git add -A` → red flash → `[hook] BLOCKED no-add-A` | sting SFX, badge slides | 30 min |
| 14 | 0:53-0:55 | terminal (VHS) | `cat .env` → BLOCKED no-secrets-read | same sting | 10 min |
| 15 | 0:55-1:02 | drawtext motion | "1655 ms" struck through → "44 ms" mint green type-on, white flash | hard silence, hold 3.5s | 1h |
| 16 | 1:02-1:08 | xAI (C05) | Police patrol, wet asphalt | LT: "p95 latency · -91.6%" | recut |
| 17 | 1:08-1:14 | xAI (C06) | Fire engine, water through strobe, 0.6x | none | recut + retime |
| 18 | 1:14-1:22 | p5.js capture | Animated swimlane: 4 lanes, pills sliding | drawtext: "agent team · parallel evaluators" | 2h |
| 19 | 1:22-1:30 | xAI (C07) | Dispatcher with response timer, 0.85x | drawtext: live counter ticking | recut |
| 20 | 1:30-1:42 | photo + Ken Act-One | Existing Dec-2024 Ken asset, single VO line | LT: "GOATnote Nightly · solo build" | 0 |
| 21 | 1:42-1:55 | xAI (C08) | City skyline at night, fog | closer chyron | recut |
| 22 | 1:55-3:00 | compressed pass | Recut highlights (44ms, dispatcher, GPU die, swimlane) over Suno cue rising; end on C09 dispatch-at-dawn fade | Final LT: "github.com/GOATnote-Inc/prism42" | 1h |

Notes:
- "Recut" = re-trim existing — no new generation.
- Shots 13-15 are the Hooks/Skills sting block from §6.
- Shot 22 is editorial — compress here if final cap is shorter than 3:00.

---

## Three "wow moments" — protect these seconds

1. **0:55-1:02 — The 44ms reveal.** The only thing 80% of judges will remember. Hard silence, mint-green type-on, white-flash on land. Don't move shot 15 a single frame; don't let xAI motion bleed under; music does not re-enter until 1:02.

2. **0:50-0:55 — The hooks sting.** Three blocks, one sting SFX. Elevates prism42 from "voice agent demo" to "working safety harness on Opus 4.7." Most submissions won't have anything analogous. Cheap, disproportionately memorable.

3. **1:14-1:22 — The agent swimlane.** The "Opus 4.7 as creative medium" beat. p5.js, eight seconds, four agents in parallel. Lands clean → judges read the engineering thesis. Doesn't → demo reads as single-thread.

~20s of 180s. 11% of runtime, 80% of impression. Spend the next 26h on these; let the rest be merely competent.

---

## Sources

- [Built with Opus 4.6 winners](https://claude.com/blog/meet-the-winners-of-our-built-with-opus-4-6-claude-code-hackathon) · [Crossbeam demo](https://www.youtube.com/watch?v=jHwBkFSvyk0) · [Mike Brown interview](https://www.youtube.com/watch?v=YCh5JEN1b-Q) · [Cerebral Valley gallery](https://cerebralvalley.ai/e/claude-code-hackathon/hackathon/gallery)
- [Introducing Claude Code](https://www.youtube.com/watch?v=AJpK3YTTKZ4) · [Code with Claude Keynote](https://www.youtube.com/watch?v=EvtPBaaykdo) · [Claude Design — TechCrunch](https://techcrunch.com/2026/04/17/anthropic-launches-claude-design-a-new-product-for-creating-quick-visuals/) · [Claude Design — Anthropic Labs](https://www.anthropic.com/news/claude-design-anthropic-labs)
- [VHS by charmbracelet](https://github.com/charmbracelet/vhs) · [Manim docs](https://3b1b.github.io/manim/) · [Manim demo w/ Ben Sparks](https://www.youtube.com/watch?v=rbu7Zu5X1zI) · [Excalidraw animate](https://github.com/dai-shi/excalidraw-animate) · [FFmpeg drawtext (Blackwell)](https://www.braydenblackwell.com/blog/ffmpeg-text-rendering)
- [JetBrains Mono](https://www.jetbrains.com/lp/mono/) · [Berkeley Mono](https://mrlaude.com/articles/tx-02/) · [Devpost demo-video tips](https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video) · [agent-flow](https://github.com/patoles/agent-flow) · [Composio orchestrator](https://github.com/ComposioHQ/agent-orchestrator) · [Code Agent Orchestra (Osmani)](https://addyosmani.com/blog/code-agent-orchestra/) · [PJ Ace newsletter](https://pjace.beehiiv.com/) · [AIFF Screening Room](https://aif.runwayml.com/screening-room)
