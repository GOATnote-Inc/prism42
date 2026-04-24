#!/usr/bin/env bash
# Phase 2-min end-to-end A/B run. Expects these env vars already exported:
#
#   OPENAI_API_KEY             — hosted rubric grader (primary in vercel
#                                mode; shadow in b300 mode)
#   PRISM42_B300_RUBRIC_URL    — http://localhost:8000/v1/chat/completions
#                                (SSH tunnel forwarded from the B300 pod)
#   PRISM42_B300_RUBRIC_TOKEN  — optional bearer; defaults to "unset" if
#                                the vLLM endpoint doesn't require auth
#   PRISM42_ITERATION_ID       — optional; tagged on every row for the
#                                iteration loop
#
# Invocation (from the repo root, with brev port-forward running in
# another terminal):
#
#   cd mvp/911-console-live
#   set -a; source ../../.env; set +a   # or however you load secrets
#   bash scripts/run_ab.sh
#
# Outputs:
#   findings/comparison.jsonl                  — appended every row
#   findings/comparison-summary-<ts>.json     — the aggregate summary
#   stdout Markdown table + "SIGNAL: pass|fail"

set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FIND_DIR="findings"
CMP_LOG="${FIND_DIR}/comparison.jsonl"
SUMMARY="${FIND_DIR}/comparison-summary-${STAMP}.json"

mkdir -p "${FIND_DIR}"

# preflight
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "[run_ab] FATAL: OPENAI_API_KEY not set — source .env first" >&2
  exit 2
fi
if [[ -z "${PRISM42_B300_RUBRIC_URL:-}" ]]; then
  echo "[run_ab] WARNING: PRISM42_B300_RUBRIC_URL not set — b300 mode will fail, vercel mode will write shadow_error rows" >&2
fi

# check that prompt + shared lib are in sync before grading
node scripts/check_prompt_sync.mjs

echo "[run_ab] 1/3 vercel baseline (seeds 1,2,3, 42 × 4 turns × 3 seeds × 2 paths = 504 graded calls)"
node scripts/run_fixture_compare.mjs --mode=vercel --seeds=1,2,3 --path="${CMP_LOG}"

echo "[run_ab] 2/3 b300 augmented (same scenario set)"
node scripts/run_fixture_compare.mjs --mode=b300 --seeds=1,2,3 --path="${CMP_LOG}"

echo "[run_ab] 3/3 aggregate metrics"
node scripts/compare_metrics.mjs --in="${CMP_LOG}" --out="${SUMMARY}"

echo ""
echo "[run_ab] done — summary: ${SUMMARY}"
echo "[run_ab] view: open http://localhost:3042/prism42-b300/compare (after running npm run dev)"
