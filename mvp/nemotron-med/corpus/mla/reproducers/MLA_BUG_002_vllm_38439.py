"""MLA-BUG-002 — NVFP4 + MLA error during processing (vLLM).

Upstream:    vllm-project/vllm#38439
URL:         https://github.com/vllm-project/vllm/issues/38439
Class:       precision
Target rail: cute-mla (SM100 / Blackwell)

Trigger:     Configure vLLM with NVFP4 quantization on a DeepSeek-family
             (MLA architecture) model and run inference on B200. The
             pipeline produces either an exception during processing or
             a numerically divergent output vs a non-NVFP4 run on the
             same inputs.

Oracle contract (docs/mla-oracle-roadmap.md §3 M5):
  - On SM100 + required libs: instantiate vLLM with NVFP4+MLA config,
    run one forward, emit candidate output as FP32 on stdout.
  - On non-SM100 or missing libs: emit a `deferred` verdict.
  - Tolerance preset used by runner: "nvfp4".

Dependencies: torch, vllm (with NVFP4 support), optionally the same
              DeepSeek-V2-Lite checkpoint used by MLA-BUG-001.

Trigger implementation status: scaffold. Full trigger lands in M6.
"""

from __future__ import annotations

import json
import sys

BUG_ID = "MLA-BUG-002"
REQUIRED_CC = (10, 0)  # SM100 Blackwell
REQUIRED_LIBS = ("torch", "vllm")


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
    # Planned: instantiate `vllm.LLM` with `quantization="nvfp4"` on a
    # DeepSeek-V2-Lite checkpoint, issue a forward pass that touches the
    # MLA attention path, and capture the decoder output. The reported
    # failure mode (vLLM #38439) is a processing error mid-pipeline —
    # if that fires, we emit status="error" with the captured traceback
    # rather than status="triggered"; the runner treats a processing
    # error as an implicit FAIL against the oracle (no valid candidate).

    _emit({
        "bug_id": BUG_ID,
        "status": "deferred",
        "reason": "trigger implementation scheduled for M6 (B200 live run); "
                   "scaffold ready, B200 capacity pending",
    })


if __name__ == "__main__":
    main()
