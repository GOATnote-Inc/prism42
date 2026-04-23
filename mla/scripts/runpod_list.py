"""Read-only RunPod check: confirm API key works, list pods, show status.

No cost. No mutations. Intended as the very first thing you run after
`source /Users/kiteboard/lostbench/.env`.

Usage:
    RUNPOD_API_KEY=... .venv/bin/python scripts/runpod_list.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner.runpod_provisioner import environment_report, list_pods


def main() -> int:
    env = environment_report()
    print(f"[env] {json.dumps(env)}")
    if not env.get("api_key_present"):
        print("[fail] set RUNPOD_API_KEY in the environment first", file=sys.stderr)
        return 1
    if not env.get("list_ok"):
        print(f"[fail] list_pods error: {env.get('list_error')}", file=sys.stderr)
        return 2
    pods = list_pods()
    if not pods:
        print("[ok] no pods running")
        return 0
    print(f"[ok] {len(pods)} pod(s):")
    for p in pods:
        pid = p.get("id", "?")
        name = p.get("name", "?")
        status = p.get("desiredStatus") or p.get("currentStatus") or p.get("status") or "?"
        gpus = p.get("gpuTypeId") or p.get("machine", {}).get("gpuTypeId") or "?"
        count = p.get("gpuCount", "?")
        print(f"  - {pid}  {status:<10s}  {count}x {gpus}  name={name!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
