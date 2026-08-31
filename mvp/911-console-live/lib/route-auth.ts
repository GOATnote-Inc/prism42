// Fail-closed request gates for the prism42 API surface.
//
// Every server route that can spend LLM budget, mint a LiveKit token, or
// inject turns into a session MUST pass one of these gates. Polarity is
// fail-closed: a missing secret is a deployment misconfiguration and the
// route returns 503 — it never silently opens.
//
// Dev escape: gated behind BOTH `NODE_ENV !== "production"` AND an
// explicit `PRISM42_DEV_OPEN=1`. `next build` / every Vercel deployment
// (production AND preview) runs with NODE_ENV=production, so the escape
// is unreachable on any deployed path — it only works under `next dev`
// on a developer machine that opted in.

import crypto from "node:crypto";

export function devOpenEscape(): boolean {
  return (
    process.env.NODE_ENV !== "production" &&
    process.env.PRISM42_DEV_OPEN === "1"
  );
}

export type WorkerAuthResult =
  | { ok: true }
  | { ok: false; status: 401 | 503; reason: string };

/** Constant-time string comparison (hash first so lengths never leak). */
function timingSafeEqualString(a: string, b: string): boolean {
  const ha = crypto.createHash("sha256").update(a).digest();
  const hb = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

/**
 * Shared-secret session auth: the caller must present
 * `x-prism42-worker-key` matching PRISM42_WORKER_KEY.
 *
 * - PRISM42_WORKER_KEY unset  → 503 (fail closed; deployment bug)
 * - header missing / mismatch → 401
 * - dev escape (see above)    → open, with a console warning
 */
export function requireWorkerKey(provided: string | null): WorkerAuthResult {
  if (devOpenEscape()) {
    console.warn(
      "[prism42/auth] PRISM42_DEV_OPEN=1 under next dev — auth gate SKIPPED.",
    );
    return { ok: true };
  }
  const expected = process.env.PRISM42_WORKER_KEY;
  if (!expected) {
    return {
      ok: false,
      status: 503,
      reason:
        "auth_not_configured: PRISM42_WORKER_KEY is unset; this endpoint fails closed",
    };
  }
  if (!provided || !timingSafeEqualString(provided, expected)) {
    return { ok: false, status: 401, reason: "unauthorized" };
  }
  return { ok: true };
}

/** JSON error response for a failed WorkerAuthResult. */
export function workerAuthErrorResponse(
  result: Extract<WorkerAuthResult, { ok: false }>,
): Response {
  return new Response(JSON.stringify({ error: result.reason }), {
    status: result.status,
    headers: { "Content-Type": "application/json" },
  });
}
