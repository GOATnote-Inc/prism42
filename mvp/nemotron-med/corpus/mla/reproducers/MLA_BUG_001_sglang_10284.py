"""MLA-BUG-001 — FP4 accuracy issue with B200 + FlashInfer MLA (SGLang).

Upstream:    sgl-project/sglang#10284
URL:         https://github.com/sgl-project/sglang/issues/10284
Class:       precision
Target rail: cute-mla (SM100 / Blackwell)

Trigger:     Run a DeepSeek-family model (MLA architecture) through SGLang's
             FlashInfer MLA backend on B200 with FP4 KV-cache quantization.
             Task-level accuracy (e.g. GSM8K) drops measurably relative to
             FP8 / bf16 baselines, beyond what the NVFP4 precision floor
             predicts.

Oracle contract (docs/mla-oracle-roadmap.md §3 M5):
  - On SM100 + required libs: run one MLA decode step, emit candidate
    output as FP32 floats on stdout in the canonical JSON shape.
  - On non-SM100 or missing libs: emit a `deferred` verdict.
  - Tolerance preset used by runner: "nvfp4" (max_rel_diff 3e-1, min_cos_sim 0.97).

Dependencies: torch, sglang, flashinfer, optionally a HF model checkpoint
              at DEEPSEEK_V2_LITE_PATH.

Trigger implementation status: scaffold. The full trigger lands in M6
(B200 live run). On non-B200 hardware this reproducer is a clean no-op
that emits a `deferred` JSON verdict with a specific reason string.
"""

from __future__ import annotations

import json
import os
import sys

BUG_ID = "MLA-BUG-001"
REQUIRED_CC = (10, 0)  # SM100 Blackwell (B200 / GB200)
REQUIRED_LIBS = ("torch", "sglang", "flashinfer")


def _emit(obj: dict) -> None:
    """Emit a JSON verdict on stdout. The runner parses the last {...} block."""
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
    assert cc is not None  # for type checkers
    if cc != REQUIRED_CC:
        _defer(f"need SM{REQUIRED_CC[0]}{REQUIRED_CC[1]} (Blackwell), got SM{cc[0]}{cc[1]}")

    missing = _check_libs()
    if missing:
        _defer(f"required library missing: {missing}")

    # === Trigger block (lands in M6 on B200) ===================================
    # Planned: construct a FlashInfer trtllm MLA decode call on DeepSeek-V2-Lite
    # shape (d_c=512, d_h^R=64, 16 heads × 128) with NVFP4 KV cache, run one
    # decode step on seeded input, and emit the candidate output for the oracle
    # to grade. M6 will reference the committed golden vector at
    # corpus/mla/reference/golden_vectors/v2_lite_decode_s16_w42.json.

    _emit({
        "bug_id": BUG_ID,
        "status": "deferred",
        "reason": "trigger implementation scheduled for M6 (B200 live run); "
                   "scaffold ready, B200 capacity pending",
    })


if __name__ == "__main__":
    main()
