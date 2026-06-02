"""Critique agent: second-pass review of a proposed mutation.

The critique agent reads the baseline + the candidate and emits a structured
verdict with four fields: numerical_risk, efficiency_risk, novelty, and
recommendation ∈ {accept, revise, reject}. Candidates flagged 'reject' are
dropped before Pareto admission. 'revise' survives but is logged for
follow-up mutation prompts to address the reviewer's concern.

Rationale: scaffold/prism-mla-scaffold.md §8 principle 4. A critique loop
filters garbage without adding a second scalar to the objective — it works
as a gate, not a weight.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CritiqueRequest:
    baseline_source: str
    candidate_source: str


@dataclass
class CritiqueResponse:
    numerical_risk: str      # none | low | medium | high
    efficiency_risk: str
    novelty: str             # duplicate | cosmetic | structural
    recommendation: str      # accept | revise | reject
    rationale: str = ""
    raw: str = ""

    @property
    def rejected(self) -> bool:
        return self.recommendation.lower() == "reject"


_PROMPT_PATH = Path(__file__).parent / "prompts" / "critique.txt"
_CRITIQUE_RE = re.compile(r"<critique>(.*?)</critique>", re.DOTALL)
_FIELD_RE = re.compile(r"^\s*(numerical_risk|efficiency_risk|novelty|recommendation)\s*:\s*(.*?)\s*$", re.MULTILINE | re.IGNORECASE)


def parse_critique(raw: str) -> CritiqueResponse:
    """Extract the four structured fields from an LLM critique response."""
    block_match = _CRITIQUE_RE.search(raw)
    body = block_match.group(1) if block_match else raw
    fields: dict[str, str] = {}
    for m in _FIELD_RE.finditer(body):
        fields[m.group(1).lower()] = m.group(2).strip()
    return CritiqueResponse(
        numerical_risk=fields.get("numerical_risk", "unknown"),
        efficiency_risk=fields.get("efficiency_risk", "unknown"),
        novelty=fields.get("novelty", "unknown"),
        recommendation=fields.get("recommendation", "revise"),
        rationale=body.strip(),
        raw=raw,
    )


def render_critique_prompt(req: CritiqueRequest) -> str:
    tpl = _PROMPT_PATH.read_text()
    return (
        tpl
        .replace("{{BASELINE_SOURCE}}", req.baseline_source)
        .replace("{{CANDIDATE_SOURCE}}", req.candidate_source)
    )
