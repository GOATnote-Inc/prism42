# Cycle-2BC critic eval — aggregate metrics

- Mode: **LIVE**
- Generated: 2026-04-26T19:05:40+00:00
- Fixtures: 100
- Rows total: 401
- Rows with actionable critic output: 0
- Rows where critic failed: 401
  - Failure modes: {'exception': 398, 'timeout': 3}

## Critic vs FSM agreement

- Agreement rate: **0.0%**
  (risk_flag=='none' AND state_mismatch==False)

## Risk-flag distribution (actionable rows only)

- `none`: 0 (0.0%)
- `low`: 0 (0.0%)
- `medium`: 0 (0.0%)
- `high`: 0 (0.0%)

## State-mismatch flags

- state_mismatch=True: 0
- state_mismatch=True AND risk=high: 0

## Top suggested corrections (most common)

- (none)

## Top-3 state_mismatch examples

- (no state_mismatch=True rows)

## Latency (critic actionable rows)

- p50: 0 ms
- p95: 0 ms
- p99: 0 ms
- avg: 0.0 ms

## Cost (Opus 4.7, $5 / $25 per MTok)

- Total input tokens: 0
- Total output tokens: 0
- Total cost: $0.0000
- Cost per call: $0.000000

## Sources

- Pricing: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-04-26)
- Opus 4.7 sampler kwargs: https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7 (fetched 2026-04-26)
