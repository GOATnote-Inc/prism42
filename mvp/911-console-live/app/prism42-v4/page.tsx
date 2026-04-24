"use client";

// /prism42-v4 — "Vision Link" surface on top of the v3 native-Claude voice backend.
//
// Same ElevenLabs ConvAI wiring as app/prism42-v3/page.tsx (agent id from
// NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID). Voice + transcript are LIVE. Everything
// else on this page — drone SVG feed, bounding-box detections, tool trace,
// 3-channel audio strip, proposed robot plan — is a narrative mock that
// illustrates how a real vision/robotics channel would layer on top of the
// same voice line. No vision pipeline is running. Intentionally does NOT
// touch /prism42, /prism42-v2, /prism42-v3, /prism42-b300 or /prism42/livekit.

import { useCallback, useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";

type TranscriptTurn = {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: number;
};

type Detection = {
  id: string;
  label: string;
  conf: number;
  box: [number, number, number, number];
  color: string;
  state: string;
};

// Design source: /tmp/b300_design/named/05-V4Vision.jsx
const V4_DETECTIONS: Detection[] = [
  { id: "d1", label: "person · supine",                conf: 0.94, box: [120, 140,  90,  50], color: "#ffd84d", state: "injured" },
  { id: "d2", label: "person · standing",              conf: 0.91, box: [280,  60,  40, 140], color: "#ffb84d", state: "caller" },
  { id: "d3", label: "vehicle · sedan · overturned",   conf: 0.97, box: [ 60,  40, 180, 120], color: "#ff0096", state: "hazard" },
  { id: "d4", label: "vehicle · truck",                conf: 0.88, box: [330, 120, 120,  80], color: "#ffb84d", state: "secondary" },
  { id: "d5", label: "fluid pool · fuel",              conf: 0.79, box: [200, 210,  80,  30], color: "#ff0096", state: "hazmat" },
  { id: "d6", label: "smoke · light",                  conf: 0.68, box: [ 80,  20, 120,  40], color: "#ff0096", state: "hazard" },
];

type ToolCall = { ms: number; op: string; args: string; out: string; ongoing?: boolean };
const V4_TOOL_CALLS: ToolCall[] = [
  { ms: 42, op: "vision.detect",   args: "model=owl-v3, stream=drone-07", out: "6 objects · 4 of concern", ongoing: true },
  { ms: 88, op: "vision.depth",    args: "scene=frame_1247",              out: "supine person 2.3m from vehicle" },
  { ms: 31, op: "vision.classify", args: "fluid_pool, spectral",          out: "gasoline · conf 0.79" },
  { ms: 54, op: "robot.plan",      args: "goal=extract_safe_zone",        out: "3 waypoints · 11m path" },
  { ms: 22, op: "hazmat.assess",   args: "fuel + heat_signature",         out: "risk=HIGH · evac 50ft" },
  { ms: 19, op: "vision.track",    args: "target=person_d1",              out: "breathing detected 14/min" },
];

function BoundingBox({ det }: { det: Detection }) {
  const [x, y, w, h] = det.box;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill="none" stroke={det.color} strokeWidth="1.5" />
      {[[0, 0], [w, 0], [0, h], [w, h]].map(([dx, dy], i) => (
        <g key={i} transform={`translate(${x + dx}, ${y + dy})`}>
          <line x1={dx ? -6 : 0} y1="0" x2={dx ? 0 : 6} y2="0" stroke={det.color} strokeWidth="2" />
          <line x1="0" y1={dy ? -6 : 0} x2="0" y2={dy ? 0 : 6} stroke={det.color} strokeWidth="2" />
        </g>
      ))}
      <g transform={`translate(${x}, ${y - 4})`}>
        <rect x="0" y="-12" width={det.label.length * 5.5 + 32} height="12" fill={det.color} opacity="0.9" />
        <text x="4" y="-3" fill="#0a0a0b" fontSize="9" fontFamily="var(--mono)" fontWeight="500">
          {det.label} · {det.conf.toFixed(2)}
        </text>
      </g>
    </g>
  );
}

function V4Inner() {
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
    <main className="v4-shell">
      {/* TOP BAR */}
      <header className="v4-topbar">
        <div className="v4-brand">
          <span className="v4-brand-mark">B300</span>
          <span className="v4-brand-slash">/</span>
          <span className="v4-brand-name">voice.console</span>
          <span className="v4-brand-slash">/</span>
          <span className="v4-brand-env">vision link</span>
        </div>
        <div className="v4-topbar-meta">
          <span className={`v4-chip v4-chip-${chipLabel}`}>
            <span className={`v4-dot ${live ? "v4-dot-live" : ""}`} />
            call #05 · {chipLabel}
          </span>
          <span className="v4-chip v4-chip-muted">field unit · DRONE-07 · 94% battery</span>
          <span className="v4-chip v4-chip-amber">uplink 42ms · 4k30</span>
          <span className="v4-chip v4-chip-muted">elapsed {elapsed}</span>
        </div>
      </header>

      <div className="v4-subbar">
        <div className="v4-subbar-left">
          simulation — synthetic demo. vision detections, tool trace, and the
          robot plan are narrative mocks; voice + transcript are live.
        </div>
        <div className="v4-subbar-right">
          robot.autonomy <span className="v4-amber">L2 · supervised</span> ·
          vision.model <span className="v4-green">owl-v3</span>
        </div>
      </div>

      {/* MAIN GRID */}
      <div className="v4-grid">
        {/* LEFT: drone feed + audio + robot plan */}
        <section className="v4-panel v4-panel-vision">
          <div className="v4-feed">
            <svg viewBox="0 0 480 300" preserveAspectRatio="xMidYMid meet" className="v4-feed-svg">
              <defs>
                <pattern id="v4scan" width="4" height="4" patternUnits="userSpaceOnUse">
                  <rect width="4" height="4" fill="#0a0a10" />
                  <line x1="0" y1="0" x2="4" y2="0" stroke="#121218" strokeWidth="0.5" />
                </pattern>
                <linearGradient id="v4sky" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0" stopColor="#15151e" />
                  <stop offset="1" stopColor="#0a0a10" />
                </linearGradient>
              </defs>
              <rect width="480" height="300" fill="url(#v4sky)" />
              <rect width="480" height="300" fill="url(#v4scan)" opacity="0.4" />
              <path d="M 0 180 L 480 200" stroke="#2a2a35" strokeWidth="0.8" />
              <path d="M 0 250 L 480 280" stroke="#2a2a35" strokeWidth="1.2" />
              <path d="M 100 300 L 240 180 L 380 300" stroke="#1f1f28" strokeWidth="0.5" fill="none" />
              <g opacity="0.5">
                <polygon points="60,160 240,140 220,180 80,200" fill="#2a2a35" />
                <polygon points="330,200 450,190 440,240 340,230" fill="#2a2a35" />
                <ellipse cx="165" cy="170" rx="45" ry="10" fill="#1f1f28" />
                <ellipse cx="300" cy="130" rx="12" ry="35" fill="#1f1f28" />
                <ellipse cx="240" cy="230" rx="40" ry="8" fill="#0f0f16" />
                <ellipse cx="140" cy="45" rx="60" ry="20" fill="#1a1a22" opacity="0.6" />
              </g>
              {V4_DETECTIONS.map((d) => <BoundingBox key={d.id} det={d} />)}
              <g stroke="#ff0096" strokeWidth="0.5" fill="none" opacity="0.8">
                <line x1="240" y1="10" x2="240" y2="30" />
                <line x1="240" y1="270" x2="240" y2="290" />
                <line x1="10" y1="150" x2="30" y2="150" />
                <line x1="450" y1="150" x2="470" y2="150" />
              </g>
              <g fontFamily="var(--mono)" fontSize="8" fill="#ff0096">
                <text x="8" y="14">ALT 24.2m</text>
                <text x="8" y="26">HDG 094°</text>
                <text x="8" y="38">SPD 0.0 m/s</text>
                <text x="425" y="14" textAnchor="end">FRM 001247</text>
                <text x="425" y="26" textAnchor="end">IR OFF</text>
                <text x="425" y="38" textAnchor="end">GPS 39.5296</text>
                <text x="8" y="294">[REC] · {elapsed}</text>
                <text x="472" y="294" textAnchor="end">f/2.8 · ISO 800</text>
              </g>
            </svg>
            <div className="v4-feed-caption">
              <span className="v4-hot">VISION LINK ACTIVE</span>
              <span className="v4-text-2"> · AI streaming scene to caller via voice </span>
              <span className="v4-text-3">· &quot;I can see a person lying 8 feet from the vehicle…&quot;</span>
            </div>
          </div>

          <div className="v4-strip">
            <div className="v4-strip-audio">
              <div className="v4-strip-hd">
                <span>call #05 · caller on line</span>
                <span className="v4-hot">● voice + vision</span>
              </div>
              <div className="v4-channel">
                <span className="v4-chan-label v4-hot">CALLER</span>
                <div className={`v4-bars ${live ? "v4-bars-live" : ""}`}>
                  {Array.from({ length: 36 }).map((_, i) => (
                    <span key={i} className="v4-bar v4-bar-hot" style={{ animationDelay: `${i * 35}ms` }} />
                  ))}
                </div>
                <span className="v4-chan-meter">{live ? "0.88" : "—"}</span>
              </div>
              <div className="v4-channel">
                <span className="v4-chan-label v4-text-2">AI</span>
                <div className="v4-bars v4-bars-idle">
                  {Array.from({ length: 36 }).map((_, i) => (
                    <span key={i} className="v4-bar v4-bar-white" style={{ animationDelay: `${i * 48}ms` }} />
                  ))}
                </div>
                <span className="v4-chan-meter">—</span>
              </div>
              <div className="v4-channel">
                <span className="v4-chan-label v4-amber">DRONE</span>
                <div className="v4-bars v4-bars-live">
                  {Array.from({ length: 36 }).map((_, i) => (
                    <span key={i} className="v4-bar v4-bar-amber" style={{ animationDelay: `${i * 90}ms` }} />
                  ))}
                </div>
                <span className="v4-chan-meter">tlm</span>
              </div>
            </div>

            <div className="v4-strip-plan">
              <div className="v4-strip-hd">
                <span>robot plan · proposed</span>
                <span className="v4-amber">awaiting commit</span>
              </div>
              <div className="v4-plan-row">
                <span className="v4-plan-n">1</span>
                <span className="v4-plan-text">approach person_d1 from north (upwind)</span>
                <span className="v4-plan-meas">4.2m</span>
              </div>
              <div className="v4-plan-row">
                <span className="v4-plan-n">2</span>
                <span className="v4-plan-text">stream vitals · thermal overlay</span>
                <span className="v4-plan-meas">continuous</span>
              </div>
              <div className="v4-plan-row">
                <span className="v4-plan-n">3</span>
                <span className="v4-plan-text">guide caller vocally to safe zone</span>
                <span className="v4-plan-meas">6.8m</span>
              </div>
              <div className="v4-plan-btns">
                <button className="v4-btn v4-btn-primary" disabled>execute ⌥↩</button>
                <button className="v4-btn v4-btn-ghost" disabled>hold</button>
              </div>
            </div>
          </div>

          <div className="v4-voice-controls">
            <div className="v4-voice-col">
              <h1 className="v4-title">Vision Link · live dispatcher</h1>
              <p className="v4-subtitle">
                native claude sonnet-4.6 inside elevenlabs convai · voice wire
                identical to /prism42-v3 · vision + robot channels are
                narrative mocks illustrating how the stack would extend
              </p>
            </div>
            <div className="v4-voice-btncol">
              <button
                type="button"
                className={`v4-big-button ${live ? "v4-big-button-live" : ""}`}
                onClick={live ? endCall : startCall}
                disabled={phase === "connecting" || phase === "ending" || !agentId}
              >
                {buttonLabel}
              </button>
              <div className="v4-hint">
                {!agentId && (
                  <span className="v4-bad">missing env: NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID</span>
                )}
                {agentId && phase === "idle" && <span>mic required. click to connect.</span>}
                {phase === "connecting" && <span>connecting to elevenlabs convai…</span>}
                {phase === "live" && <span>connected. speak normally.</span>}
                {phase === "ended" && <span>call ended. click to reconnect.</span>}
                {errorText && <span className="v4-bad">error: {errorText}</span>}
              </div>
            </div>
          </div>
        </section>

        {/* RIGHT: detections + tool trace + transcript */}
        <section className="v4-panel v4-panel-right">
          <div className="v4-sub">
            <div className="v4-sub-hd">
              <span className="v4-sub-t">VISION · DETECTIONS</span>
              <span className="v4-sub-s">6 objects · 4 high priority</span>
            </div>
            <div className="v4-det-list">
              {V4_DETECTIONS.map((d) => (
                <div key={d.id} className="v4-det-row">
                  <span className="v4-det-swatch" style={{ background: d.color }} />
                  <div>
                    <div className="v4-det-label">{d.label}</div>
                    <div className="v4-det-state">{d.state}</div>
                  </div>
                  <span className="v4-det-conf">{d.conf.toFixed(2)}</span>
                  <button className="v4-det-track" disabled>track</button>
                </div>
              ))}
            </div>
          </div>

          <div className="v4-sub">
            <div className="v4-sub-hd">
              <span className="v4-sub-t">TOOL TRACE · VISION + ROBOT</span>
              <span className="v4-sub-s">268ms p99 · ongoing stream</span>
            </div>
            <div className="v4-tool-list">
              {V4_TOOL_CALLS.map((t, i) => (
                <div key={i} className="v4-tool-row">
                  <span className={`v4-tool-ms ${t.ongoing ? "v4-tool-ms-ongoing" : ""}`}>
                    {t.ms}ms{t.ongoing ? "*" : ""}
                  </span>
                  <div>
                    <span className="v4-tool-op">{t.op}</span>
                    <span className="v4-tool-args">({t.args})</span>
                    <div className="v4-tool-out">→ {t.out}</div>
                  </div>
                </div>
              ))}
              <div className="v4-tool-foot">* = ongoing · streaming</div>
            </div>
          </div>

          <div className="v4-sub v4-sub-transcript" aria-live="polite">
            <div className="v4-sub-hd">
              <span className="v4-sub-t">TRANSCRIPT · VISION-GROUNDED</span>
              <span className="v4-sub-s">
                {turns.length} turn{turns.length === 1 ? "" : "s"} · ai uses scene context
              </span>
            </div>
            <div className="v4-transcript-body">
              {turns.length === 0 ? (
                <div className="v4-empty">
                  no transcript yet. vision context (6 detections) will be
                  referenced by the agent on every turn once the call
                  connects.
                </div>
              ) : (
                <ol className="v4-turns">
                  {turns.map((t) => (
                    <li key={t.id} className={`v4-turn v4-turn-${t.role}`}>
                      <span className="v4-turn-role">
                        {t.role === "user"
                          ? "caller"
                          : "ai · vision-grounded"}
                      </span>
                      <span className="v4-turn-text">{t.text}</span>
                      {t.role === "agent" && (
                        <span className="v4-turn-foot">
                          ↳ vision detections injected into context
                        </span>
                      )}
                    </li>
                  ))}
                  {live && (
                    <li className="v4-turn-composing">
                      <span className="v4-dot v4-dot-live" />
                      ai composing · vision context 6 objects
                    </li>
                  )}
                </ol>
              )}
            </div>
          </div>
        </section>
      </div>

      {/* Footer */}
      <footer className="v4-footer">
        <div>
          plan-c + vision · elevenlabs native-claude ·
          {agentId ? ` ${agentId.slice(0, 20)}…` : " (not configured)"}
        </div>
        <div>
          <a href="/prism42">/prism42</a> ·{" "}
          <a href="/prism42-v2">/prism42-v2</a> ·{" "}
          <a href="/prism42-v3">/prism42-v3</a> ·{" "}
          <a href="/prism42/livekit">/prism42/livekit</a>
        </div>
      </footer>

      <style jsx global>{`
        :root { --bg: #0a0a0b; --bg-outer: #050506; --panel: #121214; --panel-2: #161618; --border: #1f1f22; --border-2: #2a2a2e; --text: #e8e8ea; --text-2: #8a8a90; --text-3: #55555a; --hot: #ff0096; --hot-bg: rgba(255,0,150,0.08); --hot-border: rgba(255,0,150,0.35); --green: #4ade80; --amber: #ffb84d; --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace; --sans: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif; }
        html, body { background: var(--bg-outer); color: var(--text); font-family: var(--mono); font-size: 12px; line-height: 1.45; letter-spacing: 0.005em; }
      `}</style>

      <style jsx>{`
        .v4-shell { max-width: 1440px; margin: 0 auto; padding: 14px 18px 28px; display: flex; flex-direction: column; gap: 10px; font-family: var(--mono); color: var(--text); }
        .v4-topbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 9px 14px; background: var(--panel); border: 1px solid var(--border); border-radius: 3px; }
        .v4-brand { display: flex; align-items: center; gap: 9px; font-size: 13px; letter-spacing: 0.04em; }
        .v4-brand-mark { color: var(--hot); font-weight: 600; letter-spacing: 0.08em; }
        .v4-brand-slash { color: var(--text-3); }
        .v4-brand-name { color: var(--text); }
        .v4-brand-env { color: var(--hot); background: var(--hot-bg); padding: 2px 8px; border-radius: 2px; border: 1px solid var(--hot-border); font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; }
        .v4-topbar-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
        .v4-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; border: 1px solid var(--border-2); border-radius: 2px; color: var(--text-2); background: var(--panel-2); white-space: nowrap; }
        .v4-chip-muted { color: var(--text-3); }
        .v4-chip-amber { color: var(--amber); border-color: rgba(255,184,77,0.4); }
        .v4-chip-live { color: var(--hot); border-color: var(--hot-border); background: var(--hot-bg); }
        .v4-chip-connecting { color: var(--amber); border-color: rgba(255,184,77,0.4); }
        .v4-chip-error { color: #ff6b6b; border-color: rgba(255,107,107,0.4); }
        .v4-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); }
        .v4-dot-live { background: var(--hot); box-shadow: 0 0 8px var(--hot); animation: v4-pulse 1.2s ease-in-out infinite; }
        @keyframes v4-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
        .v4-subbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 8px 12px; border: 1px solid var(--hot-border); background: var(--hot-bg); color: var(--text-2); border-radius: 3px; font-size: 10px; letter-spacing: 0.02em; }
        .v4-subbar-left { flex: 1; }
        .v4-subbar-right { color: var(--text-3); white-space: nowrap; }
        .v4-amber { color: var(--amber); } .v4-green { color: var(--green); } .v4-hot { color: var(--hot); } .v4-text-2 { color: var(--text-2); } .v4-text-3 { color: var(--text-3); }
        .v4-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 10px; }
        @media (max-width: 960px) { .v4-grid { grid-template-columns: 1fr; } }
        .v4-panel { background: var(--panel); border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
        .v4-panel-vision, .v4-panel-right { display: flex; flex-direction: column; }
        .v4-feed { position: relative; background: #05050b; overflow: hidden; aspect-ratio: 8/5; }
        .v4-feed-svg { width: 100%; height: 100%; display: block; }
        .v4-feed-caption { position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%); background: rgba(10,10,11,0.85); border: 1px solid var(--hot-border); padding: 5px 12px; font-size: 10px; white-space: nowrap; }
        .v4-strip { display: grid; grid-template-columns: 1.3fr 1fr; border-top: 1px solid var(--border); }
        .v4-strip-audio { padding: 10px 14px; border-right: 1px solid var(--border); }
        .v4-strip-plan { padding: 10px 14px; }
        .v4-strip-hd { font-size: 9px; color: var(--text-3); letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 8px; display: flex; justify-content: space-between; }
        .v4-channel { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
        .v4-chan-label { font-size: 9px; width: 50px; letter-spacing: 0.08em; }
        .v4-chan-meter { font-size: 9px; color: var(--text-3); width: 42px; text-align: right; font-variant-numeric: tabular-nums; }
        .v4-bars { flex: 1; display: flex; gap: 1px; align-items: center; height: 18px; }
        .v4-bar { flex: 1; height: 3px; background: var(--border-2); border-radius: 1px; }
        .v4-bars-live .v4-bar-hot { background: var(--hot); animation: v4-bar 1.1s ease-in-out infinite; }
        .v4-bars-live .v4-bar-amber { background: var(--amber); animation: v4-bar 2.2s ease-in-out infinite; }
        .v4-bars-idle .v4-bar-white { background: #2a2a2e; opacity: 0.5; }
        @keyframes v4-bar { 0%,100% { height: 3px; opacity: 0.5; } 25% { height: 16px; opacity: 1; } 50% { height: 6px; opacity: 0.75; } 75% { height: 12px; opacity: 0.9; } }
        .v4-plan-row { display: grid; grid-template-columns: 16px 1fr auto; gap: 8px; align-items: baseline; font-size: 10px; padding: 2px 0; }
        .v4-plan-n { color: var(--hot); font-weight: 500; }
        .v4-plan-text { color: var(--text); }
        .v4-plan-meas { color: var(--text-3); font-variant-numeric: tabular-nums; }
        .v4-plan-btns { display: flex; gap: 4px; margin-top: 8px; }
        .v4-btn { font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; padding: 6px 10px; border-radius: 2px; cursor: not-allowed; opacity: 0.55; }
        .v4-btn-primary { flex: 1; background: var(--hot); color: var(--bg); border: 1px solid var(--hot); font-weight: 500; }
        .v4-btn-ghost { background: transparent; color: var(--text-2); border: 1px solid var(--border-2); }
        .v4-voice-controls { display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: center; padding: 14px 18px; border-top: 1px solid var(--border); }
        .v4-voice-col { display: flex; flex-direction: column; gap: 6px; }
        .v4-title { font-family: var(--sans); font-size: 18px; font-weight: 500; letter-spacing: -0.01em; margin: 0; color: var(--text); }
        .v4-subtitle { margin: 0; color: var(--text-2); font-size: 11px; letter-spacing: 0.02em; line-height: 1.5; }
        .v4-voice-btncol { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }
        .v4-big-button { font-family: var(--mono); font-size: 12px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; padding: 12px 22px; border-radius: 2px; border: 1px solid var(--hot-border); background: var(--hot-bg); color: var(--hot); cursor: pointer; transition: all 0.15s ease; }
        .v4-big-button:hover:not(:disabled) { background: rgba(255,0,150,0.16); border-color: var(--hot); box-shadow: 0 0 16px rgba(255,0,150,0.25); }
        .v4-big-button:disabled { opacity: 0.4; cursor: not-allowed; }
        .v4-big-button-live { background: var(--hot); color: var(--bg-outer); border-color: var(--hot); animation: v4-pulse 1.6s ease-in-out infinite; }
        .v4-big-button-live:hover:not(:disabled) { background: #ff33aa; }
        .v4-hint { font-size: 10px; color: var(--text-2); letter-spacing: 0.02em; text-align: right; min-height: 1.3em; }
        .v4-bad { color: #ff6b6b; }
        .v4-sub { border-bottom: 1px solid var(--border); display: flex; flex-direction: column; min-height: 0; }
        .v4-sub:last-child { border-bottom: none; }
        .v4-sub-transcript { flex: 1; min-height: 260px; }
        .v4-sub-hd { display: flex; justify-content: space-between; align-items: center; padding: 7px 14px; background: var(--panel-2); border-bottom: 1px solid var(--border); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-2); }
        .v4-sub-t { color: var(--text); } .v4-sub-s { color: var(--text-3); }
        .v4-det-list { max-height: 200px; overflow-y: auto; }
        .v4-det-row { display: grid; grid-template-columns: 10px 1fr auto auto; gap: 10px; padding: 6px 14px; border-bottom: 1px solid var(--border); align-items: center; font-size: 10px; }
        .v4-det-swatch { width: 4px; height: 14px; display: inline-block; }
        .v4-det-label { color: var(--text); }
        .v4-det-state { color: var(--text-3); font-size: 9px; }
        .v4-det-conf { color: var(--text-2); font-variant-numeric: tabular-nums; }
        .v4-det-track { background: transparent; color: var(--text-3); border: 1px solid var(--border-2); padding: 2px 6px; font-family: var(--mono); font-size: 8px; letter-spacing: 0.05em; text-transform: uppercase; cursor: not-allowed; opacity: 0.65; }
        .v4-tool-list { padding: 6px 14px; max-height: 220px; overflow-y: auto; font-size: 10px; }
        .v4-tool-row { display: grid; grid-template-columns: 48px 1fr; gap: 8px; padding: 3px 0; border-bottom: 1px dashed var(--border); }
        .v4-tool-ms { color: var(--text-3); font-variant-numeric: tabular-nums; }
        .v4-tool-ms-ongoing { color: var(--hot); }
        .v4-tool-op { color: var(--hot); }
        .v4-tool-args { color: var(--text-3); margin-left: 4px; }
        .v4-tool-out { color: var(--text-2); padding-left: 10px; }
        .v4-tool-foot { color: var(--text-3); font-size: 9px; margin-top: 4px; }
        .v4-transcript-body { flex: 1; padding: 12px 16px; overflow-y: auto; max-height: 320px; }
        .v4-empty { color: var(--text-3); font-style: italic; font-size: 11px; letter-spacing: 0.02em; }
        .v4-turns { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
        .v4-turn { display: grid; grid-template-columns: 110px 1fr; gap: 12px; align-items: baseline; padding: 6px 0; border-bottom: 1px dashed var(--border); row-gap: 2px; }
        .v4-turn:last-child { border-bottom: none; }
        .v4-turn-role { font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3); }
        .v4-turn-user .v4-turn-role { color: var(--hot); }
        .v4-turn-agent .v4-turn-role { color: var(--text-3); }
        .v4-turn-text { font-family: var(--sans); font-size: 13px; line-height: 1.5; color: var(--text); letter-spacing: 0.005em; }
        .v4-turn-agent .v4-turn-text { border-left: 2px solid var(--hot); padding-left: 10px; margin-left: -12px; }
        .v4-turn-foot { grid-column: 2 / 3; color: var(--green); font-size: 9px; margin-top: 1px; }
        .v4-turn-composing { display: flex; align-items: center; gap: 8px; color: var(--hot); font-size: 10px; font-style: italic; padding-top: 2px; }
        .v4-footer { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 9px 14px; border: 1px solid var(--border); border-radius: 3px; background: var(--panel); font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); }
        .v4-footer a { color: var(--hot); text-decoration: none; }
        .v4-footer a:hover { text-decoration: underline; }
      `}</style>
    </main>
  );
}

export default function PrismV4Page() {
  return (
    <ConversationProvider>
      <V4Inner />
    </ConversationProvider>
  );
}
