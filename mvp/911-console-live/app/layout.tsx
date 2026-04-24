import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Prism42 — Live PSAP Console",
  description:
    "GOATnote Prism42 — a public 911-call-center demonstration powered by Claude Opus 4.7 Managed Agents, ElevenLabs Conversational AI, and GEDP v0.1 (the GOATnote Emergency Dispatch Protocol). Synthetic-fixture demo. Not a medical device. Not a substitute for 911.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "Prism42 — Live PSAP Console",
    description:
      "Public 911-call-center demonstration. Synthetic fixtures only. Clinical director: Brandon Dent, MD (GOATnote Inc.).",
    type: "website",
    siteName: "GOATnote",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="simulation-banner" role="note">
          <strong>Simulation</strong> — synthetic demo, not a real
          emergency line. For a real emergency, hang up and dial 911.
        </div>
        {children}
      </body>
    </html>
  );
}
