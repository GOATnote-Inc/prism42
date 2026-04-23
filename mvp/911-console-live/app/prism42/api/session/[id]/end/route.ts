// POST /api/session/:id/end — close a session (manually from the
// dispatcher UI, OR automatically from /api/chat/completions when
// action == "end" is emitted).
//
// In Phase 2a this just flips the session phase to "closed" and
// publishes a session_closed event. Phase 2b invokes psap-auditor +
// psap-qi-reviewer asynchronously to produce the post-session verdict.

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { closeSession, getSession } from "@/lib/session-store";

export const runtime = "nodejs";

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const session = getSession(id);
  if (!session) {
    return NextResponse.json(
      { error: "session_not_found", session_id: id },
      { status: 404 },
    );
  }
  const body = (await req.json().catch(() => ({}))) as { reason?: string };
  closeSession(id, body.reason ?? "caller_disconnect");
  return NextResponse.json({ ok: true, session_id: id });
}
