"use client";

// /prism42-v3 — v2 in the B300 Voice Console visual system.
//
// SAME BACKEND AS v2: ElevenLabs ConvAI, agent_7601kq0ew05tfner6aed2xnnnfxm
// (NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID), native Sonnet 4.6, Sarah voice.
// Logic cloned verbatim from app/prism42-v2/page.tsx. Only the visual
// system is different — hot-magenta on near-black, IBM Plex Mono, sharp
// radii, panelized layout. Intentionally NOT touching /prism42-v2 so it
// stays the safe-fallback surface the user already validated.

import { useCallback, useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";

type TranscriptTurn = {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: number;
};

function V3Inner() {
  const agentId = process.env.NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID;

  const [phase, setPhase] = useState<
    "idle" | "connecting" | "live" | "ending" | "ended" | "error"
  >("idle");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState("00:00");
  const turnSeq = useRef(0);

  function appendTurn(role: "user" | "agent", text: string) {
    turnSeq.current += 1;
    const id = `t-${turnSeq.current}-${Date.now().toString(36)}`;
    setTurns((ts) => [...ts, { id, role, text, ts: Date.now() }]);
  }

  const conversation = useConversation({
    onConnect: () => {
      setPhase("live");
      setStartedAt(Date.now());
    },
    onDisconnect: () => {
      setPhase("ended");
      setStartedAt(null);
    },
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

  // Elapsed-timer tick while live.
  useEffect(() => {
    if (!startedAt) return;
    const id = setInterval(() => {
      const s = Math.floor((Date.now() - startedAt) / 1000);
      const mm = String(Math.floor(s / 60)).padStart(2, "0");
      const ss = String(s % 60).padStart(2, "0");
      setElapsed(`${mm}:${ss}`);
    }, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  // Pre-request mic permission so the click doesn't stall on a modal.
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
      .catch(() => {});
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
    } catch {}
  }, [conversation]);

  const buttonLabel =
    phase === "connecting"
      ? "connecting…"
      : phase === "live"
        ? "end the call"
        : phase === "ending"
          ? "ending…"
          : "speak to the dispatcher";

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
    <main className="v3-shell">
      {/* Top bar */}
      <header className="v3-topbar">
        <div className="v3-brand">
          <span className="v3-brand-mark">B300</span>
          <span className="v3-brand-slash">/</span>
          <span className="v3-brand-name">voice.console</span>
          <span className="v3-brand-slash">/</span>
          <span className="v3-brand-env">v3 · native-claude</span>
        </div>
        <div className="v3-topbar-meta">
          <span className="v3-chip">
            agent · {agentId ? `${agentId.slice(6, 14)}…` : "unset"}
          </span>
          <span className={`v3-chip v3-chip-${chipLabel}`}>
            <span className={`v3-dot ${live ? "v3-dot-live" : ""}`} />
            {chipLabel}
          </span>
          <span className="v3-chip v3-chip-muted">elapsed {elapsed}</span>
        </div>
      </header>

      {/* Simulation banner */}
      <div className="v3-banner">
        <span>simulation</span>
        synthetic demo, not a real emergency line. if this were real, hang
        up and dial 911 on a working phone.
      </div>

      {/* Main grid */}
      <div className="v3-grid">
        {/* Left column · live voice panel */}
        <section className="v3-panel v3-panel-voice">
          <div className="v3-panel-hd">
            <span>live voice · caller channel</span>
            <span className={`v3-panel-hd-right ${live ? "v3-hd-live" : ""}`}>
              {live ? "connected · rec" : "disconnected"}
            </span>
          </div>

          {/* Pulsing soundbar when live */}
          <div className={`v3-soundbar ${live ? "v3-soundbar-live" : ""}`}>
            {Array.from({ length: 48 }).map((_, i) => (
              <span key={i} className="v3-soundbar-tick" style={{ animationDelay: `${i * 40}ms` }} />
            ))}
          </div>

          <div className="v3-voice-body">
            <h1 className="v3-title">Live 911 Dispatcher Simulation</h1>
            <p className="v3-subtitle">
              opus 4.7 auditor + healthbench hard baseline · sovereign voice stack at{" "}
              <a href="/prism42/livekit" className="v3-subtitle-link">/prism42/livekit</a>{" "}
              (experimental)
            </p>
            <p className="v3-subtitle v3-subtitle-dim">
              real-time path · sonnet-4.6 native-claude · single voice · zero custom-llm hop ·
              &lt;1.5s first audio · opus 4.7 off-path (5% sampled critic)
            </p>

            <button
              type="button"
              className={`v3-button ${live ? "v3-button-live" : ""}`}
              onClick={live ? endCall : startCall}
              disabled={phase === "connecting" || phase === "ending" || !agentId}
            >
              {buttonLabel}
            </button>

            <div className="v3-hint">
              {!agentId && (
                <span className="v3-bad">
                  missing env: NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID
                </span>
              )}
              {agentId && phase === "idle" && (
                <span>click to connect. microphone permission required.</span>
              )}
              {phase === "connecting" && (
                <span>connecting to elevenlabs convai…</span>
              )}
              {phase === "live" && (
                <span>connected. speak normally — the dispatcher will respond.</span>
              )}
              {phase === "ended" && <span>call ended. click to reconnect.</span>}
              {errorText && <span className="v3-bad">error: {errorText}</span>}
            </div>
          </div>
        </section>

        {/* Right column · transcript */}
        <section className="v3-panel v3-panel-transcript" aria-live="polite">
          <div className="v3-panel-hd">
            <span>transcript · streaming</span>
            <span className="v3-panel-hd-right">
              {turns.length} turn{turns.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="v3-transcript-body">
            {turns.length === 0 ? (
              <div className="v3-empty">
                no transcript yet. turns will stream in once the call connects.
              </div>
            ) : (
              <ol className="v3-turns">
                {turns.map((t) => (
                  <li key={t.id} className={`v3-turn v3-turn-${t.role}`}>
                    <span className="v3-turn-role">
                      {t.role === "user" ? "caller" : "dispatcher"}
                    </span>
                    <span className="v3-turn-text">{t.text}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
      </div>

      {/* Footer */}
      <footer className="v3-footer">
        <div>
          cloud backup (plan-c) · sonnet-4.6 native-claude (real-time) · opus 4.7 auditor (off-path) ·
          {agentId ? ` ${agentId.slice(0, 20)}…` : " (not configured)"}
        </div>
        <div>
          <a href="/prism42">/prism42</a> ·{" "}
          <a href="/prism42/livekit">/prism42/livekit (experimental)</a> ·{" "}
          <a href="/prism42-v2">/prism42-v2</a>
        </div>
      </footer>

      {/* ———————————————————————————————————————————————————————————— */}
      {/* B300 Voice Console tokens · hot-magenta on near-black · IBM Plex */}
      {/* ———————————————————————————————————————————————————————————— */}
      <style jsx global>{`
        :root {
          --bg: #0a0a0b;
          --bg-outer: #050506;
          --panel: #121214;
          --panel-2: #161618;
          --border: #1f1f22;
          --border-2: #2a2a2e;
          --text: #e8e8ea;
          --text-2: #8a8a90;
          --text-3: #55555a;
          --hot: #ff0096;
          --hot-bg: rgba(255, 0, 150, 0.08);
          --hot-border: rgba(255, 0, 150, 0.35);
          --green: #4ade80;
          --amber: #ffb84d;
          --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
          --sans: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif;
        }
        html, body {
          background: var(--bg-outer);
          color: var(--text);
          font-family: var(--mono);
          font-size: 12px;
          line-height: 1.45;
          letter-spacing: 0.005em;
        }
        body > div > div.simulation-banner { display: none !important; }
      `}</style>

      <style jsx>{`
        .v3-shell {
          max-width: 1440px;
          margin: 0 auto;
          padding: 18px 20px 32px 20px;
          display: flex;
          flex-direction: column;
          gap: 14px;
          font-family: var(--mono);
          color: var(--text);
        }

        /* topbar */
        .v3-topbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          padding: 10px 14px;
          background: var(--panel);
          border: 1px solid var(--border);
          border-radius: 3px;
        }
        .v3-brand {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 13px;
          letter-spacing: 0.04em;
        }
        .v3-brand-mark {
          color: var(--hot);
          font-weight: 600;
          letter-spacing: 0.08em;
        }
        .v3-brand-slash { color: var(--text-3); }
        .v3-brand-name { color: var(--text); }
        .v3-brand-env {
          color: var(--hot);
          background: var(--hot-bg);
          padding: 2px 8px;
          border-radius: 2px;
          border: 1px solid var(--hot-border);
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .v3-topbar-meta {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .v3-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 3px 10px;
          font-size: 10px;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          border: 1px solid var(--border-2);
          border-radius: 2px;
          color: var(--text-2);
          background: var(--panel-2);
          white-space: nowrap;
        }
        .v3-chip-muted { color: var(--text-3); }
        .v3-chip-live {
          color: var(--hot);
          border-color: var(--hot-border);
          background: var(--hot-bg);
        }
        .v3-chip-error {
          color: #ff6b6b;
          border-color: rgba(255, 107, 107, 0.4);
        }
        .v3-chip-connecting { color: var(--amber); border-color: rgba(255, 184, 77, 0.4); }
        .v3-dot {
          width: 6px; height: 6px;
          border-radius: 50%;
          background: var(--text-3);
        }
        .v3-dot-live {
          background: var(--hot);
          box-shadow: 0 0 8px var(--hot);
          animation: v3-pulse-hot 1.2s ease-in-out infinite;
        }
        @keyframes v3-pulse-hot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.35; }
        }

        /* banner */
        .v3-banner {
          padding: 10px 14px;
          border: 1px solid var(--hot-border);
          background: var(--hot-bg);
          color: var(--text-2);
          border-radius: 3px;
          font-size: 11px;
          letter-spacing: 0.02em;
        }
        .v3-banner span {
          color: var(--hot);
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.14em;
          margin-right: 10px;
        }

        /* grid */
        .v3-grid {
          display: grid;
          grid-template-columns: 1.4fr 1fr;
          gap: 14px;
        }
        @media (max-width: 900px) {
          .v3-grid { grid-template-columns: 1fr; }
        }

        /* panels */
        .v3-panel {
          background: var(--panel);
          border: 1px solid var(--border);
          border-radius: 3px;
          overflow: hidden;
        }
        .v3-panel-hd {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 9px 14px;
          border-bottom: 1px solid var(--border);
          font-size: 10px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--text-2);
          background: var(--panel-2);
        }
        .v3-panel-hd-right { color: var(--text-3); }
        .v3-hd-live { color: var(--hot); }

        /* soundbar */
        .v3-soundbar {
          display: flex;
          align-items: center;
          gap: 2px;
          padding: 16px;
          border-bottom: 1px solid var(--border);
          height: 52px;
        }
        .v3-soundbar-tick {
          flex: 1;
          height: 3px;
          background: var(--border-2);
          border-radius: 1px;
          transition: all 0.15s ease;
        }
        .v3-soundbar-live .v3-soundbar-tick {
          background: var(--hot);
          animation: v3-bar 1.1s ease-in-out infinite;
        }
        @keyframes v3-bar {
          0%, 100% { height: 3px; opacity: 0.5; }
          25%      { height: 20px; opacity: 1;    }
          50%      { height: 6px;  opacity: 0.7; }
          75%      { height: 14px; opacity: 0.9; }
        }

        /* voice body */
        .v3-voice-body {
          padding: 32px 28px 28px 28px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .v3-title {
          font-family: var(--sans);
          font-size: 22px;
          font-weight: 500;
          letter-spacing: -0.01em;
          margin: 0;
          color: var(--text);
        }
        .v3-subtitle {
          margin: 0;
          color: var(--text-2);
          font-size: 11px;
          letter-spacing: 0.03em;
          line-height: 1.55;
        }
        .v3-subtitle-dim {
          opacity: 0.6;
          margin-top: 4px;
        }
        .v3-subtitle-link {
          color: var(--hot);
          text-decoration: none;
          border-bottom: 1px dotted var(--hot);
        }
        .v3-subtitle-link:hover { text-decoration: none; border-bottom-style: solid; }
        .v3-button {
          align-self: flex-start;
          margin-top: 4px;
          font-family: var(--mono);
          font-size: 12px;
          font-weight: 500;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          padding: 12px 22px;
          border-radius: 2px;
          border: 1px solid var(--hot-border);
          background: var(--hot-bg);
          color: var(--hot);
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .v3-button:hover:not(:disabled) {
          background: rgba(255, 0, 150, 0.16);
          border-color: var(--hot);
          box-shadow: 0 0 16px rgba(255, 0, 150, 0.25);
        }
        .v3-button:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .v3-button-live {
          background: var(--hot);
          color: var(--bg-outer);
          border-color: var(--hot);
        }
        .v3-button-live:hover:not(:disabled) {
          background: #ff33aa;
        }
        .v3-hint {
          font-size: 11px;
          color: var(--text-2);
          letter-spacing: 0.02em;
          min-height: 1.5em;
        }
        .v3-bad { color: #ff6b6b; }

        /* transcript */
        .v3-panel-transcript { display: flex; flex-direction: column; }
        .v3-transcript-body {
          flex: 1;
          padding: 16px 18px;
          overflow-y: auto;
          max-height: 540px;
          min-height: 300px;
        }
        .v3-empty {
          color: var(--text-3);
          font-style: italic;
          font-size: 11px;
          letter-spacing: 0.02em;
        }
        .v3-turns {
          list-style: none;
          margin: 0; padding: 0;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .v3-turn {
          display: grid;
          grid-template-columns: 90px 1fr;
          gap: 14px;
          align-items: baseline;
          padding: 8px 0;
          border-bottom: 1px dashed var(--border);
        }
        .v3-turn:last-child { border-bottom: none; }
        .v3-turn-role {
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: var(--text-3);
        }
        .v3-turn-user .v3-turn-role { color: var(--text); }
        .v3-turn-agent .v3-turn-role { color: var(--hot); }
        .v3-turn-text {
          font-family: var(--sans);
          font-size: 14px;
          line-height: 1.55;
          color: var(--text);
          letter-spacing: 0.005em;
        }
        .v3-turn-user .v3-turn-text { color: var(--text); }
        .v3-turn-agent .v3-turn-text {
          color: var(--text);
          border-left: 2px solid var(--hot);
          padding-left: 12px;
          margin-left: -14px;
        }

        /* footer */
        .v3-footer {
          display: flex;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 14px;
          padding: 10px 14px;
          border: 1px solid var(--border);
          border-radius: 3px;
          background: var(--panel);
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--text-3);
        }
        .v3-footer a {
          color: var(--hot);
          text-decoration: none;
        }
        .v3-footer a:hover { text-decoration: underline; }
      `}</style>
    </main>
  );
}

export default function PrismV3Page() {
  return (
    <ConversationProvider>
      <V3Inner />
    </ConversationProvider>
  );
}
