"""LLM backend acceptance test — Phase D strict 5-gate protocol.

Reusable harness so every LLM-backend swap (Anthropic / vLLM-local /
cloud-X) gets the same 5-gate acceptance check via a single pytest
invocation.

Environment variables
---------------------
LLM_BACKEND          anthropic | vllm-local | <other-cloud-tag>
                     Default: anthropic
LLM_BACKEND_BASE_URL OpenAI-shape base URL (required for vllm-local;
                     ignored for 'anthropic')
LLM_BACKEND_MODEL    Model name to send in chat-completions requests.
                     Default: claude-opus-4-7 when backend=anthropic.
ANTHROPIC_API_KEY    Required when backend=anthropic.
                     Omit (or set to empty) on a laptop → test skips.
OPENAI_API_KEY       Required by some cloud-X backends; ignored
                     by vllm-local (which accepts any dummy value).

5 gates (from docs/livekit-kb/25-b300-purr-migration-plan.md §Phase D acceptance)
-----------------------------------------------------------------------------------
1. Toolchain inventory recorded (skipped for cloud backends).
2. Attention backend classified as OPTIMAL | DEGRADED (skipped for cloud).
3. 5 warmup + 20 measured requests; p50/p95/max TTFT + Total + tok/s.
4. JIT penalty reported (sample-1 TTFT / warmed-median TTFT).
5. Assertions:
   a. backend = OPTIMAL  OR  backend tag is cloud (gate 2)
   b. warmed-p95 TTFT < threshold from slo.yaml (cloud: 700 ms, local: 200 ms)
   c. tokens/sec p50 >= slo.yaml llm_backend.tokens_per_sec_p50_min (30)
   d. no exceptions across all 25 requests
   e. services-still-listening check (skipped when pod unreachable)

Outputs
-------
findings/b300_bench/<UTC>-test_llm_backend_acceptance.json
One-line stdout summary printed after the assertions.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants — 20 dispatcher prompts matching the Phase D-strict sample shape.
# These are intentionally fixed so sample distributions stay comparable
# across every backend swap.  5-12 words each, classic 911-dispatcher cadence.
# ---------------------------------------------------------------------------

DISPATCHER_PROMPTS: list[str] = [
    "911 what is your emergency",
    "Is anyone injured at the scene right now",
    "Can you tell me your exact address",
    "Stay on the line help is coming",
    "How many people are in the vehicle",
    "Is the person breathing on their own",
    "Do you see any smoke or flames nearby",
    "What is the patient's approximate age",
    "Is the door locked can EMS get in",
    "Are there any weapons present at the scene",
    "Which intersection are you closest to right now",
    "Is the bleeding severe can you apply pressure",
    "How long has the person been unconscious",
    "Is there a safe place for you to wait",
    "Can you hear the ambulance approaching yet",
    "Are you somewhere the driver can see you",
    "Is the child breathing normally right now",
    "What color is the vehicle involved in the crash",
    "Has anyone else already called 911 tonight",
    "Stay calm units are less than two minutes away",
]

assert len(DISPATCHER_PROMPTS) == 20, "PROMPTS list must stay exactly 20 entries"

N_WARMUP = 5
N_MEASURED = 20
REQUEST_TIMEOUT_S = 30.0

REPO_ROOT = Path(__file__).resolve().parents[2]
FINDINGS_DIR = REPO_ROOT / "findings" / "b300_bench"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _backend() -> str:
    return _env("LLM_BACKEND", "anthropic").lower()


def _is_cloud() -> bool:
    """Returns True for any non-local backend (Anthropic or other cloud)."""
    return _backend() != "vllm-local"


def _base_url() -> str:
    b = _backend()
    if b == "anthropic":
        return "https://api.anthropic.com/v1"
    url = _env("LLM_BACKEND_BASE_URL")
    if not url:
        pytest.skip(
            "LLM_BACKEND_BASE_URL not set — required for non-anthropic backends"
        )
    return url.rstrip("/")


def _model() -> str:
    m = _env("LLM_BACKEND_MODEL")
    if m:
        return m
    if _backend() == "anthropic":
        return "claude-opus-4-7"
    pytest.skip("LLM_BACKEND_MODEL not set — required for non-anthropic backends")


def _anthropic_key() -> str:
    return _env("ANTHROPIC_API_KEY")


def _check_prerequisites() -> None:
    """Skip instead of fail when the environment isn't configured."""
    b = _backend()
    if b == "anthropic":
        if not _anthropic_key():
            pytest.skip("ANTHROPIC_API_KEY not set — skipping on this machine")
    elif b == "vllm-local":
        if not _env("LLM_BACKEND_BASE_URL"):
            pytest.skip(
                "vllm-local selected but LLM_BACKEND_BASE_URL not set"
            )
    # other cloud backends: caller must ensure relevant key is set


def _send_prompt(prompt: str) -> dict[str, Any]:
    """POST one chat-completions request; return timing + metadata dict.

    Returns a dict with keys:
      ttft_ms, total_ms, token_count, error (str|None)

    Uses httpx so we can stream and capture first-byte timing precisely.
    """
    import httpx

    b = _backend()
    url = _base_url() + "/messages" if b == "anthropic" else _base_url() + "/chat/completions"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if b == "anthropic":
        key = _anthropic_key()
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        body = {
            "model": _model(),
            "max_tokens": 64,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "system": (
                "You are a 911 dispatcher. Reply with one sentence only, "
                "10 words or fewer."
            ),
        }
    else:
        body = {
            "model": _model(),
            "max_tokens": 64,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a 911 dispatcher. Reply with one sentence only, "
                        "10 words or fewer."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        openai_key = _env("OPENAI_API_KEY", "dummy-vllm-local")
        headers["Authorization"] = f"Bearer {openai_key}"

    t0 = time.perf_counter()
    ttft_ms: float | None = None
    token_count = 0
    error: str | None = None

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    error = f"HTTP {resp.status_code}: {resp.read()[:200].decode(errors='replace')}"
                else:
                    for chunk in resp.iter_lines():
                        if ttft_ms is None and chunk.strip():
                            ttft_ms = (time.perf_counter() - t0) * 1000
                        # Count tokens loosely via SSE data chunks
                        if chunk.startswith("data:") and chunk != "data: [DONE]":
                            token_count += 1
    except httpx.TimeoutException as exc:
        error = f"Timeout after {REQUEST_TIMEOUT_S}s: {exc}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    total_ms = (time.perf_counter() - t0) * 1000
    return {
        "ttft_ms": ttft_ms if ttft_ms is not None else total_ms,
        "total_ms": total_ms,
        "token_count": token_count,
        "error": error,
    }


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return float("nan")
    data = sorted(data)
    k = (len(data) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)


def _write_findings(payload: dict) -> Path:
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = FINDINGS_DIR / f"{ts}-test_llm_backend_acceptance.json"
    out.write_text(json.dumps(payload, indent=2))
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _slo(slo: dict) -> dict:
    """Pull llm_backend section from slo.yaml; hard-fail if missing."""
    cfg = slo.get("llm_backend")
    if cfg is None:
        pytest.fail(
            "slo.yaml missing 'llm_backend' section — "
            "add it per tests/voice/README.md"
        )
    return cfg


# ---------------------------------------------------------------------------
# Gate 1 — toolchain inventory (recorded; cloud backends skip)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gate1_toolchain_inventory(pod_ssh):
    """Record toolchain snapshot. Cloud backends skip (no local pod access needed)."""
    if _is_cloud():
        pytest.skip("Gate 1: toolchain inventory N/A for cloud backend")

    cmds = {
        "nvidia_smi": "nvidia-smi --query-gpu=driver_version,compute_cap --format=csv,noheader 2>&1 | head -2",
        "nvcc_version": "nvcc --version 2>&1 | tail -1",
        "torch_info": "python3 -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_capability())' 2>&1",
        "vllm_version": "python3 -c 'import vllm; print(vllm.__version__)' 2>&1",
        "flashinfer_version": "python3 -c 'import flashinfer; print(flashinfer.__version__)' 2>&1",
    }
    inventory: dict[str, str] = {}
    for key, cmd in cmds.items():
        p = pod_ssh(cmd)
        inventory[key] = p.stdout.strip() if p.returncode == 0 else f"ERROR: {p.stderr.strip()[:120]}"

    print(f"\n[gate1] toolchain={json.dumps(inventory, indent=2)}")
    # Gate 1 always passes if we reach here — inventory is for records only.
    assert inventory, "toolchain_inventory dict must not be empty"


# ---------------------------------------------------------------------------
# Gate 2 — attention backend classification (cloud backends skip)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gate2_attention_backend(_slo, pod_ssh):
    """Parse vllm.log for attention backend; assert OPTIMAL or skip for cloud."""
    if _is_cloud():
        pytest.skip("Gate 2: attention backend N/A for cloud backend")

    p = pod_ssh(
        "grep -iE '(attention_backend|Using attention backend|FlashInfer|FA4|FlashMLA|TRTLLM|FA3|FA2|xFormers|TritonAttention|EagerAttention)'"
        " /tmp/prism42-logs/vllm.log 2>/dev/null | tail -20"
    )
    log_snippet = p.stdout if p.returncode == 0 else ""

    OPTIMAL_PATTERNS = ["FA4", "FlashInfer", "TRTLLM", "FlashMLA"]
    DEGRADED_PATTERNS = ["FA3", "FA2", "xFormers", "TritonAttention", "EagerAttention"]

    classification = "UNKNOWN"
    for pat in OPTIMAL_PATTERNS:
        if pat.lower() in log_snippet.lower():
            classification = "OPTIMAL"
            break
    if classification == "UNKNOWN":
        for pat in DEGRADED_PATTERNS:
            if pat.lower() in log_snippet.lower():
                classification = "DEGRADED"
                break

    print(f"\n[gate2] attention_backend_classification={classification}")
    assert classification == "OPTIMAL", (
        f"Gate 2 FAIL: attention backend classified as {classification} "
        f"(log snippet: {log_snippet[:300]!r}). "
        "Phase E must NOT proceed until this is OPTIMAL."
    )


# ---------------------------------------------------------------------------
# Gate 3+4 — latency benchmark (5 warmup + 20 measured)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gate3_gate4_latency_benchmark(_slo):
    """Run the 5+20 benchmark; assert SLO thresholds; write findings JSON."""
    _check_prerequisites()

    backend = _backend()
    is_cloud = _is_cloud()

    # Determine thresholds from slo.yaml
    p95_threshold_ms: float
    if is_cloud:
        p95_threshold_ms = float(
            _slo.get("warmed_p95_ttft_ms", {}).get("cloud", 700)
        )
    else:
        p95_threshold_ms = float(
            _slo.get("warmed_p95_ttft_ms", {}).get("local", 200)
        )

    toks_per_sec_min: float = float(_slo.get("tokens_per_sec_p50_min", 30))
    jit_penalty_max: float = float(_slo.get("jit_penalty_max_ratio", 3.0))

    warmup_results: list[dict] = []
    measured_results: list[dict] = []
    errors: list[str] = []

    # --- Warmup ---
    warmup_prompts = (DISPATCHER_PROMPTS[:N_WARMUP] if N_WARMUP <= N_MEASURED
                      else DISPATCHER_PROMPTS[:N_WARMUP])
    for i, prompt in enumerate(warmup_prompts):
        r = _send_prompt(prompt)
        warmup_results.append({**r, "index": i, "phase": "warmup"})
        if r["error"]:
            errors.append(f"warmup[{i}]: {r['error']}")

    # --- Measured ---
    for i, prompt in enumerate(DISPATCHER_PROMPTS):
        r = _send_prompt(prompt)
        measured_results.append({**r, "index": i, "phase": "measured"})
        if r["error"]:
            errors.append(f"measured[{i}]: {r['error']}")

    # --- Aggregates ---
    ttft_values = [r["ttft_ms"] for r in measured_results if r["error"] is None]
    total_values = [r["total_ms"] for r in measured_results if r["error"] is None]

    # tokens/sec: token_count / (total_ms/1000); exclude zero-token results
    toks_per_sec_values = [
        r["token_count"] / (r["total_ms"] / 1000)
        for r in measured_results
        if r["error"] is None and r["total_ms"] > 0 and r["token_count"] > 0
    ]

    def _agg(vals: list[float]) -> dict[str, float | None]:
        if not vals:
            return {"p50": None, "p95": None, "max": None, "n": 0}
        return {
            "p50": _percentile(vals, 50),
            "p95": _percentile(vals, 95),
            "max": max(vals),
            "n": len(vals),
        }

    ttft_agg = _agg(ttft_values)
    total_agg = _agg(total_values)
    toks_agg = _agg(toks_per_sec_values)

    # JIT penalty: sample-0 TTFT vs median of samples 5-24 (warmed)
    sample1_ttft = measured_results[0]["ttft_ms"] if measured_results else None
    warmed_ttft_vals = [
        r["ttft_ms"] for r in measured_results[5:] if r["error"] is None
    ]
    warmed_median = statistics.median(warmed_ttft_vals) if warmed_ttft_vals else None
    jit_penalty_ratio: float | None = (
        sample1_ttft / warmed_median
        if sample1_ttft is not None and warmed_median and warmed_median > 0
        else None
    )

    summary = {
        "backend": backend,
        "model": _model(),
        "is_cloud": is_cloud,
        "ttft_ms": ttft_agg,
        "total_ms": total_agg,
        "tokens_per_sec": toks_agg,
        "jit_penalty": {
            "sample1_ttft_ms": sample1_ttft,
            "warmed_median_ttft_ms": warmed_median,
            "ratio": jit_penalty_ratio,
            "note": (
                "ratio = sample-1 TTFT / warmed-median TTFT. "
                f"SLO max ratio: {jit_penalty_max}"
            ),
        },
        "n_errors": len(errors),
        "errors": errors[:10],
        "thresholds_applied": {
            "warmed_p95_ttft_ms": p95_threshold_ms,
            "tokens_per_sec_p50_min": toks_per_sec_min,
            "jit_penalty_max_ratio": jit_penalty_max,
        },
    }

    payload = {
        "test": "test_llm_backend_acceptance",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "model": _model(),
        "slo_profile": "cloud" if is_cloud else "local",
        "warmup": warmup_results,
        "measured": measured_results,
        "summary": summary,
        "gate_verdicts": {},  # filled below before write
    }

    # --- Gate assertions ---
    gate_results: dict[str, str] = {}

    # Gate 3a: warmed-p95 TTFT
    p95_ttft = ttft_agg["p95"]
    if p95_ttft is None:
        gate_results["gate_3a_warmed_p95_ttft"] = "NOT_MEASURED"
    elif p95_ttft <= p95_threshold_ms:
        gate_results["gate_3a_warmed_p95_ttft"] = "PASS"
    else:
        gate_results["gate_3a_warmed_p95_ttft"] = "FAIL"

    # Gate 3b: tokens/sec p50
    toks_p50 = toks_agg["p50"]
    if toks_p50 is None:
        gate_results["gate_3b_tokens_per_sec"] = "NOT_MEASURED"
    elif toks_p50 >= toks_per_sec_min:
        gate_results["gate_3b_tokens_per_sec"] = "PASS"
    else:
        gate_results["gate_3b_tokens_per_sec"] = "FAIL"

    # Gate 3c: no exceptions
    gate_results["gate_3c_no_exceptions"] = "PASS" if not errors else "FAIL"

    # Gate 3d: JIT penalty
    if jit_penalty_ratio is None:
        gate_results["gate_3d_jit_penalty"] = "NOT_MEASURED"
    elif jit_penalty_ratio <= jit_penalty_max:
        gate_results["gate_3d_jit_penalty"] = "PASS"
    else:
        gate_results["gate_3d_jit_penalty"] = "FAIL"

    payload["gate_verdicts"] = gate_results
    out_path = _write_findings(payload)

    # One-line stdout summary — build scalars first to avoid nested f-string quoting issues
    ttft_p50_str = f"{ttft_agg['p50']:.0f}ms" if ttft_agg["p50"] is not None else "N/A"
    ttft_p95_str = f"{p95_ttft:.0f}ms" if p95_ttft is not None else "N/A"
    toks_str = f"{toks_p50:.1f}" if toks_p50 is not None else "N/A"
    jit_str = f"{jit_penalty_ratio:.2f}x" if jit_penalty_ratio is not None else "N/A"
    print(
        f"\n[llm-backend-acceptance] backend={backend} model={_model()} "
        f"ttft_p50={ttft_p50_str} ttft_p95={ttft_p95_str} "
        f"toks/s_p50={toks_str} jit_ratio={jit_str} "
        f"errors={len(errors)} gates={gate_results} findings={out_path}"
    )

    # Hard assertions — each names the exact gate that fired
    failed_gates = [k for k, v in gate_results.items() if v == "FAIL"]
    assert not failed_gates, (
        f"Gate(s) FAILED: {failed_gates}. "
        f"ttft_p95={p95_ttft:.1f}ms (threshold={p95_threshold_ms}ms), "
        f"toks/s_p50={toks_p50}, "
        f"errors={errors[:3]}, "
        f"jit_ratio={jit_penalty_ratio}. "
        f"Full findings: {out_path}"
    )

    if p95_ttft is None or (toks_p50 is None):
        pytest.skip(
            "All requests errored out — backend may be unavailable. "
            f"Errors: {errors[:3]}"
        )


# ---------------------------------------------------------------------------
# Gate 5 — services still listening (co-residency check)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gate5_services_listening(pod_ssh, pod_reachable):
    """Assert Parakeet (:9100) and Fish (:9200) are still up after the bench."""
    if not pod_reachable:
        pytest.skip("Gate 5: pod unreachable, skipping co-residency check")

    endpoints = {
        "parakeet": "http://127.0.0.1:9100/healthz",
        "fish": "http://127.0.0.1:9200/v1/health",
    }
    dead: list[str] = []
    for svc, url in endpoints.items():
        p = pod_ssh(f"curl -sf --max-time 5 {url} -o /dev/null && echo OK || echo FAIL")
        if "OK" not in p.stdout:
            dead.append(svc)

    assert not dead, (
        f"Gate 5 FAIL: services dead after bench run: {dead}. "
        "Check GPU OOM — vLLM may have crowded out co-resident services."
    )
