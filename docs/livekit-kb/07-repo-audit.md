# 07 · Repo Audit — `@function_tool` type-hint surface in `agents/livekit/`

**Date:** 2026-04-23
**Scope:** every `@function_tool`-decorated function under `~/prism42/agents/livekit/`
**Context:** LiveKit Agents' `@function_tool` derives a JSON-schema from the function's
Python type hints. Anthropic's Messages API (2026+) rejects any `type:object` schema
whose `additionalProperties` is `true` or absent. `dict[str, Any]` hints produce
exactly such schemas. The worker currently ships a runtime monkey-patch
(`_patch_anthropic_tool_schemas` in `worker.py:71`) that walks outgoing payloads
and force-injects `additionalProperties: false`. That patch is the reason the
voice path runs at all today — this audit lays the groundwork for removing it by
fixing the declared types at the source.

---

## 1. Inventory

Files in scope:
- `~/prism42/agents/livekit/specialists.py` — 8 `@function_tool` functions
- `~/prism42/agents/livekit/orchestrator.py` — 0 (imports `TOOL_CATALOG`, no tools of its own)
- `~/prism42/agents/livekit/worker.py` — 0 (runtime + monkey-patch)
- `~/prism42/agents/livekit/grader.py` — 0 (plain async functions, not LiveKit tools)
- `~/prism42/agents/livekit/state.py` — 0 (Pydantic + Redis only)
- `~/prism42/agents/livekit/parakeet_stt.py` — 0 (STT plugin)
- `~/prism42/agents/livekit/fish_speech_tts.py` — 0 (TTS plugin)

Non-tool, non-Pydantic functions whose signatures also contain `dict[str, Any]`
(for completeness — not decorated, but reviewed):
- `specialists.py:_emit_specialist_turn` — internal helper, accepts
  `extra_context: dict[str, Any] | None`; **not schema-exposed**, all callers
  pass `None` today.
- `specialists.py:_safe_fallback` — no dict hints.
- `worker.py:_force_additional_properties_false`, `worker.py:_count_by_severity`,
  `worker.py:entrypoint`, `worker.py:_grade_async`, `worker.py:_on_item` — none
  are `@function_tool`.
- `grader.py:grade_turn`, `grader.py:grade_turn_with_shim_fallback` — not
  `@function_tool`; parameter typed `anthropic_client: Any` is fine because it
  is a Python callable not serialized into a tool schema.

### 1a. Every `@function_tool` — signature table

| # | Location (file:line) | Tool name | Parameter | Declared type | Default | Schema-safe for Anthropic? | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `specialists.py:94` | `run_safety_monitor` | `session_id` | `str` | — | yes | scalar |
| 1 | `specialists.py:94` | `run_safety_monitor` | `caller_text` | `str` | — | yes | scalar |
| 1 | `specialists.py:94` | `run_safety_monitor` | `last_specialist_turn` | `dict[str, Any] \| None` | `None` | **NO** | produces `type:object` with `additionalProperties` omitted |
| 1 | `specialists.py:94` | `run_safety_monitor` | *return* | `dict[str, Any]` | — | n/a (return types are not in `input_schema`) | Anthropic does not schema-validate tool returns |
| 2 | `specialists.py:127` | `run_ohca_detector` | `session_id` | `str` | — | yes | scalar |
| 2 | `specialists.py:127` | `run_ohca_detector` | `transcript_so_far` | `str` | — | yes | scalar |
| 2 | `specialists.py:127` | `run_ohca_detector` | *return* | `dict[str, Any]` | — | n/a | — |
| 3 | `specialists.py:166` | `run_intent_verifier` | `session_id` | `str` | — | yes | scalar |
| 3 | `specialists.py:166` | `run_intent_verifier` | `caller_text` | `str` | — | yes | scalar |
| 3 | `specialists.py:166` | `run_intent_verifier` | `transcript_so_far` | `str` | — | yes | scalar |
| 3 | `specialists.py:166` | `run_intent_verifier` | *return* | `dict[str, Any]` | — | n/a | — |
| 4 | `specialists.py:364` | `specialist_intake` | `session_id` | `str` | — | yes | scalar |
| 4 | `specialists.py:364` | `specialist_intake` | `caller_text` | `str` | — | yes | scalar |
| 4 | `specialists.py:364` | `specialist_intake` | *return* | `dict[str, Any]` | — | n/a | — |
| 5 | `specialists.py:379` | `specialist_triage` | `session_id` | `str` | — | yes | scalar |
| 5 | `specialists.py:379` | `specialist_triage` | `caller_text` | `str` | — | yes | scalar |
| 5 | `specialists.py:379` | `specialist_triage` | *return* | `dict[str, Any]` | — | n/a | — |
| 6 | `specialists.py:396` | `specialist_dispatch` | `session_id` | `str` | — | yes | scalar |
| 6 | `specialists.py:396` | `specialist_dispatch` | `caller_text` | `str` | — | yes | scalar |
| 6 | `specialists.py:396` | `specialist_dispatch` | *return* | `dict[str, Any]` | — | n/a | — |
| 7 | `specialists.py:405` | `specialist_pdi` | `session_id` | `str` | — | yes | scalar |
| 7 | `specialists.py:405` | `specialist_pdi` | `caller_text` | `str` | — | yes | scalar |
| 7 | `specialists.py:405` | `specialist_pdi` | *return* | `dict[str, Any]` | — | n/a | — |
| 8 | `specialists.py:414` | `specialist_handoff` | `session_id` | `str` | — | yes | scalar |
| 8 | `specialists.py:414` | `specialist_handoff` | `caller_text` | `str` | — | yes | scalar |
| 8 | `specialists.py:414` | `specialist_handoff` | *return* | `dict[str, Any]` | — | n/a | — |

**Total: 8 `@function_tool` functions, 19 input parameters, of which exactly 1
is problematic.**

### 1b. Problem parameter — the single item to fix

```python
# specialists.py:94-99
@function_tool
async def run_safety_monitor(
    session_id: str,
    caller_text: str,
    last_specialist_turn: dict[str, Any] | None = None,   # <-- HERE
) -> dict[str, Any]:
```

This parameter is the sole reason the `_patch_anthropic_tool_schemas` monkey-patch
exists. The 7 other tools and their 15 other parameters are `str` (already safe) or
are the return type (Anthropic does not validate the shape of a tool's return
value; it passes the stringified JSON straight back into the model's context).

Python type hint `dict[str, Any] | None` typically serializes through LiveKit's
schema derivation (which goes through Pydantic / `inspect` under the hood) as:

```json
{
  "anyOf": [
    {"type": "object"},
    {"type": "null"}
  ]
}
```

The `type:object` branch has no `properties`, no `additionalProperties`. Anthropic's
API returns a 400 of the form:

```
tools.<i>.input_schema: additionalProperties is required to be set to false
```

### 1c. Why return-type `dict[str, Any]` is fine

`input_schema` only describes how the *model* must format its tool call. The
*return* payload is serialized to a JSON string by LiveKit, shoved back into the
model's context as a `tool_result` content block, and never revalidated against
any schema. So `-> dict[str, Any]` is entirely safe — Anthropic does not care.

This matters for the fix strategy: we only have one parameter to fix, not
sixteen.

---

## 2. Minimum code-change fix per problematic signature

There is exactly one problematic signature: `run_safety_monitor.last_specialist_turn`.

### Option A — replace with a Pydantic model (preferred)

```python
class LastSpecialistTurnRef(BaseModel):
    """Compact reference to the previous voice-facing specialist turn.
    Keep narrow — the safety monitor only needs the fields that drive
    re-classification, not the full TurnRecord."""
    agent: str
    turn_id: str
    action: Literal["speak", "defer", "refuse", "escalate", "handoff", "end"]
    content: str | None = None
```

Then:

```python
@function_tool
async def run_safety_monitor(
    session_id: str,
    caller_text: str,
    last_specialist_turn: LastSpecialistTurnRef | None = None,
) -> dict[str, Any]: ...
```

**Pros:** declares exactly the contract; Pydantic emits a strict JSON schema with
`additionalProperties: false` already built in; orchestrator system prompt can
keep the same param name; no change to the callee body (it still serializes the
ref to JSON via `model_dump()`).

**Cons:** adds 5 lines of Pydantic definition; callers (the orchestrator LLM)
must populate the four named fields instead of free-form JSON. In practice the
orchestrator's system prompt already only references the parameter by name, so
this is a schema-level change not a prompt-level change.

### Option B — remove the param entirely, read from `SessionStore`

```python
@function_tool
async def run_safety_monitor(
    session_id: str,
    caller_text: str,
) -> dict[str, Any]:
    store = get_session_store()
    state = store.require(session_id)
    last_turn = state.turns[-1].model_dump() if state.turns else None
    ...
```

**Pros:** the 3rd param disappears; no Pydantic model required; `SessionStore`
is already the structural source of truth, so duplicating the last turn in the
tool call was redundant anyway; orchestrator prompt simplifies by one argument.

**Cons:** requires updating the orchestrator system prompt (`orchestrator.py:96`)
to drop `last_specialist_turn` from the documented signature. Low-risk but
a prompt edit (and therefore a re-evaluation item).

### Option C — `Annotated[dict, Field(..., json_schema_extra={"additionalProperties": False})]`

Theoretically possible but brittle: LiveKit's schema derivation does not
reliably honor `json_schema_extra` on a plain `dict` — it depends on which
Pydantic pathway is hit (some LiveKit versions go through `TypeAdapter`, others
through a hand-rolled derivation). Not recommended.

### Option D — `str` (caller passes a JSON string, callee parses)

```python
async def run_safety_monitor(
    session_id: str,
    caller_text: str,
    last_specialist_turn_json: str | None = None,
) -> dict[str, Any]:
    last = json.loads(last_specialist_turn_json) if last_specialist_turn_json else None
    ...
```

**Pros:** simplest possible fix; zero Pydantic; guaranteed-compatible schema.

**Cons:** pushes all type-safety into runtime; you lose the ability for the
orchestrator LLM to see the expected shape of the value; it also asks the LLM
to emit escaped JSON-in-a-string, which is a known regression for tool-call
accuracy across providers.

### Recommendation

**Option B (remove the param, read from `SessionStore`)** is the smallest,
cleanest fix. The `SessionStore` singleton is already the authority for turn
history; passing `last_specialist_turn` through the tool call duplicated the
data and created the schema problem at the same time. Drop it, and the
monkey-patch in `worker.py` can be retired too.

**Option A (Pydantic model)** is the backup if any downstream caller outside
this repo still wants to pass an explicit override of the last turn (none
currently does).

---

## 3. Proposed diffs

See `~/prism42/docs/livekit-kb/07-proposed-code-fixes.diff`.

The diff shows **both** Option A (Pydantic model) and Option B (remove + read
from SessionStore) in separate hunks — the reader can pick one strategy and
apply the matching hunks. **Neither is applied in this audit.**

---

## 4. Risk + blast radius

### 4a. If we apply Option B (remove `last_specialist_turn`)

| Risk | Where | Mitigation |
|---|---|---|
| Orchestrator system prompt references the old parameter name | `orchestrator.py:96` — the line `run_safety_monitor(session_id, caller_text, last_specialist_turn)` is part of the LLM prompt text | Update the prompt line to `run_safety_monitor(session_id, caller_text)`. 1-line prompt edit. |
| Downstream consumers of `run_safety_monitor` outside this repo | None known. `TOOL_CATALOG` is the only export, and `TOOL_CATALOG` is only imported by `orchestrator.py` inside this same directory. | No-op. |
| `specialists.py:95-111` — the tool body does `json.dumps({"caller_text": ..., "last_specialist_turn": last_specialist_turn})` when building the user message to Sonnet | If we drop the param, we also need to pull `last_specialist_turn` from the SessionStore inside the body | Replace `last_specialist_turn` ref in the `json.dumps({...})` call with a locally-derived `last_turn = state.turns[-1].model_dump() if state.turns else None` |
| Observed behavior change — Sonnet could classify slightly differently because the passed object is now the **last** turn rather than whatever the orchestrator chose to pass | Low. In practice the orchestrator was always passing the last turn anyway; the tool signature just let it pass something else, but nothing in this code does so. | Smoke the safety-monitor with a 3-turn fixture and diff the alerts list before/after. |
| Runtime monkey-patch in `worker.py:52-95` becomes dead code | After Option B, no tool has `dict[str, Any]` as an input hint | Delete `_force_additional_properties_false` and `_patch_anthropic_tool_schemas` entirely — ~45 lines. Optional follow-up; the patch is harmless to leave in place. |

### 4b. If we apply Option A (Pydantic model)

| Risk | Where | Mitigation |
|---|---|---|
| Orchestrator system prompt lists the parameter by name, not by field-structure | `orchestrator.py:96` | No prompt edit needed — the param name is unchanged. |
| LLM tool-call format changes from freeform dict to a 4-field object | 4.7 Opus honors typed tool schemas well, but the tool-call-correctness can dip on the first few turns until the prompt is tuned | Add a one-line example of the expected shape to the tool docstring so Anthropic sees it in the auto-generated `description`. |
| Pydantic import in `specialists.py` | Already present via `state.py`; just add `LastSpecialistTurnRef` to `state.py` and re-export | Trivial |
| Monkey-patch removal | Same as Option B — safe to leave as belt-and-suspenders | Optional |

### 4c. Blast radius on `TOOL_CATALOG` users

`TOOL_CATALOG` is referenced only by `orchestrator.py` (`specialists.py:424-435` exports it; `orchestrator.py:25` imports it). Both changes touch exactly one consumer.

### 4d. Blast radius on Pydantic models

- `state.py` defines `TurnRecord`, `SessionBrief`, `SessionState`, etc.
- `TurnRecord.debug: dict[str, Any]` and `SessionBrief.kq_responses: dict[str, str]`
  are **not** problematic because they are never used as `@function_tool`
  parameters; Pydantic serializes them fine, and they only appear in the
  `SessionStore` (Redis-backed) and inside `model_dump_json()` calls.

### 4e. Blast radius on `_emit_specialist_turn`

The helper accepts `extra_context: dict[str, Any] | None = None`. This is **internal**
(no `@function_tool`) and every call site currently passes `None`. If you want to
keep the monkey-patch removed AND later promote this helper to a tool, you will
need the same fix pattern (Pydantic model or drop).

---

## 5. Follow-up items that fall out of this audit

1. Delete the monkey-patch in `worker.py` once the source-of-truth fix ships.
   That removes ~45 lines of scary-looking AST-walking code from the hot path.
2. Add a unit test that instantiates each `@function_tool` function, inspects
   its derived `input_schema`, and asserts every `type: object` node has
   `additionalProperties: false`. A one-liner against the Anthropic contract.
3. When the 9 remaining specialists (14 total, 5 shipped in Phase 3a) land,
   apply the same rule by default: **no `dict[str, Any]` in `@function_tool`
   signatures, ever.** Either Pydantic model or no param.
4. Consider adding a pre-commit hook that `grep`s `agents/livekit/*.py` for
   `@function_tool[\s\S]*dict\[str,\s*Any\]` in a **parameter** position (not
   return) and fails the commit. Keeps the hard rule self-enforcing.

---

## 6. Appendix — why the return type does NOT need fixing

Anthropic's tool contract for `tools: [{type:"custom", custom:{name, input_schema}}]`
schema-validates the **input** (i.e. how the model formats its tool call).
Tool *results* come back into the model context as:

```json
{"type": "tool_result", "tool_use_id": "...", "content": "<stringified JSON>"}
```

The Messages API never schema-validates that content — it is an opaque string
block from the API's point of view. This is why all 8 tools can keep their
`-> dict[str, Any]` return type with zero consequence.
