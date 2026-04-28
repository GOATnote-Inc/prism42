"""Pareto dominance and front computation for multi-objective kernel scoring.

Axes (higher is better; we negate lower-is-better quantities up front):
    - tokens_per_sec
    - stability (coefficient-of-variation-derived, in [0,1])
    - -max_abs_error (numerical margin)

A candidate is on the Pareto front iff no other candidate is >= on all axes
and strictly > on at least one. The front is what we keep in the island; the
linear-score winner is additionally surfaced as the headline kernel.

Cross-ref: mental-models/munger-inversion.md §9 (don't collapse to one
scalar; keep the front).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParetoPoint:
    identifier: str
    tokens_per_sec: float
    stability: float
    max_abs_error: float   # lower is better; we invert inside dominates()

    @property
    def axes(self) -> tuple[float, float, float]:
        return (self.tokens_per_sec, self.stability, -self.max_abs_error)


def dominates(a: ParetoPoint, b: ParetoPoint) -> bool:
    """A dominates B iff A >= B on every axis and A > B on at least one."""
    a_axes = a.axes
    b_axes = b.axes
    all_ge = all(x >= y for x, y in zip(a_axes, b_axes))
    any_gt = any(x > y for x, y in zip(a_axes, b_axes))
    return all_ge and any_gt


def pareto_front(points: list[ParetoPoint]) -> list[ParetoPoint]:
    """Return the Pareto-optimal subset of points. O(n^2) — fine for the
    small populations this loop maintains. Duplicates (identical axes) are
    kept only once — whichever appears first in input order."""
    out: list[ParetoPoint] = []
    for p in points:
        # Skip if p is dominated by any other point in `points`
        if any(dominates(q, p) for q in points if q.identifier != p.identifier):
            continue
        # Skip if p is axis-equal to a point already in `out` (dedup)
        if any(p.axes == q.axes for q in out):
            continue
        out.append(p)
    return out
