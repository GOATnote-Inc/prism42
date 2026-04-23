"use client";

import type { PsapTurn } from "@/lib/types";

export function Transcript({ turns }: { turns: PsapTurn[] }) {
  return (
    <div className="panel transcript">
      <h2>Transcript · {turns.length} turns</h2>
      {turns.length === 0 && (
        <div className="dim">
          Session initialized. Waiting for the first caller utterance.
        </div>
      )}
      <ul>
        {turns.map((t) => (
          <li key={t.turn_id}>
            <div className="turn-meta">
              <span>
                {t.agent} · <span className="mono">{t.action}</span>
              </span>
              <span
                className={
                  t.self_verify.all_passed ? "ok" : "bad"
                }
                title={t.rationale}
              >
                {t.self_verify.all_passed ? "verify ok" : "verify FAIL"}
              </span>
            </div>
            <div>
              {t.content ?? (
                <span className="dim">— (no caller-facing content) —</span>
              )}
            </div>
            {t.cites.length > 0 && (
              <div
                className="mono dim"
                style={{ marginTop: 6, fontSize: 11 }}
              >
                {t.cites.slice(0, 3).join(" · ")}
                {t.cites.length > 3 && ` · +${t.cites.length - 3}`}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
