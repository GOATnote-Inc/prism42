# Phase C+D Pre-flight Checklist — B300 Nemotron NVFP4

**Date**: 2026-04-25
**Pod**: prism-mla-b300-h4h5 (31.22.104.100, user: shadeform)
**venv-nightly path**: `/opt/prism42/infra/b300/services/fish-speech/.venv-nightly`
**Probed by**: pre-flight agent (Sonnet 4.6)

---

## Summary: 3 BLOCKERS, 4 WARNINGS

| # | Item | Status |
|---|------|--------|
| 1 | HF_TOKEN valid | **FAIL — BLOCKER** |
| 2 | Model ungated (no token needed) | **PASS** |
| 3 | Disk / free space | **PASS** |
| 4 | Port 8001 free | **PASS** |
| 5 | Port 8000 free | **PASS** |
| 6 | nano_v3_reasoning_parser.py URL alive | **PASS** |
| 7 | nano_v3_reasoning_parser.py on pod | **FAIL — BLOCKER** |
| 8 | vLLM 0.20.* available in pip index | **FAIL — BLOCKER** |
| 9 | vLLM installed in .venv-nightly | UNVERIFIED (not installed yet) |
| 10 | flashinfer-python available | **PASS** (0.6.9 latest) |
| 11 | flashinfer installed in .venv-nightly | UNVERIFIED (not installed yet) |
| 12 | GPU memory headroom for co-residency | **PASS** |
| 13 | Triton sm_103a support | **PASS** (via ptxas-blackwell, PTX >= 8.8) |
| 14 | VLLM_USE_FLASHINFER_MOE_FP4 documented | **PASS** |
| 15 | HF repo gated field | **PASS** (ungated, no token required) |
| 16 | vllm service dir exists | **FAIL — WARNING** |
| 17 | Fish + Parakeet GPU footprint | **WARNING** (Fish 19.6 GB, higher than 8 GB projected) |

---

## Detailed Results

### Item 1 — HF_TOKEN access

**Status: FAIL — BLOCKER**

```
command: set -a && source /opt/prism42/agents/livekit/.env && set +a && \
         curl -sf https://huggingface.co/api/whoami -H "Authorization: Bearer $HF_TOKEN"
output:  HTTP/2 401
         {"error":"Invalid username or password."}
         HF_TOKEN first 12 chars: hf_ocnXEGdJy...
```

The token exists in `.env` and is sourced correctly, but is **invalid / revoked**. HF whoami returns 401.

**Mitigation**: Item 2 below shows the NVFP4 repo is ungated — `HF_TOKEN` is NOT required for weight download (`config.json` downloads HTTP 200 without a token). However, `huggingface-cli` and vLLM's internal downloader respect `HF_TOKEN` if set and will fail fast on 401 before falling back. **The stale token must be removed or replaced before Phase D.**

Fix options:
- `unset HF_TOKEN` in the pod environment (and remove from `.env`) — model is ungated so no token needed.
- OR generate a new valid HF token at `https://huggingface.co/settings/tokens` and update `.env`.

---

### Item 2 — Model ungated (no token required)

**Status: PASS**

```
command: curl -sf -L -o /tmp/test_ungated.json -w 'HTTP %{http_code}' \
         https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/config.json
output:  HTTP 200
         model_type: nemotron_h
         size: 1817 bytes
```

```
command: curl -sf https://huggingface.co/api/models/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
output:  gated: False
         private: False
         file_count: 18
         files: ['.gitattributes', 'README.md', 'chat_template.jinja', 'config.json',
                 'configuration_nemotron_h.py', 'generation_config.json', 'hf_quant_config.json',
                 'model-00001-of-00005.safetensors', ..., 'nano_v3_reasoning_parser.py', ...]
```

The HF API returns `gated: False`. Download succeeds without a token. The `nano_v3_reasoning_parser.py` is present in the repo file list (18 files total including 5 safetensor shards).

**Note on HF API size field**: Total size showed 0 bytes in API response — this is a known quirk of the HF API (sizes are sometimes absent from metadata). The model card states 19.4 GB (5 shards: 4x~4 GB + 1x~3.34 GB).

---

### Item 3 — Disk / free space

**Status: PASS**

```
command: df -h /opt/prism42  (falls through to df -h /)
output:  Filesystem /dev/vda4   Size 5.7T   Used 337G   Avail 4.8T   Use% 7%
```

```
HF cache location: ~/.cache/huggingface (on same volume)
Current HF cache used: 176 GB
  - Qwen/Qwen2.5-72B-Instruct: 136 GB
  - Qwen/Qwen2.5-14B-Instruct: 28 GB
  - fishaudio/s2-pro: 11 GB
  - nvidia/parakeet-tdt-0.6b-v3: 2.4 GB
```

4.8 TB available. NVFP4 weights (~19.4 GB) will easily fit. No disk blocker.

---

### Item 4 — Port 8001 free

**Status: PASS**

```
command: ss -ltn | grep :8001
output:  (empty — port 8001 clear)
```

---

### Item 5 — Port 8000 free

**Status: PASS** (bonus check)

```
command: ss -ltn | grep :8000
output:  (empty — port 8000 also clear)
```

KB-23's serve script defaults to 8000; migration plan uses 8001. Both are clear.

---

### Item 6 — nano_v3_reasoning_parser.py URL alive

**Status: PASS**

```
command: curl -sSI -L https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py
output:  HTTP/2 307
         HTTP/2 200   (after redirect)
         content-type: text/plain; charset=utf-8
```

URL is live and returns 200 after a redirect. File is accessible without authentication.

---

### Item 7 — nano_v3_reasoning_parser.py on pod

**Status: FAIL — BLOCKER**

```
command: find /opt/prism42 -name 'nano_v3_reasoning_parser.py'
output:  (empty — NOT FOUND)

command: ls /opt/prism42/infra/b300/services/vllm/
output:  NOT EXISTS (directory does not exist)
```

The reasoning parser plugin must be present before `vllm serve` runs or it will fail with a plugin-load error. The target directory also does not exist yet.

Fix:
```bash
mkdir -p /opt/prism42/infra/b300/services/vllm
curl -L https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py \
  -o /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py
```
No HF token needed (ungated). This is a 5-second fix.

---

### Item 8 — vLLM 0.20.* in pip index

**Status: FAIL — BLOCKER**

```
command: .venv-nightly/bin/pip index versions vllm
output:  vllm (0.19.1)
         Available versions: 0.19.1, 0.19.0, 0.18.1, 0.18.0, ...
         [list ends at 0.1.0 — 0.20.x absent]

command: .venv-nightly/bin/pip show vllm
output:  WARNING: Package(s) not found: vllm
         (not installed)
```

**vLLM 0.20.0 was released 2026-04-23** (confirmed via GitHub releases API). It is NOT yet indexed in PyPI as seen by the pod's pip. This could be:
1. PyPI propagation lag (vLLM 0.20.0 was published ~24h before this probe)
2. pip cache on pod is stale

Verification:
```bash
.venv-nightly/bin/pip index versions vllm --no-cache-dir 2>&1 | head -3
```

If still absent, the wheel is available directly from GitHub:
```bash
# Option A: wait for PyPI propagation (check again in a few hours)
# Option B: install from GitHub release wheel (if NVIDIA provides one)
# Option C: install from source or nightly wheel per vLLM docs
```

**This is the most significant blocker** — Phase C cannot complete until vLLM 0.20.* is installable. 0.19.1 is available but lacks the `MXFP4 W4A4 CUTLASS MoE for SM100` kernels and `FlashInfer CuteDSL batched-experts backend for NVFP4 MoE` added in 0.20.

---

### Item 9 — vLLM installed in .venv-nightly

**Status: UNVERIFIED**

Not installed. Will be resolved when Item 8 (pip availability) is resolved and install runs in Phase C.

---

### Item 10 — flashinfer-python available in pip index

**Status: PASS**

```
command: .venv-nightly/bin/pip index versions flashinfer-python
output:  flashinfer-python (0.6.9)
         Available versions: 0.6.9, 0.6.8.post1, 0.6.8, 0.6.7.post3, ...

command: .venv-nightly/bin/pip show flashinfer-python
output:  WARNING: Package(s) not found: flashinfer-python
         (not installed — will be installed in Phase C)
```

Latest is 0.6.9. Wheel resolves. No version conflict detected (torch version compatibility not yet verified against vLLM's requirements — check after vLLM install).

---

### Item 11 — flashinfer installed in .venv-nightly

**Status: UNVERIFIED** — not installed yet. Pending Phase C.

---

### Item 12 — GPU memory headroom for co-residency

**Status: PASS**

```
command: nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits
output:  275040, 31766, 242348   (all in MiB)
         Total: 268.6 GB  Used: 31.0 GB  Free: 236.7 GB

command: nvidia-smi --query-compute-apps=pid,name,used_gpu_memory --format=csv,noheader
output:
  pid 173799, .venv/bin/python,        5834 MiB  (5.7 GB)  — likely Parakeet
  pid 217878, fish-speech/.venv/...,  20068 MiB (19.6 GB)  — Fish S2-Pro (see WARNING below)
  pid 236296, .venv/bin/python,        5828 MiB  (5.7 GB)  — likely LiveKit worker
```

Math for vLLM at `--gpu-memory-utilization 0.20`:
- vLLM claim: 275040 MiB × 0.20 = 55,008 MiB (53.7 GB)
- Free after current processes: 242,348 MiB (236.7 GB)
- 55,008 < 242,348: **headroom confirmed**

Co-residency is safe. The 0.20 utilization ceiling leaves ~181 GB untouched for Fish/Parakeet.

**WARNING**: Fish S2-Pro is consuming 19.6 GB, not the 8 GB projected in KB-23 §3. The migration-plan's co-residency table (Parakeet ~9 GB + Fish ~8 GB) is off; actual Fish footprint is ~2.5x the estimate. This does not block Phase D at `--gpu-memory-utilization 0.20` (55 GB ceiling) since 19.6 + 5.7 + 5.7 = 31 GB used, well within 236 GB free.

---

### Item 13 — Triton sm_103a support in .venv-nightly

**Status: PASS** (with important context)

```
command: .venv-nightly/bin/python -c 'import triton; print(triton.__version__)'
output:  3.7.0

command: .venv-nightly/bin/python -c 'import torch; print(torch.__version__, torch.version.cuda)'
output:  2.13.0.dev20260424+cu130  13.0

command: nvidia-smi | grep CUDA
output:  CUDA Version: 13.0   Driver: 580.126.09
```

**Triton uses a dedicated `ptxas-blackwell` binary for arch >= 100 (sm_100a, sm_103a):**
```
path: .venv-nightly/lib/.../triton/backends/nvidia/bin/ptxas-blackwell
built: Fri_Nov__7_07:21:27_PM_PST_2025
```

Direct test confirms `ptxas-blackwell` compiles sm_103a with PTX >= 8.8:
```
command: sm_arch_from_capability(103) → "sm_103a"
command: ptxas-blackwell -arch sm_103a test_ptx8.8.ptx → PASS
command: ptxas-blackwell -arch sm_103a test_ptx8.7.ptx → FAIL (PTX too old — not how Triton emits)
```

The standard `ptxas` binaries (system, torch-bundled, triton-bundled) all reject sm_103a — but Triton never calls them for arch >= 100. It routes to `ptxas-blackwell`, which handles sm_103a correctly. **Fish is live and running on this same Triton, confirming real-world functionality.**

**Implication for vLLM**: When vLLM installs into `.venv-nightly`, it inherits this Triton. If vLLM's kernel compilation paths are routed through Triton (as they are for non-FA4/non-FlashInfer ops), they will use `ptxas-blackwell` correctly. The `--enforce-eager` flag remains advisable on first boot to skip CUDA graph capture until verified.

---

### Item 14 — VLLM_USE_FLASHINFER_MOE_FP4 and VLLM_FLASHINFER_MOE_BACKEND documented

**Status: PASS**

```
command: curl -sf https://raw.githubusercontent.com/vllm-project/vllm/main/vllm/envs.py | grep -A3 FLASHINFER_MOE
output:
  VLLM_USE_FLASHINFER_MOE_FP4: bool = False   # "Allow use of FlashInfer NVFP4 MoE kernels"
  VLLM_FLASHINFER_MOE_BACKEND: Literal["throughput", "latency", "masked_gemm"] = "latency"
```

Both env vars exist in vLLM main branch. `VLLM_FLASHINFER_MOE_BACKEND` default is `"latency"` (not `"throughput"`). The migration plan sets `throughput` — this is correct for batch throughput but note that `"latency"` might actually be better for the single-caller PSAP voice use case. Both values are valid; test both after first boot.

vLLM 0.20.0 release notes confirm NVFP4 MoE additions:
- `MXFP4 W4A4 CUTLASS MoE for SM100` (#37463)
- `FlashInfer CuteDSL batched-experts backend for NVFP4 MoE` (#38251)
- `TRTLLM GEN NVFP4 MoE with non-512-aligned hidden dims via weight padding` (#39510)

v0.19.0 added `B300/GB300 (SM 10.3) support: Allreduce fusion enabled by default` (#37755, #37756).

---

### Item 15 — HF repo gated field

**Status: PASS** (see Item 2 — confirmed `gated: False`)

---

### Item 16 — vllm service directory

**Status: FAIL — WARNING**

```
command: ls /opt/prism42/infra/b300/services/vllm/
output:  NOT EXISTS
```

The target directory for `nano_v3_reasoning_parser.py` and future vLLM service files does not exist. Must be created before Phase C. Single `mkdir -p` command — not a hard blocker but will cause Phase C to fail silently if not created first.

---

### Item 17 — Fish GPU footprint vs projection

**Status: WARNING**

Fish S2-Pro actual: **19.6 GB** (nvidia-smi process query)
Migration plan table (KB-23 §3): ~8 GB

The footprint is ~2.5x higher. This does not threaten the 0.20 utilization plan (55 GB ceiling vs 236 GB free), but the KB-23 co-residency table should be updated. If `--gpu-memory-utilization` is bumped above 0.85 for more KV cache, check that Parakeet + Fish total (~31 GB) + vLLM (~233 GB at 0.85) doesn't OOM.

---

## Blocker Summary

| Priority | Blocker | Time to Fix | Fix |
|----------|---------|------------|-----|
| 1 (HIGH) | `vLLM 0.20.* not in pip index` | 1-24h (PyPI lag) | Re-run `pip index versions vllm --no-cache-dir`; if still absent, install from GitHub release assets or vLLM nightly wheel |
| 2 (HIGH) | `HF_TOKEN invalid (401)` | 5 min | `unset HF_TOKEN` + remove from `.env` (model is ungated) OR generate new token at huggingface.co/settings/tokens |
| 3 (LOW) | `nano_v3_reasoning_parser.py not on pod` | 30 sec | `mkdir -p /opt/prism42/infra/b300/services/vllm && curl -L https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/resolve/main/nano_v3_reasoning_parser.py -o /opt/prism42/infra/b300/services/vllm/nano_v3_reasoning_parser.py` |

---

## Recommended Fix Order

1. Fix HF_TOKEN (remove stale token from `.env`) — 5 min.
2. Download `nano_v3_reasoning_parser.py` — 30 sec.
3. Wait for / confirm vLLM 0.20.* in PyPI (`pip index versions vllm --no-cache-dir`). If absent after 24h, escalate to: install from `https://github.com/vllm-project/vllm/releases/tag/v0.20.0` wheel assets.
4. Once vLLM 0.20.* is available: `pip install vllm==0.20.* flashinfer-python --no-deps` inside `.venv-nightly`.
5. Verify: `vllm --version` → 0.20.x; `python -c 'import flashinfer'` → OK.
6. Phase D: launch with `--enforce-eager` on first boot.

---

## Go/No-Go for Phase D Install

**NO-GO.** Three blockers. Ordering: fix HF_TOKEN and nano_v3 parser now (both < 5 min), then wait for vLLM 0.20.* PyPI availability before running Phase C install.

---

*Probed: 2026-04-25 08:07 UTC. Pod uptime: Fish active since 04:46 UTC, Parakeet co-resident. GPU 39°C, 237W / 1100W, 0% util at probe time.*
