"""Create a RunPod H100 (or B200) pod for prism-mla verify.

Dry-run by default; prints the request body without sending. Pass
--confirm to actually create the pod (COSTS MONEY).

Examples:
    # Dry-run, H100 SXM5 default:
    .venv/bin/python scripts/runpod_create.py

    # Actually create, prefer H100, fall back to H200:
    .venv/bin/python scripts/runpod_create.py --confirm --gpu H100_SXM --fallback H200

    # B200 Blackwell:
    .venv/bin/python scripts/runpod_create.py --confirm --gpu B200 --volume-gb 100

    # With a name:
    .venv/bin/python scripts/runpod_create.py --confirm --name prism-mla-fa4-attn

After --confirm the script waits up to 5 minutes for desiredStatus=RUNNING,
then prints the pod id + ssh command. Nothing more is done; next step is
`bash scripts/setup_h100.sh` on the pod.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner.runpod_provisioner import (
    GPU_TYPES,
    PodSpec,
    create_pod,
    wait_until_running,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Create a RunPod pod for prism-mla.")
    p.add_argument("--confirm", action="store_true",
                   help="Actually call the API. Without it, prints the request body.")
    p.add_argument("--name", default="prism-mla-verify")
    p.add_argument("--gpu", default="H100_SXM", choices=list(GPU_TYPES),
                   help="Primary GPU type key (see runner.runpod_provisioner.GPU_TYPES).")
    p.add_argument("--fallback", default=None, choices=list(GPU_TYPES),
                   help="Secondary GPU type to allow if primary unavailable.")
    p.add_argument("--volume-gb", type=int, default=50)
    p.add_argument("--container-disk-gb", type=int, default=100)
    p.add_argument("--image", default=PodSpec().imageName)
    p.add_argument("--wait-timeout-s", type=int, default=300)
    args = p.parse_args()

    gpu_ids = [GPU_TYPES[args.gpu]]
    if args.fallback:
        gpu_ids.append(GPU_TYPES[args.fallback])

    spec = PodSpec(
        name=args.name,
        imageName=args.image,
        gpuTypeIds=gpu_ids,
        volumeInGb=args.volume_gb,
        containerDiskInGb=args.container_disk_gb,
    )

    result = create_pod(spec, confirm=args.confirm)
    if not args.confirm:
        print(f"\n[dry-run] no pod created. re-run with --confirm to send.")
        return 0

    pod_id = result.get("id") or result.get("podId") or result.get("pod", {}).get("id")
    if not pod_id:
        print(f"[fail] create returned no id; body: {json.dumps(result)[:500]}", file=sys.stderr)
        return 2

    print(f"[ok] pod created: {pod_id}")
    print(f"[wait] up to {args.wait_timeout_s}s for RUNNING status...")
    t0 = time.time()
    pod = wait_until_running(pod_id, timeout_s=args.wait_timeout_s, poll_s=5)
    print(f"[ok] running after {time.time() - t0:.1f}s")

    # Extract connection info — schema varies; dump everything useful.
    ssh = pod.get("ssh", {}) if isinstance(pod.get("ssh"), dict) else {}
    ports = pod.get("ports") or pod.get("runtime", {}).get("ports") or []
    print(f"[info] pod_id  = {pod_id}")
    print(f"[info] status  = {pod.get('desiredStatus', '?')}")
    print(f"[info] gpu     = {pod.get('machine', {}).get('gpuTypeId', '?')}")
    print(f"[info] ssh raw = {json.dumps(ssh)[:300] if ssh else 'n/a'}")
    if ports:
        print(f"[info] ports   = {json.dumps(ports)[:300]}")
    print("\nnext:")
    print(f"  # connect via web terminal or SSH, then:")
    print(f"  cd /workspace && git clone <your_repo_url> prism-mla && cd prism-mla")
    print(f"  bash scripts/setup_h100.sh && bash scripts/verify_h100.sh")
    print(f"\nteardown when done:")
    print(f"  .venv/bin/python scripts/runpod_teardown.py {pod_id} --confirm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
