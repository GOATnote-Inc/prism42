# livekit-agents 1.5.6 + livekit-plugins-anthropic 1.5.6 — tool-schema anatomy

Deep source trace through the installed packages on `prism-mla-b300-h4h5`
(`/opt/prism42/agents/livekit/.venv/lib/python3.12/site-packages/...`).

Root-cause of the 400 `tools.0.custom: additionalProperties: true is not supported` is
identified below along with cheapest-to-most-involved fixes.

---

## 1. Installed versions (all at latest PyPI)

| Package | Installed | Latest on PyPI | Delta |
|---|---|---|---|
| `livekit-agents` | 1.5.6 | 1.5.6 | 0 |
| `livekit-plugins-anthropic` | 1.5.6 | 1.5.6 | 0 |
| `anthropic` | 0.97.0 | 0.97.0 | 0 |

No upgrade path exists. Any fix has to be local (patch / fork / pre-call rewrite).

Release cadence: livekit-agents 1.5.6 shipped 2026-04-22. The upstream `main` branch
has no commits touching `_strict.py` or the anthropic plugin's schema path after
1.5.6 was cut (checked via `gh api repos/livekit/agents/commits`).

---

## 2. Call graph — `@function_tool` → Anthropic HTTP body

```
user decorates fn:
  @function_tool
  async def send(payload: dict[str, Any]): ...
            |
            v   livekit.agents.llm.tool_context.function_tool
            |   (tool_context.py:274-320) wraps into FunctionTool,
            |   stores FunctionToolInfo(name, description, flags).
            |   NOTE: no schema built at decorate time.
            v
agent chat turn:
  LLM.chat(chat_ctx, tools=[send, ...])
            |
            v   livekit.plugins.anthropic.llm:LLM.chat
            |   (llm.py:139-256)
            |   line 169:   tool_ctx = llm.ToolContext(tools)
            |   line 170-172: tool_schemas = tool_ctx.parse_function_tools(
            |                    "anthropic", strict=self._opts.strict_tool_schema)
            |   line 180:   extra["tools"] = tool_schemas
            v
ToolContext.parse_function_tools("anthropic", strict=True)
            |
            v   livekit.agents.llm.tool_context:ToolContext.parse_function_tools
            |   (tool_context.py:525-542)
            |   dispatches to _provider_format.anthropic.to_fnc_ctx
            v
_provider_format.anthropic.to_fnc_ctx(ctx, strict=True)
            |
            v   livekit.agents.llm._provider_format.anthropic
            |   (_provider_format/anthropic.py:130-164)
            |   strict=True branch (default):
            |       fnc = llm.utils.build_strict_openai_schema(tool)
            |       schemas.append({
            |           "name":        function_data["name"],
            |           "description": function_data.get("description") or "",
            |           "input_schema": function_data["parameters"],   # <-- the schema
            |           "strict":      True,                           # <-- triggers "custom" path on server
            |       })
            v
build_strict_openai_schema(tool)
            |
            v   livekit.agents.llm.utils
            |   (utils.py:233-249)
            |   1. model = function_arguments_to_pydantic_model(tool)
            |                (utils.py:310-370 — pydantic v2 create_model from function signature)
            |   2. schema = _strict.to_strict_json_schema(model)
            |   returns {"type":"function", "function":{"name","strict":True,"description","parameters":schema}}
            v
_strict.to_strict_json_schema(pydantic_model)  <-- THE BUG LIVES HERE
            |
            v   livekit.agents.llm._strict
            |   (_strict.py:10-16)
            |   calls model.model_json_schema()
            |   then _ensure_strict_json_schema(schema, ...)
            v
_ensure_strict_json_schema(js, ...)
            |
            v   (_strict.py:32-184)
            |   At lines 58-60:
            |       typ = json_schema.get("type")
            |       if typ == "object" and "additionalProperties" not in json_schema:
            |           json_schema["additionalProperties"] = False
            |   --------- BUG -----------
            |   This ONLY sets additionalProperties when it is MISSING.
            |   Pydantic v2 emits {"type":"object","additionalProperties":true}
            |   verbatim for dict[str, Any]. That `true` is preserved, not overwritten.
            v
anthropic-plugin LLM.chat appends to extra and calls:
  self._client.messages.create(messages=..., tools=[{..., "strict":True, "input_schema":{..., "additionalProperties":true}}], ...)
            |
            v   anthropic.resources.messages.messages:AsyncMessages.create
            |   (messages.py:2382-2462)
            |   builds a literal dict and calls:
            |       await self._post("/v1/messages",
            |                        body=await async_maybe_transform({...}, MessageCreateParams*Streaming),
            |                        options=...)
            v
async_maybe_transform (anthropic/_utils/_transform.py, line 78)
            |
            v   walks the TypedDict tree; tool entries match ToolParam / ToolUnionParam
            |   (anthropic/types/tool_param.py:33 — InputSchema is
            |    Union[InputSchemaTyped, Dict[str, object]] with
            |    set_pydantic_config(InputSchemaTyped, {"extra": "allow"}) at line 29)
            |   -> dict contents pass through unchanged
            v
BaseClient._build_request (anthropic/_base_client.py:490-578)
            |
            v   at line 578:
            |       kwargs["content"] = openapi_dumps(json_data)
            |   openapi_dumps (anthropic/_utils/_json.py:11)
            |       plain json.dumps with custom encoder — no schema mutation
            v
httpx.Request("POST", "https://api.anthropic.com/v1/messages", content=<bytes>)
            |
            v
Anthropic API -> 400 Bad Request
            tools.0.custom.input_schema.properties.<field>.additionalProperties:
                true is not supported.
```

Server path shape: when `strict: true` is on a flat tool (no explicit
`type: "custom"`), the Anthropic API treats it as the custom-tool discriminator
and validates input_schema against strict-mode rules (additionalProperties
must be false everywhere, every property must be required). That is exactly
what `_ensure_strict_json_schema` is supposed to do — but it ships with the
bug above.

---

## 3. Exact source anchors (file:line — everything on the B300 pod)

Prefix: `/opt/prism42/agents/livekit/.venv/lib/python3.12/site-packages/`

### livekit-plugins-anthropic (plugin)

| Location | What it does |
|---|---|
| `livekit/plugins/anthropic/llm.py:59` | `strict_tool_schema: bool` added to `_LLMOptions` (2026-03-28, PR #5259) |
| `livekit/plugins/anthropic/llm.py:78` | `_strict_tool_schema: bool = True` constructor kwarg (underscore prefix = internal) |
| `livekit/plugins/anthropic/llm.py:108` | plumbs `strict_tool_schema=_strict_tool_schema` into opts |
| `livekit/plugins/anthropic/llm.py:166-180` | the only site that builds tool schemas. Fresh `ToolContext` + `parse_function_tools("anthropic", strict=...)` every call — nothing cached |
| `livekit/plugins/anthropic/llm.py:174-178` | `AnthropicTool` provider tools (computer_use etc.) are passed via `to_dict()` — they bypass strict mode entirely |
| `livekit/plugins/anthropic/llm.py:241-256` | dispatch: `self._client.beta.messages.create` if any tool has a `beta_flag`, else `self._client.messages.create`. A monkey patch on ONE path misses the other. |
| `livekit/plugins/anthropic/tools.py:1-46` | `AnthropicTool` / `ComputerUse` — these ship `{"type": tool_version, ...}` straight to the API with no strict mode |

### livekit-agents (SDK)

| Location | What it does |
|---|---|
| `livekit/agents/llm/tool_context.py:274-320` | `@function_tool` decorator. Only captures `name`/`description`/`flags`. NO schema computed at decoration time. |
| `livekit/agents/llm/tool_context.py:236-251` | `@function_tool(..., raw_schema={"name":..., "description":..., "parameters":{...}})` — **BYPASSES** pydantic, uses the supplied schema verbatim. This is the intended escape hatch. |
| `livekit/agents/llm/tool_context.py:520-523` | Only provider `"anthropic"` overload that accepts `strict=bool` (added in PR #5259) |
| `livekit/agents/llm/tool_context.py:525-542` | Dispatcher for `parse_function_tools(format, **kwargs)` |
| `livekit/agents/llm/_provider_format/anthropic.py:130-164` | Actual Anthropic tool-schema builder. `strict=True` branch emits `{"name","description","input_schema","strict":True}`; `strict=False` branch emits `{"name","description","input_schema"}` (no strict). |
| `livekit/agents/llm/_provider_format/anthropic.py:154-162` | `RawFunctionTool` branch — uses `info.raw_schema["parameters"]` directly with NO strict wrapper (confirms raw_schema bypasses the bug) |
| `livekit/agents/llm/utils.py:233-249` | `build_strict_openai_schema(tool)` |
| `livekit/agents/llm/utils.py:310-370` | `function_arguments_to_pydantic_model` — uses `pydantic.create_model` with `get_type_hints(func, include_extras=True)`. Pydantic v2 is used throughout (import `from pydantic import BaseModel, TypeAdapter, create_model`, uses `model_json_schema()`). |
| `livekit/agents/llm/_strict.py:10-16` | `to_strict_json_schema(model)` -> `model.model_json_schema()` then walks it |
| `livekit/agents/llm/_strict.py:59-60` | **THE BUG**: `if typ == "object" and "additionalProperties" not in json_schema: json_schema["additionalProperties"] = False`. Should be unconditional `json_schema["additionalProperties"] = False`. |

### anthropic SDK (wire path)

| Location | What it does |
|---|---|
| `anthropic/resources/messages/messages.py:2382-2462` | `AsyncMessages.create` — sync/async + stream variants are all basically the same. Builds a literal dict, wraps in `async_maybe_transform`, passes to `self._post`. |
| `anthropic/resources/messages/messages.py:944-1023` | `Messages.create` (sync counterpart — just in case your patch targets the wrong class) |
| `anthropic/types/tool_param.py:14-81` | `ToolParam` TypedDict: required `name` + `input_schema`; optional `strict: bool`, optional `type: Literal["custom"]`. `InputSchema = Union[InputSchemaTyped, Dict[str, object]]` so any dict shape passes the typing check. |
| `anthropic/types/tool_param.py:29` | `set_pydantic_config(InputSchemaTyped, {"extra": "allow"})` — extras in input_schema are allowed. |
| `anthropic/types/tool_union_param.py:27-43` | `ToolUnionParam = Union[ToolParam, ToolBash20250124Param, CodeExecutionTool..., MemoryTool..., TextEditor..., WebSearch..., WebFetch..., ToolSearchToolBm25...]`. Flat `ToolParam` does NOT appear wrapped in a `{"type":"custom","custom":{...}}` container — the API server does that nesting internally when `strict:true` is set. |
| `anthropic/_utils/_transform.py:78` | `maybe_transform` — validates/coerces via TypedDict spec. Dict entries under input_schema survive untouched. |
| `anthropic/_base_client.py:490-578` | `_build_request` — line 578: `kwargs["content"] = openapi_dumps(json_data)`. |
| `anthropic/_utils/_json.py:11-24` | `openapi_dumps` = plain `json.dumps` with custom encoder. No schema-level mutation. |

---

## 4. Why the `AsyncMessages.create` monkey-patch failed

Three plausible reasons; likely all three compound:

1. **Two create methods, one patch**. `llm.py:241` uses `self._client.beta.messages.create` whenever any tool has a `beta_flag` (e.g. ComputerUse). `llm.py:250` uses `self._client.messages.create` otherwise. A patch that only hits `anthropic.resources.messages.messages.AsyncMessages.create` misses the beta path (which lives at `anthropic.resources.beta.messages.messages.AsyncMessages.create`). If your patch only targets non-beta, and a `ComputerUse` (or any future beta-flagged tool) is in the tools list, the patch is silently bypassed.

2. **Wrong class (sync vs async)**. `chat()` streams with `stream=True`. The async client is `anthropic.AsyncClient` → `AsyncMessages` (line 1545+). Patching `Messages.create` (sync, line 944+) does nothing here.

3. **Patch mutates kwargs AFTER a bound method captures them**. If the patch wraps `AsyncMessages.create` but `chat()` already formed the awaitable before the patch was applied (module-level init order), the first call sends the pre-patch kwargs. Less likely but worth a runtime `logger.warning(..., stacklevel=2)` confirming the exact `tools=...` payload right before the HTTP write.

Verify which of the three by: (a) log `id(tools[0])` inside the patch AND inside `llm.py` just before `create`; (b) print the final body at `anthropic._base_client._build_request` via a hook. Easier to just skip the patch and fix at the schema builder.

---

## 5. Reproduction (confirmed on the pod)

```python
# On prism-mla-b300-h4h5 with the venv active:
from livekit.agents import llm
from livekit.agents.llm import utils
from typing import Any
import json

@llm.function_tool
async def send_mock_data(payload: dict[str, Any]):
    """Send payload."""
    pass

print(json.dumps(utils.build_strict_openai_schema(send_mock_data), indent=2))
```

Output:

```json
{
  "type": "function",
  "function": {
    "name": "send_mock_data",
    "strict": true,
    "description": "Send payload.",
    "parameters": {
      "properties": {
        "payload": {
          "additionalProperties": true,
          "type": "object"
        }
      },
      "required": ["payload"],
      "type": "object",
      "additionalProperties": false
    }
  }
}
```

The outer object correctly gets `additionalProperties: false` (because it was missing
from the Pydantic output). The nested `payload` field arrives with
`additionalProperties: true` and the walker skips it by the `not in json_schema`
guard — this is the exact schema fragment the Anthropic API rejects.

---

## 6. Recommended fixes — cheapest to most involved

### Fix 1 (cheapest, <5 min) — drop `dict[str, Any]` from any `@function_tool` signature

Model the payload shape explicitly with Pydantic or replace `dict[str, Any]` with
a `Literal` / `str` / typed-fields object. Any concrete typed structure will not
trigger the bug.

```python
from pydantic import BaseModel

class DispatchPayload(BaseModel):
    caller_phone: str
    incident_type: Literal["medical", "fire", "police"]
    location_text: str

@function_tool
async def dispatch(payload: DispatchPayload): ...
```

Pydantic emits `additionalProperties: false` for explicit BaseModel objects and
the pipeline succeeds untouched.

**Effort: minutes. Drawback:** only works if the schema can actually be nailed
down. For genuinely open-shape payloads (e.g. freeform caller-supplied context)
this is not viable.

### Fix 2 (also cheap) — opt out of strict mode per LLM

```python
from livekit.plugins import anthropic as lk_anthropic

llm = lk_anthropic.LLM(
    model="claude-opus-4-7",
    _strict_tool_schema=False,   # <-- added by PR #5259, it is the intended opt-out
)
```

This flips `to_fnc_ctx` to the non-strict branch (`_provider_format/anthropic.py:145-153`),
which omits both `strict: true` AND the `_ensure_strict_json_schema` walk. The
non-strict Anthropic tool path does NOT enforce the `additionalProperties: false`
rule — it accepts Pydantic's native `additionalProperties: true`.

**Effort: one-line change. Drawback:** you lose strict-mode schema conformance
(LLM may emit `"2"` for `int` fields, miss required fields, etc.). For a dispatch
console this is probably acceptable IF your Python-side argument validation
(`prepare_function_arguments` at `utils.py:373-458`) catches coercion issues — it
does, via `model.model_validate(args_dict)` on line 429 and surfaces
`ValidationError` to the LLM via the tool-error path at `utils.py:639-648`.

### Fix 3 (clean, localized) — use `raw_schema=` on the tool

```python
from livekit.agents import function_tool

@function_tool(raw_schema={
    "name": "send_data",
    "description": "Send payload.",
    "parameters": {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "additionalProperties": False,   # <-- explicit
                "properties": {},                # intentionally empty = accept nothing
            },
        },
        "required": ["payload"],
        "additionalProperties": False,
    },
})
async def send_data(raw_arguments: dict[str, object]): ...
```

`RawFunctionTool` bypasses `build_strict_openai_schema` entirely
(`_provider_format/anthropic.py:154-162`) — the schema you supply is sent
verbatim. You retain strict mode (because `to_fnc_ctx` does not wrap
`RawFunctionTool` with `strict:True`… actually wait — re-checking: the
`RawFunctionTool` branch omits the `strict:True` field entirely, so the API
treats it as a non-strict tool). If you want strict enforcement with raw_schema,
add `"strict": true` to the dict literal that `to_fnc_ctx` builds — you'd need a
fork/patch for that.

**Effort: per-tool refactor. Drawback:** loses pydantic arg-model validation
(the function signature must accept `raw_arguments: dict[str, object]`).

### Fix 4 (one-line forked patch to `_strict.py`) — correct the bug

Change `livekit/agents/llm/_strict.py:59-60` from

```python
if typ == "object" and "additionalProperties" not in json_schema:
    json_schema["additionalProperties"] = False
```

to

```python
if typ == "object":
    json_schema["additionalProperties"] = False
```

Apply as a runtime monkey-patch at import time:

```python
# patch_livekit_strict.py — import before constructing the Anthropic LLM
from livekit.agents.llm import _strict as _lk_strict

_original = _lk_strict._ensure_strict_json_schema

def _patched(json_schema, *, path, root):
    result = _original(json_schema, path=path, root=root)
    if isinstance(result, dict) and result.get("type") == "object":
        result["additionalProperties"] = False
    return result

_lk_strict._ensure_strict_json_schema = _patched
```

**Effort: one file, ~10 lines. Drawback:** monkey-patch brittleness; the
recursive call inside the walker (line 157) uses the original function name, so
wrapping only catches the top-level call. Safer: directly patch
`_lk_strict._ensure_strict_json_schema` by replacing the source function
(overwrite via `importlib.reload` + custom source) OR fork `_strict.py` and
pin-install a local copy.

**Even cleaner patch** — modify in place at package-install time in a postinstall
hook or site-packages patch script:

```python
# site-packages patcher, runs once at venv build
import pathlib, re
p = pathlib.Path("/opt/prism42/agents/livekit/.venv/lib/python3.12/site-packages/livekit/agents/llm/_strict.py")
src = p.read_text()
new = src.replace(
    'if typ == "object" and "additionalProperties" not in json_schema:\n        json_schema["additionalProperties"] = False',
    'if typ == "object":\n        json_schema["additionalProperties"] = False',
)
assert new != src, "patch no-op"
p.write_text(new)
```

### Fix 5 (upstream) — submit PR to livekit/agents

The fix in Fix 4 is a 1-line change. Upstream PR would:
1. drop the `and "additionalProperties" not in json_schema` guard
2. add a test for `dict[str, Any]` in `tests/test_strict.py`

Worth doing — this is a real bug that hits anyone with freeform payload tools.
PR #5259 landed cleanly; maintainers are responsive. Draft PR would probably
merge in days.

---

## 7. Practical recommendation

- **Immediate (today)**: Fix 2 — construct the LLM with
  `_strict_tool_schema=False`. One-line production fix, zero risk of monkey-patch
  surprises, keeps the codebase clean. Document the trade-off: arg validation is
  now pydantic-side only (not LLM-side strict), but `prepare_function_arguments`
  already handles coercion errors and surfaces them to the LLM for self-correct.

- **Short-term (this week)**: Fix 4 as a site-packages patch script applied in
  your pod image build. Restores strict-mode benefits.

- **Upstream (when time)**: Fix 5. Contribute back; delete the local patch.

- **Avoid**: continuing to chase the monkey-patch at `AsyncMessages.create`.
  There are three ways it can silently miss (beta path, sync vs async, class
  binding) and the correct fix is upstream of the SDK anyway.

---

## 8. Quick reference — where to stop chasing

- **NOT the anthropic SDK**: `maybe_transform` and `openapi_dumps` both pass
  dict contents verbatim. The bug schema is fully formed BEFORE entering the SDK.
- **NOT the plugin**: `llm.py:170-180` faithfully forwards whatever
  `parse_function_tools` returns.
- **NOT the API server**: Anthropic is correctly rejecting an invalid strict
  schema; the server-side error is a symptom, not the bug.
- **YES in livekit-agents**: `_strict.py:59-60` is the bug. Pydantic v2's
  `dict[str, Any]` emission of `additionalProperties: true` is standards-correct;
  it's the strict-mode walker that has an incomplete guard.
