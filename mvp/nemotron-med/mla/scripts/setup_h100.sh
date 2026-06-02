#!/usr/bin/env bash
# setup_h100.sh — idempotent install of prism-mla dependencies on a RunPod H100 pod.
#
# Assumes: CUDA Toolkit already installed on the host (RunPod images usually
# ship it). Creates a venv, installs torch + flashinfer + pytest + numpy,
# leaves the repo ready for scripts/verify_h100.sh.
#
# Safe to re-run. Does not rebuild existing venv.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${PRISM_VENV:-$ROOT/.venv}"
PY_BIN="${PRISM_PY:-python3}"

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PY_BIN not found on PATH" >&2
  exit 1
fi

if [[ ! -d "$VENV" ]]; then
  echo "[setup] creating venv at $VENV"
  "$PY_BIN" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
"$PIP" install -q --upgrade pip wheel

# Pin torch to a CUDA 12.x wheel compatible with H100.
# On a fresh RunPod pod this will pick the matching wheel for the host
# driver; override PRISM_TORCH_INDEX if needed.
TORCH_INDEX="${PRISM_TORCH_INDEX:-https://download.pytorch.org/whl/cu124}"

echo "[setup] installing torch (cu124) and flashinfer"
"$PIP" install -q numpy pytest
"$PIP" install -q --index-url "$TORCH_INDEX" torch
# flashinfer-python: pick the wheel that matches torch + cuda.
# The project publishes prebuilt wheels; if none matches, the `jit`
# builds fall back at first use.
"$PIP" install -q flashinfer-python

# Confirm the big three import cleanly.
"$VENV/bin/python" - <<'PY'
import numpy, torch
try:
    import flashinfer, flashinfer.mla
    print(f"numpy={numpy.__version__} torch={torch.__version__} "
          f"cuda={torch.cuda.is_available()} "
          f"flashinfer={getattr(flashinfer,'__version__','unknown')} "
          f"has_wrapper={hasattr(flashinfer.mla, 'BatchMLAPagedAttentionWrapper')}")
except Exception as e:
    import sys
    print(f"flashinfer import failed: {type(e).__name__}: {e}", file=sys.stderr)
    raise
PY

echo "[setup] done. next: bash scripts/verify_h100.sh"
