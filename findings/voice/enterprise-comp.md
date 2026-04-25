# Voice-AI production stacks competitive map (2026-04)

Generated: 2026-04-25 by competitive-architecture research team.
Scope: Tier-1 voice-AI infra, Tier-2 telephony stacks, Tier-3 911-services.
Method: WebSearch + WebFetch on each named target, prefer vendor-published or independent-bench numbers, every claim tagged.

## Bottom line (must answer)

We measure today: **TTS TTFB p95 = 2627 ms, e2e p95 = 4510 ms.**

The published-best peers we can verify:

- **TTS TTFB:** Cartesia Sonic-3 Turbo at **~40 ms model-only TTFB** via state-space-model architecture on undisclosed hardware [1, 2] (verified-public, vendor; SSM is real). ElevenLabs Flash v2.5 publishes "75 ms model latency + network" [12]. Rime Mist v3 publishes "~40 ms p90" on L40S/RTX-6000 [11].
- **End-to-end voice-to-voice:** **Twilio ConversationRelay p95 = 713 ms, p50 = 491 ms** (vendor-published, internal benchmarks across mixed providers, 2025-11-17) [3] — closest verifiable peer to a "true e2e p95" claim. AssemblyAI's Vapi build reaches **~465 ms web e2e** but only as a single-shot demo, not p95 [4]. Cerebrium documents **~500 ms voice-to-voice** with self-hosted Llama-3.1-8b-fp8 + Deepgram + Rime stack on 1xH100 [5] (vendor-published, single-config).

**Gap to close to be peer:**

| Metric | Us today | Best public peer | Gap |
|---|---|---|---|
| TTS TTFB p95 | 2627 ms | Cartesia Sonic-3 ~90 ms model TTFB / ElevenLabs ~75 ms / Rime ~40 ms p90 | **~25-30x** (~2.5 sec to shave) |
| E2E p95 | 4510 ms | Twilio ConversationRelay 713 ms p95 (mixed provider) / Hamming industry p95 4.3-5.4 s [6] | **~6x to peer, ~at industry-median p95 already** |

We are sitting at roughly the industry-median p95 for voice agents (Hamming 4.3-5.4 s p95 across 4M+ calls [6]), but the published-best providers are running an order of magnitude faster on the TTS leg specifically. The TTS leg is where the biggest, cheapest gain lives.

**Architectural patterns we are missing (one-phrase summary, ranked):**

1. **State-space-model TTS** — non-autoregressive TTS so first audio chunk emits before the text is fully consumed. Cartesia ships this in Sonic-3 [1, 2].
2. **Co-located STT+TTS+LLM in the telephony PoP** — Synthflow, Telnyx-LiveKit, and Bland all do this; eliminates 100-600 ms of cross-region hops [7, 8, 13].
3. **Multi-deployment fastest-of-N LLM routing with live-data fallback** — Vapi runs across 40+ Azure-OpenAI endpoints, exploit/explore selection, dynamic cancel-and-reroute on stddev breach. Cut their p95 by >1000 ms [9].
4. **Speech-to-speech end-to-end model (skip text intermediate)** — Sesame CSM-8B (8.3B backbone + 300M decoder, Apache-2.0) [10, 14]. OpenAI Realtime is the closed equivalent.
5. **WebSocket + token-by-token TTS streaming** — instead of HTTP request-per-utterance. PlayHT 3.0-mini, ElevenLabs Flash, Rime, Cartesia all do this; pure-HTTP stacks pay 100-300 ms reconnect cost per turn.

## Per-target table

| Company | TTS engine | STT | LLM | Hardware | TTFB / model latency | E2E claim | Tag | Source URL + date |
|---|---|---|---|---|---|---|---|---|
| Cartesia (Sonic-3) | Own SSM-based Sonic-3, two variants (Sonic-3 + Sonic-3 Turbo) | n/a (TTS only) | n/a | Undisclosed; available on AWS SageMaker JumpStart Feb 2026 | **40 ms Turbo, ~90 ms standard** model-only TTFB (vendor + customer quotes) | n/a | verified-public (vendor docs) | docs.cartesia.ai/build-with-cartesia/tts-models/latest, sonic-3 versions 2025-10-27 + 2026-01-12 [1, 2] |
| Sesame (CSM) | Own Conversational Speech Model — Llama-backbone + Mimi codec decoder | n/a | n/a (single-stage speech-to-speech) | CUDA GPU; Llama-3.2-1B + CSM-1B/8B from HF | "low-latency generation" — no explicit ms quoted | n/a | claimed-unverified for latency; verified-public for architecture + Apache-2.0 OSS | sesame.com/research/crossing_the_uncanny_valley_of_voice + github.com/SesameAILabs/csm [10, 14] |
| Bland AI | Own proprietary TTS | Own proprietary STT | Own proprietary inference | Optimized V100s, dedicated per customer | not published | "lower latency than 3rd-party-routed peers"; no ms | claimed-unverified (vendor self-reported, no measurements) | bland.ai homepage 2026 [15] |
| Synthflow | 3rd-party (multi-vendor) | 3rd-party | 3rd-party | Owned telephony + regional PoPs | not published as TTFB | **<100 ms latency** claim w/ in-house telephony, "average 400 ms" elsewhere on same site (contradicts) | claimed-unverified (marketing inconsistency) | synthflow.ai/blog/voice-ai-telephony-infrastructure 2026 [7] |
| Vapi | Multi-vendor (ElevenLabs, Cartesia, Deepgram routing) | Multi-vendor | Multi-vendor (40+ Azure-OpenAI deployments) | Cloud-routed | n/a | **p50 < 500 ms, p95 < 800 ms target** + actual: **>1000 ms p95 reduction** via routing; ~465 ms in best AssemblyAI demo (web), 965 ms+ telephony | verified-public (engineering blog + 3rd-party demo with components) | vapi.ai/blog/how-we-solved-latency-at-vapi + assemblyai.com/blog/how-to-build-lowest-latency-voice-agent-vapi 2025-07-14 [4, 9] |
| Retell AI | Multi-vendor TTS | Multi-vendor STT | GPT-4o + others | Cloud-routed, SIP trunking | n/a | **~600 ms latency** claim; 780 ms in cited bench | claimed-unverified (vendor-reported, no methodology link) | retellai.com 2026, openai.com/index/retell-ai [16] |
| PlayHT (Play 3.0 mini) | Own Play 3.0 mini | n/a | n/a | not disclosed | **143 ms mean TTFB**; 73 ms avg in independent Jambonz short-text bench | n/a | verified-public (vendor + 3rd-party Jambonz) | play.ht/news/introducing-play-3-0-mini + jambonz leaderboard [17, 18] |
| Rime AI (Mist v3) | Own Mist v3 | n/a | n/a | **L40S or RTX 6000** (vendor-specified) | **~40 ms TTFB p90** | n/a | verified-public (vendor blog 2026-04-06) | rime.ai/resources/introducing-mist-v3-enterprise-tts 2026-04-06 [11] |
| Deepgram (Aura-2) | Own Aura-2 | Deepgram Nova / Universal | n/a (uses external LLM) | Deepgram cloud GPU | **~90 ms TTFB steady-state, p95 < 200 ms** | n/a | verified-public (vendor + Coval 3rd-party referenced) | deepgram.com/learn/introducing-aura-2-enterprise-text-to-speech, /aura-2-leads-coval-real-time-tts-benchmarks [19, 20] |
| ElevenLabs (Flash v2.5) | Own Flash v2.5 | n/a (also has STT) | n/a | Upgraded GPUs (undisclosed model) | **75 ms model TTFB + app/network**, "50 ms model TTFB" claim post-upgrade | n/a | verified-public (vendor blog) | elevenlabs.io/blog/meet-flash, /text-to-speech-api-up-to-40-faster-globally [12] |
| Inworld TTS-1.5 | Own | n/a | n/a | not disclosed | **130-250 ms p90 TTFB**, Mini variant <120 ms p90 | n/a | verified-public (vendor + Artificial Analysis #1 ELO 1236) | inworld.ai/blog/introducing-inworld-tts-1-5, artificialanalysis.ai/text-to-speech [21, 22] |
| AsyncFlow | Own | n/a | n/a | "no high-tier GPU needed" | **166 ms median TTFB**, sub-200 ms p95 (independent bench), 11% faster than ElevenLabs at p95, 67% faster than Cartesia at p95 | n/a | verified-public (independent Async/Podcastle bench 2025-11-18) | async.com/blog/tts-latency-vs-quality-benchmark [23] |
| **Twilio ConversationRelay** | Plug-in (Amazon, Deepgram, ElevenLabs, Google) | Plug-in | Plug-in (any) | Twilio global media edge | n/a | **p50 491 ms, p95 713 ms** (e2e voice-to-voice; vendor-internal) | verified-public (vendor doc, dated 2025-11-17, w/ caveat "results may vary") | twilio.com/en-us/blog/developers/best-practices/guide-core-latency-ai-voice-agents [3] |
| LiveKit Agents | Plug-in | Plug-in | Plug-in | Customer-deployed | n/a | LiveKit-published target P90 < 3.5 s e2e, P99 < 5 s; 1.8 s typical (450 STT + 850 LLM + 500 TTS) | claimed-unverified for "1.8 s typical"; verified for the P90 target framing | livekit.com/blog/voice-agent-architecture-stt-llm-tts-pipelines-explained 2026 [24] |
| Telnyx-LiveKit | Plug-in (Telnyx-PoP-colocated GPU) | Plug-in | Plug-in | "Telnyx-owned GPU clusters at telephony PoP" | n/a | **<200 ms RTT** claim | claimed-unverified (vendor announcement, beta) | globenewswire 2026-04-06 [13] |
| Cerebrium reference build | Deepgram Aura / Rime Labs (~80 ms TTFB) | Deepgram (locally deployed: ~110 ms TTFB; via API: ~250 ms) | Llama-3.1-8b-fp8 (~400 ms TTFT on 1xH100), or 70b-fp8 on 2xH100 | **1xH100 for 8b, 2xH100 for 70b**; LiveKit WebRTC media transport | per-component measured | **~500 ms voice-to-voice e2e** (single-config self-host) | verified-public (vendor blog, public components) | cerebrium.ai/blog/deploying-a-global-scale-ai-voice-agent-with-500ms-latency [5] |
| Carbyne (Axon 911) | Cloud-native call handling — voice-to-voice translation referenced; specific TTS not disclosed | Multilingual STT integrated; specific not disclosed | Prepared's intelligence layer (LLM-driven) | "government-grade cloud", undisclosed | not published | not published as a system latency | opaque (no published stack ms numbers; capability claims only); verified for being acquired by Axon Nov 2025 + Metro WashCOG deployment | carbyne.com + axon.com/solutions/axon-911 + investor.axon.com 2025-11-04 [25, 26] |
| RapidSOS (HARMONY AI / UNITE) | n/a — they're a data/intelligence layer, not a voice synthesizer | Real-time transcription + 40+ language translation in UNITE | LLM-driven summaries + keyword alerts | not published | not published | not published as voice latency — they explicitly describe a data-overlay layer (transcribe / summarize / route) over an existing PSAP voice path | opaque on voice; verified-public on capability + scale (723M devices, 23,500 PSAPs, 500K+ emergencies/day) | rapidsos.com + prnewswire 2026-01-15 [27, 28] |
| Prepared 911 (now part of Axon 911) | n/a — same pattern as RapidSOS, intelligence layer | Real-time transcription + 40+ languages | Own AI for triage, summarization, key-detail extraction | not published | not published | "caller help in about a minute" (overall resolution, not voice-AI latency) | opaque (no published latency); verified-public for non-emergency triage product + Axon acquisition | prepared911.com/platform/non-emergency-triage 2026 [29] |
| Motorola Solutions (VESTA NXT + Assist + Hyper) | Not disclosed | Not disclosed | Agentic "Assist Agents" — handles non-emergency, escalates if context shifts | Not disclosed | Not published | Not published as voice latency | opaque (no published technical stack numbers); verified-public for acquisitions: RapidDeploy 2025-02, HyperYou 2026-04-09 | motorolasolutions.com/newsroom/press-releases/hyper-acquisition-and-new-agentic-assist-agents.html 2026-04-09 [30, 31] |

Note: independent Jambonz leaderboard (AWS us-east-1, vendor-agnostic) ranked PlayHT 73-92 ms TTFB short text vs ElevenLabs 532-906 ms — but Jambonz was using non-Flash ElevenLabs and likely older test (predates Flash v2.5) [18]. Treat ElevenLabs Flash v2.5 75-ms as the current vendor-current number, not Jambonz 532-906.

Note: Hamming "industry median across 4M+ calls" — p50 1.4-1.7 s, p90 3.3-3.8 s, p95 4.3-5.4 s, p99 8.4-15.3 s [6]. Our 4510 ms p95 sits inside Hamming's industry p95 band — not catastrophically behind, but the industry-best is shipping at <800 ms p95.

## Architectural patterns we are missing (top 5, ranked by gain estimate)

### 1. State-space-model (SSM) TTS — non-autoregressive first-byte
**What it is:** Traditional TTS is autoregressive (transformer): you wait for the model to consume more text before it emits the next audio token. SSMs (Cartesia's Sonic family is the production example) emit audio tokens in parallel against a sequential state, so the first audio chunk can stream before the input text is fully tokenized. This is structurally why Cartesia hits 40-90 ms TTFB on the standard variant and 40 ms on Turbo while autoregressive transformer-based TTS sits at 200-500 ms even when warm [1, 2, 19].
**Who uses it:** Cartesia (Sonic-3) is the load-bearing example. Rime Mist v3 doesn't disclose its architecture but achieves comparable 40 ms p90 — likely a related non-autoregressive design [11].
**How to retrofit:** We don't need to build an SSM ourselves. We swap our TTS provider for Cartesia or Rime. Effort: hours-to-days for the API swap; real time goes into voice-cloning + prompt re-engineering for tone parity. Expected gain on TTS TTFB p95: drop from 2627 ms to ~150-300 ms (10-15x), conditional on us not eating the gain back via network.

### 2. Co-located inference at the telephony PoP
**What it is:** Run STT, LLM, and TTS GPU inference inside the same network as the SIP trunk / WebRTC media server. The audio physically never leaves that PoP; it gets transcribed, reasoned over, and resynthesized within sub-ms intra-rack hops. Cross-region API calls cost 100-600 ms per round trip; co-location burns that to single-digit ms [5, 7, 13].
**Who uses it:** Synthflow ("in-house telephony PoPs, LATAM RTT 191 ms → 99 ms post-PoP-deploy" [7]); Telnyx-LiveKit (Apr 2026 launch, "audio never leaves the Telnyx network", sub-200 ms RTT claim [13]); Cerebrium ("inter-cluster routing reduces network latency to single-digit ms" [5]); Bland ("self-hosted infrastructure, edge delivery network" [15]). Vapi is explicitly NOT this — they fan out to 40+ Azure regions [9].
**How to retrofit:** Move our inference from cross-cloud calls (Anthropic API + ElevenLabs API + Deepgram API, each in different clouds) to a single co-located PoP. Two paths: (a) deploy on Telnyx-LiveKit beta (no infra work, vendor lock-in to Telnyx telephony), (b) self-host on Brev B300 with our STT+TTS+LLM all on one box and SIP terminating there. Path (b) matches what we've already chosen architecturally per the LiveKit pivot in our memory. Effort: large but already in flight. Expected gain on e2e p95: 500-1500 ms shave from network.

### 3. Multi-deployment fastest-of-N LLM routing
**What it is:** Vapi maintains 40+ Azure-OpenAI deployments and routes each LLM request to the currently-fastest one based on live observed latency, with continuous exploration to detect newly-fast endpoints. If a request exceeds historical stddev, it cancels and reroutes mid-flight. Result: p95 reduced by >1000 ms [9]. This is structurally different from "load balancing" — it's exploit/explore over latency distribution.
**Who uses it:** Vapi explicitly publishes this [9]. Likely Retell + Synthflow + Bland do similar internally but don't publish.
**How to retrofit:** This requires (a) >1 LLM endpoint (Anthropic + a fallback), (b) live latency tracking per endpoint, (c) a router that does cancel-and-reroute. Effort: medium — a Redis-backed latency log and a policy module. Expected gain: 500-1000 ms p95 reduction on the LLM leg specifically. NOTE: Anthropic publishes endpoint latency variance in regions but doesn't publish a fastest-of-N API; we'd build this ourselves.

### 4. Speech-to-speech end-to-end (no text intermediate)
**What it is:** Instead of audio → STT → text → LLM → text → TTS → audio, ship audio tokens through one model that generates audio tokens directly. Sesame's CSM does this with a Llama backbone + Mimi audio codec; OpenAI Realtime API is the closed-source production version. Eliminates two encoder/decoder hops + the LLM-text-to-TTS handoff [10, 14].
**Who uses it:** Sesame (Apache-2.0 OSS; 1B/3B/8B variants) [14]; OpenAI Realtime (closed); Google Gemini Live (closed). Importantly: Bland's "proprietary inference" likely is or will be a speech-to-speech architecture — they own all three models, which is the precondition.
**How to retrofit:** Heavy. Speech-to-speech requires either (a) using OpenAI Realtime (lose Anthropic), (b) self-hosting Sesame CSM-8B (Apache-2.0, but voice quality vs Sonic-3 is uncertain), (c) waiting for Anthropic to ship a Realtime equivalent. For our use case (911 emergency triage where we cannot lose Anthropic-grade reasoning), this is a research bet, not a near-term retrofit. Expected gain: 500-1500 ms e2e by collapsing two pipeline stages.

### 5. WebSocket token-streaming TTS instead of HTTP-per-utterance
**What it is:** Open one persistent WebSocket per call, stream LLM tokens into it as they generate, get audio chunks back as they're ready. Avoids HTTP-handshake-per-utterance (typically 100-300 ms TLS+TCP+HTTP/2 setup if the connection isn't pooled). Every leading TTS now supports this: PlayHT 3.0 mini explicitly added it as a launch feature [17]; ElevenLabs, Cartesia, Rime, Deepgram all support it [11, 12, 19].
**Who uses it:** Universal across the Tier-1 set (Cartesia, ElevenLabs, Deepgram, Rime, PlayHT, Inworld). If we're not on it, we're paying handshake cost per turn.
**How to retrofit:** Trivial for any modern TTS provider — flip an SDK flag. Effort: hours. Expected gain on TTS p95: 100-300 ms.

## Open-source pieces worth borrowing

| Repo | License | What to lift | What to leave |
|---|---|---|---|
| **github.com/SesameAILabs/csm** [14] | Apache-2.0 | The whole speech-to-speech architecture as a research backbone. CSM-1B is small enough to self-host; CSM-8B is the production-quality variant. HF integration in transformers 4.52.1+. | Don't use for production voice yet — open-sourced March 2025, no production-scale deployment data, watermarking logic is opinionated. Quality vs Cartesia/ElevenLabs is unproven. |
| **LiveKit Agents** (open-source) [24] | Apache-2.0 | The orchestration framework — STT/LLM/TTS plug-in pattern, WebRTC media server, barge-in handling, observability hooks. We're already using this per the memory pivot. | Their "homepage agent" reference build is a yardstick, not a production target. |
| **vLLM / SGLang / TensorRT-LLM** | Apache-2.0 / Apache-2.0 / NVIDIA | Self-host LLM inference at PoP for sub-400 ms TTFT on Llama-class models on 1xH100 (per Cerebrium [5]). Required if we want path (b) — own-PoP voice. | None, these are the standard. |
| **Kokoro 82M** TTS [22] | Apache-2.0 (referenced as cost-effective OSS option) | Cheap, surprisingly-strong-quality fallback TTS — useful as a backup-of-last-resort if our primary TTS provider has an outage. Cost: $0.70/M chars. | Quality is not Cartesia/Sonic-3 tier; don't use as primary for clinical-grade voice. |
| **Mimi audio codec** (Kyutai, used inside Sesame CSM) | Apache-2.0 | Audio tokenization at 12.5 Hz (~80 ms per token) — the "compression layer" that makes speech-to-speech tractable. Worth understanding even if we don't directly use it. | Standalone use is rare; it's bundled with CSM. |

## Sources

1. [Sonic 3 — Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest), retrieved 2026-04-25; lists model versions sonic-3-2025-10-27 and sonic-3-2026-01-12.
2. [Real-time TTS API with AI laughter and emotion | Cartesia Sonic-3](https://cartesia.ai/sonic), retrieved 2026-04-25; customer testimonial "ultra-low latency of 90ms" + claim "only product with model latency <100 ms".
3. [Core Latency in AI Voice Agents | Twilio](https://www.twilio.com/en-us/blog/developers/best-practices/guide-core-latency-ai-voice-agents), published 2025-11-17, retrieved 2026-04-25; p50 491 ms, p95 713 ms ConversationRelay e2e (vendor-internal benchmark).
4. [How to build the lowest latency voice agent in Vapi | AssemblyAI](https://www.assemblyai.com/blog/how-to-build-lowest-latency-voice-agent-vapi), published 2025-07-14, retrieved 2026-04-25; ~465 ms web e2e demo with AssemblyAI Universal-Streaming + Groq Llama-4 Maverick + ElevenLabs Flash v2.5.
5. [Deploying a global scale, AI voice agent with 500ms latency | Cerebrium](https://cerebrium.ai/blog/deploying-a-global-scale-ai-voice-agent-with-500ms-latency), retrieved 2026-04-25; full self-host stack with H100 + LiveKit.
6. [Voice Agent Evaluation Metrics | Hamming AI](https://hamming.ai/resources/voice-agent-evaluation-metrics-guide), retrieved 2026-04-25; industry p50/p90/p95/p99 across 4M+ calls.
7. [Why Synthflow Built Its Own Telephony — Voice AI](https://synthflow.ai/blog/voice-ai-telephony-infrastructure), retrieved 2026-04-25; LATAM PoP 191 ms → 99 ms RTT, "<100 ms" claim.
8. [The voice AI stack for building agents in 2026 | AssemblyAI](https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents), retrieved 2026-04-25.
9. [How we solved latency at Vapi](https://vapi.ai/blog/how-we-solved-latency-at-vapi), retrieved 2026-04-25; 40+ Azure deployments, fastest-of-N routing, p95 cut by >1000 ms.
10. [Crossing the uncanny valley of conversational voice | Sesame](https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice), retrieved 2026-04-25; CSM 1B/3B/8B variants, backbone+decoder split.
11. [Introducing Mist v3: TTS Built for Enterprise Scale | Rime](https://rime.ai/resources/introducing-mist-v3-enterprise-tts), published 2026-04-06, retrieved 2026-04-25; ~40 ms p90 TTFB on L40S/RTX-6000.
12. [Meet Flash | ElevenLabs](https://elevenlabs.io/blog/meet-flash), retrieved 2026-04-25; "75 ms + application & network latency" claim. Plus [Text to Speech API Up To 40% Faster](https://elevenlabs.io/blog/text-to-speech-api-up-to-40-faster-globally) — claims 50 ms model-TTFB post-upgrade.
13. [Telnyx Launches LiveKit on Telnyx](https://www.globenewswire.com/news-release/2026/04/06/3268608/0/en/Telnyx-Launches-LiveKit-on-Telnyx-for-Deploying-Voice-AI-Agents-with-Lower-Cost-and-Ultra-Low-Latency.html), published 2026-04-06, retrieved 2026-04-25; sub-200 ms RTT claim.
14. [github.com/SesameAILabs/csm](https://github.com/SesameAILabs/csm), retrieved 2026-04-25; Apache-2.0, Llama-backbone + Mimi codec decoder, HF transformers 4.52.1+.
15. [Bland AI homepage](https://www.bland.ai/), retrieved 2026-04-25; V100s, proprietary STT+LLM+TTS, no published ms.
16. [Retell AI](https://www.retellai.com), retrieved 2026-04-25; ~600 ms latency claim, no methodology link.
17. [Introducing Play 3.0 Mini | PlayHT](https://play.ht/news/introducing-play-3-0-mini/), retrieved 2026-04-25; 143 ms mean TTFB, WebSocket support added.
18. [Comparing speech latency of leading text-to-speech vendors | Jambonz](https://blog.jambonz.org/text-to-speech-latency-the-jambonz-leaderboard), retrieved 2026-04-25; AWS us-east-1, vendor-agnostic; PlayHT 73-92 ms vs ElevenLabs 532-906 ms (caveat: pre-Flash-v2.5 ElevenLabs).
19. [Introducing Aura-2: Enterprise-Grade Text-to-Speech | Deepgram](https://deepgram.com/learn/introducing-aura-2-enterprise-text-to-speech), retrieved 2026-04-25; ~90 ms steady-state TTFB, p95 <200 ms.
20. [Aura-2 Leads Coval's Real-Time TTS Benchmarks](https://deepgram.com/learn/aura-2-leads-coval-real-time-tts-benchmarks), retrieved 2026-04-25.
21. [Inworld TTS-1.5 launch](https://inworld.ai/blog/introducing-inworld-tts-1-5), retrieved 2026-04-25; <120 ms p90 TTFB Mini, ~200 ms Max.
22. [Artificial Analysis TTS Leaderboard](https://artificialanalysis.ai/text-to-speech), retrieved 2026-04-25; Inworld TTS-1.5 Max ELO 1236 #1, ElevenLabs v3 ELO 1179 #2.
23. [Streaming TTS benchmark: Async vs ElevenLabs vs Cartesia | Async](https://async.com/blog/tts-latency-vs-quality-benchmark/), published 2025-11-18, last modified 2026-02-19, retrieved 2026-04-25; AsyncFlow 166 ms median TTFB, 11% faster than ElevenLabs at p95, 67% faster than Cartesia at p95. Caveat: Async is the publisher of this comparison and benchmarks itself.
24. [Voice Agent Architecture: STT, LLM, and TTS Pipelines | LiveKit](https://livekit.com/blog/voice-agent-architecture-stt-llm-tts-pipelines-explained), retrieved 2026-04-25.
25. [Cloud Native Emergency Communication Response Platform | Carbyne](https://carbyne.com/), retrieved 2026-04-25.
26. [Axon to Acquire Carbyne — Investor relations](https://investor.axon.com/2025-11-04-Axon-to-Acquire-Carbyne,-Uniting-Cloud-Infrastructure-and-AI-to-Redefine-the-911-Experience), published 2025-11-04, retrieved 2026-04-25.
27. [RapidSOS — Mission-Critical Intelligence](https://rapidsos.com/), retrieved 2026-04-25.
28. [RapidSOS Introduces Real-Time Interoperability with HARMONY AI](https://www.prnewswire.com/news-releases/rapidsos-introduces-real-time-interoperability-with-harmony-ai-to-automate-emergency-coordination-302661687.html), published 2026-01-15, retrieved 2026-04-25.
29. [AI-powered Call Triage for 911 | Prepared](https://www.prepared911.com/platform/non-emergency-triage), retrieved 2026-04-25.
30. [Motorola Solutions acquires RapidDeploy](https://www.motorolasolutions.com/newsroom/press-releases/motorola-solutions-acquires-rapiddeploy.html), published 2025-02-20, retrieved 2026-04-25.
31. [Motorola Solutions Bolsters 911 Capacity — Hyper acquisition + Assist Agents](https://www.motorolasolutions.com/newsroom/press-releases/hyper-acquisition-and-new-agentic-assist-agents.html), published 2026-04-09, retrieved 2026-04-25.
