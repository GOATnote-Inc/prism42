# Sources — cycle-2h identity + tone research, 2026-04-25

All retrieval dates `2026-04-25` unless otherwise stated. Citations
referenced from `research.md` and `prism42_recommendations.md` by
`[Sn]`. Numbering starts at 101 to avoid collision with the existing
`findings/voice/best_in_class_2026-04-25/sources.md` (which uses
[S1]-[S68]). Cross-references to that document are marked as
`[Sn best_in_class]`.

## Axis A — Industry canon + first-utterance patterns

- [S101] NENA Standard for 9-1-1 Call Processing, NENA-STA-020.1-2020 (combines 56-001, 56-005, 56-006, 56-501) — `https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/nena-sta-020.1-2020_911_call.pdf` — full PDF text retrieved 2026-04-25
- [S102] NENA 56-005.1 (archived 2020 predecessor; agency-non-identification recommendation) — `https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards-archived/nena_56-005.1_archived_20200.pdf` — referenced via search snippet 2026-04-25
- [S103] APCO International standards — `https://www.apcointl.org/services/standards/find-standards/` — 2026-04-25
- [S104] Massachusetts Silent 911 Call Procedure — referenced via Snopes fact-check + Falmouth-MA / Seekonk-MA government pages — 2026-04-25
- [S105] AEDR Journal — "The Four-Second Rule for Identifying the Active Silent 911 Caller" — `https://www.aedrjournal.org/the-four-second-rule-for-identifying-the-active-silent-911-caller` — 2026-04-25
- [S106] MPDS Case Entry first question — search consensus citation; canonical Priority Dispatch protocol — 2026-04-25
- [S107] 988 Lifeline What to Expect — `https://988lifeline.org/get-help/what-to-expect/` — 2026-04-25
- [S108] 988 Lifeline FAQ on counselor training — `https://988lifeline.org/faq/about-us/what-training-does-the-988-lifeline-provide-network-crisis-counselors/` — 2026-04-25
- [S109] Crisis Text Line FAQ + volunteer training — `https://www.crisistextline.org/about-us/faq/` and `https://www.crisistextline.org/volunteer/` — 2026-04-25
- [S110] Aurelian Ava product page — `https://www.aurelian.com/ava` — 2026-04-25
- [S111] Aurelian — Snohomish County Cora launch — `https://www.businesswire.com/news/home/20251216814691/en/Aurelian-Launches-Cora-an-AI-Copilot-for-911-Call-Takers-with-Snohomish-County-911` — 2026-04-25
- [S112] Aurelian MACC 911 case study — `https://www.aurelian.com/studies/macc-911` — 2026-04-25
- [S113] Spectrum News Akron AI 911 deployment — `https://spectrumnews1.com/oh/columbus/news/2025/12/22/new-ai-system-takes-akron-s-non-emergency-calls-` — 2026-04-25
- [S114] Volusia County Sheriff's Office — VSO deploys Ava — `https://www.volusiasheriff.gov/news/volusia-county-sheriff/non-emergency-calls-now-getting-assist-from-a-i-ava.stml` — 2026-04-25
- [S115] Hoodline — Winter Garden may let Ava take 911 — `https://hoodline.com/2026/02/winter-garden-may-let-ava-take-the-911-phones/` — 2026-04-25
- [S116] CallHyper — `https://www.callhyper.com/` — 2026-04-25
- [S117] Prepared 911 — non-emergency triage AI — `https://www.prepared911.com/` and `https://www.prepared911.com/blog/transforming-non-emergency-call-handling-three-key-takeaways` — 2026-04-25
- [S118] LiveKit Documentation — Agent speech and audio — `https://docs.livekit.io/agents/build/audio/` — 2026-04-25 (canonical session.say + cached TTS pattern)
- [S119] LiveKit Agents repo — basic_agent.py (on_enter + generate_reply pattern) — `https://github.com/livekit/agents/blob/main/examples/voice_agents/basic_agent.py` — 2026-04-25
- [S120] LiveKit Documentation — Agents telephony integration — `https://docs.livekit.io/frontends/telephony/agents/` — 2026-04-25
- [S121] Pipecat-AI examples repo — `https://github.com/pipecat-ai/pipecat-examples` — 2026-04-25
- [S122] Pipecat Pipeline & Frame Processing docs — `https://docs.pipecat.ai/guides/learn/pipeline` — 2026-04-25 (TTSSpeakFrame + queue_frames canonical)
- [S123] Pipecat Issue #1787 — TTSSpeakFrame cancellation behavior — `https://github.com/pipecat-ai/pipecat/issues/1787` — 2026-04-25
- [S124] Pipecat Issue #3459 — TTSSpeakFrame text in LLM context — `https://github.com/pipecat-ai/pipecat/issues/3459` — 2026-04-25
- [S125] Kwindla (Pipecat creator) Twitter — TTSSpeakFrame canonical pattern — `https://x.com/kwindla/status/1939800741155414236` — referenced via search snippet 2026-04-25

## Axis B — Voice agent prompt-engineering canon

- [S126] OpenAI Cookbook — Realtime Prompting Guide — `https://developers.openai.com/cookbook/examples/realtime_prompting_guide` — 2026-04-25 (canonical Personality & Tone section example)
- [S127] Vapi Voice AI Prompting Guide — `https://docs.vapi.ai/prompting-guide` — 2026-04-25
- [S128] Avahi healthcare voice agent prompting writeup — `https://avahi.ai/blog/why-ai-voice-agents-in-telehealth-are-essential-for-scalable-virtual-care/` — 2026-04-25 (healthcare first-utterance pattern)
- [S129] Hume EVI Prompting Guide — `https://dev.hume.ai/docs/speech-to-speech-evi/guides/prompting` — 2026-04-25 (warm and nurturing prompt + few-shot)
- [S130] Decagon — Beyond latency: building a great voice agent — `https://decagon.ai/blog/beyond-latency-the-art-of-building-a-truly-great-voice-agent` — 2026-04-25 (warm-vs-professional + acknowledgement-before-action)
- [S131] Sesame CSM-1B GitHub — `https://github.com/SesameAILabs/csm` — 2026-04-25
- [S132] Govtech — Americans want more transparency with AI and 911 — `https://www.govtech.com/em/safety/study-finds-americans-want-more-transparency-with-ai-and-911` — 2026-04-25
- [S133] Cartesia Sonic-3 Volume/Speed/Emotion docs — `https://docs.cartesia.ai/build-with-cartesia/sonic-3/volume-speed-emotion` — 2026-04-25 (full 60+ emotion enumeration)
- [S134] Zowie — Why AI Voice Still Sounds Robotic — `https://getzowie.com/blog/why-ai-voice-still-sounds-robotic` — 2026-04-25
- [S135] Sesame Research — Crossing the Uncanny Valley of Conversational Voice — `https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice` — 2026-04-25 (4-component voice presence framework)

## Axis C — Voice-engineer playbook (2026)

- [S136] AssemblyAI 2026 voice-AI stack — `https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents` — 2026-04-25
- [S137] Hamming voice-AI latency reference (also S20 best_in_class) — `https://hamming.ai/resources/voice-ai-latency-whats-fast-whats-slow-how-to-fix-it` — 2026-04-25
- [S138] Cresta engineering — Engineering for real-time voice agent latency — `https://cresta.com/blog/engineering-for-real-time-voice-agent-latency` — 2026-04-25
- [S139] AssemblyAI 300 ms rule (also S18 best_in_class) — `https://www.assemblyai.com/blog/low-latency-voice-ai` — 2026-04-25
- [S140] LiveKit — Adaptive interruption handling — `https://livekit.com/blog/adaptive-interruption-handling` — 2026-04-25
- [S141] CallBotics — AI voice agent interruption handling guide 2026 — `https://callbotics.ai/blog/ai-voice-agent-interruption-handling` — 2026-04-25

## Axis D — Crisis-line + PSAP dispatcher human baseline

- [S142] Priority Dispatch — Protocol 41 Caller in Crisis training — `https://prioritydispatch.net/en/blog/protocol-41-caller-in-crisis-training` — 2026-04-25
- [S143] IAED Journal — Year of Hope With Protocol 41 — `https://www.iaedjournal.org/a-year-of-hope-with-protocol-41` — 2026-04-25
- [S144] Police1 — George Thompson 5 universal truths of human interaction — `https://www.police1.com/communications/articles/the-5-universal-truths-of-human-interaction-IgN9IPGbHymPfIRB/` — 2026-04-25
- [S145] Mediate.com Quick Tip — Hostage Negotiator's Tone of Voice — `https://mediate.com/quick-tip-hostage-negotiators-tone-of-voice/` — referenced via search snippet (page 403 on direct fetch) 2026-04-25
- [S146] Police1 — Hostage negotiations psychological strategies — `https://www.police1.com/swat/articles/hostage-negotiations-psychological-strategies-for-resolving-crises-QHgRY29vtb38310m/` — 2026-04-25
- [S147] Psychology Today — 5 Core Skills of Hostage Negotiators — `https://www.psychologytoday.com/us/blog/beyond-words/201510/the-5-core-skills-of-hostage-negotiators` — 2026-04-25
- [S148] Kovacorp — A Guide for 911 Dispatchers to Handle Frightened Callers — `https://www.kovacorp.com/911-dispatchers-can-handle-frightened-callers` — 2026-04-25 (verbatim "I understand you're upset. It is okay. I am here to help.")
- [S149] ShuBee — Phrases dispatchers should never say — `https://www.shubee.com/articles/phrases-dispatchers-never-say-busy/` — 2026-04-25
- [S150] CleverDude — 10 Things You Should Never Say During a 911 Call — `https://www.cleverdude.com/content/10-things-you-should-never-say-during-a-911-call` — 2026-04-25 (caller side; useful inverse-mapping)
- [S151] American Heart Association T-CPR — `https://cpr.heart.org/en/resuscitation-science/telecommunicator-cpr/telecommunicator-cpr-recommendations-and-performance-measures` — 2026-04-25
- [S152] Verbal Judo Institute — `https://verbaljudo.com/911-dispatch-course/` — 2026-04-25
- [S153] PubMed — Persuasive communication training improves DA-CPR (Resuscitation 2024) — `https://pubmed.ncbi.nlm.nih.gov/38266768/` — 2026-04-25 (also S39 best_in_class)
- [S154] Convey911 — Essential Guide to Dispatch for 911 Best Practices 2026 — `https://www.convey911.com/blog/dispatch-for-911` — 2026-04-25
- [S155] CSG Justice Center — 911 Dispatch Call Processing Protocols — `https://csgjusticecenter.org/publications/911-dispatch-call-processing-protocols-key-tools-for-coordinating-effective-call-triage/` — 2026-04-25

## Provenance + retrieval notes

- All URLs above were retrieved 2026-04-25 via WebFetch / WebSearch
  unless otherwise marked. Where the page is paywalled or returned
  403 (notably [S145] Mediate.com), the citation is via a search-result
  snippet and tagged accordingly.
- The single most-load-bearing source ([S101] NENA-STA-020.1-2020) was
  retrieved as full PDF text and the §2.2.3 SHALL clause was confirmed
  verbatim. This is the authoritative anchor for Recommendation #1.
- LiveKit's "cache TTS for fixed greetings" guidance ([S118]) was
  triple-confirmed: official Agents docs page, basic_agent.py
  reference implementation ([S119]), and telephony quickstart
  ([S120]).
- Cross-vendor convergence on "Personality & Tone in prompt header"
  was confirmed across four independent vendors: OpenAI ([S126]),
  Vapi ([S127]), Hume ([S129]), Decagon ([S130]).
- "What dispatchers explicitly avoid" was confirmed across at least
  four independent dispatcher-training sources ([S148][S149][S150]
  [S154]).
- The "few-shot prompting shapes voice/tone" pattern was confirmed
  across two independent vendors with direct measurement claims
  (Hume [S129] "warm and nurturing makes voice sound soothing";
  OpenAI [S126] "examples help establish that tone").

## What we did NOT find (gaps in evidence)

- **Public Aurelian Ava emergency-line greeting transcript.** Ava
  is non-emergency only; the exact NENA-§2.2.3-applicable line is not
  what they ship. Aurelian's product page, MACC case study, and
  three local-government press releases all describe capability,
  not the verbatim opening utterance. **This is the gap that lets
  prism42 set its own standard.**
- **Public IAED Protocol 41 specific de-escalation phrases.** The
  $99 paywalled training contains them. Available public material
  is limited to the verbatim "asks rather than tells" framing and
  the "intending vs threatening" word-choice example.
- **Empirical 911 voice-AI MOS / warmth benchmark.** No 2026
  competitor (Aurelian, Carbyne, Prepared 911, RapidSOS, Motorola)
  publishes a voice naturalness MOS or warmth Likert. Internal bar
  is the only bar.
- **Mediate.com Quick Tip on Hostage Negotiator Tone** — direct fetch
  returned 403; cross-confirmed via Police1 [S146] and Psychology
  Today [S147]. The slow-cadence-models-the-caller principle is
  triple-sourced; the Mediate.com source itself is referenced
  conditionally.
