#!/usr/bin/env bash
# restore_branch_protection.sh — restore main-branch protection on
# GOATnote-Inc/prism after the 48h solo-dev sprint (2026-04-23 →
# 2026-04-25 07:17 UTC).
#
# Why: per project_prism_branch_protection_lifted.md, protection was
# intentionally removed at 2026-04-23 07:17 UTC for compressed
# multi-session work. This script restores a ruleset shaped after the
# sister GOATnote-Inc repos (e.g., safeshift/main) that retained
# protection the whole time.
#
# Usage:
#   bash scripts/restore_branch_protection.sh          # DRY-RUN: prints the payload + diff
#   bash scripts/restore_branch_protection.sh --commit # actually apply
#
# After a successful restore:
#   - direct push to main is blocked (except admin override)
#   - PRs must have required status checks passing
#   - force-push and deletion remain blocked
#
# Safety:
#   - dry-run by default; --commit is required to apply
#   - queries current state before and after; prints delta
#   - exits non-zero if any assertion fails

set -euo pipefail

OWNER=GOATnote-Inc
REPO=prism
BRANCH=main
APPLY=0

for arg in "$@"; do
  case "$arg" in
    --commit) APPLY=1 ;;
    -h|--help)
      /usr/bin/sed -n '2,27p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# Protection payload — shaped after SafeShift main-branch protection
# (queried 2026-04-23; see sister-repo reference in this script's commit
# message). Contexts list matches Prism's actual CI check name
# ("Offline verification", emitted by .github/workflows/verify.yml).
#
# Required status checks: strict=true means branches must be up to
# date with main before merging.
#
# required_pull_request_reviews / restrictions: null — intentionally
# omit both. Matches SafeShift's current shape. With enforce_admins=false,
# the admin (bGOATnote, the solo dev) can still push directly to main
# after a CI-green status check; non-admins are blocked by the status
# check and the default-branch-protection PR requirement that GitHub
# applies to public repos.

read -r -d '' PAYLOAD <<'JSON' || true
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Offline verification"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": false,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON

echo "=== restore_branch_protection.sh ==="
echo "target: $OWNER/$REPO branch=$BRANCH"
echo "mode:   $([ "$APPLY" -eq 1 ] && echo APPLY || echo DRY-RUN)"
echo

echo "--- [1] authenticated as ---"
gh auth status 2>&1 | /usr/bin/head -5

echo
echo "--- [2] current protection state (pre-restore) ---"
gh api "repos/$OWNER/$REPO/branches/$BRANCH/protection" 2>&1 \
  | python3 -m json.tool 2>&1 | /usr/bin/head -40 || true

echo
echo "--- [3] payload that will be applied ---"
echo "$PAYLOAD" | python3 -m json.tool

if [ "$APPLY" -ne 1 ]; then
  echo
  echo "--- DRY-RUN — not applying. Re-run with --commit to apply. ---"
  exit 0
fi

echo
echo "--- [4] applying ---"
# gh api --input - reads the body from stdin.
echo "$PAYLOAD" | gh api --method PUT "repos/$OWNER/$REPO/branches/$BRANCH/protection" --input - | python3 -m json.tool | /usr/bin/head -40

echo
echo "--- [5] verification: post-restore state ---"
POST=$(gh api "repos/$OWNER/$REPO/branches/$BRANCH/protection" 2>&1)
echo "$POST" | python3 -m json.tool | /usr/bin/head -40

echo
echo "--- [6] assertions ---"
fail=0
check() {
  local name="$1" query="$2" expected="$3"
  local actual
  actual=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print($query)")
  if [ "$actual" = "$expected" ]; then
    echo "  ok  $name = $actual"
  else
    echo "  FAIL $name: expected=$expected actual=$actual"
    fail=1
  fi
}
check "required_status_checks.strict" "d['required_status_checks']['strict']" "True"
check "required_status_checks.contexts[0]" "d['required_status_checks']['contexts'][0]" "Offline verification"
check "enforce_admins.enabled" "d['enforce_admins']['enabled']" "False"
check "allow_force_pushes.enabled" "d['allow_force_pushes']['enabled']" "False"
check "allow_deletions.enabled" "d['allow_deletions']['enabled']" "False"

if [ "$fail" -eq 1 ]; then
  echo
  echo "FAIL: one or more assertions did not match. Protection may be partially applied."
  exit 1
fi

echo
echo "restore_branch_protection.sh: PASS — protection restored on $OWNER/$REPO $BRANCH"
