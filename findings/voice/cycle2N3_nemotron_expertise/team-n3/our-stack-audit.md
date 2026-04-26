# Our Stack vs Nemotron-Recommended — Audit

**Author:** Team N3, prism42 cycle-2N3
**Sources:** all citations dated 2026-04-26.

## Side-by-side

| Item | NVIDIA-recommended (cookbook + recipes) | What we ship | Verdict |
|---|---|---|---|
| **Tool-call parser** | `--tool-call-parser qwen3_coder` | `qwen3_coder` (`launch-vllm-cycle2S.sh:57`) | CORRECT. (vLLM blog `deepseek_r1` listing is wrong; cookbook + recipes both confirm `qwen3_coder` is the right choice.) [vLLM recipes](https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html) |
| **Reasoning parser** | `--reasoning-parser nano_v3 --reasoning-parser-plugin nano_v3_reasoning_parser.py` | `nano_v3` + plugin file (`launch-vllm-cycle2S.sh:38, 58-59`) | CORRECT. |
| **Auto tool choice** | `--enable-auto-tool-choice` | enabled (`launch-vllm-cycle2S.sh:56`) | CORRECT — but currently *unused*: our orchestrator passes `tools=[]` (`orchestrator.py:761`). The flag is harmless when no tools are sent. |
| **MoE backend env** | `VLLM_USE_FLASHINFER_MOE_FP4=1`, `VLLM_FLASHINFER_MOE_BACKEND=throughput`, `VLLM_ATTENTION_BACKEND=FLASHINFER` | All three set (`launch-vllm-cycle2S.sh:25-27`) | CORRECT — verified in startup log: `Using 'FLASHINFER_CUTLASS' NvFp4 MoE backend`. |
| **kv-cache-dtype** | `fp8` for FP8 model; `fp8` recommended for NVFP4 in cookbook cell 11 | `fp8` | CORRECT. |
| **Trust-remote-code** | required (custom `NemotronHForCausalLM` arch) | set | CORRECT. |
| **Tensor parallel** | `--tensor-parallel-size 1` for single-GPU | `1` | CORRECT. |
| **Async scheduling** | `--async-scheduling` (recipes) | not in launch script BUT enabled by default in vLLM 0.20 (Team M log: `Asynchronous scheduling is enabled`) | OK (latent — see Team M's L7b for persistence). |
| **Chat template** | model ships its own jinja; vLLM auto-loads it via `trust_remote_code` | not overridden (no `--chat-template` flag) | CORRECT. We use the model's bundled `<|im_start|>...<|im_end|>` ChatML template. |
| **System message format** | Plain text inside `<|im_start|>system\n...\n<|im_end|>` (the model sees pure prose; **no markdown/XML scaffolding required**) | We pass plain text, but it's a 4 KB prose protocol with markdown-style `# CONTEXT` / `# YOUR JOB` / `# HARD RULES` headers (`orchestrator.py:495-729`) | OK in form (Nemotron tolerates plain prose system messages); see audit-finding A1 below. |
| **`enable_thinking` flag** | Default `True`; explicit `False` if you want to skip the reasoning trace | NOT set anywhere in our code. Default `True` is in effect. | **AUDIT FINDING A2** — we are paying the reasoning latency on every turn. |
| **Reasoning-budget control** | Two-call `ThinkingBudgetClient` OR `ThinkingBudgetLogitsProcessor` env+flag | Not used. | OK — only relevant if A2 stays on. |
| **Sampling — tool-calling** | `temperature=0.6, top_p=0.95` | n/a (we don't tool-call) | OK. |
| **Sampling — reasoning** | `temperature=1.0, top_p=1.0` | LLM is configured by LiveKit's OpenAI-compatible client (`worker.py`). Not audited here — defer to Team R3. | DEFER. |
| **`max_tokens`** | Recipes: "recommend setting a high value" because reasoning eats tokens | Per Team M, our test probes use `max_tokens=48` which trips `finish_reason=length` 4% of the time | **AUDIT FINDING A3** — too tight when reasoning is ON. |
| **Tools=[]** | model card emits a 250-token tool catalog if `tools=[]` is non-empty; otherwise zero overhead | We pass `tools=[]` (`orchestrator.py:761`) | CORRECT — we pay zero tool-catalog overhead. (This is a missed opportunity for FSM-as-tool, see `recommendations.md` R1.) |

## Findings

### A1 — System prompt is a 4 KB prose monolith with markdown headers

The model expects plain text inside the `system` turn; markdown headers like `# CONTEXT` are tolerated but consumed as plain prose (no special parsing). The 4 KB length itself (`FAST_DISPATCHER_SYSTEM_PROMPT`) is fine — Nemotron's 256K context floor swallows it trivially. **The real issue:** the FSM rewrites the system prompt every turn (`update_instructions(prompt)` at `orchestrator.py:455`), which destroys prefix-cache reuse. Team M already documented this as 0% prefix-cache hit rate over 215 K queries (`profile.md:75-87`). The fix is architectural — split the system prompt into a stable header + per-turn mutable footer — but the orchestrator is on the frozen-paths list per the hackathon §0 charter. **Note for cycle-2T+:** when the freeze lifts, this is the highest-leverage prompt-caching win.

### A2 — Reasoning is ON by default and we never disable it

Per `chat_template.jinja` cell 23, `enable_thinking` defaults to `True`. Our orchestrator does not set `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` anywhere, so every PSAP turn pays the reasoning-trace cost. With our 5-12 word target replies (10-30 spoken tokens) and a typical reasoning trace of 50-300 tokens at our measured 313 tokens/s decode, **reasoning currently inflates LLM TTFB by 150-950 ms per turn**, all of it before the first speakable byte hits Fish TTS. This is the largest immediately addressable LLM-tier latency win. See `recommendations.md` R2.

### A3 — `max_tokens` budget is small enough to truncate replies

Team M's curl probe (`profile.md:160-170`) and the 4% `finish_reason=length` rate confirm replies are getting cut off. With reasoning ON (A2), even a "short" PSAP reply needs ~64-256 completion tokens to clear the reasoning trace and emit the 5-12 user-visible words. The current effective budget is too tight. Fix lands jointly with R2: when we disable reasoning, `max_tokens=64` is sufficient; when we keep it on, `max_tokens >= 384` is needed.

### A4 — Tool-calling parser is correct, but unused

`--tool-call-parser qwen3_coder --enable-auto-tool-choice` are wired correctly. We just never pass `tools=[]` non-empty in the hot path. This is a deliberate cycle-2P/2T architecture choice (deterministic FSM + templates instead of model-driven dispatch), not a bug. **The infrastructure is hot-pluggable** if we decide to expose FSM intents as a tool surface (see `recommendations.md` R1). No change needed unless R1 is adopted.

### A5 — vLLM blog post is misleading on reasoning parser

The official [vLLM blog](https://blog.vllm.ai/2025/12/15/run-nvidia-nemotron-3-nano.html) lists `--reasoning-parser deepseek_r1`. **This is wrong.** Per the cookbook and the recipes page, the correct parser is `nano_v3` with the plugin. The blog appears to have been drafted before NVIDIA shipped the `nano_v3` plugin file. Our launcher (`launch-vllm-cycle2S.sh:58-59`) uses `nano_v3` correctly. Do **not** copy the vLLM blog example into a future doc.

## Bottom line

We are using the right parsers, the right MoE backend, and the right chat template. The two correctness/latency wins are **A2 (disable reasoning)** and **A3 (right-size `max_tokens`)** — both are runtime config knobs, no code edits required. Both tracked in `recommendations.md` R2.

Word count: ~640.
</content>
</invoke>