#!/bin/bash
# One-command B300 pod health check + heal + synthetic-call smoke.
#
# Designed to run in two modes:
#   1. ON the pod directly:
#        bash /opt/prism42/scripts/b300_runbook.sh
#        bash /opt/prism42/scripts/b300_runbook.sh --heal
#   2. FROM the laptop, via brev exec:
#        brev exec b300-pod 'bash /opt/prism42/scripts/b300_runbook.sh'
#        brev exec b300-pod 'bash /opt/prism42/scripts/b300_runbook.sh --heal'
#
# Exit codes:
#   0 — all checks PASS
#   1 — at least one check FAIL
#
# Services checked:
#   - Parakeet STT on 127.0.0.1:9100 (GET /healthz)
#   - Fish TTS on 127.0.0.1:9200   (GET /healthz, fallback /v1/health)
#   - Redis on 127.0.0.1:6379      (PING via redis-cli OR docker exec)
#   - prism42-worker systemd unit   (active + "registered worker" in log)
#   - prism42-worker-starter (optional — only checked if enabled)
#   - synthetic_caller.py round-trip (VERDICT: PASS within 45 s)
#
# Log files (read by this script):
#   /tmp/prism42-logs/worker.log          LiveKit agent worker
#   /tmp/prism42-logs/worker-starter.log  Escape-hatch Deepgram/Cartesia worker (if deployed)
#   /tmp/prism42-logs/parakeet.log        Parakeet STT (ad-hoc nohup runs)
#   /tmp/prism42-logs/fish.log            Fish TTS (ad-hoc nohup runs)
#
# This script is NOT a replacement for scripts/verify_voice.sh — that covers
# browser-side DoD checks with human attestation. This script is the pod-side
# "is everything up and talking?" one-liner for mid-demo recovery.

set -u

HEAL=0
for arg in "$@"; do
  case "$arg" in
    --heal|-H) HEAL=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
  esac
done

PASS=0
FAIL=0
FAILURES=()

# Log dir may not exist on a freshly-booted pod.
mkdir -p /tmp/prism42-logs 2>/dev/null || true

# Color helpers (no emojis — plain text + ANSI only).
C_OK=$'\033[32m'
C_BAD=$'\033[31m'
C_WARN=$'\033[33m'
C_OFF=$'\033[0m'

check() {
  local name="$1"
  local cmd="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    printf '  %sPASS%s  %s\n' "$C_OK" "$C_OFF" "$name"
    PASS=$((PASS+1))
    return 0
  else
    printf '  %sFAIL%s  %s\n' "$C_BAD" "$C_OFF" "$name"
    FAIL=$((FAIL+1))
    FAILURES+=("$name")
    return 1
  fi
}

heal() {
  local name="$1"
  local cmd="$2"
  if [ "$HEAL" -eq 1 ]; then
    printf '  %shealing%s %s ...\n' "$C_WARN" "$C_OFF" "$name"
    eval "$cmd" 2>&1 | sed 's/^/      /' | tail -3
    sleep 3
  fi
}

echo "=================================================================="
echo "prism42 B300 runbook  (heal mode: $([ "$HEAL" -eq 1 ] && echo ON || echo OFF))"
echo "host: $(hostname)  date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=================================================================="

echo
echo "==> Parakeet STT (:9100)"
if ! check "parakeet.healthz" \
  "curl -sS --max-time 3 http://127.0.0.1:9100/healthz | grep -q '\"status\":\"ok\"'"; then
  heal "parakeet" '
    if systemctl list-unit-files 2>/dev/null | grep -q prism42-parakeet; then
      systemctl restart prism42-parakeet
    elif [ -d /opt/prism42/infra/b300/services/parakeet ]; then
      pkill -9 -f "services/parakeet/server.py" 2>/dev/null || true
      cd /opt/prism42/infra/b300/services/parakeet && \
        BIND=127.0.0.1 PORT=9100 nohup .venv/bin/python server.py \
        > /tmp/prism42-logs/parakeet.log 2>&1 &
    else
      echo "      (no parakeet unit file and no service dir — manual install needed)"
    fi
  '
fi

echo
echo "==> Fish TTS (:9200)"
# Prefer /healthz (matches in-repo server.py); fall back to /v1/health for
# alternate fish-speech builds that expose the OpenAI-compatible path.
if ! check "fish.healthz" \
  "curl -sS --max-time 3 http://127.0.0.1:9200/healthz | grep -q '\"status\":\"ok\"' || curl -sS --max-time 3 http://127.0.0.1:9200/v1/health | grep -q ok"; then
  heal "fish" '
    if systemctl list-unit-files 2>/dev/null | grep -q prism42-fish; then
      systemctl restart prism42-fish
    elif [ -d /opt/prism42/infra/b300/services/fish-speech ]; then
      pkill -9 -f "services/fish-speech/server.py" 2>/dev/null || true
      cd /opt/prism42/infra/b300/services/fish-speech && \
        BIND=127.0.0.1 PORT=9200 nohup .venv/bin/python server.py \
        > /tmp/prism42-logs/fish.log 2>&1 &
    else
      echo "      (no fish unit file and no service dir — manual install needed)"
    fi
  '
fi

echo
echo "==> Redis (:6379)"
# Two paths: native redis-cli or docker exec into the compose container.
if ! check "redis.ping" \
  "(command -v redis-cli >/dev/null 2>&1 && redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q PONG) || (docker exec prism42-redis redis-cli PING 2>/dev/null | grep -q PONG)"; then
  heal "redis" '
    if docker ps -a --format "{{.Names}}" 2>/dev/null | grep -q "^prism42-redis$"; then
      docker start prism42-redis
    elif [ -f /opt/prism42/infra/b300/docker-compose.yml ]; then
      docker compose --project-directory /opt/prism42/infra/b300 up -d redis 2>/dev/null || true
    else
      echo "      (no redis container and no compose file — manual install needed)"
    fi
  '
fi

echo
echo "==> LiveKit worker (prism42-worker)"
check "worker.active" "systemctl is-active --quiet prism42-worker"
if [ -f /tmp/prism42-logs/worker.log ]; then
  check "worker.registered" "tail -500 /tmp/prism42-logs/worker.log | grep -q 'registered worker'"
else
  check "worker.registered" "false"  # no log file -> fail
fi

# Heal: restart worker if either check above failed.
if ! systemctl is-active --quiet prism42-worker 2>/dev/null \
  || ! tail -500 /tmp/prism42-logs/worker.log 2>/dev/null | grep -q 'registered worker'; then
  heal "prism42-worker" 'systemctl restart prism42-worker && sleep 4 && systemctl is-active --quiet prism42-worker && echo restarted'
fi

echo
echo "==> LiveKit worker-starter (optional escape-hatch)"
# Only validate if the unit is enabled; if not, report INFO not FAIL.
if systemctl list-unit-files 2>/dev/null | grep -q '^prism42-worker-starter.service'; then
  if systemctl is-enabled --quiet prism42-worker-starter 2>/dev/null; then
    check "worker-starter.active" "systemctl is-active --quiet prism42-worker-starter"
  else
    printf '  %sINFO%s  worker-starter unit present but disabled (OK — escape-hatch only)\n' "$C_WARN" "$C_OFF"
  fi
else
  printf '  %sINFO%s  worker-starter unit not installed (OK — not required)\n' "$C_WARN" "$C_OFF"
fi

echo
echo "==> Synthetic caller round-trip (timeout 45s)"
# Run synthetic_caller.py with a hard wall-clock cap. It joins the
# LiveKit room, waits for the agent to publish audio, and prints
# VERDICT: PASS / FAIL ... on the last line.
SYNTH_DIR=/opt/prism42/agents/livekit
SYNTH_VENV="${SYNTH_DIR}/.venv/bin/python"
SYNTH_SCRIPT="${SYNTH_DIR}/synthetic_caller.py"

if [ ! -x "$SYNTH_VENV" ]; then
  printf '  %sFAIL%s  synth.venv missing at %s\n' "$C_BAD" "$C_OFF" "$SYNTH_VENV"
  FAIL=$((FAIL+1))
  FAILURES+=("synth.venv missing")
elif [ ! -f "$SYNTH_SCRIPT" ]; then
  printf '  %sFAIL%s  synth.script missing at %s\n' "$C_BAD" "$C_OFF" "$SYNTH_SCRIPT"
  FAIL=$((FAIL+1))
  FAILURES+=("synth.script missing")
else
  SYNTH_OUT=/tmp/prism42-logs/synth-$(date +%s).log
  # timeout(1) is on the B300 base image (coreutils). If it's not, fall
  # back to a subshell with kill.
  if command -v timeout >/dev/null 2>&1; then
    timeout --kill-after=5s 45s "$SYNTH_VENV" "$SYNTH_SCRIPT" > "$SYNTH_OUT" 2>&1
  else
    ( "$SYNTH_VENV" "$SYNTH_SCRIPT" > "$SYNTH_OUT" 2>&1 ) &
    SYNTH_PID=$!
    ( sleep 45 && kill -TERM "$SYNTH_PID" 2>/dev/null ) &
    wait "$SYNTH_PID" 2>/dev/null || true
  fi
  if tail -5 "$SYNTH_OUT" | grep -q 'VERDICT: PASS'; then
    REASON=$(grep 'VERDICT: PASS' "$SYNTH_OUT" | tail -1 | head -c 120)
    printf '  %sPASS%s  synth.pass  (%s)\n' "$C_OK" "$C_OFF" "$REASON"
    PASS=$((PASS+1))
  else
    REASON=$(tail -3 "$SYNTH_OUT" | tr '\n' ' ' | head -c 160)
    printf '  %sFAIL%s  synth.pass  (%s)\n' "$C_BAD" "$C_OFF" "${REASON:-no output}"
    FAIL=$((FAIL+1))
    FAILURES+=("synth.pass: see $SYNTH_OUT")
  fi
fi

echo
echo "=================================================================="
TOTAL=$((PASS+FAIL))
if [ "$FAIL" -eq 0 ]; then
  printf '  %sALL GREEN%s  %d/%d checks pass\n' "$C_OK" "$C_OFF" "$PASS" "$TOTAL"
  echo "=================================================================="
  exit 0
else
  printf '  %sFAIL%s  %d/%d checks pass, %d fail\n' "$C_BAD" "$C_OFF" "$PASS" "$TOTAL" "$FAIL"
  echo "  failures:"
  for f in "${FAILURES[@]}"; do
    echo "    - $f"
  done
  echo "=================================================================="
  if [ "$HEAL" -eq 0 ]; then
    echo "  next: re-run with --heal to attempt auto-recovery"
  fi
  exit 1
fi
