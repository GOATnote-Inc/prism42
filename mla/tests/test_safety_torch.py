"""Tests for compile_candidate_torch — the wider torch namespace must not
become a sandbox escape.

These run on any host; the torch-bound tests are skipped when torch isn't
importable locally. The banned-token checks always run.
"""
from __future__ import annotations

import pytest

from agent.safety import UnsafeSourceError, compile_candidate_torch


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


GOOD_TORCH = """
def mla_decode_candidate(q_nope, q_pe, ckv, kpe, sm_scale):
    q_cat = torch.cat([q_nope, q_pe], dim=-1)
    k_cat = torch.cat([ckv, kpe], dim=-1)
    scores = torch.einsum("bhd,btd->bht", q_cat, k_cat) * sm_scale
    scores = scores - scores.amax(dim=-1, keepdim=True)
    w = torch.softmax(scores, dim=-1)
    return torch.einsum("bht,btd->bhd", w, ckv)
""".strip()


@pytest.mark.skipif(not _torch_available(), reason="torch not installed")
def test_compile_candidate_torch_accepts_clean():
    fn = compile_candidate_torch(GOOD_TORCH)
    assert callable(fn)


@pytest.mark.parametrize("bad_snippet", [
    "torch.save(ckv, '/tmp/x.pt')",
    "torch.load('/tmp/x.pt')",
    "torch.jit.load('model.pt')",
    "torch.ops.load_library('libfoo.so')",
    "torch.utils.cpp_extension.load_inline(...)",
    "torch.hub.load('user/repo', 'model')",
    "torch.distributed.all_reduce(x)",
    "torch.multiprocessing.Queue()",
    "torch._C._jit_pass",
    "torch.classes.foo",
    "torch.fx.wrap",
])
def test_compile_candidate_torch_rejects_dangerous_torch_apis(bad_snippet):
    # Inject snippet into an otherwise-valid function body.
    src = GOOD_TORCH.replace("q_cat = torch.cat", f"_ = {bad_snippet}\n    q_cat = torch.cat")
    with pytest.raises(UnsafeSourceError):
        compile_candidate_torch(src)


def test_compile_candidate_torch_rejects_import():
    src = "import torch\n" + GOOD_TORCH
    with pytest.raises(UnsafeSourceError):
        compile_candidate_torch(src)


def test_compile_candidate_torch_rejects_missing_function():
    src = "x = 1"
    with pytest.raises(UnsafeSourceError):
        compile_candidate_torch(src)


def test_compile_candidate_torch_rejects_syntax_error():
    src = "def mla_decode_candidate("
    with pytest.raises(UnsafeSourceError):
        compile_candidate_torch(src)


@pytest.mark.skipif(not _torch_available(), reason="torch not installed")
def test_compile_candidate_torch_binds_F_as_functional():
    """A candidate using F.scaled_dot_product_attention should compile."""
    src = """
def mla_decode_candidate(q_nope, q_pe, ckv, kpe, sm_scale):
    B, H, D = q_nope.shape
    T = ckv.shape[1]
    q_cat = torch.cat([q_nope, q_pe], dim=-1).unsqueeze(2)
    k_cat = torch.cat([ckv, kpe], dim=-1).unsqueeze(1).expand(B, H, T, D + q_pe.shape[-1])
    v = ckv.unsqueeze(1).expand(B, H, T, D)
    out = F.scaled_dot_product_attention(q_cat, k_cat, v, scale=sm_scale)
    return out.squeeze(2)
""".strip()
    fn = compile_candidate_torch(src)
    assert callable(fn)
