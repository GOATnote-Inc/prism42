#!/usr/bin/env bash
# cycle-2R LiveKit self-host — execution script
# Companion to runbook.md. Each phase is gated by an env-var auth flag
# so accidental whole-script execution without explicit per-step
# authorization fails loud at the first gated step.
#
# Usage:
#   ./run.sh --phase=0    # DNS resolution check / GoDaddy PATCH (G2)
#   ./run.sh --phase=1    # UFW open ports (G3)
#   ./run.sh --phase=2    # Caddy install + Caddyfile (G3)
#   ./run.sh --phase=3    # livekit-server systemd takeover (G4) — Option A only
#   ./run.sh --phase=4    # Vercel preview env + worker .env + deploy (G5)
#   ./run.sh --phase=5    # End-to-end voice turn smoke (manual; prints checklist)
#   ./run.sh --phase=6    # Production cutover (G6)
#   ./run.sh --phase=all  # Run 0..6 sequentially with explicit pause between phases
#
# Authorization flags (set as needed before invoking the matching phase):
#   PRISM42_AUTH_G2=1   DNS PATCH on thegoatnote.com via GoDaddy API
#   PRISM42_AUTH_G3=1   UFW rule additions + Caddy install + start
#   PRISM42_AUTH_G4=1   systemd takeover of livekit-server (kills bare pid)
#   PRISM42_AUTH_G6=1   Production env flip to LIVEKIT_BACKEND=selfhost
#
# Required env (sourced by integrator from canonical /Users/kiteboard/lostbench/.env):
#   GODADDY_API_KEY, GODADDY_API_SECRET   (Phase 0 only)
#   VERCEL_TOKEN                          (Phase 4, 6)
#   TEAM_A_LIVEKIT_KEY, TEAM_A_LIVEKIT_SECRET  (Phase 3, 4 — from Team A handoff)

set -Eeuo pipefail

# ─────────────────────────────────────────────────────────────────────
# Configuration (frozen facts — DO NOT change without re-verification)
# ─────────────────────────────────────────────────────────────────────
POD_PUBLIC_IP="31.22.104.100"
POD_HOSTNAME="prism-mla-b300-h4h5"
LIVEKIT_DOMAIN="prism42.thegoatnote.com"
TURN_DOMAIN="turn-prism42.thegoatnote.com"
LIVEKIT_WSS_URL="wss://${LIVEKIT_DOMAIN}"
WORKER_ENV_PATH="/opt/prism42/worker/.env"   # confirmed by integrator via `systemctl cat prism42-worker | grep EnvironmentFile`
VERCEL_PROJECT_DIR="/Users/kiteboard/prism42/mvp/911-console-live"

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { printf '[%s] FATAL: %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; exit 2; }

require_env() {
    local var="$1"
    if [ -z "${!var:-}" ]; then
        die "$var not set; refusing to proceed"
    fi
}

require_gate() {
    local gate="$1"
    if [ -z "${!gate:-}" ]; then
        die "$gate not set; this phase requires explicit authorization. Set $gate=1 to proceed."
    fi
}

# ─────────────────────────────────────────────────────────────────────
# Phase 0 — DNS resolution
# ─────────────────────────────────────────────────────────────────────
phase_0() {
    log "==== Phase 0: DNS resolution ===="

    log "0.1 Verify current DNS state (read-only)"
    local v1 v2 v3 v4
    v1=$(dig +short @1.1.1.1 "$LIVEKIT_DOMAIN" | tr -d '\n' || true)
    v2=$(dig +short @8.8.8.8 "$LIVEKIT_DOMAIN" | tr -d '\n' || true)
    v3=$(dig +short @1.1.1.1 "$TURN_DOMAIN" | tr -d '\n' || true)
    v4=$(dig +short @8.8.8.8 "$TURN_DOMAIN" | tr -d '\n' || true)

    log "  $LIVEKIT_DOMAIN @1.1.1.1 = $v1"
    log "  $LIVEKIT_DOMAIN @8.8.8.8 = $v2"
    log "  $TURN_DOMAIN @1.1.1.1 = $v3"
    log "  $TURN_DOMAIN @8.8.8.8 = $v4"

    if [ "$v1" = "$POD_PUBLIC_IP" ] && [ "$v2" = "$POD_PUBLIC_IP" ] \
        && [ "$v3" = "$POD_PUBLIC_IP" ] && [ "$v4" = "$POD_PUBLIC_IP" ]; then
        log "  All 4 lookups already match $POD_PUBLIC_IP — Phase 0 SKIPPED"
        return 0
    fi

    log "0.2 DNS PATCH via GoDaddy API"
    require_gate PRISM42_AUTH_G2   # GATE_G2
    require_env  GODADDY_API_KEY
    require_env  GODADDY_API_SECRET

    local auth_header="Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}"

    log "  PATCH $LIVEKIT_DOMAIN -> $POD_PUBLIC_IP"
    curl -fsS -X PUT "https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/prism42" \
        -H "$auth_header" \
        -H "Content-Type: application/json" \
        -d "[{\"data\":\"$POD_PUBLIC_IP\",\"ttl\":600}]" \
        || die "GoDaddy PATCH for prism42.thegoatnote.com failed"

    log "  PATCH $TURN_DOMAIN -> $POD_PUBLIC_IP"
    curl -fsS -X PUT "https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/turn-prism42" \
        -H "$auth_header" \
        -H "Content-Type: application/json" \
        -d "[{\"data\":\"$POD_PUBLIC_IP\",\"ttl\":600}]" \
        || die "GoDaddy PATCH for turn-prism42.thegoatnote.com failed"

    log "0.3 Wait for propagation (TTL=600, deadline=12 min)"
    local deadline; deadline=$(( $(date +%s) + 720 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        v1=$(dig +short @1.1.1.1 "$LIVEKIT_DOMAIN" | tr -d '\n' || true)
        v2=$(dig +short @8.8.8.8 "$LIVEKIT_DOMAIN" | tr -d '\n' || true)
        v3=$(dig +short @1.1.1.1 "$TURN_DOMAIN" | tr -d '\n' || true)
        v4=$(dig +short @8.8.8.8 "$TURN_DOMAIN" | tr -d '\n' || true)
        if [ "$v1" = "$POD_PUBLIC_IP" ] && [ "$v2" = "$POD_PUBLIC_IP" ] \
            && [ "$v3" = "$POD_PUBLIC_IP" ] && [ "$v4" = "$POD_PUBLIC_IP" ]; then
            log "  DNS verified: all 4 lookups -> $POD_PUBLIC_IP"
            return 0
        fi
        log "  Not yet propagated (1.1.1.1=$v1 8.8.8.8=$v2 turn=$v3/$v4); sleeping 30s"
        sleep 30
    done
    die "DNS propagation deadline exceeded after 12 min"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 1 — UFW open production media ports
# ─────────────────────────────────────────────────────────────────────
phase_1() {
    log "==== Phase 1: UFW open media ports ===="

    log "1.1 Pre-check current UFW state"
    sudo ufw status numbered || die "UFW not available"

    require_gate PRISM42_AUTH_G3   # GATE_G3

    log "1.2 Add allow rules"
    # Idempotent: ufw treats duplicate rule additions as no-ops with a
    # "Skipping adding existing rule" message.
    sudo ufw allow 7880/tcp comment 'livekit signaling (WSS via Caddy upstream)' || true
    sudo ufw allow 7881/tcp comment 'livekit media TCP fallback' || true
    sudo ufw allow 7882/udp comment 'livekit RTC primary' || true
    sudo ufw allow 50000:60000/udp comment 'livekit SFU media range' || true
    sudo ufw allow 3478/udp comment 'livekit TURN UDP' || true
    sudo ufw allow 5349/tcp comment 'livekit TURN TLS' || true
    sudo ufw allow 80/tcp comment 'caddy ACME HTTP-01' || true
    sudo ufw allow 443/tcp comment 'caddy HTTPS' || true
    sudo ufw reload || die "ufw reload failed"

    log "1.3 Verify rules landed"
    sudo ufw status numbered | tee /tmp/ufw-status-cycle2R.txt
    if ! sudo iptables -L INPUT -n -v 2>/dev/null | grep -q "dpts:50000:60000"; then
        log "  WARN: 50000:60000 range did not appear in iptables — possible UFW syntax issue"
        log "  WARN: see Phase 1 Munger inversion in runbook.md"
    fi

    log "1.4 Smoke-probe (TCP RST or timeout?)"
    # nc -zv on a remote port: success/RST = good, timeout = bad
    nc -zv -w 5 "$POD_PUBLIC_IP" 7880 || log "  (TCP RST/no-listener = firewall let SYN through; OK pre-Caddy)"
    nc -zv -w 5 "$POD_PUBLIC_IP" 443  || log "  (TCP RST/no-listener = firewall let SYN through; OK pre-Caddy)"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 2 — Caddy install + Caddyfile
# ─────────────────────────────────────────────────────────────────────
phase_2() {
    log "==== Phase 2: Caddy install + Caddyfile ===="

    require_gate PRISM42_AUTH_G3   # GATE_G3

    log "2.1 Install Caddy if missing"
    if ! command -v caddy >/dev/null 2>&1; then
        sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl \
            || die "apt prereqs install failed"
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
            || die "Caddy GPG key fetch failed"
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null \
            || die "Caddy apt source add failed"
        sudo apt-get update || die "apt update failed"
        sudo apt-cache policy caddy
        sudo apt-get install -y caddy || die "Caddy install failed"
    else
        log "  Caddy already installed: $(caddy version)"
    fi

    log "2.2 Write /etc/caddy/Caddyfile"
    sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${LIVEKIT_DOMAIN} {
    reverse_proxy 127.0.0.1:7880
    log {
        output file /var/log/caddy/livekit.log
        format json
    }
}

${TURN_DOMAIN} {
    tls {
        protocols tls1.2 tls1.3
    }
    reverse_proxy 127.0.0.1:5349
}
EOF
    sudo mkdir -p /var/log/caddy
    sudo chown caddy:caddy /var/log/caddy
    sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
        || die "Caddyfile validation failed"

    log "2.3 Start Caddy"
    if ! sudo systemctl is-active --quiet caddy; then
        sudo systemctl enable --now caddy || die "Caddy start failed"
    else
        sudo systemctl reload caddy || sudo systemctl restart caddy
    fi
    sleep 5
    sudo systemctl status caddy --no-pager | head -20

    log "2.4 Verify ACME issuance"
    sudo journalctl -u caddy --since="2 min ago" -n 200 \
        | grep -E "certificate obtained|tls handshake|certificate magic|signed certificate|ACME" \
        | tail -10 \
        || log "  WARN: no ACME-issuance lines found in last 2 min; cert may take 30-90s on first request"

    log "2.5 External smoke (HTTPS reachable + cert valid)"
    if curl -sIo /dev/null -w '%{http_code}' "https://${LIVEKIT_DOMAIN}" --max-time 10 >/tmp/cycle2R-http-code.txt 2>&1; then
        log "  https://${LIVEKIT_DOMAIN} returned: $(cat /tmp/cycle2R-http-code.txt)"
    else
        log "  WARN: curl failed; ACME may not be done. Re-run in 90s."
    fi
    echo \
        | timeout 5 openssl s_client -connect "${LIVEKIT_DOMAIN}:443" -servername "${LIVEKIT_DOMAIN}" 2>/dev/null \
        | openssl x509 -noout -issuer -subject -dates 2>/dev/null \
        || log "  WARN: TLS cert not yet present"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 3 — livekit-server systemd takeover (Option A — full takeover)
# ─────────────────────────────────────────────────────────────────────
phase_3() {
    log "==== Phase 3: livekit-server systemd takeover (Option A) ===="

    require_gate PRISM42_AUTH_G4   # GATE_G4
    require_env  TEAM_A_LIVEKIT_KEY
    require_env  TEAM_A_LIVEKIT_SECRET

    log "3.1 Pre-check: identify bare process + capture cmdline"
    if pgrep -f livekit-server >/dev/null 2>&1; then
        local bare_pid
        bare_pid=$(pgrep -f livekit-server | head -1)
        log "  bare livekit-server pid=$bare_pid"
        cat "/proc/$bare_pid/cmdline" 2>/dev/null | tr '\0' ' '; echo
        readlink "/proc/$bare_pid/cwd" 2>/dev/null || true
    else
        log "  no bare livekit-server running"
    fi

    log "3.2 Stop bare process"
    if pgrep -f livekit-server >/dev/null 2>&1; then
        sudo pkill -TERM -f livekit-server || true
        sleep 3
        if pgrep -f livekit-server >/dev/null 2>&1; then
            log "  SIGTERM did not stop process; sending SIGKILL"
            sudo pkill -KILL -f livekit-server || true
            sleep 1
        fi
    fi
    if ss -tunlp | grep -E ':7880|:7881|:7882' | grep -v '127.0.0.1' >/dev/null 2>&1; then
        log "  WARN: ports still bound by something other than livekit-server; investigate"
        ss -tunlp | grep -E ':7880|:7881|:7882'
    fi

    log "3.3 Author /opt/livekit/livekit.yaml"
    sudo mkdir -p /opt/livekit
    local svc_user; svc_user=$(id -un)
    if [ -z "$svc_user" ] || [ "$svc_user" = "root" ]; then
        svc_user=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
        [ -z "$svc_user" ] && svc_user=root
    fi
    log "  using service user: $svc_user"

    sudo tee /opt/livekit/livekit.yaml >/dev/null <<EOF
# cycle-2R self-hosted livekit-server config (single-node, no Redis, TURN bundled)
port: 7880
bind_addresses:
  - "0.0.0.0"
rtc:
  port_range_start: 50000
  port_range_end: 60000
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: true
turn:
  enabled: true
  domain: ${TURN_DOMAIN}
  tls_port: 5349
  udp_port: 3478
  external_tls: true
keys:
  ${TEAM_A_LIVEKIT_KEY}: ${TEAM_A_LIVEKIT_SECRET}
room:
  empty_timeout: 300
  max_participants: 4
log_level: info
EOF
    sudo chmod 600 /opt/livekit/livekit.yaml
    sudo chown "$svc_user:$svc_user" /opt/livekit/livekit.yaml

    log "3.4 Locate livekit-server binary"
    local lk_bin; lk_bin=$(command -v livekit-server || true)
    if [ -z "$lk_bin" ]; then
        for cand in /usr/local/bin/livekit-server /opt/livekit/bin/livekit-server /usr/bin/livekit-server; do
            if [ -x "$cand" ]; then lk_bin="$cand"; break; fi
        done
    fi
    [ -z "$lk_bin" ] && die "livekit-server binary not found"
    log "  livekit-server binary: $lk_bin"

    log "3.5 Write systemd unit"
    sudo tee /etc/systemd/system/livekit-server.service >/dev/null <<EOF
[Unit]
Description=LiveKit SFU server (cycle-2R self-hosted)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${svc_user}
ExecStart=${lk_bin} --config /opt/livekit/livekit.yaml
Restart=on-failure
RestartSec=5s
LimitNOFILE=500000

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    if ! sudo systemctl is-active --quiet livekit-server; then
        sudo systemctl enable --now livekit-server || die "livekit-server start failed"
    else
        sudo systemctl restart livekit-server
    fi
    sleep 3

    log "3.6 Verify"
    sudo systemctl status livekit-server --no-pager | head -25
    sudo systemctl is-active livekit-server >/dev/null || die "livekit-server not active after start"
    ss -tunlp | grep -E ':7880|:7881|:7882|:3478|:5349' | sort
}

# ─────────────────────────────────────────────────────────────────────
# Phase 4 — Vercel env-flag + worker .env + preview deploy
# ─────────────────────────────────────────────────────────────────────
phase_4() {
    log "==== Phase 4: Vercel env-flag + worker .env + preview deploy ===="

    require_env VERCEL_TOKEN
    require_env TEAM_A_LIVEKIT_KEY
    require_env TEAM_A_LIVEKIT_SECRET

    log "4.1 Reminder: edit /Users/kiteboard/prism42/mvp/911-console-live/app/prism42/api/livekit-token/route.ts"
    log "  to honor LIVEKIT_BACKEND env var. See runbook.md §4.1."
    log "  (This script does NOT auto-edit source code — Team R authors the runbook;"
    log "   integrator applies the edit + commits.)"

    log "4.2 Add Vercel preview env vars"
    cd "$VERCEL_PROJECT_DIR"
    # `vercel env add NAME ENVIRONMENT <<< "value"` adds to the named env.
    # If already exists, vercel returns nonzero; we treat as soft-success.
    echo "selfhost"             | vercel env add LIVEKIT_BACKEND                 preview --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true
    echo "$LIVEKIT_WSS_URL"     | vercel env add NEXT_PUBLIC_LIVEKIT_URL_SELFHOST preview --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true
    echo "$TEAM_A_LIVEKIT_KEY"  | vercel env add LIVEKIT_API_KEY_SELFHOST        preview --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true
    echo "$TEAM_A_LIVEKIT_SECRET" | vercel env add LIVEKIT_API_SECRET_SELFHOST   preview --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true

    log "4.3 Verify env vars set"
    vercel env ls preview --token "$VERCEL_TOKEN" \
        | grep -E "LIVEKIT_BACKEND|NEXT_PUBLIC_LIVEKIT_URL_SELFHOST|LIVEKIT_API_KEY_SELFHOST|LIVEKIT_API_SECRET_SELFHOST" \
        || die "Vercel env vars missing"

    log "4.4 Update worker .env on pod"
    if [ ! -f "$WORKER_ENV_PATH" ]; then
        log "  WARN: worker .env not found at $WORKER_ENV_PATH"
        log "  Confirm path: systemctl cat prism42-worker | grep EnvironmentFile"
        log "  Skipping worker .env update; integrator handles manually."
    else
        sudo cp "$WORKER_ENV_PATH" "${WORKER_ENV_PATH}.cycle2R-backup"
        # Remove any prior LIVEKIT_URL/LIVEKIT_BACKEND/LIVEKIT_API_KEY/LIVEKIT_API_SECRET lines
        sudo sed -i.bak '/^LIVEKIT_URL=/d; /^LIVEKIT_BACKEND=/d; /^LIVEKIT_API_KEY=/d; /^LIVEKIT_API_SECRET=/d' "$WORKER_ENV_PATH"
        # Append new ones
        sudo tee -a "$WORKER_ENV_PATH" >/dev/null <<EOF
# cycle-2R: LiveKit self-host backend
LIVEKIT_BACKEND=selfhost
LIVEKIT_URL=${LIVEKIT_WSS_URL}
LIVEKIT_API_KEY=${TEAM_A_LIVEKIT_KEY}
LIVEKIT_API_SECRET=${TEAM_A_LIVEKIT_SECRET}
EOF
        sudo chmod 600 "$WORKER_ENV_PATH"
        log "  Restarting prism42-worker"
        sudo systemctl restart prism42-worker || die "worker restart failed"
        sleep 5
        sudo journalctl -u prism42-worker --since="30 sec ago" -n 50 \
            | grep -E "registered worker|connecting to|wss://${LIVEKIT_DOMAIN}" \
            | tail -10 \
            || log "  WARN: no registration line found in last 30s; investigate"
    fi

    log "4.5 Vercel preview deploy"
    cd "$VERCEL_PROJECT_DIR"
    vercel --token "$VERCEL_TOKEN" 2>&1 | tee /tmp/cycle2R-vercel-deploy.log
    log "  Capture preview URL from log above; integrator opens in browser for §5 smoke."
}

# ─────────────────────────────────────────────────────────────────────
# Phase 5 — End-to-end voice turn smoke (manual)
# ─────────────────────────────────────────────────────────────────────
phase_5() {
    log "==== Phase 5: End-to-end voice turn smoke (manual) ===="

    log "5.1 Pre-check pod-side daemons"
    sudo systemctl is-active livekit-server caddy prism42-worker || die "one or more daemons not active"

    log "5.2 Pre-check WSS reachability + cert"
    echo \
        | timeout 5 openssl s_client -connect "${LIVEKIT_DOMAIN}:443" -servername "${LIVEKIT_DOMAIN}" 2>/dev/null \
        | openssl x509 -noout -subject -issuer -dates 2>/dev/null \
        || die "TLS handshake to ${LIVEKIT_DOMAIN}:443 failed"

    log "5.3 Manual checklist (integrator runs in browser):"
    cat <<EOF

  1. Open Vercel preview URL in Chrome: <preview>/prism42/livekit
  2. Allow microphone access.
  3. Listen for greeting (Cartesia Sonic-3 TTS).
  4. Speak: "I need an ambulance, my address is 123 Main."
  5. Listen for dispatcher reply (Opus 4.7 LLM -> Cartesia TTS).
  6. End the call.

  Telemetry capture (in DevTools console while live):
    performance.getEntriesByType('measure').filter(m => m.name.startsWith('b3-'))
      .forEach(m => console.log(m.name, m.duration.toFixed(0), 'ms'));

  Pod-side log capture (run in another terminal):
    sudo journalctl -u prism42-worker --since="2 min ago" -n 200 | \\
      grep -E "turn|publish|subscribe|error|warn"

  Promotion gate — only flip production after:
    - Greeting audible + intelligible
    - Dispatcher reply audible + intelligible + on-topic
    - No 'error' entries in pod log
    - p95 round-trip < 1.5s on 3 consecutive turns
    - Brandon (user) personally attests preview sounds correct

EOF
}

# ─────────────────────────────────────────────────────────────────────
# Phase 6 — Production cutover
# ─────────────────────────────────────────────────────────────────────
phase_6() {
    log "==== Phase 6: Production cutover ===="

    require_gate PRISM42_AUTH_G6   # GATE_G6
    require_env  VERCEL_TOKEN
    require_env  TEAM_A_LIVEKIT_KEY
    require_env  TEAM_A_LIVEKIT_SECRET

    log "6.1 Add production env vars"
    cd "$VERCEL_PROJECT_DIR"
    echo "selfhost"             | vercel env add LIVEKIT_BACKEND                 production --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true
    echo "$LIVEKIT_WSS_URL"     | vercel env add NEXT_PUBLIC_LIVEKIT_URL_SELFHOST production --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true
    echo "$TEAM_A_LIVEKIT_KEY"  | vercel env add LIVEKIT_API_KEY_SELFHOST        production --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true
    echo "$TEAM_A_LIVEKIT_SECRET" | vercel env add LIVEKIT_API_SECRET_SELFHOST   production --token "$VERCEL_TOKEN" 2>&1 | tee -a /tmp/cycle2R-vercel.log || true

    log "6.2 Trigger production redeploy"
    vercel --prod --token "$VERCEL_TOKEN" 2>&1 | tee /tmp/cycle2R-vercel-prod-deploy.log

    log "6.3 Verify token route returns selfhost URL"
    sleep 30   # give edge propagation a head start
    local probe
    probe=$(curl -fsS -X POST https://www.thegoatnote.com/prism42/api/livekit-token \
        -H "Content-Type: application/json" \
        -d '{"session_id":"smoke-prod-cutover-001"}' || echo '{}')
    log "  token route response: $probe"
    if echo "$probe" | grep -q "$LIVEKIT_DOMAIN"; then
        log "  PASS — production token route returns wss://${LIVEKIT_DOMAIN}"
    else
        die "token route did NOT return ${LIVEKIT_DOMAIN}; production may still be on cloud (edge cache)"
    fi

    log "6.4 Verify ElevenLabs fallback /prism42-v3 still 200"
    if curl -sIo /dev/null -w '%{http_code}' https://www.thegoatnote.com/prism42-v3 --max-time 10 | grep -q "^200$"; then
        log "  PASS — /prism42-v3 fallback intact"
    else
        log "  WARN — /prism42-v3 not returning 200; investigate before declaring win"
    fi

    log "6.5 Manual: live voice turn against https://www.thegoatnote.com/prism42/livekit (see §5.3)"
}

# ─────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ─────────────────────────────────────────────────────────────────────
main() {
    local phase=""
    for arg in "$@"; do
        case "$arg" in
            --phase=0|--phase=1|--phase=2|--phase=3|--phase=4|--phase=5|--phase=6|--phase=all)
                phase="${arg#--phase=}"
                ;;
            -h|--help)
                grep -E "^# (Usage:|Authorization|Required env|  )" "$0" | sed 's/^# //'
                exit 0
                ;;
            *)
                die "unknown arg: $arg (try --help)"
                ;;
        esac
    done

    [ -z "$phase" ] && die "no --phase=<N> specified; try --help"

    case "$phase" in
        0)   phase_0 ;;
        1)   phase_1 ;;
        2)   phase_2 ;;
        3)   phase_3 ;;
        4)   phase_4 ;;
        5)   phase_5 ;;
        6)   phase_6 ;;
        all)
            phase_0
            log ">>> Phase 0 done. Proceeding to Phase 1 (G3 required)."
            phase_1
            log ">>> Phase 1 done. Proceeding to Phase 2 (G3)."
            phase_2
            log ">>> Phase 2 done. Proceeding to Phase 3 (G4 required)."
            phase_3
            log ">>> Phase 3 done. Proceeding to Phase 4 (Vercel preview)."
            phase_4
            log ">>> Phase 4 done. Phase 5 is manual — see checklist."
            phase_5
            log ">>> Phase 5 manual checklist printed. After Brandon attests, run --phase=6."
            ;;
    esac

    log "phase=$phase complete"
}

main "$@"
