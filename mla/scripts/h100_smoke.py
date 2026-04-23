"""CUDA smoke test — imported by scripts/verify_h100.sh.

Runs a single DeepSeek-dim MLA decode on the current GPU via FlashInfer,
compares to the torch reference, benchmarks, and prints a JSON dict on the
LAST LINE of stdout. Exit code 0 on verify pass, nonzero on any failure.

Environment:
    PRISM_BACKEND    = "auto" | "fa2" | "fa3" | "cutlass"
    PRISM_KV_LEN     = integer KV length (default 1024)
    PRISM_BATCH      = batch size (default 1)
    PRISM_PAGE_SIZE  = page size (default 64)
    PRISM_Q_DTYPE    = "bfloat16" | "float16" (default bfloat16)
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        from runner.flashinfer_runner import (
            FlashInferMLAConfig,
            environment_report,
            run_flashinfer_mla_decode,
        )
    except Exception as e:
        print(json.dumps({"import_error": f"{type(e).__name__}: {e}"}))
        return 2

    env = environment_report()
    print(f"# environment: {json.dumps(env)}", file=sys.stderr)

    cfg = FlashInferMLAConfig(
        batch_size=int(os.environ.get("PRISM_BATCH", 1)),
        kv_len=int(os.environ.get("PRISM_KV_LEN", 1024)),
        page_size=int(os.environ.get("PRISM_PAGE_SIZE", 64)),
        backend=os.environ.get("PRISM_BACKEND", "auto"),
        q_dtype=os.environ.get("PRISM_Q_DTYPE", "bfloat16"),
        kv_dtype=os.environ.get("PRISM_KV_DTYPE", "bfloat16"),
    )
    try:
        result = run_flashinfer_mla_decode(cfg)
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        # Emit a parseable JSON on last line even on failure.
        print(json.dumps({
            "verify": {"passed": False, "error": f"{type(e).__name__}: {e}"},
            "bench": {},
            "config": cfg.__dict__,
        }))
        return 3

    print(json.dumps(result))
    return 0 if result["verify"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
