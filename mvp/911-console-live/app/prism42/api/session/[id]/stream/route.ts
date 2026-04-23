// GET /api/session/:id/stream — SSE stream of structured PSAP events
// for the dispatcher UI. One stream per open console. Events:
//   - "turn"            structured PsapTurn (per schemas/psap-turn.schema.json)
//   - "grade"           RubricGrade
//   - "alert"           PsapAlert
//   - "phase_change"    new PsapPhase
//   - "session_closed"  {reason}
//   - "heartbeat"       null (keeps proxies alive)

import type { NextRequest } from "next/server";
import {
  ensureHeartbeat,
  getSession,
  subscribe,
} from "@/lib/session-store";
import { createSseWriter, sseHeaders, writeSessionEvent } from "@/lib/sse";

export const runtime = "nodejs";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const session = getSession(id);
  if (!session) {
    return new Response(
      JSON.stringify({ error: "session_not_found", session_id: id }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );
  }

  ensureHeartbeat();
  const sse = createSseWriter();

  // Replay historical turns/grades/alerts so a late-connecting UI sees
  // what already happened. Keeps dispatcher view coherent across
  // reloads / tab switches during a live call.
  sse.writeComment(`subscribed session=${id}`);
  for (const turn of session.turns) {
    writeSessionEvent(sse, { kind: "turn", at: turn.debug?.ts_ms as number ?? Date.now(), payload: turn });
  }
  for (const grade of session.grades) {
    writeSessionEvent(sse, { kind: "grade", at: Date.now(), payload: grade });
  }
  for (const alert of session.alerts) {
    writeSessionEvent(sse, { kind: "alert", at: Date.now(), payload: alert });
  }

  const unsub = subscribe(id, (evt) => writeSessionEvent(sse, evt));

  // Client disconnect → stop forwarding.
  req.signal.addEventListener("abort", () => {
    unsub();
    sse.close();
  });
  sse.closed.then(unsub);

  return new Response(sse.readable, { headers: sseHeaders() });
}
