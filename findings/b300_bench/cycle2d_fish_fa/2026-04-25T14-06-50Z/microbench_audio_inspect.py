#!/usr/bin/env python3
"""Inspect Fish raw response to understand format. Single short request."""
from __future__ import annotations
import json
import time
import urllib.request

FISH_URL = "http://127.0.0.1:9200"
PROMPT = "Nine one one, what's your emergency?"

import ormsgpack

body = ormsgpack.packb({
    "text": PROMPT,
    "format": "wav",
    "streaming": True,
    "references": [],
    "chunk_length": 200,
})

req = urllib.request.Request(
    FISH_URL + "/v1/tts",
    data=body,
    headers={"Content-Type": "application/msgpack"},
    method="POST",
)

t0 = time.perf_counter()
chunks = []
with urllib.request.urlopen(req, timeout=60) as resp:
    print(f"status={resp.status}")
    print(f"headers={dict(resp.headers)}")
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        chunks.append(chunk)

pcm = b"".join(chunks)
print(f"total_bytes={len(pcm)}")
print(f"first 32 bytes hex: {pcm[:32].hex()}")
print(f"first 4 bytes ascii: {pcm[:4]!r}")
# Check if WAV
if pcm[:4] == b"RIFF":
    print("RIFF header present")
elif pcm[:4] == b"OggS":
    print("Ogg/Opus container")
elif pcm[:2] == b"\x1a\x45":
    print("Matroska/Webm")
else:
    print(f"unknown format; first 4 bytes: {pcm[:4]!r}")

# Try unpack as int16 anyway and see peak.
import struct
n_samples_attempt = len(pcm) // 2
fmt = "<%dh" % n_samples_attempt
try:
    samples = struct.unpack(fmt, pcm[:n_samples_attempt*2])
    nonzero = sum(1 for s in samples if s != 0)
    print(f"as int16 LE: n_samples={n_samples_attempt} nonzero={nonzero} peak={max(abs(s) for s in samples)}")
except Exception as e:
    print(f"unpack failed: {e}")

# Save raw bytes for inspection.
with open("/tmp/cycle2d-fish-sample.bin", "wb") as f:
    f.write(pcm)
print("Saved to /tmp/cycle2d-fish-sample.bin")
