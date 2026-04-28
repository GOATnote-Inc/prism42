#!/usr/bin/env bash
# Block cloud LLM API key references — this repo is sovereign.
# See CLAUDE.md §2.
set -euo pipefail

[[ $# -eq 0 ]] && exit 0

PATTERN='(OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY)'

hits=0
for f in "$@"; do
  [[ -f "$f" ]] || continue
  # Allow comments that explicitly mark a line as legacy/judge-compat shim.
  if grep -EnH "$PATTERN" "$f" 2>/dev/null \
     | grep -vE '#\s*allow:\s*judge_compat\b'; then
    hits=1
  fi
done

if [[ $hits -eq 1 ]]; then
  echo ""
  echo "ERROR: cloud LLM key reference detected in staged content."
  echo "       Sovereign stack means local-only judge + serve. See CLAUDE.md §2."
  echo "       To intentionally allow a single line for back-compat, append:  # allow: judge_compat"
  exit 1
fi
exit 0
