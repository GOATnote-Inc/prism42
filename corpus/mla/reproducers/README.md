# MLA decode reproducers (Phase M)

These reproducers target the MLA decode oracle on SM100 / Blackwell.

## Bug index

| ID | Upstream issue | Target |
|---|---|---|
| [MLA-BUG-001](MLA_BUG_001_sglang_10284.py) | [sgl-project/sglang#10284](https://github.com/sgl-project/sglang/issues/10284) | FP4 accuracy issue with B200 + FlashInfer MLA |
| [MLA-BUG-002](MLA_BUG_002_vllm_38439.py) | [vllm-project/vllm#38439](https://github.com/vllm-project/vllm/issues/38439) | NVFP4 + MLA error during processing |
| [MLA-BUG-003](MLA_BUG_003_flashinfer_3047.py) | [flashinfer-ai/flashinfer#3047](https://github.com/flashinfer-ai/flashinfer/issues/3047) | MLA chunked-prefill batch-composition-dependent outputs |

## Posture

All three are **already-public** user-filed issues on the respective
trackers. Prism's role is executed verification against a correctness
oracle, not zero-day disclosure. Cite them by issue number.

Any novel correctness failure not covered by a public issue routes
off-tree via the private channel described in
`docs/kernel-research-posture.md` — never through this repo.

## Output contract

Every reproducer emits a JSON object on stdout. The runner parses the
last `{...}` block. Fields:

```json
{
  "bug_id": "MLA-BUG-00X",
  "status": "triggered" | "deferred" | "error",
  "hardware": {"cc": [10, 0], "device_name": "...", "cuda": "..."},
  "dtype": "nvfp4" | "fp8" | "bf16" | "fp32",
  "output": [[float, ...]],                // [B, d_model] FP32 values on triggered
  "reason": "..."                          // on deferred/error
}
```

## Hardware guard

Each reproducer has `REQUIRED_CC = (10, 0)` (SM100 Blackwell) and defers
cleanly on any other compute capability. All three bugs require B200 or
GB200 hardware to trigger — they are genuinely SM100-specific. A run on
H100 (SM90) is not a "missed trigger"; it is a hardware-unreachable
condition the reproducer reports explicitly.

## Trigger implementation status (2026-04-22)

Scaffolds. Library-presence checks, CC guard, and deferred-verdict
emission are complete. The actual trigger bodies (library-specific MLA
decode calls) land in **M6** when B200 capacity materializes on the
Prism rail (RunPod B200 Secure, ~$5.49/hr; capacity polled by
`scripts/poll_b200_capacity.sh`).

## Frozen-path note

`corpus/reproducers/*` is frozen per `CLAUDE.md` §3. These MLA
reproducers live at `corpus/mla/reproducers/` — a parallel, non-frozen
path.
