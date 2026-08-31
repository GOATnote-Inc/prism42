#!/usr/bin/env bash
# cycle-2R BEHAVIOR-restore script
# Returns the prism42 voice demo to the exact behavior captured at
# 2026-04-26 09:03 UTC: cycle-2N MW reference + cycle-2P file-backed
# greeting + cycle-2Q FSM-on + LiveKit Cloud media plane.
#
# Usage:
#   ./restore.sh             # full restore (pod + Vercel)
#   ./restore.sh --pod-only
#   ./restore.sh --vercel-only
#   ./restore.sh --check     # dry-run; print what would change
#
# Exit codes:
#   0 = restore complete + verification passed
#   1 = pre-flight failure (tarball missing, SHA mismatch, ssh unreachable)
#   2 = pod restore failed
#   3 = Vercel restore failed
#   4 = post-restore verification failed

set -euo pipefail

cd "$(dirname "$0")"

readonly POD="b300-pod"
readonly TARBALL="pod-state.local.tgz"
readonly EXPECTED_SHA="107f8aa68522dc9c6155526610100de3bc4cb0e39587bcf1be2ec4c0e5e50581"
readonly CLOUD_URL="wss://ai-therapy-v3svfd9o.livekit.cloud"
readonly VERCEL_PROJECT_DIR="~/prism42/mvp/911-console-live"

# Vercel env vars added by cycle-2R that must be removed on restore
readonly CYCLE2R_NEW_ENV_VARS=(
    "LIVEKIT_BACKEND"
    "NEXT_PUBLIC_LIVEKIT_URL_SELFHOST"
    "LIVEKIT_API_KEY_SELFHOST"
    "LIVEKIT_API_SECRET_SELFHOST"
)

# UFW rules added by cycle-2R that must be removed on restore
readonly CYCLE2R_UFW_PORTS=(
    "7880/tcp" "7881/tcp" "80/tcp" "443/tcp"
    "5349/tcp" "7882/udp" "3478/udp"
    "50000:60000/udp"
)

DRY_RUN=0
POD_ONLY=0
VERCEL_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --check) DRY_RUN=1 ;;
        --pod-only) POD_ONLY=1 ;;
        --vercel-only) VERCEL_ONLY=1 ;;
        *) echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

log() { printf '\n[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
run() {
    if [ "$DRY_RUN" = "1" ]; then
        printf '  WOULD-RUN: %s\n' "$*"
    else
        eval "$@"
    fi
}

# -----------------------------------------------------------------------
# Pre-flight: tarball + SHA + ssh
# -----------------------------------------------------------------------
log "PRE-FLIGHT: tarball + SHA + ssh reachability"

if [ ! -f "$TARBALL" ]; then
    echo "FATAL: $TARBALL not found in $(pwd)" >&2
    exit 1
fi

ACTUAL_SHA=$(shasum -a 256 "$TARBALL" | awk '{print $1}')
if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
    echo "FATAL: SHA mismatch on $TARBALL" >&2
    echo "  expected: $EXPECTED_SHA" >&2
    echo "  actual:   $ACTUAL_SHA" >&2
    echo "  Refusing to restore from a possibly-corrupted backup." >&2
    exit 1
fi
log "  tarball SHA OK ($ACTUAL_SHA)"

if [ "$POD_ONLY" != "1" ] && [ "$VERCEL_ONLY" != "1" ] || [ "$VERCEL_ONLY" != "1" ]; then
    if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$POD" 'echo ok' >/dev/null 2>&1; then
        echo "FATAL: ssh $POD unreachable" >&2
        exit 1
    fi
    log "  ssh $POD reachable"
fi

# -----------------------------------------------------------------------
# Vercel restore (production env)
# -----------------------------------------------------------------------
restore_vercel() {
    log "VERCEL: restore production env"

    if [ ! -d "$VERCEL_PROJECT_DIR" ]; then
        echo "FATAL: $VERCEL_PROJECT_DIR missing" >&2
        return 3
    fi

    pushd "$VERCEL_PROJECT_DIR" >/dev/null

    # Restore NEXT_PUBLIC_LIVEKIT_URL to LiveKit Cloud
    if [ "$DRY_RUN" = "1" ]; then
        printf '  WOULD-RUN: vercel env rm NEXT_PUBLIC_LIVEKIT_URL production --yes (if exists)\n'
        printf '  WOULD-RUN: echo "%s" | vercel env add NEXT_PUBLIC_LIVEKIT_URL production\n' "$CLOUD_URL"
    else
        # rm is allowed to fail (env var may not exist); add must succeed
        vercel env rm NEXT_PUBLIC_LIVEKIT_URL production --yes >/dev/null 2>&1 || true
        printf '%s' "$CLOUD_URL" | vercel env add NEXT_PUBLIC_LIVEKIT_URL production
    fi
    log "  NEXT_PUBLIC_LIVEKIT_URL restored to $CLOUD_URL"

    # Remove any cycle-2R-added env vars
    for var in "${CYCLE2R_NEW_ENV_VARS[@]}"; do
        if [ "$DRY_RUN" = "1" ]; then
            printf '  WOULD-RUN: vercel env rm %s production --yes (if exists)\n' "$var"
            printf '  WOULD-RUN: vercel env rm %s preview --yes (if exists)\n' "$var"
        else
            vercel env rm "$var" production --yes >/dev/null 2>&1 || true
            vercel env rm "$var" preview --yes >/dev/null 2>&1 || true
        fi
        log "  removed $var (if existed) from production + preview"
    done

    # Trigger a redeploy so the env-flip takes effect
    if [ "$DRY_RUN" = "1" ]; then
        printf '  WOULD-RUN: vercel --prod (redeploy production)\n'
    else
        vercel --prod --yes >/dev/null 2>&1 || {
            echo "WARN: vercel --prod failed; manual redeploy needed" >&2
        }
    fi
    log "  vercel --prod redeploy triggered"

    popd >/dev/null
    return 0
}

# -----------------------------------------------------------------------
# Pod restore (systemd drop-ins, source files, voice-refs, UFW reset)
# -----------------------------------------------------------------------
restore_pod() {
    log "POD: copying tarball + extracting + restarting services"

    if [ "$DRY_RUN" = "1" ]; then
        printf '  WOULD-RUN: scp %s %s:/tmp/\n' "$TARBALL" "$POD"
        printf '  WOULD-RUN: ssh %s sudo tar -xzf /tmp/%s -C /\n' "$POD" "$TARBALL"
    else
        scp "$TARBALL" "$POD:/tmp/cycle2R-baseline-restore.tgz"
        # Extract with -p preserve permissions, into / (tarball was made with absolute paths under sudo)
        ssh "$POD" "sudo tar -xzpf /tmp/cycle2R-baseline-restore.tgz -C / && rm /tmp/cycle2R-baseline-restore.tgz"
        ssh "$POD" 'sudo chown -R shadeform:shadeform /opt/prism42/agents/livekit/ /opt/prism42/voice-refs/'
    fi
    log "  pod files extracted in place"

    # UFW reset: remove cycle-2R-added rules; baseline only allows SSH
    log "POD: UFW reset to baseline (SSH only)"
    for port in "${CYCLE2R_UFW_PORTS[@]}"; do
        if [ "$DRY_RUN" = "1" ]; then
            printf '  WOULD-RUN: ssh %s sudo ufw delete allow %s\n' "$POD" "$port"
        else
            ssh "$POD" "sudo ufw delete allow $port" 2>/dev/null || true
        fi
    done

    # Caddy: stop + disable if installed (it's added by cycle-2R, not in baseline)
    log "POD: Caddy stop + disable (if installed)"
    if [ "$DRY_RUN" = "1" ]; then
        printf '  WOULD-RUN: ssh %s sudo systemctl disable --now caddy 2>/dev/null || true\n' "$POD"
    else
        ssh "$POD" 'sudo systemctl disable --now caddy 2>/dev/null || true'
    fi

    # daemon-reload + restart core services
    log "POD: daemon-reload + restart prism42-worker, prism42-fish"
    if [ "$DRY_RUN" = "1" ]; then
        printf '  WOULD-RUN: ssh %s sudo systemctl daemon-reload && sudo systemctl restart prism42-worker prism42-fish\n' "$POD"
    else
        ssh "$POD" 'sudo systemctl daemon-reload && sudo systemctl restart prism42-worker prism42-fish'
    fi

    return 0
}

# -----------------------------------------------------------------------
# Post-restore verification
# -----------------------------------------------------------------------
verify_pod() {
    log "VERIFY: pod service health"

    sleep 5  # give services a moment to come up

    local worker_state fish_state
    worker_state=$(ssh "$POD" 'systemctl is-active prism42-worker' 2>/dev/null || echo "unknown")
    fish_state=$(ssh "$POD" 'systemctl is-active prism42-fish' 2>/dev/null || echo "unknown")

    if [ "$worker_state" = "active" ]; then
        log "  prism42-worker: active OK"
    else
        echo "FAIL: prism42-worker is $worker_state (expected: active)" >&2
        return 4
    fi

    if [ "$fish_state" = "active" ]; then
        log "  prism42-fish: active OK"
    else
        echo "FAIL: prism42-fish is $fish_state (expected: active)" >&2
        return 4
    fi

    # Worker must be registered with LiveKit Cloud (the restore target)
    local registered_url
    registered_url=$(ssh "$POD" 'tail -200 /tmp/prism42-logs/worker.log 2>/dev/null | grep "registered worker" | tail -1' || echo "")
    if printf '%s' "$registered_url" | grep -q "ai-therapy-v3svfd9o.livekit.cloud"; then
        log "  worker registered with LiveKit Cloud OK"
    else
        echo "WARN: worker registration log doesn't confirm Cloud URL; check manually" >&2
    fi

    return 0
}

verify_vercel() {
    log "VERIFY: Vercel production env"

    pushd "$VERCEL_PROJECT_DIR" >/dev/null

    # Check NEXT_PUBLIC_LIVEKIT_URL is back to Cloud
    local has_cloud
    has_cloud=$(vercel env ls production 2>/dev/null | grep -c "NEXT_PUBLIC_LIVEKIT_URL " || echo "0")
    if [ "$has_cloud" -gt 0 ]; then
        log "  NEXT_PUBLIC_LIVEKIT_URL exists in production OK"
    else
        echo "FAIL: NEXT_PUBLIC_LIVEKIT_URL missing from production env" >&2
        popd >/dev/null
        return 4
    fi

    # Confirm cycle-2R env vars are gone
    for var in "${CYCLE2R_NEW_ENV_VARS[@]}"; do
        if vercel env ls production 2>/dev/null | grep -q "^$var "; then
            echo "WARN: $var still present in production (expected to be removed)" >&2
        fi
    done

    popd >/dev/null
    return 0
}

# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
log "===== cycle-2R BEHAVIOR-restore start ====="

if [ "$DRY_RUN" = "1" ]; then
    log "DRY-RUN MODE — no changes will be made"
fi

if [ "$VERCEL_ONLY" != "1" ]; then
    restore_pod || { echo "POD restore failed" >&2; exit 2; }
fi

if [ "$POD_ONLY" != "1" ]; then
    restore_vercel || { echo "VERCEL restore failed" >&2; exit 3; }
fi

if [ "$DRY_RUN" != "1" ]; then
    if [ "$VERCEL_ONLY" != "1" ]; then
        verify_pod || exit 4
    fi
    if [ "$POD_ONLY" != "1" ]; then
        verify_vercel || exit 4
    fi
fi

log "===== cycle-2R BEHAVIOR-restore complete ====="
echo
echo "Demo path restored to: cycle-2Q FSM-on + cycle-2P MW greeting + cycle-2N MW voice + LiveKit Cloud media."
echo "Verify in browser: https://prism42-console.vercel.app/prism42/livekit"
echo
