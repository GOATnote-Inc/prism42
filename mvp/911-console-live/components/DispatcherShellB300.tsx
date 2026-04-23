"use client";

import { DispatcherShell } from "./DispatcherShell";
import { modeLabel, type Mode } from "@/lib/mode";

/**
 * Minimal wrapper around the baseline DispatcherShell. The Phase 2-min
 * A/B experiment is a single-variable test: only the rubric-grader source
 * differs. This shell shows the active mode as a header pill, passes the
 * mode down so client-side code can choose which rubric endpoint to call,
 * but otherwise renders the identical UI.
 *
 * Heavier augmentations (live rubric strip, OHCA meter, cross-vendor
 * disagreement flag) are deferred to a later phase per the approved plan.
 */
export function DispatcherShellB300({ mode }: { mode: Mode }) {
  return (
    <div data-b300-mode={mode} style={{ minHeight: "100vh" }}>
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 14px",
          background:
            mode === "b300"
              ? "linear-gradient(90deg, rgba(199,91,57,0.16), rgba(199,91,57,0.08))"
              : "rgba(95,183,255,0.08)",
          borderBottom:
            mode === "b300"
              ? "1px solid rgba(199,91,57,0.4)"
              : "1px solid rgba(95,183,255,0.3)",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
          fontSize: 11,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: mode === "b300" ? "#c75b39" : "#5fb7ff",
        }}
      >
        <span>{modeLabel(mode)}</span>
        <span style={{ opacity: 0.6 }}>
          rubric source:{" "}
          {mode === "b300" ? "local llama-3-70b nvfp4 (B300)" : "hosted gpt-5.5"}
        </span>
      </div>
      <DispatcherShell />
    </div>
  );
}
