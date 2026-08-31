"""Synthetic caller — joins a LiveKit room as a fake browser caller and
reports exactly which voice-pipeline stages succeed.

Run on the pod (where the livekit SDK is already installed):
    brev exec b300-pod 'cd /opt/prism42/agents/livekit && \
        .venv/bin/python synthetic_caller.py'

This eliminates the human caller from the test loop. Reports:
  - token mint OK / fail
  - room connect OK / fail
  - agent participant joined Y / N (with timeout)
  - agent published audio track Y / N
  - first audio frame received within Xs
  - total audio bytes received in 25s window

Exits non-zero if any stage fails.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import urllib.request
import json

from livekit import rtc

VERCEL_BASE = os.environ.get(
    "PRISM42_BASE_URL", "https://prism42-console.vercel.app"
)
WAIT_FOR_AGENT_S = 15.0
WAIT_FOR_AUDIO_S = 30.0
TOTAL_LISTEN_S = 35.0


def _http_post(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


async def main() -> int:
    print(f"[1] minting session via {VERCEL_BASE}/prism42/api/session/start")
    sess = _http_post(f"{VERCEL_BASE}/prism42/api/session/start")
    sid = sess["session_id"]
    print(f"    session_id = {sid}")

    print(f"[2] minting LiveKit token for room={sid}")
    tok = _http_post(
        f"{VERCEL_BASE}/prism42/api/livekit-token",
        {"session_id": sid, "identity": "synthetic-caller"},
    )
    url = tok["livekit_url"]
    jwt = tok["token"]
    print(f"    livekit_url = {url}")
    print(f"    token_len   = {len(jwt)}")

    room = rtc.Room()

    agent_joined = asyncio.Event()
    agent_audio_track_subscribed = asyncio.Event()
    first_audio_at: list[float] = []
    audio_bytes_total = [0]
    speech_frames = [0]
    peak_amplitude = [0]
    agent_identity: list[str] = []

    @room.on("participant_connected")
    def _on_pc(p: rtc.RemoteParticipant) -> None:
        print(f"[evt] participant_connected: identity={p.identity!r} sid={p.sid}")
        if p.identity != "synthetic-caller":
            agent_identity.append(p.identity)
            agent_joined.set()

    @room.on("track_subscribed")
    def _on_ts(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        print(
            f"[evt] track_subscribed: kind={track.kind} "
            f"from={participant.identity} sid={track.sid}"
        )
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            agent_audio_track_subscribed.set()

            async def _drain() -> None:
                import array
                stream = rtc.AudioStream(track)
                async for frame_event in stream:
                    if not first_audio_at:
                        first_audio_at.append(time.time())
                        print(
                            f"[evt] FIRST AUDIO FRAME from {participant.identity} "
                            f"@ +{first_audio_at[0] - t0:.2f}s "
                            f"(samples={frame_event.frame.samples_per_channel}, "
                            f"sr={frame_event.frame.sample_rate})"
                        )
                    audio_bytes_total[0] += len(frame_event.frame.data)
                    # Decode frame to 16-bit samples + measure peak amplitude.
                    # Frames with peak > 1000 are speech; <50 is silence.
                    samples = array.array("h", bytes(frame_event.frame.data))
                    peak = max(abs(s) for s in samples) if samples else 0
                    if peak > 1000:
                        speech_frames[0] += 1
                        if peak > peak_amplitude[0]:
                            peak_amplitude[0] = peak

            asyncio.create_task(_drain())

    @room.on("disconnected")
    def _on_dc(reason: object) -> None:
        print(f"[evt] disconnected: reason={reason}")

    print(f"[3] connecting to room as identity=synthetic-caller")
    t0 = time.time()
    await room.connect(url, jwt)
    print(f"    connected @ +{time.time() - t0:.2f}s, sid={room.sid}")

    print(f"[4] waiting up to {WAIT_FOR_AGENT_S}s for agent participant")
    try:
        await asyncio.wait_for(agent_joined.wait(), timeout=WAIT_FOR_AGENT_S)
        print(
            f"    AGENT JOINED @ +{time.time() - t0:.2f}s "
            f"identity={agent_identity[0]!r}"
        )
    except asyncio.TimeoutError:
        print(f"    FAIL: agent never joined in {WAIT_FOR_AGENT_S}s")
        await room.disconnect()
        return 2

    print(f"[5] waiting up to {WAIT_FOR_AUDIO_S}s for agent audio track")
    try:
        await asyncio.wait_for(
            agent_audio_track_subscribed.wait(), timeout=WAIT_FOR_AUDIO_S
        )
        print(f"    AGENT AUDIO TRACK SUBSCRIBED @ +{time.time() - t0:.2f}s")
    except asyncio.TimeoutError:
        print(f"    FAIL: no agent audio track after {WAIT_FOR_AUDIO_S}s")
        await room.disconnect()
        return 3

    print(f"[6] listening for {TOTAL_LISTEN_S}s total ...")
    deadline = t0 + TOTAL_LISTEN_S
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        elapsed = time.time() - t0
        print(
            f"    +{elapsed:5.2f}s: bytes={audio_bytes_total[0]:,} "
            f"speech_frames={speech_frames[0]} peak={peak_amplitude[0]} "
            f"first_frame={'+%.2fs' % (first_audio_at[0] - t0) if first_audio_at else 'NONE'}"
        )

    await room.disconnect()
    print()
    print("=" * 60)
    print("RESULT")
    print("=" * 60)
    print(f"agent_joined            : YES ({agent_identity[0]!r})")
    print(f"audio_track_subscribed  : YES")
    print(
        f"first_audio_frame       : "
        f"{'YES (+%.2fs)' % (first_audio_at[0] - t0) if first_audio_at else 'NO'}"
    )
    print(f"total_audio_bytes       : {audio_bytes_total[0]:,}")
    print(f"speech_frames           : {speech_frames[0]} (frames with peak > 1000)")
    print(f"peak_amplitude          : {peak_amplitude[0]} (16-bit signed; >5000 = clear speech)")
    if not first_audio_at:
        print("VERDICT: agent joined but produced no audio")
        return 4
    if speech_frames[0] < 10:
        print(
            "VERDICT: agent published audio but it's all silence — "
            "TTS pipeline (Fish Speech) is the next thing to fix"
        )
        return 5
    print(
        f"VERDICT: PASS — agent spoke ({speech_frames[0]} non-silent frames, "
        f"peak amplitude {peak_amplitude[0]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
