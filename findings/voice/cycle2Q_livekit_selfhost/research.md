---
title: Self-host livekit-server on B300 — migration cost + architecture
date: 2026-04-26
scope: research-only, no code changes; decide whether to swap LiveKit Cloud for a self-hosted livekit-server on the existing Brev B300 pod
status: decision input for hackathon ship 2026-04-26
---

# Self-hosted livekit-server on B300 — migration cost + architecture

## TL;DR

**LiveKit Cloud today does signaling + SFU media relay + STUN/TURN for one room (US/EU caller ↔ Germany B300 agent). For prism42's single-room single-participant 911 demo, the only thing we are paying for is one SFU hop and the operational guarantee.** Self-hosting on B300 is technically a 1-binary install — the dragon is **inbound UDP on a Brev pod**: Brev's "expose port" path is a Cloudflare Tunnel ([Localtonet 2025](https://localtonet.com/blog/cloudflare-tunnel-alternative); Cloudflare Tunnel limitations confirmed by [Cloudflare Tunnel config](https://developers.cloudflare.com/tunnel/configuration/), 2026-04-26 fetch) which **does not support raw UDP**, and our 50000-60000/UDP media plane needs UDP. If Brev gives the pod a real public IPv4 with unrestricted UDP, this is a 3-4 hour parallel A/B. If it does not, we stay on Cloud or rent a cheap public-IP VM as a TURN/SFU front-end.

Recommendation: **Option B (parallel A/B) — only after a 15-minute verification that the Brev pod has a public IPv4 reachable on inbound UDP.** Pre-flight before sprint deadline. If verification fails, stay on LiveKit Cloud through the demo and re-visit post-hackathon.

---

## 1. What LiveKit Cloud actually does for us today

| Capability | Need for prism42 single-room 911 demo? | Source |
|---|---|---|
| WebRTC signaling (SDP/ICE over WSS :7880) | **Yes** — both browser SDK and agent worker register here. | [docs.livekit.io self-hosting (deploy)](https://docs.livekit.io/home/self-hosting/deployment/), 2026-04-26 |
| SFU media relay (UDP 50000-60000 / TCP 7881) | **Yes** — browser publishes mic, agent subscribes and publishes TTS back; SFU forwards. Even with one publisher + one subscriber, LiveKit always relays through the SFU (no P2P fallback). | [LiveKit SFU internals](https://docs.livekit.io/reference/internals/livekit-sfu/), 2026-04-26 |
| TURN over TCP/TLS for clients behind strict NAT (443) | **Yes** for any caller behind corporate/hospital NAT that blocks UDP (~1% of traffic but 100% of certain enterprise demos). | [docs.livekit.io self-hosting (vm)](https://docs.livekit.io/home/self-hosting/vm/), 2026-04-26 |
| Multi-region edge mesh (US-east, EU-central, AP-south) | **No** — for the demo we have one agent in Germany. Cloud's "connect to nearest edge" is a value-add only when the agent itself is regional. With our single-region agent, edge presence helps the *first hop* (caller → nearest edge) but the relay still has to cross to Frankfurt. | [LiveKit Cloud regions](https://livekit.com/products/agent-cloud-deployment); [community thread](https://community.livekit.io/t/choose-hosting-region-in-cloud/518), 2026-04-26 |
| Recording / Egress / Ingress | **No** — disabled in our config. |
| Distributed room state (Redis) | **No** — single node, single room. Self-host runs without Redis. [config-sample](https://github.com/livekit/livekit/blob/master/config-sample.yaml), 2026-04-26 |
| Worker scaling, auto-restart of agent | **No** — we run one Python worker on the pod via systemd; LiveKit Cloud does not manage that. |
| Operational uptime / SLA | **Maybe** — Cloud is more available than a single Brev pod, but the pod is already a SPOF for STT/LLM/TTS, so SFU adding a second SPOF is moot. |

**Bottom line:** Cloud's only load-bearing capabilities for us are (a) signaling/SFU relay, (b) TURN fallback. Multi-region routing is mostly cosmetic when the agent is single-region.

---

## 2. Latency tax of LiveKit Cloud

LiveKit does **not publish concrete cross-region SFU traversal numbers** (verified across two blog fetches: [scaling-webrtc-with-distributed-mesh](https://livekit.com/blog/scaling-webrtc-with-distributed-mesh/) and [understand-and-improve-agent-latency](https://livekit.com/blog/understand-and-improve-agent-latency); 2026-04-26). They cite a design goal of "a media server within 100ms of anyone in the world" but no measured SFU-hop number.

What we can model from public-internet RTT geography:

| Path | Approx RTT (one-way media leg) | Notes |
|---|---|---|
| US East caller → LiveKit Cloud US-East edge | 10-30 ms | Cloud anycast to nearest edge |
| LiveKit Cloud US-East edge → Frankfurt B300 agent | 80-100 ms | Transatlantic backbone (cloud uses backbone fiber per [scaling-mesh blog](https://livekit.com/blog/scaling-webrtc-with-distributed-mesh/)) |
| **US East → Cloud → Frankfurt total (current)** | **90-130 ms one-way, 180-260 ms RTT** | This is the relay path |
| US East → direct Frankfurt B300 (self-hosted) | 90-100 ms one-way, 180-200 ms RTT | No relay, but same transatlantic distance |
| **EU caller → LiveKit Cloud EU edge** | 5-20 ms | |
| LiveKit Cloud EU edge → Frankfurt B300 | 5-30 ms | Already in same region |
| **EU → Cloud → Frankfurt total** | **10-50 ms one-way, 20-100 ms RTT** | |
| EU → direct Frankfurt B300 (self-hosted) | 5-30 ms one-way, 10-60 ms RTT | Saves the SFU hop |

**Empirical estimate of Cloud's added tax for our specific topology:**
- US caller: **~5-15 ms added** (the relay is roughly on the path anyway; transatlantic is dominated by the ocean, not the cloud edge).
- EU caller: **~10-30 ms added** (the Frankfurt edge hop adds a measurable but small number).

For a 911 demo where the latency budget is ~1.5s end-to-end (CLAUDE.md §0), saving 10-30 ms is real but **not the binding constraint**. The binding constraint is LLM TTFT (~600 ms Opus 4.7) and TTS TTFB (~90 ms Cartesia). See [livekit-kb/04-deployment-patterns.md](../../../docs/livekit-kb/04-deployment-patterns.md) §4 latency budget reference.

**Verdict:** Latency-only argument for self-hosting is weak. Vertical-integration / "make B300 purr" / no-vendor-data-egress is the real argument.

---

## 3. Self-hosted livekit-server feasibility on B300

### Install (single binary, no Docker needed)

Per [github.com/livekit/livekit README](https://github.com/livekit/livekit), 2026-04-26 fetch:

```bash
# On Linux B300 pod:
curl -sSL https://get.livekit.io | bash    # installs livekit-server binary
livekit-server --version                    # verify (latest is v1.11.0 per GitHub releases)
```

(Mac path is `brew install livekit` — irrelevant for B300.)

### Required ports

Per [docs.livekit.io self-hosting/deployment](https://docs.livekit.io/home/self-hosting/deployment/) and [self-hosting/vm](https://docs.livekit.io/home/self-hosting/vm/), 2026-04-26:

| Port | Protocol | Purpose | Mandatory? |
|---|---|---|---|
| 7880 | TCP (WSS via Caddy) | Signaling (browser + agent worker connect here) | yes |
| 7881 | TCP | Media over TCP fallback | yes |
| 50000-60000 | **UDP** | Primary media (SFU relay) | **yes** |
| 3478 | UDP | TURN/UDP fallback | optional, recommended |
| 5349 | TCP (TLS) | TURN/TLS fallback for strict-NAT clients | optional, recommended |
| 80, 443 | TCP | Caddy ACME issuance + HTTPS terminate | yes (for TLS) |

### Minimum viable config

Per [config-sample.yaml](https://github.com/livekit/livekit/blob/master/config-sample.yaml), 2026-04-26 fetch — Redis is **not required** for single-node:

```yaml
port: 7880
keys:
  prism-key: <32-char-secret>
rtc:
  port_range_start: 50000
  port_range_end: 60000
  tcp_port: 7881
  use_external_ip: true       # auto-discover Brev pod public IP
turn:
  enabled: true
  domain: livekit.thegoatnote.com
  tls_port: 5349
  udp_port: 3478
room:
  empty_timeout: 300
  max_participants: 4
log_level: info
```

### TLS termination

Per [self-hosting/vm guide](https://docs.livekit.io/home/self-hosting/vm/), 2026-04-26: Caddy auto-TLS (Let's Encrypt) handles cert issuance for `livekit.thegoatnote.com`. **DNS prerequisite:** `livekit.thegoatnote.com` and a TURN subdomain (e.g. `turn-livekit.thegoatnote.com`) must both resolve to the Brev pod's public IPv4 before Caddy starts (otherwise ACME HTTP-01 challenge fails). Per CLAUDE.md the pivot doc references "Caddy auto-TLS at `livekit.thegoatnote.com`" — verify DNS via GoDaddy API before flipping.

### JWT signing — same as today

Browser fetches a short-lived JWT from `mvp/911-console-live/api/livekit-token` (Vercel route), signed with the LiveKit API secret. **Migration step:** swap the LiveKit Cloud key/secret pair for the self-hosted pair in Vercel env vars. The signing algorithm and library (`livekit-server-sdk`) are identical; only `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and `LIVEKIT_URL` change.

### Browser + worker env flips

```
# Before (Cloud)
NEXT_PUBLIC_LIVEKIT_URL = wss://ai-therapy-v3svfd9o.livekit.cloud
LIVEKIT_API_KEY/SECRET  = <cloud values>

# After (self-hosted)
NEXT_PUBLIC_LIVEKIT_URL = wss://livekit.thegoatnote.com
LIVEKIT_API_KEY/SECRET  = <self-hosted values from livekit.yaml>
```

Same flip on the agent worker's `.env` on the B300 pod. **Agent worker requires NO inbound port** — it WSS-out-registers with livekit-server (per [docs.livekit.io deploy/custom/deployments](https://docs.livekit.io/deploy/custom/deployments/), 2026-04-26: *"agent servers do not need to expose any inbound hosts or ports to the public internet"*).

### Time estimate (assuming Brev allows UDP — see §4)

| Step | Time |
|---|---|
| Verify Brev pod public IP + UDP ingress (§4) | 15 min |
| DNS A-record for `livekit.thegoatnote.com` via GoDaddy API | 5 min (already may exist per CLAUDE.md) |
| Install livekit-server + write `livekit.yaml` | 30 min |
| Caddy config + start, verify ACME issuance on :443 | 30 min |
| systemd unit (`livekit-server.service`) for autostart | 15 min |
| JWT signing endpoint env-flip + Vercel deploy | 30 min |
| Agent worker `.env` flip + restart | 15 min |
| First end-to-end voice turn test + latency measurement | 60 min |
| **Total (happy path)** | **~3.5 hours** |

If TURN issues surface (NAT'd corporate caller can't connect), add 1 hour for TURN debugging.

---

## 4. The dragon (Munger inversion)

### 4a. Brev pod public-IP / UDP ingress — the binding question

Brev's two documented port-exposure paths, per [docs.nvidia.com/brev](https://docs.nvidia.com/brev/), 2026-04-26:

1. **`brev port-forward`** — SSH-tunnel a remote port to localhost. **TCP only, single-user.** Useless for serving WebRTC media to public callers.
2. **Brev console "tunnels"** — Cloudflare Tunnel based; **routes through Cloudflare and requires browser auth on first access.** Cloudflare Tunnel **does not support UDP** ([Localtonet 2025 alt-tunnels article](https://localtonet.com/blog/cloudflare-tunnel-alternative); [Cloudflare Tunnel config docs](https://developers.cloudflare.com/tunnel/configuration/), 2026-04-26 fetch). Cloudflare offers UDP via separate paid Realtime TURN ([Cloudflare Realtime FAQ](https://developers.cloudflare.com/realtime/turn/faq/)) but that is not what `brev expose` invokes.

**Therefore:** `brev expose` cannot publish UDP 50000-60000 to the internet. The only path that works is the Brev pod having a **real public IPv4 with no firewall on inbound UDP** for those ports. Brev docs are silent on this. The user's existing pod is reachable on outbound (it talks to LiveKit Cloud, OpenAI, Anthropic). **Inbound UDP is the unknown.**

**Pre-flight check (15 min, no code change):**
```bash
# On Brev pod:
ip -4 addr show              # confirm public IPv4 assigned
ss -tunlp                    # nothing on 50000-60000 yet
# From another machine:
nc -u -v <pod-public-ip> 50000   # listen-side: nc -u -l 50000 on pod
# If the netcat round-trip works, UDP ingress works.
```

If this fails: self-hosting livekit-server on B300 alone is **not viable**. Options:
- Rent a $5/mo public-IPv4 VM (Hetzner Frankfurt) and run livekit-server there, agent worker on B300 connects out.
- Continue on LiveKit Cloud.

### 4b. TURN fallback for strict-NAT clients

If `livekit.yaml` enables TURN, livekit-server can serve its own TURN via :3478/UDP and :5349/TCP-TLS. No separate `coturn` daemon needed — livekit-server bundles it ([docs.livekit.io/home/self-hosting/deployment](https://docs.livekit.io/home/self-hosting/deployment/), 2026-04-26). For corporate-NAT callers, TURN-over-TCP-443 is the universal fallback.

### 4c. TLS cert renewal

Caddy auto-renews. If Caddy crashes, signaling drops within seconds (browser SDK can't reach :7880 over WSS). Mitigation: systemd `Restart=on-failure` for both `livekit-server.service` and `caddy.service`; b3-latency watchdog that pings `/healthz` every 30s.

### 4d. Bandwidth / egress

Opus voice is ~32-64 kbps; one full 60-min call is ~14-29 MB each direction. Hackathon-scale demo egress is rounding error. At-scale (post-hackathon, 100 concurrent calls), egress is ~6.4 Mbps sustained — still small. **Brev egress pricing is not publicly documented**; verify before scaling.

### 4e. Geographic distribution

LiveKit Cloud routes US callers via US edge → backbone → Frankfurt agent. Self-hosted: US callers cross the Atlantic on the public internet. Public-internet transatlantic RTT is ~80-100 ms; Cloud's backbone is similar (~80-100 ms with possible jitter improvements). For a hackathon demo with majority-US testers, expect **5-15 ms degradation** on US callers vs Cloud. EU callers **improve** by similar amount.

### 4f. Operational — one more daemon

`livekit-server` + `caddy` + the existing STT/LLM/TTS services + agent worker. Watchdog scope grows. Mitigation: write a single `b3-livekit.target` systemd target that wants all four units; one health check covers them.

### 4g. The hidden dragon: per-room SFU CPU cost on a GPU pod

B300 has 144 cores total, but the GPU is the precious resource. livekit-server is Go, single-binary, ~50-200 MB RAM, single-digit CPU% per room at our scale. **Negligible.** It will not contend with vLLM or Fish.

---

## 5. Recommended path

| Option | Cost | Risk | Verdict |
|---|---|---|---|
| **A. Keep LiveKit Cloud** | $0 setup, Cloud free-tier credits | vendor lock, ~10-30 ms latency tax for EU callers, demo is "not vertically integrated" | Safe, ship-by-EOD compatible |
| **B. Parallel A/B (Cloud + self-hosted, env-flag flip)** | 3.5-4.5 hr (after UDP pre-flight) | split-brain on JWT keys, two systemd units to monitor; demo can fall back to Cloud in 30 sec via env flip | **Recommended** if UDP pre-flight passes |
| C. Full cutover | 4-6 hr | if it fails on demo day, no fallback unless we re-flip env (which is fast, so this risk is small) | Defer to post-hackathon |

**Recommended: Option B**, conditional on the 15-min UDP pre-flight (§4a) succeeding. If it fails, stay on Option A through 2026-04-26 demo, and revisit post-hackathon either by getting Brev support to confirm UDP ingress, or by adding a $5/mo Hetzner Frankfurt VM as the livekit-server host (B300 stays as agent-worker-only).

---

## 6. Concrete runbook — Option B (parallel A/B)

**Prereqs (do not skip):**
1. `livekit.thegoatnote.com` A-record points to Brev pod public IP. Verify: `dig +short livekit.thegoatnote.com`.
2. `turn-livekit.thegoatnote.com` A-record same. Verify: `dig +short turn-livekit.thegoatnote.com`.
3. **UDP ingress pre-flight (§4a) passes.** If fail, abort, stay on Option A.

**Steps:**

| # | Step | Verify with |
|---|---|---|
| 1 | SSH to pod: `ssh prism-mla-b300-h4h5` | `hostname` |
| 2 | Install: `curl -sSL https://get.livekit.io \| bash` | `livekit-server --version` shows v1.11.x |
| 3 | Write `/opt/livekit/livekit.yaml` (config from §3 above; generate fresh API key/secret with `openssl rand -hex 32` for both) | `livekit-server --config /opt/livekit/livekit.yaml --bind 127.0.0.1 --dev` runs cleanly |
| 4 | Install Caddy 2.x via `apt install caddy` (or download binary) | `caddy version` |
| 5 | Write `/etc/caddy/Caddyfile`: reverse-proxy `livekit.thegoatnote.com` → `127.0.0.1:7880`, plus `tls` block for `turn-livekit.thegoatnote.com` | `caddy validate --config /etc/caddy/Caddyfile` |
| 6 | Open firewall: pod-side `ufw allow 7880,7881,80,443/tcp; ufw allow 50000:60000/udp; ufw allow 3478/udp; ufw allow 5349/tcp` (or equivalent on Brev's iptables) | `ufw status numbered` |
| 7 | Create systemd units `livekit-server.service` and `caddy.service` with `Restart=on-failure` | `systemctl status livekit-server caddy` both `active (running)` |
| 8 | Test from a laptop: open `https://livekit.thegoatnote.com` in browser; should return livekit health page (or 404 with a livekit-server header) | `curl -sI https://livekit.thegoatnote.com` returns 200/404 with `Server: livekit` header |
| 9 | Add new env keys to Vercel project (`mvp/911-console-live`): `NEXT_PUBLIC_LIVEKIT_URL_SELFHOST`, `LIVEKIT_API_KEY_SELFHOST`, `LIVEKIT_API_SECRET_SELFHOST`. Add a feature flag (e.g. `LIVEKIT_BACKEND=cloud\|selfhost`) to the Next.js page + JWT-signing API route. | `vercel env ls` |
| 10 | Add same keys to agent worker `.env` on pod, with same `LIVEKIT_BACKEND` flag in `worker.py`. Default = `cloud`. | grep the env in `systemctl show prism42-worker` |
| 11 | Deploy Vercel preview, set `LIVEKIT_BACKEND=selfhost` on preview only. Production stays `cloud`. | preview URL renders |
| 12 | One end-to-end voice turn on preview URL. Listen for the greeting, say one sentence, hear the reply. Capture `b3-latency` numbers. | `b3-latency` browser console shows full round-trip; `journalctl -u prism42-worker --since=5min` has the turn |
| 13 | If turn 12 succeeds with no audible regression: leave preview on selfhost, prod on cloud. Demo from prod URL (cloud) — selfhost is now hot-spare. | Both URLs work voice-end-to-end |
| 14 | (Post-hackathon) Promote selfhost to prod by env-flipping `LIVEKIT_BACKEND=selfhost` on production env in Vercel + redeploying. | One end-to-end voice turn on `www.thegoatnote.com/prism42/livekit` |

**Rollback:** `vercel env add LIVEKIT_BACKEND=cloud --prod` and redeploy. ~30 sec to revert.

---

## 7. Recommendation (5 bullets)

- **Keep LiveKit Cloud through 2026-04-26 demo.** The latency tax (5-30 ms for our topology) is not the binding constraint; the binding constraint is LLM TTFT and TTS TTFB. Vertical-integration framing is real but not load-bearing for ship-by EOD.
- **Run the UDP ingress pre-flight (§4a) today (15 min).** That's the single binary-decision gate. If it fails, self-hosting on B300 alone is dead and the post-hackathon path is a $5/mo Hetzner Frankfurt VM — not B300.
- **If pre-flight passes, execute Option B parallel A/B in a 4-hour block on 2026-04-27 (post-demo).** Ship the demo on Cloud, then bring up self-host as a hot-spare under a feature flag. No demo-day risk.
- **Self-hosted livekit-server is one Go binary + Caddy + systemd.** No Redis, no Docker, no coturn. ~50-200 MB RAM, negligible CPU/GPU contention with vLLM/Fish on B300. The complexity is in the **network plane**, not the daemon.
- **Promote self-host to prod only when (a) US-caller measurement shows ≤Cloud baseline ± 10 ms and (b) one corporate-NAT caller has connected via TURN/443 successfully.** Otherwise keep the env flag and dual-run.

## Don'ts

- **Don't try to use `brev expose` / Cloudflare Tunnel for LiveKit media.** Cloudflare Tunnel is TCP-only; LiveKit media is UDP. ([Localtonet 2025](https://localtonet.com/blog/cloudflare-tunnel-alternative); [Cloudflare Tunnel docs](https://developers.cloudflare.com/tunnel/configuration/)).
- **Don't switch the production demo URL on demo day.** Parallel A/B with feature flag, default = Cloud, only flip after a measured win.
- **Don't run `livekit-server --dev`** in any non-dev path — it ships with hardcoded `devkey:secret` credentials. Generate fresh keys via `openssl rand -hex 32`.
- **Don't enable Redis / distributed mode** unless you actually run multiple livekit-server nodes. Single-node mode runs without Redis ([config-sample](https://github.com/livekit/livekit/blob/master/config-sample.yaml)).
- **Don't conflate "self-host livekit-server" with "self-host the agent worker."** The agent worker is already self-hosted (running on B300); LiveKit Cloud only signals + relays media. Self-hosting the *server* is the migration; the *worker* doesn't move.

---

## Sources (all fetched 2026-04-26 unless noted)

- [github.com/livekit/livekit (README, install, releases)](https://github.com/livekit/livekit)
- [github.com/livekit/livekit/blob/master/config-sample.yaml](https://github.com/livekit/livekit/blob/master/config-sample.yaml)
- [docs.livekit.io/home/self-hosting/deployment/](https://docs.livekit.io/home/self-hosting/deployment/)
- [docs.livekit.io/home/self-hosting/distributed/](https://docs.livekit.io/home/self-hosting/distributed/)
- [docs.livekit.io/home/self-hosting/vm/](https://docs.livekit.io/home/self-hosting/vm/)
- [docs.livekit.io/home/self-hosting/local/](https://docs.livekit.io/home/self-hosting/local/)
- [docs.livekit.io/deploy/custom/deployments/](https://docs.livekit.io/deploy/custom/deployments/)
- [docs.livekit.io/reference/internals/livekit-sfu/](https://docs.livekit.io/reference/internals/livekit-sfu/)
- [livekit.com/blog/scaling-webrtc-with-distributed-mesh/](https://livekit.com/blog/scaling-webrtc-with-distributed-mesh/)
- [livekit.com/blog/understand-and-improve-agent-latency](https://livekit.com/blog/understand-and-improve-agent-latency)
- [livekit.com/products/agent-cloud-deployment](https://livekit.com/products/agent-cloud-deployment)
- [community.livekit.io/t/choose-hosting-region-in-cloud/518](https://community.livekit.io/t/choose-hosting-region-in-cloud/518)
- [docs.nvidia.com/brev/](https://docs.nvidia.com/brev/) (Brev networking, port-forward / tunnel)
- [localtonet.com/blog/cloudflare-tunnel-alternative](https://localtonet.com/blog/cloudflare-tunnel-alternative) (Cloudflare Tunnel UDP limitation)
- [developers.cloudflare.com/tunnel/configuration/](https://developers.cloudflare.com/tunnel/configuration/) (Cloudflare Tunnel docs)
- [developers.cloudflare.com/realtime/turn/faq/](https://developers.cloudflare.com/realtime/turn/faq/) (Cloudflare Realtime TURN — separate paid service)
- Internal: [/Users/kiteboard/prism42/docs/livekit-kb/04-deployment-patterns.md](../../../docs/livekit-kb/04-deployment-patterns.md), [/Users/kiteboard/prism42/docs/livekit-kb/15-cloud-swap-alternatives.md](../../../docs/livekit-kb/15-cloud-swap-alternatives.md), [/Users/kiteboard/prism42/CLAUDE.md](../../../CLAUDE.md) §0
