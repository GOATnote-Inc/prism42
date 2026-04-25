#!/usr/bin/env bash
# rollback_phase_e.sh -- one-shot rollback from local vLLM (Phase E) back
# to the Anthropic API path on the prism42 LiveKit worker pod.
#
# Phase E flipped LLM_BACKEND=vllm-local in /opt/prism42/agents/livekit/.env
# and restarted prism42-worker. If the in-flight Team E E2E voice
# attestation discovers an unrecoverable issue with the local vLLM path,
# this script flips the worker back to LLM_BACKEND=anthropic in one shot.
#
# Usage:
#   bash scripts/rollback_phase_e.sh                       # APPLY (default)
#   bash scripts/rollback_phase_e.sh --dry-run             # print steps only, no SSH
#   bash scripts/rollback_phase_e.sh --host <ssh-target>   # override SSH host
#
# Safety:
#   - dry-run prints every SSH command that would run, including the
#     exact sed expression and bak-suffix pattern. Does NOT connect.
#   - apply path uses sudo on the pod for /opt writes and systemctl.
#   - sed targets the single LLM_BACKEND= key=value line; the .env file
#     is never echoed and contents are never read into the local
#     conversation. Backup is preserved on the pod via -i.bak.<ts>.
#   - L1 verify (env), L2 wait-active, L3 verify env post-restart,
#     L4 minimal HTTP probe to api.anthropic.com (no auth, head-check).
#   - exits non-zero with a clear message on the first failed step.
#
# Per CLAUDE.md verification discipline: no claim of "rolled back" without
# the systemctl active state confirmed AND the env value re-read.

set -euo pipefail

DRY_RUN=0
SSH_HOST="prism-mla-b300-h4h5"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --host)    SSH_HOST="${2:?--host requires an ssh target}"; shift 2 ;;
    -h|--help)
      /usr/bin/sed -n '2,30p' "$0"
      exit 0
      ;;
    *) echo "ERR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

ENV_PATH="/opt/prism42/agents/livekit/.env"
SERVICE="prism42-worker"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BAK_SUFFIX=".bak.${TS}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '[%s] %s\n' "$(ts)" "$*"; }
fail() { printf '[%s] FAIL step=%s: %s\n' "$(ts)" "$1" "$2" >&2; exit 1; }

# Build the exact sed expression once. -i.bak.<ts> preserves a backup.
# Anchored to ^LLM_BACKEND= and $ so we never substitute mid-line.
SED_EXPR='s|^LLM_BACKEND=.*$|LLM_BACKEND=anthropic|'
SED_CMD="sudo sed -i${BAK_SUFFIX} -E '${SED_EXPR}' ${ENV_PATH}"

log "rollback_phase_e.sh starting"
log "  host=${SSH_HOST}"
log "  env_path=${ENV_PATH}"
log "  service=${SERVICE}"
log "  bak_suffix=${BAK_SUFFIX}"
log "  mode=$([ "${DRY_RUN}" -eq 1 ] && echo DRY-RUN || echo APPLY)"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "--- DRY-RUN: SSH commands that would run, in order ---"
  cat <<DRY
  [1/6] ssh ${SSH_HOST} 'systemctl show ${SERVICE} -p Environment'
        # purpose: print before-state of LLM_BACKEND
  [2/6] ssh ${SSH_HOST} '${SED_CMD}'
        # purpose: in-place rewrite of LLM_BACKEND= line; backup preserved at ${ENV_PATH}${BAK_SUFFIX}
        # sed expression: ${SED_EXPR}
  [3/6] ssh ${SSH_HOST} 'sudo systemctl restart ${SERVICE}'
        # purpose: pick up new env
  [4/6] ssh ${SSH_HOST} 'for i in 1 2 ... 15; do systemctl is-active ${SERVICE} && break; sleep 1; done'
        # purpose: wait up to 15s for active state
  [5/6] ssh ${SSH_HOST} 'systemctl show ${SERVICE} -p Environment'
        # purpose: confirm LLM_BACKEND=anthropic post-restart
  [6/6] ssh ${SSH_HOST} 'curl -sS -o /dev/null -w "%{http_code}" --max-time 10 https://api.anthropic.com/v1/messages -X POST -H "content-type: application/json" --data "{}"'
        # purpose: minimal head-check (200/400/401 = reachable; timeout = broken)
DRY
  log "DRY-RUN: pre-flight checks"

  # Pre-flight: confirm ssh client and date are available locally; nothing
  # is exfiltrated, no SSH connection is opened.
  command -v ssh >/dev/null 2>&1 || fail "preflight" "ssh not on PATH"
  command -v sed >/dev/null 2>&1 || fail "preflight" "sed not on PATH"
  command -v date >/dev/null 2>&1 || fail "preflight" "date not on PATH"

  # Confirm sed expression compiles locally against a synthetic line.
  test_in='LLM_BACKEND=vllm-local'
  test_out=$(printf '%s\n' "$test_in" | sed -E "${SED_EXPR}")
  if [[ "${test_out}" != "LLM_BACKEND=anthropic" ]]; then
    fail "preflight" "sed expression did not produce expected output (got: ${test_out})"
  fi
  log "  sed expression compiles + maps vllm-local -> anthropic locally: ok"
  log "DRY-RUN: PASSED (no SSH performed)"
  exit 0
fi

# ---------- APPLY MODE ----------

# Helper: run an ssh command, capture stdout, exit on rc != 0.
ssh_run() {
  local label="$1"; shift
  local cmd="$1"; shift
  log "  ssh: ${label}"
  set +e
  out=$(ssh -o ConnectTimeout=10 -o ServerAliveInterval=15 "${SSH_HOST}" "${cmd}" 2>&1)
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    printf '%s\n' "${out}" >&2
    fail "${label}" "ssh exit=${rc}"
  fi
  printf '%s' "${out}"
}

log "[1/6] verify before-state of LLM_BACKEND"
before=$(ssh_run "show-env-before" "systemctl show ${SERVICE} -p Environment 2>/dev/null | tr ' ' '\n' | grep -E '^LLM_BACKEND=' || true")
if [[ -z "${before}" ]]; then
  log "  before: LLM_BACKEND not present in unit Environment (may be loaded via EnvironmentFile)"
else
  log "  before: ${before}"
fi

log "[2/6] in-place rewrite ${ENV_PATH} -> LLM_BACKEND=anthropic (backup ${BAK_SUFFIX})"
ssh_run "sed-rewrite" "${SED_CMD}" >/dev/null
log "  rewrite: ok (backup at ${ENV_PATH}${BAK_SUFFIX})"

log "[3/6] restart ${SERVICE}"
ssh_run "systemctl-restart" "sudo systemctl restart ${SERVICE}" >/dev/null
log "  restart: ok"

log "[4/6] wait up to 15s for ${SERVICE} active"
wait_cmd='for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do '"\
"'  state=$(systemctl is-active '"${SERVICE}"' 2>/dev/null || true); '"\
"'  if [ "$state" = "active" ]; then echo "active-after=${i}s"; exit 0; fi; '"\
"'  sleep 1; '"\
"'done; '"\
"'echo "did-not-go-active state=${state}"; exit 1'
active_out=$(ssh_run "wait-active" "${wait_cmd}")
log "  ${active_out}"

log "[5/6] verify after-state of LLM_BACKEND"
after=$(ssh_run "show-env-after" "systemctl show ${SERVICE} -p Environment 2>/dev/null | tr ' ' '\n' | grep -E '^LLM_BACKEND=' || true")
log "  after: ${after}"
if ! printf '%s' "${after}" | grep -qE '^LLM_BACKEND=anthropic$'; then
  fail "verify-env" "expected LLM_BACKEND=anthropic, got: ${after:-<empty>}"
fi

log "[6/6] minimal HTTP head-check to api.anthropic.com (reachability only, no auth)"
probe_cmd='curl -sS -o /dev/null -w "%{http_code}" --max-time 10 '"\
"'-H "content-type: application/json" '"\
"'-X POST https://api.anthropic.com/v1/messages --data "{}" || echo "TIMEOUT"'
http_code=$(ssh_run "anthropic-head" "${probe_cmd}")
log "  http_code=${http_code}"
case "${http_code}" in
  200|400|401|403)
    log "  reachability: ok (${http_code} indicates Anthropic API responded)"
    ;;
  TIMEOUT|000)
    fail "anthropic-head" "Anthropic API not reachable (got ${http_code}); rollback environment is broken"
    ;;
  *)
    log "  reachability: unexpected status ${http_code}; treating as reachable but flag for review"
    ;;
esac

log "rollback_phase_e.sh: PASSED rollback to LLM_BACKEND=anthropic"
exit 0
