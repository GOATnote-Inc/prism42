"""TTS_BACKEND env flag must be honored: the worker logs the backend it
loads on every room-join. If we set elevenlabs, we'd better see
`tts.backend backend=elevenlabs` within 5 s of the next bench run.
"""
from __future__ import annotations

import re
import time

import pytest


@pytest.mark.integration
def test_tts_backend_env_is_reflected_in_log(pod_ssh, pod_worker_log, slo):
    # Read current .env
    p = pod_ssh("grep '^TTS_BACKEND=' /opt/prism42/agents/livekit/.env | head -1")
    if p.returncode != 0 or "=" not in p.stdout:
        pytest.skip("TTS_BACKEND not set on pod — test needs an explicit backend")
    declared = p.stdout.strip().split("=", 1)[1]
    assert declared in {"fish", "elevenlabs", "cartesia", "deepgram_aura"}, (
        f"unrecognized TTS_BACKEND value: {declared!r}"
    )

    # Trigger a room-join to generate a fresh log entry.
    pod_ssh(
        "cd /opt/prism42/agents/livekit && "
        ".venv/bin/python synthetic_caller.py 2>&1 | tail -3",
        timeout=60,
    )
    time.sleep(3)

    log = pod_worker_log(n=100)
    pat = re.compile(slo["backends"]["tts_backend_log_regex"])
    matches = pat.findall(log)
    if not matches:
        pytest.fail("no tts.backend log line after room-join")
    assert matches[-1] == declared, (
        f"worker loaded backend={matches[-1]!r} but .env says {declared!r}"
    )


@pytest.mark.integration
def test_required_tts_plugin_importable(pod_ssh, slo):
    """At least one of the listed TTS plugins must be importable on the
    pod. If the live one breaks, we need a fallback available.
    """
    any_ok = False
    for mod in slo["backends"]["required_tts_plugins_any_of"]:
        p = pod_ssh(
            f"cd /opt/prism42/agents/livekit && "
            f".venv/bin/python -c 'import {mod}; print(\"ok\")' 2>&1 | tail -1",
            timeout=15,
        )
        if p.returncode == 0 and "ok" in p.stdout:
            any_ok = True
            break
    assert any_ok, "none of the required TTS plugins are importable"
