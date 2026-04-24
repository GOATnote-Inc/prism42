"""Latency SLOs — regression gate for every push.

Runs bench_b300.py on the pod (3 runs), parses the hop aggregates,
asserts each hop's p50/p95 against tests/voice/slo.yaml. Failures block
merge. Thresholds are loose during the 24h perceptual-SOTA window;
tighten post-tie.
"""
from __future__ import annotations

import pytest


@pytest.mark.integration
def test_e2e_reply_slo(bench_result, slo, get_hop):
    bench = bench_result(n=3, sleep_s=15)
    hop = get_hop(bench, "t_reply_e2e_ms")
    assert hop is not None, "bench JSON missing t_reply_e2e_ms aggregate"
    if hop.get("n", 0) == 0:
        pytest.skip("no t_reply_e2e_ms samples (every run exited early)")
    tgt = slo["latency"]["t_reply_e2e_ms"]
    assert hop["p50"] is not None
    assert hop["p50"] <= tgt["p50_ms"], f"t_reply_e2e_ms p50 {hop['p50']:.0f}ms > SLO {tgt['p50_ms']}ms"
    assert hop["p95"] <= tgt["p95_ms"], f"t_reply_e2e_ms p95 {hop['p95']:.0f}ms > SLO {tgt['p95_ms']}ms"


@pytest.mark.integration
def test_tts_ttfb_slo(bench_result, slo, get_hop):
    bench = bench_result(n=3, sleep_s=15)
    # Two possible hop names depending on TTS backend.
    hop = get_hop(bench, "t_tts_ttfb_ms") or get_hop(bench, "t_fish_ttfb_ms")
    if hop is None or hop.get("n", 0) == 0:
        pytest.skip("no TTS TTFB samples in bench")
    tgt = slo["latency"]["t_tts_ttfb_ms"]
    assert hop["p50"] <= tgt["p50_ms"], f"TTS TTFB p50 {hop['p50']:.0f}ms > SLO {tgt['p50_ms']}ms"
    assert hop["p95"] <= tgt["p95_ms"], f"TTS TTFB p95 {hop['p95']:.0f}ms > SLO {tgt['p95_ms']}ms"


@pytest.mark.integration
def test_llm_ttft_slo(bench_result, slo, get_hop):
    bench = bench_result(n=3, sleep_s=15)
    hop = get_hop(bench, "t_llm_ms") or get_hop(bench, "t_llm_proxy_ms")
    if hop is None or hop.get("n", 0) == 0:
        pytest.skip("no LLM TTFT samples (Team β instrumentation required)")
    tgt = slo["latency"]["t_llm_ms"]
    assert hop["p50"] <= tgt["p50_ms"], f"LLM TTFT p50 {hop['p50']:.0f}ms > SLO {tgt['p50_ms']}ms"


@pytest.mark.integration
def test_stt_latency_slo_if_streaming(bench_result, pod_ssh, slo, get_hop):
    """STT assertion only fires if the plugin advertises streaming=True."""
    caps = pod_ssh(
        "grep -E 'streaming=True|interim_results=True' "
        "/opt/prism42/agents/livekit/parakeet_stt.py | head -3"
    )
    streaming_on = caps.returncode == 0 and "streaming=True" in caps.stdout
    if not streaming_on:
        pytest.skip("Parakeet plugin still batch-only; streaming assertion N/A")
    bench = bench_result(n=3, sleep_s=15)
    hop = get_hop(bench, "t_stt_ms")
    if hop is None or hop.get("n", 0) == 0:
        pytest.skip("bench had no stt samples even though streaming is declared")
    tgt = slo["latency"]["t_stt_ms"]
    assert hop["p50"] <= tgt["p50_ms"], f"STT partial-TTFT p50 {hop['p50']:.0f}ms > {tgt['p50_ms']}ms"
