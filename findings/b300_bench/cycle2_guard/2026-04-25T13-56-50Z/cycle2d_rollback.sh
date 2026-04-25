#!/usr/bin/env bash
# Cycle-2d Fish FA patch rollback (bash -n verification target)
set -e
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech/src && git checkout HEAD -- fish_speech/models/text2semantic/inference.py fish_speech/models/text2semantic/llama.py'
ssh prism-mla-b300-h4h5 'cd /opt/prism42/infra/b300/services/fish-speech/src && git status -s fish_speech/ && git rev-parse HEAD'
ssh prism-mla-b300-h4h5 'sudo systemctl restart prism42-fish'
ssh prism-mla-b300-h4h5 'for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf -o /dev/null http://127.0.0.1:9200/ && echo "fish-up after ${i}s" && break; sleep 1; done'
