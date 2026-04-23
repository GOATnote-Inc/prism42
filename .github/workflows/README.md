# GitHub Actions

## `verify.yml` — Verify (offline)

Runs on every push and pull request. Creates a fresh Python 3.12 venv, installs
`jsonschema`, `pytest`, `pyyaml`, and `anthropic` (import-only), then runs the
five offline layers in order: `make verify`, `make verify-t3`,
`scripts/check_pipeline_invariants.py`, `scripts/validate_artifacts.py` against
the golden case, and `pytest tests/`. Any failure fails the job.

**Does NOT:** make API calls, allocate GPU, register Managed Agents, or consume
any secret. No `ANTHROPIC_API_KEY` / `RUNPOD_API_KEY` / `LAMBDA_API_KEY` is read.

Real Managed Agents registration and harness runs are gated behind `COMMIT=1`
and run only manually via `make register-agents COMMIT=1` /
`make harness-run CASE=... COMMIT=1` with an API key set locally.
