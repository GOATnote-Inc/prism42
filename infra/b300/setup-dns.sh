#!/usr/bin/env bash
# Add the livekit.thegoatnote.com A record via the GoDaddy DNS API.
#
# Usage:
#   GODADDY_API_KEY=... GODADDY_API_SECRET=... POD_PUBLIC_IP=... ./setup-dns.sh
#
# OR if you've sourced the repo .env:
#   set -a && source ../../.env && set +a
#   POD_PUBLIC_IP=12.34.56.78 ./setup-dns.sh
#
# Idempotent — safe to re-run; PUT replaces any existing A record for
# the same name.
#
# GoDaddy API ref:
#   https://developer.godaddy.com/doc/endpoint/domains#/v1/recordReplace
#
# To get API credentials:
#   https://developer.godaddy.com/keys
#   (Production keys, not OTE — OTE doesn't manage live DNS.)

set -euo pipefail

DOMAIN="${DOMAIN:-thegoatnote.com}"
SUBDOMAIN="${SUBDOMAIN:-livekit}"
TTL="${TTL:-600}"
RECORD_TYPE="A"

: "${GODADDY_API_KEY:?GODADDY_API_KEY missing — see https://developer.godaddy.com/keys}"
: "${GODADDY_API_SECRET:?GODADDY_API_SECRET missing}"
: "${POD_PUBLIC_IP:?POD_PUBLIC_IP missing — try: POD_PUBLIC_IP=\$(curl -s ifconfig.me)}"

# Validate IP shape — cheap sanity check.
if ! [[ "${POD_PUBLIC_IP}" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
  echo "POD_PUBLIC_IP=${POD_PUBLIC_IP} doesn't look like an IPv4 address" >&2
  exit 1
fi

API_URL="https://api.godaddy.com/v1/domains/${DOMAIN}/records/${RECORD_TYPE}/${SUBDOMAIN}"

echo "==> setting ${SUBDOMAIN}.${DOMAIN}  ${RECORD_TYPE}  ${POD_PUBLIC_IP}  TTL ${TTL}"

response=$(curl -s -w "\n%{http_code}" -X PUT "${API_URL}" \
  -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}" \
  -H "Content-Type: application/json" \
  -d "[{\"data\":\"${POD_PUBLIC_IP}\",\"ttl\":${TTL}}]")

body=$(echo "${response}" | head -n -1)
code=$(echo "${response}" | tail -n 1)

if [[ "${code}" != "200" ]]; then
  echo "GoDaddy API returned HTTP ${code}:" >&2
  echo "${body}" >&2
  exit 1
fi

echo "==> DNS record set."
echo
echo "Verify (give it 60-120s for propagation):"
echo "  dig +short ${SUBDOMAIN}.${DOMAIN}"
echo "  # should print: ${POD_PUBLIC_IP}"
echo
echo "Once propagated, Caddy will auto-provision a Let's Encrypt cert"
echo "on first request to https://${SUBDOMAIN}.${DOMAIN}/health"
