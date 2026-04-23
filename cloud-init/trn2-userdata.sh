#!/bin/bash
# Prism trn2.48xlarge first-boot setup.
# Runs as root via cloud-init user-data on the AWS Neuron DLAMI
# (Deep Learning AMI Neuron Ubuntu 22.04).
#
# Neuron SDK (neuronx-cc, torch-neuronx, nki, neuron-runtime) is
# pre-installed. We only add Prism-specific workspace + clone
# aws-neuron/nki-samples.

set -euxo pipefail
exec > /var/log/prism-userdata.log 2>&1

echo "[$(date -Iseconds)] prism userdata start (trn2)"

mkdir -p /workspace /opt/prism
chown -R ubuntu:ubuntu /workspace /opt/prism
chmod 0775 /workspace

# ---------------------------------------------------------------------
# DLAMI ships Neuron SDK but version may lag; pin to latest for the
# sprint. Skip if already current.
# ---------------------------------------------------------------------
sudo -u ubuntu bash <<'EOF'
set -eux
# Activate neuron virtual env
source /opt/aws_neuronx_venv_pytorch_2_*/bin/activate 2>/dev/null || true
pip install --quiet --upgrade pip
# Neuron SDK packages — only upgrade if the repo is reachable
pip install --quiet --upgrade \
  --extra-index-url https://pip.repos.neuron.amazonaws.com \
  neuronx-cc torch-neuronx || echo "neuron pip upgrade skipped"
python -c "import neuronxcc; print('neuronxcc', neuronxcc.__version__)" || true
python -c "import neuronxcc.nki as nki; print('nki ok')" || true
EOF

# ---------------------------------------------------------------------
# Clone aws-neuron/nki-samples (MIT-0, CVE-eligible targets live under
# contributed/). This is the T5 audit surface for Trainium.
# ---------------------------------------------------------------------
sudo -u ubuntu git clone --depth 50 \
  https://github.com/aws-neuron/nki-samples.git /opt/prism/nki-samples

touch /opt/prism/boot-ready
chown ubuntu:ubuntu /opt/prism/boot-ready

echo "[$(date -Iseconds)] prism userdata done (trn2)"
