"""LLM clients for mutation generation.

Two backends:
    StubClient      — deterministic, offline, returns canned mutations.
                      Used in tests and when no API key is present.
    AnthropicClient — calls Claude (default: claude-opus-4-7) with the
                      mutation prompt. Gated behind explicit opt-in even
                      when API key exists — no accidental spend.

The mutation prompt itself lives in agent/prompts/mutation.txt. The client
is responsible only for template substitution and API call mechanics.

References:
    scaffold/prism-mla-scaffold.md §8 (agent control strategy)
    memory/claude_opus_4_7_migration.md (thinking OFF by default, rejects
        temperature/top_p/top_k/budget_tokens)
"""
from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent.critique import (
    CritiqueRequest,
    CritiqueResponse,
    parse_critique,
    render_critique_prompt,
)


@dataclass
class MutationRequest:
    current_best_source: str
    population_summary: str
    mutation_objective: str


@dataclass
class MutationResponse:
    reasoning: str
    source: str
    raw: str = ""


class LLMClient(Protocol):
    def mutate(self, req: MutationRequest) -> MutationResponse: ...
    def critique(self, req: CritiqueRequest) -> CritiqueResponse: ...


# -- Stub client: canned mutations --

_STUB_MUTATIONS: list[MutationResponse] = [
    MutationResponse(
        reasoning=(
            "bottleneck: redundant arithmetic (two separate einsums for scores).\n"
            "why: merging scores_nope + scores_rope into one einsum by concatenating\n"
            "  q_merged || q_rope and c_KV || k_R amortizes the reduction pass.\n"
            "risk: low — numerically identical to baseline, one fewer kernel launch."
        ),
        source=textwrap.dedent(
            '''
            def mla_decode_candidate(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, softmax_scale):
                q_merged = np.einsum("bhn,hnd->bhd", q_nope, W_UK)
                q_cat = np.concatenate([q_merged, q_rope], axis=-1)
                k_cat = np.concatenate([c_KV, k_R], axis=-1)
                scores = np.einsum("bhd,btd->bht", q_cat, k_cat) * softmax_scale
                scores -= scores.max(axis=-1, keepdims=True)
                exp = np.exp(scores)
                w = exp / exp.sum(axis=-1, keepdims=True)
                ctx = np.einsum("bht,btd->bhd", w, c_KV)
                return np.einsum("bhd,hdv->bhv", ctx, W_UV)
            '''
        ).strip(),
    ),
    MutationResponse(
        reasoning=(
            "bottleneck: added allocation in softmax (three temporaries).\n"
            "why: collapse the subtract-max, exp, divide into an in-place chain.\n"
            "risk: low — numpy allocates same total, but fewer intermediate names."
        ),
        source=textwrap.dedent(
            '''
            def mla_decode_candidate(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, softmax_scale):
                q_merged = np.einsum("bhn,hnd->bhd", q_nope, W_UK)
                scores = np.einsum("bhd,btd->bht", q_merged, c_KV)
                scores = scores + np.einsum("bhd,btd->bht", q_rope, k_R)
                scores *= softmax_scale
                scores -= scores.max(axis=-1, keepdims=True)
                np.exp(scores, out=scores)
                scores /= scores.sum(axis=-1, keepdims=True)
                ctx = np.einsum("bht,btd->bhd", scores, c_KV)
                return np.einsum("bhd,hdv->bhv", ctx, W_UV)
            '''
        ).strip(),
    ),
    MutationResponse(
        reasoning=(
            "bottleneck: softmax scale applied after both score components.\n"
            "why: fold softmax_scale into q_merged at materialization; saves one broadcast multiply.\n"
            "risk: low — numerically equivalent."
        ),
        source=textwrap.dedent(
            '''
            def mla_decode_candidate(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, softmax_scale):
                q_merged = np.einsum("bhn,hnd->bhd", q_nope, W_UK) * softmax_scale
                q_rope_scaled = q_rope * softmax_scale
                scores = np.einsum("bhd,btd->bht", q_merged, c_KV)
                scores += np.einsum("bhd,btd->bht", q_rope_scaled, k_R)
                scores -= scores.max(axis=-1, keepdims=True)
                exp = np.exp(scores)
                w = exp / exp.sum(axis=-1, keepdims=True)
                ctx = np.einsum("bht,btd->bhd", w, c_KV)
                return np.einsum("bhd,hdv->bhv", ctx, W_UV)
            '''
        ).strip(),
    ),
    # Negative control — produces wrong values; validator must reject.
    MutationResponse(
        reasoning=(
            "bottleneck: [intentional] drop the rope score path entirely.\n"
            "why: [wrong] rope contribution is small so skip it.\n"
            "risk: high — this is a buggy candidate; validator must catch."
        ),
        source=textwrap.dedent(
            '''
            def mla_decode_candidate(q_nope, q_rope, c_KV, k_R, W_UK, W_UV, softmax_scale):
                q_merged = np.einsum("bhn,hnd->bhd", q_nope, W_UK)
                scores = np.einsum("bhd,btd->bht", q_merged, c_KV) * softmax_scale
                scores -= scores.max(axis=-1, keepdims=True)
                exp = np.exp(scores)
                w = exp / exp.sum(axis=-1, keepdims=True)
                ctx = np.einsum("bht,btd->bhd", w, c_KV)
                return np.einsum("bhd,hdv->bhv", ctx, W_UV)
            '''
        ).strip(),
    ),
]


_STUB_CRITIQUES: list[CritiqueResponse] = [
    CritiqueResponse(
        numerical_risk="low",
        efficiency_risk="none",
        novelty="structural",
        recommendation="accept",
        rationale="fused einsum path; equivalent math, one fewer reduction",
    ),
    CritiqueResponse(
        numerical_risk="low",
        efficiency_risk="low",
        novelty="cosmetic",
        recommendation="revise",
        rationale="in-place softmax is fine on numpy but adds aliasing risk on GPU",
    ),
    CritiqueResponse(
        numerical_risk="medium",
        efficiency_risk="none",
        novelty="cosmetic",
        recommendation="accept",
        rationale="scale folded into q_merged; equivalent, saves one broadcast",
    ),
    CritiqueResponse(
        numerical_risk="high",
        efficiency_risk="none",
        novelty="structural",
        recommendation="reject",
        rationale="rope path dropped — violates MLA semantics",
    ),
]


class StubClient:
    """Deterministic offline client. Cycles through canned mutations and
    critiques independently. Critique responses are paired with mutation
    responses by index (stub[0] mutation gets stub[0] critique, etc.)."""

    def __init__(
        self,
        mutations: list[MutationResponse] | None = None,
        critiques: list[CritiqueResponse] | None = None,
    ):
        self._pool = list(mutations or _STUB_MUTATIONS)
        self._critique_pool = list(critiques or _STUB_CRITIQUES)
        self._idx = 0
        self._crit_idx = 0

    def mutate(self, req: MutationRequest) -> MutationResponse:
        if not self._pool:
            raise RuntimeError("StubClient pool is empty")
        resp = self._pool[self._idx % len(self._pool)]
        self._idx += 1
        return resp

    def critique(self, req: CritiqueRequest) -> CritiqueResponse:
        if not self._critique_pool:
            # Default to accept if no critique pool
            return CritiqueResponse("none", "none", "cosmetic", "accept", rationale="stub default")
        resp = self._critique_pool[self._crit_idx % len(self._critique_pool)]
        self._crit_idx += 1
        return resp

    def reset(self) -> None:
        self._idx = 0
        self._crit_idx = 0


# -- Anthropic client --

_PROMPT_PATH = Path(__file__).parent / "prompts" / "mutation.txt"
_PROMPT_PATH_TORCH = Path(__file__).parent / "prompts" / "mutation_torch.txt"


class AnthropicClient:
    """Calls Claude with the mutation prompt. Opt-in via allow_real_calls=True.

    Notes:
        - Model pinned to claude-opus-4-7 by default.
        - Claude 4.7 rejects temperature/top_p/top_k/budget_tokens; thinking
          is OFF by default. Do not pass those kwargs.
        - anthropic SDK required; import is lazy so the module loads without it.
    """

    def __init__(
        self,
        *,
        model: str = "claude-opus-4-7",
        allow_real_calls: bool = False,
        max_tokens: int = 4096,
    ):
        if not allow_real_calls:
            raise RuntimeError(
                "AnthropicClient requires allow_real_calls=True to prevent accidental API spend."
            )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise RuntimeError("anthropic SDK not installed; pip install anthropic") from e
        self.model = model
        self.max_tokens = max_tokens
        self._prompt_tpl = _PROMPT_PATH.read_text()

    def _render(self, req: MutationRequest) -> str:
        return (
            self._prompt_tpl
            .replace("{{CURRENT_BEST_SOURCE}}", req.current_best_source)
            .replace("{{POPULATION_SUMMARY}}", req.population_summary)
            .replace("{{MUTATION_OBJECTIVE}}", req.mutation_objective)
        )

    def mutate(self, req: MutationRequest) -> MutationResponse:
        import anthropic  # lazy
        client = anthropic.Anthropic()
        prompt = self._render(req)
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return _parse_llm_response(raw)

    def mutate_torch(self, req: MutationRequest) -> MutationResponse:
        """Torch-flavored mutation. Uses prompts/mutation_torch.txt."""
        import anthropic  # lazy
        client = anthropic.Anthropic()
        tpl = _PROMPT_PATH_TORCH.read_text()
        prompt = (
            tpl.replace("{{CURRENT_BEST_SOURCE}}", req.current_best_source)
               .replace("{{MUTATION_OBJECTIVE}}", req.mutation_objective)
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return _parse_llm_response(raw)

    def critique(self, req: CritiqueRequest) -> CritiqueResponse:
        import anthropic  # lazy
        client = anthropic.Anthropic()
        prompt = render_critique_prompt(req)
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return parse_critique(raw)


# -- Response parsing --

_REASONING_RE = re.compile(r"<reasoning>(.*?)</reasoning>", re.DOTALL)
_KERNEL_RE = re.compile(r"<kernel>(.*?)</kernel>", re.DOTALL)


def _parse_llm_response(raw: str) -> MutationResponse:
    r_match = _REASONING_RE.search(raw)
    k_match = _KERNEL_RE.search(raw)
    if not k_match:
        raise ValueError("missing <kernel> block in LLM response")
    src = k_match.group(1).strip()
    # Strip fenced code fences if the model added them inside the kernel block.
    if src.startswith("```"):
        src = src.split("\n", 1)[1] if "\n" in src else src
        if src.endswith("```"):
            src = src.rsplit("```", 1)[0]
        src = src.strip()
    reasoning = r_match.group(1).strip() if r_match else ""
    return MutationResponse(reasoning=reasoning, source=src, raw=raw)


def make_default_client() -> LLMClient:
    """Stub unless explicitly told otherwise via PRISM_USE_ANTHROPIC=1."""
    if os.environ.get("PRISM_USE_ANTHROPIC") == "1":
        return AnthropicClient(allow_real_calls=True)
    return StubClient()
