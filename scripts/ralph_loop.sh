#!/usr/bin/env bash
# ralph_loop.sh — measure → bottleneck → log → suggest-lever → repeat.
#
# Karpathy-style outer loop for the B300 voice stack. One iteration:
#   1. Run bench_b300 on the pod (N samples).
#   2. scp the JSON summary back.
#   3. Append {ts,p50,p95,bottleneck} to ralph.jsonl.
#   4. Suggest the next lever from 16a-lever-registry.yaml.
#
# Non-destructive: only reads pod state + runs the bench. Never edits
# worker.py, never restarts services. The operator applies the
# suggested lever.
#
# Usage:
#   scripts/ralph_loop.sh                      # 1 iteration
#   scripts/ralph_loop.sh --iter 6             # 6 iterations (~12 min)
#   scripts/ralph_loop.sh --iter 3 --bench-n 5 # 5 samples per iter
#   scripts/ralph_loop.sh --dry-run            # parse last log, no bench
#
# Logs:
#   /tmp/prism42-ralph/ralph.jsonl   (append-only outcome log)
#   /tmp/prism42-ralph/latest.json   (raw bench summary, overwritten)

set -euo pipefail

POD="${PRISM42_POD_HOST:-b300-pod}"
BENCH_DIR="/opt/prism42/agents/livekit"
LOG_DIR="/tmp/prism42-ralph"
LOG_FILE="$LOG_DIR/ralph.jsonl"
LATEST="$LOG_DIR/latest.json"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="$REPO_ROOT/docs/livekit-kb/16a-lever-registry.yaml"
SLO_PATH="$REPO_ROOT/tests/voice/slo.yaml"

ITER=1
BENCH_N=3
BENCH_SLEEP=15
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --iter)       ITER="$2"; shift 2 ;;
    --bench-n)    BENCH_N="$2"; shift 2 ;;
    --sleep-s)    BENCH_SLEEP="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$LOG_DIR"

_log() { printf '[ralph %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

_run_bench() {
  _log "bench iter=$1/$ITER  n=$BENCH_N  sleep=${BENCH_SLEEP}s  pod=$POD"
  local stdout="$LOG_DIR/bench_stdout.$$.txt"
  ssh -o ConnectTimeout=10 "$POD" \
    "cd $BENCH_DIR && .venv/bin/python bench_b300.py --n $BENCH_N --sleep-s $BENCH_SLEEP" \
    >"$stdout" 2>&1
  local rc=$?
  tail -25 "$stdout"

  # Prefer the [bench] wrote PATH line printed by bench_b300; fall back
  # to listing the b300_bench output dir on the pod.
  local remote
  remote=$(grep -oE '\[bench\] wrote \S+\.json' "$stdout" | tail -1 | awk '{print $3}')
  if [[ -z "$remote" ]]; then
    remote=$(ssh "$POD" "ls -t $BENCH_DIR/findings/b300_bench/*.json 2>/dev/null | head -1")
  fi
  rm -f "$stdout"

  if [[ -z "$remote" ]]; then
    _log "FATAL: bench produced no JSON summary (rc=$rc)"
    return 1
  fi
  scp -q "$POD:$remote" "$LATEST"
}

_parse_and_log() {
  python3 - "$LATEST" "$LOG_FILE" "$SLO_PATH" "$REGISTRY" <<'PY'
import json, sys, time, pathlib

bench_path, log_path, slo_path, registry_path = map(pathlib.Path, sys.argv[1:5])

bench = json.loads(bench_path.read_text())
hops = {h["hop"]: h for h in bench.get("hop_aggregates", [])}

def g(hop, key):
    return (hops.get(hop) or {}).get(key)

e2e_p50 = g("t_reply_e2e_ms", "median")
e2e_p95 = g("t_reply_e2e_ms", "p95") or g("t_reply_e2e_ms", "max")

# Bottleneck = highest-median hop excluding the e2e rollup.
per_hop = {k: v for k, v in hops.items() if k != "t_reply_e2e_ms"}
bn = max(per_hop.values(), key=lambda h: (h.get("median") or 0), default={})

out = {
    "ts": int(time.time()),
    "n": bench.get("n") or len(bench.get("samples", [])),
    "p50": e2e_p50,
    "p95": e2e_p95,
    "bottleneck_hop": bn.get("hop"),
    "bottleneck_p50": bn.get("median"),
    "per_hop_p50": {k: h.get("median") for k, h in per_hop.items()},
}
with log_path.open("a") as f:
    f.write(json.dumps(out) + "\n")

# SLO badge
slo_badge = "?"
try:
    import yaml  # type: ignore
    slo = yaml.safe_load(slo_path.read_text())
    t = slo["latency"]["t_reply_e2e_ms"]
    p50_thr = t.get("p50_ms") or t.get("p50")
    p95_thr = t.get("p95_ms") or t.get("p95")
    if e2e_p50 is None:
        slo_badge = "NO-DATA"
    elif e2e_p50 <= p50_thr and (e2e_p95 or 0) <= p95_thr:
        slo_badge = "GREEN"
    elif e2e_p50 <= p50_thr * 1.2:
        slo_badge = "YELLOW"
    else:
        slo_badge = "RED"
except Exception:
    pass

# Suggestion pulled from lever registry (status=ready, lowest priority #)
suggestion = None
try:
    import yaml  # type: ignore
    reg = yaml.safe_load(registry_path.read_text()) or {}
    levers = reg.get("levers", [])
    ready = [l for l in levers if l.get("status") == "ready"]
    ready.sort(key=lambda l: (l.get("priority", 999), l.get("id", "")))
    if ready:
        l = ready[0]
        suggestion = f"#{l['id']} {l['title']} (owner={l.get('owner','?')})"
except Exception:
    pass

print(f"  p50={e2e_p50}  p95={e2e_p95}  bottleneck={out['bottleneck_hop']}@{out['bottleneck_p50']}ms  [{slo_badge}]")
if suggestion:
    print(f"  next lever: {suggestion}")
PY
}

if [[ $DRY_RUN -eq 1 ]]; then
  if [[ ! -f "$LATEST" ]]; then
    _log "no $LATEST — run at least one non-dry iteration first"
    exit 1
  fi
  _log "dry-run: parsing last bench without re-running"
  _parse_and_log
  exit 0
fi

for i in $(seq 1 "$ITER"); do
  if _run_bench "$i"; then
    _parse_and_log
  else
    _log "iter $i failed — continuing"
  fi
done

_log "done. log: $LOG_FILE"
