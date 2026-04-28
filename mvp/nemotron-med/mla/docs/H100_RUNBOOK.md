# H100 Runbook

One-time-per-pod setup, then one command produces a parseable verification
block. Parallel pods are fine — each sets its own `CUDA_VISIBLE_DEVICES`.

## Preconditions
- RunPod Secure Cloud H100 (SXM or PCIe). 80 GB or 94 GB HBM.
- Container image: any PyTorch/CUDA 12.4+ image will do. RunPod's
  `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` has been used.
- `sudo` access if you want `ncu` counters. RunPod Secure Cloud grants
  `SYS_ADMIN` by default; Community Cloud may lock counters host-side.

## One-time setup
```bash
cd /workspace             # or wherever your repo is mounted
git clone <repo_url> prism-mla && cd prism-mla
bash scripts/setup_h100.sh
```

Creates `.venv/`, installs torch (cu124 wheel), `flashinfer-python`,
numpy, pytest. Prints a one-line sanity confirmation. Re-run safely.

## Verification
```bash
bash scripts/verify_h100.sh
```

Output block:
```
=== PRISM-MLA H100 VERIFY BEGIN ===
pwd: ...
CUDA_VISIBLE_DEVICES: 0
backend: auto
kv_len: 1024
--- checks ---
[PASS] nvidia-smi               :: NVIDIA H100 80GB HBM3, 550.90.07, 81559
[PASS] nvcc                     :: release 12.4
[PASS] venv python              :: Python 3.11.x at .venv
[PASS] import torch             :: 2.4.0 cuda=True device=... cc=(9, 0)
[PASS] import flashinfer.mla    :: v0.2.x wrapper_class=True
[PASS] cpu test suite           :: 74 passed in ...s
[PASS] cuda smoke               :: max_err=1.2e-03 median=XXX.Xus p90=XXX.Xus tok/s=XXXX
[PASS] ncu --list-sets          :: 23 sets available
[PASS] nsys --version           :: NVIDIA Nsight Systems version 2024.X
=== PRISM-MLA H100 VERIFY END (9 pass, 0 fail) ===
```

Exit code equals the number of failed checks.

## Parallel pod pattern
Terminal A on pod A (H100 #0):
```bash
CUDA_VISIBLE_DEVICES=0 bash scripts/verify_h100.sh
```
Terminal B on a *different* pod (H100 #1):
```bash
CUDA_VISIBLE_DEVICES=0 bash scripts/verify_h100.sh     # #0 of THAT pod
```
Within one pod with 2 GPUs:
```bash
CUDA_VISIBLE_DEVICES=0 bash scripts/verify_h100.sh &
CUDA_VISIBLE_DEVICES=1 bash scripts/verify_h100.sh
```

The harness honors `CUDA_VISIBLE_DEVICES` through torch. No code change
required.

## Backend selector
```bash
PRISM_BACKEND=cutlass bash scripts/verify_h100.sh
PRISM_BACKEND=fa3     bash scripts/verify_h100.sh
PRISM_BACKEND=fa2     bash scripts/verify_h100.sh
PRISM_BACKEND=auto    bash scripts/verify_h100.sh   # default
```

The CUTLASS path has the fixed-shape constraint `num_heads=128, total head
dim=576, block_num % (128/page_size) == 0`. The verify script's default
`kv_len=1024, page_size=64` satisfies this.

## Interpreting the smoke line
`max_err` is `torch_ref − flashinfer`, both in float32. For bf16 inputs,
expect roughly 1e-3 to 5e-3. `median` is per-decode latency in
microseconds. `tok/s` is `batch_size / median` (batch=1 by default).

## Failure modes and recovery
- `[FAIL] import flashinfer.mla`: run `setup_h100.sh` again; wheel may need
  rebuilding for the current torch.
- `[FAIL] cuda smoke :: verify failed max_err=X`: bf16 tolerance is set to
  5e-2 absolute; if it exceeds that, check `backend` choice. The CUTLASS
  path uses a different reduction order than the reference implementation so max_err varies.
- `[FAIL] ncu --list-sets :: permission denied`: host has
  `NVreg_RestrictProfilingToAdminUsers=1`. Either re-launch on Secure Cloud
  or run `sudo bash scripts/verify_h100.sh`.

## Paste format for bug reports
Copy the entire `=== BEGIN === ... === END ===` block. Exit code is the
fail count; a paste with `END (N pass, 0 fail)` is green across the board.
