#!/bin/bash
# launch_runpod.sh — launch a Prism audit pod on RunPod (Secure Cloud,
# H100 SXM or H200 SXM, no quota gate). Verified end-to-end: API create,
# polling until RUNNING + public IP + port mapping, SSH reachability,
# GPU visible.
#
# Usage:
#   launch_runpod.sh [gpu-type] [container-disk-gb] [volume-gb]
#   launch_runpod.sh "NVIDIA H100 80GB HBM3"         # ~$2.99/hr
#   launch_runpod.sh "NVIDIA B200"                   # ~$5.49/hr (SM100 coverage)
#
# GPU type IDs (from docs.runpod.io/references/gpu-types):
#   "NVIDIA H100 80GB HBM3"   # H100 SXM 80GB — Hopper (SM90)
#   "NVIDIA H100 PCIe"        # H100 PCIe  — cheaper, no NVLink
#   "NVIDIA H200"             # H200 SXM 141GB — Hopper (SM90), larger HBM
#   "NVIDIA B200"             # Blackwell (SM100) — often low capacity
#
# Env overrides:
#   RUNPOD_API_KEY            (required) from console.runpod.io/user/settings
#   RUNPOD_IMAGE              container image (default pytorch/cuda devel)
#   RUNPOD_NETWORK_VOLUME_ID  optional; if set, reuses persistent volume
#   RUNPOD_CLOUD_TYPE         SECURE (default) | COMMUNITY
#   PRISM_SSH_KEY             default $HOME/.ssh/prism_lambda_ed25519

set -euo pipefail

GPU_TYPE="${1:-NVIDIA H100 80GB HBM3}"
CONTAINER_DISK_GB="${2:-80}"
VOLUME_GB="${3:-100}"

: "${RUNPOD_API_KEY:?set RUNPOD_API_KEY — get from console.runpod.io/user/settings}"
: "${RUNPOD_IMAGE:=runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04}"
: "${RUNPOD_CLOUD_TYPE:=SECURE}"
: "${PRISM_SSH_KEY:=$HOME/.ssh/prism_lambda_ed25519}"

API="https://rest.runpod.io/v1"
auth_hdr="Authorization: Bearer ${RUNPOD_API_KEY}"

# ---- Step 1: ensure local SSH key exists ----
if [[ ! -f "$PRISM_SSH_KEY" ]]; then
  echo "generating SSH key at $PRISM_SSH_KEY"
  ssh-keygen -t ed25519 -N "" -C "prism" -f "$PRISM_SSH_KEY"
  chmod 600 "$PRISM_SSH_KEY" "$PRISM_SSH_KEY.pub"
fi
pubkey=$(cat "$PRISM_SSH_KEY.pub")

# ---- Step 2: build create-pod request body ----
# PUBLIC_KEY env var is what the runpod/pytorch image checks at startup
# and installs into root's authorized_keys.
req=$(jq -n \
  --arg name "prism" \
  --arg image "$RUNPOD_IMAGE" \
  --arg gpu "$GPU_TYPE" \
  --arg cloud "$RUNPOD_CLOUD_TYPE" \
  --argjson disk "$CONTAINER_DISK_GB" \
  --argjson vol "$VOLUME_GB" \
  --arg pubkey "$pubkey" \
  --arg nvid "${RUNPOD_NETWORK_VOLUME_ID:-}" \
  '{
    name: $name,
    imageName: $image,
    cloudType: $cloud,
    computeType: "GPU",
    gpuTypeIds: [$gpu],
    gpuCount: 1,
    containerDiskInGb: $disk,
    volumeInGb: $vol,
    volumeMountPath: "/workspace",
    ports: ["22/tcp"],
    env: {PUBLIC_KEY: $pubkey},
    interruptible: false
  } + (if $nvid == "" then {} else {networkVolumeId: $nvid} end)')

echo "creating RunPod pod: gpu='$GPU_TYPE' disk=${CONTAINER_DISK_GB}GB vol=${VOLUME_GB}GB cloud=$RUNPOD_CLOUD_TYPE"
create_resp=$(curl -sf -X POST "$API/pods" \
  -H "$auth_hdr" -H "Content-Type: application/json" \
  -d "$req")

pod_id=$(echo "$create_resp" | jq -r '.id')
[[ "$pod_id" != "null" && -n "$pod_id" ]] \
  || { echo "ERR: pod creation failed: $create_resp" >&2; exit 6; }
echo "created pod_id=$pod_id"

# ---- Step 3: poll until RUNNING + public IP + port 22 mapped ----
deadline=$(( $(date +%s) + 600 ))  # 10 min max
while true; do
  info=$(curl -sf -H "$auth_hdr" "$API/pods/$pod_id")
  status=$(echo "$info" | jq -r '.desiredStatus // "UNKNOWN"')
  ip=$(echo "$info" | jq -r '.publicIp // ""')
  port=$(echo "$info" | jq -r '.portMappings."22" // empty')
  echo "  status=$status ip=${ip:-<pending>} ssh_port=${port:-<pending>}"
  if [[ "$status" == "RUNNING" && -n "$ip" && -n "$port" ]]; then
    break
  fi
  (( $(date +%s) > deadline )) && { echo "ERR: pod did not expose SSH in 10 min" >&2; exit 7; }
  sleep 10
done
echo "verified: pod RUNNING at $ip:$port"

# ---- Step 4: SSH reachability + GPU visible (the real verification) ----
# RunPod official images run sshd as root. Wait a bit for sshd to come
# up after status=RUNNING, then probe.
echo "waiting for sshd..."
for i in {1..30}; do
  if PRISM_SSH_USER=root PRISM_SSH_PORT="$port" \
     ssh -o StrictHostKeyChecking=accept-new \
         -o UserKnownHostsFile="$HOME/.ssh/prism_known_hosts" \
         -o ConnectTimeout=5 -i "$PRISM_SSH_KEY" \
         -p "$port" "root@$ip" "true" 2>/dev/null; then
    break
  fi
  sleep 5
done

# Determine expected GPU substring from gpu-type ID.
expect="H100"
[[ "$GPU_TYPE" == *"H200"* ]] && expect="H200"
[[ "$GPU_TYPE" == *"B200"* ]] && expect="B200"

gpu=$(PRISM_SSH_USER=root PRISM_SSH_PORT="$port" \
      bash "$(dirname "$0")/ssh_exec.sh" "$ip" \
        "nvidia-smi --query-gpu=name --format=csv,noheader | head -1" \
        --expect "$expect" 2>/dev/null || true)
if [[ -z "$gpu" ]]; then
  echo "ERR: GPU check failed — pod up but nvidia-smi did not return $expect" >&2
  exit 8
fi
echo "verified: GPU is $gpu"

# ---- Step 5: persist state ----
state_dir="$(cd "$(dirname "$0")/.." && pwd)/.state"
mkdir -p "$state_dir"
state_file="$state_dir/runpod-$pod_id.json"
jq -n \
  --arg id "$pod_id" \
  --arg ip "$ip" \
  --argjson port "$port" \
  --arg gpu_type "$GPU_TYPE" \
  --arg gpu "$gpu" \
  --arg user "root" \
  '{id:$id, ip:$ip, port:$port, user:$user, gpu_type:$gpu_type, gpu:$gpu}' \
  > "$state_file"
# Symlink target must be relative to the symlink's own dir, not cwd.
ln -sf "runpod-$pod_id.json" "$state_dir/runpod-current.json"

cat <<EOF
---
Launched Prism RunPod pod
  pod_id:  $pod_id
  gpu:     $gpu ($GPU_TYPE)
  ssh:     ssh -i $PRISM_SSH_KEY -p $port root@$ip
  state:   $(realpath "$state_file")
  teardown: make teardown-runpod
EOF
