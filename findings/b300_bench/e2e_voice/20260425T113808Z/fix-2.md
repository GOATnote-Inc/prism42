# Fix 2: VLLM_MAX_COMPLETION_TOKENS bump 256 -> 1024

## Symptom (sessions d16d1ba1, d02411fa, d45a46e1 — turns 6, 8, 10)
- `overlap.llm_first_token_after_speech_ms` logged (929-1182 ms TTFT).
- NO `LLMMetrics` event (LLM completion never finished). NO second `fishspeech.t0`. NO `transcript.post_ok role=assistant`.
- Harness reported `reply_latency_after_pubend=+0.50s` — that's harness misreading the pre-roll greeting tail as a post-publish reply.

## Root cause (per anticipator contingency #3)
- Nemotron-3-Nano emits its first 50-150 streamed tokens to `delta.reasoning_content` (NOT `delta.content`) before exiting its `<think>` block.
- livekit-plugins-openai 1.5.6's stream consumer accumulates only `delta.content`.
- With `max_completion_tokens=256`, the model can hit the budget BEFORE exiting `<think>` -> empty assistant content -> `session.say` short-circuits -> no TTS.
- All 3 affected sessions had this symptom: TTFT logged (reasoning began), but completion never produced real content.

## Fix
- Created systemd drop-in `/etc/systemd/system/prism42-worker.service.d/20-vllm-max-tokens.conf`:
  ```
  [Service]
  Environment="VLLM_MAX_COMPLETION_TOKENS=1024"
  ```
- daemon-reload + restart prism42-worker.
- Verified: env now contains BOTH `VLLM_MODEL=nemotron-nano` AND `VLLM_MAX_COMPLETION_TOKENS=1024`. Service `active`.

## Why this should help
- Quadruples the budget (256 -> 1024) so the model has runway to exit `<think>` AND produce response content.
- Anticipator notes this is the "coarser" fix vs `enable_thinking=False`; the coarser fix is appropriate as a single-line env-var tweak (no code change).
- A real production fix would also pass `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` but that requires editing worker.py LLM client kwargs — out of scope per the spec's mainline-safe rails.

## Cost
- Each turn now MAY consume up to 1024 tokens (vs 256). At Nemotron's 311 tok/s p50, worst-case completion time ~3.3s vs prior 0.8s. Real impact: only sessions that previously hit the 256 cap see longer completion. Healthy sessions (most) stay near 800ms.

## Rollback
- `rm /etc/systemd/system/prism42-worker.service.d/20-vllm-max-tokens.conf` + `systemctl daemon-reload` + `systemctl restart prism42-worker`.
