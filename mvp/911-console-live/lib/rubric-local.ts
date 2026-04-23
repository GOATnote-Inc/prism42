// B300 local-rubric grader — calls a vLLM-served Llama-3-70B NVFP4
// endpoint with the IDENTICAL prompt the hosted GPT-5.5 grader uses.
// Single-variable A/B discipline per the approved Phase 2-min plan:
// only the serving backend differs.
//
// Route: POST to the vLLM /v1/chat/completions (OpenAI-compatible) endpoint
// configured via PRISM42_B300_RUBRIC_URL env var. 1500 ms timeout; on miss,
// error, or malformed JSON, this function throws B300GraderUnavailable so
// the route handler can 503 and the client can fall back to the hosted path.

import { RUBRIC_SYSTEM_PROMPT, weightedScore } from "./openai";
import type { PsapTurn, RubricGrade } from "./types";

const B300_RUBRIC_TIMEOUT_MS = 1500;
const B300_RUBRIC_MODEL = "local_llama70b_nvfp4";

export class B300GraderUnavailable extends Error {
  readonly kind = "b300_grader_unavailable" as const;
  readonly reason: "no_url" | "timeout" | "http_error" | "parse_error";
  constructor(
    reason: B300GraderUnavailable["reason"],
    message: string,
  ) {
    super(message);
    this.reason = reason;
  }
}

export interface B300GradeArgs {
  turn: PsapTurn;
  callerText: string;
  phase: string;
  gedpSection?: string;
}

interface ChatCompletionChoice {
  message?: { content?: string };
}
interface ChatCompletionResponse {
  choices?: ChatCompletionChoice[];
}

export async function gradeTurnB300(args: B300GradeArgs): Promise<RubricGrade> {
  const url = process.env.PRISM42_B300_RUBRIC_URL;
  if (!url) {
    throw new B300GraderUnavailable(
      "no_url",
      "PRISM42_B300_RUBRIC_URL env var not set",
    );
  }

  const start = Date.now();
  const userMsg = JSON.stringify({
    agent_turn: args.turn,
    caller_text: args.callerText,
    session_phase: args.phase,
    gedp_section: args.gedpSection,
  });

  const body = {
    model: B300_RUBRIC_MODEL,
    messages: [
      { role: "system", content: RUBRIC_SYSTEM_PROMPT },
      { role: "user", content: userMsg },
    ],
    response_format: { type: "json_object" as const },
    max_tokens: 600,
    temperature: 0,
  };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), B300_RUBRIC_TIMEOUT_MS);

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.PRISM42_B300_RUBRIC_TOKEN ?? "unset"}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    throw new B300GraderUnavailable(
      controller.signal.aborted ? "timeout" : "http_error",
      `fetch failed: ${String(err)}`,
    );
  }
  clearTimeout(timer);

  if (!resp.ok) {
    throw new B300GraderUnavailable(
      "http_error",
      `vLLM endpoint returned ${resp.status}`,
    );
  }

  let parsed: {
    criteria: RubricGrade["criteria"];
    rationales: Record<string, string>;
    cites?: string[];
  };
  try {
    const completion = (await resp.json()) as ChatCompletionResponse;
    const raw = completion.choices?.[0]?.message?.content ?? "{}";
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new B300GraderUnavailable(
      "parse_error",
      `could not parse vLLM output: ${String(err)}`,
    );
  }

  // Validate all five criteria are present; missing = drift.
  const requiredKeys = [
    "R1_clinical_accuracy",
    "R2_scope_adherence",
    "R3_safety_preservation",
    "R4_clarity_for_caller",
    "R5_protocol_adherence",
  ] as const;
  for (const k of requiredKeys) {
    if (typeof parsed.criteria?.[k] !== "number") {
      throw new B300GraderUnavailable(
        "parse_error",
        `missing or non-numeric criterion ${k}`,
      );
    }
  }

  return {
    turn_id: args.turn.turn_id,
    criteria: parsed.criteria,
    rationales: parsed.rationales ?? {},
    cites: parsed.cites ?? [],
    weighted_score: weightedScore(parsed.criteria),
    model_used: B300_RUBRIC_MODEL,
    self_grade_flag: false,
    latency_ms: Date.now() - start,
  };
}
