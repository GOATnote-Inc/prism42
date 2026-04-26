# Cycle-2I — Practice-Turn Heartbeat Scheduler (BONUS)

**Team:** I
**Charter cross-ref:** cycle-2X autonomic-ops + Team X heartbeat-design
**Goal:** detect address-intake regression within 60 min of any drift,
WITHOUT a human listening to live calls.

---

## Premise

Voice failure modes (silent VAD-fallback, Fish cold-cache, vLLM OOM,
Parakeet model swap) all surface as "agent talks over caller" in
production but produce no exception in the worker process. We need a
self-driving probe that exercises the address-intake pause case once
an hour, asserts barge-in stability, and posts a Slack/journal alert
on regression.

---

## Architecture

```
        +---------------------+
        | systemd timer:      |
        | prism42-heartbeat   |
        | OnUnitActiveSec=1h  |
        +----------+----------+
                   |
                   v
+--------------------------------------+
| heartbeat_runner.py                  |
|   1. mint LiveKit token (probe room) |
|   2. spawn worker.py in test mode    |  <-- isolated subprocess
|   3. drive synthetic_caller fixture  |      to avoid prod-room collisions
|   4. tail journalctl, parse JSON     |
|   5. assert filler/state count       |
|   6. post results -> Redis + Slack   |
+--------------------------------------+
                   |
                   v
        +---------------------+
        | heartbeat history   |
        | (Redis ring buffer) |
        +---------------------+
```

**Why subprocess, not live worker:** running probes against the prod
worker risks crossing call streams with real callers. Subprocess + a
dedicated probe room (`prism42-heartbeat-{epoch}`) keeps the test
hermetic. The worker.py code path is identical — only the room and
fixture audio source differ.

---

## Probe scenarios (rotating set)

```yaml
# /etc/prism42/heartbeat-probes.yaml
probes:
  - name: address_intake_with_pause
    fixture: tests/fixtures/address_dictation_with_pause.wav
    duration_s: 3.0
    assertions:
      max_fillers: 0
      max_speaking_listening_cycles: 1
      response_gate_template_fired: true

  - name: address_then_emergency
    fixture: tests/fixtures/address_then_chest_pain.wav
    duration_s: 5.0
    assertions:
      max_fillers: 1            # one filler OK between turns
      response_started_ms_max: 2000
      reassurance_in_reply: true

  - name: greeting_only
    fixture: null               # zero audio in
    duration_s: 1.0
    assertions:
      greeting_played_ms_max: 800   # cycle-2P file-backed greeting

rotation: round_robin             # one probe per heartbeat tick
report_to:
  - redis://127.0.0.1/heartbeat:results
  - slack://prism42-alerts        # only on FAIL
```

Three probes rotated hourly = each scenario re-tests every 3 hours,
24 runs/scenario/day, generates 72 data points/day for trend analysis.

---

## Self-adjustment (the "evaluate and adjust yourself" requirement)

The heartbeat runner does NOT auto-mutate worker config — autonomic
mutation is too risky for a PSAP runtime. Instead it:

1. Logs every assertion outcome to `redis://heartbeat:results`
2. Computes 24h moving-average pass rate per probe
3. If pass rate <80% on any probe for 6 consecutive hours, fires
   `heartbeat.regression_detected` Slack alert with the failing
   assertion + recent journal lines
4. Optionally writes a one-line proposed env-flag delta to
   `/var/lib/prism42/heartbeat-suggestions.txt` based on the failure
   mode taxonomy (e.g., max_fillers exceeded → suggest raising
   `PRISM42_ENDPOINT_MIN_DELAY_S` by 0.2 s)

Human-in-the-loop applies the suggestion. This matches the cycle-2X
charter §2 "auto-detect, human-mutate" rail and prevents an
unstable feedback loop where the heartbeat tunes itself into a corner.

---

## Minimum viable config snippet

`/etc/systemd/system/prism42-heartbeat.timer`:
```ini
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Unit=prism42-heartbeat.service
```

`/etc/systemd/system/prism42-heartbeat.service`:
```ini
[Service]
Type=oneshot
ExecStart=/opt/prism42/.venv/bin/python /opt/prism42/agents/livekit/heartbeat_runner.py
EnvironmentFile=/etc/prism42/livekit.env
StandardOutput=journal
StandardError=journal
```

That's the whole loop — 23 lines of config, one Python runner (~200
lines), zero changes to the prod worker. Total wall-clock to first
regression detection: ~6 hours from any drift.
