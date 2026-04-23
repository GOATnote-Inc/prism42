import type { Metadata } from "next";
import "./theme.css";

export const metadata: Metadata = {
  title: "prism42-b300 — the augmented dispatch console",
  description:
    "Blackwell Ultra sibling of prism42. Same 20-agent topology and 42-scenario red-team fixture, with sub-second local rubric, audio-domain OHCA classifier, and real-time cross-vendor dialectic.",
};

// Claude-design-themed layout for the B300 sibling demo at
// www.thegoatnote.com/prism42-b300. Intentionally scoped by
// data-theme so /prism42 (dark dispatcher console) and /prism42-b300
// (editorial paper) coexist without leaking styles.
export default function B300Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div data-theme="claude-b300" className="b300-root">
      {children}
    </div>
  );
}
