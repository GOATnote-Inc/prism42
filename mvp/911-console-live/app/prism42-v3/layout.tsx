import type { ReactNode } from "react";

// Route-scoped layout for /prism42-v3. Pulls IBM Plex Mono + Plex Sans
// from Google Fonts so the B300 Voice Console aesthetic matches the
// /prism42/livekit page exactly. Root layout keeps its own theme for
// /prism42 and /prism42-v2.

export const metadata = {
  title: "Prism42 v3 · Native Claude · B300 Voice Console",
  description:
    "Plan-C demo surface. Native Claude Sonnet 4.6 inside ElevenLabs ConvAI, styled in the B300 Voice Console visual system.",
};

export default function V3Layout({ children }: { children: ReactNode }) {
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
        href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
      />
      {children}
    </>
  );
}
