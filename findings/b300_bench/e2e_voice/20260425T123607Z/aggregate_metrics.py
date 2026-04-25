#!/usr/bin/env python3
"""Cycle-1 bench metrics aggregator.

Reads:
  - per-turn/turn-NN.stdout  (synthetic_caller_full output)
  - logs/worker.log slice    (b3-latency channel + LLMMetrics + TTSMetrics)

Emits:
  - per-turn/turn-NN.json    (Team-E-shape per-turn record)
  - metrics.json             (aggregated p50/p95/max for each leg)
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

ART = Path(__file__).parent
PER_TURN = ART / "per-turn"
LOGS = ART / "logs"
WORKER_LOG = LOGS / "worker.log"

PROMPTS = [
    ("P1", "I think I am having a heart attack. Chest pain and short of breath."),
    ("P1", "My neighbors not breathing. Hes on the floor."),
    ("P1", "There is a fire on the second floor. We are trapped."),
    ("P2", "Someone broke into my house and I think they are still here."),
    ("P2", "I just got hit by a car at the intersection of fifth and main."),
    ("P2", "My toddler swallowed a battery."),
    ("P3", "I want to report a stolen vehicle from last night."),
    ("P3", "There is a domestic happening next door."),
    ("P4", "My power is out, is there an outage?"),
    ("P4", "I want to report a noise complaint."),
]


def parse_stdout(stdout: str) -> dict:
    """Parse synthetic_caller_full.py stdout."""
    out = {}
    m = re.search(r"AGENT JOINED @ \+([\d.]+)s", stdout)
    out["agent_joined_at_s"] = float(m.group(1)) if m else None
    m = re.search(r"AUDIO TRACK SUBSCRIBED @ \+([\d.]+)s", stdout)
    out["audio_track_at_s"] = float(m.group(1)) if m else None
    m = re.search(r"pre-roll audio: (\d+) non-silent frames, peak (\d+)", stdout)
    if m:
        out["preroll_speech_frames"] = int(m.group(1))
        out["preroll_peak"] = int(m.group(2))
    m = re.search(r"track published @ \+([\d.]+)s", stdout)
    out["publish_start_s"] = float(m.group(1)) if m else None
    m = re.search(r"publish ended @ \+([\d.]+)s", stdout)
    out["publish_end_s"] = float(m.group(1)) if m else None
    m = re.search(r"AGENT REPLY DETECTED @ \+([\d.]+)s \(([\d.]+)s after caller end\), peak (\d+)", stdout)
    if m:
        out["reply_detected_at_s"] = float(m.group(1))
        out["reply_latency_after_pubend_s"] = float(m.group(2))
        out["reply_peak"] = int(m.group(3))
        out["publish_end_to_first_returned_audio_ms"] = int(float(m.group(2)) * 1000)
    else:
        out["reply_latency_after_pubend_s"] = None
        out["publish_end_to_first_returned_audio_ms"] = None
    m = re.search(r"reply_speech_amp_max\s*:\s*(\d+)", stdout)
    out["reply_speech_amp_max"] = int(m.group(1)) if m else None
    m = re.search(r"total_speech_frames\s*:\s*(\d+)", stdout)
    out["total_speech_frames"] = int(m.group(1)) if m else None
    m = re.search(r"VERDICT:\s*(.*)", stdout)
    out["harness_verdict"] = m.group(1).strip() if m else None
    return out


SESSION_RE = re.compile(r"session_id=([0-9a-f-]+)")
LLM_FIRST_TOKEN_RE = re.compile(r"overlap\.llm_first_token_after_speech_ms ms=(\d+) preempt=(\w+) session_id=([0-9a-f-]+) source=(\w+)")
METRICS_CAPTURED_RE = re.compile(r"metrics\.captured\s+llm_ms=(\d+) metric_type=(\w+) session_id=([0-9a-f-]+) stt_ms=(\d+) tts_ms=(\d+)")
PREROLL_SPOKEN_RE = re.compile(r"preroll\.spoken\s+session_id=([0-9a-f-]+)")
PREROLL_SKIPPED_RACE_RE = re.compile(r"preroll\.skipped_caller_spoke_race\s+session_id=([0-9a-f-]+)")
PREROLL_SKIPPED_FIRST_RE = re.compile(r"preroll\.skipped_caller_spoke_first\s+session_id=([0-9a-f-]+)")
SESSION_START_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*session_id=([0-9a-f-]+)")


def parse_worker_log() -> dict[str, dict]:
    """Group worker.log entries by session_id."""
    sessions: dict[str, dict] = {}
    if not WORKER_LOG.exists():
        return sessions
    for line in WORKER_LOG.read_text(errors="replace").splitlines():
        m = LLM_FIRST_TOKEN_RE.search(line)
        if m:
            sid = m.group(3)
            sess = sessions.setdefault(sid, {"llm_first_tokens": [], "metrics": [], "preroll": None})
            sess["llm_first_tokens"].append({
                "ms": int(m.group(1)),
                "preempt": m.group(2),
                "source": m.group(4),
            })
            continue
        m = METRICS_CAPTURED_RE.search(line)
        if m:
            sid = m.group(3)
            sess = sessions.setdefault(sid, {"llm_first_tokens": [], "metrics": [], "preroll": None})
            sess["metrics"].append({
                "metric_type": m.group(2),
                "llm_ms": int(m.group(1)),
                "stt_ms": int(m.group(4)),
                "tts_ms": int(m.group(5)),
            })
            continue
        m = PREROLL_SPOKEN_RE.search(line)
        if m:
            sid = m.group(1)
            sess = sessions.setdefault(sid, {"llm_first_tokens": [], "metrics": [], "preroll": None})
            sess["preroll"] = "spoken"
            continue
        m = PREROLL_SKIPPED_RACE_RE.search(line)
        if m:
            sid = m.group(1)
            sess = sessions.setdefault(sid, {"llm_first_tokens": [], "metrics": [], "preroll": None})
            sess["preroll"] = "skipped_race"
            continue
        m = PREROLL_SKIPPED_FIRST_RE.search(line)
        if m:
            sid = m.group(1)
            sess = sessions.setdefault(sid, {"llm_first_tokens": [], "metrics": [], "preroll": None})
            sess["preroll"] = "skipped_first"
            continue
    return sessions


def percentile(values, p):
    if not values:
        return None
    sorted_vals = sorted(values)
    k = int(round((p / 100) * (len(sorted_vals) - 1)))
    return sorted_vals[k]


def main():
    sessions = parse_worker_log()
    per_turn_records = []
    for i, (priority, prompt) in enumerate(PROMPTS, start=1):
        nn = f"{i:02d}"
        stdout_path = PER_TURN / f"turn-{nn}.stdout"
        if not stdout_path.exists():
            print(f"WARNING: turn-{nn}.stdout missing")
            continue
        stdout = stdout_path.read_text(errors="replace")
        parsed = parse_stdout(stdout)

        # Match session_id by harness verdict OR by prompt order (pod's worker
        # serves rooms 1:1 with our per-turn calls). We rely on the timestamp.
        # The synthetic_caller_full doesn't print the session_id, so we map
        # by prompt order using the worker.log sessions sorted by timestamp.
        rec = {
            "turn": i,
            "priority": priority,
            "prompt": prompt,
            "harness_file": f"turn-{nn}.stdout",
            **parsed,
        }
        per_turn_records.append(rec)

    # Match sessions in time order to turns. This requires knowing the
    # bench window — sessions in worker.log within the bench window get
    # assigned by start order to turns 1..10.
    # Find sessions that have at least one LLMMetrics entry — those are
    # sessions where the cycle-1 bench actually ran.
    valid_sessions = [
        (sid, sess) for sid, sess in sessions.items()
        if any(m["metric_type"] == "LLMMetrics" for m in sess["metrics"])
    ]
    # Sort by FIRST appearance in worker.log: re-grep to get start ts.
    sess_first_ts = {}
    if WORKER_LOG.exists():
        for line in WORKER_LOG.read_text(errors="replace").splitlines():
            m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*session_id=([0-9a-f-]+)", line)
            if m:
                sid = m.group(2)
                if sid not in sess_first_ts:
                    sess_first_ts[sid] = m.group(1)
    valid_sessions.sort(key=lambda x: sess_first_ts.get(x[0], "9999"))

    # Pair turn N with N-th valid session.
    for idx, rec in enumerate(per_turn_records):
        if idx < len(valid_sessions):
            sid, sess = valid_sessions[idx]
            rec["session_id"] = sid
            rec["preroll_state"] = sess["preroll"]
            # LLM first token (the `generate_reply` source one — that's the
            # actual reply, not the preroll/say path).
            gen_reply_tokens = [
                t for t in sess["llm_first_tokens"] if t["source"] == "generate_reply"
            ]
            if gen_reply_tokens:
                rec["llm_first_token_ms"] = gen_reply_tokens[0]["ms"]
            else:
                rec["llm_first_token_ms"] = None
            llm_metrics = [m for m in sess["metrics"] if m["metric_type"] == "LLMMetrics"]
            if llm_metrics:
                rec["llm_total_ms"] = llm_metrics[0]["llm_ms"]
            tts_metrics = [m for m in sess["metrics"] if m["metric_type"] == "TTSMetrics"]
            if tts_metrics:
                rec["tts_ttfb_ms"] = min(m["tts_ms"] for m in tts_metrics)
                rec["tts_total_ms_max"] = max(m["tts_ms"] for m in tts_metrics)
                rec["tts_chunk_count"] = len(tts_metrics)
            stt_metrics = [m for m in sess["metrics"] if m["metric_type"] == "STTMetrics"]
            if stt_metrics:
                rec["stt_ms"] = stt_metrics[0]["stt_ms"]

        # Write per-turn JSON.
        nn = f"{rec['turn']:02d}"
        (PER_TURN / f"turn-{nn}.json").write_text(json.dumps(rec, indent=2) + "\n")

    # Aggregate.
    metric_keys = [
        "stt_ms",
        "llm_first_token_ms",
        "llm_total_ms",
        "tts_ttfb_ms",
        "publish_end_to_first_returned_audio_ms",
        "reply_speech_amp_max",
    ]
    summary = {"n_turns": len(per_turn_records), "metrics": {}}
    for k in metric_keys:
        vals = [r[k] for r in per_turn_records if r.get(k) is not None]
        if vals:
            summary["metrics"][k] = {
                "n": len(vals),
                "p50": percentile(vals, 50),
                "p95": percentile(vals, 95),
                "max": max(vals),
                "min": min(vals),
                "mean": round(statistics.mean(vals), 1),
            }
    # Verification counts.
    summary["verification"] = {
        "fix1_reasoning_content_lines": "see logs/reasoning_content_count.txt",
        "fix2_preroll_spoken_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "spoken"),
        "fix2_preroll_skipped_first_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "skipped_first"),
        "fix2_preroll_skipped_race_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "skipped_race"),
        "non_empty_reply_audio_count": sum(1 for r in per_turn_records if (r.get("reply_speech_amp_max") or 0) > 1000),
    }
    (ART / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
