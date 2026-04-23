// POST /api/rubric/grade-local — B300 local-rubric path. Same body shape as
// /api/rubric/grade so the client can swap paths without touching payload
// structure. When PRISM42_B300_RUBRIC_URL is unset or the endpoint is
// unreachable, returns 503 + hint so the client falls back to the hosted
// path. Single-variable A/B discipline per the approved Phase 2-min plan.

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { gradeTurnB300, B300GraderUnavailable } from "@/lib/rubric-local";
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
    const grade = await gradeTurnB300({
      turn: body.turn,
      callerText: body.caller_text,
      phase: body.phase,
      gedpSection: body.gedp_section,
    });
    recordGrade(body.session_id, grade);
    return NextResponse.json(grade);
  } catch (err) {
    if (err instanceof B300GraderUnavailable) {
      return NextResponse.json(
        {
          error: "b300_rubric_unavailable",
          reason: err.reason,
          fallback: "hosted",
          detail: err.message,
        },
        { status: 503 },
      );
    }
    throw err;
  }
}
