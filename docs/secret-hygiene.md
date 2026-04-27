# Secret hygiene — value-dump ban

**Effective 2026-04-27** after two P0 secret-exposure incidents in one
session. Treat as a process bug, not a one-off.

## The hard rule

**Never run a command that prints env values verbatim to stdout, a log,
or a chat transcript.**

Banned (always):

| Command | Why it leaks |
|---|---|
| `systemctl show ... --property=Environment` | dumps every `Environment=` line verbatim |
| `cat /proc/<pid>/environ` | null-separated values from a running process |
| bare `printenv` (no arg) | every env var with values |
| bare `env` on its own line | same |
| `cat .env` / `cat */.env` / `cat *.env` | full file with values |
| `grep -E '...KEY=|TOKEN=|SECRET=...' file` | matched lines include values |

Allowed:

```bash
# Verify a key is set without revealing its value:
awk -F= '/^(ANTHROPIC_API_KEY|OPENAI_API_KEY|LIVEKIT_API_KEY|HF_TOKEN|NVIDIA_API_KEY)=/ \
        {print $1, "len:", length($2)}' /path/to/.env

# Count secrets present without revealing identities:
grep -cE '^(ANTHROPIC|OPENAI|LIVEKIT|HF|NVIDIA)_' /path/to/.env

# Check the systemd unit's env-file path (path only, not values):
sudo systemctl show prism42-worker.service --property=EnvironmentFiles
```

## Allowlist for legitimate value extraction

Some scripts must extract values from `.env` to construct a runtime
env file or to pipe into a docker login. These are allowed *only* if
output is redirected to a chmod-600 file and never to stdout/log.
Mark such lines with a trailing magic comment:

```bash
grep -E '^(KEY|TOKEN)=' .env > /opt/x/.env.agent  # secret-dump-allowed: chmod-600 file
```

The linter (`scripts/check_no_secret_dumps.py`) honors that comment
on a per-line basis. Use sparingly. The reviewer's question on every
allowlist: *"would this leak in CI logs, in a kubectl describe, or in
a chat transcript?"* If yes, redesign the data flow.

## Enforcement

| Layer | Mechanism |
|---|---|
| Pre-commit | `make secret-hygiene` (calls `scripts/check_no_secret_dumps.py`) |
| CI | `.github/workflows/verify.yml` runs the linter on every push |
| Code review | Reviewers reject any new banned pattern; allowlist needs an explicit reason |
| Memory rules | `~/.claude/projects/.../memory/feedback_no_secret_value_dumps.md` (assistant-side, durable) |

## Recovery posture (if a leak happens)

1. **Rotate every key** that could have been in the dumped output.
   Treat the affected pod / process / image as compromised.
2. Update `.env` with new values; re-run `bash /tmp/push-pod-env.sh`
   and `bash /tmp/ngc-login.sh` (these scripts pipe values via
   stdin and never print).
3. Restart the relevant systemd unit so the new values propagate to
   the running process tree.
4. Append an entry to `findings/clinical-log.jsonl` with timestamp,
   event tag `secret_exposure_incident`, severity, the command that
   leaked, and the rotation steps taken.
5. If the leak originated from an assistant session, add a feedback
   memory at the assistant's memory store so future sessions don't
   repeat the pattern. Pattern: `~/.claude/projects/<dir>/memory/
   feedback_no_secret_value_dumps.md`.

## Why a process rule and not just a one-off

The first incident (2026-04-27 ~20:46 UTC) used
`cat /proc/<pid>/environ`. The second (~23:09 UTC) used
`systemctl show ... --property=Environment`. Two different commands,
same class of mistake, one session apart. The class is "any command
whose default output prints env values verbatim." Banning specific
commands is whack-a-mole; the durable rule is *output shape* —
prefer name+length over name+value.

## See also

- `findings/clinical-log.jsonl` — incident log (gitignored)
- `findings/ops/parallel-session-coord.md` §4 finding 5 — first key
  rotation event
- `~/.claude/projects/<dir>/memory/feedback_no_secret_value_dumps.md`
  — assistant-side memory (cross-session durable)
