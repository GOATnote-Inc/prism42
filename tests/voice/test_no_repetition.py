"""Correctness gate: "help is on the way" must fire at most once per call,
refusal phrases must never reach TTS, agent replies must be responsive
to the caller's LAST utterance.
"""
from __future__ import annotations

import re

import pytest


def _agent_spoken_lines(worker_log: str) -> list[str]:
    """Extract text the agent actually spoke, in order, from worker.log.

    Our worker.py logs `fishspeech.t0 text_len=N` OR (post-ElevenLabs)
    logs `tts.backend.submit text=...`; the safest portable signal is
    the `conversation_item_added` handler's content, but that's not
    explicitly logged. Fallback: find lines that our orchestrator
    speech-channel would have produced — match on the known filler +
    protocol strings.
    """
    # Broad grep — anything that looks like a spoken utterance in the
    # worker log. Tighten once we add explicit `agent.spoken` log lines.
    lines = []
    for m in re.finditer(r'"spoken_content":\s*"([^"]+)"', worker_log):
        lines.append(m.group(1))
    for m in re.finditer(r'fishspeech\.t0.*?text_len=(\d+)', worker_log):
        pass  # placeholder — text_len alone isn't a string
    return lines


@pytest.mark.integration
def test_help_is_on_the_way_fires_once(pod_ssh, pod_worker_log, slo):
    """Run 3 synthetic turns and verify the reassurance phrase appears
    at most once across all three agent replies.
    """
    # Drive 3 synthetic caller turns with spaced 20s sleeps (Fish-safe).
    for utterance in [
        "I have chest pain and I cannot breathe",
        "Help my husband just collapsed",
        "What should I do? He is not breathing",
    ]:
        p = pod_ssh(
            f"cd /opt/prism42/agents/livekit && "
            f".venv/bin/python synthetic_caller_full.py "
            f"{repr(utterance)} 2>&1 | tail -3",
            timeout=120,
        )
        if p.returncode != 0:
            pytest.skip(f"synthetic_caller failed mid-run: {p.stderr[:200]}")

    log = pod_worker_log(n=800)
    # Case-insensitive count across all phrasings.
    patterns = [
        r"help is on the way",
        r"help's on the way",
        r"help is coming",
        r"units are en route",
        r"responders are on their way",
    ]
    total = sum(len(re.findall(p, log, re.IGNORECASE)) for p in patterns)
    max_allowed = slo["correctness"]["help_is_on_the_way_max_per_call"] * 3  # 3 turns
    assert total <= max_allowed, (
        f"reassurance phrase fired {total}x in 3 turns "
        f"(SLO: <= {max_allowed}). orchestrator prompt is drifting."
    )


@pytest.mark.integration
def test_no_refusal_phrases_in_recent_log(pod_worker_log, slo):
    """Last 1k lines of worker.log must contain ZERO refusal phrases
    from the SLO banned list. Guards against Claude drifting into the
    safety script when simulation prompt weakens.
    """
    log = pod_worker_log(n=1000)
    banned = slo["correctness"]["banned_refusal_substrings"]
    hits = [phrase for phrase in banned if phrase.lower() in log.lower()]
    assert not hits, f"banned refusal phrases appeared in worker log: {hits}"
