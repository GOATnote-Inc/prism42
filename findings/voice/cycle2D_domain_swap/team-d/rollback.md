# cycle-2D — Rollback procedure (Team D)

If the new domain misbehaves, every step from `applied.md` is reversible. None of them touched load-bearing services (`prism42.thegoatnote.com`, B300 pod, livekit-server, prism42-worker).

The `prism42-console.vercel.app/prism42/livekit` original URL **was never removed**, so even with zero rollback action the demo remains reachable at the old URL.

---

## Rollback layers (least-invasive first)

### Layer 0 — DO NOTHING (recommended first response)

The new URL is **additive**. The old URL still works. If the new URL has a bug, route the user back to:

```
https://prism42-console.vercel.app/prism42/livekit
```

Investigate at leisure.

### Layer 1 — Remove only the redirect (keep the domain)

If `prism42-app.thegoatnote.com` exists and the user wants to keep that hostname, but the redirect to `/prism42/livekit` is wrong, edit `mvp/911-console-live/vercel.json` and remove the entire `redirects` array (or change the destination), then redeploy:

```bash
# Edit vercel.json — remove the redirects[] block added in cycle-2D
# Then deploy:
$ cp /Users/kiteboard/prism42/.vercel/project.json /tmp/d-rollback.bak
$ cp /Users/kiteboard/prism42/mvp/911-console-live/.vercel/project.json /Users/kiteboard/prism42/.vercel/project.json
$ cd /Users/kiteboard/prism42 && vercel --prod --yes
$ cp /tmp/d-rollback.bak /Users/kiteboard/prism42/.vercel/project.json
```

### Layer 2 — Detach the Vercel custom domain

Removes the domain from the Vercel project. After this, `https://prism42-app.thegoatnote.com` will return Vercel's "domain not in project" 404 page (cert remains valid for ~30 days but no project answers).

```bash
$ cd /Users/kiteboard/prism42/mvp/911-console-live/
$ vercel domains rm prism42-app.thegoatnote.com
# CLI will prompt for confirmation; type the domain to confirm.
```

Or via REST API (no prompt):

```bash
$ TOKEN="<vercel-token>"   # from ~/Library/Application Support/com.vercel.cli/auth.json
$ curl -X DELETE \
    -H "Authorization: Bearer $TOKEN" \
    "https://api.vercel.com/v9/projects/prism42-console/domains/prism42-app.thegoatnote.com?teamId=team_9F90ShqNvPoaCCkhrjCCw91r"
```

### Layer 3 — Delete the GoDaddy CNAME

Removes DNS resolution. After this + DNS TTL expiration (10 min, since we set TTL=600), `dig prism42-app.thegoatnote.com` returns NXDOMAIN.

```bash
$ GODADDY_API_KEY=$(grep '^GODADDY_API_KEY=' /Users/kiteboard/prism42/.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
$ GODADDY_API_SECRET=$(grep '^GODADDY_API_SECRET=' /Users/kiteboard/prism42/.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
$ curl -sS -X DELETE "https://api.godaddy.com/v1/domains/thegoatnote.com/records/CNAME/prism42-app" \
    -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}" \
    -w '\nHTTP_CODE=%{http_code}\n'
# Expect: HTTP_CODE=204
```

Read-back to confirm:

```bash
$ curl -sS -X GET "https://api.godaddy.com/v1/domains/thegoatnote.com/records/CNAME/prism42-app" \
    -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}"
# Expect: []
```

### Layer 4 — Roll back vercel.json edit (full revert)

If the redirects were the only `vercel.json` change in this cycle (they were), revert the file:

```bash
$ cd /Users/kiteboard/prism42
$ git diff mvp/911-console-live/vercel.json   # confirms the cycle-2D diff is the only change
$ git checkout -- mvp/911-console-live/vercel.json
```

Then redeploy via the project.json swap trick (see `applied.md` Step 4).

---

## Post-rollback verification

After any rollback layer, re-run the verification matrix (see `verification.md`) and confirm:

- The OLD URL `https://prism42-console.vercel.app/prism42/livekit` still returns HTTP 200 (it should — we never touched it)
- `https://prism42.thegoatnote.com` still returns 200 via Caddy (B300 pod unchanged)
- ElevenLabs backup at `https://prism42-console.vercel.app/prism42-v3` still returns 200

---

## Per-step risk scoring (during rollback)

| Layer | Affects backup URLs? | Affects LiveKit signaling? | Affects worker registration? |
|---|---|---|---|
| 0 (do nothing) | No | No | No |
| 1 (remove redirect) | No | No | No |
| 2 (detach Vercel domain) | No | No | No |
| 3 (delete GoDaddy CNAME) | No | No | No |
| 4 (revert vercel.json) | No | No | No |

**Every rollback layer is safe.** None of them touch the B300 pod, the worker, or any production-critical surface.
