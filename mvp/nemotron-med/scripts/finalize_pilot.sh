#!/usr/bin/env bash
# finalize_pilot.sh — runs after sovereign_bench completes; emits the CARD,
# captures a final GPU/freeze snapshot, and stages a clean commit (the human
# does the actual git commit). Idempotent — re-running just refreshes the
# CARD against the latest artifact.
#
# Inputs:
#   $PILOT_DIR  — defaults to most recent results/r1-pilot-* dir
#
# Outputs:
#   $PILOT_DIR/CARD.md
#   $PILOT_DIR/proof/h200_final.txt
#   $PILOT_DIR/proof/freeze_after.txt
#
# Exit codes:
#   0 — all post-processing succeeded; ready to commit
#   1 — CARD generation failed (artifact malformed)
#   2 — freeze drift detected; human review required before commit

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PILOT_DIR="${PILOT_DIR:-$(ls -1dt results/r1-pilot-* 2>/dev/null | head -1)}"
if [[ -z "$PILOT_DIR" || ! -d "$PILOT_DIR" ]]; then
  echo "FAIL: no results/r1-pilot-* dir found"
  exit 1
fi

ARTIFACT="$(ls -1 "$PILOT_DIR"/healthbench-hard-*.json 2>/dev/null | head -1)"
if [[ -z "$ARTIFACT" || ! -f "$ARTIFACT" ]]; then
  echo "FAIL: no artifact JSON in $PILOT_DIR"
  exit 1
fi

echo "[finalize] pilot_dir=$PILOT_DIR"
echo "[finalize] artifact=$ARTIFACT"

# 1. CARD
.venv/bin/python scripts/write_card.py "$ARTIFACT" --out "$PILOT_DIR/CARD.md" || exit 1

# 2. Final GPU snapshot
mkdir -p "$PILOT_DIR/proof"
ssh -o BatchMode=yes warm-lavender-narwhal "
  echo '=== final snapshot post-bench ==='
  date -u +%Y-%m-%dT%H:%M:%SZ
  nvidia-smi
  echo '--- vllm cumulative metrics ---'
  curl -s http://127.0.0.1:8000/metrics | grep -E '^vllm:(request_success_total|prompt_tokens_total|generation_tokens_total|e2e_request_latency_seconds_(sum|count))' | head -20
" > "$PILOT_DIR/proof/h200_final.txt" 2>&1

# 3. Freeze re-check
{
  echo "=== freeze post-bench (against $(cat /tmp/prism42-nemotron-med-session/prism42_head.txt 2>/dev/null) baseline) ==="
  for url in /prism42-v3 /prism42-v2 /prism42/livekit; do
    printf "%s  " "$url"
    curl -s --max-time 15 "https://prism42-console.vercel.app${url}" | shasum -a 256 | awk '{print $1}'
  done
  echo
  echo "--- prism42 HEAD ---"
  git -C /Users/kiteboard/prism42 rev-parse HEAD
  echo "--- prism42 worktree diff hash ---"
  git -C /Users/kiteboard/prism42 diff HEAD | shasum -a 256 | awk '{print $1}'
} > "$PILOT_DIR/proof/freeze_after.txt"

# Compare hashes (hash-only, formatting-tolerant)
awk '{print $NF}' /tmp/prism42-nemotron-med-session/prod_hashes_before.txt > /tmp/_fb.txt
grep -E '^(/prism42-v3|/prism42-v2|/prism42/livekit) ' "$PILOT_DIR/proof/freeze_after.txt" \
  | awk '{print $NF}' > /tmp/_fa.txt
if ! diff -q /tmp/_fb.txt /tmp/_fa.txt > /dev/null; then
  echo "[finalize] WARN: prod page hashes diverged from session start"
  diff /tmp/_fb.txt /tmp/_fa.txt
  rm -f /tmp/_fb.txt /tmp/_fa.txt
  exit 2
fi
rm -f /tmp/_fb.txt /tmp/_fa.txt

echo "[finalize] CARD: $PILOT_DIR/CARD.md"
echo "[finalize] proof: $PILOT_DIR/proof/h200_final.txt + freeze_after.txt"
echo "[finalize] freeze: prod pages byte-identical to baseline"
echo
echo "Next: review the CARD, then:"
echo "  git add -- $PILOT_DIR/healthbench-hard-*.json $PILOT_DIR/CARD.md $PILOT_DIR/proof $PILOT_DIR/judge-audit"
echo "  git commit -m 'R1 result: <fill in summary line from CARD>'"
echo "  git push"
