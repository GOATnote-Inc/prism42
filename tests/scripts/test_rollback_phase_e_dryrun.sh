#!/usr/bin/env bash
# test_rollback_phase_e_dryrun.sh -- exercise scripts/rollback_phase_e.sh
# in --dry-run mode and assert the printed plan is what we expect.
#
# This test does NOT SSH anywhere. It only inspects the local script's
# dry-run output (parseable text) for required tokens and absence of
# credential-looking patterns.
#
# Run from anywhere; the test resolves the script via its own path so it
# is robust to CWD.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/rollback_phase_e.sh"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '[%s] %s\n' "$(ts)" "$*"; }
pass() { printf '[%s] PASS %s\n' "$(ts)" "$*"; }
fail() { printf '[%s] FAIL %s\n' "$(ts)" "$*" >&2; exit 1; }

[[ -f "${SCRIPT}" ]] || fail "rollback script not found at ${SCRIPT}"
[[ -x "${SCRIPT}" ]] || fail "rollback script not executable: ${SCRIPT}"

log "running: ${SCRIPT} --dry-run"
set +e
output="$("${SCRIPT}" --dry-run 2>&1)"
rc=$?
set -e

log "exit code: ${rc}"
if [[ "${rc}" -ne 0 ]]; then
  printf '%s\n' "${output}" >&2
  fail "dry-run exit code = ${rc}, expected 0"
fi
pass "dry-run exited 0"

# --- positive assertions: required tokens present ---

require_substring() {
  local needle="$1"; local label="$2"
  if printf '%s' "${output}" | grep -qF -- "${needle}"; then
    pass "found required token: ${label}"
  else
    printf '%s\n' "${output}" >&2
    fail "missing required token: ${label} (looking for: ${needle})"
  fi
}

require_regex() {
  local pattern="$1"; local label="$2"
  if printf '%s' "${output}" | grep -qE -- "${pattern}"; then
    pass "found required pattern: ${label}"
  else
    printf '%s\n' "${output}" >&2
    fail "missing required pattern: ${label} (regex: ${pattern})"
  fi
}

require_substring 'LLM_BACKEND=anthropic' 'target env value (LLM_BACKEND=anthropic)'
require_substring 'systemctl restart prism42-worker' 'systemctl restart command'
# bak suffix: scripts uses .bak.<UTC timestamp> e.g. .bak.20260425T043600Z
require_regex '\.bak\.[0-9]{8}T[0-9]{6}Z' 'bak.<ts> suffix pattern'

# --- negative assertions: zero credential-looking patterns ---

forbid_regex() {
  local pattern="$1"; local label="$2"
  local hits
  hits=$(printf '%s' "${output}" | grep -cE -- "${pattern}" || true)
  if [[ "${hits}" -eq 0 ]]; then
    pass "no credential pattern leaked: ${label}"
  else
    # Print the offending lines for debugging without echoing the secret format
    printf '%s' "${output}" | grep -nE -- "${pattern}" >&2 || true
    fail "credential pattern leaked: ${label} (pattern: ${pattern}, hits: ${hits})"
  fi
}

# Rough-check forbidden patterns. These are conservative -- if the script
# ever starts to print real secrets, these catch it.
forbid_regex 'sk-'        'sk- prefix (Anthropic/OpenAI key shape)'
forbid_regex 'Bearer '    'Bearer authorization header'
forbid_regex ':secret'    ':secret literal'

log "all assertions passed; dry-run plan is well-formed"
echo "OK: rollback_phase_e.sh --dry-run is parseable, complete, and credential-clean"
exit 0
