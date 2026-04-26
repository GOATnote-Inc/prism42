# Script

## SEGMENT 1 — COLD OPEN (0:00–0:20)
**Setting:** Glossy news desk, "GOATnote Nightly" bumper resolves into a wide of KEN (the fox anchor) behind monitors.
**Visual cue:** Bumper graphic spins. Lower-third strap snaps in. One monitor briefly shows a terminal with green text.

KEN (V.O. over bumper):
From the only desk still covering the hackathon nobody can name — this is GOATnote Nightly.

KEN (on camera):
Tonight: an anonymous compliance audit. A kernel that should not exist. And a number so small a senior engineer briefly forgot he was on camera.

FIZZLEPUFF (V.O., from puppet bureau, satellite-glitched):
Brian — Brian, no cap, the GEMM is crashing — sorry, sorry, am I early — am I — is this live, fr —

KEN (on camera, unbothered):
We'll get to him.

**Lower-third:** "BREAKING — THE HACKATHON NOBODY CAN NAME"
**Cut to:** Compliance Desk graphic.

---

## SEGMENT 2 — COMPLIANCE DESK (0:20–0:50)
**Setting:** FOX at desk. Behind him, a monitor shows redacted commit hashes.
**Visual cue:** First cut to CAT — felted puppet, pink tie, oversized round glasses, slight stop-motion judder. Chyron LIVE — PUPPET BUREAU. Faint satellite-feed scanline overlay and a one-frame signal hiccup as we land on him.

KEN (on camera):
Earlier this week, a solo developer discovered an open-source kernel repository was leaking proprietary IP from a vendor we are legally encouraged not to name. He ran a three-agent parallel audit. He used `git filter-repo`. He force-pushed a clean fresh repo. For comment, we go to our Puppet Bureau.

**Lower-third:** "LIVE — PUPPET BUREAU · anonymous IP-cleanliness investigation"

FIZZLEPUFF (on camera, glitched-in):
Brian, this is lowkey enormous — three agents, in parallel, cross-checking joint-tells the first two missed — you cannot un-leak a naming pattern, Brian, you can only scrub the history and pray the object store, deadass —

KEN (on camera, eyebrow up):
Thank you. We'll be checking back.

**Cut to:** Field-report graphic, "KERNEL LAB."

---

## SEGMENT 3 — KERNEL LAB FIELD REPORT (0:50–1:20)
**Setting:** CAT in the field. Tiny felted hard hat. Whiteboard behind him with softmax(QK^T/√d)V and "sm_103" stickers.
**Visual cue:** Stop-motion handheld bob. A felted GPU sits on a felted bench.

KEN (V.O.):
Our correspondent is at the Kernel Lab, where research-grade attention work is underway on Blackwell B300 silicon.

FIZZLEPUFF (on camera, escalating):
Brian, the math is mathing — they're targeting sm_103 directly — NVFP4 quantization on the GEMM path — this is Hopper's grandchild, Brian — and the cute DSL is pure-Python CUTLASS, which is fine, it is fine, except the C++ side is BSD-3 and the Python side is NVIDIA EULA so you cannot just — it's giving licensing collision —

KEN (V.O., dry):
Stay with the story.

FIZZLEPUFF:
Right. Right. Sorry. The kernel works.

**Lower-third:** "KERNEL LAB — B300 · NVFP4 · sm_103"
**Cut to:** B-roll of a server rack, blue LEDs.

---

## SEGMENT 4 — HARDWARE HOUR (1:20–1:50)
**Setting:** FOX at desk. Wall monitor: rack diagram, "livekit.thegoatnote.com" with a green TLS lock.
**Visual cue:** Cutaway B-roll of glowing fans. Quick cat cameo: chewing an SSH cable, freezes when he notices the camera.

KEN (on camera):
The same engineer this week stood up a self-hosted B300 pod. Caddy auto-TLS. Parakeet on port nine-one-hundred. Fish Speech on nine-two-hundred. SSH via a bypass in the Brev config that, frankly, should not work, and yet.

KEN (beat):
Not everything held. macOS ships no `timeout` binary, which silently broke a session-start hook for two days. An `.env` file with unquoted multi-line JSON took down a shell. And one performance claim — that a CUDA twelve-eight nvcc against a thirteen-oh driver had "negligible cost" — was retracted under pressure. It was, in fact, broken at runtime.

FIZZLEPUFF (V.O., off-camera, mouth full):
Sorry — the cable, was it load-bearing —

**Lower-third:** "HARDWARE HOUR — three things that broke before anything worked"
**Cut to:** ENGINEERING BREAKING NEWS sting.

---

## SEGMENT 5 — ENGINEERING BREAKING NEWS (1:50–2:30)
**Setting:** FOX center frame. Full-screen graphic loads behind him.
**Visual cue:** Two huge numbers slam in. **1655 ms** in red, slashes out. **44 ms** in green. Underneath: "TTFT p95 · vLLM 0.20 · Nemotron Nano 3 MoE · FLASHINFER."

KEN (on camera):
This is breaking. The voice agent migrated off a hosted API onto local Nemotron Nano 3 on vLLM zero-point-twenty. First boot: the NVFP4 cutlass-scaled-fp4 GEMM crashed on the GPU. They installed CUDA thirteen nvcc. They installed flashinfer-cubin. They rebuilt vLLM with native sm_103. The five-gate strict performance gate —

KEN (beat, breaks for half a second, recovers):
— passed. Time-to-first-token, p95: forty-four milliseconds. Down from sixteen-fifty-five. A ninety-one-point-six percent reduction. Three-eleven tokens per second at p50. FLASHINFER attention, optimal — not degraded. JIT penalty, three-point-four milliseconds. All three services still listening.

FIZZLEPUFF (V.O., quietly):
Brian. Brian, deadass — that's the latency of a well-rested human. We are SO back.

**Lower-third:** "TTFT p95 — 1655ms → 44ms · −91.6%"
**Cut to:** Slow push-in on FOX as desk lights dim.

---

## SEGMENT 6 — CLOSER (2:30–3:00)
**Setting:** Lights down to a single key on FOX. Monitors dim. Quiet room tone.
**Visual cue:** End-card graphic loads in the last four seconds: "GOATnote Nightly — built with Claude Code, Opus 4.7, agent teams, hooks, skills, and one cat."

KEN (on camera, level):
None of this was one model and one prompt. It was scoped agents. Tasked agents. Tested agents. Looped agents. Hooks that refused to let bad commits through. Skills that knew where the manuals lived. A coordinator and its parallel evaluators. The week shipped because the work was small enough to verify and large enough to matter.

KEN (beat):
Five days. One developer. A B300, a felted correspondent, and three things that broke on the way to a number that didn't.

FIZZLEPUFF (on camera, glitched-in one last time, calm now):
Brian. We did the thing. The dev cooked.

KEN (on camera, faintest smile):
We did the thing. Goodnight.

**Lower-third:** "GOATnote Nightly · AIFF 2026"
**Cut to:** End card, hold two seconds, fade.

---

## Voice direction notes

KEN: Warm baritone, 60–70 wpm in delivery, Brokaw/Holt cadence — clauses land, no upspeak. Eyebrow does the work the voice refuses to. ElevenLabs recommendation: **Bill** (deep newscaster) or **Brian** (American narrator) at stability 55, similarity 75, style 15. Avoid the "podcast-host" presets — too much vocal fry.

FIZZLEPUFF: Nervous tenor, slightly higher pitch, 110–130 wpm with sharp accelerations on technical terms. Breath audible. Pitch ticks up half a step when a number is correct and he knows it. ElevenLabs recommendation: **Adam** pitched +2 semitones, or **Charlie** at stability 35, similarity 80, style 60. Run through a mild AM-radio EQ + 3% packet-loss artifact for the satellite feed.

## Music bed direction
CC0 source: Kevin MacLeod "News Theme" family or FreePD "Newsroom" — orchestral synth bed, 95–105 BPM, no melody on top. Ducks −12 dB under all dialogue. Drops out entirely 1:50–2:00 (the silence before the 44ms reveal does the lifting). Re-enters soft on the closer at −18 dB. End card: single sustained low brass, four seconds, hard cut.

## Honesty audit
Four "stuff broke" beats included:
1. NVFP4 cutlass_scaled_fp4_mm GEMM crash on first vLLM boot — **Segment 5**.
2. macOS missing `timeout` binary silently breaking a session-start hook — **Segment 4**.
3. `.env` with unquoted multi-line JSON taking down shell sourcing — **Segment 4**.
4. Retracted "negligible perf cost" claim on the CUDA 12.8 nvcc / 13.0 driver split — **Segment 4**.
