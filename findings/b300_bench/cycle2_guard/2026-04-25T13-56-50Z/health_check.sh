#!/usr/bin/env bash
# cycle-2 guard: 4-service health watchdog
# Re-runnable. Exit 0 = all 4 services green. Exit non-zero = explicit diagnostic.
# Used by every cycle-2 executor BEFORE and AFTER its mutation.
#
# Services audited:
#   1. prism42-worker  (systemd)
#   2. prism42-fish    (systemd) + HTTP probe :9200
#   3. parakeet        (NOT systemd — nohup process listening :9100)
#   4. vllm            (pid 285669, nohup) + HTTP probe :8001/v1/models
#
# Usage:  ./health_check.sh
# CI use: if ! ./health_check.sh; then echo HALT; exit 1; fi

set -u
SSH_HOST="${SSH_HOST:-prism-mla-b300-h4h5}"
EXIT_CODE=0
FAIL_DIAG=()

probe() {
    local label="$1"
    local cmd="$2"
    local expect_substr="$3"

    local out
    out=$(ssh -o BatchMode=yes "$SSH_HOST" "$cmd" 2>&1)
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        FAIL_DIAG+=("[$label] ssh/cmd rc=$rc out=${out:0:200}")
        EXIT_CODE=1
        echo "FAIL $label rc=$rc"
        return 1
    fi

    if [[ -n "$expect_substr" && "$out" != *"$expect_substr"* ]]; then
        FAIL_DIAG+=("[$label] expected '$expect_substr' missing in: ${out:0:200}")
        EXIT_CODE=1
        echo "FAIL $label expected='$expect_substr'"
        return 1
    fi

    echo "OK   $label"
    return 0
}

echo "=== cycle-2 4-service health watchdog @ $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# 1. prism42-worker systemd active
probe "worker.systemd" \
    "systemctl is-active prism42-worker" \
    "active"

# 2. prism42-fish systemd active
probe "fish.systemd" \
    "systemctl is-active prism42-fish" \
    "active"

# 2b. fish HTTP root reachable (Swagger page)
probe "fish.http" \
    "curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:9200/" \
    "200"

# 3. parakeet HTTP /healthz returns model loaded
probe "parakeet.http" \
    "curl -sS -m 5 http://127.0.0.1:9100/healthz" \
    "parakeet-tdt-0.6b-v3"

# 4. vllm HTTP /v1/models 200
probe "vllm.http" \
    "curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/v1/models" \
    "200"

# 4b. vllm parent pid 285669 still alive
probe "vllm.pid" \
    "ps -p 285669 -o pid= --no-headers | tr -d ' '" \
    "285669"

echo
if [[ $EXIT_CODE -ne 0 ]]; then
    echo "=== FAIL: cycle-2 health regressed ==="
    for d in "${FAIL_DIAG[@]}"; do
        echo "  $d"
    done
    echo "=== HALT — block any pending mutating executor ==="
else
    echo "=== PASS: all 4 services green ==="
fi

exit $EXIT_CODE
