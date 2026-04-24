#!/bin/bash
# Point prism42-console.vercel.app at the most recent Ready production
# deployment. Workaround: Vercel's GitHub auto-deploy builds each push
# but does NOT auto-alias to the custom domain (the domain is
# classified Preview, not Production; converting via API returned
# `cannot_set_production_branch_as_preview`). This script queries the
# API for the latest Ready deployment and aliases in one shot.
#
# Usage: bash scripts/vercel_alias_latest.sh
#
# Requires: Vercel CLI `vercel` on PATH, logged in with access to
# the `goatnote` team. Reads ~/Library/Application Support/com.vercel.cli/auth.json
# for the API token.

set -eu

TEAM_ID="team_9F90ShqNvPoaCCkhrjCCw91r"
PROJECT_ID="prj_UCqQGmKnXhmqeQgwIHWJ9zzfX4vP"
CUSTOM_DOMAIN="prism42-console.vercel.app"
AUTH_FILE="$HOME/Library/Application Support/com.vercel.cli/auth.json"

if [ ! -f "$AUTH_FILE" ]; then
  echo "FAIL: Vercel auth file not found at $AUTH_FILE. Run 'vercel login' first."
  exit 1
fi

VTOKEN=$(python3 -c "import json; print(json.load(open(r'$AUTH_FILE'))['token'])")

LATEST=$(curl -sS -H "Authorization: Bearer $VTOKEN" \
  "https://api.vercel.com/v6/deployments?projectId=$PROJECT_ID&teamId=$TEAM_ID&state=READY&target=production&limit=1" \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['deployments'][0]['url']) if d.get('deployments') else ''")

if [ -z "$LATEST" ]; then
  echo "FAIL: no READY production deployment found"
  exit 2
fi

echo "latest ready prod deployment: https://$LATEST"
vercel alias set "https://$LATEST" "$CUSTOM_DOMAIN" --scope "$TEAM_ID" 2>&1 | tail -2

echo
echo "verify:"
curl -sS -o /dev/null -w "  https://$CUSTOM_DOMAIN → HTTP %{http_code}\n" \
  "https://$CUSTOM_DOMAIN/?_ts=$(date +%s)"
