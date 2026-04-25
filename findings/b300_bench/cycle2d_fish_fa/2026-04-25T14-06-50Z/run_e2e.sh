#!/bin/bash
# Cycle-2d 10-turn E2E driver. Runs synthetic_caller_full.py 10x with 30s spacing.
# Captures stdout per turn, prints UTC start/end window for log slicing.

set -u

ART_REMOTE_DIR="/tmp/cycle2d-e2e-out"
mkdir -p "$ART_REMOTE_DIR"

PROMPTS=(
  "I think I am having a heart attack. Chest pain and short of breath."
  "My neighbor's not breathing. He's on the floor."
  "There's a fire on the second floor. We're trapped."
  "Someone broke into my house and I think they are still here."
  "I just got hit by a car at the intersection of fifth and main."
  "My toddler swallowed a battery."
  "I want to report a stolen vehicle from last night."
  "There's a domestic happening next door."
  "My power's out, is there an outage?"
  "I want to report a noise complaint."
)

START_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "BENCH_START_UTC=$START_UTC"

cd /opt/prism42/agents/livekit
export PRISM42_HARNESS_FILLER_SKIP_S=2.5

for i in $(seq 1 10); do
  IDX=$(printf "%02d" "$i")
  PROMPT="${PROMPTS[$((i-1))]}"
  STDOUT_FILE="$ART_REMOTE_DIR/turn-$IDX.stdout"
  echo "[$(date -u +%H:%M:%S)] === TURN $IDX === $PROMPT"
  set +e
  /opt/prism42/agents/livekit/.venv/bin/python synthetic_caller_full.py "$PROMPT" > "$STDOUT_FILE" 2>&1
  RC=$?
  set -e
  echo "[$(date -u +%H:%M:%S)] turn $IDX rc=$RC stdout=$STDOUT_FILE"
  if [ "$i" -lt 10 ]; then
    sleep 30
  fi
done

END_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "BENCH_END_UTC=$END_UTC"
ls -la "$ART_REMOTE_DIR"
