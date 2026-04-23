import Link from "next/link";

// Landing page for /prism42-b300.
//
// Structure follows the analysis in docs/analysis-cost-reliability.md:
//  - hero: the tension (dispatcher burnout + AI reliability gap)
//  - cost wall: per-FTE, per-call, national extrapolation
//  - reliability wall: dispatcher failures cited + Opus 4.7 baseline
//  - what B300 changes: sub-second rubric, audio OHCA, real-time dialectic
//  - continuity: same 20 agents, same 42 scenarios, different latency
//  - CTA: enter live console (/prism42-b300/live — next phase)
//
// Copy is editorial, not marketing. Numbers are cited. No emojis.
export default function Prism42B300Landing() {
  return (
    <>
      <header className="b300-header b300-nav">
        <div className="b300-header-brand">
          prism<em>42</em>-b300
        </div>
        <nav style={{ display: "flex", gap: "var(--cb-space-5)" }}>
          <Link href="/prism42" className="b300-nav" style={{ color: "var(--cb-ink-muted)" }}>
            /prism42 (baseline)
          </Link>
          <span className="b300-tag" data-variant="ok">
            blackwell ultra
          </span>
          <span className="b300-tag">spec · <Link href="https://github.com/GOATnote-Inc/prism42/blob/main/docs/spec-b300-voice.md" style={{ color: "inherit" }}>docs/spec-b300-voice.md</Link></span>
        </nav>
      </header>

      <main className="b300-shell">
        {/* HERO */}
        <section className="b300-prose">
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
            a sibling demo of /prism42, 2026-04-23
          </p>
          <h1>
            Neither a burned-out dispatcher nor a 20&nbsp;% accurate model is
            state of the art for 911.
          </h1>
          <p style={{ fontSize: "var(--cb-text-xl)", color: "var(--cb-ink-muted)", lineHeight: 1.5 }}>
            The dialectic between them is. <strong style={{ color: "var(--cb-ink)" }}>prism42-b300</strong> is the Blackwell-Ultra sibling
            of prism42 that trades latency for additional checks without changing
            which agents run, which scenarios they face, or who has the final word.
          </p>
          <div style={{ display: "flex", gap: "var(--cb-space-3)", marginTop: "var(--cb-space-6)" }}>
            <Link href="/prism42-b300/live" className="b300-btn" data-variant="accent">
              Enter live console →
            </Link>
            <a
              href="https://github.com/GOATnote-Inc/prism42/blob/main/docs/analysis-cost-reliability.md"
              className="b300-btn"
            >
              Read the analysis
            </a>
          </div>
        </section>

        <hr className="b300-rule" />

        {/* COST WALL */}
        <section className="b300-prose">
          <h2>What it costs to run the alternative</h2>
          <p>
            A single fully-loaded 911 dispatcher in the US costs roughly{" "}
            <strong>$195 000 / year</strong> when you roll salary, benefits,
            overhead, and the mandatory 24/7 staffing multiplier into the
            DuPage Public Safety Communications disclosure — an{" "}
            <strong>$17 M annual budget for 87 FTEs serving 850 000 residents</strong>, or about
            {" "}<strong>$20 per resident per year</strong>. A B300 GPU on Verda
            runs <strong>$7.91 / hour</strong>, roughly <strong>$69 k / year</strong> if held
            24/7 — less than one full-time dispatcher.
          </p>

          <table className="b300-table">
            <thead>
              <tr>
                <th>item</th>
                <th data-numeric="true">value</th>
                <th>source</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Dispatcher base salary, US avg</td>
                <td data-numeric="true">$45 k</td>
                <td>911dispatcheredu.org, 2025</td>
              </tr>
              <tr>
                <td>Fully-loaded FTE cost (salary × 1.4)</td>
                <td data-numeric="true">~$63–85 k</td>
                <td>derived</td>
              </tr>
              <tr>
                <td>Per-FTE PSAP budget, DuPage (all-in)</td>
                <td data-numeric="true">$195 k</td>
                <td>NENA disclosure</td>
              </tr>
              <tr>
                <td>Per-capita PSAP cost, DuPage</td>
                <td data-numeric="true">$20 / resident / yr</td>
                <td>$17 M ÷ 850 k</td>
              </tr>
              <tr>
                <td>US 911 call volume</td>
                <td data-numeric="true">~240 M / yr</td>
                <td>NENA</td>
              </tr>
              <tr>
                <td>US PSAP count</td>
                <td data-numeric="true">~5 700</td>
                <td>NENA 2024</td>
              </tr>
              <tr>
                <td>B300 GPU, Brev / Verda on-demand</td>
                <td data-numeric="true">$7.91 / hr</td>
                <td>empirical 2026-04-23</td>
              </tr>
              <tr>
                <td>Annualized B300 cost @ 24/7</td>
                <td data-numeric="true">~$69 k / yr</td>
                <td>derived</td>
              </tr>
            </tbody>
          </table>

          <div className="b300-callout">
            The point is not that a GPU replaces 15 dispatchers. It is that the
            cost-per-check at the augmentation layer is small compared to the
            cost-per-check a human dispatcher represents — which is what makes
            a per-turn second opinion affordable to run on every call.
          </div>
        </section>

        <hr className="b300-rule" />

        {/* RELIABILITY WALL */}
        <section className="b300-prose">
          <h2>What it costs to not have an alternative</h2>
          <p>
            The dispatcher-assisted CPR literature is unsparing. Even with the
            standard script invoked,{" "}
            <strong>~85&nbsp;% of cardiac-arrest calls do not result in proper chest
            compressions</strong> by the caller before EMS arrives
            (Lerner et al., 2008). Cardiac-arrest recognition on
            criteria-based systems tops out around <strong>80&nbsp;%</strong> —
            one in five missed. And the staff catching these calls are in crisis:
          </p>
          <table className="b300-table">
            <thead>
              <tr>
                <th>failure mode</th>
                <th data-numeric="true">rate</th>
                <th>delta vs general pop</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Dispatchers meeting clinical PTSD criteria</td>
                <td data-numeric="true">18.3 %</td>
                <td>~13× general pop (1.4 %)</td>
              </tr>
              <tr>
                <td>Dispatchers with high burnout on ≥ 1 measure</td>
                <td data-numeric="true">43 %</td>
                <td>higher than nurses, physicians, teachers</td>
              </tr>
              <tr>
                <td>Emergency centers observing staff burnout (2023)</td>
                <td data-numeric="true">74 %</td>
                <td>NENA survey</td>
              </tr>
              <tr>
                <td>Annual dispatcher turnover</td>
                <td data-numeric="true">19 %→ 30 %+</td>
                <td>2009 to recent</td>
              </tr>
              <tr>
                <td>Vacancy rate in typical 911 center</td>
                <td data-numeric="true">20–30 %</td>
                <td>APCO / Bridge MI</td>
              </tr>
            </tbody>
          </table>

          <p>
            Claude is no savior here. Our own measured baseline — published in
            this repo —{" "}
            <strong>Opus 4.7 scores 0.196 ± 0.068 on HealthBench Hard</strong>{" "}
            (mean of N = 3 independent runs, 95 % CI half-width, 30-example
            subset, 2026-04-22). That is a reliability floor, not a ceiling.
          </p>

          <div className="b300-callout">
            So neither is sufficient alone. Both have failure modes the other
            catches. The augmentation layer — the 20 agents, the 42
            red-team scenarios, the GEDP v0.1 protocol, the structured-JSON gate
            — is the reliability engine. prism42-b300 makes three of its checks
            faster.
          </div>
        </section>

        <hr className="b300-rule" />

        {/* WHAT B300 CHANGES */}
        <section className="b300-prose">
          <h2>Three things Blackwell Ultra unlocks</h2>

          <h3>1. Sub-second rubric grade, inside the turn</h3>
          <p>
            At prism42 baseline, the rubric grader (GPT-5.5 hosted) lands
            <strong> 2–4 seconds behind real-time</strong>. That means a
            dispatcher hears a suggestion, speaks it, and only then learns
            whether the rubric flagged it. At B300 we run the grader locally
            on Llama-3-70B NVFP4 targeting{" "}
            <strong>p50 ≤ 800 ms</strong>. The rubric score arrives{" "}
            <em>before</em> the utterance ships to TTS — a new intervention
            class: pre-TTS gating, not post-hoc audit.
          </p>

          <h3>2. Continuous on-device OHCA classifier</h3>
          <p>
            Today the out-of-hospital cardiac arrest (OHCA) detector runs on
            the transcript, which loses agonal respiration, gasping, the thud
            of a collapse. On B300 a small audio-domain classifier runs at
            ~30 ms sliding-window cadence alongside the Parakeet-RNNT
            streaming STT, gated behind a five-check false-positive discipline
            (threshold, hysteresis, transcript cross-check, rubric
            confirmation, physician audit trail).
          </p>

          <h3>3. Real-time cross-vendor dialectic</h3>
          <p>
            Opus 4.7 and GPT-5.5 consume the same dispatcher context
            concurrently. A deterministic reconciler policy — always prefer
            the higher-severity action; on action-type disagreement, default
            to <em>verify</em> — decides which reaches the caller.
            Disagreement itself becomes a flag in the dispatcher UI,
            surfacing model-framing differences a sequential grader cannot.
            Neither model is the authority; the policy is.
          </p>
        </section>

        <hr className="b300-rule" />

        {/* CONTINUITY */}
        <section className="b300-prose">
          <h2>What does not change</h2>
          <p>
            GEDP v0.1 protocol. The 20 agents. SP-001–SP-010 safety preambles.
            The 42-scenario red-team fixture. The structured-JSON gate that
            every turn must pass before a caller hears it. The continuity
            claim at /prism42. This is a sibling demo, not a replacement —
            augmentations are additive, each with its own L1–L4
            self-verification record, each landed before the public URL
            serves it.
          </p>

          <div style={{ display: "flex", gap: "var(--cb-space-3)", marginTop: "var(--cb-space-6)" }}>
            <Link href="/prism42-b300/live" className="b300-btn" data-variant="accent">
              Enter live console →
            </Link>
            <a
              href="https://github.com/GOATnote-Inc/prism42/blob/main/docs/spec-b300-voice.md"
              className="b300-btn"
            >
              Read the spec
            </a>
          </div>
        </section>

        <hr className="b300-rule" />

        <footer
          className="b300-nav"
          style={{
            color: "var(--cb-ink-soft)",
            fontSize: "var(--cb-text-xs)",
            display: "flex",
            justifyContent: "space-between",
            padding: "var(--cb-space-6) 0",
          }}
        >
          <span>
            GOATnote · prism42-b300 · MIT · {new Date().getFullYear()}
          </span>
          <span>
            This is a simulation. Not a 911 service. Do not call this URL
            for emergencies.
          </span>
        </footer>
      </main>
    </>
  );
}
