"""Full-turn synthetic caller — publishes audio AND captures agent response.

Generates a test utterance via Fish Speech (so it sounds like a real caller
to Parakeet STT), publishes it on the LiveKit room, then measures whether
the agent responds with audible speech within a reasonable window.

Run on the pod where livekit + httpx + ormsgpack + Fish are reachable:
    brev exec prism-mla-b300-h4h5 'cd /opt/prism42/agents/livekit && \
        .venv/bin/python synthetic_caller_full.py "I have chest pain and shortness of breath."'

Reports per turn:
  - agent_joined Y/N + latency
  - pre-roll audio detected Y/N + amplitude
  - utterance published Y/N + duration
  - agent reply audio detected Y/N + latency from publish-end + amplitude

Exit codes:
  0 — agent responded with audible speech to the caller utterance
  2 — agent never joined
  3 — agent joined but no audio track
  4 — agent published only silence (TTS broken)
  5 — agent never replied to the caller utterance (orchestrator hung)
"""
from __future__ import annotations

import argparse
import array
import asyncio
import json
import os
import sys
import time
import urllib.request
import wave

import httpx
import numpy as np
import ormsgpack
from livekit import rtc

VERCEL_BASE = os.environ.get("PRISM42_BASE_URL", "https://prism42-console.vercel.app")
FISH_URL = os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:9200")
TARGET_SR = 48000  # LiveKit publish rate
FISH_SR = 44100  # Fish Speech S2-Pro native rate


def _http_post(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def generate_caller_audio(text: str) -> tuple[bytes, int]:
    """Synthesize caller utterance via Fish Speech. Returns (pcm_bytes, sample_rate)."""
    body = {
        "text": text, "format": "wav", "streaming": True,
        "references": [], "chunk_length": 200,
    }
    print(f"[gen] synthesizing caller audio: {text!r}")
    with httpx.stream(
        "POST", f"{FISH_URL}/v1/tts",
        content=ormsgpack.packb(body),
        headers={"Content-Type": "application/msgpack"},
        timeout=30,
    ) as r:
        r.raise_for_status()
        chunks = list(r.iter_bytes())
    pcm = b"".join(chunks)
    duration_s = len(pcm) / 2 / FISH_SR
    print(f"[gen] got {len(pcm):,} bytes ({duration_s:.2f}s of audio at {FISH_SR}Hz)")
    return pcm, FISH_SR


def resample_pcm(pcm: bytes, src_sr: int, dst_sr: int) -> bytes:
    """Naive linear-interp resample from src_sr to dst_sr (16-bit mono)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if src_sr == dst_sr:
        return samples.astype(np.int16).tobytes()
    new_len = int(round(len(samples) * dst_sr / src_sr))
    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    resampled = np.interp(x_new, x_old, samples)
    return resampled.astype(np.int16).tobytes()


async def main(text: str) -> int:
    print(f"=== STAGE A: generate caller audio for {text!r} ===")
    pcm_44k, _ = generate_caller_audio(text)
    pcm_48k = resample_pcm(pcm_44k, FISH_SR, TARGET_SR)
    duration_s = len(pcm_48k) / 2 / TARGET_SR
    print(f"[gen] resampled to {TARGET_SR}Hz, duration {duration_s:.2f}s")

    print(f"\n=== STAGE B: mint session + token via {VERCEL_BASE} ===")
    sess = _http_post(f"{VERCEL_BASE}/prism42/api/session/start")
    sid = sess["session_id"]
    tok = _http_post(
        f"{VERCEL_BASE}/prism42/api/livekit-token",
        {"session_id": sid, "identity": "synthetic-caller"},
    )
    url, jwt = tok["livekit_url"], tok["token"]
    print(f"[mint] session_id={sid} url={url}")

    print(f"\n=== STAGE C: connect + listen ===")
    room = rtc.Room()

    agent_joined = asyncio.Event()
    agent_audio_track_subscribed = asyncio.Event()
    first_audio_at: list[float] = []
    speech_frames = [0]
    peak_amplitude = [0]
    audio_after_publish_end_amp_max = [0]
    publish_end_at = [0.0]
    agent_identity: list[str] = []

    @room.on("participant_connected")
    def _on_pc(p: rtc.RemoteParticipant) -> None:
        print(f"[evt] participant_connected: identity={p.identity!r}")
        if p.identity != "synthetic-caller":
            agent_identity.append(p.identity)
            agent_joined.set()

    @room.on("track_subscribed")
    def _on_ts(track, publication, participant) -> None:
        print(f"[evt] track_subscribed kind={track.kind} from={participant.identity}")
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        agent_audio_track_subscribed.set()

        async def _drain() -> None:
            stream = rtc.AudioStream(track)
            async for fe in stream:
                if not first_audio_at:
                    first_audio_at.append(time.time())
                samples = array.array("h", bytes(fe.frame.data))
                peak = max(abs(s) for s in samples) if samples else 0
                if peak > 1000:
                    speech_frames[0] += 1
                if peak > peak_amplitude[0]:
                    peak_amplitude[0] = peak
                # Track speech amplitude AFTER our caller utterance ended.
                if publish_end_at[0] > 0 and time.time() > publish_end_at[0] + 0.3:
                    if peak > audio_after_publish_end_amp_max[0]:
                        audio_after_publish_end_amp_max[0] = peak

        asyncio.create_task(_drain())

    @room.on("disconnected")
    def _on_dc(reason) -> None:
        print(f"[evt] disconnected reason={reason}")

    t0 = time.time()
    await room.connect(url, jwt)
    print(f"[stage C] connected @ +{time.time() - t0:.2f}s")

    try:
        await asyncio.wait_for(agent_joined.wait(), timeout=15)
    except asyncio.TimeoutError:
        print("FAIL: agent never joined")
        await room.disconnect()
        return 2
    print(f"[stage C] AGENT JOINED @ +{time.time() - t0:.2f}s ({agent_identity[0]})")

    try:
        await asyncio.wait_for(agent_audio_track_subscribed.wait(), timeout=15)
    except asyncio.TimeoutError:
        print("FAIL: no agent audio track")
        await room.disconnect()
        return 3
    print(f"[stage C] AUDIO TRACK SUBSCRIBED @ +{time.time() - t0:.2f}s")

    print(f"\n=== STAGE D: wait for pre-roll (4s) ===")
    await asyncio.sleep(4.0)
    preroll_speech = speech_frames[0]
    preroll_peak = peak_amplitude[0]
    print(f"[stage D] pre-roll audio: {preroll_speech} non-silent frames, peak {preroll_peak}")

    print(f"\n=== STAGE E: publish caller audio ({duration_s:.1f}s) ===")
    src = rtc.AudioSource(TARGET_SR, 1)
    track = rtc.LocalAudioTrack.create_audio_track("synthetic-mic", src)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, options)
    print(f"[stage E] track published @ +{time.time() - t0:.2f}s")

    # Push audio in 10ms chunks.
    chunk_samples = TARGET_SR // 100  # 10ms
    chunk_bytes = chunk_samples * 2
    publish_start = time.time()
    for i in range(0, len(pcm_48k), chunk_bytes):
        block = pcm_48k[i : i + chunk_bytes]
        if len(block) < chunk_bytes:
            block = block + b"\x00" * (chunk_bytes - len(block))
        frame = rtc.AudioFrame(
            data=block,
            sample_rate=TARGET_SR,
            num_channels=1,
            samples_per_channel=chunk_samples,
        )
        await src.capture_frame(frame)
        await asyncio.sleep(0.01)
    publish_end_at[0] = time.time()
    print(f"[stage E] publish ended @ +{time.time() - t0:.2f}s")

    print(f"\n=== STAGE F: wait up to 25s for agent reply ===")
    reply_window_start = publish_end_at[0]
    reply_deadline = reply_window_start + 25.0
    reply_first_speech_at = None
    while time.time() < reply_deadline:
        await asyncio.sleep(0.5)
        if audio_after_publish_end_amp_max[0] > 1000 and reply_first_speech_at is None:
            reply_first_speech_at = time.time()
            print(
                f"[stage F] AGENT REPLY DETECTED @ +{reply_first_speech_at - t0:.2f}s "
                f"({reply_first_speech_at - reply_window_start:.2f}s after caller end), "
                f"peak {audio_after_publish_end_amp_max[0]}"
            )
            break
        elapsed = time.time() - reply_window_start
        print(
            f"[stage F] +{elapsed:5.2f}s after pub-end | "
            f"reply_peak={audio_after_publish_end_amp_max[0]} "
            f"(0 = silence)"
        )

    # Listen 5s more to capture any audio that started.
    if reply_first_speech_at:
        print(f"[stage F] listening 5s more to confirm sustained speech ...")
        await asyncio.sleep(5.0)

    await room.disconnect()

    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)
    print(f"agent_joined          : YES")
    print(f"audio_track_subscribed: YES")
    print(f"preroll_speech_frames : {preroll_speech} (peak {preroll_peak})")
    print(f"reply_speech_amp_max  : {audio_after_publish_end_amp_max[0]}")
    print(
        f"reply_latency_after_pubend: "
        f"{('+%.2fs' % (reply_first_speech_at - reply_window_start)) if reply_first_speech_at else 'NEVER'}"
    )
    print(f"total_speech_frames   : {speech_frames[0]}")
    print(f"global_peak_amplitude : {peak_amplitude[0]}")
    if not first_audio_at:
        print("VERDICT: no audio at all")
        return 4
    if preroll_speech < 5:
        print("VERDICT: pre-roll never spoke (TTS broken)")
        return 4
    if reply_first_speech_at is None:
        print(
            "VERDICT: pre-roll worked but agent NEVER replied to caller utterance "
            "(orchestrator/STT/specialist round-trip is the next bottleneck)"
        )
        return 5
    print(f"VERDICT: PASS — full turn round-trip works")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="I have chest pain and shortness of breath.")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.text)))
