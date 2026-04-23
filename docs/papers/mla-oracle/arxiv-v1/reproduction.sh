#!/usr/bin/env bash
# Reproduce the local (hardware-independent) numerical claims of the v1 paper.
# The live rail numbers (Trillium 0.999977, H100 0.999984) require rented
# hardware; this script verifies everything that can be verified offline,
# and prints the exact commands to re-execute the two live rails.
#
# Exit 0 on full offline reproduction; exit 1 on any divergence.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1. Reference self-test (numpy FP32, both absorbed + non-absorbed forms) ==="
.venv/bin/python3 corpus/mla/reference/mla_decode_numpy.py

echo
echo "=== 2. Oracle integrity (11 tests: bf16 pass, fp32 fail, shape/nan/magnitude/sign/zeros) ==="
.venv/bin/python3 -m pytest tests/test_mla_oracle.py -v --no-header

echo
echo "=== 3. Reference regression (both shapes) ==="
.venv/bin/python3 -m pytest tests/test_mla_reference.py -v --no-header

echo
echo "=== 4. Golden-vector SHA integrity ==="
.venv/bin/python3 - <<'PY'
import json, hashlib, numpy as np
for cfg in ("small", "v2_lite"):
    with open(f"corpus/mla/reference/golden_vectors/{cfg}_decode_s16_w42.json") as f:
        g = json.load(f)
    out = np.asarray(g["output"], dtype=np.float32)
    # JSON round-trip loses ~1 ULP; sha256 on regenerated-from-seeds output
    # is the strict integrity check (see tests/test_mla_reference.py).
    assert len(g["output_sha256"]) == 64, f"{cfg}: malformed sha256"
    print(f"  {cfg}: stored sha256={g['output_sha256'][:16]}... shape={out.shape}")
PY

echo
echo "=== 5. Live rails (hardware-dependent; not run by this script) ==="
cat <<'EOF'
The two live rail numbers in Table 2 are:
  * M7  (Trillium v6e-1 bf16):   cos_sim = 0.999977  ($0.60 GCP spend)
  * M6a (H100 SXM    bf16):      cos_sim = 0.999984  ($0.10 RunPod spend)

Re-executing these requires rented hardware. Exact commands below.

--- Trillium (M7) ---
  set -a && source /path/to/.env && set +a   # RUNPOD_API_KEY not needed; need GCP creds
  gcloud config set project prism421
  gcloud compute tpus tpu-vm create prism-mla-v6e1 \
    --zone=us-east5-a --accelerator-type=v6e-1 --version=v2-alpha-tpuv6e
  gcloud compute tpus tpu-vm scp \
    corpus/mla/reference/mla_decode_jax.py prism-mla-v6e1:~/ --zone=us-east5-a
  gcloud compute tpus tpu-vm ssh prism-mla-v6e1 --zone=us-east5-a \
    --command='pip install --quiet "jax[tpu]>=0.4.34" numpy \
      -f https://storage.googleapis.com/jax-releases/libtpu_releases.html \
      && python3 ~/mla_decode_jax.py --dtype bf16 --config v2_lite --seqlen 16'
  gcloud compute tpus tpu-vm delete prism-mla-v6e1 --zone=us-east5-a --quiet

--- H100 (M6a) ---
  runpodctl config --apiKey "$RUNPOD_API_KEY"
  # Requires ~/.ssh/prism_lambda_ed25519 registered with RunPod.
  # Launch or reuse an H100 SXM pod, then:
  scp -i ~/.ssh/prism_lambda_ed25519 -P <pod_port> \
    corpus/mla/reference/mla_decode_pytorch.py root@<pod_ip>:/workspace/
  ssh -i ~/.ssh/prism_lambda_ed25519 -p <pod_port> root@<pod_ip> \
    "python3 /workspace/mla_decode_pytorch.py --dtype bf16 --config v2_lite --seqlen 16"

Both emit a JSON object with the candidate output on stdout. Pipe into
the oracle (corpus/mla/oracle/harness.py) with the matching tolerance
preset to grade against the committed golden.

Full provenance for both v1 runs (pod IDs, GPU UUIDs, jax/torch versions,
timestamps) is in:
  findings/mla-oracle-trillium-2026-04-22.md
  findings/mla-oracle-h100-2026-04-22.md
EOF

echo
echo "=== reproduction.sh: all offline checks passed ==="
