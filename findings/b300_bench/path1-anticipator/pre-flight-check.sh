#!/usr/bin/env bash
# pre-flight-check.sh — Path 1 Anticipator pre-gate probe
# Run on the B300 pod AFTER Path 1 source build completes, BEFORE Phase D gate fires.
# No side effects: read-only probes only. Prints PASS/WARN/FAIL per check.
# Usage: bash pre-flight-check.sh [--vllm-port 8000]

set -euo pipefail

VLLM_PORT="${1:-8000}"
PASS=0; WARN=0; FAIL=0
PARSER_PATH="${NANO_V3_PARSER_PATH:-/workspace/nano_v3_reasoning_parser.py}"

say()  { echo "[$(date -u +%H:%M:%SZ)] $*"; }
ok()   { say "PASS  $*"; ((PASS++)) || true; }
warn() { say "WARN  $*"; ((WARN++)) || true; }
fail() { say "FAIL  $*"; ((FAIL++)) || true; }

say "=== Path 1 Anticipator Pre-Flight Check ==="
say "Target: B300/sm_103 + vLLM 0.20 + Nemotron-NVFP4"
say ""

# ─── CHECK 1: CUDA version (must be >= 12.8 for sm_103 conditional blocks) ──
say "--- CHECK 1: CUDA compiler version ---"
NVCC_VER=$(nvcc --version 2>/dev/null | grep -oP 'release \K[\d.]+' || echo "missing")
if [[ "$NVCC_VER" == "missing" ]]; then
    fail "nvcc not found — JIT compilation will fail (Failure Mode 3)"
elif python3 -c "import sys; v='$NVCC_VER'.split('.'); sys.exit(0 if (int(v[0])>12 or (int(v[0])==12 and int(v[1])>=8)) else 1)" 2>/dev/null; then
    ok "nvcc $NVCC_VER >= 12.8 — sm_103 conditional blocks will compile"
else
    fail "nvcc $NVCC_VER < 12.8 — sm_103 kernel gates will be skipped silently (Failure Mode 4)"
fi

# ─── CHECK 2: sm_103 binary presence in vLLM .so files ──────────────────────
say "--- CHECK 2: sm_103 binary presence in vLLM shared objects ---"
if ! command -v cuobjdump &>/dev/null; then
    warn "cuobjdump not available — cannot verify sm_103 binary presence (Failure Mode 4)"
else
    VLLM_SOS=$(python3 -c "import glob,vllm,os; base=os.path.dirname(vllm.__file__); print(' '.join(glob.glob(base+'/**/*.so', recursive=True)[:5]))" 2>/dev/null || echo "")
    SM103_FOUND=0
    for so in $VLLM_SOS; do
        if cuobjdump -lelf "$so" 2>/dev/null | grep -q "sm_103"; then
            SM103_FOUND=1
            break
        fi
    done
    if [[ $SM103_FOUND -eq 1 ]]; then
        ok "sm_103 ELF sections found in vLLM .so — native binary confirmed"
    else
        fail "sm_103 NOT found in vLLM .so — build may have silently dropped it (Failure Mode 4); rebuild with TORCH_CUDA_ARCH_LIST='10.0;10.3'"
    fi
fi

# ─── CHECK 3: FlashInfer version and cubin availability ─────────────────────
say "--- CHECK 3: FlashInfer version and sm_103 cubin ---"
FI_VER=$(python3 -c "import flashinfer; print(flashinfer.__version__)" 2>/dev/null || echo "missing")
if [[ "$FI_VER" == "missing" ]]; then
    fail "flashinfer not importable — Failure Mode 3 will trigger"
else
    # Semantic version check: require >= 0.6.6 (vLLM 0.19/0.20 pin)
    FI_OK=$(python3 -c "
from packaging.version import Version
import sys
try:
    v = Version('$FI_VER')
    sys.exit(0 if v >= Version('0.6.6') else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null && echo yes || echo no)
    if [[ "$FI_OK" == "yes" ]]; then
        ok "flashinfer $FI_VER >= 0.6.6 — version pin satisfied"
    else
        fail "flashinfer $FI_VER < 0.6.6 — ABI mismatch likely (Failure Mode 3); pin to 0.6.6"
    fi
fi

# ─── CHECK 4: JIT system dependencies ───────────────────────────────────────
say "--- CHECK 4: JIT compilation system dependencies ---"
MISSING_JIT=()
for dep in gcc ninja python3-dev; do
    if ! dpkg -l "$dep" &>/dev/null && ! command -v "${dep%%-*}" &>/dev/null; then
        MISSING_JIT+=("$dep")
    fi
done
if [[ ${#MISSING_JIT[@]} -eq 0 ]]; then
    ok "JIT deps present (gcc, ninja, python3-dev)"
else
    warn "JIT deps missing: ${MISSING_JIT[*]} — if sm_103 binary absent, JIT will also fail (Failure Mode 3)"
fi

# ─── CHECK 5: VLLM_USE_FLASHINFER_MOE_FP4 and related env vars ──────────────
say "--- CHECK 5: Required NVFP4 MoE env vars ---"
MISSING_ENV=()
[[ -z "${VLLM_USE_FLASHINFER_MOE_FP4:-}" ]] && MISSING_ENV+=("VLLM_USE_FLASHINFER_MOE_FP4")
[[ -z "${VLLM_FLASHINFER_MOE_BACKEND:-}" ]] && MISSING_ENV+=("VLLM_FLASHINFER_MOE_BACKEND")
if [[ ${#MISSING_ENV[@]} -eq 0 ]]; then
    ok "VLLM_USE_FLASHINFER_MOE_FP4=$VLLM_USE_FLASHINFER_MOE_FP4, VLLM_FLASHINFER_MOE_BACKEND=$VLLM_FLASHINFER_MOE_BACKEND"
else
    fail "Missing env vars: ${MISSING_ENV[*]} — Failure Mode 1 (FLASHINFER_CUTLASS mis-selection) very likely"
    echo "      Fix: export VLLM_USE_FLASHINFER_MOE_FP4=1 VLLM_FLASHINFER_MOE_BACKEND=throughput"
fi

# ─── CHECK 6: reasoning-parser plugin file presence ─────────────────────────
say "--- CHECK 6: nano_v3_reasoning_parser.py presence ---"
if [[ -f "$PARSER_PATH" ]]; then
    ok "nano_v3_reasoning_parser.py found at $PARSER_PATH"
else
    fail "nano_v3_reasoning_parser.py NOT found at $PARSER_PATH (Failure Mode 5)"
    echo "      Fix: wget -q https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py -O $PARSER_PATH"
fi

# ─── CHECK 7: vLLM version ──────────────────────────────────────────────────
say "--- CHECK 7: vLLM version ---"
VLLM_VER=$(python3 -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "missing")
if [[ "$VLLM_VER" == "missing" ]]; then
    fail "vllm not importable"
else
    VLLM_OK=$(python3 -c "
from packaging.version import Version
import sys
try:
    v = Version('$VLLM_VER')
    sys.exit(0 if v >= Version('0.20.0') else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null && echo yes || echo no)
    if [[ "$VLLM_OK" == "yes" ]]; then
        ok "vllm $VLLM_VER >= 0.20.0 — tool+reasoning parser coexistence fix (PR #30671) present"
    else
        warn "vllm $VLLM_VER < 0.20.0 — reasoning+tool-call coexistence may be broken (Failure Mode 5)"
    fi
fi

# ─── CHECK 8: GPU identity and sm_103 detection ─────────────────────────────
say "--- CHECK 8: GPU compute capability ---"
GPU_CC=$(python3 -c "
import torch
if torch.cuda.is_available():
    major, minor = torch.cuda.get_device_capability(0)
    print(f'{major}.{minor}')
else:
    print('no_cuda')
" 2>/dev/null || echo "no_cuda")
if [[ "$GPU_CC" == "10.3" ]]; then
    ok "GPU compute capability 10.3 — confirmed B300/sm_103"
elif [[ "$GPU_CC" == "10.0" ]]; then
    warn "GPU compute capability 10.0 (B200/sm_100) — not B300; sm_103 binaries will not execute, but sm_100 should work"
elif [[ "$GPU_CC" == "no_cuda" ]]; then
    fail "CUDA not available to PyTorch"
else
    warn "GPU compute capability $GPU_CC — unexpected; verify this is the correct pod"
fi

# ─── CHECK 9: vLLM server liveness (if already running) ─────────────────────
say "--- CHECK 9: vLLM server health (port $VLLM_PORT) ---"
if curl -sf "http://localhost:${VLLM_PORT}/health" -o /dev/null 2>/dev/null; then
    ok "vLLM server responding on port $VLLM_PORT"
    # Check backend selection from server logs (best-effort)
    MODELS=$(curl -sf "http://localhost:${VLLM_PORT}/v1/models" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print([m['id'] for m in d.get('data',[])])" 2>/dev/null || echo "parse_error")
    say "      Models available: $MODELS"
else
    warn "vLLM server not yet running on port $VLLM_PORT — run checks 1-8 first, then launch"
fi

# ─── CHECK 10: CUDA graph probe (batch=1 eager test) ────────────────────────
say "--- CHECK 10: CUDA graph Illegal Instruction probe ---"
if curl -sf "http://localhost:${VLLM_PORT}/health" -o /dev/null 2>/dev/null; then
    # Send batch=1 then batch=2 to probe for illegal instruction (Failure Mode 2)
    for batch_test in 1 2; do
        MSGS=$(python3 -c "
import json
msgs = [{'role':'user','content':'hello'}]
payload = {'model':'model','messages':msgs,'max_tokens':1}
print(json.dumps(payload))
")
        HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
            -H 'Content-Type: application/json' \
            -d "$MSGS" \
            "http://localhost:${VLLM_PORT}/v1/chat/completions" 2>/dev/null || echo "000")
        if [[ "$HTTP_CODE" == "200" ]]; then
            ok "Batch=$batch_test inference returned HTTP 200 — no illegal instruction"
        else
            fail "Batch=$batch_test inference returned HTTP $HTTP_CODE — possible Failure Mode 2 (CUDA graph illegal instruction); try --enforce-eager VLLM_USE_V1=0"
        fi
    done
else
    warn "Server not running — skipping CUDA graph probe (CHECK 10)"
fi

# ─── CHECK 11: Streaming tool_call shape probe ──────────────────────────────
say "--- CHECK 11: Streaming tool_call 'type:function' field probe ---"
if curl -sf "http://localhost:${VLLM_PORT}/health" -o /dev/null 2>/dev/null; then
    TOOL_PAYLOAD=$(python3 -c "
import json
payload = {
    'model': 'model',
    'messages': [{'role': 'user', 'content': 'What is 2+2?'}],
    'tools': [{'type':'function','function':{'name':'calculator','description':'calc','parameters':{'type':'object','properties':{}}}}],
    'tool_choice': {'type': 'function', 'function': {'name': 'calculator'}},
    'stream': True,
    'max_tokens': 50
}
print(json.dumps(payload))
")
    STREAM_OUT=$(curl -sf \
        -H 'Content-Type: application/json' \
        -d "$TOOL_PAYLOAD" \
        "http://localhost:${VLLM_PORT}/v1/chat/completions" 2>/dev/null | head -5 || echo "")
    if echo "$STREAM_OUT" | grep -q '"type":"function"'; then
        ok "Streaming tool_call first chunk contains 'type:function' — Failure Mode 5B not triggered"
    elif echo "$STREAM_OUT" | grep -q "tool_calls"; then
        fail "Streaming tool_call chunk missing 'type:function' field — Failure Mode 5B active; upgrade vLLM or use tool_choice:auto"
    else
        warn "Could not verify streaming tool_call shape (no tool_calls in first 5 lines); check manually"
    fi
else
    warn "Server not running — skipping streaming tool_call probe (CHECK 11)"
fi

# ─── SUMMARY ────────────────────────────────────────────────────────────────
say ""
say "=== SUMMARY: PASS=$PASS  WARN=$WARN  FAIL=$FAIL ==="
if [[ $FAIL -gt 0 ]]; then
    say "ACTION REQUIRED: $FAIL failure(s) detected. See FAIL lines above."
    say "Contingency details: findings/b300_bench/path1-anticipator/contingencies.md"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    say "WARNINGS: $WARN warning(s). Review before gate runs."
    exit 0
else
    say "All pre-flight checks passed. Gate may proceed."
    exit 0
fi
