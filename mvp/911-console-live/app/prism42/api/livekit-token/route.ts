// POST /prism42/api/livekit-token — mint a short-lived JWT for the
// browser to join a LiveKit room.
//
// The room name IS the prism42 session_id. The Python agent worker
// on the B300 pod auto-dispatches into rooms whose names match the
// `livekit-agents` worker pattern; both browser + agent end up in
// the same room, audio flows over WebRTC, structured-turn events
// flow over LiveKit data channels.
//
// Auth is by-design open for the public demo (Turnstile lands in
// Phase 3c). The token has a 30-minute TTL and only grants subscribe
// + publish on a single named room — abuse blast radius is one room.

import { NextResponse } from "next/server";
import { AccessToken } from "livekit-server-sdk";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface MintRequest {
  session_id: string;
  identity?: string; // optional caller display name
}

export async function POST(req: Request): Promise<Response> {
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const livekitUrl = process.env.NEXT_PUBLIC_LIVEKIT_URL;

  if (!apiKey || !apiSecret || !livekitUrl) {
    return NextResponse.json(
      { error: "livekit_not_configured", missing: ["LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "NEXT_PUBLIC_LIVEKIT_URL"].filter((k) => !process.env[k]) },
      { status: 500 },
    );
  }

  let body: MintRequest;
  try {
    body = (await req.json()) as MintRequest;
  } catch {
    return NextResponse.json({ error: "bad_request" }, { status: 400 });
  }

  if (!body.session_id || !/^[a-zA-Z0-9_-]{6,64}$/.test(body.session_id)) {
    return NextResponse.json(
      { error: "invalid_session_id", note: "must be 6-64 chars [A-Za-z0-9_-]" },
      { status: 400 },
    );
  }

  const identity = body.identity ?? `caller-${body.session_id.slice(0, 8)}`;

  const at = new AccessToken(apiKey, apiSecret, {
    identity,
    ttl: "30m",
  });
  at.addGrant({
    room: body.session_id,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  });

  const token = await at.toJwt();

  return NextResponse.json({
    token,
    room: body.session_id,
    livekit_url: livekitUrl,
    identity,
    expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
  });
}
