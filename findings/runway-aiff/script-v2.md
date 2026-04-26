# Script v2 — Documentary cut for AIFF 2026

**Register:** straight documentary, not satirical news.
**Subject:** engineering behind a 911 voice-dispatch agent (prism42).
**Visuals:** 911 dispatch / EMS / police / fire — no anthropomorphic characters.
**Voices:**
- BRIAN (ElevenLabs `Brian` — deep American narrator) — primary documentary voice.
- CHARLIE (ElevenLabs `Charlie` — younger British, used SPARINGLY as field-report stringer for ONE call-in moment + ONE button at the end). Reframe: not "wacky friend," but a junior reporter on the phone from a scene.

**Length target:** 75–90 seconds. Pace tight. No filler.

---

## SEGMENT 1 — Cold Open (0:00–0:14)

**Visual:** C01 — wide 911 dispatch center, blue/cyan monitor glow, rows of consoles, busy operators (4s). Cut to C02 — close on a single headset on a console, screen with anonymized caller details (4s). Lower-third: "GOATnote Nightly · Special Report".

BRIAN (V.O.):
> Every night, in rooms most people never see, a question gets asked thousands of times. *(beat)* How fast can help arrive.

CUT — Lower-third updates: "PRISM42 · solo developer build".

BRIAN (V.O.):
> This week, one developer cut the time it takes a voice agent to start answering that question — by ninety-one percent.

---

## SEGMENT 2 — Field Stringer Cold (0:14–0:23)

**Visual:** C03 — ambulance speeding through dark wet city street, light bar strobing red and blue. Lower-third: "FIELD — REPORTING IN".

CHARLIE (V.O., over phone-line filter):
> Brian — picking up a feed from the dispatch desk now — the prior pipeline was a hosted API, latency p95 sixteen-fifty-five milliseconds — they're running a local stack tonight —

BRIAN (V.O., calm, dry):
> Stay with that.

---

## SEGMENT 3 — Hardware (0:23–0:42)

**Visual chain:**
- C04 — EMT prepping equipment in back of ambulance, hands only (5s)
- B02 — server racks glowing (5s)
- B01 — GPU silicon die macro push-in (5s)
- B03 — whiteboard with attention-mechanism math (4s)

BRIAN (V.O.):
> The build: a self-hosted Blackwell-class GPU pod. Caddy auto-TLS. Parakeet on port nine-one-hundred for speech recognition. Fish Speech on nine-two-hundred for synthesis. The model: Nemotron Nano three, on vLLM zero-point-twenty.

BRIAN (V.O., beat, drier):
> Not everything held. Three things broke before anything worked. macOS ships no `timeout` binary, which silently broke a session-start hook for two days. An environment file with unquoted multi-line JSON took down a shell. And one performance claim — about a CUDA toolchain mismatch — was retracted under pressure. It was, in fact, broken at runtime.

---

## SEGMENT 4 — Engineering Breaking News (0:42–1:02)

**Visual chain:**
- C05 — police patrol car at scene, wet asphalt, lights (4s)
- C06 — fire engine at scene, water spraying through strobe (4s)
- C07 — dispatcher speaking calmly into headset, response timer on screen (5s)
- B04 — red gradient plate (6s) — composite "1655 ms" struck through, "44 ms" pushed in

BRIAN (V.O.):
> First boot of the local stack: the NVFP4 GEMM crashed on the GPU. They installed CUDA thirteen nvcc. They installed flashinfer-cubin. They rebuilt vLLM with native sm one-oh-three. The five-gate strict performance gate —

BRIAN (V.O., beat):
> — passed. Time-to-first-token, p95 — forty-four milliseconds. Down from sixteen-fifty-five.

CHARLIE (V.O., over phone):
> Brian — that's the latency of a well-rested human.

---

## SEGMENT 5 — Closer (1:02–1:18)

**Visual:** C08 — city skyline at night, distant sirens, fog (4s). Cut to C09 — dispatch center at dawn, lights still on, single console (5s). Slow fade to end card. Lower-third: "GOATnote Nightly · AIFF 2026".

BRIAN (V.O.):
> Five days. One developer. A purpose-built GPU pod, three things that broke on the way to a number that didn't, and a voice agent that now answers in forty-four milliseconds.

BRIAN (V.O., beat):
> The room never sleeps. Now neither does the model.

CHARLIE (V.O., off, simple):
> Back to you, Brian.

---

## Voice direction

- **BRIAN**: stability 60, similarity 75, style 10 — pull back the style to land more sober than the v1 satirical read. Brokaw cadence — let clauses finish.
- **CHARLIE**: stability 45, similarity 80, style 50, with a high-pass + 3% packet-loss artifact in DaVinci to sell the phone-line treatment. Reads should be hurried but never panicked.

## Music bed direction

CC0 newsroom underscore, 95–105 BPM, ducks −12 dB under VO, drops out entirely 0:42–1:02 (the silence carries the 44ms reveal), re-enters at the closer at −18 dB. Single sustained low brass on the end card.

## Honesty audit (preserved from v1)

Three "stuff broke" beats included in Segment 3:
1. macOS missing `timeout` binary
2. `.env` malformed JSON
3. Retracted "negligible perf cost" CUDA-toolchain claim

NVFP4 GEMM crash beat in Segment 4.

## Cuts from v1

- Segment 2 (compliance/disclosure) — cut entirely. Not necessary. Avoids vendor-identification risk.
- Segment 3 (kernel lab field report) — folded into Segment 3 hardware as one line about Nemotron + vLLM.
- Character names "Ken" / "Fizzlepuff" — dropped. Voices are now BRIAN (narrator) and CHARLIE (field stringer), playing themselves.
