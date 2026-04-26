---
title: LLM backend swap — AnthropicLLM → vLLM-local (Nemotron Nano 3 MoE)
date: 2026-04-24
status: research brief, not applied
scope: worker.py LLM hop only. STT (Parakeet) + TTS (Fish/Cartesia) + all
       LiveKit wiring (TurnHandlingOptions, preemptive_generation,
       AgentSession, conversation_item_added, metrics_collected, speech_created,
       b3-latency channel, transcript bus) unchanged.
word_count: ~790
---

# 24 — LLM backend swap: AnthropicLLM → vLLM-local (Nemotron Nano 3 MoE)

## 1. livekit-plugins-openai compat: base_url override

Confirmed from source at `.venv/lib/python3.14/site-packages/livekit/plugins/openai/llm.py`:

```python
class LLM(llm.LLM):
    def __init__(self, *, model="gpt-4.1", api_key=NOT_GIVEN, base_url=NOT_GIVEN, ...):
        self._client = client or openai.AsyncClient(
            api_key=api_key if is_given(api_key) else None,
            base_url=base_url if is_given(base_url) else None,
            ...
        )
```

`base_url` is a first-class constructor parameter, passed straight to `openai.AsyncClient`. The intended drop-in:

```python
from livekit.plugins.openai import LLM as OpenAILLM
llm = OpenAILLM(
    model="nvidia/NVIDIA-Nemotron-Nano-3-30B-A3B-BF16",
    base_url="http://127.0.0.1:8000/v1",
    api_key="EMPTY",
)
```

No custom plugin needed. There is no `livekit-plugins-vllm` or `livekit-plugins-nvidia-nim`; the openai plugin is the canonical path for all OpenAI-compatible local endpoints (Ollama, Fireworks, Cerebras, etc. all use this same pattern — confirmed in the 15 `with_*` static methods in the file).

**Sharp edge — strict tool schema.** The openai plugin passes `_strict_tool_schema=True` by default to `LLMStream`. This calls `parse_function_tools("openai", strict=True)`, which injects `"strict": true` and `"additionalProperties": false` into every tool schema before sending to vLLM. vLLM's `qwen3_coder` tool-call parser may not expect `strict` mode and could silently ignore or error on it. Pass `_strict_tool_schema=False` for vLLM:

```python
llm = OpenAILLM(
    model="nvidia/NVIDIA-Nemotron-Nano-3-30B-A3B-BF16",
    base_url="http://127.0.0.1:8000/v1",
    api_key="EMPTY",
    _strict_tool_schema=False,
)
```

Source: `llm.py:116` + `inference/llm.py:348`.
LiveKit docs page: https://docs.livekit.io/agents/models/llm/plugins/openai/

## 2. Custom plugin

None needed. No `livekit-plugins-vllm` package exists on PyPI as of April 2026.

## 3. Tool-calling compatibility

Nemotron Nano 3 MoE supports tool calling via vLLM with `--enable-auto-tool-choice --tool-call-parser qwen3_coder`. The model is explicitly designed for agentic/tool-calling workloads.

Source: https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html and https://vllm.ai/blog/run-nvidia-nemotron-3-nano

vLLM's OpenAI-compat layer emits tool calls in the standard `delta.tool_calls[].function.{name,arguments}` SSE format, which is exactly what `LLMStream._run` at `inference/llm.py:427-483` expects. No reformatting needed.

**One risk:** `strict` mode in the tool schema (see section 1). Use `_strict_tool_schema=False`.

## 4. System prompt format

Nemotron uses chatml internally (`<|im_start|>system\n...<|im_end|>`), but vLLM applies the tokenizer's chat template automatically via `apply_chat_template`. The LiveKit openai plugin sends a standard OpenAI `messages` array with a `{"role": "system", "content": "..."}` message. vLLM wraps this with the model's own template before tokenizing. The orchestrator's `FAST_DISPATCHER_SYSTEM_PROMPT` (plain XML/markdown string) will work as-is — no manual chatml wrapping needed. vLLM's `--served-model-name` alias does not affect template application.

**One risk:** Nemotron's chatml template may render the system prompt with different token boundaries than Sonnet's tokenizer, which can change how the model perceives the prompt structure. Empirical test needed, but no code change is required.

## 5. Streaming and token-rate matching

vLLM emits standard OpenAI SSE format (`data: {"choices":[{"delta":{"content":"..."}}]}`), consumed transparently by `openai.AsyncClient`. The LiveKit stream reader at `inference/llm.py:333-484` iterates `async for chunk in self._oai_stream` — identical code path whether the upstream is api.openai.com or `127.0.0.1:8000`.

Nemotron Nano 3 MoE (3.5B active params, MoE) on a B300 will sustain 150-300+ tok/s at batch size 1 — faster than Sonnet 4.6 (~80-100 tok/s via Anthropic API). LiveKit's `preemptive_generation` only requires that tokens arrive in a stream; there is no minimum cadence. No known vLLM streaming format issues with the livekit openai plugin.

## 6. Worker.py patch — smallest possible diff

Replace lines 326-327 in `worker.py` (the `from livekit.plugins.anthropic import ...` block and `llm=AnthropicLLM(...)` in `AgentSession`) with the backend selector below. Default stays `anthropic` — zero regression without the env var.

```python
# worker.py — replace the import + llm= line in AgentSession
_llm_backend = os.environ.get("LLM_BACKEND", "anthropic").lower()
if _llm_backend == "vllm-local":
    from livekit.plugins.openai import LLM as OpenAILLM  # noqa: PLC0415
    _llm = OpenAILLM(
        model=os.environ.get(
            "VLLM_MODEL", "nvidia/NVIDIA-Nemotron-Nano-3-30B-A3B-BF16"
        ),
        base_url=os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        api_key="EMPTY",
        _strict_tool_schema=False,
        max_completion_tokens=256,
    )
    log.info("llm.backend", backend="vllm-local", model=_llm.model)
else:
    from livekit.plugins.anthropic import LLM as AnthropicLLM  # noqa: PLC0415
    _llm = AnthropicLLM(model="claude-sonnet-4-6", caching="ephemeral")
    log.info("llm.backend", backend="anthropic", model="claude-sonnet-4-6")

session = AgentSession(
    vad=silero.VAD.load(),
    stt=ParakeetSTT(ParakeetOptions()),
    llm=_llm,          # <- was: llm=AnthropicLLM(model="claude-sonnet-4-6", caching="ephemeral")
    tts=_tts,
    turn_handling={...},
)
```

Flip: `LLM_BACKEND=vllm-local systemctl restart prism42-worker`. Roll back: unset env var or set `LLM_BACKEND=anthropic`.

## 7. Anticipated bottlenecks

| Risk | Severity | Notes |
|---|---|---|
| vLLM endpoint not up when worker starts | High | Worker constructs `openai.AsyncClient` lazily; first call raises `httpx.ConnectError`. Add a startup probe: `GET /health` on vLLM before `session.start()`. |
| Strict tool schema mismatch | High | `_strict_tool_schema=False` eliminates this — set it on the constructor. |
| Anthropic `input_schema` vs OpenAI `function` format | None | The LiveKit plugin handles the format translation; tool schemas are always serialized via `parse_function_tools("openai", ...)` for the openai backend. No overlap with the Anthropic path. |
| Nemotron chatml tokenizer vs Sonnet | Medium | System prompt renders correctly (vLLM applies template), but token count differs. Monitor `llm_ms` on turn 1 — budget may need adjustment if the prompt is longer in Nemotron tokens. |
| `caching="ephemeral"` doesn't translate | Low | Anthropic-specific kwarg; not passed to the openai plugin. vLLM has no first-class prompt cache. KV cache is implicit for same-prefix requests. No code issue — just no cache speedup on repeat turns. |
| max_tokens default | Low | Sonnet default via plugin is not bounded; set `max_completion_tokens=256` explicitly for vLLM (voice replies rarely exceed 80 tokens; 256 is generous). |
| `reasoning_effort` auto-set | Low | `LLMOptions.__init__` auto-sets `reasoning_effort="minimal"` for known reasoning models (gpt-5.x series). Nemotron model ID won't match `_supports_reasoning_effort()`, so no reasoning kwarg is injected — correct. |

## 8. A/B verification

Both backends are live behind the `LLM_BACKEND` env flag. The existing `latency.publish` log line (emitted every turn by `_publish_latency` / `_publish_latency_dict`) already captures `llm_ms`. To A/B:

```bash
# Anthropic baseline: 10 turns, log llm_ms
LLM_BACKEND=anthropic systemctl restart prism42-worker
grep "latency.publish" /var/log/prism42/worker.log | jq -r '.llm_ms' | awk '{s+=$1;n++}END{print "mean_ms="s/n}'

# vLLM flip:
LLM_BACKEND=vllm-local systemctl restart prism42-worker
# same grep
```

Add one log line at `session start` for dashboard parsing:

```python
log.info("llm.backend", backend=_llm_backend, model=_llm.model)
```

This already appears in the patch above. The `bench_b300.py --n 10` harness can parse `llm_ms` from the structured log directly; no new metric infrastructure needed.

## vLLM serve command (Nemotron Nano 3 MoE, B300)

```bash
vllm serve nvidia/NVIDIA-Nemotron-Nano-3-30B-A3B-BF16 \
    --dtype auto \
    --trust-remote-code \
    --served-model-name nvidia/NVIDIA-Nemotron-Nano-3-30B-A3B-BF16 \
    --host 127.0.0.1 \
    --port 8000 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser deepseek_r1 \
    --max-model-len 65536 \
    --tensor-parallel-size 1
```

FP8 variant (`-FP8`) saves ~50% HBM; add `--kv-cache-dtype fp8 VLLM_USE_FLASHINFER_MOE_FP8=1` if using that.

## Sources

- `livekit-plugins-openai/llm.py` (installed, read directly from venv)
- `livekit/agents/inference/llm.py` (installed, read directly)
- https://docs.livekit.io/agents/models/llm/plugins/openai/
- https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
- https://vllm.ai/blog/run-nvidia-nemotron-3-nano
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
