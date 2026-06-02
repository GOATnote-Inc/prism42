"""Safety gate for LLM-generated kernel source.

Any source that reaches the validator has been through compile_candidate,
which (a) rejects banned tokens before parse, and (b) compiles in a
namespace that excludes __builtins__ except a whitelist of math operations.

This is the agent-side counterpart to red-team §4 (agent jailbreak) and §7
(dependency hijack). It does not replace process-level isolation — at the
real-hardware stage, candidates should additionally run in a subprocess
with RLIMIT_AS/RLIMIT_CPU and network-egress disabled.

References:
    mental-models/red-team-adversarial.md §4, §7
    prism/gaming_patterns.py check_no_trivial_delegation (complementary)
"""
from __future__ import annotations

import ast
from typing import Callable

import numpy as np


_BANNED_TOKENS: tuple[str, ...] = (
    "import ",          # any import statement
    "__import__",
    "eval(",
    "exec(",
    "compile(",
    "open(",
    "subprocess",
    "os.",
    "sys.",
    "socket",
    "pickle",
    "ctypes",
    "globals(",
    "locals(",
    "getattr(",
    "setattr(",
    "delattr(",
    "vars(",
    "input(",
    "breakpoint(",
    "__builtins__",
    "__class__",
    "__bases__",
    "__subclasses__",
)

# Extra tokens banned only in the torch namespace — dangerous torch APIs that
# can load native code, serialize state, or escape the Python sandbox.
# Evolutionary candidates should never touch these even incidentally.
_BANNED_TORCH_TOKENS: tuple[str, ...] = (
    "torch.save",
    "torch.load",
    "torch.jit.load",
    "torch.jit.save",
    "torch.ops.load_library",
    "torch.utils.cpp_extension",
    "torch.hub",
    "torch.multiprocessing",
    "torch.distributed",
    "torch.cuda.nvtx",  # debugging only; out of scope for mutations
    "torch._C",          # raw C bindings
    "torch.classes",
    "torch.fx.wrap",
    "load_inline",
)

_BANNED_AST_NODES: tuple[type, ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
)


class UnsafeSourceError(ValueError):
    """Raised when candidate source contains a banned construct."""


def scan_tokens(source: str) -> list[str]:
    """Return the list of banned tokens found in source."""
    return [tok for tok in _BANNED_TOKENS if tok in source]


def scan_ast(source: str) -> list[str]:
    """Parse source and return names of banned AST nodes encountered."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise UnsafeSourceError(f"syntax error: {e}") from e
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, _BANNED_AST_NODES):
            found.append(type(node).__name__)
    return found


def compile_candidate(source: str, *, fn_name: str = "mla_decode_candidate") -> Callable:
    """Compile a candidate into a callable. Rejects unsafe source.

    The compile namespace has no builtins beyond numpy (bound as `np`) and
    a minimal `range`/`len` for convenience. The function is located by
    `fn_name`.
    """
    bad_tokens = scan_tokens(source)
    if bad_tokens:
        raise UnsafeSourceError(f"banned tokens: {bad_tokens}")
    bad_nodes = scan_ast(source)
    if bad_nodes:
        raise UnsafeSourceError(f"banned AST nodes: {bad_nodes}")

    # Restricted namespace — no full __builtins__. Exception types are
    # included so legitimate try/except blocks in candidate code work.
    safe_builtins = {
        "range": range,
        "len": len,
        "min": min,
        "max": max,
        "abs": abs,
        "sum": sum,
        "float": float,
        "int": int,
        "bool": bool,
        "True": True,
        "False": False,
        "None": None,
        # Exception types candidates might legitimately raise/catch.
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "NameError": NameError,
        "RuntimeError": RuntimeError,
        "AssertionError": AssertionError,
        "ArithmeticError": ArithmeticError,
        "ZeroDivisionError": ZeroDivisionError,
        "OverflowError": OverflowError,
    }
    ns: dict = {"np": np, "__builtins__": safe_builtins}
    try:
        exec(compile(source, "<candidate>", "exec"), ns)
    except Exception as e:
        raise UnsafeSourceError(f"compile/exec failed: {type(e).__name__}: {e}") from e
    fn = ns.get(fn_name)
    if fn is None or not callable(fn):
        raise UnsafeSourceError(f"no callable {fn_name!r} found in source")
    return fn


def compile_candidate_torch(source: str, *, fn_name: str = "mla_decode_candidate") -> Callable:
    """Like compile_candidate but binds torch + F (torch.nn.functional) into
    the restricted namespace. Adds torch-specific banned-token checks.

    This widens the attack surface vs pure numpy (torch has native-code
    APIs). The additional blocklist covers torch.save/load, torch.ops,
    torch.jit.load, torch.utils.cpp_extension, torch.hub, torch.distributed,
    torch.multiprocessing, torch._C, torch.classes, torch.fx.wrap. AST
    checks for imports still apply, so candidates cannot pull in arbitrary
    torch submodules — they must stay inside the bound `torch` / `F` / `np`
    references.
    """
    bad_tokens = scan_tokens(source)
    if bad_tokens:
        raise UnsafeSourceError(f"banned tokens: {bad_tokens}")
    bad_torch = [t for t in _BANNED_TORCH_TOKENS if t in source]
    if bad_torch:
        raise UnsafeSourceError(f"banned torch tokens: {bad_torch}")
    bad_nodes = scan_ast(source)
    if bad_nodes:
        raise UnsafeSourceError(f"banned AST nodes: {bad_nodes}")

    try:
        import torch  # lazy; keep this module importable on CPU-only hosts
        import torch.nn.functional as F
    except ImportError as e:
        raise UnsafeSourceError(
            "torch not installed; compile_candidate_torch requires torch"
        ) from e

    safe_builtins = {
        "range": range, "len": len, "min": min, "max": max, "abs": abs,
        "sum": sum, "float": float, "int": int, "bool": bool, "tuple": tuple,
        "list": list, "True": True, "False": False, "None": None,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "NameError": NameError, "RuntimeError": RuntimeError,
        "AssertionError": AssertionError, "ArithmeticError": ArithmeticError,
        "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
    }
    ns: dict = {
        "np": np,
        "torch": torch,
        "F": F,
        "__builtins__": safe_builtins,
    }
    try:
        exec(compile(source, "<candidate_torch>", "exec"), ns)
    except Exception as e:
        raise UnsafeSourceError(f"compile/exec failed: {type(e).__name__}: {e}") from e
    fn = ns.get(fn_name)
    if fn is None or not callable(fn):
        raise UnsafeSourceError(f"no callable {fn_name!r} found in source")
    return fn
