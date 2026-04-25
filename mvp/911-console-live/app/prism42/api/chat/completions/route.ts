// POST /api/chat/completions — OpenAI-compatible custom-LLM endpoint
// consumed by ElevenLabs Conversational AI. See
// docs/anthropic-elevenlabs-agent-bp-2026-04-21.md §3.1 for the contract.
//
// Pipeline for each inbound turn:
//   0. Verify ElevenLabs HMAC-SHA256 callback signature (DEFEND-20260424T1200).
//   1. Resolve session_id from the request body/user field (fallback:
//      create-on-first-use).
//   2. Build coordinator messages from the inbound OpenAI messages list
//      (drop the ElevenLabs system prompt — we use our own).
//   3. Call Anthropic with the coordinator system prompt. Accumulate
//      the full text (structured JSON expected).
//   4. Parse JSON → PsapTurn via Zod schema.
//   5. If self_verify.all_passed && action == "speak": stream the
//      content field back as OpenAI chunks. Otherwise stream the
//      safe-fallback string.
//   6. Record the turn in the session store (UI SSE fans it out).
//   7. Fire async rubric grading (non-blocking).
//
// This endpoint is intentionally NOT edge-runtime. The anthropic SDK
// and openai SDK are both Node-runtime-friendly; edge runtime costs
// a cold-start hit on the first turn of each call and doesn't win
// much when the per-turn budget is dominated by LLM inference.

import crypto from "node:crypto";
import type { NextRequest } from "next/server";
import {
  COORDINATOR_SYSTEM_PROMPT,
  REFUSAL_RESCUE_CONTENT,
  SAFE_FALLBACK_CONTENT,
  detectRefusalLeak,
  tryParseTurn,
} from "@/lib/coordinator";
import { coordinatorFallbackStream, getCoordinatorAgentId } from "@/lib/anthropic";
import { gradeTurnOpenAI, OpenAIGraderUnavailable } from "@/lib/openai";
import { createSession, getSession, recordGrade, recordTurn } from "@/lib/session-store";
import { createSseWriter, makeOpenAIChunk, sseHeaders } from "@/lib/sse";
import type { CustomLLMRequest, PsapTurn } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60; // seconds — Vercel Node cap.

// ---------------------------------------------------------------------------
// HMAC-SHA256 signature verification (DEFEND-20260424T1200)
// ---------------------------------------------------------------------------
// ElevenLabs Conversational AI sends an `elevenlabs-signature` header on
// every callback. Format:
//   elevenlabs-signature: t=<unix_timestamp>,v0=<hex_hmac_sha256>
//
// Signing input:  timestamp + "." + raw_request_body
// Secret:         ELEVENLABS_SIGNING_SECRET env var
// Stale window:   reject if |now - timestamp| > 300 seconds
//
// Dev escape hatch: if ELEVENLABS_SIGNING_SECRET is unset, OR if
// NEXT_PUBLIC_VERCEL_ENV === "preview" AND PRISM42_SKIP_HMAC_PREVIEW === "1",
// verification is skipped with a console warning. NEVER set either in prod.

const HMAC_STALE_SECONDS = 300;

type HmacVerifyResult =
  | { ok: true }
  | { ok: false; status: 401; reason: string };

function verifyElevenLabsSignature(
  rawBody: string,
  signatureHeader: string | null,
): HmacVerifyResult {
  const secret = process.env.ELEVENLABS_SIGNING_SECRET;

  // Dev escape: no secret configured.
  if (!secret) {
    console.warn(
      "[prism42/hmac] ELEVENLABS_SIGNING_SECRET is not set — " +
        "HMAC verification SKIPPED. Set this env var on Vercel before going live.",
    );
    return { ok: true };
  }

  // Preview escape: explicit opt-out for CI preview deployments.
  if (
    process.env.NEXT_PUBLIC_VERCEL_ENV === "preview" &&
    process.env.PRISM42_SKIP_HMAC_PREVIEW === "1"
  ) {
    console.warn(
      "[prism42/hmac] PRISM42_SKIP_HMAC_PREVIEW=1 on a preview env — " +
        "HMAC verification SKIPPED.",
    );
    return { ok: true };
  }

  // Header must be present.
  if (!signatureHeader) {
    return { ok: false, status: 401, reason: "missing signature header" };
  }

  // Parse t=... and v0=... from the comma-separated header.
  let timestamp: string | undefined;
  let receivedSig: string | undefined;
  for (const part of signatureHeader.split(",")) {
    const [key, val] = part.trim().split("=", 2);
    if (key === "t") timestamp = val;
    if (key === "v0") receivedSig = val;
  }

  if (!timestamp || !receivedSig) {
    return { ok: false, status: 401, reason: "invalid signature" };
  }

  // Staleness check.
  const ts = parseInt(timestamp, 10);
  if (!Number.isFinite(ts) || Math.abs(Date.now() / 1000 - ts) > HMAC_STALE_SECONDS) {
    return { ok: false, status: 401, reason: "invalid signature" };
  }

  // Compute expected HMAC.
  const signingInput = `${timestamp}.${rawBody}`;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(signingInput)
    .digest("hex");

  // Timing-safe comparison.
  let match: boolean;
  try {
    match = crypto.timingSafeEqual(
      Buffer.from(expected, "hex"),
      Buffer.from(receivedSig, "hex"),
    );
  } catch {
    // Buffers of different lengths throw — treat as mismatch.
    match = false;
  }

  if (!match) {
    return { ok: false, status: 401, reason: "invalid signature" };
  }

  return { ok: true };
}

// ---------------------------------------------------------------------------

// Matches the session_id substring ElevenLabs templates into the
// system prompt via the widget's `dynamic-variables` attribute. The
// agent's dashboard-configured system prompt must include the line
// `Session-ID: {{session_id}}` for this to fire. See
// components/CallerWidget.tsx for the client-side contract.
const SESSION_ID_FROM_SYSTEM = /Session-ID:\s*([0-9a-f]{4,}(?:-[0-9a-f]{4,})+)/i;

function resolveSessionId(body: CustomLLMRequest): string {
  // 1. Prefer an explicit body.user field — ElevenLabs populates
  //    this with the conversation id on some plan tiers. Also
  //    works for hand-curled smoke tests.
  if (body.user) return body.user;
  // 2. Parse out the templated Session-ID from the system prompt —
  //    the primary production path when the widget is mounted with
  //    `dynamic-variables='{"session_id":"..."}'`.
  const sys = body.messages.find((m) => m.role === "system");
  if (sys?.content) {
    const m = SESSION_ID_FROM_SYSTEM.exec(sys.content);
    if (m?.[1]) return m[1];
  }
  // 3. Fallback: mint a fresh session. The dispatcher UI won't see
  //    this session (it subscribes by id), so the turn stream will
  //    be orphaned. Acceptable for isolated curl tests; a missing
  //    Session-ID in production is a configuration bug to surface.
  return createSession().id;
}

export async function POST(req: NextRequest) {
  // Read raw body text first — HMAC signing input is the raw bytes before JSON
  // parsing. Calling req.text() here consumes the body; we JSON.parse manually
  // below rather than using req.json().
  const rawBody = await req.text();

  const sigResult = verifyElevenLabsSignature(
    rawBody,
    req.headers.get("elevenlabs-signature"),
  );
  if (!sigResult.ok) {
    return new Response(JSON.stringify({ error: "invalid signature" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const body = JSON.parse(rawBody) as CustomLLMRequest;
  const sessionId = resolveSessionId(body);
  const session = getSession(sessionId) ?? createSession();
  const resolvedSessionId = session.id;

  // Find the last user message — that's the caller's current utterance.
  const lastUser = [...body.messages].reverse().find((m) => m.role === "user");
  const callerText = lastUser?.content ?? "";

  // Prepare coordinator-shape messages: drop any inbound system prompt
  // (we enforce our own), keep the user/assistant history so the
  // coordinator has context, cap at last 20 turns for token hygiene.
  const history = body.messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .slice(-20)
    .map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content,
    }));

  const chunkId = `chatcmpl-${Date.now().toString(36)}`;
  const sse = createSseWriter();
  const model = body.model ?? "prism42-coordinator";

  // Kick off the Anthropic call in the background. When it resolves
  // we stream the validated `content` field — or the safe fallback —
  // as a single chunk then send [DONE].
  (async () => {
    try {
      let fullText = "";

      const agentId = getCoordinatorAgentId();
      if (agentId) {
        // Managed Agents path — Phase 2b wires
        // client.beta.agents.sessions.* here and uses the durable
        // session id from session-store. For now we fall through to
        // the direct messages.stream path; functionally equivalent
        // for a single-threaded demo.
      }

      const res = await coordinatorFallbackStream({
        systemPrompt: COORDINATOR_SYSTEM_PROMPT,
        messages: history,
        // 600 chosen 2026-04-24: typical coordinator turn JSON is 80-300
        // tokens; 600 leaves headroom without letting Opus 4.7 ramble past
        // the TTS streaming budget. Every 100 tokens ~= 100-200ms of TTS
        // latency on ElevenLabs, so tighter cap → faster perceived reply.
        maxTokens: 600,
      });
      fullText = res.fullText;

      const parse = tryParseTurn(fullText);
      let spokenText: string;
      if (parse.turn) {
        // Full Zod success — use the validated turn.
        const annotated: PsapTurn = {
          ...parse.turn,
          debug: {
            ...(parse.turn.debug ?? {}),
            ts_ms: Date.now(),
            session_id: resolvedSessionId,
          },
        };
        recordTurn(resolvedSessionId, annotated);
        fireAsyncRubricGrade(resolvedSessionId, annotated, callerText);
        spokenText = decideSpokenContent(parse.turn, callerText);
      } else if (parse.lenient_content && parse.raw_ok) {
        // JSON parsed but Zod rejected — lenient serve. The caller
        // hears the model's content; the dispatcher UI sees a
        // verify-failed alert so the validation miss is surfaced but
        // not fatal. Production voice latency > schema strictness.
        //
        // SECURITY (fix/glasswing-lenient-serve, DEFEND-20260424T1245):
        // lenient_content is unvalidated — prompt injection can plant
        // medically harmful instructions (anti-911, medication mis-advice)
        // that reach TTS on this path because Zod never ran on the content
        // field. Apply detectRefusalLeak() (now including the medical-harm
        // block list) BEFORE assigning spokenText. On match, fall through
        // to SAFE_FALLBACK_CONTENT and record a high-severity alert.
        if (detectRefusalLeak(parse.lenient_content)) {
          spokenText = SAFE_FALLBACK_CONTENT;
          recordTurn(resolvedSessionId, {
            agent: "psap-team-coordinator",
            turn_id: `t-${resolvedSessionId.slice(0, 6)}-${session.turns.length}`,
            action: "defer",
            content: SAFE_FALLBACK_CONTENT,
            rationale:
              "Lenient-serve path: content blocked by detectRefusalLeak — " +
              "potential prompt-injection carrying harmful or anti-911 instruction. " +
              "Safe fallback spoken; original content preserved in debug for audit.",
            cites: ["sp:SP-001", "sp:SP-006"],
            confidence: 0.0,
            confidence_basis: "blocked",
            self_verify: {
              checks: [
                { name: "json-parseable", passed: true },
                {
                  name: "zod-schema-valid",
                  passed: false,
                  note: parse.zod_error ?? "unknown",
                },
                {
                  name: "refusal-leak-check",
                  passed: false,
                  note: "harmful substring matched on lenient_content",
                },
              ],
              all_passed: false,
            },
            alerts: [
              {
                kind: "injection-blocked",
                severity: "high",
                detail: `lenient-serve injection blocked: ${parse.lenient_content.slice(0, 120)}`,
                source_agent: "psap-team-coordinator",
              },
            ],
            debug: {
              ts_ms: Date.now(),
              raw_head: fullText.slice(0, 240),
              zod_error: parse.zod_error,
              blocked_content: parse.lenient_content.slice(0, 240),
            },
          });
        } else {
          // Lenient content passed the harm check — serve it with a
          // medium-severity verify-failed alert for dispatcher review.
          spokenText = parse.lenient_content;
          recordTurn(resolvedSessionId, {
            agent: "psap-team-coordinator",
            turn_id: `t-${resolvedSessionId.slice(0, 6)}-${session.turns.length}`,
            action: "speak",
            content: parse.lenient_content,
            rationale:
              "Lenient serve — coordinator JSON parsed but failed Zod schema. " +
              "Caller heard the content field; full turn failed strict validation.",
            cites: ["sp:SP-006"],
            confidence: 0.5,
            confidence_basis: "uncertain",
            self_verify: {
              checks: [
                { name: "json-parseable", passed: true },
                {
                  name: "zod-schema-valid",
                  passed: false,
                  note: parse.zod_error ?? "unknown",
                },
              ],
              all_passed: false,
            },
            alerts: [
              {
                kind: "verify-failed",
                severity: "medium",
                detail: `lenient-served: ${parse.zod_error ?? "zod rejected"}`,
                source_agent: "psap-team-coordinator",
              },
            ],
            debug: {
              ts_ms: Date.now(),
              raw_head: fullText.slice(0, 240),
              zod_error: parse.zod_error,
            },
          });
        }
      } else {
        // Malformed JSON — safe fallback, no content to serve.
        spokenText = SAFE_FALLBACK_CONTENT;
        recordTurn(resolvedSessionId, {
          agent: "psap-team-coordinator",
          turn_id: `t-${resolvedSessionId.slice(0, 6)}-${session.turns.length}`,
          action: "defer",
          content: null,
          rationale: "coordinator emitted malformed JSON; safe fallback served.",
          cites: ["sp:SP-006"],
          confidence: 0.0,
          confidence_basis: "uncertain",
          self_verify: {
            checks: [{ name: "json-parseable", passed: false }],
            all_passed: false,
          },
          alerts: [
            {
              kind: "verify-failed",
              severity: "medium",
              detail: "coordinator JSON failed to parse",
              source_agent: "psap-team-coordinator",
            },
          ],
          debug: { raw_head: fullText.slice(0, 240), ts_ms: Date.now() },
        });
      }

      // Last-line-of-defense: if Claude leaked a refusal phrase through
      // the simulation framing, swap for a neutral dispatcher opener
      // before TTS. This catches Sonnet 4.6's occasional "I am an AI,
      // I cannot provide..." leak even when JSON validation passes.
      // Record an alert so the dispatcher UI surfaces the rescue.
      if (detectRefusalLeak(spokenText)) {
        const leaked = spokenText;
        spokenText = REFUSAL_RESCUE_CONTENT;
        try {
          const { recordAlert } = await import("@/lib/session-store");
          recordAlert(resolvedSessionId, {
            kind: "verify-failed",
            severity: "high",
            detail: `refusal-leak rescued; coordinator emitted: ${leaked.slice(0, 160)}`,
            source_agent: "psap-team-coordinator",
          });
        } catch {
          /* session already reaped */
        }
      }

      sse.writeJson(makeOpenAIChunk({ id: chunkId, model, content: spokenText }));
      sse.writeJson(
        makeOpenAIChunk({ id: chunkId, model, finishReason: "stop" }),
      );
      sse.writeDone();
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "coordinator call failed";
      // Stream the safe fallback so the caller hears SOMETHING, even
      // when the upstream model errored. Then record a verify-failed
      // alert so the dispatcher sees why.
      sse.writeJson(
        makeOpenAIChunk({
          id: chunkId,
          model,
          content: SAFE_FALLBACK_CONTENT,
        }),
      );
      sse.writeJson(
        makeOpenAIChunk({ id: chunkId, model, finishReason: "stop" }),
      );
      sse.writeDone();
      recordTurn(resolvedSessionId, {
        agent: "psap-team-coordinator",
        turn_id: `t-${resolvedSessionId.slice(0, 6)}-err-${Date.now().toString(36)}`,
        action: "defer",
        content: null,
        rationale: `coordinator upstream error: ${msg.slice(0, 120)}`,
        cites: ["sp:SP-006"],
        confidence: 0,
        confidence_basis: "uncertain",
        self_verify: {
          checks: [{ name: "coordinator-call-succeeded", passed: false }],
          all_passed: false,
        },
        alerts: [
          {
            kind: "verify-failed",
            severity: "high",
            detail: msg.slice(0, 200),
            source_agent: "psap-team-coordinator",
          },
        ],
        debug: { ts_ms: Date.now() },
      });
    } finally {
      sse.close();
    }
  })();

  return new Response(sse.readable, { headers: sseHeaders() });
}

// Fire-and-forget per-turn rubric grade. Landed here rather than as a
// client-triggered call so the dispatcher UI doesn't have to know the
// cross-vendor grader exists. If the OpenAI chain exhausts, a
// verify-failed alert is published on the session stream so the
// dispatcher sees that rubric data is unavailable this turn — Phase
// 2b invokes the psap-rubric-live-shim (Opus 4.7) here instead of
// recording the failure.
function fireAsyncRubricGrade(
  sessionId: string,
  turn: PsapTurn,
  callerText: string,
): void {
  // Skip grading turns that didn't produce caller-facing content —
  // defer / escalate / handoff turns aren't gradeable against the
  // R4 clarity-for-caller criterion.
  if (turn.action !== "speak" || !turn.content) return;
  void (async () => {
    try {
      const grade = await gradeTurnOpenAI({
        turn,
        callerText,
        phase: turn.next_phase?.name ?? "unknown",
        gedpSection: turn.cites.find((c) => c.startsWith("kb:")),
      });
      recordGrade(sessionId, grade);
    } catch (err) {
      const kind =
        err instanceof OpenAIGraderUnavailable
          ? "openai_grader_unavailable"
          : "rubric_error";
      // Publish a verify-failed alert so the UI sees the grader drop.
      // Guard the publish itself — if the session was already reaped
      // we swallow to avoid an unhandled rejection.
      try {
        const { recordAlert } = await import("@/lib/session-store");
        recordAlert(sessionId, {
          kind: "verify-failed",
          severity: "medium",
          detail: `rubric grader unavailable (${kind}); turn ${turn.turn_id} ungraded`,
          source_agent: "psap-rubric-live",
        });
      } catch {
        /* session gone — nothing to do */
      }
    }
  })();
}

function decideSpokenContent(
  turn: PsapTurn | null,
  _callerText: string,
): string {
  if (!turn) return SAFE_FALLBACK_CONTENT;
  if (turn.action === "speak") {
    if (!turn.self_verify.all_passed) return SAFE_FALLBACK_CONTENT;
    if (!turn.content) return SAFE_FALLBACK_CONTENT;
    return turn.content;
  }
  if (turn.action === "refuse" && turn.refuse) {
    return turn.content ?? turn.refuse.next_step_for_caller;
  }
  if (turn.action === "handoff" || turn.action === "end") {
    return turn.content ?? SAFE_FALLBACK_CONTENT;
  }
  return SAFE_FALLBACK_CONTENT;
}
