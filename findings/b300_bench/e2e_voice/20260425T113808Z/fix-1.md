# Fix 1: VLLM_MODEL drop-in

## Symptom (Turn 1)
- Exit code 4 ("pre-roll never spoke (TTS broken)").
- Reply did eventually arrive at +7.51s after caller end (peak 21218), but agent never spoke its opening greeting.
- worker.log showed: `'The model 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4' does not exist.', 'type': 'NotFoundError', 'param': 'model', 'code': 404`.

## Root cause
- vLLM is launched with `--served-model-name nemotron-nano`. Per OpenAI-compatible API spec, clients must use the served-model-name in their requests, NOT the HF root path.
- `worker.py:340` defaults `VLLM_MODEL` env var to `"nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4"` (the HF root, not the served name).
- `.env` does not override `VLLM_MODEL`, so the worker sent the wrong name.
- Pre-roll greeting was attempted via OpenAI-LLM call -> vLLM 404 -> no LLM tokens -> no TTS -> verdict "TTS broken".
- Reply at +7.51s was the framework's filler ("Okay, stay with me.") spoken from a hard-coded string, NOT from the LLM. fishspeech.done shows `chunk_count=3 max_chunk_gap_ms=2347`.

## Fix
- Created systemd drop-in `/etc/systemd/system/prism42-worker.service.d/10-vllm-model.conf`:
  ```
  [Service]
  Environment="VLLM_MODEL=nemotron-nano"
  ```
- `daemon-reload` + `restart prism42-worker`.
- Verified: `systemctl show prism42-worker -p Environment` now contains `VLLM_MODEL=nemotron-nano`. Service `active` post-restart.

## Justification: drop-in over .env edit
- Drop-in is non-secret-bearing, atomic, version-controllable, and reversible (`rm /etc/systemd/system/prism42-worker.service.d/10-vllm-model.conf` + restart).
- Avoids touching .env where API keys live.
- Mainline-safe: no code change, no Phase E env var change.
