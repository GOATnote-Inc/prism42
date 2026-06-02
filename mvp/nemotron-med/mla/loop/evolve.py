"""Evolutionary loop with population islands.

Design:
    - Three islands, each initialized with the same baseline kernel.
    - Each iteration: each island generates K candidates via its LLM client,
      each candidate is validated, benchmarked, and scored.
    - Within-island: keep top-P candidates by score.
    - Between-islands: every MIGRATE_EVERY iterations, the top candidate
      overall migrates as a new seed into the island with the weakest top.

Rationale:
    mental-models/munger-inversion.md §4 (family trap) — islands keep the
        search from collapsing onto one local maximum.
    evolution/kernel-evolution-literature.md §FunSearch — the islands
        idea originates there; AlphaEvolve adopted it.
    scaffold/prism-mla-scaffold.md §8 principle 5 (maintain diversity).

Scoring follows loop/manual_mutation.py: blended throughput + stability,
with a hard correctness gate from the validator. Failing candidates never
contribute to any population.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.critique import CritiqueRequest, CritiqueResponse
from agent.generate import generate_candidates
from agent.llm_client import LLMClient
from agent.mutate import Candidate, MutationFailure
from kernels.base.mla_decode_numpy import (
    MLAConfig,
    make_inputs,
    mla_decode_naive,
)
from loop.pareto import ParetoPoint, pareto_front
from prism import DEFAULT_INVARIANTS, validate
from runner.numpy_runner import benchmark


@dataclass
class ScoredCandidate:
    candidate: Candidate
    score: float
    tokens_per_sec: float
    stability: float
    median_ns: float
    max_abs_error: float
    critique: CritiqueResponse | None = None

    def to_pareto_point(self) -> ParetoPoint:
        return ParetoPoint(
            identifier=self.candidate.source_hash,
            tokens_per_sec=self.tokens_per_sec,
            stability=self.stability,
            max_abs_error=self.max_abs_error,
        )


@dataclass
class Island:
    name: str
    objective: str
    members: list[ScoredCandidate] = field(default_factory=list)


@dataclass
class EvolveConfig:
    mla: MLAConfig
    iterations: int = 3
    per_island: int = 3
    keep_per_island: int = 2
    migrate_every: int = 2
    tolerance: float = 1e-3
    seed: int = 0
    run_critique: bool = False
    pareto_keep: bool = False
    critique_linear_topk: int = 2
    """When run_critique=True, only the top-K linear-score candidates per
    island go through the critique gate. Saves LLM budget."""


def _score(bench, *, w_tps: float = 0.7, w_stab: float = 0.3) -> tuple[float, float]:
    """Returns (blended_score, stability). Mirrors manual_mutation.score."""
    if bench.mean_ns <= 0:
        return 0.0, 0.0
    cv = bench.std_ns / bench.mean_ns
    stability = max(0.0, 1.0 - cv)
    blended = w_tps * bench.tokens_per_sec + w_stab * stability
    return blended, stability


def _seed_island(name: str, objective: str, baseline_fn: Callable) -> Island:
    """Build an island with the baseline as its only member. Score is filled
    on first iteration — we treat the baseline itself as iteration 0."""
    import inspect as _inspect
    src = _inspect.getsource(baseline_fn)
    src_hash = hashlib.sha256(src.encode()).hexdigest()[:16]
    baseline = Candidate(
        source=src, fn=baseline_fn, reasoning="baseline",
        source_hash=src_hash, island=name, iteration=0, parent_hash=None,
    )
    return Island(
        name=name, objective=objective,
        members=[ScoredCandidate(
            candidate=baseline, score=0.0, tokens_per_sec=0.0,
            stability=0.0, median_ns=0.0, max_abs_error=0.0,
        )],
    )


def _score_candidate(
    candidate: Candidate,
    cfg: EvolveConfig,
    inputs: dict,
    sweep_configs: list[dict],
) -> ScoredCandidate | MutationFailure:
    """Run validator + bench + score. Returns MutationFailure if rejected."""
    v = validate(
        candidate.fn,
        mla_decode_naive,
        inputs,
        tolerance=cfg.tolerance,
        config_sweep=sweep_configs,
        invariants=DEFAULT_INVARIANTS,
    )
    if not v.passed:
        return MutationFailure(
            reason="validator_rejected",
            reasoning=candidate.reasoning,
            source=candidate.source,
            exception=v.failed_check or "unknown",
        )
    b = benchmark(candidate.fn, inputs, warmup=3, iters=20)
    blended, stability = _score(b)
    return ScoredCandidate(
        candidate=candidate, score=blended,
        tokens_per_sec=b.tokens_per_sec, stability=stability,
        median_ns=b.median_ns, max_abs_error=v.max_abs_error,
    )


def _pick_weakest_island(islands: list[Island]) -> Island:
    def top_score(i: Island) -> float:
        return max((m.score for m in i.members), default=0.0)
    return min(islands, key=top_score)


def _pick_best_overall(islands: list[Island]) -> ScoredCandidate | None:
    best: ScoredCandidate | None = None
    for i in islands:
        for m in i.members:
            if best is None or m.score > best.score:
                best = m
    return best


def _population_summary(island: Island) -> str:
    lines = [f"  {i+1}. hash={m.candidate.source_hash} score={m.score:,.1f}"
             for i, m in enumerate(island.members)]
    return f"island={island.name!r}; current members:\n" + "\n".join(lines) if lines else "(empty)"


def evolve(
    client: LLMClient,
    baseline_fn: Callable,
    cfg: EvolveConfig,
    *,
    log_path: Path | None = None,
) -> dict:
    """Run the evolutionary loop end-to-end. Returns a summary dict; optionally
    writes a JSON log with full history."""
    inputs = make_inputs(cfg.mla, seed=cfg.seed)
    sweep_configs = [
        make_inputs(MLAConfig(1, cfg.mla.heads, cfg.mla.kv_len // 2,
                              cfg.mla.d_c, cfg.mla.d_r, cfg.mla.qk_nope,
                              cfg.mla.v_head), seed=cfg.seed + 1),
        make_inputs(MLAConfig(cfg.mla.batch * 2, cfg.mla.heads, cfg.mla.kv_len // 4,
                              cfg.mla.d_c, cfg.mla.d_r, cfg.mla.qk_nope,
                              cfg.mla.v_head), seed=cfg.seed + 2),
    ]

    islands = [
        _seed_island("memory", "reduce HBM bytes read per decode step", baseline_fn),
        _seed_island("arith", "eliminate redundant arithmetic ops", baseline_fn),
        _seed_island("fusion", "fuse softmax scale and score reduction", baseline_fn),
    ]

    # Score the baseline once so it has a real number for migration selection.
    base_sc = _score_candidate(islands[0].members[0].candidate, cfg, inputs, sweep_configs)
    if isinstance(base_sc, ScoredCandidate):
        for i in islands:
            i.members[0] = ScoredCandidate(
                candidate=i.members[0].candidate,
                score=base_sc.score, tokens_per_sec=base_sc.tokens_per_sec,
                stability=base_sc.stability, median_ns=base_sc.median_ns,
                max_abs_error=base_sc.max_abs_error,
            )

    seen_hashes: set[str] = {m.candidate.source_hash for i in islands for m in i.members}
    history: list[dict] = []

    for it in range(1, cfg.iterations + 1):
        it_start = time.perf_counter()
        it_record = {"iteration": it, "islands": [], "migrations": []}
        for island in islands:
            top_member = max(island.members, key=lambda m: m.score)
            passes, failures = generate_candidates(
                client,
                top_member.candidate.fn,
                n=cfg.per_island,
                island=island.name,
                iteration=it,
                parent_hash=top_member.candidate.source_hash,
                population_summary=_population_summary(island),
                mutation_objective=island.objective,
                seen_hashes=seen_hashes,
            )
            scored: list[ScoredCandidate] = list(island.members)
            gen_failures = [f.reason for f in failures]
            val_failures: list[str] = []
            for cand in passes:
                res = _score_candidate(cand, cfg, inputs, sweep_configs)
                if isinstance(res, ScoredCandidate):
                    scored.append(res)
                else:
                    val_failures.append(res.exception or res.reason)

            # --- Critique gate (optional) ---
            critique_results: list[dict] = []
            if cfg.run_critique and len(scored) > 0:
                # Identify candidates new this iteration (not baseline) for critique.
                # Baseline is the iteration=0 member; skip it.
                new_in_scored = [s for s in scored if s.candidate.iteration == it]
                # Only critique the top-K by linear score to save budget.
                new_in_scored.sort(key=lambda m: m.score, reverse=True)
                top_new = new_in_scored[: cfg.critique_linear_topk]
                baseline_src = top_member.candidate.source
                reject_hashes: set[str] = set()
                for sc in top_new:
                    try:
                        cresp = client.critique(CritiqueRequest(
                            baseline_source=baseline_src,
                            candidate_source=sc.candidate.source,
                        ))
                    except Exception as e:
                        cresp = CritiqueResponse(
                            "unknown", "unknown", "unknown", "revise",
                            rationale=f"critique call failed: {type(e).__name__}: {e}",
                        )
                    sc.critique = cresp
                    critique_results.append({
                        "hash": sc.candidate.source_hash,
                        "numerical_risk": cresp.numerical_risk,
                        "efficiency_risk": cresp.efficiency_risk,
                        "novelty": cresp.novelty,
                        "recommendation": cresp.recommendation,
                    })
                    if cresp.rejected:
                        reject_hashes.add(sc.candidate.source_hash)
                scored = [s for s in scored if s.candidate.source_hash not in reject_hashes]

            # --- Selection: linear top-K, optionally unioned with Pareto front ---
            scored.sort(key=lambda m: m.score, reverse=True)
            selected: list[ScoredCandidate] = scored[: cfg.keep_per_island]
            pareto_retained: list[str] = []
            if cfg.pareto_keep and len(scored) > 1:
                points = [s.to_pareto_point() for s in scored]
                front_ids = {p.identifier for p in pareto_front(points)}
                selected_ids = {s.candidate.source_hash for s in selected}
                extras = [s for s in scored if s.candidate.source_hash in front_ids
                          and s.candidate.source_hash not in selected_ids]
                selected = selected + extras
                pareto_retained = [s.candidate.source_hash for s in extras]

            island.members = selected
            it_record["islands"].append({
                "name": island.name,
                "proposed": len(passes) + len(failures),
                "compile_failures": gen_failures,
                "validator_failures": val_failures,
                "critiques": critique_results,
                "pareto_retained": pareto_retained,
                "top_score": island.members[0].score if island.members else 0.0,
                "top_hash": island.members[0].candidate.source_hash if island.members else None,
            })

        if it % cfg.migrate_every == 0:
            best = _pick_best_overall(islands)
            weakest = _pick_weakest_island(islands)
            if best and best not in weakest.members:
                weakest.members.append(best)
                weakest.members.sort(key=lambda m: m.score, reverse=True)
                weakest.members = weakest.members[: cfg.keep_per_island + 1]
                it_record["migrations"].append(
                    {"from": best.candidate.island, "to": weakest.name,
                     "hash": best.candidate.source_hash, "score": best.score}
                )

        it_record["wall_s"] = time.perf_counter() - it_start
        history.append(it_record)

    best_overall = _pick_best_overall(islands)
    summary = {
        "config": {
            "iterations": cfg.iterations, "per_island": cfg.per_island,
            "keep_per_island": cfg.keep_per_island,
            "migrate_every": cfg.migrate_every, "tolerance": cfg.tolerance,
        },
        "best": {
            "score": best_overall.score if best_overall else 0.0,
            "tokens_per_sec": best_overall.tokens_per_sec if best_overall else 0.0,
            "stability": best_overall.stability if best_overall else 0.0,
            "median_ns": best_overall.median_ns if best_overall else 0.0,
            "hash": best_overall.candidate.source_hash if best_overall else None,
            "island": best_overall.candidate.island if best_overall else None,
            "source": best_overall.candidate.source if best_overall else None,
            "reasoning": best_overall.candidate.reasoning if best_overall else None,
        },
        "history": history,
    }
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(summary, indent=2))
    return summary
