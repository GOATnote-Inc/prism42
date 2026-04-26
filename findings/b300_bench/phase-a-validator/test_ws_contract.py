"""Phase A WebSocket contract validator for Parakeet server.

Connects to ws://localhost:9100/ws (via SSH port-forward) and sends
50 frames of 20 ms PCM16 silence @ 16 kHz mono, then sends a flush.
Asserts at least one event of type partial, preflight, or final.

Usage (run locally; requires the SSH tunnel to be up):
  ssh -L 9100:127.0.0.1:9100 prism-mla-b300-h4h5 -N -f
  python findings/b300_bench/phase-a-validator/test_ws_contract.py

Or run directly on the pod:
  ssh prism-mla-b300-h4h5 "python3 /tmp/test_ws_contract.py"
  (copy the script there first with scp)
"""
from __future__ import annotations

import asyncio
import json
import struct
import time

import aiohttp

HOST = "127.0.0.1"
PORT = 9100
WS_PATH = "/ws"   # <-- server exposes /ws; this must match
FRAME_BYTES = 640  # 20 ms @ 16 kHz PCM16 mono
N_FRAMES = 50      # 50 * 20 ms = 1 s of audio


def _silence_frame() -> bytes:
    """Generate one frame of PCM16 silence (640 bytes = 320 int16 zeros)."""
    return struct.pack("<" + "H" * (FRAME_BYTES // 2), *([0] * (FRAME_BYTES // 2)))


async def run_test() -> None:
    url = f"ws://{HOST}:{PORT}{WS_PATH}"
    print(f"[validator] connecting to {url}")

    timeout = aiohttp.ClientTimeout(total=30, sock_connect=5, sock_read=None)
    received: list[dict] = []
    t_connect = time.monotonic()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(
            url,
            protocols=("prism42-parakeet-v1",),
            max_msg_size=0,
        ) as ws:
            t_connected = time.monotonic()
            print(f"[validator] connected in {int((t_connected - t_connect)*1000)} ms")

            # Send 50 frames of silence.
            frame = _silence_frame()
            for i in range(N_FRAMES):
                await ws.send_bytes(frame)

            # Send flush to request final transcript.
            await ws.send_str(json.dumps({"type": "flush"}))
            t_flush = time.monotonic()
            print(f"[validator] sent {N_FRAMES} frames + flush at {int((t_flush-t_connected)*1000)} ms")

            # Collect responses until we see a 'final' or 5 s timeout.
            try:
                async with asyncio.timeout(5.0):
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            elapsed = int((time.monotonic() - t_flush) * 1000)
                            print(f"[validator] +{elapsed}ms  {json.dumps(payload)}")
                            received.append(payload)
                            if payload.get("type") == "final":
                                break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            print(f"[validator] ws closed/error: {msg.type}")
                            break
            except TimeoutError:
                print("[validator] 5 s timeout waiting for events")

            await ws.send_str(json.dumps({"type": "close"}))

    # Assert.
    types = {e.get("type") for e in received}
    valid = {"partial", "preflight", "final"}
    hits = types & valid
    if hits:
        print(f"\n[validator] PASS — received event types: {hits}")
        print("[validator] JSON shapes:")
        for e in received:
            print(f"  {json.dumps(e)}")
    else:
        print(f"\n[validator] FAIL — no partial/preflight/final received. Got: {received}")
        raise SystemExit(1)

    # Timing summary.
    finals = [e for e in received if e.get("type") == "final"]
    if finals:
        rtf_ms = finals[-1].get("ms", 0)
        print(f"[validator] server-reported latency from utterance start: {rtf_ms} ms")


if __name__ == "__main__":
    asyncio.run(run_test())
