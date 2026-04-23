---
title: Prism — Third-Party Vendoring Policy
date: 2026-04-21
status: Policy
scope: Rules for cloning external source into third_party/, license acceptance, NOTICE attribution flow, current pin list.
---

### 1. Policy

- No third-party source is committed in-tree.
- Clones happen at `make setup-third-party` time (target to be added when the first dependency lands).
- Every clone is pinned to a specific commit SHA, recorded in this file.
- When a clone lands, the SAME commit updates NOTICE with an attribution block.

### 2. Accepted licenses (auto-approve)

Any SPDX identifier in this set may be vendored without author sign-off:

- Apache-2.0
- MIT
- BSD-2-Clause
- BSD-3-Clause
- MPL-2.0
- ISC

### 3. Restricted licenses (require author sign-off)

Any of the following requires explicit written approval from the repo owner before vendoring:

- GPL-2.0, GPL-3.0, AGPL-3.0 (copyleft scope concerns)
- SSPL-1.0 (commercial restriction)
- Commons Clause, BUSL, Elastic License 2.0 (source-available but not OSI-open)
- Unknown or missing license (vendor must provide provenance first)

### 4. Pin format

Each pinned dependency is one row in the table below:

| Name | Repo URL | Commit SHA | SPDX license | Purpose |
|---|---|---|---|---|
| simple-evals | https://github.com/openai/simple-evals | `ee3b0318d8d1d9d72755a4120879be65f7c07e9e` | MIT | HealthBench rubric grader: `RubricItem`, `calculate_score`, `GRADER_TEMPLATE` (via `scripts/_healthbench_grader_bridge.py`). Upstream marked deprecated July 2025 for new models but continues to host the HealthBench reference implementation. Pin date 2026-04-22. |

### 5. Attribution flow

When a clone is performed:

1. Uncomment / add the pin row in §4 with the pinned SHA.
2. Append an attribution block to root NOTICE with the project name, license, and link.
3. Both changes land in the same commit as the git-clone operation itself.

### 6. Excluded paths

- third_party/ is git-tracked at the directory level (README.md and LICENSE-copies only).
- The actual source trees are gitignored — never committed. `.gitignore` excludes `third_party/*` with an explicit `!third_party/README.md` override.
- A sibling Python-compatible symlink (`third_party/simple_evals` → `simple-evals`) is also excluded — created locally by `make setup-third-party` to make the hyphen-in-dirname package importable via `from simple_evals.healthbench_eval import …`.

### 7. Setup flow

After checkout:

```
make setup-third-party
```

This target:
1. Clones every pin in §4 into `third_party/<name>/` at the pinned SHA
   (`--depth 1 --branch <tag-or-sha>` when the SHA is on a tag, else
   full clone + checkout).
2. Creates any Python-compatible symlinks (e.g. `simple_evals` →
   `simple-evals`).
3. Verifies `git -C third_party/<name> rev-parse HEAD` matches the pin.
4. Copies each upstream `LICENSE` to `third_party/<name>/LICENSE` (no-op
   if already present from clone).

A follow-up commit adds the `setup-third-party` target when a second
dependency lands; for the single simple-evals pin we unblock via a
one-shot `git clone` documented in `scripts/_healthbench_grader_bridge.py`
module docstring.
