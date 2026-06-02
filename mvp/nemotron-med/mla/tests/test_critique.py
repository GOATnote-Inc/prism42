"""Critique agent tests — parsing, stub cycling, rejected? flag."""
from __future__ import annotations

from agent.critique import CritiqueRequest, CritiqueResponse, parse_critique, render_critique_prompt
from agent.llm_client import StubClient


def test_parse_critique_extracts_four_fields():
    raw = """
<critique>
numerical_risk: low — subtract-max is stable
efficiency_risk: none
novelty: structural
recommendation: accept — cleaner reduction
</critique>
""".strip()
    c = parse_critique(raw)
    assert c.numerical_risk.startswith("low")
    assert c.efficiency_risk == "none"
    assert c.novelty == "structural"
    assert c.recommendation.startswith("accept")
    assert not c.rejected


def test_parse_critique_without_wrapper():
    raw = "numerical_risk: high\nefficiency_risk: low\nnovelty: cosmetic\nrecommendation: reject\n"
    c = parse_critique(raw)
    assert c.numerical_risk == "high"
    assert c.recommendation == "reject"
    assert c.rejected


def test_parse_critique_defaults_to_revise_when_missing():
    raw = "no structure here"
    c = parse_critique(raw)
    assert c.recommendation == "revise"


def test_stub_cycles_through_canned_critiques():
    stub = StubClient()
    req = CritiqueRequest(baseline_source="# base", candidate_source="# cand")
    responses = [stub.critique(req) for _ in range(4)]
    recs = [r.recommendation for r in responses]
    assert "accept" in recs
    assert "reject" in recs
    assert len(set(r.rationale for r in responses)) == 4  # four distinct


def test_stub_rejected_flag_matches_reject():
    stub = StubClient()
    req = CritiqueRequest(baseline_source="", candidate_source="")
    # The fourth canned critique is 'reject'
    responses = [stub.critique(req) for _ in range(4)]
    assert responses[3].rejected
    assert not responses[0].rejected


def test_render_critique_prompt_substitutes():
    req = CritiqueRequest(baseline_source="BASELINE", candidate_source="CANDIDATE")
    rendered = render_critique_prompt(req)
    assert "BASELINE" in rendered
    assert "CANDIDATE" in rendered
    assert "{{BASELINE_SOURCE}}" not in rendered
    assert "{{CANDIDATE_SOURCE}}" not in rendered
