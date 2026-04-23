"use client";

import type { PsapPhase } from "@/lib/types";

const PHASES: PsapPhase["name"][] = [
  "intake",
  "triage",
  "dispatch",
  "pdi",
  "handoff",
  "closed",
];

export function PhaseTimeline({ current }: { current: PsapPhase }) {
  return (
    <div className="panel">
      <h2>Phase</h2>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {PHASES.map((p) => (
          <span
            key={p}
            className={`phase-pill ${p}`}
            style={{
              opacity: p === current.name ? 1 : 0.35,
              borderWidth: p === current.name ? 1 : 0,
            }}
          >
            {p}
          </span>
        ))}
      </div>
      {current.determinant && (
        <div className="mono dim" style={{ marginTop: 10 }}>
          determinant · {current.determinant}
        </div>
      )}
      {current.kq_index !== undefined && (
        <div className="mono dim" style={{ marginTop: 4 }}>
          kq · {current.kq_index}
        </div>
      )}
    </div>
  );
}
