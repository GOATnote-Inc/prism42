#!/usr/bin/env bash
# Install a macOS launchd agent that runs scripts/orchestrator.py daily
# at 01:00 local time. Local alternative to the GitHub Actions workflow
# — picks up automatically if the Mac is awake at 01:00. If the Mac is
# asleep, launchd runs the job on next wake.
#
# One-time setup:
#   bash scripts/install_launchd.sh install
#
# Uninstall:
#   bash scripts/install_launchd.sh uninstall
#
# Requires ANTHROPIC_API_KEY in a location launchd can read. We point
# the plist at ~/prism/.env (gitignored) and the
# orchestrator sources it — same as interactive runs.

set -euo pipefail

LABEL="com.goatnote.prism.orchestrator"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${REPO_ROOT}/.state/launchd-logs"

install_agent() {
  mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIR}"
  cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>set -a; source ${REPO_ROOT}/.env; set +a; PRISM_ORCHESTRATOR_COMMIT=1 ${REPO_ROOT}/.venv/bin/python ${REPO_ROOT}/scripts/orchestrator.py --commit</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>1</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>${LOG_DIR}/orchestrator.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/orchestrator.stderr.log</string>
</dict>
</plist>
PLIST

  launchctl unload "${PLIST_PATH}" 2>/dev/null || true
  launchctl load -w "${PLIST_PATH}"

  echo "installed: ${PLIST_PATH}"
  echo "logs:      ${LOG_DIR}/"
  echo "schedule:  01:00 local time daily (launchd catches missed runs on wake)"
  echo ""
  echo "To trigger now: launchctl start ${LABEL}"
  echo "To disable:     launchctl unload -w ${PLIST_PATH}"
  echo "To inspect:     launchctl print gui/\$(id -u)/${LABEL}"
}

uninstall_agent() {
  if [[ -f "${PLIST_PATH}" ]]; then
    launchctl unload -w "${PLIST_PATH}" 2>/dev/null || true
    rm -f "${PLIST_PATH}"
    echo "uninstalled: ${PLIST_PATH}"
  else
    echo "not installed: ${PLIST_PATH}"
  fi
}

case "${1:-}" in
  install)
    install_agent
    ;;
  uninstall)
    uninstall_agent
    ;;
  *)
    echo "usage: $0 {install|uninstall}" >&2
    exit 1
    ;;
esac
