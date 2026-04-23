// POST /api/session/start — create a new PSAP session and return the id.
//
// The dispatcher UI calls this when the operator opens /prism42. The id
// is subsequently passed to ElevenLabs as a metadata field (they
// forward it through `user` on custom-LLM calls) so our
// /api/chat/completions endpoint can route each turn to the right
// session record.
//
// No auth on this endpoint by design — the public demo at
// www.thegoatnote.com/prism42 is intentionally open. Rate limiting
// lives in Vercel middleware (Phase 2b: Upstash Redis + Turnstile).

import { NextResponse } from "next/server";
import { createSession, ensureHeartbeat } from "@/lib/session-store";

export const runtime = "nodejs";

export async function POST() {
  ensureHeartbeat();
  const rec = createSession();
  return NextResponse.json({
    session_id: rec.id,
    created_at: rec.created_at,
    phase: rec.phase,
  });
}

export async function GET() {
  // Convenience for hand-testing: same behavior.
  return POST();
}
