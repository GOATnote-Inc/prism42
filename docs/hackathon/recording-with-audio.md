---
title: Record screen + system audio + mic on macOS 26 with OBS
date: 2026-04-26
purpose: get a Prism42 demo recording with sound for the hackathon submission, in under 5 minutes
---

# Record with sound — OBS Studio quick path

OBS Studio 32.1.2 is installed at `/Applications/OBS.app`. On macOS 26 it captures system audio natively via ScreenCaptureKit. No BlackHole, no Aggregate Device, no kernel-extension approval.

## One-time setup (~3 min)

1. Open OBS:

   ```bash
   open -a OBS
   ```

   Skip the auto-config wizard or click "Optimize for recording, I will not be streaming". Set base/output resolution to your display's native (1920×1080 or 2560×1440). FPS 30.

2. Grant macOS permissions when prompted, OR open them now:

   - **System Settings → Privacy & Security → Screen & System Audio Recording → enable OBS**
   - **System Settings → Privacy & Security → Microphone → enable OBS**

   You may need to relaunch OBS after toggling each.

3. Add the right sources in OBS's `Sources` panel (bottom of main window, `+` button):

   - **`+` → macOS Screen Capture** → pick your display → check **"Capture audio"** → OK.
     This is the magic: ScreenCaptureKit pulls system audio from the same source as the screen, no extra routing.
   - **`+` → Audio Input Capture** → pick your microphone (e.g., MacBook Pro Microphone or your AirPods) → OK.

4. Confirm both audio streams are alive in the `Audio Mixer` panel:

   - Speak — your **Audio Input Capture** bar should bounce.
   - Play any system sound (YouTube, Apple Music, your prism42 demo voice) — the **macOS Screen Capture** bar should bounce.
   - If either is silent, re-check step 2 permissions.

## Record the demo (~30 s setup, then go)

5. Click `Start Recording` (bottom-right). Run your prism42 demo.
6. Click `Stop Recording`. Output lands by default at `~/Movies/<timestamp>.mkv`.
7. Convert to .mp4 for upload (browsers prefer .mp4):

   ```bash
   cd ~/Movies
   latest=$(ls -t *.mkv | head -1)
   ffmpeg -i "$latest" -c copy "${latest%.mkv}.mp4"
   ```

   `ffmpeg` is already on your machine.

## Hackathon-specific demo recipe

For Prism42's 90-second hackathon demo:

- **Display source**: full display, NOT a window — so the browser, terminal, and any tool you reference all stay visible.
- **System audio**: this captures the prism42 voice agent speaking. Critical — it's the Opus 4.7 reasoning rendered as voice.
- **Mic**: your narration over the agent's responses.
- **Hotkey**: in OBS `Settings → Hotkeys`, bind a `Start Recording / Stop Recording` pair to something memorable (e.g., F8 / F9). Lets you start without the OBS window stealing focus.
- **Audio level target**: aim for green bars at -20 to -10 dB during voice. If you're peaking into red, lower the source's gain in the Audio Mixer.
- **Mute irrelevant sources**: if Slack/Music/etc. starts pinging mid-recording, you'll hear it. Quit them or click the speaker icon in the Audio Mixer to mute.

## Failure modes (likely on first try)

- **System audio bar is silent**. Re-check Privacy & Security → Screen & System Audio Recording → OBS toggled on. Quit and reopen OBS. macOS 26 sometimes wants the app fully relaunched.
- **Mic bar is silent**. Microphone permission. Same fix.
- **Output file is huge** (multi-GB for a 2-min recording). Lower the bitrate in `Settings → Output → Recording → Recording Quality` to "Indistinguishable Quality" instead of "Lossless". For a 90-second hackathon demo at 1080p30, ~80–150 MB is normal.
- **Tearing or stutter at start**. Don't record at the same time as another GPU-heavy task. Quit any other recorder.

## Backup plan if OBS misbehaves

OBS is the recommended path. If it fails for any reason, install the kernel-extension fallback:

```bash
brew install --cask blackhole-2ch
```

Then create an Aggregate Device in `Audio MIDI Setup` combining BlackHole + your mic, point QuickTime's screen recording at it. Adds ~5 minutes of setup. Use only if OBS won't cooperate within 10 minutes.

## What this gives you for the hackathon

- The Prism42 voice agent's speech is now in the recording. The judges hear what Opus 4.7 actually sounds like.
- Your narration over the demo lands in the same file, in sync, no post-merge needed.
- Output is a single `.mp4` you can drag straight into the hackathon submission form.

That's the entire path. Open OBS, grant the two permissions, drop the two sources, click record.
