#!/usr/bin/env bash
# Idempotent regenerator for the psap-fast Fish reference voice.
# Generates a 230-wpm Samantha-voice WAV from the same reference text
# as the existing psap preset, then installs it on the B300 pod under
# /opt/prism42/infra/b300/services/fish-speech/references/psap-fast/.
#
# Usage: bash setup_psap_fast_reference.sh
# Requires: macOS (for `say` + `afconvert`), ssh alias b300-pod.

set -euo pipefail

REF_TEXT="Nine one one, what is the address of your emergency. Stay on the line with me, help is on the way. Tell me exactly what happened and I will dispatch help immediately. Is the patient breathing normally right now."

WORK_AIFF=$(mktemp -t psap-fast-src.XXXXXX).aiff
WORK_WAV=$(mktemp -t psap-fast.XXXXXX).wav

trap 'rm -f "$WORK_AIFF" "$WORK_WAV"' EXIT

say -v Samantha -r 230 -o "$WORK_AIFF" "$REF_TEXT"
afconvert -d LEI16@44100 -c 1 -f WAVE "$WORK_AIFF" "$WORK_WAV"

# Verify format
file "$WORK_WAV"

# Install on pod (idempotent — overwrites prior file).
scp "$WORK_WAV" b300-pod:/tmp/psap-fast-staging.wav
ssh b300-pod '
  sudo mkdir -p /opt/prism42/infra/b300/services/fish-speech/references/psap-fast
  sudo mv /tmp/psap-fast-staging.wav /opt/prism42/infra/b300/services/fish-speech/references/psap-fast/ref.wav
  sudo cp -n /opt/prism42/infra/b300/services/fish-speech/references/psap/ref.lab /opt/prism42/infra/b300/services/fish-speech/references/psap-fast/ref.lab
  ls -la /opt/prism42/infra/b300/services/fish-speech/references/psap-fast/
'

echo "psap-fast reference installed. Activate via:"
echo "  sudo tee /etc/systemd/system/prism42-worker.service.d/80-cycle2L-refid.conf <<<'[Service]"
echo "  Environment=FISH_SPEECH_REFERENCE_ID=psap-fast'"
echo "  sudo systemctl daemon-reload && sudo systemctl restart prism42-worker"
