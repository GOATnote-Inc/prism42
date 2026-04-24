#!/usr/bin/env python3
"""
Fallback rubric-server: pure transformers + FastAPI, no vLLM, no FlashInfer,
no Triton compile paths. Sidesteps the sm_103a / nvcc 12.8 toolchain issue
that blocks vLLM 0.14.1 on stock Brev/Verda B300 pods.

Serves an OpenAI-compatible /v1/chat/completions endpoint so the prism42
lib/rubric-local.ts client can POST the same body shape it uses for the
vLLM path. Only the subset of the OpenAI API we need:
  - POST /v1/chat/completions with {model, messages, response_format,
    max_tokens, temperature}
  - GET  /v1/models (health check)

Expected latency profile on B300 eager (Qwen2.5-72B bf16):
  - prefill ~2k tokens: ~200-400 ms
  - decode ~100 output tokens at ~15 ms/token eager: ~1500 ms
  - total ~2 s p50 per rubric grade
  Slower than what vLLM with FlashInfer could do, but MATCH GPT-5.5's
  2-4 s ceiling is still achievable, and for the A/B experiment the
  relative latency is what matters.

Usage (on the pod):
  python3 scripts/b300_setup_rubric_transformers.py \\
      --model Qwen/Qwen2.5-72B-Instruct \\
      --port 8000 \\
      --served-name local_llama70b_nvfp4

Install deps (.venv must exist):
  source ~/workspace/prism-rubric/.venv/bin/activate
  pip install --quiet "transformers>=4.46" accelerate fastapi "uvicorn[standard]"
"""
from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.0
    response_format: Optional[Dict[str, Any]] = None


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]


state: Dict[str, Any] = {"model": None, "tokenizer": None, "served_name": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_id = os.environ["PRISM42_RUBRIC_MODEL_ID"]
    served_name = os.environ["PRISM42_RUBRIC_SERVED_NAME"]
    print(f"[rubric] loading {model_id} (bf16, device_map=auto)")
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        low_cpu_mem_usage=True,
        trust_remote_code=False,
    )
    model.eval()
    state["model"] = model
    state["tokenizer"] = tok
    state["served_name"] = served_name
    print(f"[rubric] loaded {model_id}; served_name={served_name}")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/v1/models")
def list_models():
    name = state.get("served_name") or "local_llama70b_nvfp4"
    return {
        "object": "list",
        "data": [
            {
                "id": name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "prism42-b300",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    tok = state.get("tokenizer")
    model = state.get("model")
    if tok is None or model is None:
        raise HTTPException(503, "model not loaded")

    prompt = tok.apply_chat_template(
        [m.model_dump() for m in req.messages],
        tokenize=False,
        add_generation_prompt=True,
    )

    # JSON-mode: append guidance so Qwen obeys `response_format:json_object`.
    if req.response_format and req.response_format.get("type") == "json_object":
        prompt += "\n(Respond with valid JSON only. No markdown fences.)\n"

    inputs = tok(prompt, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens or 512,
            do_sample=(req.temperature or 0.0) > 0,
            temperature=req.temperature or 0.0,
            pad_token_id=tok.eos_token_id,
        )
    gen_ids = out[0][inputs["input_ids"].shape[1]:]
    text = tok.decode(gen_ids, skip_special_tokens=True)

    # Strip to JSON if response_format requested.
    if req.response_format and req.response_format.get("type") == "json_object":
        s = text.strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.startswith("json"):
                s = s[4:]
        # try to take from first { to matching last }
        if "{" in s and "}" in s:
            s = s[s.index("{") : s.rindex("}") + 1]
        try:
            parsed = json.loads(s)
            text = json.dumps(parsed)
        except Exception:
            # leave text as-is; caller will parse
            pass

    return ChatResponse(
        id=f"chatcmpl-{int(time.time() * 1000)}",
        created=int(time.time()),
        model=state["served_name"],
        choices=[
            ChatChoice(
                message=ChatMessage(role="assistant", content=text),
                finish_reason="stop",
            )
        ],
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen2.5-72B-Instruct")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--served-name", default="local_llama70b_nvfp4")
    args = p.parse_args()
    os.environ["PRISM42_RUBRIC_MODEL_ID"] = args.model
    os.environ["PRISM42_RUBRIC_SERVED_NAME"] = args.served_name
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
