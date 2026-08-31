"""Shared fixtures for the mla test suite.

The exec-containment gate (agent/safety._assert_exec_allowed, P1-8)
refuses to execute model-generated source unless the process is the
isolated bench worker or an operator opted in. The tests below exercise
the compile path with known fixture source, so the suite opts in
explicitly; the gate's own refusal behavior is covered in
test_safety.py::TestExecContainmentGate with both variables cleared.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_inprocess_exec(monkeypatch):
    monkeypatch.setenv("PRISM_MLA_ALLOW_INPROCESS_EXEC", "1")
