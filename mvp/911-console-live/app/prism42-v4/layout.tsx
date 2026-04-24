import type { ReactNode } from "react";

// Route-scoped layout for /prism42-v4. Loads IBM Plex Mono + Plex Sans
// from Google Fonts so the B300 Voice Console "Vision Link" surface
// renders in the same typographic system as /prism42-v3. The root
// layout keeps its own theme for other routes.

export const metadata = {
  title: "Prism42 v4 · Vision Link · B300 Voice Console",
  description:
    "Vision Link demo surface. Same native-Claude voice backend as /prism42-v3, now with a hypothetical drone + robotic vision channel layered over the 911 dispatcher simulation. Detections, tool trace, and robot plan are narrative mocks.",
};

export default function V4Layout({ children }: { children: ReactNode }) {
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
