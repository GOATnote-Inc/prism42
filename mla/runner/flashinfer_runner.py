"""Real FlashInfer MLA runner + torch reference + benchmark harness.

Exposes three public surfaces:
    run_flashinfer_mla_decode(...)   - single call via BatchMLAPagedAttentionWrapper.
    benchmark_flashinfer_mla(...)    - timed sweep using torch.cuda.Event, matches
                                       the contract of runner.numpy_runner.benchmark
                                       (same BenchmarkResult dataclass).
    FlashInferMLAHarness              - stateful wrapper that holds the allocated
                                       workspace, planned layout, and inputs, so
                                       the evolve loop can call it repeatedly.

FlashInfer's MLA expects the **absorbed** form: q_nope has dim kv_lora_rank (not
qk_nope_head_dim), and the output shares that shape. DeepSeek-V2/V3 dims:
    num_heads=128, kv_lora_rank=512, qk_rope_head_dim=64

CUTLASS backend extra constraint: num_heads must be 128, total head dim 576,
block_num % (128 / page_size) == 0. See flashinfer/mla/_core.py:_check_cutlass_shape.

Multi-GPU: picks the current torch.cuda device (respects CUDA_VISIBLE_DEVICES).

API verified against flashinfer-ai/flashinfer main on 2026-04-22.
"""
from __future__ import annotations

import os
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import torch
    _HAVE_TORCH = True
except ImportError:
    torch = None  # type: ignore
    _HAVE_TORCH = False

try:
    import flashinfer  # noqa: F401
    import flashinfer.mla as _fi_mla
    _HAVE_FLASHINFER = True
except ImportError:
    _fi_mla = None  # type: ignore
    _HAVE_FLASHINFER = False


# ---- DeepSeek MLA dims (fixed by FlashInfer CUTLASS backend) ----
DEEPSEEK_NUM_HEADS = 128
DEEPSEEK_KV_LORA_RANK = 512    # head_dim_ckv
DEEPSEEK_QK_ROPE_DIM = 64      # head_dim_kpe
DEEPSEEK_HEAD_DIM_TOTAL = DEEPSEEK_KV_LORA_RANK + DEEPSEEK_QK_ROPE_DIM  # 576


def have_flashinfer() -> bool:
    return _HAVE_FLASHINFER


def have_cuda() -> bool:
    return _HAVE_TORCH and torch.cuda.is_available()


def require_gpu_environment() -> None:
    if not _HAVE_TORCH:
        raise RuntimeError("torch not installed; pip install torch")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available on this host")
    if not _HAVE_FLASHINFER:
        raise RuntimeError("flashinfer not installed; pip install flashinfer-python")


# ---- Benchmark result — binary-compatible with runner.numpy_runner.BenchmarkResult ----

@dataclass
class BenchmarkResult:
    mean_ns: float
    median_ns: float
    p90_ns: float
    std_ns: float
    iters: int
    tokens_per_sec: float
    raw_ns: list[int] = field(default_factory=list)

    @property
    def mean_s(self) -> float:
        return self.mean_ns / 1e9

    @property
    def median_s(self) -> float:
        return self.median_ns / 1e9


# ---- Helpers: paged layout construction ----

def _build_paged_layout(
    batch_size: int,
    kv_len_per_seq: int,
    page_size: int,
    device,
    *,
    dtype_ckv,
) -> dict:
    """Build the page-table / indptr / indices / kv_len tensors for a uniform
    per-seq kv_len. Returns dict suitable for BatchMLAPagedAttentionWrapper.plan().

    Layout: contiguous page assignment, no sharing, no padding beyond ceil
    to page_size. num_pages = ceil(kv_len / page_size) per seq, total =
    batch_size * pages_per_seq.
    """
    assert kv_len_per_seq > 0
    assert page_size > 0
    pages_per_seq = (kv_len_per_seq + page_size - 1) // page_size
    total_pages = batch_size * pages_per_seq

    # qo_indptr: for decode each query is length 1 -> [0,1,2,...,B]
    qo_indptr = torch.arange(batch_size + 1, dtype=torch.int32, device=device)
    # kv_indptr: prefix sums of per-seq pages -> [0, P, 2P, ..., B*P]
    kv_indptr = torch.arange(
        0, (batch_size + 1) * pages_per_seq, pages_per_seq,
        dtype=torch.int32, device=device,
    )
    # kv_indices: flat list of page indices, contiguous
    kv_indices = torch.arange(total_pages, dtype=torch.int32, device=device)
    # kv_len_arr: actual kv length for each request (B,)
    kv_len_arr = torch.full(
        (batch_size,), kv_len_per_seq, dtype=torch.int32, device=device,
    )
    # page_table: (B, pages_per_seq) for CUTLASS path
    page_table = kv_indices.view(batch_size, pages_per_seq).contiguous()
    return {
        "qo_indptr": qo_indptr,
        "kv_indptr": kv_indptr,
        "kv_indices": kv_indices,
        "kv_len_arr": kv_len_arr,
        "page_table": page_table,
        "total_pages": total_pages,
        "pages_per_seq": pages_per_seq,
    }


# ---- Torch reference (absorbed form; runs on GPU for fair compare) ----

def torch_mla_decode_absorbed(
    q_nope,       # (B, H, 512)  — already W_UK-merged (absorbed)
    q_pe,         # (B, H, 64)
    ckv,          # (B, T, 512)
    kpe,          # (B, T, 64)
    sm_scale: float,
):
    """Reference MLA decode in absorbed form. Matches FlashInfer's output
    shape (B, H, 512). Tests agreement vs flashinfer.

    Note: runs in float32 on GPU; caller can cast inputs to match
    flashinfer's dtype before calling (bf16/fp16)."""
    # Promote to float32 for a stable reference regardless of input dtype.
    q_nope_f = q_nope.float()
    q_pe_f = q_pe.float()
    ckv_f = ckv.float()
    kpe_f = kpe.float()
    scores = (
        torch.einsum("bhd,btd->bht", q_nope_f, ckv_f)
        + torch.einsum("bhd,btd->bht", q_pe_f, kpe_f)
    ) * float(sm_scale)
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    out = torch.einsum("bht,btd->bhd", w, ckv_f)
    return out  # (B, H, 512) float32


# ---- Harness ----

@dataclass
class FlashInferMLAConfig:
    batch_size: int = 1
    kv_len: int = 1024
    page_size: int = 64
    num_heads: int = DEEPSEEK_NUM_HEADS
    head_dim_ckv: int = DEEPSEEK_KV_LORA_RANK
    head_dim_kpe: int = DEEPSEEK_QK_ROPE_DIM
    causal: bool = False
    sm_scale: Optional[float] = None  # None -> 1/sqrt(head_dim_ckv + head_dim_kpe)
    q_dtype: str = "bfloat16"    # "bfloat16" | "float16"
    kv_dtype: str = "bfloat16"
    backend: str = "auto"        # "auto" | "fa2" | "fa3" | "cutlass"
    workspace_mb: int = 128
    use_cuda_graph: bool = False

    @property
    def effective_sm_scale(self) -> float:
        if self.sm_scale is not None:
            return float(self.sm_scale)
        import math
        return 1.0 / math.sqrt(self.head_dim_ckv + self.head_dim_kpe)


def _dtype_from_name(name: str):
    if not _HAVE_TORCH:
        raise RuntimeError("torch not installed")
    d = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if name not in d:
        raise ValueError(f"unknown dtype {name!r}; supported: {sorted(d)}")
    return d[name]


class FlashInferMLAHarness:
    """Stateful MLA harness. Allocates workspace + cache, plans once, runs
    repeatedly. Designed for the evolve loop: the same harness can be reused
    across candidates since all candidates share the FlashInfer call site."""

    def __init__(self, cfg: FlashInferMLAConfig, *, device: Optional[str] = None, seed: int = 0):
        require_gpu_environment()
        self.cfg = cfg
        self.device = torch.device(device) if device else torch.device(f"cuda:{torch.cuda.current_device()}")
        torch.cuda.set_device(self.device)
        self._gen = torch.Generator(device=self.device).manual_seed(seed)

        self.q_dtype = _dtype_from_name(cfg.q_dtype)
        self.kv_dtype = _dtype_from_name(cfg.kv_dtype)

        # Allocate workspace (128 MB by default per flashinfer doc).
        self.workspace = torch.empty(
            cfg.workspace_mb * 1024 * 1024,
            dtype=torch.uint8, device=self.device,
        )

        # Paged layout
        layout = _build_paged_layout(
            cfg.batch_size, cfg.kv_len, cfg.page_size, self.device,
            dtype_ckv=self.kv_dtype,
        )
        self.layout = layout

        # Allocate paged caches
        self.ckv_cache = torch.randn(
            layout["total_pages"], cfg.page_size, cfg.head_dim_ckv,
            dtype=torch.float32, generator=self._gen, device=self.device,
        ).to(self.kv_dtype)
        self.kpe_cache = torch.randn(
            layout["total_pages"], cfg.page_size, cfg.head_dim_kpe,
            dtype=torch.float32, generator=self._gen, device=self.device,
        ).to(self.kv_dtype)

        # Query tensors (absorbed form)
        self.q_nope = torch.randn(
            cfg.batch_size, cfg.num_heads, cfg.head_dim_ckv,
            dtype=torch.float32, generator=self._gen, device=self.device,
        ).to(self.q_dtype)
        self.q_pe = torch.randn(
            cfg.batch_size, cfg.num_heads, cfg.head_dim_kpe,
            dtype=torch.float32, generator=self._gen, device=self.device,
        ).to(self.q_dtype)

        # Wrapper — when use_cuda_graph=True, FlashInfer requires the
        # qo_indptr/kv_indptr/kv_indices/kv_len_arr buffers at construction
        # so .plan() can copy_() into them deterministically (per
        # flashinfer/mla/_core.py docstring). Passing them only to .plan()
        # triggers "AttributeError: 'NoneType'.copy_" because the wrapper
        # expects pre-reserved buffers.
        if cfg.use_cuda_graph:
            self.wrapper = _fi_mla.BatchMLAPagedAttentionWrapper(
                float_workspace_buffer=self.workspace,
                use_cuda_graph=True,
                qo_indptr=layout["qo_indptr"],
                kv_indptr=layout["kv_indptr"],
                kv_indices=layout["kv_indices"],
                kv_len_arr=layout["kv_len_arr"],
                backend=cfg.backend,
            )
        else:
            self.wrapper = _fi_mla.BatchMLAPagedAttentionWrapper(
                float_workspace_buffer=self.workspace,
                use_cuda_graph=False,
                backend=cfg.backend,
            )
        if cfg.backend != "cutlass":
            # Non-cutlass backends need plan()
            self.wrapper.plan(
                qo_indptr=layout["qo_indptr"],
                kv_indptr=layout["kv_indptr"],
                kv_indices=layout["kv_indices"],
                kv_len_arr=layout["kv_len_arr"],
                num_heads=cfg.num_heads,
                head_dim_ckv=cfg.head_dim_ckv,
                head_dim_kpe=cfg.head_dim_kpe,
                page_size=cfg.page_size,
                causal=cfg.causal,
                sm_scale=cfg.effective_sm_scale,
                q_data_type=self.q_dtype,
                kv_data_type=self.kv_dtype,
            )

    def gather_cache_dense(self) -> tuple:
        """Materialize the paged cache into a dense (B, T, D) layout for the
        torch reference. Used by correctness check; not hot-path."""
        B = self.cfg.batch_size
        T = self.cfg.kv_len
        # page_table: (B, pages_per_seq); cache: (total_pages, page_size, D)
        pt = self.layout["page_table"]  # (B, P)
        def _gather(cache):
            # gather pages per seq, then slice to kv_len
            # out shape: (B, P*page_size, D) -> slice first T
            gathered = cache[pt]  # (B, P, page_size, D)
            B_, P, PS, D = gathered.shape
            return gathered.reshape(B_, P * PS, D)[:, :T, :].contiguous()
        ckv_dense = _gather(self.ckv_cache)
        kpe_dense = _gather(self.kpe_cache)
        return ckv_dense, kpe_dense

    def run(self) -> "torch.Tensor":
        """One MLA decode call. Returns output tensor shape (B, H, D_ckv)."""
        cfg = self.cfg
        if cfg.backend == "cutlass":
            out = self.wrapper.run(
                q_nope=self.q_nope,
                q_pe=self.q_pe,
                ckv_cache=self.ckv_cache,
                kpe_cache=self.kpe_cache,
                kv_len=self.layout["kv_len_arr"],
                page_table=self.layout["page_table"],
            )
        else:
            out = self.wrapper.run(
                q_nope=self.q_nope,
                q_pe=self.q_pe,
                ckv_cache=self.ckv_cache,
                kpe_cache=self.kpe_cache,
            )
        return out

    # ---- CUDA Graph path (H6.1) ----

    def prepare_cuda_graph(self) -> "torch.cuda.CUDAGraph":
        """Capture a CUDA Graph of one MLA decode call for fast replay.

        Requires cfg.use_cuda_graph=True at construction. Pre-allocates
        output buffer; the wrapper writes into it on replay. Fixed-shape:
        the captured graph is only valid for the exact (batch, kv_len,
        num_heads, head_dim_ckv, head_dim_kpe) it was captured with.

        Returns the captured graph; caller replays via run_graph().
        """
        if not self.cfg.use_cuda_graph:
            raise RuntimeError(
                "prepare_cuda_graph requires cfg.use_cuda_graph=True at construction"
            )
        # Pre-allocate output buffer; shape matches q_nope.
        self._graph_output = torch.empty_like(self.q_nope)

        # Warmup (untimed; populates any lazy-allocated state inside wrapper).
        for _ in range(3):
            _ = self._run_into_buffer(self._graph_output)
        torch.cuda.synchronize()

        # Capture.
        self._graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self._graph):
            _ = self._run_into_buffer(self._graph_output)
        torch.cuda.synchronize()
        return self._graph

    def _run_into_buffer(self, out_buf):
        """Internal: run wrapper with out=out_buf. Used both in warmup and
        during graph capture."""
        cfg = self.cfg
        if cfg.backend == "cutlass":
            return self.wrapper.run(
                q_nope=self.q_nope, q_pe=self.q_pe,
                ckv_cache=self.ckv_cache, kpe_cache=self.kpe_cache,
                kv_len=self.layout["kv_len_arr"],
                page_table=self.layout["page_table"],
                out=out_buf,
            )
        return self.wrapper.run(
            q_nope=self.q_nope, q_pe=self.q_pe,
            ckv_cache=self.ckv_cache, kpe_cache=self.kpe_cache,
            out=out_buf,
        )

    def run_graph(self) -> "torch.Tensor":
        """Replay the captured CUDA Graph. Must call prepare_cuda_graph() first."""
        if not hasattr(self, "_graph"):
            raise RuntimeError("run_graph: call prepare_cuda_graph() first")
        self._graph.replay()
        return self._graph_output

    def run_torch_reference(self) -> "torch.Tensor":
        """Torch absorbed-form reference. float32 on GPU."""
        ckv_dense, kpe_dense = self.gather_cache_dense()
        return torch_mla_decode_absorbed(
            self.q_nope, self.q_pe, ckv_dense, kpe_dense,
            sm_scale=self.cfg.effective_sm_scale,
        )

    def verify_matches_reference(self, *, rtol: float = 5e-2, atol: float = 5e-2) -> dict:
        """Run both kernels and compare. bf16/fp16 tolerance is generous
        (5e-2) because absorbed vs. naive reduction order differs across
        backends. What we care about is distribution agreement."""
        out_fi = self.run().float()
        out_ref = self.run_torch_reference().float()
        max_err = (out_fi - out_ref).abs().max().item()
        mean_err = (out_fi - out_ref).abs().mean().item()
        rel_err = max_err / (out_ref.abs().max().item() + 1e-8)
        passed = max_err <= atol + rtol * out_ref.abs().max().item()
        return {
            "passed": bool(passed), "max_abs_error": float(max_err),
            "mean_abs_error": float(mean_err), "relative_error": float(rel_err),
            "out_shape": tuple(out_fi.shape), "out_dtype": str(out_fi.dtype),
        }


# ---- Benchmark (CUDA-event based) ----

def benchmark_flashinfer_mla(
    harness: FlashInferMLAHarness,
    *,
    warmup: int = 10,
    iters: int = 100,
) -> BenchmarkResult:
    """Benchmark using torch.cuda.Event for accurate GPU timing. Each iter
    does one full MLA decode call; no batching of iters."""
    if not have_cuda():
        raise RuntimeError("benchmark requires CUDA")
    # Warmup
    for _ in range(warmup):
        harness.run()
    torch.cuda.synchronize()

    starts = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    ends = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for i in range(iters):
        starts[i].record()
        harness.run()
        ends[i].record()
    torch.cuda.synchronize()

    times_ms = [starts[i].elapsed_time(ends[i]) for i in range(iters)]
    samples = [int(t * 1e6) for t in times_ms]  # ns
    mean = statistics.fmean(samples)
    median = statistics.median(samples)
    p90 = sorted(samples)[int(len(samples) * 0.9) - 1]
    std = statistics.stdev(samples) if len(samples) > 1 else 0.0
    tps = (harness.cfg.batch_size / (median / 1e9)) if median > 0 else 0.0
    return BenchmarkResult(
        mean_ns=mean, median_ns=median, p90_ns=float(p90), std_ns=std,
        iters=iters, tokens_per_sec=tps, raw_ns=samples,
    )


def run_flashinfer_mla_decode(cfg: FlashInferMLAConfig, *, seed: int = 0) -> dict:
    """Single-shot entry point: allocate harness, run once, verify, bench.
    Returns a dict suitable for JSON serialization. Used by the verify script."""
    harness = FlashInferMLAHarness(cfg, seed=seed)
    verify = harness.verify_matches_reference()
    bench = benchmark_flashinfer_mla(harness, warmup=5, iters=50)
    return {
        "config": {
            "batch_size": cfg.batch_size, "kv_len": cfg.kv_len,
            "page_size": cfg.page_size, "num_heads": cfg.num_heads,
            "head_dim_ckv": cfg.head_dim_ckv, "head_dim_kpe": cfg.head_dim_kpe,
            "q_dtype": cfg.q_dtype, "kv_dtype": cfg.kv_dtype,
            "backend": cfg.backend, "sm_scale": cfg.effective_sm_scale,
        },
        "verify": verify,
        "bench": {
            "mean_ns": bench.mean_ns, "median_ns": bench.median_ns,
            "p90_ns": bench.p90_ns, "std_ns": bench.std_ns,
            "iters": bench.iters, "tokens_per_sec": bench.tokens_per_sec,
        },
    }


# ---- Environment report ----

def environment_report() -> dict:
    """Collect an environment snapshot — useful at the top of every verify run."""
    info: dict[str, Any] = {
        "have_torch": _HAVE_TORCH,
        "have_flashinfer": _HAVE_FLASHINFER,
        "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "unset"),
    }
    if _HAVE_TORCH:
        info["torch_version"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["cuda_device_count"] = torch.cuda.device_count()
            info["current_device"] = torch.cuda.current_device()
            info["device_name"] = torch.cuda.get_device_name(torch.cuda.current_device())
            info["cc"] = torch.cuda.get_device_capability(torch.cuda.current_device())
            info["cuda_runtime_version"] = torch.version.cuda
    if _HAVE_FLASHINFER:
        info["flashinfer_version"] = getattr(flashinfer, "__version__", "unknown")
    return info
