# Cycle-2e orchestration patch — ready-to-apply plan

Scout output, read-only. Translates Team P's `findings/voice/cycle-2e-pipecat/{pattern.md, worker-target-locations.md}` into a unified-diff sketch, instrumentation contract, and PASS/FAIL signatures the executor can apply without re-deriving anything. **No code is written here.** All file:line references are verified against the current tree at `/Users/kiteboard/prism42/agents/livekit/{worker.py,orchestrator.py}` (heads checked 2026-04-25).

---

## 0. One-line summary

Add `BufferedDispatcherAgent(Agent)` subclass in `orchestrator.py` that overrides `tts_node()` with a sentence-buffer + first-segment token cap. Gate on `PRISM42_CYCLE_2E_BUFFER=1` (default OFF). Add metric-honesty triple-check (chars ≥ 8 + peak > 1000 + duration > 200 ms) so the harness's `first_useful_audio_after_speech_ms` cannot be gamed by chunked filler. Verification matrix distinguishes "audio earlier" (real win) from "just chunked" (false win) by pinning `tts_total_ms` p95 within ±10% of the cycle-2a-debug baseline.

---

## 1. Patch scope

| File | LOC added | Nature |
|---|---|---|
| `agents/livekit/orchestrator.py` | +85 | New `_SentenceBuffer` class (~40), new `BufferedDispatcherAgent(Agent)` class with `tts_node()` override (~30), new imports (~5), env-flag dispatch in `make_orchestrator()` (~10) |
| `agents/livekit/worker.py` | +5 | Single new info-log line `overlap.first_segment_published_after_llm_ms` (Option B from worker-target-locations.md §2b) wired so orchestrator can write it without importing worker internals; small log-level guard. **NO change** to `AgentSession` construction at lines 428-452. **NO change** to `preemptive_generation` at lines 446-450. **NO change** to filler logic at lines 823-858. **NO change** to `_new_turn_timing()` at line 238-260. |

**Total:** ~90 LOC new. Within the < 100 LOC glasswing target.

**Reverse:** one env var (`unset PRISM42_CYCLE_2E_BUFFER`) + worker restart. The new code stays compiled but inert.

---

## 2. Patch sketch — orchestrator.py

### 2a. Imports (top of file, after line 23)

```python
import os
import re
import time
from collections.abc import AsyncIterable, AsyncGenerator
from typing import Any

import structlog
from livekit import rtc
from livekit.agents import Agent
from livekit.agents.voice.agent import ModelSettings  # type: ignore[attr-defined]
```

### 2b. Module-level constants (after the imports block)

```python
# Pipecat sentence regex — terminator + optional close-quote/paren + whitespace.
# Exact regex from pipecat_bots/sentence_buffer.py:64.
_SENTENCE_RE = re.compile(r'[.!?]["\'\)]*\s')

# Pipecat InputParams defaults (llama_cpp_buffered_llm.py InputParams).
_FIRST_SEGMENT_MAX_TOKENS = int(os.environ.get("PRISM42_CYCLE_2E_FIRST_TOKENS", "24"))
_SEGMENT_MAX_TOKENS = int(os.environ.get("PRISM42_CYCLE_2E_NEXT_TOKENS", "32"))
_SEGMENT_HARD_MAX_TOKENS = int(os.environ.get("PRISM42_CYCLE_2E_HARD_TOKENS", "96"))

# Metric-honesty thresholds (this file's invention, not Pipecat's). The
# bench harness in synthetic_caller_full.py:153,168 already uses peak>1000
# as the "useful audio" threshold. We additionally require chars >= 8 of
# raw LLM-generated text (rejects pure punctuation / "...") and a duration
# floor of 200 ms after TTS render so phoneme-glitch chunks cannot pass as
# the first useful frame. Tunable so a flat-fail bench can prove the
# threshold isn't smuggling pollution.
_MIN_FIRST_SEGMENT_CHARS = int(os.environ.get("PRISM42_CYCLE_2E_MIN_CHARS", "8"))

# Helper: a coarse char-to-token approximation. livekit-agents has no
# tiktoken dependency, and we do not want one. Pipecat counts model-
# reported tokens; our cap is approximate by design (see pattern.md §2a:
# "stop generating, then find the best break point in what we have so
# far" — it's a fence, not a guillotine).
def _approx_tokens(text: str) -> int:
    return max(len(text) // 4, 1)
```

### 2c. The `_SentenceBuffer` class (after the constants)

Verbatim port of `pipecat_bots/sentence_buffer.py:SentenceBuffer` priority ladder. Identical to the pseudo-code in `worker-target-locations.md` §2a lines 62-120 — the integrator should copy that block. Key invariants:

- `extract_complete_sentences()` returns the prefix up through the **last** regex match (multi-sentence segments stay together — important for prosody).
- `extract_at_boundary()` priority: sentence > clause (`,` / `;` / `\n`) > word (` `) > everything.
- Both methods mutate `self.text` in place (the consumed prefix is removed).
- `reset_token_count()` is called by `BufferedDispatcherAgent.tts_node` after every successful flush; the buffer's text continues to accumulate for subsequent segments.

### 2d. The `BufferedDispatcherAgent` class

```python
class BufferedDispatcherAgent(Agent):
    """Sentence-boundary buffered TTS emit + first-segment token cap.

    See findings/voice/cycle-2e-pipecat/pattern.md.

    Gates the LLM-text → TTS-plugin handoff so the first segment ships on
    the earliest of:
      - first sentence terminator (.!? + space)
      - approximately FIRST_SEGMENT_MAX_TOKENS
    Subsequent segments use SEGMENT_MAX_TOKENS / SEGMENT_HARD_MAX_TOKENS.
    """

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        log = structlog.get_logger()
        buf = _SentenceBuffer()
        is_first = True
        cap = _FIRST_SEGMENT_MAX_TOKENS
        hard_cap = _FIRST_SEGMENT_MAX_TOKENS  # asymmetric: first is its own ceiling
        first_segment_chars: int | None = None
        t_llm_first_delta: float | None = None
        t_first_segment_published: float | None = None

        async def _gated() -> AsyncGenerator[str, None]:
            nonlocal is_first, cap, hard_cap, first_segment_chars
            nonlocal t_llm_first_delta, t_first_segment_published
            async for delta in text:
                if not delta:
                    # Risk-2 guard: ignore reasoning-content / FlushSentinel
                    # / empty deltas. Same effect as `if not chunk.delta.content`
                    # in pattern.md §4 Risk 2.
                    continue
                if t_llm_first_delta is None:
                    t_llm_first_delta = time.monotonic()
                buf.add(delta)

                # Sentence-boundary path.
                seg = buf.extract_complete_sentences()
                # Token-cap force-flush.
                if seg is None and buf.token_count >= cap:
                    seg = buf.extract_at_boundary()
                # Hard cap (first-segment only meaningful when cap < hard_cap;
                # for subsequent segments hard_cap=SEGMENT_HARD_MAX_TOKENS).
                if seg is None and buf.token_count >= hard_cap:
                    seg = buf.extract_at_boundary()

                if seg:
                    buf.reset_token_count()
                    if is_first:
                        # Metric-honesty check (a): first segment must contain
                        # at least N chars of LLM text. If under, KEEP buffering
                        # and do NOT flush yet — the audio that ships will be
                        # whatever the LLM produced after the threshold lands.
                        if len(seg) < _MIN_FIRST_SEGMENT_CHARS:
                            # Push the segment back into the buffer and keep
                            # accumulating. We extracted prematurely; the
                            # pattern's regex matched on something like "Yes. "
                            # (5 chars) — rare for our 5-12-word PSAP replies
                            # but possible.
                            buf.text = seg + buf.text
                            buf.token_count += _approx_tokens(seg)
                            continue
                        first_segment_chars = len(seg)
                        is_first = False
                        cap = _SEGMENT_MAX_TOKENS
                        hard_cap = _SEGMENT_HARD_MAX_TOKENS
                        t_first_segment_published = time.monotonic()
                        # Metric: how long did we hold the LLM stream before
                        # publishing the first segment? Should be > 0 (we are
                        # deliberately buffering). If = 0 / negative, the
                        # gate did nothing.
                        if t_llm_first_delta is not None:
                            dt_ms = int(
                                (t_first_segment_published - t_llm_first_delta) * 1000
                            )
                            log.info(
                                "overlap.first_segment_published_after_llm_ms",
                                ms=dt_ms,
                                chars=first_segment_chars,
                                approx_tokens=_approx_tokens(seg),
                                cap_used=_FIRST_SEGMENT_MAX_TOKENS,
                            )
                    yield seg
            # End-of-stream — flush the incomplete tail.
            if buf.has_content():
                tail = buf.text.strip()
                if tail:
                    if is_first and len(tail) < _MIN_FIRST_SEGMENT_CHARS:
                        # Edge case: the entire reply is shorter than the
                        # min-chars threshold (e.g. "OK."). Ship it anyway —
                        # the alternative is silence, which is worse. Log so
                        # the bench can flag it.
                        log.info(
                            "overlap.first_segment_below_threshold",
                            chars=len(tail),
                            min_chars=_MIN_FIRST_SEGMENT_CHARS,
                        )
                    yield tail

        # Delegate to Agent.default.tts_node — already wraps the underlying
        # TTS plugin (see agent.py:460-493).
        async for frame in Agent.default.tts_node(self, _gated(), model_settings):
            yield frame
```

### 2e. Modify `make_orchestrator` (currently lines 191-203)

```python
def make_orchestrator(session_id: str) -> Agent:
    instructions = (
        FAST_DISPATCHER_SYSTEM_PROMPT
        + f"\n\n# SESSION CONTEXT\nsession_id: {session_id}\n"
    )
    if os.environ.get("PRISM42_CYCLE_2E_BUFFER", "0") == "1":
        log.info("orchestrator.cycle2e_buffer.enabled", session_id=session_id)
        return BufferedDispatcherAgent(instructions=instructions, tools=[])
    log.info("orchestrator.cycle2e_buffer.disabled", session_id=session_id)
    return Agent(instructions=instructions, tools=[])
```

The env flag default `0` is critical: cycle-2a-debug's HARNESS_PARTIAL_FIX must continue to be the default behavior. The integrator turns it on in the bench environment only.

---

## 3. Patch sketch — worker.py

### 3a. New log line: `overlap.first_segment_published_after_llm_ms`

Already emitted from `BufferedDispatcherAgent.tts_node` in 2d above (Option B per `worker-target-locations.md` §2b — the orchestrator emits the line directly with `structlog`, no worker.py mutation).

### 3b. The single worker.py edit: env-flag echo to `overlap.config`

Inside `entrypoint()`, around line 458-466 where `overlap.config` is logged, add one new field so a single log line per session captures whether cycle-2e was active during that run. Critical for the bench parser to attribute timeseries to flag state.

```python
# In worker.py around line 458-466 (overlap.config log call), add:
log.info(
    "overlap.config",
    session_id=session_id,
    filler_delay_s=FILLER_DELAY_S,
    early_llm_chars=EARLY_LLM_CHARS,
    preemptive_generation_enabled=True,
    preemptive_tts_enabled=True,
    tts_backend=_tts_backend,
    cycle_2e_buffer_enabled=os.environ.get("PRISM42_CYCLE_2E_BUFFER", "0") == "1",
    cycle_2e_first_tokens=int(os.environ.get("PRISM42_CYCLE_2E_FIRST_TOKENS", "24")),
    cycle_2e_min_chars=int(os.environ.get("PRISM42_CYCLE_2E_MIN_CHARS", "8")),
)
```

That's the only worker.py change. ~5 lines added.

---

## 4. Metric-honesty enforcement — three checks

The cycle-2a-debug `first_useful_audio_after_speech_ms` is defined in `synthetic_caller_full.py:165-169` as: first audio frame with `peak > 1000` after `publish_end_at + 2.5s` (the `PRISM42_HARNESS_FILLER_SKIP_S` window). This metric is gameable — Pipecat-style chunking can ship a tiny first segment whose audio renders fast but is nearly content-free, and the harness will count it as the first useful frame.

**Three-check defense:**

| Check | Where enforced | Threshold | Effect on FAIL |
|---|---|---|---|
| (a) **First-segment min chars** | `BufferedDispatcherAgent._gated()` in 2d above | `_MIN_FIRST_SEGMENT_CHARS = 8` (env-tunable) | Push segment back into buffer; keep accumulating; do NOT yield yet |
| (b) **Audio peak > 1000** | Already in `synthetic_caller_full.py:153,168` (Team H's threshold, pre-existing) | `peak > 1000` (16-bit PCM) | Frame not counted as `first_useful_audio` — the harness loops to the next frame |
| (c) **Audio duration ≥ 200 ms** | NEW — bench-side check in `synthetic_caller_full.py` aggregate stage; orchestrator does NOT enforce (sees text, not rendered audio) | First useful audio's frame run must last ≥ 200 ms above `peak > 1000` before scoring | If shorter, the harness rejects it as a phoneme glitch and looks for the next sustained speech run |

Check (a) is enforced at the orchestrator before the chunk is even handed to TTS — the cleanest place. Checks (b) and (c) are bench-side because the orchestrator never sees rendered audio (it ships text to the TTS plugin).

**Bench-side patch obligation:** check (c) is a NEW addition to `synthetic_caller_full.py`. The current code at line 168 fires `first_useful_audio_at` on a single peak>1000 frame. The cycle-2e bench MUST gate on a 200 ms sustained run instead. This is ~10 LOC inside the existing `_drain()` callback. The integrator should add:

```python
# Track sustained-speech run for metric-honesty check (c).
_useful_run_start: list[float] = []
_useful_run_started_at: list[float] = []
# inside _drain() on each frame:
frame_dur_s = float(samples_per_channel) / float(sample_rate)
if peak > 1000:
    if not _useful_run_started_at:
        _useful_run_started_at.append(time.time())
    _useful_run_start.append(time.time())
    run_duration_s = (_useful_run_start[-1] + frame_dur_s) - _useful_run_started_at[0]
    if (
        run_duration_s >= 0.200
        and publish_end_at[0] > 0
        and time.time() > publish_end_at[0] + filler_skip_s
        and not first_useful_audio_at
    ):
        first_useful_audio_at.append(_useful_run_started_at[0])
else:
    _useful_run_started_at.clear()
```

(Sketched — the integrator confirms `samples_per_channel` and `sample_rate` are accessible from `fe.frame`.)

---

## 5. Verification protocol — distinguishing real-win from chunked-mask

The cycle-2e bench MUST run TWO arms (cycle-2a-debug baseline + cycle-2e), 10 turns each, same prompts. Then compare:

| Field | cycle-2a-debug (verified, source: result.json) | cycle-2e PASS target | cycle-2e FAIL signature |
|---|---|---|---|
| `first_useful_audio_after_speech_ms` p95 | **8283 ms** | **drops to ≤ 7800 ms** (≥ 500 ms improvement; ≥ 6% relative). Pattern.md §5 predicts -150 to -500 ms for Fish; we accept the conservative end. | drops only because chunked-mask gamed it (one of the FAIL signatures below) |
| `first_useful_audio_after_speech_ms` p50 | **7145 ms** | **drops to ≤ 6800 ms** (≥ 345 ms; ≥ 5%) | drops by < 100 ms or rises |
| `tts_total_ms_max` p95 (full reply audio render) | **7455 ms** | **stays within ±10% — i.e. 6710 - 8200 ms** | rises proportionally to the first_useful drop (e.g. drops 500 ms in first_useful but rises 600 ms in tts_total_max — chunking added overhead) |
| `useful_audio_skipped_filler_count` | **0/10** | **stays 0/10** | rises (the harness now skips the new "first chunk" because chars/duration check fails — silent regression) |
| `overlap.first_segment_published_after_llm_ms` p50 | **NEW METRIC, did not exist** | **> 0 and < 600 ms** (we are buffering, but only briefly — within a single sentence's worth of LLM tokens) | = 0 (gate did nothing; same as default Agent), OR > 1500 ms (gate held too long; net regression) |
| `llm_total_ms` p95 | **107 ms** | **unchanged ± 5 ms** | rises (orchestrator-side overhead — should not happen since we still consume the same stream) |
| `useful_reply_amp_max` p50 | **24809** | **unchanged ± 5%** (~23500 – 26050) | drops by > 10% (chunking caused TTS to render quieter audio for the first segment — degraded prosody) |
| `non_empty_reply_audio_count` | **10/10** | **stays 10/10** | drops (cut-off mid-thought from Risk 1) |
| Subjective listen | (not captured numerically; integrator listens to 1 sample) | **No mid-word cut audio in any of the 10 samples** | Mid-word cut artifact in any sample → revert |

### What "real-win" looks like in the data

- `first_useful_audio_after_speech_ms` p95 drops by 500-1500 ms.
- `tts_total_ms_max` p95 stays flat (within ±10%).
- `overlap.first_segment_published_after_llm_ms` is positive and < 600 ms (we buffered briefly, then shipped).
- `useful_audio_skipped_filler_count` stays 0/10.
- 10/10 turns produce real replies.

This is the correct outcome: TTS started speaking earlier (gain on the first-frame leg) without taking longer to finish (no chunking penalty).

### What "chunked-mask" (false win) looks like

Three independent signatures, any of which kills the patch:

1. **Skipping pollution.** `first_useful_audio_after_speech_ms` p95 dropped, but `useful_audio_skipped_filler_count` rose from 0/10 to ≥ 2/10. The harness's metric-honesty check (c) rejected the first chunk, and the metric drop is artifact of the harness, not the orchestrator.
2. **Total-render inflation.** `first_useful_audio_after_speech_ms` p95 dropped by 500 ms, but `tts_total_ms_max` p95 rose by ≥ 750 ms. The TTS plugin re-initialized per chunk and added inter-chunk gaps. Subjective listen will confirm choppy audio.
3. **Empty-buffer bypass.** `overlap.first_segment_published_after_llm_ms` p50 < 50 ms. The orchestrator did not actually buffer; the `_gated()` generator fast-pathed through (probably due to a bug in `_approx_tokens` or sentence-regex matching too eagerly). The drop is likely attributable to noise and will not reproduce.

If ANY of those three triggers, **revert** (`unset PRISM42_CYCLE_2E_BUFFER`) and capture the failed-bench artifacts under `findings/b300_bench/cycle2e_orchestration/<ISO>Z/`.

---

## 6. Acceptance criteria (cycle-2e PASS gate)

All of the following MUST hold, on N=10 turns same prompts as cycle-2a-debug:

1. **10/10 real replies preserved** (`non_empty_reply_audio_count == 10`).
2. **`first_useful_audio_after_speech_ms` p95 ≤ 7800 ms** (≥ 500 ms improvement vs cycle-2a-debug's 8283 ms).
3. **`tts_total_ms_max` p95 within ±10% of 7455 ms** (i.e. 6710-8200 ms inclusive).
4. **`useful_audio_skipped_filler_count == 0/10`** (no metric-honesty check failures).
5. **`overlap.first_segment_published_after_llm_ms` p50 between 50 and 600 ms** (we buffered, but not excessively).
6. **0/10 turns** subjective-listen artifact (mid-word cut, doubled phoneme, choppy first 200 ms).
7. **`llm_total_ms` p95 unchanged** within ±5 ms.

If criteria 1, 4, or 6 fail → revert (data integrity / safety).
If criteria 2 fails → cycle-2e provided no measurable win; revert.
If criteria 3 fails → cycle-2e is chunked-mask, not real-win; revert.
If criteria 5 fails → diagnostic mismatch (gate not actually gating); investigate before re-running.
If criteria 7 fails → orchestrator-side overhead; investigate before re-running.

If ALL criteria pass → cycle-2e is the new default for the next bench cycle, but env-flag stays gated (one bench round is not enough to change a default).

---

## 7. Apply + bench time estimate

| Phase | Action | Time |
|---|---|---|
| Apply | One `orchestrator.py` edit (~85 LOC) + one `worker.py` edit (~5 LOC) + one `synthetic_caller_full.py` edit (~10 LOC for the duration check) | 5 min |
| Lint/syntax | `uv run python -c "from agents.livekit.orchestrator import make_orchestrator; print(make_orchestrator('test'))"` | 30 s |
| Worker restart | `sudo systemctl restart prism42-worker && journalctl -u prism42-worker -f` (watch for `orchestrator.cycle2e_buffer.enabled` log line) | 30 s |
| Bench (cycle-2a-debug arm, baseline re-confirm) | 10 prompts via `synthetic_caller_full.py` with `PRISM42_CYCLE_2E_BUFFER=0` | 3-4 min |
| Bench (cycle-2e arm) | Same 10 prompts with `PRISM42_CYCLE_2E_BUFFER=1` | 3-4 min |
| Aggregate + compare | `aggregate_metrics.py` + paired-delta on the two timeseries | 1 min |
| **Total** | | **~12-15 min** |

10-min nominal target hits if the integrator parallelizes the lint/syntax check with the worker restart and runs both arms back-to-back without re-prompting between them.

---

## 8. Rollback

```bash
# Single-line rollback — env flag only. Code stays compiled but inert.
sudo systemctl set-environment PRISM42_CYCLE_2E_BUFFER=0
sudo systemctl restart prism42-worker

# Confirm:
journalctl -u prism42-worker --since '1 min ago' | grep cycle2e_buffer
# Expect: orchestrator.cycle2e_buffer.disabled
```

If the integrator wants to remove the code entirely (e.g. hackathon ended and we revert all cycle-2 work):

```bash
# Pre-stage backups before applying (the integrator should do this BEFORE editing):
cp /opt/prism42/agents/livekit/worker.py /opt/prism42/agents/livekit/worker.py.pre-cycle2e
cp /opt/prism42/agents/livekit/orchestrator.py /opt/prism42/agents/livekit/orchestrator.py.pre-cycle2e
cp /opt/prism42/agents/livekit/synthetic_caller_full.py /opt/prism42/agents/livekit/synthetic_caller_full.py.pre-cycle2e

# Then to revert:
cp /opt/prism42/agents/livekit/worker.py.pre-cycle2e /opt/prism42/agents/livekit/worker.py
cp /opt/prism42/agents/livekit/orchestrator.py.pre-cycle2e /opt/prism42/agents/livekit/orchestrator.py
cp /opt/prism42/agents/livekit/synthetic_caller_full.py.pre-cycle2e /opt/prism42/agents/livekit/synthetic_caller_full.py
sudo systemctl restart prism42-worker
```

The env-flag rollback (single line) is the preferred fast revert. The file-restore rollback is for hackathon-window-close cleanup.

---

## 9. File:line cite reference

| File | Line(s) | Role in patch |
|---|---|---|
| `agents/livekit/orchestrator.py` | 20-25 (imports) | Add `os`, `re`, `time`, `AsyncIterable`, `AsyncGenerator`, `rtc`, `ModelSettings` |
| `agents/livekit/orchestrator.py` | (new, ~28 onward) | `_SENTENCE_RE`, env-driven `_FIRST_SEGMENT_MAX_TOKENS` / `_SEGMENT_MAX_TOKENS` / `_SEGMENT_HARD_MAX_TOKENS`, `_MIN_FIRST_SEGMENT_CHARS`, `_approx_tokens()` helper |
| `agents/livekit/orchestrator.py` | (new, ~50 onward) | `_SentenceBuffer` class — verbatim port of `pipecat_bots/sentence_buffer.py` priority ladder |
| `agents/livekit/orchestrator.py` | (new, ~110 onward) | `BufferedDispatcherAgent(Agent)` class with `tts_node()` override |
| `agents/livekit/orchestrator.py` | 191-203 | Replace `Agent(...)` return with env-flag dispatch on `PRISM42_CYCLE_2E_BUFFER` |
| `agents/livekit/worker.py` | 458-466 | Add three `cycle_2e_*` fields to existing `overlap.config` log line |
| `agents/livekit/worker.py` | 428-452 | **NO change** — `AgentSession` construction unchanged |
| `agents/livekit/worker.py` | 446-450 | **NO change** — `preemptive_generation` unchanged (additive on top per pattern.md §3d) |
| `agents/livekit/worker.py` | 529-537 | **NO change** — `overlap.tts_first_audio_after_speech_ms` is the bench primary metric, untouched |
| `agents/livekit/worker.py` | 823-858 | **NO change** — filler logic unchanged |
| `agents/livekit/synthetic_caller_full.py` | 146-170 (`_drain` callback) | Add ~10 LOC: 200 ms sustained-run gate on `first_useful_audio_at` (metric-honesty check (c)) |
| `agents/livekit/synthetic_caller_full.py` | 116 (`PRISM42_HARNESS_FILLER_SKIP_S`) | **NO change** — keep at 2.5s default |

Read-only library reference (untouched, informs the override):

| File | Line(s) | Role |
|---|---|---|
| `livekit/agents/voice/agent.py` | 342-367 | The `tts_node` extension point we override |
| `livekit/agents/voice/agent.py` | 460-493 | `Agent.default.tts_node` we delegate to |
| `livekit/agents/voice/agent_activity.py` | 2407-2417 | The `tee` from `text_ch` to `tts_text_input` |
| `livekit/agents/voice/generation.py` | 49,183-185 | `text_ch` definition + populate |

---

## 10. Risks called by Team P + how this plan addresses them

| Risk (pattern.md §4) | Plan response |
|---|---|
| R1 — Cut-off mid-thought audio | Priority-ladder fallback in `_SentenceBuffer.extract_at_boundary()` prefers sentence > clause > word > all. Subjective-listen check is criterion 6 in §6 above; one mid-word cut → revert. |
| R2 — Nemotron reasoning-content out-of-order | The `if not delta: continue` guard in `_gated()` covers the empty-content case. `enable_thinking=False` (already at `worker.py:358`) keeps it moot. |
| R3 — Filler interaction (filler-vs-reply double-speak race) | No change to filler logic. `allow_interruptions=True` (filler at `worker.py:852`) preempts as before. Bench obligation: subjective listen confirms preemption is smooth — criterion 6. |
| R4 — Filler tokens at start of Nemotron replies | Relies on dispatcher prompt's 5-12-word constraint (`orchestrator.py:48-188`). If pilot data shows filler prefixes, add a `re.sub` strip filter in a follow-on cycle. Out of scope here. |
| R5 — Force-flush before meaningful content | Metric-honesty check (a) — `_MIN_FIRST_SEGMENT_CHARS = 8` floor in `_gated()` is exactly this defense. |
| R6 — Over-fragmentation regresses prosody | Verified by criterion 3 (`tts_total_ms_max` p95 within ±10%) and `useful_reply_amp_max` p50 within ±5%. |
| R7 — Sonnet 4.6 (cloud Anthropic) sees smaller win | Backend-agnostic: `tts_node` sees the same `AsyncIterable[str]` regardless. Bench is run against vllm-local Nemotron (current default LLM_BACKEND on the bench pod). |

---

## 11. What this plan does NOT do

- Does NOT modify `_SESSION_TIMINGS` or `_new_turn_timing()` in `worker.py`. The orchestrator emits its instrumentation via structlog directly (Option B from worker-target-locations.md §2b).
- Does NOT add a tokenizer dependency. `_approx_tokens()` uses `len(text) // 4` — coarse but sufficient because the cap is a fence, not a guillotine (pattern.md §2a).
- Does NOT change the LLM backend selector (`worker.py:329-370`). Cycle-2e is orchestrator-only.
- Does NOT change the TTS backend selector (`worker.py:378-409`). Cycle-2e composes with Fish, Cartesia, Deepgram, ElevenLabs.
- Does NOT alter `preemptive_generation.preemptive_tts: True` (`worker.py:446-450`). Cycle-2e is additive on top.
- Does NOT introduce any HTTP / RPC call. All in-process.
- Does NOT touch `vendor/fish-speech/` (Fix 4 from synthesis.md is cycle-2d's territory).
- Does NOT touch CUDA MPS configuration (Fix 3 is cycle-2c's territory).

---

## 12. One-line acceptance

**~90 LOC across 3 files; env-flag default OFF; PASS = first_useful_audio p95 drops ≥ 500 ms AND tts_total_ms p95 stays within ±10% AND skipped_filler_count stays 0/10 AND no mid-word cut on subjective listen; rollback is `set-environment PRISM42_CYCLE_2E_BUFFER=0`.**

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits).
