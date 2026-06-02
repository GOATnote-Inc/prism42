#!/usr/bin/env bash
# preflight.sh — six checks before any GPU sweep on the Brev pods.
#
# This script REFUSES to exit 0 unless every gate passes. Halting noisy
# is the entire point — see CLAUDE.md §4 (verify-then-claim) and
# memory/feedback_eval_preflight_judge_key.md (judge-401 silently zeroes
# every reward; resume cannot detect).
#
# Run from repo root on the laptop. ssh tunnels to pods are required to
# be open (see DEMO.md once it lands).

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SESSION_DIR="${SESSION_DIR:-/tmp/prism42-nemotron-med-session}"
mkdir -p "$SESSION_DIR"

GATES_PASSED=0
GATES_TOTAL=6

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
gate()   { printf "[%d/%d] %s ... " "$1" "$GATES_TOTAL" "$2"; }
pass()   { green "PASS"; GATES_PASSED=$((GATES_PASSED + 1)); }
fail()   { red "FAIL"; red "  -> $*"; }

# ---------------------------------------------------------------------------
# 1. HF_TOKEN set + valid (gated-model access for Llama-3.1-Nemotron-70B)
# ---------------------------------------------------------------------------
gate 1 "HF_TOKEN authenticates"
if [[ -z "${HF_TOKEN:-}" ]]; then
  fail "HF_TOKEN not set in env. Source .env or export HF_TOKEN."
elif command -v huggingface-cli >/dev/null 2>&1; then
  if HF_TOKEN="$HF_TOKEN" huggingface-cli whoami >/dev/null 2>&1; then
    pass
  else
    fail "huggingface-cli whoami failed; token invalid or expired."
  fi
else
  # No CLI available; check via raw HTTP.
  if curl -sf -H "Authorization: Bearer $HF_TOKEN" \
       https://huggingface.co/api/whoami-v2 >/dev/null; then
    pass
  else
    fail "HF whoami-v2 returned non-200; token invalid."
  fi
fi

# ---------------------------------------------------------------------------
# 2. Sovereign serve endpoint responds (NEMOTRON_SERVE_URL)
# ---------------------------------------------------------------------------
gate 2 "Nemotron serve endpoint healthy"
SERVE_URL="${NEMOTRON_SERVE_URL:-http://127.0.0.1:8000/v1}"
if [[ ! "$SERVE_URL" =~ ^http://(127\.0\.0\.1|localhost) ]]; then
  fail "NEMOTRON_SERVE_URL=$SERVE_URL is not local; sovereign stack only allows ssh-tunneled localhost."
elif curl -sf --max-time 10 "$SERVE_URL/models" >/dev/null 2>&1; then
  pass
elif curl -sf --max-time 10 "${SERVE_URL%/v1}/v2/health/ready" >/dev/null 2>&1; then
  pass
else
  fail "no response from $SERVE_URL/models. Is the H200 ssh tunnel open and Triton/NIM running?"
fi

# ---------------------------------------------------------------------------
# 3. Sovereign judge endpoint responds (NEMOTRON_REWARD_URL or JUDGE_URL)
# ---------------------------------------------------------------------------
gate 3 "Sovereign judge endpoint healthy"
JUDGE_URL="${NEMOTRON_REWARD_URL:-http://127.0.0.1:8001}"
if [[ ! "$JUDGE_URL" =~ ^http://(127\.0\.0\.1|localhost) ]]; then
  fail "judge URL is not local: $JUDGE_URL"
elif curl -sf --max-time 10 "$JUDGE_URL/health" >/dev/null 2>&1 \
     || curl -sf --max-time 10 "$JUDGE_URL/v1/models" >/dev/null 2>&1; then
  pass
else
  fail "no response from $JUDGE_URL. Is the H100 judge ssh tunnel open?"
fi

# ---------------------------------------------------------------------------
# 4. nvidia-smi healthy on at least one pod (read-only probe)
# ---------------------------------------------------------------------------
gate 4 "GPU live on serve pod"
if ssh -o BatchMode=yes -o ConnectTimeout=10 warm-lavender-narwhal \
     'nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader' \
     >"$SESSION_DIR/h200_gpu.txt" 2>&1; then
  pass
  yellow "  $(cat "$SESSION_DIR/h200_gpu.txt")"
else
  fail "ssh to warm-lavender-narwhal nvidia-smi failed; pod may be down or ssh blocked."
fi

# ---------------------------------------------------------------------------
# 5. No prod-URL leak in current working tree (run hooks against tracked files)
# ---------------------------------------------------------------------------
gate 5 "No prod-URL leak in tracked files"
cd "$REPO"
if git ls-files | xargs -0 -I{} echo {} | tr '\n' '\0' \
     | xargs -0 ./scripts/hooks/no_prod_url_leak.sh >/dev/null 2>&1; then
  pass
else
  fail "prod-URL hook tripped; run pre-commit run --all-files for details."
fi

# ---------------------------------------------------------------------------
# 6. Public prism42 baseline still intact (HEAD + worktree-diff hash)
# ---------------------------------------------------------------------------
gate 6 "Public prism42 freeze intact"
expected_head="$(cat "$SESSION_DIR/prism42_head.txt" 2>/dev/null || true)"
if [[ -z "$expected_head" ]]; then
  yellow "no prism42_head.txt baseline; run 'make freeze-baseline' first"
  fail "missing baseline; cannot verify freeze"
else
  current_head="$(git -C /Users/kiteboard/prism42 rev-parse HEAD)"
  current_hash="$(git -C /Users/kiteboard/prism42 diff HEAD | shasum -a 256 | awk '{print $1}')"
  expected_hash="$(cat "$SESSION_DIR/prism42_worktree_hash.txt" 2>/dev/null || true)"
  if [[ "$current_head" = "$expected_head" && "$current_hash" = "$expected_hash" ]]; then
    pass
  else
    fail "prism42 HEAD or worktree drifted. STOP and surface to user."
    yellow "  expected HEAD=$expected_head"
    yellow "  current  HEAD=$current_head"
    yellow "  expected diff hash=$expected_hash"
    yellow "  current  diff hash=$current_hash"
  fi
fi

# ---------------------------------------------------------------------------
echo ""
if [[ "$GATES_PASSED" -eq "$GATES_TOTAL" ]]; then
  green "preflight: $GATES_PASSED/$GATES_TOTAL gates passed"
  exit 0
else
  red "preflight: $GATES_PASSED/$GATES_TOTAL gates passed"
  red "REFUSING to proceed. Resolve the failed gates and re-run."
  exit 1
fi
