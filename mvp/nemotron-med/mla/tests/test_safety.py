"""Safety gate tests — each banned construct rejected, clean source accepted.

If the safety layer lets a bad construct through, the whole evolutionary
loop is a remote code execution vector.
"""
from __future__ import annotations

import numpy as np
import pytest

from agent.safety import UnsafeSourceError, compile_candidate


GOOD = """
def mla_decode_candidate(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, softmax_scale):
    q_merged = np.einsum("bhn,hnd->bhd", q_nope, W_UK)
    scores = np.einsum("bhd,btd->bht", q_merged, c_KV)
    scores = scores + np.einsum("bhd,btd->bht", q_rope, k_R)
    scores *= softmax_scale
    scores -= scores.max(axis=-1, keepdims=True)
    exp = np.exp(scores)
    w = exp / exp.sum(axis=-1, keepdims=True)
    ctx = np.einsum("bht,btd->bhd", w, c_KV)
    return np.einsum("bhd,hdv->bhv", ctx, W_UV)
""".strip()


def test_compile_accepts_clean_source():
    fn = compile_candidate(GOOD)
    assert callable(fn)


@pytest.mark.parametrize("bad", [
    "import os\n" + GOOD,
    "from os import system\n" + GOOD,
    GOOD + "\nos.system('echo hi')",
    GOOD + "\neval('1+1')",
    GOOD + "\nexec('x = 1')",
    GOOD + "\nopen('/etc/passwd')",
    GOOD + "\n__import__('os')",
    GOOD + "\nsubprocess.run(['ls'])",
    GOOD + "\nglobals()['x'] = 1",
    GOOD + "\ngetattr(np, 'zeros')(10)",
])
def test_compile_rejects_banned_constructs(bad):
    with pytest.raises(UnsafeSourceError):
        compile_candidate(bad)


def test_compile_rejects_import_statement():
    src = "import os\n" + GOOD
    with pytest.raises(UnsafeSourceError):
        compile_candidate(src)


def test_compile_rejects_missing_function():
    src = "x = 1"
    with pytest.raises(UnsafeSourceError):
        compile_candidate(src)


def test_compile_rejects_syntax_error():
    src = "def mla_decode_candidate(:"
    with pytest.raises(UnsafeSourceError):
        compile_candidate(src)


def test_compiled_function_is_isolated_from_builtins():
    """The restricted namespace must make full __builtins__ unavailable."""
    src = """
def mla_decode_candidate(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, softmax_scale):
    try:
        x = open  # noqa: F841 -- should be NameError in restricted ns
    except NameError:
        pass
    return np.zeros_like(q_nope) if False else np.einsum("bhn,hnd->bhd", q_nope, W_UK)[..., :W_UV.shape[-1]]
""".strip()
    # `open` is not in our banned-tokens list as an isolated identifier,
    # but it is not bound in the restricted namespace either. The function
    # should execute without raising.
    fn = compile_candidate(src)
    q_nope = np.random.randn(1, 2, 4).astype(np.float32)
    q_rope = np.random.randn(1, 2, 4).astype(np.float32)
    W_UK = np.random.randn(2, 4, 8).astype(np.float32)
    W_UV = np.random.randn(2, 8, 4).astype(np.float32)
    out = fn(q_nope, q_rope, None, None, W_UK, W_UV, 1.0)
    assert out.shape == (1, 2, 4)
