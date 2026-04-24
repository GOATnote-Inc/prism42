import Link from "next/link";
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export const dynamic = "force-dynamic";
export const revalidate = 30;

export const metadata = {
  title: "prism42-b300 · comparison wall",
};

type Gates = Record<string, { value: number; gate: number; pass: boolean }>;

interface ModeSummary {
  rows: number;
  latency: {
    primary_p50: number | null;
    primary_p90: number | null;
    primary_p99: number | null;
    shadow_p50: number | null;
    shadow_p90: number | null;
    shadow_p99: number | null;
    ratio_median: number | null;
    ratio_mean: number | null;
    ratio_p90: number | null;
  };
  agreement: {
    agreed_turns: number;
    total_turns: number;
    agreement_rate: number;
  };
  bias_by_axis: Record<
    string,
    { mean_signed_delta: number; ci95_halfwidth: number; n: number }
  >;
  failure_counts: Record<string, number>;
  seed_variance: { mean_std_of_weighted: number; max_std_of_weighted: number };
}

interface Summary {
  generated_at: string;
  input_file: string;
  input_rows: number;
  modes_present: string[];
  per_mode: Record<string, ModeSummary>;
  gates: { verdicts?: Gates };
}

function loadLatestSummary(): Summary | null {
  const dir = resolve(process.cwd(), "findings");
  let files: string[];
  try {
    files = readdirSync(dir);
  } catch {
    return null;
  }
  const summaries = files
    .filter((f) => f.startsWith("comparison-summary-") && f.endsWith(".json"))
    .sort()
    .reverse();
  if (!summaries.length) return null;
  try {
    return JSON.parse(
      readFileSync(resolve(dir, summaries[0]), "utf8"),
    ) as Summary;
  } catch {
    return null;
  }
}

function fmtMs(v: number | null | undefined): string {
  if (typeof v !== "number") return "—";
  return `${Math.round(v)} ms`;
}
function fmtRatio(v: number | null | undefined): string {
  if (typeof v !== "number") return "—";
  return v.toFixed(3);
}
function fmtPct(v: number | null | undefined): string {
  if (typeof v !== "number") return "—";
  return `${(v * 100).toFixed(1)}%`;
}
function fmtSigned(v: number | null | undefined): string {
  if (typeof v !== "number") return "—";
  return v >= 0 ? `+${v.toFixed(4)}` : v.toFixed(4);
}

const CRITERIA = [
  { key: "R1_clinical_accuracy", label: "R1 clinical accuracy", weight: 0.4 },
  { key: "R2_scope_adherence", label: "R2 scope adherence", weight: 0.2 },
  { key: "R3_safety_preservation", label: "R3 safety preservation", weight: 0.2 },
  { key: "R4_clarity_for_caller", label: "R4 clarity for caller", weight: 0.1 },
  { key: "R5_protocol_adherence", label: "R5 protocol adherence", weight: 0.1 },
];

export default function Prism42B300ComparePage() {
  const summary = loadLatestSummary();

  if (!summary) {
    return (
      <main className="b300-shell">
        <div className="b300-prose" style={{ paddingTop: "var(--cb-space-8)" }}>
          <p
            style={{
              fontFamily: "var(--cb-mono)",
              fontSize: "var(--cb-text-xs)",
              textTransform: "uppercase",
              letterSpacing: "0.12em",
              color: "var(--cb-ink-soft)",
            }}
          >
            comparison wall — empty state
          </p>
          <h1>No comparison runs yet.</h1>
          <p>
            This page reads the most recent{" "}
            <code>findings/comparison-summary-*.json</code> written by{" "}
            <code>scripts/compare_metrics.mjs</code>. To populate:
          </p>
          <pre
            style={{
              background: "var(--cb-bg-sunk)",
              padding: "var(--cb-space-4)",
              borderRadius: "var(--cb-radius-md)",
              fontSize: "var(--cb-text-sm)",
              overflowX: "auto",
            }}
          >
{`# 1. Provision B300 vLLM endpoint (see scripts/b300_setup_rubric.sh)
export PRISM42_B300_RUBRIC_URL=http://localhost:8000/v1/chat/completions
export OPENAI_API_KEY=sk-...

# 2. Run A/B on the 42-scenario fixture
cd mvp/911-console-live
node scripts/run_fixture_compare.mjs --mode=vercel --seeds=1,2,3
node scripts/run_fixture_compare.mjs --mode=b300  --seeds=1,2,3

# 3. Aggregate
node scripts/compare_metrics.mjs \\
  --in=findings/comparison.jsonl \\
  --out=findings/comparison-summary-$(date +%Y%m%dT%H%M%SZ).json`}
          </pre>
          <div
            style={{
              display: "flex",
              gap: "var(--cb-space-3)",
              marginTop: "var(--cb-space-6)",
            }}
          >
            <Link href="/prism42-b300" className="b300-btn">
              ← Evidence wall
            </Link>
            <Link href="/prism42-b300/live" className="b300-btn">
              Live console
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const b300 = summary.per_mode.b300;
  const vercel = summary.per_mode.vercel;
  const verdicts = summary.gates.verdicts ?? {};
  const allPass = Object.values(verdicts).every((v) => v.pass);

  return (
    <main className="b300-shell">
      <section className="b300-prose" style={{ maxWidth: "78ch" }}>
        <p
          style={{
            fontFamily: "var(--cb-mono)",
            fontSize: "var(--cb-text-xs)",
            textTransform: "uppercase",
            letterSpacing: "0.12em",
            color: "var(--cb-ink-soft)",
          }}
        >
          comparison wall · {summary.generated_at}
        </p>
        <h1>
          {allPass ? "Signal: pass." : "Signal: fail."} Evidence below.
        </h1>
        <p>
          Single-variable A/B on the 42-scenario red-team fixture
          (canonical turns per scenario × 3 seeds × 2 modes =&nbsp;
          <code>{summary.input_rows}</code> log rows). The only variable
          is the rubric-grader source: hosted GPT-5.5 (Vercel baseline)
          vs Llama-3-70B NVFP4 on B300 (augmented path).
        </p>

        {/* GATES */}
        <h2>Gates</h2>
        <table className="b300-table">
          <thead>
            <tr>
              <th>gate</th>
              <th data-numeric="true">observed</th>
              <th data-numeric="true">threshold</th>
              <th>verdict</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(verdicts).map(([name, v]) => (
              <tr key={name}>
                <td>{name}</td>
                <td data-numeric="true">
                  {typeof v.value === "number" ? v.value.toFixed(4) : "—"}
                </td>
                <td data-numeric="true">{v.gate}</td>
                <td>
                  <span
                    className="b300-tag"
                    data-variant={v.pass ? "ok" : "critical"}
                  >
                    {v.pass ? "pass" : "fail"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* LATENCY */}
        <h2>Latency</h2>
        <table className="b300-table">
          <thead>
            <tr>
              <th>mode</th>
              <th data-numeric="true">primary p50</th>
              <th data-numeric="true">p90</th>
              <th data-numeric="true">p99</th>
              <th data-numeric="true">shadow p50</th>
              <th data-numeric="true">ratio (median)</th>
            </tr>
          </thead>
          <tbody>
            {vercel && (
              <tr>
                <td>vercel</td>
                <td data-numeric="true">{fmtMs(vercel.latency.primary_p50)}</td>
                <td data-numeric="true">{fmtMs(vercel.latency.primary_p90)}</td>
                <td data-numeric="true">{fmtMs(vercel.latency.primary_p99)}</td>
                <td data-numeric="true">{fmtMs(vercel.latency.shadow_p50)}</td>
                <td data-numeric="true">
                  {fmtRatio(vercel.latency.ratio_median)}
                </td>
              </tr>
            )}
            {b300 && (
              <tr>
                <td>b300</td>
                <td data-numeric="true">{fmtMs(b300.latency.primary_p50)}</td>
                <td data-numeric="true">{fmtMs(b300.latency.primary_p90)}</td>
                <td data-numeric="true">{fmtMs(b300.latency.primary_p99)}</td>
                <td data-numeric="true">{fmtMs(b300.latency.shadow_p50)}</td>
                <td data-numeric="true">
                  {fmtRatio(b300.latency.ratio_median)}
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {/* AGREEMENT + FAILURE TYPES */}
        <h2>Agreement + failure types</h2>
        <table className="b300-table">
          <thead>
            <tr>
              <th>mode</th>
              <th data-numeric="true">agreement |Δ|≤0.2 on all 5</th>
              <th data-numeric="true">none</th>
              <th data-numeric="true">disagreement</th>
              <th data-numeric="true">drift</th>
              <th data-numeric="true">latency</th>
              <th data-numeric="true">timeout</th>
              <th data-numeric="true">error</th>
            </tr>
          </thead>
          <tbody>
            {(["vercel", "b300"] as const).map((m) => {
              const s = summary.per_mode[m];
              if (!s) return null;
              return (
                <tr key={m}>
                  <td>{m}</td>
                  <td data-numeric="true">
                    {fmtPct(s.agreement.agreement_rate)} (
                    {s.agreement.agreed_turns}/{s.agreement.total_turns})
                  </td>
                  <td data-numeric="true">{s.failure_counts.none}</td>
                  <td data-numeric="true">{s.failure_counts.disagreement}</td>
                  <td data-numeric="true">{s.failure_counts.drift}</td>
                  <td data-numeric="true">{s.failure_counts.latency}</td>
                  <td data-numeric="true">{s.failure_counts.timeout}</td>
                  <td data-numeric="true">{s.failure_counts.error}</td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {/* BIAS BY AXIS */}
        {b300 && (
          <>
            <h2>Direction bias by axis (B300 mode)</h2>
            <p style={{ fontSize: "var(--cb-text-sm)", color: "var(--cb-ink-muted)" }}>
              Signed mean delta (primary − shadow) per criterion, with 95% CI half-width.
              Positive = B300 rubric scored higher than hosted; negative = lower.
              Gate: |mean signed delta| ≤ 0.2 on every axis.
            </p>
            <table className="b300-table">
              <thead>
                <tr>
                  <th>criterion</th>
                  <th data-numeric="true">weight</th>
                  <th data-numeric="true">mean signed Δ</th>
                  <th data-numeric="true">95% CI ±</th>
                  <th data-numeric="true">n</th>
                </tr>
              </thead>
              <tbody>
                {CRITERIA.map((c) => {
                  const b = b300.bias_by_axis[c.key];
                  return (
                    <tr key={c.key}>
                      <td>{c.label}</td>
                      <td data-numeric="true">{c.weight}</td>
                      <td data-numeric="true">
                        {fmtSigned(b?.mean_signed_delta)}
                      </td>
                      <td data-numeric="true">
                        {b?.ci95_halfwidth?.toFixed?.(4) ?? "—"}
                      </td>
                      <td data-numeric="true">{b?.n ?? 0}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        {/* SEED VARIANCE */}
        <h2>Seed variance</h2>
        <p style={{ fontSize: "var(--cb-text-sm)", color: "var(--cb-ink-muted)" }}>
          Mean std of primary-grader weighted score across the 3 seeds for each
          (scenario, turn) tuple. Higher = rubric output more seed-sensitive
          within the same input.
        </p>
        <table className="b300-table">
          <thead>
            <tr>
              <th>mode</th>
              <th data-numeric="true">mean std</th>
              <th data-numeric="true">max std</th>
            </tr>
          </thead>
          <tbody>
            {(["vercel", "b300"] as const).map((m) => {
              const s = summary.per_mode[m];
              if (!s) return null;
              return (
                <tr key={m}>
                  <td>{m}</td>
                  <td data-numeric="true">
                    {s.seed_variance.mean_std_of_weighted?.toFixed?.(4) ?? "—"}
                  </td>
                  <td data-numeric="true">
                    {s.seed_variance.max_std_of_weighted?.toFixed?.(4) ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <hr className="b300-rule" />

        <div
          style={{
            display: "flex",
            gap: "var(--cb-space-3)",
            flexWrap: "wrap",
          }}
        >
          <Link href="/prism42-b300" className="b300-btn">
            ← Evidence wall
          </Link>
          <Link href="/prism42-b300/live" className="b300-btn">
            Live console
          </Link>
          <Link href="/prism42-b300/live?mode=b300" className="b300-btn" data-variant="accent">
            Live console (B300 mode)
          </Link>
        </div>

        <footer
          className="b300-nav"
          style={{
            color: "var(--cb-ink-soft)",
            fontSize: "var(--cb-text-xs)",
            marginTop: "var(--cb-space-8)",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>input: {summary.input_file}</span>
          <span>rows: {summary.input_rows}</span>
        </footer>
      </section>
    </main>
  );
}
