"use client";

// /prism42/livekit — Phase 3a route, B300 Voice Console design.
//
// Runs ALONGSIDE /prism42 (ElevenLabs path, stays until 3c cutover).
// Same dispatcher data (transcript / rubric / alerts / phase via SSE),
// same <LiveCallRoom sessionId /> voice wiring — only the visual
// register differs. The surrounding "12 concurrent calls / map / tool
// feed / fleet metrics" chrome is STATIC MOCK for demo framing.
//
// Live-wired: focused-call voice (LiveCallRoom), transcript turns,
// phase timeline, rubric grades, oversight alerts, session id, header
// status.
//
// Static mock: left-rail call grid (12 tiles), right-rail pipeline
// latency strip, right-rail tool-call feed, right-rail fleet metrics,
// spatial map, top-bar shift + p50/p99 readouts.

import "@livekit/components-styles";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LiveCallRoom, type LatencyTelemetry } from "@/components/LiveCallRoom";
import {
  DualSoundbar,
  Elapsed,
  LatencyMeter,
  Soundbar,
  Sparkline,
} from "@/components/b300/Primitives";
import type {
  PsapAlert,
  PsapPhase,
  PsapTurn,
  RubricGrade,
  SessionEvent,
} from "@/lib/types";

// ─────────────────────────────────────────────────────────────────────────
// STATIC MOCK DATA — surrounding call grid, tool feed, metrics.
// Sourced from /tmp/b300_design/named/02-V1CommandCenter.jsx verbatim so
// the visual shape matches the extraction reference.
// ─────────────────────────────────────────────────────────────────────────

type MockCall = {
  id: string;
  phase: PsapPhase["name"];
  kind: string;
  loc: string;
  live: boolean;
  priority: "P1" | "P2" | "P3" | "P4" | "P5";
  dur: number;
  seed: number;
  focus?: boolean;
};

const MOCK_CALLS: MockCall[] = [
  { id: "01", phase: "intake",   kind: "noise complaint",   loc: "2nd & Virginia",  live: false, priority: "P4", dur: 142, seed: 1 },
  { id: "02", phase: "closed",   kind: "lost wallet",       loc: "report only",     live: false, priority: "P5", dur: 88,  seed: 2 },
  { id: "03", phase: "dispatch", kind: "parking",           loc: "awaiting tow",    live: false, priority: "P4", dur: 215, seed: 3 },
  { id: "04", phase: "intake",   kind: "welfare check",     loc: "S. Wells Ave",    live: true,  priority: "P3", dur: 34,  seed: 4 },
  { id: "05", phase: "pdi",      kind: "MVC · injury",      loc: "I-80 E · mp14",   live: true,  priority: "P1", dur: 134, seed: 5, focus: true },
  { id: "06", phase: "closed",   kind: "barking dog",       loc: "routine",         live: false, priority: "P5", dur: 67,  seed: 6 },
  { id: "07", phase: "triage",   kind: "lang swap ES->EN",  loc: "hold",            live: true,  priority: "P3", dur: 12,  seed: 7 },
  { id: "08", phase: "closed",   kind: "false alarm",       loc: "resolved",        live: false, priority: "P5", dur: 55,  seed: 8 },
  { id: "09", phase: "handoff",  kind: "fireworks",         loc: "Virginia St",     live: false, priority: "P4", dur: 98,  seed: 9 },
  { id: "10", phase: "dispatch", kind: "medical · stable",  loc: "EMS enroute",     live: true,  priority: "P2", dur: 78,  seed: 10 },
  { id: "11", phase: "closed",   kind: "abandoned veh",     loc: "report filed",    live: false, priority: "P5", dur: 42,  seed: 11 },
  { id: "12", phase: "intake",   kind: "callback",          loc: "queued",          live: true,  priority: "P4", dur: 6,   seed: 12 },
];

const MOCK_TOOLS = [
  { t: "+00:02", name: "location.resolve",  args: "lat=39.5296, lon=-119.8138", out: "I-80 E mp14.2 ±3m",         ms: 84 },
  { t: "+00:04", name: "cad.dispatch",      args: "EMS, priority=1",            out: "unit M12 · ETA 4:00",       ms: 142 },
  { t: "+00:05", name: "cad.dispatch",      args: "PD, priority=1",             out: "unit 207 · ETA 3:20",       ms: 138 },
  { t: "+00:47", name: "history.scan",      args: "loc=mp14, window=72h",       out: "2 prior incidents",         ms: 62 },
  { t: "+01:12", name: "safety.watchlist",  args: "check=all",                  out: "none triggered",            ms: 28 },
  { t: "+01:38", name: "hazmat.upgrade",    args: "fuel_smell=true",            out: "proposed · awaiting commit", ms: 91, pending: true },
  { t: "+02:01", name: "vision.request",    args: "sms_link=true",              out: "proposed · awaiting commit", ms: 74, pending: true },
  { t: "+02:04", name: "intent.verify",     args: "pushback=t6",                out: "hold recommendation",       ms: 44 },
];

const PHASE_SEQUENCE: PsapPhase["name"][] = [
  "intake",
  "triage",
  "dispatch",
  "pdi",
  "handoff",
  "closed",
];

// ─────────────────────────────────────────────────────────────────────────

type ViewTab = "v1" | "v2" | "v3" | "v4";

export default function LiveKitDispatcherPage() {
  // Live-wired session state (unchanged from previous page.tsx).
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [phase, setPhase] = useState<PsapPhase>({ name: "intake" });
  const [turns, setTurns] = useState<PsapTurn[]>([]);
  const [grades, setGrades] = useState<RubricGrade[]>([]);
  const [alerts, setAlerts] = useState<PsapAlert[]>([]);
  const [sseState, setSseState] = useState<
    "idle" | "starting" | "connected" | "no-transcript" | "degraded"
  >("idle");
  const [roomLive, setRoomLive] = useState(false);
  // Live pipeline-latency telemetry (pushed by worker.py over the
  // `b3-latency` LiveKit data channel; fed through LatencyTap in
  // LiveCallRoom). Null until the first turn completes.
  const [latency, setLatency] = useState<LatencyTelemetry | null>(null);
  // Active tab within the console (V1 Command Center / V2 Soundbar-
  // forward / V3 MCI / V4 Vision). Swapped client-side; LiveCallRoom
  // is mounted once in V1 so the voice session survives tab switches.
  const [view, setView] = useState<ViewTab>("v1");
  const abortRef = useRef<AbortController | null>(null);
  const sessionStartTs = useRef<number>(Date.now());
  // Portal target for the LiveCallRoom — rendered ONCE at page scope
  // then portaled into whichever tab slot is active. Keeps the WebRTC
  // session alive across tab switches so latency telemetry keeps
  // flowing into V2 even if the user started the call on V1.
  const v1VoiceSlotRef = useRef<HTMLDivElement | null>(null);
  const v2VoiceSlotRef = useRef<HTMLDivElement | null>(null);
  const [voiceHost, setVoiceHost] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (view === "v1") setVoiceHost(v1VoiceSlotRef.current);
    else if (view === "v2") setVoiceHost(v2VoiceSlotRef.current);
    else setVoiceHost(null); // V3/V4: hide visually but component stays mounted
  }, [view]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSseState("starting");
      sessionStartTs.current = Date.now();
      try {
        const r = await fetch("/prism42/api/session/start", { method: "POST" });
        if (!r.ok) throw new Error(`start ${r.status}`);
        const body = (await r.json()) as {
          session_id: string;
          phase: PsapPhase;
        };
        if (cancelled) return;
        setSessionId(body.session_id);
        setPhase(body.phase);
        subscribe(body.session_id);
      } catch {
        setSseState("degraded");
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, []);

  function subscribe(id: string) {
    const ac = new AbortController();
    abortRef.current = ac;
    const url = `/prism42/api/session/${encodeURIComponent(id)}/stream`;
    (async () => {
      try {
        const r = await fetch(url, { signal: ac.signal });
        if (!r.ok || !r.body) {
          setSseState(r.status === 404 ? "no-transcript" : "degraded");
          return;
        }
        setSseState("connected");
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            handleFrame(frame);
          }
        }
      } catch (err) {
        if ((err as { name?: string }).name !== "AbortError") {
          setSseState("degraded");
        }
      }
    })();
  }

  function handleFrame(frame: string) {
    const lines = frame.split("\n");
    let event = "message";
    let data = "";
    for (const line of lines) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) data = line.slice(6);
    }
    if (!data) return;
    try {
      const parsed = JSON.parse(data) as SessionEvent;
      if (event === "turn") setTurns((ts) => [...ts, parsed.payload as PsapTurn]);
      else if (event === "grade")
        setGrades((gs) => [...gs, parsed.payload as RubricGrade]);
      else if (event === "alert")
        setAlerts((as) => [...as, parsed.payload as PsapAlert]);
      else if (event === "phase_change") setPhase(parsed.payload as PsapPhase);
      else if (event === "session_closed") setPhase({ name: "closed" });
    } catch {
      /* heartbeat / comment */
    }
  }

  const headerStatus = roomLive ? "connected · live voice" : sseState;
  const latestGrade = grades[grades.length - 1];
  const focusedMock = MOCK_CALLS.find((c) => c.focus)!;

  // Map SSE turns into transcript rows for the center panel. Every
  // PsapTurn in the stream is a dispatcher-side (AI) turn — caller
  // utterances arrive via the LiveKit audio stream, not as SSE turns.
  const liveTurns = useMemo(
    () =>
      turns.slice(-8).map((t) => ({
        text: t.content ?? "(no caller-facing content)",
        agent: t.agent,
        action: t.action,
        verify: t.self_verify.all_passed,
        cites: t.cites,
      })),
    [turns],
  );

  return (
    <div className="b3-console">
      <style>{B3_STYLES}</style>

      {/* TOP BAR */}
      <div className="b3-topbar">
        <div className="b3-topbar-left">
          <div className="b3-brand">
            <span className="b3-brand-hot">B300</span>
            <span className="b3-brand-sep"> / </span>
            <span className="b3-brand-main">voice.console</span>
            <span className="b3-brand-sep"> / reno-psap-07</span>
          </div>
          <span className="b3-chip b3-chip-ghost">
            K. ORTIZ · shift 04:12
          </span>
          <span className="b3-chip b3-chip-hot">
            <span className="b3-dot b3-dot-hot b3-dot-live" />
            {roomLive ? "LIVE VOICE" : headerStatus.toUpperCase()}
          </span>
          <span className="b3-chip b3-chip-ghost">
            session ·{" "}
            {sessionId ? sessionId.slice(0, 8) : "…"}
          </span>
        </div>
        <div className="b3-topbar-right">
          <div className="b3-tabs" role="tablist" aria-label="console view">
            {(
              [
                ["v1", "cmd"],
                ["v2", "pipe"],
                ["v3", "mci"],
                ["v4", "vis"],
              ] as Array<[ViewTab, string]>
            ).map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={view === id}
                className={`b3-tab ${view === id ? "b3-tab-active" : ""}`}
                onClick={() => setView(id)}
              >
                {id.toUpperCase()} · {label}
              </button>
            ))}
          </div>
          <span>
            p50 voice <span className="b3-green">187ms</span>
          </span>
          <span>
            p99 voice <span className="b3-amber">412ms</span>
          </span>
          <span>
            stt <span className="b3-green">parakeet</span>
          </span>
          <span>
            tts <span className="b3-green">fish</span>
          </span>
          <span>
            llm <span className="b3-green">sonnet-4.6</span>
          </span>
        </div>
      </div>

      {/* MAIN GRID — V1 Command Center (always mounted; hidden when
          another view is active to keep LiveCallRoom's portal target
          alive and the data-channel tap ticking). */}
      <div
        className="b3-main"
        style={{ display: view === "v1" ? "grid" : "none" }}
      >
        {/* LEFT: 12-call grid (static mock) */}
        <div className="b3-col b3-col-left">
          <div className="b3-panel-hd b3-panel-hd-framed">
            <span className="b3-hd-t">12 CALLS CONCURRENT</span>
            <span className="b3-hd-s">
              consistency 94.1% · escalation 8.3%
            </span>
          </div>
          <div className="b3-calls-grid">
            {MOCK_CALLS.map((c) => (
              <CallTile key={c.id} c={c} focused={!!c.focus} />
            ))}
          </div>
        </div>

        {/* CENTER: focused call — LIVE wiring */}
        <div className="b3-col b3-col-center">
          <div className="b3-panel b3-focus-hd">
            <div className="b3-focus-hd-row">
              <div>
                <div className="b3-focus-title">
                  call #{focusedMock.id} · live voice session
                </div>
                <div className="b3-focus-sub">
                  session {sessionId ? sessionId.slice(0, 8) : "…"} ·
                  headerStatus {headerStatus} · phase {phase.name}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <span className="b3-chip b3-chip-hot">P1 · DEMO</span>
                <div className="b3-focus-meta">
                  turn {turns.length} · {" "}
                  <Elapsed start={sessionStartTs.current} />
                </div>
              </div>
            </div>
            <DualSoundbar
              bars={80}
              height={22}
              seed={focusedMock.seed}
              callerActive={roomLive}
              aiActive={false}
            />
            <div className="b3-phase-row">
              <PhaseBar current={phase.name} />
            </div>
          </div>

          {/* LIVE VOICE SESSION (LiveKitRoom) */}
          <div className="b3-panel b3-voice-panel">
            <div className="b3-panel-hd">
              <span className="b3-hd-t">LIVE VOICE · CALLER CHANNEL</span>
              <span className="b3-hd-s">
                {roomLive ? "connected · rec" : "pre-connect · idle"}
              </span>
            </div>
            <div className="b3-voice-body" ref={v1VoiceSlotRef}>
              {view !== "v1" && (
                <div className="b3-voice-detached">
                  Voice hero is docked in V1. Return to CMD to interact;
                  the session, latency telemetry, and SSE transcript keep
                  running in the background.
                </div>
              )}
            </div>
          </div>

          {/* TRANSCRIPT — live from SSE, falls back to a status line */}
          <div className="b3-panel b3-transcript-panel">
            <div className="b3-panel-hd">
              <span className="b3-hd-t">TRANSCRIPT · STREAMING</span>
              <span className="b3-hd-s">
                {turns.length} turns · state {sseState}
              </span>
            </div>
            <div className="b3-transcript-body">
              {liveTurns.length === 0 && (
                <div className="b3-transcript-empty">
                  Session initialized. Waiting for the first caller
                  utterance. When the voice call begins, turns will
                  stream in from the SSE session endpoint.
                </div>
              )}
              {liveTurns.map((turn, i) => (
                <div
                  key={i}
                  className="b3-turn-row"
                  style={{
                    background: "rgba(255,255,255,0.02)",
                  }}
                >
                  <span
                    className="b3-turn-bar"
                    style={{ background: "var(--b3-hot)" }}
                  />
                  <span
                    className="b3-turn-tag"
                    style={{ color: "var(--b3-hot)" }}
                  >
                    t{i + 1} · {turn.agent}
                  </span>
                  <div
                    className="b3-turn-text"
                    style={{ color: "var(--b3-text)" }}
                  >
                    <span className="b3-turn-action">
                      {turn.action}:
                    </span>{" "}
                    {turn.text}
                    {!turn.verify && (
                      <span className="b3-turn-verify-fail">
                        · verify FAIL
                      </span>
                    )}
                    {turn.cites.length > 0 && (
                      <span className="b3-turn-cites">
                        {" · "}
                        {turn.cites.slice(0, 2).join(" · ")}
                      </span>
                    )}
                  </div>
                  <span className="b3-turn-lat">
                    {turn.verify ? "ok" : "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Dispatcher action bar (static mock) */}
          <div className="b3-action-row">
            <button className="b3-btn b3-btn-hot" disabled>
              take over ⌥↩
            </button>
            <button className="b3-btn b3-btn-ghost" disabled>
              whisper ⌥W
            </button>
            <button className="b3-btn b3-btn-ghost" disabled>
              flag for QA ⌥F
            </button>
          </div>
        </div>

        {/* RIGHT: pipeline latency (mock) + rubric (live) + alerts (live) + metrics (mock) */}
        <div className="b3-col b3-col-right">
          {/* Pipeline latency strip (ported from V2Soundbar) — static */}
          <div className="b3-panel">
            <div className="b3-panel-hd">
              <span className="b3-hd-t">PIPELINE LATENCY · LIVE</span>
              <span className="b3-hd-s">budget 800ms</span>
            </div>
            <div className="b3-latency-body">
              <LatencyMeter ms={84} budget={250} label="stt · deepgram nova-3" />
              <LatencyMeter ms={142} budget={500} label="llm · claude opus 4.7" />
              <LatencyMeter ms={96} budget={300} label="tts · cartesia sonic" />
              <LatencyMeter ms={52} budget={150} label="tool · cad dispatch" />
              <div className="b3-latency-total">
                <span className="b3-text-3">TOTAL turn-to-response</span>
                <span className="b3-mono-num b3-green">
                  374ms · within budget
                </span>
              </div>
            </div>
          </div>

          {/* Rubric (LIVE) */}
          <div className="b3-panel">
            <div className="b3-panel-hd">
              <span className="b3-hd-t">LIVE RUBRIC</span>
              <span className="b3-hd-s">
                {grades.length} graded · cross-vendor
              </span>
            </div>
            <div className="b3-rubric-body">
              {!latestGrade && (
                <div className="b3-dim">
                  No turns graded yet. GPT-5.5 cross-vendor grader is
                  warming up.
                </div>
              )}
              {latestGrade && (
                <>
                  <RubricRow
                    label="R1 clinical accuracy"
                    score={latestGrade.criteria.R1_clinical_accuracy}
                  />
                  <RubricRow
                    label="R2 scope adherence"
                    score={latestGrade.criteria.R2_scope_adherence}
                  />
                  <RubricRow
                    label="R3 safety preservation"
                    score={latestGrade.criteria.R3_safety_preservation}
                  />
                  <RubricRow
                    label="R4 clarity for caller"
                    score={latestGrade.criteria.R4_clarity_for_caller}
                  />
                  <RubricRow
                    label="R5 protocol adherence"
                    score={latestGrade.criteria.R5_protocol_adherence}
                  />
                  <div className="b3-rubric-weighted">
                    <span>weighted</span>
                    <span className="b3-mono-num">
                      {latestGrade.weighted_score.toFixed(2)}
                    </span>
                  </div>
                  <div className="b3-rubric-meta">
                    grader · {latestGrade.model_used} ·{" "}
                    {latestGrade.latency_ms}ms
                  </div>
                  {latestGrade.self_grade_flag && (
                    <div className="b3-self-grade">
                      SELF-GRADE FLAG · OpenAI chain exhausted; Claude
                      graded Claude; score not load-bearing.
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Alerts (LIVE) */}
          <div className="b3-panel">
            <div className="b3-panel-hd">
              <span className="b3-hd-t">OVERSIGHT ALERTS</span>
              <span className="b3-hd-s">
                {alerts.length} total · safety-monitor + OHCA
              </span>
            </div>
            <div className="b3-alerts-body">
              {alerts.length === 0 && (
                <div className="b3-dim">
                  No alerts. Safety-monitor, OHCA-detector, and
                  intent-verifier watching every turn.
                </div>
              )}
              {alerts
                .slice()
                .reverse()
                .slice(0, 6)
                .map((a, i) => (
                  <div
                    key={i}
                    className={`b3-alert b3-alert-${a.severity}`}
                  >
                    <div className="b3-alert-meta">
                      {a.kind} · {a.severity} · {a.source_agent}
                    </div>
                    <div className="b3-alert-detail">{a.detail}</div>
                  </div>
                ))}
            </div>
          </div>

          {/* Fleet metrics (static mock) */}
          <div className="b3-metrics-row">
            <MetricTile
              label="shift"
              value="132"
              sub="calls"
            />
            <MetricTile
              label="escalated"
              value="11"
              valueColor="var(--b3-amber)"
              sub="8.3%"
            />
            <MetricTile
              label="saved"
              value="3.8m"
              valueColor="var(--b3-green)"
              sub="vs base"
            />
            <MetricTile
              label="QA"
              value={String(alerts.filter((a) => a.severity === "critical").length || 2)}
              valueColor="var(--b3-hot)"
              sub="flagged"
            />
          </div>

          {/* TOOL CALLS (static mock) */}
          <div className="b3-panel">
            <div className="b3-panel-hd">
              <span className="b3-hd-t">TOOL CALLS · #05 (MOCK)</span>
              <span className="b3-hd-s">
                8 calls · 2 pending commit
              </span>
            </div>
            <div className="b3-tools-body">
              {MOCK_TOOLS.map((tool, i) => (
                <div key={i} className="b3-tool-row">
                  <span className="b3-tool-t">{tool.t}</span>
                  <div>
                    <span
                      className="b3-tool-name"
                      style={{
                        color: tool.pending
                          ? "var(--b3-amber)"
                          : "var(--b3-hot)",
                      }}
                    >
                      {tool.name}
                    </span>
                    <span className="b3-tool-args">({tool.args})</span>
                    <div
                      className="b3-tool-out"
                      style={{
                        color: tool.pending
                          ? "var(--b3-amber)"
                          : "var(--b3-text-2)",
                      }}
                    >
                      → {tool.out}
                    </div>
                  </div>
                  <span className="b3-tool-ms">{tool.ms}ms</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* V2 · pipeline-latency strip (live data-channel) */}
      {view === "v2" && (
        <V2Pipeline
          v2VoiceSlotRef={v2VoiceSlotRef}
          latency={latency}
          roomLive={roomLive}
          sessionId={sessionId}
          phase={phase}
          turns={turns}
        />
      )}

      {/* V3 · MCI mode (static mock) */}
      {view === "v3" && <V3MCI />}

      {/* V4 · Vision link (static mock) */}
      {view === "v4" && <V4Vision />}

      {/* Persistent LiveCallRoom mount. Always lives at page scope so
          the WebRTC session, onRoomLiveChange callbacks, and
          data-channel tap survive tab switches. When a tab has a voice
          slot (V1/V2) the portal moves the LIVE DOM into that slot;
          otherwise it's rendered into this hidden host. createPortal
          preserves the React instance across parent changes so LiveKit
          does not tear down the room. */}
      <VoiceHost
        voiceHost={voiceHost}
        sessionId={sessionId}
        onRoomLiveChange={setRoomLive}
        onLatency={setLatency}
      />

      {/* FOOTER */}
      <div className="b3-footer">
        <div className="b3-footer-links">
          <a href="/prism42">ElevenLabs path (A/B baseline)</a>
          <a href="/prism42/safety">safety + IRB</a>
          <a href="/prism42/evidence">evidence dashboard</a>
          <a
            href="https://github.com/GOATnote-Inc/prism42"
            target="_blank"
            rel="noreferrer"
          >
            source
          </a>
        </div>
        <div className="b3-footer-right">
          Clinical director: Brandon Dent, MD · GOATnote Inc. ·
          b@thegoatnote.com
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// SUBCOMPONENTS
// ─────────────────────────────────────────────────────────────────────────

function CallTile({ c, focused }: { c: MockCall; focused: boolean }) {
  return (
    <div
      className="b3-call-tile"
      style={{
        borderColor: focused
          ? "var(--b3-hot)"
          : c.live
            ? "var(--b3-border-2)"
            : "var(--b3-border)",
        background: focused ? "var(--b3-hot-bg)" : "var(--b3-panel)",
      }}
    >
      <div className="b3-call-head">
        <div className="b3-call-id">
          <span
            className={`b3-dot ${c.live ? "b3-dot-hot b3-dot-live" : "b3-dot-off"}`}
          />
          <span>#{c.id}</span>
        </div>
        <span
          className="b3-call-prio"
          style={{
            color:
              c.priority === "P1"
                ? "var(--b3-hot)"
                : c.priority === "P2"
                  ? "var(--b3-amber)"
                  : "var(--b3-text-3)",
          }}
        >
          {c.priority}
        </span>
      </div>
      <Soundbar
        bars={22}
        height={14}
        seed={c.seed}
        active={c.live}
        idle={!c.live}
      />
      <div>
        <div className="b3-call-kind">{c.kind}</div>
        <div className="b3-call-loc">{c.loc}</div>
      </div>
    </div>
  );
}

function PhaseBar({ current }: { current: PsapPhase["name"] }) {
  const idx = PHASE_SEQUENCE.indexOf(current);
  return (
    <div className="b3-phase-bar">
      {PHASE_SEQUENCE.map((p, i) => (
        <span
          key={p}
          className="b3-phase-pill"
          style={{
            color:
              i === idx
                ? "var(--b3-hot)"
                : i < idx
                  ? "var(--b3-text-3)"
                  : "var(--b3-text-4)",
          }}
        >
          {p}
        </span>
      ))}
    </div>
  );
}

function RubricRow({ label, score }: { label: string; score: number }) {
  return (
    <div className="b3-rubric-row">
      <span className="b3-rubric-label">{label}</span>
      <span className="b3-mono-num b3-rubric-score">{score.toFixed(2)}</span>
    </div>
  );
}

function MetricTile({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub: string;
  valueColor?: string;
}) {
  return (
    <div className="b3-panel b3-metric-tile">
      <div className="b3-metric-label">{label}</div>
      <div className="b3-metric-value" style={{ color: valueColor }}>
        {value}
      </div>
      <div className="b3-metric-sub">{sub}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// VOICE HOST — single stable mount of LiveCallRoom, portaled into the
// active tab's voice slot. See comment above VoiceHost usage in the main
// render for the rationale.
// ─────────────────────────────────────────────────────────────────────────

function VoiceHost({
  voiceHost,
  sessionId,
  onRoomLiveChange,
  onLatency,
}: {
  voiceHost: HTMLElement | null;
  sessionId: string | null;
  onRoomLiveChange: (live: boolean) => void;
  onLatency: (l: LatencyTelemetry) => void;
}) {
  const fallbackRef = useRef<HTMLDivElement | null>(null);
  const [fallbackEl, setFallbackEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setFallbackEl(fallbackRef.current);
  }, []);
  const target = voiceHost ?? fallbackEl;
  return (
    <>
      <div
        ref={fallbackRef}
        style={{
          position: "absolute",
          width: 0,
          height: 0,
          overflow: "hidden",
        }}
      />
      {target &&
        createPortal(
          <LiveCallRoom
            sessionId={sessionId}
            onRoomLiveChange={onRoomLiveChange}
            onLatency={onLatency}
          />,
          target,
        )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// V2 · SOUNDBAR-FORWARD + LIVE PIPELINE LATENCY
// Port of /tmp/b300_design/named/03-V2Soundbar.jsx, right-hand column.
// The LatencyMeter rows now read from the `latency` prop — real values
// pushed by worker.py over the `b3-latency` LiveKit data channel.
// ─────────────────────────────────────────────────────────────────────────

const V2_CALLS: Array<{
  id: string;
  kind: string;
  loc: string;
  priority: "P1" | "P2" | "P3" | "P4";
  live: boolean;
  phase: PsapPhase["name"];
  turns: number;
  elapsedS: number;
  stress: number;
  seed: number;
  focus?: boolean;
  speaking: "caller" | "ai" | "silent" | "ringing" | "auto";
}> = [
  { id: "05", kind: "MVC · multi-vehicle · injury", loc: "I-80 E · mp 14.2", priority: "P1", live: true, phase: "pdi", turns: 7, elapsedS: 134, stress: 0.82, seed: 5, focus: true, speaking: "caller" },
  { id: "10", kind: "medical · chest pain", loc: "S. Virginia St", priority: "P2", live: true, phase: "dispatch", turns: 4, elapsedS: 78, stress: 0.55, seed: 10, speaking: "ai" },
  { id: "04", kind: "welfare check · non-response", loc: "S. Wells Ave", priority: "P3", live: true, phase: "intake", turns: 2, elapsedS: 34, stress: 0.31, seed: 4, speaking: "ai" },
  { id: "07", kind: "lang swap · ES -> EN", loc: "hold", priority: "P3", live: true, phase: "triage", turns: 1, elapsedS: 12, stress: 0.22, seed: 7, speaking: "silent" },
  { id: "12", kind: "callback · prior incident", loc: "ring", priority: "P4", live: true, phase: "intake", turns: 0, elapsedS: 6, stress: 0.10, seed: 12, speaking: "ringing" },
  { id: "03", kind: "parking · awaiting tow", loc: "4th & Sierra", priority: "P4", live: false, phase: "dispatch", turns: 8, elapsedS: 215, stress: 0.05, seed: 3, speaking: "auto" },
];

function V2Pipeline({
  v2VoiceSlotRef,
  latency,
  roomLive,
  sessionId,
  phase,
  turns,
}: {
  v2VoiceSlotRef: React.RefObject<HTMLDivElement | null>;
  latency: LatencyTelemetry | null;
  roomLive: boolean;
  sessionId: string | null;
  phase: PsapPhase;
  turns: PsapTurn[];
}) {
  // Pipeline budget defaults (ms). Match V1 so the visual register matches.
  const stt = latency?.stt_ms ?? 0;
  const llm = latency?.llm_ms ?? 0;
  const tts = latency?.tts_ms ?? 0;
  const tool = latency?.tool_ms ?? 0;
  const total = latency?.total_ms ?? 0;
  const live = latency !== null && !latency.note;
  return (
    <div className="b3-v2-wrap">
      <div className="b3-v2-main">
        {/* LEFT: call rows */}
        <div className="b3-v2-left">
          <div className="b3-v2-colhead">
            <span>call</span>
            <span>kind · loc</span>
            <span>audio · caller / ai</span>
            <span>stress · turn</span>
            <span style={{ textAlign: "right" }}>elapsed</span>
            <span style={{ textAlign: "right" }}>act</span>
          </div>
          <div className="b3-v2-rows">
            {V2_CALLS.map((c) => (
              <V2CallRow key={c.id} c={c} focused={!!c.focus} />
            ))}
          </div>
          <div className="b3-v2-footer">
            <span>
              <span className="b3-dot b3-dot-hot" /> live human
            </span>
            <span>
              <span className="b3-legend-swatch b3-legend-hot" /> caller
            </span>
            <span>
              <span className="b3-legend-swatch b3-legend-text" /> ai
            </span>
            <span style={{ marginLeft: "auto" }}>
              {roomLive ? "connected · rec" : "pre-connect · idle"}
            </span>
          </div>
        </div>

        {/* RIGHT: focus panel with LIVE pipeline-latency strip */}
        <div className="b3-v2-right">
          <div className="b3-v2-focus-head">
            <div className="b3-hd-t b3-dim">
              focused · call #05 · session{" "}
              {sessionId ? sessionId.slice(0, 8) : "…"}
            </div>
            <div className="b3-focus-title">MVC · multi-vehicle · injury</div>
            <div className="b3-focus-sub">
              I-80 E · mp 14.2 · 39.5296, -119.8138 · phase {phase.name}
            </div>
            <div className="b3-v2-chips">
              <span className="b3-chip b3-chip-hot">P1 · MVC</span>
              <span className="b3-chip b3-chip-amber">fuel smell</span>
              <span className="b3-chip b3-chip-ghost">female · 34</span>
              <span className="b3-chip b3-chip-ghost">
                {turns.length} turns
              </span>
            </div>
          </div>

          {/* Portal slot for LiveCallRoom when view==v2. */}
          <div className="b3-v2-voice">
            <div className="b3-v2-voice-hd">
              <span>live audio · caller channel</span>
              <span className="b3-hot">{roomLive ? "● REC" : "○ idle"}</span>
            </div>
            <div className="b3-v2-voice-body" ref={v2VoiceSlotRef} />
          </div>

          {/* LIVE pipeline-latency strip — rows fed by worker.py over
              the b3-latency LiveKit data channel. */}
          <div className="b3-v2-latency">
            <div className="b3-v2-voice-hd">
              <span>pipeline latency · {live ? "live · b3-latency" : "awaiting first turn"}</span>
              <span className="b3-dim">
                {latency
                  ? `turn ${latency.turn_id.slice(0, 6)} · ${new Date(latency.ts_ms).toLocaleTimeString()}`
                  : "topic subscribed · no data"}
              </span>
            </div>
            <div className="b3-latency-body">
              <LatencyMeter ms={stt} budget={250} label="stt · parakeet" />
              <LatencyMeter ms={llm} budget={500} label="llm · sonnet-4.6" />
              <LatencyMeter ms={tts} budget={300} label="tts · fish speech" />
              <LatencyMeter ms={tool} budget={150} label="tool · cad dispatch" />
              <div className="b3-latency-total">
                <span className="b3-text-3">TOTAL turn-to-response</span>
                <span
                  className={`b3-mono-num ${
                    total === 0 ? "b3-dim" : total < 800 ? "b3-green" : "b3-amber"
                  }`}
                >
                  {total === 0 ? "— awaiting —" : `${total}ms`}
                </span>
              </div>
              {latency?.note && (
                <div className="b3-v2-note">
                  channel open · worker note: <code>{latency.note}</code>
                </div>
              )}
            </div>
          </div>

          {/* live transcript tail */}
          <div className="b3-v2-tail">
            <div className="b3-v2-voice-hd">
              <span>live transcript</span>
              <span className="b3-dim">
                streaming · {turns.length} turns
              </span>
            </div>
            <div className="b3-v2-tail-body">
              {turns.length === 0 ? (
                <div className="b3-transcript-empty">
                  waiting for first caller utterance…
                </div>
              ) : (
                turns.slice(-4).map((t, i) => (
                  <div key={i} className="b3-v2-tail-row">
                    <span className="b3-hot">
                      t{turns.length - Math.min(4, turns.length) + i + 1} ·{" "}
                      {t.agent}
                    </span>
                    <div>{t.content ?? "(no caller-facing content)"}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function V2CallRow({
  c,
  focused,
}: {
  c: (typeof V2_CALLS)[number];
  focused: boolean;
}) {
  const callerActive = c.speaking === "caller";
  const aiActive = c.speaking === "ai";
  const segs = 12;
  const fill = Math.round(c.stress * segs);
  return (
    <div
      className="b3-v2-row"
      style={{
        background: focused ? "var(--b3-hot-bg)" : "transparent",
        borderLeft: focused
          ? "2px solid var(--b3-hot)"
          : "2px solid transparent",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span
          className={`b3-dot ${c.live ? "b3-dot-hot b3-dot-live" : "b3-dot-off"}`}
        />
        <span
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: focused ? "var(--b3-hot)" : "var(--b3-text)",
          }}
        >
          #{c.id}
        </span>
      </div>
      <div>
        <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
          <span
            style={{
              fontSize: 10,
              letterSpacing: "0.05em",
              color:
                c.priority === "P1"
                  ? "var(--b3-hot)"
                  : c.priority === "P2"
                    ? "var(--b3-amber)"
                    : "var(--b3-text-3)",
            }}
          >
            {c.priority}
          </span>
          <span style={{ fontSize: 11 }}>{c.kind}</span>
        </div>
        <div
          style={{
            fontSize: 10,
            color: "var(--b3-text-3)",
            marginTop: 1,
          }}
        >
          {c.loc} · {c.phase}
        </div>
      </div>
      <div style={{ display: "grid", gap: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 8,
              color: callerActive ? "var(--b3-hot)" : "var(--b3-text-4)",
              width: 22,
              letterSpacing: "0.05em",
            }}
          >
            CLR
          </span>
          <div style={{ flex: 1 }}>
            <Soundbar
              bars={90}
              height={14}
              seed={c.seed}
              active={callerActive}
              idle={!c.live || c.speaking === "silent"}
              color="#ff0096"
            />
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 8,
              color: aiActive ? "var(--b3-text)" : "var(--b3-text-4)",
              width: 22,
              letterSpacing: "0.05em",
            }}
          >
            AI
          </span>
          <div style={{ flex: 1 }}>
            <Soundbar
              bars={90}
              height={14}
              seed={c.seed + 50}
              active={aiActive}
              idle={!c.live || c.speaking === "silent"}
              color="#e8e8ea"
              speed={100}
            />
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gap: 4 }}>
        <div style={{ display: "flex", gap: 2 }}>
          {Array.from({ length: segs }).map((_, i) => (
            <span
              key={i}
              style={{
                width: 3,
                height: 10,
                background:
                  i < fill
                    ? c.stress > 0.75
                      ? "var(--b3-hot)"
                      : c.stress > 0.5
                        ? "var(--b3-amber)"
                        : "var(--b3-green)"
                    : "var(--b3-border-2)",
              }}
            />
          ))}
        </div>
        <div style={{ fontSize: 9, color: "var(--b3-text-3)" }}>
          stress {(c.stress * 100).toFixed(0)}% · turn {c.turns}
        </div>
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--b3-text-2)",
          textAlign: "right",
        }}
      >
        <Elapsed start={Date.now() - c.elapsedS * 1000} />
      </div>
      <div style={{ textAlign: "right" }}>
        {focused ? (
          <span
            style={{
              fontSize: 9,
              color: "var(--b3-hot)",
              letterSpacing: "0.08em",
            }}
          >
            FOCUSED
          </span>
        ) : (
          <span style={{ fontSize: 9, color: "var(--b3-text-3)" }}>
            ⌥{c.id}
          </span>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// V3 · MCI MODE (static mock — no live MCI detection in this MVP)
// Port of /tmp/b300_design/named/04-V3MCI.jsx, trimmed for size.
// ─────────────────────────────────────────────────────────────────────────

const V3_INCOMING = [
  { id: "17", time: "14:07:22", loc: "I-80 E · mp 14.1", kind: "MVC · injury", conf: 0.94, dist: "0.1mi", seed: 17 },
  { id: "18", time: "14:07:48", loc: "I-80 E · mp 14.3", kind: "MVC · fire", conf: 0.97, dist: "0.2mi", seed: 18 },
  { id: "19", time: "14:08:02", loc: "I-80 E · mp 13.9", kind: "MVC · smoke", conf: 0.89, dist: "0.3mi", seed: 19 },
  { id: "20", time: "14:08:14", loc: "I-80 E · mp 14.2", kind: "pedestrian down", conf: 0.82, dist: "0.0mi", seed: 20 },
  { id: "21", time: "14:08:31", loc: "I-80 E · mp 14.4", kind: "MVC · multi", conf: 0.91, dist: "0.4mi", seed: 21 },
  { id: "22", time: "14:08:44", loc: "I-80 E · mp 14.2", kind: "injury · severe", conf: 0.95, dist: "0.1mi", seed: 22 },
];

const V3_SCAN_LOG = [
  { ms: 12, op: "history.scan", args: "window=30m, radius=1mi, type=MVC", out: "14 calls matched" },
  { ms: 8, op: "cluster.detect", args: "dbscan eps=0.4mi, min_pts=3", out: "1 cluster · 9 members" },
  { ms: 22, op: "weather.fetch", args: "loc=mp14, time=now", out: "fog · vis 0.2mi · HAZMAT risk +" },
  { ms: 18, op: "traffic.state", args: "loc=I-80 E, window=15m", out: "speed 22mph · drop from 68mph @ 14:06" },
  { ms: 34, op: "cad.units", args: "radius=10mi, available=true", out: "7 EMS · 4 PD · 2 FIRE · 1 HAZMAT" },
  { ms: 67, op: "vision.satellite", args: "loc=mp14, age<10m", out: "rendered · fog signature confirmed" },
  { ms: 41, op: "social.scan", args: "geo=39.53,-119.81, r=1mi, t=15m", out: "12 posts mention pileup" },
  { ms: 9, op: "mci.classify", args: "evidence_count=9", out: "MCI-L2 · confidence 0.87" },
];

function V3MCI() {
  // Static mock — no live MCI detection. TODO: wire detector once
  // clustering service lands (tracked in docs/clinical-roadmap.md H3).
  return (
    <div className="b3-v3-wrap">
      {/* MCI DECLARATION STRIP */}
      <div className="b3-v3-banner">
        <div className="b3-v3-banner-left">
          <span className="b3-dot b3-dot-hot b3-dot-live" style={{ width: 10, height: 10 }} />
          <span className="b3-v3-title">MCI-L2 DECLARED</span>
        </div>
        <div className="b3-v3-banner-body">
          <span className="b3-hot">9 correlated calls</span> in{" "}
          <span className="b3-mono-num">2m 14s</span> within{" "}
          <span className="b3-mono-num">0.5mi</span> of I-80 E mp 14.2 ·{" "}
          pattern: MVC + fire + injury · weather: fog (vis 0.2mi) ·{" "}
          <span className="b3-amber">multi-vehicle pileup suspected</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="b3-btn b3-btn-hot" disabled>
            activate MCI protocol ⌥M
          </button>
          <button className="b3-btn b3-btn-ghost" disabled>
            dismiss
          </button>
        </div>
      </div>

      {/* Main grid */}
      <div className="b3-v3-main">
        {/* LEFT: similar-activity scan + incoming + scan log */}
        <div style={{ display: "grid", gap: 10, minHeight: 0 }}>
          <div className="b3-panel" style={{ padding: "12px 14px" }}>
            <div className="b3-hd-t b3-dim" style={{ marginBottom: 8 }}>
              similar activity scan · last 30min
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr auto",
                gap: 10,
                alignItems: "center",
                marginBottom: 8,
              }}
            >
              <span style={{ fontSize: 28, fontWeight: 600, color: "var(--b3-hot)", lineHeight: 1 }}>
                9
              </span>
              <div>
                <div style={{ fontSize: 11 }}>matching events</div>
                <div style={{ fontSize: 9, color: "var(--b3-text-3)" }}>
                  up from 0 at 14:05
                </div>
              </div>
              <Sparkline data={[0, 0, 0, 1, 1, 3, 5, 7, 9]} width={80} height={28} color="#ff0096" />
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 8,
                fontSize: 10,
                paddingTop: 8,
                borderTop: "1px dashed var(--b3-border)",
              }}
            >
              <div>
                <span className="b3-dim">radius</span>{" "}
                <span className="b3-mono-num">0.5mi</span>
              </div>
              <div>
                <span className="b3-dim">time span</span>{" "}
                <span className="b3-mono-num">2m 14s</span>
              </div>
              <div>
                <span className="b3-dim">baseline rate</span>{" "}
                <span className="b3-mono-num">0.2/hr</span>
              </div>
              <div>
                <span className="b3-dim">observed</span>{" "}
                <span className="b3-mono-num b3-hot">241/hr</span>
              </div>
            </div>
          </div>

          <div className="b3-panel" style={{ display: "grid", gridTemplateRows: "auto 1fr", minHeight: 0 }}>
            <div className="b3-panel-hd">
              <span className="b3-hd-t">INCOMING · AUTO-GROUPED</span>
              <span className="b3-hd-s">6 ringing · 3 in progress</span>
            </div>
            <div style={{ overflowY: "auto" }}>
              {V3_INCOMING.map((c) => (
                <div
                  key={c.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "40px 70px 1fr 48px",
                    gap: 10,
                    padding: "8px 14px",
                    borderBottom: "1px solid var(--b3-border)",
                    alignItems: "center",
                    fontSize: 10,
                  }}
                >
                  <div>
                    <div style={{ color: "var(--b3-text)", fontSize: 12, fontWeight: 500 }}>
                      #{c.id}
                    </div>
                    <div className="b3-mono-num" style={{ color: "var(--b3-text-3)", fontSize: 9 }}>
                      {c.time.slice(3)}
                    </div>
                  </div>
                  <div>
                    <div className="b3-hot">{c.kind}</div>
                    <div style={{ color: "var(--b3-text-3)", fontSize: 9 }}>
                      {c.dist}
                    </div>
                  </div>
                  <Soundbar bars={40} height={12} seed={c.seed} active color="#ff0096" />
                  <span
                    className="b3-mono-num"
                    style={{ color: "var(--b3-text-2)", textAlign: "right" }}
                  >
                    {c.conf}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div
            className="b3-panel"
            style={{ display: "grid", gridTemplateRows: "auto 1fr", minHeight: 0, maxHeight: 220 }}
          >
            <div className="b3-panel-hd">
              <span className="b3-hd-t">MCI DETECTION · TOOL TRACE</span>
              <span className="b3-hd-s">8 calls · 211ms total</span>
            </div>
            <div style={{ overflowY: "auto", padding: "6px 14px", fontSize: 10 }}>
              {V3_SCAN_LOG.map((l, i) => (
                <div
                  key={i}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "40px 1fr",
                    gap: 8,
                    padding: "3px 0",
                    borderBottom: "1px dashed var(--b3-border)",
                  }}
                >
                  <span className="b3-mono-num" style={{ color: "var(--b3-text-3)" }}>
                    {l.ms}ms
                  </span>
                  <div>
                    <span className="b3-hot">{l.op}</span>
                    <span style={{ color: "var(--b3-text-3)" }}> ({l.args})</span>
                    <div style={{ color: "var(--b3-text-2)", paddingLeft: 10, fontSize: 10 }}>
                      -&gt; {l.out}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* CENTER: spatial cluster map (SVG mock) */}
        <div className="b3-panel" style={{ display: "grid", gridTemplateRows: "auto 1fr auto", minHeight: 0 }}>
          <div className="b3-panel-hd">
            <span className="b3-hd-t">CLUSTER · SPATIAL</span>
            <span className="b3-hd-s">dbscan · 9 members · eps 0.4mi</span>
          </div>
          <div style={{ position: "relative", overflow: "hidden" }}>
            <svg viewBox="0 0 460 460" style={{ width: "100%", height: "100%", display: "block" }}>
              {[...Array(24)].map((_, i) => (
                <line key={"v" + i} x1={i * 20} y1="0" x2={i * 20} y2="460" stroke="#1f1f22" strokeWidth="0.3" />
              ))}
              {[...Array(24)].map((_, i) => (
                <line key={"h" + i} x1="0" y1={i * 20} x2="460" y2={i * 20} stroke="#1f1f22" strokeWidth="0.3" />
              ))}
              <path d="M 0 230 Q 200 220 460 240" stroke="#2a2a2e" strokeWidth="3" fill="none" />
              <text x="10" y="222" fill="#55555a" fontSize="9" fontFamily="inherit">
                I-80 E -&gt;
              </text>
              <text x="120" y="252" fill="#3a3a3e" fontSize="8">mp 13</text>
              <text x="240" y="252" fill="#3a3a3e" fontSize="8">mp 14</text>
              <text x="360" y="252" fill="#3a3a3e" fontSize="8">mp 15</text>
              <rect x="180" y="140" width="180" height="180" fill="#ff0096" fillOpacity="0.04" />
              <text x="270" y="155" fill="#8a8a90" fontSize="8" textAnchor="middle">
                fog · vis 0.2mi
              </text>
              <circle
                cx="260"
                cy="230"
                r="90"
                fill="none"
                stroke="#ff0096"
                strokeWidth="0.5"
                strokeDasharray="3,3"
                opacity="0.6"
              />
              <text x="260" y="125" fill="#ff0096" fontSize="9" textAnchor="middle" letterSpacing="1">
                CLUSTER · R 0.5mi
              </text>
              {[
                { x: 248, y: 224 }, { x: 262, y: 232 }, { x: 238, y: 220 },
                { x: 260, y: 228 }, { x: 278, y: 242 }, { x: 254, y: 226 },
                { x: 250, y: 234 }, { x: 268, y: 222 }, { x: 272, y: 238 },
              ].map((m, i) => (
                <g key={i}>
                  <circle cx={m.x} cy={m.y} r="4" fill="#ff0096" opacity="0.85" />
                  <circle cx={m.x} cy={m.y} r="4" fill="none" stroke="#ff0096" strokeWidth="1" opacity="0.3">
                    <animate attributeName="r" from="4" to="14" dur="2s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.5" to="0" dur="2s" repeatCount="indefinite" />
                  </circle>
                </g>
              ))}
              <polygon points="60,190 70,196 60,202 62,196" fill="#4ade80" />
              <text x="76" y="199" fill="#4ade80" fontSize="8">EMS-M12 · 2:10</text>
              <polygon points="420,180 430,186 420,192 422,186" fill="#4ade80" />
              <text x="368" y="176" fill="#4ade80" fontSize="8">EMS-M07 · 3:40</text>
              <line x1="380" y1="430" x2="440" y2="430" stroke="#55555a" strokeWidth="1" />
              <text x="410" y="442" fill="#55555a" fontSize="8" textAnchor="middle">
                0.5 mi
              </text>
            </svg>
          </div>
          <div
            style={{
              padding: "10px 14px",
              borderTop: "1px solid var(--b3-border)",
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 8,
              fontSize: 10,
            }}
          >
            <div>
              <span className="b3-dim">members</span>{" "}
              <span className="b3-mono-num b3-hot">9</span>
            </div>
            <div>
              <span className="b3-dim">centroid</span>{" "}
              <span className="b3-mono-num">mp 14.2</span>
            </div>
            <div>
              <span className="b3-dim">density</span>{" "}
              <span className="b3-mono-num">18.0/mi²</span>
            </div>
            <div>
              <span className="b3-dim">eta first unit</span>{" "}
              <span className="b3-mono-num b3-green">2:10</span>
            </div>
          </div>
        </div>

        {/* RIGHT: evidence chain */}
        <div className="b3-panel" style={{ display: "grid", gridTemplateRows: "auto 1fr", minHeight: 0 }}>
          <div className="b3-panel-hd">
            <span className="b3-hd-t">EVIDENCE CHAIN</span>
            <span className="b3-hd-s">why this is MCI</span>
          </div>
          <div
            style={{
              padding: "10px 14px",
              display: "grid",
              gap: 10,
              fontSize: 10,
              lineHeight: 1.5,
              overflowY: "auto",
            }}
          >
            {[
              ["1 · temporal clustering", "9 calls in 2m 14s, baseline 0.007/s. probability of random occurrence < 0.001."],
              ["2 · spatial clustering", "all within 0.5mi radius of I-80 mp 14.2. dbscan eps=0.4mi min_pts=3 -> 1 dense cluster."],
              ["3 · semantic consistency", "8/9 classifications in {MVC, injury, fire, smoke}. intent coherence 0.87."],
              ["4 · environmental co-factor", "fog advisory active · visibility 0.2mi · traffic speed drop 68->22mph at 14:06:30."],
              ["5 · external corroboration", "12 geotagged social posts mention 'pileup' within 1mi / 15m window."],
            ].map(([h, body]) => (
              <div key={h}>
                <div className="b3-hot" style={{ marginBottom: 2 }}>{h}</div>
                <div style={{ color: "var(--b3-text-2)" }}>{body}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// V4 · VISION LINK (static mock — drone detection pane + tool trace +
// grounded transcript. No real vision pipeline in this MVP.)
// Port of /tmp/b300_design/named/05-V4Vision.jsx, trimmed for size.
// ─────────────────────────────────────────────────────────────────────────

const V4_DETECTIONS = [
  { id: "d1", label: "person · supine", conf: 0.94, box: [120, 140, 90, 50], color: "#ff0096", state: "injured" },
  { id: "d2", label: "person · standing", conf: 0.91, box: [280, 60, 40, 140], color: "#ffb84d", state: "caller" },
  { id: "d3", label: "vehicle · sedan · overturned", conf: 0.97, box: [60, 40, 180, 120], color: "#ff0096", state: "hazard" },
  { id: "d4", label: "vehicle · truck", conf: 0.88, box: [330, 120, 120, 80], color: "#8a8a90", state: "secondary" },
  { id: "d5", label: "fluid pool · fuel", conf: 0.79, box: [200, 210, 80, 30], color: "#ff0096", state: "hazmat" },
  { id: "d6", label: "smoke · light", conf: 0.68, box: [80, 20, 120, 40], color: "#ffb84d", state: "hazard" },
] as const;

const V4_TOOL_CALLS = [
  { ms: 42, op: "vision.detect", args: "model=owl-v3, stream=drone-07", out: "6 objects · 4 of concern", ongoing: true },
  { ms: 88, op: "vision.depth", args: "scene=frame_1247", out: "supine person 2.3m from vehicle" },
  { ms: 31, op: "vision.classify", args: "fluid_pool, spectral", out: "gasoline · conf 0.79" },
  { ms: 54, op: "robot.plan", args: "goal=extract_safe_zone", out: "3 waypoints · 11m path" },
  { ms: 22, op: "hazmat.assess", args: "fuel + heat_signature", out: "risk=HIGH · evac 50ft" },
  { ms: 19, op: "vision.track", args: "target=person_d1", out: "breathing detected 14/min" },
];

function V4Vision() {
  // Static mock — no real vision model. TODO: wire `vision.detect`
  // MCP server when the field-unit drone lands.
  return (
    <div className="b3-v4-wrap">
      <div className="b3-v4-topbar">
        <span className="b3-chip b3-chip-hot">
          <span className="b3-dot b3-dot-hot b3-dot-live" /> call #05 · live
        </span>
        <span className="b3-chip b3-chip-ghost">
          field unit · DRONE-07 · 94% battery
        </span>
        <span className="b3-chip b3-chip-amber">uplink 42ms · 4k30</span>
        <span className="b3-dim" style={{ marginLeft: "auto" }}>
          robot.autonomy <span className="b3-amber">L2 · supervised</span> ·
          vision.model <span className="b3-green">owl-v3</span>
        </span>
      </div>

      <div className="b3-v4-main">
        {/* LEFT: vision feed (SVG mock) + audio + robot plan */}
        <div style={{ display: "grid", gridTemplateRows: "1fr auto", minHeight: 0, borderRight: "1px solid var(--b3-border)" }}>
          <div style={{ position: "relative", background: "#05050b", overflow: "hidden" }}>
            <svg
              viewBox="0 0 480 300"
              preserveAspectRatio="xMidYMid meet"
              style={{ width: "100%", height: "100%", display: "block" }}
            >
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
              <g opacity="0.5">
                <polygon points="60,160 240,140 220,180 80,200" fill="#2a2a35" />
                <polygon points="330,200 450,190 440,240 340,230" fill="#2a2a35" />
                <ellipse cx="165" cy="170" rx="45" ry="10" fill="#1f1f28" />
                <ellipse cx="300" cy="130" rx="12" ry="35" fill="#1f1f28" />
                <ellipse cx="240" cy="230" rx="40" ry="8" fill="#0f0f16" />
                <ellipse cx="140" cy="45" rx="60" ry="20" fill="#1a1a22" opacity="0.6" />
              </g>
              {V4_DETECTIONS.map((d) => {
                const [x, y, w, h] = d.box;
                return (
                  <g key={d.id}>
                    <rect x={x} y={y} width={w} height={h} fill="none" stroke={d.color} strokeWidth="1.5" />
                    <rect x={x} y={y - 12} width={d.label.length * 5.5 + 32} height="12" fill={d.color} opacity="0.9" />
                    <text x={x + 4} y={y - 3} fill="#0a0a0b" fontSize="9" fontWeight="500">
                      {d.label} · {d.conf.toFixed(2)}
                    </text>
                  </g>
                );
              })}
              <g stroke="#ff0096" strokeWidth="0.5" fill="none" opacity="0.8">
                <line x1="240" y1="10" x2="240" y2="30" />
                <line x1="240" y1="270" x2="240" y2="290" />
                <line x1="10" y1="150" x2="30" y2="150" />
                <line x1="450" y1="150" x2="470" y2="150" />
              </g>
              <g fontSize="8" fill="#ff0096">
                <text x="8" y="14">ALT 24.2m</text>
                <text x="8" y="26">HDG 094°</text>
                <text x="8" y="38">SPD 0.0 m/s</text>
                <text x="425" y="14" textAnchor="end">FRM 001247</text>
                <text x="8" y="294">[REC] · 00:47</text>
              </g>
            </svg>
            <div
              style={{
                position: "absolute",
                bottom: 10,
                left: "50%",
                transform: "translateX(-50%)",
                background: "rgba(10,10,11,0.85)",
                border: "1px solid var(--b3-hot-border)",
                padding: "6px 12px",
                fontSize: 10,
              }}
            >
              <span className="b3-hot">VISION LINK ACTIVE</span>
              <span className="b3-dim">
                {" "}
                · AI streaming scene to caller via voice{" "}
              </span>
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.3fr 1fr",
              borderTop: "1px solid var(--b3-border)",
            }}
          >
            <div style={{ padding: "12px 16px", borderRight: "1px solid var(--b3-border)" }}>
              <div className="b3-hd-t b3-dim" style={{ marginBottom: 8 }}>
                call #05 · caller on line
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 9, color: "var(--b3-hot)", width: 50 }}>CALLER</span>
                  <div style={{ flex: 1 }}>
                    <Soundbar bars={90} height={18} seed={5} active color="#ff0096" />
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 9, color: "var(--b3-text-2)", width: 50 }}>AI</span>
                  <div style={{ flex: 1 }}>
                    <Soundbar bars={90} height={18} seed={55} active={false} idle color="#e8e8ea" />
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 9, color: "var(--b3-amber)", width: 50 }}>DRONE</span>
                  <div style={{ flex: 1 }}>
                    <Soundbar bars={90} height={18} seed={77} active color="#ffb84d" speed={120} />
                  </div>
                </div>
              </div>
            </div>
            <div style={{ padding: "12px 16px" }}>
              <div className="b3-hd-t b3-dim" style={{ marginBottom: 8 }}>
                robot plan · proposed
              </div>
              <div style={{ display: "grid", gap: 6, fontSize: 10 }}>
                {[
                  ["1", "approach person_d1 from north (upwind)", "4.2m"],
                  ["2", "stream vitals · thermal overlay", "continuous"],
                  ["3", "guide caller vocally to safe zone", "6.8m"],
                ].map(([n, text, dist]) => (
                  <div
                    key={n}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "16px 1fr auto",
                      gap: 8,
                      alignItems: "baseline",
                    }}
                  >
                    <span className="b3-hot">{n}</span>
                    <span style={{ color: "var(--b3-text)" }}>{text}</span>
                    <span className="b3-mono-num b3-dim">{dist}</span>
                  </div>
                ))}
                <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                  <button className="b3-btn b3-btn-hot" disabled style={{ flex: 1, padding: 6 }}>
                    execute ⌥↩
                  </button>
                  <button className="b3-btn b3-btn-ghost" disabled style={{ padding: "6px 10px" }}>
                    hold
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: detections + tools + vision-grounded transcript */}
        <div style={{ display: "grid", gridTemplateRows: "auto auto 1fr", minHeight: 0 }}>
          <div style={{ borderBottom: "1px solid var(--b3-border)" }}>
            <div className="b3-panel-hd">
              <span className="b3-hd-t">VISION · DETECTIONS</span>
              <span className="b3-hd-s">6 objects · 4 high priority</span>
            </div>
            <div style={{ maxHeight: 200, overflowY: "auto" }}>
              {V4_DETECTIONS.map((d) => (
                <div
                  key={d.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "10px 1fr auto auto",
                    gap: 10,
                    padding: "6px 14px",
                    borderBottom: "1px solid var(--b3-border)",
                    alignItems: "center",
                    fontSize: 10,
                  }}
                >
                  <span
                    style={{
                      width: 4,
                      height: 14,
                      background: d.color,
                      display: "inline-block",
                    }}
                  />
                  <div>
                    <div style={{ color: "var(--b3-text)" }}>{d.label}</div>
                    <div style={{ color: "var(--b3-text-3)", fontSize: 9 }}>{d.state}</div>
                  </div>
                  <span className="b3-mono-num" style={{ color: "var(--b3-text-2)" }}>
                    {d.conf.toFixed(2)}
                  </span>
                  <button className="b3-btn b3-btn-ghost" disabled style={{ padding: "2px 6px", fontSize: 8 }}>
                    track
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div style={{ borderBottom: "1px solid var(--b3-border)" }}>
            <div className="b3-panel-hd">
              <span className="b3-hd-t">TOOL TRACE · VISION + ROBOT</span>
              <span className="b3-hd-s">268ms p99 · ongoing stream</span>
            </div>
            <div style={{ padding: "6px 14px", maxHeight: 220, overflowY: "auto", fontSize: 10 }}>
              {V4_TOOL_CALLS.map((t, i) => (
                <div
                  key={i}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "42px 1fr",
                    gap: 8,
                    padding: "3px 0",
                    borderBottom: "1px dashed var(--b3-border)",
                  }}
                >
                  <span
                    className="b3-mono-num"
                    style={{ color: t.ongoing ? "var(--b3-hot)" : "var(--b3-text-3)" }}
                  >
                    {t.ms}ms
                    {t.ongoing ? "*" : ""}
                  </span>
                  <div>
                    <span className="b3-hot">{t.op}</span>
                    <span style={{ color: "var(--b3-text-3)" }}>({t.args})</span>
                    <div style={{ color: "var(--b3-text-2)", paddingLeft: 10 }}>
                      -&gt; {t.out}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateRows: "auto 1fr", minHeight: 0 }}>
            <div className="b3-panel-hd">
              <span className="b3-hd-t">TRANSCRIPT · VISION-GROUNDED</span>
              <span className="b3-hd-s">ai uses scene context</span>
            </div>
            <div
              style={{
                padding: "12px 16px",
                overflowY: "auto",
                fontSize: 11,
                display: "grid",
                gap: 10,
                lineHeight: 1.5,
              }}
            >
              <div>
                <span className="b3-hot" style={{ fontSize: 9, letterSpacing: "0.05em" }}>
                  t8 · caller
                </span>
                <div style={{ color: "var(--b3-text)", marginTop: 2 }}>
                  i don't know what to do, he's bleeding a lot
                </div>
              </div>
              <div>
                <span className="b3-dim" style={{ fontSize: 9, letterSpacing: "0.05em" }}>
                  t8 · ai · 312ms · vision-grounded
                </span>
                <div style={{ color: "var(--b3-text-2)", marginTop: 2 }}>
                  i can see <span className="b3-hot">the drone has arrived overhead</span>.
                  he's lying about 8 feet from the car. walk toward him —{" "}
                  <span className="b3-hot">
                    stay on the grass, away from the fuel pool i see below the sedan
                  </span>
                  .
                </div>
                <div className="b3-green" style={{ fontSize: 9, marginTop: 3 }}>
                  -&gt; 3 vision detections injected into context
                </div>
              </div>
              <div>
                <span className="b3-hot" style={{ fontSize: 9, letterSpacing: "0.05em" }}>
                  t9 · caller
                </span>
                <div style={{ color: "var(--b3-text)", marginTop: 2 }}>
                  ok i see him. should i turn him over?
                </div>
              </div>
              <div>
                <span className="b3-dim" style={{ fontSize: 9, letterSpacing: "0.05em" }}>
                  t9 · ai · 288ms · vision-grounded
                </span>
                <div style={{ color: "var(--b3-text-2)", marginTop: 2 }}>
                  <span className="b3-hot">i can see him breathing from here</span> —
                  roughly 14 breaths a minute. don't turn him. kneel beside him and keep
                  him still.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// STYLES — scoped under .b3-console. Tokens match the design spec.
// ─────────────────────────────────────────────────────────────────────────

const B3_STYLES = `
.b3-console {
  --b3-bg: #0a0a0b;
  --b3-panel: #121214;
  --b3-panel-2: #161618;
  --b3-border: #1f1f22;
  --b3-border-2: #2a2a2e;
  --b3-text: #e8e8ea;
  --b3-text-2: #8a8a90;
  --b3-text-3: #55555a;
  --b3-text-4: #3a3a3e;
  --b3-hot: #ff0096;
  --b3-hot-bg: rgba(255, 0, 150, 0.08);
  --b3-hot-border: rgba(255, 0, 150, 0.35);
  --b3-amber: #ffb84d;
  --b3-green: #4ade80;
  --b3-blue: #60a5fa;
  --b3-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  --b3-sans: 'IBM Plex Sans', -apple-system, system-ui, sans-serif;
  --b3-r-sm: 2px;
  --b3-r-md: 3px;
  --b3-r-lg: 4px;

  background: var(--b3-bg);
  color: var(--b3-text);
  font-family: var(--b3-mono);
  font-size: 12px;
  line-height: 1.4;
  letter-spacing: 0.005em;
  min-height: 100vh;
  padding: 14px;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 12px;
}
.b3-console * { box-sizing: border-box; }

/* Override the root simulation-banner text color so it's legible on
   the near-black B300 background. */
.b3-console .b3-green { color: var(--b3-green); }
.b3-console .b3-amber { color: var(--b3-amber); }
.b3-console .b3-hot { color: var(--b3-hot); }
.b3-console .b3-text-3 { color: var(--b3-text-3); }
.b3-console .b3-dim { color: var(--b3-text-3); font-size: 11px; }
.b3-console .b3-mono-num { font-variant-numeric: tabular-nums; }

/* TOP BAR */
.b3-topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 4px 2px;
}
.b3-topbar-left { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.b3-topbar-right { display: flex; gap: 12px; align-items: center; font-size: 10px; color: var(--b3-text-2); flex-wrap: wrap; }
.b3-brand { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }
.b3-brand-hot { color: var(--b3-hot); }
.b3-brand-sep { color: var(--b3-text-3); }
.b3-brand-main { color: var(--b3-text); }

.b3-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 7px; font-size: 10px; border-radius: 2px;
  font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;
}
.b3-chip-hot { background: var(--b3-hot-bg); color: var(--b3-hot); border: 1px solid var(--b3-hot-border); }
.b3-chip-ghost { background: transparent; color: var(--b3-text-2); border: 1px solid var(--b3-border-2); }

.b3-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; }
.b3-dot-hot { background: var(--b3-hot); box-shadow: 0 0 6px var(--b3-hot); }
.b3-dot-off { background: var(--b3-text-4); }
@keyframes b3-pulse-hot { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.b3-dot-live { animation: b3-pulse-hot 1.2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .b3-dot-live { animation: none; }
}

/* PANELS */
.b3-panel { background: var(--b3-panel); border: 1px solid var(--b3-border); border-radius: var(--b3-r-md); }
.b3-panel-hd {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 10px 14px; border-bottom: 1px solid var(--b3-border);
}
.b3-panel-hd-framed { border: 1px solid var(--b3-border); border-radius: var(--b3-r-md); padding: 10px 14px; }
.b3-hd-t { font-size: 10px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; color: var(--b3-text-2); }
.b3-hd-s { font-size: 10px; color: var(--b3-text-3); }

/* MAIN GRID */
.b3-main {
  display: grid; grid-template-columns: 1fr 1.5fr 1fr; gap: 12px;
  min-height: 0;
}
.b3-col { display: grid; gap: 10px; min-height: 0; }
.b3-col-left { grid-template-rows: auto 1fr; }
.b3-col-center { grid-template-rows: auto auto 1fr auto; }
.b3-col-right { grid-template-rows: auto auto auto auto auto; align-content: start; }

@media (max-width: 1280px) {
  .b3-main { grid-template-columns: 1fr; }
}

/* LEFT COLUMN: calls grid */
.b3-calls-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 6px; align-content: start; overflow-y: auto;
}
.b3-call-tile {
  border: 1px solid var(--b3-border);
  padding: 8px 10px; display: grid; gap: 6px;
  border-radius: var(--b3-r-sm); min-height: 92px;
}
.b3-call-head { display: flex; justify-content: space-between; align-items: center; }
.b3-call-id { display: flex; gap: 6px; align-items: center; font-size: 11px; font-weight: 500; }
.b3-call-prio { font-size: 9px; letter-spacing: 0.05em; }
.b3-call-kind { font-size: 10px; color: var(--b3-text); line-height: 1.3; }
.b3-call-loc { font-size: 9px; color: var(--b3-text-3); }

/* CENTER: focused call */
.b3-focus-hd { padding: 12px 14px; }
.b3-focus-hd-row {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 10px;
}
.b3-focus-title { font-size: 14px; font-weight: 500; }
.b3-focus-sub { font-size: 10px; color: var(--b3-text-2); margin-top: 2px; }
.b3-focus-meta { font-size: 10px; color: var(--b3-text-3); margin-top: 4px; }
.b3-phase-row { margin-top: 8px; }
.b3-phase-bar { display: flex; gap: 2px; }
.b3-phase-pill {
  font-size: 8px; padding: 2px 4px; letter-spacing: 0.04em;
  text-transform: uppercase;
}

/* Voice panel wraps the LiveCallRoom. The LiveCallRoom renders its
   own .caller-hero markup — we scope it here so the hero sits inside
   the panel frame rather than filling the viewport. */
.b3-voice-panel { display: grid; grid-template-rows: auto 1fr; min-height: 0; }
.b3-voice-body {
  padding: 0;
  min-height: 320px;
  position: relative;
}
/* Tighten the LiveCallRoom hero for in-panel use. */
.b3-voice-body .caller-hero {
  padding: 20px 16px;
  min-height: 320px;
  gap: 16px;
}
.b3-voice-body .caller-orb-frame { flex: 0 0 auto; }
.b3-voice-body .caller-cta h1 {
  font-family: var(--b3-sans);
  font-size: 18px;
  color: var(--b3-text);
  margin: 0 0 8px;
}
.b3-voice-body .caller-subtitle {
  font-family: var(--b3-sans);
  font-size: 12px;
  color: var(--b3-text-2);
  margin: 0 0 12px;
  max-width: 420px;
}
.b3-voice-body .caller-button {
  font-family: var(--b3-mono);
  background: var(--b3-hot);
  color: var(--b3-bg);
  border: none;
  padding: 10px 18px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  border-radius: var(--b3-r-sm);
}
.b3-voice-body .caller-button:disabled { opacity: 0.5; cursor: not-allowed; }
.b3-voice-body .caller-button.live { background: var(--b3-panel-2); color: var(--b3-text); border: 1px solid var(--b3-border-2); }
.b3-voice-body .caller-hint {
  font-family: var(--b3-mono);
  font-size: 10px;
  color: var(--b3-text-3);
  margin-top: 8px;
}
.b3-voice-body .caller-hint .bad { color: var(--b3-hot); }

/* Transcript panel */
.b3-transcript-panel { display: grid; grid-template-rows: auto 1fr; min-height: 0; }
.b3-transcript-body {
  padding: 10px 12px; overflow-y: auto; font-size: 11px;
  max-height: 320px;
}
.b3-transcript-empty {
  color: var(--b3-text-3); font-size: 11px; padding: 16px 4px;
  line-height: 1.6;
}
.b3-turn-row {
  display: grid; grid-template-columns: 4px 72px 1fr 48px;
  column-gap: 10px; padding: 7px 8px;
  border-bottom: 1px solid var(--b3-border);
}
.b3-turn-row:last-child { border-bottom: none; }
.b3-turn-bar { display: block; align-self: stretch; }
.b3-turn-tag {
  font-size: 10px; line-height: 20px; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.b3-turn-text { font-size: 12px; line-height: 20px; }
.b3-turn-action { color: var(--b3-text-3); font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; margin-right: 4px; }
.b3-turn-verify-fail {
  color: var(--b3-hot); font-size: 9px; margin-left: 8px;
  letter-spacing: 0.04em; text-transform: uppercase;
}
.b3-turn-cites { color: var(--b3-text-3); font-size: 10px; }
.b3-turn-lat {
  color: var(--b3-text-3); font-size: 10px; line-height: 20px;
  text-align: right; font-variant-numeric: tabular-nums;
}

/* Action buttons */
.b3-action-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
.b3-btn {
  padding: 10px; font-family: var(--b3-mono); font-size: 11px;
  letter-spacing: 0.08em; text-transform: uppercase; cursor: pointer;
  border-radius: var(--b3-r-sm);
}
.b3-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.b3-btn-hot { background: var(--b3-hot); color: var(--b3-bg); border: none; font-weight: 500; }
.b3-btn-ghost {
  background: transparent; color: var(--b3-text);
  border: 1px solid var(--b3-border-2);
}

/* RIGHT COLUMN */
.b3-latency-body { padding: 12px 14px; display: grid; gap: 10px; }
.b3-latency-total {
  display: flex; justify-content: space-between;
  font-size: 10px; padding-top: 6px; border-top: 1px dashed var(--b3-border);
}

.b3-rubric-body { padding: 12px 14px; display: grid; gap: 4px; }
.b3-rubric-row {
  display: flex; justify-content: space-between;
  font-size: 11px; padding: 3px 0;
}
.b3-rubric-label { color: var(--b3-text-2); }
.b3-rubric-score { color: var(--b3-text); }
.b3-rubric-weighted {
  display: flex; justify-content: space-between;
  margin-top: 6px; padding-top: 6px;
  border-top: 1px dashed var(--b3-border);
  font-size: 12px; color: var(--b3-hot); font-weight: 500;
  letter-spacing: 0.04em; text-transform: uppercase;
}
.b3-rubric-meta { font-size: 10px; color: var(--b3-text-3); margin-top: 4px; }
.b3-self-grade {
  margin-top: 8px; padding: 6px 8px;
  background: var(--b3-hot-bg); color: var(--b3-hot);
  font-size: 10px; border-radius: var(--b3-r-sm);
  border: 1px solid var(--b3-hot-border);
}

.b3-alerts-body { padding: 10px 14px; display: grid; gap: 6px; max-height: 260px; overflow-y: auto; }
.b3-alert { padding: 6px 8px; border-radius: var(--b3-r-sm); border: 1px solid var(--b3-border); }
.b3-alert-info { border-color: var(--b3-border-2); color: var(--b3-text-2); }
.b3-alert-medium { border-color: rgba(255, 184, 77, 0.3); background: rgba(255, 184, 77, 0.05); color: var(--b3-amber); }
.b3-alert-high { border-color: rgba(255, 184, 77, 0.5); background: rgba(255, 184, 77, 0.08); color: var(--b3-amber); }
.b3-alert-critical { border-color: var(--b3-hot-border); background: var(--b3-hot-bg); color: var(--b3-hot); }
.b3-alert-meta { font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 3px; opacity: 0.85; }
.b3-alert-detail { font-size: 11px; color: var(--b3-text); }

.b3-metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
.b3-metric-tile { padding: 8px 10px; }
.b3-metric-label { font-size: 9px; color: var(--b3-text-3); letter-spacing: 0.05em; text-transform: uppercase; }
.b3-metric-value { font-size: 16px; font-weight: 500; color: var(--b3-text); }
.b3-metric-sub { font-size: 9px; color: var(--b3-text-3); }

/* Tool feed */
.b3-tools-body { padding: 6px 14px 10px; overflow-y: auto; max-height: 220px; }
.b3-tool-row {
  display: grid; grid-template-columns: 46px 1fr auto; gap: 8px;
  padding: 4px 0; font-size: 11px;
  border-bottom: 1px dashed var(--b3-border);
}
.b3-tool-row:last-child { border-bottom: none; }
.b3-tool-t { color: var(--b3-text-4); }
.b3-tool-name {}
.b3-tool-args { color: var(--b3-text-3); margin-left: 4px; }
.b3-tool-out { padding-left: 10px; font-size: 10px; }
.b3-tool-ms { color: var(--b3-text-3); font-size: 10px; }

/* Footer */
.b3-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 2px; border-top: 1px solid var(--b3-border);
  font-size: 11px; color: var(--b3-text-3);
}
.b3-footer-links { display: flex; gap: 16px; }
.b3-footer-links a { color: var(--b3-text-2); text-decoration: none; }
.b3-footer-links a:hover { color: var(--b3-hot); text-decoration: underline; }
.b3-footer-right { color: var(--b3-text-3); }

/* Scrollbars */
.b3-console *::-webkit-scrollbar { width: 6px; height: 6px; }
.b3-console *::-webkit-scrollbar-track { background: transparent; }
.b3-console *::-webkit-scrollbar-thumb { background: var(--b3-border-2); border-radius: 3px; }
.b3-console *::-webkit-scrollbar-thumb:hover { background: var(--b3-text-4); }

/* Tabs (top bar) */
.b3-tabs { display: flex; gap: 2px; border: 1px solid var(--b3-border-2); border-radius: var(--b3-r-sm); overflow: hidden; }
.b3-tab {
  background: transparent; color: var(--b3-text-2);
  border: none; border-right: 1px solid var(--b3-border);
  padding: 4px 8px; font: inherit; font-size: 10px;
  letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer;
}
.b3-tab:last-child { border-right: none; }
.b3-tab:hover { color: var(--b3-text); }
.b3-tab-active { background: var(--b3-hot-bg); color: var(--b3-hot); }
.b3-chip-amber { background: rgba(255, 184, 77, 0.06); color: var(--b3-amber); border: 1px solid rgba(255, 184, 77, 0.3); }
.b3-voice-detached {
  padding: 16px; font-size: 11px; color: var(--b3-text-3);
  line-height: 1.5;
}

/* V2 — Soundbar-forward + live pipeline latency */
.b3-v2-wrap {
  display: grid; grid-template-rows: 1fr;
  min-height: 0; gap: 12px;
}
.b3-v2-main {
  display: grid; grid-template-columns: 1fr 420px; gap: 12px;
  min-height: 0;
}
.b3-v2-left {
  display: grid; grid-template-rows: auto 1fr auto; min-height: 0;
  border: 1px solid var(--b3-border); background: var(--b3-panel);
  border-radius: var(--b3-r-md);
}
.b3-v2-colhead {
  display: grid;
  grid-template-columns: 54px 180px 1fr 130px 80px 60px;
  gap: 14px; padding: 8px 14px;
  border-bottom: 1px solid var(--b3-border);
  font-size: 9px; color: var(--b3-text-3);
  letter-spacing: 0.1em; text-transform: uppercase;
}
.b3-v2-rows { overflow-y: auto; }
.b3-v2-row {
  display: grid;
  grid-template-columns: 54px 180px 1fr 130px 80px 60px;
  gap: 14px; align-items: center; padding: 10px 14px;
  border-bottom: 1px solid var(--b3-border);
}
.b3-v2-footer {
  padding: 10px 14px; border-top: 1px solid var(--b3-border);
  display: flex; gap: 24px; font-size: 10px; color: var(--b3-text-3);
  align-items: center;
}
.b3-legend-swatch { display: inline-block; width: 12px; height: 2px; vertical-align: middle; margin-right: 4px; }
.b3-legend-hot { background: var(--b3-hot); }
.b3-legend-text { background: var(--b3-text); }
.b3-v2-right {
  display: grid; grid-template-rows: auto auto auto 1fr; min-height: 0;
  background: var(--b3-panel); border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md);
}
.b3-v2-focus-head {
  padding: 14px 20px; border-bottom: 1px solid var(--b3-border);
  display: grid; gap: 4px;
}
.b3-v2-chips { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.b3-v2-voice {
  border-bottom: 1px solid var(--b3-border);
}
.b3-v2-voice-hd {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 10px 20px; font-size: 9px; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--b3-text-3);
}
.b3-v2-voice-body { min-height: 140px; padding: 8px 20px; }
.b3-v2-voice-body .caller-hero {
  padding: 10px 0; min-height: 140px; gap: 10px;
}
.b3-v2-voice-body .caller-orb-frame { flex: 0 0 80px; }
.b3-v2-voice-body .caller-cta h1 { font-size: 14px; margin: 0 0 4px; }
.b3-v2-voice-body .caller-subtitle { font-size: 11px; margin: 0 0 8px; max-width: 320px; }
.b3-v2-voice-body .caller-button {
  font-family: var(--b3-mono); background: var(--b3-hot);
  color: var(--b3-bg); border: none; padding: 8px 14px;
  font-size: 11px; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; cursor: pointer;
}
.b3-v2-latency {
  padding: 12px 20px; border-bottom: 1px solid var(--b3-border);
}
.b3-v2-note {
  font-size: 9px; color: var(--b3-amber); margin-top: 8px;
}
.b3-v2-note code {
  background: rgba(255, 184, 77, 0.08); padding: 1px 4px;
  border-radius: 2px; color: var(--b3-amber);
}
.b3-v2-tail {
  display: grid; grid-template-rows: auto 1fr; min-height: 0;
}
.b3-v2-tail-body {
  padding: 10px 20px; overflow-y: auto; font-size: 11px;
  display: grid; gap: 10px;
}
.b3-v2-tail-row { display: grid; gap: 2px; }

/* V3 — MCI mode */
.b3-v3-wrap {
  display: grid; grid-template-rows: auto 1fr; gap: 12px;
  min-height: 0;
}
.b3-v3-banner {
  background: var(--b3-hot-bg);
  border-top: 1px solid var(--b3-hot);
  border-bottom: 1px solid var(--b3-hot);
  padding: 14px 20px;
  display: grid; grid-template-columns: auto 1fr auto;
  gap: 24px; align-items: center;
}
.b3-v3-banner-left { display: flex; gap: 10px; align-items: center; }
.b3-v3-title {
  font-size: 14px; font-weight: 600; color: var(--b3-hot);
  letter-spacing: 0.12em;
}
.b3-v3-banner-body { font-size: 11px; color: var(--b3-text); line-height: 1.5; }
.b3-v3-main {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 12px; min-height: 0;
}
@media (max-width: 1280px) {
  .b3-v3-main { grid-template-columns: 1fr; }
  .b3-v2-main { grid-template-columns: 1fr; }
}

/* V4 — Vision link */
.b3-v4-wrap {
  display: grid; grid-template-rows: auto 1fr; gap: 10px;
  min-height: 0;
}
.b3-v4-topbar {
  display: flex; gap: 12px; padding: 8px 12px; align-items: center;
  border: 1px solid var(--b3-border); border-radius: var(--b3-r-md);
  background: var(--b3-panel);
  flex-wrap: wrap;
}
.b3-v4-main {
  display: grid; grid-template-columns: 1.4fr 1fr;
  min-height: 0; border: 1px solid var(--b3-border);
  border-radius: var(--b3-r-md); background: var(--b3-panel);
  overflow: hidden;
}
@media (max-width: 1280px) {
  .b3-v4-main { grid-template-columns: 1fr; }
}
`;
