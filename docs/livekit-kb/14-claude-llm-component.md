---
title: Claude LLM component — TTFT, caching, and the ElevenLabs gap
date: 2026-04-24
scope: Voice-loop LLM hop only. STT / TTS covered in 04, 09.
status: deep-dive; actions below not yet applied.
---

# 14 — Claude LLM component (Sonnet 4.6 + Opus 4.7)

## Current state

- Worker: `llm=AnthropicLLM(model="claude-sonnet-4-6")` (`worker.py:242`). No caching kwarg.
- System prompt: ~1,200 tokens, well-bounded, no tools (`orchestrator.py:28-171`).
- Plugin: `livekit-plugins-anthropic 1.5.6`.
- `t_llm_proxy_ms`: **mean 9,857 / p50 8,456 / p99 15,367** (`09-b300-voice-bench.md`). Bench header says model was `claude-opus-4-7`, adaptive thinking ON (`09-b300-voice-bench.md:35`).

**The 9.9 s proxy was Opus 4.7 with adaptive thinking — not the Sonnet 4.6 pinned in repo.** Bench and repo disagree. Action 0: `grep model= /opt/prism42/agents/livekit/worker.py`, re-bench.

## Plugin streaming (verified against main-branch `llm.py`)

- **Streaming is real.** `messages.create(..., stream=True)`; every `text_delta` yields a `ChatChunk` immediately — feeds `tts_node` preemptively, no buffering.
- **Full history every turn.** `chat_ctx.to_provider_format(format="anthropic")` serializes the whole session. No sliding window.
- **`caching="ephemeral"` supported but OFF by default.** `__init__` accepts `caching: Literal["ephemeral"]`; when set, stamps `cache_control={"type":"ephemeral"}` on last system block + last tool + last user/assistant messages. Our constructor omits it → **zero cache hits, 1,200 system tokens re-processed every turn.**

## TTFT numbers (public)

- Sonnet 4.6 non-reasoning, short prompt: **500-800 ms TTFT**, "on par with Haiku 4.5" thinking-off ([cookbook](https://platform.claude.com/cookbook/third-party-elevenlabs-low-latency-stt-claude-tts); [Hendel](https://x.com/SkyIslandAI/status/2024500667587641724)).
- Sonnet 4.6 adaptive max: 126.9 s ([AA](https://artificialanalysis.ai/models/claude-sonnet-4-6-adaptive/providers)).
- Opus 4.7 non-reasoning high: **1.75 s TTFT** ([AA](https://artificialanalysis.ai/models/claude-opus-4-7-non-reasoning)).
- Opus 4.7 adaptive max: 10-14 s ([AA](https://artificialanalysis.ai/models/claude-opus-4-7/providers)).
- Prompt caching: TTFT **up to ~85%** faster on cached prefix ([caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).

Opus 4.7 + adaptive thinking easily pays 8-15 s — matches our 9.9 s proxy. Sonnet 4.6 thinking-off is in the Haiku-4.5 ~700 ms class.

## Can we match ElevenLabs ConvAI?

Anthropic's cookbook (Haiku 4.5): STT 0.54 s, LLM TTFT 0.71 s, TTS 0.39 s, first audio 1.48 s. Sonnet 4.6 thinking-off is in the same TTFT class. **Yes — raw Anthropic + `caching="ephemeral"` + Sonnet 4.6 is ConvAI-class on the LLM hop.** Our gap is plugin config, not the model.

## Ideal-state on B300 (projection)

Sonnet 4.6 + `caching="ephemeral"` + `max_tokens=80` + last-6-turn history, turn 2+: ~85% of system prompt cached → TTFT **0.5-0.9 s**, ~60 out tokens @ 80 tok/s ≈ 0.75 s, **LLM hop p50 ≈ 1.3-1.7 s** (5x, under the 1.5 s target).

## Top 3 levers

1. **Enable caching — one line.** `AnthropicLLM(model="claude-sonnet-4-6", caching="ephemeral")`. Plugin already stamps system + history correctly; 5-min TTL matches voice session. Expected: p50 8.5 s → ~1.5 s turn 2+.
2. **Confirm the pod is actually on Sonnet.** 9.9 s p50 matches Opus 4.7 adaptive-thinking TTFT too closely to be coincidence. Re-deploy the `claude-sonnet-4-6` worker; that alone is 4-5x before caching. Add `max_tokens=80`.
3. **Trim chat history to last 6 messages.** Only last ~3 exchanges are needed to maintain Flag B. Prune `chat_ctx` per turn and stamp `cache_control` on the first user turn so the persona pre-roll caches alongside the system prompt.

## Evidence trail

- `worker.py:242`, `orchestrator.py:28-171`, `09-b300-voice-bench.md:35,50`.
- `livekit/plugins/anthropic/llm.py` 1.5.6: `caching` kwarg + cache_control stamping + immediate `text_delta` → `ChatChunk` yield.
- [Whats-new 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7): 4.7 rejects `temperature`/`top_p`/`top_k`/`budget_tokens`; thinking display default `omitted` "appears as a long pause" — warning aimed at voice.
