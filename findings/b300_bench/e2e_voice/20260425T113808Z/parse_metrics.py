#!/usr/bin/env python3
"""Parse worker.tail.log and per-turn stdout to aggregate per-leg metrics.

Per-turn fields extracted:
  - session_id (from worker.log entrypoint.start)
  - stt_ms (STTMetrics) -- STT processing time
  - llm_first_token_ms (overlap.llm_first_token_after_speech_ms source=generate_reply)
  - llm_total_ms (LLMMetrics llm_ms field)
  - tts_first_audio_after_speech_ms (overlap.tts_first_audio_after_speech_ms ms=)
  - tts_ttfb_ms (overlap.tts_first_audio_after_speech_ms ttfb_ms=)
  - fishspeech_chunk_count (REPLY fishspeech.done chunk_count=)
  - fishspeech_max_chunk_gap_ms (REPLY fishspeech.done max_chunk_gap_ms=)
  - reply_first_speech_at_pubend (from harness stdout reply_latency_after_pubend)

Note on pre-roll vs reply:
  Each session has TWO fishspeech.done events: first is pre-roll greeting, second is reply.
  We pick the SECOND one (reply) for chunk metrics.
"""
import json
import re
import sys
from pathlib import Path
from statistics import median

ART_DIR = Path("/Users/kiteboard/prism42/findings/b300_bench/e2e_voice/20260425T113808Z")
WORKER_LOG = ART_DIR / "logs" / "worker.tail.log"
TURN_DIR = ART_DIR / "per-turn"

# Test window starts at the first entrypoint AT-or-AFTER 11:38:30 (after Fix 1 applied).
# Pre-fix turn (11:38:43) is excluded.
TEST_WINDOW_START = "2026-04-25 11:40:00"


def percentile(values, pct):
    if not values:
        return None
    sorted_v = sorted(values)
    idx = int(round((pct / 100.0) * (len(sorted_v) - 1)))
    return sorted_v[idx]


def parse_worker_log():
    """Build session_id -> dict of metrics by parsing the log."""
    sessions = {}  # session_id -> metrics dict
    session_order = []  # order seen
    current_sid = None

    pat_entry = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) .* entrypoint\.start.*session_id=([0-9a-f-]+)")
    pat_backend = re.compile(r"llm\.backend.*backend=(\S+) model=(\S+)")
    pat_llm_first = re.compile(r"overlap\.llm_first_token_after_speech_ms ms=(\d+).*session_id=([0-9a-f-]+) source=generate_reply")
    pat_stt = re.compile(r"metric_type=STTMetrics session_id=([0-9a-f-]+) stt_ms=(\d+)")
    pat_llm_total = re.compile(r"llm_ms=(\d+) metric_type=LLMMetrics session_id=([0-9a-f-]+)")
    pat_tts_first = re.compile(r"overlap\.tts_first_audio_after_speech_ms ms=(\d+) session_id=([0-9a-f-]+) ttfb_ms=(\d+)")
    pat_fish_done = re.compile(r"fishspeech\.done.*chunk_count=(\d+).*max_chunk_gap_ms=(\d+).*total_ms=(\d+)")
    pat_preroll = re.compile(r"preroll\.spoken.*session_id=([0-9a-f-]+)")
    pat_filler = re.compile(r"filler\.spoken.*session_id=([0-9a-f-]+) text=(.*)")

    with open(WORKER_LOG) as f:
        lines = f.readlines()

    for line in lines:
        if line < TEST_WINDOW_START:
            continue
        m = pat_entry.search(line)
        if m:
            current_sid = m.group(2)
            ts = m.group(1)
            sessions[current_sid] = {
                "session_id": current_sid,
                "ts_start": ts,
                "fishspeech_events": [],
                "preroll_seen": False,
                "filler_text": None,
            }
            session_order.append(current_sid)
            continue
        m = pat_backend.search(line)
        if m and current_sid:
            sessions[current_sid]["llm_backend"] = m.group(1)
            sessions[current_sid]["llm_model"] = m.group(2)
        m = pat_preroll.search(line)
        if m and m.group(1) in sessions:
            sessions[m.group(1)]["preroll_seen"] = True
        m = pat_stt.search(line)
        if m and m.group(1) in sessions:
            sessions[m.group(1)]["stt_ms"] = int(m.group(2))
        m = pat_llm_first.search(line)
        if m and m.group(2) in sessions:
            # First match wins
            if "llm_first_token_ms" not in sessions[m.group(2)]:
                sessions[m.group(2)]["llm_first_token_ms"] = int(m.group(1))
        m = pat_llm_total.search(line)
        if m and m.group(2) in sessions:
            sessions[m.group(2)]["llm_total_ms"] = int(m.group(1))
        m = pat_tts_first.search(line)
        if m and m.group(2) in sessions:
            sessions[m.group(2)]["tts_first_audio_after_speech_ms"] = int(m.group(1))
            sessions[m.group(2)]["tts_ttfb_ms"] = int(m.group(3))
        m = pat_fish_done.search(line)
        if m and current_sid:
            sessions[current_sid]["fishspeech_events"].append({
                "chunk_count": int(m.group(1)),
                "max_chunk_gap_ms": int(m.group(2)),
                "total_ms": int(m.group(3)),
            })
        m = pat_filler.search(line)
        if m and m.group(1) in sessions and not sessions[m.group(1)].get("filler_text"):
            sessions[m.group(1)]["filler_text"] = m.group(2).strip()

    # For each session: pick the SECOND fishspeech (reply) chunk metrics if available
    for sid, s in sessions.items():
        events = s["fishspeech_events"]
        if len(events) >= 2:
            s["reply_chunk_count"] = events[1]["chunk_count"]
            s["reply_max_chunk_gap_ms"] = events[1]["max_chunk_gap_ms"]
            s["reply_total_ms"] = events[1]["total_ms"]
            s["preroll_chunk_count"] = events[0]["chunk_count"]
            s["preroll_max_chunk_gap_ms"] = events[0]["max_chunk_gap_ms"]
        elif len(events) == 1:
            # Only pre-roll or only reply; ambiguous
            s["preroll_chunk_count"] = events[0]["chunk_count"]
            s["preroll_max_chunk_gap_ms"] = events[0]["max_chunk_gap_ms"]
            s["reply_chunk_count"] = None
            s["reply_max_chunk_gap_ms"] = None
        else:
            s["reply_chunk_count"] = None
            s["reply_max_chunk_gap_ms"] = None

    return sessions, session_order


def parse_stdout(turn_num):
    """Parse per-turn.stdout for the harness-reported reply_latency_after_pubend."""
    path = TURN_DIR / f"turn-{turn_num:02d}.stdout"
    if not path.exists():
        return None
    text = path.read_text()
    out = {}
    m = re.search(r"reply_latency_after_pubend: \+(\d+\.\d+)s", text)
    if m:
        out["publish_end_to_first_returned_audio_ms"] = int(float(m.group(1)) * 1000)
    m = re.search(r"reply_speech_amp_max\s*:\s*(\d+)", text)
    if m:
        out["reply_speech_amp_max"] = int(m.group(1))
    m = re.search(r"preroll_speech_frames\s*:\s*(\d+)", text)
    if m:
        out["preroll_speech_frames"] = int(m.group(1))
    m = re.search(r"VERDICT:\s*(.*)", text)
    if m:
        out["harness_verdict"] = m.group(1).strip()
    return out


def main():
    sessions, order = parse_worker_log()
    # Filter to test-window sessions (post-fix-1, exclude the broken turn-1 attempt at 11:38:43)
    valid = [sid for sid in order if sessions[sid].get("ts_start", "") >= "2026-04-25 11:40:00"]
    # The order should be: turn-01-verify, turn-02, turn-03, ..., turn-10
    # Actually verify happens FIRST then the spec turns 2-10. But we ran 1-verify, 2,3,4,5,6,7,8,9,10.
    # So turn_index_to_sid: index 0 = turn-01-verify, index 1 = turn-02, ..., index 9 = turn-10.

    print(f"# Test-window sessions: {len(valid)}")
    for sid in valid:
        s = sessions[sid]
        print(f"  {s['ts_start']} sid={sid[:8]} backend={s.get('llm_backend','?')} "
              f"stt={s.get('stt_ms','?')}ms ttft={s.get('llm_first_token_ms','?')}ms "
              f"tts_after_speech={s.get('tts_first_audio_after_speech_ms','?')}ms "
              f"reply_chunks={s.get('reply_chunk_count','?')} reply_gap={s.get('reply_max_chunk_gap_ms','?')}ms "
              f"preroll_seen={s.get('preroll_seen', False)}")

    # Aggregate per-turn JSON
    per_turn = []
    # Map turn index to harness file
    turn_files = ["turn-01-verify"] + [f"turn-{n:02d}" for n in range(2, 11)]
    prompts = {
        1: ("P1", "I think I am having a heart attack. Chest pain and short of breath."),
        2: ("P1", "My neighbors not breathing. Hes on the floor."),
        3: ("P1", "There is a fire on the second floor. We are trapped."),
        4: ("P2", "Someone broke into my house and I think they are still here."),
        5: ("P2", "I just got hit by a car at the intersection of fifth and main."),
        6: ("P2", "My toddler swallowed a battery."),
        7: ("P3", "I want to report a stolen vehicle from last night."),
        8: ("P3", "There is a domestic happening next door."),
        9: ("P4", "My power is out, is there an outage?"),
        10: ("P4", "I want to report a noise complaint."),
    }

    for i, fname in enumerate(turn_files):
        turn_num = i + 1  # 1-indexed
        # Parse stdout
        stdout_path = TURN_DIR / f"{fname}.stdout"
        text = stdout_path.read_text() if stdout_path.exists() else ""
        m = re.search(r"reply_latency_after_pubend: \+(\d+\.\d+)s", text)
        publish_end_ms = int(float(m.group(1)) * 1000) if m else None
        m_pre = re.search(r"preroll_speech_frames\s*:\s*(\d+)", text)
        preroll_frames = int(m_pre.group(1)) if m_pre else None
        m_amp = re.search(r"reply_speech_amp_max\s*:\s*(\d+)", text)
        reply_amp = int(m_amp.group(1)) if m_amp else None
        m_v = re.search(r"VERDICT:\s*(.*)", text)
        verdict = m_v.group(1).strip() if m_v else None
        m_total = re.search(r"total_speech_frames\s*:\s*(\d+)", text)
        total_frames = int(m_total.group(1)) if m_total else None

        # Find matching session by index
        sid = valid[i] if i < len(valid) else None
        s = sessions.get(sid, {}) if sid else {}

        priority, prompt = prompts.get(turn_num, ("?", "?"))
        entry = {
            "turn": turn_num,
            "harness_file": fname,
            "priority": priority,
            "prompt": prompt,
            "session_id": sid,
            "ts_start": s.get("ts_start"),
            "llm_backend": s.get("llm_backend"),
            "llm_model": s.get("llm_model"),
            # Harness output
            "harness_verdict": verdict,
            "harness_exit_implied": "exit_4" if verdict and "pre-roll never spoke" in verdict else ("exit_0" if verdict and "PASS" in verdict else "other"),
            "preroll_speech_frames": preroll_frames,
            "total_speech_frames": total_frames,
            "reply_speech_amp_max": reply_amp,
            "publish_end_to_first_returned_audio_ms": publish_end_ms,
            # Worker.log metrics (per-leg)
            "stt_ms": s.get("stt_ms"),
            "llm_first_token_ms": s.get("llm_first_token_ms"),
            "llm_total_ms": s.get("llm_total_ms"),
            "tts_first_audio_after_speech_ms": s.get("tts_first_audio_after_speech_ms"),
            "tts_ttfb_ms": s.get("tts_ttfb_ms"),
            "preroll_chunk_count": s.get("preroll_chunk_count"),
            "preroll_max_chunk_gap_ms": s.get("preroll_max_chunk_gap_ms"),
            "reply_chunk_count": s.get("reply_chunk_count"),
            "reply_max_chunk_gap_ms": s.get("reply_max_chunk_gap_ms"),
            "reply_total_ms_log": s.get("reply_total_ms"),
            "preroll_seen_in_log": s.get("preroll_seen"),
            "filler_text": s.get("filler_text"),
        }
        per_turn.append(entry)

    # Write per-turn JSON
    for entry in per_turn:
        n = entry["turn"]
        outpath = TURN_DIR / f"turn-{n:02d}.json"
        outpath.write_text(json.dumps(entry, indent=2))

    # Aggregate
    def stats(field, source=per_turn):
        vals = [e[field] for e in source if e.get(field) is not None]
        if not vals:
            return None
        return {
            "count": len(vals),
            "p50": percentile(vals, 50),
            "p95": percentile(vals, 95),
            "max": max(vals),
            "min": min(vals),
        }

    metrics = {
        "test_window_utc_iso": "2026-04-25T11:40:00Z..2026-04-25T11:50:00Z",
        "n_turns": len(per_turn),
        "n_sessions_in_log": len(valid),
        "metric_definitions": {
            "stt_ms": "STT processing latency (Parakeet final partial -> word-final). Source: STTMetrics in worker.log.",
            "llm_first_token_ms": "From end-of-speech to LLM first token. Source: overlap.llm_first_token_after_speech_ms source=generate_reply.",
            "llm_total_ms": "Full LLM completion duration. Source: LLMMetrics in worker.log.",
            "tts_first_audio_after_speech_ms": "From end-of-speech (caller) to first agent audio bytes. Source: overlap.tts_first_audio_after_speech_ms.",
            "tts_ttfb_ms": "TTS time-to-first-byte (Fish Speech latency only). Source: overlap.tts_first_audio_after_speech_ms ttfb_ms.",
            "publish_end_to_first_returned_audio_ms": "HEADLINE — From caller publish_end to first detected speech amplitude on agent track. Source: synthetic_caller_full.py reply_latency_after_pubend.",
            "reply_chunk_count": "Number of TTS chunks for the REPLY (excludes pre-roll). Source: 2nd fishspeech.done in session.",
            "reply_max_chunk_gap_ms": "Largest inter-chunk gap during REPLY. Source: 2nd fishspeech.done.",
        },
        "per_leg_p50_p95_max": {
            "stt_ms": stats("stt_ms"),
            "llm_first_token_ms": stats("llm_first_token_ms"),
            "llm_total_ms": stats("llm_total_ms"),
            "tts_first_audio_after_speech_ms": stats("tts_first_audio_after_speech_ms"),
            "tts_ttfb_ms": stats("tts_ttfb_ms"),
            "publish_end_to_first_returned_audio_ms": stats("publish_end_to_first_returned_audio_ms"),
            "reply_chunk_count": stats("reply_chunk_count"),
            "reply_max_chunk_gap_ms": stats("reply_max_chunk_gap_ms"),
        },
        "counts": {
            "harness_exit_0_count": sum(1 for e in per_turn if e["harness_exit_implied"] == "exit_0"),
            "harness_exit_4_count": sum(1 for e in per_turn if e["harness_exit_implied"] == "exit_4"),
            "preroll_seen_in_log_count": sum(1 for e in per_turn if e["preroll_seen_in_log"]),
            "all_sessions_used_vllm": all(e.get("llm_backend") == "vllm-local" for e in per_turn),
            "all_sessions_model_correct": all(e.get("llm_model") == "nemotron-nano" for e in per_turn),
        },
    }

    (ART_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"\n# Aggregated metrics:")
    print(json.dumps(metrics["per_leg_p50_p95_max"], indent=2))
    print(f"\n# Counts:")
    print(json.dumps(metrics["counts"], indent=2))

    return per_turn, metrics


if __name__ == "__main__":
    main()
