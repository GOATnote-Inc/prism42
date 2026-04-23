"use client";

import type { PsapAlert } from "@/lib/types";

export function AlertsPanel({ alerts }: { alerts: PsapAlert[] }) {
  const sorted = [...alerts]
    .reverse()
    .slice(0, 12);
  return (
    <div className="panel">
      <h2>Oversight alerts</h2>
      {sorted.length === 0 && (
        <div className="dim">
          No alerts. Safety-monitor, OHCA-detector, and intent-verifier
          are watching every turn.
        </div>
      )}
      {sorted.map((a, i) => (
        <div className={`alert ${a.severity}`} key={i}>
          <div className="mono" style={{ fontSize: 11, marginBottom: 4 }}>
            {a.kind} · {a.severity} · {a.source_agent}
          </div>
          <div>{a.detail}</div>
        </div>
      ))}
    </div>
  );
}
