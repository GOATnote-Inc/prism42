# Cycle-2X — Heartbeat Event Schema (Team X)

**Status:** SPEC ONLY. Mirror of `dispatch_publisher.py`'s additive topic-segmented pattern, applied to autonomic-ops telemetry.

## 1. Topics

| Topic | Cadence | Reliability | Consumer |
|---|---|---|---|
| `prism42.heartbeat` | 30 s default (env `PRISM42_AUTONOMIC_TICK_S`) | reliable | frontend ops console (cycle-2X.2 build), incident log |
| `prism42.alert` | event-driven (state transition into `warn` / `degraded` / `failing`) | reliable | frontend banner; pages integrator if `failing` |
| `prism42.action` | event-driven (every auto-recovery attempt) | reliable | audit trail; never silent |
| `prism42.profile_ready` | event-driven (post-Nsight parse) | reliable | frontend "open report" button |
| `prism42.elasticity` | event-driven (pre/post `cuda-checkpoint` transitions) | reliable | frontend GPU-state visualizer |

All topics are **additive** to the existing `prism42.dispatch` channel. The frontend filters by topic; an old client that doesn't know about `prism42.heartbeat` simply ignores it. This mirrors `dispatch_publisher.py:23-29`.

## 2. Heartbeat payload (`prism42.heartbeat`)

```json
{
  "type": "heartbeat",
  "schema_version": 1,
  "timestamp_ms": 1714161000000,
  "tick_index": 142,
  "agent_session_id": "ses_01...",
  "host": "prism-mla-b300-h4h5",
  "state": "nominal | warn | degraded | failing",
  "components": {
    "worker": {"systemd": "active", "last_register_url": "wss://prism42.thegoatnote.com", "uptime_s": 8421},
    "fish":   {"systemd": "active", "synth_queue_depth": 0, "p95_synth_ms": 412, "uptime_s": 8421},
    "vllm":   {"http_8001": "200", "p50_ttft_ms": 51, "decode_tps": 318, "uptime_s": 8421},
    "parakeet": {"http_9100": "200", "uptime_s": 8421},
    "livekit_self": {"docker": "Up 2 hours", "rooms": 1},
    "livekit_cloud_fallback": {"reachable": true}
  },
  "gpu": {
    "utilization_pct": 38,
    "memory_used_gib": 89.4,
    "memory_total_gib": 275,
    "memory_pct": 32.5,
    "temperature_c": 64,
    "power_w": 612,
    "kv_cache_used_gib": 33.6,
    "kv_cache_total_gib": 33.6
  },
  "fsm_summary": {
    "active_rooms": 1,
    "turns_last_60s": 4,
    "intent_distribution_60s": {"gather_address": 1, "cpr_instruct": 0, "reassure": 1, "dispatch": 2}
  },
  "loop_self": {
    "auto_recovery_armed": ["vllm_restart"],
    "auto_recovery_used_30min": [],
    "cooldown_remaining_s": 0,
    "incident_count_today": 0
  }
}
```

**Notes:**
- `kv_cache_*` is best-effort; if vLLM doesn't expose it through `/metrics`, omit the keys (consumer must tolerate absence).
- `fsm_summary` is computed by reading the `prism42.dispatch` topic the heartbeat agent has subscribed to in *read-only* mode — same room, just listening to the existing publisher rather than scraping FSM internals.
- All numeric fields are integers or rounded floats; never NaN/Infinity (JSON-encode reject upstream).

## 3. Alert payload (`prism42.alert`)

```json
{
  "type": "alert",
  "schema_version": 1,
  "timestamp_ms": 1714161030000,
  "agent_session_id": "ses_01...",
  "severity": "warn | degraded | failing",
  "rule_id": "vllm_health_5xx",
  "summary": "vllm :8001/health returned 502 for 3 consecutive ticks",
  "first_observed_ms": 1714160940000,
  "tick_count": 3,
  "evidence": {
    "last_3_responses": ["502", "502", "502"],
    "journalctl_excerpt": "...optional last 5 lines that match..."
  },
  "auto_action": null
}
```

When the agent decides to auto-act, it emits a separate `prism42.action` event after the action completes:

```json
{
  "type": "action",
  "schema_version": 1,
  "timestamp_ms": 1714161045000,
  "rule_id": "vllm_health_5xx",
  "command": "systemctl restart prism42-vllm",
  "state_pre":  {"systemd": "failed", "http_8001": "502"},
  "state_post": {"systemd": "active", "http_8001": "200"},
  "duration_ms": 14821,
  "outcome": "success | failed | partial",
  "cooldown_until_ms": 1714161195000
}
```

## 4. Cadence + tier semantics

- **30 s default** is a compromise: fast enough that a vLLM 5xx is caught within ~1 turn, slow enough that the heartbeat itself contributes < 0.1% CPU on the pod (one `nvidia-smi` query + one `journalctl --since 60s` + one HTTP probe per tick).
- **State tiers (sticky):**
  - `nominal` — all components green, GPU < 70% memory, no auto-recovery used in last 30 min.
  - `warn` — one component degraded, OR GPU 70-85% memory, OR a `prism42.dispatch` reply latency > p95 baseline + 200 ms for last 5 turns. Sticky until 3 consecutive nominal ticks.
  - `degraded` — auto-recovery used in last 5 ticks, OR two components degraded simultaneously. Always emits `prism42.alert`.
  - `failing` — three consecutive auto-recovery attempts on the same component within 30 min, OR `cuda-checkpoint --get-state` returns inconsistent state, OR HBM > 95%. Halts the agent loop and pages the integrator.

## 5. Implementation contract (cf. `dispatch_publisher.py`)

- **Default OFF** behind `PRISM42_AUTONOMIC_HEARTBEAT_PUBLISH=1`. Construction is side-effect-free.
- Drop-oldest queue with `_QUEUE_MAX = 64` (one tick = one event; 64 ticks = 32 min of buffer at 30 s cadence).
- All publishes are best-effort; a failed publish logs and continues. Heartbeat MUST NOT block the agent's tool loop.
- `topic="prism42.heartbeat"`, `reliable=True`, mirroring `dispatch_publisher.py:43-44, 233`.

## 6. Frontend integration (informational only — frontend changes are out of scope for cycle-2X)

```js
room.on('dataReceived', (payload, participant, kind, topic) => {
  if (topic === 'prism42.heartbeat') {
    const ev = JSON.parse(new TextDecoder().decode(payload));
    updateHeartbeatBanner(ev.state, ev.components, ev.gpu);
  }
  if (topic === 'prism42.alert') {
    const ev = JSON.parse(new TextDecoder().decode(payload));
    showAlertToast(ev.severity, ev.summary);
  }
});
```

## 7. What this is NOT

- Not a replacement for `prism42.dispatch`. Both topics ride the same data plane; consumers filter by topic.
- Not a Prometheus / Grafana stack. The autonomic agent is the consumer-of-record; the data-track is the cheap append-only audit channel. If we want histograms and dashboards, that's a separate observability cycle.
- Not bidirectional. The frontend cannot send commands back through `prism42.heartbeat`; that would be a destructive surface, and per the gate matrix in `charter.md` §7, all destructive surfaces are env-flag-gated and not driven from the browser.
