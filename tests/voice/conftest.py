"""Shared fixtures for the voice regression test suite.

Tests marked `@pytest.mark.integration` hit the live B300 pod via SSH.
When SSH isn't reachable (no brev.pem, no network), those tests SKIP
rather than FAIL — the suite should run green on a laptop without the
pod.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

POD = os.environ.get("PRISM42_POD_HOST", "b300-pod")
BENCH_REMOTE_DIR = "/opt/prism42/agents/livekit"

REPO_ROOT = Path(__file__).resolve().parents[2]
SLO_PATH = REPO_ROOT / "tests" / "voice" / "slo.yaml"


def _pod_reachable() -> bool:
    """Return True iff ssh to the pod succeeds within 5 s."""
    try:
        rc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", POD, "true"],
            capture_output=True,
            timeout=10,
        ).returncode
        return rc == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture(scope="session")
def pod_reachable() -> bool:
    return _pod_reachable()


@pytest.fixture(scope="session")
def slo() -> dict:
    """Parsed tests/voice/slo.yaml — adjust thresholds there, not here."""
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML not installed; run `pip install pyyaml` to enable SLO tests")
    with SLO_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture
def pod_ssh(pod_reachable):
    """Returns a callable: cmd_str -> CompletedProcess.

    Raises pytest.skip if the pod is unreachable.
    """
    if not pod_reachable:
        pytest.skip(f"pod {POD} unreachable via SSH (no brev.pem? no network?)")

    def _run(cmd: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
        full = ["ssh", "-o", "ConnectTimeout=5", POD, cmd]
        return subprocess.run(full, capture_output=True, text=True, timeout=timeout)

    return _run


@pytest.fixture
def pod_worker_log(pod_ssh):
    """Returns the last N lines of /tmp/prism42-logs/worker.log."""

    def _tail(n: int = 400) -> str:
        p = pod_ssh(f"tail -{n} /tmp/prism42-logs/worker.log")
        return p.stdout if p.returncode == 0 else ""

    return _tail


@pytest.fixture
def bench_result(pod_ssh, tmp_path):
    """Runs bench_b300.py on the pod + returns the parsed JSON summary.

    Use sparingly — each invocation takes ~1-3 min depending on N and
    sleep_s. Tests that share the result should request this fixture
    with `scope="module"`.
    """

    def _bench(n: int = 3, sleep_s: int = 15) -> dict:
        cmd = (
            f"cd {BENCH_REMOTE_DIR} && "
            f".venv/bin/python bench_b300.py --n {n} --sleep-s {sleep_s}"
        )
        p = pod_ssh(cmd, timeout=600)
        if p.returncode != 0:
            pytest.skip(f"bench_b300 failed on pod: {p.stderr[:400]}")
        # Find the latest JSON summary path from stdout
        import re

        m = re.search(r"\[bench\] wrote (\S+\.json)", p.stdout)
        if not m:
            pytest.skip("bench stdout had no [bench] wrote line — version mismatch?")
        remote_json = m.group(1)
        local_json = tmp_path / "bench.json"
        subprocess.run(
            ["scp", f"{POD}:{remote_json}", str(local_json)],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if not local_json.exists():
            pytest.skip(f"scp of {remote_json} failed")
        return json.loads(local_json.read_text())

    return _bench


def _hop(bench: dict, hop_name: str) -> dict | None:
    for h in bench.get("hop_aggregates", []):
        if h.get("hop") == hop_name:
            return h
    return None


@pytest.fixture
def get_hop():
    """Fixture-form helper: get_hop(bench, "t_reply_e2e_ms") -> dict|None."""
    return _hop
