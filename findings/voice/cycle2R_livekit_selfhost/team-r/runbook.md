---
title: cycle-2R LiveKit self-host — execution runbook
team: Team R (LiveKit Cloud → B300 self-host migration)
ship-by: EOD 2026-04-26
prereq-research: ../../cycle2Q_livekit_selfhost/research.md
status: EXECUTION-READY (integrator runs, gated steps require explicit auth)
date: 2026-04-26
---

# cycle-2R — LiveKit self-host execution runbook

This document is the **typed-out, top-to-bottom integrator runbook** that promotes cycle-2Q's research draft (§6) into shippable form. Every step has: (a) prereqs + verification, (b) exact command, (c) expected output, (d) verify-exit-code, (e) rollback, (f) gate flag.

Companion files:
- [run.sh](./run.sh) — single bash entrypoint, gated by `PRISM42_AUTH_G{2,3,4}` env vars, supports `--phase=N` for incremental runs
- [rollback.sh](./rollback.sh) — idempotent, last step always restores LiveKit Cloud as active backend on Vercel

---

## 0. Verified facts (frozen as of 2026-04-26 ~08:30 UTC)

| Fact | Value | Source |
|---|---|---|
| Pod hostname | `b300-pod` | main agent recon |
| Pod public IPv4 | `31.22.104.100` (eth0, not NATed) | main agent recon |
| livekit-server already running | bare-process pid 76823, on tcp/7880, tcp/7881, udp/7882 | main agent recon |
| Firewall posture | UFW active, default DROP, only 22 + 2222 (SSH) allowed | main agent recon |
| cloudflared running | pid 11240, Brev's TCP-only tunnel — **not usable for media UDP** | main agent recon |
| DNS staged earlier | `prism42.thegoatnote.com` → may already resolve to 31.22.104.100; verify in Phase 0 | CLAUDE.md |
| Domain registrar | GoDaddy; API key sourced from `~/lostbench/.env` (DO NOT read directly per hard-rule) | CLAUDE.md |
| Vercel project | `mvp/911-console-live/` (Next.js), preview at `prism42-console.vercel.app` | repo |
| Token route | `~/prism42/mvp/911-console-live/app/prism42/api/livekit-token/route.ts` (signs JWT, returns `livekit_url` to client) | repo |
| LiveKit page | `~/prism42/mvp/911-console-live/app/prism42/livekit/page.tsx` (uses `<LiveCallRoom>`; URL comes from token-route response, no env read in page itself) | repo |
| Fallback URL to preserve | `/prism42-v3` (ElevenLabs path) — must keep working post-cutover | task spec |

---

## Gate ladder

| Gate | Authorization | What it grants |
|---|---|---|
| G1 | none — automatic | read-only verification (`dig`, `curl -I`, `ss`, `ufw status`) |
| G2 | `PRISM42_AUTH_G2=1` + GoDaddy API creds in env | DNS PATCH on `thegoatnote.com` zone |
| G3 | `PRISM42_AUTH_G3=1` | UFW rule additions + Caddy install + Caddyfile + `systemctl enable --now caddy` |
| G4 | `PRISM42_AUTH_G4=1` | systemd takeover of livekit-server (kills bare pid 76823) |
| G5 | none — Vercel API token in env | env-var add + preview deploy |
| G6 | `PRISM42_AUTH_G6=1` | Production env flip to `LIVEKIT_BACKEND=selfhost` |

The bash script refuses to run any G2+ step without the matching env var set.

---

## Phase 0 — DNS resolution (Gate G2)

**Goal:** Both `prism42.thegoatnote.com` and `turn-prism42.thegoatnote.com` resolve to `31.22.104.100` from public DNS resolvers (1.1.1.1 + 8.8.8.8).

### 0.1 Verify current state (G1, no auth needed)

```bash
# Expected: 31.22.104.100 (or empty if not yet pointed)
dig +short @1.1.1.1 prism42.thegoatnote.com
dig +short @8.8.8.8 prism42.thegoatnote.com
dig +short @1.1.1.1 turn-prism42.thegoatnote.com
dig +short @8.8.8.8 turn-prism42.thegoatnote.com
```

**Gate decision:** If both records already return `31.22.104.100`, **skip Phase 0** entirely. Move to Phase 1.

### 0.2 GoDaddy API PATCH (G2 — needs auth)

GoDaddy Domains API v1 reference: <https://developer.godaddy.com/doc/endpoint/domains#/v1/recordReplaceTypeName> (fetched 2026-04-26).

API endpoint shape: `PUT https://api.godaddy.com/v1/domains/{domain}/records/{type}/{name}` — replaces all records of `type` with name `name`. Auth header: `Authorization: sso-key <KEY>:<SECRET>`.

**Prereqs:**
- `GODADDY_API_KEY` and `GODADDY_API_SECRET` set in environment (the integrator sources these from `~/lostbench/.env` per hard-rule — DO NOT read that file directly).

```bash
# GATE_G2 — DNS auth required
test -n "${GODADDY_API_KEY:-}" || { echo "FATAL: GODADDY_API_KEY not set"; exit 2; }
test -n "${GODADDY_API_SECRET:-}" || { echo "FATAL: GODADDY_API_SECRET not set"; exit 2; }

# PATCH prism42.thegoatnote.com → 31.22.104.100
curl -fsS -X PUT "https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/prism42" \
  -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}" \
  -H "Content-Type: application/json" \
  -d '[{"data":"31.22.104.100","ttl":600}]'

# PATCH turn-prism42.thegoatnote.com → 31.22.104.100
curl -fsS -X PUT "https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/turn-prism42" \
  -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}" \
  -H "Content-Type: application/json" \
  -d '[{"data":"31.22.104.100","ttl":600}]'
```

**Expected output:** Empty body, HTTP 200. `curl -fsS` will exit non-zero on any 4xx/5xx.

**Verify (wait for propagation; TTL=600 ⇒ up to 10 min):**

```bash
# Poll until both resolvers return 31.22.104.100; bail after 12 min
deadline=$(( $(date +%s) + 720 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  v1=$(dig +short @1.1.1.1 prism42.thegoatnote.com | tr -d '\n')
  v2=$(dig +short @8.8.8.8 prism42.thegoatnote.com | tr -d '\n')
  v3=$(dig +short @1.1.1.1 turn-prism42.thegoatnote.com | tr -d '\n')
  v4=$(dig +short @8.8.8.8 turn-prism42.thegoatnote.com | tr -d '\n')
  if [ "$v1" = "31.22.104.100" ] && [ "$v2" = "31.22.104.100" ] && \
     [ "$v3" = "31.22.104.100" ] && [ "$v4" = "31.22.104.100" ]; then
    echo "DNS verified: all 4 lookups → 31.22.104.100"
    break
  fi
  echo "DNS not yet propagated (1.1.1.1=$v1 8.8.8.8=$v2 turn=$v3/$v4); sleeping 30s"
  sleep 30
done
```

**Verify exit code:** the loop's `break` lands in success branch; if loop exits via deadline, exit 1.

### 0.3 Rollback (Phase 0)

```bash
# GATE_G2 — DNS rollback
# Replace A-records with 0.0.0.0 (or omit body to delete; GoDaddy rejects empty bodies, so set to placeholder)
curl -fsS -X PUT "https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/prism42" \
  -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}" \
  -H "Content-Type: application/json" \
  -d '[{"data":"0.0.0.0","ttl":600}]'
curl -fsS -X PUT "https://api.godaddy.com/v1/domains/thegoatnote.com/records/A/turn-prism42" \
  -H "Authorization: sso-key ${GODADDY_API_KEY}:${GODADDY_API_SECRET}" \
  -H "Content-Type: application/json" \
  -d '[{"data":"0.0.0.0","ttl":600}]'
```

**Note:** Once Caddy issues a Let's Encrypt cert against the live A-record (Phase 2), the rollback semantics change — rolling DNS back to 0.0.0.0 leaves Caddy holding a cert it can't renew. The runbook's full rollback sequence (rollback.sh) reverses Phase 2 first, then Phase 0.

### 0.4 Munger inversion (Phase 0)

**Most likely failure mode:** DNS PATCH returns 200 but resolvers still cache the old NXDOMAIN / wrong A-record for >10 min. Public resolvers honor the TTL of the *previous* record, not the new one. If we set TTL=600 but the prior NXDOMAIN was cached with TTL=3600, propagation can stall.

**Mitigation:** Use TTL=600 going in. If propagation stalls past 12 min, query the GoDaddy resolver directly: `dig @ns01.domaincontrol.com prism42.thegoatnote.com` — if that returns `31.22.104.100`, the authoritative answer is correct; the public-resolver cache is the bottleneck, and we either wait it out or proceed (Caddy ACME will retry on its own schedule).

---

## Phase 1 — UFW open production media ports (Gate G3)

**Goal:** Pod's UFW allows inbound on the LiveKit port set, while keeping default DROP for everything else.

### 1.1 Pre-check (G1)

```bash
# Run on pod
sudo ufw status numbered
# Expected: Status: active; only 22, 2222 ALLOW IN
```

### 1.2 Open required ports (G3)

Per cycle-2Q research §3, the canonical port set is:
- TCP: 7880 (signaling), 7881 (media-over-TCP fallback), 80 (ACME HTTP-01), 443 (HTTPS), 5349 (TURN/TLS)
- UDP: 7882 (LiveKit RTC primary, already in use by bare process), 50000-60000 (SFU media), 3478 (TURN/UDP)

```bash
# GATE_G3 — UFW + Caddy install auth required
sudo ufw allow 7880/tcp comment 'livekit signaling (WSS via Caddy upstream)'
sudo ufw allow 7881/tcp comment 'livekit media TCP fallback'
sudo ufw allow 7882/udp comment 'livekit RTC primary'
sudo ufw allow 50000:60000/udp comment 'livekit SFU media range'
sudo ufw allow 3478/udp comment 'livekit TURN UDP'
sudo ufw allow 5349/tcp comment 'livekit TURN TLS'
sudo ufw allow 80/tcp comment 'caddy ACME HTTP-01'
sudo ufw allow 443/tcp comment 'caddy HTTPS'
sudo ufw reload
```

**Expected output:** `Rule added` for each, then `Firewall reloaded`.

**Verify (on pod):**

```bash
sudo ufw status numbered
# Expected: 8 new ALLOW IN rules above. Exit 0.
```

**Smoke from external machine** (run on integrator's laptop, not pod):

```bash
# These will only succeed after livekit-server + Caddy are running, but
# we can pre-check that the firewall isn't dropping the TCP handshake.
# Note: until the daemons listen, "connection refused" (TCP RST) is GOOD —
# it means the firewall let the SYN through and the kernel rejected because
# nothing is listening yet. "connection timed out" is BAD — that's UFW DROP.
nc -zv -w 5 31.22.104.100 7880
nc -zv -w 5 31.22.104.100 443
# UDP smoke: send a single byte and see if the kernel responds.
# After livekit-server is up, this will get an ICMP port-unreachable or silence
# (UDP can't tell the difference). Useful only for confirming kernel reachability.
echo | nc -u -w 2 31.22.104.100 7882
```

### 1.3 Rollback (Phase 1)

```bash
# Delete each rule by *number* — but numbers shift as you delete.
# Idempotent approach: delete by spec.
sudo ufw delete allow 7880/tcp
sudo ufw delete allow 7881/tcp
sudo ufw delete allow 7882/udp
sudo ufw delete allow 50000:60000/udp
sudo ufw delete allow 3478/udp
sudo ufw delete allow 5349/tcp
sudo ufw delete allow 80/tcp
sudo ufw delete allow 443/tcp
sudo ufw reload
```

### 1.4 Munger inversion (Phase 1)

**Most likely failure mode:** UFW silently rejects the range `50000:60000/udp` because the syntax isn't supported on this Ubuntu version (older UFW used `50000-60000`). Result: 10,001 ports stay DROPped, SFU media silently fails on demo-day.

**Mitigation:** After `ufw allow 50000:60000/udp`, verify the rule landed: `sudo iptables -L INPUT -n -v | grep 50000` should show `ACCEPT udp -- ... dpts:50000:60000`. If absent, fall back to `sudo ufw allow proto udp from any to any port 50000:60000`. Reference: <https://manpages.ubuntu.com/manpages/jammy/en/man8/ufw.8.html> (fetched 2026-04-26).

---

## Phase 2 — Caddy install + Caddyfile (Gate G3)

**Goal:** Caddy 2.x reverse-proxies `https://prism42.thegoatnote.com` → `127.0.0.1:7880` (signaling) and `tls`-terminates `turn-prism42.thegoatnote.com` → `127.0.0.1:5349` (TURN/TLS).

### 2.1 Pre-check (G1)

```bash
# On pod
which caddy 2>/dev/null && caddy version  # if already installed, skip 2.2
```

### 2.2 Install Caddy via official Debian package (G3)

Caddy ships an official Cloudsmith-hosted apt repo. Reference: <https://caddyserver.com/docs/install#debian-ubuntu-raspbian> (fetched 2026-04-26).

```bash
# GATE_G3 — Caddy install
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
  sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-cache policy caddy   # verify the package is visible from the new repo
sudo apt-get install -y caddy
caddy version                  # expected: v2.x.y h1:...
```

**Verify exit code:** `caddy version` exits 0 with a v2.x.y string.

### 2.3 Write `/etc/caddy/Caddyfile` (G3)

Caddyfile reference: <https://caddyserver.com/docs/caddyfile> (fetched 2026-04-26). Reverse-proxy directive: <https://caddyserver.com/docs/caddyfile/directives/reverse_proxy> (fetched 2026-04-26).

```bash
# GATE_G3 — Caddy config
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
prism42.thegoatnote.com {
    reverse_proxy 127.0.0.1:7880
    log {
        output file /var/log/caddy/livekit.log
        format json
    }
}

turn-prism42.thegoatnote.com {
    tls {
        protocols tls1.2 tls1.3
    }
    reverse_proxy 127.0.0.1:5349
}
EOF

sudo mkdir -p /var/log/caddy
sudo chown caddy:caddy /var/log/caddy
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

**Expected output of validate:** `Valid configuration` (exit 0). Any warning-as-info lines are fine; errors fail loud.

### 2.4 Start Caddy (G3)

```bash
# GATE_G3 — start daemon
sudo systemctl enable --now caddy
sleep 5
sudo systemctl status caddy --no-pager | head -20
```

**Expected output of status:** `Active: active (running)`.

### 2.5 Verify ACME issuance (G1)

ACME issuance happens on first request to the domain. Caddy initiates HTTP-01 challenge against port 80; LE responds with a cert.

```bash
# Watch logs for issuance
sudo journalctl -u caddy --since="2 min ago" -n 200 | \
  grep -E "certificate obtained|tls handshake|certificate magic|signed certificate|ACME"
# Expected within 30-90s: "certificate obtained successfully" or
# "served key authentication" + "obtained certificate".
```

**External smoke (from integrator laptop):**

```bash
# Should return HTTP/2 with valid TLS — Caddy auto-issues + serves
# even before livekit-server is wired through. The 502 from upstream
# is fine: it proves TLS is correct and Caddy's only complaint is the
# upstream is bare-process not bound to 127.0.0.1.
curl -sI https://prism42.thegoatnote.com 2>&1 | head -10
# Expected one of:
#   HTTP/2 200 ... Server: livekit-server      (livekit-server already on 7880)
#   HTTP/2 502 ... Server: Caddy               (livekit-server not listening on 127.0.0.1)
# Either is acceptable evidence that TLS issuance worked.

# TLS cert sanity:
openssl s_client -connect prism42.thegoatnote.com:443 -servername prism42.thegoatnote.com </dev/null 2>/dev/null | \
  openssl x509 -noout -issuer -subject -dates
# Expected: issuer=C=US, O=Let's Encrypt, CN=...; subject CN=prism42.thegoatnote.com; valid 90 days
```

### 2.6 Rollback (Phase 2)

```bash
sudo systemctl disable --now caddy
sudo apt-get remove -y caddy
sudo rm -f /etc/caddy/Caddyfile
sudo rm -rf /var/log/caddy
# Cert files in /var/lib/caddy can stay; harmless when daemon is gone.
```

### 2.7 Munger inversion (Phase 2)

**Most likely failure mode:** Caddy ACME challenge fails because:
1. DNS hasn't propagated (Phase 0 incomplete) — Caddy retries with exponential backoff. Fix: wait, or `sudo systemctl restart caddy` after DNS verified.
2. Port 80 blocked — UFW didn't open 80 (Phase 1 partial). Fix: `sudo ufw allow 80/tcp`.
3. The bare-process livekit-server on `0.0.0.0:7880` was already binding to the public IP — Caddy's reverse_proxy is to `127.0.0.1:7880`, but the bare process may only listen on the public interface. Fix: confirm via `ss -tlnp | grep 7880` — if it shows `0.0.0.0:7880` or `*:7880`, Caddy can still reach it via 127.0.0.1; if it shows only `31.22.104.100:7880`, the Phase 3 systemd takeover MUST bind to all interfaces (the default behavior of livekit-server).

**Most-overlooked failure:** Caddy's default config in `/etc/caddy/Caddyfile` (the example one shipped with the package) takes precedence if the upgrade re-creates it. Always `sudo caddy validate` and visually inspect the file before `systemctl restart`.

---

## Phase 3 — livekit-server systemd takeover (Gate G4)

**Goal:** Replace the bare-process pid 76823 with a `livekit-server.service` systemd unit that auto-restarts on failure, owns its own config file, and outlives shell sessions.

**Critical dependency:** Team A's forensic must determine which option to use:
- **Option A (takeover):** Stop bare process, replace with systemd. The bare process has no config file we control, or its config is lost / unauditable.
- **Option B (keep + wrap):** Bare process is fine; just write a systemd unit that calls the same cmdline and stop the bare process atomically. Used when Team A determines the bare process's keys are already wired to the worker and changing them is a risk.
- **Option C (stop + replace):** Stop bare process. Don't restart yet. Used when Team A wants to pivot to LiveKit Cloud-only path or has discovered the daemon needs reconfig before relaunch.

**The runbook below documents all three branches. The integrator chooses based on Team A's recommendation.**

### 3.1 Pre-check (G1)

```bash
# What's running today?
ps -p 76823 -o pid,user,cmd --no-headers || echo "pid 76823 is gone — already stopped"
ss -tunlp | grep -E ':7880|:7881|:7882' | head -10
# Get the cmdline + working dir Team A captured:
cat /proc/76823/cmdline | tr '\0' ' '; echo
readlink /proc/76823/cwd
# Capture the current config (so rollback can recreate it):
sudo find / -name 'livekit*.yaml' -o -name 'livekit*.yml' 2>/dev/null | head -20
```

### 3.2 Branch — Option A: Full takeover (G4)

#### 3.2.1 Stop the bare process

```bash
# GATE_G4 — systemd takeover, kills bare pid
sudo kill -TERM 76823
sleep 3
ps -p 76823 -o pid 2>/dev/null && { echo "Process did not exit on SIGTERM; sending SIGKILL"; sudo kill -KILL 76823; sleep 1; }
ss -tunlp | grep -E ':7880|:7881|:7882' && { echo "FATAL: ports still occupied"; exit 1; } || echo "ports clear"
```

#### 3.2.2 Author `/opt/livekit/livekit.yaml`

Use Team A's discovered keys. **DO NOT generate new ones unless Team A confirms config is missing.** If Team A says `keys` block must be created fresh, the integrator generates with `openssl rand -hex 32` and saves both halves to a secret-store; do not commit to git.

Schema reference: <https://github.com/livekit/livekit/blob/master/config-sample.yaml> (fetched 2026-04-26).

```bash
# GATE_G4 — config file
sudo mkdir -p /opt/livekit
sudo tee /opt/livekit/livekit.yaml > /dev/null <<'EOF'
# cycle-2R self-hosted livekit-server config
# Single-node, no Redis, TURN bundled.
port: 7880
bind_addresses:
  - "0.0.0.0"
rtc:
  port_range_start: 50000
  port_range_end: 60000
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: true
turn:
  enabled: true
  domain: turn-prism42.thegoatnote.com
  tls_port: 5349
  udp_port: 3478
  external_tls: true
keys:
  # Replace with Team A's discovered key/secret pair.
  # Format: <api-key>: <api-secret-32-char-hex>
  REPLACE_WITH_TEAM_A_KEY: REPLACE_WITH_TEAM_A_SECRET
room:
  empty_timeout: 300
  max_participants: 4
log_level: info
EOF
sudo chmod 600 /opt/livekit/livekit.yaml
sudo chown shadeform:shadeform /opt/livekit/livekit.yaml
```

**Verify config syntactically valid:**

```bash
# livekit-server's --check-config flag was added in v1.x; if the binary
# rejects it, fall back to a dry-run start.
livekit-server --config /opt/livekit/livekit.yaml --check-config 2>&1 | head -20 || \
  timeout 3 livekit-server --config /opt/livekit/livekit.yaml 2>&1 | head -20
# Expected: prints "starting LiveKit server" and binds ports in <1s; we
# kill it via timeout. No "fatal: ..." or "yaml: unmarshal" errors.
```

#### 3.2.3 Write systemd unit

Reference: <https://docs.livekit.io/home/self-hosting/vm/> (fetched 2026-04-26) shows a similar systemd unit shape.

```bash
# GATE_G4 — systemd unit
sudo tee /etc/systemd/system/livekit-server.service > /dev/null <<'EOF'
[Unit]
Description=LiveKit SFU server (cycle-2R self-hosted)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=shadeform
ExecStart=/usr/local/bin/livekit-server --config /opt/livekit/livekit.yaml
Restart=on-failure
RestartSec=5s
LimitNOFILE=500000

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now livekit-server
sleep 3
sudo systemctl status livekit-server --no-pager | head -25
```

**Expected output of status:** `Active: active (running)`.

**Verify ports:**

```bash
ss -tunlp | grep -E ':7880|:7881|:7882|:3478|:5349' | sort
# Expected:
#   tcp ... 0.0.0.0:7880     livekit-server  (signaling)
#   tcp ... 0.0.0.0:7881     livekit-server  (media TCP)
#   udp ... 0.0.0.0:7882     livekit-server  (RTC primary)
#   udp ... 0.0.0.0:3478     livekit-server  (TURN UDP)
#   tcp ... 0.0.0.0:5349     livekit-server  (TURN TLS)
# UDP 50000-60000 will only appear when a room is active; verifying via
# `ss` is a false-negative for those.
```

### 3.3 Branch — Option B: Keep bare process + wrap (G4)

If Team A says the bare process is correctly configured and we should not stop it:

```bash
# GATE_G4 — wrap-only: capture cmdline, then replace via systemd atomically.
# Idea: write a unit whose ExecStart matches the bare cmdline, then
# `systemctl start` while bare is running — systemd will complain port-in-use,
# we then `kill -TERM 76823` and systemctl auto-restarts in <5s.
# Skipped here because Option A is functionally identical and simpler.
echo "Option B: write the same /etc/systemd/system/livekit-server.service as Option A."
echo "Stop bare process: sudo kill -TERM 76823; systemctl auto-restarts."
```

### 3.4 Branch — Option C: Stop + replace (no restart yet) (G4)

```bash
# GATE_G4 — stop only
sudo kill -TERM 76823
sleep 3
ss -tunlp | grep -E ':7880|:7881|:7882' && echo "still up — escalate to KILL" || echo "stopped"
# Defer livekit-server restart pending further Team decisions. Vercel
# preview will fail at this point — that is intentional under Option C.
```

### 3.5 Rollback (Phase 3)

```bash
# GATE_G4 — rollback systemd takeover
sudo systemctl disable --now livekit-server
sudo rm -f /etc/systemd/system/livekit-server.service
sudo systemctl daemon-reload
# Re-launch the bare process from the cmdline Team A captured pre-takeover.
# Example placeholder — the integrator substitutes the real cmdline:
#   nohup /usr/local/bin/livekit-server --config /opt/livekit/livekit-original.yaml \
#     > /var/log/livekit-server-bare.log 2>&1 &
echo "Rollback: re-launch bare livekit-server using Team A's captured cmdline."
echo "Verify: ss -tunlp | grep 7880 ; ps aux | grep livekit-server"
```

### 3.6 Munger inversion (Phase 3)

**Most likely failure mode #1:** Killing pid 76823 also drops the active LiveKit Cloud handshake — *if* the agent worker is currently registered against `wss://ai-therapy-v3svfd9o.livekit.cloud`. Wait — no, the bare process is *self-hosted* livekit-server (not Cloud); the agent worker pre-cycle-2R is registered against Cloud. So killing 76823 does not affect Cloud-side traffic. **Verify before kill:** `journalctl -u prism42-worker --since=10min | grep "registered worker"` — confirm worker URL string.

**Most likely failure mode #2:** systemd unit fails to start because livekit-server binary isn't at `/usr/local/bin/livekit-server` — `which livekit-server` may show `/opt/livekit/bin/livekit-server` or similar. Fix: `which livekit-server` and substitute the actual path into `ExecStart=` before reload.

**Most likely failure mode #3:** `User=shadeform` causes systemd to fail with `Failed to determine user credentials: No such process` — the user account on a Brev pod may be `ubuntu`, `brev`, or root. Fix: `id -un` to discover, then substitute. If running as root is acceptable for the demo, drop the `User=` line entirely and the service runs as root (LiveKit doesn't require root; this is a security tradeoff worth flagging to the user before commit).

**Most-overlooked failure:** systemd `LimitNOFILE=500000` is denied because the system-wide `/etc/security/limits.conf` cap is 65536. LiveKit handles ~100 concurrent rooms with ~10k FDs, so 65536 is fine; the unit is non-fatal at lower NOFILE. Just monitor `journalctl -u livekit-server | grep "too many open files"`.

---

## Phase 4 — Vercel env-flag + dual-backend code path (low risk)

**Goal:** The token-mint route honors `LIVEKIT_BACKEND={cloud,selfhost}`. When `selfhost`, it picks `LIVEKIT_API_KEY_SELFHOST`, `LIVEKIT_API_SECRET_SELFHOST`, `NEXT_PUBLIC_LIVEKIT_URL_SELFHOST`. Default = `cloud`. Frontend page reads URL from token-route response (already does — no page change needed).

**Verified by repo grep (2026-04-26):**
- `app/prism42/api/livekit-token/route.ts:26-28` reads `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `NEXT_PUBLIC_LIVEKIT_URL`.
- `components/LiveCallRoom.tsx:100-102` consumes `livekit_url` from the token-route JSON response — no `process.env.NEXT_PUBLIC_LIVEKIT_URL` read on the client side. So the only file that needs modification is the token route.

### 4.1 Modify the token route

Edit `~/prism42/mvp/911-console-live/app/prism42/api/livekit-token/route.ts`:

```typescript
// Replace lines 25-35 with:
export async function POST(req: Request): Promise<Response> {
  const backend = (process.env.LIVEKIT_BACKEND ?? "cloud").toLowerCase();
  const isSelfhost = backend === "selfhost";

  const apiKey = isSelfhost
    ? process.env.LIVEKIT_API_KEY_SELFHOST
    : process.env.LIVEKIT_API_KEY;
  const apiSecret = isSelfhost
    ? process.env.LIVEKIT_API_SECRET_SELFHOST
    : process.env.LIVEKIT_API_SECRET;
  const livekitUrl = isSelfhost
    ? process.env.NEXT_PUBLIC_LIVEKIT_URL_SELFHOST
    : process.env.NEXT_PUBLIC_LIVEKIT_URL;

  if (!apiKey || !apiSecret || !livekitUrl) {
    return NextResponse.json(
      {
        error: "livekit_not_configured",
        backend,
        missing: (isSelfhost
          ? ["LIVEKIT_API_KEY_SELFHOST", "LIVEKIT_API_SECRET_SELFHOST", "NEXT_PUBLIC_LIVEKIT_URL_SELFHOST"]
          : ["LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "NEXT_PUBLIC_LIVEKIT_URL"]
        ).filter((k) => !process.env[k]),
      },
      { status: 500 },
    );
  }
  // ... rest unchanged (body parse, identity, AccessToken mint, return)
}
```

The rest of the file (body parse, identity derivation, `AccessToken` construction, JSON return) is identical. No frontend changes needed because `livekit_url` is delivered through the token-route response.

### 4.2 Add Vercel preview env vars (G5)

Vercel CLI ref: <https://vercel.com/docs/cli/env> (fetched 2026-04-26).

```bash
# Run from ~/prism42/mvp/911-console-live
# Auth: VERCEL_TOKEN env var must be set (sourced by integrator from
# the canonical .env). DO NOT commit the token.
cd ~/prism42/mvp/911-console-live

# Preview env only (NOT production) — production stays cloud through Phase 5.
vercel env add LIVEKIT_BACKEND preview <<<"selfhost"
vercel env add NEXT_PUBLIC_LIVEKIT_URL_SELFHOST preview <<<"wss://prism42.thegoatnote.com"
vercel env add LIVEKIT_API_KEY_SELFHOST preview         # interactive: paste from Team A
vercel env add LIVEKIT_API_SECRET_SELFHOST preview      # interactive: paste from Team A
```

**Verify:**

```bash
vercel env ls preview | grep -E "LIVEKIT_BACKEND|NEXT_PUBLIC_LIVEKIT_URL_SELFHOST|LIVEKIT_API_KEY_SELFHOST|LIVEKIT_API_SECRET_SELFHOST"
# Expected: 4 lines, all "preview" environment, ages "just now"
```

### 4.3 Add same env vars to pod's agent worker `.env`

The agent worker registers OUTBOUND with livekit-server using its API key/secret pair. It needs to see the new `LIVEKIT_URL` and the matching key/secret.

**Critical:** the agent worker file path on the pod was `/opt/prism42/worker/.env` per CLAUDE.md memory; integrator confirms via `systemctl cat prism42-worker | grep EnvironmentFile`. Below substitutes a placeholder.

```bash
# On pod, as root or shadeform
WORKER_ENV=/opt/prism42/worker/.env   # SUBSTITUTE actual path from systemd unit
sudo cp "$WORKER_ENV" "${WORKER_ENV}.cycle2R-backup"

# Append (don't overwrite existing keys; let the worker pick up new vars on restart)
sudo tee -a "$WORKER_ENV" > /dev/null <<EOF
# cycle-2R: LiveKit self-host backend
LIVEKIT_BACKEND=selfhost
LIVEKIT_URL=wss://prism42.thegoatnote.com
LIVEKIT_API_KEY=<TEAM_A_KEY>
LIVEKIT_API_SECRET=<TEAM_A_SECRET>
EOF

# Restart worker
sudo systemctl restart prism42-worker

# Verify worker registered against the new URL
sleep 5
sudo journalctl -u prism42-worker --since="30 sec ago" -n 50 | \
  grep -E "registered worker|connected to|wss://prism42.thegoatnote.com"
# Expected: "registered worker ... wss://prism42.thegoatnote.com"
```

### 4.4 Vercel preview deploy (G5)

```bash
cd ~/prism42/mvp/911-console-live
vercel --prod=false   # preview deploy
# Capture the preview URL printed.
```

**Verify in browser:** open the preview URL `/prism42/livekit`. Open browser DevTools → Network → `livekit-token` → response → `livekit_url` field should be `wss://prism42.thegoatnote.com`. The page should connect to the room (LiveCallRoom mounts, no errors in console).

### 4.5 Rollback (Phase 4)

```bash
# Revert env on Vercel preview
cd ~/prism42/mvp/911-console-live
vercel env rm LIVEKIT_BACKEND preview --yes
vercel env rm NEXT_PUBLIC_LIVEKIT_URL_SELFHOST preview --yes
vercel env rm LIVEKIT_API_KEY_SELFHOST preview --yes
vercel env rm LIVEKIT_API_SECRET_SELFHOST preview --yes

# Revert worker .env on pod
sudo mv "${WORKER_ENV}.cycle2R-backup" "$WORKER_ENV"
sudo systemctl restart prism42-worker

# Revert token-route code change (git revert / undo edit)
cd ~/prism42 && git diff mvp/911-console-live/app/prism42/api/livekit-token/route.ts
# Manual: re-edit route.ts to remove backend branching.
```

### 4.6 Munger inversion (Phase 4)

**Most likely failure mode:** Worker `.env` already has `LIVEKIT_URL` set (to Cloud), and the `tee -a` appends rather than replaces. The shell environment loader picks the *last* assignment, but some loaders pick first. Result: worker registers against Cloud despite our new line.

**Mitigation:** After append, `sudo grep -c '^LIVEKIT_URL=' "$WORKER_ENV"` — if >1, manually `sudo sed -i` to remove the old line. Alternative: use a worker-side env-loader that respects last-wins (`python-dotenv` with `override=True`).

**Most-overlooked failure:** Vercel preview deploy uses **production** env vars unless the deployment is explicitly created as a preview AND the env var is set with `--target preview`. `vercel env add LIVEKIT_BACKEND preview` correctly tags as preview, but if the integrator ran `vercel env add LIVEKIT_BACKEND` without the env arg, it would default to all environments. Verify with `vercel env ls --environment preview`.

---

## Phase 5 — End-to-end voice turn smoke (low risk, manual)

**Goal:** Real laptop with mic, real browser, real voice turn through the self-hosted stack. Greeting plays; one user utterance; one dispatcher reply; no errors.

### 5.1 Pre-check (G1)

```bash
# Pod side: verify all daemons
sudo systemctl is-active livekit-server caddy prism42-worker
# Expected: 3x "active"

# External side: WSS reachable
echo | openssl s_client -connect prism42.thegoatnote.com:443 -servername prism42.thegoatnote.com 2>/dev/null | grep -E "subject|issuer"
# Expected: subject=CN=prism42.thegoatnote.com, issuer Let's Encrypt
```

### 5.2 Run the voice turn

1. Open the Vercel preview URL `/prism42/livekit` in Chrome (or any WebRTC-enabled browser).
2. Allow microphone access when prompted.
3. **Listen** for the greeting (Cartesia Sonic-3 TTS via the agent worker).
4. **Speak** one short sentence (e.g., "I need an ambulance, my address is 123 Main").
5. **Listen** for the dispatcher reply (Opus 4.7 LLM → Cartesia TTS).
6. Hang up via the page's End Call button (or close the tab).

### 5.3 Capture telemetry

In the browser DevTools console while the call is live:

```javascript
// b3-latency telemetry — emitted by LiveCallRoom on each turn
performance.getEntriesByType('measure').filter(m => m.name.startsWith('b3-')).forEach(m => console.log(m.name, m.duration.toFixed(0), 'ms'));
```

**Expected ranges (from CLAUDE.md §0 latency budget):**
- STT first-partial: 100-300 ms
- LLM TTFT: 400-800 ms (Opus 4.7)
- TTS TTFB: 80-150 ms (Cartesia Sonic-3)
- Total round-trip: <1.5 s p95

On the pod, simultaneously:

```bash
sudo journalctl -u prism42-worker --since="2 min ago" -n 200 | \
  grep -E "turn|publish|subscribe|error|warn" | tail -40
```

**Expected:** lines for `turn started`, `subscribed to caller audio`, `published agent reply`, no `error` entries. One `warn` about reconnect is acceptable; multiple are not.

### 5.4 Promotion gate

**Only flip production env to `selfhost` after:**
1. Greeting audible, intelligible.
2. Dispatcher reply audible, intelligible, semantically responsive.
3. No errors in pod log.
4. Latency telemetry within budget (p95 < 1.5s end-to-end on at least 3 consecutive turns).
5. **Brandon (user) personally listens** to the preview URL and attests it sounds correct.

### 5.5 Rollback (Phase 5)

If the smoke fails, no rollback is required at this layer — the production URL is still on Cloud. Just leave preview broken, debug, retry.

If the smoke fails AND we want to back out preview state too, run rollback.sh `--phase=4` to revert env vars + worker + code.

### 5.6 Munger inversion (Phase 5)

**Most likely failure mode #1:** Greeting plays, user speaks, no reply, then a 30-second silence, then `disconnected` in console. Cause: agent worker registered to *Cloud* livekit-server but the JWT it received is for *self-host* — JWT is signed with the wrong key/secret pair. **Mitigation:** verify worker startup log:
```
sudo journalctl -u prism42-worker --since="5 min ago" | grep -E "registered worker|connecting to"
```
The URL in the connect line MUST be `wss://prism42.thegoatnote.com`, not `wss://ai-therapy-v3svfd9o.livekit.cloud`.

**Most likely failure mode #2:** Browser connects, but no audio in either direction. Cause: UDP 50000-60000 dropped at firewall (Phase 1 rule didn't land), so SFU media can't traverse. **Mitigation:**
```bash
# On pod, check connection-tracking for active SFU traffic
sudo conntrack -L 2>/dev/null | grep "dport=5[0-9]\{4\}" | head -5
# If empty during a live call, UDP is being DROPped.
sudo iptables -L INPUT -n -v | grep -E "50000|60000"
```

**Most-overlooked failure:** Browser blocks WSS due to mixed-content if the page is loaded via `http://` instead of `https://`. The page MUST be served over HTTPS for WebRTC. Vercel preview URLs are always HTTPS, so this only bites if a tester opens the IP directly.

---

## Phase 6 — Production cutover (Gate G6)

**Pre-condition:** Brandon has personally attested Phase 5 (5.4 step 5).

### 6.1 Flip production env (G6)

```bash
# GATE_G6 — production cutover auth required
cd ~/prism42/mvp/911-console-live

# Add same env vars to PRODUCTION environment (same values as preview)
vercel env add LIVEKIT_BACKEND production <<<"selfhost"
vercel env add NEXT_PUBLIC_LIVEKIT_URL_SELFHOST production <<<"wss://prism42.thegoatnote.com"
vercel env add LIVEKIT_API_KEY_SELFHOST production         # paste same as preview
vercel env add LIVEKIT_API_SECRET_SELFHOST production      # paste same as preview

# Trigger production redeploy
vercel --prod
```

**Verify:**

```bash
vercel env ls --environment production | grep "LIVEKIT_BACKEND"
# Expected: 1 line with value "Encrypted" and target "production"

# Hit the production URL token route
curl -fsS -X POST https://www.thegoatnote.com/prism42/api/livekit-token \
  -H "Content-Type: application/json" \
  -d '{"session_id":"smoke-prod-cutover-001"}' | jq .
# Expected: {"token":"...","room":"smoke-prod-cutover-001","livekit_url":"wss://prism42.thegoatnote.com",...}
# CRITICAL: livekit_url MUST be wss://prism42.thegoatnote.com, NOT the cloud URL.
```

### 6.2 Live voice turn against production

Repeat Phase 5.2 + 5.3 against `https://www.thegoatnote.com/prism42/livekit`.

### 6.3 Preserve fallback URL

`/prism42-v3` MUST keep working — that's the ElevenLabs path. Verify:

```bash
curl -sI https://www.thegoatnote.com/prism42-v3 | head -5
# Expected: 200 OK
```

### 6.4 Rollback (Phase 6)

```bash
# Single-command revert: flip backend env back to cloud and redeploy.
cd ~/prism42/mvp/911-console-live
vercel env rm LIVEKIT_BACKEND production --yes
# (Cloud env vars LIVEKIT_API_KEY, LIVEKIT_API_SECRET, NEXT_PUBLIC_LIVEKIT_URL
#  remain in production — backend defaults to "cloud" when LIVEKIT_BACKEND is unset.)
vercel --prod
# Production now back on LiveKit Cloud. Self-hosted infra (Phases 1-3) keeps
# running but unused. Tear down later with rollback.sh full mode.
```

### 6.5 Munger inversion (Phase 6)

**Most likely failure mode:** Vercel deploy succeeds but cached function bundles still hold the old env-var values for ~5 min while edge nodes propagate. A user hitting prod immediately after deploy may see Cloud URL in the response. **Mitigation:** wait 2-3 min, retry the curl probe. If it still shows Cloud URL after 5 min, run `vercel deploy --prod --force` to bust the build cache.

**Most-overlooked failure:** ElevenLabs path `/prism42-v3` shares the same Vercel project. Adding `LIVEKIT_BACKEND=selfhost` does NOT affect ElevenLabs (it doesn't read that var), but if the integrator accidentally adds the var with no `--environment` flag, it lands in *all* environments and may shadow other env vars during preview builds. Always specify `production` explicitly.

---

## Closing notes

- **Single binary-decision gate (per cycle-2Q §4a):** UDP ingress reachability. The fact that the bare-process livekit-server is already serving on `udp:7882` is *some* evidence ingress works; full proof requires an external `nc -u` probe to a port in 50000-60000 *while a room is active*. Phase 5.6 covers this implicitly via the live voice turn.

- **What's not in this runbook:**
  - Frontend dispatcher UI changes (Team F's territory — only env-flag plumbing here).
  - Agent worker code changes beyond `.env` (Team F + Team A).
  - LiveKit Cloud project teardown (post-demo, separate task).
  - Hetzner $5/mo VM fallback (post-hackathon, only if Brev UDP ingress later proves flaky at scale).

- **What the integrator confirms before run:**
  1. Team A has handed off livekit-server config + key/secret pair.
  2. `GODADDY_API_KEY` + `GODADDY_API_SECRET` are loaded in env (sourced from canonical `.env`).
  3. `VERCEL_TOKEN` is loaded in env.
  4. `PRISM42_AUTH_G2`, `PRISM42_AUTH_G3`, `PRISM42_AUTH_G4`, `PRISM42_AUTH_G6` set as auth events occur (the integrator does NOT set them all up-front).

- **Time budget (happy path):** Phase 0 = 12 min wait + 5 min commands; Phase 1 = 5 min; Phase 2 = 15 min (incl. ACME wait); Phase 3 = 10 min; Phase 4 = 30 min (code edit + deploy + verify); Phase 5 = 30 min (live voice tests); Phase 6 = 10 min. **Total ~2 hours commitment, ~1.5 hours active work.**

---

## Sources (all fetched 2026-04-26)

- LiveKit self-hosting: <https://docs.livekit.io/home/self-hosting/deployment/>, <https://docs.livekit.io/home/self-hosting/vm/>, <https://docs.livekit.io/home/self-hosting/distributed/>
- LiveKit config-sample: <https://github.com/livekit/livekit/blob/master/config-sample.yaml>
- Caddy install Debian/Ubuntu: <https://caddyserver.com/docs/install#debian-ubuntu-raspbian>
- Caddyfile reference: <https://caddyserver.com/docs/caddyfile>
- Caddy reverse_proxy directive: <https://caddyserver.com/docs/caddyfile/directives/reverse_proxy>
- GoDaddy Domains API v1: <https://developer.godaddy.com/doc/endpoint/domains#/v1/recordReplaceTypeName>
- UFW manpage: <https://manpages.ubuntu.com/manpages/jammy/en/man8/ufw.8.html>
- Vercel CLI env: <https://vercel.com/docs/cli/env>
- Cycle-2Q research (this cycle's input): [../../cycle2Q_livekit_selfhost/research.md](../../cycle2Q_livekit_selfhost/research.md)
- CLAUDE.md (operating charter + hackathon §0): [../../../../CLAUDE.md](../../../../CLAUDE.md)
