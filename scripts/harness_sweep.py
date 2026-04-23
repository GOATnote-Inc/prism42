#!/usr/bin/env python3
"""Prism T4.7b — harness sweep on the HealthBench Hard 30-example subset.

Orchestrates N coordinator sessions (one per clinical example in
`corpus/clinical_subset.yaml`), captures each session's final modified
clinical response, grades all responses with openai/simple-evals'
HealthBench rubric via `_real_grader`, and emits an aggregate per-axis
score plus optional paired delta vs a baseline JSON.

Sessions run against the already-registered prism-coordinator agent
(v4 or greater) with all bound skills: the 6 phase-triggered role
skills (defender / attacker / synthesizer / executor / adjudicator /
planner) + the 3 R4 clinical-domain skills (clinical-review /
differential-diagnosis / dosage-check). Progressive disclosure routes
the body loads per-phase; GPU-rail-only skill bodies never load here.

Default behavior is --dry-run: loads the manifests, prints the plan
(coordinator, bound skills, number of sessions, cost envelope, output
paths, grader pinning), writes a skeletal JSON marked `dry_run: true`.
No network, no SDK import.

Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_HARNESS_SWEEP_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic SDK is
only imported inside `do_commit()`; dry-run never touches it.
`scripts/check_sdk_containment.py` enforces this containment via AST.

Cost envelope (advisory, per 30-example sweep):
  - 30 coordinator sessions × ~$2-3/session (5-phase dialectic) ≈ $60-$90
  - Grading: ~30 examples × ~N rubric items × Opus 4.7 judge ≈ $30-$40
  - Total ≈ $100-$130 plus ~$0.08 × session-hours
  - --budget-cap-usd is a hard stop (default $120); examples beyond the
    cap are skipped and the halted_reason is recorded in the output.
  - --n-limit lets you pilot with 3-10 examples first (~$10-$45) before
    committing the full sweep budget. Honor it as a per-session ceiling.

Output layout (under --out-root):
  results/harness-sweep-<stamp>/
    aggregate.json         — overall + per-axis score, delta vs baseline if given
    per_example.json       — per-example {score, per_axis, harness_text_len}
    transcripts/<id>.log   — per-session event stream
    modified/<id>.md       — extracted harness-modified clinical response text
    judge-log.jsonl        — physician-reviewable audit log for every judge call

Paired-delta gate (when --baseline is supplied):
  For every example present in both this sweep and the baseline, compute
  d_i = harness_score_i - baseline_score_i. Report mean Δ ± 95% CI
  (Student's t, df=N-1). The R4 per-skill ship-gate is axis-specific:
  clinical-review → communication; differential-diagnosis → completeness;
  dosage-check → accuracy. Each axis delta must be >= 0.05 AND its 95%
  CI must exclude 0 for the skill to ship (docs/sota-portfolio.md §R4).
  This script reports the numbers; shipping decisions are reviewer calls.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import yaml

REPO = Path(__file__).resolve().parent.parent
AGENTS_MANIFEST = REPO / "agents" / "manifest.yaml"
SKILLS_MANIFEST = REPO / "skills" / "manifest.yaml"
DEFAULT_SUBSET = REPO / "corpus" / "clinical_subset.yaml"
DEFAULT_OUT_ROOT = REPO / "results"
BETA = "managed-agents-2026-04-01"

# Re-use healthbench_runner's grader + aggregator. These are pure
# functions; SDK containment is not violated because healthbench_runner
# imports anthropic inside its own do_commit, not at module scope.
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from healthbench_runner import (  # noqa: E402
    HEALTHBENCH_AXES,
    MODEL_ID,
    RubricItem,
    _aggregate,
    _make_anthropic_judge,
    _preflight_judge_key,
    _real_grader,
    _stub_grader,
)

# Per-example directive. The coordinator runs the 5-phase audit, writes
# modified.md on disk, then re-emits modified.md's contents between two
# unique line-anchored sentinels so the harness can pull the text out
# deterministically.
#
# Safety-engineer note (2026-04-23): an earlier version of this prompt
# showed a ```markdown fenced block with a literal placeholder
# ("<modified.md contents — no preface, no editor comments>"). The
# first live pilot demonstrated a silent failure mode — the coordinator
# copied the literal placeholder verbatim into its final turn, and the
# regex matched that echo instead of any real content. Every judge
# score came back 0 against meaningless placeholder text while the
# pipeline looked "clean". The fix is: (1) do NOT show an example
# template of the output format in the prompt (models will copy-paste
# it); (2) describe the format in natural language; (3) use unique
# sentinels flanked by double underscores so the token is unlikely to
# appear in ordinary dialectic prose; (4) require the sentinels alone
# on their own lines (line-anchored matching); (5) when parsing, take
# the LAST begin sentinel + FIRST end sentinel after it, so a quoted
# mention of the sentinel in an earlier phase does not shadow the real
# emission. All four guards together make the extraction robust to the
# model describing the protocol vs executing the protocol.
HARNESS_BEGIN_SENTINEL = "__HARNESS_MODIFIED_BEGIN__"
HARNESS_END_SENTINEL = "__HARNESS_MODIFIED_END__"

HARNESS_DIRECTIVE = f"""\
You are running a Prism clinical-rail audit against a HealthBench Hard
example. The conversation so far is in the case JSON below; the LAST
user turn is the one you must respond to.

Execute the 5-phase skilled audit using your bound skills
(prism-defender, prism-attacker, prism-synthesizer, prism-executor,
prism-adjudicator, prism-planner), layered with the clinical-domain
skills (prism-clinical-review, prism-differential-diagnosis,
prism-dosage-check) whose descriptions trigger for this case. The
synthesizer phase writes /workspace/<case_id>/modified.md carrying
your final harness-modified clinical response — the text a clinician
reader would see.

After the adjudicator verdict is written, emit the contents of
modified.md between two sentinel lines so the harness can extract
them deterministically. The protocol is:

  1. Emit a line containing ONLY the token {HARNESS_BEGIN_SENTINEL}
     (no surrounding text on that line, no markdown fence, no quotes).
  2. Emit the complete contents of /workspace/<case_id>/modified.md
     verbatim — the raw text, WITHOUT wrapping in code fences, quotes,
     or any preface.
  3. Emit a line containing ONLY the token {HARNESS_END_SENTINEL}
     (same constraints as step 1).
  4. Emit the single line: HARNESS COMPLETE: <case_id>

Do not produce any other text after the HARNESS COMPLETE line. Do not
repeat or describe the sentinel tokens inside the body — they must
appear exactly once each, each on its own line, around the content.
Do not call any sub-agent tool; callable_agents delegation is not
available on this runtime — use bash/read/write/glob only.

Case JSON:
"""

# Line-anchored sentinel matchers. Using MULTILINE + end-of-line anchor
# means a sentinel embedded mid-sentence (e.g. "I will emit
# __HARNESS_MODIFIED_BEGIN__ next...") does not match — only a line
# whose sole content is the sentinel matches.
_BEGIN_RE = re.compile(rf"^{re.escape(HARNESS_BEGIN_SENTINEL)}\s*$", re.MULTILINE)
_END_RE = re.compile(rf"^{re.escape(HARNESS_END_SENTINEL)}\s*$", re.MULTILINE)

# t critical values at α=0.05 (two-sided), df = n-1. Used for paired CI
# when scipy isn't available. Covers pilot and full-sweep Ns.
_T_CRIT_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    14: 2.145, 19: 2.093, 24: 2.064, 29: 2.045, 39: 2.023,
    49: 2.010, 99: 1.984,
}


def _t_crit(df: int) -> float:
    """Return t_{0.975, df} by table lookup with fallback to 1.96 for df>=100."""
    if df <= 0:
        return math.nan
    if df >= 100:
        return 1.96
    # Nearest-lower key (conservative — widens the CI slightly).
    keys = sorted(k for k in _T_CRIT_975 if k <= df)
    if keys:
        return _T_CRIT_975[keys[-1]]
    return _T_CRIT_975[1]


def _now_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
        + "Z"
    )


def _load_manifests() -> dict:
    if not AGENTS_MANIFEST.exists():
        raise RuntimeError(f"{AGENTS_MANIFEST.relative_to(REPO)} missing — run register_agents.py --commit first")
    if not SKILLS_MANIFEST.exists():
        raise RuntimeError(f"{SKILLS_MANIFEST.relative_to(REPO)} missing — run register_skills.py --commit first")
    agents = yaml.safe_load(AGENTS_MANIFEST.read_text()) or {}
    skills = yaml.safe_load(SKILLS_MANIFEST.read_text()) or {}
    coord = (agents.get("agents") or {}).get("coordinator") or {}
    if not agents.get("environment_id") or not coord.get("id"):
        raise RuntimeError("agents/manifest.yaml shape invalid")
    return {
        "environment_id": agents["environment_id"],
        "coordinator_id": coord["id"],
        "coordinator_version": coord["version"],
        "skills": skills.get("skills") or {},
    }


def _load_subset(path: Path, n_limit: int | None) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    examples = data.get("examples") or []
    if not isinstance(examples, list):
        raise ValueError(f"{path}: manifest.examples must be a list")
    if n_limit is not None and n_limit > 0:
        examples = examples[:n_limit]
    return examples


def _extract_modified(assistant_text: str) -> str | None:
    """Pull the modified.md content out of the coordinator's final turn.

    Extracts the body between __HARNESS_MODIFIED_BEGIN__ and
    __HARNESS_MODIFIED_END__ sentinels. The sentinels must each appear
    alone on their own line (line-anchored match); a mention inside a
    sentence does NOT count.

    Robustness strategy: use the LAST begin-sentinel and the FIRST
    end-sentinel after it. If the model quotes the sentinel in an
    earlier dialectic phase ("I will emit __HARNESS_MODIFIED_BEGIN__
    next"), that quoted mention is mid-sentence and will not match the
    line-anchored regex. But if the model reflows a quoted instance
    onto its own line for some reason, the last-begin rule still lands
    on the real emission — the final one is always the executed one.

    Returns None if sentinels are missing or malformed; the example is
    recused rather than scored against a truncated / malformed response.
    """
    begin_matches = list(_BEGIN_RE.finditer(assistant_text))
    if not begin_matches:
        return None
    last_begin = begin_matches[-1]
    after = assistant_text[last_begin.end():]
    end_match = _END_RE.search(after)
    if end_match is None:
        return None
    body = after[:end_match.start()]
    return body.strip()


def _build_prompt(example: dict) -> str:
    """Embed the full HealthBench conversation inside the harness directive."""
    case_payload = {
        "case_id": example.get("id", "HBH-CLN-UNKNOWN"),
        "target_domain": "clinical",
        "target_axis": example.get("target_axis", "unspecified"),
        "class": example.get("class", "general"),
        "messages": example.get("messages") or [],
        "healthbench_hard_example_id": example.get("healthbench_hard_example_id"),
    }
    return HARNESS_DIRECTIVE + json.dumps(case_payload, indent=2)


def _cost_est_per_session() -> float:
    """Advisory per-session cost for budgeting in dry-run."""
    return 2.50  # ~$60-90 / 30 sessions midpoint; rough


def do_dry_run(args: argparse.Namespace, run_id: str, stamp: str) -> int:
    subset_path = Path(args.manifest).resolve()
    out_root = Path(args.out_root).resolve()
    out_dir = out_root / f"harness-sweep-{stamp}"

    print("(dry-run) scripts/harness_sweep.py plan:")
    try:
        m = _load_manifests()
        print(f"  coordinator       : {m['coordinator_id']} v{m['coordinator_version']}")
        print(f"  environment       : {m['environment_id']}")
        print(f"  bound skills      : {len(m['skills'])} ({', '.join(sorted(m['skills'].keys()))})")
    except RuntimeError as e:
        print(f"  manifests         : NOT USABLE ({e})")

    try:
        examples = _load_subset(subset_path, args.n_limit)
        planned = len(examples)
    except (FileNotFoundError, ValueError) as e:
        print(f"  subset            : NOT USABLE ({e})")
        planned = 0
        examples = []

    print(f"  subset            : {subset_path}")
    print(f"  n examples        : {planned}  (--n-limit={args.n_limit or 'full'})")
    print(f"  run_id            : {run_id}")
    print(f"  out dir           : {out_dir.relative_to(REPO) if out_dir.is_relative_to(REPO) else out_dir}")
    print(f"  stream-cap-sec    : {args.stream_cap_sec}  (per session)")
    print(f"  budget-cap-usd    : ${args.budget_cap_usd:.2f}  (hard stop)")
    est = planned * _cost_est_per_session()
    print(f"  cost envelope     : ~${est:.2f}-${est * 1.4:.2f} for {planned} sessions (incl. grading)")
    print(f"  baseline          : {args.baseline or '(none — aggregate only, no paired delta)'}")
    print(f"  grader            : simple-evals@ee3b0318 via bridge (judge={args.judge_model})")

    skeletal = {
        "dry_run": True,
        "run_id": run_id,
        "generated_at": _now_iso(),
        "subset_manifest": str(subset_path),
        "n_planned": planned,
        "n_limit": args.n_limit,
        "budget_cap_usd": args.budget_cap_usd,
        "stream_cap_sec": args.stream_cap_sec,
        "judge_model": args.judge_model,
        "baseline_artifact": args.baseline,
        "per_example": [],
        "aggregate": _aggregate([]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aggregate.json").write_text(json.dumps(skeletal, indent=2, sort_keys=True) + "\n")
    print(f"(dry-run) wrote skeletal aggregate to: {out_dir / 'aggregate.json'}")
    print("(dry-run) no network activity; no anthropic SDK import")
    return 0


def _run_one_session(
    client: Any,
    m: dict,
    example: dict,
    stream_cap_sec: int,
    stamp: str,
    out_dir: Path,
) -> dict:
    """Drive one coordinator session for one HealthBench example.

    Returns a dict with:
      - session_id, case_id
      - modified_response (str | None) — extracted harness text
      - transcript_path — where the per-session events were logged
      - wall_time_sec
      - console_url
    """
    case_id = example.get("id", f"EX-{uuid.uuid4().hex[:8]}")
    transcripts_dir = out_dir / "transcripts"
    modified_dir = out_dir / "modified"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    modified_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    log_lines: list[str] = []

    def _log(s: str) -> None:
        line = s.rstrip()
        log_lines.append(line)
        print(line)

    _log(f"== harness-sweep example {case_id} ==")

    session = client.beta.sessions.create(
        agent={"type": "agent", "id": m["coordinator_id"], "version": m["coordinator_version"]},
        environment_id=m["environment_id"],
        title=f"prism-harness-sweep-{case_id}-{stamp}",
        extra_headers={"anthropic-beta": BETA},
    )
    sid = session.id
    _log(f"[{time.time()-t0:6.1f}s] session.create -> id={sid}")

    prompt = _build_prompt(example)
    client.beta.sessions.events.send(
        session_id=sid,
        events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
        extra_headers={"anthropic-beta": BETA},
    )
    _log(f"[{time.time()-t0:6.1f}s] events.send ({len(prompt)} chars)")

    deadline = t0 + float(stream_cap_sec)
    stream_assistant_text: list[str] = []
    event_types: dict[str, int] = {}
    stream_error: str | None = None

    # Phase A — stream events live. The stream is a convenience for
    # progress logging and early-idle termination. It is NOT the source
    # of truth; a dropped stream (RemoteProtocolError mid-session) must
    # not lose the session's output because Managed Agents sessions are
    # durable server-side and the event log is re-readable via
    # events.list. See anthropic.com/engineering/managed-agents:
    # "harnesses are stateless; crashed ones resume via getEvents()".
    try:
        with client.beta.sessions.events.stream(
            session_id=sid, extra_headers={"anthropic-beta": BETA}
        ) as stream:
            for ev in stream:
                now = time.time()
                etype = getattr(ev, "type", None) or type(ev).__name__
                event_types[etype] = event_types.get(etype, 0) + 1
                for block in (getattr(ev, "content", None) or []):
                    if getattr(block, "type", None) == "text":
                        stream_assistant_text.append(getattr(block, "text", "") or "")
                _log(f"[{now-t0:6.1f}s] event: {etype}")
                if etype in ("turn.ended", "session.ended", "error"):
                    break
                # Early-close on idle ONLY if the line-anchored terminal
                # marker appears in what we've streamed so far. The old
                # substring check ("HARNESS COMPLETE:" in txt) fired on
                # prose mentions of the marker in earlier dialectic
                # phases (false positive), so we tighten to a line-
                # anchored match.
                if etype == "session.status_idle":
                    joined_so_far = "".join(stream_assistant_text)
                    if re.search(rf"^HARNESS COMPLETE: {re.escape(case_id)}\s*$",
                                 joined_so_far, re.MULTILINE):
                        _log(f"[{now-t0:6.1f}s] HARNESS COMPLETE + idle; closing stream")
                        break
                if now > deadline:
                    _log(f"[{now-t0:6.1f}s] STOP (stream-cap {stream_cap_sec}s)")
                    break
    except Exception as e:  # noqa: BLE001
        stream_error = f"{type(e).__name__}: {str(e)[:300]}"
        _log(f"STREAM ERROR: {stream_error} (will fall back to events.list)")

    # Phase B — wait for Anthropic's session to settle, then pull the
    # canonical event log via events.list. This runs regardless of how
    # phase A ended (clean close, idle-early-close, stream error, or
    # deadline hit). It is the safety net: even if the TCP stream died
    # at 305s while the model was mid-emission, the session continues
    # on Anthropic's side and events.list returns the complete history
    # including the sentinel-bracketed modified response.
    settle_deadline = time.time() + 180  # 3 min max wait for session to reach a terminal state
    final = None
    while time.time() < settle_deadline:
        try:
            final = client.beta.sessions.retrieve(
                session_id=sid, extra_headers={"anthropic-beta": BETA}
            )
            status = getattr(final, "status", None)
            if status in ("idle", "terminated", "completed"):
                _log(f"session settled: status={status}")
                break
        except Exception as e:  # noqa: BLE001
            _log(f"retrieve poll error: {type(e).__name__}: {str(e)[:200]}")
        time.sleep(5)

    canonical_text: list[str] = []
    events_list_error: str | None = None
    try:
        # Paginate through events in ascending order so reconstruction
        # matches emission order. The SDK's SyncPageCursor handles the
        # page token automatically when iterated.
        for ev in client.beta.sessions.events.list(
            session_id=sid, order="asc", limit=200,
            extra_headers={"anthropic-beta": BETA},
        ):
            for block in (getattr(ev, "content", None) or []):
                if getattr(block, "type", None) == "text":
                    canonical_text.append(getattr(block, "text", "") or "")
    except Exception as e:  # noqa: BLE001
        events_list_error = f"{type(e).__name__}: {str(e)[:200]}"
        _log(f"events.list error: {events_list_error}")

    # Prefer the canonical event log if we got one; else fall back to
    # the live-stream text. Either way, extract against the joined text.
    joined = "".join(canonical_text) if canonical_text else "".join(stream_assistant_text)
    # Line-anchored terminal marker — no more false-positive on prose
    # mentions of the marker.
    final_marker = bool(
        re.search(rf"^HARNESS COMPLETE: {re.escape(case_id)}\s*$", joined, re.MULTILINE)
    )

    console_url = f"https://platform.claude.com/sessions/{sid}"
    _log(f"session URL: {console_url}")
    _log(
        f"assistant text sources: stream={len(''.join(stream_assistant_text))} chars, "
        f"events.list={len(''.join(canonical_text))} chars"
    )

    modified = _extract_modified(joined)
    if modified is None:
        _log(f"WARN: sentinel block not extracted for {case_id} — recuse")
    else:
        _log(f"extracted modified response: {len(modified)} chars")
        (modified_dir / f"{case_id}.md").write_text(modified + "\n")

    transcript_path = transcripts_dir / f"{case_id}.log"
    transcript_path.write_text("\n".join(log_lines) + "\n")

    usage = getattr(final, "usage", None) if final is not None else None
    in_toks = getattr(usage, "input_tokens", 0) if usage else 0
    out_toks = getattr(usage, "output_tokens", 0) if usage else 0
    # Placeholder pricing: $5/Mtok in, $25/Mtok out for Opus 4.7.
    session_cost = (in_toks / 1_000_000) * 5.0 + (out_toks / 1_000_000) * 25.0

    return {
        "case_id": case_id,
        "session_id": sid,
        "console_url": console_url,
        "modified_response": modified,
        "transcript_path": str(transcript_path.relative_to(REPO)),
        "event_types": event_types,
        "final_status": getattr(final, "status", None) if final is not None else None,
        "harness_text_len": len(joined),
        "modified_len": len(modified) if modified is not None else 0,
        "wall_time_sec": round(time.time() - t0, 2),
        "input_tokens": in_toks,
        "output_tokens": out_toks,
        "session_cost_usd": round(session_cost, 4),
        "final_marker": final_marker,
        "stream_error": stream_error,
        "events_list_error": events_list_error,
        "used_events_list_fallback": bool(canonical_text) and stream_error is not None,
    }


def _paired_delta(
    sweep_per_example: list[dict], baseline_path: Path
) -> dict | None:
    """Compute paired mean Δ + 95% CI on examples present in both sides.

    Returns None if the baseline file cannot be parsed or no example pairs
    exist. The caller writes either the delta block or a `null` stub.
    """
    try:
        base = json.loads(baseline_path.read_text())
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        return {"error": f"baseline unreadable: {exc}", "baseline_artifact": str(baseline_path)}
    base_by_id = {e.get("id"): e for e in (base.get("per_example") or [])}

    overall_pairs: list[tuple[float, float]] = []
    axis_pairs: dict[str, list[tuple[float, float]]] = {a: [] for a in HEALTHBENCH_AXES}
    matched_ids: list[str] = []
    missing_in_baseline: list[str] = []

    for row in sweep_per_example:
        cid = row.get("case_id")
        b = base_by_id.get(cid)
        if b is None:
            missing_in_baseline.append(cid)
            continue
        h_score = row.get("score")
        b_score = b.get("score")
        if h_score is None or b_score is None:
            continue
        overall_pairs.append((float(h_score), float(b_score)))
        matched_ids.append(cid)
        for axis in HEALTHBENCH_AXES:
            h_ax = (row.get("per_axis") or {}).get(axis)
            b_ax = (b.get("per_axis") or {}).get(axis)
            if h_ax is None or b_ax is None:
                continue
            axis_pairs[axis].append((float(h_ax), float(b_ax)))

    def _stats(pairs: list[tuple[float, float]]) -> dict:
        n = len(pairs)
        if n == 0:
            return {"n": 0, "mean": None, "ci95_half": None, "excludes_zero": None}
        deltas = [h - b for (h, b) in pairs]
        mean = sum(deltas) / n
        if n == 1:
            return {"n": 1, "mean": mean, "ci95_half": None, "excludes_zero": None}
        variance = sum((d - mean) ** 2 for d in deltas) / (n - 1)
        sd = math.sqrt(variance)
        sem = sd / math.sqrt(n)
        tcrit = _t_crit(n - 1)
        half = tcrit * sem
        excludes_zero = (mean - half > 0) or (mean + half < 0)
        return {
            "n": n,
            "mean": round(mean, 6),
            "sd": round(sd, 6),
            "sem": round(sem, 6),
            "t_crit_975": round(tcrit, 3),
            "ci95_half": round(half, 6),
            "ci95_low": round(mean - half, 6),
            "ci95_high": round(mean + half, 6),
            "excludes_zero": bool(excludes_zero),
        }

    return {
        "baseline_artifact": str(baseline_path),
        "n_matched": len(matched_ids),
        "matched_ids": matched_ids,
        "missing_in_baseline": missing_in_baseline,
        "overall_delta": _stats(overall_pairs),
        "per_axis_delta": {axis: _stats(pairs) for axis, pairs in axis_pairs.items()},
    }


def do_commit(args: argparse.Namespace, run_id: str, stamp: str) -> int:
    """Live sweep. Reached only when both --commit AND env gate pass."""
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    subset_path = Path(args.manifest).resolve()
    out_root = Path(args.out_root).resolve()
    out_dir = out_root / f"harness-sweep-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    m = _load_manifests()
    examples = _load_subset(subset_path, args.n_limit)

    client = Anthropic()
    print(f"(commit) run_id={run_id} stamp={stamp}")
    print(f"(commit) coordinator={m['coordinator_id']} v{m['coordinator_version']}")
    print(f"(commit) bound skills: {len(m['skills'])} ({', '.join(sorted(m['skills'].keys()))})")
    print(f"(commit) sessions planned: {len(examples)}  budget_cap=${args.budget_cap_usd:.2f}")

    # Pre-flight judge key. Halts LOUD on 401/403 before any real spend —
    # per memory rule "ALWAYS pre-flight judge API keys before multi-hour
    # evals".
    _preflight_judge_key(client, args.judge_model)
    print(f"(commit) preflight: judge key OK (model={args.judge_model})")

    audit_log_path = out_dir / "judge-log.jsonl"
    judge_fn: Callable[[str, RubricItem], dict] = _make_anthropic_judge(
        client,
        model_id=args.judge_model,
        audit_log_path=audit_log_path,
    )
    print(f"(commit) judge: {args.judge_model}  audit_log: {audit_log_path.relative_to(REPO)}")

    per_example: list[dict] = []
    total_cost_usd = 0.0
    halted_reason: str | None = None

    for idx, example in enumerate(examples):
        if total_cost_usd >= args.budget_cap_usd:
            halted_reason = (
                f"budget cap hit at example {idx}/{len(examples)} "
                f"(spent=${total_cost_usd:.2f} >= cap=${args.budget_cap_usd:.2f})"
            )
            print(f"(commit) HALT: {halted_reason}")
            break

        print(f"(commit) [{idx + 1}/{len(examples)}] {example.get('id')} "
              f"({example.get('class')}/{example.get('target_axis')})")
        session_summary = _run_one_session(
            client, m, example, args.stream_cap_sec, stamp, out_dir
        )

        modified = session_summary["modified_response"]
        if modified is None:
            grade = {"score": None, "per_axis": {a: None for a in HEALTHBENCH_AXES},
                     "judge_incomplete": 0, "judge_incomplete_fraction": 0.0}
        else:
            grade = _real_grader(modified, example, judge_fn=judge_fn)

        session_summary["score"] = grade["score"]
        session_summary["per_axis"] = grade["per_axis"]
        session_summary["judge_incomplete"] = grade.get("judge_incomplete", 0)
        session_summary["judge_incomplete_fraction"] = grade.get("judge_incomplete_fraction", 0.0)

        # Drop the modified-response text from the JSON-serialized row
        # (it's already on disk at modified/<id>.md). Keep the length.
        session_summary.pop("modified_response", None)

        total_cost_usd += session_summary.get("session_cost_usd", 0.0)
        per_example.append(session_summary)

        score_str = f"{grade['score']:.3f}" if grade.get("score") is not None else "RECUSED"
        print(f"(commit)   -> score={score_str} incomplete={grade.get('judge_incomplete', 0)} "
              f"cum_cost=${total_cost_usd:.2f}")

    aggregate = _aggregate(per_example)
    payload: dict = {
        "dry_run": False,
        "run_id": run_id,
        "stamp": stamp,
        "generated_at": _now_iso(),
        "subset_manifest": str(subset_path),
        "coordinator_id": m["coordinator_id"],
        "coordinator_version": m["coordinator_version"],
        "bound_skills": m["skills"],
        "judge_model": args.judge_model,
        "budget_cap_usd": args.budget_cap_usd,
        "total_cost_usd": round(total_cost_usd, 4),
        "stream_cap_sec": args.stream_cap_sec,
        "halted_reason": halted_reason,
        "aggregate": aggregate,
    }

    if args.baseline:
        payload["paired_delta"] = _paired_delta(per_example, Path(args.baseline).resolve())

    (out_dir / "aggregate.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out_dir / "per_example.json").write_text(json.dumps(per_example, indent=2, sort_keys=True) + "\n")

    print(f"(commit) aggregate -> {out_dir / 'aggregate.json'}")
    print(f"(commit) per-example -> {out_dir / 'per_example.json'}")
    if payload.get("paired_delta"):
        od = payload["paired_delta"].get("overall_delta") or {}
        print(f"(commit) paired Δ (overall): mean={od.get('mean')} 95%CI half={od.get('ci95_half')} "
              f"excludes_zero={od.get('excludes_zero')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--manifest",
        default=str(DEFAULT_SUBSET),
        help=f"Path to clinical subset YAML (default: {DEFAULT_SUBSET.relative_to(REPO)}).",
    )
    ap.add_argument(
        "--out-root",
        default=str(DEFAULT_OUT_ROOT),
        help=f"Root for results/harness-sweep-<stamp>/ (default: {DEFAULT_OUT_ROOT.relative_to(REPO)}).",
    )
    ap.add_argument(
        "--n-limit",
        type=int,
        default=None,
        help="Cap on number of examples; useful for pilots (e.g. --n-limit 3 for a smoke).",
    )
    ap.add_argument(
        "--baseline",
        default=None,
        help="Optional path to a healthbench_runner baseline JSON; enables paired delta.",
    )
    ap.add_argument(
        "--judge-model",
        default=MODEL_ID,
        help=f"Model for rubric-item judging (default {MODEL_ID}).",
    )
    ap.add_argument(
        "--stream-cap-sec",
        type=int,
        default=900,
        help="Per-session hard cap on the event stream (default 900s).",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=120.0,
        help="Hard stop when cumulative cost exceeds this (default $120).",
    )
    ap.add_argument(
        "--run-id",
        default=None,
        help="Optional UUID for this run; generated if absent.",
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run for real. Requires PRISM_HARNESS_SWEEP_COMMIT=1 in env.",
    )
    args = ap.parse_args(argv)

    run_id = args.run_id or str(uuid.uuid4())
    stamp = _now_stamp()

    if args.commit and os.environ.get("PRISM_HARNESS_SWEEP_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_HARNESS_SWEEP_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args, run_id, stamp)
    return do_dry_run(args, run_id, stamp)


if __name__ == "__main__":
    sys.exit(main())
