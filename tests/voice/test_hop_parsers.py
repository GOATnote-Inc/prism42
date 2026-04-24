"""Unit tests for the bench JSON parsing + SLO comparison helpers.

These do NOT require pod access — they run on every push to catch
parser regressions before they hide real SLO violations.
"""
from __future__ import annotations


def test_hop_lookup_happy_path(get_hop):
    bench = {
        "hop_aggregates": [
            {"hop": "t_stt_ms", "n": 3, "mean": 606.5, "median": 614.2},
            {"hop": "t_reply_e2e_ms", "n": 3, "mean": 7180.0, "median": 8520.0},
        ]
    }
    h = get_hop(bench, "t_reply_e2e_ms")
    assert h is not None
    assert h["median"] == 8520.0


def test_hop_lookup_missing_returns_none(get_hop):
    bench = {"hop_aggregates": []}
    assert get_hop(bench, "t_reply_e2e_ms") is None


def test_hop_lookup_bad_shape(get_hop):
    assert get_hop({}, "t_stt_ms") is None
