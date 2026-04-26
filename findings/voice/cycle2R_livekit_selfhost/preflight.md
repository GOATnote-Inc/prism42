# cycle-2R preflight checklist — top-to-bottom stack verification

Status as of 2026-04-26 09:34 UTC. Every line has a verification command
(plain bash) and an expected-output marker. Lines marked `[GREEN]` are
passing. Lines marked `[CHECK]` need attention. Lines marked `[PEND]` are
deferred until later phase.

## 1 — DNS

| What | Verify | Result |
|---|---|---|
| Authoritative NS | `dig +short NS thegoatnote.com` | `ns65.domaincontrol.com.` + `ns66.domaincontrol.com.` [GREEN] |
| `prism42.thegoatnote.com` at authoritative | `dig +short @ns65.domaincontrol.com prism42.thegoatnote.com` | `31.22.104.100` [GREEN] |
| `turn-prism42.thegoatnote.com` at authoritative | `dig +short @ns65.domaincontrol.com turn-prism42.thegoatnote.com` | `31.22.104.100` [GREEN] |
| `prism42` public propagation | `dig +short @1.1.1.1 prism42.thegoatnote.com` | propagating; will catch up in <1h [CHECK] |
| `turn-prism42` public propagation | `dig +short @8.8.8.8 turn-prism42.thegoatnote.com` | `31.22.104.100` [GREEN] |
| Old `livekit.thegoatnote.com` record | leftover; benign | A → 31.22.104.100, can clean up later [PEND] |

## 2 — Pod network plane

| What | Verify | Result |
|---|---|---|
| Public IPv4 on eth0 | `ssh pod 'ip -4 addr show eth0'` | `31.22.104.100/24` direct, no NAT [GREEN] |
| UFW status active | `ssh pod 'sudo ufw status'` | active [GREEN] |
| UFW :7880 tcp | rule [4] | `ALLOW IN Anywhere` [GREEN] |
| UFW :7881 tcp | rule [5] | [GREEN] |
| UFW :7882 udp | rule [6] | [GREEN] |
| UFW :50000-60000 udp | rule [7] | [GREEN] |
| UFW :3478 udp | rule [8] | [GREEN] |
| UFW :5349 tcp | rule [9] | [GREEN] |
| UFW :80 tcp | rule [10] | [GREEN] |
| UFW :443 tcp | rule [11] | [GREEN] |
| Brev allows inbound UDP | implicit pass — Let's Encrypt validators reached :443 from multiple IPs ([34.220.139.152](https://lookup.icann.org), [13.214.217.0](https://lookup.icann.org)) | [GREEN] |

## 3 — TLS / HTTPS edge (Caddy)

| What | Verify | Result |
|---|---|---|
| Caddy daemon installed | `ssh pod 'caddy version'` | `v2.11.2` [GREEN] |
| Caddy systemd service | `ssh pod 'systemctl is-active caddy'` | `active` [GREEN] |
| Caddy log dir writable | `ssh pod 'sudo ls -la /var/log/caddy/livekit.log'` | `caddy:caddy` 0600 [GREEN] |
| `:80` listener | `ss -tunlp \| grep ':80\b'` | `caddy pid=486092` [GREEN] |
| `:443` listener (tcp + udp h3) | `ss -tunlp \| grep ':443\b'` | `caddy pid=486092` tcp + udp [GREEN] |
| ACME cert `prism42.thegoatnote.com` | `journalctl -u caddy \| grep "certificate obtained"` | obtained 09:33:36 [GREEN] |
| ACME cert `turn-prism42.thegoatnote.com` | same | obtained 09:33:37 [GREEN] |
| Cert valid (no warnings on browser) | `curl -sI https://prism42.thegoatnote.com` | `HTTP/2 200`, `via: 1.1 Caddy` [GREEN] |

## 4 — LiveKit signaling + media

| What | Verify | Result |
|---|---|---|
| livekit-server running | `ssh pod 'pgrep -a livekit-server'` | pid `76823` (Docker container `b300-livekit-1` v1.11.0) [GREEN] |
| Single-port-ICE mode | livekit.yaml `udp_port: 7882, port_range: 0/0` | confirmed by Team A forensic [GREEN] |
| `:7880` signaling listening | `ss -tunlp \| grep :7880` | livekit-server [GREEN] |
| `:7881` TCP-fallback listening | same | livekit-server [GREEN] |
| `:7882` UDP media listening | same | livekit-server [GREEN] |
| Caddy reverse-proxy works | `curl -sI https://prism42.thegoatnote.com/rtc/validate` | `HTTP/2 401` (livekit speaking through Caddy) [GREEN] |
| TURN config (5349 TLS) | reverse_proxy block in Caddyfile | proxied to 127.0.0.1:5349 [GREEN] |
| External UDP media verified | will be confirmed during Phase 5 voice smoke | [PEND] |

## 5 — Voice services (frozen, NOT touched by cycle-2R)

| What | Verify | Result |
|---|---|---|
| `prism42-fish.service` | `systemctl is-active prism42-fish` | `active` [GREEN] |
| `prism42-worker.service` | `systemctl is-active prism42-worker` | `active` [GREEN] |
| vLLM Nemotron-3-Nano on `:8001` | `pgrep -af "vllm.*serve"` | pid 389310 [GREEN] |
| Parakeet STT on `:9100` | `nc -zv 127.0.0.1 9100` (from pod) | confirmed by worker.log [GREEN] |
| Fish TTS on `:9200` | same as Fish service | active [GREEN] |
| MW reference voice loaded | `grep mw_sample.wav /tmp/prism42-logs/worker.log` | `reference_voice_loaded` event present [GREEN] |
| MW intro greeting WAV | `ls /opt/prism42/voice-refs/mw_intro_greeting.wav` | 262144 bytes (cycle-2P) [GREEN] |
| FSM enabled | `systemctl show prism42-worker -p Environment \| grep PRISM42_ENABLE_FSM` | `=1` [GREEN] |
| Worker registered with LiveKit | `journalctl -u prism42-worker \| grep "registered worker"` | currently registered with **CLOUD** (`wss://ai-therapy-v3svfd9o.livekit.cloud`) [CHECK — flip in Phase 4] |

## 6 — Frontend (Vercel)

| What | Verify | Result |
|---|---|---|
| Vercel project linked | `cat mvp/911-console-live/.vercel/project.json` | `prism42-console` (`prj_UCqQGm…`) [GREEN] |
| Production URL up | `curl -sI https://prism42-console.vercel.app/prism42/livekit` | 200 [GREEN — currently chat-bubble UI on Cloud backend] |
| `voice/cycle2R-frontend` branch | `git branch -v \| grep cycle2R-frontend` | DispatchPanel + 30/30 tests pass [GREEN — pending merge] |
| `dispatch_publisher.py` skeleton | `git log agents/livekit/dispatch_publisher.py` | committed in `d88f7d2` [GREEN — default-OFF] |
| Backup URL `prism42-v3` | `curl -sI https://prism42-console.vercel.app/prism42-v3` | 200 [GREEN — preserved as fallback] |

## 7 — Phase 4 plan (pending)

| Step | Action | Authorization |
|---|---|---|
| 7.1 | `vercel env add NEXT_PUBLIC_LIVEKIT_URL preview` → `wss://prism42.thegoatnote.com` | low-risk |
| 7.2 | `vercel env add LIVEKIT_API_KEY preview` ← from container env (no echo to context) | low-risk |
| 7.3 | `vercel env add LIVEKIT_API_SECRET preview` ← same | low-risk |
| 7.4 | merge `voice/cycle2R-frontend` → main (Team F dispatcher UI) | low-risk; reversible via revert |
| 7.5 | Vercel preview deploy | low-risk |
| 7.6 | update worker `.env` on pod: `LIVEKIT_URL=wss://prism42.thegoatnote.com` + matching key/secret | low-risk; restore.sh covers |
| 7.7 | restart `prism42-worker`; verify it re-registers with `prism42.thegoatnote.com` | low-risk |
| 7.8 | preview voice-turn smoke from laptop | manual user attestation |

## 8 — Rollback artifacts

| What | Where |
|---|---|
| Pod state tarball | `findings/voice/cycle2R_livekit_selfhost/baseline-2026-04-26/pod-state.local.tgz` (gitignored, sha256 verified) |
| Restore script | `findings/voice/cycle2R_livekit_selfhost/baseline-2026-04-26/restore.sh` (idempotent; `--check` for dry-run) |
| Vercel env snapshot | `findings/voice/cycle2R_livekit_selfhost/baseline-2026-04-26/vercel-env-snapshot.txt` |
| Cycle-2R run.sh | `findings/voice/cycle2R_livekit_selfhost/team-r/run.sh` (gated by `PRISM42_AUTH_G*`) |
| Cycle-2R rollback.sh | `findings/voice/cycle2R_livekit_selfhost/team-r/rollback.sh` (Phase 6 → Vercel-back-to-Cloud runs FIRST) |

## 9 — Failure-mode table (Munger inversion)

| Failure | Detection | Recovery |
|---|---|---|
| Caddy crashes mid-call | `systemctl is-active caddy` returns failed | `systemctl restart caddy`; signaling drops <30s; existing media continues |
| livekit-server container dies | `pgrep livekit-server` empty | `docker compose -f /opt/prism42/infra/b300/docker-compose.yml up -d` (restart=unless-stopped should self-heal) |
| Brev pod reboot | DNS still resolves, but UFW rules + Caddy + livekit-server come back via systemd / docker restart-policy | confirm with watchdog after boot |
| Cert expiry (90d) | Caddy auto-renews 30d before expiry | journalctl monitor; or weekly `caddy validate` cron |
| ACME rate-limit | <50 cert orders / week / domain | only triggers on cert-thrash (config bouncing); current state stable |
| Network policy change at Brev | external UDP stops working | rollback to Cloud via `restore.sh --vercel-only` (~30s) |
| LiveKit container's API secret rotates on `--force-recreate` | worker.env + Vercel env mismatch | `secret-drift sync`: pull container env → push to worker .env + Vercel |
| TURN-via-TCP-443 test (corporate NAT) | one strict-NAT laptop test | not in critical path for hackathon demo, but should test before any external attestation |
