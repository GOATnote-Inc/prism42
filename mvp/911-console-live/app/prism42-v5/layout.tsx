import type { ReactNode } from "react";

// Route-scoped layout for /prism42-v5 — "PSAP 2031" speculative console.
// Same IBM Plex Mono + Plex Sans as v3 so the B300 Voice Console aesthetic
// carries through. V5 is a speculative vision piece — every panel except
// the live-voice channel is a high-fidelity mock of what a unified 911
// dispatch supervisor console looks like 5 years out.

export const metadata = {
  title: "Prism42 v5 · PSAP 2031 · Supervisor Console",
  description:
    "Speculative 5-year-out 911 dispatch console. One supervisor, twelve concurrent AI-handled calls, predictive triage, cross-PSAP pattern feed, closed-loop callback, and evidence-chain audit. The v3 live-voice channel is real; everything around it is the vision.",
};

export default function V5Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link
        rel="preconnect"
        href="https://fonts.gstatic.com"
        crossOrigin="anonymous"
      />
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap"
      />
      {children}
    </>
  );
}
