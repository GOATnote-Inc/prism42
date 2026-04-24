# Voice regression suite

pytest-based guard against the bug classes we've hit this week:

1. **Latency** (`test_latency_slo.py`) — p50/p95 per hop against `slo.yaml`.
2. **No repetition** (`test_no_repetition.py`) — "help is on the way" fires ≤ 1× per call.
3. **No refusal leak** (`test_refusal_rescue.py`) — banned substrings never reach TTS.
4. **TTS backend flag** (`test_tts_backend_flag.py`) — `TTS_BACKEND` env is honored in log.
5. **Parser sanity** (`test_hop_parsers.py`) — the bench-JSON helpers don't rot.

## Run locally (no pod)

```
pytest tests/voice -v -m "not integration"
```

Only parser sanity runs. Fast, no network.

## Run against the pod

```
pytest tests/voice -v -m integration
```

Requires:
- `ssh prism-mla-b300-h4h5` works (see `memory/brev_ssh_bypass.md`).
- `/opt/prism42/agents/livekit/bench_b300.py` present on pod.
- `PyYAML` installed (`pip install pyyaml`).

Integration tests auto-`pytest.skip` when the pod is unreachable — they
don't fail when you're offline.

## Adjusting SLOs

Edit `slo.yaml`. Keep it honest: raising a threshold to make the suite
green is tech debt. Raise only when we're intentionally ceding latency
for correctness.

## CI

`.github/workflows/voice-tests.yml`:
- `unit` job runs `not integration` on every push.
- `integration` job runs on `workflow_dispatch` only (pod SSH key in
  `${{ secrets.BREV_PEM }}`).

## Runbook integration

```
bash scripts/b300_runbook.sh --tests
```

Runs `pytest -m integration -x` against the pod. Exits non-zero on
any failure — wire into on-call escalation.
