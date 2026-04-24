"use client";

// /prism42-v2 — demo-safe plan-C path.
//
// What this is: ElevenLabs Conversational AI hosting a
// "prism42-v2-dispatcher" agent that uses ElevenLabs' native Claude
// integration (claude-sonnet-4-6). Zero custom LLM hop — Claude is
// invoked inside ElevenLabs, emits natural speech directly to TTS,
// with the coordinator system prompt baked into the agent's platform
// config.
//
// Plan A (/prism42): ElevenLabs → our /chat/completions → Anthropic.
// Plan B (/prism42/livekit): LiveKit + B300 self-hosted.
// Plan C (/prism42-v2): THIS. ElevenLabs agent with native Claude.
//
// Thin page by design — we only own the connect button + transcript
// list. ElevenLabs owns voice I/O and the LLM round-trip end to end.

import { useCallback, useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";

type TranscriptTurn = {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: number;
};

function V2Inner() {
  const agentId = process.env.NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID;

  const [phase, setPhase] = useState<
    "idle" | "connecting" | "live" | "ending" | "ended" | "error"
  >("idle");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const turnSeq = useRef(0);

  function appendTurn(role: "user" | "agent", text: string) {
    turnSeq.current += 1;
    const id = `t-${turnSeq.current}-${Date.now().toString(36)}`;
    setTurns((ts) => [...ts, { id, role, text, ts: Date.now() }]);
  }

  const conversation = useConversation({
    onConnect: () => setPhase("live"),
    onDisconnect: () => setPhase("ended"),
    onError: (err: unknown) => {
      const msg =
        typeof err === "string"
          ? err
          : err instanceof Error
            ? err.message
            : "unknown error";
      setErrorText(msg);
      setPhase("error");
    },
    // onMessage fires for both user transcripts and agent responses.
    // Shape per @elevenlabs/client BaseConversation:
    //   { source: "user" | "ai", role: "user" | "agent",
    //     message: string, event_id: number }
    onMessage: (evt: unknown) => {
      const e = evt as
        | { source?: string; role?: string; message?: string }
        | null
        | undefined;
      if (!e || typeof e.message !== "string" || !e.message) return;
      const role: "user" | "agent" =
        e.role === "user" || e.source === "user" ? "user" : "agent";
      appendTurn(role, e.message);
    },
  });

  const status = conversation?.status ?? "disconnected";
  const live = status === "connected" || phase === "live";

  // Pre-request mic permission on mount so the first click isn't stuck
  // behind a browser permission modal mid-call. Same pattern as
  // /prism42's CallerExperience.
  const permRequestedRef = useRef(false);
  useEffect(() => {
    if (permRequestedRef.current) return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices) return;
    permRequestedRef.current = true;
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach((t) => t.stop());
      })
      .catch(() => {
        // user can grant on first click
      });
  }, []);

  const startCall = useCallback(async () => {
    if (!agentId) {
      setErrorText(
        "NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID is not set in the deploy environment",
      );
      setPhase("error");
      return;
    }
    setErrorText(null);
    setPhase("connecting");
    setTurns([]);
    try {
      await conversation.startSession({
        agentId,
      } as Parameters<typeof conversation.startSession>[0]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorText(msg);
      setPhase("error");
    }
  }, [agentId, conversation]);

  const endCall = useCallback(async () => {
    setPhase("ending");
    try {
      await conversation.endSession();
    } catch {
      // onDisconnect fires either way
    }
  }, [conversation]);

  const buttonLabel =
    phase === "connecting"
      ? "Connecting…"
      : phase === "live"
        ? "End the call"
        : phase === "ending"
          ? "Ending…"
          : phase === "ended"
            ? "Speak to the dispatcher"
            : "Speak to the dispatcher";

  const chipLabel =
    phase === "error"
      ? "error"
      : phase === "connecting"
        ? "connecting"
        : live
          ? "live"
          : phase === "ending"
            ? "ending"
            : phase === "ended"
              ? "ended"
              : "idle";

  return (
    <main className="v2-shell">
      <header className="v2-header">
        <div>
          <h1>Prism42 v2 · Native Claude voice</h1>
          <p className="v2-subtitle">
            ElevenLabs Conversational AI · native Claude integration ·
            no custom LLM hop. Synthetic-fixture demonstration — if
            this were a real emergency, hang up and dial 911 on a
            working phone.
          </p>
        </div>
        <span
          className={`v2-chip v2-chip-${chipLabel}`}
          aria-label={`connection state: ${chipLabel}`}
        >
          {chipLabel}
        </span>
      </header>

      <section className="v2-controls">
        <button
          type="button"
          className={`v2-button ${live ? "v2-button-live" : ""}`}
          onClick={live ? endCall : startCall}
          disabled={phase === "connecting" || phase === "ending" || !agentId}
        >
          {buttonLabel}
        </button>
        <div className="v2-hint">
          {!agentId && (
            <span className="v2-bad">
              Voice agent not configured yet (missing
              NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID)
            </span>
          )}
          {agentId && phase === "idle" && (
            <span>
              Click to connect. Microphone permission will be requested
              if it hasn&apos;t been already.
            </span>
          )}
          {phase === "live" && (
            <span>Connected. Speak normally — the dispatcher will respond.</span>
          )}
          {errorText && <span className="v2-bad">Error: {errorText}</span>}
        </div>
      </section>

      <section className="v2-transcript" aria-live="polite">
        <h2>Transcript</h2>
        {turns.length === 0 ? (
          <p className="v2-empty">
            No transcript yet — it will populate once the call is
            connected.
          </p>
        ) : (
          <ol>
            {turns.map((t) => (
              <li key={t.id} className={`v2-turn v2-turn-${t.role}`}>
                <span className="v2-role">
                  {t.role === "user" ? "caller" : "dispatcher"}
                </span>
                <span className="v2-text">{t.text}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <footer className="v2-footer">
        <div>
          Plan C · demo-safe fallback · ElevenLabs agent id
          <code>
            {agentId
              ? ` ${agentId.slice(0, 16)}…`
              : " (not configured)"}
          </code>
        </div>
        <div>
          <a href="/prism42">/prism42</a> · <a href="/prism42/livekit">/prism42/livekit</a>
        </div>
      </footer>

      <style jsx>{`
        .v2-shell {
          max-width: 880px;
          margin: 0 auto;
          padding: 32px 24px 48px 24px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }
        .v2-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 16px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          padding-bottom: 16px;
        }
        .v2-header h1 {
          margin: 0 0 6px 0;
          font-size: 22px;
          font-weight: 600;
          letter-spacing: -0.01em;
        }
        .v2-subtitle {
          margin: 0;
          max-width: 60ch;
          color: var(--text-dim, #9aa4b0);
          font-size: 13px;
          line-height: 1.55;
        }
        .v2-chip {
          font-family: var(--mono, ui-monospace, Menlo, monospace);
          font-size: 11px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px solid rgba(255, 255, 255, 0.12);
          background: rgba(255, 255, 255, 0.04);
          color: var(--text-dim, #9aa4b0);
          white-space: nowrap;
          flex-shrink: 0;
        }
        .v2-chip-live {
          color: #5bd88a;
          border-color: rgba(91, 216, 138, 0.4);
          background: rgba(91, 216, 138, 0.08);
        }
        .v2-chip-connecting {
          color: #ffb86b;
          border-color: rgba(255, 184, 107, 0.4);
        }
        .v2-chip-error {
          color: #ff5f6d;
          border-color: rgba(255, 95, 109, 0.4);
          background: rgba(255, 95, 109, 0.08);
        }

        .v2-controls {
          display: flex;
          flex-direction: column;
          gap: 12px;
          padding: 24px;
          border-radius: 14px;
          border: 1px solid rgba(255, 255, 255, 0.08);
          background: rgba(15, 20, 28, 0.6);
        }
        .v2-button {
          align-self: flex-start;
          font-family: inherit;
          font-size: 15px;
          font-weight: 500;
          letter-spacing: -0.01em;
          padding: 12px 22px;
          border-radius: 10px;
          border: 1px solid rgba(95, 183, 255, 0.5);
          background: linear-gradient(
            180deg,
            rgba(95, 183, 255, 0.2) 0%,
            rgba(95, 183, 255, 0.08) 100%
          );
          color: #e7ecf2;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .v2-button:hover:not(:disabled) {
          border-color: rgba(95, 183, 255, 0.8);
          background: linear-gradient(
            180deg,
            rgba(95, 183, 255, 0.28) 0%,
            rgba(95, 183, 255, 0.12) 100%
          );
        }
        .v2-button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .v2-button-live {
          border-color: rgba(255, 95, 109, 0.6);
          background: linear-gradient(
            180deg,
            rgba(255, 95, 109, 0.22) 0%,
            rgba(255, 95, 109, 0.08) 100%
          );
        }
        .v2-hint {
          font-size: 13px;
          color: var(--text-dim, #9aa4b0);
          line-height: 1.5;
        }
        .v2-bad {
          color: #ff5f6d;
        }

        .v2-transcript {
          border-radius: 14px;
          border: 1px solid rgba(255, 255, 255, 0.08);
          background: rgba(15, 20, 28, 0.6);
          padding: 20px 24px;
        }
        .v2-transcript h2 {
          margin: 0 0 12px 0;
          font-size: 13px;
          font-weight: 500;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-dim, #9aa4b0);
        }
        .v2-transcript ol {
          list-style: none;
          padding: 0;
          margin: 0;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .v2-empty {
          margin: 0;
          color: var(--text-dim, #9aa4b0);
          font-size: 13px;
          font-style: italic;
        }
        .v2-turn {
          display: grid;
          grid-template-columns: 96px 1fr;
          gap: 16px;
          align-items: baseline;
          padding: 8px 0;
          border-bottom: 1px dashed rgba(255, 255, 255, 0.06);
        }
        .v2-turn:last-child {
          border-bottom: none;
        }
        .v2-role {
          font-family: var(--mono, ui-monospace, Menlo, monospace);
          font-size: 11px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-dim, #9aa4b0);
        }
        .v2-turn-user .v2-role {
          color: #5fb7ff;
        }
        .v2-turn-agent .v2-role {
          color: #ffb86b;
        }
        .v2-text {
          font-size: 14px;
          line-height: 1.55;
        }

        .v2-footer {
          display: flex;
          justify-content: space-between;
          gap: 16px;
          flex-wrap: wrap;
          font-size: 12px;
          color: var(--text-dim, #9aa4b0);
          padding-top: 8px;
          border-top: 1px solid rgba(255, 255, 255, 0.06);
        }
        .v2-footer code {
          font-family: var(--mono, ui-monospace, Menlo, monospace);
          font-size: 11px;
          color: var(--text-dim, #9aa4b0);
        }
        .v2-footer a {
          color: #5fb7ff;
        }
      `}</style>
    </main>
  );
}

export default function PrismV2Page() {
  return (
    <ConversationProvider>
      <V2Inner />
    </ConversationProvider>
  );
}
