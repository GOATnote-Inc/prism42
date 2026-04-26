#!/usr/bin/env bash
# cycle-2R LiveKit self-host — rollback script
#
# Reverses everything run.sh did. Idempotent — safe to re-run after
# partial state. The LAST step always restores LiveKit Cloud as the
# active backend on Vercel production, so even mid-rollback the demo
# path is back online.
#
# Usage:
#   ./rollback.sh                  # run all phases in reverse (6 -> 0)
#   ./rollback.sh --phase=N        # roll back only phase N
#   ./rollback.sh --dry-run        # print actions without executing
#
# Authorization flags:
#   PRISM42_AUTH_G2=1   GoDaddy DNS revert (only set if Phase 0 ran)
#   PRISM42_AUTH_G3=1   UFW + Caddy teardown
#   PRISM42_AUTH_G4=1   livekit-server systemd takedown + bare-process restore
#
# CRITICAL: the Vercel production env-flip (Phase 6 rollback) runs FIRST
# and unconditionally — if you're rolling back, the demo URL must work.

set -Eeuo pipefail

# ─────────────────────────────────────────────────────────────────────
# Configuration (must match run.sh)
# ─────────────────────────────────────────────────────────────────────
POD_PUBLIC_IP="31.22.104.100"
LIVEKIT_DOMAIN="prism42.thegoatnote.com"
TURN_DOMAIN="turn-prism42.thegoatnote.com"
WORKER_ENV_PATH="/opt/prism42/worker/.env"
VERCEL_PROJECT_DIR="/Users/kiteboard/prism42/mvp/911-console-live"

DRY_RUN=0

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }
softfail() { printf '[%s] SOFT-FAIL: %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  DRY: %s\n' "$*"
    else
        # Don't `set -e` out on rollback steps — we want to keep going.
        eval "$@" || softfail "command failed (continuing): $*"
    fi
}

require_gate_soft() {
    # In rollback, missing gate is a WARN not a die — we still try to
    # do whatever we can with whatever auth we have.
    local gate="$1"; local what="$2"
    if [ -z "${!gate:-}" ]; then
        warn "$gate not set; skipping $what (set $gate=1 to include)"
        return 1
    fi
    return 0
}

# ─────────────────────────────────────────────────────────────────────
# Rollback Phase 6 — Vercel production env flip back to cloud (RUNS FIRST)
# ─────────────────────────────────────────────────────────────────────
rollback_6() {
    log "==== Rollback Phase 6: production env back to cloud (RUNS FIRST) ===="

    if [ -z "${VERCEL_TOKEN:-}" ]; then
        warn "VERCEL_TOKEN not set; cannot revert production env."
        warn "Manual step: vercel env rm LIVEKIT_BACKEND production --yes && vercel --prod"
        return 1
    fi

    log "6a. Remove LIVEKIT_BACKEND from production (defaults to cloud when unset)"
    cd "$VERCEL_PROJECT_DIR"
    run "vercel env rm LIVEKIT_BACKEND production --yes --token \"$VERCEL_TOKEN\" 2>&1 | tee -a /tmp/cycle2R-rollback.log"
    # The other *_SELFHOST vars can stay; they're inert when LIVEKIT_BACKEND is unset.

    log "6b. Trigger production redeploy"
    run "vercel --prod --token \"$VERCEL_TOKEN\" 2>&1 | tee /tmp/cycle2R-rollback-prod.log"

    log "6c. Verify token route returns Cloud URL"
    sleep 30
    local probe
    probe=$(curl -fsS -X POST https://www.thegoatnote.com/prism42/api/livekit-token \
        -H "Content-Type: application/json" \
        -d '{"session_id":"smoke-rollback-001"}' 2>/dev/null || echo '{}')
    log "  token route: $probe"
    if echo "$probe" | grep -q "livekit.cloud"; then
        log "  PASS — production back on LiveKit Cloud."
    else
        warn "production token route did NOT return *.livekit.cloud — verify env"
    fi
}

# ─────────────────────────────────────────────────────────────────────
# Rollback Phase 4 — Vercel preview env + worker .env + token-route code
# ─────────────────────────────────────────────────────────────────────
rollback_4() {
    log "==== Rollback Phase 4: preview env + worker .env ===="

    if [ -n "${VERCEL_TOKEN:-}" ]; then
        cd "$VERCEL_PROJECT_DIR"
        log "4a. Remove preview env vars"
        run "vercel env rm LIVEKIT_BACKEND                  preview --yes --token \"$VERCEL_TOKEN\" 2>&1 | tee -a /tmp/cycle2R-rollback.log"
        run "vercel env rm NEXT_PUBLIC_LIVEKIT_URL_SELFHOST preview --yes --token \"$VERCEL_TOKEN\" 2>&1 | tee -a /tmp/cycle2R-rollback.log"
        run "vercel env rm LIVEKIT_API_KEY_SELFHOST         preview --yes --token \"$VERCEL_TOKEN\" 2>&1 | tee -a /tmp/cycle2R-rollback.log"
        run "vercel env rm LIVEKIT_API_SECRET_SELFHOST      preview --yes --token \"$VERCEL_TOKEN\" 2>&1 | tee -a /tmp/cycle2R-rollback.log"
        # Production *_SELFHOST keys stay until full teardown completes.
    else
        warn "VERCEL_TOKEN not set; cannot revert preview env vars (manual: vercel env rm ...)"
    fi

    log "4b. Restore worker .env from backup if present"
    if [ -f "${WORKER_ENV_PATH}.cycle2R-backup" ]; then
        run "sudo mv \"${WORKER_ENV_PATH}.cycle2R-backup\" \"$WORKER_ENV_PATH\""
        run "sudo systemctl restart prism42-worker"
        sleep 3
        run "sudo journalctl -u prism42-worker --since='30 sec ago' -n 30 | grep -E 'registered worker|connecting to' | tail -5"
    else
        warn "No worker .env backup at ${WORKER_ENV_PATH}.cycle2R-backup; manual revert required"
    fi

    log "4c. Reminder: revert token-route code change in route.ts (manual git revert)"
    log "   File: ${VERCEL_PROJECT_DIR}/app/prism42/api/livekit-token/route.ts"
}

# ─────────────────────────────────────────────────────────────────────
# Rollback Phase 3 — livekit-server systemd takedown
# ─────────────────────────────────────────────────────────────────────
rollback_3() {
    log "==== Rollback Phase 3: livekit-server systemd takedown ===="

    if ! require_gate_soft PRISM42_AUTH_G4 "livekit-server systemd takedown"; then
        return 0
    fi

    log "3a. Stop + disable systemd unit"
    if sudo systemctl is-active --quiet livekit-server 2>/dev/null; then
        run "sudo systemctl disable --now livekit-server"
    fi
    run "sudo rm -f /etc/systemd/system/livekit-server.service"
    run "sudo systemctl daemon-reload"

    log "3b. (Manual) re-launch bare livekit-server with original cmdline if Team A captured it."
    log "    Original cmdline lived in /tmp/cycle2R-bare-livekit-cmdline.txt if Phase 3.1 saved it."
    if [ -f /tmp/cycle2R-bare-livekit-cmdline.txt ]; then
        log "    cmdline: $(cat /tmp/cycle2R-bare-livekit-cmdline.txt)"
        log "    To resume bare process: nohup <cmdline> > /var/log/livekit-server-bare.log 2>&1 &"
    else
        warn "no captured bare cmdline; livekit-server is now down. Demo will use Cloud-side livekit."
    fi

    log "3c. Leave /opt/livekit/livekit.yaml in place (harmless without daemon)"
}

# ─────────────────────────────────────────────────────────────────────
# Rollback Phase 2 — Caddy teardown
# ─────────────────────────────────────────────────────────────────────
rollback_2() {
    log "==== Rollback Phase 2: Caddy teardown ===="

    if ! require_gate_soft PRISM42_AUTH_G3 "Caddy teardown"; then
        return 0
    fi

    if sudo systemctl is-active --quiet caddy 2>/dev/null; then
        run "sudo systemctl disable --now caddy"
    fi
    run "sudo apt-get remove -y caddy 2>&1 | tail -5"
    run "sudo rm -f /etc/caddy/Caddyfile"
    # Leave /var/log/caddy and /var/lib/caddy in place — harmless, easier re-install if needed.
}

# ─────────────────────────────────────────────────────────────────────
# Rollback Phase 1 — UFW rule removal
# ─────────────────────────────────────────────────────────────────────
rollback_1() {
    log "==== Rollback Phase 1: UFW rule removal ===="

    if ! require_gate_soft PRISM42_AUTH_G3 "UFW rule removal"; then
        return 0
    fi

    # Idempotent: ufw delete is OK if the rule isn't there.
    run "sudo ufw delete allow 7880/tcp 2>/dev/null || true"
    run "sudo ufw delete allow 7881/tcp 2>/dev/null || true"
    run "sudo ufw delete allow 7882/udp 2>/dev/null || true"
    run "sudo ufw delete allow 50000:60000/udp 2>/dev/null || true"
    run "sudo ufw delete allow 3478/udp 2>/dev/null || true"
    run "sudo ufw delete allow 5349/tcp 2>/dev/null || true"
    run "sudo ufw delete allow 80/tcp 2>/dev/null || true"
    run "sudo ufw delete allow 443/tcp 2>/dev/null || true"
    run "sudo ufw reload"
    run "sudo ufw status numbered"
}

# ─────────────────────────────────────────────────────────────────────
# Rollback Phase 0 — DNS revert
# ─────────────────────────────────────────────────────────────────────
rollback_0() {
    log "==== Rollback Phase 0: DNS revert ===="

    if ! require_gate_soft PRISM42_AUTH_G2 "DNS revert"; then
        return 0
    fi

    if [ -z "${GODADDY_API_KEY:-}" ] || [ -z "${GODADDY_API_SECRET:-}" ]; then
        warn "GoDaddy creds not set; skipping DNS revert (manual: PUT /v1/domains/.../records/A/livekit)"
        return 0
    fi

    local auth_header="Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}"

    # Replace with 0.0.0.0 placeholder (GoDaddy rejects empty body)
    log "0a. PATCH prism42 -> 0.0.0.0 (placeholder)"
    run "curl -fsS -X PUT 'https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/prism42' \
        -H '$auth_header' \
        -H 'Content-Type: application/json' \
        -d '[{\"data\":\"0.0.0.0\",\"ttl\":600}]'"

    log "0b. PATCH turn-prism42 -> 0.0.0.0 (placeholder)"
    run "curl -fsS -X PUT 'https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/turn-prism42' \
        -H '$auth_header' \
        -H 'Content-Type: application/json' \
        -d '[{\"data\":\"0.0.0.0\",\"ttl\":600}]'"

    log "0c. Note: Caddy holds an LE cert for ${LIVEKIT_DOMAIN}; renewal will fail post-revert."
    log "   That's fine — Caddy is also being torn down in rollback_2."
}

# ─────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ─────────────────────────────────────────────────────────────────────
main() {
    local single_phase=""
    for arg in "$@"; do
        case "$arg" in
            --dry-run)
                DRY_RUN=1
                log "DRY-RUN MODE: no commands will execute"
                ;;
            --phase=0|--phase=1|--phase=2|--phase=3|--phase=4|--phase=6)
                single_phase="${arg#--phase=}"
                ;;
            -h|--help)
                grep -E "^# (Usage:|Authorization|CRITICAL|  )" "$0" | sed 's/^# //'
                exit 0
                ;;
            *)
                warn "unknown arg: $arg (try --help)"
                exit 2
                ;;
        esac
    done

    if [ -n "$single_phase" ]; then
        log "Single-phase rollback: $single_phase"
        case "$single_phase" in
            0) rollback_0 ;;
            1) rollback_1 ;;
            2) rollback_2 ;;
            3) rollback_3 ;;
            4) rollback_4 ;;
            6) rollback_6 ;;
        esac
    else
        log "Full rollback in reverse order (6 first to restore demo URL)"
        rollback_6   # restore demo URL FIRST
        rollback_4
        rollback_3
        rollback_2
        rollback_1
        rollback_0
        log "Full rollback complete."
    fi

    log "Verify state:"
    log "  - Production token route: curl -X POST https://www.thegoatnote.com/prism42/api/livekit-token -H 'Content-Type: application/json' -d '{\"session_id\":\"verify001\"}'"
    log "    Expected: livekit_url contains 'livekit.cloud'"
    log "  - Fallback /prism42-v3: curl -sI https://www.thegoatnote.com/prism42-v3 | head -1"
    log "    Expected: HTTP/2 200"
}

main "$@"
