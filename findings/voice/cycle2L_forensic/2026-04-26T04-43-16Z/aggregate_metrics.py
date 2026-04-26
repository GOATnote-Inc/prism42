#!/usr/bin/env python3
"""Aggregate cycle-2L 4-condition metrics into result.json + summary.md."""
import json
import os
import statistics
from pathlib import Path

ART = Path(__file__).resolve().parent
COND_LABELS = {
    "A": ("A_baseline", "psap baseline (no levers)"),
    "B": ("B_psap_fast", "psap-fast preset (Lever A)"),
    "C": ("C_psap_commafix", "psap + comma-to-period (Lever B)"),
    "D": ("D_psap_fast_commafix", "psap-fast + comma-to-period (Lever A+B)"),
}


def percentile(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def load_cond(cond):
    path = ART / f"metrics_{cond}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def main():
    out = {
        "cycle": "2L",
        "purpose": "test psap-fast preset (Lever A) and comma-to-period adapter (Lever B) — alone and combined",
        "phrases": [
            "Nine one one, where is your emergency?",
            "What's your location?",
            "Are they breathing?",
            "Stay with me.",
            "Help is on the way.",
        ],
        "conditions": {},
    }
    table = []
    for cond, (label, desc) in COND_LABELS.items():
        d = load_cond(cond)
        if not d:
            continue
        phrases = d["phrases"]
        ttfbs = [p["ttfb_ms"] for p in phrases if p.get("success")]
        durations = [p["duration_s"] for p in phrases if p.get("success")]
        wpms = [p["wpm_proxy"] for p in phrases if p.get("success") and p.get("wpm_proxy")]
        n_ok = sum(1 for p in phrases if p.get("success"))
        n_total = len(phrases)
        # Per-phrase wpm
        per_phrase_wpm = {}
        for p in phrases:
            if p.get("success"):
                per_phrase_wpm[f"P{p['index']}"] = round(p["wpm_proxy"], 1)
        out["conditions"][cond] = {
            "label": label,
            "description": desc,
            "reference_id": d["reference_id"],
            "pace_tag": d["pace_tag"],
            "comma_to_period": d["comma_to_period"],
            "success_rate": f"{n_ok}/{n_total}",
            "ttfb_p50_ms": round(statistics.median(ttfbs), 2) if ttfbs else None,
            "ttfb_p95_ms": round(percentile(ttfbs, 95), 2) if ttfbs else None,
            "ttfb_max_ms": round(max(ttfbs), 2) if ttfbs else None,
            "total_render_p50_ms": round(statistics.median([p["total_ms"] for p in phrases if p.get("success")]), 2),
            "audio_duration_p50_s": round(statistics.median(durations), 3) if durations else None,
            "wpm_p50": round(statistics.median(wpms), 1) if wpms else None,
            "wpm_p1": per_phrase_wpm.get("P1"),
            "wpm_p5": per_phrase_wpm.get("P5"),
            "per_phrase_wpm": per_phrase_wpm,
            "audio_band_min_max_s": [round(min(durations), 3), round(max(durations), 3)] if durations else None,
        }
        table.append(cond)
    # Decision: highest wpm on P1 (slowest phrase) without breaking 5/5 success
    p1_wpms = {c: out["conditions"][c]["wpm_p1"] for c in table if out["conditions"][c]["success_rate"] == "5/5"}
    if not p1_wpms:
        decision = "INCONCLUSIVE_ALL_FAIL"
        winner = None
    else:
        winner = max(p1_wpms, key=lambda c: p1_wpms[c])
        # Check if it actually beats baseline by >=10 wpm (call it INCONCLUSIVE if no real lift)
        baseline_p1 = p1_wpms.get("A", 0)
        winner_p1 = p1_wpms[winner]
        if winner == "A" or (winner_p1 - baseline_p1) < 10:
            decision = f"INCONCLUSIVE_NO_LIFT (winner={winner} wpm={winner_p1:.1f} vs A={baseline_p1:.1f})"
        else:
            decision = f"PICK_{winner} (P1 wpm={winner_p1:.1f} vs A={baseline_p1:.1f}, lift={winner_p1 - baseline_p1:.1f})"
    out["decision"] = decision
    out["winner"] = winner
    out["rollback_instructions"] = [
        "1. (No drop-ins were applied to worker — bench was direct-to-Fish HTTP.)",
        "2. (If drop-ins were ever added) sudo rm /etc/systemd/system/prism42-worker.service.d/{80-cycle2L-refid,81-cycle2L-comma}.conf",
        "3. sudo systemctl daemon-reload && sudo systemctl restart prism42-worker",
        "4. sudo cp /opt/prism42/agents/livekit/fish_speech_tts.py.pre-cycle2L /opt/prism42/agents/livekit/fish_speech_tts.py",
        "5. sudo systemctl restart prism42-worker (only needed if Lever B was activated via env-var)",
        "6. Verify: curl -sf http://localhost:9200/v1/health && systemctl is-active prism42-worker",
    ]

    with open(ART / "result.json", "w") as f:
        json.dump(out, f, indent=2)

    # Per-phrase metrics file
    metrics = {
        cond: load_cond(cond) for cond in table
    }
    with open(ART / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    # Summary table
    lines = []
    lines.append("# Cycle-2L lever test — psap-fast preset and comma-to-period adapter\n")
    lines.append(f"**UTC:** {ART.name}  ")
    lines.append("**Method:** Direct-to-Fish HTTP synth bench (bypasses worker.py / LiveKit room flow). 4 conditions × 5 phrases = 20 audio files. Same seed (911), same chunk_length (200), same temp (0.1).\n")
    lines.append("## Results\n")
    lines.append("```")
    header = f"{'metric':<32}"
    for c in table:
        lab = COND_LABELS[c][0].replace('_', ' ')
        header += f" {lab:<22}"
    lines.append(header)
    rows = [
        ("real synth success",       lambda c: out["conditions"][c]["success_rate"]),
        ("TTFB p50 (ms)",            lambda c: f"{out['conditions'][c]['ttfb_p50_ms']:.2f}"),
        ("TTFB p95 (ms)",            lambda c: f"{out['conditions'][c]['ttfb_p95_ms']:.2f}"),
        ("TTFB max (ms)",            lambda c: f"{out['conditions'][c]['ttfb_max_ms']:.2f}"),
        ("total render p50 (ms)",    lambda c: f"{out['conditions'][c]['total_render_p50_ms']:.1f}"),
        ("audio duration p50 (s)",   lambda c: f"{out['conditions'][c]['audio_duration_p50_s']:.3f}"),
        ("median wpm across 5",      lambda c: f"{out['conditions'][c]['wpm_p50']:.1f}"),
        ("P1 wpm (slowest phrase)",  lambda c: f"{out['conditions'][c]['wpm_p1']:.1f}"),
        ("P5 wpm (the user's good)", lambda c: f"{out['conditions'][c]['wpm_p5']:.1f}"),
        ("audio peak band (s)",      lambda c: f"{out['conditions'][c]['audio_band_min_max_s'][0]:.2f}-{out['conditions'][c]['audio_band_min_max_s'][1]:.2f}"),
    ]
    for label, fn in rows:
        row = f"{label:<32}"
        for c in table:
            try:
                row += f" {fn(c):<22}"
            except Exception:
                row += f" {'ERR':<22}"
        lines.append(row)
    # Per-phrase wpm matrix
    lines.append("")
    lines.append(f"{'phrase':<32}" + "".join(f" {COND_LABELS[c][0]:<22}" for c in table))
    for i in range(1, 6):
        key = f"P{i}"
        row = f"{key + ' ' + repr(out['phrases'][i-1])[:22]:<32}"
        for c in table:
            v = out["conditions"][c]["per_phrase_wpm"].get(key, "ERR")
            row += f" {str(v):<22}"
        lines.append(row)
    lines.append("```\n")
    lines.append(f"## Decision\n\n**{out['decision']}**\n")
    # Lever-attribution paragraph
    a, b, c_, d_ = (out["conditions"].get(x, {}) for x in "ABCD")
    if a and b and c_ and d_:
        b_minus_a = b["wpm_p50"] - a["wpm_p50"]
        c_minus_a = c_["wpm_p50"] - a["wpm_p50"]
        d_minus_a = d_["wpm_p50"] - a["wpm_p50"]
        lines.append("## Lever attribution (median wpm vs baseline A)\n")
        lines.append(f"- **Lever A (psap-fast preset alone, B-A):** {b_minus_a:+.1f} wpm")
        lines.append(f"- **Lever B (comma-to-period alone, C-A):** {c_minus_a:+.1f} wpm")
        lines.append(f"- **A+B combined (D-A):** {d_minus_a:+.1f} wpm\n")
        b_minus_a_p1 = b["wpm_p1"] - a["wpm_p1"]
        c_minus_a_p1 = c_["wpm_p1"] - a["wpm_p1"]
        d_minus_a_p1 = d_["wpm_p1"] - a["wpm_p1"]
        lines.append("## Lever attribution on P1 (the slowest comma-bearing phrase, vs baseline A)\n")
        lines.append(f"- **Lever A (psap-fast preset alone):** {b_minus_a_p1:+.1f} wpm")
        lines.append(f"- **Lever B (comma-to-period alone):** {c_minus_a_p1:+.1f} wpm")
        lines.append(f"- **A+B combined:** {d_minus_a_p1:+.1f} wpm\n")

    lines.append("## Rollback (60–90s)\n")
    for r in out["rollback_instructions"]:
        lines.append(r)
    lines.append("")
    lines.append("## Files\n")
    lines.append("- `result.json` — 4-condition aggregate")
    lines.append("- `metrics.json` — per-phrase raw metrics")
    lines.append("- `metrics_{A,B,C,D}.json` — per-condition raw")
    lines.append("- `audio/{A_baseline,B_psap_fast,C_psap_commafix,D_psap_fast_commafix}/p{1..5}.wav` — 20 audio files")
    lines.append("- `psap_fast_reference.wav` — the new preset audio")
    lines.append("- `setup_psap_fast_reference.sh` — idempotent regen script")
    lines.append("- `patch.applied.diff` — adapter diff (Lever B)")
    lines.append("- `logs/{worker,fish}.log` — service logs at bench time")

    with open(ART / "summary.md", "w") as f:
        f.write("\n".join(lines))
    # decision.txt
    with open(ART / "decision.txt", "w") as f:
        f.write(out["decision"] + "\n")
    print("ART:", ART)
    print("DECISION:", out["decision"])


if __name__ == "__main__":
    main()
