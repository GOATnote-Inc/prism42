#!/usr/bin/env bash
# Bootstrap a B300 pod for the prism42 LiveKit voice runtime.
#
# Run as root on a fresh Ubuntu 22.04 LTS pod (Brev's default image):
#   curl -fsSL https://raw.githubusercontent.com/GOATnote-Inc/prism42/main/infra/b300/setup.sh | sudo bash -
# OR after cloning:
#   sudo bash /opt/prism42/infra/b300/setup.sh
#
# Idempotent — safe to re-run after edits to Caddyfile or livekit.yaml.
#
# What it installs (in order):
#   1. apt deps + Docker + Caddy
#   2. prism42 user (no shell, no home — service account)
#   3. clone the repo to /opt/prism42 (or git pull if it exists)
#   4. install uv + Python 3.12
#   5. uv sync the agent venv
#   6. write Caddyfile + reload Caddy
#   7. docker compose up -d (LiveKit + Redis)
#   8. install + start the systemd unit
#   9. open firewall ports (ufw)
#   10. print the next manual steps

set -euo pipefail

REPO_URL="${PRISM42_REPO_URL:-https://github.com/GOATnote-Inc/prism42.git}"
INSTALL_DIR=/opt/prism42
DOMAIN="${PRISM42_LIVEKIT_DOMAIN:-livekit.thegoatnote.com}"

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (try: sudo bash $0)" >&2
  exit 1
fi

echo "==> [1/10] apt update + base deps"
apt-get update -qq
apt-get install -y -qq \
  curl ca-certificates gnupg \
  ufw \
  build-essential pkg-config libssl-dev \
  python3 python3-venv python3-pip

echo "==> [2/10] install Docker"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "==> [3/10] install Caddy"
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi

echo "==> [4/10] create prism42 service account"
if ! id -u prism42 >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin prism42
fi

echo "==> [5/10] clone (or update) the repo to ${INSTALL_DIR}"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  (cd "${INSTALL_DIR}" && git fetch --quiet && git reset --hard origin/main)
else
  git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
fi
chown -R prism42:prism42 "${INSTALL_DIR}"

echo "==> [6/10] install uv (Python package manager) + sync agent venv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  install -m 0755 "$HOME/.local/bin/uv" /usr/local/bin/uv
fi
sudo -u prism42 bash -c "cd ${INSTALL_DIR}/agents/livekit && uv sync --frozen"

echo "==> [7/10] write Caddyfile and reload"
install -m 0644 "${INSTALL_DIR}/infra/b300/Caddyfile" /etc/caddy/Caddyfile
mkdir -p /var/log/caddy
chown -R caddy:caddy /var/log/caddy
systemctl enable caddy
systemctl reload caddy || systemctl restart caddy

echo "==> [8/10] start LiveKit + Redis via docker compose"
mkdir -p /var/log/prism42/turns /var/log/prism42/sessions
chown -R prism42:prism42 /var/log/prism42
# .env must already exist at ${INSTALL_DIR}/.env (the operator scp's
# this from their laptop — see README §provision).
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  echo "ERROR: ${INSTALL_DIR}/.env missing. scp your .env into place before re-running." >&2
  exit 1
fi
chmod 600 "${INSTALL_DIR}/.env"
chown prism42:prism42 "${INSTALL_DIR}/.env"
# Extract just the agent-relevant vars to /opt/prism42/.env.agent (systemd reads this).
grep -E '^(ANTHROPIC_API_KEY|OPENAI_API_KEY|DEEPGRAM_API_KEY|CARTESIA_API_KEY|LIVEKIT_URL|LIVEKIT_API_KEY|LIVEKIT_API_SECRET|REDIS_URL|PRISM42_LOG_DIR)=' \
  "${INSTALL_DIR}/.env" > /opt/prism42/.env.agent
chmod 600 /opt/prism42/.env.agent
chown prism42:prism42 /opt/prism42/.env.agent
# REDIS_URL default — assume the docker-compose Redis is reachable on
# the host network.
if ! grep -q '^REDIS_URL=' /opt/prism42/.env.agent; then
  echo 'REDIS_URL=redis://127.0.0.1:6379' >> /opt/prism42/.env.agent
fi
docker compose --project-directory "${INSTALL_DIR}/infra/b300" --env-file "${INSTALL_DIR}/.env" up -d

echo "==> [9/10] install + start the prism42-agent systemd unit"
install -m 0644 "${INSTALL_DIR}/infra/b300/prism42-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now prism42-agent

echo "==> [10/10] open firewall ports"
ufw allow 22/tcp                              # ssh
ufw allow 80/tcp                              # caddy http -> redirect + LE
ufw allow 443/tcp                             # caddy https / wss
# LiveKit signaling (7880/tcp) is intentionally NOT exposed: Caddy
# terminates TLS in front of 127.0.0.1:7880. Opening it publicly would
# let attackers bypass TLS and hit the signaling WebSocket directly.
# 7881/tcp (WebRTC TCP fallback) is also kept loopback-only; rely on
# 7882/udp for media. Re-open only with an explicit threat-model review.
ufw allow 7882/udp                            # livekit webrtc media
ufw allow 5349/tcp                            # livekit TURN/TLS
ufw allow 443/udp                             # livekit TURN/UDP (shares port with HTTPS)
ufw --force enable

cat <<EOF

================================================================================
prism42 B300 pod bootstrap complete.

Verify:
  systemctl status caddy
  systemctl status prism42-agent
  docker compose --project-directory ${INSTALL_DIR}/infra/b300 ps
  curl -sI https://${DOMAIN}/health     # should return 200 once Let's Encrypt issues

DNS prereq: livekit.thegoatnote.com  A  $(curl -s ifconfig.me)
  (use infra/b300/setup-dns.sh to set this via the GoDaddy API)

Next:
  1. Test from a browser: open the Next.js app's /prism42/livekit route
  2. tail logs: journalctl -u prism42-agent -f
  3. Phase 3b: uncomment the vllm block in docker-compose.yml and bring it up

================================================================================
EOF
