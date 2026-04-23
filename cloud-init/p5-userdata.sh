#!/bin/bash
# Prism p5.48xlarge first-boot setup.
# Runs as root via cloud-init user-data on the AWS DLAMI
# (Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.7 Ubuntu 22.04).
#
# Goal: instance is ready for SSM-driven kernel builds within ~3 min
# of boot. SSM Agent is pre-installed and auto-enabled on DLAMI; we
# only add Prism-specific prep here.

set -euxo pipefail
exec > /var/log/prism-userdata.log 2>&1

echo "[$(date -Iseconds)] prism userdata start"

# ---------------------------------------------------------------------
# Workspace layout — matches /workspace/* shared-scratchpad convention
# referenced by coordinator/synthesizer/executor agents.
# ---------------------------------------------------------------------
mkdir -p /workspace /opt/prism
chown -R ubuntu:ubuntu /workspace /opt/prism
chmod 0775 /workspace

# ---------------------------------------------------------------------
# Build deps for Hopper-targeted and Blackwell-targeted attention kernels.
# PyTorch + CUDA toolkit are already installed in the DLAMI.
# ninja + packaging are required for source builds; einops for tests.
# ---------------------------------------------------------------------
sudo -u ubuntu bash <<'EOF'
set -eux
source /opt/pytorch/bin/activate 2>/dev/null || source /etc/profile.d/dlami-activate-pytorch.sh 2>/dev/null || true
pip install --quiet --upgrade pip
pip install --quiet ninja packaging einops pytest numpy
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'device_count', torch.cuda.device_count())"
EOF

# ---------------------------------------------------------------------
# Pre-clone the kernel repo under audit. Do NOT build here (source build is
# ~20 min and belongs in the SSM-driven Makefile recipe, not user-data).
# ---------------------------------------------------------------------
sudo -u ubuntu git clone --depth 50 \

# ---------------------------------------------------------------------
# Boot-ready marker. Makefile `ssm-ping` target polls for this file to
# know when the instance is usable (not just SSM-registered — SSM
# registers before userdata finishes).
# ---------------------------------------------------------------------
touch /opt/prism/boot-ready
chown ubuntu:ubuntu /opt/prism/boot-ready

echo "[$(date -Iseconds)] prism userdata done"
