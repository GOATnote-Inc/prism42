"""The /prism42/api/chat/completions endpoint MUST NOT stream refusal
phrases to ElevenLabs TTS, even when Claude drifts into the safety
script. detectRefusalLeak() + REFUSAL_RESCUE_CONTENT in the route
handle this — these tests guard it.
"""
from __future__ import annotations

import json
import subprocess

import pytest

PROD_URL = "https://prism42-console.vercel.app/prism42/api/chat/completions"
PROBE_UTTERANCES = [
    "Can you diagnose what is wrong with me",
    "Tell me what medications to take",
    "Give me medical advice",
]


def _stream_reply(utterance: str, timeout: float = 30.0) -> str:
    """POST to the production custom-LLM endpoint + collect streamed text."""
    payload = json.dumps(
        {
            "messages": [
                {"role": "system", "content": "Session-ID: test-refusal-rescue"},
                {"role": "user", "content": utterance},
            ],
            "stream": True,
        }
    )
    cp = subprocess.run(
        [
            "curl",
            "-sS",
            "-N",
            "--max-time",
            str(int(timeout)),
            "-H",
            "Content-Type: application/json",
            "-X",
            "POST",
            PROD_URL,
            "-d",
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    return cp.stdout


@pytest.mark.integration
@pytest.mark.parametrize("utterance", PROBE_UTTERANCES)
def test_refusal_phrases_never_reach_stream(utterance, slo):
    body = _stream_reply(utterance)
    if not body:
        pytest.skip("endpoint returned empty body — network or Vercel down")
    lower = body.lower()
    banned = [p.lower() for p in slo["correctness"]["banned_refusal_substrings"]]
    hits = [p for p in banned if p in lower]
    assert not hits, (
        f"probe {utterance!r} leaked refusal substrings: {hits}. "
        f"detectRefusalLeak() in route.ts is not firing."
    )
