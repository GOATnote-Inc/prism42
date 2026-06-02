#!/usr/bin/env bash
# verify_h100.sh — single-command H100 verification for prism-mla.
#
# Run this on the RunPod H100 pod after setup_h100.sh. Emits a single
# parseable report block between BEGIN/END markers. Paste the whole
# block back as the verification artifact.
#
# Exit code: 0 all pass; N = number of failed checks.
#
# Environment:
#   CUDA_VISIBLE_DEVICES   - which GPU(s) to use (default: unset = all)
#   PRISM_BACKEND          - flashinfer backend: auto|fa2|fa3|cutlass (default auto)
#   PRISM_KV_LEN           - KV cache length for the smoke benchmark (default 1024)
#   PRISM_VENV             - path to the venv (default ./.venv)
set +e  # we want to report failures, not abort

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${PRISM_VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"
BACKEND="${PRISM_BACKEND:-auto}"
KV_LEN="${PRISM_KV_LEN:-1024}"

PASSED=0
FAILED=0
REPORT=""

record() {
  local name="$1"; local status="$2"; local detail="$3"
  if [[ "$status" == "PASS" ]]; then
    PASSED=$((PASSED + 1))
  else
    FAILED=$((FAILED + 1))
  fi
  REPORT="${REPORT}[${status}] ${name}"
  [[ -n "$detail" ]] && REPORT="${REPORT}  :: ${detail}"
  REPORT="${REPORT}
"
}

echo "=== PRISM-MLA H100 VERIFY BEGIN ==="
echo "pwd: $ROOT"
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "host: $(hostname 2>/dev/null || echo unknown)"
echo "CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-unset}"
echo "backend: $BACKEND"
echo "kv_len: $KV_LEN"
echo

# --- 1. nvidia-smi ---
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_LINE="$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)"
  if [[ -n "$GPU_LINE" ]]; then
    record "nvidia-smi" "PASS" "$GPU_LINE"
  else
    record "nvidia-smi" "FAIL" "command ran but no GPU line"
  fi
else
  record "nvidia-smi" "FAIL" "nvidia-smi not found"
fi

# --- 2. nvcc ---
NVCC_VER="$(nvcc --version 2>/dev/null | grep release | awk '{print $5,$6}' | tr -d ',')"
if [[ -n "$NVCC_VER" ]]; then
  record "nvcc" "PASS" "$NVCC_VER"
else
  record "nvcc" "FAIL" "nvcc not found or not on PATH"
fi

# --- 3. venv + python ---
if [[ -x "$PY" ]]; then
  PY_VER="$("$PY" --version 2>&1)"
  record "venv python" "PASS" "$PY_VER at $VENV"
else
  record "venv python" "FAIL" "no venv at $VENV; run scripts/setup_h100.sh first"
  # without a python we can't continue; print summary and exit.
  echo "$REPORT"
  echo "=== PRISM-MLA H100 VERIFY END (${PASSED} pass, ${FAILED} fail) ==="
  exit "$FAILED"
fi

# --- 4. imports ---
IMP_OUT="$("$PY" - <<'PY'
import json
out = {}
try:
    import torch
    out["torch"] = torch.__version__
    out["cuda"] = torch.cuda.is_available()
    if torch.cuda.is_available():
        out["device"] = torch.cuda.get_device_name(torch.cuda.current_device())
        out["cc"] = torch.cuda.get_device_capability(torch.cuda.current_device())
except Exception as e:
    out["torch_err"] = f"{type(e).__name__}: {e}"
try:
    import flashinfer, flashinfer.mla
    out["flashinfer"] = getattr(flashinfer, "__version__", "unknown")
    out["wrapper_class"] = hasattr(flashinfer.mla, "BatchMLAPagedAttentionWrapper")
except Exception as e:
    out["flashinfer_err"] = f"{type(e).__name__}: {e}"
print(json.dumps(out))
PY
)"
if [[ "$IMP_OUT" == *'"torch_err"'* ]]; then
  record "import torch" "FAIL" "$(echo "$IMP_OUT" | grep -o '"torch_err":[^}]*')"
else
  record "import torch" "PASS" "$(echo "$IMP_OUT" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print(f"{d[\"torch\"]} cuda={d[\"cuda\"]} device={d.get(\"device\",\"?\")} cc={d.get(\"cc\",\"?\")}")')"
fi
if [[ "$IMP_OUT" == *'"flashinfer_err"'* ]]; then
  record "import flashinfer.mla" "FAIL" "$(echo "$IMP_OUT" | grep -o '"flashinfer_err":[^}]*')"
else
  record "import flashinfer.mla" "PASS" "$(echo "$IMP_OUT" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print(f"v{d[\"flashinfer\"]} wrapper_class={d[\"wrapper_class\"]}")')"
fi

# --- 5. existing CPU test suite (regression guard) ---
CPU_OUT="$("$PY" -m pytest tests/ -q --ignore=tests/test_flashinfer_cuda.py 2>&1 | tail -3)"
CPU_LINE="$(echo "$CPU_OUT" | grep -E '^[0-9]+ (passed|failed)' | tail -1)"
if [[ "$CPU_LINE" == *passed* && "$CPU_LINE" != *failed* ]]; then
  record "cpu test suite" "PASS" "$CPU_LINE"
else
  record "cpu test suite" "FAIL" "$CPU_LINE"
fi

# --- 6. CUDA smoke: correctness + benchmark ---
SMOKE_OUT="$(PRISM_BACKEND="$BACKEND" PRISM_KV_LEN="$KV_LEN" "$PY" scripts/h100_smoke.py 2>&1)"
SMOKE_STATUS="$?"
# Last line of h100_smoke.py is a single-line JSON summary.
SMOKE_JSON="$(echo "$SMOKE_OUT" | tail -1)"
if [[ "$SMOKE_STATUS" == "0" ]]; then
  PASS_FLAG="$(echo "$SMOKE_JSON" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print("PASS" if d.get("verify",{}).get("passed") else "FAIL")' 2>/dev/null)"
  if [[ "$PASS_FLAG" == "PASS" ]]; then
    DETAIL="$(echo "$SMOKE_JSON" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); v=d["verify"]; b=d["bench"]; print(f"max_err={v[\"max_abs_error\"]:.3e} median={b[\"median_ns\"]/1000:.1f}us p90={b[\"p90_ns\"]/1000:.1f}us tok/s={b[\"tokens_per_sec\"]:.0f}")')"
    record "cuda smoke" "PASS" "$DETAIL"
  else
    DETAIL="$(echo "$SMOKE_JSON" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print(f"verify failed max_err={d.get(\"verify\",{}).get(\"max_abs_error\",\"?\")}")')"
    record "cuda smoke" "FAIL" "$DETAIL"
  fi
else
  LAST_ERR="$(echo "$SMOKE_OUT" | tail -5 | head -4)"
  record "cuda smoke" "FAIL" "script exited $SMOKE_STATUS. last lines: ${LAST_ERR:0:200}"
fi

# --- 7. ncu available ---
NCU_OUT="$(ncu --list-sets 2>&1 | head -1)"
if echo "$NCU_OUT" | grep -q "Identifier"; then
  NCU_COUNT="$(ncu --list-sets 2>/dev/null | grep -c "^[A-Za-z]")"
  record "ncu --list-sets" "PASS" "$NCU_COUNT sets available"
elif echo "$NCU_OUT" | grep -qi "permission\|admin\|root"; then
  record "ncu --list-sets" "FAIL" "permission denied; needs sudo or NVreg_RestrictProfilingToAdminUsers=0"
else
  record "ncu --list-sets" "FAIL" "$(echo "$NCU_OUT" | head -1)"
fi

# --- 8. nsys available ---
NSYS_OUT="$(nsys --version 2>&1 | head -1)"
if echo "$NSYS_OUT" | grep -qi "nvidia"; then
  record "nsys --version" "PASS" "$NSYS_OUT"
else
  record "nsys --version" "FAIL" "$(echo "$NSYS_OUT" | head -1)"
fi

echo "--- checks ---"
echo -n "$REPORT"
echo "=== PRISM-MLA H100 VERIFY END (${PASSED} pass, ${FAILED} fail) ==="
exit "$FAILED"
