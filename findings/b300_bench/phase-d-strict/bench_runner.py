#!/usr/bin/env python3
"""Phase D-5 latency benchmark: 5 warmup + 20 measured prompts, streaming TTFT."""
import urllib.request
import json
import time
import statistics
import sys

WARMUP_PROMPTS = [
    "911 what is your emergency",
    "Address please",
    "Is the person breathing",
    "How old is the patient",
    "Are you in danger right now",
]

MEASURE_PROMPTS = [
    "Stay on the line with me",
    "Tell me what happened",
    "Is anyone hurt",
    "Where are you calling from",
    "Is the door locked",
    "What's the cross street",
    "Can you describe the suspect",
    "Is there a weapon involved",
    "How many people are there",
    "What color is the vehicle",
    "Is the bleeding heavy",
    "Are you safe to talk",
    "What's the apartment number",
    "Did you see what happened",
    "Are they conscious",
    "911 what is your emergency",
    "Address please",
    "Is the person breathing",
    "How old is the patient",
    "Are you in danger right now",
]

assert len(MEASURE_PROMPTS) == 20, f"Expected 20 measure prompts, got {len(MEASURE_PROMPTS)}"

URL = "http://127.0.0.1:8001/v1/chat/completions"


def run_prompt(prompt: str, label: str) -> dict:
    body = json.dumps({
        "model": "nemotron-nano",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 24,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    ttft = None
    tok_count = 0
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            for raw_line in r:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith(b"data:"):
                    payload = line[5:].strip()
                    if payload == b"[DONE]":
                        break
                    if ttft is None:
                        ttft = (time.monotonic() - t0) * 1000
                    tok_count += 1
        total_ms = (time.monotonic() - t0) * 1000
    except Exception as e:
        return {"label": label, "prompt": prompt, "error": str(e),
                "ttft_ms": None, "total_ms": None, "tokens": 0, "toks_per_sec": None}

    toks_per_sec = (tok_count / total_ms * 1000) if total_ms > 0 else None
    return {
        "label": label,
        "prompt": prompt,
        "ttft_ms": round(ttft, 2) if ttft is not None else None,
        "total_ms": round(total_ms, 2),
        "tokens": tok_count,
        "toks_per_sec": round(toks_per_sec, 2) if toks_per_sec else None,
    }


def percentile(data, p):
    data = sorted(data)
    k = (len(data) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(data) - 1)
    return data[f] + (data[c] - data[f]) * (k - f)


def main():
    results = {"warmup": [], "measured": [], "summary": {}}

    print("=== WARMUP (5 prompts, discarded) ===", flush=True)
    for i, p in enumerate(WARMUP_PROMPTS):
        r = run_prompt(p, f"warmup_{i+1}")
        results["warmup"].append(r)
        print(f"  warmup {i+1}: ttft={r['ttft_ms']} ms  total={r['total_ms']} ms  toks={r['tokens']}", flush=True)

    print("\n=== MEASURED (20 prompts) ===", flush=True)
    for i, p in enumerate(MEASURE_PROMPTS):
        r = run_prompt(p, f"sample_{i+1}")
        results["measured"].append(r)
        print(f"  sample {i+1:2d}: ttft={r['ttft_ms']} ms  total={r['total_ms']} ms  toks={r['tokens']}  tok/s={r['toks_per_sec']}", flush=True)

    # Aggregate over measured samples
    ttfts = [r["ttft_ms"] for r in results["measured"] if r["ttft_ms"] is not None]
    totals = [r["total_ms"] for r in results["measured"] if r["total_ms"] is not None]
    tps_list = [r["toks_per_sec"] for r in results["measured"] if r["toks_per_sec"] is not None]

    # JIT penalty: sample_1 vs warmed median (samples 6-20, i.e. index 5-19)
    sample1_ttft = results["measured"][0]["ttft_ms"]
    warmed_ttfts = [r["ttft_ms"] for r in results["measured"][5:] if r["ttft_ms"] is not None]
    warmed_median_ttft = statistics.median(warmed_ttfts) if warmed_ttfts else None
    jit_penalty_ms = round(sample1_ttft - warmed_median_ttft, 2) if (sample1_ttft and warmed_median_ttft) else None

    summary = {
        "ttft_p50_ms": round(percentile(ttfts, 50), 2) if ttfts else None,
        "ttft_p95_ms": round(percentile(ttfts, 95), 2) if ttfts else None,
        "ttft_max_ms": round(max(ttfts), 2) if ttfts else None,
        "total_p50_ms": round(percentile(totals, 50), 2) if totals else None,
        "total_p95_ms": round(percentile(totals, 95), 2) if totals else None,
        "total_max_ms": round(max(totals), 2) if totals else None,
        "toks_per_sec_p50": round(percentile(tps_list, 50), 2) if tps_list else None,
        "jit_penalty_ms": jit_penalty_ms,
        "sample1_ttft_ms": sample1_ttft,
        "warmed_median_ttft_ms": round(warmed_median_ttft, 2) if warmed_median_ttft else None,
        "n_measured": len(results["measured"]),
        "n_errors": sum(1 for r in results["measured"] if r.get("error")),
    }
    results["summary"] = summary

    print("\n=== SUMMARY ===", flush=True)
    for k, v in summary.items():
        print(f"  {k}: {v}", flush=True)

    out_path = "/tmp/prism42-bench.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}", flush=True)
    return results


if __name__ == "__main__":
    main()
