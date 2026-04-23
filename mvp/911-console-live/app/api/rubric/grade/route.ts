// POST /api/rubric/grade — grade a single PSAP turn. Cross-vendor
// independent from the voice-facing Opus 4.7 agents per
// agents/psap-rubric-live.yaml (GPT-5.5 primary / GPT-5.4 fallback).
// If both OpenAI models fail, we would invoke the Opus 4.7 shim
// (psap-rubric-live-shim) — Phase 2b wires that fallback; for Phase
// 2a we surface the failure to the caller.

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { gradeTurnOpenAI, OpenAIGraderUnavailable } from "@/lib/openai";
import { recordGrade } from "@/lib/session-store";
import type { PsapTurn } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 30;

interface GradeRequestBody {
  session_id: string;
  turn: PsapTurn;
  caller_text: string;
  phase: string;
  gedp_section?: string;
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as GradeRequestBody;
  if (!body.session_id || !body.turn) {
    return NextResponse.json(
      { error: "missing_session_id_or_turn" },
      { status: 400 },
    );
  }
  try {
    const grade = await gradeTurnOpenAI({
      turn: body.turn,
      callerText: body.caller_text,
      phase: body.phase,
      gedpSection: body.gedp_section,
    });
    recordGrade(body.session_id, grade);
    return NextResponse.json(grade);
  } catch (err) {
    if (err instanceof OpenAIGraderUnavailable) {
      // Phase 2b: invoke the Opus 4.7 shim here via Managed Agents,
      // raise self_grade_flag, return the grade with the asterisk.
      return NextResponse.json(
        {
          error: "openai_grader_unavailable",
          next_step: "invoke_opus_shim",
          detail: err.message,
        },
        { status: 503 },
      );
    }
    throw err;
  }
}
