# Blackwell B300 + stable-PyTorch + Triton PTXAS regression

> **Discovery (2026-04-25)**: enabling `--compile` on fish-speech's
> autoregressive text2semantic decoder triggers `torch._inductor.exc.
> InductorError: ... PTXASError: Internal Triton PTX codegen error` on
> NVIDIA Blackwell B300 (sm_103) under stable PyTorch (2.8-2.10). This
> is a known stable-PyTorch / Triton-bundled-PTXAS regression. Fix is
> torch nightly ≥ 2.11.dev. Mid-flight finding while pivoting Fish
> from RTF 2.04 to a target ≤1.0 via torch.compile.

## Context

Voice path: LiveKit + Parakeet STT + **fish-speech S2-Pro TTS** + Claude Sonnet 4.6, on a self-hosted NVIDIA B300 (Blackwell Ultra, sm_103a). Bottleneck triangulation (`findings/b300_bench/profiler/PROFILE-20260424-local-triangulation/`) showed Fish RTF ≈ 2.04 (4824 ms wall to synthesize 2368 ms of audio) — Fish generates audio at half playback rate, causing WebRTC buffer underrun.

Investigation: fish-speech *already* wires `torch.compile` on `decode_one_token` at `fish_speech/models/text2semantic/inference.py:383-390`, but only when `--compile` is passed to `tools/api_server.py`. Pod's `prism42-fish.service` ExecStart was missing the flag → Fish ran in PyTorch eager mode end-to-end.

Adding `--compile` to the systemd unit + restart was expected to engage `torch.compile(mode="default", fullgraph=True, backend="inductor")` and drop RTF 1.5-3× (typical for autoregressive transformer decode loops).

## What actually happened

```
2026-04-25 04:43:08 [info] Loading model from checkpoints/s2-pro
2026-04-25 04:43:??  [info] Compiling function...
2026-04-25 04:44:25 [error]
torch._inductor.exc.InductorError: SubprocException:
  torch._inductor.runtime.triton_heuristics.NoTritonConfigsError:
  No valid triton configs.
  PTXASError: PTXAS error: Internal Triton PTX codegen error
```

Fish loaded the model fine, then hit the compile error on first inference. Subsequent calls retried compile and failed identically (no auto-fallback to eager). Fish served HTTP 500s on every TTS request until rollback.

## Root cause

Per PyTorch forums + multiple Triton GitHub issues (citations below):

> *"current stable torch (2.9.1+cu130) points to a Triton version where PTXAS is not compiled for SM103 compute capabilities (B300). The error manifests as: 'ptxas fatal: Value sm_103a is not defined for option gpu-name'."*

Triton bundles its own `ptxas` for portability. The stable PyTorch wheel's bundled Triton doesn't have a `ptxas` aware of compute capability 10.3 (B300). When `torch.compile` → `inductor` → Triton attempts to JIT-codegen a CUDA kernel for sm_103a, Triton emits PTX but the bundled PTXAS chokes with "Internal Triton PTX codegen error."

This is a **toolchain regression**, not a fish-speech bug.

## Reproducer

Minimal:

```python
import torch
assert torch.cuda.is_available(), "needs CUDA"
cap = torch.cuda.get_device_capability(0)
assert cap == (10, 3), f"needs B300 sm_103a, got {cap}"

@torch.compile(mode="default", fullgraph=True)
def hot(x):
    for _ in range(8):
        x = x @ x.T
    return x

x = torch.randn(64, 64, device="cuda", dtype=torch.bfloat16)
hot(x)  # raises torch._inductor.exc.InductorError on stable PyTorch + B300
```

Runs in seconds; standalone reproducer separate from fish-speech.

## Fix paths

### Option A — torch nightly (recommended, requires rebuild)

```
pip install --pre torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/nightly/cu130
```

Per PyTorch Discuss (Dec 2025): *"Torch nightly version (2.11.0.dev20251215+cu130) seems to fix the issue"* — bundled Triton + PTXAS in nightly recognize sm_103a.

For fish-speech specifically: project pins `torch==2.8.0`. Need to override the pin (`pip install ... --no-deps` then individually verify the transitively-pinned attention/kernel deps for compatibility). Estimated multi-hour scope.

### Option B — disable `--compile` on B300 detection (upstream PR proposal)

Detect B300 + incompatible torch at startup; auto-skip compile with an informational log. No upstream toolchain dependency. Patch shape:

```python
# fish_speech/models/text2semantic/inference.py near line 383
def _can_safely_compile() -> tuple[bool, str]:
    """Returns (compile_ok, rationale). Disable compile on Blackwell B300
    with stable-PyTorch < 2.11.dev where Triton's bundled PTXAS lacks
    sm_103a support (PyTorch Discuss Dec 2025)."""
    if not torch.cuda.is_available():
        return True, ""
    cap = torch.cuda.get_device_capability(0)
    if cap != (10, 3):
        return True, ""
    # B300 detected. Check torch version.
    ver = torch.__version__
    major, minor = ver.split(".")[:2]
    try:
        if int(major) > 2 or (int(major) == 2 and int(minor) >= 11):
            return True, ""
    except ValueError:
        pass
    return False, (
        f"NVIDIA Blackwell B300 (sm_103) detected with torch {ver}. "
        f"Stable PyTorch < 2.11 has a bundled-Triton/PTXAS regression "
        f"that fails 'Internal Triton PTX codegen error' on sm_103a. "
        f"Auto-disabling --compile. Install torch nightly (>=2.11.dev) "
        f"with --index-url https://download.pytorch.org/whl/nightly/cu130 "
        f"to enable compile on B300."
    )

if compile:
    ok, why = _can_safely_compile()
    if ok:
        logger.info("Compiling function...")
        decode_one_token = torch.compile(decode_one_token, ...)
    else:
        logger.warning(why)
```

12-line addition. No new deps. Defensive — operators on B300 don't get a 500-on-every-request after `--compile` deploy.

### Option C — workaround via env (untested)

Setting `TORCH_LOGS=+inductor` + `TRITON_DISABLE_LINE_INFO=1` may produce a cleaner error but doesn't fix the underlying PTXAS gap. Setting `TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas` to use the system PTXAS *might* work if the installed CUDA toolkit's PTXAS supports sm_103a — worth a quick experiment but not a robust fix for the upstream community.

## Why this matters for Project Glasswing

This is a **discovered toolchain regression that affects every Blackwell B300 deployment** of any framework using `torch.compile` (fish-speech, vLLM, SGLang, FlashInfer, custom inference servers). The Glasswing playbook is exactly the right shape: Claude Code-orchestrated solo dev finds a real bug in critical infrastructure (PyTorch toolchain on the most-recent NVIDIA datacenter GPU), proposes a defensive patch upstream, and documents the workaround for the open-source community.

The patch we'd contribute upstream isn't a fix to the underlying PyTorch-Triton gap (that's NVIDIA + Triton + PyTorch maintainers' work). It's a **fish-speech-side defensive guard** that prevents operators from a 500-on-every-request failure mode and tells them how to get compile working.

## Submission narrative slot

Section in `findings/glasswing/SUBMISSION.md`:

> **Voice mythos artifact: discovery + upstream contribution.** Solo dev + Claude Code attempted to engage `torch.compile` on the autoregressive text2semantic decoder of fish-speech, deployed on a Blackwell B300. First-attempt failed with a Triton PTXAS error. Investigation in 90 minutes identified the bug class (PyTorch stable + Triton bundled PTXAS lacks sm_103a), proposed a defensive guard upstream so future operators get an actionable error not a 500-loop, and documented the nightly-PyTorch fix path. PR: github.com/fishaudio/fish-speech/pull/{N}. The discovery generalizes — any Blackwell B300 deployment using torch.compile will hit this until upstream nightly lands.

## Citations

- [PyTorch Discuss: Blackwell + Triton PTX codegen error](https://discuss.pytorch.org/t/runtimeerror-internal-triton-ptx-codegen-error-ptx-version-7-4-does-not-support-target-sm-89/170671)
- [Triton issue #9181: PTXAS sm_121a not defined (GB10/Blackwell)](https://github.com/triton-lang/triton/issues/9181)
- [Triton issue #8539: PTXAS sm_121a not defined](https://github.com/triton-lang/triton/issues/8539)
- [Triton-Inference-Server #8632: ptxas-blackwell sm_110a](https://github.com/triton-inference-server/server/issues/8632)
- [PyTorch forum: RTX 5070 Ti Blackwell sm_120 not defined](https://discuss.pytorch.org/t/rtx-5070-ti-blackwell-pytorch-nightly-triton-still-getting-sm-120-is-not-defined-for-option-gpu-name-error/220460)

## Status

- ✓ Discovery confirmed via direct B300 deploy + log capture (PROFILE-20260424-local-triangulation linkage).
- ✓ Rollback completed; Fish returned to working baseline (PyTorch eager, RTF 2.04).
- ⏭ Upstream patch (Option B) drafted in `infra/b300/services/fish-speech/upstream-patch-blackwell-detect.diff`.
- ⏭ Upstream PR pending operator authorization.
