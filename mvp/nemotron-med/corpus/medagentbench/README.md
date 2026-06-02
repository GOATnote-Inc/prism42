# corpus/medagentbench

Pointer-only directory for the **MedAgentBench** benchmark. No local
clone. No corpus files shipped. This README is the single source of
truth for where MedAgentBench lives and what Prism's posture is.

## Upstream

- **Maintainer:** Stanford ML Group (Rohan Nagpal, Yixin Zhang,
  Shreya Johri, Yun Liu, Alaa Youssef, Andrew Y. Ng, Pranav Rajpurkar).
- **Source repository:** `https://github.com/stanfordmlgroup/MedAgentBench`
- **Docker image:** `jyxsu6/medagentbench:8080` — ships a mock FHIR
  server for agent-tool calls. Port 8080 inside the container.
- **Leaderboard:** `https://stanfordmlgroup.github.io/medagentbench/`
- **Preprint:** arXiv:2501.14654 (Jiang et al., 2026). *"MedAgentBench:
  A Realistic Virtual EHR Environment to Benchmark Medical LLM Agents."*
- **License:** Apache-2.0 (upstream repo).

## Why Prism references but does not clone

MedAgentBench is a **FHIR-side-effect benchmark**: the scorer inspects
HTTP traffic to a mock EHR server, not text. Running it requires the
Docker image on localhost, then driving the agent with tool-use loops
that issue FHIR `GET/POST/PUT` calls. This has three implications for
Prism:

1. The benchmark is not offline-verifiable. The L5 CI (`make verify`)
   has no live services; we keep it that way.
2. Running it costs both Docker host time and Claude API spend. Prism's
   hackathon budget reserves the MedAgentBench run for the **H1 epic**
   in `docs/sota-portfolio.md`, not the Apr 22-26 sprint.
3. The scorer is public and the Docker image is public. Prism's
   contribution is not re-implementing the benchmark; it is **running
   Opus 4.7** through the Prism coordinator harness against the public
   Docker server and publishing the delta vs stock Opus 4.7. Cloning
   the benchmark corpus locally would duplicate upstream without
   adding signal.

## Prism's H1 posture

When H1 executes:

1. `make setup-third-party` clones `stanfordmlgroup/MedAgentBench` into
   `third_party/MedAgentBench/` at a pinned SHA (analogous to the
   `simple-evals` bridge in `scripts/_healthbench_grader_bridge.py`).
2. `docker pull jyxsu6/medagentbench:8080` runs on the H100 workstation;
   container is localhost-only (no public port).
3. `scripts/medagentbench_runner.py` (new at H1) drives Opus 4.7 through
   the Prism coordinator harness with the `agent_toolset_20260401` tool
   bound to the local FHIR endpoints. Gated by the standard double-gate
   (`--commit` + `PRISM_MEDAGENTBENCH_COMMIT=1`).
4. Results land under `results/medagentbench-opus47-<date>/` with the
   raw HTTP trace, the scorer's verdict, and a seed-stability record.
5. Number goes into `docs/opus47-baseline-card.md` — this is the first
   public Opus 4.7 number on MedAgentBench (public baseline as of
   2026-04-22 is Claude 3.5 Sonnet v2 at 69.67%).

## Explicit non-goals for Apr 22-26

- Do **not** clone the benchmark into this directory.
- Do **not** add a `medagentbench_runner.py` this sprint.
- Do **not** cite a MedAgentBench number in the submission README; the
  baseline card row stays `not reported by Anthropic` with the Stanford
  leaderboard's 3.5 Sonnet v2 number as the only public anchor.

## Cross-reference

- `docs/opus47-baseline-card.md` — MedAgentBench row (anchors this file).
- `docs/sota-portfolio.md` — H1 epic definition.
- `scripts/_healthbench_grader_bridge.py` — pinned-clone pattern Prism
  uses for third-party scorers; same pattern applies at H1.
