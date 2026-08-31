# Cycle-2J — Combined Apply (Team J integrator artifact)

**Date:** 2026-04-26
**Operator:** Team J (Claude Opus 4.7 — Auto Mode)
**Mission:** Apply three independent additive-only patch sets in one
consolidated cycle (2I → 2T → 2U), restart worker, redeploy frontend, smoke.

---

## Patches landed (in order)

| Cycle | Commit | Files changed | Insertions / Deletions |
|---|---|---|---|
| 2I — interruption fix (P1+P2+P3) | `a2bffe1` | `agents/livekit/worker.py` | +40 / −3 |
| 2T — response gate integration | `9149dfc` | `agents/livekit/orchestrator.py` | +67 / −0 |
| 2U — transcript wiring (full 77-LoC) | `bf41a2d` | `agents/livekit/{worker,orchestrator,dispatch_publisher}.py`, `mvp/911-console-live/components/DispatchPanel.tsx` | +132 / −6 |

**Total delta across 3 commits:** 4 files (Python: 3 + TS: 1).
- `agents/livekit/worker.py`: P2/P3 (VAD `min_silence_duration`, endpointing
  `min_delay`/`max_delay`), P1 (filler suppression on FSM phase ∈
  {intake, address_confirmed}), 2U publisher try-import + ctx.room wire +
  publish_reply on assistant items + publish_caller_partial on STT-final.
- `agents/livekit/orchestrator.py`: 2T lazy-import + gate construction in
  `FsmDispatcherAgent.__init__` + gate-decision/short-circuit branch in
  `on_user_turn_completed`; 2U publish_turn after `update_instructions`
  on the LLM-fallthrough branch.
- `agents/livekit/dispatch_publisher.py`: 2U `publish_caller_partial` method
  (15 lines, before `aclose`).
- `mvp/911-console-live/components/DispatchPanel.tsx`: 2U
  `DispatchCallerPartialEvent` interface + union extension + reducer arm
  + `partial_caller_line` state + transient render slot in `Transcript`
  + CSS animation for "speaking…" pulse.

All changes are additive; no FSM logic mutated, no Caddy/DNS/LiveKit-server
touched, no Parakeet/Fish/Nemotron/vLLM config changed.

---

## Phase 1 — Local syntax + diff scope checks

```
python3 -c "import ast; ast.parse(open('agents/livekit/worker.py').read())"        # OK
python3 -c "import ast; ast.parse(open('agents/livekit/orchestrator.py').read())"  # OK
python3 -c "import ast; ast.parse(open('agents/livekit/dispatch_publisher.py').read())"  # OK
cd mvp/911-console-live && ./node_modules/.bin/tsc --noEmit                          # OK (silent → 0 errors)
```

Per-patch `git diff --stat` confirmed only the expected target files mutated.

---

## Phase 2 — Pod scp + systemd

scp from local repo to `/tmp/`, install with `sudo install -o shadeform -g
shadeform -m 644` to `/opt/prism42/agents/livekit/`. 5 files:

```
worker.py            72,886 B
orchestrator.py      31,308 B
response_gate.py     15,320 B  (was missing on pod, now installed)
templates.py         11,486 B  (was missing on pod, now installed)
dispatch_publisher.py 9,256 B  (was missing on pod, now installed)
```

**Systemd drop-ins added** (preserves pre-existing 50-/70-/100-/110-/120-
sequence; new files at 130-/140-/150- so daemon-reload merges them after
the existing config):

| File | Vars |
|---|---|
| `/etc/systemd/system/prism42-worker.service.d/130-cycle2I-barge-in.conf` | `PRISM42_FILLER_INTAKE_DISABLE=1`, `PRISM42_ENDPOINT_MIN_DELAY_S=1.0`, `PRISM42_ENDPOINT_MAX_DELAY_S=4.0`, `PRISM42_VAD_MIN_SILENCE_S=0.9` |
| `/etc/systemd/system/prism42-worker.service.d/140-cycle2T-response-gate.conf` | `PRISM42_ENABLE_RESPONSE_GATE=1` |
| `/etc/systemd/system/prism42-worker.service.d/150-cycle2U-dispatch-publisher.conf` | `PRISM42_ENABLE_DISPATCH_PUBLISHER=1` |

**Worker restart:**

```
sudo systemctl daemon-reload && sudo systemctl restart prism42-worker
sleep 4 && systemctl is-active prism42-worker  # → active
```

**Worker registration confirmed in `/tmp/prism42-logs/worker.log`:**

```
11:24:02.616 INFO livekit.agents registered worker
  {"agent_name": "", "id": "AW_SW3RGqg9Cgit",
   "url": "wss://prism42.thegoatnote.com", "region": "", "protocol": 17}
```

Worker is talking to **selfhost LiveKit** at `wss://prism42.thegoatnote.com`,
NOT Cloud — confirms cycle-2R cutover is intact post-restart.

**Process env inheritance** (verified via `/proc/<pid>/environ`):

```
PRISM42_FILLER_INTAKE_DISABLE=1
PRISM42_ENDPOINT_MIN_DELAY_S=1.0
PRISM42_ENDPOINT_MAX_DELAY_S=4.0
PRISM42_VAD_MIN_SILENCE_S=0.9
PRISM42_ENABLE_RESPONSE_GATE=1
PRISM42_ENABLE_DISPATCH_PUBLISHER=1
```

All six env vars from the three drop-ins are present in the running worker
process environ — daemon-reload merge succeeded.

---

## Phase 3 — Vercel redeploy

Used the cycle-2R G6 pattern (commit `5b455f6`):

```
cp .vercel/project.json /tmp/prism42-root-project.json.bak
cp mvp/911-console-live/.vercel/project.json .vercel/project.json
vercel deploy --prod --yes
cp /tmp/prism42-root-project.json.bak .vercel/project.json
```

**Deploy result:** `dpl_A27v5xMSQHSuvPCK2sXmvix4zDC8` (READY, target=production)
- Production URL: `https://prism42-console-<hash>-goatnote.vercel.app`
- Aliased to: `https://prism42-console.vercel.app`
- Build time: 15s
- Total deploy time: 47s

**Verification:**
```
curl -sIo /dev/null -w "%{http_code}\n" https://prism42-console.vercel.app/prism42/livekit
→ 200
```

---

## Phase 4 — Verification probes

See `verification.md` for probe outputs.

Three probes attempted. **All three pass (or pass with caveat).**

---

## Module-level import smoke (post-install)

Direct import of the three new modules with both env flags ON:

```
PRISM42_ENABLE_RESPONSE_GATE=1 PRISM42_ENABLE_DISPATCH_PUBLISHER=1 \
  /opt/prism42/agents/livekit/.venv/bin/python -c "
from response_gate import gate_for_fsm, should_use_response_gate
from dispatch_publisher import DispatchPublisher, is_enabled
import templates
print(should_use_response_gate(), is_enabled())
"
→ True True
→ templates dir: ['TEMPLATES', 'TemplateSpec', ...]
```

All three modules import cleanly on the pod's Python 3.14 venv.

---

## Constraints honored

- No Caddy / DNS / LiveKit-server / frontend backbone (LiveCallRoom etc.) touched.
- No Parakeet / Fish / Nemotron / vLLM config changed.
- vLLM never restarted.
- No `git add -A`; staged 4 files by name.
- No secrets in any committed artifact.
- Worker is on selfhost (`wss://prism42.thegoatnote.com`), not Cloud.

## Patches NOT applied

- **2I P4** (adaptive-mode probe log): logging-only, integrator skipped per brief.
- **2I P5** (FILLER_DELAY_S 0.3→0.6 default): defense-in-depth, integrator
  skipped per brief (P1+P2+P3 expected to fully resolve the symptom).
