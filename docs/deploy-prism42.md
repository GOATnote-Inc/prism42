# Deploying www.thegoatnote.com/prism42

This doc is the single source of truth for standing up the live
Prism42 PSAP console at `www.thegoatnote.com/prism42`. Three
pieces to wire — Anthropic Managed Agents, Vercel, and ElevenLabs.

_Fetched 2026-04-23 from the published ElevenLabs + Vercel docs. If
the wizards or dashboard paths have moved, consult the canonical
pages: [Vercel Microfrontends quickstart](https://vercel.com/docs/microfrontends/quickstart) ·
[Vercel multi-project routing](https://vercel.com/kb/guide/how-can-i-serve-multiple-projects-under-a-single-domain) ·
[ElevenLabs widget customization](https://elevenlabs.io/docs/eleven-agents/customization/widget)._

---

## 1. Register the 14 PSAP Managed Agents

Runs via the double-gated script. Needs `ANTHROPIC_API_KEY` sourced
from `.env`, the explicit env-var opt-in, and the `--commit` flag.

```bash
# One-time: create a venv with anthropic + pyyaml
python3 -m venv .venv
.venv/bin/pip install --quiet 'anthropic>=0.91.0' 'pyyaml>=6.0'

# Dry-run first — no network, no SDK import
.venv/bin/python3 scripts/register_psap_agents.py

# Real registration (~$0.10 one-time cost; writes agents/psap-manifest.yaml)
(set -a; source .env; set +a; \
  PRISM_PSAP_AGENTS_COMMIT=1 \
  .venv/bin/python3 scripts/register_psap_agents.py --commit)
```

On success, `agents/psap-manifest.yaml` contains `role → {id,
version}` entries for the 14 PSAP agents. The `psap-team-coordinator`
id is what you paste into the live app's `PRISM42_COORDINATOR_AGENT_ID`
env var (Step 2).

`psap-rubric-live` is deliberately not registered — it runs as a
runtime OpenAI chat-completion call (GPT-5.5 primary, GPT-5.4
fallback) for cross-vendor grader independence. The
`psap-rubric-live-shim` IS registered as the emergency-only
Anthropic fallback that raises `self_grade_flag`.

---

## 2. Deploy mvp/911-console-live/ to Vercel

### Current state (2026-04-23)

- Project linked: `goatnote/prism42-console`
- Production URL: <https://prism42-console.vercel.app>
- Latest deployment ID: `dpl_HBP7Uwve7kSiz8LjNQ4EVfMKGFSL`
- Env vars set: **NONE** — this is the outstanding blocker
- Static pages (`/prism42`, `/prism42/safety`, `/prism42/evidence`)
  return 200 and render; API endpoints return 500 until env vars
  land (the Anthropic / OpenAI clients throw on empty keys).

### 2.1 Add env vars via dashboard

Vercel CLI's `vercel env add` is interactive and can't accept a
piped secret value from this repo's `.env` without reading the
file — which violates the hard rule on credential reads. Use the
dashboard:

1. <https://vercel.com/goatnote/prism42-console/settings/environment-variables>
2. Add each of the following, scope = **Production, Preview, Development**:

   | Key | Value source |
   |---|---|
   | `ANTHROPIC_API_KEY` | repo `.env` (`ANTHROPIC_API_KEY=…`) |
   | `OPENAI_API_KEY` | repo `.env` (`OPENAI_API_KEY=…`) |
   | `PRISM42_COORDINATOR_AGENT_ID` | `agent_011CaMZirdiPJkw1nBmeyK63` (the psap-team-coordinator id from `agents/psap-manifest.yaml`, 2026-04-23) |
   | `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` | set after Step 4 (ElevenLabs agent creation) |

3. Mark the two API keys as **Sensitive**.

### 2.2 Re-deploy so the env vars take effect

```bash
cd mvp/911-console-live
vercel deploy --prod --yes
```

### 2.3 Create the project from scratch (if starting fresh)

```bash
cd mvp/911-console-live
vercel link --yes --project prism42-console
# Then the env-vars setup above, then:
vercel deploy --yes

```

The deploy reads `mvp/911-console-live/vercel.json` for per-function
timeouts (60 s for `/prism42/api/chat/completions`, 300 s for SSE
streams).

### 2.4 Smoke-test the live endpoint

```bash
curl -N -X POST https://prism42-console.vercel.app/prism42/api/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"prism42-coordinator","stream":true,
       "messages":[{"role":"user","content":"hello"}],
       "user":"smoke-test"}'
```

You should see SSE chunks in the OpenAI `chat.completion.chunk`
format ending with `data: [DONE]`. If you get a 500, check
`vercel logs --prod` — most likely cause is a missing env var
from §2.1.

---

## 3. Wire /prism42 into www.thegoatnote.com

The prism42-console project deploys to its own Vercel URL
(`prism42-console.vercel.app`). To make it reachable at
`www.thegoatnote.com/prism42`, the `thegoatnote.com` Vercel
project needs a rewrite rule that forwards `/prism42/:path*`
traffic to the prism42-console deployment.

**Why not Vercel Microfrontends?** The recommended 2026 pattern is
`microfrontends.json`, but it explicitly does NOT support Next.js
apps using `basePath` (verified [Vercel docs, 2026-04-23](https://vercel.com/docs/microfrontends/quickstart))
— and even without `basePath`, microfrontends require both
projects to be part of a named group with the `@vercel/microfrontends`
package installed on every app. For a single `/prism42` subtree, the
simpler `vercel.json` rewrite pattern is cleaner and ships today.

### 3.1 Option A — vercel.json rewrite on the main project (recommended)

In the `thegoatnote.com` Vercel project's `vercel.json`, add:

```json
{
  "rewrites": [
    {
      "source": "/prism42/:match*",
      "destination": "https://prism42-console.vercel.app/prism42/:match*"
    }
  ]
}
```

**Critical:** the destination path keeps the `/prism42` prefix
intact — our app's routes are authored at `/prism42/*` in the file
tree, not with `basePath`. A stripped-prefix rewrite
(`destination: .../:match*`) would 404 every route.

Deploy the `thegoatnote.com` project after the rewrite lands. Test:

```bash
curl -I https://www.thegoatnote.com/prism42/safety
# Should return 200 and the safety page HTML.
```

### 3.2 Option B — Vercel Microfrontends (future)

If/when we want the cross-project goodies (CDN-level routing with
no second network hop, per-branch microfrontend routing, toolbar
debugging), migrate by:

1. `vercel microfrontends create-group` from the root of the
   thegoatnote.com project.
2. Add both projects to the group in the dashboard.
3. Install `@vercel/microfrontends` in both projects.
4. In prism42-console's `next.config.ts`, wrap the config with
   `withMicrofrontends(...)`. Our `basePath` is already unset, so
   the wrapper handles the `/vc-ap-<hash>` asset prefix cleanly.
5. Add `microfrontends.json` to the default (thegoatnote.com) app:

   ```json
   {
     "$schema": "https://openapi.vercel.sh/microfrontends.json",
     "applications": {
       "thegoatnote-com": {},
       "prism42-console": {
         "routing": [
           { "paths": ["/prism42/:path*"] }
         ]
       }
     }
   }
   ```

Microfrontends routing happens inside Vercel's network (no outbound
request, no second hop), which beats Option A's rewrite on latency
by ~50–100 ms. Worth the migration once the demo is load-tested.

---

## 4. Create the ElevenLabs ConvAI agent

### 4.1 Agent creation — API-driven (recommended)

The dashboard GUI preselects an LLM (Claude Sonnet 4.6 as of
2026-04-23) and a telehealth-themed system prompt template, and
there's no guided wizard to swap them out. Use the REST API
instead, driven by the same double-gate pattern as Anthropic:

```bash
# Dry-run — no network, prints the exact POST body
.venv/bin/python3 scripts/register_elevenlabs_agent.py

# Real create (requires PRISM_ELEVENLABS_COMMIT=1 + ELEVENLABS_API_KEY sourced)
(set -a; source .env; set +a; \
  PRISM_ELEVENLABS_COMMIT=1 \
  .venv/bin/python3 scripts/register_elevenlabs_agent.py --commit)
```

On success the script:

- POSTs to `https://api.elevenlabs.io/v1/convai/agents/create`
  with the body from `agents/prism42-elevenlabs.yaml`
- Writes `agents/elevenlabs-manifest.yaml` with the returned
  `agent_id`
- Prints the agent id for you to paste into Vercel
  (`NEXT_PUBLIC_ELEVENLABS_AGENT_ID`)

The agent's system prompt is the minimum to pass-through the
`Session-ID: {{session_id}}` dynamic variable — our custom-LLM
backend REPLACES it with the 14-role coordinator prompt
anyway. Voice / first message / turn timing / language are all
set at create time; the user can override any of them in the
dashboard post-hoc without risk of this script clobbering them
on re-run (PATCH is additive when the manifest carries an id).

### 4.2 Re-running — PATCH over POST

Once `agents/elevenlabs-manifest.yaml` exists, the script
auto-switches to `PATCH /v1/convai/agents/:id`. Useful when:

- Rotating the custom-LLM URL (say, after wiring
  `www.thegoatnote.com/prism42` rewrite)
- Tightening SP-001 language in the ElevenLabs pass-through
- Adding a new dynamic variable beyond `session_id`

`--replace` forces a fresh POST (the old agent is left orphaned
— clean it up from the dashboard, or leave it, ElevenLabs
doesn't charge per idle agent).

### 4.3 Dashboard post-hoc tweaks (safe)

These settings are NOT in `prism42-elevenlabs.yaml` by design —
omitting them means PATCH leaves whatever the dashboard has set:

- **Voice** (the user's current pick: "Eric - Smooth,
  Trustworthy") — stays unless explicitly overridden in YAML
- **First message** — the widget's spoken greeting
- **Security → Allowlist** — add `www.thegoatnote.com` +
  preview domains to restrict widget embed origin
- **Security → Authentication** — must be disabled for the
  public `<elevenlabs-convai>` widget embed to work

### 4.4 Current live agent (2026-04-23)

```
agent_id: agent_4501kpybsax0fwab52xybfaa9mna
```

Already set in the Vercel project's
`NEXT_PUBLIC_ELEVENLABS_AGENT_ID` env var (Production +
Development). Smoke-test verified — calling
`/prism42/api/chat/completions` with `Session-ID:
aaaa-bbbb-cccc-dddd-eeee` and the user utterance "my husband
just collapsed in the kitchen" returned the PSAP-intake agent's
correct first response: "Okay, help is on the way. What is the
address of the emergency?"

### 4.2 Paste the agent id into Vercel env

```bash
cd mvp/911-console-live
vercel env add NEXT_PUBLIC_ELEVENLABS_AGENT_ID production
# Paste the agent id when prompted
vercel deploy --prod
```

### 4.3 Smoke-test live voice

1. Open <https://www.thegoatnote.com/prism42>.
2. The `<elevenlabs-convai>` widget should render bottom-right.
3. Click **Start call**. Speak a test utterance ("my husband
   collapsed in the kitchen").
4. The dispatcher panel should display the PSAP turn (agent
   classification, action, rationale, cites, self-verify status)
   within ~2 s of the caller finishing speaking.

### 4.4 Voice + BAA posture

- Use a **preset voice** only (no voice cloning). ElevenLabs
  allows cloning but for our healthcare-compliance posture we
  stick with presets.
- ElevenLabs is HIPAA-certified; **BAA is not explicitly
  documented** and requires confirmation via their sales team
  before production PHI. We ship the demo with synthetic
  fixtures only (SP-001 binds every agent to refuse real-caller
  claims), so a BAA is not a launch blocker for the public
  demonstration URL.

---

## 5. Post-launch verification

After the live URL is reachable and the widget can place a call:

- [ ] `www.thegoatnote.com/prism42` loads the dispatcher shell
- [ ] `www.thegoatnote.com/prism42/safety` loads the safety page
- [ ] `www.thegoatnote.com/prism42/evidence` loads the dashboard
- [ ] The `<elevenlabs-convai>` widget mounts and establishes a call
- [ ] Every caller utterance produces a PSAP turn in the transcript
- [ ] Each `speak` turn is graded by GPT-5.5 (visible in the rubric
      strip) within ~2 s
- [ ] If the widget is mounted but the endpoint is unreachable, the
      caller hears "One moment please." (the SP-006 safe-fallback),
      never a malformed instruction.

If any step fails, consult `findings/public-demo/<session_id>/`
verdict.json files (produced by psap-auditor on session close,
Phase 2b) for the post-session verdict.

---

## 6. Rollback

```bash
# Vercel: instant-rollback any prism42-console deployment
vercel rollback <deployment-url>

# Agent registration: no rollback needed — dupes aren't created
# because the script is idempotent (checks agents/psap-manifest.yaml
# by default). To re-register everything fresh:
(set -a; source .env; set +a; \
  PRISM_PSAP_AGENTS_COMMIT=1 \
  .venv/bin/python3 scripts/register_psap_agents.py --commit --replace)

# ElevenLabs: archive an agent from the dashboard if its config
# drifts. New agents can be created without affecting existing
# conversation history.
```

---

## Attribution

Clinical direction: **Brandon Dent, MD** (emergency medicine) as
clinical director of GOATnote Inc. Not "physician of record" —
attribution is always "developed under direction of."
