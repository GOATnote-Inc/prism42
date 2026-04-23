export const metadata = {
  title: "Prism42 — Safety + IRB trajectory",
};

export default function SafetyPage() {
  return (
    <main
      style={{
        maxWidth: 760,
        margin: "40px auto",
        padding: 24,
        lineHeight: 1.65,
      }}
    >
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>
        Safety posture + IRB trajectory
      </h1>
      <p style={{ color: "var(--text-dim)", marginTop: 0 }}>
        GOATnote Prism42 is a synthetic-fixture public demo. It is not
        a medical device, not FDA-cleared, not CDS-exempt, not a
        substitute for calling 911 on a real phone.
      </p>

      <h2>Safety preambles (SP-001 through SP-010)</h2>
      <p>
        Every voice-facing agent is bound to ten preambles rooted in
        the repo's <code>docs/safety-preambles.md</code>:
      </p>
      <ul>
        <li>SP-001 — simulation disclosure + terminal refusal on real-emergency claim</li>
        <li>SP-002 — scope: GEDP v0.1 (MIT) only; no MPDS / IAED content</li>
        <li>SP-003 — PHI refusal (no SSN, no insurance, no full DOB)</li>
        <li>SP-004 — no dosing, no diagnosis, no medication advice</li>
        <li>SP-005 — no fabrication under uncertainty (defer instead)</li>
        <li>SP-006 — structured-JSON self-verify gate on every turn</li>
        <li>SP-007 — 12-minute session budget + latency-breach alert</li>
        <li>SP-008 — 988 guided-redirect for suicidal ideation (3-step script)</li>
        <li>SP-009 — verbatim refusal templates</li>
        <li>SP-010 — post-session audit consent disclosed during intake</li>
      </ul>

      <h2>Cross-vendor grader independence</h2>
      <p>
        Every voice turn is graded against five HealthBench
        Hard-aligned criteria by a <em>different-vendor</em> model so
        the voice-facing agent can't grade itself. Primary:{" "}
        <code>gpt-5-5</code> (OpenAI, runtime chat-completion call
        outside Managed Agents). Fallback: <code>gpt-5-4</code>.
        Emergency shim: <code>claude-opus-4-7</code> (raises{" "}
        <code>self_grade_flag</code>; session score becomes
        non-load-bearing for published baselines).
      </p>

      <h2>IRB trajectory</h2>
      <ol>
        <li>
          <strong>Phase 0 — Synthetic fixtures (now).</strong> No PHI.
          42-scenario red-team battery runs in CI; all voice-facing
          agents emit structured JSON under{" "}
          <code>schemas/psap-turn.schema.json</code>.
        </li>
        <li>
          <strong>Phase 1 — IRB pilot.</strong> Protocol{" "}
          <code>2026-GN-PSAP-001</code> (drafted). One PSAP, clinical
          director on every shift, AI surfaces logged but not
          load-bearing.
        </li>
        <li>
          <strong>Phase 2 — Prospective outcome study.</strong>{" "}
          Paired pre/post at 2–3 PSAPs. Secondary outcomes:
          time-to-determinant, T-CPR delivery rate, GEDP adherence,
          OHCA first-minute recognition.
        </li>
        <li>
          <strong>Phase 3 — Pre-submission + SaMD filing.</strong> FDA
          510(k) or De Novo depending on clinical-decision-support
          classification. Class II SaMD target.
        </li>
      </ol>

      <h2>Clinical direction</h2>
      <p>
        Developed under the direction of{" "}
        <strong>Brandon Dent, MD</strong> (emergency medicine) as
        clinical director of GOATnote Inc. Clinical-content changes to
        <code> docs/dispatch-protocol-v0.1.md</code> require physician
        re-signature; the CI safety-expert agent enforces this gate.
      </p>

      <h2>Responsible-disclosure posture</h2>
      <p>
        Model-behavior observations route through{" "}
        <code>docs/clinical-handling.md</code>: physician review first,
        Anthropic feedback channel second, research venue third.
        Never public-issue-tracker, never social media.
      </p>

      <p style={{ marginTop: 40 }}>
        <a href="/prism42">← back to the dispatcher</a>
      </p>
    </main>
  );
}
