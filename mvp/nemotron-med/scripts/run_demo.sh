#!/usr/bin/env bash
# run_demo.sh — driver for R1 / R2 / R3 sovereign HealthBench sweeps.
#
# This script is a thin orchestrator — it runs ./scripts/preflight.sh first
# (refuses to proceed unless all 6 gates pass), then a 1-example smoke,
# REQUIRES manual artifact-JSON inspection, then if the smoke looks good
# runs the full N=3 paired-design sweep against the appropriate baseline.
#
# Usage:
#   ./scripts/run_demo.sh r1                  # 30-example, N=3, vs Opus 4.7 baseline
#   ./scripts/run_demo.sh r1 --n 5 --trials 1 # cheap iteration
#   ./scripts/run_demo.sh r2                  # adds --rag --guardrails (R2 stack)
#   ./scripts/run_demo.sh r3 --lora med-r64   # base-vs-Med A/B
#
# All artifacts land under results/<round>-<date>/.

set -euo pipefail

ROUND="${1:?expected r1|r2|r3 as first arg}"
shift || true

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

DATE="$(date +%Y%m%d-%H%M%S)"
RESULTS_DIR="results/${ROUND}-${DATE}"
mkdir -p "$RESULTS_DIR"

SERVE_URL="${NEMOTRON_SERVE_URL:-http://127.0.0.1:8000/v1}"
SERVE_MODEL="${NEMOTRON_SERVE_MODEL:-nvidia/Llama-3.1-Nemotron-70B-Instruct-HF}"
JUDGE_URL="${NEMOTRON_JUDGE_URL:-http://127.0.0.1:8000/v1}"
JUDGE_MODEL="${NEMOTRON_JUDGE_MODEL:-nvidia/Llama-3.1-Nemotron-70B-Instruct-HF}"
MANIFEST="${MANIFEST:-corpus/pins/healthbench-hard-1000.yaml}"
N=30
TRIALS=3

# Parse remaining flags (overrides for --n / --trials etc.).
EXTRA_FLAGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --n) N="$2"; shift 2 ;;
    --trials) TRIALS="$2"; shift 2 ;;
    --serve-url) SERVE_URL="$2"; shift 2 ;;
    --judge-url) JUDGE_URL="$2"; shift 2 ;;
    *) EXTRA_FLAGS+=("$1"); shift ;;
  esac
done

log() { printf "[run_demo:%s] %s\n" "$ROUND" "$*"; }

log "preflight..."
./scripts/preflight.sh

# ---------------------------------------------------------------------------
# Smoke — 1 example, READ the artifact before scaling up
# ---------------------------------------------------------------------------
SMOKE_OUT="${RESULTS_DIR}/smoke.json"
log "smoke (1 example) -> $SMOKE_OUT"
.venv/bin/python scripts/sovereign_bench.py \
  --manifest "$MANIFEST" \
  --serve-url "$SERVE_URL" \
  --serve-model "$SERVE_MODEL" \
  --judge-url "$JUDGE_URL" \
  --judge-model "$JUDGE_MODEL" \
  --smoke \
  --out "$SMOKE_OUT"

log "smoke artifact written; SPOT-CHECK before continuing:"
log "   - At least one trial_results[0].per_example[0].score should be non-null and non-zero."
log "   - judge_incomplete should be small (<10% of rubric items)."
log "   - response field should be a real medical reply (not empty / not refusal)."

# Heuristic auto-check; STILL not a substitute for a human read.
SCORE=$(.venv/bin/python -c "
import json, sys
d = json.load(open('$SMOKE_OUT'))
tr = d['trial_results'][0] if d.get('trial_results') else {}
ex = tr.get('per_example', [{}])[0]
print(ex.get('score'))
")

case "$SCORE" in
  None|null|"") log "FAIL: smoke score is None — judge likely 401 or rubric all-recused. STOP."; exit 1 ;;
  0|0.0) log "WARN: smoke score is exactly 0.0 — could be legit, could be silent judge failure. INSPECT $SMOKE_OUT before --commit."; ;;
  *) log "smoke score: $SCORE (looks live)" ;;
esac

# ---------------------------------------------------------------------------
# Full sweep
# ---------------------------------------------------------------------------
FULL_OUT="${RESULTS_DIR}/healthbench-hard-n${N}-trials${TRIALS}.json"
log "full sweep (n=$N trials=$TRIALS) -> $FULL_OUT"
.venv/bin/python scripts/sovereign_bench.py \
  --manifest "$MANIFEST" \
  --serve-url "$SERVE_URL" \
  --serve-model "$SERVE_MODEL" \
  --judge-url "$JUDGE_URL" \
  --judge-model "$JUDGE_MODEL" \
  --n "$N" \
  --trials "$TRIALS" \
  --out "$FULL_OUT" \
  "${EXTRA_FLAGS[@]:-}"

log "full sweep complete: $FULL_OUT"
log ""
log "Next: write CARD.md under $RESULTS_DIR with paired-design CI vs the baseline (Opus 4.7 0.196 +/- 0.068 for r1)."
