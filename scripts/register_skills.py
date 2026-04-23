#!/usr/bin/env python3
"""Upload the 5 Prism role-skills and bind them to the coordinator.

This is the "real flex" path: each dialectic role (defender / attacker
/ synthesizer / executor / adjudicator) is packaged as an Anthropic
Agent Skill with its own SKILL.md frontmatter, uploaded via the public-
beta `/v1/skills` endpoint (no research preview), and bound to the
already-registered `prism-coordinator` agent via `beta.agents.update`.

Opus 4.7 then loads each skill's metadata at startup (~100 tokens each)
and pulls in the full SKILL.md body on demand when the current phase
matches the skill's description — progressive disclosure.

Default --dry-run. Real upload requires BOTH:
  1) --commit
  2) PRISM_SKILLS_COMMIT=1

Missing either: refuse, exit 1.

Side effects on commit:
  - POST /v1/skills (5×)  — uploads the 5 SKILL.md files; each returns
    a skill_id (`skill_01...`). Cost: free.
  - beta.agents.update(agent_id=<coordinator>, version=<n>,
      skills=[{"type":"custom","skill_id":...}, ...])  — binds all 5
    to the coordinator. Cost: free.
  - Writes skills/manifest.yaml with role → skill_id mapping.

Beta headers:
  - Upload path auto-attaches `skills-2025-10-02` (SDK-native).
  - Agent-update path attaches `managed-agents-2026-04-01`.

Idempotency: re-running is NOT idempotent — a second run creates new
skill_ids. If skills/manifest.yaml exists, the script refuses unless
--replace is passed; --replace archives existing skills first then
re-uploads.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"
AGENTS_MANIFEST = REPO / "agents" / "manifest.yaml"
SKILLS_MANIFEST = SKILLS_DIR / "manifest.yaml"
MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"
SKILLS_BETA = "skills-2025-10-02"

# Role skills (audit-phase triggered: one per phase of the 5-agent dialectic + planner)
# followed by clinical-domain skills (rail-triggered: only load on case.rail == "clinical").
# The idempotent-extend path in do_commit() will adopt existing skill_ids from
# skills/manifest.yaml and upload only the missing roles, so appending to this
# tuple is backward-compatible with a previous --commit run.
ROLES = (
    # Phase-triggered role skills (always bound; body loads by phase match)
    "defender",
    "attacker",
    "synthesizer",
    "executor",
    "adjudicator",
    "planner",
    # R4 clinical-domain skills (docs/sota-portfolio.md §R4):
    # rail-triggered; progressive disclosure means GPU-rail runs never load
    # these bodies. Graded as paired axis deltas on HealthBench Hard.
    "clinical-review",         # communication axis
    "differential-diagnosis",  # completeness axis
    "dosage-check",            # accuracy axis
)


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
        + "Z"
    )


def _load_agents_manifest() -> dict:
    if not AGENTS_MANIFEST.exists():
        raise RuntimeError(
            f"{AGENTS_MANIFEST.relative_to(REPO)} missing — run "
            "`PRISM_AGENTS_COMMIT=1 python scripts/register_agents.py --commit` first."
        )
    data = yaml.safe_load(AGENTS_MANIFEST.read_text()) or {}
    coord = (data.get("agents") or {}).get("coordinator") or {}
    if not coord.get("id"):
        raise RuntimeError("agents/manifest.yaml: coordinator.id missing")
    return coord


def _skill_files() -> list[tuple[str, Path]]:
    """Return list of (role, path_to_SKILL_md) for every role in ROLES."""
    out: list[tuple[str, Path]] = []
    for role in ROLES:
        p = SKILLS_DIR / f"prism-{role}" / "SKILL.md"
        if not p.exists():
            raise RuntimeError(f"missing: {p.relative_to(REPO)}")
        out.append((role, p))
    return out


def do_dry_run(args: argparse.Namespace) -> int:
    print("(dry-run) scripts/register_skills.py plan:")
    try:
        coord = _load_agents_manifest()
        print(f"  coordinator id  : {coord['id']} v{coord['version']}")
    except RuntimeError as e:
        print(f"  coordinator     : UNAVAILABLE ({e})")
    existing_roles: set[str] = set()
    if SKILLS_MANIFEST.exists() and not args.replace:
        old = yaml.safe_load(SKILLS_MANIFEST.read_text()) or {}
        existing_roles = set((old.get("skills") or {}).keys())
    missing_roles: list[str] = []
    try:
        pairs = _skill_files()
        for role, p in pairs:
            size = p.stat().st_size
            state = "adopt" if role in existing_roles else "UPLOAD"
            print(f"  skill           : prism-{role:24s}  [{state}]  ({p.relative_to(REPO)}, {size} B)")
            if role not in existing_roles:
                missing_roles.append(role)
    except RuntimeError as e:
        print(f"  skills          : {e}")
    print(f"  manifest out    : {SKILLS_MANIFEST.relative_to(REPO)}")
    total = len(ROLES)
    to_upload = len(missing_roles) if not args.replace else total
    if args.replace:
        print(
            f"  would POST      : /v1/skills × {to_upload}  (--replace: archive {len(existing_roles)} old, upload all {total})"
        )
    else:
        print(
            f"  would POST      : /v1/skills × {to_upload}  (idempotent extend: adopt {len(existing_roles)}, upload {to_upload})  "
            f"+ beta.agents.update (bind {total} skills)"
        )
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def do_commit(args: argparse.Namespace) -> int:
    from anthropic import Anthropic  # noqa: PLC0415  lazy; AST-verified

    # Idempotent extend: if manifest exists without --replace, adopt
    # existing skill_ids and upload only missing roles. --replace
    # archives everything and starts fresh.

    coord = _load_agents_manifest()
    pairs = _skill_files()

    c = Anthropic()
    manifest: dict = {
        "_generated_by": "scripts/register_skills.py --commit",
        "_registered_at": _now_iso(),
        "coordinator_id": coord["id"],
        "skills": {},
    }

    # Idempotent adoption: start from existing skills/manifest.yaml if it
    # exists. Any role already mapped to a skill_id is adopted as-is.
    # This lets register_skills.py --commit --extend add missing roles
    # (e.g. the new `planner`) without duplicating display_titles.
    existing: dict = {}
    if SKILLS_MANIFEST.exists() and not args.replace:
        old = yaml.safe_load(SKILLS_MANIFEST.read_text()) or {}
        existing = old.get("skills") or {}
        for role, entry in existing.items():
            manifest["skills"][role] = entry
            print(f"  adopted existing: role={role:12s} id={entry['id']}")

    # Optional archive of previous skills on --replace.
    if args.replace and SKILLS_MANIFEST.exists():
        old = yaml.safe_load(SKILLS_MANIFEST.read_text()) or {}
        for role, entry in (old.get("skills") or {}).items():
            sid = (entry or {}).get("id")
            if not sid:
                continue
            try:
                # versions-first delete (per register_skills.py lesson 3)
                for v in c.beta.skills.versions.list(sid):
                    vnum = str(getattr(v, "version", ""))
                    if vnum:
                        try:
                            c.beta.skills.versions.delete(version=vnum, skill_id=sid)
                        except Exception:
                            pass
                c.beta.skills.delete(sid)
                print(f"  archived old skill: role={role} id={sid}")
            except Exception as e:
                print(f"  WARN: could not archive {sid}: {e}")

    # Upload fresh. API requires SKILL.md at the root of a named top-level
    # folder; we pass the filename as `prism-<role>/SKILL.md` per the
    # 400 error we hit the first time ("SKILL.md file must be exactly in
    # the top-level folder.").
    for role, path in pairs:
        if role in manifest["skills"] and not args.replace:
            # Adopted from existing manifest; skip upload.
            continue
        with path.open("rb") as fh:
            created = c.beta.skills.create(
                display_title=f"Prism {role}",
                files=[(f"prism-{role}/SKILL.md", fh.read(), "text/markdown")],
            )
        sid = getattr(created, "id", None) or getattr(created, "skill_id", None)
        if not sid:
            print(f"  ERR: role={role} — no skill_id on response: {created!r}")
            return 2
        manifest["skills"][role] = {"id": sid, "display_title": f"Prism {role}"}
        print(f"  uploaded skill: role={role:12s} id={sid}")

    # Bind all 5 to the coordinator via agent.update.
    skills_binding = [
        {"type": "custom", "skill_id": entry["id"]}
        for role, entry in manifest["skills"].items()
    ]
    updated = c.beta.agents.update(
        agent_id=coord["id"],
        version=int(coord["version"]),
        skills=skills_binding,
        extra_headers={"anthropic-beta": MANAGED_AGENTS_BETA},
    )
    new_version = getattr(updated, "version", None)
    manifest["coordinator_new_version"] = new_version
    print(
        f"  bound {len(skills_binding)} skills to coordinator "
        f"{coord['id']} — new version={new_version}"
    )

    SKILLS_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    SKILLS_MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=False))
    print(f"  wrote: {SKILLS_MANIFEST.relative_to(REPO)}")

    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run live. Requires PRISM_SKILLS_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--replace",
        action="store_true",
        help="If skills/manifest.yaml exists, archive old skills first then re-upload.",
    )
    args = ap.parse_args(argv)

    if args.commit and os.environ.get("PRISM_SKILLS_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_SKILLS_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args)
    return do_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
