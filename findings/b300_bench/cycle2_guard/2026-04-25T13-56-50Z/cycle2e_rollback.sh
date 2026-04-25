#!/usr/bin/env bash
# Cycle-2e orchestrator + worker patch rollback (bash -n verification target)
set -e
ssh prism-mla-b300-h4h5 'sudo cp /opt/prism42/agents/livekit/orchestrator.py.pre-cycle2e /opt/prism42/agents/livekit/orchestrator.py'
ssh prism-mla-b300-h4h5 'sudo cp /opt/prism42/agents/livekit/worker.py.pre-cycle2e /opt/prism42/agents/livekit/worker.py'
ssh prism-mla-b300-h4h5 'sha256sum /opt/prism42/agents/livekit/worker.py'
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-worker'
ssh prism-mla-b300-h4h5 'systemctl is-active prism42-worker'
