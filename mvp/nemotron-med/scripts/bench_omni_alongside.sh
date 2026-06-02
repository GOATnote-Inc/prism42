#!/usr/bin/env bash
# bench_omni_alongside.sh — A/B sweep Nemotron-3-Nano-Omni against the
# running Nemotron-3-Nano-30B-A3B-BF16 baseline, on the SAME 30-example
# HealthBench Hard subset, with the SAME paired-design CI math.
#
# Strategy: run Omni on the IDLE H100 pod (prism-mla-h100, 80 GiB) at
# NVFP4 (~21 GB). The running vllm-nemotron container on warm-lavender-
# narwhal H200 is NOT touched. No eviction, no destructive op on shared
# infra. Cost: ~$2.28/hr × ~2-3 hrs = ~$7.
#
# After both endpoints respond, run sovereign_bench twice (once per
# endpoint), then write a side-by-side CARD-Omni-vs-Nano.md.
#
# DOUBLE-GATED. Refuses to run unless BOTH:
#   --commit                              on the command line
#   PRISM42_OMNI_AB=1                     in the environment
#
# Either alone stays dry-run. Both = does start a container on H100
# (cost-incurring); the H100 was already running and idle so this is a
# minor incremental cost, not a brand-new pod spin-up.

set -uo pipefail

POD_OMNI="${POD_OMNI:-prism-mla-h100}"
QUANT="${QUANT:-NVFP4}"
OMNI_MODEL="nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-${QUANT}"
OMNI_CONTAINER="vllm-omni-ab"
VLLM_TAG="${VLLM_TAG:-v0.20.0}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATE_TAG="$(date +%Y%m%d-%H%M%S)"
AB_DIR="$REPO/results/r1.5-omni-ab-$DATE_TAG"

# H200 endpoint (existing, will not be modified)
NANO_SERVE_URL="${NANO_SERVE_URL:-http://127.0.0.1:8000/v1}"
NANO_MODEL="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"

# Local-side tunneled port for Omni on H100
OMNI_TUNNEL_PORT="${OMNI_TUNNEL_PORT:-8010}"
OMNI_SERVE_URL="http://127.0.0.1:${OMNI_TUNNEL_PORT}/v1"

COMMIT_FLAG=0
for arg in "$@"; do
  [[ "$arg" == "--commit" ]] && COMMIT_FLAG=1
done

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

cat <<EOF
=== Nemotron Omni vs Nano A/B sweep ===
  H200 (UNTOUCHED) : warm-lavender-narwhal [keeps serving Nano via $NANO_SERVE_URL]
  H100 (target)    : $POD_OMNI [will host Omni at port $OMNI_TUNNEL_PORT via ssh tunnel]
  Omni model       : $OMNI_MODEL
  Container name   : $OMNI_CONTAINER (kept on stop, removable later)
  vLLM image       : vllm/vllm-openai:$VLLM_TAG
  results dir      : $AB_DIR
  HF_TOKEN         : ${HF_TOKEN:+set} ${HF_TOKEN:-NOT SET}
EOF
echo

if [[ -z "${HF_TOKEN:-}" ]]; then
  red "FAIL: HF_TOKEN not set; Omni weights are gated. Source .env first."
  exit 2
fi

if [[ "$COMMIT_FLAG" -eq 0 || "${PRISM42_OMNI_AB:-0}" != "1" ]]; then
  yellow "DRY RUN — gates not met."
  yellow "Both required: --commit and PRISM42_OMNI_AB=1 in env."
  echo
  echo "Would (in order):"
  echo "  1. ssh $POD_OMNI 'docker pull vllm/vllm-openai:$VLLM_TAG'"
  echo "  2. ssh $POD_OMNI 'docker run -d --name $OMNI_CONTAINER --gpus all -p 127.0.0.1:8000:8000 ... $OMNI_MODEL'"
  echo "  3. open ssh -L $OMNI_TUNNEL_PORT:127.0.0.1:8000 $POD_OMNI tunnel"
  echo "  4. wait for Omni /v1/models"
  echo "  5. .venv/bin/python scripts/sovereign_bench.py --serve-url $OMNI_SERVE_URL --judge-url $OMNI_SERVE_URL ... --out $AB_DIR/omni.json"
  echo "  6. .venv/bin/python scripts/write_card.py $AB_DIR/omni.json"
  echo "  7. write side-by-side CARD-Omni-vs-Nano.md"
  echo "  8. tear down ssh tunnel; LEAVE Omni container running so user can decide swap"
  echo
  echo "Backout: ssh $POD_OMNI 'docker stop $OMNI_CONTAINER && docker rm $OMNI_CONTAINER'"
  exit 0
fi

# ==========================================================================
# COMMITTED PATH
# ==========================================================================
green "GATES MET — A/B sweep on $POD_OMNI; H200 untouched."
mkdir -p "$AB_DIR"

# Step 1+2: pull + launch
green "[1/8] pull vllm/vllm-openai:$VLLM_TAG on $POD_OMNI"
ssh -o BatchMode=yes "$POD_OMNI" "docker pull vllm/vllm-openai:$VLLM_TAG" 2>&1 | tail -3

green "[2/8] launch $OMNI_CONTAINER"
ssh -o BatchMode=yes "$POD_OMNI" bash -s <<EOF
set -uo pipefail
mkdir -p /opt/prism42-nemotron-med/hf_cache
docker rm -f $OMNI_CONTAINER 2>/dev/null || true
docker run -d --name $OMNI_CONTAINER \
  --gpus all --shm-size=16g \
  -e HF_TOKEN="$HF_TOKEN" \
  -p 127.0.0.1:8000:8000 \
  -v /opt/prism42-nemotron-med/hf_cache:/root/.cache/huggingface \
  vllm/vllm-openai:$VLLM_TAG \
  --model $OMNI_MODEL \
  --hf-overrides='{"architectures":["NemotronH_Nano_VL_V2"]}' \
  --trust-remote-code \
  --tensor-parallel-size 1 \
  --max-model-len 16384 \
  --max-num-seqs 32 \
  --max-num-batched-tokens 12288 \
  --gpu-memory-utilization 0.80 \
  --kv-cache-dtype fp8 \
  --enable-chunked-prefill \
  --enable-prefix-caching
EOF

# Step 3: tunnel
green "[3/8] open ssh tunnel localhost:$OMNI_TUNNEL_PORT -> $POD_OMNI:8000"
# Kill any prior tunnel on that port
pkill -f "ssh.*-L $OMNI_TUNNEL_PORT" 2>/dev/null || true
sleep 1
ssh -fN -L "$OMNI_TUNNEL_PORT":127.0.0.1:8000 "$POD_OMNI"

# Step 4: wait
green "[4/8] wait for Omni /v1/models (cold start ~12-18 min)"
for i in $(seq 1 30); do
  sleep 60
  if curl -sf "$OMNI_SERVE_URL/models" >/dev/null 2>&1; then
    green "Omni up after ${i} min"
    curl -s "$OMNI_SERVE_URL/models" | head -30
    break
  fi
  echo "  waiting... ${i} min"
  if [[ $i -eq 30 ]]; then
    red "FAIL: Omni did not become ready in 30 min"
    ssh "$POD_OMNI" "docker logs $OMNI_CONTAINER 2>&1 | tail -50"
    exit 1
  fi
done

# Step 5: bench
green "[5/8] sovereign_bench against Omni"
.venv/bin/python "$REPO/scripts/sovereign_bench.py" \
  --manifest "$REPO/corpus/clinical_subset.yaml" \
  --serve-url "$OMNI_SERVE_URL" \
  --serve-model "$OMNI_MODEL" \
  --judge-url "$OMNI_SERVE_URL" \
  --judge-model "$OMNI_MODEL" \
  --n 30 --trials 2 --max-tokens 768 --timeout-s 240 \
  --out "$AB_DIR/omni.json"

# Step 6: CARD
green "[6/8] write Omni CARD"
.venv/bin/python "$REPO/scripts/write_card.py" "$AB_DIR/omni.json" --out "$AB_DIR/CARD-omni.md"

# Step 7: side-by-side CARD
green "[7/8] compose CARD-Omni-vs-Nano.md"
NANO_CARD="$REPO/results/r1-pilot-20260428-015612/CARD.md"
OMNI_CARD="$AB_DIR/CARD-omni.md"
{
  echo "# CARD — Omni vs Nano A/B (HealthBench Hard, 30-example, N=2)"
  echo
  echo "| Model | Score (mean ± 95% HW) | Date |"
  echo "|---|---|---|"
  grep -E "^- \*\*Score\*\*" "$NANO_CARD" | head -1 | sed -E 's/^- \*\*Score\*\*: `([^`]+)`.*/| Nemotron-3-Nano-30B-A3B-BF16 | `\1` | (R1 pilot) |/'
  grep -E "^- \*\*Score\*\*" "$OMNI_CARD" | head -1 | sed -E 's/^- \*\*Score\*\*: `([^`]+)`.*/| Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 | `\1` | (this run) |/'
  echo
  echo "## Provenance"
  echo "- Nano CARD: \`$NANO_CARD\`"
  echo "- Omni CARD: \`$OMNI_CARD\`"
  echo "- Same 30-example clinical_subset.yaml (seed 42)"
  echo "- Same Triton-judge architecture (each model judges itself; same-family bias declared in both CARDs)"
  echo
  echo "Read the per-axis breakdown in each individual CARD before drawing conclusions."
} > "$AB_DIR/CARD-Omni-vs-Nano.md"

green "[8/8] done. Omni container LEFT RUNNING on $POD_OMNI for inspection."
echo
echo "  $AB_DIR/CARD-omni.md"
echo "  $AB_DIR/CARD-Omni-vs-Nano.md"
echo
echo "Cleanup when finished:"
echo "  pkill -f 'ssh.*-L $OMNI_TUNNEL_PORT'"
echo "  ssh $POD_OMNI 'docker stop $OMNI_CONTAINER && docker rm $OMNI_CONTAINER'"
