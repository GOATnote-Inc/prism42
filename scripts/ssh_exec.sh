#!/bin/bash
# ssh_exec.sh — send a shell command to a Prism instance via SSH and
# verify the output. Mirrors the ssm_exec.sh interface but for
# non-AWS providers (Lambda Labs, RunPod, Crusoe).
#
# Usage:
#   ssh_exec.sh <host> <command> [--expect <substring>]
#   ssh_exec.sh 1.2.3.4 "nvidia-smi --query-gpu=name --format=csv,noheader"
#   ssh_exec.sh 1.2.3.4 "test -f /opt/prism/boot-ready" --expect ""
#
# Verification (per "always verify after acting" rule):
#   - exit code is inherited from remote
#   - if --expect <substring> given, stdout MUST contain <substring>
#     (exits 10 if remote succeeded but expectation missed)
#   - round-trip wall time printed to stderr
#
# SSH key defaults to ~/.ssh/prism_lambda_ed25519. Override via
# PRISM_SSH_KEY env.

set -euo pipefail

HOST="${1:?usage: ssh_exec.sh <host> <command> [--expect <substr>]}"
shift
COMMAND=""
EXPECT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect) EXPECT="$2"; shift 2 ;;
    *) COMMAND+="$1 "; shift ;;
  esac
done
COMMAND="${COMMAND%% }"
[[ -n "$COMMAND" ]] || { echo "usage: ssh_exec.sh <host> <command> [--expect <substr>]" >&2; exit 2; }

: "${PRISM_SSH_KEY:=$HOME/.ssh/prism_lambda_ed25519}"
: "${PRISM_SSH_USER:=ubuntu}"
: "${PRISM_SSH_PORT:=22}"
: "${SSH_TIMEOUT:=300}"

[[ -f "$PRISM_SSH_KEY" ]] || { echo "ERR: SSH key not found at $PRISM_SSH_KEY" >&2; exit 3; }

t0=$(python3 -c 'import time; print(time.time())')
set +e
stdout=$(ssh -o StrictHostKeyChecking=accept-new \
             -o UserKnownHostsFile="$HOME/.ssh/prism_known_hosts" \
             -o ConnectTimeout=10 \
             -o ServerAliveInterval=30 \
             -i "$PRISM_SSH_KEY" \
             -l "$PRISM_SSH_USER" \
             -p "$PRISM_SSH_PORT" \
             "$HOST" \
             "$COMMAND" 2>/tmp/prism-ssh-stderr.$$)
remote_rc=$?
set -e
stderr=$(cat /tmp/prism-ssh-stderr.$$); rm -f /tmp/prism-ssh-stderr.$$
t1=$(python3 -c 'import time; print(time.time())')
dt=$(python3 -c "print(f'{$t1-$t0:.2f}')")

printf '%s' "$stdout"

# Verification layer
if [[ $remote_rc -ne 0 ]]; then
  printf '\n--- ssh_exec: remote exit=%d time=%ss stderr ---\n%s\n' "$remote_rc" "$dt" "$stderr" >&2
  exit "$remote_rc"
fi

if [[ -n "$EXPECT" ]]; then
  if ! printf '%s' "$stdout" | grep -qF -- "$EXPECT"; then
    printf '\n--- ssh_exec: expectation miss (%ss) ---\nExpected substring: %s\nGot stdout:\n%s\n' "$dt" "$EXPECT" "$stdout" >&2
    exit 10
  fi
  printf '\n--- ssh_exec: verified "%s" in stdout (%ss) ---\n' "$EXPECT" "$dt" >&2
else
  printf '\n--- ssh_exec: remote ok (%ss) ---\n' "$dt" >&2
fi
