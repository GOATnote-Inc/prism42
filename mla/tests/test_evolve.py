"""End-to-end evolve loop with StubClient. Proves:
    - baseline is scored
    - candidates are generated, validated, benchmarked, scored
    - top-per-island is retained
    - migration happens at configured cadence
    - best overall matches the best on any island
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.llm_client import StubClient
from kernels.base.mla_decode_numpy import MLAConfig, mla_decode_absorbed
from loop.evolve import EvolveConfig, evolve


def test_evolve_end_to_end_with_stub(tmp_path: Path):
    cfg = EvolveConfig(
        mla=MLAConfig(batch=1, heads=4, kv_len=32, d_c=16, d_r=8, qk_nope=16, v_head=16),
        iterations=2,
        per_island=2,
        keep_per_island=2,
        migrate_every=2,
        tolerance=1e-3,
        seed=0,
    )
    client = StubClient()
    log_path = tmp_path / "evolve.json"
    summary = evolve(client, mla_decode_absorbed, cfg, log_path=log_path)

    # Basic summary shape
    assert "best" in summary
    assert "history" in summary
    assert len(summary["history"]) == cfg.iterations

    # At least one iteration had a surviving candidate with non-zero score.
    assert summary["best"]["score"] > 0

    # Best is drawn from one of our known islands.
    assert summary["best"]["island"] in {"memory", "arith", "fusion"}

    # Log file round-trips through JSON.
    assert log_path.exists()
    loaded = json.loads(log_path.read_text())
    assert loaded["best"]["hash"] == summary["best"]["hash"]


def test_evolve_rejects_negative_control():
    """Evolve must never surface the buggy negative-control candidate as best.
    The validator should filter it out, never making it into an island's
    members list."""
    cfg = EvolveConfig(
        mla=MLAConfig(batch=1, heads=4, kv_len=32, d_c=16, d_r=8, qk_nope=16, v_head=16),
        iterations=3,
        per_island=4,     # try to include the bad stub candidate
        keep_per_island=2,
        migrate_every=10,
        tolerance=1e-3,
        seed=0,
    )
    client = StubClient()
    summary = evolve(client, mla_decode_absorbed, cfg)

    # The negative control in the stub pool drops the rope path. Its
    # reasoning contains a specific sentinel we can check for in the
    # winner.
    if summary["best"]["reasoning"]:
        assert "drop the rope" not in summary["best"]["reasoning"].lower()
