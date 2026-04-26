# Cycle-2R Team A — LiveKit self-host forensic + takeover plan

**Pod:** `prism-mla-b300-h4h5` (`31.22.104.100`, no NAT)
**Author:** Team A (cycle-2R, 2026-04-26)
**Source of truth for keys:** `keys.local.txt` in this same directory (gitignored).

## TL;DR

The "bare process" pid 76823 is **not bare** — it is `livekit-server v1.11.0` running
inside the docker container `b300-livekit-1` (project `b300`, declared by
`/opt/prism42/infra/b300/docker-compose.yml`). The container uses
`network_mode: host` and `restart: unless-stopped`, which is exactly why
listeners look like a host process and why a host-level kill is dangerous —
docker restarts it. **Recommended takeover: Option B (keep + tighten).** The
container already has the right behavior; what's missing is UFW rules + Caddy
running. A clean recreate would also rotate the API secret because the host
`.env` was edited after the container started (see §3 / §8).

---

## 1. Process basics

```
$ readlink /proc/76823/exe       # (returns nothing; container PID namespace)
$ readlink /proc/76823/cwd       # (returns nothing; container mount namespace)
$ /proc/76823/status
Name:    livekit-server
State:   S (sleeping)
PPid:    76795
Uid:     0  0  0  0
Gid:     0  0  0  0
$ ps -o pid,ppid,user,etime,start_time,cmd
  76823   76795 root  2-01:17:23 Apr24 /livekit-server --config /livekit.yaml
$ ps -p 76795 -o cmd
  /usr/bin/containerd-shim-runc-v2 -namespace moby -id 682c921a866e... -address /run/containerd/containerd.sock
```

- Started **2026-04-24** (~48 h uptime).
- Parent is `containerd-shim`, NOT `init`/`systemd`. It's a Docker container.
- `docker ps` confirms: `682c921a866e   livekit/livekit-server:latest   b300-livekit-1   Up 2 days`.
- Container labels show actual image is `v1.11.0` (compose declares `v1.9.0` — the tag was bumped to `:latest` and re-pulled in place).
- Restart policy: `unless-stopped`. NETWORK_MODE: `host`. (Confirmed by `docker inspect`.)

### Filtered environment (variable names + sha256-truncated-8 of values; values redacted)

The full key/secret pair is captured in `keys.local.txt` (gitignored, mode 600). Hashes:

| Variable             | Source                  | len | sha8       |
|----------------------|-------------------------|-----|------------|
| `LIVEKIT_API_KEY`    | running container env   | 22  | `7b1a7de9` |
| `LIVEKIT_API_SECRET` | running container env   | 64  | `44a48c2a` |
| `LIVEKIT_KEYS`       | running container env   | 88  | `ed04bc3a` |
| `LIVEKIT_API_KEY`    | host `/opt/prism42/agents/livekit/.env` | 15 | `61a88ab4` |
| `LIVEKIT_API_SECRET` | host `/opt/prism42/agents/livekit/.env` | 43 | `87ceca7c` |

**The host `.env` and the running container env do NOT match.** A
`docker compose up -d --force-recreate` will rotate the secret and break any
agent worker / Vercel route still using the running-container secret.

## 2. Config file

- Bind mount declared in compose: `./livekit.yaml:/livekit.yaml:ro`.
- Resolved host path: **`/opt/prism42/infra/b300/livekit.yaml`** (60 lines, sha256(file)[0:16]=`5db4c0d13331beab`).
- Backup also present: `livekit.yaml.bak.1777016387` (Apr 24 07:39 — same day).

### YAML structure (secret values stripped)

```yaml
port: 7880
bind_addresses: ["0.0.0.0"]
log_level: info
rtc:
  udp_port: 7882
  tcp_port: 7881
  port_range_start: 0
  port_range_end: 0          # single-port-ICE mode
  use_external_ip: true
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}    # env-substituted at start
redis:
  address: 127.0.0.1:6379
turn:
  enabled: true
  domain: livekit.thegoatnote.com
  tls_port: 5349
  udp_port: 443              # shares with HTTPS
  external_tls: true         # Caddy terminates TURN/TLS
room:
  max_participants: 4
  empty_timeout: 60
  max_publishers: 2
webhook:
  api_key: ${LIVEKIT_API_KEY}
  urls: ["https://prism42-console.vercel.app/prism42/api/livekit-webhook"]
```

No `keyfile:` directive — keys are inline templated, substituted from compose
env vars (see compose `environment:` block: `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`).

## 3. Secrets discovery

- Container compose `--env-file`: `/opt/prism42/agents/livekit/.env` (see
  `com.docker.compose.project.environment_file` label and the compose
  doc-string itself).
- `/opt/prism42/.env` does **not** exist. The compose readme says to use
  `--env-file /opt/prism42/.env` but the actual launch used the agent's
  `.env`. This is a config drift to flag for cycle-2R.
- Both pairs (running-container + on-disk) are saved to `keys.local.txt` in
  this directory. File mode 600. Path is matched by the new gitignore rule
  `findings/**/keys.local.txt` (verified with `git check-ignore`).
- `/opt/prism42/agents/livekit/.env` also holds vendor secrets:
  `ANTHROPIC_API_KEY (108 sha8=5b34eb3e)`, `OPENAI_API_KEY (164 sha8=308da6bb)`,
  `ELEVENLABS_API_KEY (51 sha8=c05a1ccd)`, etc. **Not** captured in
  `keys.local.txt` — Team A scope is LiveKit only.

## 4. Port-range config

```
rtc:
  udp_port: 7882
  tcp_port: 7881
  port_range_start: 0
  port_range_end: 0
```

**Single-port-ICE mode.** `port_range_start=0, port_range_end=0` is the
LiveKit-documented sentinel for "do not use port-range; route all RTP/RTCP
through `udp_port` only." Verified by:

- LiveKit boot log: `"rtc.portUDP": {"Start":7882,"End":0}`.
- `ss -ulnp | grep 7882` shows `*:7882` listener and `31.22.104.100:7882`
  binding from `use_external_ip: true`.
- No other UDP listeners owned by livekit-server.

This is the simpler firewall posture (one UDP port). For a single-pod demo
with <20 concurrent calls, single-port-ICE is correct. If concurrency goes
up, switch to `port_range_start=50000, port_range_end=60000` and open that
range in UFW.

## 5. Provenance

```
$ which livekit-server          # empty on host
$ dpkg -S /livekit-server       # n/a — inside container
$ docker exec b300-livekit-1 /livekit-server --version
livekit-server version 1.11.0
```

Not `apt`. Not `brew`. Not curl-bash. The image is the upstream
`livekit/livekit-server:latest` Docker tag, currently resolving to v1.11.0
(label `org.opencontainers.image.version=v1.11.0`, revision
`8ccad68d765d9a6276c76604f001faae516ced47`). Compose pin
`livekit/livekit-server:v1.9.0` is stale — the tag was retagged in place to
`:latest` and re-pulled. Recommend pinning to `:v1.11.0` explicitly to make
behavior reproducible.

## 6. TURN state

YAML says:
```yaml
turn:
  enabled: true
  domain: livekit.thegoatnote.com
  tls_port: 5349
  udp_port: 443
  external_tls: true
```

Reality:
- `ss -tlnp | grep 5349` → no listener.
- `ss -ulnp | grep 443` → no listener.
- TURN cert files: none under `/opt/prism42/infra/b300/`, none under
  `/etc/letsencrypt/live/`, none under `/opt/prism42/certs/`.
- Caddy is the planned TLS terminator (`external_tls: true`). Caddy is
  declared in `Caddyfile` but **not** running on the pod (`systemctl status
  caddy → Unit caddy.service could not be found`).

**TURN is config-enabled but operationally OFF.** Until Caddy stands up and
UFW opens 443/udp + 5349/tcp, TURN does nothing for callers behind
strict NAT. WebRTC will fall back to STUN-only / direct UDP/7882.

## 7. Firewall + reachability

```
$ sudo ufw status
Status: active
[1] 22/tcp     ALLOW IN  Anywhere
[2] 2222/tcp   ALLOW IN  Anywhere
[3] 22         ALLOW IN  Anywhere
[4] 22/tcp v6  ALLOW IN  Anywhere (v6)
[5] 2222/tcp v6 ALLOW IN  Anywhere (v6)
```

**Only SSH is open.** WSS (443/tcp), WS direct (7880/tcp), TCP-fallback
(7881/tcp), media UDP (7882/udp), TURN/TLS (5349/tcp), TURN/UDP (443/udp) —
all blocked at the host firewall. This is why production routes nothing to
the pod, and why your discovery showed listeners but no traffic.

## 8. Takeover recommendation: **Option B — keep + tighten**

The pid 76823 livekit-server is already correctly configured (single-port
ICE, host network, Redis-backed scale, valid keys block). The blockers are
external to the process: UFW + Caddy + DNS.

**Why not A (kill + systemd):** wraps the existing container in another
restart manager that fights with `restart: unless-stopped`. Doesn't add
value over `docker compose up -d` and adds a new failure mode (systemd
unit drift vs compose).

**Why not C (replace):** would rotate the LIVEKIT_API_SECRET (running-vs-
disk hashes already differ — see §1) and force a coordinated rotation of
the agent worker `.env` and the Vercel route's env. Right now the running
container is the source of truth for the secret; the on-disk `.env` is
stale. A C-style replace must come AFTER the agent worker is confirmed to
read from the same `.env` we will rebuild from.

**Option B steps** (executed by the integrator, gated by user authorization):

1. Reconcile secrets: copy the running-container `LIVEKIT_API_KEY` /
   `LIVEKIT_API_SECRET` (from `keys.local.txt`) into
   `/opt/prism42/agents/livekit/.env` so a future `docker compose up -d
   --force-recreate` is safe.
2. Pin the image tag in `docker-compose.yml`:
   `image: livekit/livekit-server:v1.11.0` (was `:v1.9.0`, currently
   `:latest`-shadowed).
3. Open UFW: `sudo ufw allow 7880/tcp; sudo ufw allow 7881/tcp;
   sudo ufw allow 7882/udp; sudo ufw allow 80/tcp; sudo ufw allow 443/tcp;
   sudo ufw allow 5349/tcp; sudo ufw allow 443/udp` — gated by user.
4. Stand up Caddy as a systemd unit (NEW unit; the bare-process livekit-
   server stays untouched). Caddy provisions LE certs and proxies WSS to
   `127.0.0.1:7880`.
5. Verify end-to-end with the standard livekit smoke
   (`livekit-cli room list --url wss://livekit.thegoatnote.com --api-key
   ... --api-secret ...`).
6. **OPTIONAL** post-stabilization: write a defensive systemd unit that
   monitors the container ID via `docker events --filter
   container=b300-livekit-1` and pages the operator on `die`/`oom`. Not
   required — `restart: unless-stopped` already auto-restarts in-place.

Tune the kernel UDP buffer that LiveKit warned about (`UDP receive buffer
is too small for a production set-up: current=425984, suggested=5000000`)
via `sudo sysctl -w net.core.rmem_max=5000000` + persist in
`/etc/sysctl.d/99-livekit.conf`.

## 9. Open questions for the integrator

- The compose env-file pointer is `/opt/prism42/agents/livekit/.env`, but
  the compose comment says `--env-file /opt/prism42/.env`. If a script
  brings the stack up assuming `/opt/prism42/.env`, vars will silently be
  empty. Decide which is canonical and align both.
- The `webhook.api_key: ${LIVEKIT_API_KEY}` is fine; the `urls:` target
  Vercel (`prism42-console.vercel.app`). Confirm the new self-hosted
  posture still wants Vercel as webhook sink, or move to a B300-local
  endpoint.
- LIVEKIT_KEYS is a third env var in the running container with len=88
  (key + ": " + secret). Possible legacy form for older clients. Worth
  verifying nothing on the path requires it before moving on.
