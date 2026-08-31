# Cycle-2M2 Team M2 — applied patches

**Date:** 2026-04-26
**Operator:** Team M2 (integrator)
**Pod:** b300-pod
**Worker restart:** 17:38:04 UTC, came back active 17:38:05 (registered worker `AW_CWmEF4BNH5P4`)
**vLLM service:** untouched (no restart)

## Patches applied (in mandated order)

| # | Cycle | File | Lines | SHA | Description |
|---|---|---|---|---|---|
| 1 | 2Q2 fix-1 | `agents/livekit/orchestrator.py` | +25/-16 | `fce8115` | Remove `return` inside try block; gate LLM-fallthrough on `if not gate_emitted_template:` so the post-try `raise StopResponse()` actually fires |
| 2 | 2Q2 fix-2 | `agents/livekit/worker.py` | +6/-1 | `b7eb08c` | Extend filler-suppress phase set to include `critical_verify` and `key_questions` |
| 3 | 2P2 A1 | `agents/livekit/dispatcher_fsm.py` | +24/-2 | `d232b44` | Gate cardiac short-circuit on `positive_arrest_cue OR (ambiguous_arrest_cue AND third_party)`; defense-in-depth split, no underlying regex tightening |
| 4 | 2P2 A3 | `agents/livekit/dispatcher_fsm.py` | +6/-0 | `8710f6b` | `_intent_in_verify` calls `_direct_question_intent` first (mirrors `_intent_in_cpr`) |
| 5 | 2P2 C3 | `agents/livekit/dispatcher_fsm.py` | +91/-1 | `f670979` | Spelled-cardinal -> digit normalizer in `classify()`; covers zero..nineteen, twenty..ninety, hundred, thousand combinations |

Total LoC delta across 3 files: **+152/-20**, all additive.

## Per-patch syntax verification (local Python 3.13)

```
python3 -c "import ast; ast.parse(open('agents/livekit/orchestrator.py').read()); print('OK')"  -> OK
python3 -c "import ast; ast.parse(open('agents/livekit/worker.py').read()); print('OK')"          -> OK
python3 -c "import ast; ast.parse(open('agents/livekit/dispatcher_fsm.py').read()); print('OK')"  -> OK
```

Each step ran cleanly after the corresponding edit, before commit.

## Pod deployment

```
scp ~/prism42/agents/livekit/orchestrator.py    b300-pod:/tmp/
scp ~/prism42/agents/livekit/worker.py          b300-pod:/tmp/
scp ~/prism42/agents/livekit/dispatcher_fsm.py  b300-pod:/tmp/
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/orchestrator.py    /opt/prism42/agents/livekit/orchestrator.py'
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/worker.py          /opt/prism42/agents/livekit/worker.py'
ssh b300-pod 'sudo install -o shadeform -g shadeform -m 644 /tmp/dispatcher_fsm.py  /opt/prism42/agents/livekit/dispatcher_fsm.py'
ssh b300-pod 'sudo systemctl restart prism42-worker && sleep 5 && systemctl is-active prism42-worker'
```

File timestamps after install (all 17:37:51 UTC):
```
2026-04-26 17:37:51.525... 37129 /opt/prism42/agents/livekit/orchestrator.py
2026-04-26 17:37:51.529... 74324 /opt/prism42/agents/livekit/worker.py
2026-04-26 17:37:51.533... 35125 /opt/prism42/agents/livekit/dispatcher_fsm.py
```

Worker re-registered 17:38:05 UTC, has been active continuously since.

## Constraints honored

- vLLM service: not restarted (12-min cold-window risk avoided)
- LiveKit URL: unchanged (selfhost worker stays on selfhost)
- Caddy / DNS / frontend backbone: not touched
- Parakeet / Fish / Nemotron service config: not touched
- Single worker restart performed, ~15s of dark window total
- ElevenLabs `/prism42` fallback path: unaffected
