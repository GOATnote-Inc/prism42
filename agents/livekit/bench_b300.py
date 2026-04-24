"""B300 voice-pipeline latency bench — wraps synthetic_caller_full.py.

Runs N back-to-back synthetic turns against the live prism42-worker on the pod,
extracts per-hop timings from the worker's structlog output, and emits a JSON
summary with mean / median / p95 / p99 per hop.

Run on the pod (where `/tmp/prism42-logs/worker.log` and `127.0.0.1:9200` are
reachable):
    cd /opt/prism42/agents/livekit
    .venv/bin/python bench_b300.py --n 10

Output:
    /opt/prism42/agents/livekit/findings/b300_bench/<UTC>.json
    stdout: human-readable table

Hops measured:
    t_stt_ms         transcript_delay reported by the LiveKit STT node
                     (utterance-end → transcript available; includes VAD tail)
    t_fish_ttfb_ms   Fish Speech time-to-first-byte (POST → first HTTP chunk)
                     — this dominates TTS and is the hop Team α is working.
    t_fish_total_ms  Fish Speech full synthesis time (POST → final byte)
    t_reply_e2e_ms   synthetic caller's reply_latency_after_pubend — the
                     ground-truth end-to-end (caller-pub-end → first audible
                     reply frame).  Includes STT + LLM + TTS TTFB + RTP hop.
    t_llm_ms         (OPTIONAL, filled if Team β wired it) LLM first-token
                     latency.  Proxy: t_reply_e2e_ms - t_stt_ms - t_fish_ttfb_ms
                     when direct measurement absent.

We correlate each caller run to its worker-log window by tailing the log
before and after the subprocess returns, then scanning the delta for the
latest fishspeech.* + user_transcript triple.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKER_LOG = Path(os.environ.get("PRISM42_WORKER_LOG", "/tmp/prism42-logs/worker.log"))
FINDINGS_DIR = Path(__file__).resolve().parent / "findings" / "b300_bench"
DEFAULT_UTTERANCE = "I have chest pain and shortness of breath."

RE_REPLY = re.compile(r"reply_latency_after_pubend:\s*\+([0-9.]+)s")
RE_FISH_T0 = re.compile(
    r"fishspeech\.t0\s+chunk_length=(\d+)\s+text_len=(\d+)"
)
RE_FISH_TTFB = re.compile(
    r"fishspeech\.t_first_byte\s+ms_since_post=(\d+)\s+ms_since_t0=(\d+)"
)
RE_FISH_DONE = re.compile(
    r"fishspeech\.done\s+audio_duration_ms=(\d+)\s+total_bytes=(\d+)\s+total_ms=(\d+)"
)
# user_transcript lines are structlog-formatted; transcript_delay is on the same line.
RE_USER_TX = re.compile(
    r'received user transcript.*?"transcript_delay":\s*([0-9.]+)',
    re.DOTALL,
)
# Team β optional lines — tolerate absence.
RE_LLM_MS = re.compile(r"llm\.(?:first_token|done).*?(?:ms|t_first_token)=(\d+)")
RE_TTS_MS = re.compile(r"tts\.(?:first_byte|done).*?ms=(\d+)")


def read_log_offset() -> int:
    try:
        return WORKER_LOG.stat().st_size
    except FileNotFoundError:
        return 0


def read_log_window(start_offset: int) -> str:
    try:
        size = WORKER_LOG.stat().st_size
    except FileNotFoundError:
        return ""
    if size <= start_offset:
        return ""
    with WORKER_LOG.open("rb") as f:
        f.seek(start_offset)
        return f.read().decode("utf-8", errors="replace")


def parse_window(window: str) -> dict:
    """Extract per-hop timings for the REPLY TTS that follows the final
    user_transcript in the window.

    Parsing model:
      1. Find the last `user_transcript` line — that marks the caller's end-
         of-utterance after the bench's publish.
      2. Scope all fishspeech.* matching to the substring *after* that line.
         This excludes pre-roll TTS and prior-turn TTS from prior runs.
      3. The very first `fishspeech.t_first_byte` in the post-transcript
         region is the true TTFB of the reply.  Subsequent `t_first_byte`
         events are mid-stream chunk heads (near-zero ms_since_post) and
         must not be used.
      4. The first `fishspeech.done` in the post-transcript region is the
         reply TTS total-synthesis time.
    """
    out: dict[str, float | None] = {
        "t_stt_ms": None,
        "t_fish_ttfb_ms": None,
        "t_fish_total_ms": None,
        "t_llm_ms": None,
    }

    # STT: last user_transcript's transcript_delay (seconds -> ms).
    tx_matches = list(RE_USER_TX.finditer(window))
    if tx_matches:
        out["t_stt_ms"] = round(float(tx_matches[-1].group(1)) * 1000, 1)
        # Scope the remainder to after the last user_transcript line.
        reply_region = window[tx_matches[-1].end():]
    else:
        reply_region = window

    # Fish TTFB: FIRST t_first_byte in the reply region is the true TTFB.
    ttfb_match = RE_FISH_TTFB.search(reply_region)
    if ttfb_match:
        out["t_fish_ttfb_ms"] = float(ttfb_match.group(1))

    # Fish total: FIRST done in the reply region corresponds to this TTFB.
    done_match = RE_FISH_DONE.search(reply_region)
    if done_match:
        out["t_fish_total_ms"] = float(done_match.group(3))

    llm_match = RE_LLM_MS.search(reply_region)
    if llm_match:
        out["t_llm_ms"] = float(llm_match.group(1))

    return out


def fish_healthy(url: str = "http://127.0.0.1:9200") -> bool:
    """Return True iff Fish /v1/health returns {"status":"ok"} within 2s."""
    try:
        import urllib.request as _u
        with _u.urlopen(f"{url}/v1/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def wait_for_fish(timeout_s: float = 30.0) -> bool:
    """Poll Fish health until ok or timeout. Returns True on success."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if fish_healthy():
            return True
        time.sleep(2.0)
    return False


def run_one(utterance: str, run_idx: int, timeout_s: float = 90.0) -> dict:
    """Run synthetic_caller_full.py once, return one-row metrics."""
    # Gate on Fish health — synthetic_caller_full posts to Fish for caller audio
    # and has no retry.  If Fish is mid-startup or mid-crash-restart, we would
    # record a meaningless exit=1 ConnectError.  Wait up to 30s instead.
    if not fish_healthy():
        print(f"  [bench] fish unhealthy pre-run, waiting up to 30s ...")
        if not wait_for_fish(30.0):
            print(f"  [bench] fish still unhealthy, recording skipped run")
            return {
                "run_idx": run_idx,
                "utterance": utterance,
                "exit_code": -2,
                "wall_s": 0.0,
                "t_reply_e2e_ms": None,
                "t_stt_ms": None,
                "t_fish_ttfb_ms": None,
                "t_fish_total_ms": None,
                "t_llm_ms": None,
                "verdict_line": "SKIPPED (fish unhealthy)",
                "stderr_tail": "",
            }

    log_offset_before = read_log_offset()
    t_start = time.time()

    caller_py = Path(__file__).with_name("synthetic_caller_full.py")
    venv_py = Path(__file__).parent / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable

    proc = subprocess.run(
        [py, str(caller_py), utterance],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    t_end = time.time()

    stdout = proc.stdout
    stderr = proc.stderr

    reply_match = RE_REPLY.search(stdout)
    reply_ms: float | None = round(float(reply_match.group(1)) * 1000, 1) if reply_match else None

    # Give the worker 0.5s to flush any final log lines (fishspeech.done
    # may emit after the caller has already disconnected).
    time.sleep(0.5)
    window = read_log_window(log_offset_before)
    hops = parse_window(window)

    return {
        "run_idx": run_idx,
        "utterance": utterance,
        "exit_code": proc.returncode,
        "wall_s": round(t_end - t_start, 2),
        "t_reply_e2e_ms": reply_ms,
        **hops,
        "verdict_line": next(
            (ln for ln in stdout.splitlines() if ln.startswith("VERDICT")),
            "",
        ),
        "stderr_tail": stderr[-500:] if stderr else "",
    }


def agg(name: str, values: list[float]) -> dict:
    if not values:
        return {"hop": name, "n": 0, "mean": None, "median": None, "p95": None, "p99": None}
    s = sorted(values)

    def pct(p: float) -> float:
        if len(s) == 1:
            return s[0]
        k = (len(s) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    return {
        "hop": name,
        "n": len(values),
        "mean": round(statistics.fmean(values), 1),
        "median": round(statistics.median(values), 1),
        "p95": round(pct(0.95), 1),
        "p99": round(pct(0.99), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=10, help="number of back-to-back runs")
    ap.add_argument(
        "--sleep-s", type=float, default=7.0,
        help="sleep between runs so the worker settles (default 7s)",
    )
    ap.add_argument(
        "--utterance", type=str, default=DEFAULT_UTTERANCE,
        help="test utterance (Fish will synthesize it for each run)",
    )
    ap.add_argument(
        "--output", type=Path, default=None,
        help="override output JSON path",
    )
    args = ap.parse_args()

    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.output or (FINDINGS_DIR / f"{utc}.json")

    print(f"[bench] N={args.n} utterance={args.utterance!r}")
    print(f"[bench] worker_log={WORKER_LOG} (size={read_log_offset():,} B)")
    print(f"[bench] output={out_path}")
    print()

    runs: list[dict] = []
    for i in range(args.n):
        print(f"--- run {i + 1}/{args.n} ---")
        try:
            row = run_one(args.utterance, i)
        except subprocess.TimeoutExpired as e:
            print(f"[bench] run {i} timed out after {e.timeout}s")
            row = {
                "run_idx": i,
                "utterance": args.utterance,
                "exit_code": -1,
                "wall_s": e.timeout,
                "t_reply_e2e_ms": None,
                "t_stt_ms": None,
                "t_fish_ttfb_ms": None,
                "t_fish_total_ms": None,
                "t_llm_ms": None,
                "verdict_line": "TIMEOUT",
                "stderr_tail": "",
            }
        runs.append(row)
        print(
            f"  exit={row['exit_code']} "
            f"reply_e2e={row['t_reply_e2e_ms']}ms "
            f"stt={row['t_stt_ms']}ms "
            f"fish_ttfb={row['t_fish_ttfb_ms']}ms "
            f"fish_total={row['t_fish_total_ms']}ms"
        )
        print(f"  verdict: {row['verdict_line']}")
        if i < args.n - 1:
            time.sleep(args.sleep_s)

    def col(key: str) -> list[float]:
        return [r[key] for r in runs if r.get(key) is not None]

    # Proxy LLM latency = t_reply_e2e_ms - t_stt_ms - t_fish_ttfb_ms.  Only
    # defined when Team β has not shipped a direct t_llm_ms and all three
    # components are present.  Captures LLM gen-to-TTS-POST gap (the window
    # between STT return and Fish receiving the first text chunk).
    for r in runs:
        if r.get("t_llm_ms") is None and all(
            r.get(k) is not None for k in ("t_reply_e2e_ms", "t_stt_ms", "t_fish_ttfb_ms")
        ):
            r["t_llm_proxy_ms"] = round(
                r["t_reply_e2e_ms"] - r["t_stt_ms"] - r["t_fish_ttfb_ms"], 1
            )
        else:
            r["t_llm_proxy_ms"] = None

    summary = {
        "utc": utc,
        "n_runs": args.n,
        "n_pass": sum(1 for r in runs if r["exit_code"] == 0),
        "utterance": args.utterance,
        "hardware": "NVIDIA B300 SXM6 AC (sm_103)",
        "software": {
            "livekit_agents": "1.5.6",
            "livekit_plugins_anthropic": "1.5.6",
            "fish_speech": "S2-Pro (self-hosted, :9200)",
            "parakeet_stt": "TDT 0.6B v3 (self-hosted, :9100)",
            "llm": "claude-opus-4-7 (via livekit-plugins-anthropic)",
        },
        "worker_log": str(WORKER_LOG),
        "hop_aggregates": [
            agg("t_stt_ms", col("t_stt_ms")),
            agg("t_fish_ttfb_ms", col("t_fish_ttfb_ms")),
            agg("t_fish_total_ms", col("t_fish_total_ms")),
            agg("t_reply_e2e_ms", col("t_reply_e2e_ms")),
            agg("t_llm_ms", col("t_llm_ms")),
            agg("t_llm_proxy_ms", col("t_llm_proxy_ms")),
        ],
        "runs": runs,
    }

    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    print()
    print(f"[bench] wrote {out_path}")
    print()
    print(
        f"{'hop':<22}{'n':>4}{'mean':>10}{'median':>10}{'p95':>10}{'p99':>10}{'min':>10}{'max':>10}"
    )
    for row in summary["hop_aggregates"]:
        if row["n"] == 0:
            print(f"{row['hop']:<22}{0:>4}  (no samples)")
            continue
        print(
            f"{row['hop']:<22}"
            f"{row['n']:>4}"
            f"{row['mean']:>10.1f}"
            f"{row['median']:>10.1f}"
            f"{row['p95']:>10.1f}"
            f"{row['p99']:>10.1f}"
            f"{row['min']:>10.1f}"
            f"{row['max']:>10.1f}"
        )
    return 0 if summary["n_pass"] == args.n else 1


if __name__ == "__main__":
    sys.exit(main())
