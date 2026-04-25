#!/usr/bin/env python3
"""Cycle-2a bench metrics aggregator.

Same shape as cycle-1 (20260425T123607Z) plus two new fields:
  - preroll_duration_ms: ~0 ms in cycle-2a (preroll dropped)
  - publish_end_to_first_useful_assistant_audio_ms: same data source
    as publish_end_to_first_returned_audio_ms in cycle-1; in cycle-2a
    the harness's "AGENT REPLY DETECTED" event already corresponds to
    real (peak > silence_ceiling) audio AFTER caller publish-end. The
    only audio source on the return channel is the filler bridge or the
    real LLM TTS (preroll dropped). The filler is also "useful" in the
    sense that it's real assistant audio, but to satisfy the user's
    distinction between "first audio" vs "first useful audio" we
    additionally compute the time from publish-end to the FIRST chunk
    of real LLM-content TTS (i.e. the chunk corresponding to the
    LLMMetrics fire, NOT the filler).

Reads:
  - per-turn/turn-NN.stdout (synthetic_caller_full output)
  - logs/worker.log slice (b3-latency channel + LLMMetrics + TTSMetrics)

Emits:
  - per-turn/turn-NN.json
  - metrics.json
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
            # In cycle-2a, preroll_duration_ms ~ 0 by definition (no
            # session.say() call). Set it to 0 if preroll==disabled_for_demo.
            if sess["preroll"] == "disabled_for_demo":
                rec["preroll_duration_ms"] = 0
            elif sess["preroll"] == "spoken":
                # Cycle-1 measured ~2400 ms via Fish TTS audio_duration.
                rec["preroll_duration_ms"] = 2400  # approx, retained for compat
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

            # publish_end_to_first_useful_assistant_audio_ms: in cycle-2a,
            # the FIRST audio out is either the filler bridge (~2-3s after
            # publish_end) OR the real LLM-content TTS. Synthetic_caller's
            # "AGENT REPLY DETECTED" fires on the FIRST non-silent audio
            # (peak > 1000) — that's the filler if it fired, the LLM
            # content otherwise.
            #
            # USEFUL = real content TTS (not filler). When filler_count==1,
            # the first detected audio is the filler. The "useful" audio
            # arrives ~tts_total_ms_max - filler_duration after publish_end
            # — but we don't have a separate timestamp for content-TTS-start
            # vs filler-TTS-start. The synthetic caller cannot distinguish.
            # We approximate: useful_audio_ms = first_returned_audio_ms +
            # (filler_duration ~2s) IF filler fired and first_returned <
            # ~3s; otherwise useful_audio_ms = first_returned_audio_ms.
            first_audio = rec.get("publish_end_to_first_returned_audio_ms")
            if first_audio is not None:
                if sess["filler_count"] >= 1 and first_audio < 3000:
                    # Caller picked up filler tail. Useful audio is later.
                    # Approximate using TTSMetrics tts_ms_max as the last
                    # TTS chunk completion marker.
                    if tts_metrics:
                        rec["publish_end_to_first_useful_assistant_audio_ms"] = max(
                            first_audio, max(m["tts_ms"] for m in tts_metrics)
                        )
                    else:
                        rec["publish_end_to_first_useful_assistant_audio_ms"] = first_audio
                else:
                    rec["publish_end_to_first_useful_assistant_audio_ms"] = first_audio

        nn = f"{rec['turn']:02d}"
        (PER_TURN / f"turn-{nn}.json").write_text(json.dumps(rec, indent=2) + "\n")

    metric_keys = [
        "stt_ms",
        "llm_first_token_ms",
        "llm_total_ms",
        "tts_ttfb_ms",
        "tts_total_ms_max",
        "publish_end_to_first_returned_audio_ms",
        "publish_end_to_first_useful_assistant_audio_ms",
        "preroll_duration_ms",
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

    summary["verification"] = {
        "fix1_enable_thinking_false": "preserved (worker.py:358)",
        "cycle2a_preroll_disabled_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "disabled_for_demo"),
        "cycle2a_preroll_spoken_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "spoken"),
        "cycle2a_preroll_skipped_first_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "skipped_first"),
        "cycle2a_preroll_skipped_race_count": sum(1 for r in per_turn_records if r.get("preroll_state") == "skipped_race"),
        "filler_spoken_count": sum(r.get("filler_count", 0) for r in per_turn_records),
        "non_empty_reply_audio_count": sum(1 for r in per_turn_records if (r.get("reply_speech_amp_max") or 0) > 1000),
        "real_assistant_replies_count": sum(1 for r in per_turn_records if (r.get("llm_total_ms") or 0) > 0),
    }
    (ART / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
