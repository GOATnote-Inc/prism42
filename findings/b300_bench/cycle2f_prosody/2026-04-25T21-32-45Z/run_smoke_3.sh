#!/bin/bash
# cycle-2f redeploy SMOKE (flag OFF). 3 turns with cycle-2d-n30 first-3 prompts.
set -u
ART_REMOTE_DIR="/tmp/cycle2f-redeploy-smoke-out"
mkdir -p "$ART_REMOTE_DIR"

PROMPTS=(
"P1|I think I am having a heart attack. Chest pain and short of breath."
"P1|My neighbor's not breathing. He's on the floor."
"P1|There's a fire on the second floor. We're trapped."
)

START_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "SMOKE_START_UTC=$START_UTC"

cd /opt/prism42/agents/livekit
export PRISM42_HARNESS_FILLER_SKIP_S=2.5

for i in $(seq 1 3); do
  IDX=$(printf "%02d" "$i")
  ENTRY="${PROMPTS[$((i-1))]}"
  PRIORITY="${ENTRY%%|*}"
  PROMPT="${ENTRY#*|}"
  STDOUT_FILE="$ART_REMOTE_DIR/turn-$IDX.stdout"
  echo "[$(date -u +%H:%M:%S)] === SMOKE TURN $IDX ($PRIORITY) === $PROMPT"
  set +e
  /opt/prism42/agents/livekit/.venv/bin/python synthetic_caller_full.py "$PROMPT" > "$STDOUT_FILE" 2>&1
  RC=$?
  set -e
  echo "[$(date -u +%H:%M:%S)] smoke turn $IDX rc=$RC"
  if [ "$i" -lt 3 ]; then
    sleep 30
  fi
done

END_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "SMOKE_END_UTC=$END_UTC"
ls -la "$ART_REMOTE_DIR"
