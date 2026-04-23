import Link from "next/link";

export const metadata = {
  title: "prism42-b300 live — B300 augmented console",
};

// Live-console route stub for /prism42-b300/live. This intentionally does
// not yet render the real DispatcherShell — the augmentations specified
// in docs/spec-b300-voice.md §5.1-5.3 (sub-second local rubric,
// audio-domain OHCA classifier, real-time cross-vendor dialectic) are
// Phase-2 build work. Landing page wires the CTA here so visitors see
// the intended destination, the current state honestly stated, and the
// path forward.
//
// Phase-2 replaces this file with:
//   import { DispatcherShellB300 } from "@/components/DispatcherShellB300";
//   export default function Live() { return <DispatcherShellB300 />; }
export default function Prism42B300LivePlaceholder() {
  return (
    <main className="b300-shell">
      <div
        className="b300-prose"
        style={{ maxWidth: "64ch", paddingTop: "var(--cb-space-8)" }}
      >
        <p
          style={{
            fontFamily: "var(--cb-mono)",
            fontSize: "var(--cb-text-xs)",
            textTransform: "uppercase",
            letterSpacing: "0.12em",
            color: "var(--cb-ink-soft)",
            marginBottom: "var(--cb-space-4)",
          }}
        >
          live console — phase 2 queued
        </p>
        <h1>The augmented console isn&rsquo;t wired yet.</h1>
        <p>
          This URL is the intended destination of the prism42-b300 CTA. It
          ships empty on purpose. Per the charter (
          <code>CLAUDE.md</code> §4), no augmentation reaches a public URL
          until it has landed an L1&ndash;L4 self-verification record on the
          42-scenario red-team fixture:
        </p>
        <ul style={{ paddingLeft: "var(--cb-space-5)", lineHeight: 1.8 }}>
          <li>
            <strong>L1 schema</strong> &mdash; the augmentation&rsquo;s
            structured output parses against its own JSON Schema&nbsp;2020-12.
          </li>
          <li>
            <strong>L2 agreement</strong> &mdash; disagreement with the
            /prism42 baseline &le;&nbsp;5&nbsp;% on the 42 scenarios, logged to{" "}
            <code>findings/b300-disagreement.jsonl</code>.
          </li>
          <li>
            <strong>L3 rubric</strong> &mdash; median rubric-grader score
            non-regression on all 5 GEDP criteria.
          </li>
          <li>
            <strong>L4 latency</strong> &mdash; measured p50 &le; stated p50
            &times; 1.05 on n&thinsp;&ge;&thinsp;100 trials on the target pod.
          </li>
        </ul>
        <p>
          Until then the honest posture is &ldquo;read the evidence, verify
          the math, see the code&rdquo; &mdash; not &ldquo;pretend it&rsquo;s
          live.&rdquo; The continuity claim at /prism42 depends on never
          over-showing.
        </p>
        <div
          style={{
            display: "flex",
            gap: "var(--cb-space-3)",
            marginTop: "var(--cb-space-6)",
          }}
        >
          <Link href="/prism42-b300" className="b300-btn">
            ← Back to the evidence wall
          </Link>
          <Link href="/prism42" className="b300-btn" data-variant="accent">
            Enter /prism42 baseline console
          </Link>
        </div>
      </div>
    </main>
  );
}
