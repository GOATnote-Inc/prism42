#!/usr/bin/env python3
"""Run a Prism audit using the 5 bound Skills for role decomposition.

Prerequisites:
  - agents/manifest.yaml (written by register_agents.py --commit)
  - skills/manifest.yaml (written by register_skills.py --commit) —
    5 skills bound to the coordinator via beta.agents.update.

The coordinator agent v2 has all 5 Prism role skills attached.
Opus 4.7 reads each skill's YAML frontmatter (name + description) at
session startup (~100 tokens per skill) and auto-loads the full
SKILL.md body on demand when the current phase matches the skill's
trigger description — progressive disclosure per Anthropic's Agent
Skills design.

The user message we send is MINIMAL — just the case JSON plus a
two-line directive ("run the 5-phase audit in order; rely on your
bound skills"). This is fundamentally different from run_solo_audit.py
which stuffs the entire phase spec into the user message: here the
role specs live in versioned, reusable Skills uploaded to the
Anthropic Skills API, not in an ephemeral prompt.

Default --dry-run. Real requires BOTH:
  1) --commit
  2) PRISM_SKILLED_AUDIT_COMMIT=1
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
AGENTS_MANIFEST = REPO / "agents" / "manifest.yaml"
SKILLS_MANIFEST = REPO / "skills" / "manifest.yaml"
OUT_ROOT = REPO / "results" / "audits"
BETA = "managed-agents-2026-04-01"

DEFAULT_CASE = {
    "target_domain": "clinical",
    "case_id": "HBH-CLN-SKILLED",
    "target_path": "(skilled-audit smoke) synthetic fever-infant case",
    "rail_hint": "clinical",
}

MINIMAL_DIRECTIVE = """\
Run a five-phase Prism audit for the case JSON below.

You have FIVE skills bound to you: prism-defender, prism-attacker,
prism-synthesizer, prism-executor, prism-adjudicator. Each skill's
description tells you when to load it; trust the descriptions. Invoke
each skill in order: defender -> attacker -> synthesizer -> executor
-> adjudicator. Do NOT attempt to call a callable_agent; sub-agent
tools are not available on this runtime. Use your built-in file
tools (write/read/glob) inside /workspace/<case_id>/.

Do not produce any output beyond what each skill's hard rules specify.
End with a one-line summary of the final verdict.json's `verdict`
field, prefixed with "SKILLED AUDIT COMPLETE:".

Case JSON:
"""


def _now_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _load_manifests() -> dict:
    if not AGENTS_MANIFEST.exists():
        raise RuntimeError("agents/manifest.yaml missing")
    if not SKILLS_MANIFEST.exists():
        raise RuntimeError(
            "skills/manifest.yaml missing — run register_skills.py --commit first."
        )
    agents = yaml.safe_load(AGENTS_MANIFEST.read_text()) or {}
    skills = yaml.safe_load(SKILLS_MANIFEST.read_text()) or {}
    env_id = agents.get("environment_id")
    coord = (agents.get("agents") or {}).get("coordinator") or {}
    if not env_id or not coord.get("id"):
        raise RuntimeError("agents/manifest.yaml shape invalid")
    return {
        "environment_id": env_id,
        "coordinator_id": coord["id"],
        "coordinator_version": coord["version"],
        "skills": skills.get("skills") or {},
    }


def do_dry_run(args: argparse.Namespace) -> int:
    case = json.loads(args.case_json) if args.case_json else DEFAULT_CASE
    print("(dry-run) scripts/run_skilled_audit.py plan:")
    try:
        m = _load_manifests()
        print(f"  coordinator      : {m['coordinator_id']} v{m['coordinator_version']}")
        print(f"  environment      : {m['environment_id']}")
        for role, entry in m["skills"].items():
            print(f"  skill bound      : {role:12s}  {entry['id']}")
    except RuntimeError as e:
        print(f"  manifest issue   : {e}")
    print(f"  case_id          : {case.get('case_id')}")
    print(f"  stream-cap-sec   : {args.stream_cap_sec}")
    print(f"  prompt size      : {len(MINIMAL_DIRECTIVE) + len(json.dumps(case)):d} chars "
          f"(vs ~3,463 for solo mode)")
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def do_commit(args: argparse.Namespace) -> int:
    from anthropic import Anthropic  # noqa: PLC0415

    m = _load_manifests()
    case = json.loads(args.case_json) if args.case_json else DEFAULT_CASE
    stamp = _now_stamp()

    c = Anthropic()
    t0 = time.time()
    lines: list[str] = []

    def _log(s: str) -> None:
        line = s.rstrip()
        lines.append(line)
        print(line)

    _log(f"== prism skilled audit — live ==")
    _log(f"case_id={case['case_id']}  bound skills: {list(m['skills'].keys())}")

    session = c.beta.sessions.create(
        agent={"type": "agent", "id": m["coordinator_id"], "version": m["coordinator_version"]},
        environment_id=m["environment_id"],
        title=f"prism-skilled-audit-{case['case_id']}-{stamp}",
        extra_headers={"anthropic-beta": BETA},
    )
    sid = session.id
    _log(f"[{time.time()-t0:6.1f}s] session.create -> id={sid}")

    prompt = MINIMAL_DIRECTIVE + json.dumps(case, indent=2)
    c.beta.sessions.events.send(
        session_id=sid,
        events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
        extra_headers={"anthropic-beta": BETA},
    )
    _log(f"[{time.time()-t0:6.1f}s] events.send -> user.message ({len(prompt)} chars)")

    deadline = t0 + float(args.stream_cap_sec)
    event_types: dict[str, int] = {}
    collected: list[dict] = []
    assistant_text: list[str] = []
    skill_loads = 0
    final_marker = False

    try:
        with c.beta.sessions.events.stream(
            session_id=sid, extra_headers={"anthropic-beta": BETA}
        ) as stream:
            for ev in stream:
                now = time.time()
                etype = getattr(ev, "type", None) or type(ev).__name__
                event_types[etype] = event_types.get(etype, 0) + 1
                collected.append({"t": round(now - t0, 2), "type": etype})

                content = getattr(ev, "content", None) or []
                for block in content:
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        txt = getattr(block, "text", "") or ""
                        assistant_text.append(txt)
                        if "SKILLED AUDIT COMPLETE:" in txt:
                            final_marker = True
                    elif btype == "tool_use":
                        tname = (getattr(block, "name", "") or "").lower()
                        # Heuristic: a "read" on a path containing "skill"
                        # is a skill-body load. The tool name itself may
                        # not be "skill".
                        tin = getattr(block, "input", None) or {}
                        path = str((tin or {}).get("file_path") or (tin or {}).get("path") or "")
                        if "SKILL.md" in path or "skill" in path.lower():
                            skill_loads += 1

                _log(f"[{now-t0:6.1f}s] event: {etype}")

                if etype in ("turn.ended", "session.ended", "error"):
                    break
                if etype == "session.status_idle" and final_marker:
                    _log(f"[{now-t0:6.1f}s] SKILLED AUDIT COMPLETE + idle; closing")
                    break
                if now > deadline:
                    _log(f"[{now-t0:6.1f}s] STOP ({args.stream_cap_sec}s cap)")
                    break
    except Exception as e:
        _log(f"STREAM ERROR: {type(e).__name__}: {str(e)[:300]}")

    _log("---")
    _log(f"event types: {event_types}")
    _log(f"total events: {len(collected)}")
    _log(f"skill-file reads (heuristic): {skill_loads}")
    joined = "".join(assistant_text)
    if joined:
        _log(f"--- assistant text ({len(joined)} chars) ---")
        _log(joined[:4000])
        _log("---")

    final = c.beta.sessions.retrieve(session_id=sid, extra_headers={"anthropic-beta": BETA})
    usage = getattr(final, "usage", None)
    _log(f"final status: {getattr(final, 'status', None)}")
    if usage:
        _log(f"usage: {usage}")
    console_url = f"https://platform.claude.com/sessions/{sid}"
    _log(f"session URL: {console_url}")

    audit_dir = OUT_ROOT / sid
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "transcript.log").write_text("\n".join(lines) + "\n")

    def _u(u):
        if u is None:
            return {}
        return {
            "input_tokens": getattr(u, "input_tokens", None),
            "output_tokens": getattr(u, "output_tokens", None),
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None),
        }

    summary = {
        "session_id": sid,
        "coordinator_id": m["coordinator_id"],
        "coordinator_version": m["coordinator_version"],
        "bound_skills": m["skills"],
        "case": case,
        "final_status": getattr(final, "status", None),
        "event_types": event_types,
        "n_events": len(collected),
        "skill_file_reads_heuristic": skill_loads,
        "skilled_audit_complete_marker": final_marker,
        "wall_time_sec": round(time.time() - t0, 2),
        "usage": _u(usage),
        "console_url": console_url,
        "generated_at": _now_stamp(),
    }
    (audit_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")

    print(f"\n(commit) transcript: {audit_dir / 'transcript.log'}")
    print(f"(commit) summary   : {audit_dir / 'summary.json'}")
    if final_marker:
        print("(commit) RESULT: skilled audit completed with final-line marker.")
    else:
        print("(commit) RESULT: no final-line marker within cap.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--case-json", default=None)
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run live. Requires PRISM_SKILLED_AUDIT_COMMIT=1 in env.",
    )
    ap.add_argument("--stream-cap-sec", type=int, default=600)
    ap.add_argument("--budget-cap-usd", type=float, default=1.0)
    args = ap.parse_args(argv)

    if args.commit and os.environ.get("PRISM_SKILLED_AUDIT_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_SKILLED_AUDIT_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args)
    return do_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
