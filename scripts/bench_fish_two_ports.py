"""Apples-to-apples Fish-Speech bench across multiple ports.

Same text, same params, N samples each, prints comparison table.
Used during the PyTorch-nightly RTF experiment to compare
mainline (port 9200) vs nightly venv (port 9201).

Usage:
    python scripts/bench_fish_two_ports.py 9200 9201 --n 3

Run on the pod (where ports 9200/9201 are local). Requires httpx +
ormsgpack in the active env.
"""
from __future__ import annotations

import argparse
import json
import time

import httpx
import ormsgpack

UTTERANCE = (
    "Nine one one, what is the address of your emergency? "
    "Please stay on the line."
)


def bench_one_port(port: int, n: int) -> dict:
    samples = []
    for i in range(n):
        body = ormsgpack.packb(
            {
                "text": UTTERANCE,
                "format": "wav",
                "chunk_length": 200,
                "streaming": True,
                "max_new_tokens": 256,
                "top_p": 0.7,
                "repetition_penalty": 1.1,
                "temperature": 0.1,
                "seed": 911,
                "references": [],
            }
        )
        t0 = time.monotonic()
        first = None
        total = 0
        try:
            with httpx.stream(
                "POST",
                f"http://127.0.0.1:{port}/v1/tts",
                content=body,
                headers={"Content-Type": "application/msgpack"},
                timeout=120.0,
            ) as r:
                if r.status_code != 200:
                    samples.append(
                        {"sample": i, "err": f"HTTP {r.status_code}"}
                    )
                    continue
                for chunk in r.iter_bytes():
                    if first is None and chunk:
                        first = time.monotonic() - t0
                    total += len(chunk)
        except Exception as e:  # noqa: BLE001
            samples.append({"sample": i, "err": str(e)[:200]})
            continue
        done = time.monotonic() - t0
        # Fish under streaming=True returns raw PCM16 mono 44.1kHz (no RIFF).
        audio_ms = total / 2 / 44100 * 1000
        samples.append(
            {
                "sample": i,
                "ttfb_ms": int(first * 1000) if first else None,
                "total_ms": int(done * 1000),
                "audio_ms": int(audio_ms) if audio_ms else None,
                "rtf": (done * 1000 / audio_ms) if audio_ms else None,
                "bytes": total,
            }
        )
    return {"port": port, "n": n, "samples": samples}


def median(xs):
    if not xs:
        return None
    s = sorted(xs)
    return s[len(s) // 2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ports", nargs="+", type=int)
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    results = [bench_one_port(p, a.n) for p in a.ports]
    print(json.dumps(results, indent=2))
    print("\n=== Summary (medians, ok-only) ===")
    print(f"{'port':<8}{'TTFB ms':<12}{'Total ms':<12}{'Audio ms':<12}{'RTF':<8}")
    for r in results:
        ok = [s for s in r["samples"] if "err" not in s and s.get("ttfb_ms") is not None]
        if not ok:
            err_sample = next((s for s in r["samples"] if "err" in s), {})
            print(f"{r['port']:<8}{'(all err: ' + str(err_sample.get('err', '?'))[:40] + ')':<48}")
            continue
        print(
            f"{r['port']:<8}"
            f"{median([s['ttfb_ms'] for s in ok]):<12}"
            f"{median([s['total_ms'] for s in ok]):<12}"
            f"{median([s['audio_ms'] for s in ok]):<12}"
            f"{median([s['rtf'] for s in ok]):<8.2f}"
        )


if __name__ == "__main__":
    main()
