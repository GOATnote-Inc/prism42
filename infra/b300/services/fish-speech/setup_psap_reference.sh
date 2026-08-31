#!/bin/bash
# Reproduce the PSAP-dispatcher reference-voice bindings that lever 7
# installed on the pod. Run on the Brev pod (or via SSH from a Mac
# laptop — the `say` / `ffmpeg` generation step is local-only).
#
# Without this, Fish Speech's voice drifts call-to-call (the
# seed/temperature knobs aren't enough per fishaudio#836 and KB 11 §3).
# With this, every synthesis clones the PSAP female-dispatcher voice
# encoded at 10×262 speaker tokens.
#
# Idempotent. Safe to re-run.

set -eu

REF_ROOT="/opt/prism42/infra/b300/services/fish-speech/references/psap"
WORKER_ENV="/opt/prism42/agents/livekit/.env"

# Step 1 — on the laptop, generate ref.wav from macOS `say` and scp to
# the pod. Skip this block if ref.wav already exists on the pod.
#
#   say -v Samantha -o /tmp/psap_ref.aiff \
#     "Nine one one, what is the address of your emergency. Stay on the line with me, help is on the way. Are you able to speak in full sentences right now. Help is coming."
#   ffmpeg -y -i /tmp/psap_ref.aiff -ar 44100 -ac 1 -sample_fmt s16 /tmp/psap_ref.wav
#   scp /tmp/psap_ref.wav b300-pod:/tmp/psap_ref.wav

# Step 2 — on the pod, install into Fish's references/ dir.
sudo mkdir -p "$REF_ROOT"
sudo chown shadeform:shadeform "$(dirname "$REF_ROOT")" "$REF_ROOT"

if [ -f /tmp/psap_ref.wav ] && [ ! -f "$REF_ROOT/ref.wav" ]; then
  cp /tmp/psap_ref.wav "$REF_ROOT/ref.wav"
fi

# Write the reference transcript adjacent to the audio.
cat > "$REF_ROOT/ref.lab" <<'TXT'
Nine one one, what is the address of your emergency. Stay on the line with me, help is on the way. Are you able to speak in full sentences right now. Help is coming.
TXT

ls -la "$REF_ROOT"

# Step 3 — wire the worker's .env so FishSpeechTTS picks up the
# reference on every synthesis (plugin line 29 reads
# FISH_SPEECH_REFERENCE_ID; 152-153 forwards it in the /v1/tts body).
if ! grep -q '^FISH_SPEECH_REFERENCE_ID=' "$WORKER_ENV"; then
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  sudo cp "$WORKER_ENV" "$WORKER_ENV.bak.$ts"
  echo "FISH_SPEECH_REFERENCE_ID=psap" | sudo tee -a "$WORKER_ENV" >/dev/null
  echo "added FISH_SPEECH_REFERENCE_ID=psap (backup at $WORKER_ENV.bak.$ts)"
else
  echo "FISH_SPEECH_REFERENCE_ID already set in $WORKER_ENV"
fi

# Step 4 — restart worker so the env reload takes effect.
sudo systemctl restart prism42-worker
sleep 3
systemctl is-active prism42-worker

# Step 5 — spot-check: Fish log should show "Loaded audio with 12.14
# seconds / Encoded prompt: torch.Size([10, 262])" on the next
# synthesis call.
echo
echo "=== verify on next synthesis ==="
echo "tail -30 /tmp/prism42-logs/fish.log | grep -E 'Loaded audio|Encoded prompt'"
