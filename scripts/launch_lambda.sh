#!/bin/bash
# launch_lambda.sh — launch a Prism audit instance on Lambda Labs (no
# quota gate, on-demand H100). Verified end-to-end: API launch, polling
# until active, SSH reachability, GPU visible.
#
# Usage:
#   launch_lambda.sh [instance-type] [region]
#   launch_lambda.sh gpu_1x_h100_pcie us-east-1   # dev default (~$2.49/hr)
#   launch_lambda.sh gpu_8x_h100_sxm5 us-east-1   # demo scale (~$24/hr)
#
# Prereqs:
#   - $LAMBDA_API_KEY exported (get from cloud.lambdalabs.com)
#   - ~/.ssh/prism_lambda_ed25519 key pair (script creates if missing)
#   - Lambda "prism" SSH key name registered with pubkey (script does this)

set -euo pipefail

INSTANCE_TYPE="${1:-gpu_1x_h100_pcie}"
REGION="${2:-us-east-1}"
KEY_NAME="prism"
SSH_KEY="$HOME/.ssh/prism_lambda_ed25519"
API="https://cloud.lambdalabs.com/api/v1"

: "${LAMBDA_API_KEY:?set LAMBDA_API_KEY — get from cloud.lambdalabs.com/api-keys}"

auth() { curl -sfu "${LAMBDA_API_KEY}:" "$@"; }

# ---- Step 1: ensure local SSH key exists ----
if [[ ! -f "$SSH_KEY" ]]; then
  echo "generating SSH key at $SSH_KEY"
  ssh-keygen -t ed25519 -N "" -C "prism-lambda" -f "$SSH_KEY"
  chmod 600 "$SSH_KEY" "$SSH_KEY.pub"
fi

# ---- Step 2: ensure key uploaded to Lambda under $KEY_NAME ----
existing_keys=$(auth "$API/ssh-keys" | jq -r '.data[].name')
if ! echo "$existing_keys" | grep -qx "$KEY_NAME"; then
  echo "uploading $KEY_NAME pubkey to Lambda"
  auth -X POST "$API/ssh-keys" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg n "$KEY_NAME" --arg k "$(cat $SSH_KEY.pub)" '{name:$n, public_key:$k}')" > /dev/null
fi
# Verify registered
auth "$API/ssh-keys" | jq -e ".data[] | select(.name==\"$KEY_NAME\")" > /dev/null \
  || { echo "ERR: SSH key not registered after upload" >&2; exit 4; }
echo "verified: SSH key '$KEY_NAME' present at Lambda"

# ---- Step 3: check availability of requested instance type ----
avail=$(auth "$API/instance-types" \
  | jq -r --arg it "$INSTANCE_TYPE" --arg r "$REGION" \
      '.data[$it].regions_with_capacity_available[] | select(.name==$r) | .name')
if [[ -z "$avail" ]]; then
  echo "ERR: $INSTANCE_TYPE not available in $REGION right now" >&2
  echo "available types + regions:" >&2
  auth "$API/instance-types" \
    | jq -r '.data | to_entries[] | .key as $t | .value.regions_with_capacity_available[]? | "\($t)\t\(.name)"' >&2
  exit 5
fi
echo "verified: $INSTANCE_TYPE available in $REGION"

# ---- Step 4: launch ----
echo "launching $INSTANCE_TYPE in $REGION..."
launch_resp=$(auth -X POST "$API/instance-operations/launch" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg r "$REGION" --arg it "$INSTANCE_TYPE" --arg k "$KEY_NAME" \
      '{region_name:$r, instance_type_name:$it, ssh_key_names:[$k], name:"prism", quantity:1}')")

instance_id=$(echo "$launch_resp" | jq -r '.data.instance_ids[0]')
[[ "$instance_id" != "null" && -n "$instance_id" ]] \
  || { echo "ERR: launch failed: $launch_resp" >&2; exit 6; }
echo "launched instance_id=$instance_id"

# ---- Step 5: poll until active + got an IP ----
deadline=$(( $(date +%s) + 600 ))  # 10 min max
while true; do
  info=$(auth "$API/instances/$instance_id")
  status=$(echo "$info" | jq -r '.data.status')
  ip=$(echo "$info" | jq -r '.data.ip // ""')
  echo "  status=$status ip=${ip:-<pending>}"
  [[ "$status" == "active" && -n "$ip" ]] && break
  (( $(date +%s) > deadline )) && { echo "ERR: instance did not become active in 10 min" >&2; exit 7; }
  sleep 10
done
echo "verified: instance active at $ip"

# ---- Step 6: SSH reachability + GPU visible (the real verification) ----
echo "waiting for sshd..."
for i in {1..30}; do
  if ssh -o StrictHostKeyChecking=accept-new \
         -o UserKnownHostsFile="$HOME/.ssh/prism_known_hosts" \
         -o ConnectTimeout=5 -i "$SSH_KEY" ubuntu@"$ip" "true" 2>/dev/null; then
    break
  fi
  sleep 5
done

gpu=$(bash "$(dirname "$0")/ssh_exec.sh" "$ip" \
  "nvidia-smi --query-gpu=name --format=csv,noheader | head -1" \
  --expect "H100" 2>/dev/null || true)
if [[ -z "$gpu" ]]; then
  echo "ERR: GPU check failed — instance up but nvidia-smi did not return H100" >&2
  exit 8
fi
echo "verified: GPU is $gpu"

# ---- Step 7: persist metadata for Makefile targets ----
state_dir="$(cd "$(dirname "$0")/.." && pwd)/.state"
mkdir -p "$state_dir"
state_file="$state_dir/lambda-$instance_id.json"
echo "$info" | jq '.data' > "$state_file"
# Symlink target must be relative to the symlink's own dir, not cwd.
ln -sf "lambda-$instance_id.json" "$state_dir/lambda-current.json"

cat <<EOF
---
Launched Prism Lambda instance
  instance_id: $instance_id
  type:        $INSTANCE_TYPE
  region:      $REGION
  ip:          $ip
  ssh:         ssh -i $SSH_KEY ubuntu@$ip
  state:       $(realpath "$state_file")
  teardown:    make teardown-lambda
EOF
