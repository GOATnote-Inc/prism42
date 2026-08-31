# 05 — Anthropic `additionalProperties: true` Debugging Playbook

**Status:** Root cause CAPTURED on `b300-pod` — 2026-04-23.
**Canonical failure mode:** `api.anthropic.com` returns `400 tools.0.custom: additionalProperties: true is not supported` on the first voice-facing turn.
**Binding:** This is a `livekit-plugins-anthropic 1.x` + `anthropic==0.97.0` + Pydantic schema-generation bug when `@function_tool` signatures use `dict[str, Any] | None` type hints.
**TL;DR:** The existing `_force_additional_properties_false` walker in `worker.py` has a guard bug — it only matches `type == "object"` (string), but Pydantic emits `type: ["object", "null"]` (list) for `dict[str, Any] | None` parameters, so the nested node with `additionalProperties: true` passes through untouched.

---

## 1. Enable full SDK debug logging

The Anthropic Python SDK honours `ANTHROPIC_LOG=debug` and emits every httpx request/response to stderr at `DEBUG` level. Two ways to turn it on:

**A. Environment variable (simplest; covers any subprocess):**

Add to `/opt/prism42/.env.agent` (the systemd `EnvironmentFile`):

```
ANTHROPIC_LOG=debug
PYTHONUNBUFFERED=1
```

Then: `sudo systemctl restart prism42-agent && journalctl -u prism42-agent -f`.

**B. Programmatic — drop-in top-of-`worker.py`:**

```python
import logging, os
os.environ.setdefault("ANTHROPIC_LOG", "debug")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("anthropic").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("httpcore").setLevel(logging.INFO)  # httpcore at DEBUG is very noisy
```

**Gotcha:** `ANTHROPIC_LOG=debug` logs the request body, but large multi-tool bodies are truncated in journalctl by default. For full bodies, use the httpx event hook in §3.

---

## 2. Synthesize a tool-call request WITHOUT a live caller

When the worker is idle (no LiveKit room open), reproduce the Anthropic call off-worker with this script. **Do not execute on the pod without approval — this makes a live billable API call.** Output the recipe only:

```python
# /tmp/repro_tools_schema.py
"""Reproduce the tool-schema Anthropic 400 without a live LiveKit job.
Run with: /opt/prism42/agents/livekit/.venv/bin/python /tmp/repro_tools_schema.py
"""
import asyncio, json, os, sys
sys.path.insert(0, "/opt/prism42/agents/livekit")

from livekit.agents import llm as lk_llm
from specialists import TOOL_CATALOG

ctx = lk_llm.ToolContext(TOOL_CATALOG)
# This is the EXACT call the livekit-plugins-anthropic plugin makes at
# llm.py:145: tool_ctx.parse_function_tools("anthropic", strict=True)
schemas = ctx.parse_function_tools("anthropic", strict=True)

print(f"--- {len(schemas)} tool schemas synthesized ---")
for s in schemas:
    print(f"name={s['name']!r}")
    # Print any nested node that has additionalProperties != false
    def walk(node, path=""):
        if isinstance(node, dict):
            ap = node.get("additionalProperties")
            t = node.get("type")
            if ap is not False and (t == "object" or (isinstance(t, list) and "object" in t)):
                print(f"  BAD NODE at {path}: type={t!r} additionalProperties={ap!r}")
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(s["input_schema"], path=s["name"])

# Optional live-call section — DO NOT RUN WITHOUT APPROVAL:
#
# from anthropic import AsyncAnthropic
# async def go():
#     client = AsyncAnthropic()
#     resp = await client.messages.create(
#         model="claude-opus-4-7",
#         max_tokens=256,
#         tools=schemas,
#         messages=[{"role": "user", "content": "hi"}],
#     )
#     print(resp.model_dump_json()[:500])
# asyncio.run(go())
```

---

## 3. Intercept the raw HTTP body via httpx event_hooks

This is the authoritative path. Because the `AsyncAnthropic` client accepts a custom `http_client=`, we can attach `event_hooks={"request": [...]}` that sees the fully serialized JSON body just before it hits the wire.

**Drop-in for `worker.py` (replaces or complements the existing monkey-patch):**

```python
import httpx, json, logging, time, pathlib

CAPTURE_DIR = pathlib.Path("/tmp/anthropic-bodies")
CAPTURE_DIR.mkdir(exist_ok=True)

async def _log_anthropic_request(request: httpx.Request) -> None:
    if "anthropic.com" not in str(request.url):
        return
    try:
        body = json.loads(request.content)
    except Exception:
        return
    fname = CAPTURE_DIR / f"{int(time.time() * 1000)}.json"
    fname.write_text(json.dumps(body, indent=2))
    # also emit a one-line summary to stderr
    tools = body.get("tools", [])
    logging.getLogger("prism42.anthropic").info(
        "anthropic_request url=%s model=%s tools=%d saved=%s",
        request.url, body.get("model"), len(tools), fname,
    )

# Give the plugin a shared AsyncAnthropic that carries our hook.
# livekit-plugins-anthropic accepts client= in its constructor (see llm.py:76).
import anthropic
SHARED_ANTHROPIC_CLIENT = anthropic.AsyncClient(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    http_client=httpx.AsyncClient(
        timeout=5.0,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100),
        event_hooks={"request": [_log_anthropic_request]},
    ),
)
```

Then construct the plugin with:

```python
from livekit.plugins import anthropic as lk_anthropic
llm = lk_anthropic.LLM(model="claude-opus-4-7", client=SHARED_ANTHROPIC_CLIENT)
```

**Read the captured body with:** `ls -lt /tmp/anthropic-bodies/ | head -3` then `cat <path>`.

---

## 4. Captured body — the exact 400-trigger (from pod, 2026-04-23)

Synthesized via §2 script on `b300-pod`. The full strict schema for `run_safety_monitor` as produced by `ToolContext.parse_function_tools("anthropic", strict=True)`:

```json
{
  "name": "run_safety_monitor",
  "description": "Classify the current turn against 8 alert classes.\n\nReturns: {\"alerts\": [...]} per the schema. Recorded directly into\nSessionState.alerts; never spoken.",
  "input_schema": {
    "properties": {
      "session_id": { "type": "string" },
      "caller_text": { "type": "string" },
      "last_specialist_turn": {
        "additionalProperties": true,
        "type": ["object", "null"]
      }
    },
    "required": ["session_id", "caller_text", "last_specialist_turn"],
    "type": "object",
    "additionalProperties": false
  },
  "strict": true
}
```

**Exact offending key path:** `tools[0].input_schema.properties.last_specialist_turn.additionalProperties == true`.

When the plugin wraps this in `{"type": "custom", "custom": <schema>}` for the 2026+ tools envelope, Anthropic's validator reports:

```
tools.0.custom: additionalProperties: true is not supported
```

Same failure surfaces on `run_intent_verifier` / `run_ohca_detector` when/if they grow `dict[str, Any] | None` params. The pattern is **any Python parameter whose runtime type is Optional[Mapping]**.

---

## 5. Why existing monkey-patch misses it

Current code in `worker.py`:

```python
def _force_additional_properties_false(node):
    if isinstance(node, dict):
        if node.get("type") == "object":           # <-- bug: only matches string
            ap = node.get("additionalProperties")
            if ap is True or ap is None:
                node["additionalProperties"] = False
        ...
```

Pydantic renders `dict[str, Any] | None` as `"type": ["object", "null"]` (list), so the equality check `node.get("type") == "object"` is False and the node is never fixed.

Upstream `_ensure_strict_json_schema` in `livekit-agents` ALSO misses it — its guard is `if typ == "object" and "additionalProperties" not in json_schema`, and here `additionalProperties` IS in the schema (explicitly `true`), so the condition is False.

---

## 6. Cleanest patch — httpx-request-hook layer (below the SDK)

Pick the layer that matches your tolerance for coupling to the plugin:

### Option A — fix the walker (minimal diff, keeps existing architecture)

In `/opt/prism42/agents/livekit/worker.py`:

```python
def _force_additional_properties_false(node):
    if isinstance(node, dict):
        t = node.get("type")
        is_object = t == "object" or (isinstance(t, list) and "object" in t)
        if is_object and node.get("additionalProperties") is not False:
            node["additionalProperties"] = False
        for v in node.values():
            _force_additional_properties_false(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _force_additional_properties_false(v)
```

Verified on pod: after this change, the same synthesis script produces `"additionalProperties": false` on `last_specialist_turn`. Keeps the SDK-level `AsyncMessages.create` wrap; zero new deps.

### Option B — httpx-request hook (defense-in-depth, survives SDK code-path changes)

If Anthropic ever adds a non-`AsyncMessages.create` endpoint (streaming wrapper, beta endpoint, Managed Agents passthrough), the SDK-level monkey-patch would miss it. The httpx hook sits below every code path:

```python
# worker.py
import json, httpx, anthropic

def _scrub_additional_properties(node):
    if isinstance(node, dict):
        t = node.get("type")
        if (t == "object" or (isinstance(t, list) and "object" in t)) \
           and node.get("additionalProperties") is not False:
            node["additionalProperties"] = False
        for v in node.values():
            _scrub_additional_properties(v)
    elif isinstance(node, list):
        for v in node:
            _scrub_additional_properties(v)

async def _scrub_hook(request: httpx.Request) -> None:
    if "anthropic.com" not in str(request.url):
        return
    if request.content is None:
        return
    try:
        body = json.loads(request.content)
    except Exception:
        return
    mutated = False
    def walk_and_mark(n):
        nonlocal mutated
        if isinstance(n, dict):
            t = n.get("type")
            if (t == "object" or (isinstance(t, list) and "object" in t)) \
               and n.get("additionalProperties") is not False:
                n["additionalProperties"] = False
                mutated = True
            for v in n.values(): walk_and_mark(v)
        elif isinstance(n, list):
            for v in n: walk_and_mark(v)
    walk_and_mark(body)
    if mutated:
        new_body = json.dumps(body).encode()
        request._content = new_body
        # Recompute Content-Length header
        request.headers["content-length"] = str(len(new_body))

SHARED_CLIENT = anthropic.AsyncClient(
    http_client=httpx.AsyncClient(
        timeout=5.0, follow_redirects=True,
        limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100),
        event_hooks={"request": [_scrub_hook]},
    ),
)
```

Then pass `client=SHARED_CLIENT` to `anthropic.LLM(...)` in the LiveKit plugin construction AND reuse it inside `specialists.py` (`_opus_client` / `_sonnet_client`).

**Recommendation:** ship Option A now (one-line change, already-scoped), and land Option B as a follow-up once the plugin construction is refactored to thread a shared client through both `orchestrator.py` and `specialists.py`. Option A unblocks voice-turn execution today.

---

## 7. Verification commands

After applying Option A, on the pod:

```bash
# 1) Confirm the synthesis no longer shows BAD NODE
/opt/prism42/agents/livekit/.venv/bin/python /tmp/repro_tools_schema.py
# expect: no "BAD NODE" lines

# 2) Restart the worker with debug logging
sudo systemctl restart prism42-agent
journalctl -u prism42-agent -f | grep -E 'anthropic|tool_schema'

# 3) Drive one voice turn through the LiveKit dashboard and confirm no 400
```

Expected log line from `worker.py`: `anthropic.tool_schema_patched` — this is the monkey-patch installation confirmation, not a per-request event. If Option B is active, you'll also see `anthropic_request url=... tools=5 saved=/tmp/anthropic-bodies/<ms>.json` on every call.

---

## 8. Upstream fixes to watch

- `livekit-agents` `_strict.py` line 59 should also gate on `type` being a list. A one-line PR upstream eliminates the need for the monkey-patch entirely. File under: `livekit/agents-js#<next>` once we verify current main.
- The Pydantic v2 behaviour of emitting `type: ["object","null"]` for `Optional[dict[str, Any]]` is correct by JSON Schema draft 2020-12, but interacts poorly with OpenAI strict-mode conventions (which drive the livekit-agents schema pipeline).
