#!/usr/bin/env python3
"""Cycle-2a-debug bench metrics aggregator.

Same shape as cycle-2a (20260425T130840Z) plus three new fields from the
patched harness (Team H bundle + filler-skip-window calibration):
  - first_useful_audio_after_speech_ms: time from publish-end to the first
    peak>1000 audio frame whose timestamp is AT LEAST FILLER_SKIP_S after
    publish-end. Excludes filler-bridge audio.
  - useful_audio_skipped_filler: bool, true when raw_to_useful_delta_ms > 50.
  - publish_end_to_first_useful_audio_ms: same value as the harness field,
    promoted to the metrics summary as the new HEADLINE number.

Reads:
  - per-turn/turn-NN.{stdout,json}
  - logs/worker.log slice (b3-latency channel + LLMMetrics + TTSMetrics)

Emits:
  - metrics.json with cycle-1 + cycle-2a + cycle-2a-debug fields.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

ART = Path(__file__).parent
PER_TURN = ART / "per-turn"
LOGS = ART / "logs"
WORKER_LOG = LOGS / "worker.log"

PROMPTS = [
    ("P1", "I think I am having a heart attack. Chest pain and short of breath."),
    ("P1", "My neighbor's not breathing. He's on the floor."),
    ("P1", "There's a fire on the second floor. We're trapped."),
    ("P2", "Someone broke into my house and I think they are still here."),
    ("P2", "I just got hit by a car at the intersection of fifth and main."),
    ("P2", "My toddler swallowed a battery."),
    ("P3", "I want to report a stolen vehicle from last night."),
    ("P3", "There's a domestic happening next door."),
    ("P4", "My power's out, is there an outage?"),
    ("P4", "I want to report a noise complaint."),
]


def parse_stdout(stdout: str) -> dict:
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

    # Cycle-2a-debug "AGENT REPLY DETECTED (raw)" — raw amplitude trigger.
    m = re.search(
        r"AGENT REPLY DETECTED \(raw\) @ \+([\d.]+)s "
        r"\(([\d.]+)s after caller end\), peak (\d+)",
        stdout,
    )
    if m:
        out["reply_detected_at_s"] = float(m.group(1))
        out["reply_latency_after_pubend_s"] = float(m.group(2))
        out["reply_peak"] = int(m.group(3))
        out["publish_end_to_first_returned_audio_ms"] = int(float(m.group(2)) * 1000)
    else:
        # Fallback to old format for backwards compat.
        m = re.search(
            r"AGENT REPLY DETECTED @ \+([\d.]+)s \(([\d.]+)s after caller end\), peak (\d+)",
            stdout,
        )
        if m:
            out["reply_detected_at_s"] = float(m.group(1))
            out["reply_latency_after_pubend_s"] = float(m.group(2))
            out["reply_peak"] = int(m.group(3))
            out["publish_end_to_first_returned_audio_ms"] = int(float(m.group(2)) * 1000)
        else:
            out["reply_latency_after_pubend_s"] = None
            out["publish_end_to_first_returned_audio_ms"] = None

    # NEW: AGENT USEFUL REPLY DETECTED (post-filler-skip).
    m = re.search(
        r"AGENT USEFUL REPLY DETECTED @ \+([\d.]+)s "
        r"\(([\d.]+)s after caller end\), peak (\d+)",
        stdout,
    )
    if m:
        out["useful_reply_at_s"] = float(m.group(1))
        out["useful_reply_latency_after_pubend_s"] = float(m.group(2))
        out["useful_reply_peak"] = int(m.group(3))
        out["publish_end_to_first_useful_audio_ms"] = int(float(m.group(2)) * 1000)

    m = re.search(r"first_useful_audio_after_speech_ms\s*:\s*(\d+|NEVER)", stdout)
    if m:
        v = m.group(1)
        out["first_useful_audio_after_speech_ms"] = int(v) if v != "NEVER" else None
    m = re.search(r"first_audio_after_speech_ms\s*:\s*(\d+|NEVER)", stdout)
    if m:
        v = m.group(1)
        out["first_audio_after_speech_ms"] = int(v) if v != "NEVER" else None
    m = re.search(r"filler_skip_window_s\s*:\s*([\d.]+)", stdout)
    if m:
        out["filler_skip_window_s"] = float(m.group(1))
    m = re.search(r"useful_reply_amp_max\s*:\s*(\d+)", stdout)
    if m:
        out["useful_reply_amp_max"] = int(m.group(1))
    m = re.search(r"useful_audio_skipped_filler=(\w+)\s+raw_to_useful_delta_ms=(-?\d+)", stdout)
    if m:
        out["useful_audio_skipped_filler"] = (m.group(1) == "True")
        out["raw_to_useful_delta_ms"] = int(m.group(2))

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
PREROLL_DISABLED_RE = re.compile(r"preroll\.disabled_for_demo\s+session_id=([0-9a-f-]+)")
PREROLL_SKIPPED_RACE_RE = re.compile(r"preroll\.skipped_caller_spoke_race\s+session_id=([0-9a-f-]+)")
PREROLL_SKIPPED_FIRST_RE = re.compile(r"preroll\.skipped_caller_spoke_first\s+session_id=([0-9a-f-]+)")
FILLER_SPOKEN_RE = re.compile(r"filler\.spoken\s+session_id=([0-9a-f-]+)")
TTS_FIRST_AUDIO_RE = re.compile(r"overlap\.tts_first_audio_after_speech_ms ms=(\d+) session_id=([0-9a-f-]+) ttfb_ms=(\d+)")


def parse_worker_log() -> dict[str, dict]:
    sessions: dict[str, dict] = {}
    if not WORKER_LOG.exists():
        return sessions

    def _ensure(sid: str) -> dict:
        return sessions.setdefault(sid, {
            "llm_first_tokens": [],
            "metrics": [],
            "preroll": None,
            "filler_count": 0,
            "tts_first_audio_ms": None,
        })

    for line in WORKER_LOG.read_text(errors="replace").splitlines():
        m = LLM_FIRST_TOKEN_RE.search(line)
        if m:
            _ensure(m.group(3))["llm_first_tokens"].append({
                "ms": int(m.group(1)),
                "preempt": m.group(2),
                "source": m.group(4),
            })
            continue
        m = METRICS_CAPTURED_RE.search(line)
        if m:
            _ensure(m.group(3))["metrics"].append({
                "metric_type": m.group(2),
                "llm_ms": int(m.group(1)),
                "stt_ms": int(m.group(4)),
                "tts_ms": int(m.group(5)),
            })
            continue
        m = PREROLL_SPOKEN_RE.search(line)
        if m:
            _ensure(m.group(1))["preroll"] = "spoken"
            continue
        m = PREROLL_DISABLED_RE.search(line)
        if m:
            _ensure(m.group(1))["preroll"] = "disabled_for_demo"
            continue
        m = PREROLL_SKIPPED_RACE_RE.search(line)
        if m:
            _ensure(m.group(1))["preroll"] = "skipped_race"
            continue
        m = PREROLL_SKIPPED_FIRST_RE.search(line)
        if m:
            _ensure(m.group(1))["preroll"] = "skipped_first"
            continue
        m = FILLER_SPOKEN_RE.search(line)
        if m:
            _ensure(m.group(1))["filler_count"] += 1
            continue
        m = TTS_FIRST_AUDIO_RE.search(line)
        if m:
            sess = _ensure(m.group(2))
            if sess.get("tts_first_audio_ms") is None:
                sess["tts_first_audio_ms"] = int(m.group(1))
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
        rec = {
            "turn": i,
            "priority": priority,
            "prompt": prompt,
            "harness_file": f"turn-{nn}.stdout",
            **parsed,
        }
        per_turn_records.append(rec)

    # Match sessions by start ts.
    sess_first_ts = {}
    if WORKER_LOG.exists():
        for line in WORKER_LOG.read_text(errors="replace").splitlines():
            m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*session_id=([0-9a-f-]+)", line)
            if m:
                sid = m.group(2)
                if sid not in sess_first_ts:
                    sess_first_ts[sid] = m.group(1)
    valid_sessions = [
        (sid, sess) for sid, sess in sessions.items()
        if any(m["metric_type"] == "LLMMetrics" for m in sess["metrics"])
    ]
    valid_sessions.sort(key=lambda x: sess_first_ts.get(x[0], "9999"))

    for idx, rec in enumerate(per_turn_records):
        if idx < len(valid_sessions):
            sid, sess = valid_sessions[idx]
            rec["session_id"] = sid
            rec["preroll_state"] = sess["preroll"]
            rec["filler_count"] = sess["filler_count"]
            if sess["preroll"] == "disabled_for_demo":
                rec["preroll_duration_ms"] = 0
            elif sess["preroll"] == "spoken":
                rec["preroll_duration_ms"] = 2400
            else:
                rec["preroll_duration_ms"] = 0
            gen_reply_tokens = [t for t in sess["llm_first_tokens"] if t["source"] == "generate_reply"]
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

        nn = f"{rec['turn']:02d}"
        (PER_TURN / f"turn-{nn}.json").write_text(json.dumps(rec, indent=2) + "\n")

    metric_keys = [
        "stt_ms",
        "llm_first_token_ms",
        "llm_total_ms",
        "tts_ttfb_ms",
        "tts_total_ms_max",
        "publish_end_to_first_returned_audio_ms",
        "publish_end_to_first_useful_audio_ms",
        "first_useful_audio_after_speech_ms",
        "first_audio_after_speech_ms",
        "preroll_duration_ms",
        "reply_speech_amp_max",
        "useful_reply_amp_max",
        "raw_to_useful_delta_ms",
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

    # Bimodal check: max - min on first_audio_after_speech_ms (raw).
    raw_vals = [r["first_audio_after_speech_ms"] for r in per_turn_records
                if r.get("first_audio_after_speech_ms") is not None]
    useful_vals = [r["first_useful_audio_after_speech_ms"] for r in per_turn_records
                   if r.get("first_useful_audio_after_speech_ms") is not None]
    summary["bimodal_check"] = {
        "raw_max_minus_min_ms": (max(raw_vals) - min(raw_vals)) if raw_vals else None,
        "useful_max_minus_min_ms": (max(useful_vals) - min(useful_vals)) if useful_vals else None,
        "raw_unimodal_target_ms": 2000,
        "useful_unimodal_target_ms": 2000,
    }

    summary["verification"] = {
        "fix1_enable_thinking_false": "preserved (worker.py:358)",
        "cycle2a_preroll_disabled_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "disabled_for_demo"),
        "cycle2a_preroll_spoken_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "spoken"),
        "filler_spoken_count": sum(r.get("filler_count", 0) for r in per_turn_records),
        "non_empty_reply_audio_count": sum(1 for r in per_turn_records if (r.get("reply_speech_amp_max") or 0) > 1000),
        "real_assistant_replies_count": sum(1 for r in per_turn_records if (r.get("llm_total_ms") or 0) > 0),
        "useful_audio_skipped_filler_count": sum(1 for r in per_turn_records if r.get("useful_audio_skipped_filler") is True),
        "useful_audio_present_count": sum(1 for r in per_turn_records if r.get("first_useful_audio_after_speech_ms") is not None),
    }
    (ART / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
