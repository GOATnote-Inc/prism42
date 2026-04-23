"""Terminate a RunPod pod by id. Dry-run by default; --confirm to actually
DELETE. This is irreversible — the pod and its container disk go away.

If you just want to stop billing without losing the pod, use
`stop_pod` via `python -c "from runner.runpod_provisioner import stop_pod;
print(stop_pod('POD_ID', confirm=True))"`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner.runpod_provisioner import delete_pod, stop_pod


def main() -> int:
    p = argparse.ArgumentParser(description="Terminate a RunPod pod.")
    p.add_argument("pod_id")
    p.add_argument("--confirm", action="store_true",
                   help="Actually call the API.")
    p.add_argument("--stop-only", action="store_true",
                   help="Stop instead of delete (preserves pod, stops GPU billing).")
    args = p.parse_args()

    op = stop_pod if args.stop_only else delete_pod
    action = "stop" if args.stop_only else "delete"
    result = op(args.pod_id, confirm=args.confirm)
    if not args.confirm:
        print(f"[dry-run] would {action} pod {args.pod_id}. re-run with --confirm.")
        return 0
    print(f"[ok] {action} pod {args.pod_id}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
