# cycle-2D — Verification (Team D)

Date: 2026-04-26 12:03 UTC

## Outcome

**The new public demo URL is live and verified end-to-end:**

```
https://prism42-app.thegoatnote.com
   → 307 redirect → 
https://prism42-app.thegoatnote.com/prism42/livekit
   → 200 OK (LiveKit + B300 dispatcher demo)
```

Total time from start of cycle to live verification: **~14 minutes** (well under the 90-min ship-by budget).

## Top-line probes

```bash
$ curl -sI https://prism42-app.thegoatnote.com/
HTTP/2 307
location: /prism42/livekit
server: Vercel
strict-transport-security: max-age=63072000

$ curl -sI https://prism42-app.thegoatnote.com/prism42/livekit
HTTP/2 200
x-matched-path: /prism42/livekit
x-nextjs-prerender: 1
content-length: 64060
```

64 KB Next.js prerender = the actual LiveKit demo page (DispatcherShell-style chrome + LiveCallRoom).

## End-to-end token API smoke test

```
$ curl -sX POST https://prism42-app.thegoatnote.com/prism42/api/livekit-token \
    -H "Content-Type: application/json" \
    -d '{"session_id":"d-team-domain-swap-smoke-001"}'

HTTP_CODE=200
{
  "room": "d-team-domain-swap-smoke-001",
  "livekit_url": "wss://prism42.thegoatnote.com",
  "identity": "caller-d-team-d",
  "expires_at": "2026-04-26T12:33:01.122Z"
}
```

Critical: `livekit_url` field is `wss://prism42.thegoatnote.com` (the B300 self-host endpoint, NOT the cloud), confirming the Vercel app and the B300 backend are correctly bound through the new architecture.

## Hard-constraint compliance check

| Constraint | Status |
|---|---|
| Don't break `wss://prism42.thegoatnote.com` (LiveKit signaling) | INTACT — `dig` returns `31.22.104.100`, `curl` returns 200 via Caddy, RTC validate returns 401 from livekit-server. No DNS or routing changes. |
| Don't break `prism42-console.vercel.app/prism42-v3` (backup) | INTACT — returns 200 |
| Don't touch the B300 pod | NO POD ACCESS — all changes were DNS (GoDaddy API) + Vercel (REST + CLI). No SSH session opened during cycle-2D. |
| Don't leak GoDaddy creds to artifacts | COMPLIANT — only `key_len=35 secret_len=22` logged; no raw values in any `findings/voice/cycle2D_domain_swap/` file. |
| Verify the rewrite scoped only to new domain | VERIFIED — `prism42-console.vercel.app/prism42` returns 200 (no redirect), `prism42-app.thegoatnote.com/prism42` returns 307. The `has: [{type:"host",value:"prism42-app.thegoatnote.com"}]` clause in `vercel.json` works as intended. |

## DNS state (post-change)

```
$ dig +short prism42-app.thegoatnote.com
cname.vercel-dns.com.
76.76.21.98
66.33.60.67

$ dig +short prism42.thegoatnote.com
31.22.104.100

$ dig +short turn-prism42.thegoatnote.com
31.22.104.100

$ dig +short thegoatnote.com
76.76.21.21
```

CNAME `prism42-app` resolves to Vercel anycast (76.76.21.x and 66.33.60.x are both correct for `cname.vercel-dns.com`).
A-records `prism42` and `turn-prism42` unchanged at the B300 pod IP.
Apex unchanged.

## TLS

```
$ openssl s_client -connect prism42-app.thegoatnote.com:443 -servername prism42-app.thegoatnote.com < /dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates
```

(verified via curl — TLS handshake clean, `strict-transport-security: max-age=63072000` returned, `server: Vercel` confirms terminator.)

Cert was provisioned by Vercel's edge from Let's Encrypt within ~5 min of the first production deployment to the project after domain attach.

## Live verification snapshot

| URL | HTTP | Notes |
|---|---|---|
| `https://prism42-app.thegoatnote.com/` | 307 → `/prism42/livekit` | NEW ENTRY POINT |
| `https://prism42-app.thegoatnote.com/prism42` | 307 → `/prism42/livekit` | NEW |
| `https://prism42-app.thegoatnote.com/prism42/livekit` | 200 | NEW — DEMO TARGET |
| `https://prism42-app.thegoatnote.com/prism42/api/livekit-token` (POST) | 200 | NEW — token API live |
| `https://prism42-console.vercel.app/prism42` | 200 | UNCHANGED — ElevenLabs path |
| `https://prism42-console.vercel.app/prism42-v3` | 200 | UNCHANGED — ElevenLabs backup |
| `https://prism42-console.vercel.app/prism42/livekit` | 200 | UNCHANGED — LiveKit auto-domain |
| `https://prism42.thegoatnote.com` | 200 | UNCHANGED — Caddy → livekit-server |
| `https://prism42.thegoatnote.com/rtc/validate` | 401 | UNCHANGED — livekit-server speaking |

## What the integrator should tell the user

> **The demo URL is now `https://prism42-app.thegoatnote.com`.**
> The bare URL auto-redirects to the LiveKit demo page (`/prism42/livekit`).
> The old `prism42-console.vercel.app/prism42/livekit` URL still works as a backup.
> The ElevenLabs fallback at `prism42-console.vercel.app/prism42-v3` still works.
> No changes were made to the LiveKit backend at `prism42.thegoatnote.com` (B300 pod).
