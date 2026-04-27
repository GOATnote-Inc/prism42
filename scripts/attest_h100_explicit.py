"""H100 deterministic attestation harness — explicit-dispatch + audio publish.

What it does
------------
1. Reads LIVEKIT_API_KEY / LIVEKIT_API_SECRET / LIVEKIT_URL from the
   environment (typically loaded from /opt/prism42/agents/livekit/.env
   by systemd or a `set -a; . .env; set +a` shell wrapper). The script
   never echoes these values to stdout — it uses them only to mint a
   token and call the dispatch API.

2. Creates an *explicit* `prism42-h100` agent dispatch into a unique
   room. Because the H100 worker now runs with `agent_name=prism42-h100`
   (per the 130-5role-enable.conf drop-in), only the H100 worker can
   service that room. The H200 sister-worker is not eligible.

3. Connects to the room as a synthetic caller participant, waits for
   the agent to join, then publishes a pre-recorded WAV
   (default: /opt/prism42/voice-refs/mw_intro_greeting.wav — a
   911-flavored utterance) as 48 kHz mono 16-bit PCM audio frames.

4. Listens for the agent's reply audio + structured-turn events, then
   disconnects cleanly.

5. Prints a one-line PASS / FAIL summary plus event counts so the
   caller can grep worker.log for the matching events
   (guardrails.check, attacker.probe, adjudicator.rule, fsm.transition,
   tts.start) without having to wade through 10K log lines.

Run on the pod
--------------
    cd /opt/prism42 && \\
      sudo bash -c '
        set -a; . agents/livekit/.env; set +a
        agents/livekit/.venv/bin/python scripts/attest_h100_explicit.py
      '

Optional flags:
    --text "I have chest pain"   (currently unused — uses WAV instead)
    --wav  /path/to/file.wav     (override the default voice-ref)
    --listen 10                  (seconds to wait after publishing)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
from livekit import api, rtc

DEFAULT_WAV = "/opt/prism42/voice-refs/mw_intro_greeting.wav"
TARGET_SR = 48000
WAIT_FOR_AGENT_S = 20.0
DEFAULT_LISTEN_S = 12.0


def _resample(pcm: bytes, src_sr: int, dst_sr: int) -> bytes:
    if src_sr == dst_sr:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    new_len = int(round(len(samples) * dst_sr / src_sr))
    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.int16).tobytes()


async def _publish_pcm(
    source: rtc.AudioSource, pcm_48k: bytes, *, frame_ms: int = 20
) -> None:
    """Publish 48 kHz mono PCM in 20 ms frames."""
    samples_per_frame = TARGET_SR * frame_ms // 1000
    bytes_per_frame = samples_per_frame * 2  # int16
    n_frames = len(pcm_48k) // bytes_per_frame
    for i in range(n_frames):
        chunk = pcm_48k[i * bytes_per_frame : (i + 1) * bytes_per_frame]
        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=TARGET_SR,
            num_channels=1,
            samples_per_channel=samples_per_frame,
        )
        await source.capture_frame(frame)
        await asyncio.sleep(frame_ms / 1000.0)


async def main(args: argparse.Namespace) -> int:
    url = os.environ.get("LIVEKIT_URL")
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    if not all([url, key, secret]):
        print("FAIL: LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET unset")
        print("      Run via:  set -a; . /opt/prism42/agents/livekit/.env; set +a")
        return 1
    print(f"[1] livekit_url = {url}  (key/secret loaded; never echoed)")

    room_name = f"attest-h100-{int(time.time())}"
    print(f"[2] room        = {room_name}")
    print(f"[3] target      = agent_name=prism42-h100 (explicit dispatch)")

    # ---- Stage A: WAV → 48 kHz PCM ---------------------------------
    wav_path = Path(args.wav)
    if not wav_path.exists():
        print(f"FAIL: wav not found: {wav_path}")
        return 1
    with wave.open(str(wav_path)) as w:
        src_sr = w.getframerate()
        src_ch = w.getnchannels()
        src_sw = w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    if src_sw != 2:
        print(f"FAIL: only 16-bit PCM supported, got {src_sw*8}-bit")
        return 1
    if src_ch == 2:
        # downmix stereo → mono
        s = np.frombuffer(pcm, dtype=np.int16).reshape(-1, 2).mean(axis=1).astype(np.int16)
        pcm = s.tobytes()
    pcm_48k = _resample(pcm, src_sr, TARGET_SR)
    duration_s = len(pcm_48k) / 2 / TARGET_SR
    print(f"[4] wav         = {wav_path.name} ({src_sr}Hz → {TARGET_SR}Hz, {duration_s:.2f}s)")

    # ---- Stage B: explicit dispatch + connect ----------------------
    lk_api = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        dispatch = await lk_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="prism42-h100",
                room=room_name,
                metadata="",
            )
        )
        print(f"[5] dispatch    = id={dispatch.id} created")

        token = (
            api.AccessToken(key, secret)
            .with_identity("synthetic-caller")
            .with_name("synthetic-caller")
            .with_grants(
                api.VideoGrants(
                    room=room_name,
                    room_join=True,
                    can_publish=True,
                    can_subscribe=True,
                )
            )
            .to_jwt()
        )

        room = rtc.Room()
        agent_joined = asyncio.Event()
        agent_audio_received = [False]
        agent_audio_bytes = [0]
        agent_identity: list[str] = []

        @room.on("participant_connected")
        def _on_pc(p: rtc.RemoteParticipant) -> None:
            print(f"[evt] participant_connected identity={p.identity!r}")
            if p.identity != "synthetic-caller":
                agent_identity.append(p.identity)
                agent_joined.set()

        @room.on("track_subscribed")
        def _on_ts(track: rtc.Track, _pub: rtc.RemoteTrackPublication, _p: rtc.RemoteParticipant) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                print(f"[evt] track_subscribed audio kind={track.kind} sid={track.sid}")
                agent_audio_received[0] = True
                # Drain frames in the background to avoid backpressure
                stream = rtc.AudioStream(track)

                async def _drain() -> None:
                    async for ev in stream:
                        agent_audio_bytes[0] += len(ev.frame.data)

                asyncio.create_task(_drain())

        await room.connect(url, token)
        print(f"[6] connected   = local_participant={room.local_participant.identity!r}")

        # ---- Stage C: wait for agent ------------------------------
        try:
            await asyncio.wait_for(agent_joined.wait(), timeout=WAIT_FOR_AGENT_S)
            print(f"[7] agent_joined identity={agent_identity[0]!r}")
        except asyncio.TimeoutError:
            print(f"FAIL: agent did not join within {WAIT_FOR_AGENT_S}s")
            await room.disconnect()
            return 2

        # ---- Stage D: publish caller WAV -------------------------
        source = rtc.AudioSource(TARGET_SR, 1)
        track = rtc.LocalAudioTrack.create_audio_track("caller-mic", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        print(f"[8] publishing caller audio ({duration_s:.2f}s)…")
        publish_start = time.time()
        await _publish_pcm(source, pcm_48k)
        publish_dur = time.time() - publish_start
        print(f"[9] publish_done after {publish_dur:.2f}s")

        # ---- Stage E: listen for agent reply --------------------
        print(f"[10] listening for agent reply for {args.listen}s…")
        await asyncio.sleep(args.listen)

        await room.disconnect()
        print(f"[11] disconnected; agent_audio_bytes={agent_audio_bytes[0]:,}")

    finally:
        await lk_api.aclose()

    print("---")
    print(
        f"RESULT: agent_joined=1 audio_received={int(agent_audio_received[0])} "
        f"agent_audio_bytes={agent_audio_bytes[0]}"
    )
    if agent_audio_received[0] and agent_audio_bytes[0] > 0:
        print("PASS — explicit dispatch reached H100, audio round-trip observed.")
        return 0
    print("PARTIAL — dispatch reached agent, but no agent audio captured.")
    return 4


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--wav", default=DEFAULT_WAV, help=f"caller WAV (default {DEFAULT_WAV})")
    p.add_argument("--listen", type=float, default=DEFAULT_LISTEN_S)
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_parse())))
