# cycle-2D — domain swap decision (Team D)

Date: 2026-04-26
Operator: Team D (Claude Opus 4.7 agent)
Mission: end the public demo URL `prism42-console.vercel.app/prism42/livekit` and replace it with a `thegoatnote.com`-anchored URL.

---

## Phase 1 — current state inventory

| Surface | DNS / hosting | Today's behavior | Owner |
|---|---|---|---|
| `thegoatnote.com` (apex) | A → `76.76.21.21` (Vercel anycast) | HTTP 308 → `https://www.thegoatnote.com/` | Vercel domain attached to **`v0-goat-note-landing-page-3c`** (apex landing page) |
| `www.thegoatnote.com` | (via Vercel) | HTTP 200 — ElevenLabs/v0 marketing landing page | Same project: `v0-goat-note-landing-page-3c` |
| `www.thegoatnote.com/prism42` | (via Vercel) | HTTP 404 — **rewrite does not exist** | (would need to be added on `v0-goat-note-landing-page-3c`) |
| `www.thegoatnote.com/prism42-v3` | (via Vercel) | HTTP 404 — also no rewrite | Same |
| `app.thegoatnote.com` | (via Vercel) | HTTP 200 (separate project `goatnote-app`) | Different team domain |
| `prism42.thegoatnote.com` | A → `31.22.104.100` (Brev B300 pod) | HTTP 200 via Caddy → livekit-server :7880 | **DO NOT TOUCH** — load-bearing WSS signaling for LiveKit |
| `turn-prism42.thegoatnote.com` | A → `31.22.104.100` | TURN | **DO NOT TOUCH** |
| `prism42-console.vercel.app/prism42/livekit` | Vercel project `prism42-console` | HTTP 200 — current LiveKit demo (the path the user wants to move) | `prism42-console` (`prj_UCqQGmKnXhmqeQgwIHWJ9zzfX4vP`) |
| `prism42-console.vercel.app/prism42-v3` | Same project | HTTP 200 — backup ElevenLabs path (must remain reachable) | Same |

Vercel custom domains attached to `prism42-console`: **none** (only auto-generated `*.vercel.app`).

GoDaddy domain registration (`thegoatnote.com`): "Third Party" registrar entry, but `vercel domains ls` confirms Vercel is the DNS terminus only via individual record points. Apex still administered via GoDaddy API (we have valid `GODADDY_API_KEY` + `GODADDY_API_SECRET` in `~/prism42/.env`, names verified by `grep -c`, values not read).

Cycle-2R cutover doc (`findings/voice/cycle2R_livekit_selfhost/cutover-2026-04-26.md`) referenced `https://www.thegoatnote.com/prism42/api/livekit-token` as the production endpoint, but that was **aspirational** — the rewrite from `www.thegoatnote.com/prism42*` to the `prism42-console` project does not exist as of this probe. The production demo lives at `prism42-console.vercel.app/prism42/livekit` only.

---

## Phase 1 — decision

### Choose Path B with a small rebrand: `prism42.thegoatnote.com/livekit` is OUT, `prism42-app.thegoatnote.com` is IN.

**Path B selected.** The new public demo URL becomes:

```
https://prism42-app.thegoatnote.com/prism42/livekit
```

with a top-level redirect on the same domain:

```
https://prism42-app.thegoatnote.com         → /prism42/livekit
https://prism42-app.thegoatnote.com/prism42 → /prism42/livekit
```

so a user typing the bare hostname lands on the demo immediately.

### Why Path B (not A, not C)

| Criterion | A (`thegoatnote.com/prism42`) | B (`prism42-app.thegoatnote.com`) — chosen | C (Caddy path-routing on `prism42`) |
|---|---|---|---|
| Touches load-bearing surface? | YES — `thegoatnote.com` already serves a v0 landing page on a different Vercel project; adding `/prism42` rewrite requires modifying `v0-goat-note-landing-page-3c` source we don't own in this repo, OR detaching the apex domain from that project and re-attaching to `prism42-console` (which would break the marketing page). | NO — brand-new subdomain, zero collisions. | YES — would re-route `/` on `prism42.thegoatnote.com` away from livekit-server. Hard constraint says don't break that. |
| Apex DNS gotchas? | YES — `thegoatnote.com` apex already 308s to `www`. Untangling the apex on a Vercel-multi-project setup is not a 90-min job. | NO — a CNAME on a fresh subdomain has none of the apex flattening / ALIAS problems. | N/A |
| Reversible? | Hard — would require re-attaching apex to v0 project on rollback. | Trivial — DELETE the CNAME + remove the Vercel domain; no other surface is affected. | Hard — any Caddy mistake takes down the active LiveKit signaling. |
| Affects `wss://prism42.thegoatnote.com`? | No (different host) | No (different host) | YES |
| Affects `prism42-console.vercel.app/prism42-v3`? | No (paths preserved) | No (paths preserved) | No |
| Time to ship | 30-60 min (apex domain dance with Vercel) + risk of breaking marketing page | 15-25 min (single CNAME + one `vercel domains add`) | 60+ min + B300 SSH + Caddy restart |

Path B optimizes for: (i) hard constraint of not breaking `wss://prism42.thegoatnote.com`, (ii) trivial rollback, (iii) Vercel's first-class custom-domain UX (auto-TLS via cert manager), (iv) zero blast radius on the marketing page, (v) shippable inside the 90-min budget.

### Why not the Path-A "bonus"

Path A rewrite (`thegoatnote.com/prism42 → prism42-console`) is **not implemented** in this cycle for two reasons:

1. The rewrite has to land in `v0-goat-note-landing-page-3c`'s codebase, which is not in this monorepo. We'd need to (a) find and clone that repo, (b) add `next.config.js` rewrites or a Vercel monorepo project link, (c) deploy it, (d) verify the marketing page didn't regress. That is not a 30-min job at the end of a 90-min sprint.
2. The user's quote is "what happened to **prism42.thegoatnote.com or thegoatnote.com/prism42**?" — they offered both shapes. `prism42-app.thegoatnote.com` is the closest clean shape that doesn't collide with the active `prism42.thegoatnote.com` LiveKit signaling host. Pivoting the user's `prism42.thegoatnote.com` desire into `prism42-app.thegoatnote.com` keeps the brand and the architecture both intact.

If the user later wants `thegoatnote.com/prism42` literally as the URL, that becomes a follow-up work item: edit `v0-goat-note-landing-page-3c`'s `next.config.js` to add `rewrites: [{ source: '/prism42/:path*', destination: 'https://prism42-app.thegoatnote.com/prism42/:path*' }]`. That hop is a one-line addition and is documented in `applied.md` under "future-work".

---

## Phase 1 — risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GoDaddy API responds 4xx (auth, rate limit) | Low | Medium | Re-check `set -a && source ~/prism42/.env && set +a`; `grep -c` confirms keys are present (already verified). Retry with explicit `-w '%{http_code}'`. |
| Vercel rejects domain ownership verification | Low | Medium | Vercel auto-verifies via DNS record match; we control the zone. Worst case: Vercel issues a TXT challenge → add via GoDaddy API. |
| TLS cert issuance lag | Medium | Low | Vercel's edge-managed Let's Encrypt typically takes 30-90s. Phase 4 verification has a 5-min wait window. |
| Rollback on partial failure | Low | Low | DNS is single record (DELETE removes); Vercel domain detach is single CLI call. Rollback procedure documented in `rollback.md`. |
| User types `prism42-console.vercel.app/...` in habit | High | None | The old URL keeps working — we are not removing the auto-domain. The new URL is additive. |
| Team A's worker registration breaks | Low | High (would break the demo entirely) | Worker registers with `wss://prism42.thegoatnote.com`, which is a **different** subdomain. Untouched in this cycle. |

---

## Phase 1 — chosen end-state architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Browser (operator)                                                  │
└─────────────────────────────────────────────────────────────────────┘
   │                                              │
   │ 1. HTTPS GET                                 │ 2. WSS upgrade
   │    https://prism42-app.thegoatnote.com/      │    wss://prism42.thegoatnote.com
   ▼                                              ▼
 ┌────────────────────────────────┐    ┌──────────────────────────────────┐
 │ Vercel edge anycast            │    │ Brev B300 pod (31.22.104.100)    │
 │ project: prism42-console       │    │ Caddy → livekit-server :7880     │
 │ (Next.js, /prism42/livekit)    │    │ (UNCHANGED — load-bearing)       │
 └────────────────────────────────┘    └──────────────────────────────────┘
              │
              │ token API (POST /prism42/api/livekit-token)
              │ returns: { url: "wss://prism42.thegoatnote.com",
              │            token: "<JWT>" }
              ▼
 (browser SDK opens WSS to prism42.thegoatnote.com per token URL)
```

Two distinct subdomains, two distinct purposes:

- `prism42-app.thegoatnote.com` — **app frontend** (Vercel) — the URL the user navigates to, has the LiveKit demo UI
- `prism42.thegoatnote.com` — **backend signaling** (B300 pod) — what the browser SDK opens WSS against, after the frontend hands it a token

This is the standard separation-of-concerns split. The user gets a clean URL, the architecture stays correct.
