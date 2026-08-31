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
- `ssh b300-pod` works (see `memory/brev_ssh_bypass.md`).
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

## LLM backend acceptance (Phase D strict gates)

`test_llm_backend_acceptance.py` runs the 5-gate acceptance protocol from
`docs/livekit-kb/25-b300-purr-migration-plan.md §Phase D acceptance` against
any LLM backend. Every future backend swap gets the same check.

### Anthropic baseline

```
LLM_BACKEND=anthropic \
ANTHROPIC_API_KEY=... \
pytest tests/voice/test_llm_backend_acceptance.py -v
```

SLO profile applied: **cloud** (warmed-p95 TTFT < 700 ms, tok/s p50 >= 30).

### Local vLLM (B300 Nemotron)

```
LLM_BACKEND=vllm-local \
LLM_BACKEND_BASE_URL=http://127.0.0.1:8001/v1 \
LLM_BACKEND_MODEL=nemotron-nano \
pytest tests/voice/test_llm_backend_acceptance.py -v
```

SLO profile applied: **local** (warmed-p95 TTFT < 200 ms, tok/s p50 >= 30).

### Any other cloud backend (e.g. Groq, Together, OpenRouter)

```
LLM_BACKEND=groq \
LLM_BACKEND_BASE_URL=https://api.groq.com/openai/v1 \
LLM_BACKEND_MODEL=llama-3-70b-8192 \
OPENAI_API_KEY=gsk_... \
pytest tests/voice/test_llm_backend_acceptance.py -v
```

SLO profile applied: **cloud** (same as Anthropic).

### What fires on failure

Each gate failure raises `AssertionError` naming the exact gate(s):

- `gate_3a_warmed_p95_ttft` — warmed-p95 TTFT exceeded threshold.
- `gate_3b_tokens_per_sec` — tokens/sec p50 below 30.
- `gate_3c_no_exceptions` — at least one request errored.
- `gate_3d_jit_penalty` — sample-1 / warmed-median ratio > 3.0×.
- Gate 2 (`test_gate2_attention_backend`) — backend classified DEGRADED or UNKNOWN
  (vLLM-local only; blocks Phase E).
- Gate 5 (`test_gate5_services_listening`) — Parakeet or Fish dead after bench.

Findings JSON written to `findings/b300_bench/<UTC>-test_llm_backend_acceptance.json`.
Thresholds live in `tests/voice/slo.yaml` under `llm_backend:`.

## Runbook integration

```
bash scripts/b300_runbook.sh --tests
```

Runs `pytest -m integration -x` against the pod. Exits non-zero on
any failure — wire into on-call escalation.
