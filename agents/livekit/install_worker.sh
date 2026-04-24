#!/bin/bash
# Install + start the prism42 worker as a systemd service.
# Run on the brev pod as the shadeform user (passwordless sudo).
set -e

SERVICE_SRC=/tmp/prism42-worker.service
SERVICE_DST=/etc/systemd/system/prism42-worker.service

if [ ! -f "$SERVICE_SRC" ]; then
  echo "FAIL: $SERVICE_SRC missing"
  exit 1
fi

sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl stop prism42-worker 2>/dev/null || true
sudo pkill -9 -f /opt/prism42/agents/livekit/.venv 2>/dev/null || true
sleep 1
sudo bash -c ': > /tmp/prism42-logs/worker.log'
sudo systemctl enable --now prism42-worker
sleep 2
echo "is-active:"
systemctl is-active prism42-worker
echo "is-enabled:"
systemctl is-enabled prism42-worker
