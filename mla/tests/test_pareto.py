"""Pareto dominance and front tests."""
from __future__ import annotations

from loop.pareto import ParetoPoint, dominates, pareto_front


def p(name, tps, stab, err):
    return ParetoPoint(identifier=name, tokens_per_sec=tps, stability=stab, max_abs_error=err)


def test_dominates_strictly_better():
    a = p("a", tps=100, stab=0.9, err=0.001)
    b = p("b", tps=50, stab=0.5, err=0.01)
    assert dominates(a, b)
    assert not dominates(b, a)


def test_does_not_dominate_if_equal_on_all():
    a = p("a", 100, 0.9, 0.001)
    b = p("b", 100, 0.9, 0.001)
    assert not dominates(a, b)
    assert not dominates(b, a)


def test_does_not_dominate_if_trade_off():
    """Faster but less stable — neither dominates."""
    a = p("a", 100, 0.5, 0.001)
    b = p("b", 50, 0.99, 0.001)
    assert not dominates(a, b)
    assert not dominates(b, a)


def test_dominates_with_smaller_error_only():
    """Same speed and stability, smaller error -> dominates."""
    a = p("a", 100, 0.9, 0.0001)
    b = p("b", 100, 0.9, 0.01)
    assert dominates(a, b)
    assert not dominates(b, a)


def test_pareto_front_rejects_dominated():
    points = [
        p("dominated", 50, 0.5, 0.01),
        p("winner", 100, 0.9, 0.001),
        p("tradeoff", 200, 0.3, 0.01),
    ]
    front = pareto_front(points)
    ids = {x.identifier for x in front}
    assert "dominated" not in ids
    assert "winner" in ids
    assert "tradeoff" in ids


def test_pareto_front_preserves_equivalent_points_once():
    points = [
        p("a", 100, 0.9, 0.001),
        p("b", 100, 0.9, 0.001),  # axis-equal duplicate
        p("dominated", 50, 0.5, 0.01),
    ]
    front = pareto_front(points)
    assert len(front) == 1


def test_pareto_front_all_on_front_if_mutually_non_dominating():
    points = [
        p("fastest_unstable", 200, 0.3, 0.01),
        p("balanced", 100, 0.9, 0.001),
        p("most_stable", 50, 0.99, 0.0001),
    ]
    front = pareto_front(points)
    assert len(front) == 3
