// POST /api/session/:id/turn — turn ingest for the LiveKit voice path.
//
// The ElevenLabs path writes turns through `/api/chat/completions` →
// recordTurn(), but the LiveKit path's worker (running on the B300 pod)
// has no equivalent route into the dispatcher SSE bus. This endpoint
// closes that gap: the worker POSTs each turn (caller transcript or
// dispatcher reply) here, and the same `recordTurn` → publish chain
// fans the event out to subscribers of `/api/session/:id/stream`.
//
// Auth: FAIL CLOSED — requires the shared-secret header
// `x-prism42-worker-key` to match PRISM42_WORKER_KEY. If the env var
// is unset the endpoint returns 503 (deployment misconfiguration)
// rather than accepting unauthenticated turn injection. The only
// escape is `next dev` + PRISM42_DEV_OPEN=1 (lib/route-auth.ts).
//
// Body: minimal PsapTurn shape. The worker sends `{ role: "user" |
// "assistant", content: string, turn_id?: string }` and we fill the
// rest with sane defaults so the existing dispatcher UI renders.

import type { NextRequest } from "next/server";
import { requireWorkerKey, workerAuthErrorResponse } from "@/lib/route-auth";
import {
  attachToSession,
  recordTurn,
} from "@/lib/session-store";
import type { PsapTurn } from "@/lib/types";

export const runtime = "nodejs";

interface WorkerTurnPayload {
  role: "user" | "assistant";
  content: string;
  turn_id?: string;
  agent?: string;
  ts_ms?: number;
  // Optional extras the worker may send for richer rendering:
  rationale?: string;
  alerts?: PsapTurn["alerts"];
  next_phase?: PsapTurn["next_phase"];
  debug?: PsapTurn["debug"];
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = requireWorkerKey(req.headers.get("x-prism42-worker-key"));
  if (!auth.ok) {
    return workerAuthErrorResponse(auth);
  }
  const { id } = await ctx.params;
  let body: WorkerTurnPayload;
  try {
    body = (await req.json()) as WorkerTurnPayload;
  } catch {
    return new Response(JSON.stringify({ error: "bad_json" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (!body || (body.role !== "user" && body.role !== "assistant") || !body.content) {
    return new Response(
      JSON.stringify({ error: "bad_payload", required: ["role", "content"] }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }
  attachToSession(id);
  const tsMs = body.ts_ms ?? Date.now();
  const turn: PsapTurn = {
    agent: (body.agent as PsapTurn["agent"]) ??
      (body.role === "assistant" ? "psap-intake" : "psap-intake"),
    turn_id: body.turn_id ?? `livekit-${tsMs}`,
    action: body.role === "user" ? "listen" : "speak",
    content: body.content,
    rationale: body.rationale ?? "",
    cites: [],
    confidence: 1,
    confidence_basis: "default",
    self_verify: { checks: [], all_passed: true },
    next_phase: body.next_phase,
    alerts: body.alerts ?? [],
    debug: { ...(body.debug ?? {}), ts_ms: tsMs, source: "livekit" },
  };
  recordTurn(id, turn);
  return new Response(JSON.stringify({ ok: true, turn_id: turn.turn_id }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
