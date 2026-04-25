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
  attachToSession,
  ensureHeartbeat,
  subscribe,
} from "@/lib/session-store";
import { createSseWriter, sseHeaders, writeSessionEvent } from "@/lib/sse";

export const runtime = "nodejs";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  // attachToSession (vs getSession) absorbs the Vercel-cold-start
  // / LiveKit-room-mints-id-elsewhere case: if the SSE call lands on
  // a serverless instance that doesn't yet have the session in its
  // in-memory map, we materialize an empty record and start
  // subscribing. The worker's /turn POST will populate it.
  const session = attachToSession(id);

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
