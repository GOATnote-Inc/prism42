#!/usr/bin/env python3
"""Aggregate cycle-2f smoke (flag OFF) metrics from per-turn stdouts.

Mirrors cycle2d_n30/aggregate_metrics.py shape so downstream tooling
can ingest both. Writes a stripped-down metrics.json next to the
existing one (this is the authoritative regenerator if the JSON ever
needs to be rebuilt from per-turn artifacts).

Usage:
    cd findings/b300_bench/cycle2f_prosody/2026-04-25T21-01-51Z
    python3 aggregate_metrics.py
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

PER_TURN_DIR = Path(__file__).parent / "per-turn"

# Regex patterns matching synthetic_caller_full.py stdout shape.
RE_FIRST_AUDIO_AFTER = re.compile(r"^first_audio_after_speech_ms:\s*(\d+|NEVER)", re.M)
RE_FIRST_USEFUL_AFTER = re.compile(r"^first_useful_audio_after_speech_ms:\s*(\d+|NEVER)", re.M)
RE_REPLY_AMP_MAX = re.compile(r"reply_speech_amp_max\s*:\s*(\d+)", re.M)
RE_USEFUL_AMP_MAX = re.compile(r"useful_reply_amp_max\s*:\s*(\d+)", re.M)
RE_USEFUL_DUR_MS = re.compile(r"useful_audio_duration_ms:\s*(\d+)", re.M)
RE_TTS_TOTAL_MS = re.compile(r"tts_total_ms\s*:\s*(\d+)", re.M)
RE_VERDICT = re.compile(r"VERDICT:\s*(\w+)", re.M)


def parse_turn(stdout_path: Path) -> dict:
    text = stdout_path.read_text(encoding="utf-8", errors="replace")
    out: dict = {"file": stdout_path.name}
    for key, regex in {
        "first_audio_after_speech_ms": RE_FIRST_AUDIO_AFTER,
        "first_useful_audio_after_speech_ms": RE_FIRST_USEFUL_AFTER,
        "reply_speech_amp_max": RE_REPLY_AMP_MAX,
        "useful_reply_amp_max": RE_USEFUL_AMP_MAX,
        "useful_audio_duration_ms": RE_USEFUL_DUR_MS,
        "tts_total_ms": RE_TTS_TOTAL_MS,
    }.items():
        match = regex.search(text)
        if match:
            val = match.group(1)
            out[key] = int(val) if val != "NEVER" else None
        else:
            out[key] = None
    verdict = RE_VERDICT.search(text)
    out["harness_verdict"] = verdict.group(1) if verdict else None
    return out


def percentile(values: list[int], p: float) -> float:
    if not values:
        return float("nan")
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def aggregate(turns: list[dict]) -> dict:
    e2e = [t["first_audio_after_speech_ms"] for t in turns if t["first_audio_after_speech_ms"]]
    tts_total = [t["tts_total_ms"] for t in turns if t["tts_total_ms"]]
    amps = [t["reply_speech_amp_max"] for t in turns if t["reply_speech_amp_max"]]
    return {
        "n_turns": len(turns),
        "first_audio_after_speech_ms": {
            "values": e2e,
            "min": min(e2e) if e2e else None,
            "max": max(e2e) if e2e else None,
            "mean": round(statistics.mean(e2e), 1) if e2e else None,
            "p50": round(percentile(e2e, 50), 1) if e2e else None,
            "p95_approx": round(percentile(e2e, 95), 1) if e2e else None,
        },
        "tts_total_ms": {
            "values": tts_total,
            "min": min(tts_total) if tts_total else None,
            "max": max(tts_total) if tts_total else None,
            "mean": round(statistics.mean(tts_total), 1) if tts_total else None,
        },
        "reply_speech_amp_max": {
            "values": amps,
            "min": min(amps) if amps else None,
            "max": max(amps) if amps else None,
            "mean": round(statistics.mean(amps), 1) if amps else None,
        },
        "harness_verdict_count": {
            "PASS": sum(1 for t in turns if t["harness_verdict"] == "PASS"),
            "FAIL": sum(1 for t in turns if t["harness_verdict"] == "FAIL"),
            "note": "PASS verdict only means audio frames received; does NOT validate reply coherence",
        },
    }


def main() -> int:
    if not PER_TURN_DIR.is_dir():
        print(f"per-turn directory missing: {PER_TURN_DIR}", file=sys.stderr)
        return 2
    turns: list[dict] = []
    for stdout in sorted(PER_TURN_DIR.glob("smoke-flag-off-turn-*.stdout")):
        turns.append(parse_turn(stdout))
    if not turns:
        print("no smoke turns found in per-turn dir", file=sys.stderr)
        return 1
    summary = aggregate(turns)
    output = {
        "test_id": "2026-04-25T21-01-51Z",
        "cycle": "cycle-2f-voice-empathy-prosody-tags",
        "verdict": "ROLLBACK_2F",
        "smoke_flag_off": summary,
        "per_turn": turns,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
