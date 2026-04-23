"""Agent pipeline with StubClient — proves the full path from mutation request
to validated, scored candidate works without an API call."""
from __future__ import annotations

import numpy as np

from agent.generate import generate_candidates
from agent.llm_client import StubClient
from agent.mutate import Candidate, MutationFailure
from kernels.base.mla_decode_numpy import (
    MLAConfig,
    make_inputs,
    mla_decode_absorbed,
    mla_decode_naive,
)
from prism import validate


def test_stub_generates_distinct_candidates():
    client = StubClient()
    passes, failures = generate_candidates(
        client,
        mla_decode_absorbed,
        n=3,
        island="test",
        iteration=1,
    )
    # Stub pool has 4 items; first 3 are valid (distinct source_hash), last
    # is a buggy negative control. Here we take 3, so all pass compile.
    assert len(passes) == 3
    assert len({c.source_hash for c in passes}) == 3
    assert all(c.island == "test" for c in passes)
    assert all(c.iteration == 1 for c in passes)


def test_stub_candidate_passes_validator():
    """First stub mutation is numerically-equivalent; must pass validator."""
    client = StubClient()
    passes, _ = generate_candidates(client, mla_decode_absorbed, n=1)
    assert len(passes) == 1
    cfg = MLAConfig(1, 4, 32, 16, 8, 16, 16)
    inputs = make_inputs(cfg, seed=0)
    result = validate(
        passes[0].fn, mla_decode_naive, inputs,
        tolerance=1e-3,
    )
    assert result.passed, result


def test_stub_negative_control_rejected_by_validator():
    """The 4th stub mutation drops the rope path — validator must reject."""
    client = StubClient()
    passes, _ = generate_candidates(client, mla_decode_absorbed, n=4)
    assert len(passes) == 4
    # Identify the negative control (last in pool)
    bad = passes[-1]
    assert "drop the rope" in bad.reasoning
    cfg = MLAConfig(1, 4, 32, 16, 8, 16, 16)
    inputs = make_inputs(cfg, seed=0)
    result = validate(
        bad.fn, mla_decode_naive, inputs,
        tolerance=1e-3,
    )
    assert not result.passed, "negative-control mutation should fail validator"


def test_generate_filters_duplicates():
    client = StubClient()
    # First call returns stub[0]; now add its hash to seen.
    passes_first, _ = generate_candidates(client, mla_decode_absorbed, n=1)
    seen = {passes_first[0].source_hash}
    client.reset()
    # Ask again with stub reset — first item is duplicate.
    passes_second, failures_second = generate_candidates(
        client, mla_decode_absorbed, n=2, seen_hashes=seen,
    )
    # stub[0] is filtered as dup; stub[1] is accepted.
    assert len(passes_second) == 1
    assert any(f.reason == "duplicate_source_hash" for f in failures_second)


def test_mutation_failure_contains_reason():
    """Force a bad LLM response to check failure reporting."""
    from agent.llm_client import MutationResponse
    bad_client = StubClient(mutations=[
        MutationResponse(reasoning="broken", source="def mla_decode_candidate(:", raw=""),
    ])
    passes, failures = generate_candidates(bad_client, mla_decode_absorbed, n=1)
    assert passes == []
    assert len(failures) == 1
    assert failures[0].reason in ("compile_failed", "unsafe_source")
