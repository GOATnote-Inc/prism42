#!/bin/bash
# ssm_exec.sh — send a shell command to a Prism EC2 instance via SSM and
# poll for the result. Used by Makefile recipes and the executor agent.
#
# Usage:
#   ssm_exec.sh <instance-name-tag> <command>
#   ssm_exec.sh prism-p5 "nvidia-smi --query-gpu=name --format=csv,noheader"
#
# Resolves instance ID by tag:Name, sends the command, polls
# GetCommandInvocation until state is terminal, prints stdout, and
# exits nonzero if the remote command failed.

set -euo pipefail

INSTANCE_TAG="${1:?usage: ssm_exec.sh <instance-tag> <command>}"
shift
COMMAND="${*:?usage: ssm_exec.sh <instance-tag> <command>}"

: "${AWS_PROFILE:=prism}"
: "${AWS_REGION:=us-east-1}"
: "${SSM_TIMEOUT:=300}"  # seconds — 5 min default; build commands override

# Resolve tag:Name -> instance-id (pick first running)
INSTANCE_ID=$(aws ec2 describe-instances \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=${INSTANCE_TAG}" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

if [[ "$INSTANCE_ID" == "None" || -z "$INSTANCE_ID" ]]; then
  echo "ERR: no running instance with tag:Name=${INSTANCE_TAG}" >&2
  exit 2
fi

# Dispatch
CMD_ID=$(aws ssm send-command \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters "commands=[\"${COMMAND//\"/\\\"}\"]" \
  --timeout-seconds "$SSM_TIMEOUT" \
  --query 'Command.CommandId' --output text)

# Poll
deadline=$(( $(date +%s) + SSM_TIMEOUT + 10 ))
while true; do
  resp=$(aws ssm get-command-invocation \
    --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" 2>/dev/null || true)
  if [[ -z "$resp" ]]; then
    sleep 1; continue
  fi
  status=$(echo "$resp" | jq -r '.Status')
  case "$status" in
    Success|Failed|Cancelled|TimedOut)
      stdout=$(echo "$resp" | jq -r '.StandardOutputContent')
      stderr=$(echo "$resp" | jq -r '.StandardErrorContent')
      rc=$(echo "$resp"   | jq -r '.ResponseCode')
      printf '%s' "$stdout"
      if [[ "$status" != "Success" ]]; then
        printf '\n--- stderr ---\n%s\n' "$stderr" >&2
        exit "$rc"
      fi
      exit 0
      ;;
    Pending|InProgress|Delayed) : ;;
    *) echo "unexpected SSM status: $status" >&2; exit 3 ;;
  esac
  if (( $(date +%s) > deadline )); then
    echo "SSM command $CMD_ID timed out" >&2
    exit 124
  fi
  sleep 2
done
