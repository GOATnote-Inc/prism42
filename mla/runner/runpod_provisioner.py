"""RunPod REST provisioner for prism-mla.

Thin typed wrapper over https://rest.runpod.io/v1. Covers the operations we
need to stand up, verify, and tear down a pod for one evolve run:

    list_pods()                              GET    /v1/pods
    get_pod(id)                              GET    /v1/pods/{id}
    create_pod(spec, confirm=...)            POST   /v1/pods
    stop_pod(id, confirm=...)                POST   /v1/pods/{id}/stop
    start_pod(id, confirm=...)               POST   /v1/pods/{id}/start
    delete_pod(id, confirm=...)              DELETE /v1/pods/{id}
    wait_until_running(id, timeout=...)

Design rules (respect the red-team archive):
    - Every cost-incurring call (create/start/delete) requires confirm=True.
      Otherwise the method returns the request body and exits without
      hitting the API. This is the Munger §1 defense against accidental spend.
    - The API key is read from RUNPOD_API_KEY env at call time; it is never
      logged, written to disk, or passed as a positional argument. Memory
      rule: no .env reads.
    - GPU type IDs use RunPod's published strings verbatim — we do not
      invent identifiers. See GPU_TYPES below.

API shape verified against https://docs.runpod.io/api-reference/ on 2026-04-22.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    import requests  # type: ignore
    _HAVE_REQUESTS = True
except ImportError:
    requests = None  # type: ignore
    _HAVE_REQUESTS = False


BASE_URL = "https://rest.runpod.io/v1"

# GPU type IDs as published by RunPod. Do not invent variants — RunPod
# rejects unknown strings. Verified 2026-04-22 from the public API reference.
GPU_TYPES = {
    "H100_SXM":   "NVIDIA H100 80GB HBM3",    # SM90 Hopper, 80 GB HBM3
    "H100_PCIE":  "NVIDIA H100 PCIe",
    "H100_NVL":   "NVIDIA H100 NVL",
    "H200":       "NVIDIA H200",              # SM90 Hopper, 141 GB HBM3e
    "H200_NVL":   "NVIDIA H200 NVL",
    "B200":       "NVIDIA B200",              # SM100 Blackwell, 192 GB HBM3e
    "A100_SXM":   "NVIDIA A100-SXM4-80GB",
    "A100_PCIE":  "NVIDIA A100 80GB PCIe",
    "L40S":       "NVIDIA L40S",
    "RTX_4090":   "NVIDIA RTX 4090",
}

# Architecture mapping for the validator/archive cross-ref. Keep aligned
# with cross-pollination/tcu-gpu-tpu-trainium-playbook.md.
ARCH_BY_GPU: dict[str, str] = {
    GPU_TYPES["H100_SXM"]:   "sm_90a",  # Hopper
    GPU_TYPES["H100_PCIE"]:  "sm_90a",
    GPU_TYPES["H100_NVL"]:   "sm_90a",
    GPU_TYPES["H200"]:       "sm_90a",  # Hopper (NOT Blackwell)
    GPU_TYPES["H200_NVL"]:   "sm_90a",
    GPU_TYPES["B200"]:       "sm_100",  # Blackwell
    GPU_TYPES["A100_SXM"]:   "sm_80",
    GPU_TYPES["A100_PCIE"]:  "sm_80",
    GPU_TYPES["L40S"]:       "sm_89",   # Ada
    GPU_TYPES["RTX_4090"]:   "sm_89",
}


@dataclass
class PodSpec:
    """Request body for POST /v1/pods. Fields default to safe minimums; caller
    overrides per workload. All fields are RunPod-published names, do not rename."""

    name: str = "prism-mla-verify"
    imageName: str = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
    computeType: str = "GPU"
    cloudType: str = "SECURE"   # Secure grants SYS_ADMIN for ncu counters
    gpuCount: int = 1
    gpuTypeIds: list[str] = field(default_factory=lambda: [GPU_TYPES["H100_SXM"]])
    gpuTypePriority: str = "availability"
    containerDiskInGb: int = 100
    volumeInGb: int = 50
    minVCPUPerGPU: int = 8
    minRAMPerGPU: int = 32
    ports: list[str] = field(default_factory=lambda: ["8888/http", "22/tcp"])
    env: dict[str, str] = field(default_factory=dict)
    interruptible: bool = False

    def to_body(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class RunPodError(RuntimeError):
    pass


class NotConfirmedError(RunPodError):
    """Raised when a cost-incurring operation is invoked without confirm=True."""


def _require_requests() -> None:
    if not _HAVE_REQUESTS:
        raise RunPodError("the 'requests' library is required: pip install requests")


def _require_api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        raise RunPodError("RUNPOD_API_KEY not set in environment")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_require_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, path: str, *, json_body: dict | None = None, timeout: int = 30) -> Any:
    _require_requests()
    url = f"{BASE_URL}{path}"
    resp = requests.request(method, url, headers=_headers(), json=json_body, timeout=timeout)
    if resp.status_code >= 400:
        raise RunPodError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


# ---- Operations ----

def list_pods() -> list[dict]:
    """GET /v1/pods — cheap, read-only; safe to call without confirm."""
    data = _request("GET", "/pods")
    # Response can be either a list or an object with a 'pods' key depending
    # on API version; normalize.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("pods") or data.get("data") or [data]
    return []


def get_pod(pod_id: str) -> dict:
    """GET /v1/pods/{id} — read-only."""
    return _request("GET", f"/pods/{pod_id}")


def create_pod(spec: PodSpec, *, confirm: bool = False, dry_run_print: bool = True) -> dict:
    """POST /v1/pods — COSTS MONEY. Requires confirm=True.

    When confirm=False, prints the request body (if dry_run_print) and
    returns it as a dict without calling the API.
    """
    body = spec.to_body()
    if not confirm:
        if dry_run_print:
            print("[runpod.dry_run] POST /v1/pods body:")
            print(json.dumps(body, indent=2))
        return {"dry_run": True, "body": body}
    return _request("POST", "/pods", json_body=body, timeout=60)


def stop_pod(pod_id: str, *, confirm: bool = False) -> dict:
    """POST /v1/pods/{id}/stop — does not delete, but stops billing for GPU."""
    if not confirm:
        return {"dry_run": True, "path": f"POST /pods/{pod_id}/stop"}
    return _request("POST", f"/pods/{pod_id}/stop")


def start_pod(pod_id: str, *, confirm: bool = False) -> dict:
    """POST /v1/pods/{id}/start — resumes a stopped pod; billing restarts."""
    if not confirm:
        return {"dry_run": True, "path": f"POST /pods/{pod_id}/start"}
    return _request("POST", f"/pods/{pod_id}/start")


def delete_pod(pod_id: str, *, confirm: bool = False) -> dict:
    """DELETE /v1/pods/{id} — permanent. Requires confirm=True."""
    if not confirm:
        return {"dry_run": True, "path": f"DELETE /pods/{pod_id}"}
    return _request("DELETE", f"/pods/{pod_id}")


def wait_until_running(pod_id: str, *, timeout_s: int = 300, poll_s: int = 5) -> dict:
    """Poll get_pod until desiredStatus/currentStatus is RUNNING, or raise."""
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = get_pod(pod_id)
        status = (last.get("desiredStatus")
                  or last.get("currentStatus")
                  or last.get("status")
                  or "")
        if str(status).upper() == "RUNNING":
            return last
        time.sleep(poll_s)
    raise RunPodError(
        f"pod {pod_id} did not reach RUNNING within {timeout_s}s; last={last}"
    )


# ---- Environment report (safe, read-only) ----

def environment_report() -> dict:
    """Non-destructive check: does RUNPOD_API_KEY look present, and can we
    list pods? Never prints the key."""
    info: dict[str, Any] = {
        "have_requests": _HAVE_REQUESTS,
        "api_key_present": bool(os.environ.get("RUNPOD_API_KEY")),
        "base_url": BASE_URL,
    }
    if not _HAVE_REQUESTS or not info["api_key_present"]:
        return info
    try:
        pods = list_pods()
        info["list_ok"] = True
        info["pod_count"] = len(pods)
    except Exception as e:
        info["list_ok"] = False
        info["list_error"] = f"{type(e).__name__}: {e}"
    return info
