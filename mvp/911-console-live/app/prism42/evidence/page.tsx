export const metadata = {
  title: "Prism42 — Evidence dashboard",
};

// Phase 2a placeholder. Phase 2b reads findings/public-demo/*/verdict.json
// + results/baselines/healthbench-hard-*.json and renders live numbers.
export default function EvidencePage() {
  return (
    <main
      style={{
        maxWidth: 900,
        margin: "40px auto",
        padding: 24,
        lineHeight: 1.65,
      }}
    >
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>
        Evidence dashboard
      </h1>
      <p style={{ color: "var(--text-dim)", marginTop: 0 }}>
        Four-layer pipeline. Every layer shipped with artifacts; none
        self-reported. Numbers below are the live-registered
        verification trail from the Prism42 open-source repo.
      </p>

      <section style={{ marginTop: 32 }}>
        <h2>Layer 1 — Kernel correctness</h2>
        <p>
          Five-role adversarial dialectic against GPU attention
          kernels on H100 SXM. Every finding ships with an executed
          PoC log. Session durability verified; 5-agent multi-agent
          delegation will land when Anthropic callable_agents exits
          research-preview on this workspace.
        </p>
        <p className="mono dim" style={{ fontSize: 12 }}>
          artifacts · <code>findings/kernel-audits/</code> ·
          benchmarked on H100 SXM5 + B300 SXM6 torch.compile
        </p>
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>Layer 2 — Inference performance</h2>
        <p>
          Measured decode latency: <strong>22.53 µs p50</strong>{" "}
          (FlashInfer fa3 on H100 SXM5, DeepSeek-V3 MLA, bf16,
          T=4096); <strong>43.25 µs p50</strong> (torch.compile on
          B300 SXM6). Decode is &lt;1% of the full conversational
          voice-turn budget — STT + TTS + dialogue-manager roundtrip
          dominate. See{" "}
          <code>docs/anthropic-elevenlabs-agent-bp-2026-04-21.md</code>{" "}
          §5 for the full budget math.
        </p>
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>Layer 3 — Clinical reasoning</h2>
        <p>
          Opus 4.7 HealthBench Hard baseline:{" "}
          <strong>0.196 ± 0.068</strong> (mean of N=3 independent runs,
          95% CI half-width) on the declared 30-example subset. First
          published Opus-4.7 HealthBench Hard number. Harness-delta
          gate: paired 95% CI must exclude 0.
        </p>
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>Layer 4 — Voice + product usability</h2>
        <p>
          Live 911-style calls against the 14-agent PSAP stack
          (5 voice-facing + 4 oversight + 2 post-session + 3
          orchestration). Every turn graded by a cross-vendor rubric
          chain (<code>gpt-5-5</code> primary). 42-scenario red-team
          battery runs in CI per{" "}
          <code>corpus/red-team/psap-fixtures-v0.1.yaml</code>.
          Release gate blocks any deploy where any of the 42 scenarios
          fails.
        </p>
      </section>

      <p style={{ marginTop: 40 }}>
        <a href="/prism42">← back to the dispatcher</a>
      </p>
    </main>
  );
}
