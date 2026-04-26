"""Aggregate cycle-2k bench metrics: per-condition wpm, sps, ttfb, peak.

Reads result.json + each WAV file. Computes:
- voiced duration via 5%-of-peak energy threshold on 10ms RMS frames
- words/syllables: hand-counted constants per phrase
- wpm = 60 * words / voiced_dur_s
- sps  = syllables / voiced_dur_s

Outputs metrics.json and prints summary table.
"""
import json
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).parent

# Hand-counted per spec phrases (mirror K1 §"Empirical speed measurements")
PHRASE_COUNTS = {
    "p1": ("Nine one one, where is your emergency?", 6, 10),
    "p2": ("What's your location?", 3, 5),
    "p3": ("Are they breathing?", 3, 4),
    "p4": ("Stay with me.", 3, 3),
    "p5": ("Help is on the way.", 5, 5),
}


def voiced_duration(wav_path: Path) -> tuple[float, float, int]:
    """Return (total_dur_s, voiced_dur_s, peak_abs)."""
    with wave.open(str(wav_path), "rb") as w:
        n = w.getnframes()
        sr = w.getframerate()
        frames = w.readframes(n)
    if n == 0:
        return 0.0, 0.0, 0
    samples = struct.unpack(f"<{n}h", frames)
    peak_abs = max(abs(s) for s in samples)
    if peak_abs == 0:
        return n / sr, 0.0, 0
    threshold = 0.05 * peak_abs
    # 10ms RMS frames
    win = max(1, sr // 100)
    voiced_count = 0
    total_frames = 0
    for i in range(0, n, win):
        chunk = samples[i:i + win]
        if not chunk:
            continue
        total_frames += 1
        # Mean abs amplitude as rough RMS proxy
        m = sum(abs(s) for s in chunk) / len(chunk)
        if m >= threshold:
            voiced_count += 1
    voiced_dur = voiced_count * win / sr
    return n / sr, voiced_dur, peak_abs


def main() -> None:
    with open(ROOT / "result.json") as f:
        bench = json.load(f)

    metrics = {"conditions": {}}
    for cond_name, cond_data in bench["conditions"].items():
        cm = {"tag": cond_data["tag"], "phrases": {}}
        for p_id, p_data in cond_data["phrases"].items():
            wav_path = ROOT / "audio" / cond_name / f"{p_id}.wav"
            if not wav_path.exists() or not p_data.get("ok"):
                cm["phrases"][p_id] = {**p_data, "ok": False, "skipped": True}
                continue
            total_dur, voiced_dur, peak = voiced_duration(wav_path)
            words, sylls = PHRASE_COUNTS[p_id][1], PHRASE_COUNTS[p_id][2]
            wpm = 60 * words / voiced_dur if voiced_dur > 0 else 0.0
            sps = sylls / voiced_dur if voiced_dur > 0 else 0.0
            cm["phrases"][p_id] = {
                "total_dur_s": round(total_dur, 3),
                "voiced_dur_s": round(voiced_dur, 3),
                "peak": peak,
                "wpm": round(wpm, 1),
                "sps": round(sps, 2),
                "words": words,
                "syllables": sylls,
                "ttfb_ms": p_data.get("ttfb_ms"),
                "total_ms": p_data.get("total_ms"),
                "audio_duration_ms": p_data.get("duration_ms"),
                "text_sent": p_data.get("text_sent"),
                "ok": True,
            }
        # Per-condition aggregates
        ok_phrases = [p for p in cm["phrases"].values() if p.get("ok")]
        if ok_phrases:
            cm["mean_wpm"] = round(sum(p["wpm"] for p in ok_phrases) / len(ok_phrases), 1)
            cm["mean_sps"] = round(sum(p["sps"] for p in ok_phrases) / len(ok_phrases), 2)
            cm["mean_ttfb_ms"] = int(sum(p["ttfb_ms"] for p in ok_phrases) / len(ok_phrases))
            cm["mean_total_ms"] = int(sum(p["total_ms"] for p in ok_phrases) / len(ok_phrases))
            cm["min_peak"] = min(p["peak"] for p in ok_phrases)
            cm["all_5_succeeded"] = len(ok_phrases) == 5
            # P1-specific (the slow phrase per K1)
            p1 = cm["phrases"].get("p1")
            if p1 and p1.get("ok"):
                cm["p1_wpm"] = p1["wpm"]
                cm["p1_sps"] = p1["sps"]
        metrics["conditions"][cond_name] = cm

    with open(ROOT / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    # Summary table
    print(f"\n{'condition':<10} {'tag':<28} {'mean_wpm':>9} {'mean_sps':>9} {'p1_wpm':>8} {'p1_sps':>7} {'min_peak':>9} {'5/5':>4}")
    print("-" * 100)
    for cn in ["baseline", "T1", "T2", "T3", "T4", "T5"]:
        c = metrics["conditions"].get(cn, {})
        print(
            f"{cn:<10} {c.get('tag', ''):<28} "
            f"{c.get('mean_wpm', '-'):>9} "
            f"{c.get('mean_sps', '-'):>9} "
            f"{c.get('p1_wpm', '-'):>8} "
            f"{c.get('p1_sps', '-'):>7} "
            f"{c.get('min_peak', '-'):>9} "
            f"{'YES' if c.get('all_5_succeeded') else 'NO':>4}"
        )

    # Per-phrase wpm grid (for picking the winner)
    print(f"\nP1-specific wpm (target = 175-200 wpm dispatcher pace):")
    for cn in ["baseline", "T1", "T2", "T3", "T4", "T5"]:
        c = metrics["conditions"].get(cn, {})
        print(f"  {cn:<10} {c.get('p1_wpm', '-')} wpm")


if __name__ == "__main__":
    main()
