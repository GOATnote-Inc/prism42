#!/usr/bin/env bash
# Fresh-laptop bootstrap for Prism. Idempotent — safe to run multiple times.
# Succeeds silently; fails loudly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

say()  { printf "\033[1;35m==>\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m!!\033[0m %s\n" "$*" >&2; exit 1; }

say "Prism bootstrap starting in $REPO_ROOT"

# 1. ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  say "Installing ffmpeg..."
  if [[ "$(uname)" == "Darwin" ]]; then
    command -v brew >/dev/null 2>&1 || fail "Homebrew not found. Install from https://brew.sh and rerun."
    brew install ffmpeg
  elif [[ "$(uname)" == "Linux" ]]; then
    command -v apt >/dev/null 2>&1 && sudo apt install -y ffmpeg || fail "Please install ffmpeg for your distro."
  else
    fail "Unsupported OS: $(uname). Install ffmpeg manually and rerun."
  fi
else
  say "ffmpeg OK: $(ffmpeg -version | head -1 | awk '{print $1, $3}')"
fi

# 2. Python ≥ 3.11
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')
    if [[ "$ver" -ge 311 ]]; then
      PYTHON="$candidate"
      break
    fi
  fi
done
[[ -n "$PYTHON" ]] || fail "Python 3.11+ not found. Install from https://www.python.org or via pyenv."
say "Python OK: $PYTHON ($("$PYTHON" --version))"

# 3. venv
if [[ ! -d .venv ]]; then
  say "Creating venv..."
  "$PYTHON" -m venv .venv
else
  say "venv exists"
fi

# 4. Python deps
say "Installing Python deps (editable + dev + ui)..."
.venv/bin/pip install -q -U pip wheel setuptools
.venv/bin/pip install -q -e ".[dev,ui]"

# 5. Smoke (dry — no API key needed)
if [[ ! -f examples/song.mp3 ]] || [[ -z "$(ls -A examples/clips 2>/dev/null | grep -v '\.gitkeep\|README' || true)" ]]; then
  say "Generating synthetic test assets..."
  .venv/bin/python scripts/make_sample_assets.py >/dev/null
fi

say "Running dry-mode smoke (no API calls)..."
rm -rf out
.venv/bin/prism cut \
  --song examples/song.mp3 \
  --clips examples/clips \
  --out out \
  --aspect 16:9 \
  --dry > /tmp/prism-smoke.log 2>&1

if [[ -f out/song__16x9.mp4 ]]; then
  size=$(ls -lh out/song__16x9.mp4 | awk '{print $5}')
  say "✅ Dry render succeeded: out/song__16x9.mp4 ($size)"
else
  say "❌ Dry smoke failed. Tail of log:"
  tail -30 /tmp/prism-smoke.log >&2
  exit 1
fi

# 6. Tests
say "Running pytest..."
.venv/bin/pytest tests -q

cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bootstrap complete. Next:

  1. export ANTHROPIC_API_KEY=sk-ant-...
  2. source .venv/bin/activate
  3. prism cut --song examples/song.mp3 --clips examples/clips --out out

Read: HANDOFF.md, docs/NEXT_PROMPT.md
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
