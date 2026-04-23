#!/usr/bin/env python3
"""MLA decode oracle runner — double-gated orchestrator.

Phase M (MLA decode oracle). See docs/mla-oracle-roadmap.md §3 M4.

Orchestrates a single MLA decode oracle run end-to-end:

    1. Load the case JSON (rail, target, bug_id, reproducer path).
    2. Load the FP32 reference (from corpus/mla/reference/golden_vectors/).
    3. Dispatch the candidate kernel to the rail-specific executor:
         - rail == "cute-mla"    → scripts/ssh_exec.sh to RunPod B200
         - rail == "tpu-pallas"  → scripts/gcp_tpu_exec.sh to GCP Trillium
    4. Fetch candidate output tensor (JSON or .npy) back.
    5. Grade against the reference via corpus/mla/oracle/harness.py.
    6. Emit verdict JSON to results/mla-oracle/<run_id>/verdict.json.

Default behavior: --dry-run. Loads case, loads reference, prints the
exec command that WOULD be sent, exits 0. No network, no spend.

Live execution requires BOTH:
    1. --commit flag on the command line, AND
    2. PRISM_MLA_ORACLE_COMMIT=1 in the environment.
Missing either stays in dry-run (exits 1 if --commit without env, to
make the refusal visible).

The Anthropic SDK is not used by this runner — MLA oracle runs are
pure kernel audits, no LLM in the hot path. The double-gate is because
the runner spends cloud compute ($5.49/hr RunPod, $1.20-5/hr GCP).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parent.parent
CASES_DIR = REPO / "cases"
GOLDEN_DIR = REPO / "corpus" / "mla" / "reference" / "golden_vectors"
RESULTS_DIR = REPO / "results" / "mla-oracle"

# Rail → exec-script + default env requirements.
RAIL_DISPATCH: Dict[str, Dict[str, Any]] = {
    "cute-mla": {
        "exec_script": REPO / "scripts" / "ssh_exec.sh",
        "target_hardware": "RunPod B200 Secure",
        "required_env": ["PRISM_RUNPOD_HOST"],  # set to the pod's SSH host when live
    },
    "tpu-pallas": {
        "exec_script": REPO / "scripts" / "gcp_tpu_exec.sh",
        "target_hardware": "GCP Trillium (v6e-1)",
        "required_env": ["PRISM_GCP_PROJECT", "PRISM_GCP_ZONE"],
    },
}


def _load_case(case_path: Path) -> Dict[str, Any]:
    if not case_path.exists():
        raise FileNotFoundError(f"case not found: {case_path}")
    with case_path.open() as fh:
        case = json.load(fh)
    rail = case.get("rail")
    if rail not in RAIL_DISPATCH:
        raise ValueError(
            f"case rail {rail!r} not dispatchable; known: {sorted(RAIL_DISPATCH)}"
        )
    return case


def _resolve_golden(case: Dict[str, Any]) -> Path:
    """Map a case to its committed golden vector file.

    Convention: case declares golden_ref (relative path under
    corpus/mla/reference/golden_vectors/). Fallback to a v2_lite default
    if the case doesn't name a specific golden — useful during bring-up.
    """
    name = case.get("golden_ref", "v2_lite_decode_s16_w42.json")
    return GOLDEN_DIR / name


def _build_exec_request(case: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the dry-run-visible exec-request body.

    The actual shell invocation happens in do_commit(); this is what
    a dry-run prints so reviewers can see what will be sent.
    """
    rail = case["rail"]
    dispatch = RAIL_DISPATCH[rail]
    target_script = dispatch["exec_script"].relative_to(REPO)
    repro_path = case["target_path"]
    return {
        "rail": rail,
        "target_hardware": dispatch["target_hardware"],
        "exec_script": str(target_script),
        "reproducer_path": repro_path,
        "required_env": dispatch["required_env"],
        "remote_command_template": f"cd /workspace && python3 {Path(repro_path).name}",
    }


def _print_dry_run(case: Dict[str, Any], golden: Path, exec_req: Dict[str, Any], run_id: str) -> None:
    print(f"=== MLA oracle runner (dry-run) ===")
    print(f"run_id:          {run_id}")
    print(f"case_id:         {case['case_id']}")
    print(f"rail:            {case['rail']}")
    print(f"target_domain:   {case.get('target_domain', '?')}")
    print(f"reproducer:      {case['target_path']}")
    print(f"golden:          {golden.relative_to(REPO) if golden.exists() else '(missing) ' + str(golden)}")
    print(f"target_hardware: {exec_req['target_hardware']}")
    print(f"exec_script:     {exec_req['exec_script']}")
    print(f"required_env:    {', '.join(exec_req['required_env'])}")
    print(f"remote_command:  {exec_req['remote_command_template']}")
    print(f"--- would write: results/mla-oracle/{run_id}/verdict.json")
    print(f"--- to run live: add --commit AND PRISM_MLA_ORACLE_COMMIT=1")


def do_commit(case: Dict[str, Any], golden_path: Path, run_id: str) -> int:
    """Execute the live run. Imports heavy deps lazily so dry-run stays import-clean."""
    # Lazy imports: numpy + oracle modules only loaded in the commit branch.
    # This keeps dry-run import-time minimal and prevents ModuleNotFoundError
    # in environments where numpy/oracle are absent.
    import numpy as np
    import subprocess

    sys.path.insert(0, str(REPO / "corpus" / "mla" / "oracle"))
    try:
        import tolerances  # type: ignore[import-not-found]
        import harness  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    rail = case["rail"]
    dispatch = RAIL_DISPATCH[rail]
    for env_key in dispatch["required_env"]:
        if not os.environ.get(env_key):
            print(f"ERR: missing required env {env_key!r} for rail {rail}", file=sys.stderr)
            return 2

    # Load reference.
    with golden_path.open() as fh:
        golden = json.load(fh)
    reference = np.asarray(golden["output"], dtype=np.float32)

    # Invoke the rail-specific exec. The reproducer is expected to:
    #   (a) produce candidate output as FP32 floats in JSON form on stdout, OR
    #   (b) write a candidate.json to /workspace/candidate.json which gets scp'd.
    # For v1: assume (a) — reproducer prints a JSON object with {"output": [[...]]}.
    script = dispatch["exec_script"]
    repro = case["target_path"]
    host_or_vm = (
        os.environ["PRISM_RUNPOD_HOST"] if rail == "cute-mla"
        else os.environ.get("PRISM_TPU_VM_NAME", "prism-mla-v6e-1")
    )
    remote_cmd = f"cd /workspace && python3 {Path(repro).name}"

    print(f"=== MLA oracle runner (LIVE, run_id={run_id}) ===", flush=True)
    print(f"invoking {script.name} {host_or_vm} '{remote_cmd}'", flush=True)

    try:
        proc = subprocess.run(
            [str(script), host_or_vm, remote_cmd],
            capture_output=True, text=True, timeout=600, check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERR: exec failed rc={e.returncode}\nstderr:\n{e.stderr}", file=sys.stderr)
        return e.returncode

    # Parse candidate output from stdout (expected JSON on the last line).
    # Reproducers are responsible for their own tee to disk; this parse is best-effort.
    try:
        # Skip any lines before the JSON payload; look for last '{' -> '}'-balanced block.
        stdout = proc.stdout.strip()
        last_open = stdout.rfind("{")
        last_close = stdout.rfind("}")
        if last_open < 0 or last_close < last_open:
            raise ValueError("no JSON object on stdout")
        payload = json.loads(stdout[last_open:last_close + 1])
        candidate = np.asarray(payload["output"], dtype=np.float32)
        dtype_label = payload.get("dtype", "fp32")
    except Exception as e:
        print(f"ERR: could not parse candidate output: {e}", file=sys.stderr)
        return 3

    # Grade.
    tol = tolerances.get_tolerance(dtype_label)
    verdict = harness.check(
        reference, candidate, tol,
        candidate_label=f"{case['case_id']}-{rail}-{dtype_label}",
    )

    # Write verdict.
    out_dir = RESULTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = out_dir / "verdict.json"
    with verdict_path.open("w") as fh:
        json.dump(
            {
                "case_id": case["case_id"],
                "run_id": run_id,
                "rail": rail,
                "hardware": dispatch["target_hardware"],
                "golden_ref": str(golden_path.relative_to(REPO)),
                "verdict": verdict.to_dict(),
            },
            fh, indent=2,
        )
    print(f"wrote {verdict_path.relative_to(REPO)}")
    print(f"passed: {verdict.passed}  reasons: {verdict.reasons}")
    return 0 if verdict.passed else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Run the MLA decode oracle for one case.")
    p.add_argument("--case", required=True, type=Path, help="path to cases/MLA-BUG-*.json")
    p.add_argument("--commit", action="store_true", help="execute live (requires PRISM_MLA_ORACLE_COMMIT=1)")
    args = p.parse_args()

    case = _load_case(args.case)
    golden = _resolve_golden(case)
    exec_req = _build_exec_request(case)
    run_id = str(uuid.uuid4())

    if not args.commit:
        _print_dry_run(case, golden, exec_req, run_id)
        return 0

    if os.environ.get("PRISM_MLA_ORACLE_COMMIT") != "1":
        print(
            "REFUSED: --commit set but PRISM_MLA_ORACLE_COMMIT=1 is not. "
            "Double-gate requires both. Staying in dry-run is safer; exiting 1.",
            file=sys.stderr,
        )
        return 1

    return do_commit(case, golden, run_id)


if __name__ == "__main__":
    sys.exit(main())
