# Nemotron 3 Nano 30B-A3B-NVFP4 — Knowledge Base

**Author:** Team N3, prism42 cycle-2N3
**Fetch date for all external sources:** 2026-04-26
**Scope:** authoritative reference for the PSAP dispatcher voice path. Companion to Team M's `cycle2S_b300_memory/team-m/profile.md` (perf/memory) and Team R3's regression diagnosis (separate lane). Do not duplicate Team M's CUDA/HBM findings.

---

## 1. Identity

- **Model:** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`
- **Released:** 2025-12-15 with the NVIDIA Nemotron 3 family (Nano 30B-A3B, Nano 4B, plus base variants).
- **License:** [NVIDIA Nemotron Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license/) — commercial use permitted with safety-guardrail preservation clause.
- **Quantization variant in use here:** NVFP4 (Blackwell-native 4-bit MoE). Sister variants: BF16 (~64 GB VRAM), FP8 (~32 GB VRAM), NVFP4 (~20 GB VRAM). [HF cookbook, cell 1](https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3-Nano/vllm_cookbook.ipynb).

## 2. Architecture (verbatim from the technical report)

Source: [NVIDIA Nemotron 3 Nano Technical Report, arXiv:2512.20848v1](https://arxiv.org/html/2512.20848v1) (Table 1).

- **Family:** hybrid **Mamba-2 + Transformer + MoE**. Not a pure transformer. This matters for prefix caching, FA backends, and speculative decoding compatibility.
- **Total params:** 31.6 B; **active per token:** 3.2 B (3.6 B incl. embeddings). Hence the "30B-A3B" name (~3 B Active).
- **Layer composition:** 52 layers total — 23 Mamba-2, 23 MoE FFN, 6 GQA attention.
- **MoE config:** 128 routed experts + 1 shared expert per MoE layer; **6 experts activated per token**.
- **Attention:** Grouped-Query Attention, 32 query heads / 2 KV heads, head dim 128 (so very narrow GQA → cheap KV cache per token, but only 2 KV heads to share).
- **Mamba-2:** state dim 128, 8 groups, 64 heads, 64 head dim.
- **Context:** **up to 1 M tokens** trained; HF default config caps at 256 K for VRAM. RULER@1M = 86.3 (state-of-the-art among open MoE).
- **Training:** 25 T tokens (94 % phase-1 broad, 6 % phase-2 high-quality, 121 B long-context). 18 M SFT samples spanning math, code, tool-use, instruction-following, multilingual (55 langs), formal proofs, terminal tasks, safety. RLVR on 22 K coding + 49 K instruction-following tasks among others.

## 3. Benchmarks (model-card numbers, fetched 2026-04-26)

Source: [HF model card NVIDIA-Nemotron-3-Nano-30B-A3B-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) tables, fetched 2026-04-26. NVFP4 weights are derived from the BF16 reference model and inherit the scores ± quant noise (NVIDIA does not publish a separate NVFP4 column — they assert near-parity).

**Most relevant to PSAP dispatcher:**

| Benchmark | Nemotron-3-Nano | Qwen3-30B-A3B | GPT-OSS-20B | Sonnet 4.6 / Opus 4.7 |
|-----------|------:|------:|------:|------:|
| **IFBench (prompt)** | **71.5** | 51.0 | 65.0 | n/a (not on this leaderboard) |
| Arena-Hard-V2 (avg) | **67.7** | 57.8 | 48.6 | n/a |
| MMLU-Pro | 78.3 | 80.9 | 75.0 | n/a |
| BFCL v4 (function calling) | **53.8** | 46.4 | n/a | n/a |
| Multi-Challenge | 38.5 | **44.8** | 33.8 | n/a |

**Reasoning / agentic (less relevant for our 5-12-word voice replies, but useful framing):** AIME25-no-tools 89.1, AIME25-with-tools 99.2, GPQA-no-tools 73.0, SWE-Bench (OpenHands) 38.8, TauBench V2 avg 49.0.

**Throughput claim from the tech report (Section "Inference speed"):** *"3.3× faster than Qwen3-30B-A3B-Thinking-2507; 2.2× faster than GPT-OSS-20B"* on a single H200 with 8 K input / 16 K output, measured with vLLM and TRT-LLM. No absolute tokens/sec was published.

**Calibration takeaway for PSAP:**
- IFBench 71.5 is high relative to Qwen-3 (51.0) and GPT-OSS-20B (65.0), but it is **not 95+**. Roughly **1 in 3 instructions are violated** at the prompt level. Our cycle-2T response gate exists precisely because of this tail; the model card data validates the gate's design.
- BFCL 53.8 means the model can produce function-call JSON ~54 % correctly out of the box. We currently use **no tool calls** in the voice hot path, so this number is forward-looking, not blocking.
- The model is not specifically tuned for emergency-response language. Its strong "agentic reasoning" benchmarks were earned on coding/math, not 911 dispatch.

## 4. Chat template — verbatim format

Source: [chat_template.jinja](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/blob/main/chat_template.jinja) fetched 2026-04-26.

**The model is `<|im_start|> / <|im_end|>` — Qwen-/ChatML-family,** with one critical addition: **every assistant turn must contain a `<think>...</think>` block, even when reasoning is disabled.**

### 4.1 Token vocabulary

- `<|im_start|>` (turn opener)
- `<|im_end|>` (turn closer)
- `<think>` (token id 12) and `</think>` (token id 13) — mandatory wrapper around any reasoning trace
- `<tool_call>` ... `</tool_call>` — wrapper around a function call
- `<function=NAME>` ... `</function>` — XML-style function-name container (Qwen-3-Coder convention)
- `<parameter=NAME>` ... `</parameter>` — XML parameter container
- `<tool_response>` ... `</tool_response>` — wrapper around the tool's reply (rendered into a synthetic `user` turn)
- `<tools>` ... `</tools>` — the rendered tool catalog inside the system message

### 4.2 Skeleton (no tools, reasoning ON, default)

```
<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_text}<|im_end|>
<|im_start|>assistant
<think>
{model writes reasoning here}
</think>
{model writes the final user-visible reply here}<|im_end|>
```

### 4.3 Skeleton (reasoning OFF)

When `enable_thinking=False` is passed to `tokenizer.apply_chat_template`, the generation prompt becomes:

```
<|im_start|>assistant
<think></think>{final reply here}<|im_end|>
```

i.e. the empty `<think></think>` pair is **prepended for the model**, so it cannot emit a reasoning trace. The reply starts immediately after `</think>`.

**This matters:** disabling reasoning is not "the model decides not to think". It is a hard structural constraint baked into the prompt by the tokenizer.

### 4.4 Skeleton (with tools)

When the request includes `tools=[...]`, the system message gets a hard-coded suffix (verbatim from the Jinja template):

```
# Tools

You have access to the following functions:

<tools>
<function>
<name>{tool_name}</name>
<description>{...}</description>
<parameters>
<parameter>
<name>{param_name}</name>
<type>{string|integer|...}</type>
<description>{...}</description>
</parameter>
... more parameters ...
<required>["param_a", "param_b"]</required>
</parameters>
</function>
... more functions ...
</tools>

If you choose to call a function ONLY reply in the following format with NO suffix:

<tool_call>
<function=example_function_name>
<parameter=example_parameter_1>
value_1
</parameter>
<parameter=example_parameter_2>
This is the value for the second parameter
that can span
multiple lines
</parameter>
</function>
</tool_call>

<IMPORTANT>
Reminder:
- Function calls MUST follow the specified format: an inner <function=...></function> block must be nested within <tool_call></tool_call> XML tags
- Required parameters MUST be specified
- You may provide optional reasoning for your function call in natural language BEFORE the function call, but NOT after
- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls
</IMPORTANT>
```

This catalog block is **emitted by the chat template, not the user**. It costs ~250 tokens per tool. Tool-rendering is bypassed entirely when `tools=[]` is omitted.

## 5. Reasoning toggle — three call sites

Per [HF cookbook cell 24](https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3-Nano/vllm_cookbook.ipynb), there are three ways to control thinking:

1. **Python tokenizer (offline):** `tokenizer.apply_chat_template(messages, enable_thinking=False, add_generation_prompt=True)`.
2. **OpenAI client → vLLM:**
   ```python
   client.chat.completions.create(
       model="nemotron",
       messages=...,
       extra_body={"chat_template_kwargs": {"enable_thinking": False}},
   )
   ```
3. **Raw vLLM HTTP:** `{"chat_template_kwargs": {"enable_thinking": false}}` as a top-level body field.

**Default is `True`.** When omitted, every reply includes a reasoning trace.

**Reasoning-budget controls** are also supported:
- `max_tokens=reasoning_budget` two-call pattern (cookbook cell 29).
- `THINKING_BUDGET_LOGITS_PROCESSOR_ARGS` env + `--logits-processors custom_logit_processors.v1.nano_v3_logit_processors:ThinkingBudgetLogitsProcessor` for single-call truncation (cookbook cell 35-37). `end_think_ids=[[13]]` (the `</think>` token id), `prompt_think_ids=[12, 1010]` recognize the thinking phase.

**Latency cost of reasoning ON for our PSAP path:** PSAP replies are 5-12 words = 10-30 spoken tokens. With reasoning ON, the model emits a `<think>...</think>` block of typically 50-300 tokens before the first user-visible token. At our measured 313 tokens/s decode (Team M), that's **+150 ms to +950 ms TTFT** before the first speakable byte. **Reasoning is currently on** in our launcher (no `chat_template_kwargs` override). This is the largest immediately addressable latency win on the LLM tier.

## 6. Tool calling — wire format and parser

Sources: [HF chat_template.jinja](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/blob/main/chat_template.jinja); [vLLM recipes Nemotron-3-Nano](https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html); [HF cookbook cell 18, 27](https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3-Nano/vllm_cookbook.ipynb).

### 6.1 Parser names (verified)

- **Tool-call parser:** `qwen3_coder` (model uses Qwen-3-Coder XML conventions).
- **Reasoning parser:** `nano_v3` — **requires** `--reasoning-parser-plugin nano_v3_reasoning_parser.py` (the plugin file ships with the HF model repo).

The vLLM blog post originally listed `--reasoning-parser deepseek_r1` ([vLLM blog 2025-12-15](https://blog.vllm.ai/2025/12/15/run-nvidia-nemotron-3-nano.html)). **That is wrong / superseded.** The official cookbook and recipes page now both specify `nano_v3` with the plugin file. There is a known issue — see §8.1.

### 6.2 What the model actually emits

After Nemotron generates its reply, vLLM's `qwen3_coder` parser pulls the XML and rewrites it into OpenAI-compatible JSON. The model's raw output looks like:

```
<think>The user wants a tip on $50 at 15%. I'll call calculate_tip.</think>
<tool_call>
<function=calculate_tip>
<parameter=bill_total>
50
</parameter>
<parameter=tip_percentage>
15
</parameter>
</function>
</tool_call>
```

After parsing, the OpenAI client sees:

```python
choice.message.reasoning_content == "The user wants a tip on $50 at 15%. I'll call calculate_tip."
choice.message.tool_calls == [
    ChatCompletionMessageToolCall(
        id="call_xxx",
        type="function",
        function=Function(
            name="calculate_tip",
            arguments='{"bill_total": 50, "tip_percentage": 15}',
        ),
    ),
]
choice.message.content is None  # tool-call turn has no user-visible content
```

### 6.3 Recommended sampling params (HF model card, fetched 2026-04-26)

- **Reasoning tasks (default):** `temperature=1.0, top_p=1.0`. Verbatim model-card guidance.
- **Tool calling:** `temperature=0.6, top_p=0.95`. Verbatim model-card guidance.
- **Non-reasoning (greedy):** `do_sample=False, num_beams=1, max_new_tokens=32`.

The cookbook's tool-calling example uses `max_tokens=512` because tool-call traces tend to include reasoning even with reasoning ON; budgets shorter than ~256 will frequently `finish_reason=length` truncate the JSON mid-write (see §8.1).

## 7. Hardware & vLLM compatibility

- **Inference engines (model-card declared):** HF Transformers, vLLM ≥ 0.12.0, TRT-LLM, SGLang, llama.cpp.
- **GPUs (model-card declared):** H100-80 GB, A100, **B200-192 GB**, RTX PRO 6000, Jetson Thor, DGX Spark. **B300 is not listed**, but B300 (sm_103) is forward-compatible with sm_100 kernels via PTX JIT — and Team M has confirmed our pod runs the NVFP4 path on B300 with `FLASHINFER_CUTLASS` MoE backend at 313 tokens/s decode, 50 ms median TTFT.
- **NVFP4 requires Blackwell.** FP8 works on Hopper (H100/H200). BF16 works everywhere.
- **Critical env vars for NVFP4:** `VLLM_USE_FLASHINFER_MOE_FP4=1`, `VLLM_FLASHINFER_MOE_BACKEND=throughput`, `VLLM_ATTENTION_BACKEND=FLASHINFER`. Without these, vLLM auto-selects `FLASHINFER_TRTLLM` MoE which pads `hidden_size` 2688 → 2816 and produces JS-garbage. (Team M confirmed our launcher persists these.)

## 8. Known failure modes (from GitHub issues + HF discussions)

### 8.1 "Tool calling with reasoning parsing broken" — vLLM ≤ 0.12.0

Source: [HF discussion #3](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3) fetched 2026-04-26.

User report 2025-12-15: with `vllm==0.12.0` + `--tool-call-parser qwen3_coder` + `--reasoning-parser nano_v3`, the model emits the reasoning content twice — once into `reasoning_content`, once into `content`. Tool calls also occasionally appear malformed.

NVIDIA response (verbatim): *"The reasoning content being replicated twice is expected — VLLM does output the reasoning content in both keys. With an adequate token budget specified in the request (so that the model doesn't get cut off), I do see the tool parsing working as expected."*

**Root causes:**
1. `--reasoning-parser deepseek_r1` is incompatible with tool calls (vLLM doc: "DeepSeek reasoning parser does not work with tool calls"). The vLLM-blog example used `deepseek_r1`; **do not copy it**.
2. Inadequate `max_tokens` truncates the JSON after `<think>...</think>` but before `</tool_call>`, leaving an unparseable response.

**Fix:** use `--reasoning-parser nano_v3 --reasoning-parser-plugin nano_v3_reasoning_parser.py` (which we already do), and ensure `max_tokens` is generous enough that the reasoning trace + tool call both fit. PR [#30671](https://github.com/vllm-project/vllm/pull/30671) on the vLLM `main` branch (~Dec 15 2025) further hardened the parser; **our build (`0.20.1.dev0+g101584af0.d20260425`) is post-fix** per Team M's launcher.

### 8.2 Empty `content` field — Issue #30904

Source: [vllm issue #30904](https://github.com/vllm-project/vllm/issues/30904).

On NVFP4, requests with `enable_thinking=False` and very short `max_tokens` (e.g. 32) sometimes return `content=""` because the parser strips the `<think></think>` wrapper but the model exits before emitting any post-`</think>` text. **Mitigation:** keep `max_tokens >= 64` even on tightly-budgeted voice replies, and ensure `chat_template_kwargs.enable_thinking=False` is set (so the pre-pended empty `<think></think>` does not consume budget).

### 8.3 "Guidance structured output blocked during thinking" — Issue #37362

Source: [vllm issue #37362](https://github.com/vllm-project/vllm/issues/37362).

When using `vllm.LLM.generate()` with `guided_json` / `guided_regex` AND the `nano_v3` reasoning parser, the guidance FSM constrains tokens **from the very first token** instead of waiting for `</think>`. Result: the model emits thousands of `{` characters because its thinking-phase tokens are forced into the JSON grammar.

**Implication for us:** if we ever add `guided_json` to bound the response gate's regen, we **must** disable reasoning (`enable_thinking=False`) on that specific call, OR use the OpenAI server endpoint (which handles it correctly) rather than the offline `LLM.generate()` API. Our voice path uses the OpenAI server endpoint, so this is forward-looking.

### 8.4 NemotronH architecture probing — Issue #33515

Source: [vllm issue #33515](https://github.com/vllm-project/vllm/issues/33515). Cosmetic — vLLM emits `Error in inspecting model architecture 'NemotronHForCausalLM'` on startup but model loads correctly. Ignorable.

### 8.5 Hallucinated tools — `str_replace_editor`

Source: HF discussion #3 (linked above).

The model occasionally hallucinates calls to tools that exist in the Anthropic / OpenCode ecosystem (`str_replace_editor`) but are not in the request's `tools=[]`. Indicates Claude/coding-agent training-data leakage. **Implication for PSAP:** if we expose tools, we must validate tool-name against our schema and re-prompt on hallucination.

## 9. Version pinning

Per the [vLLM recipes page](https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html) (fetched 2026-04-26), the canonical serve command for Nemotron-3-Nano is:

```bash
vllm serve nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-$DTYPE \
  --trust-remote-code \
  --async-scheduling \
  --kv-cache-dtype $KV_CACHE_DTYPE \
  --tensor-parallel-size 1
```

with **`--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser nano_v3 --reasoning-parser-plugin nano_v3_reasoning_parser.py`** appended for tool/reasoning support.

**Minimum vLLM version:** 0.12.0 model-card claim, but tool-calling-with-reasoning is broken there; **practical minimum is 0.12.1 / nightly post-PR-30671**, or vLLM ≥ 0.13. Our build is `0.20.1.dev0` — well past that bar.

## 10. Sources

External (all fetched 2026-04-26):
1. HF model card BF16: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
2. HF chat template: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/blob/main/chat_template.jinja
3. NVIDIA technical report: https://arxiv.org/html/2512.20848v1
4. vLLM blog post (note: deepseek_r1 listing is wrong; use nano_v3): https://blog.vllm.ai/2025/12/15/run-nvidia-nemotron-3-nano.html
5. vLLM recipes Nemotron page: https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
6. NVIDIA cookbook notebook: https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3-Nano/vllm_cookbook.ipynb
7. HF discussion #3 (tool-call+reasoning bug): https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/discussions/3
8. vLLM issue #30904 (empty content): https://github.com/vllm-project/vllm/issues/30904
9. vLLM issue #34452 (sm_120 RTX-Pro-6000): https://github.com/vllm-project/vllm/issues/34452
10. vLLM issue #37362 (guidance blocked during thinking): https://github.com/vllm-project/vllm/issues/37362
11. vLLM issue #32093 (Jetson Thor): https://github.com/vllm-project/vllm/issues/32093
12. vLLM issue #32353 (TRTLLM attention broken on Blackwell): https://github.com/vllm-project/vllm/issues/32353
13. Unsloth Nemotron-3 guide: https://unsloth.ai/docs/models/nemotron-3

Internal (file:line):
- `/Users/kiteboard/prism42/findings/voice/cycle2S_b300_memory/team-m/profile.md` — perf/memory ground truth for our pod.
- `/Users/kiteboard/prism42/findings/voice/cycle2S_b300_memory/team-m/drop-ins/launch-vllm-cycle2S.sh:48-63` — current vLLM launch invocation.
- `/Users/kiteboard/prism42/agents/livekit/orchestrator.py:495-729` — current `FAST_DISPATCHER_SYSTEM_PROMPT`.
- `/Users/kiteboard/prism42/agents/livekit/dispatcher_fsm.py:108-141, 720-790` — Intent enum + `next_prompt()`.
- `/Users/kiteboard/prism42/agents/livekit/response_gate.py:288-351` — `gate_decision()`.
- `/Users/kiteboard/prism42/agents/livekit/templates.py:106-235` — 21 deterministic templates.
</content>
</invoke>