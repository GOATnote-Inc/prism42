import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Prism42 — LiveKit + B300 Dispatcher Console",
  description:
    "Live 911 dispatcher console on Claude Opus 4.7 via LiveKit + Cartesia + Deepgram, self-hosted on B300 Blackwell Ultra. Synthetic-fixture demo.",
};

// Layout scoped to /prism42/livekit. Injects IBM Plex Mono + Sans
// from Google Fonts once. Root layout's simulation-banner still
// renders above this subtree.
export default function LiveKitLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      {/* Next.js hoists these into <head> automatically. */}
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link
        rel="preconnect"
        href="https://fonts.gstatic.com"
        crossOrigin=""
      />
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
      />
      {children}
    </>
  );
}
