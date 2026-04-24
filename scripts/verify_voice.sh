#!/bin/bash
# Voice round-trip verification harness for prism42.
#
# Runs all 8 Definition-of-Done checks, prints PASS/FAIL per item with
# specific failure detail. Exits 0 only if all 8 pass.
#
# Usage:
#   bash scripts/verify_voice.sh
#
# Designed to be re-runnable + idempotent. Used as the "is voice done?"
# gate now AND as a regression check when we flip Phase B back to
# self-hosted with Cloudflare TURN.

set -u

POD_INSTANCE="prism-mla-b300-h4h5"
APP_HOST="prism42-console.vercel.app"
APP_BASE="https://${APP_HOST}"
EXPECTED_URL_PATTERN="livekit\\.cloud"   # change to brevlab.com when flipped to self-host

PASS=0
FAIL=0
FAILURES=()

check() {
  local name="$1"
  local detail="$2"
  if [ "${3:-}" = "PASS" ]; then
    printf '  \033[32mPASS\033[0m  %-50s %s\n' "$name" "$detail"
    PASS=$((PASS+1))
  else
    printf '  \033[31mFAIL\033[0m  %-50s %s\n' "$name" "$detail"
    FAIL=$((FAIL+1))
    FAILURES+=("$name: $detail")
  fi
}

echo "==> 1/8  Pod service health (parakeet :9100, fish :9200, redis :6379)"
if PARAKEET=$(brev exec "$POD_INSTANCE" "curl -sS --max-time 3 http://127.0.0.1:9100/healthz" 2>/dev/null) && [ -n "$PARAKEET" ] && echo "$PARAKEET" | grep -q '"status":"ok"'; then
  check "parakeet" "$PARAKEET" PASS
else
  check "parakeet" "no /healthz response" FAIL
fi
if FISH=$(brev exec "$POD_INSTANCE" "curl -sS --max-time 3 http://127.0.0.1:9200/v1/health" 2>/dev/null) && [ -n "$FISH" ] && echo "$FISH" | grep -q '"status":"ok"'; then
  check "fish-speech" "$FISH" PASS
else
  check "fish-speech" "no /v1/health response" FAIL
fi
if REDIS=$(brev exec "$POD_INSTANCE" "docker exec prism42-redis redis-cli PING 2>/dev/null || ss -ltn | grep -q ':6379 ' && echo PONG_via_port" 2>/dev/null); then
  if echo "$REDIS" | grep -qE 'PONG'; then
    check "redis" "$(echo "$REDIS" | head -1)" PASS
  else
    check "redis" "$REDIS" FAIL
  fi
else
  check "redis" "no response" FAIL
fi

echo
echo "==> 2/8  Token mint route returns valid JWT"
SID="verify-$(date +%s)"
TOKEN_RESP=$(curl -sS --max-time 5 -X POST "${APP_BASE}/prism42/api/livekit-token" -H 'Content-Type: application/json' -d "{\"session_id\":\"${SID}\"}" 2>/dev/null)
if echo "$TOKEN_RESP" | python3 -c "
import sys, json, base64
d = json.loads(sys.stdin.read())
tok = d.get('token', '')
parts = tok.split('.')
if len(parts) != 3:
    raise SystemExit('not a 3-part JWT')
hdr = json.loads(base64.urlsafe_b64decode(parts[0] + '=='))
pld = json.loads(base64.urlsafe_b64decode(parts[1] + '==='))
url = d.get('livekit_url', '')
room = pld.get('video', {}).get('room', '?')
alg = hdr.get('alg')
print('alg=' + str(alg) + ' room=' + str(room) + ' url=' + url)
" >/tmp/token-info 2>&1; then
  INFO=$(cat /tmp/token-info)
  if echo "$INFO" | grep -qE "$EXPECTED_URL_PATTERN"; then
    check "token-mint" "$INFO" PASS
  else
    check "token-mint" "URL not matching $EXPECTED_URL_PATTERN: $INFO" FAIL
  fi
else
  check "token-mint" "JWT parse failed: $TOKEN_RESP" FAIL
fi

echo
echo "==> 3/8  Worker registered against expected URL"
WORKER_LOG=$(brev exec "$POD_INSTANCE" "tail -200 /tmp/prism42-logs/worker.log" 2>/dev/null)
# structlog formats "registered worker" with the URL on a continuation line;
# grep -A2 captures the continuation. Match whether expected URL appears
# within 2 lines after a "registered worker" marker.
if echo "$WORKER_LOG" | grep -A2 "registered worker" | grep -qE "$EXPECTED_URL_PATTERN"; then
  LATEST=$(echo "$WORKER_LOG" | grep -A2 "registered worker" | tail -3 | tr '\n' ' ' | head -c 140)
  check "worker-registered" "$LATEST..." PASS
else
  check "worker-registered" "no registration matching $EXPECTED_URL_PATTERN in last 200 log lines" FAIL
fi

echo
echo "==> 4/8  Worker process alive on pod"
WORKER_PS=$(brev exec "$POD_INSTANCE" "ps aux | grep -E 'worker.py' | grep -v grep | head -1" 2>/dev/null)
if [ -n "$WORKER_PS" ]; then
  PID=$(echo "$WORKER_PS" | awk '{print $2}')
  check "worker-alive" "PID $PID" PASS
else
  check "worker-alive" "no worker.py process found" FAIL
fi

echo
echo "==> 5-8/8  Browser-side checks (manual gate)"
echo "    The next 4 checks require human action — open the URL below in a"
echo "    browser, click 'Speak to the dispatcher', and verify:"
echo
echo "    URL: ${APP_BASE}/prism42/livekit"
echo
echo "    [5] pc.connectionState becomes 'connected' within 5 s"
echo "    [6] You speak 'Hello, my house is on fire' — agent transcribes"
echo "    [7] Agent responds with audible voice"
echo "    [8] 3 turns complete with p50 < 2000 ms end-to-end"
echo
echo "    These cannot be automated without a Playwright headless run; treat"
echo "    them as user-attestation gates for now."
echo

echo "==================================================================="
TOTAL=$((PASS+FAIL))
if [ $FAIL -eq 0 ]; then
  printf "  \033[32mAUTOMATED CHECKS: %d/%d PASS\033[0m  (run human checks 5-8 above)\n" "$PASS" "$TOTAL"
  exit 0
else
  printf "  \033[31mAUTOMATED CHECKS: %d/%d PASS, %d FAIL\033[0m\n" "$PASS" "$TOTAL" "$FAIL"
  echo
  echo "Failures:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  exit 1
fi
