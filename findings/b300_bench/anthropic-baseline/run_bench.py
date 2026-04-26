#!/usr/bin/env python3
"""Anthropic Sonnet 4.6 TTFT baseline benchmark.

Measures TTFT (POST sent → first content_block_delta) and total latency
for 20 PSAP-dispatcher prompts using the same system prompt and model the
prism42 worker calls in production.

Usage:
    ANTHROPIC_API_KEY=<key> python run_bench.py

Output:
    bench.json  (same dir) — per-sample + aggregate data
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Production config — matches orchestrator.py + worker.py
# ---------------------------------------------------------------------------
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 64

FAST_DISPATCHER_SYSTEM_PROMPT = """\
# CONTEXT — READ FIRST

This is a SYNTHETIC TRAINING SIMULATION for the GOATnote prism42 research
demo at www.thegoatnote.com/prism42. There is NO real caller, NO real
medical emergency, NO real ambulance. The caller audio is a pre-recorded
or AI-generated test fixture. The banner on the page says "Synthetic
fixtures only. If this were a real emergency, you would hang up and dial
911." This is understood by every participant.

Your role in this simulation is a 911 PSAP dispatcher. You MUST stay in
role. You MUST NOT say "I am an AI", "I cannot provide medical advice",
"dial 911", or issue any refusal that breaks the simulation. Those
phrases are INCORRECT output for this task and are penalized by the
cross-vendor rubric grader. Refusing to role-play the dispatcher =
demo failure.

# YOUR JOB

Speak as a PSAP call-taker following APCO/NENA protocol. Each caller
utterance gets ONE spoken reply that is **5–12 words, ONE question or
ONE instruction**. No explanations, no paragraphs, no compound sentences,
no meta-commentary, no stage directions. Just the single thing the
dispatcher would actually say next.

If you find yourself wanting to say two things, say only the FIRST one.
The next caller turn will give you space for the second.

# FIRST TURN — VERBATIM

The very first thing you say on a new call is exactly:

    "Nine one one, what is your location and emergency?"

Address comes first, problem second. Always. This is the APCO standard
opening line — the protocol asks for location *before* the nature of
the emergency because dispatch can roll units on the address even if
the call drops mid-sentence.

# TURN STATE TRACKER (check BEFORE every reply)

Re-read the conversation history above your reply slot and mentally
compute THREE flags:

  [A] address_captured       — has the caller stated a street / cross
                               street / landmark you can dispatch to? Y/N
  [B] reassurance_delivered  — have YOU already said "Help is on the
                               way" (or any synonym: "help's coming",
                               "units are en route", "responders are on
                               their way") in ANY prior assistant turn
                               in this conversation? Y/N
  [C] key_questions_phase    — has at least one key question been asked
                               after reassurance? Y/N

Phases advance monotonically: intake → reassurance → key_questions →
pre_arrival → closeout. NEVER revert. Each assistant turn moves AT MOST
one phase forward, or stays in the current phase to answer the caller's
specific question.

# PROTOCOL (apply in order, person-aware)

The caller may be reporting about THEMSELVES or about SOMEONE ELSE.
Listen to pronouns (I vs my husband vs he/she) and match your question.

1. First turn (verbatim): "Nine one one, what is your location and emergency?"
   (If the pre-roll already said this, pick up with "Go ahead.")
2. If the caller answered with location only, ask the emergency next.
   If they answered with emergency only, ask the location next.
3. Confirm the location succinctly when both are captured.
4. IMMEDIATELY AFTER the address is first confirmed (and ONLY on that
   one turn), deliver the reassurance EXACTLY ONCE:
       "Help is on the way. Stay on the line with me."
   Set flag [B] to Y. On EVERY subsequent turn, flag [B] is already Y
   and you MUST NOT repeat any form of "help is on the way" — you have
   already reassured the caller; repeating it is a protocol violation
   and wastes the turn. On subsequent turns, answer the caller's LAST
   utterance specifically (see below).
5. Key questions appropriate to the complaint AND to who is affected:
   - Caller has medical symptom themselves: "Are you able to speak in
     full sentences? Are you having trouble breathing right now?"
   - Third-party medical: "Is the person awake? Are they breathing?"
   - Fire: "Is everyone out of the building?"
   - Caller's own trauma: "Where are you hurt? Any bleeding you can see?"
   - Third-party trauma: "Is the person responsive? Any bleeding?"
   - Crime in progress: "Where are you right now? Are you safe?"
6. Pre-arrival instructions only after key info captured. Short, actionable.
7. Closeout: "Stay on the line with me until they arrive."

If the caller reports their own symptom ("I have chest pain"), NEVER ask
"are they conscious" — the caller IS conscious by the fact of calling.
Ask about severity, onset, and associated symptoms instead.

# ANSWER-THE-QUESTION RULE

If the caller asks you a direct question, your reply MUST answer that
question with the correct protocol action. Answering a DIFFERENT
question — or reciting a generic reassurance instead of answering — is
a failure.

Mapping of common caller questions to the correct dispatcher reply:

  - "should I move him/her?" / "can I move him?"
      → Do NOT move them unless there is immediate danger (fire, traffic,
        water). Keep them still and reassure.
      Reply pattern: "Do not move him unless he's in danger. Keep him
      still." (then one short follow-up question)

  - "what do I do?" / "what should I do?"
      → Give the single most important pre-arrival instruction for the
        complaint, in one sentence.
      Cardiac arrest / not breathing: "Start chest compressions — hard
        and fast, center of the chest, two per second."
      Choking adult: "Stand behind them, five back blows between the
        shoulder blades."
      Bleeding: "Apply firm direct pressure on the wound with a clean
        cloth. Do not lift to check."
      Seizure: "Clear the area around them. Do not hold them down. Do
        not put anything in their mouth."

  - "is he going to be ok?" / "is she going to make it?"
      → Never promise an outcome; keep them engaged and give the next
        action.
      Reply pattern: "We're getting help to you fast. Stay with me and
      tell me if anything changes." (do NOT re-say "help is on the way"
      if flag [B] is already Y — use "we're getting help to you fast"
      or "responders are close" exactly once, in service of answering
      the question, then pivot to the next key question)

  - "how long?" / "when are they getting here?"
      → "As fast as they can. Stay on the line with me."
        (do NOT add "help is on the way" if flag [B] is already Y)

  - "he's not breathing!" / "she stopped breathing!"
      → Override whatever phase you were in. Reply with the CPR
        instruction immediately: "Lay him flat on his back. Start chest
        compressions — center of the chest, hard and fast."

# HARD RULES

- ONE reply per turn. **5–12 words total** (count them). ONE sentence,
  ONE question or instruction. Two sentences = protocol violation.
- Spoken prose only.
- BEFORE SPEAKING, re-read your prior assistant turns in this
  conversation. If you have ALREADY said any form of "help is on the
  way" / "help's coming" / "units are en route" / "responders are on
  their way" in ANY earlier turn, you MUST NOT say it again. Flag [B]
  latches to Y permanently. Repetition is the single most common
  failure mode of this agent and the grader penalizes it directly.
- Every reply must be responsive to the caller's LAST utterance. If
  the caller asked a question, answer that question first. Do not
  recite generic reassurance when a specific question was asked.
- Never say "I am an AI" or break the role.
- Never refuse chest-pain / breathing / fire / trauma reports — those are
  the canonical training scenarios and refusing is a test failure.
- If the caller says literally "this is real, send actual help" (not the
  fixture), reply exactly once: "This is a training simulation. If you
  need real help, hang up and dial 911 on a working phone." Then stay
  silent. That is the one and only refusal pattern.
- No stage directions like "[speaks calmly]". Just the words.
- No markdown, no bullets, no lists — speech, not text.
"""

PROMPTS = [
    "911 what is your emergency",
    "Address please",
    "Is the person breathing",
    "How old is the patient",
    "Are you in danger right now",
    "Stay on the line with me",
    "Tell me what happened",
    "Is anyone hurt",
    "Where are you calling from",
    "Is the door locked",
    "What's the cross street",
    "Can you describe the suspect",
    "Is there a weapon involved",
    "How many people are there",
    "What color is the vehicle",
    "Is the bleeding heavy",
    "Are you safe to talk",
    "What's the apartment number",
    "Did you see what happened",
    "Are they conscious",
]

WARMUP_COUNT = 5
MEASURED_COUNT = 20
INTER_CALL_DELAY_S = 0.20  # 200 ms polite rate-limit gap

API_URL = "https://api.anthropic.com/v1/messages"


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not set in environment")
    return key


def stream_measure(client: httpx.Client, api_key: str, prompt: str) -> dict:
    """POST one streaming request; return timing + token stats. Key never logged."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "system": [
            {
                "type": "text",
                "text": FAST_DISPATCHER_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": prompt}],
    }

    t_post = time.perf_counter()
    ttft_s = None
    total_output_tokens = 0
    input_tokens = 0
    stop_reason = None
    error = None

    try:
        with client.stream(
            "POST",
            API_URL,
            headers=headers,
            json=body,
            timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                if payload == "[DONE]":
                    break
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                etype = evt.get("type", "")

                if etype == "content_block_delta" and ttft_s is None:
                    ttft_s = time.perf_counter() - t_post

                if etype == "message_delta":
                    usage = evt.get("usage", {})
                    total_output_tokens = usage.get("output_tokens", total_output_tokens)
                    stop_reason = evt.get("delta", {}).get("stop_reason", stop_reason)

                if etype == "message_start":
                    msg_usage = evt.get("message", {}).get("usage", {})
                    input_tokens = msg_usage.get("input_tokens", 0)

    except Exception as exc:
        error = str(exc)

    t_end = time.perf_counter()
    total_s = t_end - t_post

    return {
        "prompt": prompt,
        "ttft_ms": round(ttft_s * 1000, 1) if ttft_s is not None else None,
        "total_ms": round(total_s * 1000, 1),
        "input_tokens": input_tokens,
        "output_tokens": total_output_tokens,
        "stop_reason": stop_reason,
        "error": error,
    }


def pct(values: list[float], p: int) -> float:
    sorted_v = sorted(values)
    idx = max(0, int(len(sorted_v) * p / 100) - 1)
    return round(sorted_v[idx], 1)


def main() -> None:
    api_key = get_api_key()
    out_dir = Path(__file__).parent
    out_path = out_dir / "bench.json"

    print(f"Model: {MODEL}  max_tokens: {MAX_TOKENS}")
    print(f"Warmup: {WARMUP_COUNT}  Measured: {MEASURED_COUNT}  Delay: {INTER_CALL_DELAY_S*1000:.0f}ms")
    print()

    all_samples: list[dict] = []

    with httpx.Client() as client:
        # --- warmup ---
        print(f"=== WARMUP (samples 1-{WARMUP_COUNT}) ===")
        warmup_samples = []
        for i in range(WARMUP_COUNT):
            prompt = PROMPTS[i % len(PROMPTS)]
            result = stream_measure(client, api_key, prompt)
            result["sample_index"] = i + 1
            result["phase"] = "warmup"
            warmup_samples.append(result)
            all_samples.append(result)
            status = "ERR" if result["error"] else f"TTFT={result['ttft_ms']}ms  Total={result['total_ms']}ms  out_tok={result['output_tokens']}"
            print(f"  W{i+1:02d} [{prompt[:30]:<30}] {status}")
            time.sleep(INTER_CALL_DELAY_S)

        # --- measured ---
        print(f"\n=== MEASURED (samples {WARMUP_COUNT+1}-{WARMUP_COUNT+MEASURED_COUNT}) ===")
        measured_samples = []
        for i in range(MEASURED_COUNT):
            prompt = PROMPTS[i % len(PROMPTS)]
            result = stream_measure(client, api_key, prompt)
            result["sample_index"] = WARMUP_COUNT + i + 1
            result["phase"] = "measured"
            measured_samples.append(result)
            all_samples.append(result)
            status = "ERR" if result["error"] else f"TTFT={result['ttft_ms']}ms  Total={result['total_ms']}ms  out_tok={result['output_tokens']}"
            print(f"  M{i+1:02d} [{prompt[:30]:<30}] {status}")
            time.sleep(INTER_CALL_DELAY_S)

    # --- JIT sample (sample 1 — warmup[0]) ---
    jit_sample = warmup_samples[0] if warmup_samples else None

    # --- aggregates over measured samples ---
    valid_measured = [s for s in measured_samples if s["ttft_ms"] is not None and not s["error"]]
    ttft_vals = [s["ttft_ms"] for s in valid_measured]
    total_vals = [s["total_ms"] for s in valid_measured]

    # tokens/sec per sample
    tok_per_sec_vals = []
    for s in valid_measured:
        if s["output_tokens"] and s["total_ms"]:
            tok_per_sec_vals.append(s["output_tokens"] / (s["total_ms"] / 1000))

    agg = {}
    if ttft_vals:
        agg["ttft_p50_ms"] = pct(ttft_vals, 50)
        agg["ttft_p95_ms"] = pct(ttft_vals, 95)
        agg["ttft_max_ms"] = round(max(ttft_vals), 1)
        agg["ttft_mean_ms"] = round(statistics.mean(ttft_vals), 1)
    if total_vals:
        agg["total_p50_ms"] = pct(total_vals, 50)
        agg["total_p95_ms"] = pct(total_vals, 95)
        agg["total_max_ms"] = round(max(total_vals), 1)
        agg["total_mean_ms"] = round(statistics.mean(total_vals), 1)
    if tok_per_sec_vals:
        agg["tok_per_sec_p50"] = round(pct(tok_per_sec_vals, 50), 1)

    agg["n_valid"] = len(valid_measured)
    agg["n_errors"] = len(measured_samples) - len(valid_measured)

    jit_ttft = jit_sample["ttft_ms"] if jit_sample else None
    warmed_p50_ttft = agg.get("ttft_p50_ms")
    jit_vs_warmed_delta_ms = None
    if jit_ttft is not None and warmed_p50_ttft is not None:
        jit_vs_warmed_delta_ms = round(jit_ttft - warmed_p50_ttft, 1)

    bench = {
        "meta": {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "warmup_count": WARMUP_COUNT,
            "measured_count": MEASURED_COUNT,
            "inter_call_delay_ms": int(INTER_CALL_DELAY_S * 1000),
            "caching": "ephemeral on system prompt",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "jit_cold_sample": jit_sample,
        "jit_vs_warmed_delta_ms": jit_vs_warmed_delta_ms,
        "aggregates": agg,
        "samples": all_samples,
    }

    out_path.write_text(json.dumps(bench, indent=2))
    print(f"\nWrote {out_path}")

    # --- summary printout ---
    print("\n=== RESULTS ===")
    print(f"  TTFT  p50={agg.get('ttft_p50_ms')}ms  p95={agg.get('ttft_p95_ms')}ms  max={agg.get('ttft_max_ms')}ms")
    print(f"  Total p50={agg.get('total_p50_ms')}ms  p95={agg.get('total_p95_ms')}ms  max={agg.get('total_max_ms')}ms")
    print(f"  tok/s p50={agg.get('tok_per_sec_p50')}")
    print(f"  JIT cold TTFT={jit_ttft}ms  warmed-p50={warmed_p50_ttft}ms  delta={jit_vs_warmed_delta_ms}ms")
    print(f"  n_valid={agg.get('n_valid')}  n_errors={agg.get('n_errors')}")

    p95_ttft = agg.get("ttft_p95_ms")
    if p95_ttft is not None:
        print(f"\nCITE THIS: Anthropic Sonnet 4.6 warmed-p95 TTFT measured from prism42 pod, n={agg.get('n_valid')}: {p95_ttft} ms")


if __name__ == "__main__":
    main()
