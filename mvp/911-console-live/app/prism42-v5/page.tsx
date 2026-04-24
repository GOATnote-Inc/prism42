"use client";

// /prism42-v5 — PSAP 2031, speculative supervisor console.
//
// Creative brief: 5-year-out 911 dispatch. One human supervisor oversees
// 12 concurrent AI-handled calls, each with its own lane and pipeline.
// Features embodied here:
//   (2) AI + human symbiosis — 12 lanes, 5 live, supervisor overrides
//   (3) Cross-call pattern detection — predictive MCI banner
//   (4) Real-time translation — ES/ZH/TL lane flags
//   (5) Predictive triage — per-call trajectory + confidence bar
//   (7) Proactive callback — auto-callback timer on dispatched calls
//   (8) Evidence chain — 5-line audit row on the focused call
//   (9) Cross-PSAP network feed — anonymized prior-match hits
//
// The live-voice panel in the center is real: same ElevenLabs agent +
// useConversation hook as v3. Everything else is a high-fidelity mock
// with subtle motion (pulse, sparkline redraw, callback countdown tick,
// network-feed streak) so the page feels alive at rest.
//
// DO NOT touch /prism42-v2, /prism42-v3, /prism42-v4, /prism42-b300 —
// those are stable surfaces. v5 is additive-only.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";

type TranscriptTurn = {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: number;
};

type Lane = {
  id: string;
  phase: "intake" | "triage" | "dispatch" | "pdi" | "handoff" | "closed";
  kind: string;
  loc: string;
  priority: "P1" | "P2" | "P3" | "P4" | "P5";
  live: boolean;
  dur: number;
  seed: number;
  lang?: "EN" | "ES" | "ZH" | "TL";
  biometric?: { hr: number; stress: number };
  predict?: { label: string; conf: number };
  focus?: boolean;
};

const LANES: Lane[] = [
  {
    id: "01",
    phase: "intake",
    kind: "noise complaint",
    loc: "2nd & Virginia",
    priority: "P4",
    live: false,
    dur: 142,
    seed: 1,
  },
  {
    id: "02",
    phase: "triage",
    kind: "chest pain · 58M",
    loc: "980 Moana Ln",
    priority: "P1",
    live: true,
    dur: 46,
    seed: 2,
    biometric: { hr: 128, stress: 0.72 },
    predict: { label: "likely cardiac arrest < 90s", conf: 0.64 },
  },
  {
    id: "03",
    phase: "dispatch",
    kind: "parking",
    loc: "awaiting tow",
    priority: "P4",
    live: false,
    dur: 215,
    seed: 3,
  },
  {
    id: "04",
    phase: "intake",
    kind: "welfare check",
    loc: "S. Wells Ave",
    priority: "P3",
    live: true,
    dur: 34,
    seed: 4,
  },
  {
    id: "05",
    phase: "pdi",
    kind: "MVC · injury",
    loc: "I-80 E · mp14",
    priority: "P1",
    live: true,
    dur: 134,
    seed: 5,
    biometric: { hr: 112, stress: 0.58 },
    predict: { label: "hazmat upgrade · fuel smell", conf: 0.81 },
    focus: true,
  },
  {
    id: "06",
    phase: "closed",
    kind: "barking dog",
    loc: "routine",
    priority: "P5",
    live: false,
    dur: 67,
    seed: 6,
  },
  {
    id: "07",
    phase: "triage",
    kind: "domestic · ES",
    loc: "4th & Record",
    priority: "P2",
    live: true,
    dur: 22,
    seed: 7,
    lang: "ES",
    biometric: { hr: 104, stress: 0.88 },
    predict: { label: "weapon mentioned · prep PD", conf: 0.77 },
  },
  {
    id: "08",
    phase: "closed",
    kind: "false alarm",
    loc: "resolved",
    priority: "P5",
    live: false,
    dur: 55,
    seed: 8,
  },
  {
    id: "09",
    phase: "handoff",
    kind: "fireworks",
    loc: "Virginia St",
    priority: "P4",
    live: false,
    dur: 98,
    seed: 9,
  },
  {
    id: "10",
    phase: "dispatch",
    kind: "fall · 81F",
    loc: "Riverwalk Tower",
    priority: "P2",
    live: true,
    dur: 78,
    seed: 10,
    biometric: { hr: 92, stress: 0.44 },
    predict: { label: "hip fracture · EMS staged", conf: 0.69 },
  },
  {
    id: "11",
    phase: "closed",
    kind: "abandoned veh",
    loc: "report filed",
    priority: "P5",
    live: false,
    dur: 42,
    seed: 11,
  },
  {
    id: "12",
    phase: "intake",
    kind: "text-only · deaf caller",
    loc: "queued · TTY",
    priority: "P3",
    live: false,
    dur: 6,
    seed: 12,
  },
];

const EVIDENCE = [
  {
    t: "+02:01",
    model: "claude-opus-4.7",
    prompt_hash: "9f3a·c21",
    tool: "hazmat.upgrade(fuel_smell=true)",
    verify: "self-check pass · adjudicator agree",
  },
  {
    t: "+02:04",
    model: "claude-opus-4.7",
    prompt_hash: "9f3a·c21",
    tool: "intent.verify(pushback=t6)",
    verify: "hold rec · held",
  },
  {
    t: "+02:18",
    model: "claude-opus-4.7",
    prompt_hash: "9f3a·c22",
    tool: "cad.dispatch(EMS, P1)",
    verify: "human-committed · K.ORTIZ",
  },
  {
    t: "+02:47",
    model: "claude-opus-4.7",
    prompt_hash: "9f3a·c22",
    tool: "callback.schedule(180s)",
    verify: "auto-loop armed",
  },
  {
    t: "+03:12",
    model: "claude-opus-4.7",
    prompt_hash: "9f3a·c23",
    tool: "vision.request(sms_link)",
    verify: "pending commit",
  },
];

const NETWORK_FEED = [
  { psap: "WCSO-03", match: "voice-print 0.94", note: "3rd call this wk · same caller", age: "4m" },
  { psap: "SPD-12", match: "intersection pattern", note: "same corridor · 2 priors 90d", age: "11m" },
  { psap: "CHP-N08", match: "vehicle VIN tail", note: "stolen plate flag", age: "28m" },
  { psap: "RFD-01", match: "structure history", note: "3 prior fire responses · 180d", age: "1h" },
];

const PATTERN_HITS = [
  { id: "03 · 05 · 10", note: "3 calls · 4min · I-80 E mp12-15 corridor", risk: 0.82 },
  { id: "02 · 07", note: "elevated-HR pair · <1mi · unrelated intake", risk: 0.31 },
];

function V5Inner() {
  const agentId = process.env.NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID;

  const [phase, setPhase] = useState<
    "idle" | "connecting" | "live" | "ending" | "ended" | "error"
  >("idle");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState("00:00");
  const turnSeq = useRef(0);

  // Tickers for aliveness
  const [clock, setClock] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setClock((c) => c + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Synthetic callback countdown for focused call (resets to 180s)
  const cbRemaining = 180 - (clock % 180);
  const cbMin = String(Math.floor(cbRemaining / 60)).padStart(2, "0");
  const cbSec = String(cbRemaining % 60).padStart(2, "0");

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

  // Pre-request mic permission
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
        ? "end · release lane 05"
        : phase === "ending"
          ? "ending…"
          : "take over · lane 05";

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
              : "auto";

  // Sparkline points derived from clock tick so they re-render subtly
  const sparkPts = useMemo(() => {
    const n = 32;
    const base = clock % 60;
    return Array.from({ length: n }).map((_, i) => {
      const v =
        0.5 +
        0.35 * Math.sin((i + base) * 0.45) +
        0.15 * Math.sin((i + base) * 1.1);
      return Math.max(0.05, Math.min(0.95, v));
    });
  }, [clock]);

  const focused = LANES.find((l) => l.focus) ?? LANES[4];
  const liveCount = LANES.filter((l) => l.live).length;
  const autoCount = LANES.length - liveCount;

  return (
    <main className="v5-shell">
      {/* TOP BAR */}
      <header className="v5-topbar">
        <div className="v5-brand">
          <span className="v5-brand-mark">B300</span>
          <span className="v5-brand-slash">/</span>
          <span className="v5-brand-name">voice.console</span>
          <span className="v5-brand-slash">/</span>
          <span className="v5-brand-env">v5 · psap 2031</span>
          <span className="v5-brand-site">reno · washoe psap-07</span>
        </div>
        <div className="v5-topbar-meta">
          <span className="v5-chip">K.ORTIZ · shift 04:12</span>
          <span className="v5-chip v5-chip-live">
            <span className="v5-dot v5-dot-live" /> {liveCount} live
          </span>
          <span className="v5-chip">{autoCount} auto</span>
          <span className="v5-chip v5-chip-muted">
            p50 <b>187ms</b> · p99 <b>412ms</b>
          </span>
          <span className={`v5-chip v5-chip-${chipLabel}`}>
            lane 05 · {chipLabel}
            {live ? ` · ${elapsed}` : ""}
          </span>
        </div>
      </header>

      {/* CONCEPT BANNER */}
      <div className="v5-banner">
        <span className="v5-banner-tag">this is a concept</span>
        <span>
          lane 05 voice channel is live (elevenlabs + claude opus 4.7). the 11
          surrounding lanes, predictive triage, pattern detection, cross-psap
          feed, and evidence chain are high-fidelity mocks of the 2031 supervisor
          workflow. synthetic data, no live caller PII.
        </span>
      </div>

      {/* CROSS-CALL PATTERN ALERT — sticky at top */}
      <div className="v5-mci">
        <div className="v5-mci-left">
          <span className="v5-mci-pulse" />
          <span className="v5-mci-title">mci · pattern detected</span>
          <span className="v5-mci-sub">
            3 calls in 4 min on I-80 E mp12-15 · prob 0.82 · pre-staging BC-2
          </span>
        </div>
        <div className="v5-mci-actions">
          <button className="v5-mci-btn">escalate to ic</button>
          <button className="v5-mci-btn v5-mci-btn-ghost">dismiss</button>
        </div>
      </div>

      {/* MAIN GRID · 3 cols */}
      <div className="v5-grid">
        {/* LEFT · 12-call lanes */}
        <section className="v5-col v5-col-left">
          <div className="v5-panel-hd">
            <span>12 lanes · one supervisor</span>
            <span className="v5-panel-hd-right">
              consistency 94.1% · intervention 6.2%
            </span>
          </div>
          <div className="v5-lanes">
            {LANES.map((c) => (
              <LaneTile key={c.id} c={c} clock={clock} />
            ))}
          </div>

          {/* Pattern hits list */}
          <div className="v5-panel v5-panel-pattern">
            <div className="v5-panel-hd">
              <span>cross-call pattern hits</span>
              <span className="v5-panel-hd-right">4min window</span>
            </div>
            <div className="v5-pattern-body">
              {PATTERN_HITS.map((p) => (
                <div key={p.id} className="v5-pattern-row">
                  <span className="v5-pattern-ids">#{p.id}</span>
                  <span className="v5-pattern-note">{p.note}</span>
                  <span
                    className={`v5-pattern-risk ${
                      p.risk > 0.7 ? "v5-pattern-risk-hot" : ""
                    }`}
                  >
                    {(p.risk * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CENTER · Focused call · LIVE voice */}
        <section className="v5-col v5-col-center">
          {/* Focused header */}
          <div className="v5-panel v5-panel-focus">
            <div className="v5-focus-hd">
              <div>
                <div className="v5-focus-title">
                  lane #{focused.id} · {focused.kind}
                </div>
                <div className="v5-focus-meta">
                  I-80 E mp 14.2 · 39.5296,−119.8138 · ±3m · female, 34 ·{" "}
                  <span className="v5-focus-lang">EN</span>
                </div>
              </div>
              <div className="v5-focus-right">
                <span className="v5-chip v5-chip-live">P1 · MVC</span>
                <div className="v5-focus-turn">
                  turn 7 · elapsed {Math.floor(focused.dur / 60)}:
                  {String(focused.dur % 60).padStart(2, "0")}
                </div>
              </div>
            </div>

            {/* Pulsing dual soundbar */}
            <div
              className={`v5-soundbar ${live ? "v5-soundbar-live" : ""}`}
              aria-hidden
            >
              {Array.from({ length: 56 }).map((_, i) => (
                <span
                  key={i}
                  className="v5-sb-tick"
                  style={{ animationDelay: `${i * 28}ms` }}
                />
              ))}
            </div>

            {/* Predictive triage strip */}
            <div className="v5-predict">
              <div className="v5-predict-row">
                <span className="v5-predict-label">predict</span>
                <span className="v5-predict-text">
                  {focused.predict?.label ?? "stable · monitor"}
                </span>
                <span className="v5-predict-conf">
                  conf {((focused.predict?.conf ?? 0.5) * 100).toFixed(0)}%
                </span>
              </div>
              <div className="v5-predict-bar">
                <div
                  className="v5-predict-fill"
                  style={{
                    width: `${(focused.predict?.conf ?? 0.5) * 100}%`,
                  }}
                />
              </div>
              <div className="v5-predict-rec">
                recommended: pre-arrival spinal immobilization script · prep
                hazmat · vision link pending supervisor commit
              </div>
            </div>

            {/* Phase strip */}
            <div className="v5-phases">
              {["intake", "triage", "dispatch", "pdi", "handoff", "closed"].map(
                (p) => {
                  const order = [
                    "intake",
                    "triage",
                    "dispatch",
                    "pdi",
                    "handoff",
                    "closed",
                  ];
                  const curIdx = order.indexOf(focused.phase);
                  const thisIdx = order.indexOf(p);
                  return (
                    <span
                      key={p}
                      className={`v5-phase ${
                        thisIdx === curIdx
                          ? "v5-phase-cur"
                          : thisIdx < curIdx
                            ? "v5-phase-done"
                            : ""
                      }`}
                    >
                      {p}
                    </span>
                  );
                },
              )}
            </div>
          </div>

          {/* Live transcript · streaming */}
          <div className="v5-panel v5-panel-transcript" aria-live="polite">
            <div className="v5-panel-hd">
              <span>transcript · streaming · live voice</span>
              <span className="v5-panel-hd-right">
                {turns.length} turn{turns.length === 1 ? "" : "s"} · utterance
                conf 0.94
              </span>
            </div>
            <div className="v5-tx-body">
              {turns.length === 0 ? (
                <div className="v5-empty">
                  waiting for caller audio. press <kbd>take over · lane 05</kbd>{" "}
                  to connect the live elevenlabs channel.
                </div>
              ) : (
                <ol className="v5-turns">
                  {turns.map((t) => (
                    <li key={t.id} className={`v5-turn v5-turn-${t.role}`}>
                      <span className="v5-turn-role">
                        {t.role === "user" ? "caller" : "dispatcher·ai"}
                      </span>
                      <span className="v5-turn-text">{t.text}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>

          {/* Control row */}
          <div className="v5-ctrl">
            <button
              type="button"
              className={`v5-btn v5-btn-primary ${live ? "v5-btn-live" : ""}`}
              onClick={live ? endCall : startCall}
              disabled={phase === "connecting" || phase === "ending" || !agentId}
            >
              {buttonLabel}
            </button>
            <button className="v5-btn v5-btn-ghost" disabled>
              whisper · ⌥W
            </button>
            <button className="v5-btn v5-btn-ghost" disabled>
              flag for qa · ⌥F
            </button>
            <button className="v5-btn v5-btn-ghost" disabled>
              commit cad · ⌥⏎
            </button>
            {!agentId && (
              <span className="v5-bad">
                env missing: NEXT_PUBLIC_ELEVENLABS_V2_AGENT_ID
              </span>
            )}
            {errorText && <span className="v5-bad">error: {errorText}</span>}
          </div>

          {/* EVIDENCE CHAIN — court-ready audit */}
          <div className="v5-panel">
            <div className="v5-panel-hd">
              <span>evidence chain · lane #{focused.id}</span>
              <span className="v5-panel-hd-right">
                5 decisions · signed · chain sha · 7c1f…
              </span>
            </div>
            <div className="v5-evidence">
              {EVIDENCE.map((e, i) => (
                <div key={i} className="v5-ev-row">
                  <span className="v5-ev-t">{e.t}</span>
                  <span className="v5-ev-model">{e.model}</span>
                  <span className="v5-ev-hash">{e.prompt_hash}</span>
                  <span className="v5-ev-tool">{e.tool}</span>
                  <span className="v5-ev-verify">{e.verify}</span>
                </div>
              ))}
              <div className="v5-ev-open">
                open full evidence bundle · {EVIDENCE.length} decisions ·
                exportable to court record
              </div>
            </div>
          </div>
        </section>

        {/* RIGHT · Map · Caller multimodal · Callback · Network */}
        <section className="v5-col v5-col-right">
          {/* Map */}
          <div className="v5-panel">
            <div className="v5-panel-hd">
              <span>spatial · reno metro</span>
              <span className="v5-panel-hd-right">
                {liveCount} live · radius 12mi
              </span>
            </div>
            <svg viewBox="0 0 400 200" className="v5-map">
              {Array.from({ length: 20 }).map((_, i) => (
                <line
                  key={"v" + i}
                  x1={i * 20}
                  y1="0"
                  x2={i * 20}
                  y2="200"
                  stroke="#1f1f22"
                  strokeWidth="0.3"
                />
              ))}
              {Array.from({ length: 10 }).map((_, i) => (
                <line
                  key={"h" + i}
                  x1="0"
                  y1={i * 20}
                  x2="400"
                  y2={i * 20}
                  stroke="#1f1f22"
                  strokeWidth="0.3"
                />
              ))}
              <path d="M 0 100 L 400 100" stroke="#2a2a2e" strokeWidth="1.5" />
              <path d="M 0 105 L 400 105" stroke="#2a2a2e" strokeWidth="0.5" />
              <text x="6" y="95" fill="#55555a" fontSize="7">
                I-80 E
              </text>
              <path d="M 180 0 L 180 200" stroke="#2a2a2e" strokeWidth="1" />
              <text x="184" y="12" fill="#55555a" fontSize="7">
                US-395
              </text>

              {/* MCI corridor shade */}
              <rect
                x="200"
                y="80"
                width="140"
                height="40"
                fill="#ff0096"
                opacity="0.08"
              />

              {/* Focused call pulse */}
              <g>
                <circle
                  cx="260"
                  cy="100"
                  r="22"
                  fill="none"
                  stroke="#ff0096"
                  strokeWidth="0.6"
                  opacity={0.4 + 0.3 * Math.sin(clock * 0.7)}
                />
                <circle
                  cx="260"
                  cy="100"
                  r="14"
                  fill="none"
                  stroke="#ff0096"
                  strokeWidth="0.6"
                  opacity={0.6 + 0.3 * Math.sin(clock * 0.7 + 1)}
                />
                <circle cx="260" cy="100" r="5" fill="#ff0096" />
                <text x="270" y="98" fill="#ff0096" fontSize="8">
                  #05 P1
                </text>
                <text x="270" y="108" fill="#8a8a90" fontSize="7">
                  MVC · mp14
                </text>
              </g>
              <g>
                <circle cx="220" cy="95" r="3" fill="#ff0096" />
                <text x="226" y="92" fill="#ff0096" fontSize="7">
                  #03
                </text>
              </g>
              <g>
                <circle cx="300" cy="108" r="3" fill="#ff0096" />
                <text x="306" y="112" fill="#ff0096" fontSize="7">
                  #10
                </text>
              </g>
              <g>
                <circle cx="120" cy="70" r="3" fill="#ffb84d" />
                <text x="126" y="73" fill="#ffb84d" fontSize="8">
                  #07 ES · P2
                </text>
              </g>
              <g>
                <circle cx="90" cy="150" r="3" fill="#8a8a90" />
                <text x="96" y="153" fill="#8a8a90" fontSize="8">
                  #04
                </text>
              </g>
              <g>
                <circle cx="320" cy="40" r="3" fill="#8a8a90" />
                <text x="326" y="43" fill="#8a8a90" fontSize="8">
                  #12 TTY
                </text>
              </g>

              {/* Unit markers */}
              <g>
                <rect
                  x="245"
                  y="92"
                  width="6"
                  height="6"
                  fill="none"
                  stroke="#4ade80"
                  strokeWidth="1"
                />
                <text x="253" y="98" fill="#4ade80" fontSize="7">
                  M12 · eta 4:12
                </text>
              </g>
              <g>
                <rect
                  x="290"
                  y="92"
                  width="6"
                  height="6"
                  fill="none"
                  stroke="#4ade80"
                  strokeWidth="1"
                />
                <text x="298" y="98" fill="#4ade80" fontSize="7">
                  207
                </text>
              </g>
            </svg>
          </div>

          {/* Multimodal caller panel */}
          <div className="v5-panel">
            <div className="v5-panel-hd">
              <span>caller · multimodal · lane 05</span>
              <span className="v5-panel-hd-right">voice + bio + text</span>
            </div>
            <div className="v5-modal">
              <div className="v5-modal-row">
                <span className="v5-modal-key">voice</span>
                <span className="v5-modal-val v5-modal-val-hot">
                  en-US · stress 0.58
                </span>
              </div>
              <div className="v5-modal-row">
                <span className="v5-modal-key">ppg · hr</span>
                <span className="v5-modal-val">
                  112 bpm{" "}
                  <MiniSpark pts={sparkPts} color="#ff0096" width={96} height={18} />
                </span>
              </div>
              <div className="v5-modal-row">
                <span className="v5-modal-key">loc · gps</span>
                <span className="v5-modal-val">
                  39.5296,−119.8138 ±3m · 72mph → 0mph
                </span>
              </div>
              <div className="v5-modal-row">
                <span className="v5-modal-key">text · chat</span>
                <span className="v5-modal-val v5-modal-val-muted">
                  idle · hearing-impaired fallback armed
                </span>
              </div>
              <div className="v5-modal-row">
                <span className="v5-modal-key">vision</span>
                <span className="v5-modal-val v5-modal-val-muted">
                  sms link staged · awaiting supervisor commit
                </span>
              </div>
              <div className="v5-modal-row">
                <span className="v5-modal-key">device</span>
                <span className="v5-modal-val">
                  iPhone 18 Pro · battery 62% · signal 4/5
                </span>
              </div>
            </div>
          </div>

          {/* Callback countdown */}
          <div className="v5-panel v5-panel-callback">
            <div className="v5-panel-hd">
              <span>closed-loop callback · lane 05</span>
              <span className="v5-panel-hd-right">armed</span>
            </div>
            <div className="v5-cb-body">
              <div className="v5-cb-time">
                {cbMin}:{cbSec}
              </div>
              <div className="v5-cb-label">
                auto-callback in · &ldquo;units 90s out — still safe?&rdquo;
              </div>
              <div className="v5-cb-bar">
                <div
                  className="v5-cb-fill"
                  style={{ width: `${((180 - cbRemaining) / 180) * 100}%` }}
                />
              </div>
            </div>
          </div>

          {/* Cross-PSAP network feed */}
          <div className="v5-panel">
            <div className="v5-panel-hd">
              <span>cross-psap network · anonymized</span>
              <span className="v5-panel-hd-right">warrant: req-7c1f</span>
            </div>
            <div className="v5-net">
              {NETWORK_FEED.map((n, i) => (
                <div key={i} className="v5-net-row">
                  <span className="v5-net-psap">{n.psap}</span>
                  <span className="v5-net-match">{n.match}</span>
                  <span className="v5-net-note">{n.note}</span>
                  <span className="v5-net-age">{n.age}</span>
                </div>
              ))}
            </div>
          </div>

          {/* KPI tiles */}
          <div className="v5-kpis">
            <div className="v5-kpi">
              <div className="v5-kpi-k">shift calls</div>
              <div className="v5-kpi-v">132</div>
            </div>
            <div className="v5-kpi">
              <div className="v5-kpi-k">intervention</div>
              <div className="v5-kpi-v v5-kpi-v-amber">6.2%</div>
            </div>
            <div className="v5-kpi">
              <div className="v5-kpi-k">saved</div>
              <div className="v5-kpi-v v5-kpi-v-green">3.8m</div>
            </div>
            <div className="v5-kpi">
              <div className="v5-kpi-k">qa flag</div>
              <div className="v5-kpi-v v5-kpi-v-hot">2</div>
            </div>
          </div>
        </section>
      </div>

      {/* FOOTER */}
      <footer className="v5-footer">
        <div>
          psap 2031 · speculative surface · live lane 05 · elevenlabs + claude
          opus 4.7
        </div>
        <div>
          <a href="/prism42">/prism42</a> ·{" "}
          <a href="/prism42-v2">/prism42-v2</a> ·{" "}
          <a href="/prism42-v3">/prism42-v3</a> ·{" "}
          <a href="/prism42-v4">/prism42-v4</a>
        </div>
      </footer>

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
          --text-4: #3a3a3e;
          --hot: #ff0096;
          --hot-bg: rgba(255, 0, 150, 0.08);
          --hot-border: rgba(255, 0, 150, 0.35);
          --amber: #ffb84d;
          --amber-bg: rgba(255, 184, 77, 0.1);
          --green: #4ade80;
          --green-bg: rgba(74, 222, 128, 0.08);
          --blue: #60a5fa;
          --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
          --sans: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif;
        }
        html,
        body {
          background: var(--bg-outer);
          color: var(--text);
          font-family: var(--mono);
          font-size: 12px;
          line-height: 1.45;
          letter-spacing: 0.005em;
        }
        body > div > div.simulation-banner {
          display: none !important;
        }
      `}</style>

      <style jsx>{`
        .v5-shell {
          max-width: 1800px;
          margin: 0 auto;
          padding: 14px 18px 24px 18px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          font-family: var(--mono);
          color: var(--text);
        }

        /* topbar */
        .v5-topbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          padding: 9px 14px;
          background: var(--panel);
          border: 1px solid var(--border);
          border-radius: 3px;
        }
        .v5-brand {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 11px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .v5-brand-mark {
          color: var(--hot);
          font-weight: 600;
          letter-spacing: 0.12em;
        }
        .v5-brand-slash {
          color: var(--text-3);
        }
        .v5-brand-env {
          color: var(--hot);
          background: var(--hot-bg);
          padding: 2px 8px;
          border-radius: 2px;
          border: 1px solid var(--hot-border);
          font-size: 9px;
          letter-spacing: 0.14em;
        }
        .v5-brand-site {
          color: var(--text-3);
          font-size: 10px;
          letter-spacing: 0.08em;
          margin-left: 6px;
        }
        .v5-topbar-meta {
          display: flex;
          gap: 6px;
          align-items: center;
          flex-wrap: wrap;
        }
        .v5-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 3px 9px;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          border: 1px solid var(--border-2);
          border-radius: 2px;
          color: var(--text-2);
          background: var(--panel-2);
          white-space: nowrap;
        }
        .v5-chip b {
          color: var(--green);
          font-weight: 500;
        }
        .v5-chip-muted {
          color: var(--text-3);
        }
        .v5-chip-live {
          color: var(--hot);
          border-color: var(--hot-border);
          background: var(--hot-bg);
        }
        .v5-chip-auto {
          color: var(--text-2);
        }
        .v5-chip-connecting {
          color: var(--amber);
          border-color: rgba(255, 184, 77, 0.4);
        }
        .v5-chip-error {
          color: #ff6b6b;
          border-color: rgba(255, 107, 107, 0.4);
        }
        .v5-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--text-3);
        }
        .v5-dot-live {
          background: var(--hot);
          box-shadow: 0 0 8px var(--hot);
          animation: v5-pulse-hot 1.2s ease-in-out infinite;
        }
        @keyframes v5-pulse-hot {
          0%,
          100% {
            opacity: 1;
          }
          50% {
            opacity: 0.4;
          }
        }

        /* concept banner */
        .v5-banner {
          display: flex;
          gap: 10px;
          align-items: baseline;
          padding: 8px 14px;
          border: 1px dashed var(--hot-border);
          background: var(--hot-bg);
          color: var(--text-2);
          border-radius: 3px;
          font-size: 10px;
          letter-spacing: 0.02em;
        }
        .v5-banner-tag {
          color: var(--hot);
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.14em;
          font-size: 10px;
          flex-shrink: 0;
        }

        /* MCI banner — sticky */
        .v5-mci {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          padding: 10px 14px;
          background: linear-gradient(
            90deg,
            rgba(255, 0, 150, 0.14) 0%,
            rgba(255, 0, 150, 0.04) 100%
          );
          border: 1px solid var(--hot);
          border-radius: 3px;
          position: relative;
          overflow: hidden;
        }
        .v5-mci::before {
          content: "";
          position: absolute;
          left: 0;
          top: 0;
          bottom: 0;
          width: 3px;
          background: var(--hot);
          box-shadow: 0 0 18px var(--hot);
        }
        .v5-mci-left {
          display: flex;
          gap: 12px;
          align-items: center;
          padding-left: 10px;
        }
        .v5-mci-pulse {
          width: 10px;
          height: 10px;
          background: var(--hot);
          border-radius: 50%;
          animation: v5-pulse-hot 0.8s ease-in-out infinite;
          box-shadow: 0 0 14px var(--hot);
        }
        .v5-mci-title {
          color: var(--hot);
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .v5-mci-sub {
          color: var(--text);
          font-size: 11px;
          letter-spacing: 0.02em;
        }
        .v5-mci-actions {
          display: flex;
          gap: 6px;
        }
        .v5-mci-btn {
          font-family: var(--mono);
          font-size: 10px;
          padding: 6px 12px;
          background: var(--hot);
          color: var(--bg-outer);
          border: none;
          border-radius: 2px;
          cursor: pointer;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          font-weight: 600;
        }
        .v5-mci-btn-ghost {
          background: transparent;
          color: var(--text-2);
          border: 1px solid var(--border-2);
          font-weight: 400;
        }

        /* main grid */
        .v5-grid {
          display: grid;
          grid-template-columns: 1.1fr 1.5fr 1fr;
          gap: 10px;
          align-items: stretch;
        }
        @media (max-width: 1280px) {
          .v5-grid {
            grid-template-columns: 1fr 1.3fr;
          }
          .v5-col-right {
            grid-column: 1 / -1;
            display: grid !important;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
          }
        }
        @media (max-width: 900px) {
          .v5-grid {
            grid-template-columns: 1fr;
          }
          .v5-col-right {
            grid-template-columns: 1fr;
          }
        }

        .v5-col {
          display: flex;
          flex-direction: column;
          gap: 10px;
          min-height: 0;
        }

        /* panels */
        .v5-panel {
          background: var(--panel);
          border: 1px solid var(--border);
          border-radius: 3px;
          overflow: hidden;
        }
        .v5-panel-hd {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 14px;
          border-bottom: 1px solid var(--border);
          font-size: 9px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--text-2);
          background: var(--panel-2);
          flex-shrink: 0;
        }
        .v5-panel-hd-right {
          color: var(--text-3);
          font-size: 9px;
        }

        /* LANES */
        .v5-lanes {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 6px;
          padding: 8px;
          background: var(--panel);
          border: 1px solid var(--border);
          border-top: none;
          border-radius: 0 0 3px 3px;
          margin-top: -11px;
        }

        .v5-panel-pattern {
          margin-top: 2px;
        }
        .v5-pattern-body {
          padding: 6px 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .v5-pattern-row {
          display: grid;
          grid-template-columns: 88px 1fr 44px;
          gap: 8px;
          align-items: center;
          padding: 4px 0;
          border-bottom: 1px dashed var(--border);
          font-size: 10px;
        }
        .v5-pattern-row:last-child {
          border-bottom: none;
        }
        .v5-pattern-ids {
          color: var(--text-3);
          letter-spacing: 0.06em;
        }
        .v5-pattern-note {
          color: var(--text-2);
        }
        .v5-pattern-risk {
          text-align: right;
          color: var(--text-3);
          font-variant-numeric: tabular-nums;
        }
        .v5-pattern-risk-hot {
          color: var(--hot);
          font-weight: 600;
        }

        /* Focused panel */
        .v5-panel-focus {
          padding: 14px 16px 10px 16px;
        }
        .v5-focus-hd {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 10px;
        }
        .v5-focus-title {
          font-family: var(--sans);
          font-size: 16px;
          font-weight: 500;
          color: var(--text);
          letter-spacing: -0.005em;
        }
        .v5-focus-meta {
          font-size: 10px;
          color: var(--text-2);
          margin-top: 3px;
          letter-spacing: 0.02em;
        }
        .v5-focus-lang {
          color: var(--green);
          letter-spacing: 0.08em;
        }
        .v5-focus-right {
          text-align: right;
        }
        .v5-focus-turn {
          font-size: 9px;
          color: var(--text-3);
          margin-top: 4px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .v5-soundbar {
          display: flex;
          align-items: center;
          gap: 2px;
          margin: 10px 0;
          height: 28px;
        }
        .v5-sb-tick {
          flex: 1;
          height: 3px;
          background: var(--border-2);
          border-radius: 1px;
          transition: all 0.15s ease;
        }
        .v5-soundbar-live .v5-sb-tick {
          background: var(--hot);
          animation: v5-bar 1.1s ease-in-out infinite;
        }
        @keyframes v5-bar {
          0%,
          100% {
            height: 3px;
            opacity: 0.5;
          }
          25% {
            height: 16px;
            opacity: 1;
          }
          50% {
            height: 5px;
            opacity: 0.7;
          }
          75% {
            height: 11px;
            opacity: 0.9;
          }
        }

        /* Predictive triage */
        .v5-predict {
          border: 1px solid var(--hot-border);
          background: var(--hot-bg);
          padding: 8px 10px;
          border-radius: 2px;
          display: flex;
          flex-direction: column;
          gap: 5px;
          margin-top: 6px;
        }
        .v5-predict-row {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          gap: 10px;
        }
        .v5-predict-label {
          color: var(--hot);
          font-size: 9px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          font-weight: 600;
        }
        .v5-predict-text {
          color: var(--text);
          font-size: 11px;
          flex: 1;
        }
        .v5-predict-conf {
          color: var(--hot);
          font-size: 10px;
          font-variant-numeric: tabular-nums;
        }
        .v5-predict-bar {
          height: 3px;
          background: rgba(255, 0, 150, 0.15);
          border-radius: 1px;
          overflow: hidden;
        }
        .v5-predict-fill {
          height: 100%;
          background: var(--hot);
          transition: width 0.4s ease;
          box-shadow: 0 0 8px var(--hot);
        }
        .v5-predict-rec {
          font-size: 10px;
          color: var(--text-2);
          letter-spacing: 0.02em;
          line-height: 1.45;
        }

        /* phase strip */
        .v5-phases {
          display: flex;
          gap: 3px;
          margin-top: 10px;
        }
        .v5-phase {
          font-size: 9px;
          padding: 2px 7px;
          color: var(--text-4);
          text-transform: uppercase;
          letter-spacing: 0.12em;
          border: 1px solid var(--border);
          border-radius: 2px;
        }
        .v5-phase-done {
          color: var(--text-3);
        }
        .v5-phase-cur {
          color: var(--hot);
          border-color: var(--hot-border);
          background: var(--hot-bg);
        }

        /* transcript */
        .v5-panel-transcript {
          display: flex;
          flex-direction: column;
          min-height: 180px;
        }
        .v5-tx-body {
          flex: 1;
          padding: 10px 14px;
          overflow-y: auto;
          max-height: 260px;
          min-height: 140px;
        }
        .v5-empty {
          color: var(--text-3);
          font-style: italic;
          font-size: 10px;
          letter-spacing: 0.02em;
        }
        .v5-empty kbd {
          font-family: var(--mono);
          padding: 1px 5px;
          border: 1px solid var(--border-2);
          border-radius: 2px;
          background: var(--panel-2);
          color: var(--text-2);
          font-size: 9px;
          letter-spacing: 0.08em;
        }
        .v5-turns {
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .v5-turn {
          display: grid;
          grid-template-columns: 96px 1fr;
          gap: 10px;
          align-items: baseline;
          padding: 5px 0;
          border-bottom: 1px dashed var(--border);
        }
        .v5-turn-role {
          font-size: 9px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: var(--text-3);
        }
        .v5-turn-user .v5-turn-role {
          color: var(--text);
        }
        .v5-turn-agent .v5-turn-role {
          color: var(--hot);
        }
        .v5-turn-text {
          font-family: var(--sans);
          font-size: 12px;
          line-height: 1.5;
          color: var(--text);
        }
        .v5-turn-agent .v5-turn-text {
          border-left: 2px solid var(--hot);
          padding-left: 10px;
          margin-left: -12px;
        }

        /* ctrl row */
        .v5-ctrl {
          display: flex;
          gap: 6px;
          align-items: center;
          flex-wrap: wrap;
        }
        .v5-btn {
          font-family: var(--mono);
          font-size: 10px;
          font-weight: 500;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          padding: 9px 14px;
          border-radius: 2px;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .v5-btn-primary {
          border: 1px solid var(--hot);
          background: var(--hot);
          color: var(--bg-outer);
          font-weight: 600;
        }
        .v5-btn-primary:hover:not(:disabled) {
          background: #ff33aa;
          box-shadow: 0 0 18px rgba(255, 0, 150, 0.35);
        }
        .v5-btn-live {
          background: var(--hot-bg);
          color: var(--hot);
          border: 1px solid var(--hot-border);
        }
        .v5-btn-ghost {
          background: transparent;
          color: var(--text-2);
          border: 1px solid var(--border-2);
        }
        .v5-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .v5-bad {
          color: #ff6b6b;
          font-size: 10px;
          letter-spacing: 0.02em;
        }

        /* evidence chain */
        .v5-evidence {
          padding: 8px 14px;
          font-size: 10px;
        }
        .v5-ev-row {
          display: grid;
          grid-template-columns: 48px 120px 64px 1fr 160px;
          gap: 8px;
          padding: 5px 0;
          border-bottom: 1px dashed var(--border);
          align-items: baseline;
        }
        .v5-ev-t {
          color: var(--text-4);
          font-variant-numeric: tabular-nums;
        }
        .v5-ev-model {
          color: var(--hot);
        }
        .v5-ev-hash {
          color: var(--text-3);
        }
        .v5-ev-tool {
          color: var(--text);
        }
        .v5-ev-verify {
          color: var(--green);
          text-align: right;
          font-size: 9px;
          letter-spacing: 0.04em;
        }
        .v5-ev-open {
          margin-top: 8px;
          padding: 6px 8px;
          background: var(--panel-2);
          border-radius: 2px;
          color: var(--text-2);
          font-size: 10px;
          letter-spacing: 0.02em;
          cursor: pointer;
          text-align: center;
        }
        .v5-ev-open:hover {
          color: var(--hot);
        }

        /* map */
        .v5-map {
          width: 100%;
          display: block;
          aspect-ratio: 2 / 1;
        }

        /* modal */
        .v5-modal {
          padding: 8px 14px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-size: 10px;
        }
        .v5-modal-row {
          display: grid;
          grid-template-columns: 78px 1fr;
          gap: 10px;
          padding: 4px 0;
          border-bottom: 1px dashed var(--border);
          align-items: center;
        }
        .v5-modal-row:last-child {
          border-bottom: none;
        }
        .v5-modal-key {
          color: var(--text-3);
          letter-spacing: 0.1em;
          text-transform: uppercase;
          font-size: 9px;
        }
        .v5-modal-val {
          color: var(--text);
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .v5-modal-val-hot {
          color: var(--hot);
        }
        .v5-modal-val-muted {
          color: var(--text-3);
        }

        /* callback */
        .v5-panel-callback {
          background: linear-gradient(
            135deg,
            var(--panel) 0%,
            rgba(255, 0, 150, 0.04) 100%
          );
        }
        .v5-cb-body {
          padding: 10px 14px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .v5-cb-time {
          font-family: var(--mono);
          font-size: 24px;
          font-weight: 300;
          color: var(--hot);
          letter-spacing: 0.06em;
          font-variant-numeric: tabular-nums;
          text-shadow: 0 0 16px rgba(255, 0, 150, 0.4);
        }
        .v5-cb-label {
          font-size: 10px;
          color: var(--text-2);
          letter-spacing: 0.02em;
        }
        .v5-cb-bar {
          height: 2px;
          background: var(--border);
          overflow: hidden;
          border-radius: 1px;
        }
        .v5-cb-fill {
          height: 100%;
          background: var(--hot);
          transition: width 1s linear;
        }

        /* network feed */
        .v5-net {
          padding: 4px 14px;
          font-size: 10px;
          display: flex;
          flex-direction: column;
        }
        .v5-net-row {
          display: grid;
          grid-template-columns: 72px 110px 1fr 36px;
          gap: 8px;
          padding: 5px 0;
          border-bottom: 1px dashed var(--border);
          align-items: baseline;
        }
        .v5-net-row:last-child {
          border-bottom: none;
        }
        .v5-net-psap {
          color: var(--hot);
          letter-spacing: 0.06em;
          font-size: 10px;
        }
        .v5-net-match {
          color: var(--text);
        }
        .v5-net-note {
          color: var(--text-3);
        }
        .v5-net-age {
          color: var(--text-4);
          text-align: right;
        }

        /* KPIs */
        .v5-kpis {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 4px;
        }
        .v5-kpi {
          background: var(--panel);
          border: 1px solid var(--border);
          border-radius: 3px;
          padding: 8px 10px;
        }
        .v5-kpi-k {
          font-size: 9px;
          color: var(--text-3);
          letter-spacing: 0.1em;
          text-transform: uppercase;
        }
        .v5-kpi-v {
          font-size: 16px;
          font-weight: 500;
          margin-top: 2px;
          font-variant-numeric: tabular-nums;
        }
        .v5-kpi-v-amber {
          color: var(--amber);
        }
        .v5-kpi-v-green {
          color: var(--green);
        }
        .v5-kpi-v-hot {
          color: var(--hot);
        }

        /* footer */
        .v5-footer {
          display: flex;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 14px;
          padding: 9px 14px;
          border: 1px solid var(--border);
          border-radius: 3px;
          background: var(--panel);
          font-size: 9px;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          color: var(--text-3);
        }
        .v5-footer a {
          color: var(--hot);
          text-decoration: none;
        }
        .v5-footer a:hover {
          text-decoration: underline;
        }
      `}</style>
    </main>
  );
}

// ——————————————————————————————————————————————————
// Small components
// ——————————————————————————————————————————————————

function LaneTile({ c, clock }: { c: Lane; clock: number }) {
  // Per-tile soundbar — 12 ticks, animate only if live.
  const ticks = 12;
  const seed = c.seed;
  const focused = !!c.focus;
  return (
    <div className={`v5-tile ${focused ? "v5-tile-focus" : ""} ${c.live ? "v5-tile-live" : ""}`}>
      <div className="v5-tile-hd">
        <span
          className={`v5-dot ${c.live ? "v5-dot-live" : ""}`}
          aria-hidden
        />
        <span className="v5-tile-id">#{c.id}</span>
        <span
          className={`v5-tile-pri v5-tile-pri-${c.priority}`}
        >
          {c.priority}
        </span>
        {c.lang && c.lang !== "EN" && (
          <span className="v5-tile-lang">{c.lang}</span>
        )}
      </div>
      <div className="v5-tile-bars">
        {Array.from({ length: ticks }).map((_, i) => {
          const phase = (clock + seed + i) % 7;
          const h = c.live ? 3 + ((phase * 2) % 10) : 2;
          return (
            <span
              key={i}
              className="v5-tile-bar"
              style={{ height: `${h}px` }}
            />
          );
        })}
      </div>
      <div className="v5-tile-kind">{c.kind}</div>
      <div className="v5-tile-loc">{c.loc}</div>
      {c.predict && (
        <div className="v5-tile-predict">
          <span className="v5-tile-predict-dot" />
          {c.predict.label}
        </div>
      )}

      <style jsx>{`
        .v5-tile {
          border: 1px solid var(--border);
          background: var(--panel);
          padding: 7px 9px;
          display: grid;
          gap: 5px;
          border-radius: 2px;
          min-height: 90px;
        }
        .v5-tile-live {
          border-color: var(--border-2);
        }
        .v5-tile-focus {
          border-color: var(--hot);
          background: var(--hot-bg);
          box-shadow: 0 0 0 1px rgba(255, 0, 150, 0.2),
            inset 0 0 24px rgba(255, 0, 150, 0.04);
        }
        .v5-tile-hd {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 10px;
        }
        .v5-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--text-4);
          flex-shrink: 0;
        }
        .v5-dot-live {
          background: var(--hot);
          box-shadow: 0 0 8px var(--hot);
          animation: v5-pulse-hot 1.2s ease-in-out infinite;
        }
        @keyframes v5-pulse-hot {
          0%,
          100% {
            opacity: 1;
          }
          50% {
            opacity: 0.4;
          }
        }
        .v5-tile-id {
          font-weight: 500;
          color: var(--text);
          font-size: 10px;
        }
        .v5-tile-pri {
          margin-left: auto;
          font-size: 9px;
          color: var(--text-3);
          letter-spacing: 0.06em;
        }
        .v5-tile-pri-P1 {
          color: var(--hot);
          font-weight: 600;
        }
        .v5-tile-pri-P2 {
          color: var(--amber);
        }
        .v5-tile-lang {
          font-size: 9px;
          padding: 1px 5px;
          border: 1px solid var(--border-2);
          color: var(--blue);
          border-radius: 2px;
          letter-spacing: 0.08em;
        }
        .v5-tile-bars {
          display: flex;
          align-items: flex-end;
          gap: 1px;
          height: 14px;
        }
        .v5-tile-bar {
          flex: 1;
          background: var(--text-4);
          transition: height 0.3s ease;
          border-radius: 1px;
        }
        .v5-tile-live .v5-tile-bar {
          background: var(--hot);
          opacity: 0.85;
        }
        .v5-tile-kind {
          font-size: 10px;
          color: var(--text);
          line-height: 1.25;
        }
        .v5-tile-loc {
          font-size: 9px;
          color: var(--text-3);
        }
        .v5-tile-predict {
          display: flex;
          gap: 5px;
          align-items: center;
          font-size: 9px;
          color: var(--amber);
          letter-spacing: 0.02em;
        }
        .v5-tile-predict-dot {
          width: 4px;
          height: 4px;
          background: var(--amber);
          border-radius: 50%;
          flex-shrink: 0;
        }
      `}</style>
    </div>
  );
}

function MiniSpark({
  pts,
  color,
  width,
  height,
}: {
  pts: number[];
  color: string;
  width: number;
  height: number;
}) {
  if (pts.length === 0) return null;
  const step = width / (pts.length - 1);
  const d = pts
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(height - v * height).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
    >
      <path d={d} fill="none" stroke={color} strokeWidth="1" />
    </svg>
  );
}

export default function PrismV5Page() {
  return (
    <ConversationProvider>
      <V5Inner />
    </ConversationProvider>
  );
}
