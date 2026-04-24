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
import { LiveCallRoom } from "@/components/LiveCallRoom";
import {
  DualSoundbar,
  Elapsed,
  LatencyMeter,
  Soundbar,
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
  const abortRef = useRef<AbortController | null>(null);
  const sessionStartTs = useRef<number>(Date.now());

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
          <span>
            p50 voice <span className="b3-green">187ms</span>
          </span>
          <span>
            p99 voice <span className="b3-amber">412ms</span>
          </span>
          <span>
            tool rtt <span className="b3-green">82ms</span>
          </span>
          <span>
            stt <span className="b3-green">deepgram</span>
          </span>
          <span>
            tts <span className="b3-green">cartesia</span>
          </span>
          <span>
            llm <span className="b3-green">claude-opus-4.7</span>
          </span>
        </div>
      </div>

      {/* MAIN GRID */}
      <div className="b3-main">
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
            <div className="b3-voice-body">
              <LiveCallRoom
                sessionId={sessionId}
                onRoomLiveChange={setRoomLive}
              />
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
`;
