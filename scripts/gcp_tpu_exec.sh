#!/bin/bash
# gcp_tpu_exec.sh — send a shell command to a GCP TPU VM and verify output.
# Mirrors the ssh_exec.sh interface so the executor is provider-agnostic.
#
# Usage:
#   gcp_tpu_exec.sh <tpu_vm_name> <command> [--expect <substring>] [--zone <zone>]
#
# Example:
#   gcp_tpu_exec.sh prism-mla-v6e-1 "python3 -c 'import jax; print(jax.devices())'" \
#       --expect "TpuDevice" --zone us-east5-a
#
# Verification (per "always verify after acting" rule):
#   - exit code inherited from gcloud ssh (propagates remote rc)
#   - if --expect <substring> given, stdout MUST contain <substring>
#     (exits 10 if remote succeeded but expectation missed)
#   - round-trip wall time printed to stderr
#
# Env:
#   PRISM_GCP_PROJECT   required — the GCP project holding the TPU VM.
#   PRISM_GCP_ZONE      optional — default us-east5-a (Trillium zone).
#                       Override with --zone.
#   GCLOUD_TIMEOUT      optional — seconds, default 300.

set -euo pipefail

TPU_NAME="${1:?usage: gcp_tpu_exec.sh <tpu_vm_name> <command> [--expect <substr>] [--zone <zone>]}"
shift
COMMAND=""
EXPECT=""
ZONE="${PRISM_GCP_ZONE:-us-east5-a}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect) EXPECT="$2"; shift 2 ;;
    --zone)   ZONE="$2";   shift 2 ;;
    *) COMMAND+="$1 "; shift ;;
  esac
done
COMMAND="${COMMAND%% }"
[[ -n "$COMMAND" ]] || { echo "usage: gcp_tpu_exec.sh <tpu_vm_name> <command> [--expect <substr>] [--zone <zone>]" >&2; exit 2; }

: "${PRISM_GCP_PROJECT:?PRISM_GCP_PROJECT must be set (e.g. prism421)}"
: "${GCLOUD_TIMEOUT:=300}"

command -v gcloud >/dev/null 2>&1 || { echo "ERR: gcloud CLI not found on PATH" >&2; exit 3; }

t0=$(python3 -c 'import time; print(time.time())')
set +e
stdout=$(timeout "$GCLOUD_TIMEOUT" gcloud compute tpus tpu-vm ssh "$TPU_NAME" \
           --zone="$ZONE" \
           --project="$PRISM_GCP_PROJECT" \
           --command="$COMMAND" \
           --quiet 2>/tmp/prism-gcp-stderr.$$)
remote_rc=$?
set -e
stderr=$(cat /tmp/prism-gcp-stderr.$$); rm -f /tmp/prism-gcp-stderr.$$
t1=$(python3 -c 'import time; print(time.time())')
dt=$(python3 -c "print(f'{$t1-$t0:.2f}')")

printf '%s' "$stdout"

# Verification layer.
if [[ $remote_rc -ne 0 ]]; then
  printf '\n--- gcp_tpu_exec: remote exit=%d time=%ss stderr ---\n%s\n' "$remote_rc" "$dt" "$stderr" >&2
  exit "$remote_rc"
fi

if [[ -n "$EXPECT" ]]; then
  if ! printf '%s' "$stdout" | grep -qF -- "$EXPECT"; then
    printf '\n--- gcp_tpu_exec: expectation miss (%ss) ---\nExpected substring: %s\nGot stdout:\n%s\n' "$dt" "$EXPECT" "$stdout" >&2
    exit 10
  fi
  printf '\n--- gcp_tpu_exec: verified "%s" in stdout (%ss) ---\n' "$EXPECT" "$dt" >&2
else
  printf '\n--- gcp_tpu_exec: remote ok (%ss) ---\n' "$dt" >&2
fi
