// POST /api/chat/completions — OpenAI-compatible custom-LLM endpoint
// consumed by ElevenLabs Conversational AI. See
// docs/anthropic-elevenlabs-agent-bp-2026-04-21.md §3.1 for the contract.
//
// Pipeline for each inbound turn:
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

import type { NextRequest } from "next/server";
import {
  COORDINATOR_SYSTEM_PROMPT,
  SAFE_FALLBACK_CONTENT,
  tryParseTurn,
} from "@/lib/coordinator";
import { coordinatorFallbackStream, getCoordinatorAgentId } from "@/lib/anthropic";
import { gradeTurnOpenAI, OpenAIGraderUnavailable } from "@/lib/openai";
import { createSession, getSession, recordGrade, recordTurn } from "@/lib/session-store";
import { createSseWriter, makeOpenAIChunk, sseHeaders } from "@/lib/sse";
import type { CustomLLMRequest, PsapTurn } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60; // seconds — Vercel Node cap.

function resolveSessionId(body: CustomLLMRequest): string {
  // ElevenLabs passes the conversation id in the `user` field; the
  // dispatcher UI also sets it there via an X-Session-ID hint (see
  // app/prism42/page.tsx). Fall back to create-on-first-use so
  // handcurl'd test requests still work.
  if (body.user) return body.user;
  return createSession().id;
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as CustomLLMRequest;
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
        maxTokens: 1500,
      });
      fullText = res.fullText;

      const turn = tryParseTurn(fullText);
      const spokenText = decideSpokenContent(turn, callerText);
      if (turn) {
        const annotated: PsapTurn = {
          ...turn,
          debug: { ...(turn.debug ?? {}), ts_ms: Date.now(), session_id: resolvedSessionId },
        };
        recordTurn(resolvedSessionId, annotated);
        // Fire async rubric grade — do NOT await. The grader runs on
        // a different vendor (GPT-5.5) for cross-grader independence;
        // its latency must never block the ElevenLabs response stream.
        fireAsyncRubricGrade(resolvedSessionId, annotated, callerText);
      } else {
        // Malformed JSON — record a synthetic defer turn so the UI
        // shows what happened. Don't block the caller.
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
              detail: "coordinator JSON failed schema parse",
              source_agent: "psap-team-coordinator",
            },
          ],
          debug: { raw_head: fullText.slice(0, 200), ts_ms: Date.now() },
        });
      }

      // Stream the spoken text as a single chunk. Phase 2b: chunk by
      // word to smooth TTS pacing + insert the buffer-word "... "
      // if coordinator latency exceeds 400 ms between words.
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
