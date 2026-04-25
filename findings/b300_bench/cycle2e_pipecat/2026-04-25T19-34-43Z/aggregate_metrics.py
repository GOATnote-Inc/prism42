#!/usr/bin/env python3
"""Aggregate cycle-2e per-turn metrics and emit metrics.json + result.json.

Reads per-turn/turn-NN.stdout (10 turns) + logs/worker.log, parses each
turn's emitted scalars, and computes p50/p95/p99/mean/min/max for the
cycle-2d-n30-shape fields plus the new cycle-2e fields.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

DIR = Path(__file__).resolve().parent
WORKER_LOG = DIR / "logs" / "worker.log"
PER_TURN = sorted((DIR / "per-turn").glob("turn-*.stdout"))


def parse_turn(stdout: str) -> dict:
    out: dict = {}
    for k, regex in [
        ("first_useful_audio_after_speech_ms", r"first_useful_audio_after_speech_ms:\s*(\d+|NEVER)"),
        ("first_audio_after_speech_ms", r"first_audio_after_speech_ms:\s*(\d+|NEVER)"),
        ("reply_speech_amp_max", r"reply_speech_amp_max\s*:\s*(-?\d+)"),
        ("useful_reply_amp_max", r"useful_reply_amp_max\s*:\s*(-?\d+)"),
        ("global_peak_amplitude", r"global_peak_amplitude\s*:\s*(-?\d+)"),
        ("total_speech_frames", r"total_speech_frames\s*:\s*(-?\d+)"),
        ("tts_total_ms", r"tts_total_ms\s*:\s*(-?\d+)"),
        ("useful_audio_duration_ms", r"useful_audio_duration_ms:\s*(-?\d+)"),
        ("useful_audio_skipped_filler", r"useful_audio_skipped_filler=(True|False)"),
        ("raw_to_useful_delta_ms", r"raw_to_useful_delta_ms=(-?\d+)"),
    ]:
        m = re.search(regex, stdout)
        if m:
            v = m.group(1)
            if v == "NEVER":
                out[k] = -1
            elif v in ("True", "False"):
                out[k] = v == "True"
            else:
                out[k] = int(v)
        else:
            out[k] = None
    out["verdict_pass"] = "VERDICT: PASS" in stdout
    return out


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return -1
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "p50": -1, "p95": -1, "p99": -1, "min": -1, "max": -1, "mean": -1}
    return {
        "n": len(xs),
        "p50": round(percentile(xs, 50), 1),
        "p95": round(percentile(xs, 95), 1),
        "p99": round(percentile(xs, 99), 1),
        "min": round(min(xs), 1),
        "max": round(max(xs), 1),
        "mean": round(statistics.mean(xs), 1),
        "stdev": round(statistics.stdev(xs), 1) if len(xs) > 1 else 0,
    }


def parse_first_segment_log(log_path: Path) -> list[dict]:
    """Parse `overlap.first_segment_published_after_llm_ms` lines."""
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()
    out: list[dict] = []
    for ln in lines:
        if "first_segment_published_after_llm_ms" not in ln:
            continue
        m_ms = re.search(r"\bms=(\d+)", ln)
        m_chars = re.search(r"\bchars=(\d+)", ln)
        m_tokens = re.search(r"approx_tokens=(\d+)", ln)
        if m_ms:
            out.append({
                "ms": int(m_ms.group(1)),
                "chars": int(m_chars.group(1)) if m_chars else None,
                "approx_tokens": int(m_tokens.group(1)) if m_tokens else None,
            })
    return out


def main() -> None:
    turns: list[dict] = []
    for f in PER_TURN:
        d = parse_turn(f.read_text())
        d["turn"] = int(re.search(r"turn-(\d+)", f.name).group(1))
        d["stdout_path"] = str(f.relative_to(DIR))
        turns.append(d)
        # Write per-turn JSON sidecar.
        sidecar = f.with_suffix(".json")
        sidecar.write_text(json.dumps(d, indent=2))

    real_replies = sum(1 for t in turns if t["verdict_pass"])
    skipped_filler_count = sum(1 for t in turns if t.get("useful_audio_skipped_filler") is True)

    # Pull arrays for stats.
    fua = [t["first_useful_audio_after_speech_ms"] for t in turns
           if isinstance(t["first_useful_audio_after_speech_ms"], int) and t["first_useful_audio_after_speech_ms"] >= 0]
    fa = [t["first_audio_after_speech_ms"] for t in turns
          if isinstance(t["first_audio_after_speech_ms"], int) and t["first_audio_after_speech_ms"] >= 0]
    tts_total = [t["tts_total_ms"] for t in turns
                 if isinstance(t["tts_total_ms"], int) and t["tts_total_ms"] >= 0]
    ureply = [t["useful_reply_amp_max"] for t in turns
              if isinstance(t["useful_reply_amp_max"], int) and t["useful_reply_amp_max"] >= 0]
    rspeech = [t["reply_speech_amp_max"] for t in turns
               if isinstance(t["reply_speech_amp_max"], int) and t["reply_speech_amp_max"] >= 0]

    fs_log = parse_first_segment_log(WORKER_LOG)
    fs_ms = [r["ms"] for r in fs_log]
    fs_chars = [r["chars"] for r in fs_log if r.get("chars") is not None]
    first_seg_min_chars_passes = sum(1 for c in fs_chars if c >= 8)

    metrics = {
        "n_turns": len(turns),
        "real_replies": f"{real_replies}/{len(turns)}",
        "useful_audio_skipped_filler_count": f"{skipped_filler_count}/{len(turns)}",
        "first_useful_audio_after_speech_ms": stats(fua),
        "first_audio_after_speech_ms": stats(fa),
        "tts_total_ms": stats(tts_total),
        "useful_reply_amp_max": stats(ureply),
        "reply_speech_amp_max": stats(rspeech),
        "first_segment_published_after_llm_ms": stats([float(x) for x in fs_ms]),
        "first_segment_emitted_count": f"{len(fs_log)}/{len(turns)}",
        "first_segment_min_chars_passes": f"{first_seg_min_chars_passes}/{len(fs_log)}" if fs_log else "0/0",
        "first_segment_chars_distribution": fs_chars,
        "first_segment_records": fs_log,
        "per_turn": turns,
    }
    (DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
