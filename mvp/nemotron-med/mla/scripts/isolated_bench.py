"""Clean-run orchestrator. Spawns scripts/_bench_worker.py per
(subject, config, replicate), pins GPU clocks, aggregates JSONL.

Produces two artifacts:
    results/logs/isolated_bench_YYYYMMDD_HHMMSS.jsonl  -- one row per worker run
    results/logs/isolated_bench_YYYYMMDD_HHMMSS.md     -- human-readable summary

Rubric this harness enforces:
    - Fresh subprocess per run -> no CUDA allocator / dynamo cache leak across subjects
    - GPU clock locked at session start, reset at session end (best-effort; silently
      skipped if nvidia-smi -lgc is not permitted in this container)
    - Warmup 30 + 5-sample discard inside the worker
    - Triplicate per config; stdev/mean reported across the 3 medians
    - Full distribution (p10/p50/p90/p99/max/mean/stdev/n) per run
    - Compile / build time separate from steady-state
    - GPU uuid, driver, clocks, torch / flashinfer versions recorded per row
    - Config grid: batch x kv_len x dtype, user-specified

Designed to be slow and boring. Any "N.NNx beats X" claim derived from this output
can be traced to an exact subprocess invocation.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Grid:
    subjects: list[str]
    batches: list[int]
    kv_lens: list[int]
    dtypes: list[str]
    replicates: int

    def iter_points(self):
        for subj, b, k, d in itertools.product(self.subjects, self.batches, self.kv_lens, self.dtypes):
            for rep in range(1, self.replicates + 1):
                yield subj, b, k, d, rep


def _try_lock_clocks(verbose: bool = True) -> dict:
    """Attempt to lock GPU SM clocks at max. Returns status dict.
    Skips silently if unavailable (e.g., non-privileged container)."""
    info: dict = {"locked": False}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=clocks.max.sm", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            info["lock_skipped_reason"] = "query clocks.max.sm failed"
            return info
        max_sm = int(r.stdout.strip().split("\n")[0])
        info["max_sm_mhz"] = max_sm
        lr = subprocess.run(
            ["nvidia-smi", "-lgc", f"{max_sm},{max_sm}"],
            capture_output=True, text=True, timeout=5,
        )
        if lr.returncode == 0:
            info["locked"] = True
            info["lock_output"] = lr.stdout.strip()[:200]
            if verbose:
                print(f"[clock-lock] SM locked at {max_sm} MHz")
        else:
            info["lock_skipped_reason"] = lr.stderr.strip()[:200]
            if verbose:
                print(f"[clock-lock] could not lock: {lr.stderr.strip()[:120]}")
    except Exception as e:
        info["lock_skipped_reason"] = f"{type(e).__name__}: {e}"
    return info


def _try_reset_clocks() -> None:
    try:
        subprocess.run(["nvidia-smi", "-rgc"], capture_output=True, timeout=5)
    except Exception:
        pass


def _git_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def run_one(worker: Path, subject: str, batch: int, kv_len: int, dtype: str,
            replicate: int, candidates_json: str | None,
            warmup: int, iters: int) -> dict:
    """Spawn one worker subprocess. Returns the parsed JSON (or an error record)."""
    cmd = [
        sys.executable, str(worker),
        "--subject", subject,
        "--batch", str(batch),
        "--kv-len", str(kv_len),
        "--dtype", dtype,
        "--replicate", str(replicate),
        "--seed", "0",
        "--warmup", str(warmup),
        "--iters", str(iters),
    ]
    if candidates_json:
        cmd += ["--candidates-json", candidates_json]
    env = dict(os.environ)
    # Each subprocess gets its own torchinductor cache dir, else they share.
    # We want shared cache (saves autotune time) so we leave TORCHINDUCTOR_CACHE_DIR.
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return {
            "status": "orchestrator_timeout", "subject": subject,
            "config": {"batch": batch, "kv_len": kv_len, "dtype": dtype},
            "replicate": replicate, "wall_s": time.perf_counter() - t0,
        }
    wall_s = time.perf_counter() - t0
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        row = json.loads(last) if last else {}
    except json.JSONDecodeError:
        row = {}
    # Fold orchestrator metadata.
    row.setdefault("status", "no_json")
    row["orchestrator_wall_s"] = wall_s
    row["proc_returncode"] = proc.returncode
    if proc.returncode != 0 and not row.get("error"):
        row["error"] = (proc.stderr.strip()[-500:] or f"exit={proc.returncode}")
    return row


def aggregate(rows: list[dict]) -> list[dict]:
    """Group by (subject, batch, kv_len, dtype) and compute summary stats
    across replicates. Report mean, stdev, min, max across the p50 of each
    successful replicate."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        cfg = r.get("config") or {}
        key = (r.get("subject"), cfg.get("batch"), cfg.get("kv_len"), cfg.get("dtype"))
        groups.setdefault(key, []).append(r)
    summary: list[dict] = []
    for (subj, b, k, d), group in groups.items():
        ok = [g for g in group if g.get("status") == "ok" and g.get("warm")]
        n_ok = len(ok)
        n_total = len(group)
        p50s = [g["warm"]["p50_ns"] for g in ok]
        compiles = [g.get("compile_s", 0.0) for g in ok]
        builds = [g.get("build_s", 0.0) for g in ok]
        summary.append({
            "subject": subj, "batch": b, "kv_len": k, "dtype": d,
            "replicates_ok": n_ok, "replicates_total": n_total,
            "p50_mean_ns": statistics.fmean(p50s) if p50s else None,
            "p50_stdev_ns": statistics.stdev(p50s) if len(p50s) > 1 else 0.0,
            "p50_min_ns": min(p50s) if p50s else None,
            "p50_max_ns": max(p50s) if p50s else None,
            "compile_s_mean": statistics.fmean(compiles) if compiles else None,
            "build_s_mean": statistics.fmean(builds) if builds else None,
            "cold_ns_mean": (statistics.fmean([g.get("cold_ns", 0) for g in ok]) if ok else None),
            "max_abs_error": max((g.get("max_abs_error") or 0.0 for g in ok), default=None),
            "errors": [g.get("error") for g in group if g.get("status") != "ok"],
        })
    # Stable sort: flashinfer first, then baselines, then claude.
    def sort_key(s):
        subj = s["subject"]
        prio = 0 if subj == "flashinfer" else (1 if subj.startswith("baseline") else 2)
        return (s["batch"], s["kv_len"], s["dtype"], prio, subj)
    summary.sort(key=sort_key)
    return summary


def format_markdown(summary: list[dict], grid: Grid, session_meta: dict) -> str:
    lines = [
        "# Isolated-bench run",
        "",
        f"- session_id: `{session_meta['session_id']}`",
        f"- git_sha: `{session_meta['git_sha']}`",
        f"- grid: subjects={grid.subjects} batch={grid.batches} kv_len={grid.kv_lens} dtype={grid.dtypes} replicates={grid.replicates}",
        f"- clock_lock: {session_meta['clock_lock']}",
        f"- warmup={session_meta['warmup']}  iters={session_meta['iters']}",
        f"- start={session_meta['ts_start']}  end={session_meta['ts_end']}",
        "",
        "## Results (p50 median, mean ± stdev across replicates)",
        "",
        "| subject | B | kv_len | dtype | reps | p50 µs (mean) | ± stdev | min..max | compile s | cold µs | max_err | errors |",
        "|:---|---:|---:|:---|:---:|---:|---:|---:|---:|---:|---:|:---|",
    ]
    for s in summary:
        if s["p50_mean_ns"] is None:
            row = (f"| {s['subject']} | {s['batch']} | {s['kv_len']} | {s['dtype']} "
                   f"| {s['replicates_ok']}/{s['replicates_total']} | — | — | — | — | — | — | "
                   f"{(s['errors'] or ['?'])[0][:60] if s['errors'] else ''} |")
        else:
            row = (f"| {s['subject']} | {s['batch']} | {s['kv_len']} | {s['dtype']} "
                   f"| {s['replicates_ok']}/{s['replicates_total']} "
                   f"| {s['p50_mean_ns']/1000:.2f} "
                   f"| {s['p50_stdev_ns']/1000:.2f} "
                   f"| {s['p50_min_ns']/1000:.2f}..{s['p50_max_ns']/1000:.2f} "
                   f"| {(s['compile_s_mean'] or 0):.1f} "
                   f"| {(s['cold_ns_mean'] or 0)/1000:.1f} "
                   f"| {(s['max_abs_error'] or 0):.2e} "
                   f"| {('yes' if s['errors'] else '')} |")
        lines.append(row)
    lines += ["", "## Per-config ratios vs flashinfer", ""]
    # For each config, compute ratio of each subject to flashinfer.
    configs = sorted({(s["batch"], s["kv_len"], s["dtype"]) for s in summary})
    for (b, k, d) in configs:
        fi = next((s for s in summary if s["subject"] == "flashinfer"
                   and s["batch"] == b and s["kv_len"] == k and s["dtype"] == d), None)
        if not fi or fi["p50_mean_ns"] is None:
            continue
        fi_ref = fi["p50_mean_ns"]
        lines.append(f"**B={b}  kv_len={k}  dtype={d}** -- flashinfer p50 mean = {fi_ref/1000:.2f} µs")
        for s in [ss for ss in summary if ss["batch"] == b and ss["kv_len"] == k and ss["dtype"] == d]:
            if s["p50_mean_ns"] is None or s["subject"] == "flashinfer":
                continue
            ratio = s["p50_mean_ns"] / fi_ref
            rel_stdev = (s["p50_stdev_ns"] / s["p50_mean_ns"]) if s["p50_mean_ns"] else 0.0
            quality = " (HIGH variance >5%)" if rel_stdev > 0.05 else ""
            lines.append(f"  - {s['subject']}: {ratio:.2f}x flashinfer{quality}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Isolated, clean-run MLA benchmark orchestrator.")
    ap.add_argument("--subjects", nargs="+", required=True,
                    help="e.g. flashinfer baseline_eager baseline_compiled claude:1 claude:3")
    ap.add_argument("--batches", type=int, nargs="+", default=[1])
    ap.add_argument("--kv-lens", type=int, nargs="+", default=[1024])
    ap.add_argument("--dtypes", nargs="+", default=["bfloat16"])
    ap.add_argument("--replicates", type=int, default=9,
                    help="n>=9 per Rubric v1.1 §1.4. Set <9 only for cheap smoke, not claim-grade.")
    ap.add_argument("--candidates-json", default=None)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--out-dir", default=None,
                    help="output dir (default: results/logs/)")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    worker = root / "scripts" / "_bench_worker.py"
    out_dir = Path(args.out_dir) if args.out_dir else (root / "results" / "logs")
    out_dir.mkdir(parents=True, exist_ok=True)

    session_id = time.strftime("%Y%m%d_%H%M%S")
    jsonl_path = out_dir / f"isolated_bench_{session_id}.jsonl"
    md_path = out_dir / f"isolated_bench_{session_id}.md"

    grid = Grid(
        subjects=args.subjects, batches=args.batches,
        kv_lens=args.kv_lens, dtypes=args.dtypes,
        replicates=args.replicates,
    )

    # Clock lock (best-effort).
    clock_info = _try_lock_clocks()
    ts_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    session_meta = {
        "session_id": session_id,
        "git_sha": _git_sha(),
        "clock_lock": clock_info,
        "warmup": args.warmup,
        "iters": args.iters,
        "ts_start": ts_start,
    }

    total = (len(args.subjects) * len(args.batches) * len(args.kv_lens)
             * len(args.dtypes) * args.replicates)
    print(f"[plan] {total} runs across subjects={args.subjects}  "
          f"B={args.batches}  kv_len={args.kv_lens}  dtype={args.dtypes}  reps={args.replicates}")
    print(f"[log]  {jsonl_path}")

    rows: list[dict] = []
    try:
        with jsonl_path.open("w") as f:
            for i, (subj, b, k, d, rep) in enumerate(grid.iter_points(), 1):
                t0 = time.perf_counter()
                row = run_one(
                    worker, subj, b, k, d, rep,
                    candidates_json=args.candidates_json,
                    warmup=args.warmup, iters=args.iters,
                )
                row["session_id"] = session_id
                f.write(json.dumps(row, default=str) + "\n")
                f.flush()
                rows.append(row)
                st = row.get("status", "?")
                pmed = (row.get("warm") or {}).get("p50_ns")
                msg = f"p50={pmed/1000:.1f}us" if pmed else row.get("error", "")[:80]
                print(f"  [{i:>3d}/{total}] {subj:<22s} B={b} k={k:>5d} d={d} r={rep} "
                      f"wall={time.perf_counter()-t0:5.1f}s  {st}  {msg}")
    finally:
        _try_reset_clocks()

    session_meta["ts_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = aggregate(rows)
    md = format_markdown(summary, grid, session_meta)
    md_path.write_text(md)
    # Also write the aggregate as JSON.
    (out_dir / f"isolated_bench_{session_id}_summary.json").write_text(
        json.dumps({"meta": session_meta, "summary": summary}, default=str, indent=2))
    print(f"\n[done] wrote {md_path}")
    print(f"       and   {out_dir / f'isolated_bench_{session_id}_summary.json'}")
    print(f"       rows: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
