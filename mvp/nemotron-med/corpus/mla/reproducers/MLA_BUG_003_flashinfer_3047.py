"""MLA-BUG-003 — MLA chunked-prefill batch-composition-dependent outputs on Blackwell (FlashInfer).

Upstream:    flashinfer-ai/flashinfer#3047
URL:         https://github.com/flashinfer-ai/flashinfer/issues/3047
Class:       precision
Target rail: cute-mla (SM100 / Blackwell)

Trigger:     Run FlashInfer's MLA chunked-prefill kernel on B200 with the
             same per-example inputs packed into two different batch
             compositions (e.g. [A, B, C] vs [A, B] + [C]). The per-example
             outputs should be invariant to batch shape; on Blackwell with
             the current kernel they are not — MSE varies across batches
             for the same example.

Oracle contract (docs/mla-oracle-roadmap.md §3 M5):
  - On SM100 + required libs: run the same example through N batch
    compositions, emit the per-batch output tensors as a list.
  - The oracle grades batch-i-output vs batch-j-output at max ULP; a
    correct kernel has max_abs_diff of 0 on identical inputs across
    batch composition. This bug causes that invariant to break.
  - On non-SM100 or missing libs: emit a `deferred` verdict.
  - Tolerance preset used by runner: "fp8" (candidate is fp8 MLA decode).

Dependencies: torch, flashinfer.

Trigger implementation status: scaffold. Full trigger lands in M6.

Distinct from MLA-BUG-001/002: this is a *batch-composition invariance*
failure, not a precision-floor failure. The oracle catches it by
comparing paired outputs (same example under different batches), not
by comparing a single output against the FP32 reference — but the
candidate output is still graded against the reference to rule out
overall precision drift as the explanation.
"""

from __future__ import annotations

import json
import sys

BUG_ID = "MLA-BUG-003"
REQUIRED_CC = (10, 0)  # SM100 Blackwell
REQUIRED_LIBS = ("torch", "flashinfer")


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _get_cc():
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    return torch.cuda.get_device_capability(0)


def _defer(reason: str) -> None:
    _emit({
        "bug_id": BUG_ID,
        "status": "deferred",
        "reason": reason,
    })
    sys.exit(0)


def _check_libs() -> list[str]:
    missing = []
    for lib in REQUIRED_LIBS:
        try:
            __import__(lib)
        except ImportError:
            missing.append(lib)
    return missing


def main() -> None:
    cc = _get_cc()
    if cc is None:
        _defer("no CUDA device available (REQUIRED: SM100 / Blackwell)")
    assert cc is not None
    if cc != REQUIRED_CC:
        _defer(f"need SM{REQUIRED_CC[0]}{REQUIRED_CC[1]} (Blackwell), got SM{cc[0]}{cc[1]}")

    missing = _check_libs()
    if missing:
        _defer(f"required library missing: {missing}")

    # === Trigger block (lands in M6 on B200) ===================================
    # Planned: run `flashinfer.mla.BatchMLAPagedAttentionWrapper` (or the
    # appropriate trtllm-gen chunked-prefill wrapper) on a fixed example
    # packed into two distinct batch shapes. Emit both outputs; the
    # oracle-level integration in scripts/mla_oracle_runner.py will
    # compare them pair-wise as a batch-invariance check, in addition to
    # grading each against the FP32 reference for precision-floor sanity.

    _emit({
        "bug_id": BUG_ID,
        "status": "deferred",
        "reason": "trigger implementation scheduled for M6 (B200 live run); "
                   "scaffold ready, B200 capacity pending",
    })


if __name__ == "__main__":
    main()
