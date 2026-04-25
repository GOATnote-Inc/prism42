# cycle-2e retrofit target locations — worker.py + orchestrator.py

Companion to [`pattern.md`](pattern.md). This file maps the Pipecat sentence-buffer + first-segment-token-cap pattern onto our specific files. **No code is applied here.** Pseudo-code is for the integrator.

Read-only audit, 2026-04-25. Every file:line cite is verified against the current tree.

---

## 1. The single retrofit hook

**The cleanest insertion point is overriding `Agent.tts_node()` in `orchestrator.py`.**

Reason: `livekit/agents/voice/agent.py:342-367` documents that hook explicitly as the "different text chunking behavior" extension point. The default implementation at `voice/agent.py:460-493` already takes `text: AsyncIterable[str]` and yields `rtc.AudioFrame` — exactly the shape we need. By overriding it on our `Agent` subclass we intercept the LLM stream BEFORE it hits the underlying TTS plugin, without touching `worker.py`'s `AgentSession` construction, without monkey-patching agent_activity.py, and without modifying any plugin.

This is a one-file change in `orchestrator.py` plus a handful of telemetry hooks in `worker.py`.

---

## 2. Files that need to change

### 2a. `agents/livekit/orchestrator.py` — primary change

**Current state** (verbatim from the file):

- Line 23: `from livekit.agents import Agent`
- Line 191-203: `def make_orchestrator(session_id: str) -> Agent: ... return Agent(instructions=instructions, tools=[])` — returns the base `Agent` class directly, no subclassing.

**Change shape:**

1. Add a subclass `BufferedDispatcherAgent(Agent)` that overrides `tts_node()`.
2. `make_orchestrator()` returns an instance of the subclass instead of `Agent` directly.
3. Add `from livekit.agents import tokenize` and the new sentence-buffer + token-cap logic.

**Pseudo-code (inside `orchestrator.py`):**

```python
from collections.abc import AsyncIterable, AsyncGenerator
from typing import Any
import re

from livekit import rtc
from livekit.agents import Agent
from livekit.agents.voice.agent import ModelSettings  # exposed via voice.agent

# Pipecat's regex (sentence_buffer.py:64) — terminator + optional close-quote/paren + whitespace.
_SENTENCE_RE = re.compile(r'[.!?]["\'\)]*\s')

# Pipecat defaults (llama_cpp_buffered_llm.py InputParams) — see pattern.md §2a.
FIRST_SEGMENT_MAX_TOKENS = 24
SEGMENT_MAX_TOKENS = 32
SEGMENT_HARD_MAX_TOKENS = 96

# Heuristic token approximation: livekit-agents has no tokenizer dependency on
# the OpenAI tiktoken side, but the Pipecat pattern uses model-reported token
# counts. For our purpose, the cap is approximate — we count whitespace-split
# words ("char-count // 4" is the alternate Anthropic-blessed approximation).
# Picking word-count keeps it simple and tunable.
def _approx_tokens(text: str) -> int:
    return max(len(text) // 4, 1)


class _SentenceBuffer:
    """Direct port of pipecat_bots/sentence_buffer.py:SentenceBuffer.

    Identical extract_complete_sentences() and extract_at_boundary() priority
    ladder (sentence > clause > word > all). See pattern.md §2b.
    """
    def __init__(self) -> None:
        self.text: str = ""
        self.token_count: int = 0

    def add(self, delta: str) -> None:
        self.text += delta
        self.token_count += _approx_tokens(delta)

    def reset_token_count(self) -> None:
        self.token_count = 0

    def has_content(self) -> bool:
        return bool(self.text.strip())

    def extract_complete_sentences(self) -> str | None:
        matches = list(_SENTENCE_RE.finditer(self.text))
        if not matches:
            return None
        boundary = matches[-1].end()
        sentences = self.text[:boundary].lstrip()
        self.text = self.text[boundary:]
        return sentences if sentences else None

    def extract_at_boundary(self) -> str:
        if not self.text:
            return ""
        # Priority 1: sentence boundary
        matches = list(_SENTENCE_RE.finditer(self.text))
        if matches:
            boundary = matches[-1].end()
            result = self.text[:boundary].lstrip()
            self.text = self.text[boundary:]
            return result
        # Priority 2: clause boundary (", " or "; " or "\n")
        comma_idx = self.text.rfind(", ")
        semi_idx = self.text.rfind("; ")
        nl_idx = self.text.rfind("\n")
        clause_idx = max(comma_idx, semi_idx, nl_idx)
        if clause_idx > 0:
            boundary = clause_idx + (1 if clause_idx == nl_idx else 2)
            result = self.text[:boundary].lstrip()
            self.text = self.text[boundary:]
            return result
        # Priority 3: word boundary
        sp_idx = self.text.rfind(" ")
        if sp_idx > 0:
            result = self.text[:sp_idx + 1].lstrip()
            self.text = self.text[sp_idx + 1:]
            return result
        # Fallback: emit everything
        result = self.text.strip()
        self.text = ""
        return result


class BufferedDispatcherAgent(Agent):
    """Sentence-boundary buffered TTS emit + first-segment token cap.

    See findings/voice/cycle-2e-pipecat/pattern.md for the architecture
    rationale. This override interposes a sentence-buffer between the LLM
    text stream and the underlying TTS plugin so the first segment fires
    on the earliest of:
      - first sentence terminator (.!? + space)
      - approx FIRST_SEGMENT_MAX_TOKENS reached
    Subsequent segments use the same gate with SEGMENT_MAX_TOKENS.
    """

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        # Build a re-emitted stream that gates by sentence boundary + token cap,
        # then delegate to Agent.default.tts_node() which already wraps the
        # underlying TTS plugin (see agent.py:460-493).
        buf = _SentenceBuffer()
        is_first = True
        cap = FIRST_SEGMENT_MAX_TOKENS

        async def _gated() -> AsyncGenerator[str, None]:
            nonlocal is_first, cap
            async for delta in text:
                if not delta:
                    continue
                buf.add(delta)
                # Sentence-boundary path
                seg = buf.extract_complete_sentences()
                if seg is None and buf.token_count >= cap:
                    # Token-cap force-flush
                    seg = buf.extract_at_boundary()
                if seg:
                    buf.reset_token_count()
                    if is_first:
                        is_first = False
                        cap = SEGMENT_MAX_TOKENS
                    yield seg
            # End-of-stream — flush whatever remains (incomplete tail).
            if buf.has_content():
                yield buf.text.strip()

        # Delegate to the default tts_node implementation with the gated stream.
        async for frame in Agent.default.tts_node(self, _gated(), model_settings):
            yield frame
```

Then change `make_orchestrator()` line 191-203:

```python
def make_orchestrator(session_id: str) -> Agent:
    instructions = (
        FAST_DISPATCHER_SYSTEM_PROMPT
        + f"\n\n# SESSION CONTEXT\nsession_id: {session_id}\n"
    )
    return BufferedDispatcherAgent(instructions=instructions, tools=[])
```

**LOC estimate for `orchestrator.py`:** ~85 lines added (sentence buffer class ~40, tts_node override ~30, imports ~5, glue ~10). **Within < 100 LOC budget.**

### 2b. `agents/livekit/worker.py` — telemetry only

**No structural change to AgentSession.** The override in `orchestrator.py` does all the work. We add **two** telemetry hooks for the bench plan in `pattern.md` §5.

**Hook 1: first-segment-published-after-llm timestamp**

`worker.py` already has `_SESSION_TIMINGS[session_id]["current"]` populated by event handlers at lines 235-260. Add one new field to `_new_turn_timing()` at line 238-260:

- After line 251 (`"t_first_tts_audio": None`), add:
  ```python
  "t_first_segment_published": None,  # monotonic, first sentence-buffer flush to TTS
  ```

The override in `orchestrator.py:BufferedDispatcherAgent.tts_node` cannot easily reach `_SESSION_TIMINGS` (worker.py-internal). Two options:

- **Option A (preferred, cleaner):** export a module-level callable `_record_first_segment(session_id, ts)` from `worker.py`, import it in `orchestrator.py`, call inside `_gated()` on first non-empty `seg`.
- **Option B (acceptable, looser):** log a single structured line `overlap.first_segment_published` from inside `_gated()` with `time.monotonic()`. Telemetry parser scrapes both this line and the existing `overlap.tts_first_audio_after_speech_ms` line and computes the delta offline.

LOC for Option B: ~5 lines in `orchestrator.py`, 0 in `worker.py`. Recommend Option B for cycle-2e — keep `worker.py` untouched.

**Hook 2: env-flag for safe rollout**

`worker.py` has the cycle-2a/cycle-1 pattern of feature flags via env var (e.g. `PRISM42_EARLY_LLM_CHARS` line 103). Adopt the same idiom in `orchestrator.py`:

- `PRISM42_CYCLE_2E_BUFFER` — defaults to `0` (disabled). When `=1`, `make_orchestrator()` returns `BufferedDispatcherAgent`. When `=0`, returns the bare `Agent` (current behavior).

This gives the integrator a single env-var revert if the retrofit shows regression in the bench plan, without removing the code. Pattern matches `worker.py:329` (`_llm_backend = os.environ.get("LLM_BACKEND", "anthropic").lower()`) and `worker.py:378` (`_tts_backend`).

LOC for env-flag: ~5 lines in `orchestrator.py`. **No worker.py changes.**

### 2c. Files that do NOT need to change

- `worker.py:428-452` (`AgentSession` construction) — no change. The override is on the `Agent` instance passed via `make_orchestrator()`, which `worker.py:468` already calls and passes to `session.start(agent=orchestrator, ...)` at line 764.
- `worker.py:446-450` (`preemptive_generation`) — no change. The retrofit is additive on top of preemptive_tts. See `pattern.md` §3d.
- `fish_speech_tts.py`, `parakeet_stt.py` — no change. The override sits between LLM and TTS at the `Agent.tts_node` layer; the underlying plugins see the same `AsyncIterable[str]` shape they always have, just with sentence-grouped chunks instead of token-stream.
- `livekit-agents` source — no change. We use the documented `Agent.tts_node` extension point (line 342-367 of `voice/agent.py`).

---

## 3. The new control flow (sketch)

### Before (current)

```
LLM (vLLM Nemotron) → text_ch [token-stream]
                           ↓ tee
                      tts_text_input [token-stream]
                           ↓
                  Agent.default.tts_node()
                           ↓ wrapped_tts.stream(token by token)
                      Fish/Cartesia plugin
                           ↓
                       audio frames
```

### After (cycle-2e)

```
LLM (vLLM Nemotron) → text_ch [token-stream]
                           ↓ tee
                      tts_text_input [token-stream]
                           ↓
              BufferedDispatcherAgent.tts_node()  ← NEW
                           ↓ _gated() generator
                  _SentenceBuffer accumulates
                           ↓ flush on [.!? + space] OR cap
                  [first segment ≤ 24 tokens approx]
                  [subsequent segments ≤ 32 tokens approx]
                           ↓
                  Agent.default.tts_node(_gated(), ...)
                           ↓ wrapped_tts.stream(sentence-grouped)
                      Fish/Cartesia plugin
                           ↓
                       audio frames (earlier first frame)
```

The TTS plugin sees: `["Nine one one, what is your location and emergency? ", "Stay calm. ", "Tell me what is happening."]` instead of `["Nine", " one", " one", ",", " what", " is", ...]`. Same total content; first chunk arrives at TTS at a sentence boundary.

---

## 4. Verification matrix (read-only — for the integrator)

When the integrator applies the retrofit, they should verify:

| Layer | Command | Proves |
|---|---|---|
| Compile | `uv run python -c "from orchestrator import make_orchestrator; print(make_orchestrator('test'))"` | Imports + class instantiation work |
| Runtime smoke | `PRISM42_CYCLE_2E_BUFFER=1 uv run python worker.py console` | Worker boots; type a message; agent replies |
| Audio path | Real LiveKit room call, listen for mid-word cut artifacts | Risk 1 + Risk 6 absent in subjective listen |
| Bench | 30-turn paired delta on `overlap.tts_first_audio_after_speech_ms` per `pattern.md` §5 | Quantified gain or revert decision |

The first three are read-only-equivalent (no commit). The fourth is the gate.

---

## 5. Specific file:line targets (cited)

| Location | Line(s) | Role in retrofit |
|---|---|---|
| `agents/livekit/orchestrator.py` | 23 | Add imports for `tokenize`, `re`, etc. |
| `agents/livekit/orchestrator.py` | 191-203 | Replace `Agent(...)` with `BufferedDispatcherAgent(...)` (gated by `PRISM42_CYCLE_2E_BUFFER=1`) |
| `agents/livekit/orchestrator.py` | (new, ~204+) | New `_SentenceBuffer` class, `BufferedDispatcherAgent` class with `tts_node` override |
| `agents/livekit/worker.py` | 446-450 | **No change.** preemptive_tts stays on. Confirms additivity. |
| `agents/livekit/worker.py` | 468 | **No change.** `make_orchestrator(session_id)` continues to return whatever `make_orchestrator` returns; subclass is transparent. |
| `agents/livekit/worker.py` | 529-537 | **No change.** `overlap.tts_first_audio_after_speech_ms` log line is the bench primary metric. |

Library reference (read-only):

| File | Line(s) | Role |
|---|---|---|
| `livekit/agents/voice/agent.py` | 342-367 | The `tts_node` extension point we override |
| `livekit/agents/voice/agent.py` | 460-493 | `Agent.default.tts_node` we delegate to |
| `livekit/agents/voice/agent_activity.py` | 2407-2417 | The `tee` from `text_ch` to `tts_text_input` (untouched but informs why the override works) |
| `livekit/agents/voice/generation.py` | 49,183-185 | `text_ch` definition + populate (untouched but informs the stream contract) |
| `livekit/agents/tokenize/token_stream.py` | 112-124 | `BufferedSentenceStream` (alternative to `_SentenceBuffer` if integrator prefers leveraging built-in; trade-off is `BufferedSentenceStream` has no first-segment-cap) |

---

## 6. One-line acceptance

**Estimated retrofit:** ~85 LOC in `orchestrator.py`, 0 in `worker.py`. **Predicted gain on publish→first useful audio:** -150 to -500 ms p50 (Fish lower end / Cartesia upper end). **Risk:** **M** — gated by `PRISM42_CYCLE_2E_BUFFER=1` so revert is one env-var.
