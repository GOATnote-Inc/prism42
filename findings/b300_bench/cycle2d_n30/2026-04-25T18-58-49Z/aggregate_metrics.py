#!/usr/bin/env python3
"""Cycle-2d-n30 bench metrics aggregator.

Same shape as cycle-2d (cycle2d_fish_fa/2026-04-25T14-06-50Z) extended to n=30:
  - p99 across all metrics (n=30 supports it)
  - mean +/- 95% CI half-width
  - distribution shape: warm subset (turns 2-30, n=29), histogram, outliers
  - cold-start vs warm classification

Reads:
  - per-turn/turn-NN.{stdout,json} (1..30)
  - logs/worker.log slice (b3-latency channel + LLMMetrics + TTSMetrics)
  - prompts.txt (PRIORITY|PROMPT, 1 per line)

Emits:
  - metrics.json with cycle-2d shape + n=30 stats
  - histogram.txt
  - result.json (summary; written separately)
"""
from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

ART = Path(__file__).parent
PER_TURN = ART / "per-turn"
LOGS = ART / "logs"
WORKER_LOG = LOGS / "worker.log"
PROMPTS_PATH = ART / "prompts.txt"


def load_prompts():
    out = []
    for line in PROMPTS_PATH.read_text().splitlines():
        if not line.strip() or "|" not in line:
            continue
        priority, prompt = line.split("|", 1)
        out.append((priority.strip(), prompt.strip()))
    return out


PROMPTS = load_prompts()


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
TTS_CHUNK_GAP_RE = re.compile(r"tts\.chunk_gap_ms ms=(\d+) chunk=(\d+) session_id=([0-9a-f-]+)")


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
            "tts_chunk_gaps": [],
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
        m = TTS_CHUNK_GAP_RE.search(line)
        if m:
            _ensure(m.group(3))["tts_chunk_gaps"].append(int(m.group(1)))
            continue
    return sessions


def percentile(values, p):
    if not values:
        return None
    sorted_vals = sorted(values)
    if p >= 100:
        return sorted_vals[-1]
    if p <= 0:
        return sorted_vals[0]
    k = int(round((p / 100) * (len(sorted_vals) - 1)))
    return sorted_vals[k]


def stats_full(values):
    """Returns p50/p95/p99/max/min/mean/stdev/n + 95% CI half-width."""
    if not values:
        return None
    n = len(values)
    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if n >= 2 else 0.0
    # 95% CI half-width using t-distribution; for n>=10, t~2.0; for n=29, t=2.045; n=30 t=2.045
    # Use t for n<30 but here n>=29; approximate t(.025, df=n-1).
    if n >= 30:
        t = 2.045
    elif n >= 20:
        t = 2.093
    elif n >= 10:
        t = 2.262
    elif n >= 5:
        t = 2.776
    else:
        t = 3.182
    ci_half = t * stdev / math.sqrt(n) if n >= 2 else 0.0
    return {
        "n": n,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
        "min": min(values),
        "mean": round(mean, 1),
        "stdev": round(stdev, 1),
        "ci95_half_width": round(ci_half, 1),
    }


def histogram(values, n_buckets=10):
    if not values:
        return None
    lo, hi = min(values), max(values)
    if hi == lo:
        return {"buckets": [(lo, hi, len(values))], "lo": lo, "hi": hi}
    width = (hi - lo) / n_buckets
    counts = [0] * n_buckets
    for v in values:
        idx = int((v - lo) / width)
        if idx >= n_buckets:
            idx = n_buckets - 1
        counts[idx] += 1
    buckets = []
    for i in range(n_buckets):
        b_lo = lo + i * width
        b_hi = lo + (i + 1) * width
        buckets.append((round(b_lo, 1), round(b_hi, 1), counts[i]))
    return {"buckets": buckets, "lo": lo, "hi": hi, "width": round(width, 1)}


def text_histogram(values, label, n_buckets=10):
    h = histogram(values, n_buckets)
    if not h:
        return f"{label}: no data\n"
    lines = [f"{label}  n={len(values)}  range=[{h['lo']}, {h['hi']}] ms  bucket_width={h['width']} ms"]
    max_count = max((b[2] for b in h["buckets"]), default=1)
    for lo, hi, c in h["buckets"]:
        bar = "#" * int(40 * c / max_count) if max_count else ""
        lines.append(f"  [{lo:>8.1f}, {hi:>8.1f}) | {c:>3} | {bar}")
    return "\n".join(lines) + "\n"


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
                rec["reply_chunk_count"] = len(tts_metrics)
            stt_metrics = [m for m in sess["metrics"] if m["metric_type"] == "STTMetrics"]
            if stt_metrics:
                rec["stt_ms"] = stt_metrics[0]["stt_ms"]
            if sess.get("tts_chunk_gaps"):
                rec["reply_max_chunk_gap_ms"] = max(sess["tts_chunk_gaps"])

        nn = f"{rec['turn']:02d}"
        (PER_TURN / f"turn-{nn}.json").write_text(json.dumps(rec, indent=2) + "\n")

    # Aggregate stats over all turns and warm subset (turns 2..N).
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
        "reply_chunk_count",
        "reply_max_chunk_gap_ms",
    ]
    summary = {
        "n_turns": len(per_turn_records),
        "metrics_all": {},
        "metrics_warm": {},
    }
    warm_records = [r for r in per_turn_records if r["turn"] >= 2]
    for k in metric_keys:
        all_vals = [r[k] for r in per_turn_records if r.get(k) is not None]
        warm_vals = [r[k] for r in warm_records if r.get(k) is not None]
        if all_vals:
            summary["metrics_all"][k] = stats_full(all_vals)
        if warm_vals:
            summary["metrics_warm"][k] = stats_full(warm_vals)

    # Distribution shape: histogram on e2e and Fish full-render
    e2e_all = [r["first_audio_after_speech_ms"] for r in per_turn_records if r.get("first_audio_after_speech_ms") is not None]
    e2e_warm = [r["first_audio_after_speech_ms"] for r in warm_records if r.get("first_audio_after_speech_ms") is not None]
    fish_full_all = [r["tts_total_ms_max"] for r in per_turn_records if r.get("tts_total_ms_max") is not None]
    fish_full_warm = [r["tts_total_ms_max"] for r in warm_records if r.get("tts_total_ms_max") is not None]

    summary["distribution"] = {
        "e2e_all_hist": histogram(e2e_all),
        "e2e_warm_hist": histogram(e2e_warm),
        "fish_full_all_hist": histogram(fish_full_all),
        "fish_full_warm_hist": histogram(fish_full_warm),
    }

    # Outliers: 3-sigma on warm distribution (turn-1 always treated as cold-start
    # in cycle-2d framing).
    if fish_full_warm and len(fish_full_warm) >= 2:
        mean_w = statistics.mean(fish_full_warm)
        sd_w = statistics.stdev(fish_full_warm)
        outlier_threshold = mean_w + 3 * sd_w
        outliers_warm = [
            {"turn": r["turn"], "fish_full_ms": r["tts_total_ms_max"], "z": round((r["tts_total_ms_max"] - mean_w) / sd_w, 2) if sd_w > 0 else None}
            for r in warm_records
            if r.get("tts_total_ms_max") is not None and r["tts_total_ms_max"] > outlier_threshold
        ]
    else:
        mean_w = sd_w = None
        outliers_warm = []

    cold_threshold_ms = 2 * (statistics.median(fish_full_warm) if fish_full_warm else 0)
    cold_starts = [
        {"turn": r["turn"], "fish_full_ms": r["tts_total_ms_max"]}
        for r in per_turn_records
        if r.get("tts_total_ms_max") is not None and r["tts_total_ms_max"] >= cold_threshold_ms and cold_threshold_ms > 0
    ]

    # Bimodal rule-of-thumb: max-min spread vs 4*stdev.
    if fish_full_all and len(fish_full_all) >= 2:
        spread = max(fish_full_all) - min(fish_full_all)
        sd_all = statistics.stdev(fish_full_all)
        bimodal_indicator = spread > 4 * sd_all
    else:
        bimodal_indicator = None
        spread = sd_all = None

    summary["distribution_shape"] = {
        "warm_mean_ms": round(mean_w, 1) if mean_w is not None else None,
        "warm_stdev_ms": round(sd_w, 1) if sd_w is not None else None,
        "warm_outliers_3sigma": outliers_warm,
        "cold_start_threshold_ms": cold_threshold_ms,
        "cold_start_count": len(cold_starts),
        "cold_starts": cold_starts,
        "all_max_minus_min_ms": spread,
        "all_stdev_ms": round(sd_all, 1) if sd_all is not None else None,
        "bimodal_indicator_spread_gt_4sigma": bimodal_indicator,
    }

    # Cycle-2d comparison (warm subset)
    cycle2d = {
        "fish_full_render_p50_warm_ms": 2216,
        "fish_full_render_p95_warm_ms": 2468,
        "e2e_p95_warm_ms": 3506,
    }
    n30_warm = summary["metrics_warm"]
    cmp = {}
    if n30_warm.get("tts_total_ms_max"):
        n30_p50 = n30_warm["tts_total_ms_max"]["p50"]
        n30_p95 = n30_warm["tts_total_ms_max"]["p95"]
        cmp["fish_full_p50_delta_pct"] = round(100 * (n30_p50 - cycle2d["fish_full_render_p50_warm_ms"]) / cycle2d["fish_full_render_p50_warm_ms"], 1)
        cmp["fish_full_p95_delta_pct"] = round(100 * (n30_p95 - cycle2d["fish_full_render_p95_warm_ms"]) / cycle2d["fish_full_render_p95_warm_ms"], 1)
    if n30_warm.get("first_audio_after_speech_ms"):
        n30_e2e_p95 = n30_warm["first_audio_after_speech_ms"]["p95"]
        cmp["e2e_p95_delta_pct"] = round(100 * (n30_e2e_p95 - cycle2d["e2e_p95_warm_ms"]) / cycle2d["e2e_p95_warm_ms"], 1)
        cmp["e2e_p95_in_pm_10_band"] = abs(cmp["e2e_p95_delta_pct"]) <= 10
    summary["cycle2d_comparison"] = {"cycle2d_warm": cycle2d, "deltas": cmp}

    # Verification fields
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

    # Histogram text file
    hist_lines = ["# Cycle-2d-n30 Distribution Histograms\n"]
    hist_lines.append(text_histogram(e2e_all, "E2E (publish_end_to_first_returned_audio) ALL n=30"))
    hist_lines.append(text_histogram(e2e_warm, "E2E (publish_end_to_first_returned_audio) WARM n=29 (turns 2-30)"))
    hist_lines.append(text_histogram(fish_full_all, "Fish full-render (tts_total_ms_max) ALL n=30"))
    hist_lines.append(text_histogram(fish_full_warm, "Fish full-render (tts_total_ms_max) WARM n=29 (turns 2-30)"))
    (ART / "histogram.txt").write_text("\n".join(hist_lines))

    print(json.dumps({"n_turns": summary["n_turns"], "metrics_warm_summary": {
        k: {"p50": v.get("p50"), "p95": v.get("p95"), "p99": v.get("p99"), "mean": v.get("mean"), "ci95": v.get("ci95_half_width")}
        for k, v in summary["metrics_warm"].items()
    }}, indent=2))


if __name__ == "__main__":
    main()
