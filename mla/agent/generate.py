"""Candidate generation: take a current best, request N mutations, return the
compile-passing set. Duplicates by source_hash are rejected at this layer so
the validator sees only distinct candidates.

Used by loop/evolve.py. The generation step is intentionally cheap —
expensive filtering happens downstream in validate → benchmark → score.
"""
from __future__ import annotations

import inspect
from typing import Callable

from agent.llm_client import LLMClient, MutationRequest
from agent.mutate import Candidate, MutationFailure, mutate_once


def _kernel_source(fn: Callable) -> str:
    """Best-effort source-extraction. Falls back to repr if inspect fails."""
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return f"# source unavailable for {fn!r}"


def generate_candidates(
    client: LLMClient,
    current_best_fn: Callable,
    *,
    n: int = 4,
    island: str = "default",
    iteration: int = 0,
    parent_hash: str | None = None,
    population_summary: str = "",
    mutation_objective: str = "reduce HBM bytes read per decode step",
    seen_hashes: set[str] | None = None,
) -> tuple[list[Candidate], list[MutationFailure]]:
    """Request N mutations; return (compile-passing candidates, failures).

    Duplicates by source_hash are filtered; they count toward failures.
    """
    seen_hashes = set(seen_hashes or ())
    src = _kernel_source(current_best_fn)
    req = MutationRequest(
        current_best_source=src,
        population_summary=population_summary,
        mutation_objective=mutation_objective,
    )
    passes: list[Candidate] = []
    failures: list[MutationFailure] = []
    for _ in range(n):
        outcome = mutate_once(
            client, req,
            island=island, iteration=iteration, parent_hash=parent_hash,
        )
        if isinstance(outcome, MutationFailure):
            failures.append(outcome)
            continue
        if outcome.source_hash in seen_hashes:
            failures.append(MutationFailure(
                reason="duplicate_source_hash",
                reasoning=outcome.reasoning,
                source=outcome.source,
            ))
            continue
        seen_hashes.add(outcome.source_hash)
        passes.append(outcome)
    return passes, failures
