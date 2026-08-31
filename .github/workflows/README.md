# GitHub Actions

## `verify.yml` — Offline verification

Runs on every push and pull request to `main`. Two jobs:

1. **prism42 cleanliness check** — four greps over tracked content
   (vendor-identifier strings, personal-identifier strings, an
   internal-paths denylist, and upstream-SHA pins). Any hit fails the job.
2. **Tests (pytest)** — Python 3.12, installs `jsonschema`, `pytest`,
   `pytest-asyncio`, `pyyaml`, `numpy`, `structlog`; clones
   `openai/simple-evals` into `third_party/simple-evals` at the pinned
   SHA (see `third_party/README.md` §4) so the HealthBench grader-bridge
   tests run rather than skip; then runs
   `scripts/check_pipeline_invariants.py` (L4),
   `scripts/validate_artifacts.py` against the golden case (L1+L3), and
   `python -m pytest tests/ -q`. Any failure fails the job — nothing is
   masked.

**Does NOT:** make API calls, allocate GPU, register Managed Agents, or consume
any secret. No `ANTHROPIC_API_KEY` / `RUNPOD_API_KEY` / `LAMBDA_API_KEY` is read.

Real Managed Agents registration and harness runs are gated behind `COMMIT=1`
and run only manually via `make register-agents COMMIT=1` /
`make harness-run CASE=... COMMIT=1` with an API key set locally.
