# cycle-2D — Apply receipts (Team D)

Date: 2026-04-26 (start 11:49 UTC, end 12:03 UTC, ~14 min total)
Operator: Team D (Claude Opus 4.7 agent)
Path chosen: **B** — `prism42-app.thegoatnote.com` as the public app subdomain

---

## Step 1 — GoDaddy DNS PUT (CNAME)

**Pre-check (read existing state):**

```
GET https://api.godaddy.com/v1/domains/thegoatnote.com/records/CNAME/prism42-app
  Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}   # values not logged

→ HTTP_CODE=200
→ body: []
```

No existing record — safe to PUT.

**PUT:**

```
PUT https://api.godaddy.com/v1/domains/thegoatnote.com/records/CNAME/prism42-app
  Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}   # values not logged
  Content-Type: application/json
  body: [{"data":"cname.vercel-dns.com","ttl":600}]

→ HTTP_CODE=200
```

**Read-back verification:**

```
GET https://api.godaddy.com/v1/domains/thegoatnote.com/records/CNAME/prism42-app

→ HTTP_CODE=200
→ body: [{"data":"cname.vercel-dns.com","name":"prism42-app","ttl":600,"type":"CNAME"}]
```

**Public DNS propagation (8.8.8.8 within 1 minute):**

```
$ dig +short @8.8.8.8 prism42-app.thegoatnote.com
cname.vercel-dns.com.
76.76.21.123
66.33.60.35
```

System resolver caught up within 5 minutes:

```
$ dig +short prism42-app.thegoatnote.com
cname.vercel-dns.com.
76.76.21.98
66.33.60.67
```

Vercel anycast targets (76.76.21.x and 66.33.60.x) are the standard `cname.vercel-dns.com` resolution. Different IPs on different probes = expected anycast behavior.

---

## Step 2 — Vercel custom domain attach

```
$ cd ~/prism42/mvp/911-console-live/
$ vercel domains add prism42-app.thegoatnote.com
> Adding domain prism42-app.thegoatnote.com to project prism42-console
> Success! Domain prism42-app.thegoatnote.com added to project prism42-console. [156ms]
```

The follow-up "domain_fetch_failed (403)" message from the CLI plugin is a known noise from the Vercel CLI when querying a domain whose registrar is `Third Party` (GoDaddy). The actual attach succeeded, confirmed by:

```
$ curl -sS -H "Authorization: Bearer ${VERCEL_TOKEN}" \
    "https://api.vercel.com/v9/projects/prism42-console/domains/prism42-app.thegoatnote.com?teamId=team_9F90ShqNvPoaCCkhrjCCw91r"

{
  "name": "prism42-app.thegoatnote.com",
  "apexName": "thegoatnote.com",
  "projectId": "prj_UCqQGmKnXhmqeQgwIHWJ9zzfX4vP",
  "verified": true,        ← key field
  "createdAt": 1777204333412
}
```

`verified: true` = Vercel auto-verified DNS via the CNAME match.

---

## Step 3 — `vercel.json` redirects

Edited `~/prism42/mvp/911-console-live/vercel.json` to add scoped redirects so a user typing the bare hostname or `/prism42` lands directly on the LiveKit demo:

```jsonc
"redirects": [
  {
    "source": "/",
    "destination": "/prism42/livekit",
    "permanent": false,
    "has": [{ "type": "host", "value": "prism42-app.thegoatnote.com" }]
  },
  {
    "source": "/prism42",
    "destination": "/prism42/livekit",
    "permanent": false,
    "has": [{ "type": "host", "value": "prism42-app.thegoatnote.com" }]
  }
]
```

The `has: [{ type: "host", value: "prism42-app.thegoatnote.com" }]` clause is the **critical safety mechanism** — the redirects fire ONLY on the new domain, not on `prism42-console.vercel.app`. This protects:

- `prism42-console.vercel.app/prism42` → still serves ElevenLabs `DispatcherShell` (backup #1)
- `prism42-console.vercel.app/prism42-v3` → still serves backup ElevenLabs (backup #2)
- `prism42-console.vercel.app/prism42/livekit` → still serves directly

`permanent: false` (HTTP 307) instead of `permanent: true` (HTTP 308) deliberately — keeps browser caches small in case we want to flip the default page later without 60-day cache decay.

---

## Step 4 — Production redeploy

The Vercel project `prism42-console` is configured with `Root Directory = mvp/911-console-live`. Running `vercel --prod` from `mvp/911-console-live/` double-paths to `mvp/911-console-live/mvp/911-console-live` (Vercel error: "path … does not exist").

Workaround: the **cycle-2R project.json swap trick** — temporarily swap the repo-root `.vercel/project.json` to point at `prism42-console`, deploy from repo root, then swap back. Documented and reusable.

```
# Backup
$ cp ~/prism42/.vercel/project.json /tmp/d-team-prism42-project.json.bak

# Swap
$ cp ~/prism42/mvp/911-console-live/.vercel/project.json ~/prism42/.vercel/project.json

# Deploy
$ cd ~/prism42/ && vercel --prod --yes
> Production: https://prism42-console-<hash>-goatnote.vercel.app [READY]
> Deployment id: dpl_Vaz8jCjq3nRoBML1LnXw4CvqkUUd

# Restore
$ cp /tmp/d-team-prism42-project.json.bak ~/prism42/.vercel/project.json
```

The new deployment carries the updated `vercel.json` redirects and is the first build associated with `prism42-app.thegoatnote.com`, which triggered Vercel's TLS provisioning.

---

## Step 5 — TLS provisioning

Vercel's edge issued the Let's Encrypt cert ~5 minutes after the first deployment was live on the new domain. The first probe at 11:53 UTC returned `HTTP=000` (TLS handshake `SSL_ERROR_SYSCALL`); the post-deploy probe at 12:02 UTC returned `HTTP/2 307`. Total provisioning time: ~9 min from `vercel domains add` to first cert-served response.

---

## Verification matrix (full pass)

| # | Check | Expected | Observed | Pass |
|---|---|---|---|---|
| 1 | `https://prism42-app.thegoatnote.com/` | HTTP 307 → `/prism42/livekit` | HTTP/2 307, `location: /prism42/livekit` | YES |
| 2 | `https://prism42-app.thegoatnote.com/prism42` | HTTP 307 → `/prism42/livekit` | HTTP/2 307, `location: /prism42/livekit` | YES |
| 3 | `https://prism42-app.thegoatnote.com/prism42/livekit` | HTTP 200 (demo loads) | HTTP/2 200 | YES |
| 4 | `https://prism42-console.vercel.app/prism42` (backup #1) | HTTP 200, NOT redirected | HTTP/2 200 | YES |
| 5 | `https://prism42-console.vercel.app/prism42-v3` (backup #2) | HTTP 200 | HTTP/2 200 | YES |
| 6 | `https://prism42-console.vercel.app/prism42/livekit` (backup #3) | HTTP 200 | HTTP/2 200 | YES |
| 7 | `https://prism42.thegoatnote.com` (LiveKit signaling unchanged) | HTTP 200 via Caddy | HTTP/2 200, `via: 1.1 Caddy` | YES |
| 8 | `https://prism42.thegoatnote.com/rtc/validate` (livekit-server alive) | HTTP 401 (livekit speaking) | HTTP/2 401 | YES |
| 9 | DNS `prism42-app.thegoatnote.com` | resolves via `cname.vercel-dns.com.` | `cname.vercel-dns.com.` → 76.76.21.98 + 66.33.60.67 | YES |
| 10 | DNS `prism42.thegoatnote.com` | unchanged at `31.22.104.100` | `31.22.104.100` | YES |
| 11 | Token API E2E through new domain | returns `wss://prism42.thegoatnote.com` + valid JWT | `livekit_url: wss://prism42.thegoatnote.com`, `token: eyJhbGc…`, HTTP 200 | YES |

End-to-end token round-trip verified at 12:03 UTC: a browser loading `https://prism42-app.thegoatnote.com/prism42/livekit` will hit the Vercel-hosted token API on the same origin and receive a token whose `livekit_url` points at the B300 pod, then open WSS directly there. Both halves of the architecture independently functional.

---

## Future-work — Path A bonus (`thegoatnote.com/prism42` literal)

Not landed in this cycle. To enable later:

1. Locate the `v0-goat-note-landing-page-3c` source repo (currently unknown to this monorepo). It is the Vercel project serving `thegoatnote.com` apex / `www.thegoatnote.com`.
2. Add to its `next.config.js`:
   ```js
   async rewrites() {
     return [
       {
         source: '/prism42/:path*',
         destination: 'https://prism42-app.thegoatnote.com/prism42/:path*'
       },
       {
         source: '/prism42',
         destination: 'https://prism42-app.thegoatnote.com/prism42/livekit'
       }
     ];
   }
   ```
3. Deploy that project. After deploy, `https://thegoatnote.com/prism42` will reverse-proxy to the same Vercel deployment that serves `prism42-app.thegoatnote.com/prism42`.

Risk: a misconfigured rewrite could break the marketing landing page. Defer until v0 source is in hand and a separate cycle.

---

## Secrets handling note

Per hard rule, the values of `GODADDY_API_KEY`, `GODADDY_API_SECRET`, and `VERCEL_TOKEN` are not written to this artifact. The `Authorization` header in curl was constructed inline from env vars; the only logging done was `key_len=35 secret_len=22 TOKEN_LEN=60` for sanity. No raw token bytes appear in any cycle-2D artifact under `findings/`.
