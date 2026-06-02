#!/usr/bin/env bash
# Block any reference to prism42 prod surface in commits.
# See CLAUDE.md §1.
set -euo pipefail

[[ $# -eq 0 ]] && exit 0

PATTERN='(prism42-console\.vercel\.app|livekit\.thegoatnote\.com|wss://prism42|prism42-app\.thegoatnote\.com|ELEVENLABS_API_KEY|ELEVENLABS_SIGNING_SECRET|VERCEL_TOKEN|GODADDY_API_KEY|GODADDY_API_SECRET|prism-mla-b300-h4h5)'

hits=0
for f in "$@"; do
  [[ -f "$f" ]] || continue
  # Allow lines explicitly marked as freeze-verification reads.
  if grep -EnH "$PATTERN" "$f" 2>/dev/null \
     | grep -vE '#\s*allow:\s*freeze_verify\b|#\s*allow:\s*isolation_doc\b'; then
    hits=1
  fi
done

if [[ $hits -eq 1 ]]; then
  echo ""
  echo "ERROR: prod-surface reference detected in staged content."
  echo "       This repo is air-gapped from prism42 prod. See CLAUDE.md §1."
  exit 1
fi
exit 0
