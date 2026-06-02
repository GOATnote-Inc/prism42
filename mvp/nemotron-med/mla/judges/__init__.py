"""Sovereign judges for HealthBench rubric grading.

The default judge is `make_triton_judge` — calls a locally-served OpenAI-
compatible endpoint (TRT-LLM/Triton or vLLM) for rubric grading. No cloud
LLM keys; the judge runs on the H100 pod alongside the H200 serve.

Two implementations:
  - `make_triton_judge`        rubric grader via OpenAI-compatible chat
                               (Llama-3.1-Nemotron-70B-Instruct AWQ-int4
                               on H100 by default).
  - `make_reward_model_judge`  scalar Reward-model grader via /score
                               (Llama-3.1-Nemotron-70B-Reward on H100),
                               thresholded to {met, not-met} per item.

Both return the same Callable[[str, RubricItem], dict] shape as
`scripts.healthbench_runner._make_anthropic_judge`, so they are drop-in
replacements behind the same call site.
"""

from __future__ import annotations

from .reward import make_reward_model_judge
from .triton import make_triton_judge

__all__ = ["make_triton_judge", "make_reward_model_judge"]
