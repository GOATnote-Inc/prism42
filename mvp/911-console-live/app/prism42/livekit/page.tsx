"use client";

// /prism42/livekit — Phase 3a route. Lives ALONGSIDE /prism42 (which
// stays on the ElevenLabs path until Phase 3c cuts over). Same
// dispatcher panels (transcript / rubric / alerts / phase), same
// session-store SSE — only the caller surface differs.

import "@livekit/components-styles";
import { useEffect, useRef, useState } from "react";
import { AlertsPanel } from "@/components/AlertsPanel";
import { LiveCallRoom } from "@/components/LiveCallRoom";
import { PhaseTimeline } from "@/components/PhaseTimeline";
import { RubricStrip } from "@/components/RubricStrip";
import { Transcript } from "@/components/Transcript";
import type {
  PsapAlert,
  PsapPhase,
  PsapTurn,
  RubricGrade,
  SessionEvent,
} from "@/lib/types";

export default function LiveKitDispatcherPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [phase, setPhase] = useState<PsapPhase>({ name: "intake" });
  const [turns, setTurns] = useState<PsapTurn[]>([]);
  const [grades, setGrades] = useState<RubricGrade[]>([]);
  const [alerts, setAlerts] = useState<PsapAlert[]>([]);
  // sseState reflects ONLY the dispatcher SSE transcript stream. It is
  // decoupled from voice — a 404 from /stream (serverless in-memory
  // session store gap) is expected on Vercel and must not be surfaced
  // as "error". When the LiveKit room is connected, the header shows
  // roomLive instead.
  const [sseState, setSseState] = useState<
    "idle" | "starting" | "connected" | "no-transcript" | "degraded"
  >("idle");
  const [roomLive, setRoomLive] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSseState("starting");
      try {
        const r = await fetch("/prism42/api/session/start", { method: "POST" });
        if (!r.ok) throw new Error(`start ${r.status}`);
        const body = (await r.json()) as { session_id: string; phase: PsapPhase };
        if (cancelled) return;
        setSessionId(body.session_id);
        setPhase(body.phase);
        subscribe(body.session_id);
      } catch {
        // session/start failure is still only a transcript-plane problem
        // from the user's perspective — voice will mint its own token
        // independently via /prism42/api/livekit-token.
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
          // 404 on Vercel serverless = session-store didn't persist
          // across instances. Expected; not an error.
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

  // When the LiveKit room is live, the header shows "connected · live
  // voice" regardless of /stream state. Otherwise we surface the
  // transcript-plane status directly.
  const headerStatus = roomLive ? "connected · live voice" : sseState;

  return (
    <div className="console-shell">
      <header>
        <h1>Prism42 — Live 911 Dispatcher (LiveKit + B300)</h1>
        <div className="mono dim">
          session · {sessionId ? sessionId.slice(0, 8) : "…"} · {headerStatus}
        </div>
      </header>

      <LiveCallRoom sessionId={sessionId} onRoomLiveChange={setRoomLive} />

      <div className="console-grid">
        <div>
          <PhaseTimeline current={phase} />
          <div style={{ height: 16 }} />
          <AlertsPanel alerts={alerts} />
        </div>
        <Transcript turns={turns} />
        <div>
          <RubricStrip grades={grades} />
          <div style={{ height: 16 }} />
          <div className="panel">
            <h2>Cross-vendor grader chain</h2>
            <div className="mono dim" style={{ fontSize: 12, lineHeight: 1.7 }}>
              primary · gpt-5-5 (OpenAI)
              <br />
              fallback · gpt-5-4 (OpenAI)
              <br />
              shim · claude-opus-4-7 (raises self_grade_flag)
            </div>
          </div>
        </div>
      </div>

      <div className="footer-strip">
        <div>
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
        <div>
          Clinical director: Brandon Dent, MD · GOATnote Inc. ·
          b@thegoatnote.com
        </div>
      </div>
    </div>
  );
}
