# Voice-bottleneck synthesis — 5-team OODA, 2026-04-25

Integrator-written synthesis of T1 (Fish-fork excavation), T2 (coresidency
ablation), T3 (enterprise-comp hunt), T4 (NVIDIA Riva/NIM patterns), T5
(LLM tail forensics). All five teams ran in parallel against the post-Phase-E
DEGRADED state on the B300 pod.

## TL;DR

Team E's measured `publish_end_to_first_returned_audio_ms` p95 = 4510 ms
**conflates four independent failures** that look like one big number:

1. **Voice attest is currently broken at the LLM-output layer.** Every turn
   produced empty assistant content because Nemotron's nano_v3 reasoning-parser
   sends initial tokens to `delta.reasoning_content`, and the model spent the
   1024-token budget inside `<think>` without ever emitting `delta.content`.
   Fish only ever synthesized filler/preroll text. Engine PASS was real at the
   `200 OK` level, but the replies the harness "captured" were never real
   model replies.
2. **Worker orchestration adds an 850 ms median pad** to first-token-latency
   on 4/10 turns by waiting for preroll TTS to drain before AgentSession can
   fire `speech_created`. The fix is already wired in `worker.py` but not
   checked.
3. **CUDA stream serialization between Fish + vLLM** degrades Fish's RTF +95%
   under load. Fish itself isn't the problem — its standalone TTFB at the HTTP
   layer is **3.4 ms**. The "TTFB p95 = 2627 ms" Team E reported was
   end-to-end render time of the FULL audio under contention, not first-byte
   time.
4. **Fish-eager forces SDPBackend.MATH** in its slow-AR loop and yields one
   chunk per text-batch. SGLang-Omni's fork of the same model hits RTF 0.34 /
   TTFA 140 ms on H200 — proves the floor is software, not hardware.

The five teams converge on **5 ranked surgical fixes**, none of which require
swapping TTS provider:

| Rank | Fix | File | Predicted impact | Risk | Source |
|---|---|---|---|---|---|
| **1** | `enable_thinking=False` extra_body on OpenAILLM | `worker.py:339` | Unbroken voice — currently every turn is silent at the model layer | S | T5 + Nemotron model card |
| **2** | Gate preroll-emit on `caller_spoke.is_set()` OR enable `interruption_detection` | `worker.py:672-679` | llm_first_token p95: 2246 → ~150 ms | S | T5 forensic |
| **3** | Enable nvidia-cuda-mps-control with Fish HIGH / vLLM DEFAULT | pod systemd | RTF stable across load (kills the +95% scheduling penalty) | M | T2 ablation + T4 NVIDIA |
| **4** | Fish patch: `SDPBackend.MATH` → `SDPBackend.FLASH_ATTENTION` + drop dense causal mask | `vendor/fish-speech/.../inference.py:210` | TTFB at HTTP: 3.4 ms (already fast); RTF baseline: 1.97 → ~0.6 | M | T1 + SGLang-Omni |
| **5** | Pipecat-style speculative speech: sentence-boundary emission, `first_segment_max_tokens: 24` | `worker.py` orchestrator | Perceived V2V 500-700 ms even when component latency is higher | M | T4 + Pipecat ref |

Composing fixes 1+2+3+4 predicts: **e2e p95 from 4510 ms → ~600-1200 ms**,
all open-source, no provider swap, mainline-safe.

Cartesia / Magpie / Sesame swaps move to FALLBACK status — only needed if
fixes 1-5 don't hit the target.

---

## Detailed convergence

### Fish layer

T1 found the smoking gun: `vendor/fish-speech/fish_speech/models/text2semantic/inference.py:210`
forces `SDPBackend.MATH` for every AR token decode. SGLang-Omni's fork of
the same S2-Pro model hits RTF 0.34 / TTFA 140 ms on H200. We're at RTF 1.97
alone / 3.83 under load. The 5-10× gap is software.

T2 confirmed: Fish standalone TTFB at the HTTP layer is **3.4 ms p95** —
the 2627 ms Team E reported is full-audio-render time under contention, not
first-byte. Misnamed metric.

T2 also identified the contention class: **CUDA stream serialization**, not
HBM bandwidth (24-34% util) or compute saturation (98%) or thermal throttle
(pviol=0). Round-robin context switch between Fish CUDA context and vLLM CUDA
context. Fingerprint: SM% rises +5pp, mem util DROPS 33→24%, power DROPS
530→463W under contention.

T1's smoking-gun fix (FlashAttention + drop dense mask) is upstreamable
under FA Research License §IV(v) royalty-free feedback. Worth filing.

### Co-residency layer

T2 + T4 both point at NVIDIA CUDA MPS as the sanctioned answer. T4 cites
B300-specific MLOPart support (2 partitions, ~80 SMs + ~128 GB HBM3e each,
36% latency improvement, 2,350 GB/s peer-to-peer same-GPU bandwidth).

**Caveat from T4**: NVIDIA's own canonical Nemotron Voice Agent Blueprint
uses **4 separate H100s, not co-residency**. Read this as a signal that
NVIDIA does not believe TTS+LLM+STT same-GPU is the production-best answer
for sub-500 ms V2V. We're choosing co-residency because we have one B300,
not because it's optimal. MPS gets us close, but per-pod-per-component
scaling gets us closer if we ever go production.

### LLM layer

T5 ruled out Team R's top 3 hypotheses (preemptive double-fire, reasoning
padding direct cost, CUDA-graph JIT) and surfaced **Cause D**: preroll-TTS
overlap blocking AgentSession's `speech_created` firing. The 4 worst turns
all had VAD-EOU inside the preroll window. Worker.log shows
`WARNING livekit.agents interruption_detection is disabled` per session.

T5 also confirmed the **enable_thinking=False ship-blocker** that's
implicit in T4's expert-wiring research. Team E's Fix 2 raised
max_completion_tokens to 1024 to give the model room to finish thinking,
but every turn STILL produced empty `delta.content` — the model uses the
thinking budget without emitting reply tokens at all. This is voice
attest's silent kill switch. Setting `chat_template_kwargs.enable_thinking=False`
per request is the documented Nemotron way to disable the think-region
generation entirely.

### Industry-comp layer

T3 anchored where we sit:
- Industry-best published TTS TTFB: Cartesia 40-90 ms, Rime 40 ms p90, ElevenLabs 75 ms.
- Industry-best published e2e p95: Twilio ConversationRelay 713 ms,
  Cerebrium ~500 ms (vendor-internal claims).
- Hamming's industry-wide e2e p95 band across 4M+ calls: 4.3-5.4 s. Our
  4510 ms is INSIDE that band.
- 911 incumbents (Carbyne, Prepared, RapidSOS, Motorola/Hyper) **do not
  publish voice-AI latency p50/p95**. Capability claims only. No benchmark
  to chase.

T4 added NVIDIA's own number: Magpie TTS Multilingual on B200 = 55.1 ms
TTFB at 1 stream. Plugin (`livekit-plugins-nvidia-tts`) does not exist —
integration cost is real if we go that path.

### Pattern T4 surfaced that nobody else did

**Pipecat speculative speech**: buffered LLM with sentence-boundary
emission + `first_segment_max_tokens: 24` cap on the first LLM emission.
Pipecat's `nemotron-january-2026` reference hits V2V 500-700 ms with TTS
first audio at ~370 ms **even when component-level latency is higher**.
This masks TTS bottlenecks at the orchestrator level. Worth retrofitting
INDEPENDENTLY of fixes 3+4 above, since it composes.

---

## License situation (T1 flagged)

Fish Audio Research License (FARL), not BSD-3 as previously assumed.
Section III: hosted product surfaces require a commercial license. For our
hackathon-demo / public prism42 path, options are:

- **Stay open and switch TTS for any public surface.** Use Cartesia (or
  Magpie if we can build the plugin) for `/prism42/livekit`. Keep Fish
  internal only.
- **Contact fishaudio for commercial terms.** Multi-week, doesn't help the
  Sunday deadline.
- **Stay on Fish for the engine demo, document the license boundary.**
  Risk: Hackathon judges may flag the license posture.

The T1 patches we'd file upstream are safe under FARL §IV(v) royalty-free
feedback regardless.

---

## Recommended OODA cycle 1 (next 4 hours)

Compose fixes 1+2 (worker-side surgical, no pod restart needed beyond
worker), then re-bench with the same 10-prompt synthetic harness. Decide on
fix 3 (MPS) based on whether the new e2e p95 hits ≤ 1500 ms target.

Cycle 2 (next day): Fish patches in vendor/fish-speech/, internal bench
against the patched server, decide on upstream PR.

Cycle 3 (post-deadline): Pipecat speculative speech retrofit and / or
Cartesia plug-in for the public surface.

## Sources

- T1: `findings/voice/fish-fork-analysis/profile.md` + `vendor/fish-speech/`
- T2: `findings/voice/coresidency/ablation.json` + `summary.md` + dmon logs
- T3: `findings/voice/enterprise-comp.md`
- T4: `findings/voice/nvidia-tts-patterns.md`
- T5: `findings/voice/llm-tail-causes.md`
- Underlying Team E run: `findings/b300_bench/e2e_voice/20260425T113808Z/`
- Earlier Team N expert-wiring: `findings/b300_bench/nvidia-research/expert-wiring.md`
- Earlier Team R anticipator: `findings/b300_bench/e2e_voice-anticipator/contingencies.md`
