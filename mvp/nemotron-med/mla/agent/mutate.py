"""One mutation pipeline: request → LLM → parse → safety → compile → callable.

Everything between "an LLM gave us a string" and "a Python callable ready for
the validator" lives here. Each candidate carries enough metadata to trace it
through the loop (population, iteration, reasoning) and to regenerate it
deterministically for debugging.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from agent.llm_client import (
    LLMClient,
    MutationRequest,
    MutationResponse,
)
from agent.safety import UnsafeSourceError, compile_candidate


@dataclass
class Candidate:
    source: str
    fn: Callable
    reasoning: str
    source_hash: str
    island: str = ""
    iteration: int = 0
    parent_hash: str | None = None
    raw_llm: str = ""

    @classmethod
    def from_source(
        cls,
        source: str,
        *,
        reasoning: str = "",
        island: str = "",
        iteration: int = 0,
        parent_hash: str | None = None,
        raw_llm: str = "",
    ) -> "Candidate":
        fn = compile_candidate(source)
        h = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        return cls(
            source=source, fn=fn, reasoning=reasoning, source_hash=h,
            island=island, iteration=iteration, parent_hash=parent_hash,
            raw_llm=raw_llm,
        )


@dataclass
class MutationFailure:
    reason: str
    reasoning: str = ""
    source: str = ""
    exception: str = ""


def mutate_once(
    client: LLMClient,
    request: MutationRequest,
    *,
    island: str = "",
    iteration: int = 0,
    parent_hash: str | None = None,
) -> Candidate | MutationFailure:
    """Run one LLM call → produce a Candidate, or a MutationFailure if the
    response is unparseable, unsafe, or uncompilable."""
    try:
        resp: MutationResponse = client.mutate(request)
    except Exception as e:
        return MutationFailure(
            reason="llm_call_failed",
            exception=f"{type(e).__name__}: {e}",
        )
    try:
        return Candidate.from_source(
            resp.source,
            reasoning=resp.reasoning,
            island=island,
            iteration=iteration,
            parent_hash=parent_hash,
            raw_llm=resp.raw,
        )
    except UnsafeSourceError as e:
        return MutationFailure(
            reason="unsafe_source",
            reasoning=resp.reasoning,
            source=resp.source,
            exception=str(e),
        )
    except Exception as e:
        return MutationFailure(
            reason="compile_failed",
            reasoning=resp.reasoning,
            source=resp.source,
            exception=f"{type(e).__name__}: {e}",
        )
