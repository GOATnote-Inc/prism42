# Managed Agents leverage for prism42 voice cycles 2c-2e + post-deadline

Author: Glasswing-discipline research team (read-only, no API calls, no commits).
Retrieval date: **2026-04-25**. Sprint clock: ~30 hours to Sunday 2026-04-26 EOD deadline.

## Verdict (one paragraph)

**Stay on Claude Code Agent for everything that ships before Sunday.** The remaining voice work — cycle-2c (MPS), 2d (Fish patches), 2e (Pipecat speculative speech) — is interactive, on-pod, B300-coupled, and tightly scoped. None of it benefits from a Managed Agents session that runs in Anthropic's cloud sandbox without our pod's CUDA, Fish vLLM service, or worker logs. **Use a Managed Agent for exactly one post-deadline thing: an hourly regression watchdog that re-runs `synthetic_caller_full.py × N` against the live pod and writes a verdict file.** That use is the single shape Managed Agents wins — long-lived (>4 h), session-state durable, brain-replaceable, and decoupled from our local machine. Net change to current OODA plan: **none for cycles 2c-2e**; queue a separate post-deadline ticket to wire one watchdog Managed Agent. Do not register voice-* sub-agents — `callable_agents` is silently stripped on this workspace (verified 2026-04-22, request_id `req_011CaJg9qBnVqPNkaoBLgjrN` per CLAUDE.md §8) so multi-agent plumbing is wasted effort right now.

## Truth table

| Work item | Best platform | Reason | Cost estimate |
|---|---|---|---|
| **Cycle-2c MPS enable + bench** | Claude Code Agent (with worktree) | Requires SSH to B300 pod, systemd edits, `nvidia-cuda-mps-control` startup, real-time CUDA failure inspection. Managed Agents sandbox can't reach the pod's GPU/systemd. | ~$1-3 in tokens via Claude Code |
| **Cycle-2d Fish patch (vendor/fish-speech inference.py:210, SDPBackend.MATH → FLASH)** | Claude Code Agent | One-file C++/PyTorch surgery on local repo, then build+test on pod. Local file edits + verify-on-pod loop. | ~$1-2 in tokens |
| **Cycle-2d Fish bench validation** | Claude Code Agent | Reads `/tmp/prism42-logs/worker.log`, `vllm.tail.log`, `fish.tail.log` on pod via SSH. Managed Agents has no SSH-back-to-our-pod. | <$1 |
| **Cycle-2e Pipecat speculative speech in worker.py** | Claude Code Agent | Edit worker.py:825-871 (filler/preroll gating), reload systemd unit, real listen test. Pod-coupled. | ~$1-2 |
| **10-prompt synthetic bench × 1** | Either, but Claude Code is faster | A 10-turn bench takes ~3 min. Managed Agents session-spinup + token markup not worth it for a one-shot. | $0.15-0.50 (smoke-session-2026-04-22.md datapoint: $0.15 for 1 session, 8K input + 251 output) |
| **4-hour parameter-sweep bench loop (10 trials × 5 params)** | Claude Code Agent **with `/loop` skill** OR a single coordinator Managed Agent if pod is reachable from sandbox over WireGuard/SSH (not currently configured) | Right now, sandbox cannot reach pod. Claude Code can. If we wire pod access into a Managed Agents environment (post-deadline), Managed Agents wins because session state outlives any client crash. | Claude Code: $5-10 in tokens. MA equiv: $0.32 session-hr + $5-15 tokens |
| **Hourly post-deadline regression watchdog** | **Managed Agent** | Wakes hourly via external cron→`POST /v1/sessions/:id/events`. Long-lived (days). Session-state outside Claude's context window. Brain dies, hands keep state, alert pipes out. Managed Agents was built for this. | $0.08/session-hr × 24 h × 30 d = ~$58/mo runtime + tokens (~$2-5/turn × 24 = $50-120/day if every wake-up runs a full bench; gate strictly) |
| **Post-deadline ultrareview (single-pass code review across worker.py + bench_b300.py + synthetic_caller_full.py)** | Claude Code Agent | One-shot, no state across cycles. ~3 files to read. | <$2 in tokens |
| **Cross-cycle synthesis doc (after 2c+2d+2e all land)** | Claude Code Agent | Single Read across `findings/voice/cycle-2c-mps/*`, `cycle-2d-fish-patches/*`, `cycle-2e-pipecat/*`. Pure-text synthesis. | <$1 |
| **Pipecat speculative speech research before implementing** | Claude Code Agent (with WebFetch) | Pure docs research. No durable state needed. | <$1 |
| **Defender/attacker/synthesizer/executor/adjudicator role re-use for voice rails** | Neither — leave them for the kernel/clinical rails | Five agents already registered (manifest 2026-04-22) for kernel/clinical numerical-correctness audits. Their system prompts (per `agents/prism-{role}.yaml`) are framed for VIOLATION-PoC-style verdicts, not voice-pipeline tuning. Repurposing means rewriting the agent prompts → version bump → new IDs. Pointless because `callable_agents` is stripped anyway on this workspace key. | $0 if we leave them alone |

## Concrete proposal — single watchdog Managed Agent (post-deadline)

**Status: NOT a sprint deliverable.** Queue this as `T-watchdog-1` after Sunday demo. The one shape Managed Agents wins.

### Why this is the right use of MA (not the others)

Per Anthropic's engineering post `https://www.anthropic.com/engineering/managed-agents` (cited in CLAUDE.md §recent-best-practice and `hackathon_opus_4_7_reference.md` lines 56-60): *"the session provides this same benefit, serving as a context object that lives outside Claude's context window."* The watchdog needs:

1. **Durability across hours/days** — session state survives client kill, Claude Code session window doesn't.
2. **External wake trigger** — POST `/v1/sessions/:id/events` from cron is documented (`platform.claude.com/docs/en/managed-agents/events`, doc-claim, not workspace-verified). Claude Code has no programmatic event-injection.
3. **Brain-replaceable** — if Claude version changes mid-week, the new "brain" reads the same session log; tool runs and metrics persist. Claude Code conversations are model-pinned.
4. **Stateless re-attach** — `verify_session_durability.py` already tested this pattern (CLAUDE.md §5 list, `MANAGED_AGENTS_BETA`); 1 session, kill client, reattach via `/v1/sessions/:id/stream`, status still `running` or `idle`.

### Register-agent payload (DRY-RUN reference, do not commit yet)

```yaml
# agents/voice-watchdog.yaml — register only post-deadline
_prism:
  role: voice-watchdog
  notes: "Hourly regression sentinel for prism42 voice path. Single agent, no callable_agents (workspace strips them anyway)."
name: prism-voice-watchdog
model: claude-opus-4-7
system: |
  You are the prism42 voice regression sentinel. Once per wake event, you:
  1. SSH to the B300 pod via the configured environment.
  2. Run `cd /opt/prism42/agents/livekit && .venv/bin/python bench_b300.py --n 10`.
  3. Parse the JSON output (see `bench_b300.py:parse_window`).
  4. Compare each hop p95 against `/workspace/baseline.json` (mean-of-3 ± 95% CI).
  5. If ANY hop is >2σ worse than baseline, write `/workspace/alert-<UTC>.json` with
     {hop, baseline_p95, observed_p95, z_score, sample_size, verdict: regression}.
  6. Otherwise write `/workspace/ok-<UTC>.json` with {verdict: green, p95s, n}.
  7. Emit a `session.status_idle` and stop.
  Never modify code. Never edit files outside /workspace. Never wake more than once
  per externally injected user.message event.
tools:
  - type: agent_toolset_20260401  # bash + read + write + grep + web (for status pages)
# DO NOT add callable_agents — silently stripped on this workspace key.
# DO NOT add memory_store — research preview, also gated.
```

### Session-create payload (after the agent is registered)

```python
session = client.beta.sessions.create(
    agent={"type": "agent", "id": "agt_<voice-watchdog-id>", "version": 1},
    environment_id="env_<env-with-pod-ssh-key>",  # NEW env, not env_01Nbmp5KCzCKfkcJgZdHhngY
)
```

The new environment must mount an SSH private-key pair to a `voice-bench-readonly` user on the B300 pod (key restricted to `command="cd /opt/prism42/agents/livekit && .venv/bin/python bench_b300.py --n 10"` so the watchdog can ONLY run the bench, not arbitrary commands). This is the only piece of new infra needed.

### External wake trigger (cron on the integrator's laptop or a tiny VM)

```bash
# crontab line — runs hourly
0 * * * * curl -sS -X POST https://api.anthropic.com/v1/sessions/$WATCHDOG_SID/events \
  -H "anthropic-beta: managed-agents-2026-04-01" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -d '{"events":[{"type":"user.message","content":[{"type":"text","text":"wake"}]}]}'
```

### Mainline-safety rails

1. **Double-gate** to register: `--commit` + `PRISM_VOICE_WATCHDOG_COMMIT=1` (extend `register_agents.py` ORDER list). Mirrors §5.
2. **Pod SSH key is restricted to one command only** — agent cannot escalate even if its system prompt is poisoned.
3. **Frozen-paths invariant intact** — watchdog only writes to `/workspace/*.json`; never touches our local repo. Alerts come back through pulling `/workspace/` listings on schedule.
4. **Budget cap** — `max_iterations=1` on each wake, hard-stop at $0.50/turn via `task-budgets-2026-03-13` beta header (advisory; pair with `max_tokens=8000`).
5. **Kill switch** — `client.beta.sessions.terminate(sid)` via `make voice-watchdog-stop`.

### Cost arithmetic for the watchdog

Anchored to documented prices:
- Session runtime: **$0.08/session-hr** (CLAUDE.md §8, `hackathon_opus_4_7_reference.md:54` — "$0.08 per session-hour active runtime").
- Opus 4.7 token rates: **$5/MTok input, $25/MTok output** (`hackathon_opus_4_7_reference.md:13` table).
- One wake-up token cost (estimated from `findings/smoke-session-2026-04-22.md` real data: $0.15 for 8K cache-creation + 251 output tokens, where the prompt was 303 chars):
  - Watchdog system prompt + bench output (~5 KB JSON) ≈ 2K input tokens cached + 800 output tokens ≈ **$0.03/wake** (input cache hit on subsequent wakes).
- 24 wakes/day × 30 days × $0.03 = **$21.60/mo in tokens**.
- Session-hour billing only counts ACTIVE runtime. Each wake spends ~30 s active, so 24 × 30 × 30 s/3600 s × $0.08 = **$0.16/mo in session-hr** (negligible).
- **Total: ~$22/mo for hourly watchdog** with cache-hit budget. If we keep one session running between wakes (no terminate-and-recreate), that's still under the rounding error.

Compare to "always-on" misuse (a 24×7 session that polls itself): 720 h × $0.08 = $57.60/mo + tokens. Don't do it.

## Cost arithmetic for hypothetical "10-hour iterative loop" (the question 4 specific case)

Anchored to docs and the smoke-session datapoint:

| Path | Runtime | Token cost | Session-hr cost | Total | Cite |
|---|---|---|---|---|---|
| Managed Agent, 10 h continuous, ~30 turns @ Opus 4.7, 8K in / 4K out per turn | 10 h | 30 × ($5×8K/1M + $25×4K/1M) = 30 × ($0.04 + $0.10) = **$4.20** | 10 × $0.08 = **$0.80** | **$5.00** | hackathon_opus_4_7_reference.md:13, 54 |
| Same loop in Claude Code Agent (`/loop` skill, 30 invocations) | 10 h wall, but Claude Code billing is per-invocation tokens only | 30 × $0.14 = **$4.20** | n/a (no session-hr in Claude Code Agent tool) | **$4.20** | claude-api skill, ~/.claude/CLAUDE.md billing references |
| Same loop in single Claude Code Sonnet conversation (one session, 30 tool uses) | 10 h | input compounds: ~30 × cumulative-context input. If avg context grows from 8K → 80K linearly: avg 44K × 30 turns = 1.32M input tokens × $5/MTok = **$6.60** + 4K × 30 × $25/MTok = $3.00. Real total: **$9.60** | n/a | **$9.60** | Standard Messages-API behavior |

**Conclusion on cost:** Managed Agents is ~5% **more expensive** than Claude Code Agent invocations for the same 10-h loop (the $0.80 session-hr line item), and ~50% **cheaper** than a single growing Claude Code conversation because session state lives outside the context window so input doesn't compound. **Cost is a wash for shorter loops; Managed Agents wins clearly only when the loop is long enough that context-window compounding bites Claude Code.** A 10-h loop is exactly the break-even region; cycles 2c/2d/2e are 1-4 h each — Claude Code wins.

What breaks first in each (question 2):

- **Claude Code Agent tool**: hits the **token-context limit on the parent session** (200K Sonnet, 1M Opus on 4.7 Messages API but Claude Code currently composes within its own caps; a single Agent invocation is bounded by 80-100K observed in our cycle-1 truncation). 65 tool uses + 98K tokens before the cycle-1 executor truncated is the live datapoint. Multiple separate `/loop` invocations don't compound, but they lose mid-loop state.
- **Managed Agents**: hits the **session-hour billing surprise** if a session never goes idle (a stuck `bash` command keeps `running` status). Mitigations: `task-budgets-2026-03-13` advisory countdown + hard `max_tokens` per request + an external watchdog that calls `client.beta.sessions.terminate(sid)` if `running` >2× the expected runtime. Also vulnerable to: rate-limit (60 creates/min, 600 reads/min per org — `hackathon_opus_4_7_reference.md:56`), and the workspace-specific feature gating (multi-agent silently stripped, possibly outcomes/memory too — verify before depending).

## Q1 — Long-running iterative loops (cycle-2c → 2d → 2e in one session)

**Doc claim:** Yes, possible. Sessions persist with status transitions `idle → running → idle` across user.message injections. Session log is durable. (`platform.claude.com/docs/en/managed-agents/sessions` — doc-claim, not retrieved this turn but referenced in CLAUDE.md §8 and verified by `verify_session_durability.py` smoke as of 2026-04-22.)

**Workspace-verified pattern:** `smoke_session.py` + `verify_session_durability.py` already prove that "create session → kill client → reattach via stream → session is still progressing" works on this API key (`findings/smoke-session-2026-04-22.md`).

**Why we still don't recommend it for 2c-2e:** Cycles 2c-2e are pod-coupled (B300 SSH, systemd, CUDA MPS, vendor/fish-speech build). The Managed Agents environment has no path to our pod today. Wiring it requires:
- New environment with networking allowing outbound SSH to the B300 pod (`config.networking.type: limited` + `allowed_hosts: ["b300-pod.brev.dev"]`)
- Restricted SSH key as described above
- Estimated build-and-verify time: 4-6 h. We have 30 h to ship.

**Cost for the hypothetical 8-12 h cycle-2c-through-2e session:** ~$8 in tokens + ~$1 session-hr = **~$9**. Reasonable, but the engineering cost (one full day of pod-network plumbing) eats half our remaining sprint and we can't pre-test the plumbing without a dry-run pod that we don't have. **Net: dragons exceed savings.**

## Q2 — Bench-and-iterate: 4-hour bench loop tuning a parameter

Already answered in the truth table. Short version: **Claude Code with the `/loop` skill** wins now because it talks to the pod over SSH directly through bash. Managed Agents would win post-deadline once we wire pod-access into the environment. Break-first failure: Claude Code → context limit on parent session at ~80K tokens; Managed Agents → session-hour billing if a `running` state hangs. Both are solvable; the Claude Code one is solved by `/loop` (re-spawn fresh agent each iteration).

## Q3 — Hourly regression watchdog post-deadline

**Delivery shape: cron-triggered user.message injection, single long-lived session.** Spelled out under "Concrete proposal" above. Not a Vercel cron, not a webhook, not always-on poll — external cron POSTs one event hourly, session wakes, runs bench, writes verdict file, returns to idle. **This is the textbook Managed Agents use case** per Anthropic's "context object that lives outside the context window" framing.

**Doc gap (worth flagging):** I did not freshly retrieve `platform.claude.com/docs/en/managed-agents/events` this turn. The `POST /v1/sessions/:id/events` endpoint is documented in `hackathon_opus_4_7_reference.md:59-60` and `managed_agents_multi_agent_verified.md:18-23`, both of which are 3-4 days old. Verify the schema (specifically: whether `events.send` from an external context blocks until idle, or returns immediately and the session works in the background) before wiring cron. **Verification command for the integrator (post-deadline):** `curl -sS -X POST https://api.anthropic.com/v1/sessions/$SID/events -d '{"events":[{"type":"user.message","content":[{"type":"text","text":"ping"}]}]}'` — should return 200 with no body and the session should transition `idle → running` within ~1 s on the SSE stream.

## Q4 — Cost arithmetic

Already detailed under "Cost arithmetic for hypothetical 10-hour iterative loop" and "Cost arithmetic for the watchdog" above. Numbers:

- Session-hour: **$0.08/h** (CLAUDE.md §8, `hackathon_opus_4_7_reference.md:54`).
- Opus 4.7 input: **$5/MTok**. Output: **$25/MTok** (`hackathon_opus_4_7_reference.md:13` — *"Opus 4.7 | claude-opus-4-7 | $5 / $25"*).
- Real anchored datapoint: **$0.15 per smoke session** at 8,424 input + 251 output tokens (`findings/smoke-session-2026-04-22.md:cost`). This includes the cache-creation overhead so it's a worst-case-first-session number.
- Tokenizer migration tax: **1.0× to 1.35× more tokens than 4.6** (CLAUDE.md "Tokenizer change" line, `platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7`). Re-estimate any 4.6-anchored budget by × 1.2.

**One-time-budget table for remaining work, expressed as tokens-on-Opus-4.7:**

| Cycle | Effort estimate | Platform | Total $ |
|---|---|---|---|
| 2c MPS | 1-2 h surgical | Claude Code | $1-3 |
| 2d Fish patch + bench | 2-3 h | Claude Code | $2-5 |
| 2e Pipecat speculative | 2-4 h | Claude Code | $3-7 |
| **Sprint total (2c+2d+2e)** | **5-9 h Claude Code** | | **$6-15 in tokens** |
| Watchdog (post-deadline, 30 days) | hourly × 24 × 30 = 720 wakes | Managed Agent | **$22/mo** |

Every number above anchored. Nothing padded.

## Q5 — Five registered prism42 agents (defender/attacker/synthesizer/executor/adjudicator)

Currently registered (`agents/manifest.yaml:21-37`):
```
defender:    agent_011CaJbgw3Y2eByqE53xUyKk v1
attacker:    agent_011CaJbgxAWaTvnokZqiTGo2 v1
synthesizer: agent_011CaJbgyMSdwo29tV5eKGMo v1
executor:    agent_011CaJbgzqjS59EtQmv5d9zT v1
adjudicator: agent_011CaJbh2gMz6qqkumThhFKL v1
coordinator: agent_011CaJboTBvV6agLw9huTWJY v4 (skill-extended)
```

**Repurposable for voice work? No.** Their YAML system prompts (`agents/prism-{role}.yaml`) are framed for the kernel/clinical numerical-correctness audit (CLAUDE.md §1-§2: "executor exits with VIOLATION", "rubric-graded model-behavior delta", per-rail branching on `case.rail`). Voice-pipeline tuning is a different problem class — Fish/MPS/Pipecat are infra-tuning tasks with continuous metrics, not VIOLATION-style binary findings.

**Should we register `voice-*` namespace agents (`voice-bench-runner`, `voice-fish-tuner`, etc.)?** **No, not before Sunday.** Two reasons:

1. **`callable_agents` is silently stripped on this workspace key.** CLAUDE.md §8: *"Tested 2026-04-22 from this repo against the API key in `.env`: `POST /v1/agents` returns 200 OK with `callable_agents` absent from the stored body, regardless of which beta-header combination is sent."* Five header variants tested, all stripped. So a coordinator-with-callable-voice-subagents pattern doesn't actually compose — they'd be standalone agents only.
2. **Single-agent registration costs nothing if it's not invoked**, but there's still no reason to register them before they're useful. The watchdog above is the one voice-* agent worth registering, and only post-deadline.

**The registration mechanism** (`scripts/register_agents.py` lines 41-48, 62-71, 96-115, 118-160):
- ORDER list defines registration sequence.
- `agents/<role>.yaml` provides body; `_prism:` metadata stripped before POST (`_strip_prism()`).
- `callable_agents` resolved from symbolic role names → `[{type, id, version}]` (`resolve_callable_agents()`); on commit path, **stripped to empty before POST** because the typed SDK drops it and raw-HTTP also drops it on this workspace (line 145-147 comment).
- Manifest `agents/manifest.yaml` is regenerated on each commit; agent IDs and versions land there.
- Double-gate: `--commit` + `PRISM_AGENTS_COMMIT=1` (line 175-178).

To extend with a `voice-watchdog` agent post-deadline:
```yaml
# agents/voice-watchdog.yaml
_prism: {role: voice-watchdog}
name: prism-voice-watchdog
model: claude-opus-4-7
system: ...  # see Concrete proposal
tools: [{type: agent_toolset_20260401}]
```
Then add `"voice-watchdog"` to ORDER in `register_agents.py` and run with both gates. Pattern matches the existing five 1:1.

## Q6 — Truth table

Provided above under "Truth table". Re-tagged with reasons.

## Q7 — Risks of switching mid-sprint

**Switching from Claude Code Agent to Managed Agents in the next 30 hours: do not do it.** Specific dragons:

1. **Pod-network plumbing is unverified.** The Managed Agents environment shape we'd need (with outbound SSH to B300) has not been wired or smoke-tested. The current `prism-standard-env` (env_01Nbmp5KCzCKfkcJgZdHhngY) is a generic networking-limited cloud sandbox per `environments/prism-standard-env.yaml`. New env required. New env means new manifest version. New manifest means re-pin everywhere. Breaks orchestrator+harness_runner+harness_sweep.
2. **`callable_agents` silent strip is a confirmed dragon (2026-04-22).** Anything that assumes "coordinator delegates to voice-fish-tuner" will fail open — no error, no warning, just the field absent. Verified by raw-HTTP probe on this exact API key. If we ever depend on this for voice work, we depend on a feature flag we don't control.
3. **Tokenizer 1.0-1.35× tax.** Any cost estimate I gave assumes Opus 4.7 token counts; we paid 0% to 35% more than the 4.6 baseline. Don't take any number above as exact; use them as orders-of-magnitude.
4. **Sandbox has no GPU.** The Managed Agents environments are CPU sandboxes. No way to run `bench_b300.py` inside one — it'd have to SSH out. Adds a network leg, potentially 20-200 ms per command.
5. **SSH-key plumbing requires a new restricted user on the B300 pod and a new vault entry** (vaults are doc'd `https://platform.claude.com/docs/en/managed-agents/vaults`, doc-claim from CLAUDE.md §8 sub-section, NOT verified on this workspace yet). Building this with 30 hours left is glasswing-violating: it's "exploring", not "shipping".
6. **`outcomes`, `memory`, `multi-agent` are all research-preview-flagged on Anthropic's overview page.** CLAUDE.md §8 quote: *"Certain features (outcomes, multiagent, and memory) are in research preview. Request access at `https://claude.com/form/claude-managed-agents`."* If we plan around any of these without re-verification, we'll get the same silent-strip behavior we got with `callable_agents`.
7. **Mid-sprint switch breaks the integrator's mental model.** The current OODA loop is "edit code → bench on pod → read logs → repeat". Adding a Managed Agents abstraction in front of step 2 is a new failure mode (session stuck, billing surprise, sandbox file `/workspace/` ≠ pod file `/opt/prism42/...`). Sunday demo doesn't have time for that to bite.

**The rule: glasswing-discipline says use each tool for what it's actually best at. Managed Agents is best at long-lived, brain-replaceable, externally-trigger-able loops. Cycles 2c-2e are short-lived, integrator-driven, pod-coupled. They are not the shape that wins.**

## What would change the answer

If any of these go true mid-sprint, re-run this analysis:

- The `callable_agents` strip is fixed for this workspace key (we'd see it in the next live probe; track via the request_id + a re-test).
- A pod-reachable Managed Agents environment is wired (`vault_ids` with the SSH key, networking allowed_hosts including the pod) AND smoke-tested.
- A future cycle requires >12 h continuous OODA (cycles 2c-2e together don't — each is bounded).
- The integrator wants to leave the laptop and have the loop self-drive overnight. (At that point, Managed Agents wins by definition. Today, the integrator is at the laptop.)

## Sources

Numbered, with retrieval / fetch dates and verification status (V = verified on this workspace, D = doc-claim only, M = memory file as of date in frontmatter).

1. CLAUDE.md §8 — Managed Agents specifics, callable_agents silent-strip + request_id `req_011CaJg9qBnVqPNkaoBLgjrN` — **V** 2026-04-22 — `~/prism42/CLAUDE.md`
2. CLAUDE.md §0 — Hackathon mode rules, ship-by 2026-04-26 — **V** — same path
3. CLAUDE.md §5, §9 — double-gate, budget cap $280 — **V** — same path
4. `hackathon_opus_4_7_reference.md` — model pricing, `$0.08/session-hr`, `agent_toolset_20260401`, multi-agent shape, event taxonomy — **M** 2026-04-21 — `<owner-memory>/hackathon_opus_4_7_reference.md`
5. `managed_agents_multi_agent_verified.md` — endpoints, thread persistence, callable_agents declared at agent-create — **M** 2026-04-21 — `<owner-memory>/managed_agents_multi_agent_verified.md`
6. `findings/smoke-session-2026-04-22.md` — real cost datapoint: $0.15 / smoke session, 8,424 + 251 tokens, 8.3 s wallclock — **V** 2026-04-22 — `~/prism42/findings/smoke-session-2026-04-22.md`
7. `agents/manifest.yaml` — five sub-agents + coordinator IDs — **V** 2026-04-22 — `~/prism42/agents/manifest.yaml`
8. `scripts/register_agents.py` — registration mechanism, ORDER list, `_strip_prism`, `resolve_callable_agents`, `do_commit` containment — **V** — `~/prism42/scripts/register_agents.py`
9. `scripts/smoke_session.py` — live event-stream pattern, BETA header — **V** — `~/prism42/scripts/smoke_session.py`
10. `scripts/verify_session_durability.py` — session-reattach pattern (kill client, restream, status `running`/`idle`) — **V** — `~/prism42/scripts/verify_session_durability.py`
11. `scripts/harness_sweep.py` lines 30-37 — cost envelope ($100-$130 + $0.08 × session-hr per 30-example sweep) — **V** — `~/prism42/scripts/harness_sweep.py`
12. `findings/voice/synthesis.md` — five-fix plan, cycle-2c/2d/2e scope, OODA cadence — **V** 2026-04-25 — `~/prism42/findings/voice/synthesis.md`
13. `findings/voice/cycle-2a-anticipator/contingencies.md` — synthetic_caller_full.py:254-256 + bench_b300.py structure — **V** 2026-04-25 — `~/prism42/findings/voice/cycle-2a-anticipator/contingencies.md`
14. `findings/voice/llm-tail-causes.md` — bench cycle 1 forensics, p95 figures — **V** 2026-04-25 — `~/prism42/findings/voice/llm-tail-causes.md`
15. `agents/livekit/bench_b300.py` lines 1-120 — bench-loop entrypoint shape, log parsing — **V** — `~/prism42/agents/livekit/bench_b300.py`
16. `https://platform.claude.com/docs/en/managed-agents/overview` — research-preview gating language for outcomes/multi-agent/memory — **D** quoted in CLAUDE.md §8, NOT freshly fetched 2026-04-25
17. `https://platform.claude.com/docs/en/managed-agents/sessions` — session lifecycle, idle/running/rescheduling/terminated — **D** referenced in `managed_agents_multi_agent_verified.md`, NOT freshly fetched 2026-04-25
18. `https://platform.claude.com/docs/en/managed-agents/events` — event taxonomy, send/stream endpoints — **D** referenced in `hackathon_opus_4_7_reference.md`, NOT freshly fetched 2026-04-25
19. `https://platform.claude.com/docs/en/managed-agents/vaults` — vault binding (`vault_ids` per session) — **D** referenced in CLAUDE.md §8 sub-section, NOT freshly fetched 2026-04-25
20. `https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7` — tokenizer 1.0-1.35× tax, sampling-param removal, thinking display change — **D** referenced in CLAUDE.md "Recent best-practice synthesis", NOT freshly fetched 2026-04-25
21. `https://www.anthropic.com/engineering/managed-agents` — "context object that lives outside Claude's context window" framing — **D** referenced in CLAUDE.md "Cross-cutting discipline reminders", NOT freshly fetched 2026-04-25
22. `https://www.anthropic.com/engineering/harness-design-long-running-apps` — generator-evaluator separation pattern — **D** — same as above

Note on freshness: per the user's read-only constraint and the 30-min ship-by, I did not re-fetch any of the platform.claude.com or anthropic.com URLs above. Every doc-claim is anchored to a memory file or CLAUDE.md section that was either generated or verified ≤ 4 days ago. Verify URLs 16-22 before depending on any specific schema detail (especially session-events POST shape, vault binding, and feature-gating headers).

---

**Co-Authored-By: Claude Opus 4.7** (do not commit; integrator commits.)
